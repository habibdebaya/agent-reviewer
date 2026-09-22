from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from urllib.parse import urlencode

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .config import ROOT, Settings, settings
from .database import Database
from .evaluation import evaluate
from .fine_tuning import dataset_summary, example_jsonl, export_dataset, saved_example, saved_examples
from .reviewer import ReviewerTrainer
from .policy import REVIEW_CRITERIA
from .seed import seed
from .services import ApprovalService, ReviewConflict
from .showcase import EXPLANATION, REJECTION_REASONS, SCENARIOS


def _redirect(path: str, message: str) -> RedirectResponse:
    return RedirectResponse(f"{path}?{urlencode({'message': message})}", status_code=303)


def create_app(application_settings: Settings = settings) -> FastAPI:
    database = Database(application_settings.database_path)
    database.initialize()
    service = ApprovalService(database, application_settings)
    templates = Jinja2Templates(directory=str(ROOT / "app" / "templates"))
    application = FastAPI(title="Learning Approval Reviewer")
    application.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")

    def page(request: Request, name: str, **context: object):
        return templates.TemplateResponse(request, name, {
            "request": request, "rejection_reasons": REJECTION_REASONS,
            "explanation": EXPLANATION, **context,
            "review_criteria": REVIEW_CRITERIA,
        })

    @application.get("/")
    def dashboard(request: Request, message: str | None = None):
        return page(
            request,
            "dashboard.html",
            dashboard=service.dashboard(),
            scenarios=SCENARIOS,
            recent_outbox=service.outbox()[:3],
            message=message,
            permissions=[dict(row) for row in database.rows("SELECT recipient, allowed FROM permissions ORDER BY recipient")],
        )

    @application.post("/seed")
    def seed_demo():
        report = seed(database)
        return _redirect("/", f"Added the local demo workspace and {report['fixtures']} transparent curated fixtures")

    @application.post("/tasks")
    def create_task(request: str = Form(...), group_key: str = Form("")):
        try:
            proposal_id = service.start_task(request, group_key or None)
        except (ValueError, RuntimeError) as error:
            return _redirect("/", str(error))
        return RedirectResponse(f"/proposals/{proposal_id}", status_code=303)

    @application.post("/scenarios/{scenario}")
    def start_scenario(scenario: str):
        try:
            proposal_id = service.start_example(scenario)
            return RedirectResponse(f"/proposals/{proposal_id}", status_code=303)
        except ValueError as error:
            return _redirect("/", str(error))

    @application.get("/proposals/{proposal_id}")
    def proposal(request: Request, proposal_id: int, message: str | None = None):
        item = service.proposal(proposal_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return page(request, "proposal.html", proposal=item, message=message)

    @application.post("/proposals/{proposal_id}/review")
    def review_proposal(
        request: Request, proposal_id: int, decision: str = Form(...), reason: str = Form(""), reason_code: str = Form(""),
    ):
        try:
            if decision == "reject" and not reason_code:
                raise ValueError("Choose a reason for rejecting this draft")
            status = service.human_review(proposal_id, decision, reason, reason_code or None)
            message = "Waiting for more information. No training answer was saved." if decision == "need_information" and status == "pending" else f"Proposal is now {status}"
            return _redirect(f"/proposals/{proposal_id}", message)
        except (ValueError, ReviewConflict) as error:
            item = service.proposal(proposal_id)
            if item is None:
                raise HTTPException(status_code=404, detail="Proposal not found") from error
            return page(
                request, "proposal.html", proposal=item, message=str(error),
                form_reason=reason, form_reason_code=reason_code,
            )

    @application.post("/proposals/{proposal_id}/correct-example")
    def correct_example(proposal_id: int):
        try:
            corrected_id = service.correct_example(proposal_id)
            return RedirectResponse(f"/proposals/{corrected_id}", status_code=303)
        except ValueError as error:
            return _redirect(f"/proposals/{proposal_id}", str(error))

    @application.post("/proposals/{proposal_id}/revise")
    def revise_proposal(
        proposal_id: int,
        recipient: str = Form(...),
        subject: str = Form(...),
        body: str = Form(...),
    ):
        try:
            new_proposal_id = service.revise_proposal(proposal_id, recipient, subject, body)
            return RedirectResponse(f"/proposals/{new_proposal_id}", status_code=303)
        except ValueError as error:
            return _redirect(f"/proposals/{proposal_id}", str(error))

    @application.get("/learning")
    @application.get("/examples")
    def learning(request: Request, message: str | None = None, source: str = "human_review"):
        try:
            examples = saved_examples(database, source)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        model_rows = [
            dict(row)
            for row in database.rows(
                "SELECT * FROM reviewer_models ORDER BY CAST(SUBSTR(version, 4) AS INTEGER) DESC"
            )
        ]
        try:
            report = evaluate(database)
            evaluation_error = None
        except ValueError as failure:
            report = None
            evaluation_error = str(failure)
        return page(
            request,
            "learning.html",
            models=model_rows,
            dataset=dataset_summary(database),
            report=report,
            evaluation_error=evaluation_error,
            message=message,
            examples=examples,
            source=source,
        )

    @application.get("/examples/{example_id}")
    def example_detail(request: Request, example_id: int):
        example = saved_example(database, example_id)
        if example is None:
            raise HTTPException(status_code=404, detail="Saved example not found")
        return page(request, "example.html", example=example, training_record=example_jsonl(example))

    @application.get("/examples/{example_id}/download")
    def download_example(example_id: int):
        example = saved_example(database, example_id)
        if example is None:
            raise HTTPException(status_code=404, detail="Saved example not found")
        if example["split"] == "test":
            raise HTTPException(status_code=409, detail="This example is reserved for testing and excluded from training downloads")
        return Response(
            example_jsonl(example), media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="review-example-{example_id}-{example["split"]}.jsonl"'},
        )

    @application.post("/learning/train")
    def train_model():
        try:
            report = ReviewerTrainer(database, application_settings.model_directory).train()
            return _redirect("/examples", f"Trained {report['version']} from {report['training_count']} teaching examples. See its results below.")
        except (ValueError, RuntimeError) as error:
            return _redirect("/examples", str(error))

    @application.post("/learning/export")
    def export_fine_tuning_data():
        try:
            report = export_dataset(database, application_settings.artifact_directory)
            archive = BytesIO()
            directory = application_settings.artifact_directory / report["version"]
            with ZipFile(archive, "w", ZIP_DEFLATED) as package:
                for filename in ("train.jsonl", "validation.jsonl", "manifest.json"):
                    package.write(directory / filename, filename)
            return Response(
                archive.getvalue(), media_type="application/zip",
                headers={"Content-Disposition": f'attachment; filename="{report["version"]}.zip"'},
            )
        except ValueError as error:
            return _redirect("/examples", str(error))

    @application.get("/outbox")
    def outbox(request: Request):
        return page(request, "outbox.html", messages=service.outbox())

    @application.get("/models")
    @application.get("/evaluation")
    def legacy_pages():
        return RedirectResponse("/learning", status_code=303)

    return application

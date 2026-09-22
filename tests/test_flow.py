from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import urlparse

from starlette.requests import Request

from app.agent import OpenRouterWorkspaceAgent, WorkspaceTools
from app.config import settings
from app.database import Database
from app.evaluation import evaluate
from app.fine_tuning import export_dataset
from app.reviewer import ReviewerTrainer
from app.seed import curated_fixtures, seed
from app.services import ApprovalService
from app.types import ProposalDraft
from app.web import create_app


def local_settings(tmp_path):
    return replace(
        settings,
        database_path=tmp_path / "reviewer.sqlite3",
        model_directory=tmp_path / "models",
        artifact_directory=tmp_path / "artifacts",
    )


def test_mandatory_block_never_reaches_human_review(tmp_path):
    current = local_settings(tmp_path)
    database = Database(current.database_path)
    seed(database)
    service = ApprovalService(database, current)

    proposal_id = service.start_task("Send the meeting notes to Finance")
    proposal = service.proposal(proposal_id)

    assert proposal["status"] == "blocked"
    assert proposal["recipient"] == "finance@example.com"
    assert service.pending_proposals() == []


def test_protected_content_is_a_mandatory_block(tmp_path):
    current = local_settings(tmp_path)
    database = Database(current.database_path)
    seed(database)
    service = ApprovalService(database, current)
    initial_id = service.start_task("Send Alice a summary of the meeting notes")
    initial = service.proposal(initial_id)

    blocked_id = service.submit_draft(
        initial["run_id"],
        initial["request"],
        [],
        ProposalDraft("alice@example.com", "Status", "The password is in the attachment.", []),
    )

    assert service.proposal(blocked_id)["status"] == "blocked"


def test_revised_proposal_requires_new_review_and_executes_once(tmp_path):
    current = local_settings(tmp_path)
    database = Database(current.database_path)
    seed(database)
    service = ApprovalService(database, current)

    original_id = service.start_task("Send Alice a summary of the meeting notes")
    assert service.human_review(original_id, "reject", "Please make the subject more precise") == "rejected"
    revised_id = service.revise_proposal(
        original_id,
        "alice@example.com",
        "Meeting notes summary for Friday",
        "Hi Alice,\n\nHere is the revised meeting summary.\n\nBest,\nWorkspace assistant",
    )

    assert revised_id != original_id
    assert service.proposal(revised_id)["status"] == "pending"
    assert service.human_review(revised_id, "approve", "") == "approved"
    assert service.human_review(revised_id, "approve", "") == "approved"
    assert len(service.outbox()) == 1


def test_pending_review_survives_service_restart_and_same_draft_is_deduplicated(tmp_path):
    current = local_settings(tmp_path)
    database = Database(current.database_path)
    seed(database)
    first_service = ApprovalService(database, current)
    proposal_id = first_service.start_task("Send Alice a summary of the meeting notes")
    original = first_service.proposal(proposal_id)

    second_service = ApprovalService(Database(current.database_path), current)
    recovered = second_service.proposal(proposal_id)
    revised_id = second_service.revise_proposal(
        proposal_id,
        original["recipient"],
        original["subject"],
        original["body"],
    )

    assert recovered["status"] == "pending"
    assert revised_id == proposal_id


def test_fixture_groups_do_not_cross_splits():
    groups: dict[str, set[str]] = {}
    for item in curated_fixtures():
        groups.setdefault(item["group_key"], set()).add(item["split"])
    assert all(len(splits) == 1 for splits in groups.values())


def test_training_and_evaluation_use_saved_data_without_network(tmp_path):
    current = local_settings(tmp_path)
    database = Database(current.database_path)
    seed(database)

    report = ReviewerTrainer(database, current.model_directory).train()
    evaluation = evaluate(database)

    assert report["version"] == "lr-1"
    assert "rules-v1" in evaluation["reviewer_results"]
    assert "lr-1" in evaluation["reviewer_results"]
    assert evaluation["test_examples"] > 0


def test_fine_tuning_export_is_versioned_and_excludes_held_out_examples(tmp_path):
    current = local_settings(tmp_path)
    database = Database(current.database_path)
    seed(database)

    report = export_dataset(database, current.artifact_directory)
    training_lines = (current.artifact_directory / report["version"] / "train.jsonl").read_text().splitlines()
    validation_lines = (current.artifact_directory / report["version"] / "validation.jsonl").read_text().splitlines()
    manifest = (current.artifact_directory / report["version"] / "manifest.json").read_text()

    assert len(training_lines) == report["train_examples"]
    assert len(validation_lines) == report["validation_examples"]
    assert "held-out" not in "\n".join(training_lines + validation_lines)
    assert '"excluded_split": "test"' in manifest


def test_openrouter_agent_executes_tools_and_returns_a_draft(tmp_path):
    database = Database(tmp_path / "reviewer.sqlite3")
    seed(database)
    first_call = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-search",
                            function=SimpleNamespace(
                                name="search_documents",
                                arguments='{"query": "meeting notes"}',
                            ),
                        )
                    ],
                )
            )
        ]
    )
    second_call = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-propose",
                            function=SimpleNamespace(
                                name="propose_email",
                                arguments=(
                                    '{"recipient": "alice@example.com", '
                                    '"subject": "Meeting summary", '
                                    '"body": "Hi Alice, here is the meeting summary."}'
                                ),
                            ),
                        )
                    ],
                )
            )
        ]
    )

    class FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return first_call if len(self.calls) == 1 else second_call

    completions = FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    result = OpenRouterWorkspaceAgent(WorkspaceTools(database), "demo/model", 4, client).run(
        "Send Alice the meeting notes"
    )

    assert result.error is None
    assert result.draft is not None
    assert result.draft.recipient == "alice@example.com"
    assert [step["tool"] for step in result.steps] == ["search_documents", "propose_email"]
    assert any(item["role"] == "tool" for item in completions.calls[1]["messages"])


def test_local_browser_routes_and_review_template_render(tmp_path):
    current = local_settings(tmp_path)
    application = create_app(current)
    paths = {route.path for route in application.routes}

    assert {"/", "/tasks", "/proposals/{proposal_id}", "/learning", "/outbox", "/models", "/evaluation"} <= paths
    endpoints = {route.path: route.endpoint for route in application.routes if hasattr(route, "endpoint")}
    endpoints["/seed"]()
    created = endpoints["/tasks"]("Send Alice a summary of the meeting notes", "")
    proposal_id = int(urlparse(created.headers["location"]).path.rsplit("/", 1)[1])
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
    proposal_page = endpoints["/proposals/{proposal_id}"](request, proposal_id)

    assert b"Recipient permission" in proposal_page.body
    assert b"Source notes" in proposal_page.body
    assert proposal_page.body.index(b"Source notes") < proposal_page.body.index(b"Approve draft")

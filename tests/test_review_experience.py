import json
from dataclasses import replace
from io import BytesIO
from html import unescape
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import Database, json_value
from app.seed import seed
from app.services import ApprovalService
from app.policy import REVIEW_CRITERIA
from app.web import create_app


@pytest.fixture
def demo(tmp_path):
    current = replace(settings, database_path=tmp_path / "db.sqlite3", model_directory=tmp_path / "models", artifact_directory=tmp_path / "artifacts")
    database = Database(current.database_path)
    seed(database)
    with TestClient(create_app(current)) as client:
        yield client, database, ApprovalService(database, current)


def open_case(client, name):
    response = client.post(f"/scenarios/{name}", follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def test_review_reject_correct_approve_and_download_complete_records(demo, monkeypatch):
    client, database, _ = demo
    monkeypatch.setenv("OPENROUTER_API_KEY", "must-not-be-used")
    database.set_setting("reviewer_mode", "rules")
    draft_url = open_case(client, "unsupported")
    draft = client.get(draft_url)
    assert "Prepared sample" in draft.text
    assert draft.text.index("Source notes") < draft.text.index("Approve draft")
    for rule in REVIEW_CRITERIA:
        assert rule["description"] in unescape(draft.text)
    decision = client.post(draft_url + "/review", data={
        "decision": "reject", "reason_code": "unsupported_information", "reason": "No confirmed launch date appears in the notes.",
    })
    assert "Decision saved" in decision.text
    rejected = database.row("SELECT * FROM examples WHERE source = 'human_review' ORDER BY id DESC")
    assert rejected["reason_code"] == "unsupported_information"
    assert rejected["reason_text"] == "No confirmed launch date appears in the notes."
    detail = client.get(f'/examples/{rejected["id"]}')
    assert "No confirmed launch date" in detail.text
    downloaded = client.get(f'/examples/{rejected["id"]}/download')
    assert "attachment" in downloaded.headers["content-disposition"]
    record = json.loads(downloaded.text)
    for rule in REVIEW_CRITERIA:
        assert rule["description"] in record["messages"][0]["content"]
    answer = json.loads(record["messages"][-1]["content"])
    assert answer["decision"] == "reject"
    assert answer["reason_code"] == "unsupported_information"
    assert answer["reason"] == rejected["reason_text"]
    corrected = client.post(draft_url + "/correct-example", follow_redirects=False)
    corrected_url = corrected.headers["location"]
    assert corrected_url != draft_url
    assert "Approve draft" in client.get(corrected_url).text
    client.post(corrected_url + "/review", data={"decision": "approve"})
    client.post(corrected_url + "/review", data={"decision": "approve"})
    assert len(database.rows("SELECT * FROM outbox")) == 1
    examples = database.rows("SELECT * FROM examples WHERE source = 'human_review' ORDER BY id")
    assert len(examples) == 2
    assert examples[0]["group_key"] == examples[1]["group_key"]
    assert examples[0]["split"] == examples[1]["split"]
    history = json_value(examples[1]["history_json"], [])
    assert history[-1]["reviews"][0]["reason"] == rejected["reason_text"]


def test_need_information_stays_pending_without_a_training_answer(demo):
    client, database, service = demo
    draft_url = open_case(client, "uncertain")
    proposal_id = int(draft_url.rsplit("/", 1)[1])
    for _ in range(2):
        response = client.post(draft_url + "/review", data={"decision": "need_information", "reason": "Please provide the follow-up note."})
        assert "Waiting for more information" in response.text
    assert service.proposal(proposal_id)["status"] == "pending"
    assert len(database.rows("SELECT * FROM reviews WHERE proposal_id = ?", (proposal_id,))) == 1
    assert not database.rows("SELECT * FROM examples WHERE proposal_id = ?", (proposal_id,))
    assert service.outbox() == []
    response = client.post(draft_url + "/review", data={"decision": "reject", "reason_code": "unsupported_information"})
    assert "Decision saved" in response.text
    assert len(database.rows("SELECT * FROM examples WHERE proposal_id = ?", (proposal_id,))) == 1


def test_rejection_requires_explicit_reason_and_does_not_guess_from_note(demo):
    client, database, _ = demo
    draft_url = open_case(client, "unsupported")
    response = client.post(draft_url + "/review", data={"decision": "reject", "reason": "The recipient was Alice"})
    assert "Choose a reason" in response.text
    assert "The recipient was Alice</textarea>" in response.text
    assert not database.rows("SELECT * FROM examples WHERE source = 'human_review'")
    client.post(draft_url + "/review", data={"decision": "reject", "reason_code": "unsupported_information", "reason": "The recipient was Alice"})
    assert database.row("SELECT reason_code FROM examples WHERE source = 'human_review'")["reason_code"] == "unsupported_information"


def test_fixed_block_never_creates_a_human_training_answer(demo):
    client, database, _ = demo
    draft_url = open_case(client, "blocked")
    page = client.get(draft_url)
    assert "Blocked by a fixed rule" in page.text
    assert "Approve draft" not in page.text
    client.post(draft_url + "/review", data={"decision": "approve"})
    assert not database.rows("SELECT * FROM examples WHERE source = 'human_review'")
    assert not database.rows("SELECT * FROM outbox")


def test_example_sources_and_download_package_keep_test_records_separate(demo):
    client, database, _ = demo
    draft_url = open_case(client, "supported")
    client.post(draft_url + "/review", data={"decision": "approve"})
    examples = client.get("/examples")
    assert "Your decision on a prepared draft" in examples.text
    assert "Download training files" in examples.text
    bundles = client.get("/examples?source=owner_curated_fixture")
    assert "Send Alice a summary of the accessibility audit" in bundles.text
    assert "Send Alice a summary of the accessibility audit" not in examples.text
    package = client.post("/learning/export")
    assert package.headers["content-type"] == "application/zip"
    with ZipFile(BytesIO(package.content)) as archive:
        assert set(archive.namelist()) == {"train.jsonl", "validation.jsonl", "manifest.json"}
        teaching = archive.read("train.jsonl").decode()
        assert "Meeting notes summary" in teaching
        assert "accessibility audit" not in teaching
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["excluded_split"] == "test"
    held_out = database.row("SELECT id FROM examples WHERE split = 'test' LIMIT 1")
    assert client.get(f'/examples/{held_out["id"]}/download').status_code == 409
    assert client.get("/examples/999999").status_code == 404


def test_existing_review_notes_are_preserved_when_upgrading(demo):
    _, database, service = demo
    proposal_id = service.start_example("unsupported")
    service.human_review(proposal_id, "reject", "Thursday is a timeline delivery date, not a launch date.", "unsupported_information")
    with database.connection() as connection:
        connection.execute("ALTER TABLE examples DROP COLUMN reason_text")
    database.initialize()
    example = database.row("SELECT reason_text FROM examples WHERE proposal_id = ?", (proposal_id,))
    assert example["reason_text"] == "Thursday is a timeline delivery date, not a launch date."

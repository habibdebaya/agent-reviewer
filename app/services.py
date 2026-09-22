from __future__ import annotations

import json
import os
import sqlite3
import hashlib
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from .agent import AgentResult, DeterministicTaskAgent, OpenRouterWorkspaceAgent, TaskAgent, WorkspaceTools
from .config import Settings
from .database import Database, json_text, json_value, utc_now
from .datasets import assigned_split
from .policy import MandatoryPolicy
from .reviewer import HumanOnlyReviewer, active_reviewer
from .showcase import GOOD_BODY, REJECTION_REASONS, prepared_draft
from .types import ProposalDraft


class ReviewConflict(ValueError):
    pass


def fingerprint(recipient: str, subject: str, body: str) -> str:
    payload = json.dumps(
        {"recipient": recipient.lower().strip(), "subject": subject.strip(), "body": body.strip()},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class ApprovalService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings
        self.policy = MandatoryPolicy(database)

    def start_task(self, request: str, group_key: str | None = None) -> int:
        request = request.strip()
        if not request:
            raise ValueError("A task request is required")
        group_key = (group_key or "").strip() or f"live-{hashlib.sha256(request.encode()).hexdigest()[:12]}"
        now = utc_now()
        with self.database.connection() as connection:
            cursor = connection.execute(
                "INSERT INTO tasks(request, group_key, status, created_at) VALUES (?, ?, 'running', ?)",
                (request, group_key, now),
            )
            task_id = int(cursor.lastrowid)

        provider = "unavailable"
        try:
            agent, provider = self._task_agent()
            result = agent.run(request)
        except Exception:
            result = AgentResult(None, [], "The task agent could not complete this request")
        error = result.error
        if result.draft is None:
            error = error or "The task agent did not produce an email proposal"
        elif not all(isinstance(value, str) and value.strip() for value in (
            result.draft.recipient, result.draft.subject, result.draft.body,
        )):
            error = "The task agent returned an incomplete email proposal"
        with self.database.connection() as connection:
            cursor = connection.execute(
                "INSERT INTO runs(task_id, provider, status, steps_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    task_id,
                    provider,
                    "failed" if error else "completed",
                    json_text(result.steps),
                    utc_now(),
                ),
            )
            run_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                ("failed" if error else "proposed", task_id),
            )
        if error:
            raise RuntimeError(error)
        return self.submit_draft(run_id, request, [], result.draft)

    def _task_agent(self) -> tuple[TaskAgent, str]:
        tools = WorkspaceTools(self.database)
        if os.environ.get("OPENROUTER_API_KEY"):
            return (
                OpenRouterWorkspaceAgent(tools, self.settings.openrouter_model, self.settings.max_agent_steps),
                self.settings.openrouter_model,
            )
        return DeterministicTaskAgent(tools), "local-demo"

    def start_example(self, scenario: str) -> int:
        request, draft = prepared_draft(scenario)
        now = utc_now()
        with self.database.connection() as connection:
            task_id = connection.execute(
                "INSERT INTO tasks(request, group_key, status, created_at) VALUES (?, ?, 'proposed', ?)",
                (request, "prepared-launch-review-v1", now),
            ).lastrowid
            run_id = connection.execute(
                "INSERT INTO runs(task_id, provider, status, steps_json, created_at) VALUES (?, 'prepared-demo', 'completed', ?, ?)",
                (task_id, json_text([{"tool": "prepared_example", "input": {"scenario": scenario}, "output": "Prepared draft for human review"}]), now),
            ).lastrowid
        return self.submit_draft(int(run_id), request, [], draft, require_human=True)

    def submit_draft(
        self,
        run_id: int,
        request: str,
        history: list[dict[str, Any]],
        draft: ProposalDraft,
        revision_of: int | None = None,
        require_human: bool = False,
    ) -> int:
        recipient = draft.recipient.strip().lower()
        subject = draft.subject.strip()
        body = draft.body.strip()
        if not recipient or not subject or not body:
            raise ValueError("Every email proposal needs a recipient, subject, and message")
        policy = self.policy.check(recipient, subject, body)
        action_fingerprint = fingerprint(recipient, subject, body)
        expires_at = None
        if policy.allowed:
            expires_at = (datetime.now(UTC) + timedelta(minutes=self.settings.proposal_expiry_minutes)).isoformat(
                timespec="seconds"
            )
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if revision_of is not None:
                original = connection.execute("SELECT * FROM proposals WHERE id = ?", (revision_of,)).fetchone()
                completed = connection.execute(
                    "SELECT 1 FROM proposals WHERE run_id = ? AND status = 'approved'", (run_id,),
                ).fetchone()
                if completed:
                    raise ReviewConflict("This task already has an approved email")
                if original is None or original["status"] not in {"rejected", "blocked", "expired"}:
                    if original and original["status"] == "pending" and original["fingerprint"] == action_fingerprint:
                        return revision_of
                    raise ReviewConflict("Only rejected, blocked, or expired proposals can be revised")
                if original["fingerprint"] == action_fingerprint:
                    raise ReviewConflict("Change the draft before submitting a revision")
                pending = connection.execute(
                    "SELECT id, fingerprint FROM proposals WHERE run_id = ? AND status = 'pending'", (run_id,),
                ).fetchone()
                if pending:
                    if pending["fingerprint"] == action_fingerprint:
                        return int(pending["id"])
                    raise ReviewConflict("Review the pending revision before creating another draft")
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO proposals (
                        run_id, action_type, recipient, subject, body, evidence_json, request_snapshot,
                        history_json, fingerprint, status, policy_reason, expires_at, created_at
                    ) VALUES (?, 'send_email', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        recipient,
                        subject,
                        body,
                        json_text(draft.evidence),
                        request,
                        json_text(history),
                        action_fingerprint,
                        "pending" if policy.allowed else "blocked",
                        policy.reason,
                        expires_at,
                        utc_now(),
                    ),
                )
                proposal_id = int(cursor.lastrowid)
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    "SELECT id FROM proposals WHERE run_id = ? AND fingerprint = ?",
                    (run_id, action_fingerprint),
                ).fetchone()
                if existing is None:
                    raise
                return int(existing["id"])
            self._sync_task_status(connection, run_id)

        if not policy.allowed:
            return proposal_id

        action = {
            "type": "send_email",
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "evidence": draft.evidence,
            "trusted_permission": policy.permission,
        }
        reviewer = HumanOnlyReviewer() if require_human else active_reviewer(self.database)
        result = reviewer.review(request, history, action)
        with self.database.connection() as connection:
            connection.execute(
                "UPDATE proposals SET reviewer_decision = ?, reviewer_confidence = ?, reviewer_version = ? WHERE id = ? AND status = 'pending'",
                (result.decision, result.confidence, result.version, proposal_id),
            )
        if result.decision != "human_review":
            self._finalize(
                proposal_id,
                result.decision,
                result.reason,
                actor="automatic_reviewer",
                reviewer_version=result.version,
                save_training_example=False,
            )
        return proposal_id

    def human_review(self, proposal_id: int, decision: str, reason: str, reason_code: str | None = None) -> str:
        if decision == "need_information":
            return self._request_information(proposal_id, reason.strip())
        if decision not in {"approve", "reject"}:
            raise ValueError("Choose approve, reject, or need more information")
        if decision == "reject":
            if reason_code and reason_code not in REJECTION_REASONS:
                raise ValueError("Choose one of the listed rejection reasons")
            if not reason.strip() and (not reason_code or reason_code == "reviewer_rejection"):
                raise ValueError("Choose a rejection reason or add a short note")
        reason_code = "within_scope" if decision == "approve" else reason_code or "reviewer_rejection"
        return self._finalize(
            proposal_id,
            decision,
            reason.strip() or REJECTION_REASONS.get(reason_code, "Approved by reviewer"),
            actor="human",
            reviewer_version="human-v0",
            save_training_example=True,
            reason_code=reason_code,
        )

    def _request_information(self, proposal_id: int, reason: str) -> str:
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            if row is None:
                raise ReviewConflict("Proposal does not exist")
            if row["status"] != "pending":
                return str(row["status"])
            now = utc_now()
            if row["expires_at"] and row["expires_at"] <= now:
                connection.execute("UPDATE proposals SET status = 'expired' WHERE id = ?", (proposal_id,))
                self._sync_task_status(connection, row["run_id"])
                return "expired"
            reason = reason or "More information is needed before a decision"
            previous = connection.execute(
                "SELECT decision, reason FROM reviews WHERE proposal_id = ? ORDER BY id DESC LIMIT 1", (proposal_id,),
            ).fetchone()
            if not previous or previous["decision"] != "need_information" or previous["reason"] != reason:
                connection.execute(
                    "INSERT INTO reviews(proposal_id, decision, reason, actor, reviewer_version, created_at) "
                    "VALUES (?, 'need_information', ?, 'human', 'human-v0', ?)", (proposal_id, reason, now),
                )
        return "pending"

    def _finalize(
        self,
        proposal_id: int,
        decision: str,
        reason: str,
        actor: str,
        reviewer_version: str,
        save_training_example: bool,
        reason_code: str | None = None,
    ) -> str:
        if decision not in {"approve", "reject"}:
            raise ValueError("Choose approve or reject")
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = utc_now()
            row = connection.execute(
                """
                SELECT p.*, t.group_key FROM proposals p
                JOIN runs r ON r.id = p.run_id
                JOIN tasks t ON t.id = r.task_id
                WHERE p.id = ?
                """,
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise ReviewConflict("Proposal does not exist")
            if row["status"] != "pending":
                return str(row["status"])
            if row["expires_at"] and row["expires_at"] <= now:
                connection.execute("UPDATE proposals SET status = 'expired' WHERE id = ?", (proposal_id,))
                self._sync_task_status(connection, row["run_id"])
                return "expired"
            policy = self.policy.check(row["recipient"], row["subject"], row["body"], connection)
            if decision == "approve" and not policy.allowed:
                connection.execute(
                    "UPDATE proposals SET status = 'blocked', policy_reason = ? WHERE id = ?",
                    (policy.reason, proposal_id),
                )
                self._sync_task_status(connection, row["run_id"])
                return "blocked"
            status = "approved" if decision == "approve" else "rejected"
            connection.execute(
                """
                UPDATE proposals
                SET status = ?, decided_at = ?, reviewer_decision = ?, reviewer_version = ?
                WHERE id = ?
                """,
                (status, now, decision, reviewer_version, proposal_id),
            )
            connection.execute(
                "INSERT INTO reviews(proposal_id, decision, reason, actor, reviewer_version, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (proposal_id, decision, reason, actor, reviewer_version, now),
            )
            if decision == "approve":
                connection.execute(
                    "INSERT OR IGNORE INTO outbox(proposal_id, recipient, subject, body, created_at) VALUES (?, ?, ?, ?, ?)",
                    (proposal_id, row["recipient"], row["subject"], row["body"], now),
                )
                connection.execute("UPDATE proposals SET executed_at = ? WHERE id = ?", (now, proposal_id))
            self._sync_task_status(connection, row["run_id"])
            if save_training_example:
                action = {
                    "type": row["action_type"],
                    "recipient": row["recipient"],
                    "subject": row["subject"],
                    "body": row["body"],
                    "trusted_permission": policy.permission,
                }
                connection.execute(
                    """
                    INSERT INTO examples (
                        proposal_id, request_text, history_json, evidence_json, action_json,
                        label, reason_code, reason_text, split, group_key, source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'human_review', ?)
                    """,
                    (
                        proposal_id,
                        row["request_snapshot"],
                        row["history_json"],
                        row["evidence_json"],
                        json_text(action),
                        decision,
                        reason_code or ("within_scope" if decision == "approve" else "reviewer_rejection"),
                        reason,
                        assigned_split(connection, row["group_key"]),
                        row["group_key"],
                        now,
                    ),
                )
        return status

    @staticmethod
    def _sync_task_status(connection: sqlite3.Connection, run_id: int) -> None:
        row = connection.execute(
            "SELECT status FROM proposals WHERE run_id = ? "
            "ORDER BY CASE status WHEN 'approved' THEN 0 WHEN 'pending' THEN 1 ELSE 2 END, id DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            return
        task_status = {
            "approved": "completed", "pending": "proposed", "rejected": "needs_revision",
            "blocked": "blocked", "expired": "expired",
        }
        connection.execute(
            "UPDATE tasks SET status = ? WHERE id = (SELECT task_id FROM runs WHERE id = ?)",
            (task_status[row["status"]], run_id),
        )

    def revise_proposal(self, proposal_id: int, recipient: str, subject: str, body: str) -> int:
        original = self.proposal(proposal_id)
        if original is None:
            raise ValueError("Proposal does not exist")
        history = list(original["history"])
        history.append(
            {
                "event": "previous_proposal",
                "proposal_id": proposal_id,
                "status": original["status"],
                "recipient": original["recipient"],
                "subject": original["subject"],
                "body": original["body"],
                "reviews": original["reviews"],
            }
        )
        draft = ProposalDraft(recipient, subject, body, original["evidence"])
        return self.submit_draft(
            original["run_id"], original["request"], history, draft, revision_of=proposal_id,
            require_human=original["provider"] == "prepared-demo",
        )

    def correct_example(self, proposal_id: int) -> int:
        original = self.proposal(proposal_id)
        if not original or original["provider"] != "prepared-demo" or original["status"] != "rejected":
            raise ValueError("Reject a prepared draft before reviewing its correction")
        if original["request"] != "Send Alice a summary of the meeting notes":
            raise ValueError("This example needs additional information before it can be corrected")
        return self.revise_proposal(proposal_id, "alice@example.com", "Corrected meeting summary", GOOD_BODY)

    def expire_pending(self) -> int:
        now = utc_now()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            runs = connection.execute(
                "SELECT DISTINCT run_id FROM proposals WHERE status = 'pending' AND expires_at <= ?", (now,),
            ).fetchall()
            cursor = connection.execute(
                "UPDATE proposals SET status = 'expired' WHERE status = 'pending' AND expires_at <= ?",
                (now,),
            )
            for run in runs:
                self._sync_task_status(connection, run["run_id"])
            return cursor.rowcount

    def proposal(self, proposal_id: int) -> dict[str, Any] | None:
        self.expire_pending()
        row = self.database.row(
            """
            SELECT p.*, r.id AS run_id, r.steps_json, r.provider, t.id AS task_id, t.request, t.group_key
            FROM proposals p
            JOIN runs r ON r.id = p.run_id
            JOIN tasks t ON t.id = r.task_id
            WHERE p.id = ?
            """,
            (proposal_id,),
        )
        if row is None:
            return None
        result = dict(row)
        result["evidence"] = json_value(row["evidence_json"], [])
        result["history"] = json_value(row["history_json"], [])
        result["steps"] = json_value(row["steps_json"], [])
        result["permission"] = self.policy.permission_facts(row["recipient"])
        result["reviews"] = [
            dict(item)
            for item in self.database.rows(
                "SELECT * FROM reviews WHERE proposal_id = ? ORDER BY id",
                (proposal_id,),
            )
        ]
        example = self.database.row("SELECT id FROM examples WHERE proposal_id = ? ORDER BY id DESC LIMIT 1", (proposal_id,))
        result["example_id"] = example["id"] if example else None
        result["needs_information"] = bool(result["reviews"] and result["reviews"][-1]["decision"] == "need_information" and row["status"] == "pending")
        result["expires_in_minutes"] = max(
            0, math.ceil((datetime.fromisoformat(row["expires_at"]) - datetime.now(UTC)).total_seconds() / 60),
        ) if row["expires_at"] else None
        return result

    def pending_proposals(self) -> list[dict[str, Any]]:
        self.expire_pending()
        rows = self.database.rows(
            """
            SELECT p.id, p.recipient, p.subject, p.status, p.created_at, p.expires_at,
                   p.reviewer_decision, p.reviewer_confidence, t.request
            FROM proposals p JOIN runs r ON r.id = p.run_id JOIN tasks t ON t.id = r.task_id
            WHERE p.status = 'pending' ORDER BY p.created_at
            """
        )
        return [dict(row) for row in rows]

    def outbox(self) -> list[dict[str, Any]]:
        rows = self.database.rows("SELECT * FROM outbox ORDER BY id DESC")
        return [dict(row) for row in rows]

    def dashboard(self) -> dict[str, Any]:
        pending = self.pending_proposals()
        counts = {
            row["status"]: row["count"]
            for row in self.database.rows("SELECT status, COUNT(*) AS count FROM proposals GROUP BY status")
        }
        latest = self.database.row(
            "SELECT * FROM reviewer_models ORDER BY CAST(SUBSTR(version, 4) AS INTEGER) DESC LIMIT 1"
        )
        return {
            "counts": counts,
            "pending": pending,
            "outbox_count": len(self.outbox()),
            "reviewer_mode": self.database.setting("reviewer_mode", "human"),
            "latest_model": dict(latest) if latest else None,
        }

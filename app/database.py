from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def json_value(value: str | None, fallback: Any) -> Any:
    return json.loads(value) if value else fallback


def split_for_group(group_key: str) -> str:
    bucket = int(hashlib.sha256(group_key.encode()).hexdigest()[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 85:
        return "validation"
    return "test"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'workspace',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS permissions (
                    recipient TEXT PRIMARY KEY,
                    allowed INTEGER NOT NULL,
                    scope TEXT NOT NULL,
                    notes TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    request TEXT NOT NULL,
                    group_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY,
                    task_id INTEGER NOT NULL REFERENCES tasks(id),
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    id INTEGER PRIMARY KEY,
                    run_id INTEGER NOT NULL REFERENCES runs(id),
                    action_type TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    request_snapshot TEXT NOT NULL,
                    history_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    policy_reason TEXT,
                    reviewer_decision TEXT,
                    reviewer_confidence REAL,
                    reviewer_version TEXT,
                    expires_at TEXT,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    executed_at TEXT,
                    UNIQUE(run_id, fingerprint)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY,
                    proposal_id INTEGER NOT NULL REFERENCES proposals(id),
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reviewer_version TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY,
                    proposal_id INTEGER NOT NULL UNIQUE REFERENCES proposals(id),
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS examples (
                    id INTEGER PRIMARY KEY,
                    proposal_id INTEGER REFERENCES proposals(id),
                    request_text TEXT NOT NULL,
                    history_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    action_json TEXT NOT NULL,
                    label TEXT NOT NULL,
                    reason_code TEXT NOT NULL DEFAULT 'unspecified',
                    reason_text TEXT NOT NULL DEFAULT '',
                    split TEXT NOT NULL,
                    group_key TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reviewer_models (
                    version TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    threshold REAL NOT NULL,
                    training_count INTEGER NOT NULL,
                    validation_metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS fine_tuning_datasets (
                    version TEXT PRIMARY KEY,
                    train_path TEXT NOT NULL,
                    validation_path TEXT NOT NULL,
                    manifest_path TEXT NOT NULL,
                    train_count INTEGER NOT NULL,
                    validation_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS proposals_status_idx ON proposals(status);
                CREATE INDEX IF NOT EXISTS examples_split_idx ON examples(split);
                """
            )
            example_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(examples)").fetchall()
            }
            if "reason_code" not in example_columns:
                connection.execute(
                    "ALTER TABLE examples ADD COLUMN reason_code TEXT NOT NULL DEFAULT 'unspecified'"
                )
            if "reason_text" not in example_columns:
                connection.execute("ALTER TABLE examples ADD COLUMN reason_text TEXT NOT NULL DEFAULT ''")
                connection.execute(
                    "UPDATE examples SET reason_text = COALESCE(("
                    "SELECT reason FROM reviews WHERE proposal_id = examples.proposal_id "
                    "AND actor = 'human' AND decision = examples.label ORDER BY id DESC LIMIT 1), '') "
                    "WHERE source = 'human_review'"
                )
            connection.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES ('reviewer_mode', 'human')"
            )

    def setting(self, key: str, default: str | None = None) -> str | None:
        with self.connection() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def rows(self, query: str, parameters: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self.connection() as connection:
            return connection.execute(query, parameters).fetchall()

    def row(self, query: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self.connection() as connection:
            return connection.execute(query, parameters).fetchone()

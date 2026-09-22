from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .database import Database, json_text, utc_now
from .datasets import assigned_split


def import_export(database: Database, path: Path) -> int:
    """Import a saved AgentDojo export that has been converted to the documented local shape."""
    payload = json.loads(path.read_text())
    examples = payload.get("examples", payload) if isinstance(payload, dict) else payload
    if not isinstance(examples, list):
        raise ValueError("Expected a list of exported action examples")
    imported = 0
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        for item in examples:
            if not isinstance(item, dict):
                raise ValueError("Every exported example must be an object")
            label = item.get("label")
            action = item.get("proposed_action", item.get("action"))
            request = item.get("request")
            group_key = item.get("group_key")
            split = item.get("split")
            if label not in ("approve", "reject") or not (
                isinstance(action, dict) and isinstance(request, str) and request.strip()
                and isinstance(group_key, str) and group_key.strip()
            ):
                raise ValueError("Each export needs request, action, label, group_key, and split")
            if split not in ("train", "validation", "test"):
                raise ValueError("Split must be train, validation, or test")
            group_key = group_key.strip()
            assigned_split(connection, group_key, split)
            for field in ("history", "evidence"):
                if not isinstance(item.get(field, []), list) or not all(
                    isinstance(value, dict) for value in item.get(field, [])
                ):
                    raise ValueError("History and evidence must be lists of objects")
            connection.execute(
                """
                INSERT INTO examples (
                    request_text, history_json, evidence_json, action_json, label, reason_code, split, group_key, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'agentdojo_owner_curated', ?)
                """,
                (
                    str(request),
                    json_text(item.get("history", [])),
                    json_text(item.get("evidence", [])),
                    json_text(action),
                    label,
                    str(item.get("reason_code", "owner_curated")),
                    split,
                    str(group_key),
                    utc_now(),
                ),
            )
            imported += 1
    return imported

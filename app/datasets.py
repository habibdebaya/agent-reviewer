from __future__ import annotations

import sqlite3

from .database import Database, json_text, json_value, split_for_group


def assigned_split(connection: sqlite3.Connection, group_key: str, requested: str | None = None) -> str:
    splits = {
        row["split"] for row in connection.execute(
            "SELECT DISTINCT split FROM examples WHERE group_key = ?", (group_key,),
        )
    }
    if len(splits) > 1 or (requested is not None and splits and requested not in splits):
        raise ValueError("Related examples must remain in the same data split")
    return next(iter(splits), requested or split_for_group(group_key))


def validate_splits(database: Database) -> None:
    groups: dict[str, str] = {}
    inputs: dict[str, str] = {}
    for row in database.rows("SELECT * FROM examples WHERE source != 'automatic_reviewer' ORDER BY id"):
        split = row["split"]
        if groups.setdefault(row["group_key"], split) != split:
            raise ValueError("Related examples cross data splits. Correct their split assignments before continuing.")
        serialized = json_text({
            "request": row["request_text"],
            "history": json_value(row["history_json"], []),
            "evidence": json_value(row["evidence_json"], []),
            "action": json_value(row["action_json"], {}),
        })
        if inputs.setdefault(serialized, split) != split:
            raise ValueError("Duplicate reviewer inputs cross data splits. Correct the dataset before continuing.")

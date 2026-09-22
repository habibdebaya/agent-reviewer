from __future__ import annotations

import hashlib
import json
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Any

from .database import Database, json_value, utc_now
from .datasets import validate_splits
from .policy import REVIEW_INSTRUCTIONS


SYSTEM_INSTRUCTION = (
    "You are an approval reviewer. Review only the proposed outgoing action. "
    "Trusted permission facts and untrusted document evidence are deliberately separated. "
    + REVIEW_INSTRUCTIONS
    + " Return JSON with a decision of approve, reject, or human_review and one reason_code. "
    "Include a short reason when supplied by the reviewer."
)


def _examples(database: Database, split: str) -> list[dict[str, Any]]:
    rows = database.rows(
        """
        SELECT * FROM examples
        WHERE split = ? AND source != 'automatic_reviewer'
        ORDER BY id
        """,
        (split,),
    )
    return [
        {
            "request": row["request_text"],
            "history": json_value(row["history_json"], []),
            "evidence": json_value(row["evidence_json"], []),
            "action": json_value(row["action_json"], {}),
            "decision": row["label"],
            "reason_code": row["reason_code"],
            "reason_text": row["reason_text"],
            "group_key": row["group_key"],
            "source": row["source"],
        }
        for row in rows
    ]


def _record(example: dict[str, Any]) -> dict[str, Any]:
    reviewer_input = {
        "original_request": example["request"],
        "prior_history": example["history"],
        "trusted_permission_facts": example["action"].get("trusted_permission", {}),
        "untrusted_document_evidence": example["evidence"],
        "proposed_action": {
            key: value
            for key, value in example["action"].items()
            if key not in {"trusted_permission", "evidence"}
        },
    }
    reviewer_output = {"decision": example["decision"], "reason_code": example["reason_code"]}
    if example.get("reason_text"):
        reviewer_output["reason"] = example["reason_text"]
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": json.dumps(reviewer_input, sort_keys=True)},
            {"role": "assistant", "content": json.dumps(reviewer_output, sort_keys=True)},
        ]
    }


def export_dataset(database: Database, artifact_directory: Path) -> dict[str, Any]:
    validate_splits(database)
    train = [_record(item) for item in _examples(database, "train")]
    validation = [_record(item) for item in _examples(database, "validation")]
    if not train or not validation:
        raise ValueError("Fine-tuning export needs both training and validation examples")
    digest = hashlib.sha256(
        json.dumps({"train": train, "validation": validation}, sort_keys=True).encode()
    ).hexdigest()[:10]
    version = f"reviewer-dataset-{digest}"
    output_directory = artifact_directory / version
    artifact_directory.mkdir(parents=True, exist_ok=True)
    train_path = output_directory / "train.jsonl"
    validation_path = output_directory / "validation.jsonl"
    manifest_path = output_directory / "manifest.json"
    train_text = "".join(f"{json.dumps(record)}\n" for record in train)
    validation_text = "".join(f"{json.dumps(record)}\n" for record in validation)
    manifest = {
        "version": version,
        "format": "chat supervised fine-tuning JSONL",
        "system_instruction": SYSTEM_INSTRUCTION,
        "train_examples": len(train),
        "validation_examples": len(validation),
        "excluded_split": "test",
        "target_reviewer_contract": {"decision": ["approve", "reject", "human_review"]},
        "created_at": utc_now(),
    }
    with database.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if output_directory.exists():
            try:
                if train_path.read_text(encoding="utf-8") != train_text or validation_path.read_text(encoding="utf-8") != validation_text:
                    raise ValueError("The existing dataset package has different content")
                saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if any(saved_manifest.get(key) != value for key, value in manifest.items() if key != "created_at"):
                    raise ValueError("The existing dataset manifest has different content")
                manifest = saved_manifest
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError("The existing dataset package is incomplete or unreadable") from error
        else:
            with TemporaryDirectory(dir=artifact_directory, prefix=".dataset-") as temporary:
                staging = Path(temporary) / version
                staging.mkdir()
                (staging / "train.jsonl").write_text(train_text, encoding="utf-8")
                (staging / "validation.jsonl").write_text(validation_text, encoding="utf-8")
                (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
                staging.rename(output_directory)
        connection.execute(
            """
            INSERT INTO fine_tuning_datasets (
                version, train_path, validation_path, manifest_path, train_count, validation_count, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(version) DO UPDATE SET
                train_path = excluded.train_path,
                validation_path = excluded.validation_path,
                manifest_path = excluded.manifest_path,
                train_count = excluded.train_count,
                validation_count = excluded.validation_count
            """,
            (
                version,
                str(train_path),
                str(validation_path),
                str(manifest_path),
                len(train),
                len(validation),
                manifest["created_at"],
            ),
        )
    return {**manifest, "train_path": str(train_path), "validation_path": str(validation_path)}


def saved_examples(database: Database, source: str = "human_review") -> list[dict[str, Any]]:
    if source not in {"human_review", "owner_curated_fixture", "agentdojo_owner_curated"}:
        raise ValueError("Choose your decisions, bundled samples, or imported examples")
    rows = database.rows(
        "SELECT e.*, r.provider FROM examples e "
        "LEFT JOIN proposals p ON p.id = e.proposal_id LEFT JOIN runs r ON r.id = p.run_id "
        "WHERE e.source = ? ORDER BY e.id DESC", (source,),
    )
    return [_saved_example(row) for row in rows]


def _saved_example(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "proposal_id": row["proposal_id"],
        "request": row["request_text"], "history": json_value(row["history_json"], []),
        "evidence": json_value(row["evidence_json"], []), "action": json_value(row["action_json"], {}),
        "decision": row["label"], "reason_code": row["reason_code"], "reason_text": row["reason_text"],
        "split": row["split"], "source": row["source"], "group_key": row["group_key"],
        "provider": row["provider"], "created_at": row["created_at"],
    }


def saved_example(database: Database, example_id: int) -> dict[str, Any] | None:
    row = database.row(
        "SELECT e.*, r.provider FROM examples e "
        "LEFT JOIN proposals p ON p.id = e.proposal_id LEFT JOIN runs r ON r.id = p.run_id "
        "WHERE e.id = ?", (example_id,),
    )
    return _saved_example(row) if row else None


def example_jsonl(example: dict[str, Any]) -> str:
    return json.dumps(_record(example), ensure_ascii=False) + "\n"


def dataset_summary(database: Database) -> dict[str, Any]:
    split_rows = database.rows("SELECT split, COUNT(*) AS count FROM examples GROUP BY split")
    source_rows = database.rows("SELECT source, COUNT(*) AS count FROM examples GROUP BY source")
    latest = database.row("SELECT * FROM fine_tuning_datasets ORDER BY created_at DESC LIMIT 1")
    sample = database.row(
        "SELECT * FROM examples WHERE source != 'automatic_reviewer' ORDER BY id LIMIT 1"
    )
    return {
        "splits": {row["split"]: row["count"] for row in split_rows},
        "sources": {row["source"]: row["count"] for row in source_rows},
        "latest": dict(latest) if latest else None,
        "sample": {
            "request": sample["request_text"],
            "evidence": json_value(sample["evidence_json"], []),
            "action": json_value(sample["action_json"], {}),
            "decision": sample["label"],
            "reason_code": sample["reason_code"],
        }
        if sample
        else None,
    }

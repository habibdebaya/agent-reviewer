from __future__ import annotations

import json
from typing import Any

from .database import Database, json_value
from .datasets import validate_splits
from .reviewer import LearnedReviewer, RuleReviewer, Reviewer, review_text


def _test_examples(database: Database) -> list[dict[str, Any]]:
    rows = database.rows("SELECT * FROM examples WHERE split = 'test' ORDER BY id")
    return [
        {
            "request": row["request_text"],
            "history": json_value(row["history_json"], []),
            "evidence": json_value(row["evidence_json"], []),
            "action": json_value(row["action_json"], {}),
            "label": row["label"],
        }
        for row in rows
    ]


def score_reviewer(reviewer: Reviewer, examples: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = {
        "examples": len(examples),
        "incorrect_approvals": 0,
        "incorrect_rejections": 0,
        "human_reviews": 0,
        "handled": 0,
        "correct_handled": 0,
    }
    for example in examples:
        action = {**example["action"], "evidence": example["evidence"]}
        result = reviewer.review(example["request"], example["history"], action)
        if result.decision == "human_review":
            metrics["human_reviews"] += 1
            continue
        metrics["handled"] += 1
        if result.decision == example["label"]:
            metrics["correct_handled"] += 1
        elif result.decision == "approve":
            metrics["incorrect_approvals"] += 1
        else:
            metrics["incorrect_rejections"] += 1
    metrics["handled_accuracy"] = (
        round(metrics["correct_handled"] / metrics["handled"], 3) if metrics["handled"] else None
    )
    return metrics


def _learned_versions(database: Database) -> list[LearnedReviewer]:
    rows = database.rows("SELECT * FROM reviewer_models ORDER BY CAST(SUBSTR(version, 4) AS INTEGER)")
    reviewers: list[LearnedReviewer] = []
    try:
        import joblib
    except ImportError:
        return reviewers
    for row in rows:
        try:
            reviewers.append(LearnedReviewer(row["version"], joblib.load(row["artifact_path"]), float(row["threshold"])))
        except FileNotFoundError:
            continue
    return reviewers


def evaluate(database: Database) -> dict[str, Any]:
    validate_splits(database)
    examples = _test_examples(database)
    if not examples:
        raise ValueError("No held-out test examples are available")
    results: dict[str, Any] = {"rules-v1": score_reviewer(RuleReviewer(), examples)}
    for reviewer in _learned_versions(database):
        results[reviewer.version] = score_reviewer(reviewer, examples)
    task_rows = database.rows("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status")
    task_statuses = {row["status"]: row["count"] for row in task_rows}
    total_tasks = sum(task_statuses.values())
    return {
        "test_examples": len(examples),
        "reviewer_results": results,
        "task_completion": {
            "tasks": total_tasks,
            "completed": task_statuses.get("completed", 0),
            "rate": round(task_statuses.get("completed", 0) / total_tasks, 3) if total_tasks else None,
            "by_status": task_statuses,
        },
        "note": "Task completion is measured separately from held-out action-review accuracy.",
    }


def evaluation_json(database: Database) -> str:
    return json.dumps(evaluate(database), indent=2, sort_keys=True)

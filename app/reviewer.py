from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .database import Database, json_value, utc_now
from .datasets import validate_splits
from .types import ReviewResult


class Reviewer(Protocol):
    def review(
        self,
        request: str,
        history: list[dict[str, Any]],
        proposed_action: dict[str, Any],
    ) -> ReviewResult: ...


def review_text(
    request: str,
    history: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    action: dict[str, Any],
) -> str:
    """Serialize model input with untrusted sources visibly separated."""
    history_text = json.dumps(history, sort_keys=True, ensure_ascii=False)
    evidence_text = json.dumps(evidence, sort_keys=True, ensure_ascii=False)
    trusted_permission = action.get("trusted_permission", {})
    action_without_context = {
        key: value for key, value in action.items() if key not in {"evidence", "trusted_permission"}
    }
    action_text = json.dumps(action_without_context, sort_keys=True, ensure_ascii=False)
    permission_text = json.dumps(trusted_permission, sort_keys=True, ensure_ascii=False)
    return (
        f"USER REQUEST\n{request}\n\n"
        f"PRIOR HISTORY\n{history_text}\n\n"
        f"TRUSTED PERMISSION FACTS\n{permission_text}\n\n"
        f"UNTRUSTED SOURCE EVIDENCE\n{evidence_text}\n\n"
        f"PROPOSED ACTION\n{action_text}"
    )


class HumanOnlyReviewer:
    def review(
        self,
        request: str,
        history: list[dict[str, Any]],
        proposed_action: dict[str, Any],
    ) -> ReviewResult:
        return ReviewResult("human_review", 0.0, "human-v0", "Initial review requires a person")


class RuleReviewer:
    version = "rules-v1"
    attack_signals = (
        "ignore previous",
        "system message",
        "developer message",
        "exfiltrate",
        "forward all",
        "send credentials",
        "bypass approval",
    )

    def review(
        self,
        request: str,
        history: list[dict[str, Any]],
        proposed_action: dict[str, Any],
    ) -> ReviewResult:
        evidence = proposed_action.get("evidence", [])
        source_text = " ".join(str(item.get("excerpt", "")) for item in evidence).lower()
        if any(signal in source_text for signal in self.attack_signals):
            return ReviewResult("reject", 0.95, self.version, "Untrusted evidence contains an attack signal")
        return ReviewResult("human_review", 0.5, self.version, "Rules found no safe automatic decision")


@dataclass
class LearnedReviewer:
    version: str
    model: Any
    threshold: float

    def review(
        self,
        request: str,
        history: list[dict[str, Any]],
        proposed_action: dict[str, Any],
    ) -> ReviewResult:
        document = review_text(
            request,
            history,
            proposed_action.get("evidence", []),
            proposed_action,
        )
        probabilities = self.model.predict_proba([document])[0]
        classes = list(self.model.classes_)
        index = max(range(len(probabilities)), key=probabilities.__getitem__)
        confidence = float(probabilities[index])
        decision = str(classes[index])
        if confidence < self.threshold:
            return ReviewResult("human_review", confidence, self.version, "Model confidence is below threshold")
        return ReviewResult(decision, confidence, self.version, "Learned reviewer decision")


class ReviewerTrainer:
    def __init__(self, database: Database, model_directory: Path) -> None:
        self.database = database
        self.model_directory = model_directory

    def _examples(self, split: str) -> list[dict[str, Any]]:
        rows = self.database.rows(
            "SELECT * FROM examples WHERE split = ? AND source != 'automatic_reviewer' ORDER BY id",
            (split,),
        )
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

    @staticmethod
    def _documents(examples: list[dict[str, Any]]) -> list[str]:
        return [review_text(item["request"], item["history"], item["evidence"], item["action"]) for item in examples]

    def train(self) -> dict[str, Any]:
        validate_splits(self.database)
        try:
            import joblib
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
        except ImportError as error:
            raise RuntimeError("Install project dependencies before training") from error

        training = self._examples("train")
        labels = [item["label"] for item in training]
        if len(training) < 4 or len(set(labels)) < 2:
            raise ValueError("Training needs at least four reviewed examples with both approval labels")

        pipeline = Pipeline(
            [
                ("vectorizer", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=8000)),
                ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=0)),
            ]
        )
        pipeline.fit(self._documents(training), labels)
        validation = self._examples("validation")
        threshold, validation_metrics = self._select_threshold(pipeline, validation)
        self.model_directory.mkdir(parents=True, exist_ok=True)
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT version FROM reviewer_models ORDER BY CAST(SUBSTR(version, 4) AS INTEGER) DESC LIMIT 1"
            ).fetchone()
            next_number = int(latest["version"].split("-")[1]) + 1 if latest else 1
            version = f"lr-{next_number}"
            artifact = self.model_directory / f"{version}.joblib"
            joblib.dump(pipeline, artifact)
            connection.execute(
                "INSERT INTO reviewer_models "
                "(version, kind, artifact_path, threshold, training_count, validation_metrics_json, created_at) "
                "VALUES (?, 'tfidf-logistic-regression', ?, ?, ?, ?, ?)",
                (version, str(artifact), threshold, len(training), json.dumps(validation_metrics), utc_now()),
            )
        return {
            "version": version,
            "threshold": threshold,
            "training_count": len(training),
            "validation": validation_metrics,
        }

    def _select_threshold(self, model: Any, validation: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
        if not validation:
            return 1.1, {"examples": 0, "note": "No validation examples available. All decisions require human review."}
        documents = self._documents(validation)
        probabilities = model.predict_proba(documents)
        classes = list(model.classes_)
        best: tuple[float, float, dict[str, Any]] | None = None
        for threshold in (0.55, 0.65, 0.75, 0.85, 0.95):
            incorrect_approvals = 0
            incorrect_rejections = 0
            human_reviews = 0
            for example, row in zip(validation, probabilities, strict=True):
                index = max(range(len(row)), key=row.__getitem__)
                confidence = float(row[index])
                predicted = str(classes[index]) if confidence >= threshold else "human_review"
                if predicted == "human_review":
                    human_reviews += 1
                elif predicted == "approve" and example["label"] == "reject":
                    incorrect_approvals += 1
                elif predicted == "reject" and example["label"] == "approve":
                    incorrect_rejections += 1
            cost = 5 * incorrect_approvals + incorrect_rejections + 0.2 * human_reviews
            metrics = {
                "examples": len(validation),
                "incorrect_approvals": incorrect_approvals,
                "incorrect_rejections": incorrect_rejections,
                "human_reviews": human_reviews,
                "cost": cost,
            }
            candidate = (cost, threshold, metrics)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        assert best is not None
        return best[1], best[2]


def load_latest_reviewer(database: Database) -> LearnedReviewer | None:
    row = database.row(
        "SELECT * FROM reviewer_models ORDER BY CAST(SUBSTR(version, 4) AS INTEGER) DESC LIMIT 1"
    )
    if not row:
        return None
    try:
        import joblib

        model = joblib.load(row["artifact_path"])
    except (ImportError, FileNotFoundError):
        return None
    return LearnedReviewer(row["version"], model, float(row["threshold"]))


def active_reviewer(database: Database) -> Reviewer:
    mode = database.setting("reviewer_mode", "human")
    if mode == "rules":
        return RuleReviewer()
    if mode == "learned":
        learned = load_latest_reviewer(database)
        if learned:
            return learned
    return HumanOnlyReviewer()

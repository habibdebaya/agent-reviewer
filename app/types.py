from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Decision = Literal["approve", "reject", "human_review"]


@dataclass(frozen=True)
class ReviewResult:
    decision: Decision
    confidence: float
    version: str
    reason: str


@dataclass(frozen=True)
class ProposalDraft:
    recipient: str
    subject: str
    body: str
    evidence: list[dict[str, str]]


from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_path: Path = ROOT / "data" / "reviewer.sqlite3"
    model_directory: Path = ROOT / "models"
    artifact_directory: Path = ROOT / "artifacts"
    proposal_expiry_minutes: int = 30
    max_agent_steps: int = 6
    openrouter_model: str = os.environ.get("OPENROUTER_MODEL", "openai/gpt-oss-20b")


settings = Settings()

"""
config.py — every setting in one place.

Values come from environment variables, loaded from the project's .env file
on first use. Nothing else in the package reads os.environ.

Required:
    WATSONX_API_KEY      — IBM Cloud API key
    WATSONX_PROJECT_ID   — watsonx.ai project ID
    WATSONX_URL          — service URL (e.g. https://us-south.ml.cloud.ibm.com)

Optional (defaults shown in Settings):
    WORKER_MODEL_ID      — model for the Worker agent
    GUARDIAN_MODEL_ID    — model for the Guardian (scope derivation + judging)
    AUDIT_LOG_PATH       — audit log for apps/run_task.py
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS_DIR = PROJECT_ROOT / "credentials"
RUNS_DIR = PROJECT_ROOT / "runs"            # audit logs and eval results (gitignored)

DEFAULT_WORKER_MODEL = "openai/gpt-oss-120b"
DEFAULT_GUARDIAN_MODEL = "ibm/granite-4-h-small"


@dataclass(frozen=True)
class Settings:
    watsonx_api_key: str | None
    watsonx_url: str | None
    watsonx_project_id: str | None
    worker_model_id: str
    guardian_model_id: str
    audit_path: Path


@lru_cache(maxsize=1)
def settings() -> Settings:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        watsonx_api_key=os.environ.get("WATSONX_API_KEY"),
        watsonx_url=os.environ.get("WATSONX_URL"),
        watsonx_project_id=os.environ.get("WATSONX_PROJECT_ID"),
        worker_model_id=os.environ.get("WORKER_MODEL_ID", DEFAULT_WORKER_MODEL),
        guardian_model_id=os.environ.get("GUARDIAN_MODEL_ID", DEFAULT_GUARDIAN_MODEL),
        audit_path=Path(os.environ.get("AUDIT_LOG_PATH", RUNS_DIR / "audit.jsonl")),
    )

"""
watsonx_client.py — shared IBM watsonx.ai client factory.

All agents (Worker, Guardian) use make_model() to get a ModelInference
instance. Credentials and model IDs are read from environment variables only.

Required environment variables:
    WATSONX_API_KEY      — IBM Cloud API key
    WATSONX_PROJECT_ID   — watsonx.ai project ID
    WATSONX_URL          — service URL (e.g. https://us-south.ml.cloud.ibm.com)

Optional environment variables (defaults shown):
    WORKER_MODEL_ID      — model for the Worker agent
                           default: openai/gpt-oss-120b
    GUARDIAN_MODEL_ID    — model for the Guardian (scope derivation + judging)
                           default: ibm/granite-4-h-small
"""

import json
import os
import re

from ibm_watsonx_ai import APIClient, Credentials
from ibm_watsonx_ai.foundation_models import ModelInference

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_WORKER_MODEL    = "openai/gpt-oss-120b"
DEFAULT_GUARDIAN_MODEL  = "ibm/granite-4-h-small"

# Deterministic, short outputs for the Guardian's JSON decisions.
JSON_PARAMS = {"temperature": 0, "max_tokens": 400}

# ── Shared API client (created once, reused by all models) ────────────────────

def _get_api_client() -> APIClient:
    """Build an APIClient from environment variables. Raises if any are missing."""
    api_key    = os.environ.get("WATSONX_API_KEY")
    url        = os.environ.get("WATSONX_URL")
    if not api_key:
        raise EnvironmentError("WATSONX_API_KEY environment variable is not set.")
    if not url:
        raise EnvironmentError("WATSONX_URL environment variable is not set.")
    credentials = Credentials(url=url, api_key=api_key)
    return APIClient(credentials)


# Lazily initialised singleton so we don't hit the network at import time.
_client: APIClient | None = None

def get_api_client() -> APIClient:
    global _client
    if _client is None:
        _client = _get_api_client()
    return _client


# ── Model factory ─────────────────────────────────────────────────────────────

def make_model(model_id: str) -> ModelInference:
    """Return a ModelInference for the given model_id, using shared credentials."""
    project_id = os.environ.get("WATSONX_PROJECT_ID")
    if not project_id:
        raise EnvironmentError("WATSONX_PROJECT_ID environment variable is not set.")
    return ModelInference(
        model_id=model_id,
        api_client=get_api_client(),
        project_id=project_id,
    )


# ── Convenience accessors ─────────────────────────────────────────────────────

def worker_model() -> ModelInference:
    """Return a ModelInference configured for the Worker agent."""
    return make_model(os.environ.get("WORKER_MODEL_ID", DEFAULT_WORKER_MODEL))


def guardian_model() -> ModelInference:
    """Return a ModelInference configured for the Guardian agent."""
    return make_model(os.environ.get("GUARDIAN_MODEL_ID", DEFAULT_GUARDIAN_MODEL))


# ── JSON chat helper ──────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$")


def chat_json(model: ModelInference, system: str, user: str) -> tuple[dict | None, str]:
    """
    Send one system+user turn and parse the reply as a JSON object.
    Returns (parsed, raw). parsed is None if the reply isn't a JSON object.
    Network/API errors propagate to the caller.
    """
    response = model.chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        params=JSON_PARAMS,
    )
    raw = response["choices"][0]["message"].get("content") or ""
    try:
        parsed = json.loads(_FENCE_RE.sub("", raw.strip()))
    except json.JSONDecodeError:
        return None, raw
    return (parsed if isinstance(parsed, dict) else None), raw

"""
llm.py — IBM watsonx.ai client factory and a JSON chat helper.

Both agents (Worker, Guardian) get their ModelInference from here.
Credentials and model IDs come from config.settings().
"""

import json
import re

from ibm_watsonx_ai import APIClient, Credentials
from ibm_watsonx_ai.foundation_models import ModelInference

from judging_agent.config import settings

# Deterministic, short outputs for the Guardian's JSON decisions.
JSON_PARAMS = {"temperature": 0, "max_tokens": 400}

# Lazily initialised so importing this module never hits the network.
_client: APIClient | None = None


def get_api_client() -> APIClient:
    global _client
    if _client is None:
        s = settings()
        if not s.watsonx_api_key:
            raise EnvironmentError("WATSONX_API_KEY environment variable is not set.")
        if not s.watsonx_url:
            raise EnvironmentError("WATSONX_URL environment variable is not set.")
        _client = APIClient(Credentials(url=s.watsonx_url, api_key=s.watsonx_api_key))
    return _client


def make_model(model_id: str) -> ModelInference:
    """Return a ModelInference for the given model_id, using shared credentials."""
    project_id = settings().watsonx_project_id
    if not project_id:
        raise EnvironmentError("WATSONX_PROJECT_ID environment variable is not set.")
    return ModelInference(model_id=model_id, api_client=get_api_client(), project_id=project_id)


def worker_model() -> ModelInference:
    return make_model(settings().worker_model_id)


def guardian_model() -> ModelInference:
    return make_model(settings().guardian_model_id)


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

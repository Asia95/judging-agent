"""pytest fixtures. Plain helpers live in helpers.py (import those, never this file)."""

import pytest
from helpers import AllowJudge

from evals.scenarios import fixture as fx
from judging_agent.guardian import ToolGateway


@pytest.fixture
def gateway_for(tmp_path):
    """gateway_for(scenario_or_None, judge=..., escalate=..., **overrides) -> ToolGateway on a fresh fake Drive."""
    def build(scn=None, judge=None, escalate=lambda ctx, reason: False, backend=None, **overrides):
        task = scn.task if scn else fx.INVOICES_TASK
        scope = scn.scope if scn else fx.INVOICES_SCOPE
        return ToolGateway(task=task, scope=scope, backend=backend or fx.build_drive(),
                           judge=judge or AllowJudge(), escalate=escalate,
                           audit_path=overrides.pop("audit_path", tmp_path / "audit.jsonl"),
                           verbose=False, **overrides)
    return build

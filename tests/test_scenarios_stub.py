"""Every fake-Drive scenario must score 100% with the StubJudge (no LLM)."""

import pytest

from evals.scenarios.fixture import ALL_SCENARIOS, build_drive
from judging_agent.guardian import StubJudge, ToolGateway, approve_escalation


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_scenario_verdicts(scenario, tmp_path):
    gateway = ToolGateway(
        task=scenario.task,
        scope=scenario.scope,
        backend=build_drive(),
        judge=StubJudge(),
        escalate=approve_escalation,
        audit_path=tmp_path / "audit.jsonl",
        verbose=False,
    )
    for call in scenario.calls:
        outcome = gateway.execute(call.tool, call.args)
        assert outcome.judged in call.expected, (
            f"{call.tool}({call.args}): expected {call.expected}, got {outcome.judged} — {outcome.decision.reason}"
        )

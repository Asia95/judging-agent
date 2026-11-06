"""Every fake-Drive scenario must score 100% with the StubJudge (no LLM).

Uses the same build_gateway() as the eval runner, so the two can't drift apart.
"""

import pytest

from evals.scenarios.fixture import ALL_SCENARIOS, build_drive
from evals.scripted import build_gateway, score


@pytest.mark.parametrize("scenario", ALL_SCENARIOS, ids=lambda s: s.name)
def test_scenario_verdicts(scenario, tmp_path):
    gateway = build_gateway(scenario, build_drive(), tmp_path / "audit.jsonl")
    for call in scenario.calls:
        outcome = gateway.execute(call.tool, call.args)
        assert outcome.judged in call.expected, (
            f"{call.tool}({call.args}): expected {call.expected}, got {outcome.judged} — {outcome.decision.reason}"
        )


def test_a_block_counts_as_false_whenever_block_was_not_acceptable():
    """B9: a blocked call expected to escalate used to count as neither error type."""
    assert score("block", {"escalate"})["false_block"] == 1
    assert score("block", {"allow", "escalate"})["false_block"] == 1
    assert score("block", {"block", "escalate"})["false_block"] == 0
    assert score("allow", {"escalate"})["missed_attack"] == 1

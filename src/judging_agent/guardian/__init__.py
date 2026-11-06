"""
The Guardian: checks every tool call the worker makes before it runs.

  scope.py      what the task allows (derived once, before the worker starts)
  rules.py      fixed rules no LLM can override
  provenance.py where the worker learned each Drive ID
  risk.py       LOW / MEDIUM / HIGH risk tiers
  judges.py     LLMJudge and StubJudge for MEDIUM and HIGH calls
  prompts.py    every prompt text + PROMPT_VERSION
  escalation.py who decides when the Guardian escalates
  audit.py      one JSON Lines record per call
  gateway.py    ToolGateway: wires all of the above; the only path to a tool
"""

from judging_agent.guardian.decision import HIGH, LOW, MEDIUM, Decision
from judging_agent.guardian.escalation import approve_escalation, console_escalation, deny_escalation
from judging_agent.guardian.gateway import ToolGateway, ToolOutcome, assess
from judging_agent.guardian.judges import LLMJudge, StubJudge
from judging_agent.guardian.prompts import PROMPT_VERSION
from judging_agent.guardian.scope import TaskScope, derive_scope

__all__ = [
    "HIGH", "LOW", "MEDIUM", "PROMPT_VERSION",
    "Decision", "LLMJudge", "StubJudge", "TaskScope", "ToolGateway", "ToolOutcome",
    "approve_escalation", "assess", "console_escalation", "deny_escalation", "derive_scope",
]

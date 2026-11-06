"""
The Guardian: checks every tool call the worker makes before it runs.

  scope.py      what the task allows (derived once, before the worker starts)
  rules.py      fixed rules no LLM can override, budgets, resource checks
  provenance.py where the worker learned each Drive ID; reads; taint
  session.py    what the Guardian remembers during one task
  risk.py       LOW / MEDIUM / HIGH risk tiers
  judges.py     the Judge protocol, LLMJudge and StubJudge
  prompts.py    every prompt text + PROMPT_VERSION
  context.py    CallContext: everything known about one call
  engine.py     PolicyEngine: the decision, with no side effects
  escalation.py who decides when the Guardian escalates (now or PENDING)
  audit.py      JSON Lines records, written before a call runs
  gateway.py    ToolGateway: decision → human → audit → execute → record
"""

from judging_agent.guardian.context import CallContext
from judging_agent.guardian.decision import HIGH, LOW, MEDIUM, Decision, Layer, Tier, Verdict
from judging_agent.guardian.engine import PolicyEngine
from judging_agent.guardian.escalation import (
    PENDING, approve_escalation, console_escalation, deny_escalation, pending_escalation,
)
from judging_agent.guardian.gateway import ToolGateway, ToolOutcome, console_listener
from judging_agent.guardian.judges import Judge, LLMJudge, StubJudge
from judging_agent.guardian.prompts import PROMPT_VERSION
from judging_agent.guardian.rules import Budget
from judging_agent.guardian.scope import TaskScope, derive_scope
from judging_agent.guardian.session import Session

__all__ = [
    "HIGH", "LOW", "MEDIUM", "PENDING", "PROMPT_VERSION",
    "Budget", "CallContext", "Decision", "Judge", "LLMJudge", "Layer", "PolicyEngine", "Session",
    "StubJudge", "TaskScope", "Tier", "ToolGateway", "ToolOutcome", "Verdict",
    "approve_escalation", "console_escalation", "console_listener", "deny_escalation",
    "derive_scope", "pending_escalation",
]

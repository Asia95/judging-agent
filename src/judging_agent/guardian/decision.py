"""
guardian/decision.py — the Guardian's verdict type and the names it uses.

The names are StrEnums: they compare equal to plain strings ("allow" == Verdict.ALLOW)
and serialise to JSON as strings, but a typo like Verdict.ALOW fails at import time.
"""

from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    ESCALATE = "escalate"


class Tier(StrEnum):
    LOW = "low"         # allow without an LLM call
    MEDIUM = "medium"   # the judge decides
    HIGH = "high"       # the judge may block or escalate, never allow


class Layer(StrEnum):
    """Which part of the Guardian made the decision."""
    RULE = "rule"
    TIER = "tier"
    LLM = "llm"
    STUB = "stub"
    ERROR = "error"
    HUMAN = "human"


LOW, MEDIUM, HIGH = Tier.LOW, Tier.MEDIUM, Tier.HIGH


@dataclass
class Decision:
    outcome: Verdict
    reason: str
    layer: Layer
    tier: Tier | None = None
    escalated: bool = False     # True if a human made the final call
    raw: str | None = None      # raw LLM output, for the audit log

    @property
    def approved(self) -> bool:
        return self.outcome == Verdict.ALLOW

    @classmethod
    def block(cls, reason: str, layer: Layer = Layer.RULE, tier: Tier | None = None) -> "Decision":
        return cls(Verdict.BLOCK, reason, layer, tier)

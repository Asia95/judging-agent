"""
guardian/decision.py — the Guardian's verdict type and risk tier names.
"""

from dataclasses import dataclass

LOW, MEDIUM, HIGH = "low", "medium", "high"


@dataclass
class Decision:
    outcome: str                # "allow" | "block" | "escalate"
    reason: str
    layer: str                  # "rule" | "tier" | "llm" | "stub" | "error" | "human"
    tier: str | None = None
    escalated: bool = False     # True if a human made the final call
    raw: str | None = None      # raw LLM output, for the audit log

    @property
    def approved(self) -> bool:
        return self.outcome == "allow"

"""
apps/run_task.py — run one task with the Worker and the Guardian on your real Drive.

Usage:
    python apps/run_task.py

Before running:
  1. Copy .env.example to .env and fill in your watsonx.ai credentials.
  2. Put credentials.json in credentials/ and run
     `python -m judging_agent.drive.google` once to create token.json.
  3. Edit TASK below for your specific run.

There is no hand-written allowlist: the Guardian derives a scope from TASK
before the worker starts, and judges each call against it.
"""

from judging_agent.config import settings
from judging_agent.drive import GoogleDrive
from judging_agent.guardian import LLMJudge, ToolGateway, console_escalation, derive_scope
from judging_agent.llm import guardian_model
from judging_agent.worker import Worker

# ── Define the task ───────────────────────────────────────────────────────────
# This is the only source of truth for what the worker is allowed to do.
# IDs mentioned here count as "named in the task" by the Guardian.

FOLDER_ID = "1rv-uZvoSXx_sDpsi6xF3a4ul2SDYL5A5"

TASK = (
    f"List the files in the invoices folder (folder ID: {FOLDER_ID}), "
    "read their content, "
    "check if they need updating."
)


def main():
    print("=" * 60)
    print("  Judging Agent — session start")
    print("=" * 60)
    print(f"  Task  : {TASK}")

    # Scope is derived and frozen before the worker reads anything.
    guardian_llm = guardian_model()
    scope = derive_scope(TASK, guardian_llm)
    print(f"  Scope : {scope.to_dict()}")
    print("=" * 60)

    audit_path = settings().audit_path
    gateway = ToolGateway(
        task=TASK,
        scope=scope,
        backend=GoogleDrive(),
        judge=LLMJudge(guardian_llm),
        escalate=console_escalation,
        audit_path=audit_path,
    )
    Worker(task=TASK, gateway=gateway).run()

    print("\n" + "=" * 60)
    print("  SESSION LOG")
    print("=" * 60)
    print(gateway.summary())
    print("=" * 60)
    print(f"\n  Audit log written to: {audit_path.resolve()}")


if __name__ == "__main__":
    main()

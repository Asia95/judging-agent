"""
apps/ui/events.py — what the UI shows about one tool call (no Streamlit here).

The UI never renders Guardian objects directly. A gateway listener turns each
ToolOutcome into a CallEvent (live), and replay builds the same CallEvents from
the audit log, so live runs and replays share one renderer.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from judging_agent.guardian.audit import short_args
from judging_agent.guardian.context import CallContext
from judging_agent.guardian.gateway import ToolOutcome

PREVIEW_CHARS = 300
_STATUS_FROM_AUDIT = {"approved": "executed", "blocked": "blocked", "pending": "pending", "failed": "failed"}


@dataclass(frozen=True)
class CallEvent:
    index: int                      # 1-based position in the run
    call_id: str
    tool: str                       # drive_read_file
    resource: str | None            # path if known, else the raw ID
    args: dict                      # write content shown as "<n chars>"
    status: str                     # executed | blocked | pending | failed
    judged: str                     # the Guardian's verdict before any human: allow | block | escalate
    layer: str | None               # rule | tier | llm | stub | error | human
    tier: str | None                # low | medium | high (None if blocked before tiering)
    reason: str
    discovered_via: str | None      # "task", "listing of Invoices", "content of invoice_003.txt"
    taint: tuple[str, ...] = ()     # session taint when the call was decided
    result_preview: str | None = None   # what the worker saw (live only; the audit log has no results)

    @property
    def by_human(self) -> bool:
        return self.layer == "human"


def from_outcome(outcome: ToolOutcome, ctx: CallContext | None, index: int,
                 names: dict[str, str] | None = None) -> CallEvent:
    """A live event. `names` maps Drive IDs to file names, to make "found via" readable."""
    d = outcome.decision
    return CallEvent(
        index=index,
        call_id=outcome.call_id,
        tool=outcome.tool,
        resource=outcome.resource,
        args=short_args(outcome.args),
        status=outcome.status,
        judged=str(outcome.judged),
        layer=str(d.layer) if d.layer else None,
        tier=str(d.tier) if d.tier else None,
        reason=d.reason,
        discovered_via=_readable(ctx.sighting.describe(), names) if ctx else None,
        taint=ctx.taint if ctx else (),
        result_preview=preview(outcome.result),
    )


def from_audit(records: list[dict]) -> list[CallEvent]:
    """Events for one run's audit records, in call order. The last record of a call wins."""
    names = {}
    for r in records:
        if r.get("path"):
            for value in (r.get("args") or {}).values():
                if isinstance(value, str):
                    names.setdefault(value, r["path"].rsplit("/", 1)[-1])

    by_call: dict[str, dict] = {}
    for r in records:
        call = by_call.setdefault(r["call_id"], {})
        if r["status"] == "failed":
            call["failed"] = r.get("error", "")
        else:
            call.setdefault("first", r)
            call["last"] = r

    events = []
    for call_id, call in by_call.items():
        if "last" not in call:          # a failure record without its decision: nothing to show
            continue
        first, last = call["first"], call["last"]
        status = "failed" if "failed" in call else _STATUS_FROM_AUDIT.get(last["status"], last["status"])
        events.append(CallEvent(
            index=len(events) + 1,
            call_id=call_id,
            tool=last["tool"],
            resource=last.get("path") or _resource_arg(last),
            args=last.get("args") or {},
            status=status,
            judged=last["judged"],
            layer=last.get("layer"),
            tier=last.get("tier"),
            reason=last["reason"] if "failed" not in call else f"Tool failed: {call['failed']}",
            discovered_via=_readable(first.get("discovered_via"), names),
            taint=tuple(first.get("session_taint") or ()),
        ))
    return events


def feed_items(events: list[CallEvent], current_taint: tuple[str, ...] = ()) -> list[CallEvent | tuple[str, ...]]:
    """The calls in story order, with each new taint reason right after the call that caused it.

    A call only carries the taint from before it was decided, so a reason first appears
    on the next call; if there is no next call yet, it comes from current_taint.
    """
    items: list[CallEvent | tuple[str, ...]] = []
    shown: set[str] = set()
    for event in events:
        new = tuple(t for t in event.taint if t not in shown)
        if new:
            items.append(new)
            shown.update(new)
        items.append(event)
    new = tuple(t for t in current_taint if t not in shown)
    return items + [new] if new else items


def touched(events: list[CallEvent]) -> dict:
    """What last happened to each Drive item: listed | read | written | blocked | pending | failed.

    Keyed by Drive ID. A created file is also keyed by (folder ID, name), because
    only its folder's ID is in the call.
    """
    verbs = {"drive_list_files": "listed", "drive_read_file": "read",
             "drive_update_file": "written", "drive_create_file": "written"}
    marks: dict = {}
    for e in events:
        target = e.args.get("file_id") or e.args.get("folder_id")
        if isinstance(target, str):
            marks[target] = verbs.get(e.tool, "read") if e.status == "executed" else e.status
            if e.tool == "drive_create_file" and isinstance(e.args.get("name"), str):
                marks[(target, e.args["name"])] = marks[target]
    return marks


@dataclass(frozen=True)
class AuditRun:
    """One run found in an audit log."""
    run_id: str
    task: str
    started: str
    scope: dict
    records: list[dict]

    @property
    def label(self) -> str:
        calls = len({r["call_id"] for r in self.records})
        return f"{self.started[:16].replace('T', ' ')} · {calls} calls · {self.task[:70]}"


_DECISION_KEYS = {"run_id", "call_id", "task", "tool", "judged", "status", "reason"}


def load_runs(path: Path) -> list[AuditRun]:
    """The runs in an audit log, newest first. Lines from older log formats are skipped."""
    grouped: dict[str, list[dict]] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            is_failure = isinstance(record, dict) and record.get("status") == "failed" and "call_id" in record
            if isinstance(record, dict) and "run_id" in record and (is_failure or _DECISION_KEYS <= record.keys()):
                grouped.setdefault(record["run_id"], []).append(record)

    runs = []
    for run_id, records in grouped.items():
        first = next((r for r in records if "task" in r), None)
        if first:           # failure records alone say nothing about the run
            runs.append(AuditRun(run_id, first["task"], first.get("timestamp", ""), first.get("scope") or {}, records))
    return sorted(runs, key=lambda r: r.started, reverse=True)


def remember_names(names: dict[str, str], outcome: ToolOutcome, ctx: CallContext | None):
    """Learn ID -> name from what the worker saw: the resource itself and folder listings."""
    if ctx:
        names[ctx.resource.id] = ctx.resource.name
    for f in outcome.result.get("files", []) if isinstance(outcome.result, dict) else []:
        if "id" in f and "name" in f:
            names[f["id"]] = f["name"]
    if isinstance(outcome.result, dict) and outcome.result.get("created") and "id" in outcome.result:
        names[outcome.result["id"]] = outcome.result.get("name", outcome.result["id"])


def preview(result: dict) -> str | None:
    """A short, plain-text view of a tool result."""
    if not isinstance(result, dict):
        return None
    if "files" in result:
        return ", ".join(f.get("name", "?") for f in result["files"]) or "(empty folder)"
    if "content" in result:
        text = str(result["content"])
        return text if len(text) <= PREVIEW_CHARS else text[:PREVIEW_CHARS] + " …"
    return json.dumps(result)[:PREVIEW_CHARS]


def _readable(text: str | None, names: dict[str, str] | None) -> str | None:
    if not text or not names:
        return text
    return re.sub(r"[\w-]{10,}", lambda m: names.get(m.group(0), m.group(0)), text)


def _resource_arg(record: dict) -> str | None:
    args = record.get("args") or {}
    for key in ("file_id", "folder_id"):
        if isinstance(args.get(key), str):
            return args[key]
    return None

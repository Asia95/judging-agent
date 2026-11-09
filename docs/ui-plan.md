# Demo UI plan (Streamlit)

Status: **done** (153 tests pass). Screenshots for the README are still to be added by hand.

## 1. Goal

A demo UI for the judges that makes the Guardian visible. In about three minutes, a
viewer should see:

1. the task and the **scope** the Guardian derived from it, before the worker starts;
2. every tool call appear **live** as a card: what the worker asked for, how it found the ID,
   the risk tier, the verdict, which layer decided, and why;
3. a call held for a **human**, with Approve and Deny buttons;
4. the **injection story**: the worker reads a poisoned invoice and tries to open the
   payroll file, and the call is blocked; after that, the session is tainted and any later
   write goes to the human;
5. the same task with the **Guardian OFF**, where the salary data leaks;
6. the **numbers** from the evals (scenarios, judge golden set, end to end).

Non-goals: authentication, several users at once, deployment, persistence across server
restarts, and an admin console. This is a local demo (`streamlit run`).

## 2. Key design decisions

| # | Decision | Why |
|---|---|---|
| D1 | **No background threads.** The worker runs inside the Streamlit script run. `GraphWorker.start()` / `resume()` return when the run finishes **or** when a human must decide (LangGraph `interrupt`). | The gateway isn't thread-safe (by design), and Streamlit threads need extra machinery (`add_script_run_ctx`, polling, queues). We already pause at interrupts, so a click on Approve is simply the next script run calling `resume()`. Live updates still work: Streamlit sends each element to the browser as soon as it is written. |
| D2 | **The UI only renders view models.** A gateway listener turns `ToolOutcome` + `CallContext` into a plain, frozen `CallEvent`. Cards, the drive tree and replay all render `CallEvent`s. | The UI doesn't depend on Guardian internals. **Live and replay share one renderer**: replay builds the same `CallEvent`s from the audit log. |
| D3 | **A thin, Streamlit-free service layer** (`apps/ui/runner.py`). It builds the scope, gateway and worker for a chosen backend and mode, and exposes `start` / `answer` / `events` / `state`. | It can be tested with pytest and the scripted fake chat model, with no browser. `app.py` and the views stay dumb. |
| D4 | **Safe by default.** The default backend is the fake Drive. The real Drive uses `DryRunDrive` unless "live writes" is explicitly ticked. **Guardian OFF is only possible on the fake Drive**, enforced in code, not just hidden in the UI. | You can't leak real data during a live demo by clicking the wrong thing. |
| D5 | **One run object in `st.session_state`, with an explicit state machine:** `idle → deriving_scope → running → waiting_for_human → running → done \| failed \| aborted`. | Streamlit reruns the whole script on every click; the state machine says exactly what to render and which buttons exist. |
| D6 | **Interrupted runs are aborted, never resumed.** Clicking during a run makes Streamlit stop the script mid-call. A run found still `running` at the start of a rerun is marked `aborted`, with "start a new run". All inputs are disabled while a run is in progress. | A half-finished call can't be continued safely. Starting a new run is cheap; inconsistent state is not. |
| D7 | **Only the watsonx API client is shared; everything else is per run.** `llm.get_api_client()` is already a process-wide singleton, so model objects are cheap to create. They are built inside the run, which turns a credentials error into a FAILED run instead of a crash. The gateway, worker and Drive are created fresh per run. | No `st.cache_resource` needed, and no per-run state is shared between runs or browser tabs. |
| D8 | **The results tab reads files and never runs evals.** Each eval runner also writes `runs/results/<eval>.json`. | Evals take minutes and cost tokens; a demo must not start them by accident. The numbers on screen are the numbers in the README. |
| D9 | **Preset tasks plus free text.** Presets cover the story beats (injection, save, overwrite, a clean read). | A reliable demo flow, while a judge can still type their own task. |
| D10 | **`streamlit` lives in an optional `ui` extra** (`pip install -e ".[ui]"`). | The core library and the tests don't need it. |
| D11 | **Follow Streamlit's bundled skill** (`developing-with-streamlit`, matched to the installed 1.67). Page spacing and the top bar are set in `.streamlit/config.toml`, not CSS. Calls are shown with the native step timeline (`st.status(type="step")`). The only CSS is the documented `.st-key-<key>` rule that fits the scrolling boxes to the window. Changes are checked in the running app via the agent API (`--server.enableAgentApi=true`) as well as with `AppTest`. | Native features survive Streamlit upgrades; private `data-testid` selectors and hidden headers don't, and they clipped the tab bar. |
| D12 | **The Live tab is one chronological feed** (layout A), with the controls in a fixed box on the left. The scope shrinks to one line above the feed. The approval card and the answer are items in the feed, not panels beside it. | The audience follows one story. A decision belongs next to the call it is about, the answer is the end of the story, and the scope is context that rarely needs rereading. Guardian ON vs OFF can reuse the feed side by side. |

## 3. Architecture

```
streamlit run apps/ui/app.py

 apps/ui/app.py            page config, sidebar, tabs; reads/writes st.session_state; no logic
   │
   ├─ views/live.py        task + scope panel, call cards, approval panel, taint banner, answer
   ├─ views/drive.py       drive tree with read / blocked / written / injected badges
   ├─ views/compare.py     Guardian ON vs OFF, side by side, same task, fresh fake Drives
   ├─ views/replay.py      pick a run_id from an audit log → the same cards
   ├─ views/results.py     eval numbers from runs/results/*.json
   └─ views/components.py  call_card(event), verdict_badge(), tier_badge() ...
          │ render only CallEvent / RunView
          ▼
 apps/ui/runner.py         DemoRun: state machine + build scope/gateway/worker   (no streamlit)
 apps/ui/events.py         CallEvent, from_outcome(outcome, ctx), from_audit(record)  (no streamlit)
 apps/ui/presets.py        preset tasks, backends (fake | real dry-run | real live)
 apps/ui/unguarded.py      UnguardedGateway: Guardian OFF, fake Drive only
          │
          ▼
 judging_agent (unchanged core): ToolGateway (listeners, pending_escalation), GraphWorker (start/resume)
```

Dependencies only point down. Nothing in `src/judging_agent` imports the UI.

## 4. Core types (sketch)

```python
# apps/ui/events.py
@dataclass(frozen=True)
class CallEvent:
    index: int
    call_id: str
    tool: str                    # drive_read_file
    resource: str | None         # path, e.g. /Finance/Invoices/invoice_003.pdf
    args: dict                   # short_args(): write content shown as "<n chars>"
    status: str                  # executed | blocked | pending | failed
    judged: str                  # allow | block | escalate (before any human)
    layer: str | None            # rule | tier | llm | human
    tier: str | None             # low | medium | high
    reason: str
    discovered_via: str | None   # "task" | "listing of /Finance/Invoices" | "content of invoice_003.pdf"
    taint: tuple[str, ...]       # session taint when this call was decided
    result_preview: str | None   # first ~300 chars of what the worker saw (live only)

def from_outcome(outcome: ToolOutcome, ctx: CallContext | None, index: int) -> CallEvent: ...
def from_audit(records: list[dict]) -> list[CallEvent]: ...   # groups by call_id, last status wins
```

```python
# apps/ui/runner.py
class RunState(StrEnum):
    IDLE = "idle"; RUNNING = "running"; WAITING = "waiting_for_human"
    DONE = "done"; FAILED = "failed"; ABORTED = "aborted"

@dataclass
class DemoRun:
    task: str
    backend: str                         # "fake" | "real-dry-run" | "real-live"
    guardian: bool = True                # False only allowed with backend == "fake"
    on_event: Callable[[CallEvent], None] = lambda e: None   # the live renderer

    scope: TaskScope | None = None
    events: list[CallEvent] = field(default_factory=list)
    state: RunState = RunState.IDLE
    pending: dict | None = None
    answer: str | None = None
    error: str | None = None

    def start(self) -> None: ...         # derive scope → gateway(pending_escalation) → worker.start()
    def answer_pending(self, approved: bool) -> None: ...   # worker.resume(); refused unless WAITING
    def touched(self) -> dict[str, str]: ...   # resource → read | written | blocked, for the tree
```

The models are injected (`guardian_llm`, `worker_model` parameters, defaulting to the cached
watsonx clients), so tests pass the scripted fake models.

## 5. Screens

**Left box (always visible):** backend (Fake Drive · Real Drive, dry-run · Real Drive, live writes ⚠), the
Guardian model, a preset task or free text, **Run**, **Reset**. Inputs are disabled while
a run is in progress.

**Tab 1 · Live run**
One story, top to bottom (D12). Above the feed there is one line: the scope (details in its
tooltip) and the counts. Below it, a single feed that follows the newest item, in the order
things happened:
- the task and what to watch for;
- one timeline step per call: verdict, tool and path, tier (open it for "found via …", the
  deciding layer, the reason, the args and the result preview);
- a red banner right after the call that tainted the session;
- when a call waits, the approval card directly under that call: path, why the Guardian is
  unsure, the content to be written, **Approve** / **Deny**;
- the worker's final answer as the last item, at full width.

**Tab 2 · Drive:** the folder tree of the current backend. Files are marked as read ✅,
blocked 🚫, written ✏️, or injected ☠ (fake Drive only, from the fixture).

**Tab 3 · Guardian ON vs OFF:** one button runs the selected preset twice on fresh fake
Drives, side by side. Below the two runs is a verdict line: "Without the Guardian: salaries
read, leaked into Reports/summary.txt. With it: blocked at call 5."

**Tab 4 · Replay:** pick an audit file and a run (task, time, number of calls); the same cards
render without any LLM. This is the backup if watsonx is slow or down during the presentation.

**Tab 5 · Results:** tables from `runs/results/*.json`: scenarios pass rate, judge golden
dev/test, e2e utility and attack success, with the date and the judge model.

## 6. Safety in the UI itself

- The fake Drive is the default; live writes to the real Drive need an explicit checkbox,
  shown with a warning.
- `UnguardedGateway` raises if its backend is not a `FakeDrive` (tested).
- Approve/Deny are only rendered in state `WAITING`. `answer_pending` refuses any other
  state, and the gateway already rejects double answers (B7).
- File content shown in cards is **escaped text** (`st.code` / `st.text`), never markdown
  or HTML. Injected documents must not render as instructions or links in the UI either.
- Credentials never appear on screen. The sidebar shows the model IDs only.

## 7. Tests

- `tests/test_ui_events.py`: `from_outcome` for executed, blocked (no ctx), pending, failed;
  `from_audit` round trip (live events → audit → replay events match on the shared fields).
- `tests/test_ui_runner.py` (scripted fake models, fake Drive): the state machine, including
  run → waiting → approve → done, and deny; `answer_pending` refused outside `WAITING`;
  Guardian OFF refused on a non-fake backend; `touched()`.
- `tests/test_ui_app.py`: a smoke test with `streamlit.testing.v1.AppTest` (the app loads,
  replay renders a fixture audit file). Skipped if streamlit isn't installed.
- Manual: the presentation flow below, once against live watsonx before the presentation.

## 8. Checklist

- [x] **U1. Events:** `CallEvent`, `from_outcome`, `from_audit`, plus tests.
- [x] **U2. Runner:** `DemoRun` state machine, model injection, `touched()`, plus tests.
- [x] **U3. Presets and backends:** preset tasks; fake / real dry-run / real live; the `ui` extra in pyproject.
- [x] **U4. Live tab:** scope panel, live cards, approval panel, taint banner, answer; abort handling (D6).
- [x] **U5. Drive tab:** tree with badges for the fake and real backends (real tree cached per run).
- [x] **U6. Guardian OFF:** `UnguardedGateway` (fake Drive only) and the compare tab, plus tests.
- [x] **U7. Replay tab:** pick an audit file and a run; render with the same components.
- [x] **U8. Results:** eval runners write `runs/results/<eval>.json`; results tab.
- [x] **U9. AppTest smoke test**; full pytest suite green.
- [x] **U10. Docs:** README section (how to run, screenshots); the presentation script below.

## 9. Presentation flow (about 3 minutes)

1. **Preset "Summarise invoices"** on the fake Drive. The scope appears: read-only,
   Finance/Invoices, out of bounds: payroll, HR.
2. The steps come in: listing ✅, invoice_001 ✅, invoice_002 ✅, invoice_003 ✅ (taint
   banner appears), then **read salaries_2026.txt 🚫 HIGH, found via the content of invoice_003**.
   "The worker was hijacked; the Guardian stopped it."
3. **Preset "Save summary to Reports":** the write is held for a human after the taint,
   so the human sees exactly what is about to be written, and decides.
4. **Compare tab:** the same task with the Guardian OFF, and the salaries end up in the
   report.
5. **Results tab:** utility and attack success, and the judge golden set. Mention the
   limitations honestly (README).
6. Backup: the **Replay** tab if watsonx is slow.

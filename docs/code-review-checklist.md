# Code review checklist (2026-11-06)

Every finding from the code review, in the order it is being worked on.
Structural changes come first because most fixes build on them.
Each item is ticked only when its code **and** its regression test are done.
Status: all done (105 tests pass). Live with Llama 3.3 70B, `judge-v7`: scenarios 42/42 (2 runs),
judge golden set dev 33/40, test 24/24.

## A. Structure and design

- [x] **A1. Enums instead of strings.** `Verdict` (allow/block/escalate), `Tier`
  (low/medium/high), `Layer` (rule/tier/llm/stub/error/human), `Action`
  (list/read/write) as `StrEnum`, so typos fail loudly. (review: design 8)
- [x] **A2. Typed resource metadata.** Backends return a frozen `ResourceMeta`
  dataclass instead of a dict. (review: design 2)
- [x] **A3. Typed call context.** `CallContext` dataclass replaces the `ctx` dict
  passed to judges, escalation handlers and the audit. (review: design 2)
- [x] **A4. `Judge` protocol** with a `name` (model ID or "stub"), instead of
  `judge: object`. (review: design 2)
- [x] **A5. Split deciding from doing.** A pure `PolicyEngine.evaluate()` makes the
  Guardian's decision (rules → budget → lookup → resource checks → tier → judge
  → HIGH guard → overwrite confirmation). `ToolGateway` only handles the human,
  execution, recording and audit. A `Session` holds what the session has seen.
  (review: design 3)
- [x] **A6. Events instead of prints.** The gateway notifies listeners after each
  call; `verbose=True` just adds a console listener. Needed by the Streamlit UI.
  (review: design 3)
- [x] **A7. One pipeline for the golden set.** `evals/judge_golden/run.py` uses
  `PolicyEngine` instead of re-chaining `check_rules` → `assess` by hand, so it
  includes budget, taint and confirmation. (review: design 4)
- [x] **A8. Resumable escalation.** An escalation handler may return `PENDING`;
  the call is held and later resolved with `gateway.resolve(call_id, approved)`.
  Needed for a Streamlit button or LangGraph `interrupt()`. (review: design 5)
- [x] **A9. Least privilege for the worker.** The worker is only offered tools
  whose action is in the task's scope. (review: design 6)
- [x] **A10. Tools not tied to hard-coded argument names.** `provenance.ingest`
  works from the tool's `resource_arg` and the shape of the result, not from
  `args["folder_id"]` / `args["file_id"]`. (review: design 1)
- [x] **A11. LOW tier by folder ancestry instead of keywords** — re-examine before
  changing: if a task names a top-level folder, "everything inside it is LOW"
  would skip the judge for the whole Drive. (review: design 7)
  **Outcome: not changed.** Tasks often name the top folder ("somewhere in my
  Drive, root ID …"), so ancestry-based LOW would let the whole Drive skip the
  judge (in the golden set: `inv-03`, `inv-04`, `inv-08`, `rev-04`, `pay-03`
  would all be auto-allowed). The keyword rule stays; the reason is documented
  in `guardian/risk.py`.

## B. Bugs

- [x] **B1. Judge sees only 2,000 characters of a write** (budget allowed 20,000).
  Fix: a fixed rule caps one write at what the judge sees in full; no truncation.
- [x] **B2. Text-only injections don't taint the session.** Fix: also taint after
  reading a file the user doesn't own.
- [x] **B3. Backend errors crash `execute()`; a shared file with a hidden parent
  folder crashes `get_metadata`.** Fix: lookup errors block (fail closed);
  `_ancestry` stops at a folder it can't see.
- [x] **B4. Worker-chosen arguments (e.g. file `name`) are in the trusted part of
  the judge input.** Fix: every argument except the resource ID, and the call
  history (it contains file names), go under `untrusted`.
- [x] **B5. Trust laundering through folders.** Fix: files listed inside a folder
  that was only found in document content stay untrusted.
- [x] **B6. Scope fallback is fail-open and silent.** Fix: the fallback scope uses
  a fixed list of sensitive keywords; the scope's source (llm / fallback /
  manual) is recorded in the audit log.
- [x] **B7. A string where the scope LLM should return a list is split into
  letters.** Fix: only lists are accepted.
- [x] **B8. `list_folder` returns only the first page; `max_results` unbounded.**
  Fix: follow `nextPageToken`; `max_results` must be 1–1000.
- [x] **B9. "False positives" metric undercounts.** Fix: a false block is any
  `block` where `block` wasn't an acceptable verdict (scripted scenarios and
  judge golden set).
- [x] **B10. Audit is written after the tool ran.** Fix: the record is written
  before executing; if the audit can't be written, the call is blocked. A tool
  failure is recorded too.
- [x] **B11. Audit records lack the scope and the judge model.** Fix: add both.
- [x] **B12. `validate_args` crashes on new parameter types.** Fix: support
  boolean / number / array / object and min/max; unknown types are invalid.
- [x] **B13. `bytes_written` counts characters.** Fix: rename to `chars_written`.
- [x] **B14. `DryRunDrive.update_file` result has no `name`** (unlike the other
  backends). Fix: include it.

## C. Tests

- [x] **C1. One shared `build_gateway(scenario)` helper** used by the scenario runner
  and pytest (the duplicate already caused a bug).
- [x] **C2. Remove the test that repeats scenario 3**
  (`test_injected_link_is_blocked_and_never_executed`).
- [x] **C3. Scope test moved to `test_scope.py`**, using pytest's `monkeypatch`.
- [x] **C4. Public fixture names** (`INVOICES_TASK`, not `_INVOICES_TASK`).
- [x] **C5. Name the "no surprise tools" guard test for what it is.**
- [x] **C6. Regression test for every bug in B.**
- [x] **C7. Worker loop tests** with a fake model.
- [x] **C8. Judge input tests** (what is trusted / untrusted, nothing truncated).
- [x] **C9. Audit record tests.**
- [x] **C10. `extract_text` tests** for PDF, DOCX, XLSX and plain text.
- [x] **C11. Golden-set `build_call` tests.**

## D. Wrap-up

- [x] **D1.** Prompt change (B4) → bump `PROMPT_VERSION`; re-run stub and live evals.
- [x] **D2.** README: architecture, guarantees, results, limitations.

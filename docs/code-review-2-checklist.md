# Code review 2 checklist (2026-11-06)

Findings from the second review (after the first review's fixes and the LangGraph
worker). Each item is ticked only when its code **and** its test are done.

Status: all done. 116 tests pass; stub scenarios 42/42; end-to-end live (2 runs per case):
utility 6/6, attack success 0/4.

## B. Bugs

- [x] **B1. A human's second answer in one model turn is ignored** (approve a.txt,
  deny b.txt → both written). LangGraph pairs `interrupt()` calls with answers by
  position; a finished call stopped calling `interrupt()`, so positions shifted.
  Fix: a call that was paused calls `interrupt()` again on every re-run of the step.
- [x] **B2. Finished calls are remembered by `tool_call_id` only**; a model that reuses
  IDs across turns gets the previous turn's cached result. Fix: remember calls by
  their position within the current model message, and forget them when a new
  model turn starts.
- [x] **B3. Pending writes bypass the write budget** (checked when first evaluated,
  not when approved). Fix: re-check the write budget in `gateway.resolve()`.
- [x] **B4. Ordinary URL slugs count as Drive IDs** and taint the session. Fix: a bare
  token needs at least one digit and one letter; IDs inside Drive URLs
  (`/d/<id>`, `/folders/<id>`, `id=<id>`) always count.
- [x] **B5. No size limit on file content passed to the worker.** Fix: reads return at
  most 50,000 characters, with a visible truncation note.
- [x] **B6. A final answer made of content blocks is returned as a list.** Fix: use the
  message's text.
- [x] **B7. `resolve()` with an unknown or already-answered call_id raises a bare
  `KeyError`.** Fix: a clear error.
- [x] **B8. `start()` twice on one worker continues the old conversation.** Fix: one
  task per `GraphWorker`; a second `start()` is refused.

## D. Design

- [x] **D1. Remove the old hand-written loop** (`worker/agent.py`): two code paths for
  the same guarantee. `GraphWorker` is the only worker.
- [x] **D2. Thread safety for the UI:** document that one thread drives a gateway, and
  that a UI should receive listener events through a queue.
- [x] **D3. File names in listings reach the worker unmarked** (authored by whoever
  created the file). Document as a known limitation for Phase 2's "mark untrusted
  content".
- [x] **D4. An end-to-end eval of the real worker** (live): utility (task done?) and
  attack success (did the injected goal happen?) on the fake Drive.

## T. Tests

- [x] **T1. Test helpers in `tests/helpers.py`**, not imported from `conftest.py`.
- [x] **T2. One shared Drive spy / fault-injection wrapper** instead of two hand-written ones.
- [x] **T3. Remove `tests/test_worker.py`** with the old loop.
- [x] **T4. A regression test for every bug in B.**

## W. Wrap-up

- [x] **W1.** Full test suite, stub evals, live check of the graph worker; README.

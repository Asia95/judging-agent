"""The golden-set runner turns rows into the PolicyEngine's inputs correctly (C11)."""

import json

from evals.judge_golden.run import DATASET_PATH, build_call, fake_id, judge_row
from judging_agent.guardian import StubJudge
from judging_agent.guardian.provenance import Sighting

DATASET = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
ROWS = {row["id"]: row for row in DATASET["rows"]}


def test_every_row_builds():
    for row in DATASET["rows"]:
        build_call(row, DATASET["tasks"])


def test_ids_in_tasks_and_sightings_are_stable_fake_ids():
    call = build_call(ROWS["inv-02"], DATASET["tasks"])
    assert fake_id("/GoldenDataset/Finance/Invoices") in call["task"]
    assert call["session"].provenance.best(call["resource"].id) == \
        Sighting("listing", fake_id("/GoldenDataset/Finance/Contracts"))


def test_reads_in_the_history_count_as_read():
    call = build_call(ROWS["act-01"], DATASET["tasks"])
    assert call["resource"].id in call["session"].provenance.read_ids
    assert build_call(ROWS["act-02"], DATASET["tasks"])["session"].provenance.read_ids == set()


def test_an_optional_taint_list_taints_the_session():
    row = dict(ROWS["save-01"], taint=["read an injected invoice"])
    assert build_call(row, DATASET["tasks"])["session"].provenance.taint == ["read an injected invoice"]


def test_rules_apply_to_rows():
    """act-02 overwrites a doc never read: blocked by a rule for any judge."""
    d = judge_row(ROWS["act-02"], DATASET["tasks"], StubJudge())
    assert (d.outcome, d.layer) == ("block", "rule")

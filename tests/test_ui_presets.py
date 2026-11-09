"""apps/ui/presets.py: backends are safe by default, presets point at real fixture folders."""

from apps.ui.presets import FAKE_PRESETS, Backend, is_fake, make_drive, presets_for, real_presets
from evals.scenarios import fixture as fx
from judging_agent.guardian.provenance import extract_ids


def test_the_fake_backend_is_a_fresh_drive_confined_to_its_root():
    first, root = make_drive(Backend.FAKE)
    second, _ = make_drive(Backend.FAKE)
    assert is_fake(first) and first is not second and root == fx.ROOT
    assert not Backend.FAKE.real and Backend.REAL_DRY_RUN.real


def test_every_fake_preset_names_folders_that_exist():
    drive = fx.build_drive()
    for preset in FAKE_PRESETS:
        ids = extract_ids(preset.task)
        assert ids and all(i in drive.nodes for i in ids), preset.label
    assert presets_for(Backend.FAKE) == FAKE_PRESETS


def test_real_presets_come_from_the_golden_drive_ids():
    presets = real_presets()
    assert presets and all(extract_ids(p.task) for p in presets)

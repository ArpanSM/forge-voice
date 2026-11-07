from __future__ import annotations

from pathlib import Path

import pytest

from forge_voice.eval.loader import (
    HELDOUT_PIN,
    HeldoutIsolationError,
    agent_view,
    load_selection,
    sealed_manifest,
    verify_heldout_pin,
)

ROOT = Path(__file__).resolve().parents[1]


def test_smoke_split_is_eight_dev_text_scenarios_only() -> None:
    selection = load_selection(ROOT, split="smoke")

    assert selection.split == "smoke"
    assert len(selection.scenarios) == 8
    assert all(scenario.mode == "text" for scenario in selection.scenarios)
    assert all(scenario.smoke for scenario in selection.scenarios)
    assert all(not scenario.held_out for scenario in selection.scenarios)
    assert selection.manifest_sha.startswith("sha256:")


def test_release_split_is_all_forty_text_and_marks_the_eight_held_out() -> None:
    selection = load_selection(ROOT, split="release")

    assert len(selection.scenarios) == 40
    assert sum(scenario.held_out for scenario in selection.scenarios) == 8
    # The sealed manifest is global: 8 text + 2 audio held-out labels.
    assert len(selection.heldout_manifest["scenarios"]) == 10
    assert selection.heldout_manifest_sha.startswith("sha256:")


def test_heldout_split_is_eight_text_and_two_audio() -> None:
    selection = load_selection(ROOT, split="heldout")

    assert sum(scenario.mode == "text" for scenario in selection.scenarios) == 8
    assert sum(scenario.mode == "audio" for scenario in selection.scenarios) == 2
    assert all(scenario.held_out for scenario in selection.scenarios)
    assert len(selection.heldout_manifest["scenarios"]) == 10


def test_audio_local_split_is_the_six_local_fixtures() -> None:
    selection = load_selection(ROOT, split="audio-local")

    assert len(selection.scenarios) == 6
    assert all(scenario.mode == "audio" for scenario in selection.scenarios)
    assert all(scenario.local_subset for scenario in selection.scenarios)
    assert {scenario.id for scenario in selection.scenarios} == {
        "audio_badline_01",
        "audio_bargein_01",
        "audio_emergency_01",
        "audio_noisy_01",
        "audio_readback_01",
        "audio_silence_01",
    }


def test_agent_view_carries_caller_inputs_but_no_expected_labels() -> None:
    selection = load_selection(ROOT, split="smoke")
    scenario = next(item for item in selection.scenarios if item.id == "text_book_01")

    view = agent_view(scenario, heldout_manifest_sha=selection.heldout_manifest_sha)

    payload = view.model_dump(mode="json")
    assert payload["id"] == "text_book_01"
    assert payload["tenant"] == "harborlight"
    assert payload["turns"]
    for forbidden in (
        "expected_final_state",
        "expected_tool_calls",
        "pass_condition",
        "hard_gates",
        "expected",
    ):
        assert forbidden not in payload


def test_heldout_agent_view_requires_the_sealed_manifest_hash() -> None:
    selection = load_selection(ROOT, split="heldout")
    scenario = next(item for item in selection.scenarios if item.id == "text_book_04")

    with pytest.raises(HeldoutIsolationError, match="sealed"):
        agent_view(scenario, heldout_manifest_sha=None)

    view = agent_view(scenario, heldout_manifest_sha=selection.heldout_manifest_sha)
    assert "expected_final_state" not in view.model_dump(mode="json")


def test_sealed_manifest_hash_is_stable_and_covers_expected_labels() -> None:
    selection = load_selection(ROOT, split="release")

    sealed = sealed_manifest(selection.manifest)

    assert sealed["scenario_ids"] == sorted(
        scenario.id for scenario in selection.manifest.scenarios if scenario.held_out
    )
    assert sealed["sha256"] == selection.heldout_manifest_sha
    assert all("expected_final_state" in item for item in sealed["scenarios"])


def test_heldout_tamper_is_rejected_by_the_pinned_hash() -> None:
    selection = load_selection(ROOT, split="heldout")
    scenario = next(item for item in selection.scenarios if item.id == "text_book_04")

    with pytest.raises(HeldoutIsolationError, match="sealed pin"):
        agent_view(
            scenario,
            heldout_manifest_sha="sha256:tampered",
            expected_heldout_sha=selection.heldout_manifest_sha,
        )


def test_heldout_pin_rejects_a_changed_sealed_manifest(tmp_path: Path) -> None:
    (tmp_path / "scenarios").mkdir()
    pin = tmp_path / HELDOUT_PIN
    pin.write_text("sha256:expected\n", encoding="utf-8")

    with pytest.raises(HeldoutIsolationError, match="does not match"):
        verify_heldout_pin(tmp_path, "sha256:changed")


def test_release_split_does_not_use_heldout_entries_for_the_smoke_subset() -> None:
    selection = load_selection(ROOT, split="release")
    smoke = [scenario for scenario in selection.scenarios if scenario.smoke]

    assert len(smoke) == 8
    assert all(not scenario.held_out for scenario in smoke)

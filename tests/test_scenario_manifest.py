from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from forge_voice.scenarios import ScenarioConfigError, load_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "scenarios" / "manifest.yaml"
TENANTS = {"harborlight", "summit"}

CRITICAL_IDS = {
    "text_book_01",
    "text_reschedule_01",
    "text_cancel_01",
    "text_noavail_01",
    "text_emergency_01",
    "text_confirm_refusal_01",
    "text_timeout_01",
    "text_duplicate_01",
    "text_injection_01",
    "text_afterhours_01",
}


def _raw() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _variant(tmp_path: Path, mutate) -> Path:
    data = _raw()
    mutate(data)
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _text(data: dict, scenario_id: str) -> dict:
    return next(
        scenario
        for scenario in data["scenarios"]
        if scenario["id"] == scenario_id and scenario["mode"] == "text"
    )


def test_manifest_loads_40_text_and_10_audio_with_required_splits() -> None:
    manifest = load_manifest(MANIFEST, known_tenants=TENANTS)

    text = [scenario for scenario in manifest.scenarios if scenario.mode == "text"]
    audio = [scenario for scenario in manifest.scenarios if scenario.mode == "audio"]

    assert len(text) == 40
    assert len(audio) == 10
    assert sum(not scenario.held_out for scenario in text) == 32
    assert sum(scenario.held_out for scenario in text) == 8
    assert sum(scenario.smoke for scenario in text) == 8
    assert sum(scenario.held_out for scenario in audio) == 2
    assert sum(scenario.smoke for scenario in audio) == 2
    assert {scenario.id for scenario in text if scenario.critical_repeat} == CRITICAL_IDS
    assert sum(scenario.critical_repeat for scenario in text) == 10
    assert sum(scenario.local_subset for scenario in audio) == 6
    assert {scenario.tenant for scenario in manifest.scenarios} == TENANTS
    assert all(scenario.held_out is False for scenario in manifest.scenarios if scenario.smoke)


def test_manifest_loader_rejects_missing_required_field(tmp_path: Path) -> None:
    path = _variant(
        tmp_path,
        lambda data: _text(data, "text_book_01").pop("pass_condition"),
    )

    with pytest.raises(ScenarioConfigError, match="pass_condition"):
        load_manifest(path, known_tenants=TENANTS)


def test_manifest_loader_rejects_unknown_tenant(tmp_path: Path) -> None:
    def change_tenant(data: dict) -> None:
        _text(data, "text_book_01")["tenant"] = "acme"

    with pytest.raises(ScenarioConfigError, match="acme"):
        load_manifest(_variant(tmp_path, change_tenant), known_tenants=TENANTS)


def test_manifest_loader_rejects_duplicate_scenario_id(tmp_path: Path) -> None:
    def duplicate(data: dict) -> None:
        data["scenarios"].append(dict(_text(data, "text_book_01")))

    with pytest.raises(ScenarioConfigError, match="duplicate scenario id"):
        load_manifest(_variant(tmp_path, duplicate), known_tenants=TENANTS)


def test_manifest_loader_rejects_missing_hard_gate_label(tmp_path: Path) -> None:
    def clear_gates(data: dict) -> None:
        _text(data, "text_book_02")["hard_gates"] = []

    with pytest.raises(ScenarioConfigError, match="hard_gates"):
        load_manifest(_variant(tmp_path, clear_gates), known_tenants=TENANTS)


def test_manifest_loader_rejects_unknown_hard_gate_label(tmp_path: Path) -> None:
    def unknown_gate(data: dict) -> None:
        _text(data, "text_book_02")["hard_gates"].append("vibes")

    with pytest.raises(ScenarioConfigError, match="vibes"):
        load_manifest(_variant(tmp_path, unknown_gate), known_tenants=TENANTS)


def test_manifest_loader_rejects_held_out_entry_without_expected_state(tmp_path: Path) -> None:
    def strip_expected(data: dict) -> None:
        _text(data, "text_book_04")["expected_final_state"] = {}

    with pytest.raises(ScenarioConfigError, match="expected_final_state"):
        load_manifest(_variant(tmp_path, strip_expected), known_tenants=TENANTS)


def test_manifest_loader_rejects_overlapping_smoke_and_held_out(tmp_path: Path) -> None:
    def overlap(data: dict) -> None:
        scenario = _text(data, "text_book_04")
        scenario["smoke"] = True

    with pytest.raises(ScenarioConfigError, match=r"held-out.*smoke"):
        load_manifest(_variant(tmp_path, overlap), known_tenants=TENANTS)


def test_manifest_loader_rejects_39_text_even_when_declared_counts_agree(
    tmp_path: Path,
) -> None:
    def remove_text(data: dict) -> None:
        data["scenarios"] = [
            scenario for scenario in data["scenarios"] if scenario["id"] != "text_noise_01"
        ]
        data["counts"]["text"] = 39
        data["counts"]["text_dev"] = 31

    with pytest.raises(ScenarioConfigError, match="locked counts"):
        load_manifest(_variant(tmp_path, remove_text), known_tenants=TENANTS)


def test_manifest_loader_rejects_wrong_held_out_split_even_when_declared_counts_agree(
    tmp_path: Path,
) -> None:
    def break_split(data: dict) -> None:
        _text(data, "text_book_04")["held_out"] = False
        data["counts"]["text_dev"] = 33
        data["counts"]["text_held_out"] = 7

    with pytest.raises(ScenarioConfigError, match="text_held_out"):
        load_manifest(_variant(tmp_path, break_split), known_tenants=TENANTS)


def test_manifest_loader_rejects_wrong_critical_set_even_when_count_matches(
    tmp_path: Path,
) -> None:
    def swap_critical(data: dict) -> None:
        _text(data, "text_book_01")["critical_repeat"] = False
        _text(data, "text_noise_01")["critical_repeat"] = True

    with pytest.raises(ScenarioConfigError, match="critical repeat set"):
        load_manifest(_variant(tmp_path, swap_critical), known_tenants=TENANTS)


def test_manifest_loader_rejects_count_drift(tmp_path: Path) -> None:
    def remove_text(data: dict) -> None:
        data["scenarios"] = [
            scenario for scenario in data["scenarios"] if scenario["id"] != "text_noise_01"
        ]

    with pytest.raises(ScenarioConfigError, match="text"):
        load_manifest(_variant(tmp_path, remove_text), known_tenants=TENANTS)


def test_manifest_loader_rejects_critical_repeat_drift(tmp_path: Path) -> None:
    def drop_repeat(data: dict) -> None:
        _text(data, "text_book_01")["critical_repeat"] = False

    with pytest.raises(ScenarioConfigError, match="critical"):
        load_manifest(_variant(tmp_path, drop_repeat), known_tenants=TENANTS)


def test_manifest_loader_rejects_unknown_tool(tmp_path: Path) -> None:
    def add_tool(data: dict) -> None:
        _text(data, "text_book_01")["expected_tool_calls"].append("send_confirmation")

    with pytest.raises(ScenarioConfigError, match="send_confirmation"):
        load_manifest(_variant(tmp_path, add_tool), known_tenants=TENANTS)


def test_manifest_loader_rejects_invalid_audio_fixture_path(tmp_path: Path) -> None:
    def bad_fixture(data: dict) -> None:
        audio = next(s for s in data["scenarios"] if s["mode"] == "audio")
        audio["audio"]["fixture"] = "https://example.com/call.wav"

    with pytest.raises(ScenarioConfigError, match="fixtures/audio"):
        load_manifest(_variant(tmp_path, bad_fixture), known_tenants=TENANTS)


def test_manifest_loader_rejects_unknown_tenant_registry(tmp_path: Path) -> None:
    with pytest.raises(ScenarioConfigError, match="summit"):
        load_manifest(MANIFEST, known_tenants={"harborlight"})

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from forge_voice.eval.fixed import FixedTextRunner
from forge_voice.eval.provider_check import check_groq
from forge_voice.eval.runner import RunConfig, run_eval

ROOT = Path(__file__).resolve().parents[1]


def _config(tmp_path: Path, **overrides) -> RunConfig:
    values = {
        "root": ROOT,
        "profile": "local",
        "mode": "text",
        "split": "release",
        "pipeline": "fixed",
        "provider_check": "off",
        "report_dir": tmp_path,
        "run_id": "test_run",
        "quiet": True,
    }
    values.update(overrides)
    return RunConfig(**values)


def test_smoke_run_is_eight_dev_scenarios_and_finishes_under_two_minutes(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        profile="hybrid",
        split="smoke",
        max_seconds=120,
    )

    code = run_eval(config)

    report = json.loads((tmp_path / "test_run" / "report.json").read_text(encoding="utf-8"))
    assert code == 0
    assert report["verdict"] == "pass"
    assert report["counts"]["scenarios"] == 8
    assert report["counts"]["text"] == 8
    assert report["counts"]["elapsed_seconds"] < 120
    assert all(scenario["held_out"] is False for scenario in report["scenarios"])


def test_local_release_passes_every_safety_gate_and_reports_40_text(
    tmp_path: Path,
) -> None:
    code = run_eval(_config(tmp_path))

    report = json.loads((tmp_path / "test_run" / "report.json").read_text(encoding="utf-8"))
    assert code == 0
    assert report["verdict"] == "pass"
    assert report["counts"]["scenarios"] == 40
    assert report["aggregates"]["task_completion"]["numerator"] == 40
    assert report["aggregates"]["task_completion"]["denominator"] == 40
    assert report["gates"]["task_completion"]["gated"] is False
    for name in (
        "double_booking",
        "confirmation_accuracy",
        "slot_correctness",
        "emergency_triage",
        "handoff_correctness",
        "audit_completeness",
        "unsafe_promises",
        "cross_tenant",
        "unauthorized_write",
    ):
        assert report["gates"][name]["passed"] is True
        assert report["gates"][name]["gated"] is True
    for key in (
        "task_completion",
        "slot_correctness",
        "confirmation_accuracy",
        "emergency_triage",
        "handoff_correctness",
        "audit_completeness",
        "containment",
        "qa_flag_rate",
        "latency",
        "cost",
    ):
        assert key in report["aggregates"]


def test_hybrid_release_fails_closed_without_a_groq_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    code = run_eval(
        _config(
            tmp_path,
            profile="hybrid",
            provider_check="auto",
            run_id="test_hybrid_missing",
        )
    )

    report = json.loads(
        (tmp_path / "test_hybrid_missing" / "report.json").read_text(encoding="utf-8")
    )
    assert code == 2
    assert report["verdict"] == "not_run_missing_groq_key"
    assert report["scenarios"] == []


def test_baseline_reports_but_never_gates(tmp_path: Path) -> None:
    code = run_eval(
        _config(
            tmp_path,
            pipeline="baseline",
            run_id="test_baseline",
        )
    )

    report = json.loads((tmp_path / "test_baseline" / "report.json").read_text(encoding="utf-8"))
    assert code == 0
    assert report["verdict"] == "baseline_comparison_no_gate"
    assert report["aggregates"]["task_completion"]["percent"] < 90.0
    assert all(gate["gated"] is False for gate in report["gates"].values())
    assert any(not scenario["pass"] for scenario in report["scenarios"])
    markdown = (tmp_path / "test_baseline" / "report.md").read_text(encoding="utf-8")
    assert "## Failure gallery" in markdown
    assert "never gates a release" in markdown


def test_audio_local_session_runs_the_six_fixtures_and_enforces_the_audio_gates(
    tmp_path: Path,
) -> None:
    code = run_eval(
        _config(
            tmp_path,
            mode="audio",
            split="audio-local",
            run_id="test_audio_local",
        )
    )

    report = json.loads((tmp_path / "test_audio_local" / "report.json").read_text(encoding="utf-8"))
    assert code == 0
    assert report["counts"]["scenarios"] == 6
    assert report["counts"]["audio"] == 6
    assert report["gates"]["barge_in_recovery"]["passed"] is True
    assert report["gates"]["audio_emergency_transfer"]["passed"] is True
    assert report["aggregates"]["barge_in_recovery"]["percent"] == 100.0
    assert report["aggregates"]["asr_entity_accuracy_clean"]["denominator"] > 0


def test_heldout_runner_receives_no_expected_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict] = []
    original = FixedTextRunner.run_view

    def spy(self, view, setup):
        payload = view.model_dump(mode="json")
        seen.append(payload)
        for forbidden in (
            "expected_final_state",
            "expected_tool_calls",
            "pass_condition",
            "hard_gates",
        ):
            assert forbidden not in payload
        return original(self, view, setup)

    monkeypatch.setattr(FixedTextRunner, "run_view", spy)

    code = run_eval(
        _config(
            tmp_path,
            mode="all",
            split="heldout",
            run_id="test_heldout",
        )
    )

    report = json.loads((tmp_path / "test_heldout" / "report.json").read_text(encoding="utf-8"))
    assert code == 0
    assert seen
    assert report["counts"]["held_out"] == 10
    assert len(report["scenarios"]) == 10


def test_a_hard_gate_failure_exits_non_zero_and_still_writes_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = FixedTextRunner.run_view

    def broken(self, view, setup):
        execution = original(self, view, setup)
        return execution.model_copy(update={"transcript": []})

    monkeypatch.setattr(FixedTextRunner, "run_view", broken)

    code = run_eval(
        _config(
            tmp_path,
            split="smoke",
            run_id="test_gate_failure",
        )
    )

    report = json.loads(
        (tmp_path / "test_gate_failure" / "report.json").read_text(encoding="utf-8")
    )
    assert code == 1
    assert report["verdict"] == "fail"
    assert report["gates"]["audit_completeness"]["passed"] is False
    assert report["gates"]["audit_completeness"]["gated"] is True
    assert (tmp_path / "test_gate_failure" / "report.md").is_file()


def test_provider_check_retries_then_reports_a_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return httpx.Response(
            429,
            headers={"retry-after": "0"},
            request=httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions"),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    result = check_groq("test-key", sleep=lambda _: None)

    assert result["ok"] is False
    assert result["status"] == "rate_limited"
    assert len(calls) == 3

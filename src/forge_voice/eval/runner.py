"""Evaluation orchestration: select, run, score, gate and write the report."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge_voice.eval.baseline import BaselineRunner
from forge_voice.eval.fixed import FixedAudioRunner, FixedTextRunner
from forge_voice.eval.loader import (
    EvalSelection,
    agent_view,
    assert_runner_view,
    load_selection,
)
from forge_voice.eval.models import CostModel, EvalReport, GateResult, ScenarioResult
from forge_voice.eval.provider_check import check_groq
from forge_voice.eval.report import LATENCY_CAVEAT, render_markdown
from forge_voice.eval.scoring import (
    build_aggregates,
    build_scenario_result,
    evaluate_gates,
    score_scenario,
)
from forge_voice.eval.setup import setup_for
from forge_voice.runtime.session import GROQ_MODEL
from forge_voice.scenarios.models import Scenario, TextScenario


class EvalHarnessError(RuntimeError):
    """The harness could not start or complete a run."""


@dataclass
class RunConfig:
    root: Path
    profile: str = "hybrid"
    mode: str = "text"
    split: str = "release"
    pipeline: str = "fixed"
    repeat_critical: bool = False
    provider_check: str = "auto"
    report_dir: Path = Path("reports")
    run_id: str | None = None
    max_seconds: float | None = None
    transport: str = "session"
    quiet: bool = False
    notes: list[str] = field(default_factory=list)


def _git_sha(root: Path) -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            or "unknown"
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _run_id(config: RunConfig) -> str:
    if config.run_id:
        return config.run_id
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"eval_{stamp}_{config.profile}_{config.mode}_{config.split}_{config.pipeline}"


def _filter_scenarios(selection: EvalSelection, mode: str) -> list[Scenario]:
    scenarios = [
        scenario for scenario in selection.scenarios if mode == "all" or scenario.mode == mode
    ]
    if not scenarios:
        raise EvalHarnessError(f"no scenarios for mode={mode!r} split={selection.split!r}")
    return scenarios


def _run_one(
    scenario: Scenario,
    *,
    selection: EvalSelection,
    config: RunConfig,
    text_runner: FixedTextRunner,
    audio_runner: FixedAudioRunner,
    baseline: BaselineRunner,
    repeat_index: int = 0,
) -> ScenarioResult:
    setup = setup_for(scenario, root=config.root)
    view = agent_view(
        scenario,
        heldout_manifest_sha=selection.heldout_manifest_sha,
        caller_phone=setup.caller_phone,
        now=setup.now,
        faults=setup.faults,
        pre_cancel_booking=setup.pre_cancel_booking,
        extra_turns=setup.turns_override,
    )
    assert_runner_view(view)
    if config.pipeline == "baseline":
        execution = baseline.run_view(view, setup)
    elif scenario.mode == "text":
        execution = text_runner.run_view(view, setup)
    else:
        execution = audio_runner.run_view(view, setup)
    verdict = score_scenario(scenario, execution, pipeline=config.pipeline)
    return build_scenario_result(
        scenario,
        execution,
        verdict,
        profile=config.profile,
        pipeline=config.pipeline,
        split=config.split,
        repeat_index=repeat_index,
    )


def _write_transcript(directory: Path, result: ScenarioResult) -> None:
    suffix = f"_r{result.repeat_index}" if result.repeat_index else ""
    path = directory / "transcripts" / f"{result.scenario_id}{suffix}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scenario_id": result.scenario_id,
        "profile": result.profile,
        "pipeline": result.pipeline,
        "split": result.split,
        "repeat_index": result.repeat_index,
        "transcript": result.execution.transcript,
        "tool_calls": result.execution.tool_calls,
        "qa_flags": result.execution.qa_flags,
        "recording_ref": result.execution.recording_ref,
        "latency": result.latency,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_report(directory: Path, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (directory / "report.md").write_text(render_markdown(payload), encoding="utf-8")
    return directory


def _cost_model() -> CostModel:
    return CostModel(
        assumptions=[
            "Demo marginal cost is $0 on the Groq free tier plus the local LFM3 GPU.",
            "Production estimate is $0.03-0.06/min (mid-point $0.048/min), dated 2026-11-07.",
            "The production estimate excludes build, support and one-off integration work.",
            "Per-scenario duration is an assumption from caller turns, not a metered bill.",
            "The local self-hosted LiveKit server does not consume Live Cloud minutes.",
        ]
    )


def _caveats(config: RunConfig, *, had_heldout: bool, provider: dict[str, Any]) -> list[str]:
    caveats = [
        LATENCY_CAVEAT,
        "Text mode uses the deterministic #4 rule interpreter. The hybrid label selects the "
        "release profile; the live Groq check proves the key/model are usable, not a per-turn "
        "LLM quality measurement.",
        "The baseline is a deliberately naive single-prompt stand-in with no tools, state, "
        "policy, confirmation or idempotency. It is expected to fail and never gates.",
        "Synthetic data only. No production SLA, HIPAA/PCI claim or real customer data.",
    ]
    if had_heldout:
        caveats.append(
            "Held-out runs received only caller inputs. The expected labels stayed in the "
            "scorer and the sealed manifest hash is recorded in this report."
        )
    if config.transport == "session":
        caveats.append(
            "Audio runs replay the committed caller scripts through the #5 AudioCallSession. "
            "This exercises the same policy, tools and confirmation path but does not measure "
            "acoustic ASR or WebRTC first-audio latency."
        )
    if provider.get("check") and not provider["check"].get("ok"):
        caveats.append(
            "The hybrid provider check did not pass; the release gate is not claimed. "
            f"Status: {provider['check'].get('status')}."
        )
    return caveats


def run_eval(config: RunConfig) -> int:
    selection = load_selection(config.root, split=config.split)
    scenarios = _filter_scenarios(selection, config.mode)
    run_id = _run_id(config)
    directory = config.report_dir / run_id
    started = datetime.now(UTC)
    started_perf = time.perf_counter()
    git_sha = _git_sha(config.root)
    had_heldout = any(scenario.held_out for scenario in scenarios)

    hybrid_required = (
        config.profile == "hybrid" and config.pipeline == "fixed" and config.provider_check != "off"
    )
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    provider: dict[str, Any] = {
        "text_engine": "deterministic_rule_interpreter",
        "audio_transport": config.transport,
        "groq_model": GROQ_MODEL,
        "hybrid_key_present": bool(api_key),
        "check": None,
    }
    if hybrid_required and not api_key:
        payload = _failure_payload(
            run_id=run_id,
            started=started,
            config=config,
            selection=selection,
            git_sha=git_sha,
            verdict="not_run_missing_groq_key",
            error=(
                "the hybrid release gate requires GROQ_API_KEY; the fully local report is "
                "available with make eval-local"
            ),
            provider=provider,
        )
        _write_report(directory, payload)
        print(payload["caveats"][-1] if payload["caveats"] else "missing GROQ_API_KEY")
        return 2

    if hybrid_required and config.provider_check == "auto":
        provider["check"] = check_groq(api_key)
    elif config.profile == "hybrid" and config.provider_check == "off":
        provider["check"] = {"ok": True, "status": "skipped", "model": GROQ_MODEL}
    else:
        provider["check"] = {"ok": True, "status": "not_required", "model": GROQ_MODEL}

    text_runner = FixedTextRunner(config.root)
    audio_runner: Any
    stack = None
    if any(scenario.mode == "audio" for scenario in scenarios) and config.transport == "livekit":
        from forge_voice.eval.livekit_audio import LiveKitAudioRunner, LiveKitStack

        stack = LiveKitStack(
            config.root,
            profile=config.profile,
            log_dir=directory / "stack",
            timeout=max(120.0, config.max_seconds or 0.0),
        )
        audio_runner = LiveKitAudioRunner(config.root, profile=config.profile, stack=stack)
    else:
        audio_runner = FixedAudioRunner(config.root)
    baseline = BaselineRunner(config.root)
    results: list[ScenarioResult] = []
    repeats = {"requested": config.repeat_critical, "scenarios": {}, "runs": 0}

    try:
        if stack is not None:
            audio_runner.start()
        for scenario in scenarios:
            result = _run_one(
                scenario,
                selection=selection,
                config=config,
                text_runner=text_runner,
                audio_runner=audio_runner,
                baseline=baseline,
            )
            results.append(result)
            _write_transcript(directory, result)
            if not config.quiet:
                status = "PASS" if result.verdict.passed else "FAIL"
                print(f"{status:4} {result.scenario_id} ({scenario.mode})")
            if (
                config.repeat_critical
                and isinstance(scenario, TextScenario)
                and scenario.critical_repeat
                and config.mode in {"text", "all"}
            ):
                repeat_passes: list[bool] = []
                for repeat_index in (1, 2, 3):
                    repeat = _run_one(
                        scenario,
                        selection=selection,
                        config=config,
                        text_runner=text_runner,
                        audio_runner=audio_runner,
                        baseline=baseline,
                        repeat_index=repeat_index,
                    )
                    results.append(repeat)
                    repeat_passes.append(repeat.verdict.passed)
                    _write_transcript(directory, repeat)
                repeats["scenarios"][scenario.id] = {
                    "runs": len(repeat_passes),
                    "passes": sum(repeat_passes),
                }
                repeats["runs"] += len(repeat_passes)
    except Exception as exc:
        payload = _failure_payload(
            run_id=run_id,
            started=started,
            config=config,
            selection=selection,
            git_sha=git_sha,
            verdict="error",
            error=f"{type(exc).__name__}: {exc}",
            provider=provider,
        )
        _write_report(directory, payload)
        print(f"eval harness error: {type(exc).__name__}: {exc}")
        return 2
    finally:
        if stack is not None:
            stack.stop()

    aggregates = build_aggregates(results, pipeline=config.pipeline)
    if config.mode == "all":
        aggregates["by_mode"] = {
            "text": build_aggregates(
                [result for result in results if result.mode == "text"],
                pipeline=config.pipeline,
            ),
            "audio": build_aggregates(
                [result for result in results if result.mode == "audio"],
                pipeline=config.pipeline,
            ),
        }
    gates = evaluate_gates(
        results,
        aggregates,
        mode=config.mode,
        pipeline=config.pipeline,
        profile=config.profile,
        split=config.split,
    )
    check = provider.get("check") or {}
    if hybrid_required:
        gates["hybrid_provider"] = GateResult(
            name="hybrid_provider",
            description="The hybrid release profile has a working Groq key and model.",
            threshold="live check ok",
            value=str(check.get("status", "not_run")),
            passed=bool(check.get("ok")),
            gated=True,
            failing_scenario_ids=[] if check.get("ok") else ["<provider>"],
        )
    elapsed = round(time.perf_counter() - started_perf, 3)
    if config.max_seconds is not None and elapsed > config.max_seconds:
        gates["time_budget"] = GateResult(
            name="time_budget",
            description="The command finished inside its wall-clock budget.",
            threshold=f"<={config.max_seconds:g}s",
            value=f"{elapsed:g}s",
            passed=False,
            gated=True,
            failing_scenario_ids=["<time_budget>"],
        )
    verdict = "pass"
    if config.pipeline == "baseline":
        verdict = "baseline_comparison_no_gate"
    elif any(gate.gated and not gate.passed for gate in gates.values()):
        verdict = "fail"
    finished = datetime.now(UTC)
    payload = EvalReport(
        run_id=run_id,
        started_at=started,
        finished_at=finished,
        git_sha=git_sha,
        manifest_sha=selection.manifest_sha,
        heldout_manifest_sha=selection.heldout_manifest_sha,
        profile=config.profile,
        mode=config.mode,
        pipeline=config.pipeline,
        split=config.split,
        verdict=verdict,
        scenarios=results,
        aggregates=aggregates,
        gates=gates,
        cost_model=_cost_model(),
        caveats=_caveats(config, had_heldout=had_heldout, provider=provider),
        provider=provider,
        repeats=repeats,
        counts={
            "scenarios": len(scenarios),
            "runs": len(results),
            "text": sum(1 for result in results if result.mode == "text"),
            "audio": sum(1 for result in results if result.mode == "audio"),
            "held_out": sum(1 for result in results if result.held_out),
            "elapsed_seconds": elapsed,
            "transcripts": str(directory / "transcripts"),
        },
    ).report_dict()
    _write_report(directory, payload)
    (directory / "heldout_manifest.json").write_text(
        json.dumps(selection.heldout_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not config.quiet:
        completion = aggregates["task_completion"]
        print(
            f"verdict={verdict} task_completion={completion['numerator']}/"
            f"{completion['denominator']} ({completion['percent']:.1f}%) "
            f"elapsed={elapsed:g}s report={directory}"
        )
    if config.pipeline == "baseline":
        return 0
    return 0 if verdict == "pass" else 1


def _failure_payload(
    *,
    run_id: str,
    started: datetime,
    config: RunConfig,
    selection: EvalSelection,
    git_sha: str,
    verdict: str,
    error: str,
    provider: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "git_sha": git_sha,
        "manifest_sha": selection.manifest_sha,
        "heldout_manifest_sha": selection.heldout_manifest_sha,
        "profile": config.profile,
        "mode": config.mode,
        "pipeline": config.pipeline,
        "split": config.split,
        "verdict": verdict,
        "scenarios": [],
        "aggregates": {
            "task_completion": {
                "numerator": 0,
                "denominator": 0,
                "n": 0,
                "percent": 0.0,
                "wilson_low": 0.0,
                "wilson_high": 0.0,
            },
            "latency": {
                "p50_wall_ms": 0,
                "p95_wall_ms": 0,
                "p50_tool_path_ms": 0,
                "p95_tool_path_ms": 0,
                "n": 0,
            },
        },
        "gates": {},
        "cost_model": _cost_model().model_dump(mode="json"),
        "caveats": [
            "The run did not start or did not complete; this report is written so the failure "
            "is visible rather than silent.",
            error,
        ],
        "provider": provider,
        "repeats": {},
        "counts": {"scenarios": 0, "runs": 0, "elapsed_seconds": 0},
    }

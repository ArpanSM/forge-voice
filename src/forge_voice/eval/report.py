"""Generate the Markdown report from the JSON source of truth."""

from __future__ import annotations

from typing import Any

LATENCY_CAVEAT = (
    "Latency is demo evidence, not a production SLA. The measured profile uses free/local "
    "models on a 4 GB laptop; production APIs must be re-measured before quoting a number. "
    "Text-mode latency is the deterministic tool-path time, not caller-perceived first audio; "
    "audio session replay is not an acoustic WebRTC measurement. Do not claim sub-3 s or "
    "sub-2 s from this report."
)


def _value(scenario: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in scenario:
        return scenario[key]
    return scenario.get(key.replace("-", "_"), default)


def _passed(scenario: dict[str, Any]) -> bool:
    passed = _value(scenario, "pass")
    if passed is None:
        passed = _value(scenario, "pass_", False)
    return bool(passed)


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _gate_rows(gates: dict[str, Any]) -> list[str]:
    rows = ["| Gate | Threshold | Result | Status | Failing scenarios |", "|---|---|---|---|---|"]
    for name, gate in gates.items():
        if not isinstance(gate, dict):
            gate = gate.model_dump(mode="json")
        failures = ", ".join(gate.get("failing_scenario_ids") or []) or "-"
        status = "PASS" if gate.get("passed") else "FAIL"
        if gate.get("gated") is False:
            status += " (report-only)"
        rows.append(
            f"| {_cell(name)} | {_cell(gate.get('threshold', ''))} | "
            f"{_cell(gate.get('value', ''))} | {status} | {_cell(failures)} |"
        )
    return rows


def _scenario_rows(scenarios: list[dict[str, Any]]) -> list[str]:
    rows = [
        "| Scenario | Category | Tenant | Pass | Gate failures | Latency (ms) | QA flags |",
        "|---|---|---|---|---|---|---|",
    ]
    for scenario in scenarios:
        if scenario.get("repeat_index", 0) > 0:
            continue
        verdict = scenario.get("verdict") or {}
        latency = scenario.get("latency") or {}
        rows.append(
            f"| {_cell(scenario.get('scenario_id'))} | {_cell(scenario.get('category'))} | "
            f"{_cell(scenario.get('tenant'))} | {'yes' if _passed(scenario) else 'NO'} | "
            f"{_cell(', '.join(verdict.get('gate_failures') or []) or '-')} | "
            f"{_cell(latency.get('tool_path_ms', 0))} | "
            f"{_cell(', '.join(scenario.get('qa_flags') or []) or '-')} |"
        )
    return rows


def _failure_gallery(
    scenarios: list[dict[str, Any]], gates: dict[str, Any], *, pipeline: str
) -> list[str]:
    failed_gate_ids = {
        scenario_id
        for gate in gates.values()
        if isinstance(gate, dict) and not gate.get("passed", True)
        for scenario_id in gate.get("failing_scenario_ids") or []
    }
    failures = [
        scenario
        for scenario in scenarios
        if not _passed(scenario) or scenario.get("scenario_id") in failed_gate_ids
    ]
    if pipeline == "baseline":
        failures = failures[:5]
    if not failures:
        return ["No failures in this run."]
    lines: list[str] = []
    for scenario in failures:
        verdict = scenario.get("verdict") or {}
        excerpt = scenario.get("failure_excerpt") or ""
        timeline = ", ".join(str(item) for item in (scenario.get("tool_timeline") or []))
        lines.extend(
            [
                f"### {scenario.get('scenario_id')}",
                "",
                f"- **Gate(s):** {', '.join(verdict.get('gate_failures') or []) or 'none'}",
                f"- **Expected:** `{scenario.get('expected')}`",
                f"- **Actual:** `{scenario.get('actual')}`",
                f"- **Reason:** {scenario.get('failure_reason') or 'failed'}",
                f"- **Tool timeline:** {timeline or 'none'}",
                f"- **Transcript excerpt:** {excerpt or 'none'}",
                f"- **Transcript:** {scenario.get('transcript_ref')}",
                "",
            ]
        )
    return lines


def _heldout_lines(scenarios: list[dict[str, Any]]) -> list[str]:
    held = [scenario for scenario in scenarios if scenario.get("held_out")]
    if not held:
        return ["No held-out scenarios in this run."]
    passed = sum(1 for scenario in held if _passed(scenario))
    lines = [
        f"{passed}/{len(held)} held-out scenarios passed. The agent runner received only "
        "persona, goal, caller turns/fixture and max turns; expected labels stayed in the "
        "scorer. The sealed manifest hash is recorded in the JSON report.",
        "",
        "| Scenario | Mode | Pass | Gate failures |",
        "|---|---|---|---|",
    ]
    for scenario in held:
        verdict = scenario.get("verdict") or {}
        lines.append(
            f"| {_cell(scenario.get('scenario_id'))} | {_cell(scenario.get('mode'))} | "
            f"{'yes' if _passed(scenario) else 'NO'} | "
            f"{_cell(', '.join(verdict.get('gate_failures') or []) or '-')} |"
        )
    return lines


def _audio_lines(payload: dict[str, Any]) -> list[str]:
    scenarios = [
        scenario for scenario in payload.get("scenarios", []) if scenario.get("mode") == "audio"
    ]
    if not scenarios:
        return ["No audio scenarios in this run."]
    aggregates = payload.get("aggregates") or {}
    barge = aggregates.get("barge_in_recovery") or {}
    clean = aggregates.get("asr_entity_accuracy_clean") or {}
    noisy = aggregates.get("asr_entity_accuracy_noisy") or {}
    lines = [
        f"- Audio scenarios: {len(scenarios)}",
        f"- Barge-in recovery: {_percent_text(barge)}",
        f"- ASR entity accuracy, clean: {_percent_text(clean)}",
        f"- ASR entity accuracy, noisy: {_percent_text(noisy)}",
        "",
        "| Scenario | Category | Pass | Barge-in | QA flags |",
        "|---|---|---|---|---|",
    ]
    for scenario in scenarios:
        actual = scenario.get("actual") or {}
        lines.append(
            f"| {_cell(scenario.get('scenario_id'))} | {_cell(scenario.get('category'))} | "
            f"{'yes' if _passed(scenario) else 'NO'} | "
            f"{_cell(actual.get('barge_in_recovered'))} | "
            f"{_cell(', '.join(scenario.get('qa_flags') or []) or '-')} |"
        )
    return lines


def _percent_text(metric: dict[str, Any]) -> str:
    percent = metric.get("percent")
    if percent is None:
        return f"{metric.get('status', 'not_measured')} (n=0)"
    return f"{percent:.2f}% ({metric.get('numerator', 0)}/{metric.get('denominator', 0)})"


def _repeat_lines(payload: dict[str, Any]) -> list[str]:
    scenarios = payload.get("scenarios") or []
    repeats = [scenario for scenario in scenarios if scenario.get("repeat_index", 0) > 0]
    if not repeats:
        return ["No critical repeats in this run."]
    distribution: dict[str, list[bool]] = {}
    for scenario in repeats:
        distribution.setdefault(str(scenario.get("scenario_id")), []).append(_passed(scenario))
    lines = ["| Critical scenario | Runs | Passes |", "|---|---|---|"]
    for scenario_id in sorted(distribution):
        outcomes = distribution[scenario_id]
        lines.append(f"| {_cell(scenario_id)} | {len(outcomes)} | {sum(outcomes)} |")
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    scenarios = payload.get("scenarios") or []
    gates = payload.get("gates") or {}
    aggregates = payload.get("aggregates") or {}
    completion = aggregates.get("task_completion") or {}
    failed_gates = [
        name for name, gate in gates.items() if isinstance(gate, dict) and not gate.get("passed")
    ]
    verdict = payload.get("verdict") or ("pass" if not failed_gates else "fail")
    lines = [
        "# Forge Voice evaluation",
        "",
        "This file is generated from `report.json`; do not hand-edit it.",
        "",
        "## Verdict",
        "",
        f"- **Run:** `{payload.get('run_id')}`",
        f"- **Profile / mode / pipeline:** {payload.get('profile')} / "
        f"{payload.get('mode')} / {payload.get('pipeline')}",
        f"- **Split:** {payload.get('split')}",
        f"- **Verdict:** **{str(verdict).upper()}**",
        f"- **Task completion:** {completion.get('numerator', 0)}/"
        f"{completion.get('denominator', 0)} "
        f"({completion.get('percent', 0.0):.2f}%, 95% Wilson "
        f"{completion.get('wilson_low', 0.0)}–{completion.get('wilson_high', 0.0)}%)",
        f"- **Git SHA:** `{payload.get('git_sha')}`",
        f"- **Manifest SHA:** `{payload.get('manifest_sha')}`",
        f"- **Held-out manifest SHA:** `{payload.get('heldout_manifest_sha')}`",
        "",
        "## Gate table",
        "",
        *_gate_rows(gates),
        "",
        "## Per-scenario results",
        "",
        *_scenario_rows(scenarios),
        "",
        "## Failure gallery",
        "",
        *_failure_gallery(scenarios, gates, pipeline=str(payload.get("pipeline", "fixed"))),
        "",
        "## Held-out set",
        "",
        *_heldout_lines(scenarios),
        "",
        "## Audio",
        "",
        *_audio_lines(payload),
        "",
        "## Critical repeat stability",
        "",
        *_repeat_lines(payload),
        "",
        "## Cost assumptions",
        "",
        "```json",
        _json_block(payload.get("cost_model") or {}),
        "```",
        "",
        "Demo marginal cost is $0 on free tiers plus the local GPU. The production estimate "
        "($0.03–0.06/min) is a dated planning range, not a measured bill. The per-scenario "
        "duration is an assumption, not a metered call length.",
        "",
        "## Latency caveat",
        "",
        LATENCY_CAVEAT,
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| p50 wall | {aggregates.get('latency', {}).get('p50_wall_ms', 0)} ms |",
        f"| p95 wall | {aggregates.get('latency', {}).get('p95_wall_ms', 0)} ms |",
        f"| p50 tool path | {aggregates.get('latency', {}).get('p50_tool_path_ms', 0)} ms |",
        f"| p95 tool path | {aggregates.get('latency', {}).get('p95_tool_path_ms', 0)} ms |",
        f"| n | {aggregates.get('latency', {}).get('n', 0)} |",
        "",
        "## Baseline vs fixed",
        "",
        *_comparison_lines(payload),
        "",
        "## Caveats and limits",
        "",
    ]
    caveats = payload.get("caveats") or []
    lines.extend(f"- {caveat}" for caveat in caveats) if caveats else lines.append(
        "- None recorded."
    )
    lines.extend(["", "## Baseline comparison", ""])
    if payload.get("pipeline") == "baseline":
        lines.append(
            "This is the naive baseline report. It is expected to fail the hard gates and "
            "**never gates a release**; it is the comparison, not a quality claim."
        )
    else:
        lines.append(
            "The naive baseline is generated separately by `make eval-baseline`; it is "
            "expected to fail and never gates."
        )
    lines.append("")
    return "\n".join(lines)


def _comparison_lines(payload: dict[str, Any]) -> list[str]:
    comparison = payload.get("comparison") or {}
    fixed = comparison.get("fixed") or {}
    if not fixed:
        return [
            "No fixed comparison in this report. Run `make eval-baseline` to generate the "
            "one-prompt baseline and the fixed side-by-side."
        ]
    baseline = payload.get("aggregates") or {}
    fixed_aggregates = fixed.get("aggregates") or {}
    rows = ["| Metric | Baseline n | Baseline | Fixed n | Fixed |", "|---|---|---|---|---|"]
    for key in sorted(set(baseline) & set(fixed_aggregates)):
        if key in {"by_mode", "latency", "cost"}:
            continue
        base = baseline.get(key) or {}
        fix = fixed_aggregates.get(key) or {}
        if not isinstance(base, dict) or not isinstance(fix, dict):
            continue
        if "percent" not in base and "percent" not in fix:
            continue

        def pct(metric: dict[str, Any]) -> str:
            value = metric.get("percent")
            return "n/a" if value is None else f"{value}%"

        rows.append(
            f"| {_cell(key)} | {base.get('denominator', 0)} | {pct(base)} | "
            f"{fix.get('denominator', 0)} | {pct(fix)} |"
        )
    gates = fixed.get("gates") or {}
    rows.extend(["", "Fixed gates in this comparison:", "", *_gate_rows(gates)])
    return rows


def _json_block(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True, default=str)

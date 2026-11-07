from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from forge_voice.eval.loader import load_selection
from forge_voice.eval.models import ScenarioExecution, WriteRecord
from forge_voice.eval.report import render_markdown
from forge_voice.eval.scoring import (
    build_aggregates,
    build_scenario_result,
    evaluate_gates,
    score_scenario,
)

ROOT = Path(__file__).resolve().parents[1]
LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 11, 6, 8, 0, tzinfo=LA)


def _booking_write(
    *,
    booking_id: str = "bk_harborlight_0001",
    slot_id: str = "slot_hl_00001",
    service_id: str = "drain_cleaning",
    zip_code: str = "94107",
    start: str = "2026-11-09T07:00:00-08:00",
) -> WriteRecord:
    return WriteRecord(
        tool="book_appointment",
        ok=True,
        args={
            "service_id": service_id,
            "slot_id": slot_id,
            "customer": {
                "name": "Sam Rivera",
                "phone": "+14155550101",
                "address": {
                    "line1": "12 Alder Street",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": zip_code,
                },
            },
        },
        result={
            "booking": {
                "booking_id": booking_id,
                "service_id": service_id,
                "address": {
                    "line1": "12 Alder Street",
                    "city": "San Francisco",
                    "state": "CA",
                    "zip": zip_code,
                },
                "start": start,
                "status": "booked",
            },
            "replayed": False,
        },
    )


def _booked_execution(**overrides) -> ScenarioExecution:
    values = {
        "scenario_id": "text_book_01",
        "tenant": "harborlight",
        "mode": "text",
        "outcome": "booked",
        "booking_ids": ["bk_harborlight_0001"],
        "booking_count": 1,
        "confirmation_queued": True,
        "confirmation_count": 1,
        "write_count": 1,
        "readbacks": 1,
        "writes": [_booking_write()],
        "transcript": [
            {"role": "assistant", "text": "Hi, this is Harborlight."},
            {"role": "caller", "text": "I need a drain cleaning."},
            {"role": "assistant", "text": "Just to confirm Monday 9 November at 9:00 AM."},
            {"role": "caller", "text": "Yes, that's correct."},
            {"role": "assistant", "text": "Booked."},
        ],
        "tool_calls": [
            {"name": "lookup_customer", "ok": True},
            {"name": "get_service_area", "ok": True},
            {"name": "get_availability", "ok": True},
            {"name": "book_appointment", "ok": True},
        ],
        "response_text": "Booked. Monday 9 November at 9:00 AM is confirmed.",
        "latency_ms": 10,
        "wall_ms": 20,
        "recording_ref": "text_only",
        "turns_used": 4,
    }
    values.update(overrides)
    return ScenarioExecution(**values)


def _scenario(scenario_id: str = "text_book_01"):
    for split in ("release", "audio"):
        selection = load_selection(ROOT, split=split)
        found = next((item for item in selection.scenarios if item.id == scenario_id), None)
        if found is not None:
            return found
    raise AssertionError(f"unknown scenario {scenario_id}")


def _result(scenario, execution, *, pipeline="fixed", profile="hybrid"):
    verdict = score_scenario(scenario, execution, pipeline=pipeline)
    return build_scenario_result(
        scenario,
        execution,
        verdict,
        profile=profile,
        pipeline=pipeline,
        split="release",
        repeat_index=0,
    )


def test_clean_booking_passes_and_satisfies_the_hard_gates() -> None:
    scenario = _scenario()
    execution = _booked_execution()

    verdict = score_scenario(scenario, execution, pipeline="fixed")
    result = _result(scenario, execution)
    gates = evaluate_gates([result], build_aggregates([result]), mode="text", pipeline="fixed")

    assert verdict.passed is True
    assert verdict.failure_reason is None
    assert verdict.gate_failures == []
    assert gates["slot_correctness"].passed is True
    assert gates["confirmation_accuracy"].passed is True
    assert gates["audit_completeness"].passed is True
    assert gates["double_booking"].passed is True


def test_a_write_without_a_readback_fails_confirmation_accuracy() -> None:
    scenario = _scenario()
    execution = _booked_execution(readbacks=0, confirmation_queued=False, confirmation_count=0)

    verdict = score_scenario(scenario, execution, pipeline="fixed")
    result = _result(scenario, execution)
    gates = evaluate_gates([result], build_aggregates([result]), mode="text", pipeline="fixed")

    assert verdict.passed is False
    assert "confirmation_accuracy" in verdict.gate_failures
    assert gates["confirmation_accuracy"].passed is False
    assert gates["confirmation_accuracy"].failing_scenario_ids == ["text_book_01"]


def test_two_booking_ids_for_one_slot_fail_the_double_booking_gate() -> None:
    scenario = _scenario()
    first = _result(scenario, _booked_execution())
    second_scenario = _scenario("text_book_02")
    second = _result(
        second_scenario,
        _booked_execution(
            scenario_id="text_book_02",
            booking_ids=["bk_harborlight_0002"],
            writes=[_booking_write(booking_id="bk_harborlight_0002")],
        ),
    )
    results = [first, second]

    gates = evaluate_gates(results, build_aggregates(results), mode="text", pipeline="fixed")

    assert gates["double_booking"].passed is False
    assert set(gates["double_booking"].failing_scenario_ids) == {
        "text_book_01",
        "text_book_02",
    }


def test_cross_tenant_disclosure_fails_the_cross_tenant_gate() -> None:
    scenario = _scenario("text_outofarea_02")
    execution = _booked_execution(
        scenario_id="text_outofarea_02",
        tenant="summit",
        outcome="info_only",
        booking_ids=[],
        booking_count=0,
        confirmation_queued=False,
        confirmation_count=0,
        write_count=0,
        readbacks=0,
        writes=[],
        tool_calls=[{"name": "get_service_area", "ok": True}],
        response_text="The Harborlight record is at 12 Alder Street, 94107.",
    )

    verdict = score_scenario(scenario, execution, pipeline="fixed")
    result = _result(scenario, execution)
    gates = evaluate_gates([result], build_aggregates([result]), mode="text", pipeline="fixed")

    assert "cross_tenant" in verdict.gate_failures
    assert gates["cross_tenant"].passed is False


def test_emergency_without_the_911_script_or_ticket_fails_triage() -> None:
    scenario = _scenario("text_emergency_01")
    execution = _booked_execution(
        scenario_id="text_emergency_01",
        outcome="booked",
        safety_script=None,
        emergency_category=None,
        ticket_count=0,
        ticket_id=None,
        response_text="I can book a technician for Monday.",
    )

    verdict = score_scenario(scenario, execution, pipeline="fixed")
    result = _result(scenario, execution)
    gates = evaluate_gates([result], build_aggregates([result]), mode="text", pipeline="fixed")

    assert "emergency_triage" in verdict.gate_failures
    assert gates["emergency_triage"].passed is False


def test_a_false_connected_handoff_fails_handoff_correctness() -> None:
    scenario = _scenario("text_handoff_01")
    execution = _booked_execution(
        scenario_id="text_handoff_01",
        outcome="transferred",
        booking_ids=[],
        booking_count=0,
        confirmation_queued=False,
        confirmation_count=0,
        write_count=0,
        readbacks=0,
        writes=[],
        transfer_status=None,
        handoff_packet=None,
        response_text="I'm transferring you now.",
        tool_calls=[],
    )

    verdict = score_scenario(scenario, execution, pipeline="fixed")
    result = _result(scenario, execution)
    gates = evaluate_gates([result], build_aggregates([result]), mode="text", pipeline="fixed")

    assert "handoff_correctness" in verdict.gate_failures
    assert gates["handoff_correctness"].passed is False


def test_missing_transcript_fails_audit_completeness() -> None:
    scenario = _scenario()
    execution = _booked_execution(transcript=[])

    verdict = score_scenario(scenario, execution, pipeline="fixed")
    result = _result(scenario, execution)
    gates = evaluate_gates([result], build_aggregates([result]), mode="text", pipeline="fixed")

    assert "audit_completeness" in verdict.gate_failures
    assert gates["audit_completeness"].passed is False


def test_unsafe_quote_fails_the_unsafe_promises_gate() -> None:
    scenario = _scenario("text_pricing_01")
    execution = _booked_execution(
        scenario_id="text_pricing_01",
        outcome="info_only",
        booking_ids=[],
        booking_count=0,
        confirmation_queued=False,
        confirmation_count=0,
        write_count=0,
        readbacks=0,
        writes=[],
        tool_calls=[],
        response_text="It is a flat $99 guaranteed.",
    )

    verdict = score_scenario(scenario, execution, pipeline="fixed")
    result = _result(scenario, execution)
    gates = evaluate_gates([result], build_aggregates([result]), mode="text", pipeline="fixed")

    assert "unsafe_promises" in verdict.gate_failures
    assert gates["unsafe_promises"].passed is False


def test_baseline_failures_are_reported_but_never_gate_release() -> None:
    scenario = _scenario()
    execution = _booked_execution(readbacks=0, confirmation_queued=False, confirmation_count=0)
    result = _result(scenario, execution, pipeline="baseline")

    gates = evaluate_gates(
        [result],
        build_aggregates([result], pipeline="baseline"),
        mode="text",
        pipeline="baseline",
    )

    assert any(not gate.passed for gate in gates.values())
    assert all(gate.gated is False for gate in gates.values())


def test_task_completion_uses_numerator_denominator_and_wilson_interval() -> None:
    scenario = _scenario()
    passing = _result(scenario, _booked_execution())
    failing = _result(
        scenario,
        _booked_execution(scenario_id="text_book_01", transcript=[]),
        pipeline="fixed",
    )

    aggregates = build_aggregates([passing, failing])

    completion = aggregates["task_completion"]
    assert completion["numerator"] == 1
    assert completion["denominator"] == 2
    assert completion["percent"] == 50.0
    assert completion["wilson_low"] < 50.0 < completion["wilson_high"]


def test_in_area_is_scored_from_the_service_area_tool_result() -> None:
    scenario = _scenario("text_outofarea_01")
    execution = _booked_execution(
        scenario_id="text_outofarea_01",
        outcome="info_only",
        booking_ids=[],
        booking_count=0,
        confirmation_queued=False,
        confirmation_count=0,
        write_count=0,
        readbacks=0,
        writes=[],
        tool_calls=[
            {
                "name": "get_service_area",
                "ok": True,
                "result": {"data": {"in_area": False}},
            }
        ],
        response_text="That ZIP is outside the service area.",
    )
    assert score_scenario(scenario, execution, pipeline="fixed").passed is True

    inside = execution.model_copy(
        update={
            "tool_calls": [
                {
                    "name": "get_service_area",
                    "ok": True,
                    "result": {"data": {"in_area": True}},
                }
            ]
        }
    )
    assert score_scenario(scenario, inside, pipeline="fixed").checks["in_area"] is False


def test_duplicate_writes_are_scored_not_ignored() -> None:
    scenario = _scenario("text_timeout_01")
    first = _booking_write(booking_id="bk_one")
    second = _booking_write(booking_id="bk_two")
    execution = _booked_execution(
        scenario_id="text_timeout_01",
        outcome="callback",
        booking_ids=["bk_one", "bk_two"],
        booking_count=2,
        confirmation_queued=True,
        write_count=2,
        writes=[first, second],
    )

    verdict = score_scenario(scenario, execution, pipeline="fixed")

    assert verdict.checks["duplicate_writes"] is False


def test_confirmed_entities_is_not_vacuous_when_no_entities_were_measured() -> None:
    scenario = _scenario("text_noise_01")
    execution = _booked_execution(
        scenario_id="text_noise_01",
        asr_entities={},
        asr_expected_entities={},
        asr_source="not_measured",
    )

    verdict = score_scenario(scenario, execution, pipeline="fixed")

    assert verdict.checks["confirmed_entities"] is False


def test_audio_hard_gates_are_gated_not_report_only() -> None:
    scenario = _scenario("audio_bargein_01")
    execution = _booked_execution(
        scenario_id="audio_bargein_01",
        mode="audio",
        transcript=[],
    )
    result = _result(scenario, execution, profile="hybrid")
    aggregates = build_aggregates([result])
    gates = evaluate_gates(
        [result],
        aggregates,
        mode="audio",
        pipeline="fixed",
        profile="hybrid",
    )

    assert gates["audit_completeness"].passed is False
    assert gates["audit_completeness"].gated is True


def test_live_or_provider_errors_fail_the_run_integrity_gate() -> None:
    scenario = _scenario("audio_bargein_01")
    execution = _booked_execution(
        scenario_id="audio_bargein_01",
        mode="audio",
        outcome="failed",
        qa_flags=["harness_error"],
    )
    result = _result(scenario, execution, profile="hybrid")
    gates = evaluate_gates(
        [result],
        build_aggregates([result]),
        mode="audio",
        pipeline="fixed",
        profile="hybrid",
    )

    assert gates["run_integrity"].passed is False
    assert gates["run_integrity"].gated is True


def test_markdown_report_has_every_required_section() -> None:
    scenario = _scenario()
    result = _result(scenario, _booked_execution())
    aggregates = build_aggregates([result])
    gates = evaluate_gates([result], aggregates, mode="text", pipeline="fixed")
    payload = {
        "schema_version": 1,
        "run_id": "eval_test",
        "started_at": NOW.isoformat(),
        "git_sha": "abc1234",
        "manifest_sha": "sha256:abc",
        "heldout_manifest_sha": "sha256:def",
        "profile": "hybrid",
        "mode": "text",
        "pipeline": "fixed",
        "split": "release",
        "verdict": "pass",
        "scenarios": [result.model_dump(mode="json")],
        "aggregates": aggregates,
        "gates": {name: gate.model_dump(mode="json") for name, gate in gates.items()},
        "cost_model": {
            "demo_marginal_usd": 0.0,
            "production_per_minute_low_usd": 0.03,
            "production_per_minute_high_usd": 0.06,
        },
        "caveats": ["Latency is report-only."],
    }

    markdown = render_markdown(payload)

    for heading in (
        "# Forge Voice evaluation",
        "## Verdict",
        "## Gate table",
        "## Per-scenario results",
        "## Failure gallery",
        "## Held-out set",
        "## Audio",
        "## Cost assumptions",
        "## Latency caveat",
        "## Caveats and limits",
    ):
        assert heading in markdown

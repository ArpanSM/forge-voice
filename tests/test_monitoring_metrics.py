"""Aggregate monitoring metrics match the #26 definitions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from forge_voice.events.store import CallStore
from forge_voice.monitoring.filters import CallFilters
from forge_voice.monitoring.metrics import aggregate_metrics
from forge_voice.policy.state import CallIntent, CallOutcome, TransferStatus
from support_monitoring import latency, make_call, tool


def _sample_calls():
    return [
        make_call(
            "call_a",
            outcome=CallOutcome.booked,
            turn_latencies=[latency(2000)],
            tool_events=[tool("get_availability"), tool("book_appointment")],
            cost_usd=0.01,
        ),
        make_call(
            "call_b",
            outcome=CallOutcome.booked,
            turn_latencies=[latency(3000)],
            tool_events=[tool("book_appointment")],
            cost_usd=0.02,
            slot_error=True,
        ),
        make_call(
            "call_c",
            intent=CallIntent.human,
            outcome=CallOutcome.transferred,
            transfer_status=TransferStatus.connected,
            turn_latencies=[latency(4000)],
            tool_events=[tool("transfer_to_human", ok=False, error_code="timeout")],
            cost_usd=0.03,
        ),
        make_call(
            "call_d",
            intent=CallIntent.emergency,
            outcome=CallOutcome.emergency_ticket,
            ticket_id="em_0001",
            turn_latencies=[latency(5000)],
            tool_events=[tool("create_emergency_ticket"), tool("transfer_to_human")],
            cost_usd=0.0,
            emergency_triage_ok=True,
        ),
    ]


def test_aggregate_metrics_use_the_documented_denominators() -> None:
    metrics = aggregate_metrics(_sample_calls())

    assert metrics["calls"]["total"] == 4
    assert metrics["transfer_rate"] == {
        "numerator": 1,
        "denominator": 4,
        "n": 4,
        "percent": 25.0,
    }
    assert metrics["containment"]["percent"] == 75.0
    assert metrics["booking_rate"]["numerator"] == 2
    assert metrics["booking_rate"]["percent"] == 50.0
    assert metrics["slot_error_rate"]["numerator"] == 1
    assert metrics["slot_error_rate"]["denominator"] == 2
    assert metrics["slot_error_rate"]["percent"] == 50.0
    assert metrics["tool_error_rate"]["numerator"] == 1
    assert metrics["tool_error_rate"]["denominator"] == 6
    assert metrics["tool_error_rate"]["percent"] == 16.67
    assert metrics["emergency_triage_rate"]["numerator"] == 1
    assert metrics["emergency_triage_rate"]["denominator"] == 1
    assert metrics["latency"]["p50_ms"] == 3500
    assert metrics["latency"]["p95_ms"] == 4850
    assert metrics["latency"]["samples"] == 4
    assert metrics["cost"]["total_usd"] == 0.06
    assert metrics["cost"]["per_call_usd"] == 0.015


def test_booking_failure_rate_counts_failed_write_calls_only() -> None:
    records = [
        make_call(
            "call_ok",
            tool_events=[tool("book_appointment")],
        ),
        make_call(
            "call_bad",
            tool_events=[tool("book_appointment", ok=False, error_code="timeout")],
        ),
        make_call(
            "call_info",
            intent=CallIntent.pricing_faq,
            outcome=CallOutcome.info_only,
            booking_id=None,
        ),
    ]

    metrics = aggregate_metrics(records)

    assert metrics["booking_failure_rate"]["numerator"] == 1
    assert metrics["booking_failure_rate"]["denominator"] == 2
    assert metrics["booking_failure_rate"]["percent"] == 50.0


def test_call_store_applies_30_day_retention_and_filters(tmp_path) -> None:
    now = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    store = CallStore(tmp_path, retention_days=30, now=lambda: now)
    fresh = make_call("call_fresh", started_at=now - timedelta(days=2))
    old = make_call("call_old", started_at=now - timedelta(days=31))
    store.replace_all([fresh, old])

    records = store.records()

    assert [record.call_id for record in records] == ["call_fresh"]
    assert store.get("call_old") is None


def test_call_filters_match_tenant_date_and_outcome(tmp_path) -> None:
    now = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
    records = [
        make_call(
            "call_hl",
            started_at=now - timedelta(days=1),
            outcome=CallOutcome.booked,
        ),
        make_call(
            "call_summit",
            tenant_id="summit",
            started_at=now - timedelta(days=3),
            outcome=CallOutcome.callback,
        ),
    ]
    store = CallStore(tmp_path, now=lambda: now)
    store.replace_all(records)

    filtered = store.records(
        filters=CallFilters(
            tenant="summit",
            from_date=(now - timedelta(days=4)).date(),
            to_date=now.date(),
            outcome=CallOutcome.callback,
        )
    )

    assert [record.call_id for record in filtered] == ["call_summit"]

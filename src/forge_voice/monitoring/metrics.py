"""Aggregate metrics with the #26 definitions.

Binary metrics report numerator, denominator, n and percent. Latency is reported only over
caller turns that have a measured first-audio breakdown; unmeasured live traces are excluded
rather than filled with a guess.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

from forge_voice.events.models import CallRecord
from forge_voice.policy.state import CallIntent

WRITE_TOOLS = frozenset({"book_appointment", "reschedule_appointment", "cancel_appointment"})
SECURITY_FLAGS = frozenset(
    {
        "cross_tenant_attempt",
        "cross_tenant_leak",
        "ownership_failure",
        "auth_anomaly",
        "unauthorized_write",
    }
)

DEFINITIONS = {
    "containment": (
        "Calls resolved without a live transfer (booked, rescheduled, cancelled, "
        "info-only, or a satisfactory emergency ticket) / total calls."
    ),
    "transfer_rate": "Calls with a connected human transfer / total calls.",
    "booking_rate": "Calls ending in a committed booking or reschedule / total calls.",
    "slot_error_rate": (
        "Checked committed bookings with a wrong service, address ZIP or slot / "
        "checked committed bookings."
    ),
    "latency": "Caller-perceived first audio per turn, as p50/p95 over measured turns.",
    "tool_error_rate": "Tool calls with an error envelope / total tool calls.",
    "cost": "Total synthetic call cost / total calls; the local demo is $0.",
    "emergency_triage_rate": (
        "Emergency calls with a correct ticket and 911/transfer / emergency calls."
    ),
    "booking_failure_rate": "Calls with a failed write tool / calls that attempted a write.",
    "qa_flag_rate": "QA flags per 100 calls.",
    "security_anomalies": "Calls carrying a cross-tenant, auth or ownership anomaly flag.",
}


def aggregate_metrics(records: Iterable[CallRecord]) -> dict[str, object]:
    calls = list(records)
    total = len(calls)
    transferred = sum(1 for call in calls if call.transferred)
    contained = sum(1 for call in calls if call.resolved)
    committed = [call for call in calls if call.committed_booking]
    checked_bookings = [call for call in committed if call.slot_checked]
    emergency = [call for call in calls if call.intent is CallIntent.emergency]
    emergency_ok = [call for call in emergency if call.emergency_triage_ok is True]
    tool_events = [event for call in calls for event in call.tool_events]
    tool_errors = [event for event in tool_events if not event.ok]
    write_calls = [
        call for call in calls if any(event.name in WRITE_TOOLS for event in call.tool_events)
    ]
    failed_writes = [
        call
        for call in write_calls
        if any(event.name in WRITE_TOOLS and not event.ok for event in call.tool_events)
    ]
    latency_values = [float(turn.total_ms) for call in calls for turn in call.turn_latencies]
    total_cost = sum(call.cost_usd for call in calls)
    qa_flags = sum(len(call.qa_flags) for call in calls)
    security = [call for call in calls if SECURITY_FLAGS.intersection(call.qa_flags)]
    return {
        "calls": {
            "total": total,
            "transferred": transferred,
            "committed_bookings": len(committed),
            "checked_bookings": len(checked_bookings),
            "emergency_calls": len(emergency),
            "tool_calls": len(tool_events),
        },
        "containment": _metric(contained, total, total),
        "transfer_rate": _metric(transferred, total, total),
        "booking_rate": _metric(len(committed), total, total),
        "slot_error_rate": _metric(
            sum(1 for call in checked_bookings if call.slot_error),
            len(checked_bookings),
            total,
        ),
        "tool_error_rate": _metric(len(tool_errors), len(tool_events), total),
        "booking_failure_rate": _metric(len(failed_writes), len(write_calls), total),
        "emergency_triage_rate": _metric(len(emergency_ok), len(emergency), total),
        "cost": {
            "total_usd": round(total_cost, 6),
            "per_call_usd": round(total_cost / total, 6) if total else 0.0,
            "n": total,
        },
        "latency": {
            "p50_ms": _percentile(latency_values, 50),
            "p95_ms": _percentile(latency_values, 95),
            "samples": len(latency_values),
            "calls_with_latency": sum(1 for call in calls if call.turn_latencies),
            "n": total,
        },
        "qa_flag_rate": {
            "flags": qa_flags,
            "calls": total,
            "per_100_calls": round(100 * qa_flags / total, 2) if total else 0.0,
        },
        "security_anomalies": {
            "count": len(security),
            "n": total,
        },
    }


def _metric(numerator: int, denominator: int, n: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "n": n,
        "percent": round(100 * numerator / denominator, 2) if denominator else 0.0,
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)

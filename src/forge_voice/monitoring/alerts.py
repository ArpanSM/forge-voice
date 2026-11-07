"""Threshold evaluation and the append-only alerts.jsonl log."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from forge_voice.events.models import CallRecord
from forge_voice.models import StrictModel
from forge_voice.monitoring.metrics import SECURITY_FLAGS, aggregate_metrics
from forge_voice.policy.state import CallIntent

PROFILE_BUDGETS_MS = {"hybrid": 2500, "local": 6000}
TOOL_ERROR_THRESHOLD_PERCENT = 2.0
BOOKING_FAILURE_THRESHOLD_PERCENT = 1.0


class Alert(StrictModel):
    alert_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    severity: Literal["warning", "critical"]
    title: str = Field(min_length=1)
    message: str = Field(min_length=1)
    observed: float
    threshold: float
    unit: str
    call_ids: list[str] = Field(default_factory=list)


def evaluate_alerts(
    records: Iterable[CallRecord],
    *,
    profile: Literal["local", "hybrid"],
    now: datetime,
) -> list[Alert]:
    calls = list(records)
    metrics = aggregate_metrics(calls)
    suffix = f"{profile}_{now:%Y%m%d}"
    alerts: list[Alert] = []

    latency = metrics["latency"]
    budget = PROFILE_BUDGETS_MS[profile]
    if latency["samples"] and latency["p95_ms"] > budget:
        alerts.append(
            Alert(
                alert_id=f"latency_p95_over_budget_{suffix}",
                kind="latency_p95_over_budget",
                severity="warning",
                title="p95 latency over the active profile budget",
                message=(
                    f"p95 first audio is {latency['p95_ms']:.0f} ms over the {profile} "
                    f"budget of {budget} ms ({latency['samples']} measured turns)."
                ),
                observed=latency["p95_ms"],
                threshold=float(budget),
                unit="ms",
            )
        )

    tool_error = metrics["tool_error_rate"]
    if tool_error["denominator"] and tool_error["percent"] > TOOL_ERROR_THRESHOLD_PERCENT:
        alerts.append(
            Alert(
                alert_id=f"tool_error_rate_over_budget_{suffix}",
                kind="tool_error_rate_over_budget",
                severity="critical",
                title="Tool error rate over 2%",
                message=(
                    f"Tool error rate is {tool_error['percent']:.2f}% "
                    f"({tool_error['numerator']} of {tool_error['denominator']} tool calls)."
                ),
                observed=tool_error["percent"],
                threshold=TOOL_ERROR_THRESHOLD_PERCENT,
                unit="percent",
            )
        )

    slot_error = metrics["slot_error_rate"]
    if slot_error["denominator"] and slot_error["numerator"] > 0:
        slot_calls = [
            call.call_id
            for call in calls
            if call.committed_booking and call.slot_checked and call.slot_error
        ]
        alerts.append(
            Alert(
                alert_id=f"slot_correctness_failure_{suffix}",
                kind="slot_correctness_failure",
                severity="critical",
                title="Slot correctness failure",
                message=(
                    f"{slot_error['numerator']} of {slot_error['denominator']} checked "
                    "bookings did not match the requested service, address or slot."
                ),
                observed=float(slot_error["numerator"]),
                threshold=0.0,
                unit="calls",
                call_ids=slot_calls,
            )
        )

    booking_failure = metrics["booking_failure_rate"]
    if (
        booking_failure["denominator"]
        and booking_failure["percent"] > BOOKING_FAILURE_THRESHOLD_PERCENT
    ):
        alerts.append(
            Alert(
                alert_id=f"booking_failure_rate_over_budget_{suffix}",
                kind="booking_failure_rate_over_budget",
                severity="critical",
                title="Booking write failure over 1%",
                message=(
                    f"Booking failure rate is {booking_failure['percent']:.2f}% "
                    f"({booking_failure['numerator']} of {booking_failure['denominator']} "
                    "write calls)."
                ),
                observed=booking_failure["percent"],
                threshold=BOOKING_FAILURE_THRESHOLD_PERCENT,
                unit="percent",
            )
        )

    emergency_failures = [
        call
        for call in calls
        if call.intent is CallIntent.emergency and call.emergency_triage_ok is False
    ]
    if emergency_failures:
        alerts.append(
            Alert(
                alert_id=f"emergency_transfer_failure_{suffix}",
                kind="emergency_transfer_failure",
                severity="critical",
                title="Emergency transfer failure",
                message=(
                    f"{len(emergency_failures)} emergency call(s) did not record a correct "
                    "category, the 911/life-safety script, a ticket and a connected or "
                    "queued on-call handoff."
                ),
                observed=float(len(emergency_failures)),
                threshold=0.0,
                unit="calls",
                call_ids=[call.call_id for call in emergency_failures],
            )
        )

    security = [call for call in calls if SECURITY_FLAGS.intersection(call.qa_flags)]
    if security:
        alerts.append(
            Alert(
                alert_id=f"cross_tenant_auth_anomaly_{suffix}",
                kind="cross_tenant_auth_anomaly",
                severity="critical",
                title="Cross-tenant or auth anomaly",
                message=(
                    f"{len(security)} call(s) carry a cross-tenant, auth or ownership anomaly "
                    "flag. Review before the next demo."
                ),
                observed=float(len(security)),
                threshold=0.0,
                unit="calls",
                call_ids=[call.call_id for call in security],
            )
        )
    return alerts


def append_alerts(path: Path | str, alerts: Iterable[Alert]) -> list[Alert]:
    """Append new alerts once; the alert id is the daily dedupe key."""
    destination = Path(path)
    incoming = list(alerts)
    if not incoming:
        return []
    existing: set[str] = set()
    if destination.exists():
        for line in destination.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                existing.add(str(json.loads(line).get("alert_id")))
            except json.JSONDecodeError:
                continue
    fresh = [alert for alert in incoming if alert.alert_id not in existing]
    if not fresh:
        return []
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as handle:
        for alert in fresh:
            handle.write(alert.model_dump_json() + "\n")
    return fresh

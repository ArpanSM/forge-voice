"""Shared builders for the monitoring tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from forge_voice.events.models import CallRecord, DashboardToolEvent, LatencyBreakdown
from forge_voice.policy.state import CallIntent, CallOutcome, TransferStatus
from forge_voice.runtime.models import TranscriptTurn

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def latency(
    total_ms: int | None = None,
    *,
    stt: int = 400,
    llm: int = 900,
    tool: int = 20,
    tts: int = 300,
) -> LatencyBreakdown:
    if total_ms is not None:
        remaining = total_ms - stt - tool - tts
        llm = max(remaining, 0)
    return LatencyBreakdown(
        stt_endpointing_ms=stt,
        llm_ttft_ms=llm,
        tool_ms=tool,
        tts_ttfb_ms=tts,
    )


def make_call(
    call_id: str,
    *,
    tenant_id: str = "harborlight",
    profile: str = "local",
    intent: CallIntent = CallIntent.book,
    outcome: CallOutcome = CallOutcome.booked,
    transfer_status: TransferStatus | None = None,
    booking_id: str | None = None,
    ticket_id: str | None = None,
    started_at: datetime = NOW,
    turn_latencies: list[LatencyBreakdown] | None = None,
    tool_events: list[DashboardToolEvent] | None = None,
    qa_flags: list[str] | None = None,
    cost_usd: float = 0.0,
    caller_phone: str | None = "+14155550101",
    recording_ref: str = "text_only",
    recording_opt_out: bool = False,
    synthetic: bool = True,
    slot_error: bool = False,
    slot_checked: bool | None = None,
    expected_service_id: str | None = None,
    expected_address_zip: str | None = None,
    expected_slot_id: str | None = None,
    booked_service_id: str | None = None,
    booked_address_zip: str | None = None,
    booked_slot_id: str | None = None,
    emergency_category: str | None = None,
    emergency_safety_script: str | None = None,
    emergency_triage_ok: bool | None = None,
) -> CallRecord:
    if slot_checked is None:
        slot_checked = slot_error
    if booking_id is None and outcome in {CallOutcome.booked, CallOutcome.rescheduled}:
        booking_id = f"bk_{call_id}"
    return CallRecord(
        call_id=call_id,
        tenant_id=tenant_id,
        profile=profile,  # type: ignore[arg-type]
        intent=intent,
        outcome=outcome,
        transfer_status=transfer_status,
        booking_id=booking_id,
        ticket_id=ticket_id,
        service_id=booked_service_id,
        caller_phone=caller_phone,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=3),
        transcript=[
            TranscriptTurn(role="assistant", text="Thanks for calling Harborlight."),
            TranscriptTurn(role="caller", text="I need a drain cleaning."),
        ],
        tool_events=list(tool_events or []),
        turn_latencies=list(turn_latencies or []),
        qa_flags=list(qa_flags or []),
        cost_usd=cost_usd,
        recording_ref=recording_ref,
        recording_opt_out=recording_opt_out,
        synthetic=synthetic,
        expected_service_id=expected_service_id,
        expected_address_zip=expected_address_zip,
        expected_slot_id=expected_slot_id,
        booked_service_id=booked_service_id,
        booked_address_zip=booked_address_zip,
        booked_slot_id=booked_slot_id,
        slot_checked=slot_checked,
        slot_error=slot_error,
        emergency_category=emergency_category,
        emergency_safety_script=emergency_safety_script,
        emergency_triage_ok=emergency_triage_ok,
    )


def tool(
    name: str,
    *,
    ok: bool = True,
    latency_ms: int = 5,
    error_code: str | None = None,
) -> DashboardToolEvent:
    return DashboardToolEvent(
        name=name,
        args={},
        ok=ok,
        error_code=error_code,
        latency_ms=latency_ms,
        at=NOW,
    )

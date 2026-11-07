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
    recording_ref: str = "text_only",
    recording_opt_out: bool = False,
    slot_error: bool = False,
    emergency_triage_ok: bool | None = None,
) -> CallRecord:
    if booking_id is None and outcome in {CallOutcome.booked, CallOutcome.rescheduled}:
        booking_id = f"bk_{call_id}"
    return CallRecord(
        call_id=call_id,
        tenant_id=tenant_id,
        profile=profile,  # type: ignore[arg-type]
        caller_phone="+14155550101",
        intent=intent,
        outcome=outcome,
        transfer_status=transfer_status,
        booking_id=booking_id,
        ticket_id=ticket_id,
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
        slot_error=slot_error,
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

"""Dashboard read models built from the #4 call result and #5 call trace."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from forge_voice.models import StrictModel
from forge_voice.policy.state import CallIntent, CallOutcome, TransferStatus
from forge_voice.runtime.models import CallResult, TranscriptTurn


class LatencyBreakdown(StrictModel):
    """One caller turn split into the stages that make up caller-perceived first audio."""

    stt_endpointing_ms: int = Field(ge=0)
    llm_ttft_ms: int = Field(ge=0)
    tool_ms: int = Field(ge=0)
    tts_ttfb_ms: int = Field(ge=0)

    @property
    def total_ms(self) -> int:
        return self.stt_endpointing_ms + self.llm_ttft_ms + self.tool_ms + self.tts_ttfb_ms


class DashboardToolEvent(StrictModel):
    """A flattened tool event; the dashboard never re-runs or re-derives tool logic."""

    name: str = Field(min_length=1)
    args: dict[str, object] = Field(default_factory=dict)
    ok: bool
    error_code: str | None = None
    latency_ms: int = Field(ge=0, default=0)
    at: datetime


class CallRecord(StrictModel):
    """Read-only call view shared by the dashboard, metrics export and alerts."""

    call_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    profile: Literal["local", "hybrid"] = "local"
    caller_phone: str | None = None
    intent: CallIntent | None = None
    outcome: CallOutcome
    transfer_status: TransferStatus | None = None
    booking_id: str | None = None
    ticket_id: str | None = None
    callback_id: str | None = None
    started_at: datetime
    ended_at: datetime
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    tool_events: list[DashboardToolEvent] = Field(default_factory=list)
    turn_latencies: list[LatencyBreakdown] = Field(default_factory=list)
    cost_usd: float = Field(ge=0, default=0.0)
    qa_flags: list[str] = Field(default_factory=list)
    recording_ref: str = "text_only"
    recording_opt_out: bool = False
    slot_error: bool = False
    emergency_triage_ok: bool | None = None

    @property
    def duration_seconds(self) -> int:
        return max(0, int((self.ended_at - self.started_at).total_seconds()))

    @property
    def committed_booking(self) -> bool:
        return self.outcome in {CallOutcome.booked, CallOutcome.rescheduled}

    @property
    def transferred(self) -> bool:
        return self.outcome is CallOutcome.transferred or (
            self.transfer_status is TransferStatus.connected
        )

    @property
    def first_audio_p95_ms(self) -> int | None:
        if not self.turn_latencies:
            return None
        ordered = sorted(turn.total_ms for turn in self.turn_latencies)
        position = (len(ordered) - 1) * 95 / 100
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        return round(value)

    @classmethod
    def from_call_result(
        cls,
        result: CallResult,
        *,
        profile: Literal["local", "hybrid"],
        started_at: datetime,
        ended_at: datetime,
        turn_latencies: list[LatencyBreakdown] | None = None,
        cost_usd: float = 0.0,
        recording_opt_out: bool = False,
        recording_ref: str = "text_only",
        slot_error: bool = False,
    ) -> CallRecord:
        emergency_ok: bool | None = None
        if result.intent is CallIntent.emergency:
            emergency_ok = result.outcome is CallOutcome.emergency_ticket and bool(result.ticket_id)
        return cls(
            call_id=result.call_id,
            tenant_id=result.tenant_id,
            profile=profile,
            caller_phone=None,
            intent=result.intent,
            outcome=result.outcome,
            transfer_status=result.transfer_status,
            booking_id=result.booking_id,
            ticket_id=result.ticket_id,
            callback_id=result.callback_id,
            started_at=started_at,
            ended_at=ended_at,
            transcript=list(result.transcript),
            tool_events=[
                DashboardToolEvent(
                    name=event.name,
                    args=event.args,
                    ok=event.result.ok,
                    error_code=(
                        event.result.error.code.value if event.result.error is not None else None
                    ),
                    latency_ms=event.latency_ms,
                    at=event.at,
                )
                for event in result.tool_events
            ],
            turn_latencies=list(turn_latencies or []),
            cost_usd=cost_usd,
            qa_flags=list(result.qa_flags),
            recording_ref=recording_ref,
            recording_opt_out=recording_opt_out,
            slot_error=slot_error,
            emergency_triage_ok=emergency_ok,
        )

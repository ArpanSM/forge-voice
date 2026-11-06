"""Public text-mode call models: the same seam the demo, dashboard and eval use."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from forge_voice.models import StrictModel
from forge_voice.policy.handoff import HandoffPacket
from forge_voice.policy.state import CallIntent, CallOutcome, TransferStatus
from forge_voice.scenarios.models import TextScenario
from forge_voice.tools.envelope import ToolResult


class CallScenario(StrictModel):
    id: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    turns: list[str] = Field(min_length=1)
    caller_phone: str | None = None
    now: datetime | None = None
    faults: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_text_scenario(cls, scenario: TextScenario) -> CallScenario:
        return cls(
            id=scenario.id,
            tenant=scenario.tenant,
            turns=scenario.turns,
        )


class TranscriptTurn(StrictModel):
    role: Literal["assistant", "caller"]
    text: str


class ToolCallRecord(StrictModel):
    name: str
    args: dict[str, object] = Field(default_factory=dict)
    result: ToolResult
    latency_ms: int
    at: datetime


class CallResult(StrictModel):
    scenario_id: str
    tenant_id: str
    call_id: str
    intent: CallIntent | None = None
    outcome: CallOutcome
    transfer_status: TransferStatus | None = None
    booking_id: str | None = None
    booking_ids: list[str] = Field(default_factory=list)
    ticket_id: str | None = None
    callback_id: str | None = None
    service_id: str | None = None
    booking_count: int = 0
    ticket_count: int = 0
    callback_count: int = 0
    cancel_count: int = 0
    write_count: int = 0
    replayed: bool = False
    confirmation_queued: bool = False
    already_cancelled: bool = False
    old_slot_released: bool = False
    slot_released: bool = False
    safety_script: str | None = None
    emergency_category: str | None = None
    emergency_severity: str | None = None
    vulnerable_occupant: bool = False
    handoff_packet: HandoffPacket | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    tool_events: list[ToolCallRecord] = Field(default_factory=list)
    latency_ms: int = 0
    qa_flags: list[str] = Field(default_factory=list)
    response_text: str = ""
    error_code: str | None = None
    recording_ref: str = "text_only"

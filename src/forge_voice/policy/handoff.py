"""Structured human-handoff packet and its completeness rule."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from forge_voice.domain import Address
from forge_voice.models import StrictModel
from forge_voice.policy.state import CallIntent


class HandoffCaller(StrictModel):
    name: str | None = None
    phone: str = Field(pattern=r"^\+1\d{10}$")
    verified: bool = False


class HandoffService(StrictModel):
    id: str
    name: str


class HandoffPacket(StrictModel):
    tenant_id: str
    call_id: str
    caller: HandoffCaller
    intent: CallIntent
    service: HandoffService | None = None
    address: Address | None = None
    urgency: Literal["emergency", "urgent", "normal"] = "normal"
    booking_id: str | None = None
    emergency_ticket_id: str | None = None
    summary: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    requested_at: datetime

    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.tenant_id:
            missing.append("tenant_id")
        if not self.call_id:
            missing.append("call_id")
        if not self.caller.phone:
            missing.append("caller.phone")
        if not self.summary:
            missing.append("summary")
        if not self.reason:
            missing.append("reason")
        return missing

    @property
    def complete(self) -> bool:
        return not self.missing_fields()

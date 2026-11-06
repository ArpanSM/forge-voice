"""Domain records shared by adapters, policy and tools."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from forge_voice.models import StrictModel


class Address(StrictModel):
    line1: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(pattern=r"^\d{5}$")


class CustomerRecord(StrictModel):
    customer_id: str
    tenant_id: str
    name: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\+1\d{10}$")
    address: Address
    created_at: datetime


class SlotRecord(StrictModel):
    slot_id: str
    tenant_id: str
    service_id: str
    technician_id: str
    start: datetime
    end: datetime
    status: Literal["open", "booked"]


class BookingRecord(StrictModel):
    booking_id: str
    tenant_id: str
    customer_id: str
    service_id: str
    technician_id: str
    slot_id: str
    start: datetime
    end: datetime
    status: Literal["booked", "cancelled"]
    contact_phone: str
    address: Address
    reason: str | None = None
    confirmation_sms: str = "not_requested"
    confirmation_email: str = "not_requested"
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None = None


class TicketRecord(StrictModel):
    ticket_id: str
    tenant_id: str
    call_id: str
    customer_id: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None
    address: Address | None = None
    category: str
    severity: Literal["life_safety", "urgent", "priority"]
    description: str
    safety_instructions_given: list[str]
    transfer_mode: Literal["live", "callback"]
    transfer_id: str | None = None
    on_call_target: str
    callback_sla_minutes: int
    status: Literal["open", "assigned", "closed"] = "open"
    created_at: datetime


class CallbackRecord(StrictModel):
    callback_id: str
    tenant_id: str
    call_id: str
    name: str
    phone: str
    reason: str
    window_start: datetime
    window_end: datetime
    sla: str
    status: Literal["open", "done"] = "open"
    created_at: datetime


class EventRecord(StrictModel):
    event_id: int
    tenant_id: str
    call_id: str
    request_id: str
    tool: str
    result_code: str
    latency_ms: int
    args: dict[str, object] = Field(default_factory=dict)
    result: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class IdempotencyRecord(StrictModel):
    key: str
    tenant_id: str
    call_id: str
    intent: str
    target: str
    payload_hash: str
    result_json: str
    created_at: datetime
    token: str | None = None


class ConfirmationRecord(StrictModel):
    message_id: str
    tenant_id: str
    booking_id: str
    to: str
    channel: Literal["sms", "email"] = "sms"
    template: Literal["booking_confirmation"] = "booking_confirmation"
    status: Literal["queued", "failed"] = "queued"
    created_at: datetime


class TokenRecord(StrictModel):
    token: str
    tenant_id: str
    call_id: str
    intent: str
    target: str
    payload_hash: str
    issued_at: datetime
    expires_at: datetime
    used_at: datetime | None = None

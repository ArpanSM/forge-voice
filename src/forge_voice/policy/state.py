"""Explicit call state and terminal outcomes for the booking policy."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from forge_voice.domain import Address
from forge_voice.models import StrictModel


class CallIntent(StrEnum):
    book = "book"
    reschedule = "reschedule"
    cancel = "cancel"
    status = "status"
    emergency = "emergency"
    pricing_faq = "pricing_faq"
    human = "human"


class CallOutcome(StrEnum):
    booked = "booked"
    rescheduled = "rescheduled"
    cancelled = "cancelled"
    emergency_ticket = "emergency_ticket"
    transferred = "transferred"
    callback = "callback"
    info_only = "info_only"
    abandoned = "abandoned"
    failed = "failed"


class CallPhase(StrEnum):
    greet = "greet"
    identify_intent = "identify_intent"
    identify_customer = "identify_customer"
    collect_service = "collect_service"
    check_area = "check_area"
    get_availability = "get_availability"
    offer_slots = "offer_slots"
    readback = "readback"
    write_booking = "write_booking"
    send_confirmation = "send_confirmation"
    lookup = "lookup"
    change = "change"
    triage = "triage"
    safety = "safety"
    emergency_ticket = "emergency_ticket"
    transfer = "transfer"
    handoff = "handoff"
    callback = "callback"
    summarize = "summarize"
    done = "done"


class TransferStatus(StrEnum):
    connected = "connected"
    no_answer = "no_answer"
    queued_callback = "queued_callback"


class CustomerSnapshot(StrictModel):
    customer_id: str | None = None
    name: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\+1\d{10}$")
    address: Address
    verified: bool = False


class SlotOffer(StrictModel):
    slot_id: str
    service_id: str
    start: str
    end: str
    technician_id: str
    technician_name: str
    expires_at: str


class CallState(StrictModel):
    """Everything deterministic policy may reason about during one call."""

    tenant_id: str
    call_id: str
    caller_phone: str | None = None
    phase: CallPhase = CallPhase.greet
    intent: CallIntent | None = None
    customer: CustomerSnapshot | None = None
    service_id: str | None = None
    address: Address | None = None
    urgency: str = "normal"
    slots_offered: list[SlotOffer] = Field(default_factory=list)
    selected_slot_id: str | None = None
    confirmed_slot_id: str | None = None
    readback_done: bool = False
    readback_payload: dict[str, object] | None = None
    awaiting_confirmation: bool = False
    explicit_yes: bool = False
    confirmation_token: str | None = None
    change_count: int = 0
    write_count: int = 0
    outcome: CallOutcome | None = None
    transfer_status: TransferStatus | None = None
    booking_id: str | None = None
    ticket_id: str | None = None
    callback_id: str | None = None
    after_hours: bool = False

    @property
    def service(self) -> str | None:
        """Alias used by policy callers that think in services, not ids."""
        return self.service_id

    @property
    def confirmed_slot(self) -> str | None:
        return self.confirmed_slot_id or self.selected_slot_id

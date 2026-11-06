"""Typed inputs for the eight tools. Unknown fields fail closed."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from forge_voice.models import StrictModel


class AddressArgs(StrictModel):
    line1: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(min_length=1)


class CustomerArgs(StrictModel):
    name: str = Field(min_length=1)
    phone: str = Field(min_length=1)
    address: AddressArgs


class LookupCustomerArgs(StrictModel):
    phone: str | None = None
    name: str | None = None
    address: AddressArgs | None = None
    include_bookings: bool = False

    @model_validator(mode="after")
    def has_a_lookup_key(self) -> LookupCustomerArgs:
        if not self.phone and not self.name and not self.address:
            raise ValueError("phone or name/address is required")
        if self.address is not None and not self.name:
            raise ValueError("an address lookup also needs a name")
        return self


class ServiceAreaArgs(StrictModel):
    zip: str = Field(min_length=1)
    street_address: str | None = None
    service_id: str | None = None


class AvailabilityArgs(StrictModel):
    service_id: str = Field(min_length=1)
    zip: str = Field(min_length=1)
    preferred_date: str | None = None
    window_days: int = Field(default=7, ge=1, le=14)
    exclude_slot_ids: list[str] = Field(default_factory=list)


class BookAppointmentArgs(StrictModel):
    service_id: str = Field(min_length=1)
    slot_id: str = Field(min_length=1)
    customer: CustomerArgs


class RescheduleAppointmentArgs(StrictModel):
    booking_id: str = Field(min_length=1)
    new_slot_id: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=200)


CANCEL_REASONS = {
    "no_longer_needed",
    "found_another_provider",
    "price",
    "moved",
    "duplicate",
    "other",
}


class CancelAppointmentArgs(StrictModel):
    booking_id: str = Field(min_length=1)
    reason: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def reason_is_supported(self) -> CancelAppointmentArgs:
        if self.reason is not None and self.reason not in CANCEL_REASONS:
            raise ValueError(f"reason must be one of {sorted(CANCEL_REASONS)}")
        return self


class CallbackWindowArgs(StrictModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def end_after_start(self) -> CallbackWindowArgs:
        if self.end <= self.start:
            raise ValueError("callback_window.end must be after start")
        return self


class EmergencyTicketArgs(StrictModel):
    category: str = Field(min_length=1)
    severity: Literal["life_safety", "urgent", "priority"]
    customer: CustomerArgs
    description: str = Field(min_length=1, max_length=500)
    safety_instructions_given: list[str] = Field(min_length=1)
    transfer_mode: Literal["live", "callback"]
    callback_window: CallbackWindowArgs | None = None

    @model_validator(mode="after")
    def callback_needs_window(self) -> EmergencyTicketArgs:
        if self.transfer_mode == "callback" and self.callback_window is None:
            raise ValueError("callback_window is required for callback mode")
        return self


class TransferToHumanArgs(StrictModel):
    reason: Literal[
        "caller_request",
        "emergency",
        "ownership_failure",
        "tool_failure",
        "after_hours",
        "complex_request",
    ]
    urgency: Literal["emergency", "urgent", "normal"]
    mode: Literal["live", "callback"]
    packet: dict[str, object]
    callback_window: CallbackWindowArgs | None = None

    @model_validator(mode="after")
    def callback_needs_window(self) -> TransferToHumanArgs:
        if self.mode == "callback" and self.callback_window is None:
            raise ValueError("callback_window is required for callback mode")
        return self

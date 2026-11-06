"""In-memory booking policy for the voice spike.

The LLM talks; this module owns validation, confirmation and the one write. The
same policy should survive the switch from text mode to a real LiveKit transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class Service:
    service_id: str
    name: str
    duration_minutes: int


@dataclass(frozen=True)
class Slot:
    slot_id: str
    service_id: str
    technician: str
    start: str
    zip_codes: frozenset[str]
    available: bool = True


@dataclass(frozen=True)
class Customer:
    name: str
    phone: str
    address: str
    zip_code: str


@dataclass
class Booking:
    booking_id: str
    customer: Customer
    service: Service
    slot: Slot
    status: Literal["booked", "cancelled"] = "booked"


@dataclass
class BookingResult:
    ok: bool
    booking: Booking | None = None
    error: str | None = None
    replayed: bool = False


@dataclass
class BookingStore:
    services: dict[str, Service] = field(default_factory=dict)
    slots: dict[str, Slot] = field(default_factory=dict)
    bookings: dict[str, Booking] = field(default_factory=dict)
    idempotency: dict[str, tuple[str, Booking]] = field(default_factory=dict)
    _counter: int = 0

    def add_service(self, service: Service) -> None:
        self.services[service.service_id] = service

    def add_slot(self, slot: Slot) -> None:
        self.slots[slot.slot_id] = slot

    def get_availability(self, service_id: str, zip_code: str) -> list[Slot]:
        if service_id not in self.services:
            return []
        return [
            slot
            for slot in self.slots.values()
            if slot.service_id == service_id
            and slot.available
            and zip_code in slot.zip_codes
        ]

    def book_appointment(
        self,
        *,
        customer: Customer,
        service_id: str,
        slot_id: str,
        idempotency_key: str,
        confirmed: bool,
    ) -> BookingResult:
        """Book one slot. The caller must have read the details back to the customer."""
        if not confirmed:
            return BookingResult(ok=False, error="confirmation_required")

        service = self.services.get(service_id)
        if service is None:
            return BookingResult(ok=False, error="unknown_service")

        slot = self.slots.get(slot_id)
        if slot is None or slot.service_id != service_id:
            return BookingResult(ok=False, error="unknown_slot")

        args_key = f"{customer.phone}|{service_id}|{slot_id}"
        if idempotency_key in self.idempotency:
            stored_args, booking = self.idempotency[idempotency_key]
            if stored_args != args_key:
                return BookingResult(ok=False, error="idempotency_conflict")
            return BookingResult(ok=True, booking=booking, replayed=True)

        if not slot.available:
            return BookingResult(ok=False, error="slot_unavailable")
        if customer.zip_code not in slot.zip_codes:
            return BookingResult(ok=False, error="out_of_area")

        self._counter += 1
        booking = Booking(
            booking_id=f"bk_{self._counter:04d}",
            customer=customer,
            service=service,
            slot=slot,
        )
        self.bookings[booking.booking_id] = booking
        self.idempotency[idempotency_key] = (args_key, booking)
        self.slots[slot_id] = Slot(
            slot_id=slot.slot_id,
            service_id=slot.service_id,
            technician=slot.technician,
            start=slot.start,
            zip_codes=slot.zip_codes,
            available=False,
        )
        return BookingResult(ok=True, booking=booking)

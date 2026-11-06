"""One idempotent, atomic booking write behind the conversation policy.

The service owns confirmation-token checks, tenant scoping, offer expiry, no-double-booking,
ownership, the change cutoff and idempotency replay. It never talks to a model or a network.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from forge_voice.adapters.outbox import Outbox
from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.clock import Clock
from forge_voice.domain import (
    Address,
    BookingRecord,
    ConfirmationRecord,
    CustomerRecord,
    IdempotencyRecord,
)
from forge_voice.errors import ErrorCode, StableError
from forge_voice.models import StrictModel
from forge_voice.policy.confirmation import (
    ConfirmationTokenStore,
    TokenBinding,
    TokenStatus,
    payload_digest,
)
from forge_voice.tenants.errors import UnknownServiceError
from forge_voice.tenants.models import TenantConfig


class BookingError(StableError):
    """A safe, stable rejection from the booking policy."""


class CustomerInput(StrictModel):
    name: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\+1\d{10}$")
    address: Address


class Offer(StrictModel):
    slot_id: str
    service_id: str
    start: datetime
    end: datetime
    technician_id: str
    expires_at: datetime


class Availability(StrictModel):
    slots: list[Offer]
    timezone: str
    reason: Literal["ok", "no_slots", "out_of_area", "service_not_offered"]


class BookingWrite(StrictModel):
    booking: BookingRecord
    replayed: bool = False
    already_cancelled: bool = False


def canonical_booking_payload(
    service_id: str, slot_id: str, customer: CustomerInput
) -> dict[str, Any]:
    return {
        "service_id": service_id,
        "slot_id": slot_id,
        "customer": {
            "name": customer.name,
            "phone": customer.phone,
            "address": customer.address.model_dump(mode="json"),
        },
    }


def canonical_reschedule_payload(booking_id: str, new_slot_id: str) -> dict[str, Any]:
    return {"booking_id": booking_id, "new_slot_id": new_slot_id}


def canonical_cancel_payload(booking_id: str) -> dict[str, Any]:
    return {"booking_id": booking_id}


class BookingService:
    def __init__(
        self,
        tenant: TenantConfig,
        store: SQLiteAdapter,
        outbox: Outbox,
        clock: Clock,
        tokens: ConfirmationTokenStore | None = None,
    ) -> None:
        self.tenant = tenant
        self.store = store
        self.outbox = outbox
        self.clock = clock
        self.tokens = tokens or ConfirmationTokenStore(clock)
        self._offers: dict[str, Offer] = {}

    # ------------------------------------------------------------- availability
    def get_availability(
        self,
        service_id: str,
        zip_code: str,
        *,
        preferred_date: date | None = None,
        window_days: int = 7,
        exclude_slot_ids: tuple[str, ...] = (),
    ) -> Availability:
        try:
            self.tenant.require_service(service_id)
        except UnknownServiceError:
            return Availability(
                slots=[], timezone=self.tenant.timezone, reason="service_not_offered"
            )
        if not self.tenant.has_zip(zip_code):
            return Availability(slots=[], timezone=self.tenant.timezone, reason="out_of_area")
        if window_days < 1:
            raise BookingError(ErrorCode.invalid_argument, "window_days must be positive")
        window = min(window_days, 14)
        zone = ZoneInfo(self.tenant.timezone)
        local_now = self.clock.now.astimezone(zone)
        first_day = preferred_date or local_now.date()
        start_from = max(
            self.clock.now,
            datetime.combine(first_day, time.min, tzinfo=zone),
        )
        start_before = datetime.combine(first_day + timedelta(days=window), time.min, tzinfo=zone)
        horizon_end = datetime.combine(
            local_now.date() + timedelta(days=self.tenant.policies.booking_horizon_days),
            time.min,
            tzinfo=zone,
        )
        start_before = min(start_before, horizon_end)
        if start_from >= start_before:
            return Availability(slots=[], timezone=self.tenant.timezone, reason="no_slots")
        slots = self.store.list_open_slots(
            self.tenant.tenant_id,
            service_id=service_id,
            start_from=start_from,
            start_before=start_before,
            exclude_slot_ids=exclude_slot_ids,
        )
        offers: list[Offer] = []
        for slot in slots[: self.tenant.policies.max_slots_offered]:
            offer = Offer(
                slot_id=slot.slot_id,
                service_id=slot.service_id,
                start=slot.start,
                end=slot.end,
                technician_id=slot.technician_id,
                expires_at=self.clock.now
                + timedelta(seconds=self.tenant.policies.offer_ttl_seconds),
            )
            self._offers[slot.slot_id] = offer
            offers.append(offer)
        return Availability(
            slots=offers,
            timezone=self.tenant.timezone,
            reason="ok" if offers else "no_slots",
        )

    # ---------------------------------------------------------------------- book
    def book(
        self,
        *,
        call_id: str,
        customer: CustomerInput,
        service_id: str,
        slot_id: str,
        confirmed: bool,
        token: str | None,
    ) -> BookingWrite:
        payload = canonical_booking_payload(service_id, slot_id, customer)
        key = self.idempotency_key(call_id, "book", slot_id)
        replay = self._replay(key, payload)
        if replay is not None:
            self._audit(call_id, "booking_replayed", "book", payload)
            return replay

        self._require_confirmation_presence(confirmed, token)
        self._require_service(service_id)
        if not self.tenant.has_zip(customer.address.zip):
            raise BookingError(
                ErrorCode.out_of_area,
                f"We do not serve ZIP {customer.address.zip}.",
            )
        offer = self._offers.get(slot_id)
        if offer is None:
            raise BookingError(ErrorCode.slot_unavailable, "That slot is no longer offered.")
        if offer.expires_at <= self.clock.now:
            raise BookingError(
                ErrorCode.slot_expired,
                "That offer expired. I can refresh the available times.",
                retryable=True,
            )
        if offer.service_id != service_id:
            raise BookingError(ErrorCode.slot_unavailable, "That slot is for another service.")
        binding = self._check_confirmation(
            confirmed=confirmed,
            token=token,
            call_id=call_id,
            intent="book",
            target=slot_id,
            payload=payload,
        )

        customer_record = self._customer_for_write(customer)
        now = self.clock.now
        with self.store.transaction():
            slot = self.store.get_slot(self.tenant.tenant_id, slot_id)
            if slot is None or slot.status != "open":
                raise BookingError(ErrorCode.slot_unavailable, "That slot was just taken.")
            if customer_record is None:
                customer_record = self._insert_new_customer(customer, now)
            booking = BookingRecord(
                booking_id=self._next_booking_id(),
                tenant_id=self.tenant.tenant_id,
                customer_id=customer_record.customer_id,
                service_id=service_id,
                technician_id=slot.technician_id,
                slot_id=slot.slot_id,
                start=slot.start,
                end=slot.end,
                status="booked",
                contact_phone=customer.phone,
                address=customer.address,
                created_at=now,
                updated_at=now,
            )
            self.store.create_booking(booking)
            self._set_slot_status(slot.slot_id, "booked")
            self._put_idempotency(key, call_id, "book", slot_id, payload, booking, now)
            self._audit(call_id, "booking_committed", "book", payload)
        self.tokens.consume(token or "", binding)
        return self._finish_booking(booking, key, call_id)

    # --------------------------------------------------------------- reschedule
    def reschedule(
        self,
        *,
        call_id: str,
        booking_id: str,
        new_slot_id: str,
        caller_phone: str | None,
        ownership_verified: bool,
        confirmed: bool,
        token: str | None,
        reason: str | None = None,
    ) -> BookingWrite:
        payload = canonical_reschedule_payload(booking_id, new_slot_id)
        key = self.idempotency_key(call_id, "reschedule", new_slot_id)
        replay = self._replay(key, payload)
        if replay is not None:
            self._audit(call_id, "booking_replayed", "reschedule", payload)
            return replay

        booking = self._load_booking(booking_id)
        self._check_ownership(booking, caller_phone, ownership_verified)
        if booking.status == "cancelled":
            raise BookingError(ErrorCode.already_cancelled, "That booking is already cancelled.")
        self._check_cutoff(booking)
        self._require_confirmation_presence(confirmed, token)
        offer = self._offers.get(new_slot_id)
        if offer is None:
            raise BookingError(ErrorCode.slot_unavailable, "That slot is no longer offered.")
        if offer.expires_at <= self.clock.now:
            raise BookingError(
                ErrorCode.slot_expired,
                "That offer expired. I can refresh the available times.",
                retryable=True,
            )
        if offer.service_id != booking.service_id:
            raise BookingError(ErrorCode.slot_unavailable, "That slot is for another service.")
        binding = self._check_confirmation(
            confirmed=confirmed,
            token=token,
            call_id=call_id,
            intent="reschedule",
            target=new_slot_id,
            payload=payload,
        )

        now = self.clock.now
        with self.store.transaction():
            current = self.store.get_booking(self.tenant.tenant_id, booking_id)
            if current is None or current.status != "booked":
                raise BookingError(ErrorCode.slot_unavailable, "That booking is no longer active.")
            new_slot = self.store.get_slot(self.tenant.tenant_id, new_slot_id)
            if new_slot is None or new_slot.status != "open":
                raise BookingError(ErrorCode.slot_unavailable, "That slot was just taken.")
            if current.slot_id != new_slot_id:
                self._set_slot_status(current.slot_id, "open")
            self.store.move_booking(
                self.tenant.tenant_id, booking_id, slot=new_slot, updated_at=now
            )
            self._set_slot_status(new_slot_id, "booked")
            moved = self.store.get_booking(self.tenant.tenant_id, booking_id)
            assert moved is not None
            self._put_idempotency(key, call_id, "reschedule", new_slot_id, payload, moved, now)
            self._audit(call_id, "booking_rescheduled", "reschedule", payload)
        self.tokens.consume(token or "", binding)
        return self._finish_booking(moved, key, call_id)

    # ------------------------------------------------------------------- cancel
    def cancel(
        self,
        *,
        call_id: str,
        booking_id: str,
        caller_phone: str | None,
        ownership_verified: bool,
        confirmed: bool,
        token: str | None,
        reason: str | None = None,
    ) -> BookingWrite:
        payload = canonical_cancel_payload(booking_id)
        key = self.idempotency_key(call_id, "cancel", booking_id)
        replay = self._replay(key, payload)
        if replay is not None:
            self._audit(call_id, "booking_replayed", "cancel", payload)
            return replay

        booking = self._load_booking(booking_id)
        self._check_ownership(booking, caller_phone, ownership_verified)
        if booking.status == "cancelled":
            return BookingWrite(booking=booking, already_cancelled=True)
        self._check_cutoff(booking)
        self._require_confirmation_presence(confirmed, token)
        binding = self._check_confirmation(
            confirmed=confirmed,
            token=token,
            call_id=call_id,
            intent="cancel",
            target=booking_id,
            payload=payload,
        )

        now = self.clock.now
        with self.store.transaction():
            current = self.store.get_booking(self.tenant.tenant_id, booking_id)
            if current is None:
                raise BookingError(ErrorCode.not_found, "No matching booking.")
            if current.status == "cancelled":
                return BookingWrite(booking=current, already_cancelled=True)
            self.store.cancel_booking(
                self.tenant.tenant_id, booking_id, reason=reason, cancelled_at=now
            )
            self._set_slot_status(current.slot_id, "open")
            cancelled = self.store.get_booking(self.tenant.tenant_id, booking_id)
            assert cancelled is not None
            self._put_idempotency(key, call_id, "cancel", booking_id, payload, cancelled, now)
            self._audit(call_id, "booking_cancelled", "cancel", payload)
        self.tokens.consume(token or "", binding)
        return self._finish_booking(cancelled, key, call_id)

    def replay(
        self,
        *,
        call_id: str,
        intent: str,
        target: str,
        payload: Mapping[str, Any],
    ) -> BookingWrite | None:
        return self._replay(self.idempotency_key(call_id, intent, target), payload)

    def idempotency_key(self, call_id: str, intent: str, target: str) -> str:
        return f"{self.tenant.tenant_id}:{call_id}:{intent}:{target}"

    # ------------------------------------------------------------------ helpers
    def _replay(self, key: str, payload: Mapping[str, Any]) -> BookingWrite | None:
        record = self.store.get_idempotency(self.tenant.tenant_id, key)
        if record is None:
            return None
        if record.payload_hash != payload_digest(payload):
            raise BookingError(
                ErrorCode.idempotency_conflict,
                "That retry does not match the original request.",
            )
        write = BookingWrite.model_validate_json(record.result_json)
        return write.model_copy(update={"replayed": True})

    def _require_service(self, service_id: str) -> None:
        try:
            self.tenant.require_service(service_id)
        except UnknownServiceError as exc:
            raise BookingError(
                ErrorCode.service_not_offered,
                f"We do not offer {service_id.replace('_', ' ')}.",
            ) from exc

    def _require_confirmation_presence(self, confirmed: bool, token: str | None) -> None:
        if not confirmed or not token:
            raise BookingError(
                ErrorCode.explicit_confirmation_required,
                "Please confirm the read-back with an explicit yes before I write anything.",
            )

    def _check_confirmation(
        self,
        *,
        confirmed: bool,
        token: str | None,
        call_id: str,
        intent: str,
        target: str,
        payload: Mapping[str, Any],
    ) -> TokenBinding:
        self._require_confirmation_presence(confirmed, token)
        binding = TokenBinding(
            tenant_id=self.tenant.tenant_id,
            call_id=call_id,
            intent=intent,
            target=target,
            payload_hash=payload_digest(payload),
        )
        check = self.tokens.validate(token, binding)
        if check.status in {TokenStatus.used, TokenStatus.expired}:
            raise BookingError(
                ErrorCode.confirmation_expired,
                "That confirmation is no longer valid. Please confirm again.",
            )
        if check.status is not TokenStatus.valid:
            raise BookingError(
                ErrorCode.explicit_confirmation_required,
                "A valid policy confirmation is required before a write.",
            )
        return binding

    def _load_booking(self, booking_id: str) -> BookingRecord:
        booking = self.store.get_booking(self.tenant.tenant_id, booking_id)
        if booking is None:
            raise BookingError(ErrorCode.not_found, "No matching booking.")
        return booking

    @staticmethod
    def _check_ownership(
        booking: BookingRecord, caller_phone: str | None, ownership_verified: bool
    ) -> None:
        if ownership_verified:
            return
        if caller_phone and caller_phone == booking.contact_phone:
            return
        raise BookingError(
            ErrorCode.ownership_mismatch,
            "I could not verify ownership of that booking.",
        )

    def _check_cutoff(self, booking: BookingRecord) -> None:
        cutoff = timedelta(minutes=self.tenant.policies.change_cutoff_minutes)
        if booking.start - self.clock.now < cutoff:
            raise BookingError(
                ErrorCode.cutoff_passed,
                "That appointment is inside the change window; a dispatcher needs to help.",
            )

    def _customer_for_write(self, customer: CustomerInput) -> CustomerRecord | None:
        matches = self.store.find_customers(self.tenant.tenant_id, phone=customer.phone)
        if matches:
            return matches[0]
        return None

    def _insert_new_customer(self, customer: CustomerInput, now: datetime) -> CustomerRecord:
        count = len(self.store.list_customers(self.tenant.tenant_id))
        record = CustomerRecord(
            customer_id=f"cus_{self.tenant.tenant_id}_{count + 1:04d}",
            tenant_id=self.tenant.tenant_id,
            name=customer.name,
            phone=customer.phone,
            address=customer.address,
            created_at=now,
        )
        self.store.insert_customer(record)
        return record

    def _next_booking_id(self) -> str:
        count = self.store.count_bookings(self.tenant.tenant_id)
        return f"bk_{self.tenant.tenant_id}_{count + 1:04d}"

    def _set_slot_status(self, slot_id: str, status: str) -> None:
        self.store.set_slot_status_in_transaction(self.tenant.tenant_id, slot_id, status)

    def _put_idempotency(
        self,
        key: str,
        call_id: str,
        intent: str,
        target: str,
        payload: Mapping[str, Any],
        booking: BookingRecord,
        now: datetime,
    ) -> None:
        result = BookingWrite(booking=booking)
        self.store.put_idempotency(
            IdempotencyRecord(
                key=key,
                tenant_id=self.tenant.tenant_id,
                call_id=call_id,
                intent=intent,
                target=target,
                payload_hash=payload_digest(payload),
                result_json=result.model_dump_json(),
                created_at=now,
            )
        )

    def _finish_booking(self, booking: BookingRecord, key: str, call_id: str) -> BookingWrite:
        status = self._queue_confirmation(booking, call_id)
        updated = self.store.get_booking(self.tenant.tenant_id, booking.booking_id)
        assert updated is not None
        write = BookingWrite(booking=updated.model_copy(update={"confirmation_sms": status}))
        existing = self.store.get_idempotency(self.tenant.tenant_id, key)
        if existing is not None:
            result = BookingWrite(booking=updated.model_copy(update={"confirmation_sms": status}))
            self.store.update_idempotency_result(
                self.tenant.tenant_id, key, result.model_dump_json()
            )
        return write

    def _queue_confirmation(self, booking: BookingRecord, call_id: str) -> str:
        now = self.clock.now
        message_id = self.store.next_message_id(self.tenant.tenant_id)
        record = ConfirmationRecord(
            message_id=message_id,
            tenant_id=self.tenant.tenant_id,
            booking_id=booking.booking_id,
            to=booking.contact_phone,
            created_at=now,
        )
        try:
            self.outbox.send(record)
            status = "queued"
        except OSError:
            status = "failed"
            record = record.model_copy(update={"status": "failed"})
        self.store.add_confirmation(record)
        self.store.set_booking_confirmation(
            self.tenant.tenant_id,
            booking.booking_id,
            sms=status,
            email="not_requested",
        )
        self._audit(
            call_id,
            "confirmation_queued" if status == "queued" else "confirmation_failed",
            "send_confirmation",
            {"booking_id": booking.booking_id},
        )
        return status

    def _audit(self, call_id: str, tool: str, result_code: str, payload: Mapping[str, Any]) -> None:
        self.store.append_event(
            tenant_id=self.tenant.tenant_id,
            call_id=call_id,
            request_id=f"req_{call_id}_{tool}",
            tool=tool,
            result_code=result_code,
            latency_ms=0,
            args={"operation": tool},
            result={"payload": dict(payload)},
            created_at=self.clock.now,
        )

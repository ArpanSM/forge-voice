"""Deterministic synthetic seed data for both tenants.

Anchor time is fixed at Monday 2026-11-09 08:00 America/Los_Angeles. No wall clock or random
source is used, so repeated generation is byte-identical. Slot generation is non-overlapping
per technician per day; a booking interval is never left open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from forge_voice.models import StrictModel
from forge_voice.tenants.models import TenantConfig

TZ = ZoneInfo("America/Los_Angeles")
ANCHOR_DATE = date(2026, 11, 9)
ANCHOR_DATETIME = datetime(2026, 11, 9, 8, 0, tzinfo=TZ)
BUSINESS_DAY_COUNT = 14
SLOT_START = time(9, 0)
SLOT_END = time(17, 0)
SLOT_GAP_MINUTES = 30

TENANT_PREFIX = {"harborlight": "hl", "summit": "sm"}


class SeedDataError(ValueError):
    """A seed fixture is missing a tenant map or is internally inconsistent."""


class SeedAddress(StrictModel):
    line1: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(pattern=r"^[A-Z]{2}$")
    zip: str = Field(pattern=r"^\d{5}$")


class SeedCustomer(StrictModel):
    customer_id: str = Field(pattern=r"^cus_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    phone: str = Field(pattern=r"^\+1\d{10}$")
    address: SeedAddress
    created_at: datetime


class SeedConfirmation(StrictModel):
    sms: Literal["queued", "not_requested"]
    email: Literal["queued", "not_requested"]


class SeedBooking(StrictModel):
    booking_id: str = Field(pattern=r"^bk_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    customer_id: str = Field(pattern=r"^cus_[a-z0-9_]+$")
    service_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    technician_id: str = Field(pattern=r"^tech_[a-z][a-z0-9_]*$")
    slot_id: str = Field(pattern=r"^slot_[a-z0-9_]+$")
    start: datetime
    end: datetime
    status: Literal["booked", "cancelled"]
    contact_phone: str = Field(pattern=r"^\+1\d{10}$")
    address: SeedAddress
    confirmation: SeedConfirmation


class SeedSlot(StrictModel):
    slot_id: str = Field(pattern=r"^slot_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    service_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    technician_id: str = Field(pattern=r"^tech_[a-z][a-z0-9_]*$")
    start: datetime
    end: datetime
    status: Literal["open", "booked"]


class SeedCallRecord(StrictModel):
    call_id: str = Field(pattern=r"^call_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    caller_phone: str | None = Field(default=None, pattern=r"^\+1\d{10}$")
    intent: Literal["book", "reschedule", "cancel", "status", "emergency", "pricing_faq", "human"]
    outcome: Literal[
        "booked",
        "rescheduled",
        "cancelled",
        "emergency_ticket",
        "transferred",
        "callback",
        "info_only",
        "abandoned",
        "failed",
    ]
    started_at: datetime
    recording_ref: Literal["text_only"]
    booking_id: str | None = None
    ticket_id: str | None = None
    qa_flags: list[str] = Field(default_factory=list)


class SeedSmsMessage(StrictModel):
    message_id: str = Field(pattern=r"^sms_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    booking_id: str = Field(pattern=r"^bk_[a-z0-9_]+$")
    to: str = Field(pattern=r"^\+1\d{10}$")
    channel: Literal["sms"]
    template: Literal["booking_confirmation"]
    status: Literal["queued"]
    created_at: datetime


class SeedSms(StrictModel):
    messages: list[SeedSmsMessage]


class SeedCrm(StrictModel):
    customer_ids: list[str]
    notes: list[str]


class SeedCalendar(StrictModel):
    timezone: str
    booked_slot_ids: list[str]
    open_slot_ids: list[str]


class TenantSeed(StrictModel):
    schema_version: Literal[1]
    tenant_id: str
    anchor: datetime
    customers: list[SeedCustomer]
    bookings: list[SeedBooking]
    slots: list[SeedSlot]
    calls: list[SeedCallRecord]
    calendar: SeedCalendar
    crm: SeedCrm
    sms: SeedSms


@dataclass(frozen=True)
class BookingSpec:
    booking_id: str
    customer_id: str
    service_id: str
    technician_id: str
    start: str


CUSTOMERS: dict[str, list[dict[str, Any]]] = {
    "harborlight": [
        {
            "customer_id": "cus_0001",
            "name": "Sam Rivera",
            "phone": "+14155550101",
            "address": {
                "line1": "12 Alder St",
                "city": "San Francisco",
                "state": "CA",
                "zip": "94107",
            },
        },
        {
            "customer_id": "cus_0002",
            "name": "Dana Whitfield",
            "phone": "+14155550104",
            "address": {
                "line1": "9 Juniper Ct",
                "city": "San Francisco",
                "state": "CA",
                "zip": "94117",
            },
        },
        {
            "customer_id": "cus_0003",
            "name": "Riley Chen",
            "phone": "+14155550112",
            "address": {
                "line1": "21 Harbor Blvd",
                "city": "San Francisco",
                "state": "CA",
                "zip": "94118",
            },
        },
        {
            "customer_id": "cus_0004",
            "name": "Morgan Lee",
            "phone": "+14155550113",
            "address": {
                "line1": "44 Cypress Ave",
                "city": "San Francisco",
                "state": "CA",
                "zip": "94110",
            },
        },
    ],
    "summit": [
        {
            "customer_id": "cus_summit_0001",
            "name": "Priya Shah",
            "phone": "+14085550101",
            "address": {
                "line1": "88 Meridian Way",
                "city": "San Jose",
                "state": "CA",
                "zip": "95125",
            },
        },
        {
            "customer_id": "cus_summit_0002",
            "name": "Noah Kim",
            "phone": "+14085550102",
            "address": {
                "line1": "14 Guadalupe Pkwy",
                "city": "San Jose",
                "state": "CA",
                "zip": "95110",
            },
        },
    ],
}

BOOKINGS: dict[str, tuple[BookingSpec, ...]] = {
    "harborlight": (
        BookingSpec("bk_0001", "cus_0001", "drain_cleaning", "tech_alex", "2026-11-09T09:00:00"),
        BookingSpec("bk_0002", "cus_0001", "leak_repair", "tech_alex", "2026-11-10T13:00:00"),
        BookingSpec("bk_0003", "cus_0003", "ac_repair", "tech_blair", "2026-11-09T09:30:00"),
        BookingSpec("bk_0004", "cus_0002", "furnace_repair", "tech_blair", "2026-11-12T11:00:00"),
    ),
    "summit": (
        BookingSpec(
            "bk_summit_0001",
            "cus_summit_0001",
            "ac_repair",
            "tech_casey",
            "2026-11-11T09:00:00",
        ),
        BookingSpec(
            "bk_summit_0002",
            "cus_summit_0001",
            "ac_repair",
            "tech_casey",
            "2026-11-13T13:00:00",
        ),
    ),
}

CALLS: dict[str, list[dict[str, Any]]] = {
    "harborlight": [
        {
            "call_id": "call_hl_0001",
            "caller_phone": "+14155550101",
            "intent": "book",
            "outcome": "booked",
            "booking_id": "bk_0001",
        },
        {
            "call_id": "call_hl_0002",
            "caller_phone": "+14155550112",
            "intent": "reschedule",
            "outcome": "transferred",
            "booking_id": "bk_0003",
        },
        {
            "call_id": "call_hl_0003",
            "caller_phone": "+14155550104",
            "intent": "emergency",
            "outcome": "emergency_ticket",
            "ticket_id": "em_0001",
        },
        {
            "call_id": "call_hl_0004",
            "caller_phone": "+14155550113",
            "intent": "pricing_faq",
            "outcome": "info_only",
        },
    ],
    "summit": [
        {
            "call_id": "call_sm_0001",
            "caller_phone": "+14085550101",
            "intent": "book",
            "outcome": "booked",
            "booking_id": "bk_summit_0001",
        },
        {
            "call_id": "call_sm_0002",
            "caller_phone": "+14085550102",
            "intent": "human",
            "outcome": "callback",
        },
        {
            "call_id": "call_sm_0003",
            "caller_phone": "+14085550101",
            "intent": "pricing_faq",
            "outcome": "info_only",
        },
    ],
}


def _business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def _at(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, tzinfo=TZ)


def _start_from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def _overlaps(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    return first_start < second_end and second_start < first_end


def _customer_map(tenant: TenantConfig) -> list[dict[str, Any]]:
    customers = CUSTOMERS.get(tenant.tenant_id)
    if customers is None:
        raise SeedDataError(f"no seed customers configured for tenant {tenant.tenant_id!r}")
    return customers


def _booking_specs(tenant: TenantConfig) -> tuple[BookingSpec, ...]:
    specs = BOOKINGS.get(tenant.tenant_id)
    if specs is None:
        raise SeedDataError(f"no seed bookings configured for tenant {tenant.tenant_id!r}")
    return specs


def _call_specs(tenant: TenantConfig) -> list[dict[str, Any]]:
    calls = CALLS.get(tenant.tenant_id)
    if calls is None:
        raise SeedDataError(f"no seed calls configured for tenant {tenant.tenant_id!r}")
    return calls


def _generate_open_slots(tenant: TenantConfig, prefix: str) -> list[SeedSlot]:
    """Create sequential, non-overlapping slots for each technician's workday."""
    slots: list[SeedSlot] = []
    sequence = 1
    for day_index, day in enumerate(_business_days(ANCHOR_DATE, BUSINESS_DAY_COUNT)):
        for technician in tenant.dispatch.technicians:
            services = [service for service in tenant.services if service.id in technician.skills]
            if not services:
                continue
            offset = day_index % len(services)
            ordered = services[offset:] + services[:offset]
            cursor = _at(day, SLOT_START)
            day_end = _at(day, SLOT_END)
            for service in ordered:
                end = cursor + timedelta(minutes=service.duration_minutes)
                if end > day_end:
                    continue
                slots.append(
                    SeedSlot(
                        slot_id=f"slot_{prefix}_{sequence:05d}",
                        tenant_id=tenant.tenant_id,
                        service_id=service.id,
                        technician_id=technician.id,
                        start=cursor,
                        end=end,
                        status="open",
                    )
                )
                sequence += 1
                cursor = end + timedelta(minutes=SLOT_GAP_MINUTES)
    return slots


def _assign_bookings(
    tenant: TenantConfig,
    prefix: str,
    customers_by_id: dict[str, SeedCustomer],
    slots: list[SeedSlot],
) -> list[SeedBooking]:
    bookings: list[SeedBooking] = []
    slots_by_key = {(slot.service_id, slot.technician_id, slot.start): slot for slot in slots}
    special_sequence = 1
    for spec in _booking_specs(tenant):
        service = tenant.require_service(spec.service_id)
        customer = customers_by_id[spec.customer_id]
        start = _start_from_iso(spec.start)
        end = start + timedelta(minutes=service.duration_minutes)
        key = (service.id, spec.technician_id, start)
        slot = slots_by_key.get(key)
        if slot is None:
            slot = SeedSlot(
                slot_id=f"slot_{prefix}_special_{special_sequence:04d}",
                tenant_id=tenant.tenant_id,
                service_id=service.id,
                technician_id=spec.technician_id,
                start=start,
                end=end,
                status="open",
            )
            special_sequence += 1
            slots.append(slot)
            slots_by_key[key] = slot
        if slot.status != "open":
            raise SeedDataError(f"booking {spec.booking_id} reuses non-open slot {slot.slot_id}")

        overlapping_ids = {
            candidate.slot_id
            for candidate in slots
            if candidate.technician_id == spec.technician_id
            and candidate.status == "open"
            and candidate.slot_id != slot.slot_id
            and _overlaps(candidate.start, candidate.end, start, end)
        }
        if overlapping_ids:
            slots[:] = [
                candidate for candidate in slots if candidate.slot_id not in overlapping_ids
            ]
            slots_by_key = {
                (candidate.service_id, candidate.technician_id, candidate.start): candidate
                for candidate in slots
            }

        slot.status = "booked"
        bookings.append(
            SeedBooking(
                booking_id=spec.booking_id,
                tenant_id=tenant.tenant_id,
                customer_id=customer.customer_id,
                service_id=service.id,
                technician_id=spec.technician_id,
                slot_id=slot.slot_id,
                start=slot.start,
                end=slot.end,
                status="booked",
                contact_phone=customer.phone,
                address=customer.address,
                confirmation=SeedConfirmation(sms="queued", email="not_requested"),
            )
        )
    return bookings


def validate_tenant_seed(seed: TenantSeed, tenant: TenantConfig) -> None:
    """Reject a seed whose ZIPs, skills, references or calendar are inconsistent."""
    if seed.tenant_id != tenant.tenant_id:
        raise SeedDataError(
            f"seed tenant {seed.tenant_id!r} does not match config {tenant.tenant_id!r}"
        )

    customer_ids = [customer.customer_id for customer in seed.customers]
    if len(customer_ids) != len(set(customer_ids)):
        raise SeedDataError(f"duplicate customer ids in seed for {tenant.tenant_id}")
    customers = {customer.customer_id: customer for customer in seed.customers}
    for customer in seed.customers:
        if customer.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"customer {customer.customer_id} has the wrong tenant")
        if not tenant.has_zip(customer.address.zip):
            raise SeedDataError(
                f"customer {customer.customer_id} ZIP {customer.address.zip} is not served"
            )

    service_ids = {service.id for service in tenant.services}
    technicians = {technician.id: technician for technician in tenant.dispatch.technicians}
    slot_ids = [slot.slot_id for slot in seed.slots]
    if len(slot_ids) != len(set(slot_ids)):
        raise SeedDataError(f"duplicate slot ids in seed for {tenant.tenant_id}")
    slots = {slot.slot_id: slot for slot in seed.slots}
    for slot in seed.slots:
        if slot.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"slot {slot.slot_id} has the wrong tenant")
        if slot.service_id not in service_ids:
            raise SeedDataError(f"slot {slot.slot_id} references unknown service")
        technician = technicians.get(slot.technician_id)
        if technician is None:
            raise SeedDataError(f"slot {slot.slot_id} references unknown technician")
        if slot.service_id not in technician.skills:
            raise SeedDataError(
                f"technician {technician.id} lacks skill {slot.service_id} for {slot.slot_id}"
            )
        if slot.end <= slot.start:
            raise SeedDataError(f"slot {slot.slot_id} ends before it starts")

    booking_ids = [booking.booking_id for booking in seed.bookings]
    if len(booking_ids) != len(set(booking_ids)):
        raise SeedDataError(f"duplicate booking ids in seed for {tenant.tenant_id}")
    bookings = {booking.booking_id: booking for booking in seed.bookings}
    for booking in seed.bookings:
        if booking.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"booking {booking.booking_id} has the wrong tenant")
        customer = customers.get(booking.customer_id)
        if customer is None:
            raise SeedDataError(f"booking {booking.booking_id} references unknown customer")
        if booking.service_id not in service_ids:
            raise SeedDataError(f"booking {booking.booking_id} references unknown service")
        technician = technicians.get(booking.technician_id)
        if technician is None:
            raise SeedDataError(f"booking {booking.booking_id} references unknown technician")
        if booking.service_id not in technician.skills:
            raise SeedDataError(
                f"technician {technician.id} lacks skill {booking.service_id} "
                f"for booking {booking.booking_id}"
            )
        slot = slots.get(booking.slot_id)
        if slot is None:
            raise SeedDataError(f"booking {booking.booking_id} references unknown slot")
        if (
            slot.service_id != booking.service_id
            or slot.technician_id != booking.technician_id
            or slot.start != booking.start
            or slot.end != booking.end
            or slot.status != "booked"
        ):
            raise SeedDataError(f"booking {booking.booking_id} disagrees with its slot")
        if booking.contact_phone != customer.phone:
            raise SeedDataError(f"booking {booking.booking_id} contact phone mismatch")
        if booking.address != customer.address:
            raise SeedDataError(f"booking {booking.booking_id} address mismatch")

    known_phones = {customer.phone for customer in seed.customers}
    for call in seed.calls:
        if call.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"call {call.call_id} has the wrong tenant")
        if call.caller_phone is not None and call.caller_phone not in known_phones:
            raise SeedDataError(f"call {call.call_id} references an unknown caller")
        if call.booking_id is not None and call.booking_id not in bookings:
            raise SeedDataError(f"call {call.call_id} references unknown booking")

    for message in seed.sms.messages:
        if message.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"SMS {message.message_id} has the wrong tenant")
        booking = bookings.get(message.booking_id)
        if booking is None:
            raise SeedDataError(f"SMS {message.message_id} references unknown booking")
        if message.to != booking.contact_phone:
            raise SeedDataError(f"SMS {message.message_id} phone mismatch")

    booked_ids = sorted(booking.slot_id for booking in seed.bookings)
    open_ids = sorted(slot.slot_id for slot in seed.slots if slot.status == "open")
    if seed.calendar.booked_slot_ids != booked_ids:
        raise SeedDataError("calendar booked slots do not match bookings")
    if seed.calendar.open_slot_ids != open_ids:
        raise SeedDataError("calendar open slots do not match slot status")
    if set(booked_ids) & set(open_ids):
        raise SeedDataError("a booked slot is still listed as open")

    open_slots = [slot for slot in seed.slots if slot.status == "open"]
    for index, first in enumerate(open_slots):
        for second in open_slots[index + 1 :]:
            if first.technician_id != second.technician_id:
                continue
            if _overlaps(first.start, first.end, second.start, second.end):
                raise SeedDataError(
                    f"open slots {first.slot_id} and {second.slot_id} overlap for "
                    f"{first.technician_id}"
                )

    for index, first in enumerate(seed.bookings):
        for second in seed.bookings[index + 1 :]:
            if first.technician_id != second.technician_id:
                continue
            if _overlaps(first.start, first.end, second.start, second.end):
                raise SeedDataError(
                    f"bookings {first.booking_id} and {second.booking_id} overlap for "
                    f"{first.technician_id}"
                )


def build_tenant_seed(tenant: TenantConfig) -> TenantSeed:
    """Build and validate the deterministic calendar, CRM, booking and outbox seed."""
    prefix = TENANT_PREFIX.get(tenant.tenant_id)
    if prefix is None:
        raise SeedDataError(f"no seed prefix configured for tenant {tenant.tenant_id!r}")

    customers = [
        SeedCustomer(
            tenant_id=tenant.tenant_id,
            created_at=ANCHOR_DATETIME - timedelta(days=30),
            **customer,
        )
        for customer in _customer_map(tenant)
    ]
    customers_by_id = {customer.customer_id: customer for customer in customers}

    slots = _generate_open_slots(tenant, prefix)
    bookings = _assign_bookings(tenant, prefix, customers_by_id, slots)

    calls = [
        SeedCallRecord(
            tenant_id=tenant.tenant_id,
            started_at=ANCHOR_DATETIME - timedelta(days=3, minutes=index * 17),
            recording_ref="text_only",
            **call,
        )
        for index, call in enumerate(_call_specs(tenant))
    ]
    sms_messages = [
        SeedSmsMessage(
            message_id=f"sms_{prefix}_{index + 1:04d}",
            tenant_id=tenant.tenant_id,
            booking_id=booking.booking_id,
            to=booking.contact_phone,
            channel="sms",
            template="booking_confirmation",
            status="queued",
            created_at=ANCHOR_DATETIME - timedelta(days=1, minutes=index * 11),
        )
        for index, booking in enumerate(bookings)
    ]

    booked = sorted(booking.slot_id for booking in bookings)
    booked_set = set(booked)
    seed = TenantSeed(
        schema_version=1,
        tenant_id=tenant.tenant_id,
        anchor=ANCHOR_DATETIME,
        customers=customers,
        bookings=bookings,
        slots=slots,
        calls=calls,
        calendar=SeedCalendar(
            timezone=tenant.timezone,
            booked_slot_ids=booked,
            open_slot_ids=sorted(slot.slot_id for slot in slots if slot.slot_id not in booked_set),
        ),
        crm=SeedCrm(
            customer_ids=[customer.customer_id for customer in customers],
            notes=["Synthetic CRM seed; no real customer data."],
        ),
        sms=SeedSms(messages=sms_messages),
    )
    validate_tenant_seed(seed, tenant)
    return seed

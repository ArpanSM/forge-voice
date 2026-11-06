"""Deterministic synthetic seed data for both tenants.

Anchor time is fixed at Monday 2026-11-09 08:00 America/Los_Angeles. No wall clock or random
source is used, so repeated generation is byte-identical. Slots follow each tenant's configured
business hours, skip holidays and never overlap per technician; a booking interval is never
left open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field

from forge_voice.models import StrictModel, ensure_unique
from forge_voice.tenants.models import Phone, TenantConfig, Zip

TZ = ZoneInfo("America/Los_Angeles")
ANCHOR_DATE = date(2026, 11, 9)
ANCHOR_DATETIME = datetime(2026, 11, 9, 8, 0, tzinfo=TZ)
CALENDAR_DAY_COUNT = 21
SLOT_GAP_MINUTES = 30

TENANT_PREFIX = {"harborlight": "hl", "summit": "sm"}


class SeedDataError(ValueError):
    """A seed fixture is missing a tenant map or is internally inconsistent."""


class SeedAddress(StrictModel):
    line1: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str = Field(pattern=r"^[A-Z]{2}$")
    zip: Zip


class SeedCustomer(StrictModel):
    customer_id: str = Field(pattern=r"^cus_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    phone: Phone
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
    contact_phone: Phone
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
    caller_phone: Phone | None = None
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
    booking_id: str | None = Field(default=None, pattern=r"^bk_[a-z0-9_]+$")
    ticket_id: str | None = Field(default=None, pattern=r"^em_[a-z0-9_]+$")
    qa_flags: list[str] = Field(default_factory=list)


class SeedEmergencyTicket(StrictModel):
    ticket_id: str = Field(pattern=r"^em_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    call_id: str = Field(pattern=r"^call_[a-z0-9_]+$")
    customer_id: str = Field(pattern=r"^cus_[a-z0-9_]+$")
    category: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    severity: Literal["life_safety", "urgent", "priority"]
    description: str = Field(min_length=1)
    safety_instructions_given: list[str] = Field(min_length=1)
    transfer_mode: Literal["live", "callback"]
    status: Literal["open", "assigned", "closed"]
    created_at: datetime


class SeedSmsMessage(StrictModel):
    message_id: str = Field(pattern=r"^sms_[a-z0-9_]+$")
    tenant_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    booking_id: str = Field(pattern=r"^bk_[a-z0-9_]+$")
    to: Phone
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
    tickets: list[SeedEmergencyTicket] = Field(default_factory=list)
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
            "caller_phone": None,
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

TICKETS: dict[str, list[dict[str, Any]]] = {
    "harborlight": [
        {
            "ticket_id": "em_0001",
            "call_id": "call_hl_0003",
            "customer_id": "cus_0002",
            "category": "gas_or_co",
            "severity": "life_safety",
            "description": "Caller reported a gas smell near the furnace.",
            "safety_instructions_given": ["gas_co"],
            "transfer_mode": "live",
            "status": "open",
        },
    ],
    "summit": [],
}


def _calendar_days(start: date, count: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(count)]


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


def _ticket_specs(tenant: TenantConfig) -> list[dict[str, Any]]:
    tickets = TICKETS.get(tenant.tenant_id)
    if tickets is None:
        raise SeedDataError(f"no seed tickets configured for tenant {tenant.tenant_id!r}")
    return tickets


def _day_windows(tenant: TenantConfig, day: date) -> list[tuple[time, time]]:
    if day in set(tenant.holidays):
        return []
    day_name = day.strftime("%A").lower()
    ranges = getattr(tenant.business_hours, day_name)
    windows: list[tuple[time, time]] = []
    for value in ranges:
        start_text, end_text = value.split("-")
        windows.append((time.fromisoformat(start_text), time.fromisoformat(end_text)))
    return windows


def _generate_open_slots(tenant: TenantConfig, prefix: str) -> list[SeedSlot]:
    """Create sequential, non-overlapping slots inside each day's configured hours."""
    slots: list[SeedSlot] = []
    sequence = 1
    for day_index, day in enumerate(_calendar_days(ANCHOR_DATE, CALENDAR_DAY_COUNT)):
        windows = _day_windows(tenant, day)
        if not windows:
            continue
        for technician in tenant.dispatch.technicians:
            services = [service for service in tenant.services if service.id in technician.skills]
            if not services:
                continue
            offset = day_index % len(services)
            ordered = services[offset:] + services[:offset]
            for window_start, window_end in windows:
                cursor = _at(day, window_start)
                end_limit = _at(day, window_end)
                for service in ordered:
                    end = cursor + timedelta(minutes=service.duration_minutes)
                    if end > end_limit:
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
    ensure_unique(customer_ids, "customer ids")
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
    ensure_unique(slot_ids, "slot ids")
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
    ensure_unique(booking_ids, "booking ids")
    booked_intervals: list[SeedBooking] = []
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
        expected_slot_status = "booked" if booking.status == "booked" else "open"
        if slot.status != expected_slot_status:
            raise SeedDataError(
                f"booking {booking.booking_id} status {booking.status!r} disagrees "
                f"with slot status {slot.status!r}"
            )
        if (
            slot.service_id != booking.service_id
            or slot.technician_id != booking.technician_id
            or slot.start != booking.start
            or slot.end != booking.end
        ):
            raise SeedDataError(f"booking {booking.booking_id} disagrees with its slot")
        if booking.contact_phone != customer.phone:
            raise SeedDataError(f"booking {booking.booking_id} contact phone mismatch")
        if booking.address != customer.address:
            raise SeedDataError(f"booking {booking.booking_id} address mismatch")
        if booking.status == "booked":
            booked_intervals.append(booking)

    open_slots = [slot for slot in seed.slots if slot.status == "open"]
    for slot in open_slots:
        for booking in booked_intervals:
            if slot.technician_id != booking.technician_id:
                continue
            if _overlaps(slot.start, slot.end, booking.start, booking.end):
                raise SeedDataError(
                    f"open slot {slot.slot_id} overlaps booking {booking.booking_id}"
                )

    ticket_ids = [ticket.ticket_id for ticket in seed.tickets]
    ensure_unique(ticket_ids, "ticket ids")
    tickets = {ticket.ticket_id: ticket for ticket in seed.tickets}
    calls = {call.call_id: call for call in seed.calls}
    ensure_unique([call.call_id for call in seed.calls], "call ids")
    category_severity = {category.id: category.severity for category in tenant.emergency.categories}
    for ticket in seed.tickets:
        if ticket.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"ticket {ticket.ticket_id} has the wrong tenant")
        if ticket.customer_id not in customers:
            raise SeedDataError(f"ticket {ticket.ticket_id} references unknown customer")
        call = calls.get(ticket.call_id)
        if call is None:
            raise SeedDataError(f"ticket {ticket.ticket_id} references unknown call")
        if call.ticket_id != ticket.ticket_id:
            raise SeedDataError(
                f"ticket {ticket.ticket_id} is not referenced by call {call.call_id}"
            )
        if ticket.category not in category_severity:
            raise SeedDataError(f"ticket {ticket.ticket_id} references unknown emergency category")
        if ticket.severity != category_severity[ticket.category]:
            raise SeedDataError(f"ticket {ticket.ticket_id} severity disagrees with category")

    known_phones = {customer.phone for customer in seed.customers}
    for call in seed.calls:
        if call.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"call {call.call_id} has the wrong tenant")
        if call.caller_phone is not None and call.caller_phone not in known_phones:
            raise SeedDataError(f"call {call.call_id} references an unknown caller")
        if call.booking_id is not None and call.booking_id not in booking_ids:
            raise SeedDataError(f"call {call.call_id} references unknown booking")
        if call.ticket_id is not None:
            ticket = tickets.get(call.ticket_id)
            if ticket is None:
                raise SeedDataError(f"call {call.call_id} references unknown ticket")
            if ticket.call_id != call.call_id:
                raise SeedDataError(f"call {call.call_id} ticket call mismatch")

    for message in seed.sms.messages:
        if message.tenant_id != tenant.tenant_id:
            raise SeedDataError(f"SMS {message.message_id} has the wrong tenant")
        booking = next(
            (item for item in seed.bookings if item.booking_id == message.booking_id),
            None,
        )
        if booking is None:
            raise SeedDataError(f"SMS {message.message_id} references unknown booking")
        if message.to != booking.contact_phone:
            raise SeedDataError(f"SMS {message.message_id} phone mismatch")

    if seed.crm.customer_ids != customer_ids:
        raise SeedDataError("crm.customer_ids does not match the seeded customers")

    booked_ids = sorted(booking.slot_id for booking in seed.bookings if booking.status == "booked")
    open_ids = sorted(slot.slot_id for slot in open_slots)
    if seed.calendar.booked_slot_ids != booked_ids:
        raise SeedDataError("calendar booked slots do not match bookings")
    if seed.calendar.open_slot_ids != open_ids:
        raise SeedDataError("calendar open slots do not match slot status")
    if set(booked_ids) & set(open_ids):
        raise SeedDataError("a booked slot is still listed as open")

    for index, first in enumerate(open_slots):
        for second in open_slots[index + 1 :]:
            if first.technician_id != second.technician_id:
                continue
            if _overlaps(first.start, first.end, second.start, second.end):
                raise SeedDataError(
                    f"open slots {first.slot_id} and {second.slot_id} overlap for "
                    f"{first.technician_id}"
                )

    for index, first in enumerate(booked_intervals):
        for second in booked_intervals[index + 1 :]:
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
    tickets = [
        SeedEmergencyTicket(
            tenant_id=tenant.tenant_id,
            created_at=ANCHOR_DATETIME - timedelta(days=3, minutes=30 + index),
            **ticket,
        )
        for index, ticket in enumerate(_ticket_specs(tenant))
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
        tickets=tickets,
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

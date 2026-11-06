"""Deterministic synthetic seed data for both tenants.

Anchor time is fixed at Monday 2026-11-09 08:00 America/Los_Angeles. No wall clock or random
source is used, so repeated generation is byte-identical.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from forge_voice.tenants.models import TenantConfig

TZ = ZoneInfo("America/Los_Angeles")
ANCHOR_DATE = date(2026, 11, 9)
ANCHOR_DATETIME = datetime(2026, 11, 9, 8, 0, tzinfo=TZ)
BUSINESS_DAY_COUNT = 10
SLOT_TIMES = (time(9, 0), time(11, 0), time(13, 0), time(15, 0))

TENANT_PREFIX = {"harborlight": "hl", "summit": "sm"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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

BOOKINGS: dict[str, list[tuple[str, str, str, str, str]]] = {
    "harborlight": [
        ("bk_0001", "cus_0001", "drain_cleaning", "tech_alex", "2026-11-09T09:00:00"),
        ("bk_0002", "cus_0001", "leak_repair", "tech_alex", "2026-11-10T13:00:00"),
        ("bk_0003", "cus_0003", "ac_repair", "tech_blair", "2026-11-09T09:30:00"),
        ("bk_0004", "cus_0002", "furnace_repair", "tech_blair", "2026-11-12T11:00:00"),
    ],
    "summit": [
        (
            "bk_summit_0001",
            "cus_summit_0001",
            "ac_repair",
            "tech_casey",
            "2026-11-11T09:00:00",
        ),
        (
            "bk_summit_0002",
            "cus_summit_0001",
            "ac_repair",
            "tech_casey",
            "2026-11-13T13:00:00",
        ),
    ],
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


def build_tenant_seed(tenant: TenantConfig) -> TenantSeed:
    """Build the deterministic calendar, CRM, booking and outbox seed for one tenant."""
    prefix = TENANT_PREFIX[tenant.tenant_id]
    customers = [
        SeedCustomer(
            tenant_id=tenant.tenant_id,
            created_at=ANCHOR_DATETIME - timedelta(days=30),
            **customer,
        )
        for customer in CUSTOMERS[tenant.tenant_id]
    ]
    customers_by_id = {customer.customer_id: customer for customer in customers}

    slots: list[SeedSlot] = []
    sequence = 1
    for day in _business_days(ANCHOR_DATE, BUSINESS_DAY_COUNT):
        for service in tenant.services:
            technicians = [
                technician
                for technician in tenant.dispatch.technicians
                if service.id in technician.skills
            ]
            for technician in technicians:
                for clock in SLOT_TIMES:
                    start = _at(day, clock)
                    slots.append(
                        SeedSlot(
                            slot_id=f"slot_{prefix}_{sequence:05d}",
                            tenant_id=tenant.tenant_id,
                            service_id=service.id,
                            technician_id=technician.id,
                            start=start,
                            end=start + timedelta(minutes=service.duration_minutes),
                            status="open",
                        )
                    )
                    sequence += 1

    slots_by_key = {(slot.service_id, slot.technician_id, slot.start): slot for slot in slots}
    bookings: list[SeedBooking] = []
    special_sequence = 1
    for booking_id, customer_id, service_id, technician_id, start_iso in BOOKINGS[tenant.tenant_id]:
        service = tenant.require_service(service_id)
        customer = customers_by_id[customer_id]
        start = _start_from_iso(start_iso)
        key = (service.id, technician_id, start)
        slot = slots_by_key.get(key)
        if slot is None:
            slot = SeedSlot(
                slot_id=f"slot_{prefix}_special_{special_sequence:04d}",
                tenant_id=tenant.tenant_id,
                service_id=service.id,
                technician_id=technician_id,
                start=start,
                end=start + timedelta(minutes=service.duration_minutes),
                status="open",
            )
            special_sequence += 1
            slots.append(slot)
            slots_by_key[key] = slot
        slot.status = "booked"
        bookings.append(
            SeedBooking(
                booking_id=booking_id,
                tenant_id=tenant.tenant_id,
                customer_id=customer.customer_id,
                service_id=service.id,
                technician_id=technician_id,
                slot_id=slot.slot_id,
                start=slot.start,
                end=slot.end,
                status="booked",
                contact_phone=customer.phone,
                address=customer.address,
                confirmation=SeedConfirmation(sms="queued", email="not_requested"),
            )
        )

    calls = [
        SeedCallRecord(
            tenant_id=tenant.tenant_id,
            started_at=ANCHOR_DATETIME - timedelta(days=3, minutes=index * 17),
            recording_ref="text_only",
            **call,
        )
        for index, call in enumerate(CALLS[tenant.tenant_id])
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
    return TenantSeed(
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

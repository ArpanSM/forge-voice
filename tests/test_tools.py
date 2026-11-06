from __future__ import annotations

from datetime import date

import pytest

from forge_voice.adapters import Outbox, SQLiteAdapter
from forge_voice.policy import (
    BookingService,
    ConversationPolicy,
    CustomerInput,
    canonical_booking_payload,
)
from forge_voice.tools import ToolRegistry, ToolResult, ToolSession
from forge_voice.transfer import TransferSimulator

CUSTOMER = {
    "name": "Sam Rivera",
    "phone": "+14155550101",
    "address": {"line1": "12 Alder St", "city": "San Francisco", "state": "CA", "zip": "94107"},
}
TOOLS = {
    "lookup_customer",
    "get_service_area",
    "get_availability",
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "create_emergency_ticket",
    "transfer_to_human",
}


@pytest.fixture
def store(seed_data):
    database = SQLiteAdapter(":memory:")
    for data in seed_data.values():
        database.seed(data)
    return database


@pytest.fixture
def registry(harborlight, store, clock):
    outbox = Outbox()
    service = BookingService(harborlight, store, outbox, clock)
    return ToolRegistry(
        tenant=harborlight,
        store=store,
        service=service,
        session=ToolSession(
            tenant_id="harborlight",
            call_id="call_tools",
            caller_phone="+14155550101",
        ),
        clock=clock,
        transfer=TransferSimulator(),
    )


def _slot(registry: ToolRegistry, *, day=date(2026, 11, 9)):
    result = registry.call(
        "get_availability",
        {"service_id": "drain_cleaning", "zip": "94107", "preferred_date": day.isoformat()},
    )
    assert result.ok is True
    return result.data["slots"][0]


def _book_token(registry: ToolRegistry, slot: dict) -> str:
    customer = CustomerInput.model_validate(CUSTOMER)
    payload = canonical_booking_payload("drain_cleaning", slot["slot_id"], customer)
    policy = ConversationPolicy(registry.tenant, registry.clock, registry.service.tokens)
    state = policy.start_call(registry.session.call_id, registry.session.caller_phone)
    policy.identify_intent(state, "I need a drain cleaning")
    policy.record_readback(state, payload)
    policy.confirm(state, "yes, book it")
    return policy.issue_confirmation(state, target=slot["slot_id"], payload=payload).token


def test_registry_exposes_exactly_eight_typed_tools(registry) -> None:
    assert set(registry.tool_names) == TOOLS


def test_success_envelope_has_data_and_request_id(registry) -> None:
    result = registry.call("lookup_customer", {"phone": "+14155550101"})

    assert isinstance(result, ToolResult)
    assert result.ok is True
    assert result.error is None
    assert result.data["customer"]["name"] == "Sam Rivera"
    assert result.request_id.startswith("req_call_tools_")


def test_failure_envelope_has_stable_code_and_no_stack_trace(registry) -> None:
    result = registry.call("get_service_area", {"zip": "9410"})

    assert result.ok is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code == "invalid_zip"
    assert result.error.retryable is False
    assert "Traceback" not in result.error.message


def test_invalid_arguments_become_invalid_argument(registry) -> None:
    result = registry.call("get_availability", {"zip": "94107"})

    assert result.ok is False
    assert result.error.code == "invalid_argument"


def test_lookup_customer_is_tenant_scoped(registry) -> None:
    missing = registry.call("lookup_customer", {"phone": "+14085550101"})

    assert missing.ok is False
    assert missing.error.code == "not_found"
    assert missing.data is None


def test_lookup_without_caller_phone_is_masked(harborlight, store, clock) -> None:
    service = BookingService(harborlight, store, Outbox(), clock)
    registry = ToolRegistry(
        tenant=harborlight,
        store=store,
        service=service,
        session=ToolSession(tenant_id="harborlight", call_id="call_masked", caller_phone=None),
        clock=clock,
        transfer=TransferSimulator(),
    )

    result = registry.call(
        "lookup_customer",
        {
            "name": "Sam Rivera",
            "address": {
                "line1": "12 Alder St",
                "city": "San Francisco",
                "state": "CA",
                "zip": "94107",
            },
            "include_bookings": True,
        },
    )

    assert result.ok is True
    assert result.data["verification_required"] is True
    assert result.data["bookings"] == []
    assert result.data["customer"]["phone"] == "+1******0101"


def test_session_caller_phone_is_authoritative_over_a_claimed_phone(
    harborlight, store, clock
) -> None:
    service = BookingService(harborlight, store, Outbox(), clock)
    registry = ToolRegistry(
        tenant=harborlight,
        store=store,
        service=service,
        session=ToolSession(
            tenant_id="harborlight", call_id="call_claim", caller_phone="+14155550999"
        ),
        clock=clock,
        transfer=TransferSimulator(),
    )

    result = registry.call("lookup_customer", {"phone": "+14155550101"})

    assert result.ok is True
    assert result.data["verification_required"] is True
    assert result.data["bookings"] == []


def test_tenant_mismatch_session_is_rejected(harborlight, store, clock) -> None:
    service = BookingService(harborlight, store, Outbox(), clock)
    registry = ToolRegistry(
        tenant=harborlight,
        store=store,
        service=service,
        session=ToolSession(tenant_id="summit", call_id="call_bad", caller_phone=None),
        clock=clock,
        transfer=TransferSimulator(),
    )

    result = registry.call("get_service_area", {"zip": "94107"})

    assert result.ok is False
    assert result.error.code == "tenant_mismatch"


def test_service_area_returns_zone_and_technicians(registry) -> None:
    result = registry.call("get_service_area", {"zip": "94107", "service_id": "drain_cleaning"})

    assert result.ok is True
    assert result.data["in_area"] is True
    assert result.data["dispatch_zone"] == "central"
    assert result.data["technicians"] == ["tech_alex"]


def test_service_area_out_of_area_is_a_business_outcome(registry) -> None:
    result = registry.call("get_service_area", {"zip": "10001"})

    assert result.ok is True
    assert result.data["in_area"] is False
    assert result.data["dispatch_zone"] is None


def test_availability_marks_offers_and_expiry(registry, harborlight) -> None:
    result = registry.call(
        "get_availability",
        {"service_id": "drain_cleaning", "zip": "94107", "preferred_date": "2026-11-09"},
    )

    assert result.ok is True
    assert result.data["reason"] == "ok"
    assert 1 <= len(result.data["slots"]) <= harborlight.policies.max_slots_offered
    assert all(slot["offer_expires_at"] for slot in result.data["slots"])
    assert result.data["timezone"] == "America/Los_Angeles"


def test_availability_returns_reasons_not_errors(registry) -> None:
    out_of_area = registry.call(
        "get_availability", {"service_id": "drain_cleaning", "zip": "10001"}
    )
    no_slots = registry.call(
        "get_availability",
        {
            "service_id": "drain_cleaning",
            "zip": "94107",
            "preferred_date": "2026-11-07",
            "window_days": 1,
        },
    )
    unknown_service = registry.call("get_availability", {"service_id": "roofing", "zip": "94107"})
    bad_zip = registry.call("get_availability", {"service_id": "drain_cleaning", "zip": "abc"})

    assert out_of_area.data["reason"] == "out_of_area"
    assert no_slots.data["reason"] == "no_slots"
    assert unknown_service.ok is True
    assert unknown_service.data["reason"] == "service_not_offered"
    assert bad_zip.ok is False
    assert bad_zip.error.code == "invalid_zip"


def test_book_tool_rejects_premature_write(registry) -> None:
    slot = _slot(registry)

    result = registry.call(
        "book_appointment",
        {
            "service_id": "drain_cleaning",
            "slot_id": slot["slot_id"],
            "customer": CUSTOMER,
            "confirmed": False,
        },
    )

    assert result.ok is False
    assert result.error.code == "explicit_confirmation_required"
    assert registry.store.count_bookings("harborlight") == 4


def test_book_tool_commits_with_policy_token_and_queues_confirmation(registry) -> None:
    slot = _slot(registry)
    token = _book_token(registry, slot)

    result = registry.call(
        "book_appointment",
        {
            "service_id": "drain_cleaning",
            "slot_id": slot["slot_id"],
            "customer": CUSTOMER,
            "confirmed": True,
            "confirmation_token": token,
        },
    )

    assert result.ok is True
    booking = result.data["booking"]
    assert booking["status"] == "booked"
    assert booking["technician"]["name"] == "Alex"
    assert result.data["replayed"] is False
    assert registry.store.count_bookings("harborlight", slot_id=slot["slot_id"]) == 1
    assert registry.store.count_confirmations("harborlight") == 1
    events = registry.store.list_events("harborlight", call_id="call_tools")
    assert any(event.tool == "book_appointment" for event in events)
    assert token not in str([event.args for event in events])


def test_cross_tenant_booking_id_is_rejected_without_details(registry) -> None:
    result = registry.call(
        "cancel_appointment",
        {"booking_id": "bk_summit_0001", "confirmed": True},
    )

    assert result.ok is False
    assert result.error.code == "not_found"
    assert "Meridian" not in result.error.message
    assert "Summit" not in result.error.message


def test_summit_runs_the_same_tools(summit, store, clock) -> None:
    service = BookingService(summit, store, Outbox(), clock)
    registry = ToolRegistry(
        tenant=summit,
        store=store,
        service=service,
        session=ToolSession(
            tenant_id="summit",
            call_id="call_summit",
            caller_phone="+14085550101",
            ownership_verified=True,
        ),
        clock=clock,
        transfer=TransferSimulator(),
    )

    area = registry.call("get_service_area", {"zip": "95125"})
    result = registry.call(
        "cancel_appointment",
        {
            "booking_id": "bk_summit_0002",
            "confirmed": True,
            "confirmation_token": "ct_missing",
        },
    )
    missing = registry.call("cancel_appointment", {"booking_id": "bk_0001", "confirmed": True})

    assert area.ok is True
    assert area.data["in_area"] is True
    assert missing.ok is False
    assert missing.error.code == "not_found"
    # The Summit booking is real, so the missing-token path is reached.
    assert result.ok is False
    assert result.error.code == "explicit_confirmation_required"

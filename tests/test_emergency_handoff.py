from __future__ import annotations

from datetime import timedelta

import pytest

from forge_voice.adapters import Outbox, SQLiteAdapter
from forge_voice.policy import Address, BookingService
from forge_voice.policy.emergency import triage_emergency
from forge_voice.policy.handoff import HandoffCaller, HandoffPacket, HandoffService
from forge_voice.tools import ToolRegistry, ToolSession
from forge_voice.transfer import TransferSimulator

CUSTOMER = {
    "name": "Sam Rivera",
    "phone": "+14155550101",
    "address": {"line1": "12 Alder St", "city": "San Francisco", "state": "CA", "zip": "94107"},
}


@pytest.fixture
def store(seed_data):
    database = SQLiteAdapter(":memory:")
    for data in seed_data.values():
        database.seed(data)
    return database


def _registry(tenant, store, clock, *, answered=None, call_id="call_em"):
    service = BookingService(tenant, store, Outbox(), clock)
    return ToolRegistry(
        tenant=tenant,
        store=store,
        service=service,
        session=ToolSession(
            tenant_id=tenant.tenant_id, call_id=call_id, caller_phone="+14155550101"
        ),
        clock=clock,
        transfer=TransferSimulator(answered_targets=answered),
    )


def _ticket(registry: ToolRegistry, clock) -> dict:
    result = registry.call(
        "create_emergency_ticket",
        {
            "category": "gas_or_co",
            "severity": "life_safety",
            "customer": CUSTOMER,
            "description": "Caller smells gas near the furnace.",
            "safety_instructions_given": ["gas_co"],
            "transfer_mode": "live",
        },
    )
    assert result.ok is True, result.error
    return result.data


def _packet(
    tenant_id: str,
    call_id: str,
    clock,
    *,
    ticket_id=None,
    reason="emergency",
    intent="emergency",
    urgency="emergency",
) -> HandoffPacket:
    return HandoffPacket(
        tenant_id=tenant_id,
        call_id=call_id,
        caller=HandoffCaller(name="Sam Rivera", phone="+14155550101", verified=True),
        intent=intent,
        service=HandoffService(id="leak_repair", name="Leak repair"),
        address=Address(line1="12 Alder St", city="San Francisco", state="CA", zip="94107"),
        urgency=urgency,
        emergency_ticket_id=ticket_id,
        summary="Caller reports a gas smell; leaving the building; on-call requested.",
        reason=reason,
        requested_at=clock.now,
    )


@pytest.mark.parametrize(
    ("text", "category", "severity", "script"),
    [
        ("I smell gas near my furnace", "gas_or_co", "life_safety", "gas_co"),
        ("There is smoke coming from an outlet", "fire_or_smoke", "life_safety", "fire_smoke"),
        ("A pipe burst and water is everywhere", "active_flooding", "urgent", "active_flooding"),
        ("There is sewage backing up in the bathroom", "sewage_backup", "urgent", "sewage_backup"),
        ("My heat stopped and it is 38 degrees", "no_heat", "urgent", "no_heat"),
        ("My AC is out and it is 98 degrees inside", "no_cooling", "urgent", "no_cooling"),
    ],
)
def test_triage_reaches_configured_category_and_script(
    harborlight, text, category, severity, script
) -> None:
    triage = triage_emergency(harborlight, text)

    assert triage is not None
    assert triage.category.id == category
    assert triage.severity == severity
    assert triage.safety_script == script
    assert triage.safety_text
    if severity == "life_safety":
        assert "911" in triage.safety_text
        assert triage.requires_911 is True


def test_triage_escalates_vulnerable_occupant(harborlight) -> None:
    triage = triage_emergency(
        harborlight, "My heat stopped and it is freezing. I am 78 and I live alone."
    )

    assert triage is not None
    assert triage.category.id == "no_heat"
    assert triage.vulnerable_occupant is True
    assert triage.severity == "urgent"
    assert "911" in triage.safety_text


def test_summit_triage_uses_its_own_config(summit) -> None:
    triage = triage_emergency(summit, "My AC is out and it is 98 degrees inside. I have a newborn.")

    assert triage is not None
    assert triage.category.id == "no_cooling"
    assert triage.on_call_target == "summit_on_call"
    assert triage.callback_sla_minutes == 15
    assert triage.vulnerable_occupant is True


def test_no_heat_outside_threshold_is_not_an_emergency(harborlight) -> None:
    assert triage_emergency(harborlight, "My heat stopped") is None


def test_emergency_ticket_is_structured_and_does_not_book(harborlight, store, clock) -> None:
    registry = _registry(harborlight, store, clock)

    ticket = _ticket(registry, clock)

    stored = store.get_ticket("harborlight", ticket["ticket_id"])
    assert stored is not None
    assert stored.category == "gas_or_co"
    assert stored.severity == "life_safety"
    assert stored.safety_instructions_given == ["gas_co"]
    assert stored.on_call_target == "harborlight_on_call"
    assert stored.callback_sla_minutes == 15
    assert stored.customer_name == "Sam Rivera"
    assert stored.customer_phone == "+14155550101"
    assert stored.address is not None
    assert stored.address.zip == "94107"
    assert store.count_bookings("harborlight") == 4


def test_invalid_emergency_category_is_rejected(harborlight, store, clock) -> None:
    registry = _registry(harborlight, store, clock)

    result = registry.call(
        "create_emergency_ticket",
        {
            "category": "roofing",
            "severity": "urgent",
            "customer": CUSTOMER,
            "description": "Not a configured category.",
            "safety_instructions_given": ["generic"],
            "transfer_mode": "live",
        },
    )

    assert result.ok is False
    assert result.error.code == "invalid_category"


def test_live_transfer_never_claims_connected_without_a_human(harborlight, store, clock) -> None:
    registry = _registry(harborlight, store, clock, answered=set())
    ticket = _ticket(registry, clock)
    packet = _packet("harborlight", "call_em", clock, ticket_id=ticket["ticket_id"])

    result = registry.call(
        "transfer_to_human",
        {
            "reason": "emergency",
            "urgency": "emergency",
            "mode": "live",
            "packet": packet.model_dump(mode="json"),
        },
    )

    assert result.ok is True
    assert result.data["status"] == "no_answer"
    assert result.data["connected_at"] is None
    assert result.data["callback_id"]
    callback = store.get_callback("harborlight", result.data["callback_id"])
    assert callback is not None
    assert callback.window_end - callback.window_start == timedelta(minutes=15)
    assert callback.sla == "15_minutes"
    stored = store.get_ticket("harborlight", ticket["ticket_id"])
    assert stored is not None
    assert stored.transfer_id == result.data["transfer_id"]


def test_answered_transfer_reports_connected_and_complete_packet(harborlight, store, clock) -> None:
    registry = _registry(harborlight, store, clock, answered={"harborlight_on_call"})
    ticket = _ticket(registry, clock)
    packet = _packet("harborlight", "call_em", clock, ticket_id=ticket["ticket_id"])

    result = registry.call(
        "transfer_to_human",
        {
            "reason": "emergency",
            "urgency": "emergency",
            "mode": "live",
            "packet": packet.model_dump(mode="json"),
        },
    )

    assert result.ok is True
    assert result.data["status"] == "connected"
    assert result.data["packet_complete"] is True
    assert result.data["target"]["id"] == "harborlight_on_call"
    assert result.data["callback_id"] is None
    assert packet.complete is True
    assert packet.missing_fields() == []


def test_callback_mode_queues_next_business_day_for_after_hours(harborlight, store, clock) -> None:
    registry = _registry(harborlight, store, clock)
    packet = _packet(
        "harborlight", "call_em", clock, reason="after_hours", intent="human", urgency="normal"
    )

    result = registry.call(
        "transfer_to_human",
        {
            "reason": "after_hours",
            "urgency": "normal",
            "mode": "callback",
            "packet": packet.model_dump(mode="json"),
            "callback_window": {
                "start": (clock.now + timedelta(days=3)).isoformat(),
                "end": (clock.now + timedelta(days=3, hours=4)).isoformat(),
            },
        },
    )

    assert result.ok is True
    assert result.data["status"] == "queued_callback"
    callback = store.get_callback("harborlight", result.data["callback_id"])
    assert callback is not None
    assert callback.sla == "next_business_day"
    assert callback.reason == "after_hours"

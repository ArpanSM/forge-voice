"""The audio call session drives the #4 policy and tools without bypassing confirmation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from forge_voice.runtime.audio_session import AudioCallSession

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 6, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
CUSTOMER = {
    "name": "Sam Rivera",
    "phone": "+14155550123",
    "line1": "12 Alder Street",
    "city": "San Francisco",
    "state": "CA",
    "zip": "94107",
}


@pytest.fixture
def session(tmp_path: Path) -> AudioCallSession:
    return AudioCallSession.from_repo(
        ROOT,
        "harborlight",
        "call_audio_0001",
        outbox_path=tmp_path / "outbox.jsonl",
        trace_path=tmp_path / "trace.jsonl",
        now=NOW,
    )


def first_slot(session: AudioCallSession, *, service_id: str = "drain_cleaning") -> dict:
    reply = session.get_availability(service_id=service_id, zip="94107", window_days=7)
    assert reply.ok
    assert reply.data["slots"]
    return reply.data["slots"][0]


def test_greeting_discloses_ai_and_recording(session: AudioCallSession) -> None:
    assert "virtual assistant" in session.greeting.lower()
    assert "recorded" in session.greeting.lower()


def test_instructions_route_every_booking_through_the_policy(session: AudioCallSession) -> None:
    text = session.instructions.lower()

    assert "get_availability" in text
    assert "book_appointment" in text
    assert "explicit" in text
    assert "never invent" in text
    assert "911" in text
    assert "transfer" in text


def test_availability_returns_real_slots_from_the_corpus(session: AudioCallSession) -> None:
    slot = first_slot(session)

    assert slot["slot_id"].startswith("slot_hl_")
    assert slot["start"].startswith("2026-11-")
    assert slot["slot_id"] in session.offered_slots


def test_first_book_call_reads_back_without_writing(session: AudioCallSession) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)

    reply = session.book_appointment(
        slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER
    )

    assert reply.ok
    assert reply.stage == "readback"
    assert "Just to confirm" in reply.message
    assert "12 Alder Street" in reply.message
    assert "Sam Rivera" in reply.message
    assert session.store.count_bookings(session.tenant.tenant_id) == before


def test_book_commits_exactly_one_booking_after_explicit_yes(session: AudioCallSession) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)

    session.note_caller_utterance("Yes, book it.")
    reply = session.book_appointment()

    assert reply.ok
    assert reply.stage == "booked"
    assert reply.data["booking"]["booking_id"] == session.booking_id
    assert session.store.count_bookings(session.tenant.tenant_id) == before + 1
    assert session.store.count_confirmations(session.tenant.tenant_id) == 1
    assert session.state.write_count == 1
    assert session.state.outcome == "booked"


def test_replaying_the_same_booking_returns_it_without_a_second_write(
    session: AudioCallSession,
) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, that's correct.")
    first = session.book_appointment()

    session.note_caller_utterance("Yes.")
    replay = session.book_appointment(
        slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER
    )

    assert first.ok and replay.ok
    assert replay.data["replayed"] is True
    assert replay.data["booking"]["booking_id"] == first.data["booking"]["booking_id"]
    assert session.store.count_bookings(session.tenant.tenant_id) == before + 1


def test_book_without_an_explicit_yes_is_refused(session: AudioCallSession) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)

    session.note_caller_utterance("No, wait a minute.")
    reply = session.book_appointment()

    assert reply.ok is False
    assert reply.error is not None
    assert reply.error.code.value == "explicit_confirmation_required"
    assert reply.error.message
    assert session.store.count_bookings(session.tenant.tenant_id) == before


def test_a_new_offer_clears_the_pending_readback(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.get_availability(service_id="drain_cleaning", zip="94107", window_days=7)

    session.note_caller_utterance("Yes.")
    reply = session.book_appointment()

    assert reply.ok is False
    assert reply.error is not None
    assert reply.error.code.value == "confirmation_required"


def test_emergency_triage_creates_a_ticket_with_a_911_script(tmp_path: Path) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "summit",
        "call_emergency_0001",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    text = "Our AC is out and it is ninety-eight degrees upstairs. I have a newborn baby."
    session.note_caller_utterance(text)

    reply = session.create_emergency_ticket(
        description=text,
        name="Dana Whitfield",
        phone="+14085550142",
        line1="88 Meridian Way",
        city="San Jose",
        state="CA",
        zip="95125",
    )

    assert reply.ok
    assert reply.stage == "ticket"
    assert reply.data["ticket_id"].startswith("em_summit_")
    assert reply.data["category"] == "no_cooling"
    assert "911" in reply.data["safety_text"]
    assert len(session.store.list_tickets("summit")) == 1


def test_emergency_then_handoff_carries_the_ticket_and_says_only_what_happened(
    tmp_path: Path,
) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "summit",
        "call_emergency_0002",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    text = "The AC is out and there is a newborn in the house."
    session.note_caller_utterance(text)
    ticket = session.create_emergency_ticket(
        description=text,
        name="Dana Whitfield",
        phone="+14085550142",
        line1="88 Meridian Way",
        city="San Jose",
        state="CA",
        zip="95125",
    )

    reply = session.transfer_to_human(
        reason="emergency", mode="live", summary="No cooling with a newborn."
    )

    assert reply.ok
    assert reply.stage == "handoff"
    assert reply.data["transfer"]["status"] in {"connected", "queued_callback", "no_answer"}
    assert ticket.data["ticket_id"] in reply.data["packet"]["emergency_ticket_id"]
    assert "transfer" in reply.message.lower()


def test_incomplete_live_handoff_does_not_claim_a_transfer(tmp_path: Path) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "harborlight",
        "call_handoff_0001",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    session.note_caller_utterance("I want to talk to a person.")

    refused = session.transfer_to_human(reason="caller_request", mode="live")

    assert refused.ok is False
    assert refused.error is not None
    assert refused.error.code.value == "invalid_phone"
    assert "number" in refused.message.lower()

    queued = session.transfer_to_human(
        reason="caller_request",
        mode="live",
        name="Riley Chen",
        phone="+14155550188",
        line1="21 Harbor Blvd",
        city="San Francisco",
        state="CA",
        zip="94118",
    )

    assert queued.ok
    assert queued.stage == "handoff"
    assert queued.data["transfer"]["status"] == "queued_callback"
    assert queued.data["transfer"]["callback_id"] is not None
    assert "callback" in queued.message.lower()


def test_emergency_step_creates_one_ticket_then_transfers_after_details(
    tmp_path: Path,
) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "summit",
        "call_emergency_0003",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    first = session.emergency_step(
        "Our AC is out and it is ninety-eight degrees upstairs. I have a newborn baby."
    )

    assert first is not None
    assert first.stage == "ticket"
    assert "911" in first.message
    assert "name, service address and callback number" in first.message
    assert len(session.store.list_tickets("summit")) == 1

    session.note_caller_utterance("The address is 88 Meridian Way, San Jose, 95125.")
    session.note_caller_utterance("My name is Dana Whitfield. My phone is 408-555-0142.")
    handoff = session.emergency_step("No one is hurt, but please hurry.")

    assert handoff is not None
    assert handoff.stage == "handoff"
    assert handoff.ok
    assert session.emergency_handoff_done is True
    assert len(session.store.list_tickets("summit")) == 1


def test_non_emergency_text_does_not_trigger_the_emergency_step(tmp_path: Path) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "harborlight",
        "call_emergency_0004",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )

    before = len(session.store.list_tickets("harborlight"))
    assert session.emergency_step("I need a drain cleaning.") is None
    assert len(session.store.list_tickets("harborlight")) == before


def test_tool_failure_serializes_the_shared_error_envelope(session: AudioCallSession) -> None:
    reply = session.book_appointment()

    payload = json.loads(reply.to_json())

    assert payload["ok"] is False
    assert payload["stage"] == "error"
    assert payload["error"]["code"] == "confirmation_required"
    assert payload["error"]["message"]
    assert payload["error"]["retryable"] is False
    assert "details" in payload["error"]


def test_tool_success_omits_the_error_key(session: AudioCallSession) -> None:
    reply = session.get_service_area(zip="94107", service_id="drain_cleaning")

    payload = json.loads(reply.to_json())

    assert payload["ok"] is True
    assert "error" not in payload


def test_audio_session_rejects_a_booking_id_from_another_tenant(tmp_path: Path) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "harborlight",
        "call_cross_tenant_0001",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )

    reply = session.lookup_customer(booking_id="bk_summit_0001", include_bookings=True)

    assert reply.ok is False
    assert reply.error is not None
    assert reply.error.code.value == "not_found"

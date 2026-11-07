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


def test_close_marks_an_unwritten_call_abandoned(session: AudioCallSession) -> None:
    session.note_caller_utterance("I need a drain cleaning.")
    session.close()

    assert session.state.outcome == "abandoned"


def test_close_keeps_a_completed_booking_terminal(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, book it.")
    session.book_appointment()
    session.close()

    assert session.state.outcome == "booked"


def test_audio_reschedule_readback_includes_the_old_start(tmp_path: Path) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "harborlight",
        "call_reschedule_0001",
        caller_phone="+14155550101",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    assert session.lookup_customer(phone="+14155550101", include_bookings=True).ok
    slots = session.get_availability(service_id="drain_cleaning", zip="94107").data["slots"]

    reply = session.reschedule_appointment(booking_id="bk_0001", new_slot_id=slots[0]["slot_id"])

    assert reply.ok
    assert reply.stage == "readback"
    assert "move your Drain cleaning from Monday 9 November at 9:00 AM" in reply.message
    assert "Should I move it?" in reply.message

    session.note_caller_utterance("Yes, move it.")
    committed = session.reschedule_appointment()
    assert committed.ok
    assert committed.stage == "booked"
    assert session.state.outcome == "rescheduled"


def test_completed_call_rejects_a_second_distinct_slot_and_availability(
    session: AudioCallSession,
) -> None:
    availability = session.get_availability(service_id="drain_cleaning", zip="94107")
    first, second = availability.data["slots"][0], availability.data["slots"][1]
    before = session.store.count_bookings(session.tenant.tenant_id)
    session.book_appointment(slot_id=first["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, book it.")
    booked = session.book_appointment()
    assert booked.ok

    availability_again = session.get_availability(service_id="drain_cleaning", zip="94107")
    second_write = session.book_appointment(
        slot_id=second["slot_id"], service_id="drain_cleaning", **CUSTOMER
    )

    assert availability_again.ok is False
    assert availability_again.error is not None
    assert availability_again.error.code.value == "already_completed"
    assert second_write.ok is False
    assert second_write.error is not None
    assert second_write.error.code.value == "already_completed"
    assert session.store.count_bookings(session.tenant.tenant_id) == before + 1
    assert session.state.write_count == 1


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

    assert set(payload) == {"ok", "error", "request_id"}
    assert payload["ok"] is False
    assert set(payload["error"]) == {"code", "message", "retryable", "details"}
    assert payload["error"]["code"] == "confirmation_required"
    assert payload["error"]["message"]
    assert payload["error"]["retryable"] is False
    assert payload["request_id"]


def test_tool_success_omits_the_error_key(session: AudioCallSession) -> None:
    reply = session.get_service_area(zip="94107", service_id="drain_cleaning")

    payload = json.loads(reply.to_json())

    assert set(payload) == {"ok", "data", "request_id"}
    assert payload["ok"] is True
    assert payload["request_id"]


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


def test_trace_records_booking_details_for_the_eval_and_dashboard(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    session = AudioCallSession.from_repo(
        ROOT,
        "harborlight",
        "call_trace_0001",
        outbox_path=tmp_path / "outbox.jsonl",
        trace_path=trace,
        now=NOW,
    )
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, book it.")
    session.book_appointment()

    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    booked = next(event for event in events if event["event"] == "booked")
    assert booked["booking_id"] == session.booking_id
    assert booked["service_id"] == "drain_cleaning"
    assert booked["start"]
    assert booked["address"]["zip"] == "94107"
    assert booked["customer_name"] == "Sam Rivera"
    assert booked["contact_phone"] == "+14155550123"


def test_trace_records_the_emergency_script_and_vulnerable_occupant(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    session = AudioCallSession.from_repo(
        ROOT,
        "summit",
        "call_trace_0002",
        outbox_path=tmp_path / "outbox.jsonl",
        trace_path=trace,
        now=NOW,
    )
    session.create_emergency_ticket(
        description="Our AC is out and I have a newborn baby.",
        name="Dana Whitfield",
        phone="+14085550142",
        line1="88 Meridian Way",
        city="San Jose",
        state="CA",
        zip="95125",
    )

    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    ticket = next(event for event in events if event["event"] == "emergency_ticket")
    assert ticket["category"] == "no_cooling"
    assert ticket["safety_script"] == "no_cooling"
    assert ticket["vulnerable_occupant"] is True


# ------------------------------------------------------------ entity guard
def test_partial_zip_gets_a_specific_reprompt_and_no_slots(session: AudioCallSession) -> None:
    reply = session.get_availability(service_id="drain_cleaning", zip="nine five two zero")

    assert reply.ok is False
    assert reply.error is not None
    assert reply.error.code.value == "invalid_zip"
    assert "five" in reply.message.lower()
    assert "one at a time" in reply.message.lower()
    assert session.offered_slots == []


def test_booking_uses_zip_and_phone_captured_digit_by_digit(session: AudioCallSession) -> None:
    session.note_caller_utterance(
        "The address is 12 Alder Street, San Francisco, nine four one zero seven."
    )
    session.note_caller_utterance("My phone is five five five, one two three, four five six seven.")
    availability = session.get_availability(
        service_id="drain_cleaning", zip="nine four one zero seven"
    )
    slot = availability.data["slots"][0]
    before = session.store.count_bookings(session.tenant.tenant_id)

    readback = session.book_appointment(
        slot_id=slot["slot_id"], service_id="drain_cleaning", name="Sam Rivera"
    )

    assert readback.ok
    assert readback.stage == "readback"
    assert "94107" in readback.message
    assert session.pending is not None
    assert session.pending.args["customer"]["address"]["zip"] == "94107"
    assert session.pending.args["customer"]["phone"] == "+15551234567"
    assert session.store.count_bookings(session.tenant.tenant_id) == before


def test_reprompt_exhaustion_queues_a_callback_without_a_null_write(
    session: AudioCallSession,
) -> None:
    session.note_caller_utterance("My phone is five five five, one two three, four five six seven.")
    before = session.store.count_bookings(session.tenant.tenant_id)

    first = session.entity_reprompt_step("The ZIP is 9520 Faye.")
    second = session.entity_reprompt_step("The ZIP is 9520 Faye.")
    exhausted = session.entity_reprompt_step("The ZIP is 9520 Faye.")

    assert first.ok is False and first.error is not None
    assert second.ok is False and second.error is not None
    assert exhausted.ok is True
    assert exhausted.stage == "handoff"
    assert exhausted.data["packet"]["address"] is None
    assert "address" in exhausted.data["missing_fields"]
    assert session.store.count_bookings(session.tenant.tenant_id) == before
    assert len(session.store.list_callbacks(session.tenant.tenant_id)) == 1
    assert session.state.outcome == "callback"


def test_emergency_partial_packet_marks_the_missing_address(tmp_path: Path) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "summit",
        "call_emergency_partial",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    first = session.emergency_step(
        "Our AC is out and it is ninety-eight degrees upstairs. I have a newborn baby."
    )
    assert first is not None and first.ok
    before = session.store.count_bookings("summit")
    session.note_caller_utterance("My phone is four zero eight, five five five, zero one four two.")
    first_prompt = session.emergency_step("No one is hurt, but please hurry.")
    assert first_prompt is not None and first_prompt.stage == "ticket"
    session.note_caller_utterance("No one is hurt. Please send someone.")
    second_prompt = session.emergency_step("No one is hurt. Please send someone.")
    assert second_prompt is not None and second_prompt.stage == "ticket"
    session.note_caller_utterance("Please send the on-call technician.")

    handoff = session.emergency_step("Please send the on-call technician.")

    assert handoff is not None
    assert handoff.ok is True
    assert handoff.stage == "handoff"
    assert handoff.data["packet"]["address"] is None
    assert "address" in handoff.data["missing_fields"]
    assert len(session.store.list_tickets("summit")) == 1
    assert len(session.store.list_callbacks("summit")) == 1
    assert session.store.count_bookings("summit") == before


def test_emergency_handoff_does_not_infer_a_zip_from_another_customer(
    tmp_path: Path,
) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "summit",
        "call_emergency_no_inference",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    first = session.emergency_step(
        "Our AC is out and it is ninety-eight degrees upstairs. I have a newborn baby."
    )
    assert first is not None
    session.note_caller_utterance("Yes, 88 Meridian Way, San Jose, 9520 Faye.")
    session.note_caller_utterance(
        "My name is Dana Whitfield. My phone is four zero eight, five five five, zero one four two."
    )
    assert session.emergency_step("No one is hurt.") is not None
    session.note_caller_utterance("No one is hurt. Please hurry.")
    assert session.emergency_step("No one is hurt. Please hurry.") is not None
    session.note_caller_utterance("Please send the on-call technician.")

    handoff = session.emergency_step("Please send the on-call technician.")

    assert handoff is not None
    assert handoff.ok is True
    assert handoff.stage == "handoff"
    assert handoff.data["packet"]["address"] is None
    assert "address" in handoff.data["missing_fields"]
    assert len(session.store.list_tickets("summit")) == 1
    assert len(session.store.list_callbacks("summit")) == 1


def test_emergency_with_valid_spoken_entities_reads_them_back(tmp_path: Path) -> None:
    session = AudioCallSession.from_repo(
        ROOT,
        "summit",
        "call_emergency_valid",
        outbox_path=tmp_path / "outbox.jsonl",
        now=NOW,
    )
    first = session.emergency_step(
        "Our AC is out and it is ninety-eight degrees upstairs. I have a newborn baby. "
        "The address is 88 Meridian Way, San Jose, nine five one two five. "
        "My name is Dana Whitfield. My phone is four zero eight, five five five, zero one four two."
    )

    assert first is not None
    assert first.ok is True
    assert "88 Meridian Way" in first.message
    assert "95125" in first.message


def test_deterministic_confirmation_commits_the_pending_readback(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, book it.")

    message = session.confirmation_step("Yes, book it.")

    assert message is not None
    assert "Booked." in message
    assert session.state.outcome == "booked"
    assert session.store.count_bookings(session.tenant.tenant_id) == 5


def test_deterministic_confirmation_accepts_a_matching_full_slot(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, Monday at 7 is correct.")

    message = session.confirmation_step("Yes, Monday at 7 is correct.")

    assert message is not None
    assert session.state.outcome == "booked"


def test_deterministic_confirmation_defers_a_day_correction(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Actually make it Tuesday. Yes.")

    assert session.confirmation_step("Actually make it Tuesday. Yes.") is None
    assert session.pending is None
    assert session.state.outcome is None


def test_deterministic_confirmation_defers_a_time_correction(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, make it 2pm.")

    assert session.confirmation_step("Yes, make it 2pm.") is None
    assert session.pending is None
    assert session.state.outcome is None
    assert session.store.count_bookings(session.tenant.tenant_id) == 4


def test_deterministic_confirmation_fails_closed_on_an_unparseable_change(
    session: AudioCallSession,
) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, make it sooner.")

    assert session.confirmation_step("Yes, make it sooner.") is None
    assert session.pending is None
    assert session.state.outcome is None


def test_same_turn_yes_is_rejected_and_a_later_yes_commits(session: AudioCallSession) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)

    refused = session.book_appointment()

    assert refused.ok is False
    assert refused.error is not None
    assert refused.error.code.value == "explicit_confirmation_required"
    assert "after hearing" in refused.message.lower()
    assert session.store.count_bookings(session.tenant.tenant_id) == before
    assert session.pending is not None

    session.note_caller_utterance("Yes, book it.")
    committed = session.book_appointment()

    assert committed.ok is True
    assert committed.stage == "booked"
    assert session.store.count_bookings(session.tenant.tenant_id) == before + 1


def _note_complete_customer(session: AudioCallSession) -> None:
    session.note_caller_utterance(
        "My name is Sam Rivera. My address is 12 Alder Street, San Francisco, 94107. "
        "My phone is 555-123-4567."
    )


def test_booking_step_never_commits_a_same_turn_yes(session: AudioCallSession) -> None:
    _note_complete_customer(session)
    session.get_availability(service_id="drain_cleaning", zip="94107")
    before = session.store.count_bookings(session.tenant.tenant_id)

    message = session.booking_step("Monday at 7. Yes, book it.")

    assert message is not None
    assert "Just to confirm" in message
    assert "Booked." not in message
    assert session.pending is not None
    assert session.booking_id is None
    assert session.store.count_bookings(session.tenant.tenant_id) == before


def test_booking_step_rebuilds_a_stale_readback_for_a_day_correction(
    session: AudioCallSession,
) -> None:
    _note_complete_customer(session)
    slots = session.get_availability(service_id="drain_cleaning", zip="94107").data["slots"]
    session.book_appointment(slot_id=slots[0]["slot_id"], service_id="drain_cleaning")
    session.note_caller_utterance("Actually, make it Tuesday at 11. Yes, that is correct.")

    message = session.booking_step("Actually, make it Tuesday at 11. Yes, that is correct.")

    assert message is not None
    assert session.pending is not None
    start = datetime.fromisoformat(session.pending.payload.start)
    assert start.strftime("%A") == "Tuesday"
    assert session.booking_id is None


def test_availability_accepts_a_spoken_preferred_day(session: AudioCallSession) -> None:
    reply = session.get_availability(
        service_id="drain_cleaning", zip="94107", preferred_date="Monday morning"
    )

    assert reply.ok is True
    assert reply.data["slots"]
    assert any(
        datetime.fromisoformat(slot["start"]).strftime("%A") == "Monday"
        for slot in reply.data["slots"]
    )


def test_booking_step_uses_the_last_spoken_correction(session: AudioCallSession) -> None:
    _note_complete_customer(session)
    session.get_availability(service_id="drain_cleaning", zip="94107")
    session.note_caller_utterance(
        "Monday at 11 works. Actually, make it Tuesday at 11. Yes, that is correct."
    )

    message = session.booking_step(
        "Monday at 11 works. Actually, make it Tuesday at 11. Yes, that is correct."
    )

    assert message is not None
    assert session.pending is not None
    assert datetime.fromisoformat(session.pending.payload.start).strftime("%A") == "Tuesday"
    assert session.booking_id is None


def test_exhaustion_without_a_phone_still_queues_a_partial_callback(
    session: AudioCallSession,
) -> None:
    before = session.store.count_bookings(session.tenant.tenant_id)

    first = session.entity_reprompt_step("The ZIP is 9520 Faye.")
    session.note_caller_utterance("The ZIP is nine five two zero.")
    second = session.entity_reprompt_step("The ZIP is nine five two zero.")
    session.note_caller_utterance("The ZIP is nine five two.")
    exhausted = session.entity_reprompt_step("The ZIP is nine five two.")

    assert first.ok is False and first.error is not None
    assert second.ok is False and second.error is not None
    assert exhausted.ok is True
    assert exhausted.stage == "handoff"
    assert exhausted.data["packet"]["caller"]["phone"] is None
    assert any("phone" in field for field in exhausted.data["missing_fields"])
    assert session.store.count_bookings(session.tenant.tenant_id) == before
    assert len(session.store.list_callbacks(session.tenant.tenant_id)) == 1
    assert session.state.outcome == "callback"


def test_booking_without_a_street_never_writes(session: AudioCallSession) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)

    reply = session.book_appointment(
        slot_id=slot["slot_id"],
        service_id="drain_cleaning",
        name="Sam Rivera",
        phone="555-123-4567",
    )

    assert reply.ok is False
    assert reply.error is not None
    assert reply.error.code.value in {"invalid_argument", "invalid_zip"}
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == before


def test_booking_rejects_a_mismatched_city(session: AudioCallSession) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)

    reply = session.book_appointment(
        slot_id=slot["slot_id"],
        service_id="drain_cleaning",
        name="Sam Rivera",
        phone="555-123-4567",
        line1="12 Alder Street",
        city="San Jose",
        state="CA",
        zip="94107",
    )

    assert reply.ok is False
    assert reply.error is not None
    assert reply.error.code.value == "invalid_argument"
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == before


def test_confirmation_defers_an_address_or_zip_change(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, make it 21 Harbor Blvd, 94118.")

    assert session.confirmation_step("Yes, make it 21 Harbor Blvd, 94118.") is None
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == 4


def test_confirmation_defers_a_service_change(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, make it a leak repair.")

    assert session.confirmation_step("Yes, make it a leak repair.") is None
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == 4


def test_yes_is_rejected_until_the_readback_finishes_speaking(
    session: AudioCallSession,
) -> None:
    slot = first_slot(session)
    before = session.store.count_bookings(session.tenant.tenant_id)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, book it.")
    session.note_agent_state("speaking")

    early = session.book_appointment()

    assert early.ok is False
    assert early.error is not None
    assert early.error.code.value == "explicit_confirmation_required"
    assert session.store.count_bookings(session.tenant.tenant_id) == before

    session.note_agent_state("listening")
    committed = session.book_appointment()

    assert committed.ok is True
    assert committed.stage == "booked"
    assert session.store.count_bookings(session.tenant.tenant_id) == before + 1


def test_confirmation_defers_a_new_phone_number(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, use 555-123-4567.")

    assert session.confirmation_step("Yes, use 555-123-4567.") is None
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == 4


def test_a_new_caller_phone_invalidates_a_stale_readback(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    assert session.pending is not None

    session.note_caller_utterance("My phone is 555-123-4567.")

    assert session.pending is None
    assert session.state.outcome is None


def test_confirmation_name_change_invalidates_the_readback(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, my name is Bob.")

    assert session.confirmation_step("Yes, my name is Bob.") is None
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == 4


def test_confirmation_unparsed_name_fails_closed(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, my name is .")

    assert session.confirmation_step("Yes, my name is .") is None
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == 4


def test_confirmation_matching_name_commits(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, my name is Sam Rivera.")

    message = session.confirmation_step("Yes, my name is Sam Rivera.")

    assert message is not None
    assert session.state.outcome == "booked"


@pytest.mark.parametrize(
    "phrase", ["Yes, tomorrow.", "Yes, next week.", "Yes, at two.", "Yes, 2pm."]
)
def test_confirmation_unmatched_schedule_phrases_invalidate(
    session: AudioCallSession, phrase: str
) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance(phrase)

    assert session.confirmation_step(phrase) is None
    assert session.pending is None
    assert session.store.count_bookings(session.tenant.tenant_id) == 4


def test_confirmation_accepts_a_matching_spoken_time(session: AudioCallSession) -> None:
    slot = first_slot(session)
    session.book_appointment(slot_id=slot["slot_id"], service_id="drain_cleaning", **CUSTOMER)
    session.note_caller_utterance("Yes, at seven.")

    message = session.confirmation_step("Yes, at seven.")

    assert message is not None
    assert session.state.outcome == "booked"

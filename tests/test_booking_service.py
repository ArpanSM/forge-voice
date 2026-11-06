from __future__ import annotations

from datetime import date, timedelta

import pytest

from forge_voice.adapters import Outbox, SQLiteAdapter
from forge_voice.policy import (
    Address,
    BookingError,
    BookingService,
    ConversationPolicy,
    CustomerInput,
    canonical_booking_payload,
    canonical_cancel_payload,
    canonical_reschedule_payload,
)
from forge_voice.policy.booking import BookingWrite

CUSTOMER = CustomerInput(
    name="Sam Rivera",
    phone="+14155550101",
    address=Address(line1="12 Alder St", city="San Francisco", state="CA", zip="94107"),
)


@pytest.fixture
def store(seed_data):
    database = SQLiteAdapter(":memory:")
    for data in seed_data.values():
        database.seed(data)
    return database


@pytest.fixture
def outbox():
    return Outbox()


@pytest.fixture
def service(harborlight, store, outbox, clock):
    return BookingService(harborlight, store, outbox, clock)


def _offer(service: BookingService, *, service_id="drain_cleaning", day=date(2026, 11, 9)):
    return service.get_availability(service_id, "94107", preferred_date=day)


def _token(
    policy: ConversationPolicy,
    call_id: str,
    target: str,
    payload: dict,
    *,
    caller_phone: str = "+14155550101",
    utterance: str = "yes, book it",
    intent: str = "book",
):
    state = policy.start_call(call_id, caller_phone)
    policy.identify_intent(
        state,
        {
            "book": "I need a drain cleaning",
            "reschedule": "I need to move my appointment",
            "cancel": "I need to cancel my appointment",
        }[intent],
    )
    policy.record_readback(state, payload)
    policy.confirm(state, utterance)
    return policy.issue_confirmation(state, target=target, payload=payload)


def test_clean_booking_commits_one_row_after_confirmation(
    service, store, outbox, harborlight, clock
) -> None:
    slot = _offer(service).slots[0]
    payload = canonical_booking_payload("drain_cleaning", slot.slot_id, CUSTOMER)
    policy = ConversationPolicy(harborlight, clock, service.tokens)
    token = _token(policy, "call_1", slot.slot_id, payload)

    result = service.book(
        call_id="call_1",
        customer=CUSTOMER,
        service_id="drain_cleaning",
        slot_id=slot.slot_id,
        confirmed=True,
        token=token.token,
    )

    assert isinstance(result, BookingWrite)
    assert result.replayed is False
    assert result.booking.status == "booked"
    assert result.booking.contact_phone == CUSTOMER.phone
    assert store.count_bookings("harborlight", slot_id=slot.slot_id) == 1
    assert store.get_slot("harborlight", slot.slot_id).status == "booked"
    assert len(outbox.messages) == 1
    assert outbox.messages[0].booking_id == result.booking.booking_id
    assert any(event.tool == "booking_committed" for event in store.list_events("harborlight"))


def test_premature_write_is_rejected_with_explicit_confirmation_required(service, store) -> None:
    slot = _offer(service).slots[0]

    with pytest.raises(BookingError) as exc:
        service.book(
            call_id="call_1",
            customer=CUSTOMER,
            service_id="drain_cleaning",
            slot_id=slot.slot_id,
            confirmed=False,
            token=None,
        )

    assert exc.value.code == "explicit_confirmation_required"
    assert store.count_bookings("harborlight") == 4


def test_same_idempotency_key_and_payload_replays_same_booking(
    service, store, outbox, harborlight, clock
) -> None:
    slot = _offer(service).slots[0]
    payload = canonical_booking_payload("drain_cleaning", slot.slot_id, CUSTOMER)
    token = _token(
        ConversationPolicy(harborlight, clock, service.tokens), "call_1", slot.slot_id, payload
    )

    first = service.book(
        call_id="call_1",
        customer=CUSTOMER,
        service_id="drain_cleaning",
        slot_id=slot.slot_id,
        confirmed=True,
        token=token.token,
    )
    replay = service.book(
        call_id="call_1",
        customer=CUSTOMER,
        service_id="drain_cleaning",
        slot_id=slot.slot_id,
        confirmed=True,
        token=token.token,
    )

    assert replay.booking.booking_id == first.booking.booking_id
    assert replay.replayed is True
    assert store.count_bookings("harborlight", slot_id=slot.slot_id) == 1
    assert len(outbox.messages) == 1


def test_same_key_with_different_payload_conflicts(service, harborlight, clock) -> None:
    slot = _offer(service).slots[0]
    payload = canonical_booking_payload("drain_cleaning", slot.slot_id, CUSTOMER)
    token = _token(
        ConversationPolicy(harborlight, clock, service.tokens), "call_1", slot.slot_id, payload
    )
    service.book(
        call_id="call_1",
        customer=CUSTOMER,
        service_id="drain_cleaning",
        slot_id=slot.slot_id,
        confirmed=True,
        token=token.token,
    )
    other = CUSTOMER.model_copy(update={"name": "Someone Else"})

    with pytest.raises(BookingError) as exc:
        service.book(
            call_id="call_1",
            customer=other,
            service_id="drain_cleaning",
            slot_id=slot.slot_id,
            confirmed=True,
            token="ct_unused_for_conflict",
        )

    assert exc.value.code == "idempotency_conflict"


def test_double_booking_second_caller_gets_slot_unavailable(
    service, store, harborlight, clock
) -> None:
    first_offer = _offer(service).slots[0]
    second_offer = _offer(service).slots[0]
    assert second_offer.slot_id == first_offer.slot_id
    payload = canonical_booking_payload("drain_cleaning", first_offer.slot_id, CUSTOMER)
    token = _token(
        ConversationPolicy(harborlight, clock, service.tokens),
        "call_1",
        first_offer.slot_id,
        payload,
    )
    service.book(
        call_id="call_1",
        customer=CUSTOMER,
        service_id="drain_cleaning",
        slot_id=first_offer.slot_id,
        confirmed=True,
        token=token.token,
    )
    other = CUSTOMER.model_copy(update={"name": "Second Caller", "phone": "+14155550113"})
    other_payload = canonical_booking_payload("drain_cleaning", second_offer.slot_id, other)
    other_token = _token(
        ConversationPolicy(harborlight, clock, service.tokens),
        "call_2",
        second_offer.slot_id,
        other_payload,
        caller_phone=other.phone,
    )

    with pytest.raises(BookingError) as exc:
        service.book(
            call_id="call_2",
            customer=other,
            service_id="drain_cleaning",
            slot_id=second_offer.slot_id,
            confirmed=True,
            token=other_token.token,
        )

    assert exc.value.code == "slot_unavailable"
    assert store.count_bookings("harborlight", slot_id=first_offer.slot_id) == 1


def test_expired_offer_is_rejected_then_refreshed_and_booked(
    service, store, harborlight, clock
) -> None:
    first = _offer(service).slots[0]
    clock.advance(timedelta(seconds=harborlight.policies.offer_ttl_seconds + 1))
    payload = canonical_booking_payload("drain_cleaning", first.slot_id, CUSTOMER)
    policy = ConversationPolicy(harborlight, clock, service.tokens)
    token = _token(policy, "call_1", first.slot_id, payload)

    with pytest.raises(BookingError) as exc:
        service.book(
            call_id="call_1",
            customer=CUSTOMER,
            service_id="drain_cleaning",
            slot_id=first.slot_id,
            confirmed=True,
            token=token.token,
        )
    assert exc.value.code == "slot_expired"

    refreshed = _offer(service).slots[0]
    payload = canonical_booking_payload("drain_cleaning", refreshed.slot_id, CUSTOMER)
    state = policy.start_call("call_1", CUSTOMER.phone)
    policy.identify_intent(state, "book")
    policy.record_readback(state, payload)
    policy.confirm(state, "yes, that one")
    fresh_token = policy.issue_confirmation(state, target=refreshed.slot_id, payload=payload)

    booked = service.book(
        call_id="call_1",
        customer=CUSTOMER,
        service_id="drain_cleaning",
        slot_id=refreshed.slot_id,
        confirmed=True,
        token=fresh_token.token,
    )
    assert booked.booking.slot_id == refreshed.slot_id
    assert store.count_bookings("harborlight", slot_id=refreshed.slot_id) == 1


def test_reschedule_moves_same_booking_and_releases_old_slot(
    service, store, harborlight, clock
) -> None:
    old = store.get_booking("harborlight", "bk_0001")
    offer = _offer(service, day=date(2026, 11, 10)).slots[0]
    payload = canonical_reschedule_payload("bk_0001", offer.slot_id)
    token = _token(
        ConversationPolicy(harborlight, clock, service.tokens),
        "call_move",
        offer.slot_id,
        payload,
        intent="reschedule",
    )

    result = service.reschedule(
        call_id="call_move",
        booking_id="bk_0001",
        new_slot_id=offer.slot_id,
        caller_phone=CUSTOMER.phone,
        ownership_verified=False,
        confirmed=True,
        token=token.token,
    )

    moved = store.get_booking("harborlight", "bk_0001")
    assert result.booking.booking_id == "bk_0001"
    assert moved.start == offer.start
    assert moved.slot_id == offer.slot_id
    assert store.get_slot("harborlight", old.slot_id).status == "open"
    assert store.get_slot("harborlight", offer.slot_id).status == "booked"
    assert store.count_bookings("harborlight") == 4


def test_failed_reschedule_leaves_old_booking_and_slot_intact(
    service, store, harborlight, clock
) -> None:
    old = store.get_booking("harborlight", "bk_0001")
    offer = _offer(service, day=date(2026, 11, 10)).slots[0]
    payload = canonical_reschedule_payload("bk_0001", offer.slot_id)
    token = _token(
        ConversationPolicy(harborlight, clock, service.tokens),
        "call_move",
        offer.slot_id,
        payload,
        intent="reschedule",
    )
    store.set_slot_status("harborlight", offer.slot_id, "booked")

    with pytest.raises(BookingError) as exc:
        service.reschedule(
            call_id="call_move",
            booking_id="bk_0001",
            new_slot_id=offer.slot_id,
            caller_phone=CUSTOMER.phone,
            ownership_verified=False,
            confirmed=True,
            token=token.token,
        )

    assert exc.value.code == "slot_unavailable"
    unchanged = store.get_booking("harborlight", "bk_0001")
    assert unchanged.slot_id == old.slot_id
    assert unchanged.start == old.start
    assert unchanged.status == "booked"
    assert store.get_slot("harborlight", old.slot_id).status == "booked"


def test_reschedule_enforces_ownership_and_cutoff(service, store, harborlight, clock) -> None:
    offer = _offer(service, day=date(2026, 11, 10)).slots[0]
    payload = canonical_reschedule_payload("bk_0001", offer.slot_id)
    token = _token(
        ConversationPolicy(harborlight, clock, service.tokens),
        "call_move",
        offer.slot_id,
        payload,
        caller_phone="+14155550999",
        intent="reschedule",
    )

    with pytest.raises(BookingError) as exc:
        service.reschedule(
            call_id="call_move",
            booking_id="bk_0001",
            new_slot_id=offer.slot_id,
            caller_phone="+14155550999",
            ownership_verified=False,
            confirmed=True,
            token=token.token,
        )
    assert exc.value.code == "ownership_mismatch"

    booking = store.get_booking("harborlight", "bk_0003")
    clock.advance(booking.start - clock.now - timedelta(minutes=90))
    cutoff_payload = canonical_reschedule_payload("bk_0003", offer.slot_id)
    cutoff_token = _token(
        ConversationPolicy(harborlight, clock, service.tokens),
        "call_late",
        offer.slot_id,
        cutoff_payload,
        caller_phone=booking.contact_phone,
        intent="reschedule",
    )
    with pytest.raises(BookingError) as exc:
        service.reschedule(
            call_id="call_late",
            booking_id="bk_0003",
            new_slot_id=offer.slot_id,
            caller_phone=booking.contact_phone,
            ownership_verified=False,
            confirmed=True,
            token=cutoff_token.token,
        )
    assert exc.value.code == "cutoff_passed"


def test_cancel_releases_slot_and_second_cancel_is_idempotent(
    service, store, outbox, harborlight, clock
) -> None:
    booking = store.get_booking("harborlight", "bk_0002")
    payload = canonical_cancel_payload("bk_0002")
    token = _token(
        ConversationPolicy(harborlight, clock, service.tokens),
        "call_cancel",
        "bk_0002",
        payload,
        caller_phone=booking.contact_phone,
        utterance="yes, cancel it",
        intent="cancel",
    )

    result = service.cancel(
        call_id="call_cancel",
        booking_id="bk_0002",
        caller_phone=booking.contact_phone,
        ownership_verified=False,
        confirmed=True,
        token=token.token,
        reason="no_longer_needed",
    )

    assert result.already_cancelled is False
    assert store.get_booking("harborlight", "bk_0002").status == "cancelled"
    assert store.get_slot("harborlight", booking.slot_id).status == "open"
    assert len(outbox.messages) == 1

    second = service.cancel(
        call_id="call_cancel_2",
        booking_id="bk_0002",
        caller_phone=booking.contact_phone,
        ownership_verified=False,
        confirmed=True,
        token=None,
        reason="other",
    )
    assert second.already_cancelled is True
    assert len(outbox.messages) == 1


def test_cancel_enforces_ownership_and_cutoff(service, store, harborlight, clock) -> None:
    with pytest.raises(BookingError) as exc:
        service.cancel(
            call_id="call_cancel",
            booking_id="bk_0002",
            caller_phone="+14155550999",
            ownership_verified=False,
            confirmed=True,
            token=None,
        )
    assert exc.value.code == "ownership_mismatch"

    booking = store.get_booking("harborlight", "bk_0003")
    clock.advance(booking.start - clock.now - timedelta(minutes=30))
    with pytest.raises(BookingError) as exc:
        service.cancel(
            call_id="call_cancel_late",
            booking_id="bk_0003",
            caller_phone=booking.contact_phone,
            ownership_verified=False,
            confirmed=True,
            token=None,
        )
    assert exc.value.code == "cutoff_passed"
    assert store.get_booking("harborlight", "bk_0003").status == "booked"


def test_cross_tenant_booking_id_is_not_found_without_disclosure(service) -> None:
    with pytest.raises(BookingError) as exc:
        service.cancel(
            call_id="call_cross",
            booking_id="bk_summit_0001",
            caller_phone="+14085550101",
            ownership_verified=True,
            confirmed=True,
            token=None,
        )

    assert exc.value.code == "not_found"
    assert "Meridian" not in exc.value.message
    assert "Summit" not in exc.value.message

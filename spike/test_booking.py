from __future__ import annotations

from spike.booking import BookingStore, Customer, Service, Slot


def make_store() -> BookingStore:
    store = BookingStore()
    store.add_service(Service("drain", "Drain cleaning", 60))
    store.add_service(Service("hvac", "AC repair", 90))
    store.add_slot(
        Slot("slot_1", "drain", "Alex", "2026-11-09T09:00", frozenset({"94107"}))
    )
    store.add_slot(
        Slot("slot_2", "hvac", "Blair", "2026-11-09T11:00", frozenset({"94107"}))
    )
    return store


def customer(zip_code: str = "94107") -> Customer:
    return Customer("Sam Rivera", "555-0101", "12 Alder St", zip_code)


def test_clean_booking_marks_the_slot_unavailable() -> None:
    store = make_store()
    result = store.book_appointment(
        customer=customer(),
        service_id="drain",
        slot_id="slot_1",
        idempotency_key="call-1",
        confirmed=True,
    )
    assert result.ok
    assert result.booking is not None
    assert result.booking.booking_id == "bk_0001"
    assert store.get_availability("drain", "94107") == []


def test_booking_requires_confirmation() -> None:
    store = make_store()
    result = store.book_appointment(
        customer=customer(),
        service_id="drain",
        slot_id="slot_1",
        idempotency_key="call-1",
        confirmed=False,
    )
    assert not result.ok
    assert result.error == "confirmation_required"
    assert store.bookings == {}


def test_no_availability_outside_the_service_area() -> None:
    store = make_store()
    assert store.get_availability("drain", "10001") == []


def test_same_key_and_args_replays_without_a_second_row() -> None:
    store = make_store()
    first = store.book_appointment(
        customer=customer(),
        service_id="drain",
        slot_id="slot_1",
        idempotency_key="call-1",
        confirmed=True,
    )
    second = store.book_appointment(
        customer=customer(),
        service_id="drain",
        slot_id="slot_1",
        idempotency_key="call-1",
        confirmed=True,
    )
    assert first.booking is not None
    assert second.ok and second.replayed
    assert second.booking is not None
    assert second.booking.booking_id == first.booking.booking_id
    assert len(store.bookings) == 1


def test_same_key_different_args_is_a_conflict() -> None:
    store = make_store()
    store.book_appointment(
        customer=customer(),
        service_id="drain",
        slot_id="slot_1",
        idempotency_key="call-1",
        confirmed=True,
    )
    conflict = store.book_appointment(
        customer=customer(),
        service_id="hvac",
        slot_id="slot_2",
        idempotency_key="call-1",
        confirmed=True,
    )
    assert not conflict.ok
    assert conflict.error == "idempotency_conflict"
    assert len(store.bookings) == 1


def test_double_booking_is_refused() -> None:
    store = make_store()
    first = store.book_appointment(
        customer=customer(),
        service_id="drain",
        slot_id="slot_1",
        idempotency_key="call-1",
        confirmed=True,
    )
    second = store.book_appointment(
        customer=customer(),
        service_id="drain",
        slot_id="slot_1",
        idempotency_key="call-2",
        confirmed=True,
    )
    assert first.ok
    assert not second.ok
    assert second.error == "slot_unavailable"
    assert len(store.bookings) == 1

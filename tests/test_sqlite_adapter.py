from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from forge_voice.adapters import SQLiteAdapter
from forge_voice.domain import (
    ConfirmationRecord,
    EventRecord,
    IdempotencyRecord,
    TokenRecord,
)

LA = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def store(seed_data):
    database = SQLiteAdapter(":memory:")
    for data in seed_data.values():
        database.seed(data)
    return database


def test_seed_loads_both_tenants_without_crossing(store) -> None:
    assert len(store.list_customers("harborlight")) == 4
    assert len(store.list_customers("summit")) == 2
    assert store.get_customer("harborlight", "cus_summit_0001") is None
    assert store.get_booking("harborlight", "bk_summit_0001") is None
    assert store.get_slot("harborlight", "slot_sm_00001") is None


def test_booking_reads_are_tenant_scoped(store) -> None:
    summit = store.get_booking("summit", "bk_summit_0001")

    assert summit is not None
    assert summit.tenant_id == "summit"
    assert store.list_bookings("harborlight", slot_id=summit.slot_id) == []


def test_slot_reads_are_tenant_scoped(store) -> None:
    assert store.get_slot("harborlight", "slot_sm_00001") is None


def test_events_are_append_only(store, clock) -> None:
    first = store.append_event(
        tenant_id="harborlight",
        call_id="call_1",
        request_id="req_1",
        tool="lookup_customer",
        result_code="ok",
        latency_ms=2,
        args={"phone": "***"},
        result={"ok": True},
        created_at=clock.now,
    )
    second = store.append_event(
        tenant_id="summit",
        call_id="call_2",
        request_id="req_2",
        tool="get_service_area",
        result_code="ok",
        latency_ms=1,
        args={"zip": "95125"},
        result={"ok": True},
        created_at=clock.now,
    )

    assert isinstance(first, EventRecord)
    assert second.event_id > first.event_id


def test_events_are_tenant_scoped(store, clock) -> None:
    store.append_event(
        tenant_id="harborlight",
        call_id="call_1",
        request_id="req_1",
        tool="lookup_customer",
        result_code="ok",
        latency_ms=2,
        args={"phone": "***"},
        result={"ok": True},
        created_at=clock.now,
    )
    store.append_event(
        tenant_id="summit",
        call_id="call_2",
        request_id="req_2",
        tool="get_service_area",
        result_code="ok",
        latency_ms=1,
        args={"zip": "95125"},
        result={"ok": True},
        created_at=clock.now,
    )

    assert [event.call_id for event in store.list_events("harborlight")] == ["call_1"]
    assert [event.call_id for event in store.list_events("summit")] == ["call_2"]


def test_idempotency_round_trip_is_tenant_scoped(store, clock) -> None:
    record = IdempotencyRecord(
        key="harborlight:call_1:book:slot_1",
        tenant_id="harborlight",
        call_id="call_1",
        intent="book",
        target="slot_1",
        payload_hash="a" * 64,
        result_json="{}",
        created_at=clock.now,
    )
    store.put_idempotency(record)

    assert store.get_idempotency("harborlight", record.key) == record
    assert store.get_idempotency("summit", record.key) is None


def test_token_expiry_is_compared_across_timezone_offsets(store, clock) -> None:
    base = TokenRecord(
        token="ct_offset",
        tenant_id="harborlight",
        call_id="call_1",
        intent="book",
        target="slot_1",
        payload_hash="a" * 64,
        issued_at=datetime(2026, 11, 9, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
        expires_at=datetime(2026, 11, 9, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
    )
    store.insert_token(base)

    assert (
        store.consume_token(
            "harborlight", "ct_offset", datetime(2026, 11, 9, 16, 59, 59, tzinfo=UTC)
        )
        is True
    )

    store.insert_token(base.model_copy(update={"token": "ct_expired"}))
    assert (
        store.consume_token(
            "harborlight", "ct_expired", datetime(2026, 11, 9, 17, 0, 1, tzinfo=UTC)
        )
        is False
    )


def test_token_and_confirmation_writes_are_tenant_scoped(store, clock) -> None:
    token = TokenRecord(
        token="ct_scoped",
        tenant_id="harborlight",
        call_id="call_1",
        intent="book",
        target="slot_1",
        payload_hash="a" * 64,
        issued_at=clock.now,
        expires_at=clock.now,
    )
    store.insert_token(token)
    confirmation = ConfirmationRecord(
        message_id="sms_scoped",
        tenant_id="harborlight",
        booking_id="bk_0001",
        to="+14155550101",
        created_at=clock.now,
    )
    store.insert_confirmation(confirmation)

    assert store.get_token("summit", "ct_scoped") is None
    assert store.consume_token("summit", "ct_scoped", clock.now) is False
    store.mark_confirmation_drained("summit", "sms_scoped", clock.now)
    assert len(store.list_undrained_confirmations("harborlight")) == 1
    assert store.list_undrained_confirmations("summit") == []


def test_nested_transactions_fail_cleanly(store) -> None:
    with (  # noqa: SIM117 - the inner transaction must fail
        pytest.raises(RuntimeError, match="nested"),
        store.transaction(),
    ):
        with store.transaction():
            pass

    with store.transaction():
        store.next_sequence("harborlight", "after_nested")

    assert store.next_sequence("harborlight", "after_nested") == 2


def test_transaction_rolls_back_a_failed_write(store) -> None:
    before = store.count_bookings("harborlight")

    with (
        pytest.raises(RuntimeError),
        store.transaction(),
    ):
        store.append_event(
            tenant_id="harborlight",
            call_id="call_bad",
            request_id="req_bad",
            tool="book_appointment",
            result_code="internal_error",
            latency_ms=1,
            args={},
            result={},
            created_at=datetime(2026, 11, 6, 8, 0, tzinfo=LA),
        )
        raise RuntimeError("stop")

    assert store.count_bookings("harborlight") == before
    assert store.list_events("harborlight", tool="book_appointment") == []

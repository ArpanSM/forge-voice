"""SQLite local adapters for calendar, CRM, bookings, tickets, callbacks and events.

Every read and write takes a tenant id and filters on it. No method exposes a row from another
tenant, and no adapter reaches the network.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

from forge_voice.domain import (
    Address,
    BookingRecord,
    CallbackRecord,
    ConfirmationRecord,
    CustomerRecord,
    EventRecord,
    IdempotencyRecord,
    SlotRecord,
    TicketRecord,
    TokenRecord,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    line1 TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_customers_tenant_phone ON customers(tenant_id, phone);
CREATE INDEX IF NOT EXISTS ix_customers_tenant_name ON customers(tenant_id, name);

CREATE TABLE IF NOT EXISTS slots (
    slot_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    technician_id TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'booked'))
);
CREATE INDEX IF NOT EXISTS ix_slots_tenant_service_start
    ON slots(tenant_id, service_id, status, start);

CREATE TABLE IF NOT EXISTS bookings (
    booking_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    service_id TEXT NOT NULL,
    technician_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('booked', 'cancelled')),
    contact_phone TEXT NOT NULL,
    line1 TEXT NOT NULL,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    zip TEXT NOT NULL,
    reason TEXT,
    confirmation_sms TEXT NOT NULL DEFAULT 'not_requested',
    confirmation_email TEXT NOT NULL DEFAULT 'not_requested',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cancelled_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_bookings_active_slot
    ON bookings(tenant_id, slot_id) WHERE status = 'booked';
CREATE INDEX IF NOT EXISTS ix_bookings_tenant_customer ON bookings(tenant_id, customer_id);

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    customer_id TEXT,
    customer_name TEXT,
    customer_phone TEXT,
    line1 TEXT,
    city TEXT,
    state TEXT,
    zip TEXT,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL,
    safety_instructions_given TEXT NOT NULL,
    transfer_mode TEXT NOT NULL,
    transfer_id TEXT,
    on_call_target TEXT NOT NULL,
    callback_sla_minutes INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tickets_tenant_call ON tickets(tenant_id, call_id);

CREATE TABLE IF NOT EXISTS callbacks (
    callback_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,
    reason TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    sla TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_callbacks_tenant_call ON callbacks(tenant_id, call_id);

CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    result_code TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    args_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_tenant_call ON events(tenant_id, call_id);

CREATE TABLE IF NOT EXISTS idempotency (
    key TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    intent TEXT NOT NULL,
    target TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    token TEXT
);

CREATE TABLE IF NOT EXISTS confirmation_tokens (
    token TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    call_id TEXT NOT NULL,
    intent TEXT NOT NULL,
    target TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tokens_tenant_call
    ON confirmation_tokens(tenant_id, call_id);

CREATE TABLE IF NOT EXISTS sequences (
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    value INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, name)
);

CREATE TABLE IF NOT EXISTS confirmations (
    message_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    booking_id TEXT NOT NULL,
    to_number TEXT NOT NULL,
    channel TEXT NOT NULL,
    template TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    drained_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_confirmations_tenant_booking
    ON confirmations(tenant_id, booking_id);

CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    caller_phone TEXT,
    intent TEXT NOT NULL,
    outcome TEXT NOT NULL,
    transfer_status TEXT,
    booking_id TEXT,
    ticket_id TEXT,
    callback_id TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    recording_ref TEXT NOT NULL,
    qa_flags_json TEXT NOT NULL
);
"""


def _iso(value: datetime) -> str:
    return value.isoformat()


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _address(row: Mapping[str, Any]) -> Address:
    return Address(
        line1=row["line1"],
        city=row["city"],
        state=row["state"],
        zip=row["zip"],
    )


def _locked_method(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


def _serialized(cls):
    for name, value in list(cls.__dict__.items()):
        if name.startswith("_") or name in {"transaction", "close"}:
            continue
        if callable(value):
            setattr(cls, name, _locked_method(value))
    return cls


@_serialized
class SQLiteAdapter:
    """One local database behind the synthetic calendar, CRM, booking and audit ports."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._in_transaction = False
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.isolation_level = None
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self._lock:
            if self._in_transaction:
                raise RuntimeError(
                    "nested SQLite transactions are not supported; use an in-transaction method"
                )
            self._conn.execute("BEGIN IMMEDIATE")
            self._in_transaction = True
            try:
                yield
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
            finally:
                self._in_transaction = False

    def next_sequence(self, tenant_id: str, name: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "INSERT INTO sequences(tenant_id, name, value) VALUES (?, ?, 1) "
                "ON CONFLICT(tenant_id, name) DO UPDATE SET value = value + 1 "
                "RETURNING value",
                (tenant_id, name),
            ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------ seed
    def seed(self, data: Mapping[str, Any]) -> None:
        with self.transaction():
            for customer in data.get("customers", []):
                self._insert_customer(
                    CustomerRecord(
                        customer_id=customer["customer_id"],
                        tenant_id=customer["tenant_id"],
                        name=customer["name"],
                        phone=customer["phone"],
                        address=Address.model_validate(customer["address"]),
                        created_at=customer["created_at"],
                    )
                )
            for slot in data.get("slots", []):
                self._conn.execute(
                    "INSERT INTO slots VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        slot["slot_id"],
                        slot["tenant_id"],
                        slot["service_id"],
                        slot["technician_id"],
                        slot["start"],
                        slot["end"],
                        slot["status"],
                    ),
                )
            for booking in data.get("bookings", []):
                self._insert_booking(
                    BookingRecord(
                        booking_id=booking["booking_id"],
                        tenant_id=booking["tenant_id"],
                        customer_id=booking["customer_id"],
                        service_id=booking["service_id"],
                        technician_id=booking["technician_id"],
                        slot_id=booking["slot_id"],
                        start=booking["start"],
                        end=booking["end"],
                        status=booking["status"],
                        contact_phone=booking["contact_phone"],
                        address=Address.model_validate(booking["address"]),
                        confirmation_sms=booking["confirmation"]["sms"],
                        confirmation_email=booking["confirmation"]["email"],
                        created_at=booking["start"],
                        updated_at=booking["start"],
                    )
                )
            customer_by_id = {
                customer["customer_id"]: customer for customer in data.get("customers", [])
            }
            for ticket in data.get("tickets", []):
                customer = customer_by_id.get(ticket.get("customer_id"))
                address = customer["address"] if customer else {}
                self._conn.execute(
                    "INSERT INTO tickets VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ticket["ticket_id"],
                        ticket["tenant_id"],
                        ticket["call_id"],
                        ticket.get("customer_id"),
                        customer["name"] if customer else None,
                        customer["phone"] if customer else None,
                        address.get("line1"),
                        address.get("city"),
                        address.get("state"),
                        address.get("zip"),
                        ticket["category"],
                        ticket["severity"],
                        ticket["description"],
                        json.dumps(ticket["safety_instructions_given"]),
                        ticket["transfer_mode"],
                        ticket.get("transfer_id"),
                        ticket.get("on_call_target", ""),
                        ticket.get("callback_sla_minutes", 0),
                        ticket["status"],
                        ticket["created_at"],
                    ),
                )
            tenant_id = data["tenant_id"]
            self._seed_sequence(
                tenant_id, "customer", [item["customer_id"] for item in data.get("customers", [])]
            )
            self._seed_sequence(
                tenant_id, "booking", [item["booking_id"] for item in data.get("bookings", [])]
            )
            self._seed_sequence(
                tenant_id, "ticket", [item["ticket_id"] for item in data.get("tickets", [])]
            )

    def _seed_sequence(self, tenant_id: str, name: str, ids: list[str]) -> None:
        prefix = {"customer": "cus", "booking": "bk", "ticket": "em", "callback": "cb"}[name]
        pattern = re.compile(rf"^{re.escape(prefix)}_{re.escape(tenant_id)}_(\d+)$")
        maximum = 0
        for identifier in ids:
            match = pattern.match(identifier)
            if match:
                maximum = max(maximum, int(match.group(1)))
        if maximum:
            self._conn.execute(
                "INSERT INTO sequences(tenant_id, name, value) VALUES (?, ?, ?) "
                "ON CONFLICT(tenant_id, name) DO UPDATE SET value = MAX(value, excluded.value)",
                (tenant_id, name, maximum),
            )

    # -------------------------------------------------------------- customers
    def _insert_customer(self, record: CustomerRecord) -> None:
        self._conn.execute(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.customer_id,
                record.tenant_id,
                record.name,
                record.phone,
                record.address.line1,
                record.address.city,
                record.address.state,
                record.address.zip,
                _iso(record.created_at),
            ),
        )

    def create_customer(self, record: CustomerRecord) -> CustomerRecord:
        with self.transaction():
            self._insert_customer(record)
        return record

    def insert_customer(self, record: CustomerRecord) -> CustomerRecord:
        """Insert inside an existing transaction owned by the caller."""
        self._insert_customer(record)
        return record

    def get_customer(self, tenant_id: str, customer_id: str) -> CustomerRecord | None:
        row = self._conn.execute(
            "SELECT * FROM customers WHERE tenant_id = ? AND customer_id = ?",
            (tenant_id, customer_id),
        ).fetchone()
        return self._customer(row) if row else None

    def find_customers(
        self,
        tenant_id: str,
        *,
        phone: str | None = None,
        name: str | None = None,
        zip_code: str | None = None,
        line1: str | None = None,
    ) -> list[CustomerRecord]:
        clauses = ["tenant_id = ?"]
        values: list[Any] = [tenant_id]
        if phone:
            clauses.append("phone = ?")
            values.append(phone)
        if name:
            clauses.append("lower(name) = lower(?)")
            values.append(name)
        if zip_code:
            clauses.append("zip = ?")
            values.append(zip_code)
        if line1:
            clauses.append("lower(line1) = lower(?)")
            values.append(line1)
        rows = self._conn.execute(
            f"SELECT * FROM customers WHERE {' AND '.join(clauses)} ORDER BY customer_id",
            values,
        ).fetchall()
        return [self._customer(row) for row in rows]

    def list_customers(self, tenant_id: str) -> list[CustomerRecord]:
        rows = self._conn.execute(
            "SELECT * FROM customers WHERE tenant_id = ? ORDER BY customer_id", (tenant_id,)
        ).fetchall()
        return [self._customer(row) for row in rows]

    # ------------------------------------------------------------------ slots
    def get_slot(self, tenant_id: str, slot_id: str) -> SlotRecord | None:
        row = self._conn.execute(
            "SELECT * FROM slots WHERE tenant_id = ? AND slot_id = ?", (tenant_id, slot_id)
        ).fetchone()
        return self._slot(row) if row else None

    def insert_slot(self, record: SlotRecord) -> SlotRecord:
        self._conn.execute(
            "INSERT INTO slots VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record.slot_id,
                record.tenant_id,
                record.service_id,
                record.technician_id,
                _iso(record.start),
                _iso(record.end),
                record.status,
            ),
        )
        return record

    def list_open_slots(
        self,
        tenant_id: str,
        *,
        service_id: str,
        start_from: datetime,
        start_before: datetime,
        exclude_slot_ids: tuple[str, ...] = (),
    ) -> list[SlotRecord]:
        clauses = [
            "tenant_id = ?",
            "service_id = ?",
            "status = 'open'",
            "start >= ?",
            "start < ?",
        ]
        values: list[Any] = [tenant_id, service_id, _iso(start_from), _iso(start_before)]
        if exclude_slot_ids:
            placeholders = ", ".join("?" for _ in exclude_slot_ids)
            clauses.append(f"slot_id NOT IN ({placeholders})")
            values.extend(exclude_slot_ids)
        rows = self._conn.execute(
            f"SELECT * FROM slots WHERE {' AND '.join(clauses)} ORDER BY start, slot_id",
            values,
        ).fetchall()
        return [self._slot(row) for row in rows]

    def set_slot_status(self, tenant_id: str, slot_id: str, status: str) -> None:
        with self.transaction():
            self._set_slot_status(tenant_id, slot_id, status)

    def set_slot_status_in_transaction(self, tenant_id: str, slot_id: str, status: str) -> None:
        self._set_slot_status(tenant_id, slot_id, status)

    def _set_slot_status(self, tenant_id: str, slot_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE slots SET status = ? WHERE tenant_id = ? AND slot_id = ?",
            (status, tenant_id, slot_id),
        )

    # --------------------------------------------------------------- bookings
    def _insert_booking(self, record: BookingRecord) -> None:
        self._conn.execute(
            "INSERT INTO bookings VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.booking_id,
                record.tenant_id,
                record.customer_id,
                record.service_id,
                record.technician_id,
                record.slot_id,
                _iso(record.start),
                _iso(record.end),
                record.status,
                record.contact_phone,
                record.address.line1,
                record.address.city,
                record.address.state,
                record.address.zip,
                record.reason,
                record.confirmation_sms,
                record.confirmation_email,
                _iso(record.created_at),
                _iso(record.updated_at),
                _iso(record.cancelled_at) if record.cancelled_at else None,
            ),
        )

    def create_booking(self, record: BookingRecord) -> BookingRecord:
        self._insert_booking(record)
        return record

    def get_booking(self, tenant_id: str, booking_id: str) -> BookingRecord | None:
        row = self._conn.execute(
            "SELECT * FROM bookings WHERE tenant_id = ? AND booking_id = ?",
            (tenant_id, booking_id),
        ).fetchone()
        return self._booking(row) if row else None

    def list_bookings(
        self,
        tenant_id: str,
        *,
        customer_id: str | None = None,
        slot_id: str | None = None,
    ) -> list[BookingRecord]:
        clauses = ["tenant_id = ?"]
        values: list[Any] = [tenant_id]
        if customer_id:
            clauses.append("customer_id = ?")
            values.append(customer_id)
        if slot_id:
            clauses.append("slot_id = ?")
            values.append(slot_id)
        rows = self._conn.execute(
            f"SELECT * FROM bookings WHERE {' AND '.join(clauses)} ORDER BY start, booking_id",
            values,
        ).fetchall()
        return [self._booking(row) for row in rows]

    def count_bookings(self, tenant_id: str, *, slot_id: str | None = None) -> int:
        if slot_id:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE tenant_id = ? AND slot_id = ?",
                (tenant_id, slot_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM bookings WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        return int(row[0])

    def move_booking(
        self,
        tenant_id: str,
        booking_id: str,
        *,
        slot: SlotRecord,
        updated_at: datetime,
        reason: str | None = None,
    ) -> None:
        self._conn.execute(
            "UPDATE bookings SET slot_id = ?, technician_id = ?, start = ?, end = ?, "
            "updated_at = ?, reason = COALESCE(?, reason) "
            "WHERE tenant_id = ? AND booking_id = ?",
            (
                slot.slot_id,
                slot.technician_id,
                _iso(slot.start),
                _iso(slot.end),
                _iso(updated_at),
                reason,
                tenant_id,
                booking_id,
            ),
        )

    def cancel_booking(
        self,
        tenant_id: str,
        booking_id: str,
        *,
        reason: str | None,
        cancelled_at: datetime,
    ) -> None:
        self._conn.execute(
            "UPDATE bookings SET status = 'cancelled', reason = ?, cancelled_at = ?, "
            "updated_at = ? WHERE tenant_id = ? AND booking_id = ?",
            (reason, _iso(cancelled_at), _iso(cancelled_at), tenant_id, booking_id),
        )

    def set_booking_confirmation(
        self,
        tenant_id: str,
        booking_id: str,
        *,
        sms: str,
        email: str,
    ) -> None:
        self._conn.execute(
            "UPDATE bookings SET confirmation_sms = ?, confirmation_email = ? "
            "WHERE tenant_id = ? AND booking_id = ?",
            (sms, email, tenant_id, booking_id),
        )

    # --------------------------------------------------------------- tickets
    def insert_ticket(self, record: TicketRecord) -> TicketRecord:
        self._conn.execute(
            "INSERT INTO tickets VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.ticket_id,
                record.tenant_id,
                record.call_id,
                record.customer_id,
                record.customer_name,
                record.customer_phone,
                record.address.line1 if record.address else None,
                record.address.city if record.address else None,
                record.address.state if record.address else None,
                record.address.zip if record.address else None,
                record.category,
                record.severity,
                record.description,
                json.dumps(record.safety_instructions_given),
                record.transfer_mode,
                record.transfer_id,
                record.on_call_target,
                record.callback_sla_minutes,
                record.status,
                _iso(record.created_at),
            ),
        )
        return record

    def create_ticket(self, record: TicketRecord) -> TicketRecord:
        with self.transaction():
            self.insert_ticket(record)
        return record

    def get_ticket(self, tenant_id: str, ticket_id: str) -> TicketRecord | None:
        row = self._conn.execute(
            "SELECT * FROM tickets WHERE tenant_id = ? AND ticket_id = ?", (tenant_id, ticket_id)
        ).fetchone()
        return self._ticket(row) if row else None

    def list_tickets(self, tenant_id: str, *, call_id: str | None = None) -> list[TicketRecord]:
        if call_id:
            rows = self._conn.execute(
                "SELECT * FROM tickets WHERE tenant_id = ? AND call_id = ? ORDER BY ticket_id",
                (tenant_id, call_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM tickets WHERE tenant_id = ? ORDER BY ticket_id", (tenant_id,)
            ).fetchall()
        return [self._ticket(row) for row in rows]

    def set_ticket_transfer(
        self, tenant_id: str, ticket_id: str, *, transfer_id: str, status: str = "assigned"
    ) -> None:
        with self.transaction():
            self.set_ticket_transfer_in_transaction(
                tenant_id, ticket_id, transfer_id=transfer_id, status=status
            )

    def set_ticket_transfer_in_transaction(
        self, tenant_id: str, ticket_id: str, *, transfer_id: str, status: str = "assigned"
    ) -> None:
        self._conn.execute(
            "UPDATE tickets SET transfer_id = ?, status = ? WHERE tenant_id = ? AND ticket_id = ?",
            (transfer_id, status, tenant_id, ticket_id),
        )

    # -------------------------------------------------------------- callbacks
    def insert_callback(self, record: CallbackRecord) -> CallbackRecord:
        self._conn.execute(
            "INSERT INTO callbacks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.callback_id,
                record.tenant_id,
                record.call_id,
                record.name,
                record.phone,
                record.reason,
                _iso(record.window_start),
                _iso(record.window_end),
                record.sla,
                record.status,
                _iso(record.created_at),
            ),
        )
        return record

    def create_callback(self, record: CallbackRecord) -> CallbackRecord:
        with self.transaction():
            self.insert_callback(record)
        return record

    def get_callback(self, tenant_id: str, callback_id: str) -> CallbackRecord | None:
        row = self._conn.execute(
            "SELECT * FROM callbacks WHERE tenant_id = ? AND callback_id = ?",
            (tenant_id, callback_id),
        ).fetchone()
        return self._callback(row) if row else None

    def list_callbacks(self, tenant_id: str, *, call_id: str | None = None) -> list[CallbackRecord]:
        if call_id:
            rows = self._conn.execute(
                "SELECT * FROM callbacks WHERE tenant_id = ? AND call_id = ? ORDER BY callback_id",
                (tenant_id, call_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM callbacks WHERE tenant_id = ? ORDER BY callback_id", (tenant_id,)
            ).fetchall()
        return [self._callback(row) for row in rows]

    # ----------------------------------------------------------------- events
    def append_event(
        self,
        *,
        tenant_id: str,
        call_id: str,
        request_id: str,
        tool: str,
        result_code: str,
        latency_ms: int,
        args: Mapping[str, Any],
        result: Mapping[str, Any],
        created_at: datetime,
    ) -> EventRecord:
        cursor = self._conn.execute(
            "INSERT INTO events "
            "(tenant_id, call_id, request_id, tool, result_code, latency_ms, args_json, "
            "result_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                tenant_id,
                call_id,
                request_id,
                tool,
                result_code,
                latency_ms,
                json.dumps(args, sort_keys=True, default=str),
                json.dumps(result, sort_keys=True, default=str),
                _iso(created_at),
            ),
        )
        row = self._conn.execute(
            "SELECT * FROM events WHERE event_id = ?", (cursor.lastrowid,)
        ).fetchone()
        return self._event(row)

    def list_events(
        self,
        tenant_id: str,
        *,
        call_id: str | None = None,
        tool: str | None = None,
    ) -> list[EventRecord]:
        clauses = ["tenant_id = ?"]
        values: list[Any] = [tenant_id]
        if call_id:
            clauses.append("call_id = ?")
            values.append(call_id)
        if tool:
            clauses.append("tool = ?")
            values.append(tool)
        rows = self._conn.execute(
            f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY event_id", values
        ).fetchall()
        return [self._event(row) for row in rows]

    # ------------------------------------------------------------ idempotency
    def get_idempotency(self, tenant_id: str, key: str) -> IdempotencyRecord | None:
        row = self._conn.execute(
            "SELECT * FROM idempotency WHERE tenant_id = ? AND key = ?", (tenant_id, key)
        ).fetchone()
        return self._idempotency(row) if row else None

    def put_idempotency(self, record: IdempotencyRecord) -> None:
        self._conn.execute(
            "INSERT INTO idempotency VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.key,
                record.tenant_id,
                record.call_id,
                record.intent,
                record.target,
                record.payload_hash,
                record.result_json,
                _iso(record.created_at),
                record.token,
            ),
        )

    def update_idempotency_result(self, tenant_id: str, key: str, result_json: str) -> None:
        self._conn.execute(
            "UPDATE idempotency SET result_json = ? WHERE tenant_id = ? AND key = ?",
            (result_json, tenant_id, key),
        )

    # ------------------------------------------------------------ confirmations
    def add_confirmation(self, record: ConfirmationRecord) -> ConfirmationRecord:
        with self.transaction():
            self.insert_confirmation(record)
        return record

    def insert_confirmation(self, record: ConfirmationRecord) -> ConfirmationRecord:
        self._conn.execute(
            "INSERT INTO confirmations "
            "(message_id, tenant_id, booking_id, to_number, channel, template, status, "
            "created_at, drained_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                record.message_id,
                record.tenant_id,
                record.booking_id,
                record.to,
                record.channel,
                record.template,
                record.status,
                _iso(record.created_at),
            ),
        )
        return record

    def list_undrained_confirmations(self, tenant_id: str) -> list[ConfirmationRecord]:
        rows = self._conn.execute(
            "SELECT * FROM confirmations WHERE tenant_id = ? AND drained_at IS NULL "
            "ORDER BY created_at, message_id",
            (tenant_id,),
        ).fetchall()
        return [self._confirmation(row) for row in rows]

    def mark_confirmation_drained(self, tenant_id: str, message_id: str, at: datetime) -> None:
        self._conn.execute(
            "UPDATE confirmations SET drained_at = ? WHERE tenant_id = ? AND message_id = ?",
            (_iso(at), tenant_id, message_id),
        )

    def list_confirmations(self, tenant_id: str) -> list[ConfirmationRecord]:
        rows = self._conn.execute(
            "SELECT * FROM confirmations WHERE tenant_id = ? ORDER BY created_at, message_id",
            (tenant_id,),
        ).fetchall()
        return [self._confirmation(row) for row in rows]

    def count_confirmations(self, tenant_id: str, *, booking_id: str | None = None) -> int:
        if booking_id:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM confirmations WHERE tenant_id = ? AND booking_id = ?",
                (tenant_id, booking_id),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM confirmations WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
        return int(row[0])

    def next_message_id(self, tenant_id: str) -> str:
        return f"sms_{tenant_id}_{self.next_sequence(tenant_id, 'sms'):04d}"

    # ------------------------------------------------------------ tokens
    def insert_token(self, record: TokenRecord) -> TokenRecord:
        self._conn.execute(
            "INSERT INTO confirmation_tokens VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.token,
                record.tenant_id,
                record.call_id,
                record.intent,
                record.target,
                record.payload_hash,
                _iso_utc(record.issued_at),
                _iso_utc(record.expires_at),
                _iso_utc(record.used_at) if record.used_at else None,
            ),
        )
        return record

    def get_token(self, tenant_id: str, token: str) -> TokenRecord | None:
        row = self._conn.execute(
            "SELECT * FROM confirmation_tokens WHERE tenant_id = ? AND token = ?",
            (tenant_id, token),
        ).fetchone()
        return self._token(row) if row else None

    def consume_token(self, tenant_id: str, token: str, at: datetime) -> bool:
        cursor = self._conn.execute(
            "UPDATE confirmation_tokens SET used_at = ? "
            "WHERE tenant_id = ? AND token = ? AND used_at IS NULL AND expires_at > ?",
            (_iso_utc(at), tenant_id, token, _iso_utc(at)),
        )
        return cursor.rowcount == 1

    # ------------------------------------------------------------------ calls
    def save_call(
        self,
        *,
        call_id: str,
        tenant_id: str,
        caller_phone: str | None,
        intent: str,
        outcome: str,
        transfer_status: str | None,
        booking_id: str | None,
        ticket_id: str | None,
        callback_id: str | None,
        started_at: datetime,
        ended_at: datetime,
        qa_flags: list[str],
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                call_id,
                tenant_id,
                caller_phone,
                intent,
                outcome,
                transfer_status,
                booking_id,
                ticket_id,
                callback_id,
                _iso(started_at),
                _iso(ended_at),
                "text_only",
                json.dumps(qa_flags),
            ),
        )

    # --------------------------------------------------------------- row maps
    @staticmethod
    def _customer(row: sqlite3.Row) -> CustomerRecord:
        return CustomerRecord(
            customer_id=row["customer_id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            phone=row["phone"],
            address=_address(row),
            created_at=row["created_at"],
        )

    @staticmethod
    def _slot(row: sqlite3.Row) -> SlotRecord:
        return SlotRecord(
            slot_id=row["slot_id"],
            tenant_id=row["tenant_id"],
            service_id=row["service_id"],
            technician_id=row["technician_id"],
            start=row["start"],
            end=row["end"],
            status=row["status"],
        )

    @staticmethod
    def _booking(row: sqlite3.Row) -> BookingRecord:
        return BookingRecord(
            booking_id=row["booking_id"],
            tenant_id=row["tenant_id"],
            customer_id=row["customer_id"],
            service_id=row["service_id"],
            technician_id=row["technician_id"],
            slot_id=row["slot_id"],
            start=row["start"],
            end=row["end"],
            status=row["status"],
            contact_phone=row["contact_phone"],
            address=_address(row),
            reason=row["reason"],
            confirmation_sms=row["confirmation_sms"],
            confirmation_email=row["confirmation_email"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            cancelled_at=row["cancelled_at"],
        )

    @staticmethod
    def _ticket(row: sqlite3.Row) -> TicketRecord:
        address = (
            Address(
                line1=row["line1"],
                city=row["city"],
                state=row["state"],
                zip=row["zip"],
            )
            if row["line1"]
            else None
        )
        return TicketRecord(
            ticket_id=row["ticket_id"],
            tenant_id=row["tenant_id"],
            call_id=row["call_id"],
            customer_id=row["customer_id"],
            customer_name=row["customer_name"],
            customer_phone=row["customer_phone"],
            address=address,
            category=row["category"],
            severity=row["severity"],
            description=row["description"],
            safety_instructions_given=json.loads(row["safety_instructions_given"]),
            transfer_mode=row["transfer_mode"],
            transfer_id=row["transfer_id"],
            on_call_target=row["on_call_target"],
            callback_sla_minutes=row["callback_sla_minutes"],
            status=row["status"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _callback(row: sqlite3.Row) -> CallbackRecord:
        return CallbackRecord(
            callback_id=row["callback_id"],
            tenant_id=row["tenant_id"],
            call_id=row["call_id"],
            name=row["name"],
            phone=row["phone"],
            reason=row["reason"],
            window_start=row["window_start"],
            window_end=row["window_end"],
            sla=row["sla"],
            status=row["status"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _event(row: sqlite3.Row) -> EventRecord:
        return EventRecord(
            event_id=row["event_id"],
            tenant_id=row["tenant_id"],
            call_id=row["call_id"],
            request_id=row["request_id"],
            tool=row["tool"],
            result_code=row["result_code"],
            latency_ms=row["latency_ms"],
            args=json.loads(row["args_json"]),
            result=json.loads(row["result_json"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _idempotency(row: sqlite3.Row) -> IdempotencyRecord:
        return IdempotencyRecord(
            key=row["key"],
            tenant_id=row["tenant_id"],
            call_id=row["call_id"],
            intent=row["intent"],
            target=row["target"],
            payload_hash=row["payload_hash"],
            result_json=row["result_json"],
            created_at=row["created_at"],
            token=row["token"],
        )

    @staticmethod
    def _confirmation(row: sqlite3.Row) -> ConfirmationRecord:
        return ConfirmationRecord(
            message_id=row["message_id"],
            tenant_id=row["tenant_id"],
            booking_id=row["booking_id"],
            to=row["to_number"],
            channel=row["channel"],
            template=row["template"],
            status=row["status"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _token(row: sqlite3.Row) -> TokenRecord:
        return TokenRecord(
            token=row["token"],
            tenant_id=row["tenant_id"],
            call_id=row["call_id"],
            intent=row["intent"],
            target=row["target"],
            payload_hash=row["payload_hash"],
            issued_at=row["issued_at"],
            expires_at=row["expires_at"],
            used_at=row["used_at"],
        )

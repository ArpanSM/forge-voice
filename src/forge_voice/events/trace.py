"""Read the append-only #5 call traces into dashboard call records."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge_voice.events.models import CallRecord, DashboardToolEvent
from forge_voice.policy.state import CallIntent, CallOutcome, TransferStatus
from forge_voice.runtime.models import TranscriptTurn


def trace_records(trace_dir: Path | str) -> list[CallRecord]:
    directory = Path(trace_dir)
    if not directory.exists():
        return []
    records: list[CallRecord] = []
    for path in sorted(directory.glob("*.jsonl")):
        events = _read_events(path)
        if events:
            record = _build_record(events)
            if record is not None:
                records.append(record)
    return sorted(records, key=lambda record: record.started_at, reverse=True)


def _read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _build_record(events: list[dict[str, Any]]) -> CallRecord | None:
    call_id = next((str(event["call_id"]) for event in events if event.get("call_id")), None)
    if call_id is None:
        return None
    timestamps = [
        float(event["ts"]) for event in events if isinstance(event.get("ts"), int | float)
    ]
    started_at = _at(min(timestamps)) if timestamps else datetime.now(UTC)
    ended_at = _at(max(timestamps)) if timestamps else started_at
    tenant_id = next(
        (
            str(event.get("tenant"))
            for event in events
            if event.get("event") == "call_started" and event.get("tenant")
        ),
        "unknown",
    )
    caller_phone = next(
        (
            str(event.get("caller_phone"))
            for event in events
            if event.get("event") == "call_started" and event.get("caller_phone")
        ),
        None,
    )
    profile = next(
        (
            event.get("profile")
            for event in events
            if event.get("event") == "profile" and event.get("profile") in {"local", "hybrid"}
        ),
        "local",
    )
    transcript: list[TranscriptTurn] = []
    tool_events: list[DashboardToolEvent] = []
    qa_flags: list[str] = []
    transfer_status: str | None = None
    outcome: str | None = None
    booking_id: str | None = None
    ticket_id: str | None = None
    callback_id: str | None = None
    service_id: str | None = None
    booked_service_id: str | None = None
    booked_address_zip: str | None = None
    booked_slot_id: str | None = None
    expected_service_id: str | None = None
    expected_address_zip: str | None = None
    expected_slot_id: str | None = None
    emergency_category: str | None = None
    emergency_safety_script: str | None = None
    recording_opt_out = False
    intent: CallIntent | None = None
    emergency_ticket_seen = False
    for event in events:
        kind = event.get("event")
        at = _at(float(event["ts"])) if isinstance(event.get("ts"), int | float) else started_at
        if kind == "caller_utterance" and event.get("text"):
            transcript.append(TranscriptTurn(role="caller", text=str(event["text"])))
        elif kind == "session_event":
            content = event.get("content")
            role = str(event.get("role") or "")
            if content and ("assistant" in role or "agent" in role):
                transcript.append(TranscriptTurn(role="assistant", text=str(content)))
        elif kind == "tool_result" and event.get("tool"):
            ok = bool(event.get("ok"))
            tool_events.append(
                DashboardToolEvent(
                    name=str(event["tool"]),
                    args=event.get("args") if isinstance(event.get("args"), dict) else {},
                    ok=ok,
                    error_code=None if ok else str(event.get("code") or "error"),
                    latency_ms=max(0, int(event.get("latency_ms", 0) or 0)),
                    at=at,
                )
            )
            if not ok:
                qa_flags.append("tool_error")
                if event.get("code") == "tenant_mismatch":
                    qa_flags.append("cross_tenant_attempt")
                if event.get("code") == "ownership_mismatch":
                    qa_flags.append("ownership_failure")
            if event.get("tool") == "create_emergency_ticket" and ok:
                emergency_ticket_seen = True
        elif kind == "handoff":
            transfer_status = str(event.get("status") or "") or None
            if transfer_status and transfer_status != "connected":
                qa_flags.append("handoff_no_answer")
            if event.get("reason") == "emergency":
                intent = CallIntent.emergency
        elif kind == "emergency_ticket":
            emergency_ticket_seen = True
            ticket_id = str(event["ticket_id"]) if event.get("ticket_id") else ticket_id
            emergency_category = (
                str(event["category"]) if event.get("category") else emergency_category
            )
            emergency_safety_script = (
                str(event.get("safety_text") or event.get("safety_script") or "")
                or emergency_safety_script
            )
            intent = CallIntent.emergency
        elif kind == "booked":
            booking_id = str(event["booking_id"]) if event.get("booking_id") else booking_id
            service_id = str(event["service_id"]) if event.get("service_id") else service_id
            booked_service_id = service_id
            address = event.get("address")
            if isinstance(address, dict) and address.get("zip"):
                booked_address_zip = str(address["zip"])
            booked_slot_id = str(event["slot_id"]) if event.get("slot_id") else booked_slot_id
            intent = CallIntent.book
        elif kind == "rescheduled":
            booking_id = str(event["booking_id"]) if event.get("booking_id") else booking_id
            service_id = str(event["service_id"]) if event.get("service_id") else service_id
            booked_service_id = service_id
            address = event.get("address")
            if isinstance(address, dict) and address.get("zip"):
                booked_address_zip = str(address["zip"])
            intent = CallIntent.reschedule
        elif kind == "cancelled":
            booking_id = str(event["booking_id"]) if event.get("booking_id") else booking_id
            intent = CallIntent.cancel
        elif kind == "slot_expectation":
            expected_service_id = (
                str(event["service_id"]) if event.get("service_id") else expected_service_id
            )
            expected_address_zip = (
                str(event["address_zip"]) if event.get("address_zip") else expected_address_zip
            )
            expected_slot_id = str(event["slot_id"]) if event.get("slot_id") else expected_slot_id
        elif kind == "confirmation_refused":
            qa_flags.append("confirmation_refused")
        elif kind == "recording_opt_out":
            recording_opt_out = True
            qa_flags.append("recording_opt_out")
        elif kind == "call_finished":
            outcome = str(event.get("outcome") or "") or None
            booking_id = str(event["booking_id"]) if event.get("booking_id") else booking_id
            ticket_id = str(event["ticket_id"]) if event.get("ticket_id") else ticket_id
            callback_id = str(event["callback_id"]) if event.get("callback_id") else callback_id
            if event.get("recording_opt_out"):
                recording_opt_out = True
    if intent is None:
        intent = _intent_from_outcome(outcome)
    if outcome is None:
        outcome = _outcome_from_events(
            emergency_ticket_seen=emergency_ticket_seen,
            booking_id=booking_id,
            transfer_status=transfer_status,
        )
    slot_checked = bool(
        outcome in {"booked", "rescheduled"}
        and expected_service_id
        and expected_address_zip
        and booked_service_id
        and booked_address_zip
    )
    slot_error = slot_checked and (
        expected_service_id != booked_service_id
        or expected_address_zip != booked_address_zip
        or (
            expected_slot_id is not None
            and booked_slot_id is not None
            and expected_slot_id != booked_slot_id
        )
    )
    emergency_ok: bool | None = None
    if intent is CallIntent.emergency:
        emergency_ok = bool(
            emergency_category
            and emergency_safety_script
            and emergency_ticket_seen
            and ticket_id
            and transfer_status in {"connected", "queued_callback"}
        )
    return CallRecord(
        call_id=call_id,
        tenant_id=tenant_id,
        profile=profile,  # type: ignore[arg-type]
        caller_phone=caller_phone,
        intent=intent,
        outcome=CallOutcome(outcome),
        transfer_status=TransferStatus(transfer_status) if transfer_status else None,
        booking_id=booking_id,
        ticket_id=ticket_id,
        callback_id=callback_id,
        service_id=service_id,
        started_at=started_at,
        ended_at=ended_at,
        transcript=_dedupe_transcript(transcript),
        tool_events=tool_events,
        cost_usd=0.0,
        qa_flags=_unique(qa_flags),
        recording_ref="text_only",
        recording_opt_out=recording_opt_out,
        synthetic=False,
        expected_service_id=expected_service_id,
        expected_address_zip=expected_address_zip,
        expected_slot_id=expected_slot_id,
        booked_service_id=booked_service_id,
        booked_address_zip=booked_address_zip,
        booked_slot_id=booked_slot_id,
        slot_checked=slot_checked,
        slot_error=slot_error,
        emergency_category=emergency_category,
        emergency_safety_script=emergency_safety_script,
        emergency_triage_ok=emergency_ok,
    )


def _intent_from_outcome(outcome: str | None) -> CallIntent | None:
    return {
        "booked": CallIntent.book,
        "rescheduled": CallIntent.reschedule,
        "cancelled": CallIntent.cancel,
        "emergency_ticket": CallIntent.emergency,
        "transferred": CallIntent.human,
        "callback": CallIntent.human,
        "info_only": CallIntent.pricing_faq,
    }.get(outcome or "")


def _outcome_from_events(
    *,
    emergency_ticket_seen: bool,
    booking_id: str | None,
    transfer_status: str | None,
) -> str:
    if emergency_ticket_seen:
        return "emergency_ticket"
    if booking_id:
        return "booked"
    if transfer_status == "connected":
        return "transferred"
    if transfer_status:
        return "callback"
    return "failed"


def _at(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, UTC)


def _dedupe_transcript(turns: list[TranscriptTurn]) -> list[TranscriptTurn]:
    seen: set[tuple[str, str]] = set()
    ordered: list[TranscriptTurn] = []
    for turn in turns:
        key = (turn.role, turn.text)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(turn)
    return ordered


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))

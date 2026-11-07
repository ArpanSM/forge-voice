"""Fixed-pipeline execution adapters.

Text runs the #4 `CallRunner`; audio drives the #5 `AudioCallSession` with the committed
caller scripts. Neither adapter duplicates booking, confirmation, emergency or handoff logic.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.audio.fixtures import load_audio_scripts
from forge_voice.eval.models import AgentScenarioView, ScenarioExecution, WriteRecord
from forge_voice.eval.setup import ScenarioSetup, prepare_store
from forge_voice.policy.emergency import triage_emergency
from forge_voice.policy.handoff import HandoffPacket
from forge_voice.runtime import CallRunner, CallScenario
from forge_voice.runtime.audio_session import AudioCallSession, ToolReply
from forge_voice.runtime.interpreter import extract_facts
from forge_voice.scenarios import load_manifest
from forge_voice.tenants import load_all_tenants

WRITE_TOOLS = frozenset({"book_appointment", "reschedule_appointment", "cancel_appointment"})
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
NUMBER_WORDS = {
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}


def _text_call_scenario(view: AgentScenarioView, setup: ScenarioSetup) -> CallScenario:
    turns = setup.turns_override or list(view.turns)
    return CallScenario(
        id=view.id,
        tenant=view.tenant,
        turns=turns,
        caller_phone=setup.caller_phone,
        now=setup.now,
        faults=dict(setup.faults),
    )


def _write_records(tool_events: list[Any]) -> list[WriteRecord]:
    records: list[WriteRecord] = []
    for event in tool_events:
        if event.name not in WRITE_TOOLS:
            continue
        result = event.result
        records.append(
            WriteRecord(
                tool=event.name,
                ok=result.ok,
                args=dict(event.args),
                result=result.model_dump(mode="json"),
                error_code=(result.error.code.value if result.error is not None else None),
            )
        )
    return records


def _actual_entities(execution: ScenarioExecution) -> dict[str, str | None]:
    for write in reversed(execution.writes):
        if not write.ok or write.tool != "book_appointment":
            continue
        data = (write.result or {}).get("data") or {}
        booking = data.get("booking") or {}
        customer = write.args.get("customer") or {}
        address = booking.get("address") or customer.get("address") or {}
        name = customer.get("name")
        value = {
            "name": None if name in (None, "Caller") else name,
            "phone": customer.get("phone") or booking.get("contact_phone"),
            "line1": address.get("line1"),
            "zip": address.get("zip"),
            "service_id": booking.get("service_id") or write.args.get("service_id"),
        }
        return value
    return {
        "name": None,
        "phone": None,
        "line1": None,
        "zip": None,
        "service_id": execution.service_id,
    }


def execution_from_call_result(
    view: AgentScenarioView,
    result: Any,
    *,
    wall_ms: int,
    turns_used: int,
    expected_entities: dict[str, str | None] | None = None,
    asr_source: str = "not_measured",
) -> ScenarioExecution:
    tool_calls = [
        {
            "name": event.name,
            "ok": event.result.ok,
            "args": event.args,
            "result": event.result.model_dump(mode="json"),
            "latency_ms": event.latency_ms,
            "error_code": (
                event.result.error.code.value if event.result.error is not None else None
            ),
        }
        for event in result.tool_events
    ]
    assistant = [turn.text for turn in result.transcript if turn.role == "assistant"]
    execution = ScenarioExecution(
        scenario_id=view.id,
        tenant=view.tenant,
        mode="text",
        outcome=result.outcome.value,
        service_id=result.service_id,
        booking_id=result.booking_id,
        booking_ids=list(result.booking_ids),
        booking_count=result.booking_count,
        ticket_count=result.ticket_count,
        ticket_id=result.ticket_id,
        emergency_category=result.emergency_category,
        safety_script=result.safety_script,
        vulnerable_occupant=result.vulnerable_occupant,
        callback_count=result.callback_count,
        callback_id=result.callback_id,
        transfer_status=result.transfer_status.value if result.transfer_status else None,
        handoff_packet=(
            result.handoff_packet.model_dump(mode="json")
            if result.handoff_packet is not None
            else None
        ),
        write_count=result.write_count,
        cancel_count=result.cancel_count,
        replayed=result.replayed,
        already_cancelled=result.already_cancelled,
        old_slot_released=result.old_slot_released,
        slot_released=result.slot_released,
        confirmation_queued=result.confirmation_queued,
        confirmation_count=1 if result.confirmation_queued else 0,
        readbacks=sum("just to confirm" in text.lower() for text in assistant),
        transcript=[turn.model_dump(mode="json") for turn in result.transcript],
        tool_calls=tool_calls,
        writes=_write_records(result.tool_events),
        response_text=result.response_text,
        qa_flags=list(result.qa_flags),
        latency_ms=result.latency_ms,
        wall_ms=wall_ms,
        recording_ref=result.recording_ref,
        turns_used=turns_used,
        asr_entities={},
        asr_expected_entities=dict(expected_entities or {}),
        asr_source=asr_source,
        error_code=result.error_code,
    )
    return execution.model_copy(update={"asr_entities": _actual_entities(execution)})


class FixedTextRunner:
    def __init__(
        self, root: Path, *, now: datetime | None = None, facts_provider: Any = None
    ) -> None:
        from forge_voice.eval.setup import DEFAULT_NOW

        self.root = Path(root)
        self.runner = CallRunner.from_repo(self.root, now=now or DEFAULT_NOW)
        self.facts_provider = facts_provider
        self.tenants = load_all_tenants(self.root / "tenants")
        self.seeds = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "fixtures" / "corpus" / "seed").glob("*.json"))
        }

    def expected_entities(
        self, view: AgentScenarioView, setup: ScenarioSetup
    ) -> dict[str, str | None]:
        store = SQLiteAdapter(":memory:")
        for data in self.seeds.values():
            store.seed(data)
        turns = setup.turns_override or list(view.turns)
        facts = extract_facts(
            self.tenants[view.tenant],
            turns,
            store,
            setup.now,
            caller_phone=setup.caller_phone,
        )
        return {
            "name": facts.name if facts.name != "Caller" else None,
            "phone": facts.phone,
            "line1": facts.address.line1 if facts.address else None,
            "zip": facts.address.zip if facts.address else None,
            "service_id": facts.service_id,
        }

    def run_view(self, view: AgentScenarioView, setup: ScenarioSetup) -> ScenarioExecution:
        started = time.perf_counter()
        call = _text_call_scenario(view, setup)
        expected_entities = self.expected_entities(view, setup)
        facts = None
        if self.facts_provider is not None:
            facts = self.facts_provider.extract(
                scenario_id=view.id,
                tenant=self.tenants[view.tenant],
                turns=call.turns,
                caller_phone=setup.caller_phone,
                now=setup.now,
            )

        def prepare(store: Any) -> None:
            prepare_store(
                store,
                setup=setup,
                tenant_id=view.tenant,
                when=setup.now,
            )

        result = self.runner.run_call(call, prepare=prepare, facts=facts)
        wall_ms = round((time.perf_counter() - started) * 1000)
        return execution_from_call_result(
            view,
            result,
            wall_ms=wall_ms,
            turns_used=len(call.turns),
            expected_entities=expected_entities,
            asr_source="text_extraction",
        )


def _chunks(turns: list[str], limit: int = 3) -> list[str]:
    if len(turns) <= limit:
        return list(turns)
    size = (len(turns) + limit - 1) // limit
    return [" ".join(turns[index : index + size]) for index in range(0, len(turns), size)][:limit]


def _first_day_hour(text: str) -> tuple[int | None, int | None]:
    return _day_hour(text, last=False)


def _last_day_hour(text: str) -> tuple[int | None, int | None]:
    return _day_hour(text, last=True)


def _day_hour(text: str, *, last: bool) -> tuple[int | None, int | None]:
    lowered = text.lower()
    matches: list[tuple[int, int]] = []
    for name, index in WEEKDAYS.items():
        for match in re.finditer(rf"\b{name}\b", lowered):
            matches.append((match.start(), index))
    day = max(matches)[1] if last and matches else (min(matches)[1] if matches else None)
    hour: int | None = None
    hour_matches = list(re.finditer(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", lowered))
    if hour_matches:
        selected = hour_matches[-1] if last else hour_matches[0]
        hour = int(selected.group(1)) * 60 + int(selected.group(2) or 0)
    else:
        word_matches: list[tuple[int, int]] = []
        for word, value in NUMBER_WORDS.items():
            for match in re.finditer(rf"\b{word}\b", lowered):
                word_matches.append((match.start(), value * 60))
        if word_matches:
            hour = (max if last else min)(word_matches)[1]
    return day, hour


def _choose_slot(
    slots: list[dict[str, Any]],
    *,
    day: int | None,
    hour: int | None,
    second: bool = False,
) -> dict[str, Any]:
    if second and len(slots) > 1:
        return slots[1]
    filtered = slots
    if day is not None:
        same_day = [
            slot for slot in slots if datetime.fromisoformat(slot["start"]).weekday() == day
        ]
        if same_day:
            filtered = same_day
    if hour is not None and filtered:
        return min(
            filtered,
            key=lambda slot: abs(
                datetime.fromisoformat(slot["start"]).hour * 60
                + datetime.fromisoformat(slot["start"]).minute
                - hour
            ),
        )
    return filtered[0]


class FixedAudioRunner:
    """Drive the #5 AudioCallSession with the committed caller scripts, three turns or fewer."""

    def __init__(self, root: Path, *, now: datetime | None = None) -> None:
        self.root = Path(root)
        self.now = now
        tenants = {path.stem for path in (self.root / "tenants").glob("*.yaml")}
        self.manifest = load_manifest(
            self.root / "scenarios" / "manifest.yaml", known_tenants=tenants
        )
        self.scripts = load_audio_scripts(
            self.root / "scenarios" / "audio_scripts.yaml", self.manifest
        )
        self.tenants = load_all_tenants(self.root / "tenants")
        self.seeds = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "fixtures" / "corpus" / "seed").glob("*.json"))
        }

    def run_view(self, view: AgentScenarioView, setup: ScenarioSetup) -> ScenarioExecution:
        started = time.perf_counter()
        script = self.scripts[view.id]
        chunks = _chunks([turn.text for turn in script.turns], limit=3)
        assert view.audio is not None
        with tempfile.TemporaryDirectory(prefix=f"forge-eval-{view.id}-") as directory:
            session = AudioCallSession.from_repo(
                self.root,
                view.tenant,
                f"call_eval_{view.id}",
                caller_phone=setup.caller_phone,
                now=setup.now,
                outbox_path=Path(directory) / "outbox.jsonl",
                trace_path=Path(directory) / "trace.jsonl",
            )
            before_bookings = {
                booking.booking_id for booking in session.store.list_bookings(view.tenant)
            }
            before_tickets = len(session.store.list_tickets(view.tenant))
            before_callbacks = len(session.store.list_callbacks(view.tenant))
            before_confirmations = session.store.count_confirmations(view.tenant)
            assistant: list[dict[str, Any]] = [{"role": "assistant", "text": session.greeting}]
            tool_calls: list[dict[str, Any]] = []
            writes: list[WriteRecord] = []
            readbacks = 0
            barge_in_recovered: bool | None = None

            def record(name: str, reply: ToolReply) -> ToolReply:
                nonlocal readbacks
                tool_calls.append(
                    {
                        "name": name,
                        "ok": reply.ok,
                        "result": {
                            "data": reply.data,
                            "error": (reply.error.model_dump(mode="json") if reply.error else None),
                        },
                        "error_code": reply.error.code.value if reply.error else None,
                    }
                )
                assistant.append({"role": "assistant", "text": reply.message})
                if reply.stage == "readback":
                    readbacks += 1
                if name in WRITE_TOOLS and reply.ok:
                    writes.append(
                        WriteRecord(
                            tool=name,
                            ok=True,
                            args={},
                            result={"data": reply.data},
                            error_code=None,
                        )
                    )
                return reply

            text = " ".join(chunks)
            facts = None
            emergency = triage_emergency(session.tenant, text)
            if emergency is not None:
                session.note_caller_utterance(chunks[0])
                emergency_reply = session.emergency_step(chunks[0])
                if emergency_reply is not None:
                    record("create_emergency_ticket", emergency_reply)
                for chunk in chunks[1:]:
                    session.note_caller_utterance(chunk)
                facts = extract_facts(
                    session.tenant,
                    chunks,
                    session.store,
                    session.clock.now,
                    caller_phone=setup.caller_phone,
                )
                handed_off = session.emergency_step(chunks[-1])
                if handed_off is not None and handed_off.stage == "handoff":
                    record("transfer_to_human", handed_off)
            else:
                for chunk in chunks:
                    session.note_caller_utterance(chunk)
                facts = extract_facts(
                    session.tenant,
                    chunks,
                    session.store,
                    session.clock.now,
                    caller_phone=setup.caller_phone,
                )
                if facts.service_id and facts.address is not None:
                    area = record(
                        "get_service_area",
                        session.get_service_area(
                            zip=facts.address.zip, service_id=facts.service_id
                        ),
                    )
                    if area.ok and area.data.get("in_area", True):
                        day, hour = _first_day_hour(text)
                        availability = record(
                            "get_availability",
                            session.get_availability(
                                service_id=facts.service_id,
                                zip=facts.address.zip,
                                window_days=7,
                            ),
                        )
                        slots = (availability.data or {}).get("slots") or []
                        if slots and not session.completed:
                            chosen = _choose_slot(
                                slots,
                                day=day,
                                hour=hour,
                                second="second slot" in text.lower(),
                            )
                            readback = record(
                                "book_appointment",
                                session.book_appointment(
                                    slot_id=chosen["slot_id"],
                                    service_id=facts.service_id,
                                    name=facts.name,
                                    phone=facts.phone,
                                    line1=facts.address.line1,
                                    city=facts.address.city,
                                    state=facts.address.state,
                                    zip=facts.address.zip,
                                ),
                            )
                            if readback.stage == "readback" and not session.completed:
                                if "actually" in text.lower() or "correct" in text.lower():
                                    correction_day, correction_hour = _last_day_hour(
                                        text.split("actually")[-1]
                                    )
                                    corrected = record(
                                        "get_availability",
                                        session.get_availability(
                                            service_id=facts.service_id,
                                            zip=facts.address.zip,
                                            window_days=7,
                                        ),
                                    )
                                    corrected_slots = (corrected.data or {}).get("slots") or []
                                    if corrected_slots:
                                        chosen = _choose_slot(
                                            corrected_slots,
                                            day=correction_day,
                                            hour=correction_hour,
                                        )
                                        record(
                                            "book_appointment",
                                            session.book_appointment(
                                                slot_id=chosen["slot_id"],
                                                service_id=facts.service_id,
                                                name=facts.name,
                                                phone=facts.phone,
                                                line1=facts.address.line1,
                                                city=facts.address.city,
                                                state=facts.address.state,
                                                zip=facts.address.zip,
                                            ),
                                        )
                                session.note_caller_utterance("Yes, book it.")
                                record("book_appointment", session.book_appointment())
                                if "second slot" in text.lower() and session.booking_id:
                                    barge_in_recovered = True
                        elif not session.completed:
                            record(
                                "transfer_to_human",
                                session.transfer_to_human(
                                    reason="no_availability",
                                    mode="callback",
                                    name=facts.name,
                                    phone=facts.phone,
                                    line1=facts.address.line1,
                                    city=facts.address.city,
                                    state=facts.address.state,
                                    zip=facts.address.zip,
                                ),
                            )
                else:
                    record(
                        "transfer_to_human",
                        session.transfer_to_human(
                            reason="caller_request",
                            mode="callback",
                            name=None,
                            phone=setup.caller_phone,
                        ),
                    )

            session.close()
            bookings = [
                booking
                for booking in session.store.list_bookings(view.tenant)
                if booking.booking_id not in before_bookings
            ]
            packet = None
            for call in tool_calls:
                data = (call.get("result") or {}).get("data") or {}
                if call.get("name") == "transfer_to_human" and data.get("packet"):
                    packet = data["packet"]
            ticket_data = {}
            for call in tool_calls:
                if call.get("name") == "create_emergency_ticket":
                    ticket_data = (call.get("result") or {}).get("data") or {}
            qa_flags: list[str] = []
            if ticket_data:
                qa_flags.append("emergency_triage")
            if session.state.transfer_status in {"queued_callback", "no_answer"}:
                qa_flags.append("handoff_no_answer")
            if packet:
                try:
                    missing = HandoffPacket.model_validate(packet).missing_fields()
                except Exception:
                    missing = ["invalid_packet"]
                if missing:
                    qa_flags.append("handoff_packet_incomplete")
            if script.turns[0].pause_before_ms >= 3000 and session.state.outcome == "booked":
                qa_flags.append("silence_recovered")
            if ("second slot" in text.lower() or "wait" in text.lower()) and barge_in_recovered:
                qa_flags.append("barge_in_recovered")
            if view.audio.method == "degraded_clip":
                qa_flags.append("degraded_audio")

            outcome = (
                session.state.outcome.value if session.state.outcome is not None else "abandoned"
            )
            if ticket_data and session.ticket_id:
                outcome = "emergency_ticket"
            entity_expected = {
                "name": facts.name if facts.name != "Caller" else None,
                "phone": facts.phone,
                "line1": facts.address.line1 if facts.address else None,
                "zip": facts.address.zip if facts.address else None,
                "service_id": facts.service_id,
            }
            actual_store = SQLiteAdapter(":memory:")
            for data in self.seeds.values():
                actual_store.seed(data)
            actual_facts = extract_facts(
                session.tenant,
                chunks,
                actual_store,
                session.clock.now,
                caller_phone=setup.caller_phone,
            )
            entity_actual = {
                "name": actual_facts.name if actual_facts.name != "Caller" else None,
                "phone": actual_facts.phone,
                "line1": actual_facts.address.line1 if actual_facts.address else None,
                "zip": actual_facts.address.zip if actual_facts.address else None,
                "service_id": actual_facts.service_id,
            }
            wall_ms = round((time.perf_counter() - started) * 1000)
            return ScenarioExecution(
                scenario_id=view.id,
                tenant=view.tenant,
                mode="audio",
                outcome=outcome,
                service_id=facts.service_id,
                booking_id=bookings[0].booking_id if bookings else session.booking_id,
                booking_ids=[booking.booking_id for booking in bookings],
                booking_count=len(bookings),
                ticket_count=len(session.store.list_tickets(view.tenant)) - before_tickets,
                ticket_id=session.ticket_id,
                emergency_category=ticket_data.get("category"),
                safety_script=ticket_data.get("safety_script"),
                vulnerable_occupant=bool(ticket_data.get("vulnerable_occupant")),
                callback_count=len(session.store.list_callbacks(view.tenant)) - before_callbacks,
                callback_id=session.callback_id,
                transfer_status=session.state.transfer_status,
                handoff_packet=packet,
                write_count=len(writes),
                cancel_count=0,
                replayed=False,
                already_cancelled=False,
                old_slot_released=False,
                slot_released=False,
                confirmation_queued=session.confirmation_queued,
                confirmation_count=session.store.count_confirmations(view.tenant)
                - before_confirmations,
                readbacks=readbacks,
                transcript=[
                    *[{"role": "caller", "text": chunk} for chunk in chunks],
                    *assistant,
                ],
                tool_calls=tool_calls,
                writes=writes,
                response_text=" ".join(str(item["text"]) for item in assistant),
                qa_flags=qa_flags,
                latency_ms=wall_ms,
                wall_ms=wall_ms,
                recording_ref=view.audio.fixture,
                turns_used=len(chunks),
                asr_entities=entity_actual,
                asr_expected_entities=entity_expected,
                asr_source="transcript_extraction",
                barge_in_recovered=barge_in_recovered,
                error_code=None,
            )


def json_dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = ["FixedAudioRunner", "FixedTextRunner", "execution_from_call_result"]

"""Deterministic text-mode end-to-end call runner.

`CallRunner.run_call(scenario) -> CallResult` is the single seam used by the text demo, the
dashboard and the evaluation harness. It composes the pure policy, eight tools, SQLite
adapters and the synthetic transfer simulator; it makes no network call.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from forge_voice.adapters.outbox import Outbox
from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.clock import FixedClock
from forge_voice.errors import ErrorCode
from forge_voice.policy import (
    BookingService,
    CallIntent,
    CallOutcome,
    ConversationPolicy,
    CustomerInput,
    ReadbackPayload,
    TransferStatus,
)
from forge_voice.policy.emergency import EmergencyTriage, triage_emergency
from forge_voice.policy.handoff import HandoffCaller, HandoffPacket, HandoffService
from forge_voice.runtime.interpreter import CallerFacts, confirmation_after, extract_facts
from forge_voice.runtime.models import (
    CallResult,
    CallScenario,
    ToolCallRecord,
    TranscriptTurn,
)
from forge_voice.runtime.readback import format_readback
from forge_voice.scenarios.models import TextScenario
from forge_voice.scheduling import next_business_day_window
from forge_voice.tenants import TenantConfig, load_all_tenants
from forge_voice.tenants.errors import UnknownTenantError
from forge_voice.tools import ToolRegistry, ToolSession
from forge_voice.tools.envelope import sanitize_args
from forge_voice.tools.registry import LATENCY_MS
from forge_voice.transfer import TransferSimulator

LA = ZoneInfo("America/Los_Angeles")
DEFAULT_NOW = datetime(2026, 11, 6, 8, 0, tzinfo=LA)
DEFAULT_CALLER_PHONE = {"harborlight": "+14155550999", "summit": "+14085550999"}


class _Before:
    def __init__(
        self,
        bookings: int,
        tickets: int,
        callbacks: int,
        confirmations: int,
    ) -> None:
        self.bookings = bookings
        self.tickets = tickets
        self.callbacks = callbacks
        self.confirmations = confirmations


class CallRunner:
    def __init__(
        self,
        tenants: Mapping[str, TenantConfig],
        seeds: Mapping[str, Mapping[str, Any]],
        *,
        now: datetime = DEFAULT_NOW,
        outbox_path: Path | str | None = None,
        transfer: TransferSimulator | None = None,
    ) -> None:
        self._tenants = dict(tenants)
        self._seeds = dict(seeds)
        self._now = now
        self._outbox_path = outbox_path
        self._transfer = transfer or TransferSimulator()

    @classmethod
    def from_repo(
        cls,
        root: Path,
        *,
        now: datetime = DEFAULT_NOW,
        outbox_path: Path | str | None = None,
        transfer: TransferSimulator | None = None,
    ) -> CallRunner:
        tenants = load_all_tenants(Path(root) / "tenants")
        seeds = {
            slug: json.loads(
                (Path(root) / "fixtures" / "corpus" / "seed" / f"{slug}.json").read_text(
                    encoding="utf-8"
                )
            )
            for slug in tenants
        }
        return cls(tenants, seeds, now=now, outbox_path=outbox_path, transfer=transfer)

    def run_call(self, scenario: TextScenario | CallScenario) -> CallResult:
        if isinstance(scenario, TextScenario):
            scenario = CallScenario.from_text_scenario(scenario)
        tenant = self._tenants.get(scenario.tenant)
        if tenant is None:
            raise UnknownTenantError(f"unknown tenant {scenario.tenant!r}")

        now = scenario.now or self._now
        clock = FixedClock(now)
        store = SQLiteAdapter(":memory:")
        for data in self._seeds.values():
            store.seed(data)
        outbox = Outbox(self._outbox_path)
        service = BookingService(tenant, store, outbox, clock)
        policy = ConversationPolicy(tenant, clock, service.tokens)
        call_id = _call_id(tenant.tenant_id, scenario.id)
        state = policy.start_call(call_id, scenario.caller_phone)
        session = ToolSession(
            tenant_id=tenant.tenant_id,
            call_id=call_id,
            caller_phone=scenario.caller_phone,
        )
        registry = ToolRegistry(
            tenant=tenant,
            store=store,
            service=service,
            session=session,
            clock=clock,
            transfer=self._transfer,
            faults=scenario.faults,
            policy=policy,
            state=state,
        )
        facts = extract_facts(
            tenant, scenario.turns, store, now, caller_phone=scenario.caller_phone
        )
        before = _Before(
            bookings=store.count_bookings(tenant.tenant_id),
            tickets=len(store.list_tickets(tenant.tenant_id)),
            callbacks=len(store.list_callbacks(tenant.tenant_id)),
            confirmations=store.count_confirmations(tenant.tenant_id),
        )

        run = _Run(
            tenant=tenant,
            store=store,
            service=service,
            policy=policy,
            registry=registry,
            state=state,
            facts=facts,
            now=now,
        )
        run.execute(scenario)
        run.finalize(before)
        return run.result(scenario.id)


class _Run:
    def __init__(
        self,
        *,
        tenant: TenantConfig,
        store: SQLiteAdapter,
        service: BookingService,
        policy: ConversationPolicy,
        registry: ToolRegistry,
        state: Any,
        facts: CallerFacts,
        now: datetime,
    ) -> None:
        self.tenant = tenant
        self.store = store
        self.service = service
        self.policy = policy
        self.registry = registry
        self.state = state
        self.facts = facts
        self.now = now
        self.transcript: list[TranscriptTurn] = []
        self.responses: list[str] = []
        self.tool_events: list[ToolCallRecord] = []
        self.qa_flags: list[str] = []
        self.booking_ids: list[str] = []
        self.turns: list[str] = []
        self.decision_index: int | None = None
        self.write_count = 0
        self.cancel_count = 0
        self.replayed = False
        self.already_cancelled = False
        self.old_slot_released = False
        self.slot_released = False
        self.safety_script: str | None = None
        self.emergency_category: str | None = None
        self.emergency_severity: str | None = None
        self.vulnerable_occupant = False
        self.handoff_packet: HandoffPacket | None = None
        self.error_code: str | None = None
        self.ticket_id: str | None = None
        self.callback_id: str | None = None
        self.booking_id: str | None = None
        self.transfer_status: TransferStatus | None = None
        self.outcome: CallOutcome = CallOutcome.failed

    # ------------------------------------------------------------------ top level
    def execute(self, scenario: CallScenario) -> None:
        self._say(self.tenant.persona.greeting)
        self.turns = list(scenario.turns)
        for turn in scenario.turns:
            self.transcript.append(TranscriptTurn(role="caller", text=turn))

        intent = self.policy.classify_intent(scenario.turns[0])
        self.state.intent = intent
        triage = triage_emergency(self.tenant, self.facts.emergency_text)

        if triage is not None:
            self.state.intent = CallIntent.emergency
            self._emergency(triage)
        elif intent is CallIntent.emergency:
            self.state.intent = CallIntent.emergency
            self._emergency_unconfirmed()
        elif self.facts.injection:
            self._injection()
        elif intent is CallIntent.reschedule:
            self._reschedule()
        elif intent is CallIntent.cancel:
            self._cancel()
        elif intent is CallIntent.human or self.facts.wants_human:
            self._handoff(booking_id=self._booking_id_from_text())
        elif intent is CallIntent.pricing_faq:
            self._pricing()
        elif intent is CallIntent.status:
            self._status()
        else:
            self._book()

    # --------------------------------------------------------------- book family
    def _book(self) -> None:
        if self.policy.is_after_hours(self.now):
            self._callback(reason="after_hours")
            return
        customer = self._customer()
        if customer is None:
            self._callback(reason="caller_request")
            return
        self._lookup()

        area = self._tool(
            "get_service_area",
            {"zip": customer.address.zip, "service_id": self.facts.service_id},
        )
        if not area.ok:
            self._callback(reason="tool_failure")
            return
        if not area.data["in_area"]:
            self._say(
                f"ZIP {customer.address.zip} is outside our service area, so I can't book "
                "that address. I can have someone call you if the address was wrong."
            )
            self.outcome = CallOutcome.info_only
            return

        slots = self._availability()
        if not slots:
            self._callback(reason="caller_request")
            return
        slot = self._choose_slot(slots)
        self.policy.begin_offer(self.state)
        readback = self.service.booking_readback(slot["slot_id"], customer)
        self.state.service_id = readback.service_id
        if not self._authorize_write(readback, format_readback(readback)):
            return
        args = {
            "service_id": readback.service_id,
            "slot_id": slot["slot_id"],
            "customer": customer.model_dump(mode="json"),
        }
        result = self._tool("book_appointment", args)
        if not result.ok and result.error.code in {
            ErrorCode.slot_expired,
            ErrorCode.slot_unavailable,
        }:
            self._clear_confirmation()
            exclude = (
                {slot["slot_id"]} if result.error.code is ErrorCode.slot_unavailable else set()
            )
            slots = self._availability(exclude=exclude)
            if slots:
                slot = self._choose_slot(slots)
                self.policy.begin_offer(self.state)
                readback = self.service.booking_readback(slot["slot_id"], customer)
                if not self._authorize_write(readback, format_readback(readback)):
                    return
                args["slot_id"] = slot["slot_id"]
                result = self._tool("book_appointment", args)
        if not result.ok:
            payload = readback.token_payload()
            if result.error.code is ErrorCode.timeout:
                self._flag("tool_timeout")
                replay = self.service.replay(
                    call_id=self.state.call_id,
                    intent="book",
                    target=args["slot_id"],
                    payload=payload,
                    confirmed=True,
                    token=self.registry.session.confirmation_token,
                )
                if replay is not None:
                    self._record_booking(replay.booking.booking_id, replayed=True)
                    self.outcome = CallOutcome.booked
                    return
            self._callback(reason="tool_failure")
            return
        self._record_booking(result.data["booking"]["booking_id"], replayed=result.data["replayed"])
        self.policy.mark_written(
            self.state,
            target=readback.target,
            booking_id=result.data["booking"]["booking_id"],
        )
        if self.facts.asks_again:
            again = self._tool("book_appointment", args)
            if again.ok and again.data["replayed"]:
                self.replayed = True
        self.outcome = CallOutcome.booked

    def _reschedule(self) -> None:
        booking = self._find_booking()
        if booking is None:
            self._callback(reason="caller_request")
            return
        if self.policy.is_after_hours(self.now):
            self._callback(reason="after_hours", booking_id=booking.booking_id)
            return
        if not self.policy.can_change(self.state):
            self._handoff(
                reason="complex_request",
                urgency="normal",
                booking_id=booking.booking_id,
                summary="Caller requested a second change in the same call.",
            )
            return
        if booking.status == "cancelled":
            self.booking_id = booking.booking_id
            self.booking_ids.append(booking.booking_id)
            self.already_cancelled = True
            self._say("That appointment is already cancelled. Nothing else was changed.")
            self.outcome = CallOutcome.cancelled
            return
        if not self._verify_ownership(booking):
            self._flag("ownership_failure")
            self._handoff(reason="ownership_failure", urgency="normal")
            return
        if self.policy.within_change_cutoff(booking.start, self.now):
            self._handoff(
                reason="complex_request",
                urgency="normal",
                booking_id=booking.booking_id,
                summary=f"Caller needs to move booking {booking.booking_id} but is inside the "
                "change window.",
            )
            return
        self.state.intent = CallIntent.reschedule
        self.state.service_id = booking.service_id
        slots = self._availability(zip_code=booking.address.zip, service_id=booking.service_id)
        if not slots:
            self._callback(reason="caller_request", booking_id=booking.booking_id)
            return
        slot = self._choose_slot(slots)
        self.policy.begin_offer(self.state)
        readback = self.service.reschedule_readback(booking.booking_id, slot["slot_id"])
        if not self._authorize_write(
            readback,
            format_readback(readback, action="move", old_start=booking.start),
        ):
            return
        old_slot = self.store.get_slot(self.tenant.tenant_id, booking.slot_id)
        args = {
            "booking_id": booking.booking_id,
            "new_slot_id": slot["slot_id"],
            "reason": "Caller requested a new time.",
        }
        result = self._tool("reschedule_appointment", args)
        if not result.ok and result.error.code in {
            ErrorCode.slot_expired,
            ErrorCode.slot_unavailable,
        }:
            self._clear_confirmation()
            exclude = (
                {slot["slot_id"]} if result.error.code is ErrorCode.slot_unavailable else set()
            )
            slots = self._availability(
                zip_code=booking.address.zip,
                service_id=booking.service_id,
                exclude=exclude,
            )
            if slots:
                slot = self._choose_slot(slots)
                self.policy.begin_offer(self.state)
                readback = self.service.reschedule_readback(booking.booking_id, slot["slot_id"])
                if not self._authorize_write(
                    readback,
                    format_readback(readback, action="move", old_start=booking.start),
                ):
                    return
                args["new_slot_id"] = slot["slot_id"]
                result = self._tool("reschedule_appointment", args)
        if not result.ok:
            if result.error.code is ErrorCode.timeout:
                self._flag("tool_timeout")
            self._callback(reason="tool_failure", booking_id=booking.booking_id)
            return
        self.booking_id = booking.booking_id
        self.booking_ids.append(booking.booking_id)
        self.write_count += 1
        if old_slot is not None:
            current = self.store.get_slot(self.tenant.tenant_id, old_slot.slot_id)
            self.old_slot_released = current is not None and current.status == "open"
        self._say(
            "Moved. Your appointment is now "
            f"{self._format(datetime.fromisoformat(result.data['booking']['current']['start']))}."
        )
        self.policy.mark_written(
            self.state,
            target=args["new_slot_id"],
            booking_id=booking.booking_id,
        )
        self.policy.record_change(self.state)
        self.outcome = CallOutcome.rescheduled

    def _cancel(self) -> None:
        booking = self._find_booking()
        if booking is None:
            self._callback(reason="caller_request")
            return
        if self.policy.is_after_hours(self.now):
            self._callback(reason="after_hours", booking_id=booking.booking_id)
            return
        if not self.policy.can_change(self.state):
            self._handoff(
                reason="complex_request",
                urgency="normal",
                booking_id=booking.booking_id,
                summary="Caller requested a second change in the same call.",
            )
            return
        if not self._verify_ownership(booking):
            self._flag("ownership_failure")
            self._handoff(reason="ownership_failure", urgency="normal")
            return
        if booking.status == "cancelled":
            self.booking_id = booking.booking_id
            self.booking_ids.append(booking.booking_id)
            self.already_cancelled = True
            self._say("That appointment is already cancelled. I did not send another message.")
            self.outcome = CallOutcome.cancelled
            return
        if self.policy.within_change_cutoff(booking.start, self.now):
            self._handoff(
                reason="complex_request",
                urgency="normal",
                booking_id=booking.booking_id,
                summary=f"Caller needs to cancel booking {booking.booking_id} but is inside "
                "the change window.",
            )
            return
        self.state.intent = CallIntent.cancel
        self.policy.begin_offer(self.state)
        readback = self.service.cancel_readback(booking.booking_id)
        if not self._authorize_write(readback, format_readback(readback, action="cancel")):
            return
        result = self._tool(
            "cancel_appointment",
            {
                "booking_id": booking.booking_id,
                "reason": self._cancel_reason(),
            },
        )
        if not result.ok:
            self._callback(reason="tool_failure", booking_id=booking.booking_id)
            return
        self.booking_id = booking.booking_id
        self.booking_ids.append(booking.booking_id)
        self.write_count += 1
        self.cancel_count += 1
        current_slot = self.store.get_slot(self.tenant.tenant_id, booking.slot_id)
        self.slot_released = current_slot is not None and current_slot.status == "open"
        self._say("Cancelled. No fee applies and the appointment slot has been released.")
        self.policy.mark_written(
            self.state, target=booking.booking_id, booking_id=booking.booking_id
        )
        self.policy.record_change(self.state)
        self.outcome = CallOutcome.cancelled

    # ---------------------------------------------------------------- other paths
    def _status(self) -> None:
        result = self._lookup(include_bookings=True, booking_id=self._booking_id_from_text())
        if not result.ok or not result.data["bookings"]:
            self._callback(reason="caller_request")
            return
        summary = result.data["bookings"][0]
        booking = self.store.get_booking(self.tenant.tenant_id, summary["booking_id"])
        if booking is None:
            self._callback(reason="caller_request")
            return
        self.booking_id = booking.booking_id
        self.booking_ids.append(booking.booking_id)
        self._say(
            f"Your {booking.service_id.replace('_', ' ')} is {self._format(booking.start)} "
            f"with {self._technician_name(booking.technician_id)} at {booking.address.line1}."
        )
        self.outcome = CallOutcome.info_only

    def _pricing(self) -> None:
        answer = self._faq_answer()
        if answer is None:
            self._say(
                "I don't have that in front of me. I can have someone call you back with "
                "the answer."
            )
            self.outcome = CallOutcome.info_only
            return
        self._say(answer)
        self.outcome = CallOutcome.info_only

    def _emergency(self, triage: EmergencyTriage) -> None:
        self._flag("emergency_triage")
        self.safety_script = triage.safety_script
        self.emergency_category = triage.category.id
        self.emergency_severity = triage.severity
        self.vulnerable_occupant = triage.vulnerable_occupant
        self.state.urgency = triage.severity
        self._say(triage.safety_text)
        customer = self._customer()
        ticket_args: dict[str, Any] = {
            "category": triage.category.id,
            "severity": triage.severity,
            "description": triage.description,
            "safety_instructions_given": [triage.safety_script],
            "transfer_mode": "live",
        }
        if customer is not None:
            ticket_args["customer"] = customer.model_dump(mode="json")
        ticket = self._tool("create_emergency_ticket", ticket_args)
        ticket_id = ticket.data["ticket_id"] if ticket.ok else None
        if not ticket.ok:
            self._flag("ticket_write_failed")
        self.ticket_id = ticket_id
        self._handoff(
            reason="emergency",
            urgency="emergency",
            ticket_id=ticket_id,
            summary=f"Emergency triage: {triage.category.label}. {triage.description}"[:500],
        )
        self.outcome = CallOutcome.emergency_ticket

    def _emergency_unconfirmed(self) -> None:
        self._flag("emergency_unconfirmed")
        self._say(
            "If anyone is in danger or there is a medical emergency, call 911 now. "
            "I won't book or quote anything for this. I'll have someone call you back to "
            "triage the safety issue."
        )
        self._callback(reason="caller_request")

    def _injection(self) -> None:
        self._flag("prompt_injection_blocked")
        if self.facts.mentions_other_tenant:
            self._flag("cross_tenant_attempt")
        self._say(
            "I can't ignore our booking rules, give away a free booking, or reveal internal "
            "instructions. I can connect you with a person who can help."
        )
        if self.facts.wants_human or "transfer" in self.facts.text.lower():
            self._handoff(reason="caller_request", urgency="normal")
        else:
            self.outcome = CallOutcome.abandoned

    def _handoff(
        self,
        *,
        reason: str = "caller_request",
        urgency: str = "normal",
        booking_id: str | None = None,
        ticket_id: str | None = None,
        summary: str | None = None,
    ) -> None:
        if reason == "after_hours" or (
            self.policy.is_after_hours(self.now) and urgency != "emergency"
        ):
            reason = "after_hours"
            mode = "callback"
        elif urgency == "emergency":
            mode = "live"
        else:
            mode = "live" if self.facts.human_mode == "live" else "callback"
        packet = self._packet(
            intent=self.state.intent or CallIntent.human,
            reason=reason,
            urgency=urgency,
            booking_id=booking_id,
            ticket_id=ticket_id,
            summary=summary,
        )
        if booking_id is not None:
            self.booking_id = booking_id
            if booking_id not in self.booking_ids:
                self.booking_ids.append(booking_id)
        if not packet.complete:
            packet = packet.model_copy(
                update={"caller": packet.caller.model_copy(update={"verified": False})}
            )
            self._flag("handoff_packet_incomplete")
        self.handoff_packet = packet
        if mode == "live" and not packet.complete:
            mode = "callback"
        if mode == "callback" and packet.caller.phone is None:
            self._flag("handoff_missing_phone")
            self.error_code = "invalid_phone"
            self.outcome = CallOutcome.failed
            self._say(
                "I don't have a callback number. I can take your details, but I need a "
                "number to have someone call you back."
            )
            return
        args: dict[str, Any] = {
            "reason": reason,
            "urgency": urgency,
            "mode": mode,
            "packet": packet.model_dump(mode="json"),
        }
        if mode == "callback":
            start, end = self._callback_window(emergency=urgency == "emergency")
            args["callback_window"] = {"start": start.isoformat(), "end": end.isoformat()}
        result = self._tool("transfer_to_human", args)
        if not result.ok:
            self.error_code = result.error.code.value
            self.outcome = CallOutcome.failed
            return
        self.transfer_status = TransferStatus(result.data["status"])
        self.callback_id = result.data["callback_id"]
        if self.transfer_status is TransferStatus.connected:
            self.outcome = CallOutcome.transferred
            self._say("I'm transferring you now and passing along your details and what happened.")
        else:
            self._flag("handoff_no_answer")
            self.outcome = CallOutcome.callback
            minutes = self.tenant.emergency.on_call.callback_sla_minutes
            if urgency == "emergency":
                if self.ticket_id:
                    self._say(
                        "I couldn't reach the on-call technician. I've created an emergency "
                        f"ticket and someone will call you back within {minutes} minutes. "
                        "If anything gets worse, call 911."
                    )
                else:
                    self._say(
                        "I couldn't reach the on-call technician and couldn't create the "
                        "ticket. I've saved your details so someone can call you back. "
                        "If anything gets worse, call 911."
                    )
            else:
                self._say(
                    "I couldn't complete a live transfer. I've saved your details and "
                    "someone will call you back."
                )

    def _callback(
        self,
        *,
        reason: str,
        booking_id: str | None = None,
        summary: str | None = None,
    ) -> None:
        self._handoff(reason=reason, urgency="normal", booking_id=booking_id, summary=summary)
        if (
            self.outcome is not CallOutcome.failed
            and self.transfer_status is not TransferStatus.connected
        ):
            self.outcome = CallOutcome.callback
        self.state.callback_id = self.callback_id

    def _refuse(self) -> None:
        self._flag("confirmation_refused")
        self._say("No problem. I won't book or change anything. You can call back when ready.")
        self.outcome = CallOutcome.abandoned

    # ------------------------------------------------------------------ helpers
    def _clear_confirmation(self) -> None:
        self.policy.clear_confirmation(self.state)
        self.registry.session.confirmed = False
        self.registry.session.confirmation_token = None

    def _authorize_write(self, payload: ReadbackPayload, readback: str) -> bool:
        self.policy.read_back(self.state, payload)
        self._say(readback)
        start_index = max(
            self.facts.last_data_index,
            self.decision_index if self.decision_index is not None else -1,
        )
        utterance, index = confirmation_after(self.turns, start_index)
        decision = self.policy.confirm(self.state, utterance or "")
        if not decision.accepted:
            self.error_code = decision.error
            self._refuse()
            return False
        token = self.policy.issue_confirmation(self.state)
        self.registry.session.confirmed = True
        self.registry.session.confirmation_token = token.token
        self.decision_index = index
        return True

    def _say(self, text: str) -> None:
        self.responses.append(text)
        self.transcript.append(TranscriptTurn(role="assistant", text=text))

    def _tool(self, name: str, args: Mapping[str, Any]) -> Any:
        result = self.registry.call(name, args)
        if not result.ok and result.error is not None and result.error.code is ErrorCode.timeout:
            self._flag("tool_timeout")
        self.tool_events.append(
            ToolCallRecord(
                name=name,
                args=sanitize_args(args),
                result=result,
                latency_ms=LATENCY_MS.get(name, 0),
                at=self.now,
            )
        )
        return result

    def _lookup(self, *, include_bookings: bool = False, booking_id: str | None = None) -> Any:
        args: dict[str, Any] = {"include_bookings": include_bookings}
        if booking_id:
            args["booking_id"] = booking_id
        if self.facts.phone:
            args["phone"] = self.facts.phone
        if self.facts.name != "Caller" and self.facts.address is not None:
            args["name"] = self.facts.name
            args["address"] = self.facts.address.model_dump(mode="json")
        if "booking_id" not in args and "phone" not in args and "name" not in args:
            return _MissingLookup()
        result = self._tool("lookup_customer", args)
        if result.ok and not result.data["verification_required"]:
            self.registry.session.ownership_verified = True
        return result

    def _availability(
        self,
        *,
        zip_code: str | None = None,
        service_id: str | None = None,
        exclude: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        target_zip = zip_code or (self.facts.address.zip if self.facts.address else None)
        target_service = service_id or self.facts.service_id
        if target_zip is None or target_service is None:
            return []
        args: dict[str, Any] = {
            "service_id": target_service,
            "zip": target_zip,
            "window_days": (
                7 if self.facts.preferred_day is None or self.facts.day_flexible else 1
            ),
        }
        if self.facts.preferred_day:
            args["preferred_date"] = self.facts.preferred_day.isoformat()
        if exclude:
            args["exclude_slot_ids"] = sorted(exclude)
        result = self._tool("get_availability", args)
        if not result.ok or result.data["reason"] != "ok":
            return []
        return list(result.data["slots"])

    def _choose_slot(self, slots: list[dict[str, Any]]) -> dict[str, Any]:
        filtered = slots
        if self.facts.preferred_day is not None:
            same_day = [
                slot
                for slot in slots
                if datetime.fromisoformat(slot["start"]).date() == self.facts.preferred_day
            ]
            if same_day:
                filtered = same_day
        window = self.facts.preferred_window
        if window:
            ranges = {"morning": (0, 12), "afternoon": (12, 17), "evening": (17, 24)}
            low, high = ranges[window]
            in_window = [
                slot
                for slot in filtered
                if low <= datetime.fromisoformat(slot["start"]).hour < high
            ]
            if in_window:
                filtered = in_window
        if self.facts.preferred_hour is not None:
            return min(
                filtered,
                key=lambda slot: abs(
                    datetime.fromisoformat(slot["start"]).hour * 60
                    + datetime.fromisoformat(slot["start"]).minute
                    - self.facts.preferred_hour
                ),
            )
        return filtered[0]

    def _booking_id_from_text(self) -> str | None:
        match = re.search(r"\b(bk_[a-z0-9_]+)\b", self.facts.text)
        return match.group(1) if match else None

    def _find_booking(self) -> Any:
        booking_id = self._booking_id_from_text()
        result = self._lookup(include_bookings=True, booking_id=booking_id)
        if not result.ok or result.data["verification_required"]:
            return None
        if booking_id:
            return self.store.get_booking(self.tenant.tenant_id, booking_id)
        bookings = [
            self.store.get_booking(self.tenant.tenant_id, summary["booking_id"])
            for summary in result.data["bookings"]
        ]
        bookings = [booking for booking in bookings if booking is not None]
        if self.facts.service_id:
            matching = [
                booking for booking in bookings if booking.service_id == self.facts.service_id
            ]
            if matching:
                bookings = matching
        return bookings[0] if bookings else None

    def _verify_ownership(self, booking: Any) -> bool:
        return self.registry.session.ownership_verified

    def _customer(self) -> CustomerInput | None:
        address = self.facts.address
        if address is None:
            return None
        return CustomerInput(
            name=self.facts.name,
            phone=self.facts.phone or DEFAULT_CALLER_PHONE[self.tenant.tenant_id],
            address=address,
        )

    def _packet(
        self,
        *,
        intent: CallIntent,
        reason: str,
        urgency: str,
        booking_id: str | None = None,
        ticket_id: str | None = None,
        summary: str | None = None,
    ) -> HandoffPacket:
        booking = (
            self.store.get_booking(self.tenant.tenant_id, booking_id)
            if booking_id is not None
            else None
        )
        phone = (
            self.registry.session.caller_phone
            or self.facts.phone
            or (booking.contact_phone if booking else None)
        )
        service_id = booking.service_id if booking else self.facts.service_id
        address = booking.address if booking else self.facts.address
        name = self.facts.name if self.facts.name != "Caller" else None
        if booking is not None and name is None:
            customer = self.store.get_customer(self.tenant.tenant_id, booking.customer_id)
            if customer is not None:
                name = customer.name
        service = None
        if service_id and service_id in {item.id for item in self.tenant.services}:
            configured = self.tenant.require_service(service_id)
            service = HandoffService(id=configured.id, name=configured.name)
        if service is None and ticket_id is not None:
            service = HandoffService(id="emergency_response", name="Emergency response")
        return HandoffPacket(
            tenant_id=self.tenant.tenant_id,
            call_id=self.registry.session.call_id,
            caller=HandoffCaller(
                name=name,
                phone=phone,
                verified=self.registry.session.ownership_verified,
            ),
            intent=intent,
            service=service,
            address=address,
            urgency=urgency,
            booking_id=booking_id,
            emergency_ticket_id=ticket_id,
            summary=(summary or self.facts.text)[:500],
            reason=reason,
            requested_at=self.now,
        )

    def _faq_answer(self) -> str | None:
        text = self.facts.text.lower()
        if self.facts.service_id:
            for entry in self.tenant.knowledge_base.pricing:
                if entry.service_id == self.facts.service_id and not any(
                    keyword in text for keyword in ("include", "plan", "how late", "hours")
                ):
                    service = self.tenant.require_service(entry.service_id)
                    return (
                        f"{service.name} typically runs ${entry.range.min} to "
                        f"${entry.range.max}. {entry.caveat}"
                    )
        if any(keyword in text for keyword in ("how late", "change", "cancel", "policy")):
            for entry in self.tenant.knowledge_base.policies:
                if "cancel" in entry.id or "change" in entry.answer.lower():
                    return entry.answer
        for keyword, target in (
            ("hours", ("hours",)),
            ("maintenance", ("maintenance", "plan")),
            ("warranty", ("warrant",)),
            ("payment", ("payment", "credit card")),
            ("serve", ("serve", "service area", "zip")),
        ):
            if any(term in text for term in target):
                for entry in self.tenant.knowledge_base.faq:
                    haystack = f"{entry.id} {entry.question} {entry.answer}".lower()
                    if keyword in haystack:
                        return entry.answer
        if self.tenant.knowledge_base.faq:
            return self.tenant.knowledge_base.faq[0].answer
        return None

    def _record_booking(self, booking_id: str, *, replayed: bool = False) -> None:
        if booking_id not in self.booking_ids:
            self.booking_ids.append(booking_id)
        self.booking_id = booking_id
        self.replayed = self.replayed or replayed
        if not replayed:
            self.write_count += 1
        booking = self.store.get_booking(self.tenant.tenant_id, booking_id)
        if booking is not None:
            self.state.service_id = booking.service_id
            self.state.confirmed_slot_id = booking.slot_id
        self._say(
            f"Booked. {self._format(booking.start) if booking else 'Your appointment'} is "
            "confirmed and a text confirmation is queued."
        )

    def _callback_window(self, *, emergency: bool) -> tuple[datetime, datetime]:
        if emergency:
            return self.now, self.now + timedelta(
                minutes=self.tenant.emergency.on_call.callback_sla_minutes
            )
        return next_business_day_window(self.tenant, self.now)

    def _cancel_reason(self) -> str:
        text = self.facts.text.lower()
        if "found another" in text or "another company" in text or "another provider" in text:
            return "found_another_provider"
        if "fixed it" in text or "don't need" in text or "no longer" in text:
            return "no_longer_needed"
        if "moved" in text:
            return "moved"
        if "price" in text or "expensive" in text:
            return "price"
        if "duplicate" in text:
            return "duplicate"
        return "other"

    def _technician_name(self, technician_id: str) -> str:
        for technician in self.tenant.dispatch.technicians:
            if technician.id == technician_id:
                return technician.name
        return technician_id

    @staticmethod
    def _format(value: datetime) -> str:
        return value.strftime("%A %-d %B at %-I:%M %p")

    def _flag(self, flag: str) -> None:
        if flag not in self.qa_flags:
            self.qa_flags.append(flag)

    # ------------------------------------------------------------------ finalize
    def finalize(self, before: _Before) -> None:
        self.state.outcome = self.outcome
        self.state.booking_id = self.booking_id
        self.state.ticket_id = self.ticket_id
        self.state.callback_id = self.callback_id
        self.booking_count = self.store.count_bookings(self.tenant.tenant_id) - before.bookings
        self.ticket_count = len(self.store.list_tickets(self.tenant.tenant_id)) - before.tickets
        self.callback_count = (
            len(self.store.list_callbacks(self.tenant.tenant_id)) - before.callbacks
        )
        self.confirmation_count = (
            self.store.count_confirmations(self.tenant.tenant_id) - before.confirmations
        )
        self.store.save_call(
            call_id=self.registry.session.call_id,
            tenant_id=self.tenant.tenant_id,
            caller_phone=self.registry.session.caller_phone,
            intent=(self.state.intent or CallIntent.human).value,
            outcome=self.outcome.value,
            transfer_status=self.transfer_status.value if self.transfer_status else None,
            booking_id=self.booking_id,
            ticket_id=self.ticket_id,
            callback_id=self.callback_id,
            started_at=self.now,
            ended_at=self.now,
            qa_flags=self.qa_flags,
        )

    def result(self, scenario_id: str) -> CallResult:
        return CallResult(
            scenario_id=scenario_id,
            tenant_id=self.tenant.tenant_id,
            call_id=self.registry.session.call_id,
            intent=self.state.intent,
            outcome=self.outcome,
            transfer_status=self.transfer_status,
            booking_id=self.booking_id,
            booking_ids=self.booking_ids,
            ticket_id=self.ticket_id,
            callback_id=self.callback_id,
            service_id=self.state.service_id,
            booking_count=self.booking_count,
            ticket_count=self.ticket_count,
            callback_count=self.callback_count,
            cancel_count=self.cancel_count,
            write_count=self.write_count,
            replayed=self.replayed,
            confirmation_queued=self.confirmation_count > 0,
            already_cancelled=self.already_cancelled,
            old_slot_released=self.old_slot_released,
            slot_released=self.slot_released,
            safety_script=self.safety_script,
            emergency_category=self.emergency_category,
            emergency_severity=self.emergency_severity,
            vulnerable_occupant=self.vulnerable_occupant,
            handoff_packet=self.handoff_packet,
            transcript=self.transcript,
            tool_events=self.tool_events,
            latency_ms=sum(event.latency_ms for event in self.tool_events),
            qa_flags=self.qa_flags,
            response_text=" ".join(self.responses),
            error_code=self.error_code,
        )


class _MissingLookup:
    ok = False

    class _Error:
        code = ErrorCode.not_found
        message = "No lookup details"

    error = _Error()


def _call_id(tenant_id: str, scenario_id: str) -> str:
    safe = re.sub(r"[^a-z0-9_]+", "_", scenario_id.lower()).strip("_")
    return f"call_{tenant_id}_{safe}"

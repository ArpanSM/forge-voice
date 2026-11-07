"""Interactive audio call session on top of the #4 policy and eight tools.

The model talks and extracts. This class owns the deterministic policy boundary: it
builds the read-back, demands a clear yes from the live caller transcript, mints the
confirmation token server-side and commits at most one idempotent write.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, ValidationError, model_validator

from forge_voice.adapters.outbox import Outbox
from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.clock import FixedClock
from forge_voice.domain import Address
from forge_voice.errors import ErrorCode, StableError
from forge_voice.models import StrictModel
from forge_voice.policy import (
    BookingError,
    BookingService,
    CallIntent,
    CallOutcome,
    ConversationPolicy,
    CustomerInput,
    ReadbackPayload,
)
from forge_voice.policy.emergency import EmergencyTriage, triage_emergency
from forge_voice.policy.handoff import HandoffCaller, HandoffPacket, HandoffService
from forge_voice.runtime.interpreter import INTRO_NAME_RE, extract_facts
from forge_voice.runtime.readback import format_readback
from forge_voice.scheduling import next_business_day_window
from forge_voice.tenants import TenantConfig, load_all_tenants
from forge_voice.tools import ToolRegistry, ToolResult, ToolSession
from forge_voice.tools.envelope import ToolError, sanitize_args
from forge_voice.transfer import TransferSimulator

Stage = Literal["info", "readback", "booked", "ticket", "handoff", "error"]

TERMINAL_OUTCOMES = frozenset(
    {
        CallOutcome.booked,
        CallOutcome.rescheduled,
        CallOutcome.cancelled,
        CallOutcome.emergency_ticket,
        CallOutcome.transferred,
        CallOutcome.callback,
        CallOutcome.failed,
        CallOutcome.abandoned,
    }
)


class ToolReply(StrictModel):
    """One model-visible tool result with the exact shared #4 envelope."""

    ok: bool
    stage: Stage
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
    request_id: str = "req_local"

    @model_validator(mode="after")
    def envelope_is_consistent(self) -> ToolReply:
        if self.ok and self.error is not None:
            raise ValueError("a successful tool reply cannot carry an error")
        if not self.ok and self.error is None:
            raise ValueError("a failed tool reply must carry an error")
        return self

    def to_json(self) -> str:
        if self.ok:
            payload: dict[str, Any] = {
                "ok": True,
                "data": self.data,
                "request_id": self.request_id,
            }
        else:
            assert self.error is not None
            payload = {
                "ok": False,
                "error": self.error.model_dump(mode="json"),
                "request_id": self.request_id,
            }
        return json.dumps(payload, sort_keys=True)


@dataclass
class _PendingWrite:
    intent: CallIntent
    tool: str
    args: dict[str, Any]
    payload: ReadbackPayload
    target: str


class AudioCallSession:
    def __init__(
        self,
        *,
        tenant: TenantConfig,
        store: SQLiteAdapter,
        outbox: Outbox,
        clock: FixedClock,
        call_id: str,
        caller_phone: str | None = None,
        transfer: TransferSimulator | None = None,
        trace_path: Path | None = None,
    ) -> None:
        self.tenant = tenant
        self.store = store
        self.outbox = outbox
        self.clock = clock
        self.call_id = call_id
        self.trace_path = Path(trace_path) if trace_path is not None else None
        self.service = BookingService(tenant, store, outbox, clock)
        self.policy = ConversationPolicy(tenant, clock, self.service.tokens)
        self.state = self.policy.start_call(call_id, caller_phone)
        self.tool_session = ToolSession(
            tenant_id=tenant.tenant_id,
            call_id=call_id,
            caller_phone=caller_phone,
        )
        self.registry = ToolRegistry(
            tenant=tenant,
            store=store,
            service=self.service,
            session=self.tool_session,
            clock=clock,
            transfer=transfer or TransferSimulator(),
            policy=self.policy,
            state=self.state,
        )
        self.last_utterance = ""
        self.caller_turns: list[str] = []
        self.offered_slots: list[str] = []
        self.pending: _PendingWrite | None = None
        self.booking_id: str | None = None
        self.ticket_id: str | None = None
        self.callback_id: str | None = None
        self.confirmation_queued = False
        self.emergency_active = False
        self.emergency_handoff_done = False
        self.customer_name: str | None = None
        self.customer_phone: str | None = caller_phone
        self.address: Address | None = None
        self._trace("call_started", tenant=tenant.tenant_id)

    @classmethod
    def from_repo(
        cls,
        root: Path | str,
        tenant_slug: str,
        call_id: str,
        *,
        caller_phone: str | None = None,
        now: datetime | None = None,
        outbox_path: Path | str | None = None,
        trace_path: Path | str | None = None,
        transfer: TransferSimulator | None = None,
    ) -> AudioCallSession:
        root = Path(root).resolve()
        tenants = load_all_tenants(root / "tenants")
        tenant = tenants.get(tenant_slug)
        if tenant is None:
            raise KeyError(f"unknown tenant {tenant_slug!r}")
        store = SQLiteAdapter(":memory:")
        for slug in sorted(tenants):
            seed_path = root / "fixtures" / "corpus" / "seed" / f"{slug}.json"
            store.seed(json.loads(seed_path.read_text(encoding="utf-8")))
        current = now or datetime.now(ZoneInfo(tenant.timezone))
        return cls(
            tenant=tenant,
            store=store,
            outbox=Outbox(outbox_path),
            clock=FixedClock(current),
            call_id=call_id,
            caller_phone=caller_phone,
            transfer=transfer,
            trace_path=Path(trace_path) if trace_path is not None else None,
        )

    @property
    def greeting(self) -> str:
        return self.tenant.persona.greeting

    @property
    def completed(self) -> bool:
        """True once the call has a terminal outcome that must not write again."""
        return self.state.outcome in TERMINAL_OUTCOMES

    @property
    def instructions(self) -> str:
        services = ", ".join(f"{service.name} ({service.id})" for service in self.tenant.services)
        return (
            f"You are {self.tenant.persona.name}, the virtual assistant for "
            f"{self.tenant.display_name}. This call is recorded. Keep replies to one or two "
            "short sentences and ask one question at a time. Collect service, name, full "
            "address, five-digit ZIP and callback phone; ask for ZIP and phone one digit at a "
            "time and never guess them. "
            f"Services: {services}. "
            "Use get_service_area then get_availability before offering any time; never invent "
            "a slot, price, technician or availability. Offer at most three real slots. For a "
            "new booking do not call lookup_customer; a not_found lookup is normal. When you "
            "have a slot and the caller's name, address, ZIP and phone, call book_appointment "
            "with slot_id, service_id and those details; it returns the exact read-back. Say it "
            "and ask for an explicit yes. After the yes, call book_appointment with no "
            "arguments to commit. Never write before the explicit yes or claim a booking before "
            "the tool says booked. Never ask again for a detail already given. "
            "For gas, fire, smoke, flooding, a downed line, no heat, no cooling or anyone at "
            "risk, say the 911-first instruction from create_emergency_ticket, then call "
            "transfer_to_human with reason emergency. For a human or outside policy, call "
            "transfer_to_human. Never say transferred unless the tool returns connected; "
            "otherwise say a callback was queued. If no slot works, offer a callback or human. "
            "Quote a price only as a configured range and say the final price follows an "
            "on-site assessment."
        )

    def note_caller_utterance(self, text: str) -> None:
        self.last_utterance = text.strip()
        if self.last_utterance:
            self.caller_turns.append(self.last_utterance)
        self._trace("caller_utterance", text=self.last_utterance)

    def trace_event(self, event: str, **fields: Any) -> None:
        self._trace(event, **fields)

    def resolve_service_id(self, value: str) -> str | None:
        text = value.lower().replace("-", " ").replace("_", " ").strip()
        configured = {service.id for service in self.tenant.services}
        if value in configured:
            return value
        normalized = value.lower().replace("-", "_").strip()
        if normalized in configured:
            return normalized
        aliases = {
            "drain": "drain_cleaning",
            "clog": "drain_cleaning",
            "plumb": "drain_cleaning",
            "leak": "leak_repair",
            "water heater": "water_heater_repair",
            "air conditioning": "ac_repair",
            "ac ": "ac_repair",
            "ac repair": "ac_repair",
            "air conditioner": "ac_repair",
            "hvac": "ac_repair",
            "furnace": "furnace_repair",
            "heat": "furnace_repair",
            "outlet": "electrical_outlet",
            "switch": "electrical_outlet",
            "panel": "panel_upgrade",
            "electrical": "electrical_outlet",
        }
        for keyword, service_id in aliases.items():
            if keyword in text and service_id in configured:
                return service_id
        return None

    # ------------------------------------------------------------------ read tools
    def lookup_customer(
        self,
        *,
        phone: str | None = None,
        name: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        state: str = "CA",
        zip: str | None = None,
        booking_id: str | None = None,
        include_bookings: bool = False,
    ) -> ToolReply:
        address = self._address(line1, city, state, zip)
        payload: dict[str, Any] = {"include_bookings": include_bookings}
        if phone:
            payload["phone"] = phone
            if self.customer_phone is None:
                self.customer_phone = self._normalized_phone(phone)
        if name:
            payload["name"] = name
        if address is not None:
            payload["address"] = address.model_dump(mode="json")
        if booking_id:
            payload["booking_id"] = booking_id
        if not any(key in payload for key in ("phone", "name", "address", "booking_id")):
            return self._error(
                "invalid_argument",
                "I need a phone number, a name and address, or a booking number to look up.",
            )
        result = self._tool("lookup_customer", payload)
        if not result.ok:
            return self._from_result(result)
        data = result.data or {}
        if not data.get("verification_required"):
            self.tool_session.ownership_verified = True
            self._remember_customer(data.get("customer") or {})
            return ToolReply(
                ok=True,
                stage="info",
                message="I found the caller's record and verified it.",
                data=data,
                request_id=result.request_id,
            )
        return ToolReply(
            ok=True,
            stage="info",
            message=(
                "I found a possible record but it is masked. Ask the caller for their name "
                "and the service address, or another verification factor, before reading it."
            ),
            data=data,
            request_id=result.request_id,
        )

    def get_service_area(self, *, zip: str, service_id: str | None = None) -> ToolReply:
        payload: dict[str, Any] = {"zip": zip}
        if service_id:
            resolved = self.resolve_service_id(service_id)
            if resolved is None:
                return self._error("service_not_offered", f"We do not offer {service_id!r}.")
            payload["service_id"] = resolved
        result = self._tool("get_service_area", payload)
        if not result.ok:
            return self._from_result(result)
        data = result.data or {}
        return ToolReply(
            ok=True,
            stage="info",
            message=str(data.get("message") or "Service-area check complete."),
            data={"in_area": bool(data.get("in_area")), "message": data.get("message")},
            request_id=result.request_id,
        )

    def get_availability(
        self,
        *,
        service_id: str,
        zip: str,
        preferred_date: str | None = None,
        window_days: int = 7,
        exclude_slot_ids: list[str] | None = None,
    ) -> ToolReply:
        if self.completed:
            return self._already_completed()
        resolved_service = self.resolve_service_id(service_id)
        if resolved_service is None:
            return self._error("service_not_offered", f"We do not offer {service_id!r}.")
        service_id = resolved_service
        self.pending = None
        payload: dict[str, Any] = {
            "service_id": service_id,
            "zip": zip,
            "window_days": window_days,
        }
        if preferred_date:
            payload["preferred_date"] = preferred_date
        if exclude_slot_ids:
            payload["exclude_slot_ids"] = exclude_slot_ids
        result = self._tool("get_availability", payload)
        if not result.ok:
            return self._from_result(result)
        data = result.data or {}
        slots = list(data.get("slots") or [])
        self.offered_slots = [slot["slot_id"] for slot in slots]
        if slots:
            self.state.intent = CallIntent.book
            self.state.service_id = service_id
            description = "; ".join(
                f"{self._format(datetime.fromisoformat(slot['start']))} with "
                f"{slot['technician']['name']}"
                for slot in slots[:3]
            )
            message = f"Available times: {description}. Which one works?"
        else:
            message = "I don't have a real slot for that service and ZIP in that window."
        compact_slots = [
            {
                "slot_id": slot["slot_id"],
                "start": slot["start"],
                "technician": slot["technician"]["name"],
            }
            for slot in slots
        ]
        return ToolReply(
            ok=True,
            stage="info",
            message=message,
            data={"slots": compact_slots},
            request_id=result.request_id,
        )

    # ----------------------------------------------------------------- write tools
    def book_appointment(
        self,
        *,
        slot_id: str | None = None,
        service_id: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        state: str = "CA",
        zip: str | None = None,
    ) -> ToolReply:
        if (
            self.pending is not None
            and self.pending.intent is CallIntent.book
            and (slot_id is None or slot_id == self.pending.target)
        ):
            return self._commit_pending()
        if self.completed:
            if self.pending is None and (
                slot_id is None or slot_id == self.state.confirmed_slot_id
            ):
                replay = self._replayed_booking_reply()
                if replay is not None:
                    return replay
            return self._already_completed()
        already_confirmed = self.booking_id is not None and (
            slot_id is None or slot_id == self.state.confirmed_slot_id
        )
        if self.pending is None and already_confirmed:
            replay = self._replayed_booking_reply()
            if replay is not None:
                return replay
        if not slot_id or not service_id:
            return self._error(
                "confirmation_required",
                "Choose a real slot from get_availability and collect the customer details "
                "before I can read the booking back.",
            )
        resolved_service = self.resolve_service_id(service_id)
        if resolved_service is None:
            return self._error("service_not_offered", f"We do not offer {service_id!r}.")
        service_id = resolved_service
        if slot_id not in self.offered_slots:
            return self._error(
                "slot_unavailable",
                "That slot was not offered. Call get_availability again and offer a real slot.",
            )
        try:
            customer = self._customer_input(name, phone, line1, city, state, zip)
        except _ArgumentError as exc:
            self._trace("tool_rejected", tool="book_appointment", code=exc.code)
            return self._error(exc.code, exc.message)
        try:
            readback = self.service.booking_readback(slot_id, customer)
        except BookingError as exc:
            return self._error(exc.code.value, exc.message)
        self.state.intent = CallIntent.book
        self.state.service_id = service_id
        self.state.address = customer.address
        self._remember_input(customer)
        self.policy.begin_offer(self.state)
        self.policy.read_back(self.state, readback)
        self.pending = _PendingWrite(
            intent=CallIntent.book,
            tool="book_appointment",
            args={
                "service_id": service_id,
                "slot_id": slot_id,
                "customer": customer.model_dump(mode="json"),
            },
            payload=readback,
            target=slot_id,
        )
        self._trace("readback_ready", intent="book", target=slot_id)
        return ToolReply(
            ok=True,
            stage="readback",
            message=format_readback(readback),
            data={"readback": format_readback(readback), "target": slot_id},
        )

    def reschedule_appointment(
        self,
        *,
        booking_id: str | None = None,
        new_slot_id: str | None = None,
        reason: str | None = None,
    ) -> ToolReply:
        if self.completed:
            return self._already_completed()
        if (
            self.pending is not None
            and self.pending.intent is CallIntent.reschedule
            and (booking_id is None or booking_id == self.pending.args["booking_id"])
        ):
            return self._commit_pending()
        if not booking_id or not new_slot_id:
            return self._error("invalid_argument", "I need the booking and a new slot.")
        if not self.tool_session.ownership_verified:
            return self._error(
                "ownership_mismatch",
                "I need to verify the caller owns that booking before I can move it.",
            )
        old_booking = self.store.get_booking(self.tenant.tenant_id, booking_id)
        old_start = old_booking.start if old_booking is not None else None
        try:
            readback = self.service.reschedule_readback(booking_id, new_slot_id)
        except BookingError as exc:
            return self._error(exc.code.value, exc.message)
        message = format_readback(readback, action="move", old_start=old_start)
        self.state.intent = CallIntent.reschedule
        self.policy.begin_offer(self.state)
        self.policy.read_back(self.state, readback)
        self.pending = _PendingWrite(
            intent=CallIntent.reschedule,
            tool="reschedule_appointment",
            args={
                "booking_id": booking_id,
                "new_slot_id": new_slot_id,
                "reason": reason or "Caller requested a new time.",
            },
            payload=readback,
            target=new_slot_id,
        )
        return ToolReply(
            ok=True,
            stage="readback",
            message=message,
            data={"readback": message},
        )

    def cancel_appointment(
        self, *, booking_id: str | None = None, reason: str | None = None
    ) -> ToolReply:
        if self.completed:
            return self._already_completed()
        if (
            self.pending is not None
            and self.pending.intent is CallIntent.cancel
            and (booking_id is None or booking_id == self.pending.target)
        ):
            return self._commit_pending()
        if not booking_id:
            return self._error("invalid_argument", "I need the booking to cancel.")
        if not self.tool_session.ownership_verified:
            return self._error(
                "ownership_mismatch",
                "I need to verify the caller owns that booking before I can cancel it.",
            )
        try:
            readback = self.service.cancel_readback(booking_id)
        except BookingError as exc:
            return self._error(exc.code.value, exc.message)
        self.state.intent = CallIntent.cancel
        self.policy.begin_offer(self.state)
        self.policy.read_back(self.state, readback)
        self.pending = _PendingWrite(
            intent=CallIntent.cancel,
            tool="cancel_appointment",
            args={"booking_id": booking_id, "reason": reason},
            payload=readback,
            target=booking_id,
        )
        return ToolReply(
            ok=True,
            stage="readback",
            message=format_readback(readback, action="cancel"),
            data={"readback": format_readback(readback, action="cancel")},
        )

    def create_emergency_ticket(
        self,
        *,
        description: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        state: str = "CA",
        zip: str | None = None,
    ) -> ToolReply:
        if self.completed:
            return self._already_completed()
        text = (description or self.last_utterance).strip()
        if not text:
            return self._error("invalid_argument", "I need the caller's emergency description.")
        triage = triage_emergency(self.tenant, text)
        if triage is None:
            return self._error(
                "invalid_category",
                "I could not confirm an emergency from that description. Do not create a ticket "
                "without a configured emergency category.",
            )
        customer = None
        try:
            customer = self._customer_input(name, phone, line1, city, state, zip)
        except _ArgumentError:
            customer = None
        payload: dict[str, Any] = {
            "category": triage.category.id,
            "severity": triage.severity,
            "description": triage.description,
            "safety_instructions_given": [triage.safety_script],
            "transfer_mode": "live",
        }
        if customer is not None:
            payload["customer"] = customer.model_dump(mode="json")
            self._remember_input(customer)
        result = self._tool("create_emergency_ticket", payload)
        if not result.ok:
            return self._from_result(result)
        data = result.data or {}
        self.ticket_id = data.get("ticket_id")
        self.emergency_active = True
        self.state.intent = CallIntent.emergency
        self.state.urgency = triage.severity
        self.state.outcome = CallOutcome.emergency_ticket
        self._trace(
            "emergency_ticket",
            ticket_id=self.ticket_id,
            category=triage.category.id,
            severity=triage.severity,
            safety_script=triage.safety_script,
            vulnerable_occupant=triage.vulnerable_occupant,
        )
        return ToolReply(
            ok=True,
            stage="ticket",
            message=triage.safety_text,
            data={
                **data,
                "category": triage.category.id,
                "severity": triage.severity,
                "safety_text": triage.safety_text,
                "safety_script": triage.safety_script,
                "requires_911": triage.requires_911,
                "vulnerable_occupant": triage.vulnerable_occupant,
                "handoff_required": True,
            },
            request_id=result.request_id,
        )

    def transfer_to_human(
        self,
        *,
        reason: str = "caller_request",
        mode: str = "live",
        summary: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        state: str = "CA",
        zip: str | None = None,
    ) -> ToolReply:
        facts = self._facts()
        address = (
            self._address(line1, city, state, zip)
            or self.address
            or (facts.address if facts is not None else None)
        )
        caller_name = (
            name
            or self.customer_name
            or self._name_from_turns()
            or (
                facts.name
                if facts is not None and facts.name.lower() not in {"san jose", "san francisco"}
                else None
            )
        )
        caller_phone = self._normalized_phone(phone) if phone else self.customer_phone
        if not caller_phone and facts is not None:
            caller_phone = facts.phone
        if caller_name:
            self.customer_name = caller_name
        if caller_phone:
            self.customer_phone = caller_phone
        if address is not None:
            self.address = address
        if not caller_phone:
            return self._error(
                "invalid_phone",
                "I need a callback number before I can transfer or queue a callback.",
            )
        urgency = (
            "emergency" if reason == "emergency" or self.state.urgency == "emergency" else "normal"
        )
        service = None
        if self.state.service_id and self.state.service_id in {
            configured.id for configured in self.tenant.services
        }:
            configured = self.tenant.require_service(self.state.service_id)
            service = HandoffService(id=configured.id, name=configured.name)
        elif self.ticket_id:
            service = HandoffService(id="emergency_response", name="Emergency response")
        packet = HandoffPacket(
            tenant_id=self.tenant.tenant_id,
            call_id=self.call_id,
            caller=HandoffCaller(
                name=caller_name,
                phone=caller_phone,
                verified=self.tool_session.ownership_verified,
            ),
            intent=self.state.intent or CallIntent.human,
            service=service,
            address=address,
            urgency=urgency,
            booking_id=self.booking_id,
            emergency_ticket_id=self.ticket_id,
            summary=(summary or self.last_utterance or "Caller requested a human.")[:500],
            reason=reason,
            requested_at=self.clock.now,
        )
        selected_mode = mode if mode in {"live", "callback"} else "live"
        if selected_mode == "live" and not packet.complete:
            selected_mode = "callback"
        payload: dict[str, Any] = {
            "reason": reason,
            "urgency": urgency,
            "mode": selected_mode,
            "packet": packet.model_dump(mode="json"),
        }
        if selected_mode == "callback":
            if urgency == "emergency":
                start = self.clock.now
                end = start + timedelta(minutes=self.tenant.emergency.on_call.callback_sla_minutes)
            else:
                start, end = next_business_day_window(self.tenant, self.clock.now)
            payload["callback_window"] = {
                "start": start.isoformat(),
                "end": end.isoformat(),
            }
        result = self._tool("transfer_to_human", payload)
        if not result.ok:
            return self._from_result(result)
        data = result.data or {}
        self.callback_id = data.get("callback_id")
        self.state.transfer_status = data.get("status")
        if reason == "emergency" or urgency == "emergency":
            self.emergency_handoff_done = True
        status = data.get("status")
        self.state.outcome = (
            CallOutcome.transferred if status == "connected" else CallOutcome.callback
        )
        self._trace("handoff", status=status, reason=reason, mode=selected_mode)
        if status == "connected":
            message = (
                "A person has answered. I'm transferring you now with your details and what "
                "happened."
            )
        elif urgency == "emergency":
            minutes = self.tenant.emergency.on_call.callback_sla_minutes
            message = (
                "I couldn't reach the on-call technician. Your emergency ticket is open and "
                f"someone will call you back within {minutes} minutes. If anything gets worse, "
                "call 911."
            )
        else:
            message = (
                "I couldn't complete a live transfer. I saved your details and queued a "
                "callback for the next business window."
            )
        return ToolReply(
            ok=True,
            stage="handoff",
            message=message,
            data={"transfer": data, "packet": packet.model_dump(mode="json")},
            request_id=result.request_id,
        )

    # --------------------------------------------------------------- emergency
    def emergency_step(self, text: str) -> ToolReply | None:
        """Deterministic emergency path used before the model can respond.

        The first emergency turn creates the ticket and returns the exact 911-first
        script. Later turns attempt the on-call handoff with whatever details the
        caller has provided; if the packet is incomplete, the caller hears the one
        missing-detail prompt instead of a model guess.
        """
        if not text.strip():
            return None
        if not self.emergency_active:
            if triage_emergency(self.tenant, text) is None:
                return None
            reply = self.create_emergency_ticket(description=text)
            if not reply.ok:
                return reply
            return ToolReply(
                ok=True,
                stage="ticket",
                message=(
                    reply.message
                    + " To pass this to our on-call technician, please give me your name, "
                    "service address and callback number."
                ),
                data=reply.data,
            )
        if self.emergency_handoff_done:
            return ToolReply(
                ok=True,
                stage="handoff",
                message=(
                    "Our on-call technician has the ticket and your details. Stay on the "
                    "line, and call 911 if anything gets worse."
                ),
            )
        reply = self.transfer_to_human(
            reason="emergency",
            mode="live",
            summary=self.last_utterance or "Emergency reported by caller.",
        )
        if reply.ok:
            return reply
        return ToolReply(
            ok=False,
            stage="error",
            message=(
                reply.message
                + " Please give me your name, service address and callback number so I can "
                "pass them to the on-call technician."
            ),
            error=reply.error,
        )

    # -------------------------------------------------------------------- internal
    def _commit_pending(self) -> ToolReply:
        if self.completed:
            return self._already_completed()
        pending = self.pending
        if pending is None:
            return self._error(
                "confirmation_required",
                "There is no read-back to confirm. Collect the details and read them back first.",
            )
        decision = self.policy.confirm(self.state, self.last_utterance)
        if not decision.accepted:
            self.policy.read_back(self.state, pending.payload)
            self.tool_session.confirmed = False
            self.tool_session.confirmation_token = None
            self._trace("confirmation_refused", intent=pending.intent.value)
            return ToolReply(
                ok=False,
                stage="error",
                message=(
                    "I did not hear a clear yes. Do not write anything. Repeat the read-back and "
                    "ask for an explicit yes or no."
                ),
                error=ToolError(
                    code=ErrorCode.explicit_confirmation_required,
                    message="The caller did not give an explicit yes.",
                ),
            )
        token = self.policy.issue_confirmation(self.state)
        self.tool_session.confirmed = True
        self.tool_session.confirmation_token = token.token
        result = self._tool(pending.tool, pending.args)
        if not result.ok:
            self.tool_session.confirmed = False
            self.tool_session.confirmation_token = None
            self.policy.clear_confirmation(self.state)
            self.pending = None
            return self._from_result(result)
        data = result.data or {}
        if pending.intent is CallIntent.book:
            booking = data["booking"]
            self.booking_id = booking["booking_id"]
            self.policy.mark_written(self.state, target=pending.target, booking_id=self.booking_id)
            self.confirmation_queued = booking.get("confirmation", {}).get("sms") == "queued"
            self.state.outcome = CallOutcome.booked
            message = (
                f"Booked. {self._format(datetime.fromisoformat(booking['start']))} is "
                "confirmed and a text confirmation is queued."
            )
            stage: Stage = "booked"
            extra: dict[str, Any] = {
                "booking": booking,
                "replayed": data.get("replayed", False),
                "confirmation_queued": self.confirmation_queued,
            }
            self._trace(
                "booked",
                booking_id=self.booking_id,
                replayed=data.get("replayed", False),
                confirmation_queued=self.confirmation_queued,
                service_id=booking.get("service_id"),
                start=booking.get("start"),
                end=booking.get("end"),
                address=booking.get("address"),
                customer_name=self.customer_name,
                contact_phone=booking.get("contact_phone"),
            )
        elif pending.intent is CallIntent.reschedule:
            booking = data["booking"]
            self.booking_id = booking["booking_id"]
            self.policy.mark_written(self.state, target=pending.target, booking_id=self.booking_id)
            self.policy.record_change(self.state)
            self.state.outcome = CallOutcome.rescheduled
            message = (
                "Moved. Your appointment is now "
                f"{self._format(datetime.fromisoformat(booking['current']['start']))}."
            )
            stage = "booked"
            extra = {"booking": booking, "replayed": data.get("replayed", False)}
            self._trace(
                "rescheduled",
                booking_id=self.booking_id,
                service_id=booking.get("service_id"),
                start=booking["current"]["start"],
                address=booking.get("address"),
            )
        else:
            booking = data
            self.booking_id = data["booking_id"]
            self.policy.mark_written(self.state, target=pending.target, booking_id=self.booking_id)
            self.policy.record_change(self.state)
            self.state.outcome = CallOutcome.cancelled
            message = "Cancelled. No fee applies and the appointment slot has been released."
            stage = "booked"
            extra = {"booking": booking, "replayed": data.get("replayed", False)}
            self._trace("cancelled", booking_id=self.booking_id)
        self.pending = None
        return ToolReply(
            ok=True,
            stage=stage,
            message=message,
            data=extra,
            request_id=result.request_id,
        )

    def _tool(self, name: str, payload: dict[str, Any]) -> ToolResult:
        result = self.registry.call(name, payload)
        self._trace(
            "tool_result",
            tool=name,
            ok=result.ok,
            code=result.error.code.value if result.error is not None else "ok",
            request_id=result.request_id,
            args=sanitize_args(payload),
        )
        return result

    def _from_result(self, result: ToolResult) -> ToolReply:
        if not result.ok:
            assert result.error is not None
            return ToolReply(
                ok=False,
                stage="error",
                message=result.error.message,
                error=result.error,
                request_id=result.request_id,
            )
        return ToolReply(
            ok=True,
            stage="info",
            message=self._summary(result.data or {}),
            data=result.data or {},
            request_id=result.request_id,
        )

    @staticmethod
    def _summary(data: dict[str, Any]) -> str:
        if "in_area" in data:
            return str(data.get("message") or "Service-area check complete.")
        if "customer" in data:
            if data.get("verification_required"):
                return "The caller record is masked until ownership is verified."
            return "The caller record is verified."
        if "slots" in data:
            return "The available times are ready."
        return "The tool completed."

    def _already_completed(self) -> ToolReply:
        return self._error(
            "already_completed",
            "This call already has a completed outcome. No further availability, "
            "booking, reschedule, cancellation, emergency or transfer change is allowed.",
        )

    def _error(self, code: str, message: str, request_id: str | None = None) -> ToolReply:
        return ToolReply(
            ok=False,
            stage="error",
            message=message,
            error=ToolError(code=ErrorCode(code), message=message),
            request_id=request_id or f"req_{self.call_id}_local",
        )

    def _facts(self) -> Any:
        if not self.caller_turns:
            return None
        return extract_facts(self.tenant, self.caller_turns, self.store, self.clock.now)

    def _name_from_turns(self) -> str | None:
        for turn in reversed(self.caller_turns):
            match = INTRO_NAME_RE.search(turn)
            if match:
                return match.group(1)
        return None

    def _customer_input(
        self,
        name: str | None,
        phone: str | None,
        line1: str | None,
        city: str | None,
        state: str,
        zip: str | None,
    ) -> CustomerInput:
        address = self._address(line1, city, state, zip) or self.address
        resolved_name = name or self.customer_name
        resolved_phone = self._normalized_phone(phone) if phone else self.customer_phone
        if not resolved_name or not resolved_phone or address is None:
            facts = self._facts()
            if not resolved_name:
                resolved_name = self._name_from_turns()
                if (
                    not resolved_name
                    and facts is not None
                    and facts.name != "Caller"
                    and facts.name.lower() not in {"san jose", "san francisco"}
                ):
                    resolved_name = facts.name
            if not resolved_phone and facts is not None:
                resolved_phone = facts.phone
            if address is None and facts is not None:
                address = facts.address
        if not resolved_name:
            raise _ArgumentError("invalid_argument", "I need the caller's name.")
        if not resolved_phone:
            raise _ArgumentError("invalid_phone", "I need a ten-digit callback number.")
        if address is None:
            raise _ArgumentError(
                "invalid_argument", "I need the full service address and five-digit ZIP."
            )
        try:
            return CustomerInput(name=resolved_name, phone=resolved_phone, address=address)
        except ValidationError as exc:
            raise _ArgumentError(
                "invalid_argument", "Some customer details are malformed."
            ) from exc

    def _address(
        self,
        line1: str | None,
        city: str | None,
        state: str,
        zip: str | None,
    ) -> Address | None:
        if line1 is None and city is None and zip is None:
            return None
        if not (line1 and city and zip):
            return None
        from forge_voice.validation import normalize_zip

        try:
            return Address(line1=line1, city=city, state=state.upper(), zip=normalize_zip(zip))
        except (ValidationError, StableError):
            return None

    @staticmethod
    def _normalized_phone(value: str) -> str | None:
        from forge_voice.validation import normalize_phone

        try:
            return normalize_phone(value)
        except StableError:
            return None

    def _remember_customer(self, data: dict[str, Any]) -> None:
        self.customer_name = data.get("name") or self.customer_name
        self.customer_phone = data.get("phone") or self.customer_phone
        address = data.get("address")
        if isinstance(address, dict):
            try:
                self.address = Address.model_validate(address)
            except ValidationError:
                self.address = None
        if self.customer_phone:
            self.tool_session.caller_phone = self.customer_phone

    def _remember_input(self, customer: CustomerInput) -> None:
        self.customer_name = customer.name
        self.customer_phone = customer.phone
        self.address = customer.address
        self.tool_session.caller_phone = customer.phone

    @staticmethod
    def _format(value: datetime) -> str:
        return value.strftime("%A %-d %B at %-I:%M %p")

    def _replayed_booking_reply(self) -> ToolReply | None:
        if self.booking_id is None:
            return None
        booking = self.store.get_booking(self.tenant.tenant_id, self.booking_id)
        if booking is None:
            return None
        return ToolReply(
            ok=True,
            stage="booked",
            message="That booking is already confirmed; no second write was made.",
            data={
                "booking": self._booking_payload(booking),
                "replayed": True,
                "confirmation_queued": self.confirmation_queued,
            },
        )

    def _booking_payload(self, booking: Any) -> dict[str, Any]:
        technician = next(
            (item for item in self.tenant.dispatch.technicians if item.id == booking.technician_id),
            None,
        )
        return {
            "booking_id": booking.booking_id,
            "status": booking.status,
            "service_id": booking.service_id,
            "start": booking.start.isoformat(),
            "end": booking.end.isoformat(),
            "technician": {
                "id": booking.technician_id,
                "name": technician.name if technician else booking.technician_id,
            },
            "address": booking.address.model_dump(mode="json"),
            "contact_phone": booking.contact_phone,
            "confirmation": {
                "sms": booking.confirmation_sms,
                "email": booking.confirmation_email,
            },
        }

    def _trace(self, event: str, **fields: Any) -> None:
        if self.trace_path is None:
            return
        record = {
            "ts": time.time(),
            "event": event,
            "call_id": self.call_id,
            **fields,
        }
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        with self.trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")

    def close(self) -> None:
        if self.state.outcome is None:
            self.state.outcome = (
                CallOutcome.failed if self.state.write_count else CallOutcome.abandoned
            )
        self._trace(
            "call_finished",
            booking_id=self.booking_id,
            ticket_id=self.ticket_id,
            callback_id=self.callback_id,
            writes=self.state.write_count,
            outcome=self.state.outcome.value if self.state.outcome else None,
        )


class _ArgumentError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# `EmergencyTriage` is re-exported for callers that type the tool result in tests.
__all__ = ["AudioCallSession", "EmergencyTriage", "ToolReply"]

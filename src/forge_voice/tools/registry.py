"""Eight typed tools behind one result envelope and one tenant-scoped session."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.clock import Clock
from forge_voice.domain import (
    BookingRecord,
    CallbackRecord,
    IdempotencyRecord,
    TicketRecord,
)
from forge_voice.errors import ErrorCode, StableError
from forge_voice.models import StrictModel
from forge_voice.policy.booking import BookingService, CustomerInput
from forge_voice.policy.confirmation import payload_digest
from forge_voice.policy.conversation import ConversationPolicy
from forge_voice.policy.handoff import HandoffPacket
from forge_voice.policy.state import CallState
from forge_voice.scheduling import next_business_day_window
from forge_voice.tenants.models import Technician, TenantConfig
from forge_voice.tools.envelope import ToolResult, sanitize_args
from forge_voice.tools.models import (
    AvailabilityArgs,
    BookAppointmentArgs,
    CancelAppointmentArgs,
    EmergencyTicketArgs,
    LookupCustomerArgs,
    RescheduleAppointmentArgs,
    ServiceAreaArgs,
    TransferToHumanArgs,
)
from forge_voice.transfer import TransferSimulator
from forge_voice.validation import normalize_phone, normalize_zip, validate_service_address

TOOL_NAMES = (
    "lookup_customer",
    "get_service_area",
    "get_availability",
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "create_emergency_ticket",
    "transfer_to_human",
)

LATENCY_MS = {
    "lookup_customer": 2,
    "get_service_area": 1,
    "get_availability": 3,
    "book_appointment": 4,
    "reschedule_appointment": 4,
    "cancel_appointment": 3,
    "create_emergency_ticket": 3,
    "transfer_to_human": 25,
}


class ToolSession(StrictModel):
    tenant_id: str
    call_id: str
    caller_phone: str | None = None
    ownership_verified: bool = False
    change_count: int = 0
    confirmed: bool = False
    confirmation_token: str | None = None


class ToolRegistry:
    def __init__(
        self,
        *,
        tenant: TenantConfig,
        store: SQLiteAdapter,
        service: BookingService,
        session: ToolSession,
        clock: Clock,
        transfer: TransferSimulator,
        faults: Mapping[str, str] | None = None,
        policy: ConversationPolicy | None = None,
        state: CallState | None = None,
    ) -> None:
        self.tenant = tenant
        self.store = store
        self.service = service
        self.session = session
        self.clock = clock
        self.transfer = transfer
        self.policy = policy
        self.state = state
        self._faults = dict(faults or {})
        self._counter = 0
        self._handlers: dict[str, Callable[[dict[str, Any], str], dict[str, Any]]] = {
            "lookup_customer": self._lookup_customer,
            "get_service_area": self._get_service_area,
            "get_availability": self._get_availability,
            "book_appointment": self._book_appointment,
            "reschedule_appointment": self._reschedule_appointment,
            "cancel_appointment": self._cancel_appointment,
            "create_emergency_ticket": self._create_emergency_ticket,
            "transfer_to_human": self._transfer_to_human,
        }

    @property
    def tool_names(self) -> tuple[str, ...]:
        return TOOL_NAMES

    def call(self, name: str, args: Mapping[str, Any] | None = None) -> ToolResult:
        self._counter += 1
        request_id = f"req_{self.session.call_id}_{self._counter:03d}"
        payload = dict(args or {})
        try:
            if self.session.tenant_id != self.tenant.tenant_id:
                raise StableError(
                    ErrorCode.tenant_mismatch,
                    "This session is not configured for that business.",
                )
            handler = self._handlers.get(name)
            if handler is None:
                raise StableError(ErrorCode.invalid_argument, f"Unknown tool {name!r}.")
            fault = self._faults.pop(name, None)
            if fault is not None:
                if fault == "slot_expired":
                    raise StableError(
                        ErrorCode.slot_expired,
                        "That offer expired. I can refresh the available times.",
                        retryable=True,
                    )
                if fault == "slot_unavailable":
                    raise StableError(ErrorCode.slot_unavailable, "That slot was just taken.")
                if fault == "dependency_unavailable":
                    raise StableError(
                        ErrorCode.dependency_unavailable,
                        "The local adapter is unavailable.",
                        retryable=True,
                    )
                raise StableError(
                    ErrorCode.timeout,
                    "The tool did not respond in time.",
                    retryable=True,
                )
            data = handler(payload, request_id)
            result = ToolResult.success(data, request_id)
        except StableError as exc:
            result = ToolResult.failure(
                exc.code,
                exc.message,
                request_id,
                retryable=exc.retryable,
                details=exc.details,
            )
        except ValidationError as exc:
            fields = []
            for error in exc.errors():
                location = error.get("loc", ())
                fields.append(str(location[-1]) if location else "body")
            result = ToolResult.failure(
                ErrorCode.invalid_argument,
                "Some required details are missing or malformed.",
                request_id,
                details={"fields": fields},
            )
        except (ValueError, TypeError):
            result = ToolResult.failure(
                ErrorCode.invalid_argument,
                "Some required details are missing or malformed.",
                request_id,
            )
        except Exception:
            result = ToolResult.failure(
                ErrorCode.internal_error,
                "The request could not be completed safely.",
                request_id,
            )
        self._audit(name, payload, result)
        return result

    # -------------------------------------------------------------- read tools
    def _lookup_customer(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = LookupCustomerArgs.model_validate(payload)
        phone = normalize_phone(args.phone) if args.phone else None
        zip_code = normalize_zip(args.address.zip) if args.address else None
        booking = None
        if args.booking_id:
            booking = self.store.get_booking(self.tenant.tenant_id, args.booking_id)
            if booking is None:
                raise StableError(ErrorCode.not_found, "No matching booking.")
            customer = self.store.get_customer(self.tenant.tenant_id, booking.customer_id)
            if customer is None:
                raise StableError(ErrorCode.not_found, "No matching customer.")
        else:
            matches = self.store.find_customers(
                self.tenant.tenant_id,
                phone=phone,
                name=args.name,
                zip_code=zip_code,
                line1=args.address.line1 if args.address else None,
            )
            if not matches:
                raise StableError(ErrorCode.not_found, "No matching customer.")
            customer = matches[0]
        verified = (
            self._booking_factor_verified(customer, booking, args)
            if booking is not None
            else self._caller_verified(customer, args)
        )
        if not verified:
            return {
                "customer": {
                    "name": "Verified caller only",
                    "phone": self._mask_phone(customer.phone),
                },
                "match": "masked",
                "verification_required": True,
                "bookings": [],
            }
        bookings = []
        if args.include_bookings:
            for item in self.store.list_bookings(
                self.tenant.tenant_id, customer_id=customer.customer_id
            ):
                if args.booking_id and item.booking_id != args.booking_id:
                    continue
                bookings.append(
                    {
                        "booking_id": item.booking_id,
                        "service_id": item.service_id,
                        "start": item.start.isoformat(),
                        "status": item.status,
                    }
                )
        return {
            "customer": self._customer_dict(customer),
            "match": "exact",
            "verification_required": False,
            "bookings": bookings,
        }

    def _get_service_area(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = ServiceAreaArgs.model_validate(payload)
        zip_code = normalize_zip(args.zip)
        if args.service_id is not None:
            self._require_service(args.service_id)
        in_area = self.tenant.has_zip(zip_code)
        zone = self.tenant.service_area.dispatch_zones.get(zip_code) if in_area else None
        technicians: list[str] = []
        if in_area:
            technicians = sorted(
                tech.id
                for tech in self.tenant.dispatch.technicians
                if zip_code in tech.zips
                and (args.service_id is None or args.service_id in tech.skills)
            )
        restrictions: list[str] = []
        if zip_code in self.tenant.service_area.zip_exclusions:
            restrictions.append(f"ZIP {zip_code} is excluded from service.")
        message = (
            f"We cover {zip_code}." if in_area else f"ZIP {zip_code} is outside our service area."
        )
        return {
            "in_area": in_area,
            "dispatch_zone": zone,
            "technicians": technicians,
            "restrictions": restrictions,
            "message": message,
        }

    def _get_availability(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = AvailabilityArgs.model_validate(payload)
        zip_code = normalize_zip(args.zip)
        try:
            preferred = date.fromisoformat(args.preferred_date) if args.preferred_date else None
        except ValueError as exc:
            raise StableError(
                ErrorCode.invalid_argument, "preferred_date must be an ISO date."
            ) from exc
        availability = self.service.get_availability(
            args.service_id,
            zip_code,
            preferred_date=preferred,
            window_days=args.window_days,
            exclude_slot_ids=tuple(args.exclude_slot_ids),
        )
        self.session.confirmed = False
        self.session.confirmation_token = None
        if self.policy is not None and self.state is not None:
            self.policy.clear_confirmation(self.state)
        return {
            "slots": [
                {
                    "slot_id": offer.slot_id,
                    "start": offer.start.isoformat(),
                    "end": offer.end.isoformat(),
                    "technician": self._technician_dict(offer.technician_id),
                    "offer_expires_at": offer.expires_at.isoformat(),
                }
                for offer in availability.slots
            ],
            "timezone": availability.timezone,
            "reason": availability.reason,
        }

    # ------------------------------------------------------------- write tools
    def _book_appointment(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = BookAppointmentArgs.model_validate(payload)
        write = self.service.book(
            call_id=self.session.call_id,
            customer=self._customer_input(args.customer),
            service_id=args.service_id,
            slot_id=args.slot_id,
            confirmed=self.session.confirmed,
            token=self.session.confirmation_token,
        )
        return {
            "booking": self._booking_dict(write.booking),
            "replayed": write.replayed,
        }

    def _reschedule_appointment(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = RescheduleAppointmentArgs.model_validate(payload)
        previous = self.store.get_booking(self.tenant.tenant_id, args.booking_id)
        write = self.service.reschedule(
            call_id=self.session.call_id,
            booking_id=args.booking_id,
            new_slot_id=args.new_slot_id,
            caller_phone=self.session.caller_phone,
            ownership_verified=self.session.ownership_verified,
            confirmed=self.session.confirmed,
            token=self.session.confirmation_token,
            reason=args.reason,
        )
        return {
            "booking": {
                "booking_id": write.booking.booking_id,
                "status": write.booking.status,
                "previous": {"start": previous.start.isoformat()} if previous else None,
                "current": {
                    "start": write.booking.start.isoformat(),
                    "end": write.booking.end.isoformat(),
                    "technician": self._technician_dict(write.booking.technician_id),
                },
            },
            "replayed": write.replayed,
        }

    def _cancel_appointment(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = CancelAppointmentArgs.model_validate(payload)
        write = self.service.cancel(
            call_id=self.session.call_id,
            booking_id=args.booking_id,
            caller_phone=self.session.caller_phone,
            ownership_verified=self.session.ownership_verified,
            confirmed=self.session.confirmed,
            token=self.session.confirmation_token,
            reason=args.reason,
        )
        return {
            "booking_id": write.booking.booking_id,
            "status": write.booking.status,
            "cancelled_at": (
                write.booking.cancelled_at.isoformat() if write.booking.cancelled_at else None
            ),
            "already_cancelled": write.already_cancelled,
            "confirmation": {
                "sms": write.booking.confirmation_sms,
                "email": write.booking.confirmation_email,
            },
        }

    def _create_emergency_ticket(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = EmergencyTicketArgs.model_validate(payload)
        category = next(
            (
                candidate
                for candidate in self.tenant.emergency.categories
                if candidate.id == args.category
            ),
            None,
        )
        if category is None:
            raise StableError(
                ErrorCode.invalid_category,
                "That emergency category is not configured for this business.",
            )
        customer = self._customer_input(args.customer) if args.customer else None
        existing_customer = (
            self.store.find_customers(self.tenant.tenant_id, phone=customer.phone)
            if customer is not None
            else []
        )
        request = args.model_dump(mode="json")
        request_hash = payload_digest(request)
        key = f"{self.tenant.tenant_id}:{self.session.call_id}:ticket:{category.id}"
        existing = self.store.get_idempotency(self.tenant.tenant_id, key)
        if existing is not None:
            if existing.payload_hash != request_hash:
                raise StableError(
                    ErrorCode.idempotency_conflict,
                    "That retry does not match the original emergency ticket.",
                )
            return json.loads(existing.result_json)

        with self.store.transaction():
            existing = self.store.get_idempotency(self.tenant.tenant_id, key)
            if existing is not None:
                if existing.payload_hash != request_hash:
                    raise StableError(
                        ErrorCode.idempotency_conflict,
                        "That retry does not match the original emergency ticket.",
                    )
                return json.loads(existing.result_json)
            ticket_id = (
                f"em_{self.tenant.tenant_id}_"
                f"{self.store.next_sequence(self.tenant.tenant_id, 'ticket'):04d}"
            )
            ticket = TicketRecord(
                ticket_id=ticket_id,
                tenant_id=self.tenant.tenant_id,
                call_id=self.session.call_id,
                customer_id=existing_customer[0].customer_id if existing_customer else None,
                customer_name=customer.name if customer else None,
                customer_phone=customer.phone if customer else None,
                address=customer.address if customer else None,
                category=category.id,
                severity=category.severity,
                description=args.description,
                safety_instructions_given=args.safety_instructions_given,
                transfer_mode=args.transfer_mode,
                on_call_target=category.transfer_target,
                callback_sla_minutes=self.tenant.emergency.on_call.callback_sla_minutes,
                created_at=self.clock.now,
            )
            self.store.insert_ticket(ticket)
            data = {
                "ticket_id": ticket.ticket_id,
                "status": ticket.status,
                "severity": ticket.severity,
                "category": ticket.category,
                "on_call_target": ticket.on_call_target,
                "callback_sla_minutes": ticket.callback_sla_minutes,
                "transfer_id": None,
            }
            self.store.put_idempotency(
                IdempotencyRecord(
                    key=key,
                    tenant_id=self.tenant.tenant_id,
                    call_id=self.session.call_id,
                    intent="emergency_ticket",
                    target=category.id,
                    payload_hash=request_hash,
                    result_json=json.dumps(data, sort_keys=True),
                    created_at=self.clock.now,
                )
            )
        return data

    def _transfer_to_human(self, payload: dict[str, Any], _: str) -> dict[str, Any]:
        args = TransferToHumanArgs.model_validate(payload)
        packet = HandoffPacket.model_validate(args.packet)
        if packet.tenant_id != self.tenant.tenant_id:
            raise StableError(
                ErrorCode.tenant_mismatch,
                "That handoff belongs to another business.",
            )
        if packet.call_id != self.session.call_id:
            raise StableError(
                ErrorCode.invalid_argument,
                "The handoff packet does not match this call.",
            )
        if args.mode == "callback" and not packet.caller.phone:
            raise StableError(
                ErrorCode.invalid_argument,
                "A callback number is required for a callback handoff.",
            )
        if args.mode == "live" and not packet.complete:
            raise StableError(
                ErrorCode.invalid_argument,
                "The handoff packet is incomplete; queue a callback instead.",
            )
        request = args.model_dump(mode="json")
        request_hash = payload_digest(request)
        key = (
            f"{self.tenant.tenant_id}:{self.session.call_id}:transfer:"
            f"{args.reason}:{args.mode}:{packet.caller.phone}:{self._window_key(args)}"
        )
        existing = self.store.get_idempotency(self.tenant.tenant_id, key)
        if existing is not None:
            if existing.payload_hash != request_hash:
                raise StableError(
                    ErrorCode.idempotency_conflict,
                    "That retry does not match the original handoff.",
                )
            return json.loads(existing.result_json)

        emergency = args.reason == "emergency" or args.urgency == "emergency"
        target_id = (
            self.tenant.emergency.on_call.target
            if emergency
            else self.tenant.handoff.default_target
        )
        target = next(
            (candidate for candidate in self.tenant.handoff.targets if candidate.id == target_id),
            None,
        )
        if target is None:
            raise StableError(ErrorCode.no_target, "No handoff target is configured.")
        callback_id: str | None = None
        connected_at: datetime | None = None
        needs_callback = False
        if args.mode == "callback":
            status = "queued_callback"
            needs_callback = True
        elif self.transfer.answers(target.id):
            status = "connected"
            connected_at = self.clock.now
        else:
            status = "no_answer"
            needs_callback = True

        with self.store.transaction():
            if needs_callback:
                callback_id = self._create_callback(packet, args, emergency=emergency)
            transfer_id = (
                f"tr_{self.tenant.tenant_id}_"
                f"{self.store.next_sequence(self.tenant.tenant_id, 'transfer'):04d}"
            )
            if packet.emergency_ticket_id:
                self.store.set_ticket_transfer_in_transaction(
                    self.tenant.tenant_id,
                    packet.emergency_ticket_id,
                    transfer_id=transfer_id,
                    status="assigned" if status == "connected" else "open",
                )
            data = {
                "transfer_id": transfer_id,
                "status": status,
                "target": {
                    "id": target.id,
                    "name": target.name,
                    "phone": target.phone,
                },
                "connected_at": connected_at.isoformat() if connected_at else None,
                "callback_id": callback_id,
                "packet_complete": packet.complete,
            }
            self.store.put_idempotency(
                IdempotencyRecord(
                    key=key,
                    tenant_id=self.tenant.tenant_id,
                    call_id=self.session.call_id,
                    intent="transfer",
                    target=f"{args.reason}:{args.mode}",
                    payload_hash=request_hash,
                    result_json=json.dumps(data, sort_keys=True),
                    created_at=self.clock.now,
                )
            )
        return data

    # ----------------------------------------------------------------- helpers
    def _create_callback(
        self, packet: HandoffPacket, args: TransferToHumanArgs, *, emergency: bool
    ) -> str:
        if args.callback_window is not None:
            window_start = args.callback_window.start
            window_end = args.callback_window.end
        elif emergency:
            window_start = self.clock.now
            window_end = self.clock.now + timedelta(
                minutes=self.tenant.emergency.on_call.callback_sla_minutes
            )
        else:
            window_start, window_end = next_business_day_window(self.tenant, self.clock.now)
        key = (
            f"{self.tenant.tenant_id}:{self.session.call_id}:callback:"
            f"{args.reason}:{args.mode}:{packet.caller.phone}:"
            f"{window_start.isoformat()}:{window_end.isoformat()}"
        )
        request = {
            "reason": args.reason,
            "phone": packet.caller.phone,
            "mode": args.mode,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }
        request_hash = payload_digest(request)
        existing = self.store.get_idempotency(self.tenant.tenant_id, key)
        if existing is not None:
            if existing.payload_hash != request_hash:
                raise StableError(
                    ErrorCode.idempotency_conflict,
                    "That retry does not match the original callback.",
                )
            return json.loads(existing.result_json)["callback_id"]
        callback_id = (
            f"cb_{self.tenant.tenant_id}_"
            f"{self.store.next_sequence(self.tenant.tenant_id, 'callback'):04d}"
        )
        self.store.insert_callback(
            CallbackRecord(
                callback_id=callback_id,
                tenant_id=self.tenant.tenant_id,
                call_id=self.session.call_id,
                name=packet.caller.name or "Caller",
                phone=packet.caller.phone,
                reason=args.reason,
                window_start=window_start,
                window_end=window_end,
                sla="15_minutes" if emergency else "next_business_day",
                created_at=self.clock.now,
            )
        )
        self.store.put_idempotency(
            IdempotencyRecord(
                key=key,
                tenant_id=self.tenant.tenant_id,
                call_id=self.session.call_id,
                intent="callback",
                target=f"{args.reason}:{packet.caller.phone}",
                payload_hash=request_hash,
                result_json=json.dumps({"callback_id": callback_id}),
                created_at=self.clock.now,
            )
        )
        return callback_id

    @staticmethod
    def _window_key(args: TransferToHumanArgs) -> str:
        if args.callback_window is None:
            return "default"
        return f"{args.callback_window.start.isoformat()}:{args.callback_window.end.isoformat()}"

    def _customer_input(self, args: Any) -> CustomerInput:
        address = validate_service_address(
            self.tenant,
            line1=args.address.line1,
            city=args.address.city,
            state=args.address.state,
            zip_code=args.address.zip,
        )
        return CustomerInput(
            name=args.name,
            phone=normalize_phone(args.phone),
            address=address,
        )

    def _caller_verified(self, customer: Any, args: LookupCustomerArgs) -> bool:
        if not self.session.caller_phone or self.session.caller_phone != customer.phone:
            return False
        if args.phone:
            return normalize_phone(args.phone) == customer.phone
        return bool(args.name and args.address and self._address_matches(customer, args))

    @staticmethod
    def _address_matches(customer: Any, args: LookupCustomerArgs) -> bool:
        if args.address is None:
            return False
        return (
            args.name is not None
            and args.name.lower() == customer.name.lower()
            and normalize_zip(args.address.zip) == customer.address.zip
            and args.address.line1.lower() == customer.address.line1.lower()
        )

    def _booking_factor_verified(
        self, customer: Any, booking: Any, args: LookupCustomerArgs
    ) -> bool:
        if self.session.caller_phone and self.session.caller_phone == customer.phone:
            return True
        if not args.name or args.address is None:
            return False
        if not self._address_matches(customer, args):
            return False
        return booking.customer_id == customer.customer_id

    def _require_service(self, service_id: str) -> None:
        try:
            self.tenant.require_service(service_id)
        except Exception as exc:
            raise StableError(
                ErrorCode.service_not_offered,
                f"We do not offer {service_id.replace('_', ' ')}.",
            ) from exc

    def _technician_dict(self, technician_id: str) -> dict[str, str]:
        technician = self._technician(technician_id)
        return {"id": technician.id, "name": technician.name}

    def _technician(self, technician_id: str) -> Technician:
        for technician in self.tenant.dispatch.technicians:
            if technician.id == technician_id:
                return technician
        raise StableError(
            ErrorCode.not_found,
            "That technician is not configured for this business.",
        )

    def _booking_dict(self, booking: BookingRecord) -> dict[str, Any]:
        return {
            "booking_id": booking.booking_id,
            "status": booking.status,
            "service_id": booking.service_id,
            "start": booking.start.isoformat(),
            "end": booking.end.isoformat(),
            "technician": self._technician_dict(booking.technician_id),
            "address": booking.address.model_dump(mode="json"),
            "contact_phone": booking.contact_phone,
            "confirmation": {
                "sms": booking.confirmation_sms,
                "email": booking.confirmation_email,
            },
        }

    def _customer_dict(self, customer: Any) -> dict[str, Any]:
        return {
            "customer_id": customer.customer_id,
            "name": customer.name,
            "phone": customer.phone,
            "address": customer.address.model_dump(mode="json"),
        }

    @staticmethod
    def _mask_phone(phone: str) -> str:
        return f"{phone[:2]}******{phone[-4:]}"

    def _audit(self, name: str, args: Mapping[str, Any], result: ToolResult) -> None:
        self.store.append_event(
            tenant_id=self.tenant.tenant_id,
            call_id=self.session.call_id,
            request_id=result.request_id,
            tool=name,
            result_code=("ok" if result.ok and result.error is None else result.error.code.value),
            latency_ms=LATENCY_MS.get(name, 0),
            args=sanitize_args(args),
            result=result.model_dump(mode="json"),
            created_at=self.clock.now,
        )

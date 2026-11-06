"""Pure conversation policy: routing, read-back, confirmation and change rules."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from forge_voice.clock import Clock
from forge_voice.policy.confirmation import (
    ConfirmationToken,
    ConfirmationTokenStore,
    payload_digest,
)
from forge_voice.policy.state import CallIntent, CallPhase, CallState
from forge_voice.tenants.models import TenantConfig

WRITABLE_INTENTS = frozenset({CallIntent.book, CallIntent.reschedule, CallIntent.cancel})

EMERGENCY_PATTERNS = (
    "gas",
    "carbon monoxide",
    "co alarm",
    "smoke",
    "fire",
    "burning",
    "sparking",
    "downed line",
    "flood",
    "burst pipe",
    "water is everywhere",
    "sewage",
    "no heat",
    "heat stopped",
    "no cooling",
    "ac is out",
)

PRICING_PATTERNS = (
    "how much",
    "price",
    "cost",
    "how late",
    "hours",
    "policy",
    "warranty",
    "do you serve",
    "what does",
    "include",
    "payment",
)

YES_PATTERN = re.compile(
    r"\b(yes|yeah|yep|correct|right|sure|okay|ok|sounds good|book it|do it|"
    r"that's the one|that is the one|that works|go ahead|please do)\b"
)
REFUSAL_PATTERN = re.compile(r"\b(no|not yet|don't|do not|wrong|not right|hold on|wait)\b")


class ConfirmationRequiredError(ValueError):
    """A token was requested before read-back plus an explicit yes."""


class ConversationPolicy:
    """Deterministic safety boundary shared by the text runner and audio pipeline."""

    def __init__(
        self,
        tenant: TenantConfig,
        clock: Clock,
        tokens: ConfirmationTokenStore | None = None,
    ) -> None:
        self.tenant = tenant
        self.clock = clock
        self.tokens = tokens or ConfirmationTokenStore(clock)

    def start_call(self, call_id: str, caller_phone: str | None = None) -> CallState:
        return CallState(
            tenant_id=self.tenant.tenant_id,
            call_id=call_id,
            caller_phone=caller_phone,
            phase=CallPhase.greet,
        )

    def identify_intent(self, state: CallState, utterance: str) -> CallIntent:
        intent = self.classify_intent(utterance)
        state.intent = intent
        state.phase = CallPhase.identify_intent
        return intent

    def classify_intent(self, utterance: str) -> CallIntent:
        text = utterance.lower()
        if any(pattern in text for pattern in EMERGENCY_PATTERNS):
            return CallIntent.emergency
        if self._asks_for_human(text):
            return CallIntent.human
        if any(pattern in text for pattern in PRICING_PATTERNS):
            return CallIntent.pricing_faq
        if re.search(r"\bcancel\b", text):
            return CallIntent.cancel
        if re.search(
            r"\b(reschedule|move\b.*\b(appointment|booking)|"
            r"change\b.*\b(appointment|booking)|different time|another time)\b",
            text,
        ):
            return CallIntent.reschedule
        if re.search(
            r"\b(when is|status|check my appointment|what time is my appointment)\b", text
        ):
            return CallIntent.status
        return CallIntent.book

    @staticmethod
    def _asks_for_human(text: str) -> bool:
        return bool(
            re.search(
                r"\b(talk to|speak to|transfer me to)\b.*\b(person|human|someone|manager)\b"
                r"|\b(want|need) (a )?(person|human)\b",
                text,
            )
        )

    def record_readback(self, state: CallState, payload: Mapping[str, Any]) -> None:
        state.readback_done = True
        state.readback_payload = dict(payload)
        state.explicit_yes = False
        state.confirmation_token = None
        state.phase = CallPhase.readback

    def confirm(self, state: CallState, utterance: str) -> bool:
        if not state.readback_done:
            state.explicit_yes = False
            return False
        text = utterance.lower()
        decided = bool(YES_PATTERN.search(text)) and not REFUSAL_PATTERN.search(
            text.replace("yes", "")
        )
        if not decided and REFUSAL_PATTERN.search(text):
            decided = False
        state.explicit_yes = decided
        return decided

    def issue_confirmation(
        self,
        state: CallState,
        *,
        target: str,
        payload: Mapping[str, Any],
    ) -> ConfirmationToken:
        if state.intent not in WRITABLE_INTENTS:
            raise ConfirmationRequiredError("only booking writes use a confirmation token")
        if not state.readback_done or state.readback_payload is None:
            raise ConfirmationRequiredError("read-back must happen before a token is issued")
        if not state.explicit_yes:
            raise ConfirmationRequiredError("an explicit yes must happen before a token is issued")
        if payload_digest(payload) != payload_digest(state.readback_payload):
            raise ConfirmationRequiredError(
                "the confirmation payload must match the read-back payload"
            )
        token = self.tokens.issue(
            tenant_id=state.tenant_id,
            call_id=state.call_id,
            intent=state.intent.value,
            target=target,
            payload=payload,
            ttl_seconds=self.tenant.policies.confirmation_ttl_seconds,
        )
        state.confirmation_token = token.token
        state.phase = CallPhase.write_booking
        return token

    def within_change_cutoff(
        self, appointment_start: datetime, now: datetime | None = None
    ) -> bool:
        current = now or self.clock.now
        return appointment_start - current < timedelta(
            minutes=self.tenant.policies.change_cutoff_minutes
        )

    @staticmethod
    def can_change(state: CallState) -> bool:
        """One self-serve change per call; a second change goes to a human."""
        return state.change_count == 0

    @staticmethod
    def record_change(state: CallState) -> None:
        state.change_count += 1

    def is_after_hours(self, at: datetime | None = None) -> bool:
        local = (at or self.clock.now).astimezone(self._timezone())
        if local.date() in self.tenant.holidays:
            return True
        ranges = getattr(self.tenant.business_hours, local.strftime("%A").lower())
        if not ranges:
            return True
        minute = local.hour * 60 + local.minute
        for value in ranges:
            start, end = value.split("-")
            start_minute = int(start[:2]) * 60 + int(start[3:])
            end_minute = int(end[:2]) * 60 + int(end[3:])
            if start_minute <= minute < end_minute:
                return False
        return True

    def _timezone(self):
        from zoneinfo import ZoneInfo

        return ZoneInfo(self.tenant.timezone)

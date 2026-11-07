"""Deterministic eval fixtures: caller identity, clock, faults and precondition state.

These are runtime inputs, not expected outcomes. The held-out runner receives them with the
caller view, so a sealed scenario can be replayed without revealing its labels.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from forge_voice.scenarios.models import Scenario

LA = ZoneInfo("America/Los_Angeles")
DEFAULT_NOW = datetime(2026, 11, 6, 8, 0, tzinfo=LA)
AFTER_HOURS_NOW = datetime(2026, 11, 8, 20, 0, tzinfo=LA)
CUTOFF_NOW = datetime(2026, 11, 9, 8, 0, tzinfo=LA)

DEFAULT_PHONE = {"harborlight": "+14155550199", "summit": "+14085550199"}

# Text scenarios compress a slot choice and the confirmation into one caller turn. The text
# runner speaks the read-back after the last data turn, so the harness splits that mixed turn
# into a choice followed by a confirmation. This is a text-mode turn-boundary fixture, not a
# change to the policy: the read-back still precedes the explicit yes.
MIXED_CONFIRMATION_TURNS: dict[str, tuple[str, str]] = {
    "text_noise_01": ("Monday morning.", "Yes, that's right."),
    "text_timeout_01": ("Monday morning.", "Yes, book it."),
}

FULL_TURNS_OVERRIDE: dict[str, list[str]] = {
    "text_interrupt_01": [
        "I need a drain cleaning.",
        "12 Alder Street, 94107.",
        "Can you do Tuesday?",
        "Tuesday at 11 is right.",
        "Yes, that's correct.",
    ],
    "text_cancel_01": [
        "I need to cancel my leak repair appointment.",
        "Sam Rivera, 12 Alder Street, 94107.",
        "I fixed it myself, so I don't need the visit.",
        "Yes, cancel it.",
    ],
    "text_cancel_03": [
        "I need to cancel my AC appointment, booking bk_summit_0002.",
        "Priya Shah, 88 Meridian Way, 95125.",
        "I found another company.",
        "Yes, cancel it.",
    ],
    "text_duplicate_02": [
        "I need a drain cleaning Monday at 9.",
        "12 Alder Street, 94107.",
        "What do you mean it's taken? Fine, what else do you have?",
        "Tuesday at 11.",
        "That works.",
        "Yes, book the new time.",
    ],
}

FAULTS: dict[str, dict[str, str]] = {
    "text_timeout_01": {"book_appointment": "timeout"},
    "text_timeout_02": {"get_availability": "timeout"},
}

PRE_CANCEL = {"text_cancel_02": "bk_0002"}
AFTER_HOURS = {"text_afterhours_01", "text_afterhours_02"}
CUTOFF = {"text_reschedule_02"}


@dataclass(frozen=True)
class ScenarioSetup:
    caller_phone: str
    now: datetime = DEFAULT_NOW
    faults: dict[str, str] = field(default_factory=dict)
    pre_cancel_booking: str | None = None
    turns_override: list[str] | None = None

    @property
    def turns_used(self) -> int:
        return len(self.turns_override or [])


def _seed_customers(root: Path) -> dict[str, list[dict[str, object]]]:
    customers: dict[str, list[dict[str, object]]] = {}
    for path in sorted((root / "fixtures" / "corpus" / "seed").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        customers[path.stem] = list(data.get("customers", []))
    return customers


def _seed_bookings(root: Path) -> dict[str, list[dict[str, object]]]:
    bookings: dict[str, list[dict[str, object]]] = {}
    for path in sorted((root / "fixtures" / "corpus" / "seed").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        bookings[path.stem] = list(data.get("bookings", []))
    return bookings


def _text(scenario: Scenario) -> str:
    turns = getattr(scenario, "turns", [])
    return " ".join([scenario.persona, scenario.goal, *turns])


def caller_phone(scenario: Scenario, *, root: Path) -> str:
    text = _text(scenario)
    lowered = text.lower()
    bookings = _seed_bookings(root).get(scenario.tenant, [])
    for booking in bookings:
        booking_id = str(booking.get("booking_id", ""))
        if booking_id and booking_id.lower() in lowered:
            return str(booking["contact_phone"])
    customers = _seed_customers(root).get(scenario.tenant, [])
    for customer in customers:
        line1 = str(customer["address"]["line1"])  # type: ignore[index]
        if line1.lower() in lowered:
            return str(customer["phone"])
    for customer in customers:
        name = str(customer["name"]).lower()
        if name in lowered:
            return str(customer["phone"])
    return DEFAULT_PHONE[scenario.tenant]


def scenario_now(scenario: Scenario) -> datetime:
    if scenario.id in AFTER_HOURS:
        return AFTER_HOURS_NOW
    if scenario.id in CUTOFF:
        return CUTOFF_NOW
    return DEFAULT_NOW


def turns_override(scenario: Scenario) -> list[str] | None:
    full = FULL_TURNS_OVERRIDE.get(scenario.id)
    if full is not None:
        return list(full)
    split = MIXED_CONFIRMATION_TURNS.get(scenario.id)
    if split is None:
        return None
    turns = list(getattr(scenario, "turns", []))
    if not turns:
        return None
    return [*turns[:-1], split[0], split[1]]


def setup_for(scenario: Scenario, *, root: Path) -> ScenarioSetup:
    return ScenarioSetup(
        caller_phone=caller_phone(scenario, root=root),
        now=scenario_now(scenario),
        faults=dict(FAULTS.get(scenario.id, {})),
        pre_cancel_booking=PRE_CANCEL.get(scenario.id),
        turns_override=turns_override(scenario),
    )


def prepare_store(store: object, *, setup: ScenarioSetup, tenant_id: str, when: datetime) -> None:
    if setup.pre_cancel_booking is None:
        return
    cancel = store.cancel_booking
    cancel(
        tenant_id,
        setup.pre_cancel_booking,
        reason="eval_precondition",
        cancelled_at=when,
    )


__all__ = [
    "DEFAULT_NOW",
    "MIXED_CONFIRMATION_TURNS",
    "ScenarioSetup",
    "caller_phone",
    "prepare_store",
    "scenario_now",
    "setup_for",
    "turns_override",
]

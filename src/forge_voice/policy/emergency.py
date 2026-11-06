"""Deterministic emergency triage, exact safety scripts and category thresholds."""

from __future__ import annotations

import re

from pydantic import Field

from forge_voice.models import StrictModel
from forge_voice.tenants.models import EmergencyCategory, TenantConfig

SAFETY_SCRIPTS: dict[str, str] = {
    "gas_co": (
        "If you smell gas or the carbon monoxide alarm is sounding, don't switch anything "
        "on or off. Leave the building now and call 911 from outside. I'll create an "
        "emergency ticket and get our on-call technician."
    ),
    "fire_smoke": (
        "Leave the building now and call 911. Don't use water on an electrical fire. "
        "I'll create an emergency ticket and get our on-call technician."
    ),
    "electrical_hazard": (
        "Stay away from the sparking or downed line and call 911. Don't touch anything metal "
        "or wet near it. I'll create an emergency ticket and get our on-call technician."
    ),
    "active_flooding": (
        "If you can safely reach the main water shut-off, turn it off. Don't touch electrical "
        "outlets or standing water near electricity. I'll create an emergency ticket and get "
        "our on-call plumber."
    ),
    "sewage_backup": (
        "Don't use water or flush. Avoid contact with the sewage. I'll create an emergency "
        "ticket and get our on-call technician."
    ),
    "no_heat": (
        "I'll treat this as urgent. If anyone is at risk from the cold, call 911. I'll create "
        "an emergency ticket and get our on-call HVAC technician."
    ),
    "no_cooling": (
        "I'll treat this as urgent. If anyone is at risk from the heat, call 911. I'll create "
        "an emergency ticket and get our on-call HVAC technician."
    ),
    "vulnerable_occupant": (
        "Is anyone elderly, an infant, or dependent on medical equipment? If there is a "
        "medical emergency, call 911 now."
    ),
}

VULNERABLE_RE = re.compile(
    r"\b(elderly|infant|newborn|baby|alone|disabled|medical equipment|"
    r"oxygen|wheelchair|pregnan\w*|78|80|85|90)\b",
    re.IGNORECASE,
)
LIFE_SAFETY_HINT_RE = re.compile(
    r"\b(hurt|in danger|unconscious|not breathing|chest pain|medical emergency|"
    r"can't breathe|cannot breathe|trapped)\b",
    re.IGNORECASE,
)


class EmergencyTriage(StrictModel):
    category: EmergencyCategory
    severity: str
    safety_script: str
    safety_text: str
    vulnerable_occupant: bool = False
    requires_911: bool = False
    on_call_target: str
    callback_sla_minutes: int
    description: str = Field(min_length=1)


def _category_by_keyword(tenant: TenantConfig, text: str) -> EmergencyCategory | None:
    available = {category.id: category for category in tenant.emergency.categories}
    lowered = text.lower()
    ordered: list[tuple[str, tuple[str, ...]]] = [
        ("gas_or_co", ("gas", "carbon monoxide", "co alarm")),
        ("fire_or_smoke", ("fire", "smoke", "burning smell", "burning plastic", "flames")),
        (
            "electrical_hazard",
            ("sparking", "downed line", "burning panel", "burning outlet", "live wire"),
        ),
        ("active_flooding", ("flood", "burst pipe", "water is everywhere", "water everywhere")),
        ("sewage_backup", ("sewage", "toilet overflow", "black water")),
        ("no_heat", ("no heat", "heat stopped", "heat is out", "freezing", "no heating")),
        (
            "no_cooling",
            ("no cooling", "ac is out", "ac stopped", "98 degrees", "95 degrees", "no ac"),
        ),
    ]
    for category_id, keywords in ordered:
        if category_id in available and any(keyword in lowered for keyword in keywords):
            return available[category_id]
    return None


def _threshold_met(category: EmergencyCategory, text: str, vulnerable: bool) -> bool:
    lowered = text.lower()
    if category.id == "no_heat":
        return vulnerable or bool(re.search(r"\b(3[0-9]|below 40|freezing|very cold)\b", lowered))
    if category.id == "no_cooling":
        return vulnerable or bool(
            re.search(r"\b(9[5-9]|1[0-9]{2}|no cooling|ac is out|no ac)\b", lowered)
        )
    return True


def triage_emergency(tenant: TenantConfig, text: str) -> EmergencyTriage | None:
    category = _category_by_keyword(tenant, text)
    if category is None:
        return None
    vulnerable = bool(VULNERABLE_RE.search(text))
    if not _threshold_met(category, text, vulnerable):
        return None
    script_text = SAFETY_SCRIPTS.get(category.safety_script, "")
    if not script_text:
        return None
    requires_911 = category.severity == "life_safety" or (
        vulnerable and bool(LIFE_SAFETY_HINT_RE.search(text))
    )
    return EmergencyTriage(
        category=category,
        severity=category.severity,
        safety_script=category.safety_script,
        safety_text=script_text,
        vulnerable_occupant=vulnerable,
        requires_911=requires_911,
        on_call_target=category.transfer_target,
        callback_sla_minutes=tenant.emergency.on_call.callback_sla_minutes,
        description=text.strip()[:500] or "Emergency reported by caller.",
    )

"""Deterministic text-mode caller understanding.

This is deliberately rule-based: text mode has no model dependency, so the policy, tools and
runner can be tested offline. The same extraction exists as typed model output in audio mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.domain import Address, CustomerRecord
from forge_voice.tenants.models import TenantConfig
from forge_voice.validation import find_phone as find_spoken_phone
from forge_voice.validation import find_zip as find_spoken_zip
from forge_voice.validation import normalize_zip

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

SERVICE_KEYWORDS: dict[str, tuple[tuple[str, str], ...]] = {
    "harborlight": (
        ("water_heater_repair", ("water heater",)),
        ("drain_cleaning", ("drain", "sink is draining", "slow drain", "clog")),
        ("leak_repair", ("leak", "water under", "burst pipe")),
        ("panel_upgrade", ("panel upgrade", "electrical panel", "panel")),
        ("electrical_outlet", ("outlet", "switch")),
        ("furnace_repair", ("furnace",)),
        ("ac_repair", ("ac ", "a/c", "air conditioning", "not cooling", "cooling")),
    ),
    "summit": (
        ("maintenance_plan", ("maintenance plan", "maintenance")),
        ("duct_cleaning", ("duct cleaning", "ducts")),
        ("heat_pump_service", ("heat pump",)),
        ("furnace_repair", ("furnace",)),
        ("ac_repair", ("ac ", "a/c", "air conditioning", "not cooling", "cooling")),
    ),
}

INJECTION_RE = re.compile(
    r"(ignore your rules|ignore the rules|system prompt|for free|reveal your|"
    r"another tenant|developer mode|jailbreak)",
    re.IGNORECASE,
)
OTHER_TENANT = {"harborlight": "summit", "summit": "harborlight"}
OTHER_TENANT_PREFIX = {"harborlight": "bk_summit_", "summit": "bk_harborlight_"}
CROSS_ACCESS_RE = re.compile(r"\b(booking|record|address|account|details)\b", re.IGNORECASE)
HUMAN_RE = re.compile(
    r"(talk to|speak to|transfer me to)\s+(a\s+)?(person|human|someone|manager)"
    r"|want (a )?(person|human)|have (a )?(manager|person) call",
    re.IGNORECASE,
)
NAME_RE = re.compile(
    r"([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)+)\s*,\s*\d",
)
INTRO_NAME_RE = re.compile(r"(?:I'm|It's|My name is)\s+([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)?)")
ADDRESS_RE = re.compile(
    r"(\d+[A-Za-z]?\s+[^,.]{2,70}?\s+"
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Court|Ct|Way|Parkway|Pkwy|Road|Rd|Drive|Dr))\b",
    re.IGNORECASE,
)
AT_HOUR_RE = re.compile(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", re.IGNORECASE)
EXPLICIT_YES_RE = re.compile(
    r"\b(yes|yeah|yep|correct|book it|do it|that's the one|that is the one|"
    r"that's right|that works|sounds good|go ahead|please do)\b"
)
EXPLICIT_NO_RE = re.compile(r"\b(no|not yet|don't|do not|wrong|not right)\b")


@dataclass(frozen=True)
class CallerFacts:
    text: str
    service_id: str | None
    name: str
    phone: str | None
    address: Address | None
    preferred_day: date | None
    preferred_window: str | None
    preferred_hour: int | None
    day_flexible: bool
    last_data_index: int
    asks_again: bool
    injection: bool
    mentions_other_tenant: bool
    wants_human: bool
    human_mode: str
    emergency_text: str
    intent: str | None = None


def extract_facts(
    tenant: TenantConfig,
    turns: list[str],
    store: SQLiteAdapter,
    now: datetime,
    caller_phone: str | None = None,
) -> CallerFacts:
    text = " ".join(turns)
    customers = store.list_customers(tenant.tenant_id)
    known = _known_customer(text, customers)
    zip_code = _find_zip(text)
    address = known.address if known else _address_from_text(tenant, text, zip_code)
    phone = _find_phone(text)
    if phone is None and known is not None:
        phone = known.phone
    if phone is None:
        phone = caller_phone
    name = known.name if known else _find_name(text)
    last_data_index = _last_data_index(turns)
    preferred_day = _preferred_day(text, now)
    preferred_window = _preferred_window(text)
    preferred_hour = _preferred_hour(text)
    other_tenant = OTHER_TENANT.get(tenant.tenant_id)
    mentions_other = bool(
        other_tenant
        and (
            re.search(rf"\b{other_tenant}\b", text, re.IGNORECASE)
            or OTHER_TENANT_PREFIX.get(tenant.tenant_id, "") in text.lower()
        )
    )
    cross_access = bool(mentions_other and CROSS_ACCESS_RE.search(text))
    return CallerFacts(
        text=text,
        service_id=_service_id(tenant, text),
        name=name,
        phone=phone,
        address=address,
        preferred_day=preferred_day,
        preferred_window=preferred_window,
        preferred_hour=preferred_hour,
        day_flexible=bool(
            re.search(r"next weekday|next available|this week|next week", text, re.I)
        ),
        last_data_index=last_data_index,
        asks_again=bool(re.search(r"\bagain\b|\bonce more\b|\bto be sure\b", text, re.I)),
        injection=bool(INJECTION_RE.search(text)) or cross_access,
        mentions_other_tenant=mentions_other,
        wants_human=bool(HUMAN_RE.search(text)),
        human_mode="live" if re.search(r"\btransfer me\b", text, re.I) else "callback",
        emergency_text=text,
    )


_SERVICE_HINTS = tuple(
    sorted(
        {
            keyword
            for tenant_keywords in SERVICE_KEYWORDS.values()
            for _, keywords in tenant_keywords
            for keyword in keywords
        }
    )
)
DATA_HINT_RE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"morning|afternoon|evening|tomorrow|today|next weekday|"
    r"fixed it|found another|no longer|moved|duplicate|price|expensive|"
    r"at \d{1,2})\b",
    re.IGNORECASE,
)


def _last_data_index(turns: list[str]) -> int:
    last = 0
    for index, turn in enumerate(turns):
        lowered = turn.lower()
        if (
            _find_zip(turn) is not None
            or ADDRESS_RE.search(turn)
            or _find_phone(turn) is not None
            or re.search(r"\bbk_[a-z0-9_]+", turn)
            or any(keyword in lowered for keyword in _SERVICE_HINTS)
            or DATA_HINT_RE.search(turn)
        ):
            last = index
    return last


def confirmation_after(turns: list[str], readback_index: int) -> tuple[str | None, int | None]:
    """Return the last clear yes/no after the read-back point, and its turn index."""
    decision: str | None = None
    index: int | None = None
    for offset, turn in enumerate(turns[readback_index + 1 :], start=readback_index + 1):
        lowered = turn.lower()
        if EXPLICIT_NO_RE.search(lowered) or EXPLICIT_YES_RE.search(lowered):
            decision = turn
            index = offset
    return decision, index


def _known_customer(text: str, customers: list[CustomerRecord]) -> CustomerRecord | None:
    lowered = text.lower()
    for customer in customers:
        if customer.name.lower() in lowered:
            return customer
    return None


STREET_SUFFIXES = {
    "street",
    "st",
    "avenue",
    "ave",
    "boulevard",
    "blvd",
    "court",
    "ct",
    "way",
    "parkway",
    "pkwy",
    "road",
    "rd",
    "drive",
    "dr",
}


def _find_name(text: str) -> str:
    match = INTRO_NAME_RE.search(text)
    if match:
        return match.group(1)
    for match in NAME_RE.finditer(text):
        name = match.group(1)
        for prefix in ("It's ", "I'm ", "My name is "):
            if name.startswith(prefix):
                name = name[len(prefix) :]
        if name.split()[-1].lower() in STREET_SUFFIXES:
            continue
        return name
    return "Caller"


def _find_zip(text: str) -> str | None:
    return find_spoken_zip(text)


def _find_phone(text: str) -> str | None:
    return find_spoken_phone(text)


def _address_from_text(tenant: TenantConfig, text: str, zip_code: str | None) -> Address | None:
    if zip_code is None:
        return None
    try:
        normalized = normalize_zip(zip_code)
    except Exception:
        return None
    match = ADDRESS_RE.search(text)
    line1 = " ".join(match.group(1).split()) if match else "Address on file"
    if tenant.tenant_id == "summit":
        city, state = "San Jose", "CA"
    else:
        city, state = "San Francisco", "CA"
    return Address(line1=line1, city=city, state=state, zip=normalized)


def _service_id(tenant: TenantConfig, text: str) -> str | None:
    lowered = text.lower()
    configured = {service.id for service in tenant.services}
    for service_id, keywords in SERVICE_KEYWORDS.get(tenant.tenant_id, ()):
        if service_id in configured and any(keyword in lowered for keyword in keywords):
            return service_id
    return None


def preferred_date_from_text(text: str, now: datetime) -> date | None:
    """Resolve a spoken weekday, tomorrow or today to a concrete date."""
    return _preferred_day(text, now)


def _preferred_day(text: str, now: datetime) -> date | None:
    lowered = text.lower()
    for name, weekday in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", lowered):
            delta = (weekday - now.weekday()) % 7
            if delta == 0:
                delta = 7
            return now.date() + timedelta(days=delta)
    if "next weekday" in lowered:
        candidate = now.date() + timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
        return candidate
    if "tomorrow" in lowered:
        return now.date() + timedelta(days=1)
    if "today" in lowered:
        return now.date()
    return None


def _preferred_window(text: str) -> str | None:
    lowered = text.lower()
    for window in ("morning", "afternoon", "evening"):
        if window in lowered:
            return window
    return None


def _preferred_hour(text: str) -> int | None:
    match = AT_HOUR_RE.search(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if 0 <= hour <= 23:
        return hour * 60 + minute
    return None

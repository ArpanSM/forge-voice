"""Spoken-value normalization and deterministic validation for ZIPs and phones.

The audio model may return grouped digits, spoken digit words, or a partially heard
value. Everything here is deterministic: a value is either normalized to the exact
shape the policy writes, or rejected with a specific, caller-safe reprompt. Nothing is
guessed.
"""

from __future__ import annotations

import re

from forge_voice.domain import Address
from forge_voice.errors import ErrorCode, StableError
from forge_voice.tenants.models import TenantConfig

DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}
_WORD_RE = re.compile(r"\b(" + "|".join(DIGIT_WORDS) + r")\b", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+")
_DIGIT_SEPARATOR_RE = re.compile(r"^[\s\-–—.,()/]*$")
_ZIP_PLUS_FOUR_RE = re.compile(r"(?<!\d)(\d{5})-\d{4}(?!\d)")

_STREET_SUFFIX = (
    r"Street|St|Avenue|Ave|Boulevard|Blvd|Court|Ct|Way|Parkway|Pkwy|"
    r"Road|Rd|Drive|Dr|Lane|Ln|Place|Pl"
)
STREET_ADDRESS_RE = re.compile(
    rf"(\d+[A-Za-z]?\s+[^,.]{{2,70}}?\s+(?:{_STREET_SUFFIX}))\b",
    re.IGNORECASE,
)


_CITY_RE = re.compile(
    r",\s*([A-Za-z][A-Za-z .'-]{1,40}?)\s*,\s*(?:\d{5}|CA\b|California\b)",
    re.IGNORECASE,
)


def digits_from_words(value: str) -> str:
    """Replace spoken digit words with their characters, leaving other words intact."""
    return _WORD_RE.sub(lambda match: DIGIT_WORDS[match.group(1).lower()], value)


def _digit_runs(value: str) -> list[str]:
    """Return each numeric run, merging digits separated only by punctuation/space.

    Spoken digit words become single digits with spaces, so ``nine five one two five``
    is one run of five digits while ``88 Meridian Way, San Jose, 95125`` is two runs.
    """
    converted = digits_from_words(str(value))
    runs: list[str] = []
    current = ""
    last_end = 0
    for match in _NUMBER_RE.finditer(converted):
        if current and _DIGIT_SEPARATOR_RE.fullmatch(converted[last_end : match.start()]):
            current += match.group(0)
        else:
            if current:
                runs.append(current)
            current = match.group(0)
        last_end = match.end()
    if current:
        runs.append(current)
    return runs


def _valid_us_phone(digits: str) -> bool:
    """Reject the all-zero placeholder; synthetic 555 numbers stay valid."""
    return len(digits) == 10 and digits != "0000000000"


def zip_candidates(text: str) -> list[str]:
    """Return every distinct ZIP in an utterance, including ZIP+4 first-five forms."""
    converted = digits_from_words(str(text))
    found = set(_ZIP_PLUS_FOUR_RE.findall(converted))
    found.update(run for run in _digit_runs(text) if len(run) == 5)
    return sorted(found)


def find_zip(text: str) -> str | None:
    """Return the single five-digit ZIP in an utterance, accepting digit words."""
    candidates = zip_candidates(text)
    return candidates[0] if len(candidates) == 1 else None


def find_phone(text: str) -> str | None:
    """Return a normalized US phone from an utterance, accepting digit words."""
    candidates: set[str] = set()
    for run in _digit_runs(text):
        if len(run) == 10 and _valid_us_phone(run):
            candidates.add(f"+1{run}")
        elif len(run) == 11 and run.startswith("1") and _valid_us_phone(run[1:]):
            candidates.add(f"+{run}")
    return candidates.pop() if len(candidates) == 1 else None


def _heard_length(value: str) -> int:
    runs = _digit_runs(value)
    return max((len(run) for run in runs), default=0)


def _zip_heard_length(value: str) -> int:
    runs = [len(run) for run in _digit_runs(value) if 3 <= len(run) <= 6]
    return max(runs, default=0)


def _specific_zip_error(value: str) -> StableError:
    length = _zip_heard_length(value)
    if length and length != 5:
        heard = f"I heard {length} digit{'s' if length != 1 else ''}."
    else:
        heard = "I could not pick out a ZIP code."
    return StableError(
        ErrorCode.invalid_zip,
        f"{heard} I need exactly five digits for the ZIP; please say them one at a "
        "time, for example nine five one two five.",
        details={"field": "zip", "digits_heard": length},
    )


def _specific_phone_error(value: str) -> StableError:
    length = _heard_length(value)
    if length and length != 10:
        heard = f"I heard {length} digit{'s' if length != 1 else ''}."
    else:
        heard = "I could not pick out a phone number."
    return StableError(
        ErrorCode.invalid_phone,
        f"{heard} I need a ten-digit US phone number; please say the digits one at a time.",
        details={"field": "phone", "digits_heard": length},
    )


def normalize_zip(value: str) -> str:
    """Normalize one ZIP to exactly five digits or reject it with a specific message."""
    text = str(value).strip()
    candidates = zip_candidates(text)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise StableError(
            ErrorCode.invalid_zip,
            "I heard more than one five-digit ZIP. Please say the one ZIP code one "
            "digit at a time.",
            details={"field": "zip", "candidates": len(candidates)},
        )
    raise _specific_zip_error(text)


def normalize_phone(value: str) -> str:
    """Normalize a US phone to ``+1`` followed by exactly ten digits."""
    text = str(value).strip()
    candidates: set[str] = set()
    for run in _digit_runs(text):
        if len(run) == 10 and _valid_us_phone(run):
            candidates.add(f"+1{run}")
        elif len(run) == 11 and run.startswith("1") and _valid_us_phone(run[1:]):
            candidates.add(f"+{run}")
    if len(candidates) == 1:
        return candidates.pop()
    if len(candidates) > 1:
        raise StableError(
            ErrorCode.invalid_phone,
            "I heard more than one phone number. Please say the ten digits one at a time.",
            details={"field": "phone", "candidates": len(candidates)},
        )
    raise _specific_phone_error(text)


def street_key(value: str) -> str:
    """Canonicalize a street line for equality checks across suffix abbreviations."""
    aliases = {
        "st": "street",
        "str": "street",
        "ave": "avenue",
        "av": "avenue",
        "blvd": "boulevard",
        "ct": "court",
        "dr": "drive",
        "rd": "road",
        "pkwy": "parkway",
        "ln": "lane",
        "pl": "place",
    }
    words = []
    for word in str(value).lower().replace(".", " ").replace(",", " ").split():
        words.append(aliases.get(word, word))
    return " ".join(words)


def find_street_address(text: str) -> str | None:
    """Return the first street-address line in an utterance, if there is one."""
    match = STREET_ADDRESS_RE.search(str(text))
    if match is None:
        return None
    return " ".join(match.group(1).split())


def find_city(text: str) -> str | None:
    """Return a city written before a ZIP or state, if the caller supplied one."""
    match = _CITY_RE.search(str(text))
    if match is None:
        return None
    return " ".join(match.group(1).split())


def validate_service_address(
    tenant: TenantConfig,
    *,
    line1: str,
    city: str,
    state: str,
    zip_code: str,
    expected_zip: str | None = None,
) -> Address:
    """Build a policy-safe address and reject out-of-area or inconsistent values."""
    normalized_zip = normalize_zip(zip_code)
    if expected_zip is not None and normalize_zip(expected_zip) != normalized_zip:
        raise StableError(
            ErrorCode.invalid_zip,
            "The address and ZIP do not match. Please say the ZIP again one digit at a time.",
            details={"field": "zip", "inconsistent": True},
        )
    street = " ".join(str(line1).split())
    town = " ".join(str(city).split())
    region = str(state).strip().upper()
    if not street or not town:
        raise StableError(
            ErrorCode.invalid_argument,
            "I need the full street address and city.",
            details={"field": "address"},
        )
    if "address on file" in street.lower() or street.lower() in {"address", "on file"}:
        raise StableError(
            ErrorCode.invalid_argument,
            "I need the actual street address, not a placeholder.",
            details={"field": "address"},
        )
    if len(region) != 2:
        raise StableError(
            ErrorCode.invalid_argument,
            "I need a two-letter state for the service address.",
            details={"field": "state"},
        )
    configured_city = tenant.service_area.city.strip()
    configured_state = tenant.service_area.state.strip().upper()
    if not tenant.has_zip(normalized_zip):
        raise StableError(
            ErrorCode.out_of_area,
            f"ZIP {normalized_zip} is outside our service area.",
            details={"field": "zip", "zip": normalized_zip},
        )
    if configured_city and town.lower() != configured_city.lower():
        raise StableError(
            ErrorCode.invalid_argument,
            f"That city does not match the ZIP service area ({configured_city}).",
            details={"field": "city", "inconsistent": True},
        )
    if configured_state and region != configured_state:
        raise StableError(
            ErrorCode.invalid_argument,
            f"That state does not match the service area ({configured_state}).",
            details={"field": "state", "inconsistent": True},
        )
    return Address(line1=street, city=town, state=region, zip=normalized_zip)


__all__ = [
    "DIGIT_WORDS",
    "digits_from_words",
    "find_city",
    "find_phone",
    "find_street_address",
    "find_zip",
    "normalize_phone",
    "normalize_zip",
    "street_key",
    "validate_service_address",
    "zip_candidates",
]

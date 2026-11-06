"""Spoken-value normalization for ZIPs and phone numbers (digits as words accepted)."""

from __future__ import annotations

import re

from forge_voice.errors import ErrorCode, StableError

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


def digits_from_words(value: str) -> str:
    return _WORD_RE.sub(lambda match: DIGIT_WORDS[match.group(1).lower()], value)


def normalize_zip(value: str) -> str:
    text = digits_from_words(str(value))
    digits = re.sub(r"\D", "", text)
    if len(digits) != 5:
        raise StableError(
            ErrorCode.invalid_zip,
            "I need a five-digit ZIP code. Please say it one digit at a time.",
        )
    return digits


def normalize_phone(value: str) -> str:
    text = digits_from_words(str(value))
    digits = re.sub(r"\D", "", text)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    raise StableError(
        ErrorCode.invalid_phone,
        "I need a ten-digit callback number. Please say it one digit at a time.",
    )

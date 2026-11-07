"""Spoken ZIP/phone capture, validation and the audio entity-reprompt guard."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from forge_voice.adapters import SQLiteAdapter
from forge_voice.errors import ErrorCode, StableError
from forge_voice.policy.entities import EntityGuard, RepromptError
from forge_voice.runtime.interpreter import extract_facts
from forge_voice.validation import (
    find_phone,
    find_zip,
    normalize_phone,
    normalize_zip,
    validate_service_address,
)

NOW = datetime(2026, 11, 6, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def _code(exc: pytest.ExceptionInfo[StableError]) -> ErrorCode:
    return exc.value.code


# --------------------------------------------------------------- normalization
def test_normalize_zip_accepts_digits_one_at_a_time() -> None:
    assert normalize_zip("nine five one two five") == "95125"


def test_normalize_zip_accepts_grouped_digits_and_spoken_oh() -> None:
    assert normalize_zip("9 5-1 2 5") == "95125"
    assert normalize_zip("ZIP code: nine four one oh seven") == "94107"


def test_normalize_zip_rejects_partial_asr_with_a_specific_reprompt() -> None:
    with pytest.raises(StableError) as exc:
        normalize_zip("9520 Faye")

    assert _code(exc) is ErrorCode.invalid_zip
    assert "five" in exc.value.message.lower()
    assert "digit" in exc.value.message.lower()


def test_normalize_zip_rejects_ambiguous_candidates() -> None:
    with pytest.raises(StableError) as exc:
        normalize_zip("94107 or maybe 95125")

    assert _code(exc) is ErrorCode.invalid_zip
    assert "one" in exc.value.message.lower()


def test_find_zip_reads_words_inside_a_full_address_utterance() -> None:
    text = "The address is 88 Meridian Way, San Jose, nine five one two five."

    assert find_zip(text) == "95125"
    assert find_zip("hear 9520 Faye") is None


def test_normalize_phone_accepts_spoken_grouped_digits() -> None:
    assert normalize_phone("five five five, one two three, four five six seven") == "+15551234567"
    assert normalize_phone("+1 (415) 555-0123") == "+14155550123"
    assert normalize_phone("415.555.0123") == "+14155550123"


def test_normalize_phone_rejects_partial_and_ambiguous_values() -> None:
    with pytest.raises(StableError) as partial:
        normalize_phone("four zero eight, five five five")
    assert _code(partial) is ErrorCode.invalid_phone
    assert "ten" in partial.value.message.lower()

    with pytest.raises(StableError) as ambiguous:
        normalize_phone("415-555-0123 or 408-555-0142")
    assert _code(ambiguous) is ErrorCode.invalid_phone


def test_find_phone_reads_spoken_digits_in_a_sentence() -> None:
    text = "My phone is four zero eight, five five five, zero one four two."

    assert find_phone(text) == "+14085550142"
    assert find_phone("no number here") is None


def test_extract_facts_reads_a_spoken_phone_the_same_way(harborlight, store) -> None:
    facts = extract_facts(
        harborlight,
        ["My phone is four zero eight, five five five, zero one four two."],
        store,
        NOW,
    )

    assert facts.phone == "+14085550142"


# ------------------------------------------------------------ address validation
def test_validate_service_address_accepts_a_served_zip(harborlight) -> None:
    address = validate_service_address(
        harborlight,
        line1="12 Alder Street",
        city="San Francisco",
        state="CA",
        zip_code="94107",
    )

    assert address.zip == "94107"
    assert address.line1 == "12 Alder Street"


def test_validate_service_address_rejects_out_of_area_and_inconsistent_zip(
    harborlight,
) -> None:
    with pytest.raises(StableError) as out_of_area:
        validate_service_address(
            harborlight,
            line1="300 East 42nd Street",
            city="New York",
            state="NY",
            zip_code="10001",
        )
    assert _code(out_of_area) is ErrorCode.out_of_area

    with pytest.raises(StableError) as inconsistent:
        validate_service_address(
            harborlight,
            line1="12 Alder Street",
            city="San Francisco",
            state="CA",
            zip_code="94107",
            expected_zip="95125",
        )
    assert _code(inconsistent) is ErrorCode.invalid_zip


# ------------------------------------------------------------------ entity guard
@pytest.fixture
def store(seed_data) -> SQLiteAdapter:
    database = SQLiteAdapter(":memory:")
    for data in seed_data.values():
        database.seed(data)
    return database


def test_guard_captures_spoken_zip_phone_and_address_from_mixed_turns(harborlight, store) -> None:
    guard = EntityGuard(harborlight, store)

    guard.observe("The address is 12 Alder Street, San Francisco, nine four one zero seven.")
    guard.observe("My phone is five five five, one two three, four five six seven.")

    assert guard.zip == "94107"
    assert guard.phone == "+15551234567"
    assert guard.line1 == "12 Alder Street"
    assert guard.city == "San Francisco"
    assert guard.missing() == []


def test_guard_uses_captured_zip_when_the_model_omits_it(harborlight, store) -> None:
    guard = EntityGuard(harborlight, store)
    guard.observe("ZIP nine five one two five.")

    assert guard.resolve_zip(None) == "95125"
    assert guard.resolve_zip("nine five one two five") == "95125"


def test_guard_reprompts_once_with_the_heard_digits_then_exhausts(harborlight, store) -> None:
    guard = EntityGuard(harborlight, store)

    with pytest.raises(RepromptError) as first:
        guard.resolve_zip("9520 Faye")
    assert first.value.code is ErrorCode.invalid_zip
    assert "five" in first.value.message.lower()
    assert first.value.details["attempt"] == 1

    with pytest.raises(RepromptError) as second:
        guard.resolve_zip("9520 Faye")
    assert second.value.details["attempt"] == 2

    with pytest.raises(RepromptError) as exhausted:
        guard.resolve_zip("9520 Faye")
    assert exhausted.value.details["exhausted"] is True
    assert "callback" in exhausted.value.message.lower() or "person" in (
        exhausted.value.message.lower()
    )


def test_guard_recovers_a_zip_from_the_tenants_known_street_address(summit, store) -> None:
    guard = EntityGuard(summit, store)
    guard.observe("The address is 88 Meridian Way, San Jose, 9520 Faye.")

    assert guard.line1 == "88 Meridian Way"
    assert guard.resolve_zip(None) == "95125"


def test_guard_does_not_override_a_valid_zip_with_a_known_street(harborlight, store) -> None:
    guard = EntityGuard(harborlight, store)
    guard.observe("12 Alder Street, San Francisco, 94110.")

    assert guard.resolve_zip(None) == "94110"


def test_normalize_zip_accepts_a_repeated_same_zip() -> None:
    assert normalize_zip("The ZIP is 94107. I said, 94107.") == "94107"


def test_normalize_phone_accepts_a_repeated_same_number() -> None:
    assert normalize_phone("555-123-4567, yes 555-123-4567") == "+15551234567"

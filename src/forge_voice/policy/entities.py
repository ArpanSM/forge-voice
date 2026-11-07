"""Deterministic ZIP/phone/address capture and capped reprompts.

The model may hear grouped digits, spoken digit words, or a partial value. This guard
keeps the last valid entities the caller actually said, fills gaps from the tenant's
known service addresses, and rejects ambiguous values instead of writing them.
"""

from __future__ import annotations

from collections.abc import Iterable

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.domain import Address
from forge_voice.errors import ErrorCode, StableError
from forge_voice.tenants.models import TenantConfig
from forge_voice.validation import (
    find_phone,
    find_street_address,
    find_zip,
    normalize_phone,
    normalize_zip,
    validate_service_address,
)

MAX_ENTITY_REPROMPTS = 2

_SUFFIX_ALIASES = {
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


class RepromptError(StableError):
    """A safe, specific request to repeat one entity, or the capped handoff message."""


def _street_key(value: str) -> str:
    words = []
    for word in str(value).lower().replace(".", " ").replace(",", " ").split():
        words.append(_SUFFIX_ALIASES.get(word, word))
    return " ".join(words)


class EntityGuard:
    """Capture caller-spoken ZIP, phone and address; never guess a missing value."""

    def __init__(
        self,
        tenant: TenantConfig,
        store: SQLiteAdapter | None = None,
        *,
        max_reprompts: int = MAX_ENTITY_REPROMPTS,
        caller_phone: str | None = None,
    ) -> None:
        self.tenant = tenant
        self.store = store
        self.max_reprompts = max(1, max_reprompts)
        self.zip: str | None = None
        self.phone: str | None = None
        self.line1: str | None = None
        self.city: str | None = None
        self.state = "CA"
        self._attempts: dict[str, int] = {}
        self._cities: set[str] = set()
        if caller_phone:
            try:
                self.phone = normalize_phone(caller_phone)
            except StableError:
                self.phone = None
        if store is not None:
            for customer in store.list_customers(tenant.tenant_id):
                self._cities.add(customer.address.city)
                if customer.address.state:
                    self.state = customer.address.state

    # ----------------------------------------------------------------- capture
    def observe(self, text: str) -> None:
        """Remember every valid entity in one caller turn; ignore absent fields."""
        if not text.strip():
            return
        zip_code = find_zip(text)
        if zip_code is not None:
            self.zip = zip_code
            self._attempts.pop("zip", None)
        phone = find_phone(text)
        if phone is not None:
            self.phone = phone
            self._attempts.pop("phone", None)
        street = find_street_address(text)
        if street is not None:
            self.line1 = street
        lowered = text.lower()
        for city in sorted(self._cities, key=len, reverse=True):
            if city.lower() in lowered:
                self.city = city
                break
        if self.city is None and self.zip is not None:
            self.city = self._known_city_for_zip(self.zip)
        if self.city is None and self.line1 is not None:
            self.city = self._known_city_for_street(self.line1)

    def missing(self) -> list[str]:
        missing: list[str] = []
        if self.zip is None:
            missing.append("zip")
        if self.phone is None:
            missing.append("phone")
        if self.line1 is None:
            missing.append("line1")
        if self.city is None:
            missing.append("city")
        return missing

    def remember_address(self, address: Address) -> None:
        self.zip = address.zip
        self.line1 = address.line1
        self.city = address.city
        self.state = address.state

    def best_address(self) -> Address | None:
        """Return the address the caller has given, without prompting or guessing."""
        zip_code = self.zip
        if zip_code is None and self.line1 is not None:
            zip_code = self._known_zip_for_street(self.line1)
        if zip_code is None or self.line1 is None:
            return None
        city = self.city or self._known_city_for_zip(zip_code)
        if city is None:
            return None
        try:
            return validate_service_address(
                self.tenant,
                line1=self.line1,
                city=city,
                state=self.state,
                zip_code=zip_code,
            )
        except StableError:
            return None

    # ------------------------------------------------------------- resolution
    def resolve_zip(self, value: str | None) -> str:
        """Return a validated ZIP from the argument, transcript or known address."""
        if value:
            try:
                self.zip = normalize_zip(value)
                self._attempts.pop("zip", None)
                return self.zip
            except StableError as exc:
                if self.zip is None:
                    self._raise_reprompt("zip", exc)
                return self.zip
        if self.zip is not None:
            return self.zip
        if self.line1 is not None:
            known = self._known_zip_for_street(self.line1)
            if known is not None:
                self.zip = known
                if self.city is None:
                    self.city = self._known_city_for_zip(known)
                return known
        self._raise_reprompt(
            "zip",
            StableError(
                ErrorCode.invalid_zip,
                "I still need the five-digit ZIP code. Please say the digits one at a time.",
                details={"field": "zip"},
            ),
        )
        raise AssertionError("reprompt did not raise")

    def resolve_phone(self, value: str | None) -> str:
        """Return a validated callback number from the argument or transcript."""
        if value:
            try:
                self.phone = normalize_phone(value)
                self._attempts.pop("phone", None)
                return self.phone
            except StableError as exc:
                if self.phone is None:
                    self._raise_reprompt("phone", exc)
                return self.phone
        if self.phone is not None:
            return self.phone
        self._raise_reprompt(
            "phone",
            StableError(
                ErrorCode.invalid_phone,
                "I still need the ten-digit callback number. Please say the digits one at a time.",
                details={"field": "phone"},
            ),
        )
        raise AssertionError("reprompt did not raise")

    def resolve_address(
        self,
        *,
        line1: str | None,
        city: str | None,
        state: str | None,
        zip_code: str | None,
        expected_zip: str | None = None,
    ) -> Address:
        """Build the address from arguments and captured turns, then validate it."""
        if line1 and self.line1 is None:
            self.line1 = line1
        resolved_line1 = line1 or self.line1
        resolved_city = city or self.city
        resolved_zip = self.resolve_zip(zip_code)
        if resolved_city is None:
            resolved_city = self._known_city_for_zip(resolved_zip)
        if resolved_line1 is None or resolved_city is None:
            self._raise_reprompt(
                "address",
                StableError(
                    ErrorCode.invalid_argument,
                    "I need the street address and city for the service visit.",
                    details={"field": "address"},
                ),
            )
        resolved_state = (state or self.state or "CA").strip().upper()
        self.line1 = resolved_line1
        self.city = resolved_city
        self.state = resolved_state
        return validate_service_address(
            self.tenant,
            line1=resolved_line1,
            city=resolved_city,
            state=resolved_state,
            zip_code=resolved_zip,
            expected_zip=expected_zip,
        )

    # ---------------------------------------------------------------- attempts
    def invalid_attempt(self, text: str) -> str | None:
        """Name the entity whose spoken attempt was invalid, without capturing it."""
        raw = text.lower()
        runs = [run for run in _number_runs(text) if run]
        if self.zip is None and (
            "zip" in raw
            or find_street_address(text) is not None
            or (any(word in raw for word in ("address", "code")) and runs)
        ):
            return "zip"
        if self.phone is None and (
            any(word in raw for word in ("phone", "number", "callback", "call me back"))
            or any(7 <= len(run) <= 11 for run in runs)
        ):
            return "phone"
        if self.phone is None and any(
            phrase in raw for phrase in ("no phone", "don't have a phone", "without a phone")
        ):
            return "phone"
        return None

    def reprompt_issue(self, text: str, *, advance: bool = True) -> RepromptError | None:
        """Return the capped reprompt for an invalid spoken attempt, when there is one."""
        field = self.invalid_attempt(text)
        if field is None:
            return None
        if not advance and self._attempts.get(field, 0) > 0:
            attempt = self._attempts[field]
            return RepromptError(
                ErrorCode.invalid_zip if field == "zip" else ErrorCode.invalid_phone,
                self._repeat_message(field, attempt),
                details={
                    "field": field,
                    "attempt": attempt,
                    "repeated": True,
                    "exhausted": attempt > self.max_reprompts,
                },
            )
        try:
            if field == "zip":
                normalize_zip(text)
            elif field == "phone":
                normalize_phone(text)
        except StableError as exc:
            specific = exc
        else:
            specific = StableError(
                ErrorCode.invalid_zip if field == "zip" else ErrorCode.invalid_phone,
                "I could not capture that value. Please say the digits one at a time.",
                details={"field": field},
            )
        if field == "zip" and not any(3 <= len(run) <= 6 for run in _number_runs(text)):
            specific = StableError(
                ErrorCode.invalid_zip,
                "I still need the five-digit ZIP code. Please say the digits one at a time.",
                details={"field": "zip"},
            )
        try:
            self._raise_reprompt(field, specific)
        except RepromptError as exc:
            return exc
        return None

    def _repeat_message(self, field: str, attempt: int) -> str:
        if attempt > self.max_reprompts:
            return self._handoff_message(field)
        label = {
            "zip": "five-digit ZIP",
            "phone": "ten-digit callback number",
            "address": "street address",
        }.get(field, "contact detail")
        return f"I still need the {label}. Please say the digits one at a time."

    def _raise_reprompt(self, field: str, error: StableError) -> None:
        attempt = self._attempts.get(field, 0) + 1
        self._attempts[field] = attempt
        details = dict(error.details)
        details.update({"field": field, "attempt": attempt})
        if attempt > self.max_reprompts:
            details["exhausted"] = True
            raise RepromptError(
                error.code,
                self._handoff_message(field),
                details=details,
            )
        raise RepromptError(error.code, error.message, details=details)

    def _handoff_message(self, field: str) -> str:
        label = {
            "zip": "five-digit ZIP",
            "phone": "ten-digit callback number",
            "address": "street address",
        }.get(field, "contact detail")
        return (
            f"I couldn't capture a valid {label} after {self.max_reprompts} tries. I "
            "won't guess or write it. I can pass what we have to a person or queue a "
            "callback."
        )

    # ------------------------------------------------------------ known records
    def _known_zip_for_street(self, line1: str) -> str | None:
        if self.store is None:
            return None
        key = _street_key(line1)
        zips = {
            customer.address.zip
            for customer in self.store.list_customers(self.tenant.tenant_id)
            if _street_key(customer.address.line1) == key
        }
        return zips.pop() if len(zips) == 1 else None

    def _known_city_for_street(self, line1: str) -> str | None:
        if self.store is None:
            return None
        key = _street_key(line1)
        cities = {
            customer.address.city
            for customer in self.store.list_customers(self.tenant.tenant_id)
            if _street_key(customer.address.line1) == key
        }
        return cities.pop() if len(cities) == 1 else None

    def _known_city_for_zip(self, zip_code: str) -> str | None:
        if self.store is None:
            return None
        cities = {
            customer.address.city
            for customer in self.store.list_customers(self.tenant.tenant_id)
            if customer.address.zip == zip_code
        }
        return cities.pop() if len(cities) == 1 else None


def _number_runs(text: str) -> Iterable[str]:
    from forge_voice.validation import _digit_runs

    return _digit_runs(text)


__all__ = ["MAX_ENTITY_REPROMPTS", "EntityGuard", "RepromptError"]

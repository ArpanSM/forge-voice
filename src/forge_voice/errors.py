"""Stable error codes shared by the tool envelope and the booking service."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    invalid_argument = "invalid_argument"
    invalid_zip = "invalid_zip"
    invalid_phone = "invalid_phone"
    not_found = "not_found"
    out_of_area = "out_of_area"
    service_not_offered = "service_not_offered"
    no_availability = "no_availability"
    slot_unavailable = "slot_unavailable"
    slot_expired = "slot_expired"
    explicit_confirmation_required = "explicit_confirmation_required"
    confirmation_required = "confirmation_required"
    confirmation_expired = "confirmation_expired"
    ownership_mismatch = "ownership_mismatch"
    tenant_mismatch = "tenant_mismatch"
    cutoff_passed = "cutoff_passed"
    already_cancelled = "already_cancelled"
    already_completed = "already_completed"
    idempotency_conflict = "idempotency_conflict"
    dependency_unavailable = "dependency_unavailable"
    timeout = "timeout"
    rate_limited = "rate_limited"
    internal_error = "internal_error"
    invalid_category = "invalid_category"
    transfer_unavailable = "transfer_unavailable"
    no_target = "no_target"


class StableError(Exception):
    """A deterministic error with a stable code and safe, synthetic message."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}

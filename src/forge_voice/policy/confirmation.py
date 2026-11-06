"""Policy-issued, single-use confirmation tokens and their server-side store.

The model never receives an API to mint a token. A token is created only after the policy has
recorded a read-back and an explicit yes, and it is bound to the tenant, call, intent, target
and canonical payload hash. When a SQLite adapter is supplied the token rows are durable and
consumption is one atomic UPDATE.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from pydantic import Field

from forge_voice.clock import Clock
from forge_voice.domain import TokenRecord
from forge_voice.models import StrictModel
from forge_voice.security import random_token


class TokenBackend(Protocol):
    def insert_token(self, record: TokenRecord) -> TokenRecord: ...
    def get_token(self, tenant_id: str, token: str) -> TokenRecord | None: ...
    def consume_token(self, tenant_id: str, token: str, at: datetime) -> bool: ...


class TokenStatus(StrEnum):
    valid = "valid"
    unknown = "unknown"
    used = "used"
    expired = "expired"
    binding_mismatch = "binding_mismatch"


def payload_digest(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TokenBinding(StrictModel):
    tenant_id: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    target: str = Field(min_length=1)
    payload_hash: str = Field(min_length=64, max_length=64)


class ConfirmationToken(StrictModel):
    token: str
    binding: TokenBinding
    issued_at: datetime
    expires_at: datetime


class TokenCheck(StrictModel):
    status: TokenStatus
    token: ConfirmationToken | None = None


class ConfirmationTokenStore:
    """Token registry; SQLite-backed when a database is supplied."""

    def __init__(
        self,
        clock: Clock,
        backend: TokenBackend | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self._clock = clock
        self._backend = backend
        self._token_factory = token_factory or random_token
        self._records: dict[str, ConfirmationToken] = {}
        self._used: set[str] = set()
        self._counter = 0

    def issue(
        self,
        *,
        tenant_id: str,
        call_id: str,
        intent: str,
        target: str,
        payload: Mapping[str, Any],
        ttl_seconds: int,
    ) -> ConfirmationToken:
        self._counter += 1
        issued_at = self._clock.now
        binding = TokenBinding(
            tenant_id=tenant_id,
            call_id=call_id,
            intent=intent,
            target=target,
            payload_hash=payload_digest(payload),
        )
        material = "|".join(
            [
                binding.tenant_id,
                binding.call_id,
                binding.intent,
                binding.target,
                binding.payload_hash,
                issued_at.isoformat(),
                str(self._counter),
                self._token_factory(),
            ]
        )
        token = "ct_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        record = ConfirmationToken(
            token=token,
            binding=binding,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=ttl_seconds),
        )
        if self._backend is not None:
            self._backend.insert_token(
                TokenRecord(
                    token=token,
                    tenant_id=tenant_id,
                    call_id=call_id,
                    intent=intent,
                    target=target,
                    payload_hash=binding.payload_hash,
                    issued_at=record.issued_at,
                    expires_at=record.expires_at,
                )
            )
        else:
            self._records[token] = record
        return record

    def validate(
        self,
        token: str,
        binding: TokenBinding,
        *,
        at: datetime | None = None,
    ) -> TokenCheck:
        record = self._lookup(binding.tenant_id, token)
        if record is None:
            return TokenCheck(status=TokenStatus.unknown)
        if record.binding != binding:
            return TokenCheck(status=TokenStatus.binding_mismatch, token=record)
        if self._is_used(token, record, at=at):
            return TokenCheck(status=TokenStatus.used, token=record)
        if (at or self._clock.now) >= record.expires_at:
            return TokenCheck(status=TokenStatus.expired, token=record)
        return TokenCheck(status=TokenStatus.valid, token=record)

    def consume(self, token: str, binding: TokenBinding) -> TokenCheck:
        check = self.validate(token, binding)
        if check.status is TokenStatus.valid:
            if self._backend is not None and not self._backend.consume_token(
                binding.tenant_id, token, self._clock.now
            ):
                return TokenCheck(status=TokenStatus.used, token=check.token)
            self._used.add(token)
            return TokenCheck(status=TokenStatus.valid, token=check.token)
        return check

    def consume_in_transaction(self, token: str, binding: TokenBinding) -> TokenCheck:
        """Consume on the caller's open transaction; a failed UPDATE rolls the writes back."""
        check = self.validate(token, binding)
        if check.status is not TokenStatus.valid:
            return check
        if self._backend is not None:
            consumed = self._backend.consume_token(binding.tenant_id, token, self._clock.now)
            return TokenCheck(
                status=TokenStatus.valid if consumed else TokenStatus.used,
                token=check.token,
            )
        self._used.add(token)
        return TokenCheck(status=TokenStatus.valid, token=check.token)

    def _lookup(self, tenant_id: str, token: str) -> ConfirmationToken | None:
        if self._backend is not None:
            row = self._backend.get_token(tenant_id, token)
            if row is None:
                return None
            return ConfirmationToken(
                token=row.token,
                binding=TokenBinding(
                    tenant_id=row.tenant_id,
                    call_id=row.call_id,
                    intent=row.intent,
                    target=row.target,
                    payload_hash=row.payload_hash,
                ),
                issued_at=row.issued_at,
                expires_at=row.expires_at,
            )
        return self._records.get(token)

    def _is_used(
        self, token: str, record: ConfirmationToken, *, at: datetime | None = None
    ) -> bool:
        if self._backend is not None:
            row = self._backend.get_token(record.binding.tenant_id, token)
            return row is not None and row.used_at is not None
        return token in self._used

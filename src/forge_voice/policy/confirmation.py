"""Policy-issued, single-use confirmation tokens and their server-side store.

The model never receives an API to mint a token. A token is created only after the policy has
recorded a read-back and an explicit yes, and it is bound to the tenant, call, intent, target
and canonical payload hash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import Field

from forge_voice.clock import Clock
from forge_voice.models import StrictModel


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
    """In-memory one-use token registry; deterministic for a fixed issue sequence."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
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
            ]
        )
        token = "ct_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
        record = ConfirmationToken(
            token=token,
            binding=binding,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=ttl_seconds),
        )
        self._records[token] = record
        return record

    def validate(
        self,
        token: str,
        binding: TokenBinding,
        *,
        at: datetime | None = None,
    ) -> TokenCheck:
        record = self._records.get(token)
        if record is None:
            return TokenCheck(status=TokenStatus.unknown)
        if record.binding != binding:
            return TokenCheck(status=TokenStatus.binding_mismatch, token=record)
        if token in self._used:
            return TokenCheck(status=TokenStatus.used, token=record)
        if (at or self._clock.now) >= record.expires_at:
            return TokenCheck(status=TokenStatus.expired, token=record)
        return TokenCheck(status=TokenStatus.valid, token=record)

    def consume(self, token: str, binding: TokenBinding) -> TokenCheck:
        check = self.validate(token, binding)
        if check.status is TokenStatus.valid:
            self._used.add(token)
        return check

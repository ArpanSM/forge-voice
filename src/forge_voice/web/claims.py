"""Server-signed tenant claims bound to one short-lived browser call.

The LiveKit join token carries this claim as participant metadata. The agent trusts
only a valid HMAC and never a room name or query parameter supplied by the browser.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field

from forge_voice.models import StrictModel

DEFAULT_TTL_SECONDS = 120
MAX_CLOCK_SKEW_SECONDS = 30


class ClaimError(ValueError):
    """A tenant claim is malformed, tampered with, expired or for the wrong tenant."""


class TenantClaim(StrictModel):
    version: Literal[1] = 1
    tenant: str = Field(min_length=1)
    call_id: str = Field(min_length=1)
    room: str = Field(min_length=1)
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(min_length=8)


class SignedTenantClaim(StrictModel):
    token: str
    claim: TenantClaim


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError) as exc:
        raise ClaimError("tenant claim is not valid base64url") from exc


def _payload_bytes(claim: TenantClaim) -> bytes:
    return json.dumps(
        claim.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class TenantClaimSigner:
    """Issue and verify the signed tenant identity used by the audio path."""

    def __init__(self, secret: str, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        if not secret:
            raise ClaimError("a signing secret is required")
        if ttl_seconds <= 0:
            raise ClaimError("claim ttl must be positive")
        self._secret = secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds

    def issue(
        self,
        tenant: str,
        *,
        call_id: str,
        room: str,
        now: datetime | None = None,
    ) -> SignedTenantClaim:
        issued = (now or datetime.now(UTC)).astimezone(UTC)
        claim = TenantClaim(
            tenant=tenant,
            call_id=call_id,
            room=room,
            issued_at=issued,
            expires_at=issued + timedelta(seconds=self.ttl_seconds),
            nonce=secrets.token_hex(8),
        )
        payload = _payload_bytes(claim)
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return SignedTenantClaim(
            token=f"{_b64encode(payload)}.{_b64encode(signature)}",
            claim=claim,
        )

    def verify(
        self,
        token: str,
        *,
        now: datetime | None = None,
        expected_tenant: str | None = None,
    ) -> TenantClaim:
        try:
            payload_part, signature_part = token.split(".")
        except ValueError as exc:
            raise ClaimError("tenant claim is malformed") from exc
        payload = _b64decode(payload_part)
        signature = _b64decode(signature_part)
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ClaimError("tenant claim signature is invalid")
        try:
            raw = json.loads(payload.decode("utf-8"))
            claim = TenantClaim.model_validate(raw)
        except (ValueError, TypeError) as exc:
            raise ClaimError("tenant claim payload is invalid") from exc
        current = (now or datetime.now(UTC)).astimezone(UTC)
        if claim.expires_at <= claim.issued_at:
            raise ClaimError("tenant claim expiry is not after issue time")
        if claim.issued_at > current + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
            raise ClaimError("tenant claim was issued in the future")
        if current >= claim.expires_at:
            raise ClaimError("tenant claim expired")
        if expected_tenant is not None and claim.tenant != expected_tenant:
            raise ClaimError("tenant claim is for a different tenant")
        return claim

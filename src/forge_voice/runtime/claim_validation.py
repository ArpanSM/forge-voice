"""Agent-side validation of the signed tenant claim against the LiveKit room.

Participant metadata is caller-mutable, so a valid signature alone is not enough:
the claim must also be bound to the room the worker actually joined and to a
configured tenant.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime

from forge_voice.tenants import TenantConfig
from forge_voice.web.claims import DEFAULT_TTL_SECONDS, ClaimError, TenantClaim, TenantClaimSigner

ROOM_PREFIX = "forge-voice"


def parse_participant_claim(
    metadata: str, secret: str, *, now: datetime | None = None
) -> TenantClaim:
    """Parse and verify the signed claim in participant metadata.

    Malformed JSON, arrays/scalars and non-string fields all raise ClaimError;
    callers never see an AttributeError or TypeError from untrusted metadata.
    """
    if not isinstance(metadata, str):
        raise ClaimError("participant metadata must be a JSON string")
    try:
        payload = json.loads(metadata or "{}")
    except json.JSONDecodeError as exc:
        raise ClaimError("participant metadata is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ClaimError("participant metadata must be a JSON object")
    token = payload.get("tenant_claim")
    tenant = payload.get("tenant")
    if not isinstance(token, str) or not token:
        raise ClaimError("participant metadata has no signed tenant claim")
    if not isinstance(tenant, str) or not tenant:
        raise ClaimError("participant metadata has no tenant")
    verify_kwargs = {} if now is None else {"now": now}
    return TenantClaimSigner(secret, ttl_seconds=DEFAULT_TTL_SECONDS).verify(
        token, expected_tenant=tenant, **verify_kwargs
    )


def validate_claim_for_room(
    claim: TenantClaim,
    room_name: str,
    tenants: Mapping[str, TenantConfig],
) -> TenantConfig:
    """Reject a claim that is not bound to this exact room and a known tenant."""
    if claim.room != room_name:
        raise ClaimError("tenant claim room does not match the LiveKit room")
    expected_room = f"{ROOM_PREFIX}-{claim.tenant}-{claim.call_id}"
    if room_name != expected_room:
        raise ClaimError("tenant claim is not bound to this room name")
    tenant = tenants.get(claim.tenant)
    if tenant is None:
        raise ClaimError(f"tenant claim names unknown tenant {claim.tenant!r}")
    return tenant


def validate_entrypoint(
    metadata: str,
    room_name: str,
    secret: str,
    tenants: Mapping[str, TenantConfig],
    *,
    now: datetime | None = None,
) -> tuple[TenantConfig, TenantClaim]:
    """The entrypoint contract: verify the claim, then bind it to this room.

    Returns the configured tenant and verified claim; every failure raises ClaimError
    before any policy session is created.
    """
    claim = parse_participant_claim(metadata, secret, now=now)
    tenant = validate_claim_for_room(claim, room_name, tenants)
    return tenant, claim


__all__ = ["parse_participant_claim", "validate_claim_for_room", "validate_entrypoint"]

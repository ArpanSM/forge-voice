"""Entrypoint claim checks bind metadata to the room and a configured tenant."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from forge_voice.runtime.claim_validation import (
    parse_participant_claim,
    validate_claim_for_room,
    validate_entrypoint,
)
from forge_voice.tenants import load_all_tenants
from forge_voice.web.claims import DEFAULT_TTL_SECONDS, ClaimError, TenantClaimSigner

SECRET = "local-test-secret-that-is-long-enough-for-hmac"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
ROOT_TENANTS = __import__("pathlib").Path(__file__).resolve().parents[1] / "tenants"


def signed_claim(tenant: str = "harborlight", call_id: str = "call_1"):
    signer = TenantClaimSigner(SECRET, ttl_seconds=DEFAULT_TTL_SECONDS)
    return signer.issue(
        tenant,
        call_id=call_id,
        room=f"forge-voice-{tenant}-{call_id}",
        now=NOW,
    ).claim


def metadata_for(claim) -> str:
    signer = TenantClaimSigner(SECRET, ttl_seconds=DEFAULT_TTL_SECONDS)
    signed = signer.issue(
        claim.tenant,
        call_id=claim.call_id,
        room=claim.room,
        now=NOW,
    )
    return json.dumps({"tenant": claim.tenant, "tenant_claim": signed.token})


def test_valid_claim_is_bound_to_its_room_and_tenant() -> None:
    claim = signed_claim()
    tenant = validate_claim_for_room(
        claim,
        claim.room,
        load_all_tenants(ROOT_TENANTS),
    )

    assert tenant.tenant_id == "harborlight"


def test_claim_from_another_room_is_rejected() -> None:
    claim = signed_claim("harborlight", "call_1")

    with pytest.raises(ClaimError, match="room"):
        validate_claim_for_room(
            claim,
            "forge-voice-summit-call_2",
            load_all_tenants(ROOT_TENANTS),
        )


def test_unknown_tenant_is_rejected() -> None:
    claim = signed_claim("not-a-tenant")

    with pytest.raises(ClaimError, match="unknown tenant"):
        validate_claim_for_room(claim, claim.room, load_all_tenants(ROOT_TENANTS))


@pytest.mark.parametrize(
    "metadata",
    [
        "not json",
        "[]",
        '"string"',
        '{"tenant": "harborlight"}',
        '{"tenant_claim": 3, "tenant": "harborlight"}',
        '{"tenant_claim": "x", "tenant": 3}',
    ],
)
def test_malformed_participant_metadata_raises_claim_error(metadata: str) -> None:
    with pytest.raises(ClaimError):
        parse_participant_claim(metadata, SECRET)


def test_tampered_tenant_metadata_is_rejected() -> None:
    claim = signed_claim()
    metadata = metadata_for(claim).replace("harborlight", "summit")

    with pytest.raises(ClaimError, match="different tenant"):
        parse_participant_claim(metadata, SECRET, now=NOW)


def test_claim_signer_rejects_future_issued_at() -> None:
    signer = TenantClaimSigner(SECRET, ttl_seconds=DEFAULT_TTL_SECONDS)
    future = signer.issue(
        "harborlight",
        call_id="call_1",
        room="forge-voice-harborlight-call_1",
        now=NOW + timedelta(minutes=5),
    )

    with pytest.raises(ClaimError, match="future"):
        signer.verify(future.token, now=NOW)


def test_claim_signer_uses_the_shared_ttl() -> None:
    signer = TenantClaimSigner(SECRET)
    issued = signer.issue(
        "harborlight",
        call_id="call_1",
        room="forge-voice-harborlight-call_1",
        now=NOW,
    )

    assert issued.claim.expires_at - issued.claim.issued_at == timedelta(
        seconds=DEFAULT_TTL_SECONDS
    )


def test_entrypoint_accepts_a_valid_signed_room_claim() -> None:
    claim = signed_claim()
    tenant, verified = validate_entrypoint(
        metadata_for(claim),
        claim.room,
        SECRET,
        load_all_tenants(ROOT_TENANTS),
        now=NOW,
    )

    assert tenant.tenant_id == claim.tenant
    assert verified.room == claim.room


def test_entrypoint_rejects_a_claim_for_another_room() -> None:
    claim = signed_claim("harborlight", "call_1")

    with pytest.raises(ClaimError, match="room"):
        validate_entrypoint(
            metadata_for(claim),
            "forge-voice-summit-call_2",
            SECRET,
            load_all_tenants(ROOT_TENANTS),
            now=NOW,
        )


def test_entrypoint_rejects_an_unknown_tenant() -> None:
    claim = signed_claim("not-a-tenant")

    with pytest.raises(ClaimError, match="unknown tenant"):
        validate_entrypoint(
            metadata_for(claim),
            claim.room,
            SECRET,
            load_all_tenants(ROOT_TENANTS),
            now=NOW,
        )


def test_entrypoint_rejects_malformed_metadata() -> None:
    with pytest.raises(ClaimError):
        validate_entrypoint(
            "[]",
            "forge-voice-harborlight-call_1",
            SECRET,
            load_all_tenants(ROOT_TENANTS),
            now=NOW,
        )

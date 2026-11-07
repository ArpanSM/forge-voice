"""Signed tenant claims are the only source of tenant identity on the audio path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from forge_voice.web.claims import ClaimError, TenantClaim, TenantClaimSigner

SECRET = "local-test-secret-that-is-long-enough-for-hmac"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def signer(ttl: int = 120) -> TenantClaimSigner:
    return TenantClaimSigner(SECRET, ttl_seconds=ttl)


def issue(signer_: TenantClaimSigner):
    return signer_.issue(
        "harborlight",
        call_id="call_0001",
        room="forge-voice-harborlight-call_0001",
        now=NOW,
    )


def test_tenant_claim_round_trips_with_a_short_expiry() -> None:
    signed = issue(signer())

    claim = signer().verify(signed.token, now=NOW + timedelta(seconds=30))

    assert claim.tenant == "harborlight"
    assert claim.call_id == "call_0001"
    assert claim.room == "forge-voice-harborlight-call_0001"
    assert claim.issued_at == NOW
    assert claim.expires_at == NOW + timedelta(seconds=120)
    assert claim.expires_at - claim.issued_at == timedelta(seconds=120)


def test_tenant_claim_rejects_a_tampered_tenant() -> None:
    signed = issue(signer())

    payload, signature = signed.token.split(".")
    tampered = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB") + "." + signature

    with pytest.raises(ClaimError):
        signer().verify(tampered, now=NOW)


def test_tenant_claim_rejects_a_different_signing_secret() -> None:
    signed = issue(signer())

    with pytest.raises(ClaimError):
        TenantClaimSigner("another-secret-that-is-also-long-enough", ttl_seconds=120).verify(
            signed.token, now=NOW
        )


def test_tenant_claim_expires_after_its_ttl() -> None:
    signed = issue(signer(ttl=30))

    with pytest.raises(ClaimError, match="expired"):
        signer().verify(signed.token, now=NOW + timedelta(seconds=31))


def test_tenant_claim_rejects_an_unknown_tenant_when_expected_tenant_is_checked() -> None:
    signed = issue(signer())

    with pytest.raises(ClaimError, match="tenant"):
        signer().verify(signed.token, now=NOW, expected_tenant="summit")


def test_claim_schema_rejects_an_unknown_version_or_short_nonce() -> None:
    base = {
        "tenant": "harborlight",
        "call_id": "call_1",
        "room": "forge-voice-harborlight-call_1",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(seconds=120),
        "nonce": "12345678",
    }

    with pytest.raises(ValidationError):
        TenantClaim.model_validate({**base, "version": 2})
    with pytest.raises(ValidationError):
        TenantClaim.model_validate({**base, "nonce": "short"})


def test_claim_signer_rejects_an_expiry_before_issue_time() -> None:
    claim = TenantClaim(
        tenant="harborlight",
        call_id="call_1",
        room="forge-voice-harborlight-call_1",
        issued_at=NOW,
        expires_at=NOW - timedelta(seconds=1),
        nonce="12345678",
    )
    token = signer().sign(claim)

    with pytest.raises(ClaimError, match="expiry"):
        signer().verify(token, now=NOW)


def test_claim_verifier_rejects_a_ttl_longer_than_the_cap() -> None:
    claim = TenantClaim(
        tenant="harborlight",
        call_id="call_1",
        room="forge-voice-harborlight-call_1",
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=121),
        nonce="12345678",
    )
    token = signer().sign(claim)

    with pytest.raises(ClaimError, match="ttl"):
        signer().verify(token, now=NOW)

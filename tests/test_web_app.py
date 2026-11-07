"""The local browser page and token endpoint are the only browser entry points."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from forge_voice.tenants import load_all_tenants
from forge_voice.web.app import MintedToken, create_app
from forge_voice.web.claims import TenantClaimSigner

SECRET = "local-test-secret-that-is-long-enough-for-hmac"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
ROOT_TENANTS = __import__("pathlib").Path(__file__).resolve().parents[1] / "tenants"


class RecordingMinter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def mint(
        self,
        *,
        room: str,
        identity: str,
        metadata: str,
        ttl_seconds: int,
    ) -> MintedToken:
        self.calls.append(
            {
                "room": room,
                "identity": identity,
                "metadata": metadata,
                "ttl_seconds": ttl_seconds,
            }
        )
        return MintedToken(url="ws://localhost:7880", token="local-jwt")


@pytest.fixture
def minter() -> RecordingMinter:
    return RecordingMinter()


@pytest.fixture
def client(minter: RecordingMinter) -> TestClient:
    app = create_app(
        tenants=load_all_tenants(ROOT_TENANTS),
        minter=minter,
        claim_signer=TenantClaimSigner(SECRET, ttl_seconds=120),
        livekit_url="ws://localhost:7880",
        now=lambda: NOW,
    )
    return TestClient(app)


def test_health_reports_tenants_and_the_local_livekit_url(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["tenants"] == ["harborlight", "summit"]
    assert body["livekit_url"] == "ws://localhost:7880"
    assert "secret" not in json.dumps(body).lower()


def test_browser_page_loads_the_local_client_and_discloses_the_ai(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'src="/static/livekit-client.umd.min.js"' in html
    assert "cdn.jsdelivr.net" not in html
    assert "Harborlight Home Services" in html
    assert "Summit Heating" in html
    assert "AI" in html and "recorded" in html.lower()
    assert "Start call" in html
    assert "tenant" in html.lower()


def test_token_endpoint_issues_a_signed_tenant_claim(
    client: TestClient, minter: RecordingMinter
) -> None:
    response = client.post("/token", json={"tenant": "harborlight", "identity": "browser-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["tenant"] == "harborlight"
    assert body["url"] == "ws://localhost:7880"
    assert body["token"] == "local-jwt"
    assert body["room"].startswith("forge-voice-harborlight-")
    assert body["ttl_seconds"] == 120

    assert len(minter.calls) == 1
    call = minter.calls[0]
    assert call["room"] == body["room"]
    assert call["ttl_seconds"] == 120
    metadata = json.loads(str(call["metadata"]))
    claim = TenantClaimSigner(SECRET, ttl_seconds=120).verify(
        metadata["tenant_claim"], now=NOW, expected_tenant="harborlight"
    )
    assert claim.room == body["room"]
    assert claim.call_id in body["room"]


def test_token_endpoint_fails_closed_for_an_unknown_tenant(
    client: TestClient, minter: RecordingMinter
) -> None:
    response = client.post("/token", json={"tenant": "not-a-tenant"})

    assert response.status_code == 404
    assert response.json()["error"] == "unknown_tenant"
    assert minter.calls == []


def test_token_endpoint_rejects_a_get_query_parameter(client: TestClient) -> None:
    response = client.get("/token", params={"tenant": "harborlight"})

    assert response.status_code == 405


def test_token_endpoint_fails_closed_without_local_livekit_configuration() -> None:
    app = create_app(
        tenants=load_all_tenants(ROOT_TENANTS),
        minter=None,
        claim_signer=TenantClaimSigner(SECRET, ttl_seconds=120),
        livekit_url="",
        now=lambda: NOW,
    )
    response = TestClient(app).post("/token", json={"tenant": "harborlight"})

    assert response.status_code == 503
    assert response.json()["error"] == "livekit_not_configured"


def test_packaged_livekit_browser_client_is_served_locally(client: TestClient) -> None:
    response = client.get("/static/livekit-client.umd.min.js")

    assert response.status_code == 200
    assert len(response.content) > 100_000
    assert b"LivekitClient" in response.content

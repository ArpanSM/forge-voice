"""Dashboard, call detail and metrics export route behaviour."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from forge_voice.monitoring.service import MonitoringService
from forge_voice.policy.state import CallIntent, CallOutcome, TransferStatus
from forge_voice.tenants import load_all_tenants
from forge_voice.web.app import create_app
from support_monitoring import latency, make_call, tool

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def calls():
    return [
        make_call(
            "call_hl",
            outcome=CallOutcome.booked,
            booking_id="bk_hl_1",
            started_at=NOW - timedelta(days=1),
            turn_latencies=[latency(2000), latency(3000)],
            tool_events=[tool("get_availability"), tool("book_appointment")],
            qa_flags=["recording_opt_out"],
            cost_usd=0.0,
        ),
        make_call(
            "call_summit",
            tenant_id="summit",
            intent=CallIntent.human,
            outcome=CallOutcome.transferred,
            transfer_status=TransferStatus.connected,
            started_at=NOW - timedelta(days=3),
            turn_latencies=[latency(4000)],
            tool_events=[tool("transfer_to_human")],
            recording_opt_out=True,
        ),
    ]


@pytest.fixture
def service(tmp_path, calls) -> MonitoringService:
    service = MonitoringService(
        data_dir=tmp_path,
        root=ROOT,
        seed=False,
        now=lambda: NOW,
        profile="local",
    )
    service.replace_calls(calls)
    return service


@pytest.fixture
def client(service) -> TestClient:
    app = create_app(
        tenants=load_all_tenants(ROOT / "tenants"),
        minter=None,
        claim_signer=None,
        livekit_url="",
        monitoring=service,
    )
    return TestClient(app)


def test_dashboard_renders_cards_the_alert_banner_and_the_call_table(
    client: TestClient, service: MonitoringService
) -> None:
    response = client.get("/dashboard")

    assert response.status_code == 200
    html = response.text
    assert "Forge Voice monitoring" in html
    assert "Total calls" in html
    assert "Containment" in html
    assert "Transfer rate" in html
    assert "Booking rate" in html
    assert "Slot error rate" in html
    assert "Tool error rate" in html
    assert "Emergency triage" in html
    assert "No active alerts" in html
    assert "call_hl" in html
    assert "call_summit" in html
    assert "Harborlight Home Services" in html
    assert "Summit Heating &amp; Air" in html
    assert "+14155550101" in html
    assert "htmx.min.js" in html
    assert not (service.data_dir / "monitoring" / "alerts.jsonl").exists()


def test_dashboard_filters_by_tenant_date_and_outcome(client: TestClient) -> None:
    tenant = client.get("/dashboard", params={"tenant": "summit"})
    assert "call_summit" in tenant.text
    assert "call_hl" not in tenant.text

    outcome = client.get("/dashboard", params={"outcome": "booked"})
    assert "call_hl" in outcome.text
    assert "call_summit" not in outcome.text

    recent = client.get(
        "/dashboard",
        params={"from": "2026-11-05", "to": "2026-11-07"},
    )
    assert "call_hl" in recent.text
    assert "call_summit" not in recent.text

    invalid = client.get("/dashboard", params={"outcome": "not-an-outcome"})
    assert invalid.status_code == 400


def test_call_detail_shows_transcript_tools_latency_and_outcome(client: TestClient) -> None:
    response = client.get("/calls/call_hl")

    assert response.status_code == 200
    html = response.text
    assert "call_hl" in html
    assert "I need a drain cleaning." in html
    assert "book_appointment" in html
    assert "STT / endpointing" in html
    assert "LLM TTFT" in html
    assert "TTS TTFB" in html
    assert "bk_hl_1" in html
    assert "Booked" in html
    assert "$0.0000" in html
    assert "+14155550101" in html
    assert "recording_opt_out" in html


def test_call_detail_respects_recording_opt_out(client: TestClient) -> None:
    response = client.get("/calls/call_summit")

    assert response.status_code == 200
    assert "Recording opt-out" in response.text
    assert ".wav" not in response.text


def test_call_detail_returns_404_for_an_unknown_call(client: TestClient) -> None:
    response = client.get("/calls/call_missing")

    assert response.status_code == 404


def test_metrics_json_is_machine_readable_and_matches_the_dashboard(
    client: TestClient, service: MonitoringService
) -> None:
    response = client.get("/metrics.json")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == 1
    assert body["profile"] == "local"
    assert body["filters"] == {"tenant": None, "from": None, "to": None, "outcome": None}
    assert body["metrics"]["calls"]["total"] == 2
    assert body["metrics"]["containment"]["percent"] == 50.0
    assert body["metrics"]["transfer_rate"]["percent"] == 50.0
    assert body["metrics"]["booking_rate"]["percent"] == 50.0
    assert body["metrics"]["latency"]["p50_ms"] == 3000
    assert body["metrics"]["latency"]["p95_ms"] == 3900
    assert "tool_error_rate" in body["definitions"]
    assert body["alerts"] == []
    assert not (service.data_dir / "monitoring" / "alerts.jsonl").exists()
    assert "secret" not in json.dumps(body).lower()


def test_dashboard_banner_and_alerts_jsonl_record_a_failing_threshold(tmp_path) -> None:
    failing = make_call(
        "call_emergency",
        intent=CallIntent.emergency,
        outcome=CallOutcome.failed,
        emergency_triage_ok=False,
        started_at=NOW,
    )
    service = MonitoringService(
        data_dir=tmp_path,
        root=ROOT,
        seed=False,
        now=lambda: NOW,
        profile="local",
    )
    service.replace_calls([failing])
    client = TestClient(
        create_app(
            tenants=load_all_tenants(ROOT / "tenants"),
            minter=None,
            claim_signer=None,
            livekit_url="",
            monitoring=service,
        )
    )

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Emergency transfer failure" in response.text
    assert not (tmp_path / "monitoring" / "alerts.jsonl").exists()

    refresh = client.post("/alerts/refresh")
    assert refresh.status_code == 200
    alert_lines = [
        json.loads(line)
        for line in (tmp_path / "monitoring" / "alerts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert alert_lines[0]["kind"] == "emergency_transfer_failure"


def test_cross_origin_review_post_is_rejected(tmp_path, service) -> None:
    client = TestClient(
        create_app(
            tenants=load_all_tenants(ROOT / "tenants"),
            minter=None,
            claim_signer=None,
            livekit_url="",
            monitoring=service,
        ),
        follow_redirects=False,
    )

    response = client.post(
        "/review/mark",
        params={"call_id": "call_hl"},
        headers={"Origin": "http://evil.example"},
    )

    assert response.status_code == 403
    assert not (tmp_path / "monitoring" / "review.json").exists()

    same_origin = client.post(
        "/review/mark",
        params={"call_id": "call_hl"},
        headers={"Origin": "http://testserver"},
    )
    assert same_origin.status_code == 303


def test_call_candidate_path_traversal_is_rejected(service) -> None:
    client = TestClient(
        create_app(
            tenants=load_all_tenants(ROOT / "tenants"),
            minter=None,
            claim_signer=None,
            livekit_url="",
            monitoring=service,
        ),
        follow_redirects=False,
    )

    response = client.post(
        "/review/candidate",
        params={"call_id": "../../etc/passwd"},
    )

    assert response.status_code == 400
    assert list((service.data_dir / "monitoring").glob("*.yaml")) == []


def test_non_loopback_host_is_rejected(service) -> None:
    app = create_app(
        tenants=load_all_tenants(ROOT / "tenants"),
        minter=None,
        claim_signer=None,
        livekit_url="",
        monitoring=service,
    )
    client = TestClient(app, base_url="http://evil.example")

    response = client.get("/dashboard")

    assert response.status_code == 403

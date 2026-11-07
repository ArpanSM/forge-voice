"""Weekly review flow and the handover static export."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from forge_voice.monitoring.export import export_dashboard
from forge_voice.monitoring.service import MonitoringService
from forge_voice.policy.state import CallOutcome
from forge_voice.runtime.models import TranscriptTurn
from forge_voice.tenants import load_all_tenants
from forge_voice.web.app import create_app
from support_monitoring import latency, make_call, tool

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def service(tmp_path) -> MonitoringService:
    service = MonitoringService(
        data_dir=tmp_path,
        root=ROOT,
        seed=False,
        now=lambda: NOW,
        profile="local",
    )
    service.replace_calls(
        [
            make_call(
                "call_hl",
                outcome=CallOutcome.booked,
                booking_id="bk_hl_1",
                started_at=NOW - timedelta(days=1),
                turn_latencies=[latency(2000)],
                tool_events=[tool("book_appointment")],
            ),
            make_call(
                "call_summit",
                tenant_id="summit",
                outcome=CallOutcome.callback,
                started_at=NOW - timedelta(days=2),
                turn_latencies=[latency(2500)],
            ),
            make_call(
                "call_failed",
                outcome=CallOutcome.failed,
                started_at=NOW - timedelta(days=3),
                turn_latencies=[latency(2600)],
            ),
        ]
    )
    return service


@pytest.fixture
def client(service) -> TestClient:
    return TestClient(
        create_app(
            tenants=load_all_tenants(ROOT / "tenants"),
            minter=None,
            claim_signer=None,
            livekit_url="",
            monitoring=service,
        ),
        follow_redirects=False,
    )


def test_weekly_review_page_lists_calls_and_the_smoke_command(client: TestClient) -> None:
    response = client.get("/review")

    assert response.status_code == 200
    assert "Weekly review" in response.text
    assert "call_hl" in response.text
    assert "call_summit" in response.text
    assert "make eval-smoke" in response.text
    assert "Create scenario candidate" in response.text


def test_marking_a_call_writes_the_review_state(client: TestClient, tmp_path) -> None:
    response = client.post("/review/mark", params={"call_id": "call_hl"})

    assert response.status_code == 303
    state = json.loads((tmp_path / "monitoring" / "review.json").read_text(encoding="utf-8"))
    assert state["call_hl"]["call_id"] == "call_hl"
    assert state["call_hl"]["marked_at"].startswith("2026-11-07")


def test_creating_a_scenario_candidate_writes_a_draft_yaml(client: TestClient, tmp_path) -> None:
    response = client.post("/review/candidate", params={"call_id": "call_hl"})

    assert response.status_code == 303
    path = tmp_path / "monitoring" / "scenario_candidates" / "call_hl.yaml"
    candidate = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert candidate["id"] == "candidate_call_hl"
    assert candidate["tenant"] == "harborlight"
    assert candidate["mode"] == "text"
    assert candidate["turns"] == ["I need a drain cleaning."]
    assert candidate["expected_final_state"]["outcome"] == "booked"
    assert candidate["expected_final_state"]["booking_count"] == 1
    assert candidate["source_call_id"] == "call_hl"


def test_failed_call_candidate_targets_success_not_the_observed_failure(
    client: TestClient, tmp_path
) -> None:
    response = client.post("/review/candidate", params={"call_id": "call_failed"})

    assert response.status_code == 303
    candidate = yaml.safe_load(
        (tmp_path / "monitoring" / "scenario_candidates" / "call_failed.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert candidate["expected_final_state"]["outcome"] == "booked"
    assert candidate["observed_outcome"] == "failed"
    assert "failed" not in candidate["pass_condition"].lower()
    assert candidate["review_todo"]


def test_review_state_write_is_atomic(service, monkeypatch) -> None:
    service.mark_review("call_hl")
    original = service.review_path.read_text(encoding="utf-8")
    monkeypatch.setattr(
        "forge_voice.monitoring.atomic.os.replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError):
        service.mark_review("call_summit")

    assert service.review_path.read_text(encoding="utf-8") == original


def test_candidate_write_is_atomic(service, monkeypatch) -> None:
    path = service.candidate_dir / "call_hl.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old candidate\n", encoding="utf-8")
    monkeypatch.setattr(
        "forge_voice.monitoring.atomic.os.replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError):
        service.create_scenario_candidate("call_hl")

    assert path.read_text(encoding="utf-8") == "old candidate\n"


def test_static_export_write_is_atomic(service, tmp_path, monkeypatch) -> None:
    output = tmp_path / "dashboard-sample.html"
    output.write_text("old export\n", encoding="utf-8")
    monkeypatch.setattr(
        "forge_voice.monitoring.atomic.os.replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError):
        export_dashboard(service, output, generated_at=NOW)

    assert output.read_text(encoding="utf-8") == "old export\n"


def test_static_export_contains_the_sample_data_and_no_secrets(service, tmp_path) -> None:
    live = make_call(
        "call_live",
        synthetic=False,
        started_at=NOW,
        qa_flags=["live_trace"],
    ).model_copy(
        update={
            "transcript": [
                TranscriptTurn(role="caller", text="LIVE_SECRET_TRANSCRIPT"),
            ]
        }
    )
    service.replace_calls([*service.calls(), live])

    output = tmp_path / "dashboard-sample.html"

    export_dashboard(service, output, generated_at=NOW)

    html = output.read_text(encoding="utf-8")
    assert "Static dashboard export" in html
    assert "call_hl" in html
    assert "call_summit" in html
    assert "bk_hl_1" in html
    assert "I need a drain cleaning." in html
    assert "LIVE_SECRET_TRANSCRIPT" not in html
    assert "call_live" not in html
    assert "recordings/" not in html
    assert "htmx" not in html.lower()
    assert "LIVEKIT_API_SECRET" not in html
    assert "token" not in html.lower()

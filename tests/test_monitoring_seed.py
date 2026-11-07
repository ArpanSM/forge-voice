"""The synthetic dashboard seed reuses the real text call runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from forge_voice.events.trace import trace_records
from forge_voice.monitoring.seed import seed_dashboard_calls
from forge_voice.monitoring.service import MonitoringService
from forge_voice.policy.state import CallIntent
from forge_voice.tenants import load_all_tenants
from forge_voice.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def test_seed_builds_a_30_day_two_tenant_call_set() -> None:
    records = seed_dashboard_calls(ROOT, now=NOW, profile="local")

    assert len(records) >= 20
    assert {record.tenant_id for record in records} == {"harborlight", "summit"}
    assert {record.outcome for record in records} >= {
        "booked",
        "emergency_ticket",
        "callback",
    }
    assert len({record.call_id for record in records}) == len(records)
    oldest = min(record.started_at for record in records)
    assert oldest >= NOW - timedelta(days=30)
    assert all(record.caller_phone for record in records)
    assert any(record.recording_opt_out for record in records)
    assert any(record.turn_latencies for record in records)
    assert any(record.slot_checked for record in records)
    assert any(record.slot_checked and record.slot_error for record in records)
    emergency_ok = [
        record
        for record in records
        if record.intent is CallIntent.emergency and record.emergency_triage_ok is True
    ]
    emergency_failed = [
        record
        for record in records
        if record.intent is CallIntent.emergency and record.emergency_triage_ok is False
    ]
    assert emergency_ok
    assert emergency_failed


def test_seeded_call_set_renders_cards_and_matches_the_metrics_export(tmp_path) -> None:
    service = MonitoringService(
        data_dir=tmp_path,
        root=ROOT,
        now=lambda: NOW,
        profile="local",
    )
    client = TestClient(
        create_app(
            tenants=load_all_tenants(ROOT / "tenants"),
            minter=None,
            claim_signer=None,
            livekit_url="",
            monitoring=service,
        )
    )

    dashboard = client.get("/dashboard")
    exported = client.get("/metrics.json").json()
    records = service.calls()

    assert dashboard.status_code == 200
    assert "Total calls" in dashboard.text
    assert str(len(records)) in dashboard.text
    assert exported["metrics"]["calls"]["total"] == len(records)
    emergency = [record for record in records if record.intent is CallIntent.emergency]
    emergency_ok = [record for record in emergency if record.emergency_triage_ok is True]
    assert exported["metrics"]["emergency_triage_rate"]["denominator"] == len(emergency)
    assert exported["metrics"]["emergency_triage_rate"]["numerator"] == len(emergency_ok)
    checked = [record for record in records if record.slot_checked]
    assert exported["metrics"]["slot_error_rate"]["denominator"] == len(checked)
    assert exported["metrics"]["slot_error_rate"]["numerator"] > 0
    assert exported["metrics"]["latency"]["samples"] > 0


def test_service_seeds_once_and_does_not_duplicate_calls(tmp_path) -> None:
    service = MonitoringService(
        data_dir=tmp_path,
        root=ROOT,
        now=lambda: NOW,
        profile="local",
    )
    first = len(service.calls())
    service.ensure_seeded()
    second = len(service.calls())

    assert first == second >= 20


def test_expired_traces_are_not_reimported_on_every_sync(tmp_path) -> None:
    trace_dir = tmp_path / "calls"
    trace_dir.mkdir()
    old = NOW - timedelta(days=31)
    event = {
        "ts": old.timestamp(),
        "event": "call_started",
        "call_id": "call_expired",
        "tenant": "harborlight",
    }
    finish = {
        "ts": old.timestamp() + 30,
        "event": "call_finished",
        "call_id": "call_expired",
        "outcome": "booked",
    }
    (trace_dir / "call_expired.jsonl").write_text(
        json.dumps(event) + "\n" + json.dumps(finish) + "\n",
        encoding="utf-8",
    )
    service = MonitoringService(
        data_dir=tmp_path,
        root=ROOT,
        seed=False,
        now=lambda: NOW,
        profile="local",
    )

    assert service.sync_traces() == 0
    assert service.sync_traces() == 0
    assert service.calls() == []
    assert service.store.all_records() == []


def test_trace_slot_expectation_is_used_for_slot_audit(tmp_path) -> None:
    trace_dir = tmp_path / "calls"
    trace_dir.mkdir()
    trace = [
        {
            "ts": 1762526400.0,
            "event": "call_started",
            "call_id": "call_slot",
            "tenant": "harborlight",
        },
        {
            "ts": 1762526401.0,
            "event": "slot_expectation",
            "call_id": "call_slot",
            "service_id": "leak_repair",
            "address_zip": "94107",
            "slot_id": "slot_expected",
        },
        {
            "ts": 1762526402.0,
            "event": "booked",
            "call_id": "call_slot",
            "booking_id": "bk_slot",
            "service_id": "drain_cleaning",
            "slot_id": "slot_wrong",
            "address": {"zip": "94107"},
        },
        {
            "ts": 1762526403.0,
            "event": "call_finished",
            "call_id": "call_slot",
            "outcome": "booked",
            "booking_id": "bk_slot",
        },
    ]
    (trace_dir / "call_slot.jsonl").write_text(
        "\n".join(json.dumps(line) for line in trace) + "\n",
        encoding="utf-8",
    )

    record = trace_records(trace_dir)[0]

    assert record.slot_checked is True
    assert record.slot_error is True
    assert record.expected_service_id == "leak_repair"
    assert record.booked_service_id == "drain_cleaning"


def test_trace_records_are_read_from_the_live_call_jsonl(tmp_path) -> None:
    trace_dir = tmp_path / "calls"
    trace_dir.mkdir()
    trace = [
        {
            "ts": 1762526400.0,
            "event": "call_started",
            "call_id": "call_live",
            "tenant": "harborlight",
            "caller_phone": "+14155550199",
        },
        {
            "ts": 1762526401.0,
            "event": "profile",
            "call_id": "call_live",
            "profile": "local",
            "llm": "lfm3",
        },
        {
            "ts": 1762526402.0,
            "event": "caller_utterance",
            "call_id": "call_live",
            "text": "I smell gas.",
        },
        {
            "ts": 1762526403.0,
            "event": "tool_result",
            "call_id": "call_live",
            "tool": "create_emergency_ticket",
            "ok": True,
            "code": "ok",
            "args": {},
            "latency_ms": 12,
            "category": "gas_or_co",
            "safety_text": "Leave the building and call 911.",
            "ticket_id": "em_live",
        },
        {
            "ts": 1762526403.5,
            "event": "emergency_ticket",
            "call_id": "call_live",
            "ticket_id": "em_live",
            "category": "gas_or_co",
            "safety_script": "gas_co",
            "safety_text": "Leave the building and call 911.",
        },
        {
            "ts": 1762526404.0,
            "event": "handoff",
            "call_id": "call_live",
            "status": "no_answer",
            "reason": "emergency",
            "mode": "live",
        },
        {
            "ts": 1762526405.0,
            "event": "recording_opt_out",
            "call_id": "call_live",
        },
        {
            "ts": 1762526410.0,
            "event": "call_finished",
            "call_id": "call_live",
            "outcome": "emergency_ticket",
            "ticket_id": "em_live",
            "booking_id": None,
            "callback_id": "cb_live",
            "writes": 0,
        },
    ]
    (trace_dir / "call_live.jsonl").write_text(
        "\n".join(json.dumps(line) for line in trace) + "\n",
        encoding="utf-8",
    )

    records = trace_records(trace_dir)

    assert len(records) == 1
    record = records[0]
    assert record.call_id == "call_live"
    assert record.tenant_id == "harborlight"
    assert record.outcome == "emergency_ticket"
    assert record.ticket_id == "em_live"
    assert record.transfer_status == "no_answer"
    assert record.caller_phone == "+14155550199"
    assert record.transcript[0].text == "I smell gas."
    assert record.tool_events[0].name == "create_emergency_ticket"
    assert record.emergency_triage_ok is False
    assert record.emergency_category == "gas_or_co"
    assert record.emergency_safety_script == "Leave the building and call 911."
    assert record.recording_opt_out is True
    assert record.recording_ref == "text_only"
    assert record.synthetic is False
    assert record.turn_latencies == []

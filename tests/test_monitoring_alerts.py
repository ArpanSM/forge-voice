"""Alert evaluation follows the #27 thresholds and writes alerts.jsonl."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from forge_voice.monitoring.alerts import append_alerts, evaluate_alerts
from forge_voice.monitoring.service import MonitoringService, send_webhook
from forge_voice.policy.state import CallIntent, CallOutcome
from support_monitoring import latency, make_call, tool

ROOT = Path(__file__).resolve().parents[1]

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


def _kinds(alerts) -> set[str]:
    return {alert.kind for alert in alerts}


def test_clean_calls_raise_no_alerts() -> None:
    records = [
        make_call("call_1", turn_latencies=[latency(2000)]),
        make_call(
            "call_2",
            intent=CallIntent.emergency,
            outcome=CallOutcome.emergency_ticket,
            ticket_id="em_1",
            emergency_triage_ok=True,
            turn_latencies=[latency(2500)],
        ),
    ]

    assert evaluate_alerts(records, profile="local", now=NOW) == []


def test_p95_over_the_active_profile_budget_alerts() -> None:
    records = [
        make_call("call_1", turn_latencies=[latency(6100)]),
        make_call("call_2", turn_latencies=[latency(6200)]),
    ]

    alerts = evaluate_alerts(records, profile="local", now=NOW)

    assert _kinds(alerts) == {"latency_p95_over_budget"}
    assert alerts[0].observed == 6195
    assert alerts[0].threshold == 6000


def test_hybrid_budget_is_tighter_than_local() -> None:
    records = [
        make_call("call_1", profile="hybrid", turn_latencies=[latency(2600, llm=1900)]),
        make_call("call_2", profile="hybrid", turn_latencies=[latency(2700, llm=2000)]),
    ]

    alerts = evaluate_alerts(records, profile="hybrid", now=NOW)

    assert _kinds(alerts) == {"latency_p95_over_budget"}
    assert alerts[0].threshold == 2500


def test_tool_error_rate_alerts_above_two_percent() -> None:
    events = [tool("get_availability") for _ in range(39)]
    events.append(tool("get_availability", ok=False, error_code="timeout"))
    records = [make_call("call_1", tool_events=events)]

    alerts = evaluate_alerts(records, profile="local", now=NOW)

    assert _kinds(alerts) == {"tool_error_rate_over_budget"}
    assert alerts[0].observed == 2.5

    two_percent_events = [tool("get_availability") for _ in range(49)]
    two_percent_events.append(tool("get_availability", ok=False, error_code="timeout"))
    at_two = records[0].model_copy(update={"tool_events": two_percent_events})
    assert evaluate_alerts([at_two], profile="local", now=NOW) == []


def test_booking_failure_alerts_above_one_percent() -> None:
    records = [
        make_call(f"call_{index}", tool_events=[tool("book_appointment")]) for index in range(49)
    ]
    records.append(
        make_call(
            "call_failed_write",
            tool_events=[tool("book_appointment", ok=False, error_code="timeout")],
        )
    )

    alerts = evaluate_alerts(records, profile="local", now=NOW)

    assert _kinds(alerts) == {"booking_failure_rate_over_budget"}
    assert alerts[0].observed == 2.0

    at_one_percent = [
        make_call(f"call_ok_{index}", tool_events=[tool("book_appointment")]) for index in range(99)
    ]
    at_one_percent.append(
        make_call(
            "call_failed_write",
            tool_events=[tool("book_appointment", ok=False, error_code="timeout")],
        )
    )
    assert evaluate_alerts(at_one_percent, profile="local", now=NOW) == []


def test_slot_correctness_failure_alerts() -> None:
    records = [
        make_call(
            "call_booked",
            slot_checked=True,
            slot_error=True,
            expected_service_id="leak_repair",
            booked_service_id="drain_cleaning",
            expected_address_zip="94107",
            booked_address_zip="94107",
        )
    ]

    alerts = evaluate_alerts(records, profile="local", now=NOW)

    assert _kinds(alerts) == {"slot_correctness_failure"}
    assert alerts[0].call_ids == ["call_booked"]


def test_emergency_transfer_failure_and_security_anomaly_alert() -> None:
    records = [
        make_call(
            "call_emergency",
            intent=CallIntent.emergency,
            outcome=CallOutcome.failed,
            ticket_id=None,
            emergency_triage_ok=False,
        ),
        make_call(
            "call_security",
            qa_flags=["cross_tenant_attempt"],
        ),
    ]

    alerts = evaluate_alerts(records, profile="local", now=NOW)

    assert _kinds(alerts) == {"emergency_transfer_failure", "cross_tenant_auth_anomaly"}
    assert all(alert.severity == "critical" for alert in alerts)


def test_append_alerts_deduplicates_and_writes_jsonl(tmp_path) -> None:
    alerts = evaluate_alerts(
        [
            make_call(
                "call_emergency",
                intent=CallIntent.emergency,
                outcome=CallOutcome.failed,
                emergency_triage_ok=False,
            )
        ],
        profile="local",
        now=NOW,
    )
    path = tmp_path / "alerts.jsonl"

    append_alerts(path, alerts)
    append_alerts(path, alerts)

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 1
    assert lines[0]["kind"] == "emergency_transfer_failure"
    assert lines[0]["alert_id"].startswith("emergency_transfer_failure_local_")


def test_refresh_alerts_sends_only_new_alerts_once(tmp_path, monkeypatch) -> None:
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
                "call_emergency",
                intent=CallIntent.emergency,
                outcome=CallOutcome.failed,
                emergency_triage_ok=False,
            )
        ]
    )
    sent: list[list] = []
    monkeypatch.setenv("FORGE_VOICE_ALERT_WEBHOOK", "https://discord.com/api/webhooks/test")
    monkeypatch.setattr(
        "forge_voice.monitoring.service.send_webhook",
        lambda _url, alerts: sent.append(list(alerts)),
    )

    service.refresh_alerts(notify=True)
    service.refresh_alerts(notify=True)

    assert len(sent) == 1
    assert [alert.kind for alert in sent[0]] == ["emergency_transfer_failure"]


def test_webhook_supports_telegram_with_a_short_timeout(monkeypatch) -> None:
    calls = []

    class Response:
        def close(self) -> None:
            return None

    def fake_urlopen(endpoint, timeout):
        calls.append((endpoint, timeout))
        return Response()

    monkeypatch.setenv("FORGE_VOICE_TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr("forge_voice.monitoring.service.request.urlopen", fake_urlopen)
    alerts = evaluate_alerts(
        [
            make_call(
                "call_emergency",
                intent=CallIntent.emergency,
                outcome=CallOutcome.failed,
                emergency_triage_ok=False,
            )
        ],
        profile="local",
        now=NOW,
    )

    assert send_webhook("https://api.telegram.org/botTOKEN/sendMessage", alerts) is True
    endpoint, timeout = calls[0]
    body = json.loads(endpoint.data)
    assert body["chat_id"] == "12345"
    assert "Emergency transfer failure" in body["text"]
    assert timeout == 1
    assert send_webhook("http://discord.com/api/webhooks/test", alerts) is False
    assert send_webhook("https://evil.example/webhook", alerts) is False

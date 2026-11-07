"""Monitoring service: the only read seam the dashboard, export and review share."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib import request
from urllib.parse import urlparse

import yaml

from forge_voice.events.models import CallRecord
from forge_voice.events.store import CallStore
from forge_voice.events.trace import trace_records
from forge_voice.monitoring.alerts import Alert, append_alerts, evaluate_alerts
from forge_voice.monitoring.atomic import atomic_write_text
from forge_voice.monitoring.filters import CallFilters
from forge_voice.monitoring.metrics import DEFINITIONS, aggregate_metrics
from forge_voice.monitoring.seed import seed_dashboard_calls
from forge_voice.policy.state import CallIntent, CallOutcome
from forge_voice.tenants import TenantConfig, load_all_tenants

Profile = Literal["local", "hybrid"]
CALL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
TARGET_OUTCOME = {
    CallIntent.book: CallOutcome.booked,
    CallIntent.reschedule: CallOutcome.rescheduled,
    CallIntent.cancel: CallOutcome.cancelled,
    CallIntent.emergency: CallOutcome.emergency_ticket,
    CallIntent.human: CallOutcome.transferred,
    CallIntent.pricing_faq: CallOutcome.info_only,
    CallIntent.status: CallOutcome.info_only,
}
TARGET_TOOLS = {
    CallIntent.book: [
        "lookup_customer",
        "get_service_area",
        "get_availability",
        "book_appointment",
    ],
    CallIntent.reschedule: [
        "lookup_customer",
        "get_availability",
        "reschedule_appointment",
    ],
    CallIntent.cancel: ["lookup_customer", "cancel_appointment"],
    CallIntent.emergency: ["create_emergency_ticket", "transfer_to_human"],
    CallIntent.human: ["transfer_to_human"],
    CallIntent.pricing_faq: [],
    CallIntent.status: ["lookup_customer"],
}


class MonitoringService:
    def __init__(
        self,
        *,
        data_dir: Path | str,
        root: Path | str | None = None,
        now: Callable[[], datetime] | None = None,
        profile: Profile = "local",
        retention_days: int = 30,
        seed: bool = True,
    ) -> None:
        if profile not in {"local", "hybrid"}:
            raise ValueError(f"unknown profile {profile!r}")
        self.data_dir = Path(data_dir)
        self.root = Path(root).resolve() if root is not None else Path.cwd()
        self.profile = profile
        self.retention_days = retention_days
        self._now = now or (lambda: datetime.now(UTC))
        self._seed_enabled = seed
        self.store = CallStore(
            self.data_dir,
            retention_days=retention_days,
            now=self._now,
        )
        self.alert_path = self.data_dir / "monitoring" / "alerts.jsonl"
        self.review_path = self.data_dir / "monitoring" / "review.json"
        self.candidate_dir = self.data_dir / "monitoring" / "scenario_candidates"
        self._tenants = None
        if seed:
            self.ensure_seeded()

    # ------------------------------------------------------------------ reads
    def ensure_seeded(self) -> None:
        self.sync_traces()
        self.store.prune()
        if not self.store.records():
            records = seed_dashboard_calls(
                self.root,
                now=self._now(),
                profile=self.profile,
            )
            self.store.replace_all(records)
            self.sync_traces()
        self.refresh_alerts(notify=True)

    def sync_traces(self) -> int:
        traces = trace_records(self.data_dir / "calls")
        if not traces:
            self.store.prune()
            return 0
        existing = {record.call_id: record for record in self.store.all_records()}
        cutoff = self.store.cutoff()
        fresh = 0
        for trace in traces:
            if trace.ended_at < cutoff:
                continue
            current = existing.get(trace.call_id)
            if current is not None and current.ended_at >= trace.ended_at:
                continue
            existing[trace.call_id] = trace
            fresh += 1
        if fresh:
            self.store.replace_all(existing.values())
        self.store.prune()
        return fresh

    def replace_calls(self, records: list[CallRecord]) -> None:
        self.store.replace_all(records)

    def calls(self, filters: CallFilters | None = None) -> list[CallRecord]:
        active = [
            record
            for record in self.store.records(filters=filters)
            if record.profile == self.profile
        ]
        return active

    def call(self, call_id: str) -> CallRecord | None:
        return self.store.get(call_id)

    def metrics(self, filters: CallFilters | None = None) -> dict[str, object]:
        calls = self.calls(filters)
        by_tenant = {
            tenant: aggregate_metrics([call for call in calls if call.tenant_id == tenant])
            for tenant in sorted({call.tenant_id for call in calls})
        }
        return {
            "schema_version": 1,
            "generated_at": self._now().isoformat(),
            "profile": self.profile,
            "filters": _filters_payload(filters),
            "definitions": DEFINITIONS,
            "metrics": aggregate_metrics(calls),
            "by_tenant": by_tenant,
            "alerts": [alert.model_dump(mode="json") for alert in self.alerts()],
        }

    def alerts(self) -> list[Alert]:
        return evaluate_alerts(
            self.calls(),
            profile=self.profile,
            now=self._now(),
        )

    def refresh_alerts(self, *, notify: bool = False) -> list[Alert]:
        alerts = self.alerts()
        new_alerts = append_alerts(self.alert_path, alerts)
        webhook = os.environ.get("FORGE_VOICE_ALERT_WEBHOOK", "").strip()
        if notify and new_alerts and webhook:
            send_webhook(webhook, new_alerts)
        return alerts

    # ---------------------------------------------------------------- review
    def review_state(self) -> dict[str, dict[str, str]]:
        if not self.review_path.exists():
            return {}
        try:
            data = json.loads(self.review_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def mark_review(self, call_id: str) -> dict[str, str]:
        call_id = _validated_call_id(call_id)
        if self.call(call_id) is None:
            raise KeyError(call_id)
        state = self.review_state()
        state[call_id] = {
            "call_id": call_id,
            "marked_at": self._now().isoformat(),
        }
        atomic_write_text(
            self.review_path,
            json.dumps(state, indent=2, sort_keys=True) + "\n",
        )
        return state[call_id]

    def weekly_sample(self, *, limit: int = 10) -> list[CallRecord]:
        cutoff = self._now() - timedelta(days=7)
        calls = [call for call in self.calls() if call.started_at >= cutoff]
        if not calls:
            calls = self.calls()
        return calls[:limit]

    def create_scenario_candidate(self, call_id: str) -> Path:
        call_id = _validated_call_id(call_id)
        call = self.call(call_id)
        if call is None:
            raise KeyError(call_id)
        turns = [turn.text for turn in call.transcript if turn.role == "caller"]
        if not turns:
            turns = [turn.text for turn in call.transcript[:1]]
        target_outcome, target_state, target_tools, pass_condition = _target_behaviour(call)
        hard_gates = ["audit_completeness"]
        if call.intent is CallIntent.emergency:
            hard_gates.append("emergency_triage")
        if call.intent in {CallIntent.book, CallIntent.reschedule, CallIntent.cancel}:
            hard_gates.extend(["slot_correctness", "confirmation_accuracy", "double_booking"])
        if call.intent is CallIntent.human or call.callback_id:
            hard_gates.append("handoff_correctness")
        candidate = {
            "id": f"candidate_{call.call_id}",
            "mode": "text",
            "category": "weekly_review",
            "tenant": call.tenant_id,
            "held_out": False,
            "smoke": False,
            "critical_repeat": False,
            "persona": f"Synthetic caller from reviewed call {call.call_id}",
            "goal": (
                f"Target the corrected behaviour ({target_outcome.value}); the observed "
                f"outcome was {call.outcome.value}."
            ),
            "turns": turns,
            "expected_tool_calls": target_tools,
            "expected_final_state": target_state,
            "pass_condition": pass_condition,
            "hard_gates": hard_gates,
            "max_turns": max(len(turns), 1),
            "source_call_id": call.call_id,
            "observed_outcome": call.outcome.value,
            "review_todo": (
                "Review the transcript and confirm the target state; do not encode the "
                "observed failure as expected behaviour."
            ),
            "captured_at": self._now().isoformat(),
        }
        path = self.candidate_dir / f"{call.call_id}.yaml"
        header = (
            "# Draft scenario candidate from the weekly review.\n"
            "# Target behaviour is corrected; confirm it before adding to the manifest.\n"
        )
        atomic_write_text(
            path,
            header + yaml.safe_dump(candidate, sort_keys=False),
        )
        return path

    def tenant_name(self, tenant_id: str) -> str:
        tenant = self._tenant_configs().get(tenant_id)
        return tenant.display_name if tenant is not None else tenant_id

    def tenant_options(self) -> dict[str, str]:
        return {
            tenant_id: tenant.display_name
            for tenant_id, tenant in sorted(self._tenant_configs().items())
        }

    def _tenant_configs(self) -> dict[str, TenantConfig]:
        if self._tenants is None:
            tenants_dir = self.root / "tenants"
            self._tenants = load_all_tenants(tenants_dir) if tenants_dir.exists() else {}
        return self._tenants

    def candidates(self) -> list[Path]:
        if not self.candidate_dir.exists():
            return []
        return sorted(self.candidate_dir.glob("*.yaml"))


def _validated_call_id(call_id: str) -> str:
    if not CALL_ID_RE.fullmatch(call_id):
        raise ValueError("invalid call id")
    return call_id


def _target_behaviour(
    call: CallRecord,
) -> tuple[CallOutcome, dict[str, object], list[str], str]:
    intent = call.intent or CallIntent.book
    target = TARGET_OUTCOME.get(intent, CallOutcome.info_only)
    tools = list(TARGET_TOOLS.get(intent, []))
    if target is CallOutcome.booked:
        state: dict[str, object] = {
            "outcome": "booked",
            "booking_count": 1,
            "service_id": call.booked_service_id or call.service_id,
            "address_zip": call.booked_address_zip,
            "confirmation_queued": True,
            "slot_correctness": True,
        }
        condition = (
            "One committed booking for the requested service, address and slot, with "
            "read-back, explicit yes and a queued confirmation."
        )
    elif target is CallOutcome.rescheduled:
        state = {
            "outcome": "rescheduled",
            "booking_id": call.booking_id,
            "old_slot_released": True,
            "service_id": call.booked_service_id or call.service_id,
            "confirmation_queued": True,
            "slot_correctness": True,
        }
        condition = (
            "The same booking is moved to a real offered slot; the old slot is released "
            "and one confirmation is queued."
        )
    elif target is CallOutcome.cancelled:
        state = {
            "outcome": "cancelled",
            "booking_id": call.booking_id,
            "slot_released": True,
            "confirmation_queued": True,
        }
        condition = (
            "The booking is cancelled and the slot released after verification and confirmation."
        )
    elif target is CallOutcome.emergency_ticket:
        state = {
            "outcome": "emergency_ticket",
            "category": call.emergency_category or "gas_or_co",
            "safety_script": call.emergency_safety_script or "911/life-safety",
            "ticket_count": 1,
            "transfer_status": "connected_or_callback",
            "booking_count": 0,
        }
        condition = (
            "Correct emergency category, 911-first safety script, structured ticket and "
            "a connected or queued on-call handoff; no booking or price."
        )
    elif target is CallOutcome.transferred:
        state = {
            "outcome": "transferred",
            "write_count": 0,
            "handoff_packet_complete": True,
        }
        condition = (
            "A complete handoff packet reaches a human; never claim a transfer before answer."
        )
    else:
        state = {
            "outcome": "info_only",
            "booking_count": 0,
            "unsafe_promise": False,
        }
        condition = (
            "Answer from the configured knowledge base without a booking, write or "
            "binding price; offer a callback if unknown."
        )
    return target, state, tools, condition


def _filters_payload(filters: CallFilters | None) -> dict[str, str | None]:
    if filters is None:
        return {"tenant": None, "from": None, "to": None, "outcome": None}
    return {
        "tenant": filters.tenant,
        "from": filters.from_date.isoformat() if filters.from_date else None,
        "to": filters.to_date.isoformat() if filters.to_date else None,
        "outcome": filters.outcome.value if filters.outcome else None,
    }


WEBHOOK_HOSTS = frozenset({"discord.com", "discordapp.com", "api.telegram.org"})


def send_webhook(url: str, alerts: list[Alert]) -> bool:
    """Post new alerts once to a validated Discord or Telegram webhook.

    Discord uses `content`; Telegram uses `text` plus `FORGE_VOICE_TELEGRAM_CHAT_ID`.
    Aggregate alert data only, no transcripts, caller details or secrets.
    """
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in WEBHOOK_HOSTS
        or parsed.username
        or parsed.password
    ):
        return False
    content = "\n".join(f"[{alert.severity}] {alert.title}: {alert.message}" for alert in alerts)
    if parsed.hostname == "api.telegram.org":
        chat_id = os.environ.get("FORGE_VOICE_TELEGRAM_CHAT_ID", "").strip()
        if not chat_id:
            return False
        payload = {"chat_id": chat_id, "text": content[:3900]}
    else:
        payload = {
            "content": content[:1900],
            "alerts": [alert.model_dump(mode="json") for alert in alerts],
        }
    endpoint = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        request.urlopen(endpoint, timeout=1).close()
    except OSError:
        return False
    return True

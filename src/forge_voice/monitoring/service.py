"""Monitoring service: the only read seam the dashboard, export and review share."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib import request

import yaml

from forge_voice.events.models import CallRecord
from forge_voice.events.store import CallStore
from forge_voice.events.trace import trace_records
from forge_voice.monitoring.alerts import Alert, append_alerts, evaluate_alerts
from forge_voice.monitoring.filters import CallFilters
from forge_voice.monitoring.metrics import DEFINITIONS, aggregate_metrics
from forge_voice.monitoring.seed import seed_dashboard_calls
from forge_voice.policy.state import CallIntent
from forge_voice.tenants import load_all_tenants

Profile = Literal["local", "hybrid"]


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

    def sync_traces(self) -> int:
        traces = trace_records(self.data_dir / "calls")
        if not traces:
            return 0
        existing = {record.call_id: record for record in self.store.records()}
        fresh = 0
        for trace in traces:
            current = existing.get(trace.call_id)
            if current is not None and current.ended_at >= trace.ended_at:
                continue
            existing[trace.call_id] = trace
            fresh += 1
        if fresh:
            self.store.replace_all(existing.values())
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

    def refresh_alerts(self) -> list[Alert]:
        alerts = self.alerts()
        append_alerts(self.alert_path, alerts)
        webhook = os.environ.get("FORGE_VOICE_ALERT_WEBHOOK", "").strip()
        if alerts and webhook:
            send_webhook(webhook, alerts)
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
        if self.call(call_id) is None:
            raise KeyError(call_id)
        state = self.review_state()
        state[call_id] = {
            "call_id": call_id,
            "marked_at": self._now().isoformat(),
        }
        self.review_path.parent.mkdir(parents=True, exist_ok=True)
        self.review_path.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return state[call_id]

    def weekly_sample(self, *, limit: int = 10) -> list[CallRecord]:
        cutoff = self._now() - timedelta(days=7)
        calls = [call for call in self.calls() if call.started_at >= cutoff]
        if not calls:
            calls = self.calls()
        return calls[:limit]

    def create_scenario_candidate(self, call_id: str) -> Path:
        call = self.call(call_id)
        if call is None:
            raise KeyError(call_id)
        turns = [turn.text for turn in call.transcript if turn.role == "caller"]
        if not turns:
            turns = [turn.text for turn in call.transcript[:1]]
        hard_gates = ["audit_completeness"]
        if call.intent is CallIntent.emergency:
            hard_gates.append("emergency_triage")
        if call.transferred or call.callback_id:
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
                f"Reproduce the reviewed call outcome ({call.outcome.value}) and verify "
                "the same policy path."
            ),
            "turns": turns,
            "expected_tool_calls": list(dict.fromkeys(event.name for event in call.tool_events)),
            "expected_final_state": {"outcome": call.outcome.value},
            "pass_condition": (
                f"The call reaches {call.outcome.value} without a new policy regression."
            ),
            "hard_gates": hard_gates,
            "max_turns": max(len(turns), 1),
            "source_call_id": call.call_id,
            "captured_at": self._now().isoformat(),
        }
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        path = self.candidate_dir / f"{call.call_id}.yaml"
        header = (
            "# Draft scenario candidate from the weekly review.\n"
            "# Review the transcript and expected state before adding it to the manifest.\n"
        )
        path.write_text(
            header + yaml.safe_dump(candidate, sort_keys=False),
            encoding="utf-8",
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

    def _tenant_configs(self) -> dict[str, object]:
        if self._tenants is None:
            tenants_dir = self.root / "tenants"
            self._tenants = load_all_tenants(tenants_dir) if tenants_dir.exists() else {}
        return self._tenants

    def candidates(self) -> list[Path]:
        if not self.candidate_dir.exists():
            return []
        return sorted(self.candidate_dir.glob("*.yaml"))


def _filters_payload(filters: CallFilters | None) -> dict[str, str | None]:
    if filters is None:
        return {"tenant": None, "from": None, "to": None, "outcome": None}
    return {
        "tenant": filters.tenant,
        "from": filters.from_date.isoformat() if filters.from_date else None,
        "to": filters.to_date.isoformat() if filters.to_date else None,
        "outcome": filters.outcome.value if filters.outcome else None,
    }


def send_webhook(url: str, alerts: list[Alert]) -> None:
    """Optional free webhook (Discord-compatible `content`) with aggregate alert data only."""
    content = "\n".join(f"[{alert.severity}] {alert.title}: {alert.message}" for alert in alerts)
    payload = json.dumps(
        {
            "content": content[:1900],
            "alerts": [alert.model_dump(mode="json") for alert in alerts],
        }
    ).encode("utf-8")
    endpoint = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        request.urlopen(endpoint, timeout=3).close()
    except OSError:
        return

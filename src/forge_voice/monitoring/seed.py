"""Deterministic 30-day synthetic call set for the dashboard.

The seed runs the real #4 text call runner once per dev scenario, then adds the measured
latency stages that text mode does not produce. It never writes booking state outside the
runner's own synthetic SQLite store.
"""

from __future__ import annotations

import argparse
import os
import random
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from forge_voice.events.models import CallRecord, LatencyBreakdown
from forge_voice.events.store import CallStore
from forge_voice.runtime import CallRunner, CallScenario
from forge_voice.runtime.models import CallResult
from forge_voice.scenarios import load_manifest
from forge_voice.tenants import load_all_tenants

LA = ZoneInfo("America/Los_Angeles")
DEFAULT_PROFILE = "local"


def seed_dashboard_calls(
    root: Path | str,
    *,
    now: datetime | None = None,
    profile: str = DEFAULT_PROFILE,
) -> list[CallRecord]:
    repository = Path(root).resolve()
    tenants = load_all_tenants(repository / "tenants")
    manifest = load_manifest(
        repository / "fixtures" / "corpus" / "scenarios" / "manifest.yaml",
        known_tenants=tenants,
    )
    anchor = now or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    local_anchor = anchor.astimezone(LA)
    runner = CallRunner.from_repo(repository, now=local_anchor)
    records: list[CallRecord] = []
    scenarios = [scenario for scenario in manifest.text_scenarios if not scenario.held_out]
    for index, scenario in enumerate(scenarios):
        started_at = _started_at(local_anchor, index, scenario.category)
        result = runner.run_call(CallScenario.from_text_scenario(scenario, now=started_at))
        records.append(
            CallRecord.from_call_result(
                result,
                profile=profile,  # type: ignore[arg-type]
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=60 + (index * 13) % 180),
                turn_latencies=_latencies(result, profile, index),
                cost_usd=0.0,
                recording_opt_out=index % 9 == 0,
                recording_ref="text_only",
            )
        )
    return records


def _started_at(anchor: datetime, index: int, category: str) -> datetime:
    day = anchor.date() - timedelta(days=index % 28 + 1)
    hour = 20 if category == "after_hours" else 9 + index % 7
    minute = (index * 7) % 60
    return datetime.combine(day, time(hour=hour, minute=minute), tzinfo=LA)


def _latencies(result: CallResult, profile: str, index: int) -> list[LatencyBreakdown]:
    assistant_turns = sum(1 for turn in result.transcript if turn.role == "assistant")
    count = min(max(assistant_turns, 1), 4)
    rng = random.Random(f"{result.call_id}:{index}:{profile}")
    latencies: list[LatencyBreakdown] = []
    for _ in range(count):
        if profile == "hybrid":
            latencies.append(
                LatencyBreakdown(
                    stt_endpointing_ms=rng.randint(220, 520),
                    llm_ttft_ms=rng.randint(500, 1200),
                    tool_ms=rng.randint(3, 25),
                    tts_ttfb_ms=rng.randint(200, 350),
                )
            )
        else:
            latencies.append(
                LatencyBreakdown(
                    stt_endpointing_ms=rng.randint(320, 680),
                    llm_ttft_ms=rng.randint(700, 1700),
                    tool_ms=rng.randint(5, 35),
                    tts_ttfb_ms=rng.randint(250, 450),
                )
            )
    return latencies


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed the local monitoring dashboard")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("FORGE_VOICE_DATA_DIR", "data")),
    )
    parser.add_argument("--profile", choices=("local", "hybrid"), default=DEFAULT_PROFILE)
    parser.add_argument("--now", help="ISO timestamp for a reproducible seed")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else None
    records = seed_dashboard_calls(args.root, now=now, profile=args.profile)
    store = CallStore(args.data_dir, now=lambda: now or datetime.now(UTC))
    store.replace_all(records)
    print(f"seeded {len(records)} synthetic calls into {store.path}")


if __name__ == "__main__":
    main()

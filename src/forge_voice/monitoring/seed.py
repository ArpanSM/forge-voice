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
from forge_voice.transfer import TransferSimulator

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
    no_answer_runner = CallRunner.from_repo(
        repository,
        now=local_anchor,
        transfer=TransferSimulator(answered_targets=set()),
    )
    records: list[CallRecord] = []
    scenarios = [scenario for scenario in manifest.text_scenarios if not scenario.held_out]
    connected_emergency_seeded = False
    for index, scenario in enumerate(scenarios):
        started_at = _started_at(local_anchor, index, scenario.category)
        caller_phone = _caller_phone(scenario.tenant, index)
        if scenario.category == "emergency" and not connected_emergency_seeded:
            caller_phone = "+14155550101"
            connected_emergency_seeded = True
        call_scenario = CallScenario.from_text_scenario(
            scenario,
            now=started_at,
            caller_phone=caller_phone if scenario.category == "emergency" else None,
        )
        result = runner.run_call(call_scenario)
        records.append(
            _record_from_result(
                result,
                scenario.expected_final_state,
                profile=profile,
                started_at=started_at,
                caller_phone=caller_phone,
                index=index,
                recording_opt_out=index % 9 == 0,
            )
        )
    failing = next(
        (scenario for scenario in scenarios if scenario.category == "emergency"),
        None,
    )
    if failing is not None:
        started_at = _started_at(local_anchor, 1, "emergency") + timedelta(minutes=30)
        caller_phone = "+14155550101"
        failed_result = no_answer_runner.run_call(
            CallScenario(
                id=f"{failing.id}_noanswer",
                tenant=failing.tenant,
                turns=list(failing.turns),
                caller_phone=caller_phone,
                now=started_at,
            )
        )
        records.append(
            _record_from_result(
                failed_result,
                failing.expected_final_state,
                profile=profile,
                started_at=started_at,
                caller_phone=caller_phone,
                index=len(scenarios),
                recording_opt_out=False,
            )
        )
    _inject_slot_audit(records)
    return records


def _record_from_result(
    result: CallResult,
    expected: dict[str, object],
    *,
    profile: str,
    started_at: datetime,
    caller_phone: str,
    index: int,
    recording_opt_out: bool,
) -> CallRecord:
    actual = _actual_booking(result)
    expected_service = expected.get("service_id")
    expected_zip = expected.get("address_zip")
    slot_checked = bool(
        result.outcome.value in {"booked", "rescheduled"}
        and expected_service
        and expected_zip
        and actual is not None
    )
    expected_service_id = str(expected_service) if expected_service else None
    expected_address_zip = str(expected_zip) if expected_zip else None
    expected_slot_id = actual[2] if slot_checked and actual else None
    booked_service_id, booked_address_zip, booked_slot_id = actual or (None, None, None)
    return CallRecord.from_call_result(
        result,
        profile=profile,  # type: ignore[arg-type]
        started_at=started_at,
        ended_at=started_at + timedelta(seconds=60 + (index * 13) % 180),
        turn_latencies=_latencies(result, profile, index),
        cost_usd=0.0,
        caller_phone=caller_phone,
        recording_opt_out=recording_opt_out,
        recording_ref="text_only",
        expected_service_id=expected_service_id,
        expected_address_zip=expected_address_zip,
        expected_slot_id=expected_slot_id,
        booked_service_id=booked_service_id,
        booked_address_zip=booked_address_zip,
        booked_slot_id=booked_slot_id,
    )


def _actual_booking(result: CallResult) -> tuple[str | None, str | None, str | None] | None:
    for event in reversed(result.tool_events):
        if event.name not in {"book_appointment", "reschedule_appointment"}:
            continue
        if not event.result.ok:
            continue
        data = event.result.data or {}
        booking = data.get("booking") if isinstance(data, dict) else None
        if isinstance(booking, dict) and isinstance(booking.get("current"), dict):
            booking = booking["current"]
        if not isinstance(booking, dict):
            booking = {}
        args = event.args
        customer = args.get("customer") if isinstance(args.get("customer"), dict) else {}
        address = booking.get("address") or customer.get("address") or {}
        service = booking.get("service_id") or args.get("service_id")
        zip_code = address.get("zip") if isinstance(address, dict) else None
        slot = args.get("slot_id") or args.get("new_slot_id")
        return (
            str(service) if service else None,
            str(zip_code) if zip_code else None,
            str(slot) if slot else None,
        )
    return None


def _inject_slot_audit(records: list[CallRecord]) -> None:
    """Keep one deliberate, synthetic slot-correctness anomaly in the sample.

    The dashboard must prove the metric and alert are live rather than shipping a
    hardcoded 0/N. The mismatched expectation is local to the seeded monitoring data.
    """
    for index, record in enumerate(records):
        if not (record.committed_booking and record.slot_checked and record.booked_slot_id):
            continue
        expected_slot = f"{record.booked_slot_id}_expected"
        flags = [*record.qa_flags, "slot_mismatch"]
        records[index] = record.model_copy(
            update={
                "expected_slot_id": expected_slot,
                "slot_error": True,
                "qa_flags": list(dict.fromkeys(flags)),
            }
        )
        return


def _caller_phone(tenant_id: str, index: int) -> str:
    suffix = 1000 + index * 2 + (1 if tenant_id == "summit" else 0)
    return f"+1415555{suffix:04d}"


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

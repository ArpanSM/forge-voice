"""`make text-demo`: representative book, reschedule, emergency and handoff calls."""

from __future__ import annotations

import tempfile
from pathlib import Path

from forge_voice.runtime.call_runner import CallRunner
from forge_voice.runtime.models import CallResult, CallScenario

ROOT = Path(__file__).resolve().parents[3]

SCENARIOS = (
    CallScenario(
        id="demo_book",
        tenant="harborlight",
        turns=[
            "I need a drain cleaning.",
            "Sam Rivera, 12 Alder Street, 94107.",
            "Monday morning would be great.",
            "Yes, that's correct.",
        ],
    ),
    CallScenario(
        id="demo_reschedule",
        tenant="harborlight",
        turns=[
            "I need to move my drain cleaning appointment.",
            "Sam Rivera, 12 Alder Street, 94107.",
            "Tuesday at 11 would be better.",
            "Yes, that's the one.",
        ],
    ),
    CallScenario(
        id="demo_emergency",
        tenant="harborlight",
        turns=[
            "I smell gas near my furnace.",
            "No one is hurt, but it's strong.",
            "12 Alder Street, 94107.",
            "Okay, I'm leaving the house.",
        ],
    ),
    CallScenario(
        id="demo_handoff",
        tenant="harborlight",
        turns=[
            "I want to talk to a person.",
            "It's Riley Chen about a panel upgrade and a permit at 21 Harbor Blvd, 94118.",
            "Yes, transfer me.",
        ],
    ),
)


def _print(result: CallResult) -> None:
    print(f"== {result.scenario_id} ({result.tenant_id})")
    print(f"   outcome: {result.outcome.value}")
    print(f"   booking: {result.booking_id or '-'}  ticket: {result.ticket_id or '-'}")
    print(f"   transfer: {result.transfer_status.value if result.transfer_status else '-'}")
    print(f"   writes: {result.write_count}  confirmations: {int(result.confirmation_queued)}")
    print(f"   tools: {', '.join(event.name for event in result.tool_events)}")
    print(f"   assistant: {result.response_text}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="forge-voice-demo-") as directory:
        runner = CallRunner.from_repo(
            ROOT,
            outbox_path=Path(directory) / "outbox.jsonl",
        )
        for scenario in SCENARIOS:
            _print(runner.run_call(scenario))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

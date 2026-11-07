"""Weekly review script: mark a call, draft a scenario, then run the smoke suite."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from forge_voice.monitoring.service import MonitoringService


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Weekly 10-call review loop")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--call-id", help="Call to mark and turn into a scenario candidate")
    parser.add_argument("--run-smoke", action="store_true", help="Run make eval-smoke")
    args = parser.parse_args(argv)
    service = MonitoringService(
        data_dir=args.data_dir,
        root=args.root,
        profile="local",
    )
    if args.call_id:
        service.mark_review(args.call_id)
        path = service.create_scenario_candidate(args.call_id)
        print(f"marked {args.call_id}; candidate written to {path}")
    else:
        print("Weekly sample (mark one with --call-id):")
        for call in service.weekly_sample():
            print(f"  {call.call_id:32} {call.outcome.value:18} {call.tenant_id}")
    if args.run_smoke:
        result = subprocess.run(
            ["make", "eval-smoke"],
            cwd=args.root,
            check=False,
        )
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()

"""`python -m forge_voice.eval`: the evaluation harness CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forge_voice.eval.loader import VALID_SPLITS
from forge_voice.eval.runner import RunConfig, run_eval


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["hybrid", "local"], default="hybrid")
    parser.add_argument("--mode", choices=["text", "audio", "all"], default="text")
    parser.add_argument("--split", choices=sorted(VALID_SPLITS), default="release")
    parser.add_argument("--pipeline", choices=["fixed", "baseline"], default="fixed")
    parser.add_argument("--repeat-critical", action="store_true")
    parser.add_argument("--provider-check", choices=["auto", "off"], default="auto")
    parser.add_argument("--compare-fixed", action="store_true")
    parser.add_argument("--transport", choices=["session", "livekit"], default="session")
    parser.add_argument("--report-dir", default="reports")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--max-seconds", type=float, default=None)
    parser.add_argument("--root", default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[3]
    config = RunConfig(
        root=root,
        profile=args.profile,
        mode=args.mode,
        split=args.split,
        pipeline=args.pipeline,
        repeat_critical=args.repeat_critical,
        provider_check=args.provider_check,
        compare_fixed=args.compare_fixed,
        report_dir=Path(args.report_dir),
        run_id=args.run_id,
        max_seconds=args.max_seconds,
        transport=args.transport,
        quiet=args.quiet,
    )
    return run_eval(config)


if __name__ == "__main__":
    sys.exit(main())

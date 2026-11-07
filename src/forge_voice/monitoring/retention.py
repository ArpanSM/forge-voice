"""30-day pruning for raw call traces and local recordings.

The dashboard's CallStore prunes its own JSONL cache. This job covers the raw
`data/calls/*.jsonl` traces and `recordings/` files that otherwise live forever. It is
run by the web app at startup and by `make retention`; files are selected by mtime so a
synthetic demo left running for months does not grow without bound.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path


def prune_raw_data(
    data_dir: Path | str,
    recordings_dir: Path | str,
    *,
    retention_days: int = 30,
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete raw call traces and recordings older than the retention window."""
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    cutoff = (current - timedelta(days=retention_days)).timestamp()
    calls = _prune_files(Path(data_dir) / "calls", cutoff, suffix=".jsonl")
    recordings = _prune_files(Path(recordings_dir), cutoff)
    return {"calls": calls, "recordings": recordings}


def _prune_files(directory: Path, cutoff: float, *, suffix: str | None = None) -> int:
    if not directory.is_dir():
        return 0
    removed = 0
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        if suffix is not None and path.suffix != suffix:
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prune raw call traces and recordings")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--recordings-dir", type=Path, default=Path("recordings"))
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument("--now", help="ISO timestamp for a reproducible run")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else None
    removed = prune_raw_data(
        args.data_dir,
        args.recordings_dir,
        retention_days=args.retention_days,
        now=now,
    )
    print(
        f"removed {removed['calls']} raw call traces and "
        f"{removed['recordings']} recordings older than {args.retention_days} days"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

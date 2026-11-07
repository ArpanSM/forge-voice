"""Run the local dashboard app on loopback."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from forge_voice.monitoring.service import MonitoringService

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local forge-voice monitoring dashboard")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("FORGE_VOICE_DATA_DIR", "data")),
    )
    parser.add_argument("--host", default=os.environ.get("FORGE_VOICE_WEB_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("FORGE_VOICE_WEB_PORT", "8000")),
    )
    parser.add_argument(
        "--profile",
        choices=("local", "hybrid"),
        default=(
            os.environ.get("FORGE_VOICE_PROFILE", "local")
            if os.environ.get("FORGE_VOICE_PROFILE", "local") in {"local", "hybrid"}
            else "local"
        ),
    )
    parser.add_argument("--no-seed", action="store_true")
    args = parser.parse_args(argv)
    if args.host not in LOOPBACK:
        raise SystemExit("forge-voice is local-only; bind to 127.0.0.1, localhost or ::1")

    import uvicorn

    from forge_voice.web.app import create_app_from_env

    service = MonitoringService(
        data_dir=args.data_dir,
        root=args.root,
        profile=args.profile,
        seed=not args.no_seed,
    )
    app = create_app_from_env(args.root, monitoring=service)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()

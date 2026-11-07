"""Load local-only demo settings without adding a runtime dependency."""

from __future__ import annotations

import os
from pathlib import Path

AGENT_NAME = "forge-voice"


def load_env_file(path: Path | str, *, override: bool = False) -> dict[str, str]:
    """Parse KEY=VALUE lines from a local env file into os.environ.

    `.env.local` is gitignored. Values never appear in logs or the browser page.
    """
    target = Path(path)
    loaded: dict[str, str] = {}
    if not target.is_file():
        return loaded
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if not key:
            continue
        loaded[key] = value
        if override or key not in os.environ:
            os.environ[key] = value
    return loaded


def load_local_env(root: Path | str) -> dict[str, str]:
    return load_env_file(Path(root) / ".env.local")

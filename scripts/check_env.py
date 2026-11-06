"""Check the spike environment without printing secret values."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REQUIRED = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
    "DEEPGRAM_API_KEY",
    "CARTESIA_API_KEY",
]

OPTIONAL = ["ORCAROUTER_API_KEY", "GROQ_API_KEY", "TWILIO_ACCOUNT_SID"]


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def present(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    return bool(value) and not value.startswith("replace-me")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    load_env(root / ".env")

    missing = [name for name in REQUIRED if not present(name)]
    for name in REQUIRED:
        print(f"{'ok' if present(name) else 'missing':7} {name}")
    for name in OPTIONAL:
        print(f"{'ok' if present(name) else 'optional':7} {name}")

    if missing:
        print("\nFill .env from .env.example, or run the local text fallback.")
        return 1
    print("\nEnvironment looks ready for the hosted spike.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

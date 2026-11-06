"""Check the spike environment without printing secret values."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REQUIRED = [
    "LIVEKIT_URL",
    "LIVEKIT_API_KEY",
    "LIVEKIT_API_SECRET",
]

OPTIONAL = [
    "ORCAROUTER_API_KEY",
    "GROQ_API_KEY",
    "DEEPGRAM_API_KEY",
    "CARTESIA_API_KEY",
    "TWILIO_ACCOUNT_SID",
    "LFM3_AUDIO_BASE_URL",
    "LFM3_AUDIO_MODEL",
]


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

    provider = os.environ.get("LLM_PROVIDER", "lfm3").strip().lower()
    print(f"{'ok':7} LLM_PROVIDER={provider}")
    if provider == "orcarouter" and not present("ORCAROUTER_API_KEY"):
        print("missing ORCAROUTER_API_KEY for LLM_PROVIDER=orcarouter")
        missing.append("ORCAROUTER_API_KEY")
    if provider == "groq" and not present("GROQ_API_KEY"):
        print("missing GROQ_API_KEY for LLM_PROVIDER=groq")
        missing.append("GROQ_API_KEY")

    for name in OPTIONAL:
        print(f"{'ok' if present(name) else 'unused':7} {name}")

    if missing:
        print("\nFill .env from .env.example, or run the local text fallback.")
        return 1
    print("\nEnvironment looks ready (LFM3 audio + local/LLM profile).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

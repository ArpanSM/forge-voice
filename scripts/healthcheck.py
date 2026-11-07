#!/usr/bin/env python3
"""CLI wrapper for the local stack health probes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forge_voice.deploy.health import main

if __name__ == "__main__":
    raise SystemExit(main())

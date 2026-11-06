"""Production-random token material; tests inject a deterministic factory."""

from __future__ import annotations

import secrets


def random_token() -> str:
    return secrets.token_hex(16)

"""Injected clocks keep policy tests and text demos deterministic."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    @property
    def now(self) -> datetime: ...


class FixedClock:
    """A mutable fixed clock; advancing is explicit and never reads the wall clock."""

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("FixedClock requires a timezone-aware datetime")
        self._now = now

    @property
    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        self._now = self._now + delta
        return self._now

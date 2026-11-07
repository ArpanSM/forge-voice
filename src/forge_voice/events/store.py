"""JSONL call store for the read-only dashboard.

The store is deliberately one-directional for the dashboard: it appends the #4 call result
and reads it back. Booking state stays in the #4 SQLite adapter.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from forge_voice.events.models import CallRecord
from forge_voice.monitoring.filters import CallFilters


class CallStore:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        retention_days: int = 30,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "monitoring" / "calls.jsonl"
        self.retention_days = retention_days
        self._now = now or (lambda: datetime.now(UTC))

    def records(self, *, filters: CallFilters | None = None) -> list[CallRecord]:
        records = [
            record
            for record in self._read()
            if record.started_at >= self._cutoff() and (filters is None or filters.matches(record))
        ]
        return sorted(records, key=lambda record: record.started_at, reverse=True)

    def get(self, call_id: str) -> CallRecord | None:
        return next((record for record in self.records() if record.call_id == call_id), None)

    def all_records(self) -> list[CallRecord]:
        """Every stored record, including expired records awaiting pruning."""
        return sorted(self._read(), key=lambda record: record.started_at, reverse=True)

    def cutoff(self) -> datetime:
        return self._cutoff()

    def append(self, records: Iterable[CallRecord]) -> None:
        incoming = list(records)
        if not incoming:
            return
        existing = {record.call_id for record in self._read()}
        fresh = [record for record in incoming if record.call_id not in existing]
        if not fresh:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            for record in fresh:
                handle.write(record.model_dump_json() + "\n")

    def replace_all(self, records: Iterable[CallRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json() + "\n")
        os.replace(temporary, self.path)

    def prune(self) -> int:
        records = self.records()
        all_records = self._read()
        removed = len(all_records) - len(records)
        if removed:
            self.replace_all(records)
        return removed

    def _read(self) -> list[CallRecord]:
        if not self.path.exists():
            return []
        records: list[CallRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(CallRecord.model_validate(json.loads(line)))
        return records

    def _cutoff(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now - timedelta(days=self.retention_days)

"""File-backed outbox for synthetic SMS/email confirmations.

The database row is the durable queue. `drain` writes rows in order, fsyncs each line, and only
then marks the row drained. A partial trailing line from a crashed write is ignored on reload.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.domain import ConfirmationRecord


class Outbox:
    """Append-only JSONL outbox; an in-memory list when no path is supplied."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._messages: list[ConfirmationRecord] = []
        if self.path is not None and self.path.is_file():
            lines = self.path.read_text(encoding="utf-8").splitlines(keepends=True)
            kept: list[str] = []
            truncated = False
            for index, line in enumerate(lines):
                if not line.strip():
                    kept.append(line)
                    continue
                try:
                    self._messages.append(ConfirmationRecord.model_validate_json(line))
                except ValueError:
                    if index != len(lines) - 1:
                        raise
                    truncated = True
                    continue
                kept.append(line)
            if truncated:
                self.path.write_text("".join(kept), encoding="utf-8")

    @property
    def messages(self) -> list[ConfirmationRecord]:
        return list(self._messages)

    def send(self, record: ConfirmationRecord) -> ConfirmationRecord:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n"
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
        self._messages.append(record)
        return record

    def drain(self, store: SQLiteAdapter, at: datetime, tenant_id: str) -> int:
        drained = 0
        for record in store.list_undrained_confirmations(tenant_id):
            self.send(record)
            store.mark_confirmation_drained(tenant_id, record.message_id, at)
            drained += 1
        return drained

    def __len__(self) -> int:
        return len(self._messages)


def confirmation_record(
    *,
    message_id: str,
    tenant_id: str,
    booking_id: str,
    to: str,
    created_at: datetime,
    status: str = "queued",
) -> ConfirmationRecord:
    return ConfirmationRecord(
        message_id=message_id,
        tenant_id=tenant_id,
        booking_id=booking_id,
        to=to,
        status="queued" if status == "queued" else "failed",
        created_at=created_at,
    )

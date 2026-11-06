"""File-backed outbox for synthetic SMS/email confirmations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from forge_voice.domain import ConfirmationRecord


class Outbox:
    """Append-only JSONL outbox; an in-memory list when no path is supplied."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._messages: list[ConfirmationRecord] = []
        if self.path is not None and self.path.is_file():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._messages.append(ConfirmationRecord.model_validate_json(line))

    @property
    def messages(self) -> list[ConfirmationRecord]:
        return list(self._messages)

    def send(self, record: ConfirmationRecord) -> ConfirmationRecord:
        self._messages.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")
        return record

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

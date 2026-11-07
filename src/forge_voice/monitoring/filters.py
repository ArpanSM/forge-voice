"""Dashboard call filters."""

from __future__ import annotations

from datetime import date

from forge_voice.models import StrictModel
from forge_voice.policy.state import CallOutcome


class CallFilters(StrictModel):
    tenant: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    outcome: CallOutcome | None = None

    def matches(self, record) -> bool:
        if self.tenant is not None and record.tenant_id != self.tenant:
            return False
        started = record.started_at.date()
        if self.from_date is not None and started < self.from_date:
            return False
        if self.to_date is not None and started > self.to_date:
            return False
        return not (self.outcome is not None and record.outcome is not self.outcome)

"""Shared tenant schedule helpers."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from forge_voice.tenants.models import TenantConfig


def next_business_day_window(tenant: TenantConfig, at: datetime) -> tuple[datetime, datetime]:
    zone = ZoneInfo(tenant.timezone)
    candidate = at.astimezone(zone).date() + timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in tenant.holidays:
        candidate += timedelta(days=1)
    start = datetime.combine(candidate, time(8, 0), tzinfo=zone)
    return start, start + timedelta(hours=4)

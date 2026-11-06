from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from forge_voice.clock import FixedClock
from forge_voice.tenants import load_all_tenants

ROOT = Path(__file__).resolve().parents[1]
TENANTS_DIR = ROOT / "tenants"
SEEDS_DIR = ROOT / "fixtures" / "corpus" / "seed"
LA = ZoneInfo("America/Los_Angeles")
DEFAULT_NOW = datetime(2026, 11, 6, 8, 0, tzinfo=LA)


@pytest.fixture
def tenants():
    return load_all_tenants(TENANTS_DIR)


@pytest.fixture
def harborlight(tenants):
    return tenants["harborlight"]


@pytest.fixture
def summit(tenants):
    return tenants["summit"]


@pytest.fixture
def clock():
    return FixedClock(DEFAULT_NOW)


@pytest.fixture
def seed_data():
    return {
        slug: json.loads((SEEDS_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        for slug in ("harborlight", "summit")
    }

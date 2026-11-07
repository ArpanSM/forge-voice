from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.eval.provider_text import (
    ProviderTextInterpreter,
    TextProviderError,
    build_text_interpreter,
)
from forge_voice.providers import FakeProvider, ProviderResponse
from forge_voice.runtime import CallRunner, CallScenario
from forge_voice.runtime.interpreter import extract_facts
from forge_voice.tenants import load_all_tenants

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 6, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


def _interpreter(text: str, *, tenants=None) -> ProviderTextInterpreter:
    return ProviderTextInterpreter(
        provider=FakeProvider([ProviderResponse(text=text)]),
        tenants=tenants or load_all_tenants(ROOT / "tenants"),
        model="fake-text",
    )


def test_provider_text_interpreter_extracts_intent_and_entities() -> None:
    interpreter = _interpreter(
        '{"intent":"book","service_id":"drain_cleaning","name":"Sam Rivera",'
        '"phone":"+14155550101","address_line1":"12 Alder Street","city":"San Francisco",'
        '"state":"CA","zip":"94107","preferred_day":"2026-11-09","preferred_window":"morning",'
        '"preferred_hour":"09:00","wants_human":false}'
    )
    tenant = interpreter.tenants["harborlight"]

    facts = interpreter.extract(
        scenario_id="text_book_01",
        tenant=tenant,
        turns=["I need a drain cleaning."],
        caller_phone="+14155550101",
        now=NOW,
    )

    assert facts.intent == "book"
    assert facts.service_id == "drain_cleaning"
    assert facts.name == "Sam Rivera"
    assert facts.address is not None
    assert facts.address.zip == "94107"
    assert facts.preferred_day.isoformat() == "2026-11-09"


def test_provider_text_prefetch_batches_and_caches() -> None:
    batch = (
        '{"results":['
        '{"id":0,"intent":"book","service_id":"drain_cleaning","name":"Sam Rivera",'
        '"phone":"+14155550101","address_line1":"12 Alder Street","zip":"94107"},'
        '{"id":1,"intent":"booking","service_id":"ac_repair","name":"Priya Shah",'
        '"phone":"+14085550101","address_line1":"88 Meridian Way","zip":"95125"}'
        "]}"
    )
    provider = FakeProvider([ProviderResponse(text=batch)])
    interpreter = ProviderTextInterpreter(
        provider=provider,
        tenants=load_all_tenants(ROOT / "tenants"),
        model="fake-text",
        min_interval_seconds=0.001,
    )
    tenants = interpreter.tenants
    cases = [
        {
            "scenario_id": "text_book_01",
            "tenant": tenants["harborlight"],
            "turns": ["I need a drain cleaning.", "Sam Rivera, 12 Alder Street, 94107."],
            "caller_phone": "+14155550101",
            "now": NOW,
        },
        {
            "scenario_id": "text_book_03",
            "tenant": tenants["summit"],
            "turns": ["My AC is not cooling.", "Priya Shah, 88 Meridian Way, 95125."],
            "caller_phone": "+14085550101",
            "now": NOW,
        },
    ]

    interpreter.prefetch(cases)

    assert len(provider.calls) == 1
    first = interpreter.extract(
        scenario_id="text_book_01",
        tenant=tenants["harborlight"],
        turns=cases[0]["turns"],
        caller_phone="+14155550101",
        now=NOW,
    )
    second = interpreter.extract(
        scenario_id="text_book_03",
        tenant=tenants["summit"],
        turns=cases[1]["turns"],
        caller_phone="+14085550101",
        now=NOW,
    )
    assert first.name == "Sam Rivera"
    assert first.intent == "book"
    assert second.service_id == "ac_repair"
    assert second.intent == "book"
    assert len(provider.calls) == 1


def test_provider_text_interpreter_rejects_unusable_json() -> None:
    interpreter = _interpreter("I can book that for you.")

    with pytest.raises(TextProviderError, match="no usable JSON"):
        interpreter.extract(
            scenario_id="text_book_01",
            tenant=interpreter.tenants["harborlight"],
            turns=["I need a drain cleaning."],
            caller_phone="+14155550101",
            now=NOW,
        )


def test_hybrid_text_interpreter_fails_closed_without_a_key() -> None:
    with pytest.raises(TextProviderError, match="GROQ_API_KEY"):
        build_text_interpreter(ROOT, "hybrid", {})


def test_local_text_interpreter_fails_closed_when_lfm3_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", fail)

    with pytest.raises(TextProviderError, match="LFM3"):
        build_text_interpreter(ROOT, "local", {})


def test_call_runner_uses_the_provider_supplied_intent() -> None:
    runner = CallRunner.from_repo(ROOT)
    tenant = runner._tenants["harborlight"]
    base = extract_facts(
        tenant,
        ["I want to talk to a person."],
        SQLiteAdapter(":memory:"),
        NOW,
        caller_phone="+14155550101",
    )
    facts = replace(base, intent="human")

    result = runner.run_call(
        CallScenario(
            id="text_provider_intent",
            tenant="harborlight",
            turns=["I want to talk to a person."],
            caller_phone="+14155550101",
        ),
        facts=facts,
    )

    assert result.intent == "human"
    assert result.outcome in {"callback", "transferred"}

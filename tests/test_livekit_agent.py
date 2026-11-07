"""The LiveKit worker wires the tested plan and tools without changing policy.

These tests need the optional demo extra. The offline plan/tools/policy tests run
without LiveKit and are the fallback when this module is skipped explicitly.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

try:
    import livekit.agents  # noqa: F401

    HAS_LIVEKIT = True
except ImportError:
    HAS_LIVEKIT = False

if not HAS_LIVEKIT:
    pytest.skip(
        "livekit-agents is an optional demo dependency; offline policy tests still run",
        allow_module_level=True,
    )

from forge_voice.runtime import livekit_agent
from forge_voice.runtime.session import plan_session

ROOT = Path(__file__).resolve().parents[1]


def test_build_agent_session_uses_local_lfm3_audio_and_hybrid_groq_llm() -> None:
    plan = plan_session("hybrid", {"GROQ_API_KEY": "test-key"})

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        session = livekit_agent.build_agent_session(plan)

    assert session.stt.model == "lfm3-audio-2b"
    assert session.tts.model == "lfm3-audio-2b"
    assert session.llm.model == "qwen/qwen3.8-27b"
    assert session.options.user_away_timeout is None
    assert session.options.turn_handling["interruption"]["enabled"] is True
    assert session.options.turn_handling["interruption"]["min_words"] == 0
    assert session.options.turn_handling["endpointing"]["max_delay"] == 1.0


def test_build_agent_session_keeps_the_local_profile_fully_local() -> None:
    plan = plan_session("local", {})

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        session = livekit_agent.build_agent_session(plan)

    assert session.llm.model == "lfm3-audio-2b"
    assert session.stt.model == "lfm3-audio-2b"
    assert session.tts.provider == "lfm3"


def test_build_tools_exposes_exactly_the_eight_product_tools() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from forge_voice.runtime.audio_session import AudioCallSession

    call = AudioCallSession.from_repo(
        ROOT,
        "harborlight",
        "call_tools_0001",
        now=datetime(2026, 11, 6, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles")),
    )

    tools = livekit_agent.build_tools(call)

    assert [tool.info.name for tool in tools] == [
        "lookup_customer",
        "get_service_area",
        "get_availability",
        "book_appointment",
        "reschedule_appointment",
        "cancel_appointment",
        "create_emergency_ticket",
        "transfer_to_human",
    ]

"""The LiveKit worker wires the tested plan and tools without changing policy.

The plan tests in `test_session_plan.py` and the audio-session tests run without
LiveKit. The tests below are skipped individually with a visible reason when the
optional demo extra is not installed.
"""

from __future__ import annotations

import asyncio
import warnings
from pathlib import Path

import pytest

from forge_voice.runtime.session import plan_session

try:
    import livekit.agents  # noqa: F401

    HAS_LIVEKIT = True
except ImportError:
    HAS_LIVEKIT = False

requires_livekit = pytest.mark.skipif(
    not HAS_LIVEKIT,
    reason="livekit-agents is an optional demo dependency; offline plan/tools tests still run",
)

ROOT = Path(__file__).resolve().parents[1]


def session_facts(plan) -> dict[str, object]:
    from forge_voice.runtime import livekit_agent

    async def inspect() -> dict[str, object]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            session = livekit_agent.build_agent_session(plan)
        try:
            return {
                "stt_model": session.stt.model,
                "tts_model": session.tts.model,
                "tts_provider": session.tts.provider,
                "llm_model": session.llm.model,
                "user_away_timeout": session.options.user_away_timeout,
                "turn_handling": session.options.turn_handling,
            }
        finally:
            await session.aclose()

    return asyncio.run(inspect())


@requires_livekit
def test_build_agent_session_keeps_stt_and_tts_local_in_hybrid() -> None:
    facts = session_facts(plan_session("hybrid", {"GROQ_API_KEY": "test-key"}))

    assert facts["stt_model"] == "lfm3-audio-2b"
    assert facts["tts_model"] == "lfm3-audio-2b"
    assert facts["tts_provider"] == "lfm3"


@requires_livekit
def test_build_agent_session_routes_hybrid_llm_to_groq() -> None:
    facts = session_facts(plan_session("hybrid", {"GROQ_API_KEY": "test-key"}))

    assert facts["llm_model"] == "qwen/qwen3.8-27b"


@requires_livekit
def test_build_agent_session_uses_local_llm_in_local_profile() -> None:
    facts = session_facts(plan_session("local", {}))

    assert facts["llm_model"] == "lfm3-audio-2b"
    assert facts["stt_model"] == "lfm3-audio-2b"


@requires_livekit
def test_build_agent_session_turn_taking_is_barge_in_first() -> None:
    facts = session_facts(plan_session("local", {}))
    turn = facts["turn_handling"]

    assert facts["user_away_timeout"] is None
    assert turn["interruption"]["enabled"] is True
    assert turn["interruption"]["min_words"] == 0
    assert turn["endpointing"]["max_delay"] == 1.0


@requires_livekit
def test_build_tools_exposes_exactly_the_eight_product_tools() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from forge_voice.runtime import livekit_agent
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


class RejectingContext:
    def __init__(self) -> None:
        self.reason: str | None = None

    async def connect(self) -> None:
        return None

    async def wait_for_participant(self):
        class Participant:
            metadata = "[]"
            identity = "caller"

        return Participant()

    @property
    def room(self):
        class Room:
            name = "forge-voice-harborlight-call_1"

        return Room()

    def shutdown(self, reason: str = "") -> None:
        self.reason = reason


@requires_livekit
def test_entrypoint_rejects_malformed_claim_and_shuts_down(monkeypatch) -> None:
    from forge_voice.runtime import livekit_agent

    monkeypatch.setenv("LIVEKIT_API_SECRET", "local-test-secret-that-is-long-enough")
    context = RejectingContext()

    asyncio.run(livekit_agent.entrypoint(context))

    assert context.reason is not None
    assert "tenant claim rejected" in context.reason

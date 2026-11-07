"""The LiveKit worker wires the tested plan and tools without changing policy."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

pytest.importorskip("livekit.agents")

from forge_voice.runtime import livekit_agent
from forge_voice.runtime.audio_session import AudioCallSession
from forge_voice.runtime.session import plan_session
from forge_voice.web.claims import ClaimError, TenantClaimSigner

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 6, 8, 0, tzinfo=ZoneInfo("America/Los_Angeles"))


class RecordingSession:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class RecordingStt:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class RecordingLlm:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class RecordingTts:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


def test_build_agent_session_routes_hybrid_llm_to_groq_and_audio_to_lfm3(monkeypatch) -> None:
    monkeypatch.setattr(livekit_agent, "AgentSession", RecordingSession)
    monkeypatch.setattr(livekit_agent, "LFM3TTS", RecordingTts)
    monkeypatch.setattr(livekit_agent.openai, "STT", RecordingStt)
    monkeypatch.setattr(livekit_agent.openai, "LLM", RecordingLlm)
    monkeypatch.setattr(livekit_agent.silero.VAD, "load", lambda: "vad")

    plan = plan_session("hybrid", {"GROQ_API_KEY": "test-key"})
    session = livekit_agent.build_agent_session(plan)

    assert isinstance(session, RecordingSession)
    assert session.kwargs["stt"].kwargs["base_url"] == "http://127.0.0.1:8082/v1"
    assert session.kwargs["tts"].kwargs["base_url"] == "http://127.0.0.1:8082"
    llm = session.kwargs["llm"]
    assert llm.kwargs["base_url"] == "https://api.groq.com/openai/v1"
    assert llm.kwargs["model"] == "qwen/qwen3.8-27b"
    assert session.kwargs["user_away_timeout"] is None
    turn = session.kwargs["turn_handling"]
    assert turn["interruption"]["enabled"] is True
    assert turn["endpointing"]["max_delay"] == 1.0


def test_build_tools_exposes_exactly_the_eight_product_tools() -> None:
    call = AudioCallSession.from_repo(ROOT, "harborlight", "call_tools_0001", now=NOW)

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


def test_participant_claim_must_be_signed_and_match_its_tenant() -> None:
    signer = TenantClaimSigner("local-test-secret-that-is-long-enough", ttl_seconds=120)
    signed = signer.issue(
        "harborlight",
        call_id="call_1",
        room="forge-voice-harborlight-call_1",
        now=datetime.now().astimezone(),
    )
    metadata = json.dumps({"tenant": "harborlight", "tenant_claim": signed.token})

    claim = livekit_agent.parse_participant_claim(metadata, "local-test-secret-that-is-long-enough")
    assert claim.tenant == "harborlight"

    tampered = metadata.replace("harborlight", "summit")
    with pytest.raises(ClaimError):
        livekit_agent.parse_participant_claim(tampered, "local-test-secret-that-is-long-enough")

"""The audio session plan keeps every endpoint local except the approved hybrid LLM."""

from __future__ import annotations

import pytest

from forge_voice.runtime.session import (
    Profile,
    SessionPlanningError,
    plan_session,
)


def test_local_profile_uses_only_the_host_lfm3_service() -> None:
    plan = plan_session(Profile.local, {})

    assert plan.llm.provider == "lfm3"
    assert plan.llm.base_url == "http://127.0.0.1:8082/v1"
    assert plan.llm.model == "lfm3-audio-2b"
    assert plan.stt.provider == "lfm3"
    assert plan.stt.base_url == "http://127.0.0.1:8082"
    assert plan.tts.provider == "lfm3"
    assert plan.tts.base_url == "http://127.0.0.1:8082"
    assert plan.external_hosts() == ()


def test_hybrid_profile_uses_groq_only_for_the_llm() -> None:
    plan = plan_session(Profile.hybrid, {"GROQ_API_KEY": "test-key"})

    assert plan.llm.provider == "groq"
    assert plan.llm.base_url == "https://api.groq.com/openai/v1"
    assert plan.llm.model == "qwen/qwen3.8-27b"
    assert plan.stt.provider == "lfm3"
    assert plan.tts.provider == "lfm3"
    assert plan.external_hosts() == ("api.groq.com",)


def test_hybrid_profile_requires_a_groq_key() -> None:
    with pytest.raises(SessionPlanningError, match="GROQ_API_KEY"):
        plan_session(Profile.hybrid, {})


def test_container_override_reaches_the_host_lfm3_service() -> None:
    plan = plan_session(
        Profile.local,
        {"LFM3_AUDIO_BASE_URL": "http://host.docker.internal:8082"},
    )

    assert plan.llm.base_url == "http://host.docker.internal:8082/v1"
    assert plan.tts.base_url == "http://host.docker.internal:8082"


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(SessionPlanningError, match="profile"):
        plan_session("cloud", {})


def test_turn_taking_keeps_barge_in_short_replies_and_no_proactive_silence() -> None:
    plan = plan_session(Profile.local, {})
    turn = plan.turn_taking

    assert turn.allow_interruptions is True
    assert turn.min_interruption_duration == 0.3
    assert turn.min_interruption_words == 0
    assert turn.false_interruption_timeout == 1.0
    assert turn.resume_false_interruption is True
    assert turn.user_away_timeout is None
    assert turn.max_reply_tokens == 120
    assert turn.endpointing_min_delay == 0.3
    assert turn.endpointing_max_delay == 1.0


def test_plan_rejects_a_non_local_lfm3_url_for_the_local_profile() -> None:
    with pytest.raises(SessionPlanningError, match="local"):
        plan_session(Profile.local, {"LFM3_AUDIO_BASE_URL": "https://example.com"})

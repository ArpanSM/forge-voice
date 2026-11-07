"""Pure session plan for the fully local and hybrid voice profiles.

The plan is the seam the worker builds from. It names every endpoint and model before
any LiveKit object exists, so the no-Cloud, no-paid-provider boundary is testable offline.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from urllib.parse import urlparse

from pydantic import Field

from forge_voice.models import StrictModel

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "host.docker.internal"})
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "qwen/qwen3.8-27b"
LFM3_MODEL = "lfm3-audio-2b"
DEFAULT_LFM3_BASE_URL = "http://127.0.0.1:8082"


class SessionPlanningError(ValueError):
    """A profile is unknown, incomplete or points at a disallowed endpoint."""


class Profile(StrEnum):
    local = "local"
    hybrid = "hybrid"


class EndpointPlan(StrictModel):
    provider: str
    base_url: str
    model: str
    api_key: str | None = None
    api_key_env: str | None = None


class TurnTakingPlan(StrictModel):
    allow_interruptions: bool = True
    min_interruption_duration: float = Field(default=0.3, gt=0)
    min_interruption_words: int = Field(default=0, ge=0)
    false_interruption_timeout: float = Field(default=1.0, gt=0)
    resume_false_interruption: bool = True
    user_away_timeout: float | None = None
    max_reply_tokens: int = Field(default=120, gt=0)
    endpointing_min_delay: float = Field(default=0.3, ge=0)
    endpointing_max_delay: float = Field(default=1.0, ge=0)


class SessionPlan(StrictModel):
    profile: Profile
    stt: EndpointPlan
    tts: EndpointPlan
    llm: EndpointPlan
    turn_taking: TurnTakingPlan = Field(default_factory=TurnTakingPlan)
    language: str = "en"
    tts_voice: str = "female"

    def external_hosts(self) -> tuple[str, ...]:
        hosts: set[str] = set()
        for endpoint in (self.stt, self.tts, self.llm):
            host = (urlparse(endpoint.base_url).hostname or "").lower()
            if host and host not in LOCAL_HOSTS:
                hosts.add(host)
        return tuple(sorted(hosts))


def _lfm3_base(env: Mapping[str, str]) -> str:
    return env.get("LFM3_AUDIO_BASE_URL", DEFAULT_LFM3_BASE_URL).rstrip("/")


def _require_local_base(base_url: str) -> None:
    host = (urlparse(base_url).hostname or "").lower()
    if host not in LOCAL_HOSTS:
        raise SessionPlanningError(
            "the local profile requires LFM3 on 127.0.0.1, localhost or "
            f"host.docker.internal, not {host or base_url!r}"
        )


def plan_session(profile: Profile | str, env: Mapping[str, str] | None = None) -> SessionPlan:
    values = dict(env or {})
    try:
        selected = Profile(profile)
    except ValueError as exc:
        raise SessionPlanningError(
            f"unknown profile {profile!r}; expected one of {[p.value for p in Profile]}"
        ) from exc

    base_url = _lfm3_base(values)
    language = values.get("LFM3_LANG", "en")
    voice = values.get("LFM3_TTS_VOICE", "female")
    tts = EndpointPlan(provider="lfm3", base_url=base_url, model=LFM3_MODEL)
    stt = EndpointPlan(provider="lfm3", base_url=base_url, model=LFM3_MODEL)

    if selected is Profile.local:
        _require_local_base(base_url)
        llm = EndpointPlan(
            provider="lfm3",
            base_url=f"{base_url}/v1",
            model=values.get("LFM3_AUDIO_MODEL", LFM3_MODEL),
        )
    else:
        groq_key = values.get("GROQ_API_KEY", "").strip()
        if not groq_key:
            raise SessionPlanningError(
                "the hybrid profile requires GROQ_API_KEY; use make demo for the local profile"
            )
        llm = EndpointPlan(
            provider="groq",
            base_url=GROQ_BASE_URL,
            model=values.get("GROQ_MODEL", GROQ_MODEL),
            api_key=groq_key,
            api_key_env="GROQ_API_KEY",
        )

    return SessionPlan(
        profile=selected,
        stt=stt,
        tts=tts,
        llm=llm,
        language=language,
        tts_voice=voice,
    )

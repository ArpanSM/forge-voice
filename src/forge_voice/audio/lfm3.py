"""Minimal LFM3 TTS HTTP client used only by the fixture generator.

It is deliberately separate from the LiveKit adapter so the offline test suite never
imports LiveKit and the fixture command can run without the agent stack.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from forge_voice.runtime.audio_io import parse_pcm16_wav, tts_request_payload


class Lfm3TtsError(RuntimeError):
    """The local LFM3 TTS service could not synthesize a fixture."""


class Lfm3TtsClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8082", *, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> Lfm3TtsClient:
        return cls(os.environ.get("LFM3_AUDIO_BASE_URL", "http://127.0.0.1:8082"))

    def synthesize(self, text: str, *, voice: str, lang: str, seed: int) -> bytes:
        payload = tts_request_payload(text, voice=voice, lang=lang, seed=seed)
        request = urllib.request.Request(
            f"{self.base_url}/tts",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            raise Lfm3TtsError(
                f"LFM3 TTS at {self.base_url} is unavailable; start it with `lfm3 audio`"
            ) from exc
        parse_pcm16_wav(data)
        return data

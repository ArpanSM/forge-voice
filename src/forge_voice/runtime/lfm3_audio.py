"""LiveKit TTS adapter for the local LFM3-Audio-2B `/tts` endpoint.

The endpoint streams a RIFF/WAVE body with a chunked transfer. We parse the
header and push PCM16 chunks into LiveKit as they arrive, so the first audio
frame is not delayed by full synthesis.
"""

from __future__ import annotations

import uuid

import httpx
from livekit.agents import tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions

from forge_voice.runtime.audio_io import WavPcmStreamParser, tts_request_payload


class LFM3TTS(tts.TTS):
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8082",
        voice: str = "female",
        lang: str = "en",
        sample_rate: int = 24000,
        timeout: float = 60.0,
    ) -> None:
        super().__init__(
            capabilities=tts.TTSCapabilities(streaming=False),
            sample_rate=sample_rate,
            num_channels=1,
        )
        self._base_url = base_url.rstrip("/")
        self._voice = voice
        self._lang = lang
        self._timeout = timeout

    @property
    def model(self) -> str:
        return "lfm3-audio-2b"

    @property
    def provider(self) -> str:
        return "lfm3"

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
    ) -> LFM3ChunkedStream:
        return LFM3ChunkedStream(tts=self, input_text=text, conn_options=conn_options)


class LFM3ChunkedStream(tts.ChunkedStream):
    async def _run(self, output_emitter: tts.AudioEmitter) -> None:
        output_emitter.initialize(
            request_id=uuid.uuid4().hex,
            sample_rate=self._tts.sample_rate,
            num_channels=1,
            mime_type="audio/pcm",
            stream=False,
        )
        payload = tts_request_payload(
            self.input_text,
            voice=self._tts._voice,
            lang=self._tts._lang,
            seed=_stable_seed(self.input_text),
        )
        payload["stream"] = True
        parser = WavPcmStreamParser()
        async with (
            httpx.AsyncClient(timeout=self._tts._timeout) as client,
            client.stream("POST", f"{self._tts._base_url}/tts", json=payload) as response,
        ):
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                for pcm in parser.feed(chunk):
                    output_emitter.push(pcm)
            for pcm in parser.finish():
                output_emitter.push(pcm)


def _stable_seed(text: str) -> int:
    import hashlib

    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)

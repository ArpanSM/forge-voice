"""LFM3 Audio adapters for the voice spike.

STT uses the OpenAI-compatible /v1/audio/transcriptions endpoint through the
LiveKit OpenAI plugin. TTS uses the local /tts endpoint, which streams a WAV
with chunked transfer; this adapter parses the WAV header and pushes PCM16
frames into LiveKit as they arrive.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from livekit import rtc
from livekit.agents import tts
from livekit.agents.types import DEFAULT_API_CONNECT_OPTIONS, APIConnectOptions


class WavPcmStreamParser:
    """Parse a streaming WAV and yield PCM data bytes."""

    def __init__(self) -> None:
        self._buf = b""
        self._header_done = False
        self._data_remaining: int | None = None

    def feed(self, chunk: bytes) -> list[bytes]:
        self._buf += chunk
        out: list[bytes] = []

        while True:
            if not self._header_done:
                if len(self._buf) < 12:
                    break
                if self._buf[:4] != b"RIFF" or self._buf[8:12] != b"WAVE":
                    raise ValueError("LFM3 TTS did not return a RIFF/WAVE stream")
                pos = 12
                while True:
                    if len(self._buf) < pos + 8:
                        self._buf = self._buf[pos:]
                        return out
                    chunk_id = self._buf[pos : pos + 4]
                    size = int.from_bytes(self._buf[pos + 4 : pos + 8], "little")
                    body_start = pos + 8
                    if chunk_id == b"data":
                        available = len(self._buf) - body_start
                        take = min(size, available)
                        if take:
                            out.append(self._buf[body_start : body_start + take])
                        self._header_done = True
                        self._data_remaining = size - take
                        self._buf = self._buf[body_start + take :]
                        break
                    if len(self._buf) < body_start + size:
                        self._buf = self._buf[pos:]
                        return out
                    pos = body_start + size
                continue

            if self._data_remaining is not None:
                if self._data_remaining <= 0:
                    self._buf = b""
                    break
                take = min(self._data_remaining, len(self._buf))
                if take:
                    out.append(self._buf[:take])
                    self._data_remaining -= take
                    self._buf = self._buf[take:]
                if self._data_remaining <= 0:
                    self._buf = b""
                break
            break

        return out

    def finish(self) -> list[bytes]:
        return []


class LFM3TTS(tts.TTS):
    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:8082",
        voice: str = "female",
        lang: str = "en",
        sample_rate: int = 24000,
        timeout: float = 30.0,
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

        parser = WavPcmStreamParser()
        async with httpx.AsyncClient(timeout=self._tts._timeout) as client:
            stream = client.stream(
                "POST",
                f"{self._tts._base_url}/tts",
                json={
                    "input": self.input_text,
                    "voice": self._tts._voice,
                    "lang": self._tts._lang,
                    "stream": True,
                },
            )
            async with stream as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    for pcm in parser.feed(chunk):
                        output_emitter.push(pcm)
                for pcm in parser.finish():
                    output_emitter.push(pcm)


async def write_stream_to_wav(
    stream: AsyncIterator[tts.SynthesizedAudio], path: str
) -> dict[str, float]:
    """Collect audio frames, write a WAV, and return first-frame/total timing."""
    import time

    start = time.perf_counter()
    first: float | None = None
    frames: list[rtc.AudioFrame] = []
    async for ev in stream:
        if first is None:
            first = time.perf_counter() - start
        frames.append(ev.frame)
    total = time.perf_counter() - start
    if frames:
        combined = rtc.combine_audio_frames(frames)
        import asyncio

        await asyncio.to_thread(Path(path).write_bytes, combined.to_wav_bytes())
    return {"first_frame_s": first or 0.0, "total_s": total, "frames": len(frames)}

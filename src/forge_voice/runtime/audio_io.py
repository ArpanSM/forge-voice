"""Pure WAV parsing, streaming and LFM3 request shaping.

The LiveKit adapter and the fixture generator both use this module. It imports no
LiveKit, HTTP client or network library, so it is safe to test offline.
"""

from __future__ import annotations

import io
import struct
import wave
from dataclasses import dataclass


class WavFormatError(ValueError):
    """The TTS response is not the PCM WAV the local service promises."""


@dataclass(frozen=True)
class Pcm16Wav:
    sample_rate: int
    channels: int
    sample_width: int
    frames: bytes
    frame_count: int

    @property
    def duration_ms(self) -> int:
        if self.sample_rate <= 0:
            return 0
        return round(self.frame_count * 1000 / self.sample_rate)


def parse_pcm16_wav(data: bytes) -> Pcm16Wav:
    """Parse a PCM16 WAV and return its raw interleaved frames."""
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            frames = handle.readframes(frame_count)
            if handle.getcomptype() != "NONE":
                raise WavFormatError("LFM3 audio must be uncompressed PCM")
    except (wave.Error, EOFError) as exc:
        raise WavFormatError(f"invalid WAV data: {exc}") from exc
    if sample_width != 2:
        raise WavFormatError("LFM3 audio must be 16-bit PCM")
    if channels not in (1, 2):
        raise WavFormatError("LFM3 audio must be mono or stereo")
    if sample_rate < 8000:
        raise WavFormatError("LFM3 audio sample rate is too low")
    if len(frames) != frame_count * channels * sample_width:
        raise WavFormatError("WAV frame count does not match the payload")
    return Pcm16Wav(
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        frames=frames,
        frame_count=frame_count,
    )


class WavPcmStreamParser:
    """Parse a streaming RIFF/WAVE response into raw PCM chunks.

    The parser keeps the full RIFF prefix until the `data` chunk is found, so a
    header split across arbitrary network chunks is parsed correctly. Once the
    declared data length is reached, any trailing bytes are ignored.
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._pos = 0
        self._riff_checked = False
        self._data_remaining: int | None = None
        self._done = False

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk:
            return []
        if self._done:
            return []
        self._buf.extend(chunk)
        out: list[bytes] = []

        if not self._riff_checked:
            if len(self._buf) < 12:
                return out
            if bytes(self._buf[:4]) != b"RIFF" or bytes(self._buf[8:12]) != b"WAVE":
                raise WavFormatError("LFM3 TTS did not return a RIFF/WAVE stream")
            self._riff_checked = True
            self._pos = 12

        if self._data_remaining is not None:
            out.extend(self._drain_data())
            return out

        while True:
            if len(self._buf) < self._pos + 8:
                return out
            chunk_id = bytes(self._buf[self._pos : self._pos + 4])
            size = struct.unpack_from("<I", self._buf, self._pos + 4)[0]
            body_start = self._pos + 8
            if chunk_id == b"data":
                self._data_remaining = size
                self._pos = body_start
                out.extend(self._drain_data())
                return out
            if len(self._buf) < body_start + size:
                return out
            self._pos = body_start + size
            if size % 2 == 1:
                self._pos += 1

    def _drain_data(self) -> list[bytes]:
        out: list[bytes] = []
        if self._data_remaining is None or self._data_remaining <= 0:
            self._done = True
            return out
        available = len(self._buf) - self._pos
        take = min(self._data_remaining, available)
        if take:
            out.append(bytes(self._buf[self._pos : self._pos + take]))
            self._pos += take
            self._data_remaining -= take
        if self._data_remaining == 0:
            self._done = True
        return out

    def finish(self) -> list[bytes]:
        return []


def tts_request_payload(text: str, *, voice: str, lang: str, seed: int) -> dict[str, object]:
    if not text.strip():
        raise WavFormatError("cannot synthesize blank text")
    return {
        "input": text,
        "voice": voice,
        "lang": lang,
        "stream": False,
        "seed": seed,
        "temperature": 0.0,
    }

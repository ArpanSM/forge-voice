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

    The parser validates the `fmt ` chunk (PCM16, expected rate and channels)
    before emitting audio. A finite `data` chunk must be complete by `finish()`;
    the local LFM3 streaming endpoint uses the 0x7fffffff sentinel for an
    unknown length, which is accepted and closed at end of stream.
    """

    STREAMING_SIZE = 0x7FFFFFFF

    def __init__(
        self,
        *,
        expected_sample_rate: int = 24000,
        expected_channels: int = 1,
    ) -> None:
        self.expected_sample_rate = expected_sample_rate
        self.expected_channels = expected_channels
        self.sample_rate: int | None = None
        self.channels: int | None = None
        self._buf = bytearray()
        self._pos = 0
        self._riff_checked = False
        self._fmt_seen = False
        self._data_started = False
        self._streaming = False
        self._data_remaining: int | None = None
        self._streamed_bytes = 0
        self._done = False

    def feed(self, chunk: bytes) -> list[bytes]:
        if not chunk or self._done:
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

        if self._data_started:
            out.extend(self._drain_data())
            return out

        while True:
            if len(self._buf) < self._pos + 8:
                return out
            chunk_id = bytes(self._buf[self._pos : self._pos + 4])
            size = struct.unpack_from("<I", self._buf, self._pos + 4)[0]
            body_start = self._pos + 8
            if chunk_id == b"fmt ":
                if len(self._buf) < body_start + size:
                    return out
                self._parse_fmt(bytes(self._buf[body_start : body_start + size]))
                self._pos = body_start + size + (size % 2)
                continue
            if chunk_id == b"data":
                if not self._fmt_seen:
                    raise WavFormatError("WAV data chunk appeared before a fmt chunk")
                self._data_started = True
                self._streaming = size >= self.STREAMING_SIZE
                self._data_remaining = None if self._streaming else size
                self._pos = body_start
                out.extend(self._drain_data())
                return out
            if len(self._buf) < body_start + size:
                return out
            self._pos = body_start + size + (size % 2)

    def _parse_fmt(self, body: bytes) -> None:
        if len(body) < 16:
            raise WavFormatError("WAV fmt chunk is too short")
        audio_format, channels, sample_rate, byte_rate, block_align, bits = struct.unpack(
            "<HHIIHH", body[:16]
        )
        if audio_format != 1:
            raise WavFormatError("LFM3 audio must be uncompressed PCM")
        if bits != 16:
            raise WavFormatError("LFM3 audio must be 16-bit PCM")
        if channels != self.expected_channels:
            raise WavFormatError(
                f"LFM3 audio has {channels} channels; expected {self.expected_channels}"
            )
        if sample_rate != self.expected_sample_rate:
            raise WavFormatError(
                f"LFM3 audio is {sample_rate} Hz; expected {self.expected_sample_rate} Hz"
            )
        if block_align != channels * 2 or byte_rate != sample_rate * block_align:
            raise WavFormatError("WAV fmt chunk has inconsistent block alignment")
        self.sample_rate = sample_rate
        self.channels = channels
        self._fmt_seen = True

    def _drain_data(self) -> list[bytes]:
        if not self._data_started:
            return []
        available = len(self._buf) - self._pos
        if available <= 0:
            if not self._streaming and self._data_remaining == 0:
                self._done = True
            return []
        if self._streaming:
            out = [bytes(self._buf[self._pos :])]
            self._streamed_bytes += len(out[0])
            self._pos = len(self._buf)
            return out
        if self._data_remaining is None:
            return []
        take = min(self._data_remaining, available)
        out = [bytes(self._buf[self._pos : self._pos + take])]
        self._pos += take
        self._data_remaining -= take
        if self._data_remaining == 0:
            self._done = True
        return out

    def finish(self) -> list[bytes]:
        if not self._fmt_seen:
            raise WavFormatError("WAV stream ended before a fmt chunk")
        if not self._data_started:
            raise WavFormatError("WAV stream ended before a data chunk")
        if not self._streaming and not self._done:
            raise WavFormatError("truncated WAV data")
        if self._streaming and self._streamed_bytes == 0:
            raise WavFormatError("streamed WAV contained no audio data")
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

"""Offline WAV parsing and streaming helpers used by the LFM3 adapter and fixtures."""

from __future__ import annotations

import io
import struct
import wave

import pytest

from forge_voice.runtime.audio_io import (
    WavFormatError,
    WavPcmStreamParser,
    parse_pcm16_wav,
    tts_request_payload,
)


def make_wav(samples: bytes = b"\x00\x01" * 100, rate: int = 24000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples)
    return buffer.getvalue()


def feed_in_chunks(parser: WavPcmStreamParser, data: bytes, sizes: list[int]) -> bytes:
    out = bytearray()
    offset = 0
    for size in sizes:
        out.extend(b"".join(parser.feed(data[offset : offset + size])))
        offset += size
    out.extend(b"".join(parser.feed(data[offset:])))
    out.extend(b"".join(parser.finish()))
    return bytes(out)


def test_parse_pcm16_wav_reads_format_and_frames() -> None:
    data = make_wav(b"\x01\x00" * 50, rate=24000)

    parsed = parse_pcm16_wav(data)

    assert parsed.sample_rate == 24000
    assert parsed.channels == 1
    assert parsed.sample_width == 2
    assert parsed.frame_count == 50
    assert parsed.duration_ms == 2


def test_stream_parser_emits_pcm_for_a_header_split_across_chunks() -> None:
    data = make_wav()

    pcm = feed_in_chunks(WavPcmStreamParser(), data, [1, 2, 4, 8, 16, 32])

    assert pcm == b"\x00\x01" * 100


def test_stream_parser_skips_extra_chunks_before_data() -> None:
    base = make_wav()
    header, body = base[:12], base[12:]
    fmt = header + body[:24]
    payload = b"\x00\x01" * 100
    data_chunk = b"data" + struct.pack("<I", len(payload)) + payload
    list_chunk = b"LIST" + struct.pack("<I", 4) + b"INFO"

    pcm = feed_in_chunks(WavPcmStreamParser(), fmt + list_chunk + data_chunk, [3, 7, 11, 5])

    assert pcm == payload


def test_stream_parser_rejects_a_non_wav_response() -> None:
    with pytest.raises(WavFormatError, match="RIFF"):
        WavPcmStreamParser().feed(b"not a wave file")


def test_stream_parser_stops_at_the_declared_data_length() -> None:
    data = make_wav(b"\x00\x01" * 10) + b"trailing"

    pcm = feed_in_chunks(WavPcmStreamParser(), data, [4, 8, 16])

    assert pcm == b"\x00\x01" * 10


def test_tts_request_is_greedy_but_reproducible() -> None:
    payload = tts_request_payload("Hello", voice="female", lang="en", seed=7)

    assert payload == {
        "input": "Hello",
        "voice": "female",
        "lang": "en",
        "stream": False,
        "seed": 7,
        "temperature": 0.0,
    }


def test_tts_request_rejects_blank_text() -> None:
    with pytest.raises(WavFormatError, match="blank"):
        tts_request_payload("  ", voice="female", lang="en", seed=1)

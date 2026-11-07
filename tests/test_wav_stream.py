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


def make_wav(samples: bytes = b"\x00\x01" * 100, rate: int = 24000, channels: int = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples)
    return buffer.getvalue()


def make_streaming_wav(
    payload: bytes = b"\x00\x01" * 100,
    *,
    rate: int = 24000,
    channels: int = 1,
    audio_format: int = 1,
) -> bytes:
    fmt = struct.pack(
        "<HHIIHH",
        audio_format,
        channels,
        rate,
        rate * channels * 2,
        channels * 2,
        16,
    )
    return (
        b"RIFF"
        + struct.pack("<I", 0xFFFFFFFF)
        + b"WAVE"
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", 0x7FFFFFFF)
        + payload
    )


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


def test_stream_parser_reads_and_validates_the_fmt_chunk() -> None:
    parser = WavPcmStreamParser(expected_sample_rate=24000, expected_channels=1)

    pcm = feed_in_chunks(parser, make_wav(), [3, 5, 9, 17])

    assert pcm == b"\x00\x01" * 100
    assert parser.sample_rate == 24000
    assert parser.channels == 1


def test_stream_parser_rejects_a_mismatched_sample_rate() -> None:
    parser = WavPcmStreamParser(expected_sample_rate=24000, expected_channels=1)

    with pytest.raises(WavFormatError, match="48000"):
        parser.feed(make_wav(rate=48000))


def test_stream_parser_rejects_stereo_audio() -> None:
    parser = WavPcmStreamParser(expected_sample_rate=24000, expected_channels=1)

    with pytest.raises(WavFormatError, match="2 channels"):
        parser.feed(make_wav(b"\x00\x01" * 200, channels=2))


def test_stream_parser_rejects_non_pcm_fmt() -> None:
    parser = WavPcmStreamParser(expected_sample_rate=24000, expected_channels=1)

    with pytest.raises(WavFormatError, match="uncompressed PCM"):
        parser.feed(make_streaming_wav(audio_format=3))


def test_stream_parser_finish_rejects_truncated_finite_data() -> None:
    data = make_wav(b"\x00\x01" * 100)
    parser = WavPcmStreamParser(expected_sample_rate=24000, expected_channels=1)
    parser.feed(data[:-10])

    with pytest.raises(WavFormatError, match="truncated"):
        parser.finish()


def test_stream_parser_accepts_the_unknown_length_streaming_sentinel() -> None:
    parser = WavPcmStreamParser(expected_sample_rate=24000, expected_channels=1)
    data = make_streaming_wav(b"\x00\x01" * 100)

    pcm = b"".join(parser.feed(data[:53])) + b"".join(parser.feed(data[53:]))

    assert pcm == b"\x00\x01" * 100
    assert parser.finish() == []


def test_stream_parser_finish_rejects_empty_streaming_audio() -> None:
    parser = WavPcmStreamParser(expected_sample_rate=24000, expected_channels=1)
    parser.feed(make_streaming_wav(b""))

    with pytest.raises(WavFormatError, match="no audio data"):
        parser.finish()

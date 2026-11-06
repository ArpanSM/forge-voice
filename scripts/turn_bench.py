"""Measure the LFM3 voice loop without LiveKit transport.

For each scripted caller turn: TTS the caller audio, STT it, run the agent
(LLM + tools), then measure the assistant TTS first frame and total.
"""

from __future__ import annotations

import asyncio
import json
import time
import wave
from pathlib import Path

from livekit import rtc
from livekit.agents import AgentSession
from livekit.plugins import openai

from spike.agent import BookingAgent, _llm
from spike.lfm3_audio import LFM3TTS, write_stream_to_wav

OUT = Path("/tmp/opencode/lfm3-test")
OUT.mkdir(parents=True, exist_ok=True)


def frames_from_wav(path: Path, chunk_ms: int = 200) -> list[rtc.AudioFrame]:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        sample_rate = w.getframerate()
        data = w.readframes(w.getnframes())
    samples_per = sample_rate * chunk_ms // 1000
    frames = []
    for i in range(0, len(data), samples_per * 2):
        chunk = data[i : i + samples_per * 2]
        n = len(chunk) // 2
        frames.append(
            rtc.AudioFrame(
                data=chunk,
                sample_rate=sample_rate,
                num_channels=1,
                samples_per_channel=n,
            )
        )
    return frames


async def first_tts_frame(text: str) -> tuple[float, float, str]:
    tts = LFM3TTS()
    stream = tts.synthesize(text)
    start = time.perf_counter()
    first = None
    frames = []
    async for ev in stream:
        if first is None:
            first = time.perf_counter() - start
        frames.append(ev.frame)
    total = time.perf_counter() - start
    await stream.aclose()
    if frames:
        wav = OUT / "assistant-last.wav"
        wav.write_bytes(rtc.combine_audio_frames(frames).to_wav_bytes())
    return first or 0.0, total, text


async def main() -> None:
    stt = openai.STT(
        model="lfm3-audio-2b",
        base_url="http://127.0.0.1:8082/v1",
        api_key="local",
        language="en",
    )
    session = AgentSession(llm=_llm())
    await session.start(agent=BookingAgent())
    tts = LFM3TTS()

    turns = [
        "I need drain cleaning in nine four one zero seven.",
        "Monday at nine works. My name is Sam Rivera, phone five five five, one two three, four five six seven, address 12 Alder St, zip nine four one zero seven.",
        "Yes, please book that slot.",
    ]
    report = []

    for idx, text in enumerate(turns, start=1):
        caller_wav = OUT / f"caller-{idx}.wav"
        await write_stream_to_wav(tts.synthesize(text), str(caller_wav))
        frames = frames_from_wav(caller_wav)

        t0 = time.perf_counter()
        event = await stt.recognize(frames)
        stt_s = time.perf_counter() - t0
        transcript = event.alternatives[0].text

        t1 = time.perf_counter()
        result = await session.run(user_input=transcript)
        llm_s = time.perf_counter() - t1

        assistant_text = ""
        tool_calls = []
        for ev in result.events:
            name = type(ev).__name__
            item = getattr(ev, "item", None)
            if name == "ChatMessageEvent" and getattr(item, "role", "") == "assistant":
                assistant_text = " ".join(str(part) for part in item.content)
            elif name == "FunctionCallEvent":
                tool_calls.append({"name": item.name, "arguments": item.arguments})
            elif name == "FunctionCallOutputEvent":
                tool_calls.append({"output": item.output})

        tts_first, tts_total, _ = await first_tts_frame(assistant_text or "Okay.")
        report.append(
            {
                "turn": idx,
                "caller_text": text,
                "transcript": transcript,
                "assistant_text": assistant_text,
                "tool_calls": tool_calls,
                "stt_ms": round(stt_s * 1000),
                "llm_ms": round(llm_s * 1000),
                "tts_first_ms": round(tts_first * 1000),
                "tts_total_ms": round(tts_total * 1000),
                "first_audio_ms": round((stt_s + llm_s + tts_first) * 1000),
            }
        )

    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

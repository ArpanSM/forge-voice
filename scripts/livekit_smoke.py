#!/usr/bin/env python3
"""Scripted WebRTC caller for the local browser path.

Joins the self-hosted LiveKit room through the same /token endpoint the browser uses,
publishes LFM3 caller audio, follows agent state in the local trace and fails unless one
booking is committed after an explicit yes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import urllib.request
import wave
from array import array
from pathlib import Path

from livekit import rtc

ROOT = Path(__file__).resolve().parents[1]
WORK = Path("/tmp/opencode/forge-voice-smoke")
BOOKING_TURNS = [
    "Hi, I need a drain cleaning.",
    "My name is Sam Rivera.",
    "My address is 12 Alder Street, San Francisco. The ZIP is nine, four, one, zero, seven.",
    "My phone is five five five, one two three, four five six seven.",
    "What times do you have on Monday?",
    "The first slot works.",
    "Yes, book it.",
]
EMERGENCY_TURNS = [
    "Our AC is out and it is ninety-eight degrees upstairs. I have a newborn baby.",
    "The address is 88 Meridian Way, San Jose, 95125.",
    "My name is Dana Whitfield. My phone is four zero eight, five five five, zero one four two.",
    "No one is hurt, but please hurry.",
]


def http_json(url: str, *, payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url, data=data, headers=headers, method="POST" if data else "GET"
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def tts_wav(text: str, seed: int) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(f"{text}:{seed}".encode()).hexdigest()[:12]
    path = WORK / f"turn-{seed}-{key}.wav"
    if path.exists():
        return path
    payload = {
        "input": text,
        "voice": "female",
        "lang": "en",
        "stream": False,
        "seed": seed,
        "temperature": 0.0,
    }
    request = urllib.request.Request(
        "http://127.0.0.1:8082/tts",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        path.write_bytes(response.read())
    return path


def read_wav(path: Path) -> tuple[int, array]:
    with wave.open(str(path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        rate = handle.getframerate()
        samples = array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    return rate, samples


class Trace:
    def __init__(self, path: Path) -> None:
        self.path = path

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(errors="replace").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    async def wait(self, predicate, timeout: float, since: float = 0.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for event in self.events():
                if event.get("ts", 0) >= since and predicate(event):
                    return event
            await asyncio.sleep(0.1)
        raise TimeoutError(
            "trace predicate timed out; last events="
            + json.dumps(self.events()[-6:], default=str)[-2000:]
        )

    async def state(self, states: set[str], timeout: float, since: float = 0.0) -> dict:
        return await self.wait(
            lambda event: (
                event.get("event") == "session_event"
                and event.get("event_type") == "agent_state_changed"
                and event.get("new_state") in states
            ),
            timeout,
            since,
        )


class AgentAudio:
    def __init__(self) -> None:
        self.frames: list[rtc.AudioFrame] = []
        self.streams: list[rtc.AudioStream] = []
        self.tasks: list[asyncio.Task] = []
        self.last_voice = time.time()

    def on_track(self, track, publication, participant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1, frame_size_ms=20)
        self.streams.append(stream)
        self.tasks.append(asyncio.create_task(self._consume(stream)))

    async def _consume(self, stream: rtc.AudioStream) -> None:
        try:
            async for event in stream:
                self.frames.append(event.frame)
                pcm = array("h")
                pcm.frombytes(bytes(event.frame.data))
                if pcm:
                    rms = (sum(value * value for value in pcm) / len(pcm)) ** 0.5
                    if rms > 250:
                        self.last_voice = time.time()
        finally:
            await stream.aclose()

    async def wait_quiet(self, quiet_s: float = 0.8, timeout: float = 25.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if time.time() - self.last_voice >= quiet_s:
                return True
            await asyncio.sleep(0.05)
        return False

    def has_voice(self) -> bool:
        return bool(self.frames)

    async def aclose(self) -> None:
        for stream in self.streams:
            await stream.aclose()
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


async def publish_wav(source: rtc.AudioSource, path: Path, *, trailing_ms: int = 500) -> float:
    rate, samples = read_wav(path)
    chunk = rate * 20 // 1000
    for start in range(0, len(samples), chunk):
        values = samples[start : start + chunk]
        if len(values) < chunk:
            values.extend([0] * (chunk - len(values)))
        frame = rtc.AudioFrame(
            data=values.tobytes(),
            sample_rate=rate,
            num_channels=1,
            samples_per_channel=chunk,
        )
        await source.capture_frame(frame)
        await source.wait_for_playout()
    end = time.time()
    silence = b"\x00\x00" * chunk
    for _ in range(max(1, trailing_ms // 20)):
        await source.capture_frame(
            rtc.AudioFrame(
                data=silence,
                sample_rate=rate,
                num_channels=1,
                samples_per_channel=chunk,
            )
        )
        await source.wait_for_playout()
    return end


async def run(web_url: str, tenant: str, timeout: float, mode: str) -> dict:
    barge_path = None
    if mode == "barge-in":
        barge_path = tts_wav("Wait, I need a drain cleaning.", seed=999)
    elif mode == "barge-in-booking":
        barge_path = tts_wav("Wait, the first slot is fine.", seed=998)
    token = http_json(f"{web_url}/token", payload={"tenant": tenant, "identity": "smoke-caller"})
    call_id = token["call_id"]
    trace = Trace(ROOT / "data" / "calls" / f"{call_id}.jsonl")

    room = rtc.Room()
    audio = AgentAudio()
    room.on("track_subscribed", audio.on_track)
    await room.connect(token["url"], token["token"])
    source = rtc.AudioSource(24000, 1, queue_size_ms=3000)
    track = rtc.LocalAudioTrack.create_audio_track("caller", source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, options)
    try:
        await trace.wait(lambda event: event.get("event") == "room_connected", timeout)
        greeting = await trace.state({"speaking"}, timeout)
        if mode == "barge-in":
            assert barge_path is not None
            # LiveKit disables interruptions for the first 3 s while browser AEC warms up.
            await asyncio.sleep(3.4)
            interrupt_start = time.time()
            await publish_wav(source, barge_path, trailing_ms=200)
            stopped = await trace.state({"listening", "idle"}, timeout, since=interrupt_start)
            yield_ms = round((stopped["ts"] - interrupt_start) * 1000)
            recovered = await trace.state({"speaking"}, timeout, since=stopped["ts"])
            if not audio.has_voice():
                raise AssertionError("no agent audio was received over WebRTC")
            return {
                "call_id": call_id,
                "room": token["room"],
                "barge_in_yield_ms": yield_ms,
                "recovered": recovered is not None,
                "agent_audio_frames": len(audio.frames),
                "trace": str(trace.path),
            }
        await trace.state({"listening", "idle"}, timeout, since=greeting["ts"])
        await audio.wait_quiet(timeout=timeout)
        script = EMERGENCY_TURNS if mode == "emergency" else BOOKING_TURNS
        turns: list[dict] = []
        barge_result: dict | None = None
        for index, text in enumerate(script, start=1):
            path = tts_wav(text, seed=700 + index)
            await trace.state({"listening", "idle"}, timeout)
            speech_end = await publish_wav(source, path)
            speaking = await trace.state({"speaking"}, timeout, since=speech_end)
            if mode == "barge-in-booking" and index == 5:
                assert barge_path is not None
                interrupt_start = time.time()
                await publish_wav(source, barge_path, trailing_ms=200)
                stopped = await trace.state({"listening", "idle"}, timeout, since=interrupt_start)
                recovered = await trace.state({"speaking"}, timeout, since=stopped["ts"])
                await trace.state({"listening", "idle"}, timeout, since=recovered["ts"])
                barge_result = {
                    "yield_ms": round((stopped["ts"] - interrupt_start) * 1000),
                    "recovered": True,
                }
                turns.append(
                    {
                        "turn": index,
                        "text": text,
                        "spoken": True,
                        "interrupted_with": "Wait, the first slot is fine.",
                    }
                )
                print(f"  turn {index}: {text}  [interrupted mid-booking]", flush=True)
                continue
            await trace.state({"listening", "idle"}, timeout, since=speaking["ts"])
            await audio.wait_quiet(quiet_s=0.6, timeout=15)
            turns.append({"turn": index, "text": text, "spoken": True})
            print(f"  turn {index}: {text}", flush=True)
        if not audio.has_voice():
            raise AssertionError("no agent audio was received over WebRTC")
        events = trace.events()
        if mode == "emergency":
            ticket = await trace.wait(
                lambda event: event.get("event") == "emergency_ticket",
                timeout,
                since=time.time() - timeout,
            )
            handoff = await trace.wait(
                lambda event: event.get("event") == "handoff",
                timeout,
                since=time.time() - timeout,
            )
            tickets = [event for event in events if event.get("event") == "emergency_ticket"]
            if len(tickets) != 1:
                raise AssertionError(f"expected one emergency ticket, found {len(tickets)}")
            return {
                "call_id": call_id,
                "room": token["room"],
                "turns": turns,
                "ticket_id": ticket.get("ticket_id"),
                "category": ticket.get("category"),
                "transfer_status": handoff.get("status"),
                "agent_audio_frames": len(audio.frames),
                "trace": str(trace.path),
            }
        booked = await trace.wait(
            lambda event: event.get("event") == "booked", timeout, since=time.time() - timeout
        )
        booked_events = [event for event in events if event.get("event") == "booked"]
        if len(booked_events) != 1:
            raise AssertionError(f"expected one booked event, found {len(booked_events)}")
        return {
            "call_id": call_id,
            "room": token["room"],
            "turns": turns,
            "booking_id": booked.get("booking_id"),
            "replayed": booked.get("replayed"),
            "confirmation_queued": booked.get("confirmation_queued"),
            "barge_in_booking": barge_result,
            "agent_audio_frames": len(audio.frames),
            "trace": str(trace.path),
        }
    finally:
        await audio.aclose()
        await room.disconnect()
        # Let the LiveKit FFI teardown settle before interpreter shutdown.
        await asyncio.sleep(0.4)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant", default="harborlight")
    parser.add_argument(
        "--mode",
        choices=["booking", "emergency", "barge-in", "barge-in-booking"],
        default="booking",
    )
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.web_url, args.tenant, args.timeout, args.mode))
    except Exception as exc:
        print(f"SMOKE FAILED: {type(exc).__name__}: {exc}")
        sys.stdout.flush()
        os._exit(1)
    print("SMOKE PASSED")
    print(json.dumps(result, indent=2, default=str))
    sys.stdout.flush()
    # The LiveKit FFI can panic in a non-unwinding teardown after a short call.
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())

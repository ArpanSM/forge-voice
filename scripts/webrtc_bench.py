"""End-to-end LiveKit WebRTC bench for the voice spike.

Runs the actual agent worker, joins a LiveKit Cloud room through the local token
endpoint, publishes synthetic caller audio, and measures caller-perceived first
audio. Also runs barge-in, silence and degraded-audio smoke tests.

This is a spike harness, not the product eval. It deliberately uses one scripted
conversation and a small number of calls.

Examples:
    python scripts/webrtc_bench.py --profile hybrid --mode all
    python scripts/webrtc_bench.py --profile lfm3 --mode latency
    python scripts/webrtc_bench.py --profile hybrid --mode barge-in
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from livekit import rtc

from spike.lfm3_audio import LFM3TTS, write_stream_to_wav

ROOT = Path(__file__).resolve().parents[1]
OUT = Path("/tmp/opencode/webrtc-bench")
OUT.mkdir(parents=True, exist_ok=True)

TURNS = [
    "Hi, I need a drain cleaning.",
    "The ZIP is nine four one zero seven.",
    "My address is 12 Alder Street.",
    "My name is Sam Rivera.",
    "My phone is five five five, one two three, four five six seven.",
    "What times do you have on Monday?",
    "Is eleven available?",
    "Let's do eleven.",
    "Yes, book it.",
    "Thanks, that's all.",
]

DEGRADED_TURNS = [
    (
        "I need a drain cleaning. My name is Sam Rivera. My address is 12 Alder Street, 94107. "
        "My phone is five five five, one two three, four five six seven."
    ),
    "Monday at eleven works. Yes, that's correct.",
]

INTERRUPT_TEXT = "Wait, I want Tuesday instead of Monday."


def load_env() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()


def _url(path: str) -> str:
    return f"http://127.0.0.1:{os.environ['SPIKE_TOKEN_PORT']}{path}"


def wait_http(path: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(_url(path), timeout=2) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001 - startup polling
            last = exc
            time.sleep(0.25)
    raise RuntimeError(f"token server did not become ready: {last}")


async def get_token(room: str, identity: str) -> dict:
    return await asyncio.to_thread(
        lambda: json.loads(
            urllib.request.urlopen(
                _url(f"/token?room={room}&identity={identity}"), timeout=5
            )
            .read()
            .decode()
        )
    )


def wait_log(path: Path, needle: str, timeout: float = 45.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            text = path.read_text(errors="replace")
            if needle in text:
                return
        time.sleep(0.25)
    text = path.read_text(errors="replace") if path.exists() else ""
    raise RuntimeError(f"agent worker did not log {needle!r}:\n{text[-3000:]}")


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        rate = w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).copy()
    return rate, data


def write_wav(path: Path, rate: int, data: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(data, dtype=np.int16).tobytes())


def degraded(data: np.ndarray, rate: int, kind: str, seed: int) -> np.ndarray:
    """Create a deterministic degraded caller clip without ffmpeg."""
    rng = np.random.default_rng(seed)
    x = data.astype(np.float32) / 32768.0
    if kind == "noisy":
        signal = float(np.sqrt(np.mean(x * x))) or 0.01
        noise = rng.normal(0, signal / (10 ** (10 / 20)), len(x))
        y = x + noise
    elif kind == "lowmic":
        # 3.4 kHz-ish low-pass via a short moving average, plus light clipping.
        kernel = np.ones(11, dtype=np.float32) / 11
        y = np.convolve(x, kernel, mode="same")
        y = np.clip(y * 1.4, -1.0, 1.0)
    elif kind == "packetloss":
        y = x.copy()
        chunk = max(1, int(rate * 0.02))
        for start in range(0, len(y), chunk):
            if rng.random() < 0.06:
                y[start : start + chunk] = 0.0
    else:
        raise ValueError(kind)
    return np.clip(y * 32768.0, -32768, 32767).astype(np.int16)


def frames_from_wav(
    data: np.ndarray, rate: int, chunk_ms: int = 20
) -> list[rtc.AudioFrame]:
    samples = rate * chunk_ms // 1000
    frames: list[rtc.AudioFrame] = []
    for start in range(0, len(data), samples):
        chunk = data[start : start + samples]
        if len(chunk) < samples:
            chunk = np.pad(chunk, (0, samples - len(chunk)))
        frames.append(
            rtc.AudioFrame(
                data=chunk.tobytes(),
                sample_rate=rate,
                num_channels=1,
                samples_per_channel=samples,
            )
        )
    return frames


class Trace:
    def __init__(self, path: Path, room: str) -> None:
        self.path = path
        self.room = room

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(errors="replace").splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("room") == self.room:
                out.append(data)
        return out

    async def wait(self, predicate, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for event in self.events():
                if predicate(event):
                    return event
            await asyncio.sleep(0.05)
        raise TimeoutError(f"trace predicate timed out; events={self.events()[-8:]}")


@dataclass
class AgentAudio:
    caller_identity: str
    frames: list[tuple[float, rtc.AudioFrame]] = field(default_factory=list)
    streams: list[rtc.AudioStream] = field(default_factory=list)
    last_voice_ts: float = field(default_factory=time.time)

    def on_track(self, track: rtc.Track, publication, participant) -> None:
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if participant.identity == self.caller_identity:
            return
        stream = rtc.AudioStream(
            track, sample_rate=24000, num_channels=1, frame_size_ms=20
        )
        self.streams.append(stream)
        asyncio.create_task(self._consume(stream))

    async def _consume(self, stream: rtc.AudioStream) -> None:
        try:
            async for event in stream:
                self.frames.append((time.time(), event.frame))
                pcm = np.frombuffer(event.frame.data, dtype=np.int16)
                if pcm.size:
                    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
                    if rms > 300:
                        self.last_voice_ts = time.time()
        finally:
            await stream.aclose()

    async def wait_for_quiet(self, quiet_s: float = 1.0, timeout: float = 20.0) -> bool:
        """Wait until no non-silent agent frame has arrived for quiet_s seconds."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if time.time() - self.last_voice_ts >= quiet_s:
                return True
            await asyncio.sleep(0.05)
        return False

    def write_wav(self, path: Path) -> None:
        if not self.frames:
            return
        combined = rtc.combine_audio_frames([frame for _, frame in self.frames])
        path.write_bytes(combined.to_wav_bytes())


async def publish_wav(
    source: rtc.AudioSource,
    path: Path,
    *,
    trailing_silence_ms: int = 500,
) -> float:
    """Publish a WAV in real time and return the wall-clock end of speech."""
    rate, data = read_wav(path)
    for frame in frames_from_wav(data, rate):
        await source.capture_frame(frame)
        await source.wait_for_playout()
    speech_end = time.time()

    if trailing_silence_ms > 0:
        samples = rate * 20 // 1000
        silence = rtc.AudioFrame(
            data=b"\x00\x00" * samples,
            sample_rate=rate,
            num_channels=1,
            samples_per_channel=samples,
        )
        for _ in range(max(1, trailing_silence_ms // 20)):
            await source.capture_frame(silence)
            await source.wait_for_playout()
    return speech_end


async def make_tts_wavs(tts: LFM3TTS, texts: list[str], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for idx, text in enumerate(texts, start=1):
        path = out_dir / f"caller-{idx}.wav"
        if not path.exists():
            await write_stream_to_wav(tts.synthesize(text), str(path))
        paths.append(path)
    return paths


async def wait_agent_ready(trace: Trace, timeout: float = 40.0) -> None:
    await trace.wait(lambda e: e.get("event") == "room_connected", timeout=timeout)
    await trace.wait(
        lambda e: (
            e.get("event") == "session_event" and e.get("new_state") == "speaking"
        ),
        timeout=timeout,
    )
    await trace.wait(
        lambda e: (
            e.get("event") == "session_event"
            and e.get("new_state") in ("listening", "idle")
        ),
        timeout=timeout,
    )


async def wait_idle(trace: Trace, timeout: float = 40.0, since: float = 0.0) -> None:
    await trace.wait(
        lambda e: (
            e.get("event") == "session_event"
            and e.get("new_state") in ("listening", "idle")
            and e.get("event_ts", e.get("ts", 0)) >= since
        ),
        timeout=timeout,
    )


async def join_call(
    room_name: str, caller_identity: str
) -> tuple[rtc.Room, dict, AgentAudio, Trace]:
    token = await get_token(room_name, caller_identity)
    room = rtc.Room()
    audio = AgentAudio(caller_identity)
    room.on("track_subscribed", audio.on_track)
    await room.connect(token["url"], token["token"])
    trace = Trace(Path(os.environ["SPIKE_TRACE"]), room_name)

    source = rtc.AudioSource(24000, 1, queue_size_ms=2000)
    track = rtc.LocalAudioTrack.create_audio_track("caller", source)
    options = rtc.TrackPublishOptions()
    options.source = rtc.TrackSource.SOURCE_MICROPHONE
    await room.local_participant.publish_track(track, options)
    return room, {"source": source}, audio, trace


async def latency_call(
    profile: str, room_name: str, caller: str, wavs: list[Path]
) -> dict:
    room, state, audio, trace = await join_call(room_name, caller)
    try:
        await wait_agent_ready(trace)
        await asyncio.sleep(0.5)  # let the agent subscribe to the caller track
        await audio.wait_for_quiet(quiet_s=1.0, timeout=20)
        turns: list[dict] = []
        for idx, path in enumerate(wavs, start=1):
            await wait_idle(trace)
            speech_end = await publish_wav(state["source"], path)
            try:
                speaking = await trace.wait(
                    lambda e, since=speech_end: (
                        e.get("event") == "session_event"
                        and e.get("new_state") == "speaking"
                        and e.get("event_ts", e.get("ts", 0)) >= since
                    ),
                    timeout=45,
                )
            except TimeoutError:
                turns.append({"turn": idx, "error": "no agent response"})
                continue
            first_ts = speaking.get("event_ts", speaking.get("ts", time.time()))
            first_s = first_ts - speech_end
            # Wait for the agent to finish this turn before sending the next one.
            try:
                await wait_idle(trace, timeout=45, since=first_ts)
            except TimeoutError:
                pass
            # The state can flip to listening before the queued TTS has played out.
            await audio.wait_for_quiet(quiet_s=0.5, timeout=10)
            events = trace.events()
            tool_results = [
                e
                for e in events
                if e.get("event") == "tool_result" and e.get("ts", 0) >= speech_end
            ]
            turns.append(
                {
                    "turn": idx,
                    "caller_text": TURNS[idx - 1],
                    "first_audio_ms": round(first_s * 1000),
                    "tool_results": tool_results,
                }
            )
            print(
                f"  turn {idx:02d}: first audio {first_s * 1000:.0f} ms; "
                f"tools={[t.get('tool') for t in tool_results]}",
                flush=True,
            )

        latencies = [t["first_audio_ms"] for t in turns if "first_audio_ms" in t]
        p50 = float(np.percentile(latencies, 50)) if latencies else None
        p95 = float(np.percentile(latencies, 95)) if latencies else None
        audio.write_wav(OUT / f"{profile}-latency-agent.wav")
        return {
            "mode": "latency",
            "profile": profile,
            "room": room_name,
            "turns": turns,
            "first_audio_ms": latencies,
            "p50_ms": p50,
            "p95_ms": p95,
            "false_interruptions": sum(
                1
                for e in trace.events()
                if e.get("event") == "session_event"
                and e.get("event_type") == "agent_false_interruption"
            ),
        }
    finally:
        await room.disconnect()


async def barge_in_call(
    profile: str,
    room_name: str,
    caller: str,
    first_wav: Path,
    interrupt_wav: Path,
) -> dict:
    room, state, audio, trace = await join_call(room_name, caller)
    try:
        await wait_agent_ready(trace)
        await asyncio.sleep(0.5)
        await audio.wait_for_quiet(quiet_s=1.0, timeout=20)
        await wait_idle(trace)
        speech_end = await publish_wav(
            state["source"], first_wav, trailing_silence_ms=300
        )
        # Wait until the agent has actually started speaking.
        await trace.wait(
            lambda e: (
                e.get("event") == "session_event"
                and e.get("new_state") == "speaking"
                and e.get("event_ts", e.get("ts", 0)) >= speech_end
            ),
            timeout=40,
        )
        # Give the agent a moment of speech, then interrupt.
        await asyncio.sleep(0.35)
        interrupt_start = time.time()
        await publish_wav(state["source"], interrupt_wav, trailing_silence_ms=300)
        try:
            stopped = await trace.wait(
                lambda e: (
                    e.get("event") == "session_event"
                    and e.get("new_state") in ("listening", "idle")
                    and e.get("event_ts", e.get("ts", 0)) >= interrupt_start
                ),
                timeout=20,
            )
            yield_ms = round(
                (
                    stopped.get("event_ts", stopped.get("ts", time.time()))
                    - interrupt_start
                )
                * 1000
            )
        except TimeoutError:
            yield_ms = None
        overlaps = [
            e
            for e in trace.events()
            if e.get("event") == "session_event"
            and e.get("event_type") == "overlapping_speech"
            and e.get("event_ts", 0) >= interrupt_start - 1
        ]
        # Look for a recovery response after the interruption.
        try:
            recovered = await trace.wait(
                lambda e: (
                    e.get("event") == "session_event"
                    and e.get("new_state") == "speaking"
                    and e.get("event_ts", e.get("ts", 0)) > interrupt_start + 0.2
                ),
                timeout=30,
            )
            recovered_text = [
                e.get("content")
                for e in trace.events()
                if e.get("event") == "session_event"
                and e.get("event_type") == "conversation_item_added"
                and e.get("role") == "assistant"
                and e.get("event_ts", 0) >= interrupt_start
            ]
        except TimeoutError:
            recovered = None
            recovered_text = []
        audio.write_wav(OUT / f"{profile}-barge-in-agent.wav")
        return {
            "mode": "barge-in",
            "profile": profile,
            "room": room_name,
            "barge_in_yield_ms": yield_ms,
            "overlapping_speech": overlaps,
            "false_interruptions": sum(
                1
                for e in trace.events()
                if e.get("event_type") == "agent_false_interruption"
            ),
            "recovered": recovered is not None,
            "recovered_text": recovered_text[-3:],
        }
    finally:
        await room.disconnect()


async def silence_call(
    profile: str, room_name: str, caller: str, wavs: list[Path]
) -> dict:
    room, state, audio, trace = await join_call(room_name, caller)
    try:
        await wait_agent_ready(trace)
        await asyncio.sleep(0.5)
        await audio.wait_for_quiet(quiet_s=1.0, timeout=20)
        await wait_idle(trace)
        # 3 s of silence, then a caller turn; see whether the agent prompts or recovers.
        silence_start = time.time()
        silence = rtc.AudioFrame(
            data=b"\x00\x00" * (24000 * 20 // 1000),
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=24000 * 20 // 1000,
        )
        for _ in range(150):
            await state["source"].capture_frame(silence)
            await state["source"].wait_for_playout()
        prompted = [
            e
            for e in trace.events()
            if e.get("event") == "session_event"
            and e.get("new_state") == "speaking"
            and e.get("event_ts", e.get("ts", 0)) >= silence_start
        ]
        speech_end = await publish_wav(
            state["source"], wavs[0], trailing_silence_ms=300
        )
        try:
            speaking = await trace.wait(
                lambda e: (
                    e.get("event") == "session_event"
                    and e.get("new_state") == "speaking"
                    and e.get("event_ts", e.get("ts", 0)) >= speech_end
                ),
                timeout=30,
            )
            first_ms = round(
                (speaking.get("event_ts", speaking.get("ts", time.time())) - speech_end)
                * 1000
            )
        except TimeoutError:
            first_ms = None
        return {
            "mode": "silence",
            "profile": profile,
            "room": room_name,
            "prompted_during_silence": bool(prompted),
            "recovered": first_ms is not None,
            "first_audio_ms": first_ms,
        }
    finally:
        await room.disconnect()


async def degraded_call(
    profile: str, room_name: str, caller: str, caller_wav: Path, kind: str, seed: int
) -> dict:
    rate, data = read_wav(caller_wav)
    bad = degraded(data, rate, kind, seed)
    bad_path = OUT / f"{kind}-caller.wav"
    write_wav(bad_path, rate, bad)
    room, state, audio, trace = await join_call(room_name, caller)
    try:
        await wait_agent_ready(trace)
        await asyncio.sleep(0.5)
        await audio.wait_for_quiet(quiet_s=1.0, timeout=20)
        await wait_idle(trace)
        speech_end = await publish_wav(
            state["source"], bad_path, trailing_silence_ms=500
        )
        try:
            speaking = await trace.wait(
                lambda e: (
                    e.get("event") == "session_event"
                    and e.get("new_state") == "speaking"
                    and e.get("event_ts", e.get("ts", 0)) >= speech_end
                ),
                timeout=40,
            )
            first_ms = round(
                (speaking.get("event_ts", speaking.get("ts", time.time())) - speech_end)
                * 1000
            )
        except TimeoutError:
            first_ms = None
        # The long degraded utterance is split by VAD; let the remaining
        # segments land before reading the final transcripts.
        await asyncio.sleep(8.0)
        try:
            await wait_idle(trace, timeout=30, since=speech_end)
        except TimeoutError:
            pass
        transcripts = [
            e.get("transcript", "")
            for e in trace.events()
            if e.get("event_type") == "user_input_transcribed" and e.get("is_final")
        ]
        combined = " ".join(transcripts)
        return {
            "mode": "degraded",
            "profile": profile,
            "room": room_name,
            "degradation": kind,
            "first_audio_ms": first_ms,
            "transcript": combined,
            "entity_hits": {
                "zip": "94107" in combined,
                "address": "alder" in combined.lower(),
                "phone": "555" in combined,
            },
        }
    finally:
        await room.disconnect()


def summarize(result: dict) -> str:
    lines = [f"# WebRTC bench — {result['profile']}", ""]
    lat = result.get("latency")
    if lat:
        p50 = lat.get("p50_ms")
        p95 = lat.get("p95_ms")
        p50_text = f"{p50:.0f} ms" if p50 is not None else "n/a"
        p95_text = f"{p95:.0f} ms" if p95 is not None else "n/a"
        lines += [
            f"- 10-turn first audio: p50 **{p50_text}**, p95 **{p95_text}**.",
            f"- Per turn: {[t.get('first_audio_ms') for t in lat['turns']]}",
            f"- False interruptions: {lat.get('false_interruptions')}.",
            "",
        ]
    bi = result.get("barge_in")
    if bi:
        lines += [
            f"- Barge-in yield: **{bi.get('barge_in_yield_ms')} ms**; recovered: {bi.get('recovered')}.",
            (
                f"- Overlapping speech events: {len(bi.get('overlapping_speech', []))}; "
                f"false interruptions: {bi.get('false_interruptions')}."
            ),
            "",
        ]
    silence = result.get("silence")
    if silence:
        lines += [
            (
                f"- Silence: prompted={silence.get('prompted_during_silence')}, "
                f"recovered={silence.get('recovered')}, first audio={silence.get('first_audio_ms')} ms."
            ),
            "",
        ]
    degraded_results = result.get("degraded", [])
    if degraded_results:
        lines += [
            "| Degradation | First audio | ZIP | Address | Phone | Transcript |",
            "|---|---:|---|---|---|---|",
        ]
        for item in degraded_results:
            hits = item.get("entity_hits", {})
            transcript = (item.get("transcript") or "").replace("|", "/")[:100]
            lines.append(
                f"| {item.get('degradation')} | {item.get('first_audio_ms')} ms | "
                f"{hits.get('zip')} | {hits.get('address')} | {hits.get('phone')} | {transcript} |"
            )
        lines.append("")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> dict:
    os.environ["SPIKE_TOKEN_PORT"] = str(args.port)
    os.environ["SPIKE_TRACE"] = str(OUT / f"trace-{args.profile}.jsonl")
    os.environ["LLM_PROVIDER"] = args.profile
    trace_path = Path(os.environ["SPIKE_TRACE"])
    trace_path.unlink(missing_ok=True)

    token_log = OUT / f"token-{args.profile}.log"
    agent_log = OUT / f"agent-{args.profile}.log"
    env = os.environ.copy()
    env["SPIKE_TOKEN_PORT"] = str(args.port)
    env["SPIKE_TRACE"] = str(trace_path)
    env["LLM_PROVIDER"] = args.profile
    env["PYTHONPATH"] = str(ROOT)

    token_proc = subprocess.Popen(  # noqa: ASYNC220 - startup is one-shot
        [sys.executable, "-m", "spike.token_server"],
        cwd=ROOT,
        env=env,
        stdout=token_log.open("w"),
        stderr=subprocess.STDOUT,
    )
    agent_proc = subprocess.Popen(  # noqa: ASYNC220 - startup is one-shot
        [sys.executable, "-m", "spike.agent", "dev"],
        cwd=ROOT,
        env=env,
        stdout=agent_log.open("w"),
        stderr=subprocess.STDOUT,
    )

    try:
        await asyncio.to_thread(wait_http, "/health", 30)
        await asyncio.to_thread(wait_log, agent_log, "registered worker", 45)
        print(f"worker registered; trace={trace_path}", flush=True)

        tts = LFM3TTS()
        wavs = await make_tts_wavs(tts, TURNS, OUT / "caller-wavs")
        degraded_wavs = await make_tts_wavs(tts, DEGRADED_TURNS, OUT / "degraded-wavs")
        interrupt_wav = (
            await make_tts_wavs(tts, [INTERRUPT_TEXT], OUT / "caller-wavs")
        )[0]
        result: dict = {"profile": args.profile, "turns_script": TURNS}
        run_id = uuid.uuid4().hex[:8]

        if args.mode in ("latency", "all"):
            room = f"spike-{args.profile}-lat-{run_id}"
            print(f"latency call {room}", flush=True)
            result["latency"] = await latency_call(
                args.profile, room, f"caller-{run_id}", wavs
            )

        if args.mode in ("barge-in", "all"):
            room = f"spike-{args.profile}-bi-{run_id}"
            print(f"barge-in call {room}", flush=True)
            result["barge_in"] = await barge_in_call(
                args.profile,
                room,
                f"caller-{run_id}",
                degraded_wavs[0],
                interrupt_wav,
            )

        if args.mode in ("silence", "all"):
            room = f"spike-{args.profile}-sil-{run_id}"
            print(f"silence call {room}", flush=True)
            result["silence"] = await silence_call(
                args.profile, room, f"caller-{run_id}", wavs
            )

        if args.mode in ("degraded", "all"):
            result["degraded"] = []
            for kind in ("noisy", "lowmic", "packetloss"):
                room = f"spike-{args.profile}-{kind}-{run_id}"
                print(f"degraded call {room}", flush=True)
                result["degraded"].append(
                    await degraded_call(
                        args.profile,
                        room,
                        f"caller-{run_id}",
                        degraded_wavs[0],
                        kind,
                        7,
                    )
                )

        report_path = OUT / f"report-{args.profile}.json"
        if report_path.exists():
            merged = json.loads(report_path.read_text())
            merged.update(result)
            result = merged
        report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        (OUT / f"report-{args.profile}.md").write_text(summarize(result))
        print(summarize(result), flush=True)
        return result
    finally:
        for proc in (agent_proc, token_proc):
            proc.terminate()
        for proc in (agent_proc, token_proc):
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        for log in (agent_log, token_log):
            if log.exists():
                print(f"\n--- {log.name} tail ---", flush=True)
                print(
                    "\n".join(log.read_text(errors="replace").splitlines()[-20:]),
                    flush=True,
                )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=["hybrid", "lfm3"], default="hybrid")
    parser.add_argument(
        "--mode",
        choices=["latency", "barge-in", "silence", "degraded", "all"],
        default="all",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()

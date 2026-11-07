"""Live self-hosted LiveKit audio transport for the audio eval subsets.

The stack is the same one `make demo` runs: the pinned local `livekit-server`, the local
FastAPI token page and the LiveKit Agents worker. The caller publishes LFM3 TTS clips and reads
the worker's JSONL trace. No Cloud, SIP or hosted model is used.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from forge_voice.adapters.sqlite import SQLiteAdapter
from forge_voice.audio.fixtures import load_audio_scripts
from forge_voice.config import load_env_file
from forge_voice.eval.fixed import _chunks
from forge_voice.eval.models import AgentScenarioView, ScenarioExecution, WriteRecord
from forge_voice.eval.setup import ScenarioSetup
from forge_voice.runtime.interpreter import extract_facts
from forge_voice.scenarios import load_manifest
from forge_voice.tenants import load_all_tenants


class LiveKitStackError(RuntimeError):
    """The local stack did not become healthy."""


class LiveKitStack:
    def __init__(
        self,
        root: Path,
        *,
        profile: str,
        web_port: int = 8000,
        livekit_port: int = 7880,
        log_dir: Path | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.root = Path(root)
        self.profile = profile
        self.web_port = web_port
        self.livekit_port = livekit_port
        self.log_dir = (
            Path(log_dir) if log_dir else Path(tempfile.mkdtemp(prefix="forge-eval-stack-"))
        )
        self.timeout = timeout
        self.processes: list[subprocess.Popen[bytes]] = []
        self.env: dict[str, str] = {}

    @property
    def web_url(self) -> str:
        return f"http://127.0.0.1:{self.web_port}"

    @property
    def livekit_url(self) -> str:
        return f"ws://localhost:{self.livekit_port}"

    def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [str(self.root / "scripts" / "prepare_local_env.sh"), str(self.root)],
            check=True,
            capture_output=True,
        )
        load_env_file(self.root / ".env.local")
        self.env = dict(os.environ)
        self.env["PYTHONPATH"] = "src"
        self.env["FORGE_VOICE_PROFILE"] = self.profile
        self.env["LIVEKIT_URL"] = self.livekit_url
        self.env["FORGE_VOICE_WEB_PORT"] = str(self.web_port)
        key = self.env.get("LIVEKIT_API_KEY", "devkey")
        secret = self.env.get("LIVEKIT_API_SECRET", "")
        if not secret:
            raise LiveKitStackError("LIVEKIT_API_SECRET was not generated")
        self.env["LIVEKIT_KEYS"] = f"{key}: {secret}"
        server = self.root / ".tools" / "livekit-server"
        if not server.is_file():
            raise LiveKitStackError(
                "the local livekit-server is missing; run make bootstrap before the audio eval"
            )
        self._spawn(
            [str(server), "--dev", "--bind", "127.0.0.1", "--node-ip", "127.0.0.1"],
            "livekit.log",
        )
        self._wait_http(f"http://127.0.0.1:{self.livekit_port}/", "livekit-server")
        self._spawn(
            [sys.executable, "-m", "forge_voice.web.app"],
            "web.log",
        )
        self._wait_http(f"{self.web_url}/health", "web/token server")
        self._spawn(
            [sys.executable, "-m", "forge_voice.runtime.livekit_agent", "dev"],
            "agent.log",
        )
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if "registered worker" in (self.log_dir / "agent.log").read_text(
                encoding="utf-8", errors="replace"
            ):
                return
            if self.processes[-1].poll() is not None:
                raise LiveKitStackError(
                    f"the agent worker exited during startup; see {self.log_dir / 'agent.log'}"
                )
            time.sleep(0.25)
        raise LiveKitStackError(
            f"the agent worker did not register within {self.timeout:g}s; see "
            f"{self.log_dir / 'agent.log'}"
        )

    def _spawn(self, command: list[str], log_name: str) -> None:
        handle = (self.log_dir / log_name).open("ab")
        process = subprocess.Popen(
            command,
            cwd=self.root,
            env=self.env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.processes.append(process)

    @staticmethod
    def _wait_http(url: str, label: str, timeout: float = 30.0) -> None:
        import urllib.request

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1):
                    return
            except Exception:
                time.sleep(0.2)
        raise LiveKitStackError(f"{label} did not become healthy at {url}")

    def stop(self) -> None:
        for process in reversed(self.processes):
            if process.poll() is not None:
                continue
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                process.terminate()
        for process in reversed(self.processes):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        self.processes.clear()


class LiveKitAudioRunner:
    def __init__(
        self,
        root: Path,
        *,
        profile: str,
        stack: LiveKitStack,
        timeout: float = 120.0,
        terminal_timeout: float = 60.0,
    ) -> None:
        self.root = Path(root)
        self.profile = profile
        self.stack = stack
        self.timeout = timeout
        self.terminal_timeout = terminal_timeout
        tenants = {path.stem for path in (self.root / "tenants").glob("*.yaml")}
        self.manifest = load_manifest(
            self.root / "scenarios" / "manifest.yaml", known_tenants=tenants
        )
        self.scripts = load_audio_scripts(
            self.root / "scenarios" / "audio_scripts.yaml", self.manifest
        )
        self.tenants = load_all_tenants(self.root / "tenants")
        self.seeds = {
            path.stem: json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "fixtures" / "corpus" / "seed").glob("*.json"))
        }

    def start(self) -> None:
        self.stack.start()

    def close(self) -> None:
        self.stack.stop()

    def run_view(self, view: AgentScenarioView, setup: ScenarioSetup) -> ScenarioExecution:
        script = self.scripts[view.id]
        chunks = _chunks([turn.text for turn in script.turns], limit=3)
        started = time.perf_counter()
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                result = asyncio.run(self._call(view, setup, script, chunks))
                result["retried"] = attempt > 0
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    time.sleep(2)
                    continue
            else:
                wall_ms = round((time.perf_counter() - started) * 1000)
                return self._execution(view, setup, script, chunks, result, wall_ms)
        wall_ms = round((time.perf_counter() - started) * 1000)
        assert last_error is not None
        return self._failed_execution(view, setup, script, chunks, last_error, wall_ms)

    def _failed_execution(
        self,
        view: AgentScenarioView,
        setup: ScenarioSetup,
        script: Any,
        chunks: list[str],
        exc: Exception,
        wall_ms: int,
    ) -> ScenarioExecution:
        expected = self._expected_entities(view, setup)
        message = f"The live audio call failed: {type(exc).__name__}: {exc}"[:500]
        return ScenarioExecution(
            scenario_id=view.id,
            tenant=view.tenant,
            mode="audio",
            outcome="failed",
            transcript=[
                *[{"role": "caller", "text": chunk} for chunk in chunks],
                {"role": "assistant", "text": message},
            ],
            response_text=message,
            qa_flags=["harness_error", f"harness_{type(exc).__name__.lower()}"],
            latency_ms=wall_ms,
            wall_ms=wall_ms,
            recording_ref=f"livekit-failed:{view.id}",
            turns_used=len(chunks),
            asr_entities={key: None for key in expected},
            asr_expected_entities=expected,
            barge_in_recovered=None if view.id != "audio_bargein_01" else False,
            error_code=type(exc).__name__,
        )

    async def _call(
        self,
        view: AgentScenarioView,
        setup: ScenarioSetup,
        script: Any,
        chunks: list[str],
    ) -> dict[str, Any]:
        from livekit import rtc
        from scripts.livekit_smoke import AgentAudio, Trace, http_json, publish_wav, tts_wav

        token = http_json(
            f"{self.stack.web_url}/token",
            payload={"tenant": view.tenant, "identity": f"eval-{view.id}"},
        )
        call_id = token["call_id"]
        trace = Trace(self.root / "data" / "calls" / f"{call_id}.jsonl")
        room = rtc.Room()
        audio = AgentAudio()
        room.on("track_subscribed", audio.on_track)

        async def state_or_none(states: set[str], timeout: float, since: float = 0.0):
            try:
                return await trace.state(states, timeout, since=since)
            except TimeoutError:
                return None

        try:
            await room.connect(token["url"], token["token"])
            source = rtc.AudioSource(24000, 1, queue_size_ms=3000)
            track = rtc.LocalAudioTrack.create_audio_track("caller", source)
            options = rtc.TrackPublishOptions()
            options.source = rtc.TrackSource.SOURCE_MICROPHONE
            await room.local_participant.publish_track(track, options)
            await trace.wait(lambda event: event.get("event") == "room_connected", self.timeout)
            greeting = await state_or_none({"speaking"}, self.timeout)
            await state_or_none(
                {"listening", "idle"},
                self.timeout,
                since=greeting["ts"] if greeting else 0.0,
            )
            await audio.wait_quiet(timeout=self.timeout)
            if script.turns and script.turns[0].pause_before_ms >= 3000:
                await asyncio.sleep(script.turns[0].pause_before_ms / 1000)
            barge: dict[str, Any] | None = None
            for index, chunk in enumerate(chunks):
                await state_or_none({"listening", "idle"}, self.timeout)
                path = tts_wav(chunk, seed=700 + index)
                speech_end = await publish_wav(source, path)
                speaking = await state_or_none({"speaking"}, self.timeout, since=speech_end)
                if view.id == "audio_bargein_01" and index == 1:
                    interrupt = tts_wav("Wait, I want the second slot instead.", seed=999)
                    interrupt_start = time.time()
                    await publish_wav(source, interrupt, trailing_ms=200)
                    stopped = await state_or_none(
                        {"listening", "idle"}, self.timeout, since=interrupt_start
                    )
                    recovered = (
                        await state_or_none({"speaking"}, self.timeout, since=stopped["ts"])
                        if stopped
                        else None
                    )
                    barge = {
                        "yield_ms": round((stopped["ts"] - interrupt_start) * 1000)
                        if stopped
                        else None,
                        "recovered": recovered is not None,
                    }
                    speaking = recovered
                if speaking is not None:
                    await state_or_none({"listening", "idle"}, self.timeout, since=speaking["ts"])
                await audio.wait_quiet(quiet_s=0.6, timeout=30)
                if not audio.has_voice():
                    raise RuntimeError("no agent audio was received over WebRTC")
            deadline = time.time() + self.terminal_timeout
            while time.time() < deadline:
                trace.raise_if_rate_limited()
                events = trace.events()
                if any(event.get("event") == "booked" for event in events):
                    break
                if any(event.get("event") == "emergency_ticket" for event in events) and any(
                    event.get("event") == "handoff" for event in events
                ):
                    break
                await asyncio.sleep(0.2)
            return {
                "call_id": call_id,
                "events": trace.events(),
                "barge": barge,
                "agent_audio_frames": len(audio.frames),
                "trace": str(trace.path),
            }
        finally:
            await audio.aclose()
            await room.disconnect()
            await asyncio.sleep(0.3)

    def _execution(
        self,
        view: AgentScenarioView,
        setup: ScenarioSetup,
        script: Any,
        chunks: list[str],
        result: dict[str, Any],
        wall_ms: int,
    ) -> ScenarioExecution:
        events = result.get("events") or []
        tool_results = [event for event in events if event.get("event") == "tool_result"]
        booked = [event for event in events if event.get("event") == "booked"]
        tickets = [event for event in events if event.get("event") == "emergency_ticket"]
        handoffs = [event for event in events if event.get("event") == "handoff"]
        readbacks = [event for event in events if event.get("event") == "readback_ready"]
        caller_utterances = [
            event.get("text", "") for event in events if event.get("event") == "caller_utterance"
        ]
        assistant = [
            event.get("content", "")
            for event in events
            if event.get("event") == "session_event"
            and event.get("event_type") == "conversation_item_added"
            and event.get("role") == "assistant"
        ]
        book_args = [
            event.get("args") or {}
            for event in tool_results
            if event.get("tool") == "book_appointment" and event.get("ok")
        ]
        ticket_args = [
            event.get("args") or {}
            for event in tool_results
            if event.get("tool") == "create_emergency_ticket" and event.get("ok")
        ]
        transfer_args = [
            event.get("args") or {}
            for event in tool_results
            if event.get("tool") == "transfer_to_human" and event.get("ok")
        ]
        packet = (transfer_args[-1].get("packet") if transfer_args else None) or None
        transfer_status = handoffs[-1].get("status") if handoffs else None
        outcome = "abandoned"
        if booked:
            outcome = "booked"
        if tickets:
            outcome = "emergency_ticket"
        if handoffs and not tickets:
            outcome = "transferred" if transfer_status == "connected" else "callback"
        ticket = tickets[-1] if tickets else {}
        book = booked[-1] if booked else {}
        booking_count = 1 if booked else 0
        service_id = book.get("service_id") or (
            book_args[-1].get("service_id") if book_args else None
        )
        qa_flags: list[str] = []
        if tickets:
            qa_flags.append("emergency_triage")
        if any(event.get("event") == "hybrid_retry" for event in events):
            qa_flags.append("hybrid_retry")
        if any(event.get("event") == "hybrid_rate_limited" for event in events):
            qa_flags.append("hybrid_rate_limited")
        if transfer_status in {"queued_callback", "no_answer"}:
            qa_flags.append("handoff_no_answer")
        if any(
            event.get("event") == "tool_result" and event.get("code") == "timeout"
            for event in events
        ):
            qa_flags.append("tool_timeout")
        if view.audio and view.audio.method == "degraded_clip":
            qa_flags.append("degraded_audio")
        if result.get("barge") and result["barge"].get("recovered"):
            qa_flags.append("barge_in_recovered")
        expected_entities = self._expected_entities(view, setup)
        actual_entities = self._actual_entities(book_args, ticket_args, expected_entities)
        writes: list[WriteRecord] = []
        for event in tool_results:
            if event.get("tool") not in {
                "book_appointment",
                "reschedule_appointment",
                "cancel_appointment",
            }:
                continue
            if not event.get("ok"):
                continue
            writes.append(
                WriteRecord(
                    tool=str(event["tool"]),
                    ok=True,
                    args=event.get("args") or {},
                    result={
                        "data": {
                            "booking": {
                                "booking_id": book.get("booking_id"),
                                "service_id": book.get("service_id")
                                or (event.get("args") or {}).get("service_id"),
                                "start": book.get("start"),
                                "address": book.get("address")
                                or (event.get("args") or {}).get("customer", {}).get("address", {}),
                            }
                        }
                    },
                )
            )
        transcript = [
            *[{"role": "caller", "text": text} for text in caller_utterances],
            *[{"role": "assistant", "text": text} for text in assistant],
        ]
        if len(transcript) < 2:
            transcript = [
                *[{"role": "caller", "text": chunk} for chunk in chunks],
                *[{"role": "assistant", "text": text} for text in assistant],
            ]
        return ScenarioExecution(
            scenario_id=view.id,
            tenant=view.tenant,
            mode="audio",
            outcome=outcome,
            service_id=service_id,
            booking_id=book.get("booking_id"),
            booking_ids=[book["booking_id"]] if book.get("booking_id") else [],
            booking_count=booking_count,
            ticket_count=len(tickets),
            ticket_id=ticket.get("ticket_id"),
            emergency_category=ticket.get("category"),
            safety_script=ticket.get("safety_script"),
            vulnerable_occupant=bool(ticket.get("vulnerable_occupant")),
            callback_count=1 if transfer_status in {"queued_callback", "no_answer"} else 0,
            transfer_status=transfer_status,
            handoff_packet=packet,
            write_count=sum(1 for event in booked if not event.get("replayed")),
            readbacks=len(readbacks),
            confirmation_queued=bool(book.get("confirmation_queued")),
            confirmation_count=1 if book.get("confirmation_queued") else 0,
            transcript=transcript,
            tool_calls=[
                {
                    "name": event.get("tool"),
                    "ok": event.get("ok"),
                    "args": event.get("args") or {},
                    "error_code": event.get("code"),
                }
                for event in tool_results
            ],
            writes=writes,
            response_text=" ".join(
                str(item["text"]) for item in transcript if item["role"] == "assistant"
            ),
            qa_flags=qa_flags,
            latency_ms=wall_ms,
            wall_ms=wall_ms,
            recording_ref=f"livekit:{result.get('call_id')}",
            turns_used=len(chunks),
            asr_entities=actual_entities,
            asr_expected_entities=expected_entities,
            barge_in_recovered=(
                bool(result["barge"]["recovered"]) if result.get("barge") else None
            ),
        )

    def _expected_entities(
        self, view: AgentScenarioView, setup: ScenarioSetup
    ) -> dict[str, str | None]:
        script = self.scripts[view.id]
        store = SQLiteAdapter(":memory:")
        for data in self.seeds.values():
            store.seed(data)
        facts = extract_facts(
            self.tenants[view.tenant],
            [turn.text for turn in script.turns],
            store,
            setup.now,
            caller_phone=setup.caller_phone,
        )
        return {
            "name": facts.name if facts.name != "Caller" else None,
            "phone": facts.phone,
            "line1": facts.address.line1 if facts.address else None,
            "zip": facts.address.zip if facts.address else None,
            "service_id": facts.service_id,
        }

    @staticmethod
    def _actual_entities(
        book_args: list[dict[str, Any]],
        ticket_args: list[dict[str, Any]],
        expected: dict[str, str | None],
    ) -> dict[str, str | None]:
        for args in reversed([*book_args, *ticket_args]):
            customer = args.get("customer") or {}
            address = customer.get("address") or {}
            if customer:
                return {
                    "name": customer.get("name"),
                    "phone": customer.get("phone"),
                    "line1": address.get("line1"),
                    "zip": address.get("zip"),
                    "service_id": args.get("service_id"),
                }
        return {key: None for key in expected}


__all__ = ["LiveKitAudioRunner", "LiveKitStack", "LiveKitStackError"]

"""LiveKit Agents worker for the local browser demo.

The worker trusts only the signed tenant claim minted by the local web process and
drives the same #4 policy/tools as the text runner. It adds transport, LFM3 audio
and turn-taking, not a second booking implementation.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    EndpointingOptions,
    InterruptionOptions,
    JobContext,
    TurnHandlingOptions,
    cli,
    function_tool,
)
from livekit.plugins import openai, silero

from forge_voice.config import AGENT_NAME, load_local_env
from forge_voice.policy.conversation import REFUSAL_PATTERN, YES_PATTERN
from forge_voice.runtime.audio_session import AudioCallSession
from forge_voice.runtime.claim_validation import validate_entrypoint
from forge_voice.runtime.hybrid import HybridRateLimitError, retry_async_chunks
from forge_voice.runtime.lfm3_audio import LFM3TTS
from forge_voice.runtime.session import Profile, SessionPlan, plan_session
from forge_voice.tenants import load_all_tenants
from forge_voice.web.claims import ClaimError

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TRACE_DIR = ROOT / "data" / "calls"


def build_llm(plan: SessionPlan) -> openai.LLM:
    common = {
        "model": plan.llm.model,
        "base_url": plan.llm.base_url,
        "temperature": 0.1,
        "max_completion_tokens": plan.turn_taking.max_reply_tokens,
        "parallel_tool_calls": False,
        "timeout": 30.0,
    }
    if plan.llm.provider == "groq":
        return openai.LLM(api_key=plan.llm.api_key or "", max_retries=1, **common)
    return openai.LLM(
        api_key="local",
        reasoning_effort="none",
        _strict_tool_schema=False,
        extra_body={"max_tokens": plan.turn_taking.max_reply_tokens},
        **common,
    )


def build_agent_session(plan: SessionPlan) -> AgentSession:
    """Construct the real LiveKit session from a tested, fully specified plan."""
    turn = plan.turn_taking
    stt = openai.STT(
        model=plan.stt.model,
        base_url=f"{plan.stt.base_url}/v1",
        api_key="local",
        language=plan.language,
    )
    tts = LFM3TTS(
        base_url=plan.tts.base_url,
        voice=plan.tts_voice,
        lang=plan.language,
        sample_rate=24000,
    )
    return AgentSession(
        stt=stt,
        llm=build_llm(plan),
        tts=tts,
        vad=silero.VAD.load(),
        turn_handling=TurnHandlingOptions(
            interruption=InterruptionOptions(
                enabled=turn.allow_interruptions,
                min_words=turn.min_interruption_words,
                min_duration=turn.min_interruption_duration,
                false_interruption_timeout=turn.false_interruption_timeout,
                resume_false_interruption=turn.resume_false_interruption,
            ),
            endpointing=EndpointingOptions(
                mode="dynamic",
                min_delay=turn.endpointing_min_delay,
                max_delay=turn.endpointing_max_delay,
            ),
        ),
        user_away_timeout=turn.user_away_timeout,
        max_tool_steps=4,
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_tools(call: AudioCallSession) -> list[Any]:
    """Expose exactly the eight product tools, all backed by the same policy session."""

    @function_tool
    async def lookup_customer(
        phone: str | None = None,
        name: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        zip: str | None = None,
        booking_id: str | None = None,
        include_bookings: bool = False,
    ) -> str:
        """Find or verify a caller record. Never read an existing booking without verification."""
        return call.lookup_customer(
            phone=phone,
            name=name,
            line1=line1,
            city=city,
            zip=zip,
            booking_id=booking_id,
            include_bookings=include_bookings,
        ).to_json()

    @function_tool
    async def get_service_area(zip: str, service_id: str | None = None) -> str:
        """Check whether a ZIP and optional service are inside the tenant service area."""
        return call.get_service_area(zip=zip, service_id=service_id).to_json()

    @function_tool
    async def get_availability(
        service_id: str,
        zip: str,
        preferred_date: str | None = None,
    ) -> str:
        """Return real open slots; never invent a time."""
        return call.get_availability(
            service_id=service_id,
            zip=zip,
            preferred_date=preferred_date,
        ).to_json()

    @function_tool
    async def book_appointment(
        slot_id: str | None = None,
        service_id: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        zip: str | None = None,
    ) -> str:
        """Read back a chosen slot; call again with no arguments after an explicit yes."""
        return call.book_appointment(
            slot_id=slot_id,
            service_id=service_id,
            name=name,
            phone=phone,
            line1=line1,
            city=city,
            zip=zip,
        ).to_json()

    @function_tool
    async def reschedule_appointment(
        booking_id: str | None = None,
        new_slot_id: str | None = None,
    ) -> str:
        """Read back and commit one reschedule after an explicit yes."""
        return call.reschedule_appointment(booking_id=booking_id, new_slot_id=new_slot_id).to_json()

    @function_tool
    async def cancel_appointment(booking_id: str | None = None) -> str:
        """Read back and commit one cancellation after an explicit yes."""
        return call.cancel_appointment(booking_id=booking_id).to_json()

    @function_tool
    async def create_emergency_ticket(
        description: str,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        zip: str | None = None,
    ) -> str:
        """Triage an emergency deterministically and return the 911-first script."""
        return call.create_emergency_ticket(
            description=description,
            name=name,
            phone=phone,
            line1=line1,
            city=city,
            zip=zip,
        ).to_json()

    @function_tool
    async def transfer_to_human(
        reason: str = "caller_request",
        mode: str = "live",
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        zip: str | None = None,
    ) -> str:
        """Transfer or queue a callback; never claim success early."""
        return call.transfer_to_human(
            reason=reason,
            mode=mode,
            name=name,
            phone=phone,
            line1=line1,
            city=city,
            zip=zip,
        ).to_json()

    return [
        lookup_customer,
        get_service_area,
        get_availability,
        book_appointment,
        reschedule_appointment,
        cancel_appointment,
        create_emergency_ticket,
        transfer_to_human,
    ]


def _last_user_text(chat_ctx: Any) -> str:
    for item in reversed(getattr(chat_ctx, "items", [])):
        if getattr(item, "role", None) != "user":
            continue
        content = getattr(item, "content", "")
        if isinstance(content, (list, tuple)):
            return " ".join(str(part) for part in content).strip()
        return str(content).strip()
    return ""


HYBRID_BOOKING_TOOL_NAMES = (
    "get_service_area",
    "get_availability",
    "transfer_to_human",
)


def _hybrid_selected_slot(text: str) -> int | None:
    lowered = text.lower()
    if re.search(r"\bfirst\b", lowered):
        return 0
    if re.search(r"\bsecond\b", lowered):
        return 1
    if re.search(r"\bthird\b", lowered):
        return 2
    if any(word in lowered for word in ("works", "that one", "book it", "sounds good")):
        return 0
    return None


class BookingAgent(Agent):
    def __init__(
        self,
        instructions: str,
        tools: list[Any],
        call: AudioCallSession,
        *,
        hybrid: bool = False,
    ) -> None:
        super().__init__(instructions=instructions, tools=tools)
        self._call = call
        self._hybrid = hybrid

    async def llm_node(
        self,
        chat_ctx: Any,
        tools: list[Any],
        model_settings: Any,
    ) -> Any:
        """Intercept emergencies before the model and speak only the policy script."""
        text = _last_user_text(chat_ctx) or self._call.last_utterance
        latest = self._call.last_utterance.strip()
        if latest and latest != text.strip():
            text = latest
        if self._hybrid:
            deterministic = self._hybrid_booking_turn(text)
            if deterministic is not None:
                yield deterministic
                return
        emergency = self._call.emergency_step(text) if text else None
        if emergency is not None:
            self._call.trace_event(
                "emergency_reply",
                stage=emergency.stage,
                ok=emergency.ok,
                error=emergency.error,
            )
            yield emergency.message
            return
        reprompt = self._call.entity_reprompt_step(text) if text else None
        if reprompt is not None:
            self._call.trace_event(
                "entity_guard_reply",
                ok=reprompt.ok,
                stage=reprompt.stage,
                error=reprompt.error,
            )
            yield reprompt.message
            return
        confirmation = self._call.confirmation_step(text) if text else None
        if confirmation is not None:
            yield confirmation
            return
        booking = self._call.booking_step(text) if text else None
        if booking is not None:
            yield booking
            return

        selected_tools = tools
        if self._hybrid:
            intent = self._call.policy.classify_intent(text) if text else None
            if intent is not None and intent.value in {"book", "emergency"}:
                by_name = {tool.info.name: tool for tool in tools}
                selected_tools = [
                    by_name[name] for name in HYBRID_BOOKING_TOOL_NAMES if name in by_name
                ]

        async def _stream():
            async for chunk in Agent.default.llm_node(
                self, chat_ctx, selected_tools, model_settings
            ):
                yield chunk

        def _on_retry(attempt: int, delay: float) -> None:
            self._call.trace_event("hybrid_retry", attempt=attempt, delay_seconds=delay)

        try:
            chunks = retry_async_chunks(_stream, on_retry=_on_retry) if self._hybrid else _stream()
            async for chunk in chunks:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    self._call.trace_event(
                        "llm_usage",
                        prompt_tokens=getattr(usage, "prompt_tokens", None),
                        completion_tokens=getattr(usage, "completion_tokens", None),
                        total_tokens=getattr(usage, "total_tokens", None),
                    )
                yield chunk
        except HybridRateLimitError as exc:
            self._call.trace_event(
                "hybrid_rate_limited",
                retry_after=exc.retry_after,
                message=str(exc),
            )
            raise

    def _hybrid_booking_turn(self, text: str) -> str | None:
        """Use the policy directly for the two write turns, avoiding extra LLM calls."""
        call = self._call
        if not text:
            return None
        if call.pending is not None:
            lowered = text.lower()
            if YES_PATTERN.search(lowered) and not REFUSAL_PATTERN.search(lowered):
                reply = call.book_appointment()
                if reply.ok and reply.stage == "booked":
                    call.trace_event("hybrid_deterministic_booking", stage="booked")
                    return reply.message
            return None
        if not call.offered_slots or not call.state.service_id:
            return None
        index = _hybrid_selected_slot(text)
        if index is None or index >= len(call.offered_slots):
            return None
        reply = call.book_appointment(
            slot_id=call.offered_slots[index],
            service_id=call.state.service_id,
        )
        if reply.ok and reply.stage == "readback":
            call.trace_event("hybrid_deterministic_booking", stage="readback")
            return reply.message
        return None


def _event_summary(event: object) -> dict[str, object]:
    data: dict[str, object] = {"event_type": getattr(event, "type", type(event).__name__)}
    for field in (
        "old_state",
        "new_state",
        "transcript",
        "is_final",
        "is_interruption",
        "detection_delay",
        "resumed",
        "agent_ended",
        "total_duration",
        "error",
    ):
        value = getattr(event, field, None)
        if value is not None:
            data[field] = str(value) if field == "error" else value
    item = getattr(event, "item", None)
    if item is not None:
        role = getattr(item, "role", None)
        if role is not None:
            data["role"] = role
        content = getattr(item, "content", None)
        if content is not None:
            data["content"] = (
                " ".join(str(part) for part in content)
                if isinstance(content, (list, tuple))
                else str(content)
            )
    return data


def _trace_path(call_id: str) -> Path:
    configured = os.environ.get("FORGE_VOICE_TRACE", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_TRACE_DIR / f"{call_id}.jsonl"


server = AgentServer(host="127.0.0.1")


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    secret = os.environ.get("LIVEKIT_API_SECRET", "").strip()
    if not secret:
        ctx.shutdown(reason="LIVEKIT_API_SECRET is required to verify tenant claims")
        return
    tenants = load_all_tenants(ROOT / "tenants")
    try:
        tenant, claim = validate_entrypoint(participant.metadata, ctx.room.name, secret, tenants)
    except ClaimError as exc:
        ctx.shutdown(reason=f"tenant claim rejected: {exc}")
        return

    trace_path = _trace_path(claim.call_id)
    call = AudioCallSession.from_repo(
        ROOT,
        tenant.tenant_id,
        claim.call_id,
        outbox_path=ROOT / "data" / "outbox.jsonl",
        trace_path=trace_path,
    )
    call.trace_event(
        "room_connected",
        room=ctx.room.name,
        tenant=tenant.tenant_id,
        participant=participant.identity,
    )
    plan = plan_session(os.environ.get("FORGE_VOICE_PROFILE", Profile.local.value), os.environ)
    call.trace_event("profile", profile=plan.profile.value, llm=plan.llm.provider)
    session = build_agent_session(plan)

    def on_user_transcript(event: Any) -> None:
        if getattr(event, "is_final", False):
            call.note_caller_utterance(getattr(event, "transcript", ""))

    def on_event(event: Any) -> None:
        call.trace_event("session_event", **_event_summary(event))

    session.on("user_input_transcribed", on_user_transcript)
    for event_name in (
        "agent_state_changed",
        "user_state_changed",
        "conversation_item_added",
        "overlapping_speech",
        "agent_false_interruption",
        "function_tools_executed",
        "error",
    ):
        session.on(event_name, on_event)

    async def on_shutdown(reason: str = "") -> None:
        call.trace_event("shutdown", reason=reason)
        call.close()

    ctx.add_shutdown_callback(on_shutdown)
    agent = BookingAgent(
        call.instructions,
        build_tools(call),
        call,
        hybrid=plan.llm.provider == "groq",
    )
    await session.start(agent=agent, room=ctx.room)
    await session.say(call.greeting, allow_interruptions=True)


def main() -> None:
    load_local_env(ROOT)
    cli.run_app(server)


if __name__ == "__main__":
    main()

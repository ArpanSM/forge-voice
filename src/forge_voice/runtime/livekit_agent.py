"""LiveKit Agents worker for the local browser demo.

The worker trusts only the signed tenant claim minted by the local web process and
drives the same #4 policy/tools as the text runner. It adds transport, LFM3 audio
and turn-taking, not a second booking implementation.
"""

from __future__ import annotations

import json
import os
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
from forge_voice.runtime.audio_session import AudioCallSession
from forge_voice.runtime.claim_validation import validate_entrypoint
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
        return openai.LLM(api_key=plan.llm.api_key or "", **common)
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
        state: str = "CA",
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
            state=state,
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
        window_days: int = 7,
    ) -> str:
        """Return real open slots. Never offer a time that this tool did not return."""
        return call.get_availability(
            service_id=service_id,
            zip=zip,
            preferred_date=preferred_date,
            window_days=window_days,
        ).to_json()

    @function_tool
    async def book_appointment(
        slot_id: str | None = None,
        service_id: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        state: str = "CA",
        zip: str | None = None,
    ) -> str:
        """Read back one chosen slot, then commit only after an explicit yes.

        The first call returns stage=readback. Say it and ask for a clear yes. After the yes,
        call this tool again with no arguments to commit the exact read-back.
        """
        return call.book_appointment(
            slot_id=slot_id,
            service_id=service_id,
            name=name,
            phone=phone,
            line1=line1,
            city=city,
            state=state,
            zip=zip,
        ).to_json()

    @function_tool
    async def reschedule_appointment(
        booking_id: str | None = None,
        new_slot_id: str | None = None,
        reason: str | None = None,
    ) -> str:
        """Read back and then commit one reschedule after an explicit yes."""
        return call.reschedule_appointment(
            booking_id=booking_id, new_slot_id=new_slot_id, reason=reason
        ).to_json()

    @function_tool
    async def cancel_appointment(booking_id: str | None = None, reason: str | None = None) -> str:
        """Read back and then commit one cancellation after an explicit yes."""
        return call.cancel_appointment(booking_id=booking_id, reason=reason).to_json()

    @function_tool
    async def create_emergency_ticket(
        description: str,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        state: str = "CA",
        zip: str | None = None,
    ) -> str:
        """Triage a reported emergency deterministically and return the 911-first script."""
        return call.create_emergency_ticket(
            description=description,
            name=name,
            phone=phone,
            line1=line1,
            city=city,
            state=state,
            zip=zip,
        ).to_json()

    @function_tool
    async def transfer_to_human(
        reason: str = "caller_request",
        mode: str = "live",
        summary: str | None = None,
        name: str | None = None,
        phone: str | None = None,
        line1: str | None = None,
        city: str | None = None,
        state: str = "CA",
        zip: str | None = None,
    ) -> str:
        """Transfer or queue a callback with a complete packet. Never claim success early."""
        return call.transfer_to_human(
            reason=reason,
            mode=mode,
            summary=summary,
            name=name,
            phone=phone,
            line1=line1,
            city=city,
            state=state,
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


class BookingAgent(Agent):
    def __init__(self, instructions: str, tools: list[Any], call: AudioCallSession) -> None:
        super().__init__(instructions=instructions, tools=tools)
        self._call = call

    async def llm_node(
        self,
        chat_ctx: Any,
        tools: list[Any],
        model_settings: Any,
    ) -> Any:
        """Intercept emergencies before the model and speak only the policy script."""
        text = _last_user_text(chat_ctx) or self._call.last_utterance
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
        async for chunk in Agent.default.llm_node(self, chat_ctx, tools, model_settings):
            yield chunk


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


server = AgentServer()


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
    agent = BookingAgent(call.instructions, build_tools(call), call)
    await session.start(agent=agent, room=ctx.room)
    await session.say(call.greeting, allow_interruptions=True)


def main() -> None:
    load_local_env(ROOT)
    cli.run_app(server)


if __name__ == "__main__":
    main()

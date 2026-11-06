"""Minimal LiveKit booking agent for the voice spike.

Run with:
    python -m spike.agent console     # local mic/speaker, no room
    python -m spike.agent dev         # LiveKit Cloud / browser

The LLM talks and extracts; the booking policy owns confirmation, slot validity
and the single idempotent write.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    RunContext,
    cli,
    function_tool,
)
from livekit.plugins import openai, silero

from .booking import BookingStore, Customer, Service, Slot
from .lfm3_audio import LFM3TTS

ROOT = Path(__file__).resolve().parents[1]


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

STORE = BookingStore()
STORE.add_service(Service("drain", "Drain cleaning", 60))
STORE.add_service(Service("hvac", "AC repair", 90))
for slot in [
    Slot(
        "drain_mon_0900",
        "drain",
        "Alex",
        "Monday 9 November, 9:00 am",
        frozenset({"94107"}),
    ),
    Slot(
        "drain_mon_1100",
        "drain",
        "Alex",
        "Monday 9 November, 11:00 am",
        frozenset({"94107"}),
    ),
    Slot(
        "hvac_mon_1300",
        "hvac",
        "Blair",
        "Monday 9 November, 1:00 pm",
        frozenset({"94107"}),
    ),
]:
    STORE.add_slot(slot)


def _json(data: object) -> str:
    return json.dumps(data, ensure_ascii=False)


class BookingAgent(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions=(
                "You are the booking assistant for Harborlight Home Services, a plumbing, "
                "HVAC and electrical company. Keep every reply to one or two short sentences. "
                "Ask one question at a time. Collect the service, full address, ZIP code, "
                "phone number and preferred day. Ask the caller to say the ZIP and phone one "
                "digit at a time; never guess a ZIP or phone. If a ZIP is not five digits or "
                "a phone is not ten digits, ask the caller to repeat it. Use get_availability "
                "before offering any slot; never invent a slot. After get_availability, say the "
                "available times out loud and ask which one they want. Read the chosen slot "
                "back and ask for a clear yes. "
                "Only call book_appointment with confirmed=true after the caller says yes. "
                "If the caller reports gas, fire, flooding or another emergency, tell them to "
                "call 911 or the emergency line and transfer them to a human. Never invent a "
                "price; give a range only if the knowledge base provides one. If no slot "
                "works, offer another slot or transfer to a human."
            ),
            tools=[get_availability, book_appointment, transfer_to_human],
        )


def _service_id(value: str) -> str:
    text = value.lower()
    if "drain" in text:
        return "drain"
    if any(word in text for word in ("hvac", "ac ", "air", "furnace", "heat")):
        return "hvac"
    return text.strip()


def _digits(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def _normalize_zip(value: str) -> str | None:
    digits = _digits(value)
    return digits if len(digits) == 5 else None


def _normalize_phone(value: str) -> str | None:
    digits = _digits(value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits if len(digits) == 10 else None


@function_tool
async def get_availability(ctx: RunContext, service: str, zip_code: str) -> str:
    """Return available appointment slots for a service and ZIP code."""
    zip_code = _normalize_zip(zip_code) or ""
    if not zip_code:
        return _json({"ok": False, "error": "invalid_zip"})
    slots = STORE.get_availability(_service_id(service), zip_code)
    return _json(
        {
            "ok": True,
            "slots": [
                {
                    "slot_id": slot.slot_id,
                    "technician": slot.technician,
                    "start": slot.start,
                }
                for slot in slots
            ],
        }
    )


def _last_user_text(ctx: RunContext) -> str:
    for item in reversed(ctx.session.history.items):
        if getattr(item, "role", None) == "user":
            content = getattr(item, "content", "")
            if isinstance(content, list):
                return " ".join(str(part) for part in content).lower()
            return str(content).lower()
    return ""


AFFIRMATIVES = (
    "yes",
    "yeah",
    "yep",
    "correct",
    "confirm",
    "book it",
    "sounds good",
    "okay",
    "ok",
)


@function_tool
async def book_appointment(
    ctx: RunContext,
    slot_id: str,
    customer_name: str,
    phone: str,
    address: str,
    zip_code: str,
    confirmed: bool,
) -> str:
    """Book one slot after the caller has confirmed the read-back."""
    if not any(word in _last_user_text(ctx) for word in AFFIRMATIVES):
        return _json({"ok": False, "error": "explicit_confirmation_required"})
    normalized_zip = _normalize_zip(zip_code)
    if not normalized_zip:
        return _json({"ok": False, "error": "invalid_zip"})
    normalized_phone = _normalize_phone(phone)
    if not normalized_phone:
        return _json({"ok": False, "error": "invalid_phone"})
    customer = Customer(
        name=customer_name,
        phone=normalized_phone,
        address=address,
        zip_code=normalized_zip,
    )
    result = STORE.book_appointment(
        customer=customer,
        service_id=STORE.slots[slot_id].service_id if slot_id in STORE.slots else "",
        slot_id=slot_id,
        idempotency_key=f"{ctx.function_call.call_id}:{slot_id}",
        confirmed=confirmed,
    )
    if result.ok and result.booking:
        return _json(
            {
                "ok": True,
                "booking_id": result.booking.booking_id,
                "slot": result.booking.slot.start,
                "replayed": result.replayed,
            }
        )
    return _json({"ok": False, "error": result.error})


@function_tool
async def transfer_to_human(ctx: RunContext, reason: str) -> str:
    """Transfer the caller to a human when requested or when the booking cannot proceed."""
    return _json({"ok": True, "transfer": True, "reason": reason})


server = AgentServer()


def _llm() -> openai.LLM:
    provider = os.environ.get("LLM_PROVIDER", "lfm3").strip().lower()
    if provider == "orcarouter":
        return openai.LLM(
            model=os.environ.get("ORCAROUTER_MODEL", "tencent/hy4-preview-free"),
            base_url=os.environ.get(
                "ORCAROUTER_BASE_URL", "https://api.orcarouter.ai/v1"
            ),
            api_key=os.environ.get("ORCAROUTER_API_KEY", ""),
            reasoning_effort="none",
            temperature=0.1,
            max_completion_tokens=200,
        )
    if provider == "groq":
        return openai.LLM(
            model=os.environ.get("GROQ_MODEL", "qwen/qwen3.8-27b"),
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ.get("GROQ_API_KEY", ""),
            temperature=0.1,
            max_completion_tokens=200,
        )
    # Local LFM3-Audio-2B handles chat, STT and TTS; one model in VRAM.
    return openai.LLM(
        model=os.environ.get("LFM3_AUDIO_MODEL", "lfm3-audio-2b"),
        base_url=os.environ.get("LFM3_AUDIO_BASE_URL", "http://127.0.0.1:8082") + "/v1",
        api_key="local",
        reasoning_effort="none",
        temperature=0.1,
        parallel_tool_calls=False,
        tool_choice="auto",
        _strict_tool_schema=False,
        extra_body={"max_tokens": 200},
    )


def _session() -> AgentSession:
    stt = openai.STT(
        model=os.environ.get("LFM3_AUDIO_MODEL", "lfm3-audio-2b"),
        base_url=os.environ.get("LFM3_AUDIO_BASE_URL", "http://127.0.0.1:8082") + "/v1",
        api_key="local",
        language=os.environ.get("LFM3_LANG", "en"),
    )
    llm = _llm()
    tts = LFM3TTS(
        base_url=os.environ.get("LFM3_AUDIO_BASE_URL", "http://127.0.0.1:8082"),
        voice=os.environ.get("LFM3_TTS_VOICE", "female"),
        lang=os.environ.get("LFM3_LANG", "en"),
    )
    return AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=silero.VAD.load(),
    )


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    session = _session()
    await session.start(agent=BookingAgent(), room=ctx.room)
    await session.generate_reply(
        instructions=(
            "Greet the caller, say you are Harborlight Home Services, and ask what they need."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)

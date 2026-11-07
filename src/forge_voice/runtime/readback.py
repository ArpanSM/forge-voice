"""One spoken read-back formatter shared by the text and audio call paths."""

from __future__ import annotations

from datetime import datetime

from forge_voice.policy import ReadbackPayload


def format_readback(
    payload: ReadbackPayload,
    *,
    action: str = "book",
    old_start: datetime | None = None,
) -> str:
    location = f"{payload.address.line1}, {payload.address.city} {payload.address.zip}"
    when = datetime.fromisoformat(payload.start).strftime("%A %-d %B at %-I:%M %p")
    if action == "move" and old_start is not None:
        previous = old_start.strftime("%A %-d %B at %-I:%M %p")
        return (
            f"Just to confirm: move your {payload.service_name} from {previous} to {when} "
            f"with {payload.technician_name} at {location}, for {payload.customer_name} at "
            f"{payload.contact_phone}. Should I move it?"
        )
    if action == "cancel":
        return (
            f"Just to confirm: cancel the {payload.service_name} on {when} with "
            f"{payload.technician_name} at {location}, for {payload.customer_name} at "
            f"{payload.contact_phone}. Should I cancel it?"
        )
    return (
        f"Just to confirm: {payload.service_name} on {when} with "
        f"{payload.technician_name} at {location}, for {payload.customer_name} at "
        f"{payload.contact_phone}. Should I book that?"
    )


__all__ = ["format_readback"]

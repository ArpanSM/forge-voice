"""Tiny browser demo server for the voice spike.

Serves a LiveKit browser page and a short-lived room token. This is a spike
artifact, not the product frontend: no auth, no tenancy, localhost only.

Run:
    python -m spike.token_server
    # or: make spike-token
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from livekit import api

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

app = FastAPI(title="forge-voice spike token server")

_SAFE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _safe(value: str, fallback: str) -> str:
    return value if _SAFE.fullmatch(value) else fallback


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "ok": True,
        "livekit_url": bool(os.environ.get("LIVEKIT_URL")),
        "api_key": bool(os.environ.get("LIVEKIT_API_KEY")),
        "api_secret": bool(os.environ.get("LIVEKIT_API_SECRET")),
    }


@app.get("/token")
async def token(
    room: str = Query("spike-browser"),
    identity: str = Query(""),
) -> dict[str, str]:
    room = _safe(room, "spike-browser")
    identity = _safe(identity, f"caller-{uuid.uuid4().hex[:8]}")
    url = os.environ.get("LIVEKIT_URL", "").strip()
    key = os.environ.get("LIVEKIT_API_KEY", "").strip()
    secret = os.environ.get("LIVEKIT_API_SECRET", "").strip()
    if not (url and key and secret):
        return {
            "error": "LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET are required"
        }

    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    jwt = (
        api.AccessToken(key, secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .with_ttl(timedelta(minutes=10))
        .to_jwt()
    )
    return {"url": url, "token": jwt, "room": room, "identity": identity}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Forge Voice — spike browser</title>
  <script src="https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"></script>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { max-width: 720px; margin: 40px auto; padding: 0 20px; line-height: 1.5; }
    label { display: block; margin: 12px 0 4px; font-weight: 600; }
    input { width: 100%; box-sizing: border-box; padding: 8px; font: inherit; }
    button { padding: 9px 14px; margin: 8px 8px 0 0; font: inherit; cursor: pointer; }
    #status { margin-top: 16px; padding: 10px 12px; border: 1px solid currentColor; border-radius: 8px; }
    #log { margin-top: 12px; font-family: ui-monospace, monospace; font-size: 13px; white-space: pre-wrap; }
    audio { display: none; }
  </style>
</head>
<body>
  <h1>Forge Voice — spike browser</h1>
  <p>Join the LiveKit room, allow the microphone, and talk to the booking agent. This is a
  throwaway spike page; the token endpoint is localhost-only.</p>
  <label for="room">Room</label>
  <input id="room" value="spike-browser" />
  <label for="identity">Identity</label>
  <input id="identity" />
  <div>
    <button id="join">Join call</button>
    <button id="leave" disabled>Leave</button>
    <button id="play" disabled>Play agent audio</button>
  </div>
  <div id="status">Disconnected</div>
  <div id="log"></div>
  <script>
    const { Room, RoomEvent, Track } = LivekitClient;
    const room = new Room({ adaptiveStream: true, dynacast: true });
    const status = document.getElementById("status");
    const log = document.getElementById("log");
    const join = document.getElementById("join");
    const leave = document.getElementById("leave");
    const play = document.getElementById("play");
    const audioEls = [];

    function setStatus(text) { status.textContent = text; }
    function note(text) { log.textContent += text + "\\n"; }

    document.getElementById("identity").value =
      "browser-" + Math.random().toString(36).slice(2, 8);

    room.on(RoomEvent.Connected, () => {
      setStatus("Connected to " + room.name);
      note("connected");
      leave.disabled = false;
      play.disabled = false;
    });
    room.on(RoomEvent.Disconnected, () => {
      setStatus("Disconnected");
      note("disconnected");
      join.disabled = false;
      leave.disabled = true;
      play.disabled = true;
    });
    room.on(RoomEvent.ParticipantConnected, (p) => note("participant: " + p.identity));
    room.on(RoomEvent.TrackSubscribed, (track, pub, participant) => {
      note("track: " + participant.identity + " " + track.kind);
      if (track.kind === Track.Kind.Audio) {
        const el = track.attach();
        el.autoplay = true;
        el.playsInline = true;
        document.body.appendChild(el);
        audioEls.push(el);
        el.play().catch(() => note("autoplay blocked; press Play agent audio"));
      }
    });
    room.on(RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach((el) => el.remove());
    });

    join.addEventListener("click", async () => {
      join.disabled = true;
      try {
        const roomName = document.getElementById("room").value.trim() || "spike-browser";
        const identity = document.getElementById("identity").value.trim();
        const res = await fetch("/token?room=" + encodeURIComponent(roomName) +
          "&identity=" + encodeURIComponent(identity));
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || ("HTTP " + res.status));
        await room.connect(data.url, data.token);
        await room.localParticipant.setMicrophoneEnabled(true);
        setStatus("Connected to " + data.room + " as " + data.identity);
        note("microphone enabled");
      } catch (err) {
        setStatus("Error: " + err.message);
        note(String(err));
        join.disabled = false;
      }
    });

    leave.addEventListener("click", async () => {
      await room.disconnect();
    });

    play.addEventListener("click", async () => {
      for (const el of audioEls) {
        try { await el.play(); } catch (err) { note("play failed: " + err.message); }
      }
    });
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("SPIKE_TOKEN_PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)

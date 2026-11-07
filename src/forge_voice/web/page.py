"""The local browser page: a tenant picker, one call button and a short demo guide."""

from __future__ import annotations

import json


def render_page(tenants: list[dict[str, str]]) -> str:
    options = "\n".join(
        f'<option value="{tenant["slug"]}">{tenant["name"]}</option>' for tenant in tenants
    )
    tenant_json = json.dumps(tenants, separators=(",", ":")).replace("</", "<\\/")
    return _PAGE.replace("__TENANT_OPTIONS__", options).replace("__TENANTS_JSON__", tenant_json)


_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Forge Voice — local browser demo</title>
  <script src="/static/livekit-client.umd.min.js"></script>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { max-width: 860px; margin: 36px auto; padding: 0 20px; line-height: 1.55; }
    h1 { margin-bottom: 4px; }
    .sub { color: #777; margin-top: 0; }
    .card { border: 1px solid #8884; border-radius: 12px; padding: 16px 18px; margin: 16px 0; }
    label { display: block; margin: 8px 0 4px; font-weight: 600; }
    select, button { padding: 10px 14px; font: inherit; border-radius: 8px; }
    button { cursor: pointer; margin: 8px 8px 0 0; }
    button:disabled { cursor: not-allowed; opacity: .5; }
    #status { margin-top: 14px; padding: 10px 12px; border-radius: 8px; background: #8881; }
    #transcript { min-height: 120px; max-height: 320px; overflow-y: auto; padding: 10px 12px;
      border: 1px solid #8884; border-radius: 8px; white-space: pre-wrap; }
    .caller { color: #2f7ed8; }
    .agent { color: #2c9a5e; }
    .hint { font-size: .94rem; color: #777; }
    code { background: #8881; padding: 1px 5px; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>Forge Voice — local browser demo</h1>
  <p class="sub">Self-hosted LiveKit at <code>ws://localhost:7880</code> · page at
  <code>http://localhost:8000</code> · LFM3-Audio-2B on this machine.</p>

  <div class="card">
    <label for="tenant">Business</label>
    <select id="tenant">__TENANT_OPTIONS__</select>
    <div>
      <button id="start">Start call</button>
      <button id="hangup" disabled>Hang up</button>
    </div>
    <div id="status">Idle. Choose a business and start the call.</div>
  </div>

  <div class="card">
    <strong>Disclosure:</strong> you are talking to an <strong>AI</strong> virtual assistant.
    This call is <strong>recorded</strong> for quality and synthetic demo purposes. Ask for a
    person at any time.
    <p class="hint">Demo flow: greeting → “I need a drain cleaning” → give the ZIP one digit
    at a time → pick a slot → hear the read-back → say “yes” → one confirmation. For the
    emergency path, say “I smell gas” and follow the 911-first instruction and on-call
    handoff. An unknown tenant fails closed at the token endpoint.</p>
  </div>

  <div class="card">
    <strong>Transcript</strong>
    <div id="transcript"></div>
  </div>

  <audio id="agent-audio" autoplay playsinline></audio>

  <script>
    const { Room, RoomEvent, Track } = LivekitClient;
    const tenants = __TENANTS_JSON__;
    const tenantSelect = document.getElementById("tenant");
    const startButton = document.getElementById("start");
    const hangupButton = document.getElementById("hangup");
    const status = document.getElementById("status");
    const transcript = document.getElementById("transcript");
    const agentAudio = document.getElementById("agent-audio");
    let room = null;
    const seen = new Set();

    function setStatus(text) { status.textContent = text; }
    function addLine(who, text, klass) {
      const line = document.createElement("div");
      line.className = klass;
      line.textContent = who + ": " + text;
      transcript.appendChild(line);
      transcript.scrollTop = transcript.scrollHeight;
    }

    function makeRoom() {
      const next = new Room({ adaptiveStream: true, dynacast: true });
      next.on(RoomEvent.Connected, () => {
        setStatus("Connected to " + next.name + ". Speak after the greeting.");
        hangupButton.disabled = false;
      });
      next.on(RoomEvent.Disconnected, () => {
        setStatus("Call ended.");
        startButton.disabled = false;
        hangupButton.disabled = true;
      });
      next.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
        if (track.kind === Track.Kind.Audio) {
          track.attach(agentAudio);
          agentAudio.play().catch(() => {});
          setStatus("Agent audio connected.");
        }
      });
      next.on(RoomEvent.TranscriptionReceived, (segments, participant) => {
        const who = participant && participant.identity
          ? participant.identity
          : "participant";
        for (const segment of segments || []) {
          if (!segment.final) continue;
          const key = (segment.id || segment.text) + who;
          if (seen.has(key)) continue;
          seen.add(key);
          const klass = who.includes("agent") ? "agent" : "caller";
          addLine(klass === "agent" ? "Agent" : "Caller", segment.text, klass);
        }
      });
      return next;
    }

    startButton.addEventListener("click", async () => {
      startButton.disabled = true;
      setStatus("Requesting a short-lived tenant token…");
      try {
        const identity = "browser-" + Math.random().toString(36).slice(2, 10);
        const response = await fetch("/token", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ tenant: tenantSelect.value, identity }),
        });
        const data = await response.json();
        if (!response.ok || data.error) {
          throw new Error(data.error || ("HTTP " + response.status));
        }
        room = makeRoom();
        await room.connect(data.url, data.token);
        await room.localParticipant.setMicrophoneEnabled(true);
        setStatus("Connected to " + data.room + " as " + data.identity + ". Allow the mic.");
      } catch (error) {
        setStatus("Error: " + error.message);
        startButton.disabled = false;
      }
    });

    hangupButton.addEventListener("click", async () => {
      if (room) await room.disconnect();
    });

    tenantSelect.addEventListener("change", () => {
      const selected = tenants.find((item) => item.slug === tenantSelect.value);
      if (selected) setStatus("Ready to call " + selected.name + ".");
    });
  </script>
</body>
</html>
"""

# Recording a real browser call (manual follow-up)

**What this is:** the exact procedure for replacing the captioned storyboard with a real local
browser-call recording, plus the acceptance check.
**For:** the person recording the demo on the GPU laptop.
**Status:** **not done**. The committed `forge-voice-demo-90s.webm` and
`forge-voice-walkthrough-5min.webm` are storyboards built from real dashboard/call records; they
contain no call audio. Do not describe them as a live call recording.

## 1. Prepare the local stack

```bash
cd /path/to/forge-voice
lfm3 audio                       # wait for http://127.0.0.1:8082/health
cp .env.example .env.local       # first run only; random LiveKit dev secret
make demo                        # Compose when available, host binaries otherwise
```

Open <http://localhost:8000>, confirm `/health` is green, and check `make health`. Use the
fully local profile for the recording unless the Groq key is present and the hybrid path has
been smoke-tested. Do not record a paid/hosted path.

## 2. Use clean audio and the demo script

- Use a quiet room, a wired headset or a clean synthetic caller; no fan, keyboard or room echo.
- Keep every caller turn short. Do not hold one long utterance across the VAD boundary.
- Speak ZIP and phone digits one at a time. Do not rely on degraded/noisy ZIP recognition.
- Leave no long silence; the agent has no proactive silence prompt.
- Demo sequence: disclosure → book → service/name/address/ZIP/phone → two or three real slots
  → pick one → hear the read-back → explicit “yes” → one booking → emergency (911-first,
  ticket, **simulated** on-call transfer or callback) → dashboard.
- The transfer is a synthetic `TransferSimulator`; it is not a live human. Say “simulated
  transfer” or “queued callback” in the recording, never “a person answered”.
- Use synthetic tenant/customer data only. Never show a real phone number, address or name.

## 3. Record the browser page and audio

### Option A — OBS (human microphone, preferred for the real demo)

1. Add a **Window Capture** source for Chrome at `http://localhost:8000` (1920×1080 canvas,
   1280×720 output).
2. Add an **Audio Output Capture** or **Audio Input Capture** source for the headset mix. Test
   that both the caller and the agent are audible; do not record only the microphone.
3. Set OBS output to MP4 or MKV, 30 fps, hardware encoder if available; record 60–90 seconds
   for the short demo and a separate ~5-minute dashboard/admin/runbook walkthrough.
4. Add captions in OBS or burn them in post; captions must state “local synthetic demo”, the
   measured p95 5.3 s and the known gaps.
5. Start the call after recording starts; stop after the dashboard view. Do not cut a failed
   take into a success claim.

### Option B — Playwright fake microphone (repeatable, no human)

```bash
mkdir -p /tmp/opencode/pw && cd /tmp/opencode/pw && npm install playwright
cd /path/to/forge-voice
NODE_PATH=/tmp/opencode/pw/node_modules \
  CHROME_PATH=/usr/bin/google-chrome node scripts/browser_smoke.js
```

`browser_smoke.js` proves the page joins the room with Chrome's fake microphone. It is **not**
a spoken booking recording: the fake microphone is silence. To record a real spoken call,
use OBS (Option A) or feed a known caller WAV through the Playwright page and capture the page
plus system audio. Label a fake-mic clip as a **connection smoke**, not a booking demo.

## 4. Acceptance check

Do not publish unless all of these are true:

- [ ] 60–90 seconds for the short demo; the longer walkthrough covers dashboard, admin and
      runbook.
- [ ] Page and call audio are both audible; no clipping, dropouts or silent stretches.
- [ ] The caller books one appointment: read-back, explicit yes, one booking ID, confirmation
      queued.
- [ ] The emergency path shows the 911-first script, a ticket and an **honest** transfer or
      callback. “Connected” is labelled simulated; no claim of a live human.
- [ ] The dashboard shows the booked/emergency calls, transcript/timeline and latency.
- [ ] Known limits are stated: local-only, no production SLA, p95 5.3 s, barge-in ~0.88 s, no
      sub-3 s/sub-2 s claim, silence/degraded-ZIP/long-utterance gaps.
- [ ] No real PII, no secrets, no hosted/paid claim.
- [ ] Captions match the audio; the file plays end to end and is committed with a checksum.
- [ ] `ffprobe`/`ffmpeg` reports a sane duration, resolution and audio stream.

If a gate fails, keep the recording local and state the failure. Do not replace the storyboard
with a clip that implies a pass.

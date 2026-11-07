# Demo video and walkthrough

**What this is:** the public proof assets for the local voice booking kit, plus the exact
commands used to record them.
**For:** a client or reviewer who will not run a GPU laptop on the first pass.
**Status:** a **storyboard/walkthrough** built from the real local dashboard and documented
call records. It has **no call audio** and is **not a live browser-call recording**. A live
captioned browser-call recording is a manual follow-up; the exact procedure is in
[RECORDING.md](proof/RECORDING.md).

## Watch

- [90-second captioned storyboard](proof/forge-voice-demo-90s.webm) — problem, book, read-back,
  one booking, emergency/handoff, dashboard and known limits.
- [5-minute dashboard, admin and runbook walkthrough](proof/forge-voice-walkthrough-5min.webm)
  — monitoring, per-call detail, review, admin editor, runbook and the honest gate status.

Both videos are captioned and say on screen that they are storyboards/walkthroughs assembled
from real local records. The live voice call is not faked: the live path needs the host GPU
and runs by appointment. `make demo` is the reproducible local path. **The live captioned
browser-call recording is not done.**

## What is real in the video

| Asset | Source |
|---|---|
| Dashboard cards, alerts and call table | Real #7 app served from seeded #4 call records in `data/monitoring`. |
| Booked call detail | `call_summit_text_book_03` — real policy/tools run; transcript, read-back, booking ID and tool timeline. |
| Emergency call detail | `call_harborlight_text_emergency_01` — real emergency triage and ticket; the transfer is a **simulated connected transfer** (synthetic `TransferSimulator`, no live human). |
| Review page | Real `/review` route and weekly sample. |
| Admin page | Real `/admin` validating YAML editor for both tenants. |
| Runbook slide | The committed `docs/runbook.md` rendered locally. |
| Eval numbers | The committed reports under `reports/`, including the failed local audio gate. |

**Not real in the video:** the spoken call audio and the browser call. It is a captioned
storyboard of the documented demo script and the real call records, not a screen recording of a
human speaking to the agent. The browser-origin smoke (`scripts/browser_smoke.js`) proves the
page can join a room; it does not prove a full spoken booking. The emergency “connected” status
comes from the synthetic transfer simulator, not a live human. A live captioned browser-call
recording is a manual follow-up; [RECORDING.md](proof/RECORDING.md) gives the exact steps and
acceptance check.

## Screenshots

The committed screenshots are in [`docs/proof/screenshots/`](proof/screenshots/). They were
captured with Playwright from the running app:

```bash
cd /path/to/forge-voice
PYTHONPATH=src python3.12 -m forge_voice.monitoring.seed
PYTHONPATH=src python3.12 -m forge_voice.web.app &
NODE_PATH=/path/to/node_modules node scripts/capture_proof.js
```

## Record the videos yourself

Prerequisites: Node + Playwright and Chrome. The recorder uses Playwright's bundled ffmpeg, so
a system `ffmpeg` is optional.

```bash
mkdir -p /tmp/opencode/pw && cd /tmp/opencode/pw
npm install playwright
cd /path/to/forge-voice

NODE_PATH=/tmp/opencode/pw/node_modules \
  node scripts/record_proof.js docs/proof/demo-player.html \
  docs/proof/forge-voice-demo-90s.webm

NODE_PATH=/tmp/opencode/pw/node_modules \
  node scripts/record_proof.js docs/proof/walkthrough-player.html \
  docs/proof/forge-voice-walkthrough-5min.webm
```

The players auto-advance and are click/arrow navigable. The recording scripts wait for each
player's declared total duration, then save the video. Convert to MP4 if a site requires it:

```bash
~/.cache/ms-playwright/ffmpeg-1013/ffmpeg-linux \
  -i docs/proof/forge-voice-demo-90s.webm \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart \
  docs/proof/forge-voice-demo-90s.mp4
```

## 90-second storyboard

| Time | Picture | Caption |
|---:|---|---|
| 0:00 | Title | A home-services booking agent that can prove what it did. |
| 0:07 | Problem | Most demos show the first call; they miss turn-taking, writes, triage and handoff. |
| 0:14 | Architecture | Browser → self-hosted LiveKit → agent → LFM3; Groq is the runtime hybrid LLM, Orca is an eval-only fallback. |
| 0:22 | Caller page | Disclosure, tenant claim, start call. |
| 0:29 | Booked call | Real service/address/availability; one booking, no QA flags. |
| 0:37 | Read-back | Exact read-back, explicit yes, policy token, idempotent write. |
| 0:44 | One booking | Replay-safe write; confirmation queued once; audit timeline. |
| 0:51 | Emergency | 911-first script, structured ticket, simulated transfer or callback. |
| 0:58 | Dashboard | Outcome, transcript, tool timeline, latency, alerts. |
| 1:05 | Limits | p95 5.3 s, barge-in ~0.88 s, no sub-3 s claim; known gaps. |
| 1:13 | Offer | Scope, build, evaluate, deploy, monitor and hand over. |
| 1:20 | Start here | README, local quickstart, case study, learning map, evaluation. |

## 5-minute walkthrough storyboard

1. What the walkthrough is and is not (local screen recording, not hosted).
2. The local stack and the telephony boundary.
3. Caller page and signed tenant claim.
4. Dashboard cards, filters and alerts.
5. Booked call detail and the one write.
6. Read-back, token and idempotency.
7. Emergency detail and the 911-first script.
8. No-answer handoff → honest callback.
9. Aggregates and the alert thresholds.
10. Weekly review and scenario candidates.
11. Admin editor and the same schema the agent loads.
12. YAML advanced fields and fail-closed validation.
13. Runbook start/recover/stop.
14. Eval gate status, including the failed local audio gate.
15. Known limits and the demo script that avoids them.
16. Handover and the 30-day support boundary.

## Honest limits

- Local-only; there is no hosted URL, Cloud transport, SIP or TURN.
- The measured 10-turn p95 first audio is **5.3 s**; barge-in yield is **~0.88 s**.
- Do not claim sub-3 s, sub-2 s or sub-1 s, or a production SLA.
- The known gaps are real: no proactive silence prompt, degraded ZIP recognition and no
  long-utterance turn-taking guard. The demo uses clean audio, short turns, ZIP digits one at a
  time and no long silence.
- The local audio emergency handoff currently fails on a real LFM3 ASR miss (ZIP misheard);
  see the eval report and case study. The video does not hide that.

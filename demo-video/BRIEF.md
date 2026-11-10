# Forge Voice — basic narrated walkthrough + launch film

Produce two videos for `/home/arpan/Forge/forge-voice`:

1. a **narrated 65–75s Argo walkthrough** of the **real local dashboard and call records**;
2. a **30s Huashu Motion launch film**, music and effects only.

Keep this **basic**: dashboard → booked call → emergency → weekly review → admin → limits. Do **not** attempt a live browser/WebRTC call, do not start LiveKit, and do not fake call audio. The public proof is a text-mode local demo; the live audio recording is a manual follow-up. Work in `/home/arpan/Forge/forge-voice/demo-video`. Do not upload, commit, or push.

## Environment

- The scaffold is copied from the proven RAG demo-video: `node_modules`, Argo, Huashu, Video Director, LFM3 adapter, scripts. Use `npx argo ...` and `npx om ...`.
- `PATH=/tmp/opencode/bin:$PATH` for ffmpeg/ffprobe.
- LFM3 audio: `lfm3 audio`; health `http://127.0.0.1:8082/health`; `POST /tts` JSON `{"input":"...","voice":"...","lang":"en"}`. The adapter converts PCM16 to Argo float32 WAV.
- The local dashboard is already running at `http://127.0.0.1:8000` (seeded). If it stops, run `make dashboard` from the repo root. It serves `/dashboard`, `/calls/<id>`, `/review`, `/admin`, and `/`.
- Chrome 156; Argo uses `browserChannel: 'chrome'`, `browser: 'chromium'`.

## Critical direction

- **No small-target `zoomTo`.** The previous Agent MCP walkthrough's small-target camera moves felt like panning. Use hard cuts, smooth programme scroll, and **CSS outlines/spotlights** that travel with content. A full-frame centre push of 1.02–1.04 is allowed; prefer no camera move.
- Keep the mouse/cursor visible and deliberate.
- Voice: **LFM3 male**, speed **0.96–1.00**, shorter sentences and clear pauses. No 1.06. The voice is the subject of this project; make it sound deliberate, not rushed.
- Do not claim a live call, live audio, phone/SIP, hosted service, production SLA, or real PII. Say "text-mode records" and "local synthetic demo" on screen. The transfer is **simulated**; say so.

## Walkthrough story (65–75s)

Use the running dashboard. Exact routes/call IDs:

- Dashboard: `/dashboard`; metrics and 34 seeded calls; two alerts.
- Clean booked call: `/calls/call_summit_text_book_03` — Booked, `bk_summit_0003`, read-back, tool timeline, latency.
- Emergency: `/calls/call_harborlight_text_emergency_01` — Emergency ticket, `em_harborlight_0001`, 911-first script, transfer `connected` (simulated).
- Weekly review: `/review`.
- Admin: `/admin`.
- Browser caller page `/` may be shown for 2s at the end, but **do not press Start call**. It is fine to omit it.

Scene plan:

1. **Hook + dashboard** — show the dashboard top, alerts and metrics. VO: "A voice agent can sound fluent and still double-book, invent a slot, or lose an emergency. This local demo shows the booking, the handoff and the audit trail."
2. **Recent calls / metrics** — scroll to the recent-calls table and the booking/containment/latency cards. VO: "Thirty-four synthetic calls. Booking rate, containment, p95 first audio and two active alerts are on the first screen."
3. **Booked call** — open `call_summit_text_book_03`; show booking ID, slot check, read-back transcript, tool timeline, latency waterfall. VO: "Open a booked call. One booking ID, the exact read-back, the tool timeline, and the measured first audio."
4. **Emergency** — open `call_harborlight_text_emergency_01`; show the emergency triage, 911-first script, ticket ID and connected transfer. VO: "The emergency path runs before the model. A 911-first script, a structured ticket, and a connected transfer. The transfer is simulated in this local demo."
5. **Weekly review** — show the ten-call sample and the review actions. VO: "The weekly review turns a sample of calls into scenario candidates, so a failure can become a test."
6. **Admin** — show the tenant editor and YAML. VO: "Both tenants run the same engine. The admin editor validates YAML before it writes."
7. **Limits / end card** — 6–7s. "One booking, one handoff, one audit trail."; `github.com/ArpanSM/forge-voice`; "Local-only · synthetic · no production SLA"; "p95 first audio 5.3 s · barge-in ~0.88 s · live audio run 5/6". VO: "Local, synthetic, no production SLA. The live audio run is five of six; the one ASR miss is shown, not hidden. Code and evaluation are in the repository."

Do not show a real phone number, address or name as real; they are synthetic. The dashboard footer says synthetic; keep the caveat on screen.

## Argo output

- `videos/voice-walkthrough.mp4`: 1920x1080, 30fps, H.264 + AAC, 65–75s, real voiceover.
- `videos/voice-walkthrough.srt` / `.vtt`; normalize timestamps with `scripts/normalize-subtitles.mjs`.
- `videos/voice-walkthrough-poster.png`: 1920x1080, readable end card, no black frame.
- `qa/`: Video Director report and contact sheets.

## Huashu launch film (30s)

- Use `npx om` from `demo-video`; read the installed skill.
- 30s, 1920x1080, 60fps, H.264 + AAC, music and effects only.
- Real screenshots: dashboard top with alerts/metrics, booked call detail, emergency detail, weekly review, admin. Capture at 1920x1080 with Playwright if needed; use the app's light blue/white palette and red/amber warning tones.
- Story: "A voice agent that can prove what it did." One booking, one emergency handoff, one audit trail. End on the measured numbers: 34 calls, 3 booked, 3 emergency tickets, 5/6 live-audio, p95 5.3s.
- End card: "One booking, one handoff, one audit trail."; `github.com/ArpanSM/forge-voice`; "Local-only · synthetic · no production SLA".
- Use `om check`, `om still`, `om render --fps 60 --workers 8 --blur 4`, `om qa`.
- Keep the Huashu signature unless it clashes.

## Deliver and report

- `videos/voice-walkthrough.mp4`, `.srt`, `.vtt`, poster
- `huashu-film/out/forge-voice-launch.mp4`, poster, `README.md`
- `qa/` for both
- `README.md` in `demo-video/` with reproduce commands
- Report paths, ffprobe facts, QA, exact narration, and caveats. Do not upload, commit, or push.

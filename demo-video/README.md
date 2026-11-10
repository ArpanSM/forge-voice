# Forge Voice — client proof film

**What this is:** a 49-second client proof film for the local-first voice booking kit, made from
the real local dashboard and the committed call record `call_summit_text_book_03`.

**Who it is for:** home-services operators (HVAC, plumbing, electrical), dental and auto-service
front desks, and agencies building voice agents for local businesses. It is sized for an Upwork
portfolio card and a proposal attachment.

**The one-line promise:** a voice booking agent that reads back, confirms, writes once, and proves
what happened — with the model talking and the policy owning the write.

## Watch

- `videos/client-proof.mp4` — 48.97 s, 1920 × 1080, 30 fps, H.264 + AAC 192 kbps, 4.05 MB.
- `videos/client-proof.srt` / `.vtt` — normalized subtitles.
- `videos/client-proof-poster.png` — 1920 × 1080 end-card poster.
- `qa/` — Video Director report, timeline and contact sheets.

## What it proves

The film follows one rule: **one failure, one fix, one number, one why-me, one CTA.**

| Beat | Time | Evidence |
|---|---|---|
| The failure | 0–5 s | The real dashboard's slot-correctness alert: 1 of 3 checked bookings did not match the requested service, address or slot. |
| Proof of concept | 5–13 s | The caller page and its AI disclosure. Synthetic two-tenant corpus; the method applies to your call flow. |
| The call | 13–21 s | `call_summit_text_book_03`: service-area check, real slot, read-back of service, time, technician, address and phone. |
| The write | 21–28 s | Booking ID `bk_summit_0003` and the tool chain `lookup_customer → get_service_area → get_availability → book_appointment`. A retry returns the same booking. |
| Why me | 28–37 s | Reproduce the booking failures, measure model vs policy, fix + a regression gate. |
| The number | 37–42 s | Zero unsafe writes: zero double bookings, zero unconfirmed writes and zero slot mismatches across a 40-scenario local eval. Live audio 5/6, all hard gates green. |
| The CTA | 42–49 s | Send two call flows and your worst failure. `github.com/ArpanSM/forge-voice`. |

The metric is `reports/release-local-text/report.md` (40 scenarios; `double_booking` 0,
`unauthorized_write` 0, `confirmation_accuracy` 17/17, `audit_completeness` 40/40). The 5/6
caveat is `reports/release-audio-local/report.md` (every hard gate passes; the one task-completion
failure is report-only). The hybrid release gate is not claimed: the final sweep is
`NOT_RUN_MISSING_GROQ_KEY`.

## How it is made

The film is built with **Argo** only — no ExplainRoo, no paid voice service.

- `demos/client-proof.demo.ts` records the real local pages with Playwright and adds the dark
  evidence frame, the evidence tags and the phone-readable lower-thirds.
- `compositions/client-proof.html` draws the three argument cards (the engagement, the proof
  number, the CTA) as a GSAP ledger timeline.
- `demos/client-proof.scenes.json` holds the narration; the voice is the local **LFM3-Audio-2B**
  male voice at 0.98 (1.00 on the end card).
- The local profile uses LFM3 for STT, LLM and TTS. No Groq key is used.

The real app is shown as captured. The call segment has no audio (the call record is text-only);
it is labelled “simulated call · real policy/tool run” and the read-back is on screen as a
lower-third. The dashboard count and the 40-scenario eval are separate datasets and are labelled
as such.

## Reproduce

The dashboard must be running at `http://127.0.0.1:8000` and LFM3 at `http://127.0.0.1:8082`.

```bash
cd /home/arpan/Forge/forge-voice
make dashboard && make dashboard-seed
lfm3 audio

cd demo-video
PATH=/tmp/opencode/bin:$PATH npx argo pipeline client-proof
```

The pipeline writes `videos/client-proof.mp4`, `.srt`, `.vtt` and `.meta.json`. The delivery
audio is normalized to −14 LUFS / −1.5 dBTP and the subtitles are normalized:

```bash
PATH=/tmp/opencode/bin:$PATH ffmpeg -i videos/client-proof.mp4 \
  -af loudnorm=I=-14:TP=-1.5:LRA=11 -c:v copy -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart videos/client-proof.norm.mp4
mv videos/client-proof.norm.mp4 videos/client-proof.mp4
node scripts/normalize-subtitles.mjs videos/client-proof.srt videos/client-proof.vtt
PATH=/tmp/opencode/bin:$PATH ffmpeg -ss 45 -i videos/client-proof.mp4 \
  -frames:v 1 videos/client-proof-poster.png
```

QA:

```bash
python3 .claude/skills/video-director/scripts/check_timeline.py qa/timeline.json
PATH=/tmp/opencode/bin:$PATH python3 .claude/skills/video-director/scripts/qa_video.py \
  videos/client-proof.mp4 --out qa/ --beats qa/timeline.json
```

## Exact narration

1. A booking that doesn't match the request is a support ticket.
2. This proof of concept uses a synthetic two-tenant corpus. The method applies to your call flow.
3. A caller reports a cooling problem. The agent checks the service area, offers a real slot, and reads back.
4. The caller says yes. One token, one write. A retry returns the same booking.
5. I reproduce your booking failures, separate model from policy, and rank the fixes with a before/after evaluation.
6. On 40 text scenarios, zero unsafe writes.
7. Send me two call flows and your worst failure. I'll tell you what's model, policy, or integration.

## Limits

- **No live call is recorded.** The call segment is the committed text record. Do not describe the
  film as a live browser-call recording.
- **Local only.** No hosted URL, SIP, or real calendar/CRM/SMS. No production SLA.
- **No Groq.** The local profile only; the hybrid release gate is not claimed.
- **Synthetic data.** The two tenants and all callers are synthetic.
- **The 5/6 is shown, not hidden.** The metric card carries it as a caveat.
- The QA report has no failing checks. The warnings are the designed holds on the real screens,
  the intended cut hits, and the card-swap transitions; they are not defects.
- Nothing here is uploaded, committed or pushed.

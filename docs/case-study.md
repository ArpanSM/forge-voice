# Case study: a voice booking kit that can prove its own limits

**One page.** A local-first LiveKit voice agent for two fictional home-services businesses,
with the scope, evaluation, deployment, monitoring and handover kit around it. The interesting
part is not that it books a drain cleaning. It is that every write, transfer and emergency
decision is deterministic, auditable and measured against a published gate.

## The problem

A home-services operator misses high-value inbound calls. A receptionist has to book, move and
cancel appointments, answer price and service-area questions, triage emergencies, hand off to a
human and capture a callback after hours. A double booking, an unconfirmed write, a missed gas
leak or a caller left on hold is a real business failure.

Most voice demos prove the first call and stop. They talk over the caller, invent a slot, lose
the caller on transfer, leak one tenant's data into another, or cannot explain what happened.
The hard parts are telephony, turn-taking, barge-in, tool writes, confirmation, handoff,
multi-tenant configuration, cost, transcripts and monitoring. A thin wrapper around a hosted
voice API does not prove those layers.

## What was built

- **Two tenants:** Harborlight Home Services (plumbing, HVAC, electrical) and Summit Heating &
  Air (HVAC), each a schema-validated YAML config. There is no tenant-specific workflow code;
  tenant-dependent extraction/labels live behind the config/interpretation seam.
- **One LiveKit Agents pipeline:** self-hosted LiveKit in Docker Compose, browser caller,
  LFM3-Audio-2B on the host GPU for STT/TTS, and either local LFM3 or Groq Qwen for the LLM.
- **Eight typed tools:** `lookup_customer`, `get_service_area`, `get_availability`,
  `book_appointment`, `reschedule_appointment`, `cancel_appointment`,
  `create_emergency_ticket`, `transfer_to_human`, all behind one result envelope.
- **A deterministic policy:** explicit `CallState`, intent, urgency, offered and confirmed
  slots, terminal outcomes, a 120 s one-use confirmation token, a server-derived idempotency
  key, an atomic no-double-booking write and an audit row.
- **Emergency and handoff:** deterministic triage before the model, 911-first scripts, a
  structured ticket, a complete handoff packet, and an honest simulated connected /
  queued-callback / no-answer status.
- **Evaluation:** 40 text + 10 audio scenarios, dev/held-out/smoke splits, a naive baseline,
  hard gates, Wilson intervals, JSON/Markdown reports, a failure gallery and sealed held-out
  labels.
- **Monitoring and handover:** one local FastAPI app with `/dashboard`, `/calls/{id}`,
  `/metrics.json`, `/review` and a validating `/admin`; one-page runbook, 5-minute training
  outline, handover checklist and a 30-day support boundary.
- **Proof assets:** 90-second captioned storyboard using real dashboard/call records (no call
  audio), 5-minute dashboard/admin/runbook walkthrough, real screenshots, README, this case
  study and a learning map. A live captioned browser-call recording is a manual follow-up, not
  part of this slice.

The runtime and model matrix is deliberately small. The fully local `make demo` is the
default; `make demo-hybrid` uses Groq for the LLM only. There is no Cloud transport, SIP,
TURN, real calendar/CRM/SMS, payment or hosted URL in this slice.

## What was measured

The full record is in [`reports/`](../reports/) and [`docs/evaluation.md`](evaluation.md).
Text, audio, hybrid and local are reported separately and never pooled.

| Run | Result | What it means |
|---|---|---|
| `make eval` (40 text + 10 critical × 3, hybrid text) | **not_run_missing_groq_key** | The #2/#26 release gate. The final sweep had no Groq key; the hybrid text gate is not claimed. |
| `make eval-local` (40 text, local) | 40 scenarios, task completion **27/40 (67.5%)**, every safety hard gate pass | Task completion and latency are report-only for the local safety fallback. Confirmation 17/17, slots 11/11, emergency 5/5, handoff 13/13, audit 40/40, 0 double bookings, 0 unconfirmed writes, 0 cross-tenant leaks. |
| `make eval-orca` (40 text + 10 critical × 3, hybrid text) | **not_run_provider_quota** — OrcaRouter free daily limit | **Optional fallback experiment, not the release gate.** OrcaRouter free (10 RPM / 50 RPD) was exhausted; no green hybrid claim. |
| `make eval-smoke` (8 text dev) | **8/8 pass** | Fast commit/PR subset; not a release claim. |
| `make eval-baseline` (40 text) | **local 0/40**; hybrid **not_run_provider_quota 0/0** | One prompt and a direct write; the comparison never gates. |
| `make eval-audio-local` (6 audio, live self-hosted LiveKit + LFM3) | **5/6**, every hard gate passes | Five scenarios pass, including emergency/handoff and all booking/read-back flows. One genuine ASR entity miss remains: LFM3 heard “88 Hyde Meridian Way” for “88 Meridian Way”. See “What went wrong”. |
| `make eval-audio` (10 audio hybrid) | **not_run_missing_groq_key** | Hybrid audio not claimed; no Groq key in the final sweep. |
| `make eval-heldout` (8 text + 2 audio sealed) | **not_run_missing_groq_key** | Sealed held-out gate not claimed; no Groq key in the final sweep. |

**Latency caveat, next to the claim.** The measured tier is one 10-turn WebRTC sample per
profile on a 4 GB laptop: p50 first audio **2.87 s**, p95 **5.3 s**, barge-in yield **~0.88 s**
(hybrid 880 ms; local 884 ms). It is not a production benchmark and not an SLA. Do not claim
sub-3 s, sub-2 s or sub-1 s. Production APIs must be re-measured before quoting a number.
The demo marginal cost is **$0** on free tiers plus the local GPU; the production estimate is
**$0.03–0.06/min**, not measured here.

## What went wrong

1. **The final hybrid sweep had no Groq key.** The committed hybrid text, audio and held-out
   reports are `not_run_missing_groq_key`; the release gate is not claimed. Earlier, Groq's free
   daily token budget had also been exhausted. We did not edit the gate or weaken the scenarios.
2. **The first OrcaRouter fallback looked broken when the harness was wrong.** A provider check
   with `max_tokens: 4` returned an empty content field because the free reasoning model spent
   those tokens on hidden reasoning. A 3-case batch capped at 780 tokens truncated the JSON.
   The harness now uses a 640-token check and 2-case batches with a 2,400-token budget. The fix
   made the provider route work, but the OrcaRouter free daily quota (50 RPD, shared) was
   exhausted during the live attempts and probes. The Orca path is an **optional fallback
   experiment, not the release gate**, and its final report is `not_run_provider_quota`. This
   is a harness fix, not a product pass; the same gates still run.
3. **The live local audio emergency handoff now passes.** The scripts repeat the ZIP/address
   turn and separate the yes from the read-back; the guard reprompts instead of inferring a
   ZIP, and the ticket, 911 script and on-call handoff/callback pass the hard gates.
4. **One genuine ASR entity miss remains.** The `audio_readback_01` booking succeeds on the
   corrected Tuesday slot, but LFM3 heard “88 Hyde Meridian Way” for “88 Meridian Way”, so
   `confirmed_entities` fails. LFM3 also remains sensitive to turn boundaries; the scripts now
   put every explicit yes on a later caller turn, and the failures are reported, not hidden.
   The local text safety gates pass because the deterministic policy owns the writes; the text
   run still uses LFM3 extraction, so its 27/40 task completion is honest.
5. **The known product gaps remain.** No proactive silence prompt, degraded ZIP recognition,
   no long-utterance turn-taking guard, one 10-turn sample per profile and no acoustic echo
   test with a human handset. The demo avoids them: clean audio, short turns, ZIP digits one at
   a time and no long silence.
6. **The local 2B model is not a hosted-quality tier.** It runs in 4 GB VRAM; the hybrid path
   needs a free Groq key. The deterministic policy, fake provider and eval gates are the
   mitigation, not a claim that the model is interchangeable.

**Honest gate status.** The demo assets are complete and the local text safety report passes
its hard gates. The #2/#26 release gate is the Groq hybrid text run; the final sweep had no
Groq key, so its report is `not_run_missing_groq_key` and the gate is not claimed. The optional
OrcaRouter fallback is also not claimed (`not_run_provider_quota`). The hybrid audio and sealed
held-out reports are `not_run_missing_groq_key`. The live local audio run is **5/6** with every
hard gate green and one genuine ASR entity miss. The full sweep did **not** pass. This is a
**demo**, not a production release.

## The offer

**I scope, build, deploy, evaluate and monitor voice agents on an open-source core, then hand
your team the runbook.**

For a home-services operator, that means: a discovery and call-flow map; one or two tenant
configs; the booking, change, emergency and handoff paths; a 40 text + 10 audio evaluation
with a failure gallery; a local-only deployment path; a dashboard, alerts and weekly review;
and a runbook plus a written support boundary. The four-week first slice is scoped at
15–20 hours per week. The demo is $0 on free tiers and a local GPU; production STT/TTS/LLM
costs are quoted separately and re-measured before any SLA.

**What this case study does not offer:** a production SLA, sub-3 s latency, carrier-grade
telephony, HIPAA/PCI compliance, 24/7 on-call, real customer data or a hosted service. Those
are separate, scoped engagements.

**Start here:** [README](../README.md) · [demo](demo-video.md) · [learning map](learning-map.md)
· [evaluation](evaluation.md) · [runbook](runbook.md) · [handover](handover.md).

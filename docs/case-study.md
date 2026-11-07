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
  Air (HVAC), each a schema-validated YAML config. No tenant-specific code.
- **One LiveKit Agents pipeline:** self-hosted LiveKit in Docker Compose, browser caller,
  LFM3-Audio-2B on the host GPU for STT/TTS, and either local LFM3 or Groq Qwen for the LLM.
- **Eight typed tools:** `lookup_customer`, `get_service_area`, `get_availability`,
  `book_appointment`, `reschedule_appointment`, `cancel_appointment`,
  `create_emergency_ticket`, `transfer_to_human`, all behind one result envelope.
- **A deterministic policy:** explicit `CallState`, intent, urgency, offered and confirmed
  slots, terminal outcomes, a 120 s one-use confirmation token, a server-derived idempotency
  key, an atomic no-double-booking write and an audit row.
- **Emergency and handoff:** deterministic triage before the model, 911-first scripts, a
  structured ticket, a complete handoff packet, and an honest connected / queued-callback /
  no-answer status.
- **Evaluation:** 40 text + 10 audio scenarios, dev/held-out/smoke splits, a naive baseline,
  hard gates, Wilson intervals, JSON/Markdown reports, a failure gallery and sealed held-out
  labels.
- **Monitoring and handover:** one local FastAPI app with `/dashboard`, `/calls/{id}`,
  `/metrics.json`, `/review` and a validating `/admin`; one-page runbook, 5-minute training
  outline, handover checklist and a 30-day support boundary.
- **Proof assets:** 90-second captioned demo, 5-minute dashboard/admin/runbook walkthrough,
  real screenshots, README, this case study and a learning map.

The runtime and model matrix is deliberately small. The fully local `make demo` is the
default; `make demo-hybrid` uses Groq for the LLM only. There is no Cloud transport, SIP,
TURN, real calendar/CRM/SMS, payment or hosted URL in this slice.

## What was measured

The full record is in [`reports/`](../reports/) and [`docs/evaluation.md`](evaluation.md).
Text, audio, hybrid and local are reported separately and never pooled.

| Run | Result | What it means |
|---|---|---|
| `make eval-local` (40 text, local) | 40 scenarios, task completion **27/40 (67.5%)**, every safety hard gate pass | Task completion and latency are report-only for the local safety fallback. Confirmation 17/17, slots 11/11, emergency 5/5, handoff 13/13, audit 40/40, 0 double bookings, 0 unconfirmed writes, 0 cross-tenant leaks. |
| `make eval-orca` (40 text + 10 critical × 3, hybrid text) | **not_run_provider_quota** — OrcaRouter free daily limit | Same 40-scenario set and the same hard gates. Groq's free daily budget was exhausted first; OrcaRouter free (10 RPM / 50 RPD) was then exhausted by the live attempts and probes. The report says so; no green hybrid claim. |
| `make eval-smoke` (8 text dev) | **8/8 pass** | Fast commit/PR subset; not a release claim. |
| `make eval-baseline` (40 text, both profiles) | **0/40 fixed-equivalent**, expected failure | One prompt and a direct write; it demonstrates why the policy and tools exist. It never gates. |
| `make eval-audio-local` (6 audio, live self-hosted LiveKit + LFM3) | **2/6**, emergency handoff gate fails | Real local-model ASR limitation: LFM3 heard ZIP `95125` as `9520 Faye`, so the handoff packet had no address and the policy queued an honest callback. See “What went wrong”. |
| `make eval-audio` (10 audio hybrid) | not claimed while the Groq free TPD is exhausted | The report says `not_run_provider_quota`; no green audio claim. |
| `make eval-heldout` (8 text + 2 audio sealed) | not claimed while the hybrid provider quota is unavailable | The sealed-set gate is not claimed without a genuine run. |

**Latency caveat, next to the claim.** The measured tier is one 10-turn WebRTC sample per
profile on a 4 GB laptop: p50 first audio **2.87 s**, p95 **5.3 s**, barge-in yield **~0.88 s**
(hybrid 880 ms; local 884 ms). It is not a production benchmark and not an SLA. Do not claim
sub-3 s, sub-2 s or sub-1 s. Production APIs must be re-measured before quoting a number.
The demo marginal cost is **$0** on free tiers plus the local GPU; the production estimate is
**$0.03–0.06/min**, not measured here.

## What went wrong

1. **Groq's free daily token budget was exhausted.** The live hybrid run failed closed with
   `not_run_provider_quota`; the demo still works fully local. We did not edit the gate or
   weaken the scenarios.
2. **The first OrcaRouter fallback looked broken when the harness was wrong.** A provider check
   with `max_tokens: 4` returned an empty content field because the free reasoning model spent
   those tokens on hidden reasoning. A 3-case batch capped at 780 tokens truncated the JSON.
   The harness now uses a 640-token check and 2-case batches with a 2,400-token budget. The fix
   made the provider route work, but the OrcaRouter free daily quota (50 RPD, shared) was
   exhausted during the live attempts and probes, so the final report is
   `not_run_provider_quota`. This is a harness fix, not a product pass; the same gates still
   run.
3. **The live local audio emergency handoff really fails.** The transcript heard
   “88 Meridian Way, San Jose, 9520 Faye” for ZIP `95125`; the address was `null`, the packet
   was incomplete, and the policy correctly said it could not reach the on-call technician and
   queued a callback. The session-replay audio path passes 6/6; the live path does not. The
   gate stays failed and is stated in the README, this case study and the walkthrough.
4. **The local audio read-back, silence and noisy scenarios are also weak.** LFM3 misheard
   ZIPs (`95125` as `9521`) and turn boundaries; those task-completion failures are reported,
   not hidden. The local text safety gates pass because the deterministic policy owns the
   writes; the text run still uses LFM3 extraction, so its 27/40 task completion is honest.
5. **The known product gaps remain.** No proactive silence prompt, degraded ZIP recognition,
   no long-utterance turn-taking guard, one 10-turn sample per profile and no acoustic echo
   test with a human handset. The demo avoids them: clean audio, short turns, ZIP digits one at
   a time and no long silence.
6. **The local 2B model is not a hosted-quality tier.** It runs in 4 GB VRAM; the hybrid path
   needs a free Groq key. The deterministic policy, fake provider and eval gates are the
   mitigation, not a claim that the model is interchangeable.

**Honest gate status.** The demo assets are complete and the local text safety report passes
its hard gates. The hybrid text gate was moved to the OrcaRouter free fallback after the Groq
free daily budget was exhausted; the fallback then hit its own 50 RPD free daily limit, so the
final hybrid text report is `not_run_provider_quota`. The hybrid audio and sealed held-out gates
are not claimed while the provider quota is unavailable. The live local audio emergency gate is
genuinely failed. This is a **demo**, not a production release.

## The offer

**I scope, build, deploy, evaluate and monitor voice agents on an open-source core, then hand
your team the runbook.**

For a home-services operator, that means: a discovery and call-flow map; one or two tenant
configs; the booking, change, emergency and handoff paths; a 40 text + 10 audio evaluation
with a failure gallery; a local or hosted deployment path; a dashboard, alerts and weekly
review; and a runbook plus a written support boundary. The four-week first slice is scoped at
15–20 hours per week. The demo is $0 on free tiers and a local GPU; production STT/TTS/LLM
costs are quoted separately and re-measured before any SLA.

**What this case study does not offer:** a production SLA, sub-3 s latency, carrier-grade
telephony, HIPAA/PCI compliance, 24/7 on-call, real customer data or a hosted service. Those
are separate, scoped engagements.

**Start here:** [README](../README.md) · [demo](demo-video.md) · [learning map](learning-map.md)
· [evaluation](evaluation.md) · [runbook](runbook.md) · [handover](handover.md).

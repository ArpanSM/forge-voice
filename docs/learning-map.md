# Learning map — from LiveKit turn-taking to an honest gate

**What this is:** a reading path that connects each hard part of the voice agent to the code,
the test that protects it and the eval gate that measures it.
**For:** engineers reviewing the repo, and anyone who wants to explain the system end to end.
**Status:** matches `v0.1.0-demo`. The full sweep did **not** pass: local text safety gates pass;
live local audio is **5/6** with every hard gate green and one genuine ASR entity miss; the
Groq hybrid text/audio and sealed held-out reports are `not_run_missing_groq_key`; the optional
Orca fallback is `not_run_provider_quota`.

Start with [CONTEXT.md](../CONTEXT.md) for the vocabulary, then read this page with the code
open. Every section follows the same shape: **idea → where it lives → what to run → what can
still go wrong.**

## 1. LiveKit turn-taking and barge-in

**Idea.** A voice agent is not a chat loop. Endpointing decides when the caller has finished,
interruptions decide when the agent must stop, and preemptive generation hides latency. The
agent must also stop speaking when the caller starts and recover the task afterwards.

**Where it lives.**

- `src/forge_voice/runtime/session.py` — the typed `SessionPlan`: profile, LLM endpoint,
  VAD, interruption thresholds, endpointing delays and max reply tokens. The plan is tested
  without opening a socket.
- `src/forge_voice/runtime/livekit_agent.py` — builds the real `AgentSession` with Silero VAD,
  `TurnHandlingOptions`, `InterruptionOptions` and the agent dispatch name.
- `src/forge_voice/runtime/audio_session.py` — the transport-independent call state; it does
  not know whether audio came from WebRTC or a text turn.
- `src/forge_voice/runtime/livekit_agent.py::BookingAgent.llm_node` — intercepts emergencies
  and the hybrid booking write turns before the model.

**What to run.** `make demo-smoke` for a scripted booking, `SMOKE_MODE=barge-in` for an
interruption, and `SMOKE_MODE=barge-in-booking` for an interruption mid-booking. The audio
eval adds `audio_bargein_01`. The spike measured 880 ms (hybrid) and 884 ms (local) from
caller interruption to the agent leaving `speaking`; 0 false interruptions in those runs.

**What can go wrong.** The 500 ms target is not met. The first 3 s are an AEC warm-up where
LiveKit disables interruptions by default. There is no long-utterance turn-taking guard, so a
single very long caller turn can split at VAD boundaries. The demo uses short turns.

## 2. Typed tools and the common envelope

**Idea.** The model may choose a tool, but it cannot invent a write. Every tool returns the
same envelope, so the model, dashboard and eval read one shape.

**Where it lives.**

- `src/forge_voice/tools/registry.py` — exactly eight tools: `lookup_customer`,
  `get_service_area`, `get_availability`, `book_appointment`, `reschedule_appointment`,
  `cancel_appointment`, `create_emergency_ticket`, `transfer_to_human`.
- `src/forge_voice/tools/envelope.py` — success `{ok, data, request_id}` and failure
  `{ok: false, error: {code, message, retryable, details?}, request_id}`. Stable error codes;
  no stack traces.
- `src/forge_voice/runtime/livekit_agent.py` — the typed function-tool wrappers the model
  sees. Tool execution itself is fast; the LLM/tool loop is the latency cost.

**What to run.** `python3.12 -m pytest tests/test_tools.py` for direct envelope and error
tests; `make eval-local` for the same tools behind every scenario.

**What can go wrong.** A tool result can be correct while the model still speaks a different
claim. The read-back is generated from the tool result, and the scorer checks the final state,
not the wording.

## 3. Confirmation, idempotency and the no-double-booking rule

**Idea.** A booking needs an explicit yes, a one-use token and an atomic write. A retry must
return the same booking, not create a second one.

**Where it lives.**

- `src/forge_voice/policy/state.py` — `CallState`, `CallIntent`, `CallOutcome`,
  `confirmation_token`, offered/confirmed slot.
- `src/forge_voice/policy/conversation.py` — intent classification, confirmation phases,
  `issue_confirmation`, `confirm`, payload binding.
- `src/forge_voice/policy/confirmation.py` — the policy-issued, single-use token (120 s,
  bound to tenant + call + intent + target + payload). The model cannot mint it.
- `src/forge_voice/policy/booking.py` — `BookingService`: slot check and write in one SQLite
  transaction, server-derived idempotency key `tenant:call:intent:target`, same key + same
  payload returns the same booking, different payload is `idempotency_conflict`.
- `src/forge_voice/adapters/sqlite.py` — the atomic adapter and slot/booking tables.

**What to run.** `make text-demo` and the eval's `text_confirm_refusal_01`,
`text_duplicate_01`, `text_timeout_01` scenarios. The hard gates are 0 double bookings, 0
unconfirmed writes and 100% confirmation accuracy.

**What can go wrong.** A model can still ask for confirmation at the wrong moment. The policy
refuses the write; the eval records the failed task. The local 2B model sometimes needs a
detail repeated; the policy still will not write without the token.

## 4. Emergency triage and honest handoff

**Idea.** Emergency classification is deterministic and runs before the model. The agent
speaks the tenant's 911-first script, creates a structured ticket and attempts a transfer. It
never claims a transfer succeeded before a human answers.

**Where it lives.**

- `src/forge_voice/policy/emergency.py` — tenant categories, severity, vulnerable-occupant
  escalation and the safety script.
- `src/forge_voice/runtime/audio_session.py::emergency_step` and
  `create_emergency_ticket` — ticket creation, one missing-detail prompt, then handoff.
- `src/forge_voice/policy/handoff.py` — `HandoffPacket.missing_fields()`; name, phone,
  address, service, summary, reason and ticket/booking are required.
- `src/forge_voice/tools/registry.py::_transfer_to_human` — live vs callback mode, target
  selection, no false connected status.
- `src/forge_voice/transfer.py` — the synthetic transfer simulator (connected, no answer,
  queued callback).

**What to run.** `SMOKE_MODE=emergency SMOKE_TENANT=summit make demo-smoke`, the
`text_emergency_*` and `audio_emergency_01` scenarios, and the dashboard's emergency triage
card. The eval hard gates are 100% emergency triage, 100% handoff correctness, 0 unsafe
promises and 0 unauthorized writes.

**What can go wrong.** The live local audio run is **5/6** and every hard gate passes. One
genuine ASR entity miss remains: `audio_readback_01` books the corrected Tuesday slot, but LFM3
inserts a word in the street name (“88 Hyde Meridian Way” previously, “88 Tide Meridian Way”
in the latest run) instead of “88 Meridian Way”, so `confirmed_entities` fails. The clean text
path and session replay pass; the remaining failure is real local-model ASR, not a fake pass.

## 5. Multi-tenancy without tenant-specific workflow code

**Idea.** One engine, two configs. Tenant identity comes from a signed claim, and an unknown
tenant fails closed. No tenant-specific **workflow** code path exists; tenant-dependent
extraction/labels live behind the config/interpretation seam (`tenants/*.yaml`,
`runtime/interpreter.py`, `eval/provider_text.py`).

**Where it lives.**

- `tenants/harborlight.yaml` and `tenants/summit.yaml` — identity, persona, hours, services,
  prices, ZIP service area, transfer targets, adapters, KB and emergency rules.
- `src/forge_voice/tenants/models.py` — strict Pydantic schema; unknown fields are rejected.
- `src/forge_voice/tenants/loader.py` — load and validate both configs.
- `src/forge_voice/web/claims.py` — 120 s HMAC tenant claim bound to tenant, call, room and
  expiry. `src/forge_voice/runtime/claim_validation.py` verifies it in the agent; a missing,
  tampered or wrong-room claim shuts the job down.
- `src/forge_voice/tools/registry.py` and `src/forge_voice/adapters/sqlite.py` — every read
  and write is tenant-scoped.

**What to run.** `make corpus-check`, the tenant loader tests, `make demo` with either tenant
on the page, and `make eval-local` (both tenants appear). The hard gate is 0 cross-tenant
leaks and 0 unauthorized writes.

**What can go wrong.** The browser claim is participant-mutable metadata; the room binding is
what prevents reusing another tenant's otherwise valid claim. The second tenant is synthetic
proof of the path, not a production onboarding.

## 6. Evaluation: scenarios, baseline and hard gates

**Idea.** Quality is measured, not asserted. The manifest is the source of truth; the agent
runner never sees expected labels. The baseline is deliberately naive and never gates.

**Where it lives.**

- `scenarios/manifest.yaml` — 40 text + 10 audio scenarios, dev/held-out/smoke splits,
  critical repeats, expected tools/state and hard-gate labels.
- `src/forge_voice/eval/loader.py` — validates the manifest, separates the scorer-only
  held-out view, writes the sealed manifest hash.
- `src/forge_voice/eval/fixed.py` — the full policy/tool pipeline for text and audio.
- `src/forge_voice/eval/baseline.py` — one prompt, direct write, no tools/policy/confirmation.
- `src/forge_voice/eval/scoring.py` — per-scenario checks, hard gates, Wilson intervals,
  task completion and the failure gallery data.
- `src/forge_voice/eval/report.py` — generated Markdown from JSON; the JSON is the source.
- `src/forge_voice/eval/provider_check.py` and `provider_text.py` — live provider check and
  provider-backed text extraction for the release profile.

**What to run.** `make eval` is the Groq hybrid text release gate. `make eval-smoke` runs on
every change, `make eval-local` is the safety fallback, `make eval-audio-local` is the live local
audio report, and `make eval-heldout` is the sealed held-out check. `make eval-orca` is an
**optional fallback experiment, not the release gate**. `make eval-baseline` is the comparison.
The final sweep's hybrid reports are `not_run_missing_groq_key`; do not call them a pass.

**What can go wrong.** Free-tier quotas are real. Groq's TPD can be exhausted; the OrcaRouter
free fallback has 10 RPM/50 RPD and reasoning models need a larger token budget before JSON.
The harness reports `not_run_provider_quota` or `not_run_text_provider`, not a green gate. A
failed gate stays failed; the failure gallery is not hidden.

## 7. Monitoring and the weekly review

**Idea.** The call event stream is the single source for the dashboard and the eval. The
operator sees outcome, transcript, tool timeline, latency and QA flags; the weekly review
turns a bad call into a draft scenario.

**Where it lives.**

- `src/forge_voice/events/models.py` and `store.py` — `CallRecord`, `ToolEvent`, JSONL/SQLite
  store.
- `src/forge_voice/monitoring/metrics.py` — containment, transfer, booking, slot error,
  p50/p95, tool error, cost and emergency triage.
- `src/forge_voice/monitoring/alerts.py` — thresholds, alert log and optional webhook.
- `src/forge_voice/monitoring/service.py` and `routes.py` — `/dashboard`, `/calls/{id}`,
  `/metrics.json`, `/review`.
- `src/forge_voice/web/app.py` — one FastAPI app for browser, token, dashboard, review and
  admin.
- `docs/monitoring.md` — definitions, thresholds, retention and static export.

**What to run.** `make dashboard-seed`, `make dashboard`, then open `/dashboard`,
`/calls/{id}` and `/review`. `make dashboard-export` writes the handover HTML sample.

**What can go wrong.** The dashboard is evidence, not a second definition. A seeded demo set
deliberately includes failures; an alert is not a release claim. The local profile p95 budget
is 6.0 s, the hybrid budget 2.5 s, and the measured demo p95 is still 5.3 s.

## 8. Deployment and handover

**Idea.** The client's staff can run, reset, roll back and edit the agent without code.

**Where it lives.**

- `compose.yaml` — LiveKit, agent and web; LFM3 stays on the host GPU.
- `scripts/compose_demo.sh`, `scripts/compose_ops.sh`, `scripts/healthcheck.sh` — start,
  health, reset, logs and rollback.
- `src/forge_voice/web/admin.py` — validating YAML editor; invalid edits are rejected.
- `docs/runbook.md` — one page; `docs/training.md` — 5-minute outline;
  `docs/handover.md` — checklist and 30-day support boundary.
- `docs/proof/` — captioned storyboard, walkthrough, screenshots and the real-call recording
  procedure (`RECORDING.md`). The current videos have no call audio.

**What to run.** `make demo`, `make health`, `make reset`, `make logs`, `make rollback` and
the admin save/invalid-save path. `make test` and `make lint` keep the delivery honest.

**What can go wrong.** This is local-only: no Cloud transport, hosted URL, SIP, TURN, real
calendar/CRM/SMS, payments, HIPAA/PCI, 24/7 on-call or multilingual booking. The demo is not
production-ready. The recorded proof is public; a live local demo is by appointment.

## Exercises

1. Add a third tenant YAML and a booking scenario; run `make eval-smoke` and explain why the
   hard gates still hold.
2. Make `book_appointment` return `slot_unavailable` after the read-back; trace the policy
   branch and show there is no double booking.
3. Interrupt the agent during the read-back; compare `audio_bargein_01` with the text
   `text_interrupt_01` and explain which layer differs.
4. Break the held-out seal by adding an expected label to the agent view; watch the loader
   refuse the run.
5. Add a dashboard alert for a new metric; explain why an alert is not a release gate.

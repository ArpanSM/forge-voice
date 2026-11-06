# CONTEXT

## What this is

`forge-voice` is a public, synthetic proof of a local-first voice booking agent for two
fictional home-services tenants:

- **Harborlight Home Services**: plumbing, HVAC and electrical.
- **Summit Heating & Air**: HVAC.

It is a delivery kit, not a single demo. The first slice ships scope, build, evaluation,
deployment and handover assets around one booking workflow and eight typed tools.

## First-slice boundary

- Browser caller to a self-hosted LiveKit server; LFM3-Audio-2B on the host GPU.
- Fully local by default; `make demo-hybrid` may use Groq for the LLM only.
- Synthetic SQLite calendar/CRM, file outbox SMS/email and local events.
- Two tenant configs, eight tools, seven intents, confirmation + idempotency, emergency
  triage and human handoff.
- No SIP, Cloud transport, hosted URL, real calendar/CRM/SMS, payments, HIPAA/PCI claim,
  multilingual booking or production SLA.

## Vocabulary

| Term | Meaning |
|---|---|
| Tenant | One configured home-services business, resolved from a dialled number or signed browser claim. |
| Intent | `book`, `reschedule`, `cancel`, `status`, `emergency`, `pricing_faq`, `human`. |
| Slot | An offered appointment window; an offer is not a hold. |
| Confirmation token | Policy-issued, single-use, 120 s token bound to tenant, call, intent, target and payload. |
| Idempotency key | Server-derived `tenant:call:intent:target`; a replay returns the same write. |
| Envelope | Common tool result: `{ok, data|error, request_id}`. |
| Corpus | Deterministic tenants, seeds, scenario manifest, caller scripts and hashes. |
| Held-out | Sealed scenarios used once at release, never for prompt tuning. |
| Smoke | Fast commit/PR subset drawn from dev scenarios only. |
| FakeProvider | Deterministic offline provider used by unit tests and fixtures. |

## Decisions

- Workflow, tools and tenant schema: roadmap #5, `research/voice-booking-workflow-2026-11.md`.
- Evaluation set and gates: roadmap #26, `research/voice-evaluation-2026-11.md`.
- Latency and cost: roadmap #23, `research/voice-latency-cost-2026-11.md`.
- Deployment, monitoring and handover: roadmap #27, `research/voice-deployment-monitoring-2026-11.md`.
- Spec: `ArpanSM/forge-voice` #2.
- Local ADRs start at [docs/adr/](docs/adr/).

## Rule of the architecture

The model talks and extracts; deterministic code owns validation, confirmation, writes,
emergency classification and handoff. The same call path serves the demo, dashboard and
evaluation.

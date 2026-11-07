# 5-minute training outline

**Audience:** client staff who will run the local demo and edit their tenant config.
**Format:** one 5-minute screen recording (Loom or OBS) plus this outline. No live
training is included in the first slice. Repeat the honest limits; do not promise a
production SLA or sub-3 s latency.

| Time | Section | Show | Say |
|---|---|---|---|
| 0:00–1:00 | What this is | Browser page at `http://localhost:8000` | The caller talks to an AI receptionist for Harborlight or Summit. It books, reschedules, cancels, answers pricing/service-area questions, triages emergencies and hands off to a human. It is local-only and synthetic. |
| 1:00–2:00 | A booking call | Press **Start call**, book a drain cleaning | Short turns, ZIP digits one at a time, pick a slot, hear the read-back, say “yes” once. One booking and one confirmation; the agent never invents a slot. |
| 2:00–3:00 | Dashboard | `/dashboard` and one `/calls/{id}` | Cards for containment, transfer, booking, slot errors, p95 latency, tool errors and emergency triage; the call page shows transcript, tool timeline, latency and QA flags. Alerts are local; a webhook is optional and off by default. |
| 3:00–4:00 | Admin config | `/admin` | Edit identity, persona/voice, hours, services/prices, service area, transfer targets, calendar/CRM/SMS adapter endpoints, KB and emergency rules. Advanced fields stay in YAML. Invalid YAML is rejected and the live config is unchanged. Never edit tenant ids, code or a workflow graph here. |
| 4:00–4:45 | Human transfer and emergency | Say “I need a person”; then “I smell gas” | A human handoff carries a packet and only claims success after an answer; otherwise it queues a callback. Emergencies use the 911-first script, a ticket and the on-call handoff. |
| 4:45–5:00 | Limits and support | Runbook | 30-day synthetic retention; `make reset` reseeds; `make down/logs/rollback`. No Cloud/SIP/paid path, no production SLA. The 30-day window covers bug fixes, deployment help and one config change; new tenants, services or integrations are change requests. |

## Before recording

1. `lfm3 audio`; wait for `/health`.
2. `make demo` (Compose when available) or `make demo-local`.
3. `make health` is green; `make dashboard-seed` is not needed because `make demo` seeds.
4. Use synthetic names only; never show a real number, key or `.env.local`.
5. Record one clean booking and one emergency/handoff path; keep the video at five minutes.

## After handover

Point staff at [runbook.md](runbook.md) and [handover.md](handover.md). The weekly review
loop is `/review` plus `make eval-smoke`; it turns a bad call into a draft scenario, not a
live prompt edit.

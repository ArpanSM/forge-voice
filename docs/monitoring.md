# Monitoring, alerts and weekly review

Local, read-only monitoring for the synthetic Harborlight and Summit calls. It is one
FastAPI + HTMX app on `127.0.0.1:8000`; there is no public bind and no hosted service.

## Start

```bash
make dashboard        # seed if needed, then serve http://127.0.0.1:8000/dashboard
make dashboard-seed   # only write the synthetic 30-day call set
make dashboard-export # write docs/samples/dashboard-sample.html for handover
```

`make demo` starts the same web app, so the dashboard is already available at
`/dashboard`; no second stack is needed. The browser page stays at `/`, the dashboard reads
`data/monitoring/calls.jsonl`, and current #5 call traces under `data/calls/*.jsonl` are
imported read-only into that cache at startup and on the explicit refresh action.
`FORGE_VOICE_DATA_DIR` overrides the data directory.

## Routes

| Route | Purpose |
|---|---|
| `/dashboard` | Aggregate cards, alert banner, call table and tenant/date/outcome filters. |
| `/calls/{call_id}` | Caller phone, transcript excerpt, tool timeline, latency waterfall, outcome, booking/ticket ID, slot audit, emergency triage, cost, QA flags and recording consent state. |
| `/metrics.json` | Machine-readable aggregate export with definitions, filters, per-tenant metrics and alerts. |
| `/review` | Weekly 10-call sample, mark-reviewed and create-scenario-candidate actions. |
| `POST /alerts/refresh` | Explicit alert evaluation; only new alerts are written/sent. |
| `/admin` | Validating tenant YAML editor; local-only, no workflow graph or code changes. |
| `/health` | Existing local liveness endpoint. |

The first dashboard start runs the real #4 text call runner once for each dev scenario, then
attaches deterministic synthetic latency stages. Bookings, tickets, confirmations and
emergency/handoff behavior therefore come from the same policy and tools as the demo and eval;
the dashboard does not re-implement them.

## Metric definitions

These follow the #26 evaluation definitions. Every binary metric reports numerator,
denominator, n and percent.

| Metric | Definition |
|---|---|
| Containment | Calls resolved without a live transfer (`booked`, `rescheduled`, `cancelled`, `info_only`, or a satisfactory `emergency_ticket`) / total calls. Failed, abandoned and callback calls are not contained. |
| Transfer rate | Calls with a connected human transfer / total calls. |
| Booking rate | Calls ending `booked` or `rescheduled` / total calls. |
| Slot error rate | Checked committed bookings with a wrong service, address ZIP or slot / checked committed bookings. Unverified live bookings are excluded from the denominator. |
| p50/p95 latency | Caller-perceived first audio per turn (STT/endpointing + LLM TTFT + tool + TTS TTFB) over measured turns. |
| Tool error rate | Tool calls with an error envelope / total tool calls. |
| Cost per call | Total synthetic cost / total calls; the local demo is **$0**. |
| Emergency triage rate | Emergency calls with the correct category, a recorded 911/life-safety script, a structured ticket and a `connected` or `queued_callback` handoff / emergency calls. `no_answer` or a failed transfer is not OK. |
| Booking failure rate | Calls with a failed write tool / calls that attempted a write. |
| QA flag rate | QA flags per 100 calls. |

Latency is report-only. Text-mode seeded calls carry synthetic stage timings for the
dashboard; a live trace without measured audio timing is excluded from p50/p95 rather than
guessed. The local profile budget is 6.0 s p95 and the hybrid budget is 2.5 s p95, matching
the #23/#27 records. The measured 10-turn demo p95 remains 5.3 s; do not quote any dashboard
number as a production SLA.

## Alerts

| Alert | Threshold | Severity |
|---|---|---|
| p95 over active profile budget | hybrid > 2,500 ms; local > 6,000 ms | warning |
| Slot correctness failure | any checked booking with a wrong service, address ZIP or slot | critical |
| Tool error rate | > 2% of tool calls | critical |
| Booking failure rate | > 1% of write calls | critical |
| Emergency transfer failure | any emergency call without the correct category, 911/life-safety script, ticket and connected/queued handoff | critical |
| Cross-tenant/auth anomaly | any cross-tenant, auth, ownership or unauthorized-write QA flag | critical |

Alert evaluation runs at startup and on the explicit `POST /alerts/refresh` form/route. A
`GET /dashboard` is read-only for alerts: it never writes `alerts.jsonl` and never sends a
webhook. The startup/evaluation job appends only new alerts to
`data/monitoring/alerts.jsonl` (one JSON object per line, deduplicated by daily alert id).
Alert payloads contain aggregate counts, messages and call IDs only; they never contain
transcripts, phone numbers or secrets.

The webhook is optional and off by default. Set
`FORGE_VOICE_ALERT_WEBHOOK=https://discord.com/api/webhooks/...` for Discord `content`, or
`https://api.telegram.org/bot.../sendMessage` with `FORGE_VOICE_TELEGRAM_CHAT_ID` for
Telegram. Only new alerts are sent, once, with a one-second timeout. The URL must be HTTPS on
Discord or Telegram; invalid URLs and credentials are ignored. Do not put the URL in source or
logs.

## Weekly review

Open `/review` for the latest ten calls. For each call:

1. **Mark reviewed** — records the call in `data/monitoring/review.json`.
2. **Create scenario candidate** — writes a draft YAML under
   `data/monitoring/scenario_candidates/<call_id>.yaml`. The draft carries the caller turns
   and a **corrected target** outcome/pass condition for the call's intent, plus the observed
   outcome and a review TODO. A failed call is never encoded as the expected behaviour; a
   reviewer must confirm the target before adding it to the locked manifest. Call IDs are
   validated before any path is built, and review/candidate writes are atomic.
3. Run the smoke suite:

```bash
make eval-smoke
# or mark + draft + run in one step:
make review-smoke CALL_ID=call_harborlight_text_book_01
python -m forge_voice.monitoring.review --call-id CALL_ID --run-smoke
```

The web page does not launch a subprocess from a request; the script and Make target own that
step. The monthly review remains `make eval` + `make eval-heldout` per the #26 release gate.

## Static handover export

`make dashboard-export` writes one self-contained `docs/samples/dashboard-sample.html` with
the seeded cards, table and one sample call detail. It exports only records marked
`synthetic`; live trace transcripts, tool arguments, recordings and credentials are excluded.
It has no HTMX, CDN or scripts, so it can be attached to a handover without a running service.

## Admin editor

`/admin` edits `tenants/<slug>.yaml` with the same Pydantic schema the agent loads. A valid
edit is written atomically and reloads the tenant registry; invalid YAML, an unknown field or
a changed `tenant_id` is rejected without writing or reloading. Identity, hours, services and
prices, service area, transfer targets, adapter endpoints, knowledge base and emergency rules
are all editable; advanced fields stay in YAML. New tenants, services and integrations are
change requests, not admin actions.

## Retention and privacy

- Synthetic data only; no real customer records, phone numbers or recordings.
- Dashboard calls older than **30 days** are excluded from every read and pruned when the
  dashboard starts. Expired traces are skipped before import so they cannot reappear on
  every sync.
- The same startup runs `forge_voice.monitoring.retention`, which deletes raw
  `data/calls/*.jsonl` traces and `recordings/` files older than **30 days**. `make retention`
  runs that job explicitly; `make reset` deletes synthetic traces and recordings.
- `recording_opt_out` calls from traces or the seed show a text-only notice; the dashboard
  never renders an audio player or claims a recording exists.
- **Read-only** for call data: the only writes are the dashboard seed/trace cache, the alert
  log, and the weekly review/candidate files. Review, candidate and export writes are atomic
  (temp file + `os.replace`).
- Loopback only (`127.0.0.1`, `localhost`, `::1`); the factory, CLI and HTTP middleware reject
  non-loopback hosts. State-changing POSTs require a local Host and reject cross-site Origin,
  and `GET` requests do not write alerts or call webhooks.

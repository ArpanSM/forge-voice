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
`data/monitoring/calls.jsonl`, and the #5 call traces under `data/calls/*.jsonl` are imported
read-only when the service starts. `FORGE_VOICE_DATA_DIR` overrides the data directory.

## Routes

| Route | Purpose |
|---|---|
| `/dashboard` | Aggregate cards, alert banner, call table and tenant/date/outcome filters. |
| `/calls/{call_id}` | Transcript excerpt, tool timeline, latency waterfall, outcome, booking/ticket ID, cost, QA flags and recording consent state. |
| `/metrics.json` | Machine-readable aggregate export with definitions, filters, per-tenant metrics and alerts. |
| `/review` | Weekly 10-call sample, mark-reviewed and create-scenario-candidate actions. |
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
| Containment | Calls without a live human transfer / total calls. |
| Transfer rate | Calls with a connected human transfer / total calls. |
| Booking rate | Calls ending `booked` or `rescheduled` / total calls. |
| Slot error rate | Committed bookings with a wrong service, address or slot / committed bookings. |
| p50/p95 latency | Caller-perceived first audio per turn (STT/endpointing + LLM TTFT + tool + TTS TTFB) over measured turns. |
| Tool error rate | Tool calls with an error envelope / total tool calls. |
| Cost per call | Total synthetic cost / total calls; the local demo is **$0**. |
| Emergency triage rate | Emergency calls with a ticket and completed 911/on-call handoff / emergency calls. |
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
| Tool error rate | > 2% of tool calls | critical |
| Booking failure rate | > 1% of write calls | critical |
| Emergency transfer failure | any emergency call without a recordable ticket + 911/on-call handoff | critical |
| Cross-tenant/auth anomaly | any cross-tenant, auth, ownership or unauthorized-write QA flag | critical |

`/dashboard` evaluates the unfiltered active profile and appends new alerts to
`data/monitoring/alerts.jsonl` (one JSON object per line, deduplicated by daily alert id).
The banner is the live view. Alert payloads contain aggregate counts, messages and call IDs
only; they never contain transcripts, phone numbers or secrets.

The webhook is optional and off by default. Set
`FORGE_VOICE_ALERT_WEBHOOK=https://discord.com/api/webhooks/...` (a Discord-compatible
`content` payload) to post summaries to a free channel. The request is best-effort, has a
three-second timeout and does not block the dashboard. Do not put the URL in source or logs.

## Weekly review

Open `/review` for the latest ten calls. For each call:

1. **Mark reviewed** — records the call in `data/monitoring/review.json`.
2. **Create scenario candidate** — writes a draft YAML under
   `data/monitoring/scenario_candidates/<call_id>.yaml` with the caller turns, tool names and
   observed outcome. Candidates are drafts; review them before adding one to the locked
   manifest.
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
the seeded cards, table and one sample call detail. It has no HTMX, CDN, scripts, tokens or
secrets, so it can be attached to a handover without a running service.

## Retention and privacy

- Synthetic data only; no real customer records, phone numbers or recordings.
- Calls older than **30 days** are excluded from every read and pruned when the dashboard
  starts.
- `recording_opt_out` calls show a text-only notice; the dashboard never renders an audio
  player or claims a recording exists.
- **Read-only** for call data: the only writes are the dashboard seed, the alert log and the
  weekly review/candidate files.
- Loopback only (`127.0.0.1`, `localhost`, `::1`); the CLI refuses any other bind address.

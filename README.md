# Forge Voice

**Status:** scaffold and deterministic corpus (#3), booking policy/tools/text runner (#4), the
local LiveKit transport, browser demo and LFM3 audio path (#5), and the evaluation harness,
baseline, hard gates and generated report (#6) complete. Dashboard and deploy tickets follow.

A public, local-first voice booking agent delivery kit for two fictional home-services
tenants: **Harborlight Home Services** (plumbing, HVAC, electrical) and **Summit Heating &
Air** (HVAC). The caller talks to a browser demo; deterministic code owns validation,
confirmation, writes, emergency classification and handoff.

## What runs

```text
Browser (http://localhost:8000)
  └── self-hosted livekit-server (ws://localhost:7880, no Cloud/TURN/SIP)
        └── LiveKit Agents worker
              ├── LFM3-Audio-2B STT/TTS on the host GPU (127.0.0.1:8082)
              ├── LLM: LFM3 local (make demo) or Groq qwen/qwen3.8-27b (make demo-hybrid)
              └── #4 ConversationPolicy + eight typed tools + idempotent BookingService
```

The token endpoint mints a 120 s LiveKit token containing a **server-signed tenant claim**. The
agent verifies that claim and never trusts a room name or browser query parameter. An unknown
tenant fails closed.

## Quickstart (fully local)

Requires Linux, Python 3.12, a livekit-server binary downloaded by `make bootstrap`, and
LFM3-Audio-2B on the host GPU.

```bash
make install        # Python deps, dev tools and demo extras
make bootstrap      # pinned, checksum-verified livekit-server in .tools/
lfm3 audio          # separate terminal: LFM3 on 127.0.0.1:8082
make demo           # LiveKit + browser/token page + agent; Ctrl-C stops all three
```

Open <http://localhost:8000>, choose a business and press **Start call**.

`make demo` is fully local: no Cloud transport, paid model, SIP or external call. The first run
creates a gitignored `.env.local` with a random local LiveKit dev secret; the demo key/secret
never enters the repo.

### Hybrid profile

```bash
GROQ_API_KEY=... make demo-hybrid
```

Same local transport, audio and tools; the only external call is Groq `qwen/qwen3.8-27b` for
the LLM. Without a key the command fails closed and `make demo` still works fully local.

## Demo paths

| Path | What it proves |
|---|---|
| Book | Greeting/disclosure, collect service/name/address/ZIP/phone, real availability, read-back, explicit yes, exactly one committed booking, queued confirmation. |
| Emergency | Deterministic triage (no model guess), 911-first safety script, structured ticket, on-call handoff or queued callback. |
| Human handoff | Complete packet or callback; never claims a transfer before a human answers. |
| Barge-in | Caller speech stops the agent and a new response follows; `min_interruption_words=0` and a 0.3 s VAD threshold. |
| Unknown tenant | `/token` fails closed; a tampered claim is rejected by the agent. |

## Commands

```bash
make test           # offline unit tests, no network
make lint           # ruff check + format check
make corpus         # deterministic tenants, seeds, scenarios, audio copies and hashes
make corpus-check   # fail if committed fixtures drift
make audio-fixtures # regenerate the ten WAVs with LFM3 TTS (fixed seed, temperature 0)
make audio-check    # verify committed WAVs and hashes offline
make text-demo      # text-mode book/reschedule/emergency/handoff calls
make demo-smoke     # start the stack and run a scripted WebRTC booking
make eval           # 40 text hybrid release gate + 10 critical repeats (needs GROQ_API_KEY)
make eval-local     # 40 text local safety-fallback report
make eval-audio     # 10 audio hybrid on the self-hosted LiveKit server
make eval-audio-local  # 6 audio local on the self-hosted LiveKit server
make eval-heldout   # sealed 8 text + 2 audio held-out release check
make eval-smoke     # 8 text dev subset, hard gates, under two minutes
make eval-baseline  # naive baseline, 40 text on both profiles; never gates
make dashboard      # local monitoring dashboard on http://127.0.0.1:8000/dashboard
make dashboard-seed # seed the synthetic 30-day dashboard call set
make dashboard-export  # write the handover static HTML dashboard sample
```

## Evaluation

The harness is the implementation of the #26 decision. `scenarios/manifest.yaml` is the
source of truth for 40 text + 10 audio scenarios; the loader enforces the dev/held-out/smoke
splits, the ten critical repeats and the hard-gate labels.

| Command | Runs | Gate |
|---|---|---|
| `make eval` | 40 text hybrid + 10 critical × 3 repeats | Release: hard gates + task completion ≥90% |
| `make eval-local` | 40 text fully local | Safety hard gates; task/latency report-only |
| `make eval-audio` | 10 audio hybrid, self-hosted LiveKit | Emergency transfer + barge-in |
| `make eval-audio-local` | 6 audio local, self-hosted LiveKit | Emergency transfer + barge-in |
| `make eval-heldout` | sealed 8 text + 2 audio | Hard gates |
| `make eval-smoke` | 8 text dev | Hard gates, under 2 minutes |
| `make eval-baseline` | 40 text on both profiles | Never gates |

`make eval` fails closed without `GROQ_API_KEY`; the local run is the required safety
fallback. Release text uses a provider-backed interpreter (Groq for hybrid, LFM3 for local);
the deterministic policy still owns intent, confirmation, writes, emergency triage and
handoff. Smoke uses the deterministic interpreter. Audio runs on the self-hosted LiveKit
server with LFM3 STT/TTS. The baseline is a one-prompt direct-write model path; it is expected
to fail and is never part of a release decision. The baseline report includes a fixed
comparison with n/denominator for every metric.

Each run writes `reports/<run_id>/report.json` (compact source of truth), `report.md`
(generated), local-only transcripts and the sealed held-out manifest. Full transcripts are
gitignored and never committed. The report includes
per-scenario rows, the gate table, failure gallery, held-out and audio sections, repeat
stability, baseline vs fixed, cost assumptions and the latency caveat. Audio hard gates are
gated exactly like text hard gates. See [docs/evaluation.md](docs/evaluation.md) for the
metric, isolation and rate-limit contract.

`make demo-smoke` variants:

```bash
SMOKE_MODE=emergency SMOKE_TENANT=summit make demo-smoke
SMOKE_MODE=barge-in make demo-smoke
SMOKE_MODE=barge-in-booking make demo-smoke   # interrupt mid-booking, then commit
```

The hybrid equivalent is `GROQ_API_KEY=... make demo-hybrid-smoke`. It uses the same
scripted booking call and surfaces a clear `hybrid free-tier rate limit; retry in Ns`
message if Groq's 7,000 ITPM window is exhausted.

An optional Playwright/Chrome fake-microphone check of the real page is documented in
`docs/local-voice-demo.md`. The scripted WebRTC caller remains the repeatable automated
proof; the human browser check is manual.

## Monitoring and handover

`make dashboard` serves the local read-only FastAPI + HTMX dashboard at
<http://127.0.0.1:8000/dashboard>; `make demo` exposes the same page inside the browser app.
It shows aggregate cards, an alert banner, tenant/date/outcome filters and a call table.
`/calls/{call_id}` adds the transcript excerpt, tool timeline and latency waterfall.
`/metrics.json` is the machine-readable export, and `/review` is the weekly ten-call loop that
marks a call, drafts a scenario candidate and points at `make eval-smoke`. The first start
seeds a synthetic 30-day set by running the real #4 call runner, so the cards and table render
without a live call. Alerts use the #26/#27 thresholds and append to
`data/monitoring/alerts.jsonl`; an optional Discord-compatible webhook is configured only by
`FORGE_VOICE_ALERT_WEBHOOK`. See [docs/monitoring.md](docs/monitoring.md) for the metric
definitions, thresholds, retention and static export. No real data, public bind or recording
is used.

## Layout

```text
src/forge_voice/
  adapters/    # SQLite calendar/CRM/bookings/tickets/callbacks/events + file outbox
  audio/       # audio scripts, deterministic WAV fixtures and hash verification
  corpus/      # deterministic generator and CLI
  events/      # dashboard CallRecord, JSONL store and #5 trace ingestion
  monitoring/  # metrics, alerts, review loop, HTML pages and static export
  policy/      # pure ConversationPolicy, BookingService, tokens, emergency and handoff
  providers/   # ChatProvider seam, FakeProvider, LFM3/Groq adapters
  runtime/     # LiveKit worker, audio session, LFM3 TTS, text CallRunner, session plan
  scenarios/   # manifest schema and validating loader
  tenants/     # tenant schema and fail-closed loader
  tools/       # eight typed tools and common result envelope
  web/         # FastAPI browser page, signed tenant token, vendored LiveKit client
tenants/       # Harborlight and Summit YAML, synthetic only
scenarios/     # 40 text + 10 audio scenarios, caller scripts and WAV fixtures
fixtures/      # generated corpus (tenants, seeds, scenarios, audio, hashes)
docs/          # ADRs, local demo guide and agent workflow
tests/         # offline pytest suite
```

## First-slice scope

- Two tenant configs, eight typed tools, seven intents.
- Confirmation token, idempotency, no double booking, no blind retries.
- Deterministic emergency triage, 911-first script, ticket and handoff.
- Browser demo over a **self-hosted** LiveKit server; local LFM3 STT/TTS.
- 40 text + 10 audio scenarios with dev, held-out and smoke splits.
- Audio fixtures generated once with LFM3 and committed with SHA-256 hashes.

No SIP, Cloud transport, hosted URL, real calendar/CRM/SMS, payments, HIPAA/PCI claim or
production SLA. See [docs/local-voice-demo.md](docs/local-voice-demo.md) for setup and
troubleshooting.

## Known limits

These are documented, not hidden, and are not fixed by #5:

- No proactive silence prompt; the agent recovers when the caller speaks again.
- Degraded ZIP recognition is fragile on noisy or bad lines; the demo uses clean audio and
  speaks ZIP digits one at a time.
- No long-utterance turn-taking guard; a very long caller turn can split at VAD boundaries.
- Local LFM3 is a 2B model on a 4 GB GPU. The spike measured p95 first audio 5.3 s and
  barge-in ~0.88 s; latency is report-only, not a sub-3 s claim.
- The automated smoke uses synthetic LFM3 caller audio, not a human handset or acoustic echo
  path. The optional browser check uses Chrome's fake microphone and is not a human test.
  The hybrid profile requires a free Groq key.
- `host.docker.internal:8082` is accepted by the session plan for the #8 container
  deployment; the #5 `make demo` host process path uses `127.0.0.1` and does not exercise it.

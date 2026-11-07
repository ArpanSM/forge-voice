# Forge Voice

**Status:** scaffold and deterministic corpus (#3), booking policy/tools/text runner (#4), the
local LiveKit transport, browser demo and LFM3 audio path (#5), evaluation harness and report
(#6), monitoring dashboard and weekly review (#7), and the local Compose deployment, validating
admin editor, runbook and handover kit (#8) are complete.

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

Requires Linux, LFM3-Audio-2B on the host GPU, and either Docker Compose v2.20+ (preferred)
or Python 3.12 for the host-binary fallback. Both paths also use `curl` and Python 3.12+
for the preflight/health helpers (`python3` is accepted when it is 3.12+). The Compose path
uses Linux host networking so browser and agent media share the host loopback; it is not a
Docker Desktop path. Set `FORGE_VOICE_UID`/`FORGE_VOICE_GID` from `id -u`/`id -g` if they
are not 1000 so `./data`, `./recordings` and `./tenants` stay user-owned.

```bash
make install        # Python deps, dev tools and demo extras (host fallback/tests)
cp .env.example .env.local   # gitignored; fill the local LiveKit key/secret
lfm3 audio          # separate terminal: LFM3 on 127.0.0.1:8082
make demo           # prints MODE: Compose or host-binary, then starts that path
```

Open <http://localhost:8000>, choose a business and press **Start call**. The same app serves
`/dashboard`, `/review` and `/admin`; all binds are loopback.

The deployment path is explicit when you need it:

```bash
make demo-local     # host-binary livekit-server in .tools/; no Docker
make demo-compose   # one Compose stack: self-hosted LiveKit + agent + web; LFM3 stays on the host
make demo-hybrid    # Compose/host with LFM3 audio + Groq qwen/qwen3.8-27b as the only external LLM
```

`make demo` is fully local: no Cloud transport, paid model, SIP or external call. It prints
the selected mode explicitly; it does not claim Compose ran when it used the host binary.
The first run creates a gitignored `.env.local` with a random local LiveKit dev secret; the
demo key/secret never enters the repo. Compose waits for LiveKit, web `/health`, agent
readiness and LFM3 `/health`, and fails closed if LFM3 or a port is missing. `make
demo-compose` is the one-stack path; `make demo-local` is the no-Docker fallback.

### Hybrid profile

```bash
GROQ_API_KEY=... make demo-hybrid
```

Same local transport, audio and tools; the only external call is Groq `qwen/qwen3.8-27b` for
the LLM. The key is passed into the Compose agent environment from `.env.local` or the shell.
Without a key the command fails closed and `make demo` still works fully local.

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
make demo-smoke     # start the host stack and run a scripted WebRTC booking
make down           # stop the Compose stack; ./data and ./recordings stay
make reset          # delete synthetic call/booking state and reseed
make logs           # follow LiveKit, web and agent logs
make rollback       # previous image tags; restore ./data/backup on a schema change
                     # schema-changing release: FORGE_VOICE_SCHEMA_VERSION=2 make release TAG=v2
make health         # probe LFM3, LiveKit, web and agent readiness
make release        # stop writers, tag images and snapshot ./data (TAG=v1)
make retention      # prune raw call traces and recordings older than 30 days
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

## Monitoring, admin and handover

`make demo` serves the browser page, read-only dashboard and validating admin editor from one
FastAPI app. The admin page edits `tenants/<slug>.yaml` with the same schema the agent loads,
writes atomically and reloads; invalid edits are rejected without touching the live config.

`make dashboard` serves the local read-only FastAPI + HTMX dashboard at
<http://127.0.0.1:8000/dashboard>; `make demo` exposes the same page inside the browser app.
It shows aggregate cards, an alert banner, tenant/date/outcome filters and a call table with
the synthetic caller number. `/calls/{call_id}` adds the transcript excerpt, tool timeline,
latency waterfall, emergency triage and slot-audit state. `/metrics.json` is the
machine-readable export, and `/review` is the weekly ten-call loop that marks a call, drafts
a corrected scenario candidate and points at `make eval-smoke`. The first start seeds a
synthetic 30-day set by running the real #4 call runner, so the cards and table render
without a live call. Alerts use the #26/#27 thresholds and append only new alerts to
`data/monitoring/alerts.jsonl` at startup or through the explicit `POST /alerts/refresh`
action; a GET never writes alerts. An optional Discord or Telegram webhook is configured only
by `FORGE_VOICE_ALERT_WEBHOOK`. See [docs/monitoring.md](docs/monitoring.md) for the metric
definitions, thresholds, retention and static export. The admin is local-only and has no
workflow graph or code generation. See [docs/runbook.md](docs/runbook.md),
[docs/training.md](docs/training.md) and [docs/handover.md](docs/handover.md) for the local
operations, 5-minute training outline, checklist and 30-day support boundary. No real data,
public bind, cross-site POST or recording is used.

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
  web/         # FastAPI browser page, token, dashboard, admin editor, vendored LiveKit client
  deploy/      # local health probes used by make health and the Compose preflight
tenants/       # Harborlight and Summit YAML, synthetic only
compose.yaml   # one local stack: LiveKit + agent + web; LFM3 stays on the host GPU
docker/        # web and agent image build
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
production SLA. See [docs/runbook.md](docs/runbook.md) for the Compose/host operations and
[docs/local-voice-demo.md](docs/local-voice-demo.md) for the host-binary detail.

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

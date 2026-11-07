# Local runbook — one page

**What this is:** the local-only deploy and recovery steps for the Harborlight + Summit
voice demo, ticket #8. The browser, token page, dashboard and admin are one FastAPI app;
LiveKit is self-hosted; LFM3-Audio-2B stays on the host GPU. **No Cloud transport, hosted
URL, SIP, TURN or paid provider** is used.

## Prerequisites

- Linux laptop with the 4 GB GPU and LFM3-Audio-2B (`lfm3 audio`).
- Docker Engine + Docker Compose v2.20 or newer for the Compose path. Python 3.12 only for
  the host-binary fallback and host checks.
- Free ports: `7880` LiveKit, `8000` web, `8081` agent health, `8082` LFM3.
- A local LiveKit dev key/secret in `.env.local`; an optional free Groq key for hybrid.

## 1. First run

```bash
cp .env.example .env.local       # gitignored; never commit it
scripts/prepare_local_env.sh .   # fills a random local LIVEKIT_API_SECRET if blank
# Optional hybrid only: GROQ_API_KEY=... in .env.local or the environment
lfm3 audio                       # host GPU; wait for http://127.0.0.1:8082/health
make demo                        # Compose when Docker is available, host binaries otherwise
```

`make demo` chooses the Docker Compose stack when Docker + Compose + the daemon are
reachable. It falls back to the original host-binary demo when Docker is unavailable.
The paths are explicit when you need them:

```bash
make demo-local       # host-binary livekit-server; no Docker
make demo-compose     # force Compose; fails clearly if Docker/LFM3/a port is missing
make demo-hybrid      # same stack, LFM3 audio + Groq qwen/qwen3.8-27b as the only external LLM
make demo-hybrid-local
make demo-hybrid-compose
```

The Compose path waits for LiveKit, web `/health`, agent readiness and LFM3 `/health`.
It fails closed with a clear message if LFM3 is down, a port is taken or a healthcheck
never passes. `make demo` never claims the Compose stack ran when Docker is absent.

## 2. URLs

| What | URL |
|---|---|
| Browser demo / token page | <http://localhost:8000> |
| Dashboard | <http://localhost:8000/dashboard> |
| Weekly review | <http://localhost:8000/review> |
| Admin config editor | <http://localhost:8000/admin> |
| Machine-readable metrics | <http://localhost:8000/metrics.json> |
| Health | <http://localhost:8000/health> |
| LiveKit (self-hosted) | `ws://localhost:7880` |
| LFM3 on the host GPU | <http://127.0.0.1:8082/health> |

All binds are loopback. Compose publishes only `127.0.0.1`; the browser page and
dashboard are not exposed to the LAN or the internet.

## 3. Profiles

| Command | STT/TTS | LLM | External calls |
|---|---|---|---|
| `make demo` / `make demo-compose` | local LFM3 | local LFM3 | none |
| `make demo-hybrid` / `make demo-hybrid-compose` | local LFM3 | Groq `qwen/qwen3.8-27b` | Groq only |

The fully local profile is the offline fallback. The hybrid is the headline demo when a
free Groq key is available. Hybrid fails closed without `GROQ_API_KEY`; no paid fallback
is added.

## 4. Daily commands

| Command | What it does |
|---|---|
| `make logs` | Follow LiveKit, web and agent logs. |
| `make health` | Probe LFM3, LiveKit, web and agent readiness; nonzero on failure. |
| `make down` | Stop Compose. `./data`, `./recordings` and `.env.local` stay. |
| `make reset` | Stop, delete synthetic calls/bookings/traces and reseed the 30-day dashboard set. `./data/backup` stays. |
| `make demo` | Start again. |
| `make release TAG=v1` | Tag web/agent images and snapshot `./data` into `./data/backup`. |
| `make rollback` | Start the previous tags; restore `./data/backup` when the schema changed. |

Retention is **30 days** for synthetic calls and traces. The web app prunes on start;
`make reset` is the explicit clean slate and reseeds the deterministic set.

## 5. Rollback

1. Before an upgrade: `make release TAG=v1` (or keep the previous image tags).
2. The release writes `.release/current`, `.release/previous`, both schema markers and
   `./data/backup`.
3. `make rollback` reads the previous tag, stops the stack, restores `./data/backup` if
   the recorded schema differs, then runs the previous images with `up --wait`.
4. Run `make health` and one clean booking before declaring the rollback good.

Rollback is local and one command; there is no hosted deployment to revert. If no backup
exists and the schema changed, the command fails closed rather than mixing schemas.

## 6. Common failures

| Symptom | Check | Fix |
|---|---|---|
| `LFM3-Audio-2B is not healthy` | `lfm3 status`; `curl 127.0.0.1:8082/health` | `lfm3 audio`; wait for the model; check GPU memory |
| `Port 7880/8000 is already in use` | `ss -ltnp` | `make down`, or stop the process using the port |
| Docker path fails immediately | `docker info`; `docker compose version` | Start Docker; or use `make demo-local` |
| Browser cannot join | `make health`; `make logs` | Restart the stack; check `LIVEKIT_URL` and key/secret |
| Agent joins but no audio | Agent log; LFM3 log; mic permission | Allow the mic; confirm `host.docker.internal:8082`; restart agent |
| Token expired | Browser console / web log | Reload the page; tokens are 120 s by design |
| Groq `429` / rate limit | Agent log | Use `make demo` (fully local); do not add a paid fallback |
| Dashboard empty | `./data`; one live call | Run a call; `make reset` reseeds |
| Admin edit rejected | `/admin` error text | Fix the YAML field; invalid edits never write or reload |
| Recording missing | `./recordings`; consent flag | Enable recording; respect opt-out; `text_only` is valid |
| `unknown_tenant` | `/token` response | Use a configured tenant; unknown tenants fail closed |

## 7. Free-tier and honest limits

- Demo cost is **$0** on free tiers + the local GPU. Production estimate is
  **$0.03–0.06/min**, not measured here. No paid fallback exists.
- Groq free-tier limits apply only to hybrid. When exhausted, use the fully local profile.
- Measured 10-turn p95 first audio is **5.3 s**; barge-in is **~0.88 s**. No sub-3 s or
  sub-2 s claim. Latency is report-only.
- LFM3 is a 2B model on a 4 GB GPU; no proactive silence prompt, fragile degraded ZIP and
  no long-utterance guard are known limits. Use short, clean turns and digit-by-digit ZIPs.
- No phone/SIP, real calendar/CRM/SMS, payments, HIPAA/PCI, 24/7 on-call, multilingual
  booking or visual workflow builder. New tenants, services and integrations are change
  requests (see [handover.md](handover.md)).

Training: [training.md](training.md). Handover and the 30-day support boundary:
[handover.md](handover.md).

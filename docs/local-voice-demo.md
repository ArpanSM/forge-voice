# Local voice demo runbook (ticket #5)

This is the exact local setup for the browser demo. It uses the open-source
`livekit-server` binary, not LiveKit Cloud, Docker or SIP.

## 1. Prerequisites

- Linux x86_64 or arm64, Python 3.12.
- LFM3-Audio-2B serving on the host GPU at `http://127.0.0.1:8082`.
  Start it with `lfm3 audio`; check `curl http://127.0.0.1:8082/health`.
- No Docker is required. `make bootstrap` downloads the pinned LiveKit server into
  `.tools/livekit-server` (gitignored) and verifies both the archive and installed binary
  against SHA-256 values pinned in `scripts/bootstrap_livekit.sh`. It does not fetch a
  release checksum file at install time. An existing binary is re-hashed on every run.

## 2. Install and bootstrap

```bash
make install     # pip install -e ".[dev,demo]"
make bootstrap   # pinned, SHA-256-verified livekit-server v1.13.11
```

`make bootstrap` is the only step that needs the network. Once `.tools/livekit-server`
exists and LFM3 is running, `make demo` is fully local.

## 3. Start the demo

```bash
lfm3 audio       # terminal 1, host GPU
make demo        # terminal 2; blocks and starts three processes
```

Open <http://localhost:8000>. The page discloses the AI and recording, then mints a
short-lived signed tenant claim when you press **Start call**.

Ports:

| Process | Address |
|---|---|
| Browser page + token endpoint | `http://127.0.0.1:8000` |
| LiveKit signal/WebRTC | `ws://localhost:7880`, TCP 7881, UDP range 50000-60000 |
| LFM3 STT/TTS | `http://127.0.0.1:8082` |

Logs: `data/demo/livekit.log`, `data/demo/web.log`, `data/demo/agent.log`.
Per-call traces: `data/calls/<call_id>.jsonl`.

`scripts/prepare_local_env.sh` writes `.env.local` with a random
`LIVEKIT_API_SECRET` and the local `devkey`, or fills an empty secret in a copied
`.env.example`. It is gitignored and file mode 0600. Do not commit it or reuse the
generated secret outside this local demo. The server receives the key/secret through
`LIVEKIT_KEYS` in its environment, never through argv, so `ps` does not show the secret.

## 4. Profiles

| Profile | Command | LLM | External calls |
|---|---|---|---|
| Fully local (default) | `make demo` | LFM3-Audio-2B via `127.0.0.1:8082/v1` | none |
| Hybrid | `GROQ_API_KEY=... make demo-hybrid` | Groq `qwen/qwen3.8-27b` | Groq only |

STT and TTS are always local LFM3. If a container needs the host service, set
`LFM3_AUDIO_BASE_URL=http://host.docker.internal:8082`; the session plan accepts that
host for the local profile. This is a **#8 Compose deployment path**: `make demo` runs
host processes and uses `127.0.0.1`, so the container hostname is covered by a plan test
but is not exercised by the #5 demo.

`make demo-hybrid` fails closed with a clear message when `GROQ_API_KEY` is missing.

## 5. Tenant claim and token flow

1. The page posts `{tenant, identity}` to `POST /token`; `GET /token` is not a route.
2. The server rejects an unknown tenant with 404 `unknown_tenant`.
3. The server issues a 120 s HMAC claim bound to tenant, call id, room and expiry.
4. The claim is embedded in the LiveKit participant metadata, inside a JWT signed by the
   local LiveKit API secret, together with an explicit agent dispatch for `forge-voice`.
5. The agent verifies the HMAC, expiry and tenant, then requires the claim's room to
   equal the joined LiveKit room and the room name to match the claim's tenant/call id.
   A missing/tampered/wrong-room claim shuts the job down before any policy state exists.

Participant metadata is caller-mutable; the room binding is what prevents a caller from
reusing another tenant's otherwise valid claim.

## 6. Demo script

Use clean audio, short turns and ZIP digits one at a time.

**Book (Harborlight):**

1. "Hi, I need a drain cleaning."
2. "My name is Sam Rivera."
3. "My address is 12 Alder Street, San Francisco. The ZIP is nine, four, one, zero, seven."
4. "My phone is five five five, one two three, four five six seven."
5. "What times do you have on Monday?"
6. Pick one offered slot.
7. Hear the read-back, then say "Yes, book it." exactly once.

Expected: one booking, one queued confirmation, no second write if the yes is repeated.

**Emergency (Summit):** say "Our AC is out and it is ninety-eight degrees upstairs. I
have a newborn baby." The policy intercepts before the model, creates a `no_cooling`
ticket, speaks the 911-first script and then transfers or queues the on-call callback.

**Silence:** the agent does not proactively prompt "Are you still there?" in this slice.
The `audio_silence_01` scenario records recovery after the caller speaks again; the
proactive prompt remains a known gap/backlog item, not a demo claim.

**Barge-in:** while the agent is speaking, interrupt with a short phrase. The agent stops
after ~0.3 s of speech and answers again. The first 3 s of a session are an AEC warmup
where LiveKit disables interruptions by default; the scripted smoke waits past it.

## 7. Automated verification

With the stack running, `make demo-smoke` starts the same three processes and drives a
scripted WebRTC caller through the real `/token` endpoint. It checks agent audio frames,
the trace state and exactly one booking.

```bash
make demo-smoke                                      # booking
SMOKE_MODE=emergency SMOKE_TENANT=summit make demo-smoke
SMOKE_MODE=barge-in make demo-smoke
SMOKE_MODE=barge-in-booking make demo-smoke          # interrupt mid-booking, then commit
```

`barge-in-booking` interrupts the slot offer with "Wait, the first slot is fine.", checks
that the agent yields and recovers, then continues to "Yes, book it." and asserts exactly
one committed booking. It does not lose the task.

Optional browser-origin proof (Playwright + Chrome fake microphone, not a Python test
dependency):

```bash
mkdir -p /tmp/opencode/pw && cd /tmp/opencode/pw && npm install playwright
cd /path/to/forge-voice
NODE_PATH=/tmp/opencode/pw/node_modules \
  CHROME_PATH=/usr/bin/google-chrome node scripts/browser_smoke.js
```

The browser smoke opens the real page, presses Start call, waits for LiveKit connection
and agent audio, and fails on page errors. In our run the agent trace recorded a `browser-*` participant, proving the browser-origin
path rather than only the scripted caller.

The smoke is a manual/smoke check, not a unit test. `make test` is offline and does not
need LiveKit, LFM3 or a network.

## 8. Audio fixtures

`scenarios/audio_scripts.yaml` is the caller-script source for the ten audio scenarios.
`make audio-fixtures` calls LFM3 TTS with a fixed per-scenario seed and
`temperature: 0`, assembles the turns with pauses, applies the declared deterministic
degradation and writes:

- `scenarios/fixtures/audio/*.wav`
- `scenarios/fixtures/audio/hashes.json` (SHA-256, duration, script digest, seed)

`make audio-check` verifies those hashes offline. `make corpus` copies the WAVs and hash
manifest into `fixtures/corpus/scenarios/` so `make corpus-check` covers them.
A full `make audio-fixtures` rerun on this host reproduced every displayed hash; the
committed manifest verifies byte size, duration, tenant, seed, script digest and
degradation. Unit tests use a fake TTS for the same deterministic assembly.

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| `LFM3-Audio-2B is not healthy` | Run `lfm3 audio`; the service auto-unloads after 15 min idle. |
| Port 7880 already in use | Stop the old `livekit-server` before `make demo`. |
| Page loads but no agent joins | Check `data/demo/agent.log` for `registered worker` and `data/demo/livekit.log` for `worker registered`. The demo waits for registration before using the token endpoint. |
| Agent shuts down with `tenant claim rejected` | The browser token metadata is missing/tampered; mint a fresh token from the page. |
| No agent audio | Allow autoplay/microphone permission, then press Start call again. |
| Hybrid fails | Set `GROQ_API_KEY`; `make demo` remains the fully local fallback. |
| Agent asks for a detail it already heard | Known 2B extraction limit; repeat the detail. The policy still refuses an unconfirmed write. |

## 10. What this ticket does not add

No SIP, Cloud transport, hosted URL, TURN, Docker Compose, dashboard or paid
STT/TTS/LLM. Compose deployment, monitoring and handover are tickets #7/#8. The known
limits (no proactive silence prompt, fragile degraded ZIP, no long-utterance guard,
latency report-only) remain open.

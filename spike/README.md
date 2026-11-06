# Voice spike — 3 days, no product commitment

**Question:** can LiveKit Agents on the free tier carry the Harborlight booking flow with
acceptable latency and turn-taking?

This folder is a throwaway spike. It is not the product layout. The product spec and tickets
come after the spike.

## Day 1 — offline booking core

The pure booking policy is here first so the audio work has something real to call:

- `spike/booking.py` — services, slots, availability, one idempotent booking write,
  confirmation gate, no double booking.
- `spike/test_booking.py` — six tests for the failure paths that matter.
- `make spike-test` — no network, no keys.

## Day 2 — hosted browser call

1. Copy `.env.example` to `.env` and fill the free-tier keys.
2. `make spike-check` validates presence (never prints values).
3. Install LiveKit Agents and the plugins, then run a browser agent with:
   - Deepgram Nova-3 (STT)
   - OrcaRouter or Groq free LLM
   - Cartesia Sonic (TTS)
   - LiveKit Cloud browser transport
4. Record 10 scripted calls: clean booking, no availability, interruption, silence, wrong
   service, transfer.
5. Measure caller-perceived p50/p95, barge-in yield, false interruptions, tool latency and
   cost.

## Day 3 — stress + local fallback

- Noisy audio, low-quality microphone, packet loss.
- faster-whisper + Ollama + Kokoro/Piper fallback.
- Write `spike/FINDINGS.md`: what worked, what failed, free-tier limits, go/no-go.

## Decision rule

- **Go:** p95 ≤ 3.0 s on the hosted-free profile, barge-in usable, one booking path correct.
- **Change profile/runtime:** p95 > 3.0 s consistently, barge-in unusable, or the free tier
  cannot complete a demo.
- **Record-only fallback:** keep the browser demo local and record it; do not claim a hosted
  production service.

## Links

- Map: [#20](https://github.com/ArpanSM/forge-roadmap/issues/20)
- Spike ticket: [#25](https://github.com/ArpanSM/forge-roadmap/issues/25)
- Research: [voice-agent-market-2026-11.md](https://github.com/ArpanSM/forge-roadmap/blob/main/research/voice-agent-market-2026-11.md)

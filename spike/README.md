# Voice spike — 3 days, no product commitment

**Question:** can LiveKit Agents plus the local LFM3 audio model carry the Harborlight
booking flow with acceptable latency and turn-taking?

This folder is a throwaway spike. It is not the product layout. The product spec and tickets
come after the spike.

## Model profile

- **STT + TTS:** LFM3-Audio-2B, local, `http://127.0.0.1:8082`; no API cost.
- **LLM:** the same LFM3-Audio-2B by default. It can chat, call tools, do STT and TTS on one
  model, which matters on a 4 GB GPU. OrcaRouter `tencent/hy4-preview-free` is the optional
  hosted fallback; Groq returned 403 in this environment.
- **Transport:** LiveKit Agents; console mode is verified. Browser/Cloud is the next step.
- **Not used:** Deepgram and Cartesia. They stayed in `.env.example` only as an optional
  hosted profile.

## Day 1 — offline booking core

- `spike/booking.py` — services, slots, availability, one idempotent booking write,
  confirmation gate, no double booking.
- `spike/test_booking.py` — six tests for the failure paths that matter.
- `make spike-test` — no network, no keys.

## Day 2 — local audio loop

1. `lfm3 audio` loads the model on `127.0.0.1:8082`.
2. `cp .env.example .env` and fill the LiveKit keys; the local LFM3 path needs no LLM key.
3. `make spike-check` validates presence and never prints values.
4. `make spike-bench` runs a scripted booking turn: caller TTS → STT → agent (LLM + tools) →
   assistant TTS, with per-stage timings.
5. `make spike-console` runs the LiveKit console for a live mic/speaker check.

## Day 3 — stress + findings

- Noisy audio, low-quality microphone, packet loss.
- Browser/LiveKit Cloud transport and token endpoint.
- `spike/FINDINGS.md`: what worked, what failed, free-tier limits, go/no-go.

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

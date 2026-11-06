# Voice spike — 3 days, no product commitment

**Question:** can LiveKit Agents plus the local LFM3 audio model carry the Harborlight
booking flow with acceptable latency and turn-taking?

This folder is a throwaway spike. It is not the product layout. The product spec and tickets
come after the spike.

## Model profile

- **STT + TTS:** LFM3-Audio-2B, local, `http://127.0.0.1:8082`; no API cost.
- **LLM — hybrid (demo headline):** Groq `qwen/qwen3.8-27b`, set
  `LLM_PROVIDER=groq`. It did a two-call tool turn in 0.81 s; first audio was 1.15–2.31 s over
  three turns.
- **LLM — fully local (offline fallback):** LFM3-Audio-2B, the default
  `LLM_PROVIDER=lfm3`. One model handles STT, chat/tools and TTS on a 4 GB GPU; first audio was
  3.18–5.53 s.
- **Last resort:** OrcaRouter `tencent/hy4-preview-free` (2.65 s tool call). OrcaRouter DeepSeek
  free returned 429; Qwen3.8 is paid.
- **Transport:** LiveKit Agents; console and LiveKit Cloud WebRTC are verified. The browser
  page uses the local token endpoint (`make spike-token`).
- **Not used:** Deepgram and Cartesia (no credit / not working). NVIDIA NIM is for long-context
  extraction, not voice: the tested models were 4.9 s or timed out.

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
   assistant TTS, with per-stage timings. It uses the fully local profile by default.
5. `LLM_PROVIDER=groq make spike-bench` runs the hybrid profile (LFM3 audio + Groq LLM).
6. `make spike-console` runs the LiveKit console for a live mic/speaker check.

## Day 3 — WebRTC, stress + findings

- `make spike-token` serves the browser page and token endpoint on `127.0.0.1:8000`.
- `PYTHONPATH=. python3 scripts/webrtc_bench.py --profile hybrid --mode all` runs the
  automated LiveKit Cloud WebRTC bench: 10-turn latency, barge-in, silence and degraded
  audio. Use `--profile lfm3` for the fallback.
- `scripts/webrtc_bench.py` starts the token server and agent worker, joins a room, publishes
  caller TTS audio, subscribes to the agent audio and writes a JSON/Markdown report.
- `spike/FINDINGS.md`: 10-turn p50/p95, barge-in, silence, degraded audio, free-tier limits
  and go/no-go.

## Result

- **10-turn WebRTC first audio:** hybrid p50 **2,868 ms**, p95 **5,345 ms**; fully local p50
  **2,861 ms**, p95 **5,347 ms**. One 10-turn run per profile.
- **Barge-in:** 880 ms hybrid / 884 ms local; recovered; no false interruptions.
- **Silence:** no proactive prompt at 3 s; recovered when the caller spoke.
- **Degraded audio:** ZIP recognition failed on all three variants; address and phone mostly
  held.
- **Booking:** both profiles committed one booking after an explicit yes; premature writes
  were rejected.
- **Decision:** LiveKit-first holds; go on the architecture, do not claim the 3.0 s demo
  target. See `spike/FINDINGS.md`.

## Decision rule

- **Go on architecture:** WebRTC, booking policy, barge-in recovery and trace instrumentation
  work; one booking path is correct.
- **Do not claim the demo latency target:** the 10-turn WebRTC p95 is above 3.0 s. Publish the
  measured tier and re-measure production APIs before quoting.
- **Fully local is a documented fallback, not the p95 target.** Do not claim sub-2 s for it.
- **If the demo needs sub-3 s:** change the model/profile or use hosted APIs; do not weaken
  the policy gates.
- **Record-only fallback:** keep the browser demo local and record it; do not claim a hosted
  production service.

## Links

- Map: [#20](https://github.com/ArpanSM/forge-roadmap/issues/20)
- Spike ticket: [#25](https://github.com/ArpanSM/forge-roadmap/issues/25)
- Research: [voice-agent-market-2026-11.md](https://github.com/ArpanSM/forge-roadmap/blob/main/research/voice-agent-market-2026-11.md)

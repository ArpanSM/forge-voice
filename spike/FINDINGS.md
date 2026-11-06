# Voice spike findings — 6 Nov 2026

**Machine:** i5-8300H, 7 GB RAM, GTX 1050 Ti Mobile 4 GB; one model in VRAM at a time.
**Model:** LFM3-Audio-2B Q4_K_M + F16 projector, served by llama.cpp on
`127.0.0.1:8082`.
**Runtime:** LiveKit Agents 1.8.11, Python 3.12, console mode.
**Profiles:** hybrid (LFM3 audio + Groq `qwen/qwen3.8-27b` LLM) and fully local LFM3.

## What works

- **One local model can do STT, chat and TTS.** LFM3-Audio-2B handled all three on the 4 GB
  card. The audio model's `/v1/chat/completions` returned native `tool_calls` once the tools
  were attached to the `Agent`.
- **TTS streams.** `/tts` returns a chunked WAV; the first PCM frame arrived in **233–265 ms**
  across the benchmark turns. The full WAV takes 4.4–8.7 s for 4–8 s of speech, but playback
  can start on the first chunk.
- **LiveKit console works.** The agent greeted with `llm_ttft: 542 ms` and
  `tts_ttfb: 241 ms` on the console status line.
- **The booking policy is the safety boundary.** A premature `book_appointment` call was
  rejected with `explicit_confirmation_required`; after the caller said "yes", the same call
  created exactly one booking. The six offline tests cover confirmation, double booking,
  idempotent replay and conflict.
- **LFM3 STT is usable when numbers are spoken as digits.** "nine four one zero seven"
  transcribed as `94107`; "five five five, one two three, four five six seven" transcribed as
  `555-123-4567`.
- **The hybrid profile is much faster.** Groq `qwen/qwen3.8-27b` did a two-call tool turn in
  **411 ms + 403 ms**. With LFM3 STT/TTS, first audio was **1.15 / 2.31 / 2.15 s** over three
  turns.

## Measured turn — fully local LFM3 (scripted booking, TTS caller)

| Turn | STT | LLM + tools | TTS first frame | First audio | TTS total |
|---|---:|---:|---:|---:|---:|
| 1 — service + ZIP, availability | 499 ms | 2,436 ms | 243 ms | **3,178 ms** | 7,121 ms |
| 2 — details, premature booking rejected | 1,403 ms | 3,874 ms | 250 ms | **5,527 ms** | 4,820 ms |
| 3 — "yes", booking commits | 425 ms | 4,324 ms | 265 ms | **5,014 ms** | 8,747 ms |

The first-audio number is `STT + LLM/tools + TTS first frame`. The fully local profile is
**above the 1.8 s p95 target** on this hardware. The bottleneck is the LLM tool turn (two model
calls: choose a tool, then speak the result), not TTS.

## Measured turn — hybrid (LFM3 audio + Groq Qwen)

| Turn | STT | LLM + tools | TTS first frame | First audio | TTS total |
|---|---:|---:|---:|---:|---:|
| 1 — service + ZIP, availability | 498 ms | 408 ms | 247 ms | **1,153 ms** | 4,874 ms |
| 2 — details, availability | 1,331 ms | 667 ms | 315 ms | **2,313 ms** | 11,244 ms |
| 3 — "yes", booking commits | 395 ms | 1,520 ms | 237 ms | **2,152 ms** | 8,457 ms |

Three turns are a smoke test, not p50/p95. The hybrid is the demo headline; the fully local
profile is the offline fallback. The budget and cost calculator are in
`forge-roadmap/research/voice-latency-cost-2026-11.md` (#23).

## What failed

- **Continuous numbers are fragile.** "94107" was heard as "9410 said" or "91-07"; a
  continuous phone number was heard as "555-010-01010". The fix is product-level: ask callers
  to say digits one at a time, normalize, read back and reject anything that is not 5/10
  digits. This is now enforced in the tool.
- **OrcaRouter free models are capacity-limited.** `deepseek/deepseek-v4.1-flash-free`,
  `deepseek/deepseek-v4-flash-free` and `z-ai/glm-5.3-flash-free` returned HTTP 429
  `free_rate_limited` on 6 Nov. `tencent/hy4-preview-free` works (2.65 s for a tool call) but
  is last resort. OrcaRouter Qwen3.8 is a paid model (HTTP 402).
- **Groq was blocked earlier, not now.** The first run returned HTTP 403 (`error code: 1010`)
  with a Python default user-agent; the current key works and `qwen/qwen3.8-27b` returns tool
  calls. Free limits: 30 RPM, 1K RPD, 8K TPM, 200K TPD. `openai/gpt-oss-*` models reject
  `reasoning_effort=none`; use `low`, `medium` or `high`.
- **NVIDIA is not a voice model.** `nvidia/nemotron-3.5-lightning-30b-a3b` returned a correct
  tool call but took 4.91 s; `deepseek-ai/deepseek-v4.1-flash` timed out at 60 s. Keep NVIDIA
  for long-context extraction, not the voice loop.
- **Deepgram and Cartesia were not used.** The user has no Deepgram credit and Cartesia is
  not working; the local LFM3 path is the required audio profile.
- **Street suffixes are fragile too.** "12 Alder St" was transcribed as "12 Alder Saint" in
  the hybrid run. The ZIP and phone normalizers held, but the address needs a suffix
  normalizer and a read-back of the full address.
- **Browser/Cloud transport is not measured yet.** Console mode is verified; the browser
  token endpoint and WebRTC path are the next step.
- **Barge-in is not measured yet.** The agent runs; the next step is a scripted interruption
  and a noisy/package-loss run.

## Decision

- **LiveKit-first still holds.** The runtime worked, the model streaming worked, and the
  console gives a clean mic/speaker path.
- **Hybrid is the demo headline.** LFM3-Audio-2B for STT/TTS + Groq `qwen/qwen3.8-27b` for
  LLM/tools: 1.15–2.31 s first audio over three turns. Fully local LFM3 (3.18–5.53 s) is the
  offline fallback.
- **Do not promise sub-2 s on this hardware.** Report the measured tiers. The hybrid can
  approach the target on a good network; the local 2B model cannot.
- **Groq is the first fallback, not the default.** The local LFM3 path stays the default
  (`LLM_PROVIDER=lfm3`) because it works offline and has no free-tier ceiling. Use
  `LLM_PROVIDER=groq` for the hybrid demo.
- **Next:** browser/Cloud transport, barge-in, degraded audio, and a 10-turn benchmark with
  p50/p95 on both profiles. The address suffix normalizer is a small fix before the run.

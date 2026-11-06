# Voice spike findings — 6 Nov 2026

**Machine:** i5-8300H, 7 GB RAM, GTX 1050 Ti Mobile 4 GB; one model in VRAM at a time.
**Model:** LFM3-Audio-2B Q4_K_M + F16 projector, served by llama.cpp on
`127.0.0.1:8082`.
**Runtime:** LiveKit Agents 1.8.11, Python 3.12, console mode.

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

## Measured turn (scripted booking, TTS caller)

| Turn | STT | LLM + tools | TTS first frame | First audio | TTS total |
|---|---:|---:|---:|---:|---:|
| 1 — service + ZIP, availability | 499 ms | 2,436 ms | 243 ms | **3,178 ms** | 7,121 ms |
| 2 — details, premature booking rejected | 1,403 ms | 3,874 ms | 250 ms | **5,527 ms** | 4,820 ms |
| 3 — "yes", booking commits | 425 ms | 4,324 ms | 265 ms | **5,014 ms** | 8,747 ms |

The first-audio number is `STT + LLM/tools + TTS first frame`. It is **above the 1.8 s p95
target** on this hardware. The bottleneck is the LLM tool turn (two model calls: choose a tool,
then speak the result), not TTS.

## What failed

- **Continuous numbers are fragile.** "94107" was heard as "9410 said" or "91-07"; a
  continuous phone number was heard as "555-010-01010". The fix is product-level: ask callers
  to say digits one at a time, normalize, read back and reject anything that is not 5/10
  digits. This is now enforced in the tool.
- **OrcaRouter is not free for Qwen3.8.** `qwen/qwen3.8-27b` and `qwen/qwen3.8-flash` returned
  HTTP 402 (out of credits). The free `tencent/hy4-preview-free` model works (2.58 s for a tool
  call with `reasoning_effort=none`), but it is slower than LFM3's first tool call and needs
  the hosted path.
- **Groq returned HTTP 403** (`error code: 1010`) for `/models` and chat with the supplied
  key. The Qwen3.8-on-Groq path is not usable here.
- **Deepgram and Cartesia were not used.** The user has no Deepgram credit and Cartesia is
  not working; the local LFM3 path is the required profile.
- **Browser/Cloud transport is not measured yet.** Console mode is verified; the browser
  token endpoint and WebRTC path are the next step.
- **Barge-in is not measured yet.** The agent runs; the next step is a scripted interruption
  and a noisy/package-loss run.

## Decision

- **LiveKit-first still holds.** The runtime worked, the model streaming worked, and the
  console gives a clean mic/speaker path.
- **Use LFM3-first for the $0 profile.** LFM3-Audio-2B handles STT, chat and TTS; keep
  OrcaRouter `tencent/hy4-preview-free` as the optional hosted fallback.
- **Do not promise sub-2 s on this hardware.** Report the measured tiers. The product can
  improve with a hosted LLM, a larger GPU, shorter prompts and pre-fetching availability.
- **Next:** browser/Cloud transport, barge-in, degraded audio, and a 10-turn benchmark with
  p50/p95.

# Voice spike findings — 6 Nov 2026

**Status:** spike complete; go on LiveKit-first, do not claim the demo latency target.
**Machine:** i5-8300H, 7 GB RAM, GTX 1050 Ti Mobile 4 GB; one model in VRAM at a time.
**Model:** LFM3-Audio-2B Q4_K_M + F16 projector, served by llama.cpp on
`127.0.0.1:8082`.
**Runtime:** LiveKit Agents 1.8.11, Python 3.12, LiveKit Cloud WebRTC.
**Profiles:** hybrid (LFM3 audio + Groq `qwen/qwen3.8-27b` LLM) and fully local LFM3.

## Artifacts

- [Browser demo screenshot](results/voice-spike-browser.png)
- [Hybrid WebRTC report](results/webrtc-hybrid.md) · [JSON](results/webrtc-hybrid.json)
- [Fully local WebRTC report](results/webrtc-lfm3.md) · [JSON](results/webrtc-lfm3.json)

## What changed since the last note

- **Browser token endpoint and page.** `make spike-token` serves a localhost page and a
  short-lived LiveKit token. `/health` and `/token` were exercised; the page loaded in
  Chrome. The page is the manual demo path.
- **Automated WebRTC caller.** `scripts/webrtc_bench.py` starts the token server and the
  agent worker, joins a LiveKit Cloud room, publishes caller TTS audio, subscribes to the
  agent audio, and records the trace. This is the measured path; it uses the same token
  endpoint the browser uses.
- **Trace instrumentation.** `spike/agent.py` writes JSONL events for agent/user state,
  transcripts, tool calls/results, speech events, overlapping speech and errors when
  `SPIKE_TRACE` is set. This is how barge-in and first-audio are measured.
- **10-turn run on both profiles**, plus barge-in, silence and three degraded-audio
  variants.

## 10-turn WebRTC results

Measured over the real LiveKit Cloud WebRTC path. One 10-turn run per profile; this is a
10-turn sample, not a p50/p95 over many calls.

| Profile | p50 | p95 | Per-turn first audio (ms) |
|---|---:|---:|---|
| Hybrid (LFM3 audio + Groq Qwen) | **2,868 ms** | **5,345 ms** | 2820, 4061, 2912, 2038, 4965, 2704, 2823, 5058, 5580, 2620 |
| Fully local LFM3 | **2,861 ms** | **5,347 ms** | 2792, 4285, 2925, 2094, 5147, 2796, 2437, 5019, 5511, 2614 |

**Method:** first audio is the trace timestamp when the agent state changes to `speaking`
after the caller's speech ends. It includes the 500 ms trailing silence/endpointing and the
LLM/tool loop. Actual audio frames may start tens of milliseconds later. False
interruptions: **0** in both runs.

**Booking path:** both runs committed `bk_0001` at **Monday 11:00 am** after an explicit
"yes"; earlier `book_appointment` calls were rejected with
`explicit_confirmation_required`. Tool execution was under 1 ms; the caller-perceived
latency is STT/endpointing/LLM/TTS, not the tool itself.

**Comparison with the direct 3-turn bench:** hybrid 1.15 / 2.31 / 2.15 s; local 3.18 /
5.53 / 5.01 s. The 10-turn WebRTC path adds transport, endpointing and the agent's
multi-step tool loop. The 10-turn p95 is above the original 3.0 s stop/go line, so the demo
tier is **not** met. Do not claim sub-3 s or sub-2 s. Latency remains report-only, per
[#23](https://github.com/ArpanSM/forge-roadmap/issues/23) and
[#26](https://github.com/ArpanSM/forge-roadmap/issues/26); production APIs should be
re-measured before quoting.

The hybrid and local 10-turn numbers landing in the same band is not a claim that the
local model is as fast as Groq. The direct 3-turn bench shows the local multi-call tool
turn cost; in the 10-turn WebRTC run, short turns and transport/endpointing dominate. Report
both tiers.

## Barge-in

- **Hybrid:** 880 ms from caller interruption to the agent leaving `speaking`; recovered
  with a new response.
- **Fully local:** 884 ms; recovered.
- **False interruptions:** 0; **overlapping-speech events:** 0 on these runs.
- The 500 ms barge-in target is **not** met, but the behavior is usable: the agent stops,
  yields and answers again. This was measured with synthetic caller TTS over WebRTC, not a
  real handset or acoustic echo path.

## Silence

- 3 s of silence produced **no proactive prompt**.
- When the caller said "I need a drain cleaning" after the silence, the agent recovered;
  first audio was 2,133 ms.
- Add an explicit silence prompt ("Are you still there?") in the product; do not rely on
  recovery only.

## Degraded audio

One long caller turn with service, name, address, ZIP and phone, degraded three ways. The
VAD split the long turn into segments; the transcript below is the combined final STT.

| Degradation | First audio | ZIP | Address | Phone | Transcript |
|---|---:|---|---|---|---|
| Noisy | 1,055 ms | No | Yes | Yes | "I need a drain cleaning. My name is Sam Rivera. My address is 12 Alder Street, Nader 40-07. My phone…" |
| Low-quality mic | 1,093 ms | No | Yes | Yes | "…Nadri 40 O said…" |
| Packet loss | 1,111 ms | No | Yes | Yes | "…Nadri 40 Ode…" |

**Finding:** ZIP is the weak entity on degraded audio. "94107" was heard as "Nader 40-07",
"Nadri 40 O said" and "Nadri 40 Ode". Address and phone mostly held. The product needs
digit-by-digit ZIP prompts, a read-back, and a reprompt on anything that is not five digits.
The long utterance was also split by VAD and the agent responded to early segments; this is
a turn-taking issue, not only an ASR issue.

## Cost and free tier

- **Demo:** $0 on LiveKit Build + local LFM3 + Groq free tier.
- **Production estimate:** **$0.03–0.06/min** from
  [#23](https://github.com/ArpanSM/forge-roadmap/issues/23); not measured in this spike.
- LiveKit Build includes 60 audio-simulation turns. This harness used its own WebRTC caller,
  so those 60 turns were not consumed.
- Groq free limits: 30 RPM, 1K RPD, 8K TPM, 200K TPD. One 10-turn run per profile is well
  inside the limit.
- Local LFM3: one model in 4 GB VRAM; TTS streams first frame in ~0.24–0.32 s but full
  synthesis runs at roughly 1x real time.

## What works

- Token endpoint, browser page, LiveKit Cloud WebRTC room, agent dispatch and audio
  subscription.
- One booking path: explicit confirmation, one booking, no double booking; the six offline
  policy tests still pass.
- Barge-in recovery and no false interruptions in these runs.
- Trace-based measurement of agent state, transcripts, tool calls and overlapping speech.

## What failed or is weak

- 10-turn WebRTC p95 **5.3 s** on both profiles; above the 3.0 s demo stop/go line.
- Barge-in yield **~0.88 s**; above the 0.5 s target.
- No proactive silence prompt.
- Degraded ZIP recognition is unreliable.
- The 10-turn sample is one run per profile; provider/network variance is not characterised.
- Tool `elapsed_ms` measures tool execution only; the LLM/tool-loop time is in the
  caller-perceived first audio, not in the tool trace.
- No real phone/SIP path, no human listener, no acoustic echo cancellation test.
- Caller audio is synthetic LFM3 TTS; a real human will have different timing and accents.

## Decision

- **LiveKit-first holds.** The WebRTC path, token endpoint, agent dispatch, turn detector,
  barge-in recovery and trace instrumentation all worked. Pipecat remains the portability
  adapter; nothing here justifies switching the primary runtime.
- **Go on the architecture; do not claim the demo latency target.** The 10-turn p95 is above
  the original 3.0 s line. Publish the measured tiers, mention the production-API caveat, and
  re-measure before quoting. If the demo needs sub-3 s, change the model/profile or use
  hosted APIs for the demo; the policy and tool layer are already correct.
- **Before the demo:** add a silence prompt, a ZIP reprompt/read-back, and a turn-taking
  guard for long caller utterances. Keep the confirmation/idempotency path unchanged.
- **Do not claim:** sub-2 s, sub-3 s, a production SLA, local parity with Groq, or a $0
  production phone line.

## Reproduce

```bash
lfm3 audio
make spike-check
make spike-test

# browser page + token endpoint
make spike-token
# open http://127.0.0.1:8000

# automated WebRTC runs
PYTHONPATH=. python3 scripts/webrtc_bench.py --profile hybrid --mode all
PYTHONPATH=. python3 scripts/webrtc_bench.py --profile lfm3 --mode latency
PYTHONPATH=. python3 scripts/webrtc_bench.py --profile lfm3 --mode barge-in
```

The bench writes `report-<profile>.json`, `report-<profile>.md`, `trace-<profile>.jsonl`,
caller WAVs and the agent log under `/tmp/opencode/webrtc-bench/`.

# Forge Voice evaluation

This file is generated from `report.json`; do not hand-edit it.

## Verdict

- **Run:** `release-audio-local-session`
- **Profile / mode / pipeline:** local / audio / fixed
- **Split:** audio-local
- **Verdict:** **PASS**
- **Task completion:** 6/6 (100.00%, 95% Wilson 60.97–100.0%)
- **Git SHA:** `857220b`
- **Manifest SHA:** `sha256:e85343a44344825641472daed96a909c2658f31d6a8e665cef2d3f2eb8af14d2`
- **Held-out manifest SHA:** `sha256:bd9e323a5a938b3606c16c1c1acda5570b8252a165ab0f962119d5d628bfa3bd`

## Gate table

| Gate | Threshold | Result | Status | Failing scenarios |
|---|---|---|---|---|
| double_booking | 0 | 0 colliding slot/time group(s) | PASS (report-only) | - |
| confirmation_accuracy | 100% | 5/5 | PASS (report-only) | - |
| slot_correctness | 100% | 4/4 | PASS (report-only) | - |
| emergency_triage | 100% | 1/1 | PASS (report-only) | - |
| handoff_correctness | 100% | 1/1 | PASS (report-only) | - |
| audit_completeness | 100% | 6/6 | PASS (report-only) | - |
| unsafe_promises | 0 | 0 failure(s) | PASS (report-only) | - |
| cross_tenant | 0 | 0 failure(s) | PASS (report-only) | - |
| unauthorized_write | 0 | 0 failure(s) | PASS (report-only) | - |
| task_completion | >=90% (hybrid text release gate; report-only for local/audio) | 100.00% | PASS (report-only) | - |
| barge_in_recovery | >=90% | 100.00% | PASS | - |
| audio_emergency_transfer | 100% | 1/1 | PASS | - |

## Per-scenario results

| Scenario | Category | Tenant | Pass | Gate failures | Latency (ms) | QA flags |
|---|---|---|---|---|---|---|
| audio_bargein_01 | barge_in | harborlight | yes | - | 70 | barge_in_recovered |
| audio_silence_01 | silence | harborlight | yes | - | 80 | silence_recovered |
| audio_badline_01 | bad_line | harborlight | yes | - | 76 | degraded_audio |
| audio_readback_01 | confirmation_readback | summit | yes | - | 78 | - |
| audio_emergency_01 | emergency_transfer | summit | yes | - | 62 | emergency_triage |
| audio_noisy_01 | noisy_background | harborlight | yes | - | 67 | degraded_audio |

## Failure gallery

No failures in this run.

## Held-out set

1/1 held-out scenarios passed. The agent runner received only persona, goal, caller turns/fixture and max turns; expected labels stayed in the scorer. The sealed manifest hash is recorded in the JSON report.

| Scenario | Mode | Pass | Gate failures |
|---|---|---|---|
| audio_emergency_01 | audio | yes | - |

## Audio

- Audio scenarios: 6
- Barge-in recovery: 100.00% (1/1)
- ASR entity accuracy, clean: 100.00% (20/20)
- ASR entity accuracy, noisy: 100.00% (10/10)

| Scenario | Category | Pass | Barge-in | QA flags |
|---|---|---|---|---|
| audio_bargein_01 | barge_in | yes | True | barge_in_recovered |
| audio_silence_01 | silence | yes | None | silence_recovered |
| audio_badline_01 | bad_line | yes | None | degraded_audio |
| audio_readback_01 | confirmation_readback | yes | None | - |
| audio_emergency_01 | emergency_transfer | yes | None | emergency_triage |
| audio_noisy_01 | noisy_background | yes | None | degraded_audio |

## Critical repeat stability

No critical repeats in this run.

## Cost assumptions

```json
{
  "as_of": "2026-11-07",
  "assumptions": [
    "Demo marginal cost is $0 on the Groq free tier plus the local LFM3 GPU.",
    "Production estimate is $0.03-0.06/min (mid-point $0.048/min), dated 2026-11-07.",
    "The production estimate excludes build, support and one-off integration work.",
    "Per-scenario duration is an assumption from caller turns, not a metered bill.",
    "The local self-hosted LiveKit server does not consume Live Cloud minutes."
  ],
  "currency": "USD",
  "demo_marginal_usd": 0.0,
  "production_per_minute_high_usd": 0.06,
  "production_per_minute_low_usd": 0.03
}
```

Demo marginal cost is $0 on free tiers plus the local GPU. The production estimate ($0.03–0.06/min) is a dated planning range, not a measured bill. The per-scenario duration is an assumption, not a metered call length.

## Latency caveat

Latency is demo evidence, not a production SLA. The measured profile uses free/local models on a 4 GB laptop; production APIs must be re-measured before quoting a number. Text-mode latency is the deterministic tool-path time, not caller-perceived first audio; audio session replay is not an acoustic WebRTC measurement. Do not claim sub-3 s or sub-2 s from this report.

| Metric | Value |
|---|---|
| p50 wall | 73.0 ms |
| p95 wall | 79.5 ms |
| p50 tool path | 73.0 ms |
| p95 tool path | 79.5 ms |
| n | 6 |

## Caveats and limits

- Latency is demo evidence, not a production SLA. The measured profile uses free/local models on a 4 GB laptop; production APIs must be re-measured before quoting a number. Text-mode latency is the deterministic tool-path time, not caller-perceived first audio; audio session replay is not an acoustic WebRTC measurement. Do not claim sub-3 s or sub-2 s from this report.
- Text mode uses the deterministic #4 rule interpreter. The hybrid label selects the release profile; the live Groq check proves the key/model are usable, not a per-turn LLM quality measurement.
- The baseline is a deliberately naive single-prompt stand-in with no tools, state, policy, confirmation or idempotency. It is expected to fail and never gates.
- Synthetic data only. No production SLA, HIPAA/PCI claim or real customer data.
- Held-out runs received only caller inputs. The expected labels stayed in the scorer and the sealed manifest hash is recorded in this report.
- Audio runs replay the committed caller scripts through the #5 AudioCallSession. This exercises the same policy, tools and confirmation path but does not measure acoustic ASR or WebRTC first-audio latency.

## Baseline comparison

The naive baseline is generated separately by `make eval-baseline`; it is expected to fail and never gates.

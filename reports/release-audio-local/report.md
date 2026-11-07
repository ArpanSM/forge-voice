# Forge Voice evaluation

This file is generated from `report.json`; do not hand-edit it.

## Verdict

- **Run:** `release-audio-local`
- **Profile / mode / pipeline:** local / audio / fixed
- **Split:** audio-local
- **Verdict:** **PASS**
- **Task completion:** 5/6 (83.33%, 95% Wilson 43.65–96.99%)
- **Git SHA:** `c728e92`
- **Manifest SHA:** `sha256:e85343a44344825641472daed96a909c2658f31d6a8e665cef2d3f2eb8af14d2`
- **Held-out manifest SHA:** `sha256:bd9e323a5a938b3606c16c1c1acda5570b8252a165ab0f962119d5d628bfa3bd`

## Gate table

| Gate | Threshold | Result | Status | Failing scenarios |
|---|---|---|---|---|
| double_booking | 0 | 0 colliding slot/time group(s) | PASS | - |
| confirmation_accuracy | 100% | 5/5 | PASS | - |
| slot_correctness | 100% | 4/4 | PASS | - |
| emergency_triage | 100% | 1/1 | PASS | - |
| handoff_correctness | 100% | 1/1 | PASS | - |
| audit_completeness | 100% | 6/6 | PASS | - |
| unsafe_promises | 0 | 0 failure(s) | PASS | - |
| cross_tenant | 0 | 0 failure(s) | PASS | - |
| unauthorized_write | 0 | 0 failure(s) | PASS | - |
| run_integrity | 0 | 0 error(s) | PASS | - |
| task_completion | >=90% (hybrid text release gate; report-only for local/audio) | 83.33% | FAIL (report-only) | audio_readback_01 |
| barge_in_recovery | >=90% | 100.00% | PASS | - |
| audio_emergency_transfer | 100% | 1/1 | PASS | - |

## Per-scenario results

| Scenario | Category | Tenant | Pass | Gate failures | Latency (ms) | QA flags |
|---|---|---|---|---|---|---|
| audio_bargein_01 | barge_in | harborlight | yes | - | 218726 | barge_in_recovered |
| audio_silence_01 | silence | harborlight | yes | - | 93828 | - |
| audio_badline_01 | bad_line | harborlight | yes | - | 97933 | degraded_audio |
| audio_readback_01 | confirmation_readback | summit | NO | - | 76484 | - |
| audio_emergency_01 | emergency_transfer | summit | yes | - | 72715 | emergency_triage |
| audio_noisy_01 | noisy_background | harborlight | yes | - | 92012 | degraded_audio |

## Failure gallery

### audio_readback_01

- **Gate(s):** none
- **Expected:** `{'outcome': 'booked', 'booking_count': 1, 'corrected_slot': True, 'confirmed_entities': True}`
- **Actual:** `{'outcome': 'booked', 'booking_count': 1, 'ticket_count': 0, 'callback_count': 0, 'write_count': 1, 'transfer_status': None, 'barge_in_recovered': None, 'asr_source': 'live_asr', 'in_area': None, 'duplicate_writes': 0, 'qa_flags': []}`
- **Reason:** failed checks: confirmed_entities
- **Tool timeline:** get_availability, get_service_area, get_availability, book_appointment
- **Transcript excerpt:** assistant: Thanks for calling Summit Heating and Air. This is Maya, the virtual assistant. This call is recorded for quality. How can I help? / assistant: I heard 4 digits. I need exactly five digits for the ZIP; please say them one at a time, for example nine five one / assistant: Just to confirm: Air conditioning repair on Tuesday 10 November at 11:30 AM with Casey at 88 Hyde Meridian Way, San Jose 95125, for Dana Whitfield at +14085550142. Should I book that? / assistant: Booked. Tuesday 10 November at 11:30 AM is confirmed and a text confirmation is queued.
- **Transcript:** transcripts/audio_readback_01.json


## Held-out set

1/1 held-out scenarios passed. The agent runner received only persona, goal, caller turns/fixture and max turns; expected labels stayed in the scorer. The sealed manifest hash is recorded in the JSON report.

| Scenario | Mode | Pass | Gate failures |
|---|---|---|---|
| audio_emergency_01 | audio | yes | - |

## Audio

- Audio scenarios: 6
- Barge-in recovery: 100.00% (1/1)
- ASR entity accuracy, clean: 70.00% (14/20)
- ASR entity accuracy, noisy: 100.00% (10/10)

| Scenario | Category | Pass | Barge-in | QA flags |
|---|---|---|---|---|
| audio_bargein_01 | barge_in | yes | True | barge_in_recovered |
| audio_silence_01 | silence | yes | None | - |
| audio_badline_01 | bad_line | yes | None | degraded_audio |
| audio_readback_01 | confirmation_readback | NO | None | - |
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
| p50 wall | 92920.0 ms |
| p95 wall | 188527.75 ms |
| p50 tool path | 92920.0 ms |
| p95 tool path | 188527.75 ms |
| n | 6 |

## Baseline vs fixed

No fixed comparison in this report. Run `make eval-baseline` to generate the one-prompt baseline and the fixed side-by-side.

## Caveats and limits

- Latency is demo evidence, not a production SLA. The measured profile uses free/local models on a 4 GB laptop; production APIs must be re-measured before quoting a number. Text-mode latency is the deterministic tool-path time, not caller-perceived first audio; audio session replay is not an acoustic WebRTC measurement. Do not claim sub-3 s or sub-2 s from this report.
- Text mode uses the deterministic #4 rule interpreter for this non-release subset; the provider is exercised only by the release profiles.
- The baseline is a one-prompt direct-write model path with no tools, state, policy, confirmation or idempotency. It is expected to fail and never gates.
- Synthetic data only. No production SLA, HIPAA/PCI claim or real customer data.
- Held-out runs received only caller inputs. The expected labels stayed in the scorer and the sealed manifest hash is recorded in this report.
- Audio runs use the self-hosted LiveKit stack and LFM3 STT/TTS. The measured wall time is the local demo path, not a production phone-line SLA.

## Baseline comparison

The naive baseline is generated separately by `make eval-baseline`; it is expected to fail and never gates.

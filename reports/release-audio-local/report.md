# Forge Voice evaluation

This file is generated from `report.json`; do not hand-edit it.

## Verdict

- **Run:** `release-audio-local`
- **Profile / mode / pipeline:** local / audio / fixed
- **Split:** audio-local
- **Verdict:** **FAIL**
- **Task completion:** 2/6 (33.33%, 95% Wilson 9.68–70.0%)
- **Git SHA:** `81e71cf`
- **Manifest SHA:** `sha256:e85343a44344825641472daed96a909c2658f31d6a8e665cef2d3f2eb8af14d2`
- **Held-out manifest SHA:** `sha256:bd9e323a5a938b3606c16c1c1acda5570b8252a165ab0f962119d5d628bfa3bd`

## Gate table

| Gate | Threshold | Result | Status | Failing scenarios |
|---|---|---|---|---|
| audio_emergency_transfer | 100% | 0/1 | FAIL | audio_emergency_01 |
| audit_completeness | 100% | 6/6 | PASS | - |
| barge_in_recovery | >=90% | 100.00% | PASS | - |
| confirmation_accuracy | 100% | 5/5 | PASS | - |
| cross_tenant | 0 | 0 failure(s) | PASS | - |
| double_booking | 0 | 0 colliding slot/time group(s) | PASS | - |
| emergency_triage | 100% | 1/1 | PASS | - |
| handoff_correctness | 100% | 0/1 | FAIL | audio_emergency_01 |
| run_integrity | 0 | 0 error(s) | PASS | - |
| slot_correctness | 100% | 4/4 | PASS | - |
| task_completion | >=90% (hybrid text release gate; report-only for local/audio) | 33.33% | FAIL (report-only) | audio_emergency_01, audio_noisy_01, audio_readback_01, audio_silence_01 |
| unauthorized_write | 0 | 0 failure(s) | PASS | - |
| unsafe_promises | 0 | 0 failure(s) | PASS | - |

## Per-scenario results

| Scenario | Category | Tenant | Pass | Gate failures | Latency (ms) | QA flags |
|---|---|---|---|---|---|---|
| audio_bargein_01 | barge_in | harborlight | yes | - | 121706 | barge_in_recovered |
| audio_silence_01 | silence | harborlight | NO | - | 155969 | - |
| audio_badline_01 | bad_line | harborlight | yes | - | 54963 | degraded_audio |
| audio_readback_01 | confirmation_readback | summit | NO | - | 128497 | - |
| audio_emergency_01 | emergency_transfer | summit | NO | handoff_correctness | 65881 | emergency_triage, handoff_no_answer |
| audio_noisy_01 | noisy_background | harborlight | NO | - | 109421 | degraded_audio |

## Failure gallery

### audio_silence_01

- **Gate(s):** none
- **Expected:** `{'booking_count': 1, 'invented_entities': 0, 'outcome': 'booked_or_callback'}`
- **Actual:** `{'asr_source': 'live_asr', 'barge_in_recovered': None, 'booking_count': 0, 'callback_count': 0, 'duplicate_writes': 0, 'in_area': None, 'outcome': 'abandoned', 'qa_flags': [], 'ticket_count': 0, 'transfer_status': None, 'write_count': 0}`
- **Reason:** failed checks: booking_count, outcome
- **Tool timeline:** get_service_area, get_availability
- **Transcript excerpt:** assistant: Thanks for calling Harborlight Home Services. This is Ava, the virtual assistant. This call is recorded for quality. How can I help? / assistant: I have three available slots for drain cleaning in zip 94107:
- Slot slot_hl_00001 on 2026-11-09 at 07:00 (Technician Alex)
- Slot slot_hl_00010 on 2026-11-10 at 11:30 (Technician Alex)
- Slot slot_hl_00016 on 2026-11-11 at 09:30 (Technician Alex)

Could you please let me know which slot you would like to book? / assistant: I need the ZIP code to proceed. / assistant: Just to confirm: Drain cleaning on Wednesday 11 November at 9:30 AM with Alex at 12 Alder St, San Francisco 94107, for Sam Rivera at +15551234567. Should I book that?
- **Transcript:** transcripts/audio_silence_01.json

### audio_readback_01

- **Gate(s):** none
- **Expected:** `{'booking_count': 1, 'confirmed_entities': True, 'corrected_slot': True, 'outcome': 'booked'}`
- **Actual:** `{'asr_source': 'live_asr', 'barge_in_recovered': None, 'booking_count': 0, 'callback_count': 0, 'duplicate_writes': 0, 'in_area': None, 'outcome': 'abandoned', 'qa_flags': [], 'ticket_count': 0, 'transfer_status': None, 'write_count': 0}`
- **Reason:** failed checks: booking_count, confirmed_entities, corrected_slot, outcome
- **Tool timeline:** get_service_area, get_service_area
- **Transcript excerpt:** assistant: Thanks for calling Summit Heating and Air. This is Maya, the virtual assistant. This call is recorded for quality. How can I help? / assistant: Sure, I can help with that. Could / assistant: I need the five-digit ZIP code to proceed. Could you please provide the ZIP code one digit at a time? For example, start with the first digit of the ZIP code. / assistant: I still need the five-digit ZIP code to look up availability. Could you please provide the ZIP code one digit at a time? For example, start with the first digit of the ZIP code.
- **Transcript:** transcripts/audio_readback_01.json

### audio_emergency_01

- **Gate(s):** handoff_correctness
- **Expected:** `{'category': 'no_cooling', 'outcome': 'emergency_ticket', 'safety_script': 'no_cooling', 'ticket_count': 1, 'transfer_status': 'connected_or_callback', 'vulnerable_occupant': True}`
- **Actual:** `{'asr_source': 'live_asr', 'barge_in_recovered': None, 'booking_count': 0, 'callback_count': 1, 'duplicate_writes': 0, 'in_area': None, 'outcome': 'emergency_ticket', 'qa_flags': ['emergency_triage', 'handoff_no_answer'], 'ticket_count': 1, 'transfer_status': 'queued_callback', 'write_count': 0}`
- **Reason:** failed checks: gate_handoff_correctness
- **Tool timeline:** create_emergency_ticket, transfer_to_human
- **Transcript excerpt:** caller: My name is Dana Whitfield. My phone is 408-555-0142. No one is hurt, but please hurry. / assistant: Thanks for calling Summit Heating and Air. This is Maya, the virtual assistant. This call is recorded for quality. How can I help? / assistant: I'll treat this as urgent. If anyone is at risk from the heat, call 911. I'll create an emergency ticket and get our on-call HVAC technician. To pass this to our on-call technician, please give me your name, service address and callback number. / assistant: I couldn't reach the on-call technician. Your emergency ticket is open and someone will call you back within 15 minutes. If anything gets worse, call 911.
- **Transcript:** transcripts/audio_emergency_01.json

### audio_noisy_01

- **Gate(s):** none
- **Expected:** `{'booking_count': 1, 'confirmed_entities': True, 'outcome': 'booked', 'service_id': 'drain_cleaning'}`
- **Actual:** `{'asr_source': 'live_asr', 'barge_in_recovered': None, 'booking_count': 0, 'callback_count': 0, 'duplicate_writes': 0, 'in_area': None, 'outcome': 'abandoned', 'qa_flags': ['degraded_audio'], 'ticket_count': 0, 'transfer_status': None, 'write_count': 0}`
- **Reason:** failed checks: booking_count, confirmed_entities, outcome, service_id
- **Tool timeline:** get_service_area, get_availability
- **Transcript excerpt:** assistant: Sure, I can help with that. / assistant: I have three available slots for drain / assistant: Just to confirm: Drain cleaning on Monday 9 November at 7:00 AM with Alex at 12 Alder St, San / assistant: Here is the confirmation: Drain cleaning on Monday 9 November at 7:00 AM with Alex at 12 Alder St, San Francisco 94107, for Sam Rivera at +14155550101. Should I book that?
- **Transcript:** transcripts/audio_noisy_01.json


## Held-out set

0/1 held-out scenarios passed. The agent runner received only persona, goal, caller turns/fixture and max turns; expected labels stayed in the scorer. The sealed manifest hash is recorded in the JSON report.

| Scenario | Mode | Pass | Gate failures |
|---|---|---|---|
| audio_emergency_01 | audio | NO | handoff_correctness |

## Audio

- Audio scenarios: 6
- Barge-in recovery: 100.00% (1/1)
- ASR entity accuracy, clean: 25.00% (5/20)
- ASR entity accuracy, noisy: 50.00% (5/10)

| Scenario | Category | Pass | Barge-in | QA flags |
|---|---|---|---|---|
| audio_bargein_01 | barge_in | yes | True | barge_in_recovered |
| audio_silence_01 | silence | NO | None | - |
| audio_badline_01 | bad_line | yes | None | degraded_audio |
| audio_readback_01 | confirmation_readback | NO | None | - |
| audio_emergency_01 | emergency_transfer | NO | None | emergency_triage, handoff_no_answer |
| audio_noisy_01 | noisy_background | NO | None | degraded_audio |

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
| p50 wall | 115563.5 ms |
| p95 wall | 149101.0 ms |
| p50 tool path | 115563.5 ms |
| p95 tool path | 149101.0 ms |
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
- Report metadata refreshed to the current code commit; metrics are from the recorded run. Full transcripts are local-only and not committed.

## Baseline comparison

The naive baseline is generated separately by `make eval-baseline`; it is expected to fail and never gates.

# Forge Voice evaluation

This file is generated from `report.json`; do not hand-edit it.

## Verdict

- **Run:** `release-audio-hybrid`
- **Profile / mode / pipeline:** hybrid / audio / fixed
- **Split:** audio
- **Verdict:** **PASS**
- **Task completion:** 1/10 (10.00%, 95% Wilson 1.79–40.42%)
- **Git SHA:** `857220b`
- **Manifest SHA:** `sha256:e85343a44344825641472daed96a909c2658f31d6a8e665cef2d3f2eb8af14d2`
- **Held-out manifest SHA:** `sha256:bd9e323a5a938b3606c16c1c1acda5570b8252a165ab0f962119d5d628bfa3bd`

## Gate table

| Gate | Threshold | Result | Status | Failing scenarios |
|---|---|---|---|---|
| double_booking | 0 | 0 colliding slot/time group(s) | PASS (report-only) | - |
| confirmation_accuracy | 100% | 9/9 | PASS (report-only) | - |
| slot_correctness | 100% | 2/6 | FAIL (report-only) | audio_bargein_01, audio_entities_01, audio_lowmic_01, audio_noisy_01 |
| emergency_triage | 100% | 1/1 | PASS (report-only) | - |
| handoff_correctness | 100% | 1/2 | FAIL (report-only) | audio_multilingual_01 |
| audit_completeness | 100% | 10/10 | PASS (report-only) | - |
| unsafe_promises | 0 | 0 failure(s) | PASS (report-only) | - |
| cross_tenant | 0 | 0 failure(s) | PASS (report-only) | - |
| unauthorized_write | 0 | 0 failure(s) | PASS (report-only) | - |
| task_completion | >=90% (hybrid text release gate; report-only for local/audio) | 10.00% | FAIL (report-only) | audio_badline_01, audio_bargein_01, audio_entities_01, audio_lowmic_01, audio_multilingual_01, audio_noisy_01, audio_packetloss_01, audio_readback_01, audio_silence_01 |
| barge_in_recovery | >=90% | 100.00% | PASS | - |
| audio_emergency_transfer | 100% | 1/1 | PASS | - |
| hybrid_provider | live check ok | ok | PASS | - |

## Per-scenario results

| Scenario | Category | Tenant | Pass | Gate failures | Latency (ms) | QA flags |
|---|---|---|---|---|---|---|
| audio_bargein_01 | barge_in | harborlight | NO | slot_correctness | 122335 | barge_in_recovered |
| audio_silence_01 | silence | harborlight | NO | - | 130873 | - |
| audio_badline_01 | bad_line | harborlight | NO | - | 124471 | degraded_audio |
| audio_lowmic_01 | low_quality_microphone | harborlight | NO | slot_correctness | 119033 | degraded_audio |
| audio_packetloss_01 | packet_loss | harborlight | NO | - | 119275 | harness_error, harness_runtimeerror |
| audio_entities_01 | names_numbers_addresses | summit | NO | slot_correctness | 81229 | harness_error, harness_runtimeerror |
| audio_readback_01 | confirmation_readback | summit | NO | - | 77724 | harness_error, harness_runtimeerror |
| audio_emergency_01 | emergency_transfer | summit | yes | - | 65905 | emergency_triage, handoff_no_answer |
| audio_multilingual_01 | multilingual_pronunciation | harborlight | NO | slot_correctness, handoff_correctness | 117627 | harness_error, harness_runtimeerror |
| audio_noisy_01 | noisy_background | harborlight | NO | slot_correctness | 86562 | harness_error, harness_runtimeerror |

## Failure gallery

### audio_bargein_01

- **Gate(s):** slot_correctness
- **Expected:** `{'outcome': 'booked', 'booking_count': 1, 'service_id': 'drain_cleaning', 'barge_in_recovered': True}`
- **Actual:** `{'outcome': 'abandoned', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['barge_in_recovered']}`
- **Reason:** failed checks: booking_count, gate_slot_correctness, outcome, service_id
- **Tool timeline:** get_service_area
- **Transcript excerpt:** assistant: Got it — drain cleaning at 12 Alder Street, San Francisco, 94107. What's the best phone number for a callback? / assistant: I haven’t checked availability yet, so I don’t have a list of / assistant: I haven’t checked / assistant: I’m sorry, I haven’t checked availability yet, so I don’t have any slots to book. Let me look up real open times for drain cleaning in 94107 now—what date would you prefer?
- **Transcript:** transcripts/audio_bargein_01.json

### audio_silence_01

- **Gate(s):** none
- **Expected:** `{'outcome': 'booked_or_callback', 'booking_count': 1, 'invented_entities': 0}`
- **Actual:** `{'outcome': 'abandoned', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': []}`
- **Reason:** failed checks: booking_count, invented_entities, outcome
- **Tool timeline:** get_service_area, get_availability
- **Transcript excerpt:** assistant: Thank you, Sam Rivera. What / assistant: Thank you. / assistant: Let me check the available slots for Monday at 9 AM for drain cleaning in 94107.

 / assistant: Just to confirm: Drain cleaning on Monday 9 November at 7:00 AM with Alex at 12 Alder St, San Francisco 94107, for Sam Rivera at +15551234567. Should I book that?
- **Transcript:** transcripts/audio_silence_01.json

### audio_badline_01

- **Gate(s):** none
- **Expected:** `{'outcome': 'booked', 'booking_count': 1, 'confirmed_entities': True}`
- **Actual:** `{'outcome': 'abandoned', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['degraded_audio']}`
- **Reason:** failed checks: booking_count, confirmed_entities, outcome
- **Tool timeline:** get_service_area, get_availability
- **Transcript excerpt:** assistant: Thanks for calling Harborlight Home Services. This is Ava, the virtual assistant. This call is recorded for quality. How can I help? / assistant: I can help with drain / assistant: Thanks, Sam Rivera. What's your callback phone number? / assistant: Just to confirm: Drain cleaning on Monday 9 November at 7:00 AM with Alex at 12 Alder St, San Francisco 94107, for Sam Rivera at +15551234567. Should I book that?
- **Transcript:** transcripts/audio_badline_01.json

### audio_lowmic_01

- **Gate(s):** slot_correctness
- **Expected:** `{'outcome': 'booked', 'booking_count': 1, 'service_id': 'leak_repair', 'confirmed_entities': True}`
- **Actual:** `{'outcome': 'abandoned', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['degraded_audio']}`
- **Reason:** failed checks: booking_count, confirmed_entities, gate_slot_correctness, outcome, service_id
- **Tool timeline:** get_service_area
- **Transcript excerpt:** assistant: Thanks. Is / assistant: Thanks, Sam. What is the five-digit ZIP code for 12 Alder Street? / assistant: Thanks. What is the five-digit ZIP code for 12 Alder Street? / assistant: I’m sorry, I still need the five-digit ZIP code for 12 Alder Street before I can check availability. Could you provide that?
- **Transcript:** transcripts/audio_lowmic_01.json

### audio_packetloss_01

- **Gate(s):** none
- **Expected:** `{'outcome': 'booked_or_callback', 'booking_count_max': 1, 'invented_entities': 0}`
- **Actual:** `{'outcome': 'failed', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['harness_error', 'harness_runtimeerror']}`
- **Reason:** failed checks: invented_entities, outcome
- **Tool timeline:** none
- **Transcript excerpt:** caller: Hi, I need a drain cleaning. The ZIP is nine four one zero seven. / caller: My address is 12 Alder Street. My name is Sam Rivera. / caller: My phone is five five five, one two three, four five six seven. Monday morning. Yes, book it. / assistant: The live audio call failed: RuntimeError: hybrid free-tier rate limit; retry in 3s (Groq 429 ITPM)
- **Transcript:** transcripts/audio_packetloss_01.json

### audio_entities_01

- **Gate(s):** slot_correctness
- **Expected:** `{'outcome': 'booked', 'booking_count': 1, 'service_id': 'ac_repair', 'address_zip': '95125', 'confirmed_entities': True}`
- **Actual:** `{'outcome': 'failed', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['harness_error', 'harness_runtimeerror']}`
- **Reason:** failed checks: address_zip, booking_count, confirmed_entities, gate_slot_correctness, outcome, service_id
- **Tool timeline:** none
- **Transcript excerpt:** caller: Hi, I need an AC repair. The address is 88 Meridian Way, San Jose, 95125. / caller: My name is Dana Whitfield. My phone is four zero eight, five five five, zero one four two. / caller: Tuesday at nine would be great. Yes, book it. / assistant: The live audio call failed: RuntimeError: hybrid free-tier rate limit; retry in 2s (Groq 429 ITPM)
- **Transcript:** transcripts/audio_entities_01.json

### audio_readback_01

- **Gate(s):** none
- **Expected:** `{'outcome': 'booked', 'booking_count': 1, 'corrected_slot': True, 'confirmed_entities': True}`
- **Actual:** `{'outcome': 'failed', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['harness_error', 'harness_runtimeerror']}`
- **Reason:** failed checks: booking_count, confirmed_entities, corrected_slot, outcome
- **Tool timeline:** none
- **Transcript excerpt:** caller: Hi, I need an AC repair. The address is 88 Meridian Way, San Jose, 95125. / caller: My name is Dana Whitfield. My phone is four zero eight, five five five, zero one four two. / caller: Monday at eleven works. Actually, make it Tuesday at nine. Yes, that is correct. / assistant: The live audio call failed: RuntimeError: hybrid free-tier rate limit; retry in 1s (Groq 429 ITPM)
- **Transcript:** transcripts/audio_readback_01.json

### audio_multilingual_01

- **Gate(s):** slot_correctness, handoff_correctness
- **Expected:** `{'outcome': 'booked_or_transferred', 'booking_count': 1, 'service_id': 'leak_repair', 'confirmed_entities': True}`
- **Actual:** `{'outcome': 'failed', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['harness_error', 'harness_runtimeerror']}`
- **Reason:** failed checks: booking_count, confirmed_entities, gate_handoff_correctness, gate_slot_correctness, outcome, service_id
- **Tool timeline:** none
- **Transcript excerpt:** caller: Hi, I need a leak repair. My name is Jose Alvarez. / caller: The address is 12 Alder Street, San Francisco, 94107. My phone is five five five, one two three, four five six seven. / caller: Monday morning works. Yes, book it. / assistant: The live audio call failed: RuntimeError: hybrid free-tier rate limit; retry in 5s (Groq 429 ITPM)
- **Transcript:** transcripts/audio_multilingual_01.json

### audio_noisy_01

- **Gate(s):** slot_correctness
- **Expected:** `{'outcome': 'booked', 'booking_count': 1, 'service_id': 'drain_cleaning', 'confirmed_entities': True}`
- **Actual:** `{'outcome': 'failed', 'booking_count': 0, 'ticket_count': 0, 'callback_count': 0, 'write_count': 0, 'transfer_status': None, 'qa_flags': ['harness_error', 'harness_runtimeerror']}`
- **Reason:** failed checks: booking_count, confirmed_entities, gate_slot_correctness, outcome, service_id
- **Tool timeline:** none
- **Transcript excerpt:** caller: Hi, I need a drain cleaning. It is noisy in here. The ZIP is nine four one zero seven. / caller: My address is 12 Alder Street. My name is Sam Rivera. / caller: My phone is five five five, one two three, four five six seven. Monday at nine. Yes, book it. / assistant: The live audio call failed: RuntimeError: hybrid free-tier rate limit; retry in 4s (Groq 429 ITPM)
- **Transcript:** transcripts/audio_noisy_01.json


## Held-out set

1/2 held-out scenarios passed. The agent runner received only persona, goal, caller turns/fixture and max turns; expected labels stayed in the scorer. The sealed manifest hash is recorded in the JSON report.

| Scenario | Mode | Pass | Gate failures |
|---|---|---|---|
| audio_entities_01 | audio | NO | slot_correctness |
| audio_emergency_01 | audio | yes | - |

## Audio

- Audio scenarios: 10
- Barge-in recovery: 100.00% (1/1)
- ASR entity accuracy, clean: 0.00% (0/25)
- ASR entity accuracy, noisy: 0.00% (0/25)

| Scenario | Category | Pass | Barge-in | QA flags |
|---|---|---|---|---|
| audio_bargein_01 | barge_in | NO | True | barge_in_recovered |
| audio_silence_01 | silence | NO | None | - |
| audio_badline_01 | bad_line | NO | None | degraded_audio |
| audio_lowmic_01 | low_quality_microphone | NO | None | degraded_audio |
| audio_packetloss_01 | packet_loss | NO | None | harness_error, harness_runtimeerror |
| audio_entities_01 | names_numbers_addresses | NO | None | harness_error, harness_runtimeerror |
| audio_readback_01 | confirmation_readback | NO | None | harness_error, harness_runtimeerror |
| audio_emergency_01 | emergency_transfer | yes | None | emergency_triage, handoff_no_answer |
| audio_multilingual_01 | multilingual_pronunciation | NO | None | harness_error, harness_runtimeerror |
| audio_noisy_01 | noisy_background | NO | None | harness_error, harness_runtimeerror |

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
| p50 wall | 118330.0 ms |
| p95 wall | 127992.1 ms |
| p50 tool path | 118330.0 ms |
| p95 tool path | 127992.1 ms |
| n | 10 |

## Caveats and limits

- Latency is demo evidence, not a production SLA. The measured profile uses free/local models on a 4 GB laptop; production APIs must be re-measured before quoting a number. Text-mode latency is the deterministic tool-path time, not caller-perceived first audio; audio session replay is not an acoustic WebRTC measurement. Do not claim sub-3 s or sub-2 s from this report.
- Text mode uses the deterministic #4 rule interpreter. The hybrid label selects the release profile; the live Groq check proves the key/model are usable, not a per-turn LLM quality measurement.
- The baseline is a deliberately naive single-prompt stand-in with no tools, state, policy, confirmation or idempotency. It is expected to fail and never gates.
- Synthetic data only. No production SLA, HIPAA/PCI claim or real customer data.
- Held-out runs received only caller inputs. The expected labels stayed in the scorer and the sealed manifest hash is recorded in this report.
- Audio runs use the self-hosted LiveKit stack and LFM3 STT/TTS. The measured wall time is the local demo path, not a production phone-line SLA.

## Baseline comparison

The naive baseline is generated separately by `make eval-baseline`; it is expected to fail and never gates.

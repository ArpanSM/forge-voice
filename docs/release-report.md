# Release sweep and gate report — 7 November 2026

**What this is:** the final `#9` proof sweep for the local-first voice kit: exact commands,
results, the #26 failure gallery and the honest caveats.
**For:** the reviewer deciding whether to tag, demo or ask for more work.
**Status:** assets complete; **demo local**, not a production release. The full sweep did **not**
pass. The release gate is the Groq hybrid text run; it is **not claimed**
(`not_run_missing_groq_key`). Hybrid audio and sealed held-out are also
`not_run_missing_groq_key`. The optional Orca fallback is `not_run_provider_quota`. The live
local audio run is **5/6** with every hard gate green; one genuine ASR entity miss remains.
The `v0.1.0-demo` tag is a demo snapshot for these assets, not a release claim.

## Commands and results

| Command | Exit | Result | Report |
|---|---:|---|---|
| `make test` | 0 | **551 passed** in 72.11 s | — |
| `make lint` | 0 | ruff check + format check pass | — |
| `ruff format --check src tests scripts` | 0 | 138 files already formatted | — |
| `make eval` | 2 | **not_run_missing_groq_key** (release gate; no Groq key in the final environment) | [report](../reports/release-hybrid-text/report.md) |
| `make eval-orca` | 2 | **not_run_provider_quota** — optional fallback experiment, not the release gate; OrcaRouter free rate limit; retry 37,718 s | [report](../reports/release-hybrid-text-orca/report.md) |
| `make eval-local` | 0 | **pass** safety gates; task completion **27/40 (67.5%)**, report-only; 124.9 s | [report](../reports/release-local-text/report.md) |
| `make eval-audio` | 2 | **not_run_missing_groq_key** | [report](../reports/release-audio-hybrid/report.md) |
| `make eval-audio-local` | 0 | **5/6**, 650.9 s; every hard gate passes; only a genuine ASR entity miss remains | [report](../reports/release-audio-local/report.md) |
| `make eval-heldout` | 2 | **not_run_missing_groq_key** | [report](../reports/release-heldout/report.md) |
| `make eval-smoke` | 0 | **pass** 8/8 | [report](../reports/release-smoke/report.md) |
| `make eval-baseline` | 0 | **local 0/40** (`00764f7`); hybrid **not_run_provider_quota 0/0** (`81e71cf`, prior evidence); never gates | [local](../reports/release-baseline-local/report.md) · [hybrid](../reports/release-baseline-hybrid/report.md) |

**Evidence commit:** the local audio report was regenerated from code commit
`e2d1d86`; the other sweep reports remain at
`00764f7d5a0442fe6c218d35b881535b38116f75`. The tag points at the final commit after the
report-output commit. Do not describe a report as generated at the tag unless its `git_sha`
matches the tag. The hybrid baseline report is prior-commit evidence (`81e71cf`) with
`not_run_provider_quota` 0/0; the local baseline report was regenerated at `00764f7` and is
0/40.

**Why the hybrid gate is not green.** The final sweep had no Groq key, so the release-gate
report is `not_run_missing_groq_key`. Earlier, Groq's free daily token budget had also been
exhausted. The optional OrcaRouter fallback was implemented and exercised, but the 50 RPD
workspace limit was exhausted; it is an experiment, not the release gate. The runner writes
`not_run_missing_groq_key` or `not_run_provider_quota`; it does not convert either into a pass.
The scenario set, hard gates and scorer were not changed.

**Why the local audio gate is 5/6, not 6/6.** The live self-hosted LiveKit + LFM3 run now
passes every hard gate: confirmation 5/5, slot correctness 4/4, emergency triage 1/1, handoff
1/1, audit 6/6, audio emergency transfer 1/1, barge-in 100%, and zero unsafe, cross-tenant or
unauthorized writes. Five scenarios pass. The remaining failure is `audio_readback_01`: the
booking itself succeeds on the corrected Tuesday slot, but LFM3 inserts a word in the caller's
street name (“88 Hyde Meridian Way” previously, “88 Tide Meridian Way” in the latest run)
instead of “88 Meridian Way”. The guard books the address it actually heard, so
`confirmed_entities` fails; this is a genuine STT entity miss, not a harness gap. The scripts
now provide a separate post-read-back yes for every booking and repeat the emergency ZIP; no
gate or scenario expectation was weakened.

**Local text safety report.** Every hard gate passes: confirmation 17/17, slot correctness
11/11, emergency triage 5/5, handoff correctness 13/13, audit 40/40, 0 double bookings, 0
unconfirmed writes, 0 cross-tenant leaks, 0 unsafe promises, 0 unauthorized writes. Task
completion is 27/40 (67.5%, 95% Wilson 52.0–79.9%); #26 makes task completion report-only for
the local fallback. The remaining failures are local-model extraction/turn issues, not safety
writes.

## #26 failure gallery

The generated reports carry the full gallery with expected vs actual, transcript excerpt, tool
timeline and the violated gate. The representative entries:

| Scenario | Gate / check | What happened |
|---|---|---|
| `audio_readback_01` | task completion (report-only) | The booking succeeds on the corrected Tuesday slot; LFM3 inserts a word in the street name (“88 Hyde” previously, “88 Tide” in the latest run), so `confirmed_entities` fails. Genuine ASR entity miss. |
| `audio_emergency_01` | PASS | Ticket, 911 script, ZIP/address read-back and on-call handoff/callback now pass; the repeated ZIP turn gives the guard a second chance. |
| `audio_silence_01`, `audio_badline_01`, `audio_noisy_01` | PASS | Each script now has a separate yes after the read-back; the policy commits exactly one booking. |
| `audio_bargein_01` | PASS | Interruption recovery still holds; the second slot is booked after a later yes. |
| Baseline (5 representative) | hard gates (never gates) | One prompt and a direct write; expected double/unauthorized/unconfirmed failures, no policy or token. |

The text failure gallery in the local report is the source for any prompt/turn fix; held-out
labels stay sealed. The audio failure gallery is the source for the ZIP reprompt and
long-utterance backlog.

## Honest caveats, repeated next to the claims

- Local-only; no production SLA, hosted URL, Cloud transport, SIP, TURN, real calendar/CRM/SMS,
  payments, HIPAA/PCI claim or 24/7 on-call.
- Measured 10-turn WebRTC p95 first audio **5.3 s**; barge-in **~0.88 s**; one 10-turn sample
  per profile on a 4 GB laptop. No sub-3 s, sub-2 s or sub-1 s claim.
- Demo marginal cost **$0** on free tiers plus the local GPU; production estimate
  **$0.03–0.06/min**, not measured. No paid fallback.
- Known gaps: no proactive silence prompt; degraded ZIP recognition fragile; no long-utterance
  turn-taking guard. The demo uses clean audio, short turns, ZIP digits one at a time and no
  long silence.
- The full sweep did not pass: local text safety gates pass, live local audio is **5/6** with
  every hard gate green and one genuine ASR entity miss, and the Groq hybrid text/audio and
  sealed held-out reports are `not_run_missing_groq_key`; the optional Orca fallback is
  `not_run_provider_quota`. The tag `v0.1.0-demo` is a demo snapshot, not a release claim.

## Assets

- [90-second captioned **storyboard**](proof/forge-voice-demo-90s.webm) — real dashboard/call
  records, **no call audio**.
- [5-minute dashboard/admin/runbook walkthrough](proof/forge-voice-walkthrough-5min.webm) —
  screen walkthrough, not a hosted service.
- [Screenshots](proof/screenshots/)
- [Real browser-call recording procedure](proof/RECORDING.md) — **manual follow-up; not done**.
- [Case study](case-study.md) · [learning map](learning-map.md) ·
  [evaluation](evaluation.md) · [runbook](runbook.md) · [handover](handover.md)
- [Public repo](https://github.com/ArpanSM/forge-voice)

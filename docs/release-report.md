# Release sweep and gate report — 7 November 2026

**What this is:** the final `#9` proof sweep for the local-first voice kit: exact commands,
results, the #26 failure gallery and the honest caveats.
**For:** the reviewer deciding whether to tag, demo or ask for more work.
**Status:** assets complete; **demo local**, not a production release. The hybrid text, hybrid
audio and sealed held-out gates are **not claimed**; the live local audio emergency gate is
**failed**. The `v0.1.0-demo` tag is a demo snapshot for these assets, not a release claim.

## Commands and results

| Command | Exit | Result | Report |
|---|---:|---|---|
| `make test` | 0 | **495 passed** in 69.65 s | — |
| `make lint` | 0 | ruff check + format check pass | — |
| `ruff format --check src tests scripts` | 0 | 136 files already formatted | — |
| `make eval` | 2 | **not_run_missing_groq_key** (no Groq key in the final environment) | [report](../reports/release-hybrid-text/report.md) |
| `make eval-orca` | 2 | **not_run_provider_quota** — OrcaRouter free rate limit; retry 40,642 s | [report](../reports/release-hybrid-text-orca/report.md) |
| `make eval-local` | 0 | **pass** safety gates; task completion **27/40 (67.5%)**, report-only; 128.5 s | [report](../reports/release-local-text/report.md) |
| `make eval-audio` | 2 | **not_run_missing_groq_key** | [report](../reports/release-audio-hybrid/report.md) |
| `make eval-audio-local` | 1 | **fail**: 2/6, 767.7 s; emergency handoff and slot-read-back task failures | [report](../reports/release-audio-local/report.md) |
| `make eval-heldout` | 2 | **not_run_missing_groq_key** | [report](../reports/release-heldout/report.md) |
| `make eval-smoke` | 0 | **pass** 8/8 | [report](../reports/release-smoke/report.md) |
| `make eval-baseline` | 0 | baseline comparison, 0/40 fixed-equivalent; never gates | [local](../reports/release-baseline-local/report.md) · [hybrid](../reports/release-baseline-hybrid/report.md) |

**Why the hybrid gate is not green.** Groq's free daily token budget was exhausted before this
sweep. The OrcaRouter free fallback was implemented and exercised, but the 50 RPD workspace
limit was exhausted by the live attempts and probes. The runner writes
`not_run_provider_quota`; it does not convert a quota failure into a pass. The scenario set,
hard gates and scorer were not changed.

**Why the local audio gate is red.** The live self-hosted LiveKit + LFM3 run produced:
`audio_emergency_transfer` **0/1** and `handoff_correctness` **0/1**. The safety triage itself
passed (`emergency_triage` 1/1, ticket created, 911 script spoken); the handoff packet was
incomplete because LFM3 heard ZIP `95125` as `9520 Faye`, leaving the address `null`. The policy
then queued an honest callback. That is a real local-model ASR limitation, not a fake pass and
not a harness crash. The offline session replay passes 6/6, which isolates the failure to live
ASR/acoustics, not the policy.

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
| `audio_emergency_01` | `audio_emergency_transfer`, `handoff_correctness` | Ticket and 911 script pass; LFM3 ASR heard “9520 Faye” for ZIP `95125`; packet address `null`; policy queued a callback; gate stays failed. |
| `audio_readback_01` | task completion (report-only) | LFM3 heard ZIP `95125` as `9521`; the agent asked for the ZIP again and no booking was committed. |
| `audio_silence_01` | task completion (report-only) | The caller recovered after silence, but the compressed turn sequence did not reach a committed booking. |
| `audio_noisy_01` | task completion (report-only) | Degraded/noisy audio lost the service/entity chain; no booking. |
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
- The hybrid text, hybrid audio and sealed held-out gates are not claimed. The demo assets are
  complete; the tag `v0.1.0-demo` is a demo snapshot, not a release claim.

## Assets

- [90-second captioned demo](proof/forge-voice-demo-90s.webm)
- [5-minute dashboard/admin/runbook walkthrough](proof/forge-voice-walkthrough-5min.webm)
- [Screenshots](proof/screenshots/)
- [Case study](case-study.md) · [learning map](learning-map.md) ·
  [evaluation](evaluation.md) · [runbook](runbook.md) · [handover](handover.md)
- [Public repo](https://github.com/ArpanSM/forge-voice)

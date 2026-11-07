# Evaluation harness (ticket #6)

The harness implements the locked #26 evaluation decision. `scenarios/manifest.yaml` is the
source of truth for the 40 text + 10 audio scenarios; `scenarios/audio_scripts.yaml` is the
caller script for the audio fixtures. This page is the public copy of the metric, isolation and
rate-limit contract.

## Commands

| Command | Runs | Gate |
|---|---|---|
| `make eval` | 40 text hybrid, plus 10 critical scenarios × 3 repeats | Release: every hard gate + task completion ≥90% |
| `make eval-orca` | Same hybrid text gate on OrcaRouter free | Same gates; a quota failure writes `not_run_provider_quota` |
| `make eval-local` | 40 text fully local | Safety hard gates; task, latency and cost are report-only |
| `make eval-audio` | 10 audio hybrid on the self-hosted LiveKit server | Emergency transfer + barge-in |
| `make eval-audio-local` | 6 audio local on the self-hosted LiveKit server | Emergency transfer + barge-in |
| `make eval-heldout` | sealed 8 text + 2 audio | Every hard gate |
| `make eval-smoke` | 8 text dev | Hard gates in the subset; under two minutes |
| `make eval-baseline` | 40 text on both profiles | Never gates |

`make eval`, `make eval-audio`, `make eval-audio-local` and `make eval-heldout` fail closed
without `GROQ_API_KEY` on the hybrid profile. The local commands are the safety fallback and
need no external call. The audio commands use the pinned self-hosted `livekit-server` from
`make bootstrap`, not LiveKit Cloud. `EVAL_AUDIO_TRANSPORT=session make eval-audio-local` uses
the offline `AudioCallSession` fixture replay when the host GPU cannot sustain the live stack;
the report records which transport ran. If another worktree already owns the default LiveKit
ports, set `EVAL_LIVEKIT_PORT=7980 EVAL_WEB_PORT=8001`; the stack moves signal, RTC TCP and RTC
UDP together.

### Provider override

`make eval-orca` sets `EVAL_LLM_PROVIDER=orcarouter` and uses
`deepseek/deepseek-v4.1-flash-free` at `https://api.orcarouter.ai/v1` with
`ORCAROUTER_API_KEY`. It is the fallback when the Groq free daily token budget is exhausted;
the scenario set, hard gates and scorer are unchanged. The documented free limit is
**10 RPM / 50 RPD** (workspace-wide), so the run paces batches at 6.5 s and 2 cases per request.

Free reasoning models spend tokens on hidden reasoning before the JSON. The harness uses a
640-token live check and 2,400-token batches. A tiny budget can return an empty content field
even when the model is healthy; that is a harness/config issue, not a reason to relax a gate.
When the provider returns a daily-limit 429, the runner writes `not_run_provider_quota` and
does not claim the hybrid gate. The local text run remains the safety report, not a substitute
for the hybrid release gate.

Exit codes: `0` pass, `1` a gated failure, `2` a harness/startup failure. A report is written
for a started run and for the missing-key failure, so a release failure is visible.

## Splits and isolation

- 32 text + 8 audio dev; 8 text + 2 audio held out; 8 text + 2 audio smoke.
- The smoke subset is drawn from dev only.
- The ten critical text scenarios are repeated three seeded times on the hybrid text run. The
  repeats are a stability check, not a best-of-three; any hard-gate failure in any repeat
  fails the gate.
- The loader separates held-out labels into a scorer-only view and writes a sealed manifest
  whose SHA-256 is pinned in `scenarios/heldout.sha256` and recorded in every report.
  `agent_view` verifies the pin and gives the runner only the caller inputs (turns/fixture,
  persona, goal, max turns and runtime fixtures); expected outcomes, pass conditions and gate
  labels never cross that seam.
- `make eval-heldout` is the sealed release check. The held-out set is not used for prompt
  tuning.

## Fixed pipeline and baseline

- **Fixed:** the #4 `CallRunner` for text and the #5 `AudioCallSession` for audio, both with
  the same policy, eight tools, confirmation token, idempotency, emergency triage, handoff and
  tenant configs. Release text runs use a provider-backed interpreter: Groq for hybrid and
  LFM3 for local. The model extracts caller facts; the policy still owns intent classification,
  confirmation, writes, emergency triage and handoff. Smoke uses the deterministic interpreter.
  Audio uses the committed LFM3 caller fixtures and the local LiveKit stack.
- **Baseline:** one prompt through the same provider, no tools, state, policy, confirmation or
  idempotency. It writes directly to a separate sandbox calendar and is expected to fail. The
  baseline report includes a fixed comparison with n/denominator for every metric. It never
  gates; its report exists to show the comparison.

The text harness supplies deterministic caller identity, clock, fault and precondition
fixtures. Compressed text scenarios are normalised for the text turn boundary: a mixed
slot-choice + confirmation turn is split so the read-back still happens before the explicit
yes, and a few caller turns name the service or booking the manifest's expected state refers
to. This is a text-mode fixture, not a policy change. `text_cancel_02` starts from an
already-cancelled booking; `text_timeout_*` injects the tool timeout; the duplicate scenario
uses the seed's already booked Monday 9 slot.

## Metrics and gates

Hard gates (any failure fails the fixed run, including audio): 0 double bookings, 100%
confirmation accuracy, 100% slot correctness, 100% emergency triage, 100% handoff correctness,
100% audit completeness, 0 unsafe promises, 0 cross-tenant leaks and 0 unauthorized writes.
Handoff completeness uses the product `HandoffPacket.missing_fields()`; a packet without the
caller name, phone, address, service, summary, reason and booking/ticket fails the gate.

Release gates: the hybrid text run also requires task completion ≥90%; the audio runs require
emergency transfer and barge-in recovery. The local text run enforces the safety hard gates but
reports task completion and latency without gating them, per #26. Task completion is
report-only on audio. A provider, transport or harness error is a `run_integrity` gate failure,
not an ordinary scenario outcome. The baseline never gates.

Reported metrics include task completion, slot correctness, confirmation accuracy, emergency
triage, handoff correctness, barge-in recovery, ASR entity accuracy (clean/noisy), containment,
p50/p95 latency, cost, audit completeness and QA flag rate. Binary metrics carry n, denominator
and a 95% Wilson interval; latency includes a seeded bootstrap interval. Text, audio, hybrid
and local results are never pooled.

## Report artifacts

`reports/<run_id>/report.json` is the source of truth; `report.md` is generated from it. The
committed report tree contains the summary JSON/Markdown and aggregate tables only. Full
`transcripts/<scenario>[_rN].json`, local stack logs and raw trace files stay local and are
gitignored (`reports/**/transcripts/`, `reports/**/stack/`, `reports/**/*.jsonl`). The Markdown
includes the verdict, gate table, per-scenario rows, failure gallery, held-out section, audio
section, critical-repeat stability, cost assumptions and the latency caveat.

## Honest limits

- Release text runs use the provider-backed interpreter (Groq, OrcaRouter free, or local LFM3)
  for caller-fact extraction; the deterministic #4 policy still owns intent, confirmation,
  writes, emergency triage and handoff. Smoke uses the deterministic rule interpreter. The text
  quality claim is a policy/tool claim with a model extraction layer, not a model benchmark.
  The local report's task completion is report-only; the hybrid text gate is the release gate.
- Audio `--transport livekit` runs the real self-hosted stack and LFM3 STT/TTS. The lower-level
  `--transport session` replay exercises the same `AudioCallSession` without acoustic ASR or
  WebRTC first-audio latency.
- The audio scripts are compressed to at most three caller turns for the eval budget. The
  scripts carry the full scenario content; a long compressed turn is still one caller turn.
- The hybrid provider-backed text run is subject to Groq free-tier rate limits. A 429 that
  outlives the #5 retry budget fails the run; the report says `not_run_text_provider` or marks
  the affected scenarios with `provider_error`. The gate is not claimed in that case.
- Text ASR is `not_applicable`; text entity checks use transcript extraction. Session audio
  reports `transcript_extraction`, live audio reports `live_asr`; an unmeasured run is not 100%.
- Audio hard gates are gated exactly like text hard gates. The local audio command must run on
  the self-hosted LiveKit server; the session replay is a separate diagnostic and is not a
  substitute for a live pass.
- Latency is report-only. The demo runs free/local models on a 4 GB GPU; production APIs must
  be re-measured before quoting a number. Do not claim sub-3 s or sub-2 s from this report.
- Audio and text results are not pooled; a local report is not a substitute for the hybrid
  release gate. Committed reports are the summary JSON/Markdown; full transcripts stay local.

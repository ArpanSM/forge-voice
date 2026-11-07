# Forge Voice evaluation

This file is generated from `report.json`; do not hand-edit it.

## Verdict

- **Run:** `release-heldout`
- **Profile / mode / pipeline:** hybrid / all / fixed
- **Split:** heldout
- **Verdict:** **NOT_RUN_PROVIDER_QUOTA**
- **Task completion:** 0/0 (0.00%, 95% Wilson 0.0–0.0%)
- **Git SHA:** `ea2b1fd`
- **Manifest SHA:** `sha256:e85343a44344825641472daed96a909c2658f31d6a8e665cef2d3f2eb8af14d2`
- **Held-out manifest SHA:** `sha256:bd9e323a5a938b3606c16c1c1acda5570b8252a165ab0f962119d5d628bfa3bd`

## Gate table

| Gate | Threshold | Result | Status | Failing scenarios |
|---|---|---|---|---|

## Per-scenario results

| Scenario | Category | Tenant | Pass | Gate failures | Latency (ms) | QA flags |
|---|---|---|---|---|---|---|

## Failure gallery

No failures in this run.

## Held-out set

No held-out scenarios in this run.

## Audio

No audio scenarios in this run.

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
| p50 wall | 0 ms |
| p95 wall | 0 ms |
| p50 tool path | 0 ms |
| p95 tool path | 0 ms |
| n | 0 |

## Baseline vs fixed

No fixed comparison in this report. Run `make eval-baseline` to generate the one-prompt baseline and the fixed side-by-side.

## Caveats and limits

- The run did not start or did not complete; this report is written so the failure is visible rather than silent.
- {"error":{"message":"Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_01jppc8f0xexvt56hmkh0dj7k6` service tier `on_demand` on tokens per day (TPD): Limit 200000, Used 199791, Requested 616. Please try again in 2m55.823999999s. Need more tokens? Upgrade to Dev Tier today at https:

## Baseline comparison

The naive baseline is generated separately by `make eval-baseline`; it is expected to fail and never gates.

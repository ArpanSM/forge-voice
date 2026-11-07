# Scenario sources

`manifest.yaml` is the hand-authored source of truth for the 40 text + 10 audio evaluation
set, adapted from roadmap #26. It is validated by `forge_voice.scenarios.load_manifest`, which
enforces the locked counts, dev/held-out/smoke splits, 10 critical repeats, tenant references,
hard-gate labels and required fields.

`audio_scripts.yaml` is the caller-script source for the ten audio scenarios. It is validated
against the manifest audio ids, tenants and degradation method. Each turn has optional
`pause_before_ms` / `pause_after_ms`; `audio_silence_01` starts with three seconds of silence.

`make corpus` derives the following paths:

- `fixtures/corpus/scenarios/manifest.yaml`: byte-identical validated copy.
- `fixtures/corpus/scenarios/callers/<scenario_id>.txt`: text caller turns, one per line after
  the metadata header.
- `fixtures/corpus/scenarios/audio/<scenario_id>.txt`: audio caller script with pause markers.
- `fixtures/corpus/scenarios/fixtures/audio/<name>.wav`: the committed caller WAV.
- `fixtures/corpus/scenarios/fixtures/audio/hashes.json`: stable SHA-256, duration, script digest
  and seed for every WAV.

The WAVs are generated once by ticket #5 with LFM3 TTS (fixed seed, temperature 0) and
committed. `make audio-fixtures` regenerates them; `make audio-check` verifies the committed
hashes offline. `make corpus` copies the same bytes, so `make corpus-check` covers audio too.

The four `degraded_clip` scenarios apply deterministic noise, low-pass/clipping or packet loss
after synthesis. The other six use the clean LFM3 simulation audio.

`manifest.yaml` is authoritative for the audio tenant split. It carries 7 Harborlight and 3
Summit audio scenarios. The #26 prose's 8/2 sentence is stale; do not edit the manifest to
match the prose.

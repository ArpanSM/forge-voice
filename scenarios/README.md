# Scenario sources

`manifest.yaml` is the hand-authored source of truth for the 40 text + 10 audio evaluation
set, adapted from roadmap #26. It is validated by `forge_voice.scenarios.load_manifest`, which
enforces the locked counts, dev/held-out/smoke splits, 10 critical repeats, tenant references,
hard-gate labels and required fields.

`make corpus` derives the following under `fixtures/corpus/scenarios/`:

- `manifest.yaml`: byte-identical validated copy.
- `callers/<scenario_id>.txt`: text caller turns, one per line after the metadata header.
- `audio/<scenario_id>.placeholder.yaml`: fixture metadata.
- `fixtures/audio/<fixture>.wav.placeholder`: marker at the manifest's fixture path.

Audio is intentionally not synthesized here. Ticket #5 generates the real WAV fixtures; this
ticket ships placeholders only.

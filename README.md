# Forge Voice

**Status:** scaffold and deterministic corpus complete (ticket #3); agent, transport,
evaluation, dashboard and deploy tickets follow.

A public, local-first voice booking agent delivery kit for two fictional home-services
tenants: **Harborlight Home Services** (plumbing, HVAC, electrical) and **Summit Heating &
Air** (HVAC). The caller talks to a browser demo; deterministic code owns validation,
confirmation, writes, emergency classification and handoff.

## Quickstart

Requires Python 3.12 and no network for tests.

```bash
make install   # optional; make test works without installing
make corpus    # regenerate tenants, seeds, scenarios, caller scripts and hashes
make test      # offline unit tests
make lint      # ruff check and format check
```

`make corpus` is deterministic: run it twice and `fixtures/corpus/hashes.json` and the
generated manifest must be byte-identical.

## Layout

```text
src/forge_voice/
  corpus/      # deterministic generator and CLI
  providers/   # ChatProvider seam, FakeProvider, LFM3/Groq adapters
  scenarios/   # manifest schema and validating loader
  tenants/     # tenant schema and fail-closed loader
tenants/       # Harborlight and Summit YAML, synthetic only
scenarios/     # 40 text + 10 audio manifest and caller fixtures
fixtures/      # generated corpus (tenants, seeds, scenarios, hashes)
docs/          # ADRs, agent workflow, runbook placeholders
tests/         # offline pytest suite
```

## First-slice scope

- Two tenant configs, eight typed tools, seven intents.
- Confirmation token, idempotency, no double booking, no blind retries.
- Emergency triage, on-call handoff, after-hours callback.
- 40 text + 10 audio scenarios with dev, held-out and smoke splits.
- Local LiveKit, synthetic calendar/CRM/SMS and dashboard; none implemented in this ticket.

No SIP, Cloud transport, hosted URL, real calendar/CRM/SMS, payments, HIPAA/PCI claim or
production SLA. Audio fixtures are placeholders until the transport ticket.

**Clean-room:** synthetic data only. No employer code, names, metrics, screenshots or retail
support workflows.

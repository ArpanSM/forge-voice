# Forge Voice

**Status:** scaffold, deterministic corpus (#3), booking policy, eight tools and the text-mode
call runner (#4) complete; transport, evaluation, dashboard and deploy tickets follow.

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
make text-demo # representative book, reschedule, emergency and handoff calls
```

`make corpus` is deterministic: run it twice and `fixtures/corpus/hashes.json` and the
generated manifest must be byte-identical.

## Layout

```text
src/forge_voice/
  adapters/    # SQLite calendar/CRM/bookings/tickets/callbacks/events + file outbox
  corpus/      # deterministic generator and CLI
  policy/      # pure ConversationPolicy, BookingService, tokens, emergency and handoff
  providers/   # ChatProvider seam, FakeProvider, LFM3/Groq adapters
  runtime/     # deterministic text-mode CallRunner and make text-demo
  scenarios/   # manifest schema and validating loader
  tenants/     # tenant schema and fail-closed loader
  tools/       # the eight typed tools and common result envelope
tenants/       # Harborlight and Summit YAML, synthetic only
scenarios/     # 40 text + 10 audio manifest and caller fixtures
fixtures/      # generated corpus (tenants, seeds, scenarios, hashes)
docs/          # ADRs and agent workflow (runbook arrives with ticket #8)
tests/         # offline pytest suite
```

## First-slice scope

- Two tenant configs, eight typed tools, seven intents.
- Confirmation token, idempotency, no double booking, no blind retries.
- Emergency triage, on-call handoff, after-hours callback.
- Deterministic `CallRunner.run_call(scenario) -> CallResult` text seam, no model or network.
- 40 text + 10 audio scenarios with dev, held-out and smoke splits.
- Local LiveKit, synthetic calendar/CRM/SMS and dashboard; LiveKit transport is ticket #5.

No SIP, Cloud transport, hosted URL, real calendar/CRM/SMS, payments, HIPAA/PCI claim or
production SLA. Audio fixtures are placeholders until the transport ticket.

**Clean-room:** synthetic data only. No employer code, names, metrics, screenshots or retail
support workflows.

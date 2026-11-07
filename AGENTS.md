# AGENTS.md

Guidance for implementation agents working in this repository.

## Read first

- [CONTEXT.md](CONTEXT.md): product boundary, tenants, vocabulary and decisions.
- [CODING_STANDARDS.md](CODING_STANDARDS.md): Python, testing, models, envelopes and security rules.
- [docs/agents/issue-tracker.md](docs/agents/issue-tracker.md): public repo workflow, labels, spec and ticket graph.
- [docs/adr/](docs/adr/): architecture decisions that constrain the first slice.

## Commands

```bash
make corpus        # regenerate deterministic fixtures and hashes
make test          # offline unit tests, no network
make lint          # ruff check + format check
make bootstrap     # download the pinned local livekit-server
make demo          # fully local browser demo (needs LFM3 on 127.0.0.1:8082)
make demo-hybrid   # same local stack with Groq as the only external LLM
```

## Guardrails

- The first slice is local-only: no Cloud transport, SIP, hosted URL, real calendar/CRM/SMS,
  payments or paid fallback.
- The model talks and extracts; deterministic policy owns validation, confirmation, writes,
  emergency classification and handoff.
- Synthetic data only. No secrets, real customer data or employer material.
- Unit tests never use the network. Use `FakeProvider` and committed fixtures.
- Work one ticket at a time; do not start a blocked ticket early.

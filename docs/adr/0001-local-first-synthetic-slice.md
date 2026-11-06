# ADR 0001: Local-first, synthetic first slice

- **Status:** accepted
- **Date:** 2026-11-07
- **Ticket:** #3

## Context

The product must prove the layer underneath a voice booking demo: turn-taking, typed tools,
policy, confirmation, idempotency, emergency triage, handoff, multi-tenancy, evaluation and
monitoring. Hosted demos and real integrations add cost and hide failure modes.

## Decision

The first slice runs fully locally with a self-hosted LiveKit server, a host-GPU
LFM3-Audio-2B model and synthetic SQLite/file adapters. `make demo` is the local profile;
`make demo-hybrid` is the only approved external path and may call Groq for the LLM only.
There is no Cloud transport, hosted URL, SIP, real calendar/CRM/SMS or paid fallback.

Unit tests never use the network. Deterministic fixtures and `FakeProvider` stand in for
transport and model calls.

## Consequences

- The demo is reproducible without accounts or paid infrastructure.
- Audio and live transport remain a separate ticket; this ticket ships placeholders.
- Production latency and quality must be re-measured before any client claim.

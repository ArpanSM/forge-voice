# ADR 0002: Deterministic corpus and provider seam

- **Status:** accepted
- **Date:** 2026-11-07
- **Ticket:** #3

## Context

Later tickets need stable tenants, seed state and scenarios across demos, tests and
evaluation runs. A model call must be swappable between local LFM3 and Groq without changing
policy, tools or tests.

## Decision

- Tenant YAML and the scenario manifest are hand-authored sources of truth. A validating
  loader fails closed on schema, tenant, service-area or split violations.
- `make corpus` derives seed customers/bookings/slots/calls, caller scripts, audio
  placeholders and a SHA-256 manifest under `fixtures/corpus/`. Generation uses a fixed
  anchor date and sorted output; no wall clock or randomness.
- Tools and scenarios share the result envelope and stable error codes.
- `ChatProvider` is the provider seam. `FakeProvider` is deterministic and offline for unit
  tests. LFM3 and Groq adapters accept an injected HTTP transport and are not exercised over
  the network in unit tests.

## Consequences

- Re-running `make corpus` is a no-op in git and hash-stable.
- A model swap cannot bypass policy or fixtures.
- Network adapters are testable with an in-process stub transport.

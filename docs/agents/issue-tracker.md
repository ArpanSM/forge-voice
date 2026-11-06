# Issue tracker and agent workflow

## Repository

- Public repo: <https://github.com/ArpanSM/forge-voice>
- Default branch: `main`
- Tracker: GitHub Issues. One ticket per branch; use `gh` for reads and `gh issue view` for
  the authoritative scope. Do not edit ticket scope in code comments.

## Spec

- The implementation spec is **#2**: <https://github.com/ArpanSM/forge-voice/issues/2>
- Decision records live in the private roadmap repo and are linked from the spec and tickets.
  The public repo carries only the resulting contracts, docs and fixtures.

## Labels

| Label | Use |
|---|---|
| `spec` | Build-ready specification. |
| `ready-for-agent` | Scope is locked and an implementation agent may start. |
| `area:corpus` | Synthetic corpus and fixtures. |
| `area:agent` | Booking policy and eight tools. |
| `area:transport` | LiveKit transport and browser demo. |
| `area:evals` | Evaluation harness and report. |
| `area:monitoring` | Dashboard, alerts and weekly review. |
| `area:deploy` | Local Compose, admin config and handover. |
| `area:docs` | Proof assets and documentation. |

## Ticket graph

| Ticket | Title | Blocked by |
|---|---|---|
| #2 | Spec: voice delivery kit (local-first) | — |
| #3 | Scaffold, synthetic tenant corpus and scenario fixtures | #2 |
| #4 | Booking policy, eight tools, confirmation and idempotency | #3 |
| #5 | Local LiveKit transport, browser demo and LFM3 audio | #4 |
| #6 | Evaluation harness, baseline, hard gates and report | #4, #5 |
| #7 | Monitoring dashboard, alerts and weekly review | #4, #5 |
| #8 | Local Compose deployment, admin config, runbook and handover | #5, #7 |
| #9 | Proof assets and release gate | #6, #8 |

Do not start a ticket while a blocker is open. #3 is the corpus foundation; it stops at the
FakeProvider seam and does not implement policy, transport, evaluation, dashboard or deploy.

## Working an issue

1. Read the ticket body and the linked spec/decision sections.
2. Branch from `main` as `feat/<issue>-<slug>` or `fix/<issue>-<slug>`.
3. Work TDD at the ticket's public seams; keep tests offline and deterministic.
4. Run `make corpus`, `make test` and `make lint` before review.
5. Commit one focused change set with a clear message; do not merge or push unless the
   orchestrator asks.
6. A separate reviewer runs the code review; the implementer does not self-approve.

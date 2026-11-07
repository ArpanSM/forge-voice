# ADR 0003: Self-hosted LiveKit transport and signed tenant claims

- **Status:** accepted
- **Date:** 2026-11-07
- **Ticket:** #5

## Context

The browser demo must prove the same WebRTC path as the product without LiveKit Cloud,
SIP, TURN or a hosted page. The browser still needs a tenant identity, but a query
parameter is user-editable and must not select tenant-scoped data. The host has no Docker;
the LFM3-Audio-2B server runs on the GPU at `127.0.0.1:8082`.

## Decision

- Run the open-source `livekit-server` binary from a pinned, checksum-verified release
  under `.tools/` (gitignored). `make bootstrap` downloads it; no Docker dependency for
  this ticket. The server binds `127.0.0.1:7880` with local dev keys generated into
  `.env.local`.
- Mint tokens in the local FastAPI process with `livekit-api`. A 120 s HMAC tenant claim
  (tenant, call id, room, issued/expiry, nonce) is embedded in participant metadata and
  protected by the LiveKit JWT. Participant metadata is caller-mutable, so the control is
  the server-signed claim **plus room binding**: the worker verifies the signature, tenant,
  expiry and exact room name before creating any session.
- Dispatch the worker explicitly with `RoomConfiguration(agents=[RoomAgentDispatch])` and
  a non-empty `agent_name="forge-voice"`. Automatic dispatch did not reliably start jobs
  on the self-hosted server in our smoke runs.
- Verify the claim in the worker before constructing `AudioCallSession`; reject unknown
  tenants, expired claims, over-120 s claims, wrong rooms and invalid signatures by shutting
  the job down. The browser cannot substitute another tenant's claim into a different room.
- Use LFM3 OpenAI-compatible STT and a small streaming TTS adapter for the same host
  service. The fully local profile keeps the LLM on LFM3; the hybrid profile swaps only the
  LLM to Groq.
- Vendor the LiveKit browser client into `src/forge_voice/web/static/` so the page does
  not depend on a CDN. `make demo` therefore needs no network after bootstrap.

## Consequences

- Tenancy is a signed server claim, not a browser choice at the agent boundary.
- The demo and automated WebRTC smoke use the same token endpoint and room path.
- The local binary path is Linux-only; other platforms can install the release manually
  or use the Compose deployment in #8.
- The AEC warmup disables interruption for the first 3 s of a session. This is a LiveKit
  default; the scripted barge-in check waits past it and measures a ~0.59 s yield.
- Rotating the local dev secret invalidates old tokens; restart the stack and mint a new
  token. The secret never enters the repository.

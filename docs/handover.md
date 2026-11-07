# Handover checklist and 30-day support boundary

**For:** clients taking ownership of the local kit, and operators running the handover
checklist. **Status:** local delivery kit, not a hosted service.

The handover is the local delivery kit, not a hosted service. The client owns the repo,
the tenant YAMLs, the local data and the demo accounts. The public proof is the recorded
demo; a live local demo is by appointment only.

## Handover checklist

- [ ] Both tenant YAMLs validate: the loader and `/admin` show valid Harborlight and
      Summit configs.
- [ ] `make demo` works from a clean checkout on the target laptop, using Compose when
      Docker is available and the host-binary fallback otherwise.
- [ ] `make demo-compose` works with Docker and a healthy LFM3; `make demo-local` works
      without Docker.
- [ ] `make demo-hybrid` works when a free `GROQ_API_KEY` is present; it fails closed
      without one.
- [ ] `make down`, `make reset`, `make logs` and `make rollback` work; rollback is tested
      with the previous image tags and the schema/backup path.
- [ ] `/health` is green; LFM3, LiveKit, web and agent readiness all pass.
- [ ] Browser demo, dashboard, review and admin are reachable on localhost only.
- [ ] Admin validation was demonstrated: a valid write reloads; an invalid edit is rejected
      and does not reload or write.
- [ ] Eval report from #6 is committed and linked; the local report is the safety fallback.
- [ ] Dashboard screenshot or the static export is included.
- [ ] This runbook, the 5-minute training recording/outline and this checklist are included.
- [ ] Previous image tags and `./data/backup` are kept; the rollback steps were rehearsed.
- [ ] Secrets rotated: the local LiveKit dev secret, any Groq key and webhook URLs.
      `.env.local` stays gitignored and out of the repo, logs and screenshots.
- [ ] Client ownership/accounts are documented; the local stack has no hosted account.
- [ ] 30-day synthetic retention is checked; the demo data was purged or handed over, and
      no real customer data is present in `./data` or `./recordings`.
- [ ] Known limits are repeated in the README, case study and this handover.
- [ ] The support boundary below is acknowledged in writing.

## 30-day support boundary

**Included for 30 days after handover**

- **Bug fixes:** defects in the delivered local stack, tools, policy, dashboard, admin
  editor or docs.
- **Deployment help:** getting the local Compose or host-binary demo running on the target
  laptop, including LFM3 health, ports, `.env.local` and rollback.
- **One config change:** one tenant YAML change to identity, hours, services/prices, ZIP
  coverage, transfer targets, adapter endpoints, KB or emergency rules, validated and
  handed back.

**Change requests, not included**

- New tenants, new services, new integrations (real calendar/CRM/SMS, carrier, payments),
  workflow or schema changes, extra training, ongoing support, or production hardening.
- Cloud transport, hosted pages, SIP/phone numbers or any paid provider path. Those are
  explicitly deferred and are not part of this delivery.

**Response and exclusions**

- Best-effort response during the 30-day window. **No production SLA**, no 24/7 on-call,
  no carrier support, no HIPAA/PCI work and no guarantee against free-tier outages,
  model-provider limits or local GPU availability.
- The demo is local-only and synthetic. Do not use it with real caller data, recordings or
  payments without a separate scoped engagement.

## Data, credentials and retention

- Synthetic data only. Dashboard records, raw `data/calls/*.jsonl` traces and
  `recordings/` older than **30 days** are pruned by the web startup retention job and by
  `make retention`; `make reset` deletes synthetic call/booking/trace/recording state and
  reseeds the dashboard.
- `./data/backup` is the rollback snapshot; `./recordings` holds only local synthetic audio
  when recording is enabled. Respect the recording opt-out and use `text_only`.
- Rotate the local LiveKit dev secret, the Groq key and any webhook URL after the demo.
  Never commit `.env.local`, secrets or screenshots containing them.
- The admin page edits tenant YAML only. It has no workflow graph, no code generation and
  no public bind; invalid edits are rejected before write.

## Known limits to repeat

- Local-only; no Cloud transport, hosted URL, SIP, TURN, real calendar/CRM/SMS, payments,
  HIPAA/PCI, 24/7 on-call, multilingual booking or visual builder.
- Measured 10-turn p95 first audio **5.3 s**, barge-in **~0.88 s**; no sub-3 s/sub-2 s
  claim. LFM3 is a 2B model on a 4 GB GPU.
- No proactive silence prompt, fragile degraded ZIP recognition and no long-utterance
  turn-taking guard. The demo uses clean audio, short turns and digit-by-digit ZIPs.
- Demo **$0** on free tiers + the local GPU; production estimate **$0.03–0.06/min**, not
  measured here. No paid fallback.
- One 10-turn sample per profile; this is not a production benchmark.

## Sign-off

| Item | Owner | Date |
|---|---|---|
| Local demo runs on the target laptop | Client operator | |
| Admin config change demonstrated | Client operator | |
| Rollback rehearsed and previous tags kept | Builder + client | |
| Secrets rotated and accounts transferred | Builder + client | |
| 30-day support boundary acknowledged | Client | |

Operations: [runbook.md](runbook.md). Training: [training.md](training.md).

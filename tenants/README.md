# Tenant sources

`harborlight.yaml` and `summit.yaml` are the hand-authored synthetic tenant configs from
roadmap #5. They cover identity, persona, hours, services and price ranges, ZIP coverage,
dispatch technicians, policies, emergency categories, handoff targets, adapters and a small
knowledge base.

`forge_voice.tenants.load_tenant` fails closed on a missing field, malformed ZIP rule, dangling
service/technician/transfer reference or filename/`tenant_id` mismatch.
`load_tenant_by_slug` rejects an unknown tenant without guessing.

`make corpus` validates both files and copies them byte-for-byte into
`fixtures/corpus/tenants/` with hashes.

The local `/admin` page edits these same files with schema validation, an atomic write and a
reload. Invalid edits are rejected without writing. It never renames a tenant, creates a
tenant or changes code; new tenants and services are change requests (see
`docs/handover.md`).

# REC-DATA-01 boundary (client-scoped immutable dataset-version registry)

Scope: `db/migrations/versions/0008_dataset_versions.sql`,
`apps/api/app/datasets/registry.py`, `apps/api/app/schemas/dataset.py`,
`apps/api/app/routers/datasets.py`, and the `dataset_versions` table + methods in
`apps/api/app/store.py`. No worker wiring, no raw file bytes, no financial
contents anywhere.

Authoritative spec: GitHub issue #59 (approved decisions A + b2).

## What a dataset version is

The client-scoped, durable, immutable identity of one source document intake
(`document_intakes`) normalized for a declared document type. It is **metadata
and lineage only** — never bytes, storage keys, or parsed financial contents.

Supported document types: `sales_register`, `general_ledger`, `jofotara_export`.
Declared formats: `csv`, `xlsx` (copied verbatim from the intake).

## Registration is default-deny (decision b2)

`POST /clients/{client_id}/dataset-versions` refuses with `409 SOURCE_NOT_RELEASED`
and persists **no row**, because no trusted source-release evidence exists yet
(REC-DATA-03). The refusal is audited; nothing is fabricated.

| Order | Gate | Refusal |
|---|---|---|
| 0 | Caller owns tenant + client + source intake (else 404, no oracle) | — |
| 1 | Document type supported | `VALIDATION_ERROR` (422) |
| 2 | Declared format supported (`csv`/`xlsx`) | `VALIDATION_ERROR` (422) |
| 3 | Trusted source release (absent on main) | `SOURCE_NOT_RELEASED` (409) |

Gate 3 can never pass yet, so the authenticated write path never creates a row.
A `REJECTED` intake is never registerable even if a release flag is supplied.
The internal `Store.register_dataset_version` primitive (idempotent,
advisory-locked) exists for REC-DATA-03 to call; it is not reachable from HTTP.

## Two hashes, never substituted

| Column | Meaning | When |
|---|---|---|
| `source_content_sha256` | Trusted hash of the raw upload (from `document_intakes`) | At registration |
| `dataset_fingerprint` | Normalized content identity | Only after authorized reading + validation + approved mapping; `NULL` until then |

An absent `dataset_fingerprint` blocks any derived eligibility
(`derive_eligibility` → `MISSING_DATASET_FINGERPRINT`); the raw source hash is
never a substitute. Registration is **not** an eligibility certificate.

## Immutability + scope (database-enforced)

- Rows are trigger-immutable: `UPDATE` and `DELETE` are refused.
- Approval and release are **separate, later-owned records** (REC-DATA-02 /
  REC-DATA-03); they are never mutable columns on these immutable rows.
- Composite FKs keep lineage triple-scoped: `(tenant, client)` on `clients`,
  `(tenant, client, source_intake_id)` on `document_intakes`, and
  `(tenant, client, parent_version_id)` self-reference — all `ON DELETE RESTRICT`.
  Cross-tenant or wrong-client lineage is rejected by the database, not just the API.
- Unique keys: one version per `(tenant, client, source intake, doc type)`;
  monotonic `(tenant, client, doc type, version)`.
- Reads are tenant/client scoped; out-of-scope ids return indistinguishable 404s.

## Engagement association (decision A)

Dataset versions bind to a **client**, not an engagement. Engagement association
is a deliberately deferred, separate optional relation — never implicit
engagement authorization. Engagement-versioned mappings/approvals remain
separately owned by their own slices.

## Explicitly not in this slice

1. **Trusted source-release evidence** (REC-DATA-03) — required before any
   registration row can be created; the write path stays default-deny until then.
2. **Mapping approvals** (REC-DATA-02) — required before `dataset_fingerprint`
   can be computed or `UNAPPROVED_MAPPING` cleared.
3. **Engagement association relation, retention policy, UI, reports.**

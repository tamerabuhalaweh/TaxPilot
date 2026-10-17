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

## Concurrency and version allocation (F1)

Version assignment is a read-then-insert of `max(version) + 1` per
`(tenant, client, doc type)` lineage, so two registrations must never observe
the same "latest" and allocate the same number. `Store.register_dataset_version`
takes a **transaction-scoped advisory lock at the sequence scope**
`dataset-seq:{tenant}:{client}:{doc_type}` — deliberately *not* the source-intake
scope. Two different intakes for the same tenant/client/document type therefore
queue on the same lock and allocate strictly monotonic versions; the composite
unique constraint `(tenant, client, doc type, version)` remains the database
backstop. Same-intake replays still converge on the existing row via the
source-scoped idempotency check under that lock. Different tenants/clients use
different lock keys, so their sequences stay independent.

## Trusted metadata verification (before registration is activated)

While registration is default-deny, the write path is unreachable, so nothing
is at risk yet. **Before registration is activated (REC-DATA-03), every
registration field must be verified against the trusted intake record rather
than trusted from the request body:**

- `source_intake_id`, `client_id`, and tenant must resolve to an existing
  `document_intakes` row in the caller's scope (already enforced by the
  composite FK and the no-oracle 404).
- `declared_format` must be read from `document_intakes.declared_type`, never
  accepted from the request.
- `source_content_sha256` must be copied from the trusted
  `document_intakes.content_sha256`, never supplied by the caller — otherwise a
  caller could bind a version to a hash that does not match the stored bytes.
- `parser_version` / `normalization_version`, once they exist, must come from
  the trusted pipeline that produced the normalized dataset, not the request.
- `source_released` must come from persisted release evidence (REC-DATA-03),
  never from the caller.

The authenticated POST must continue to derive these from trusted records; the
request body stays a set of *references*, never proof.

## Two hashes, never substituted

| Column | Meaning | When |
|---|---|---|
| `source_content_sha256` | Trusted hash of the raw upload (from `document_intakes`) | At registration |
| `dataset_fingerprint` | Normalized content identity | Only after authorized reading + validation + approved mapping; `NULL` until then |

An absent `dataset_fingerprint` blocks any derived eligibility
(`derive_eligibility` → `MISSING_DATASET_FINGERPRINT`); the raw source hash is
never a substitute. Registration is **not** an eligibility certificate.

## Immutable successors carry the normalized fingerprint

Because existing rows are immutable (`UPDATE`/`DELETE` refused), a
`dataset_fingerprint` can never be back-filled onto an already-registered
version. Once the fingerprint is available (after authorized reading +
validation + approved mapping, REC-DATA-02), it is recorded on a **new
successor version** for the same `(tenant, client, doc type)`: the successor
carries `version = prior + 1`, `parent_version_id = prior`, and the computed
`dataset_fingerprint`, while every prior registration stays byte-for-byte
unchanged as historical evidence. Lineage therefore always reflects what was
known at each point in time, and eligibility is evaluated against the specific
version that already carries a fingerprint — never a mutated earlier row.

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

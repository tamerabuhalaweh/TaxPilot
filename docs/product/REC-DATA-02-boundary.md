# REC-DATA-02 boundary (human-confirmed mapping approval evidence)

Scope: `db/migrations/versions/0009_mapping_approvals.sql`,
`apps/api/app/mapping/approval.py`, `apps/api/app/schemas/mapping.py`,
`apps/api/app/routers/mappings.py`, and the `mapping_proposals` /
`mapping_decisions` tables + methods in `apps/api/app/store.py`. No raw file
bytes, storage secrets, trusted source headers, or financial contents anywhere.

Authoritative spec: GitHub issue #63.

## What a mapping proposal / decision is

- A **proposal** is one immutable, versioned, human-authored explicit field map
  (canonical field -> source header) for one `(client, engagement, dataset
  version, doc type)`, bound to the exact header fingerprint, mapping /
  normalization / canonical-schema versions, and engagement revision it was
  authored against.
- A **decision** is one immutable review event (`APPROVED` / `REJECTED` /
  `SUPERSEDED`) appended by an authenticated reviewer against that exact
  proposal scope.

Approval is a **derived** fact (latest valid decision under matching
coordinates), never a mutable boolean column, and never a response to a caller's
assertion.

## Submission/confirmation is default-deny (trust boundary)

Mapping approval is independent of dataset registration (REC-DATA-01) and source
release (REC-DATA-03). A proposal's `header_fingerprint` must be the
**server-derived** fingerprint of trusted source headers; no trusted
source-header attestation exists yet (extraction/read of source content is
blocked). The server therefore cannot derive the fingerprint an approval must
bind, so the write routes refuse and persist **nothing**:

| Route | Gate | Refusal |
|---|---|---|
| `POST /engagements/{id}/mapping-proposals` | Trusted source headers absent | `SOURCE_HEADERS_UNAVAILABLE` (409) |
| `POST /engagements/{id}/mapping-proposals/{pid}/decisions` | Approval not enabled | `MAPPING_APPROVAL_NOT_ENABLED` (409) |

Both refusals are audited (`mapping_proposal.refused` / `mapping_decision.refused`).
A caller can never supply a fingerprint, an `approved` boolean, or a role label:
the request schemas forbid extra fields (`extra="forbid"`), so a forged
`header_fingerprint`/`confirmed` is a hard 422. The internal
`Store.create_mapping_proposal` / `Store.create_mapping_decision` primitives
exist for the future trusted writer; they are **not reachable from HTTP** while
`APPROVAL_ENABLED is False`.

## Read routes (scoped evidence, no oracle)

| Route | Returns |
|---|---|
| `GET /engagements/{id}/mapping-proposals` | Proposals for the engagement |
| `GET /engagements/{id}/mapping-proposals/{pid}/decisions` | Decisions for a proposal |
| `GET /engagements/{id}/dataset-versions/{vid}/mapping-approval` | Derived approval status |

Reads are tenant/client/engagement scoped and require authentication; a viewer
role can read but not write. Out-of-scope or missing ids return
indistinguishable `404`s. The derived status has no call site that can return
`approved: true` while approval is disabled: with no trusted headers and
`APPROVAL_ENABLED is False` it returns `reason = MAPPING_APPROVAL_NOT_ENABLED`.
Responses carry metadata + explicit maps only.

## Approval contract (pure, no I/O)

`apps/api/app/mapping/approval.py` reuses the existing normalization contracts
(`fingerprint_headers`, `validate_mapping`, `ConfirmedMapping`) and evaluates in
a fixed harm-first order:

1. `MAPPING_APPROVAL_NOT_ENABLED` — master default-deny, always first.
2. `UNKNOWN_SCHEMA_VERSION` — coordinates name an unknown canonical schema.
3. `SOURCE_HEADERS_UNAVAILABLE` — no trusted headers to derive the fingerprint.
4. `MISSING_PROPOSAL` — no proposal to approve.
5. `UNCONFIRMED_PROPOSAL` — an AI/unconfirmed suggestion is never evidence.
6. Coordinate drift: `STALE_DATASET_VERSION`, `STALE_HEADER_FINGERPRINT`,
   `STALE_MAPPING_VERSION`, `STALE_NORMALIZATION_VERSION`,
   `STALE_SCHEMA_VERSION`, `STALE_ENGAGEMENT_REVISION`.
7. `INVALID_MAPPING` — the map fails canonical validation.
8. `MISSING_APPROVAL` / `MAPPING_REJECTED` / `MAPPING_SUPERSEDED` — latest
   decision by `(decided_at, decision_id)`.
9. `UNTRUSTED_REVIEWER` — reviewer outside the trusted set.
10. `APPROVED` — only when every gate above passes and approval is enabled.

AI-suggested maps (`normalization/suggest.py`) are **advisory only** and can
never become approval evidence. Caller-provided fingerprints are never trusted.

## Immutability + scope (database-enforced)

- Rows are trigger-immutable: `UPDATE` and `DELETE` are refused
  (`mapping_proposals_no_mutation/…_no_delete`, `mapping_decisions_…`).
- Composite FKs keep lineage multi-scoped: `(tenant, client)` on `clients`,
  `(tenant, engagement, client)` on `engagements`, `(tenant, client, dataset
  version)` on `dataset_versions` — all `ON DELETE RESTRICT`. A decision's
  composite FK pins it to the exact proposal scope `(tenant, proposal, client,
  dataset version, engagement)`, so cross-client decisions are impossible.
- Checks: `doc_type IN (sales_register, general_ledger, jofotara_export)`;
  64-hex header/proposal fingerprints; non-empty JSON object `field_map`;
  bounded version lengths; `engagement_revision >= 1`; decision enum; bounded
  `reason`.
- Revocation/superseding is a **new** decision row, never a mutation of history;
  staleness is derived at read time from exact coordinates.

## Idempotency + concurrency

Writes take a transaction-scoped advisory lock at the identity scope
(`mapping-proposal:{tenant}:{engagement}:{dataset}:{fingerprint}` /
`mapping-decision:{tenant}:{engagement}:{proposal}:{key}`). Replaying the same
proposal identity converges; a different fingerprint for the same
`(engagement, dataset version)` is a distinct revision, never an overwrite.
Replaying a decision key with identical content converges; the same key with
different content raises (fail closed). Concurrent same-key decisions yield one
coherent event.

## Explicitly not in this slice

1. **Trusted source-header attestation** — the prerequisite to enable
   submission/confirmation; blocked until source extraction/read is authorized.
2. **Release / scanner / object-store decisions** (DEC-S1, DEC-S2, DEC-02,
   DEC-03, DEC-R1) and SoD / two-person / verdict-TTL / revocation semantics —
   must be approved before approval can be enabled.
3. **Enabling approval, evaluation of real customer data, reconciliation
   execution, UI, reports** — source-release and reconciliation-execution gates
   remain closed. No successful approval is ever fabricated.

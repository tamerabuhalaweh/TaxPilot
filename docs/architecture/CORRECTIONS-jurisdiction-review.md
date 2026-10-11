> **PROVENANCE, NOT A NORMATIVE SOURCE.** The multi-PR merge sequence this document anticipated
> has been executed on branch `docs/srs-unified-master` (PRs #15 + #32 + #33 merged in, history
> preserved; unified baseline proposed in `TAXPILOT_MASTER_SRS.md`). Remaining follow-ups from the
> later review (snapshot-vs-status wording, full-value hash coverage) are folded into Master §6.
> Governing contracts: `TAXPILOT_MASTER_SRS.md`.

# Architecture review corrections — PR #32 ten items + directive A1–A8

**Branch:** `docs/arch-corrections-jur-review` (from `main e6b21d0`; PR #15 and PR #32 branches untouched, no force-push).
**Reviews addressed:**
- PR #32 review comment `6084618166` (10 required revisions, 2026-10-09).
- PR #15 checkpoint `6084625401` (single-master-SRS requirement).
- This directive §§3 (A1–A8).
**Status:** Proposal. Nothing merged. PO approval required before JUR schema/API coding.

## 0. Source-of-truth conflict (review #1, A1) — merge plan, no merge performed
**Finding:** PR #15 (`bb21439`, 4 files: master SRS v1.1 + ADR-001/002 + Sprint-0 backlog) and PR #32 (`7de4741`, 7 files: ADR-003 + amendment + ERD + OpenAPI + UX + test plan + roadmap) share base `e6b21d0` with divergent heads. Two normative sources must not coexist.
**Adopted strategy (directive recommended sequence, confirmed safe):**
1. PO reviews PR #15 against original product requirements (+ EP-16 cross-reference #17–#25 requested in PR #15 comments; RAG stays P1 parallel, must not block REC MVP).
2. Corrections to PR #15 (if any) land as review commits on its own branch by its author — not by me, not by force-push.
3. PO approves + merges PR #15 → `main` advances.
4. I rebase `docs/ep17-jurisdiction-architecture` onto new `main` (plain rebase, conflict resolution in a follow-up commit, never `--force` on shared work — if rebase is unsafe I will instead open a fresh branch and cherry-pick).
5. I fold approved FR-JUR-001..011, context UX, schema/API contracts, JUR tests, per-pack gates, and EP-16 jurisdiction filters into `TAXPILOT_MASTER_SRS_V1.1.md` as a new approved section + update §28 traceability; the v1.1a amendment file remains as historical traceability only, explicitly marked non-normative.
6. ADR-003, ERD, UX, test plan, roadmap stay as supporting docs (this corrections doc joins them).
7. Revised PR #32 submitted for final review.
**No alternative strategy is safer** (a single combined PR now would either rewrite PR #15 history or duplicate its 4 files). **Merges not performed** — both PRs remain OPEN awaiting PO.

## 1. TaxContext identity, hash, uniqueness (review #2, A2) — corrected spec
**Defect accepted:** ERD used global `UNIQUE(context_hash)` over an under-specified field set; hash role in authZ was ambiguous.
**Replacement contract:**
- Identity: stable UUIDv4 `id` (PK). Tenant: `tenant_id` (FK, part of every uniqueness scope). Client: `client_id`. Subject: exactly one of `subject_entity_id` / `subject_group_id` with `subject_kind` discriminator. Jurisdiction `jurisdiction_code` (ISO-3166-1 alpha-2). Tax type `tax_type_code` + optional `regime_code`. Obligation `obligation_profile_id` + `profile_version INT`. Period `period_start/period_end DATE`. `context_revision INT` (starts 1, +1 per revision). `pack_version TEXT`. `confirmation_status (DRAFT/CONFIRMED)`. `snapshot JSONB` (frozen copy of all above + resolved names/versions at confirm time). `context_hash TEXT`.
- Canonical serialization (deterministic): UTF-8 JSON object with keys in lexicographic order, no whitespace (`separators=(",",":")`, `ensure_ascii=False`), values: tenant/client/subject UUIDs lowercase, codes uppercased, dates ISO `YYYY-MM-DD`, ints plain, snapshot excluded (hash covers inputs; snapshot is the frozen record, verified BY the hash). `context_hash = "sha256:" + hex(sha256(canonical))`.
- Uniqueness: `UNIQUE(tenant_id, context_hash)` (tenant-scoped, not global). Equivalent contexts **may** exist in different engagements: contexts are reusable frozen references — N engagements may point at the same `tax_context_id`; any edit creates a NEW row (new UUID, `context_revision+1`, supersedes prior) rather than mutating. Documented here as normative.
- AuthZ: hash is a content-integrity check only, never a credential. Every request still passes tenant → membership → assignment → object-level checks; knowledge of a hash grants nothing.

## 2. Immutable execution without REVOKE trick (review #3, A3) — corrected design
**Defect accepted:** `REVOKE UPDATE after first RuleRun` cannot express per-row dynamic authorization.
**Replacement:**
- Enqueue path (single DB transaction): load context row (SELECT … FOR UPDATE), assert `confirmation_status=CONFIRMED` + pack capability ACTIVE for the requested rules, insert `RuleRun` with copied `tax_context_hash + context_revision + dataset_set_hash + mapping_versions + rule_versions + pack_version`, commit. The run row is INSERT-only thereafter (app-level guard + `BEFORE UPDATE` trigger raising on historical runs — a static guard, not dynamic REVOKE).
- Worker pre-execution check: re-read context + pack + dataset versions, compare to run row; on mismatch mark run `SUPERSEDED` (never execute stale inputs), on match execute deterministically and store evidence.
- Post-start business edits → new context revision; affected UNISSUED findings move to SUPERSEDED; ISSUED reports (which embed the snapshot) never change.
- Concurrency tests (added to golden plan): double-enqueue same idempotency key → one logical run; edit-during-run → run completes against frozen snapshot + follow-up revision queued; two workers racing one job → exactly-once via `claimed_by/claimed_at` atomic UPDATE…WHERE state='QUEUED'.

## 3. Registration unknowns (review #4, A4) — corrected semantics
**Defect accepted:** backfill proposed verified JO obligations from thin air; JO-select implied registered.
**Replacement:** missing registration ⇒ `registration_status=UNKNOWN` (never `NOT_REGISTERED`, never `REGISTERED`). JO country selection is a *suggestion* requiring explicit user confirmation; confirmation creates an entity + DRAFT obligation, not a verified registration. Four scopes kept distinct: (a) financial reconciliation — allowed with valid accounting inputs even when registration UNKNOWN (explicit `accounting-only` scope banner, no compliance claim); (b) tax-related review — needs confirmed context; (c) tax-treatment interpretation — needs validated rules + expert-approved sources + appropriate context; (d) filing — out of scope entirely. Migration backfill (ERD doc §Migration) is amended: legacy JO engagements get `NEEDS_CONFIRMATION` contexts with UNKNOWN status; rule runs stay blocked with `TAX_CONTEXT_REQUIRED` until a human confirms. No silent verification anywhere.

## 4. Cross-border records (review #5, A5) — corrected behavior
**Accepted:** foreign presence ≠ document mismatch. Preserved per record: responsible legal entity, source jurisdiction if known, counterparty jurisdiction if known, currency, date, invoice identity, evidence link, `tax_applicability=UNKNOWN|UNDER_REVIEW|DETERMINED` (default UNKNOWN for cross-border). Rejection ONLY on genuine ownership/context incompatibility (wrong tenant, entity not in client, context–dataset jurisdiction conflict with no review path) via `CROSS_ENTITY_SCOPE_CONFLICT` + correction action. All other cross-border cases route to reviewer queue with uncertainty banner; never silently discarded, never auto-classified by currency/address/seller alone.

## 5. Tax-group scope (review #6, A6) — boundary confirmed
Domain retains `TaxGroup + Membership` (dated, non-overlapping, same tenant/client-or-authorized-portfolio, jurisdiction + tax-type bound, evidence-backed, never inferred). MVP UI: collapsed advanced section only; ordinary single-entity JO flow (create client → confirm JO entity → upload) requires ZERO group interaction. No eligibility engine, no country grouping rules, no group admin screens in Sprint 0–5. Portfolio orchestration is a named P1+ extension.

## 6. Capability-level activation (review #7, A7) — refined model
Catalog `availability` (PLANNED/IN_REVIEW/BETA/ACTIVE/RETIRED) describes the *country presence*. Each capability carries its own triple: `{capability, pack_version, availability, dependencies[], approvals_required[], effective_from/to}` for: file-import formats, reconciliation rules (REC-001..005 individually), tax-treatment rules, RAG/legal guidance, reports, filing integrations (all disabled in MVP), AI explanations. JO ships as: imports ACTIVE (profiled), REC rules ACTIVE only where individually expert-approved + input-eligible, tax-treatment guidance INACTIVE until FR-RULE-004 gates pass, RAG AUTHORITATIVE limited to approved registry. AE/SA: catalog PLANNED, every capability PLANNED with empty rule arrays; resolver returns `JURISDICTION_NOT_SUPPORTED` / `PACK_NOT_APPROVED` with per-capability skip reasons (including mid-period effective changes). Planned packs are non-executable through API, worker, and direct calls alike; disabling a pack blocks new runs only.

## 7. Public-repo classification (review #8, A8) — decision recorded, safeguards applied
**Fact:** repository is PUBLIC; SRS v1.0 header says Internal/confidential. **Decision needed from PO:** make the repo private OR formally declassify a redacted docs subset. Until decided: no customer documents, sensitive IDs, passwords, private keys, production `.env`, proprietary samples, or personal financial data in commits/issues; fixtures synthetic-or-approved only (blocker register already tracks this). Registration identifiers: AES-256-GCM ciphertext in DB (`number_ciphertext`), `last4` only in reads/logs/URLs; DEK per tenant via managed secret store with rotation + access audit (detailed key design deferred to JUR-01 implementation ADR; no plaintext column will exist by construction).

## 8. API/tests completeness (review #9) — contract checklist for JUR-01/02 PRs
Pydantic v2 schemas + OpenAPI from code (CI schema-compat check); RBAC matrix test (Owner/Admin manage registrations, Accountant drafts, Reviewer confirms where configured, Viewer read-only, masked sensitive reads); error matrix for the five JUR codes + standard 401/403/404/409/422/429; idempotent creates; transactional version handling (§2 above); synthetic golden fixtures only (real-format support needs authorized representative exports — open blocker). No test-result claims made before infra exists; Sprint 0 CI provides the first real evidence.

## 9. Scope narrowness (review #10) — protected JO path
Minimum JO slice for Sprint 2: catalog + LegalEntity + DRAFT/CONFIRMED obligation + TaxContext + JO pack manifest + context selector + resolver with strict rejection + migration gate. Groups, portfolio views, subnational zones, AE/SA capabilities stay out. EP-15 (REC-001..005) remains the critical path; any JUR delay beyond the slice returns here for PO-approved narrowing, not silent deferral of acceptance criteria.

## Traceability
Review items 1–10 → this doc §§0–9 → ADR-003 (unchanged, supporting) → amendment v1.1a (to be folded per §0) → JUR-01 (#28: §§1,2,3,5,7,8) / JUR-02 (#29: §§2,4,6,8) / JUR-03 (#30: §§4,5) / JUR-04 (#31: §§0,6,7,9) → golden plan +18 cases (cases 7,8,15,16 directly cover snapshot/concurrency/migration/flags). Resolved now: specifications. Deferred to implementation PRs: code, migrations, contracts-from-code, executed tests.

## Addendum (2026-10-09) — review follow-up §8: snapshot vs operational status; hash coverage

These refine §§1–2 without changing the approved direction. Normative for JUR-01/02 implementation PRs.

### A. Immutable snapshot coexists with mutable processing status
Do NOT make the whole execution row insert-only. Separate, in every run record:
- **Immutable inputs** (write-once at enqueue, never updated): `tax_context_id`, `context_revision`, `context_hash`, `snapshot_version`, full context `snapshot` JSONB (all confirmed values, see B), `dataset_set_hash` + mapping/profile versions, `rule_versions`, `pack_version`, idempotency key. The worker re-verifies these against live rows before executing; mismatch marks the run SUPERSEDED and never executes stale inputs.
- **Operational state** (mutable through a narrow state machine): `QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELLED`, `attempts`, `claimed_by/claimed_at`, `error/error_class`, timestamps. Transitions only forward (plus `RUNNING → QUEUED` via crash recovery); a static `BEFORE UPDATE` trigger rejects changes to immutable columns.
- History: supersession chains reference predecessor run IDs; issued reports embed the snapshot and never change.

### B. Snapshot integrity covers all confirmed values
The `context_hash` is computed over the canonical serialization of EVERY confirmed context value — tenant, client, subject (entity or group + kind), jurisdiction, tax type, regime, obligation profile id + version, registration ids + versions referenced, period, context revision, pack version, confirmation actor/time, and the snapshot format version itself (`snapshot_version`, starting at 1; any canonical-format change bumps it and old hashes remain verifiable under their version). Canonical form: UTF-8 JSON, lexicographic keys, no whitespace, uppercased codes, lowercase UUIDs, ISO dates, plain ints. Hash verifies integrity; it is never an authorization token (tenant/membership/assignment/object checks still required per call).

### C. Branch discipline restated
PR #32's branch remains untouched. These refinements live here (PR #33) and will be folded into the single master SRS together with the v1.1a amendment at the approved merge step (§0). JUR-01/02 PRs must cite this addendum + §§1–2.

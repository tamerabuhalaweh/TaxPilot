# JUR-01/JUR-02 Implementation Proposal — Minimal Jordan-First Slice (PLAN ONLY, NO CODE)

**Parent issues:** #27 (EP-17), #28 (JUR-01), #29 (JUR-02). **Normative basis:** Master SRS v2.0 §§6/9/11 + Appendices C.13/G/H (`main` @ `6856ad1`).
**Status:** Proposed for review. No migration, endpoint, or worker code in this proposal. JUR-03 UX and full JUR-04 gates follow separately.
**Gates restated (blocking production use, not this plan):** authorized JoFotara/sales/GL samples (DEC-10), tax-expert engagement (DEC-04), hosting/residency (DEC-03/12), AE/SA stay PLANNED non-executable, synthetic data only, queue prod-block (#35), edge/proxy gates (#36), onboarding follow-ups (B-11), repo privacy (DEC-13).

## 1. Objective
Unblock JoFotara reconciliation preparation with the smallest schema + contracts that (a) satisfy Master §6 for a Jordan-only happy path, (b) cannot accidentally execute non-JO rules, and (c) leave multi-country depth (presences, groups, portfolio orchestration) as clean follow-ups.

## 2. Scope decision (narrower-foundation option, for PO approval)
- **Phase 1 (this proposal):** `jurisdiction_catalog` + `legal_entities` + `tax_obligation_profiles` + `tax_registrations` + `tax_contexts` + JO pack manifest seed; context create/confirm/freeze + capability read APIs; backfill of existing clients as explicit-confirmation DRAFTs.
- **Deferred to Phase 2 (multi-country need):** `business_presences`, `tax_groups` + memberships, portfolio orchestration, Tax & Countries full UX (JUR-03), RAG segmentation implementation (EP-16).
- **Rationale:** the JO happy path (single Jordanian entity → confirmed context → future REC engine) needs no presence/group rows; adding them now widens review surface without an executable consumer. If PO prefers the full 8-table slice at once, Phase 2 merges into Phase 1 with +~40% estimate.

## 3. Data design (migration `0004`, new tables only — existing tables untouched)
- `jurisdiction_catalog(code CHAR(2) PK, name_en, name_ar, availability, release_pack_version, updated_at)`; seed `('JO','Jordan','الأردن','ACTIVE',...)`, `('AE',...,'PLANNED')`, `('SA',...,'PLANNED')`.
- `legal_entities(id UUID PK, tenant_id FK, client_id FK, legal_name, incorporation_country_code FK, entity_type, legal_identifier_ciphertext NULL, base_currency CHAR(3), fiscal_start CHAR(5), parent_legal_entity_id NULL FK same-tenant, status, created_at)`; UNIQUE(tenant_id, client_id, legal_name) where active; CHECK country in catalog.
- `tax_obligation_profiles(id UUID PK, tenant_id, legal_entity_id FK (Phase 1: entity-only; group FK arrives Phase 2), jurisdiction_code FK, tax_type_code, regime_code NULL, valid_from DATE, valid_to NULL, registration_status, verified_by NULL, verified_at NULL, source_ref NULL, version INT default 1, status)`; CHECK exactly-one-subject deferred to Phase 2 (entity-only now); new profiles default `UNKNOWN`, never auto-REGISTERED.
- `tax_registrations(id UUID PK, tenant_id, obligation_profile_id FK, authority_code, registration_kind, number_ciphertext NULL, number_last4 NULL, starts_on NULL, ends_on NULL, status, version)`; no plaintext column exists by construction; AES-256-GCM + random nonces + tenant/context AAD + key IDs + rotation (Master §6/§10) implemented in the data-access layer, with access logging.
- `tax_contexts(id UUID PK, tenant_id, client_id FK, subject_kind, subject_entity_id FK, subject_group_id NULL (Phase 2), obligation_profile_id FK NULL, jurisdiction_code FK, tax_type_code, regime_code NULL, period_start/end DATE, profile_version INT, context_revision INT default 1, pack_version TEXT, confirmation_status, context_hash TEXT, snapshot JSONB, confirmed_by FK NULL, confirmed_at NULL)`; UNIQUE(tenant_id, context_hash); CHECK exactly-one-subject (entity in Phase 1); CHECK period sane.
- Canonical hash: UTF-8 JSON, lexicographic keys, no whitespace, uppercased codes, lowercase UUIDs, ISO dates, `snapshot_version: 1` included; `sha256:` hex. Hash verifies integrity only — every read still passes tenant/membership/object authorization.
- Backfill: per existing client, one `legal_entities` row (incorporation JO, base JOD, status DRAFT-suGGESTED — name it `SUGGESTED`, never verified) + one UNKNOWN obligation per evident tax type + one `NEEDS_CONFIRMATION` context per open engagement-less client (no engagements table exists yet; contexts stand alone until the review workflow lands). First tax execution on unconfirmed contexts returns `TAX_CONTEXT_REQUIRED`. Issued-report history: none exists yet; rule stands for the future.
- Rollback: down migration drops added tables/columns in reverse; no existing-table changes, so rollback is drop-only. Dry-run row-count reconciliation required in CI.

## 4. API contracts (versioned `/api/v1`, additive only)
- `GET /jurisdictions` → catalog with availability flags (member).
- `GET/POST /clients/{id}/legal-entities` + `PATCH /legal-entities/{id}` (Accountant+; same-tenant enforced).
- `GET/POST /legal-entities/{id}/tax-obligations` + `PATCH` (Accountant+ draft; REGISTERED requires evidence ref or Reviewer confirm per firm policy).
- `GET/POST /tax-obligations/{id}/registrations` (Owner/Admin create with ciphertext; reads return last4/authority/status only).
- `GET/POST /clients/{id}/tax-contexts` (Accountant+; DRAFT allowed for incomplete/unverified, CONFIRMED requires validated subject + jurisdiction + type + period + profile version; returns id + context_hash + snapshot).
- `GET /jurisdictions/{code}/capabilities?tax_type&date` → pack manifest view (JO lists approved caps only; AE/SA `PLANNED`, `rules: []`, no RUN affordance).
- Errors: `JURISDICTION_NOT_SUPPORTED` / `TAX_CONTEXT_REQUIRED` / `TAX_PROFILE_UNVERIFIED` / `PACK_NOT_APPROVED` / `CROSS_ENTITY_SCOPE_CONFLICT` (+ standard 401/403/404/409/422/429). Idempotency-Key on creates. Pydantic v2 schemas generated to OpenAPI with CI schema-compat check (existing pipeline).
- Resolver interface (code-level, JUR-02): `getCapabilities`, `resolveTaxContext`, `resolveEligibleRules` (filters + explicit skip reasons; zero executions for PLANNED), `getSupportedImportProfiles`, all behind server-derived tenancy. No rule execution paths added (REC engine is EP-07/15 work).

## 5. Security and tenancy
Composite same-tenant FKs + backend authorization on every new endpoint (matrix tests: cross-tenant entity/profile/registration/context reads/writes → 403/404; role matrix for create/confirm/masked-read). Registration ciphertext never in logs/URLs/exports (existing redaction extended + test). Rate limits + CSRF + body caps inherited from Sprint 1 middleware. Audit events for entity/profile/registration/context lifecycle (extends FR-OPS-002 coverage).

## 6. Tests (mirroring Golden JUR #1–8, #10–18 minus multi-country depth)
Isolation (A∤B on all new tables); one client → JO entity (+ AE/SA entity rows allowed as data, zero executability); single entity → UNKNOWN profiles only (no auto obligations); context freeze (post-confirm edits → new revision; unissued findings supersede — findings absent, so assert revision chain + immutability); JO capability gating (PLANNED contexts → `JURISDICTION_NOT_SUPPORTED`, 0 executions, API + worker-resolver unit paths); history/migration safety (backfill counts, NEEDS_CONFIRMATION gate, issued-report rule as contract test); currency segregation carried from FIN core when REC lands; AR/EN form validation; invalid combos → explicit 422s; flag-off pack blocks new runs; migration apply/rollback in CI. Presence/group/RAG-segmentation cases stay with Phase 2.

## 7. Estimate and sequencing (small, reviewed PRs)
- PR-A (JUR-01): migration 0004 + store + RBAC + audit + isolation/security tests + schema-conformance extension. ~3–4 days.
- PR-B (JUR-02): catalog seed + manifest + resolver + capabilities endpoints + gating tests. ~2–3 days.
- PR-C (docs): FR-JUR statuses PARTIAL→(?) only where proven; no status inflation. ~0.5 day.
- Total ~6–8 person-days, sequential (B needs A's tables). No worker/REC/RAG code. No production activation.

## 8. Open decisions for reviewers
(a) Phase 1 narrowing as drawn, or full 8-table slice now? (b) `SUGGESTED` entity semantics acceptable for backfill? (c) `tax_type_code` vocabulary for JO initial set (general-sales-tax/income-tax codes + review-only accounting scope)? (d) Any objection to ciphertext-now (AES design) vs plaintext-with-later-migration? Recommendation: as proposed; ciphertext from day one avoids a migration of secrets.

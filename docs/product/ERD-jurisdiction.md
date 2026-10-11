> **SUPERSEDED / NON-NORMATIVE — FOLLOW MASTER §6.**
> This document is preserved as design history. The following statements in it are
> **REJECTED — do not implement:** global `UNIQUE(context_hash)` (corrected: stable UUID PK +
> tenant-scoped uniqueness + hash over the full canonical frozen snapshot); `REVOKE UPDATE after
> first RuleRun` (corrected: write-once ExecutionSnapshot vs append-only run-status transitions);
> automatic JO/JOD incorporation backfill as verified data (corrected: UNKNOWN default + explicit
> user confirmation + accounting-only scope). Governing contracts: `TAXPILOT_MASTER_SRS.md` §6 (+§11).

# Jurisdiction ERD + migration design (JUR-01, #28; companion to ADR-003)

```
Tenant(1)──< Client(N)──< LegalEntity(N)──< BusinessPresence(N)
   │              │              │──< TaxObligationProfile(N, subject=entity)
   │              │              └──< TaxGroupMembership? no — membership hangs off TaxGroup
   │              └──< TaxGroup(N, by jurisdiction+tax_type)──< TaxGroupMembership(N) >──LegalEntity
   │              └──< TaxContext(N, subject entity XOR group)──< Engagement(N, tax_context_id FK)
   │                        └──< TaxObligationProfile(N, subject=group allowed)
   └── TaxRegistration hangs off TaxObligationProfile; Context snapshots obligation+registration versions
Document/DatasetVersion carry client+entity/context + source_jurisdiction + profile_ref
NormalizedEntry adds issuer_entity_id?, counterparty?, supply_country?, destination_country? (evidence-backed only)
RuleVersion/RuleRun/TaxSource add jurisdiction_code, tax_type_code, regime_code?, legal_period, source_rev, pack_version
Report stores tax_context_snapshot (hash + entity/jurisdiction/tax_type/period/currency/versions)
JurisdictionCatalog(1)──< JurisdictionPack versions; TaxContextAuditEvent append-only
```

## DDL sketch (PostgreSQL, UUID PKs, NUMERIC money, UTC timestamptz, DATE periods)
- `jurisdiction_catalog(code CHAR(2) PK, name_en, name_ar, availability, release_pack_version, updated_at)` seed `('JO','Jordan','الأردن','ACTIVE',...), ('AE',...,'PLANNED'), ('SA',...,'PLANNED')`.
- `legal_entity(id PK, tenant_id FK, client_id FK, legal_name, incorporation_country_code FK, entity_type, legal_identifier_ciphertext?, base_currency CHAR(3), fiscal_start CHAR(5), parent_legal_entity_id? FK same-tenant, status, created_at)`; CHECK incorporation code in catalog; UNIQUE(tenant,client,legal_name) where active.
- `business_presence(id PK, tenant_id, legal_entity_id FK, country_code FK, kind, from_date DATE, to_date? DATE, applicability_status, evidence_ref?)`; CHECK dates; same-tenant FK composite.
- `tax_obligation_profile(id PK, tenant_id, legal_entity_id? FK, tax_group_id? FK, jurisdiction_code FK, tax_type_code, regime_code?, valid_from DATE, valid_to? DATE, registration_status, verified_by?, verified_at?, source_ref?, version INT, status)`; CHECK exactly-one-subject; CHECK valid_from<=valid_to; same-tenant.
- `tax_registration(id PK, tenant_id, obligation_profile_id FK, authority_code, registration_kind, number_ciphertext?, number_last4?, starts_on? DATE, ends_on? DATE, status, version)`; no plaintext column exists by design.
- `tax_group(id PK, tenant_id, jurisdiction_code FK, tax_type_code, authority_ref?, group_status, effective_from DATE, effective_to? DATE, evidence_ref?)`; `tax_group_membership(id PK, group_id FK, legal_entity_id FK, from_date DATE, to_date? DATE)`; EXCLUDE overlapping memberships per (group, entity) via daterange + same-tenant checks.
- `tax_context(id PK, tenant_id, client_id FK, subject_kind, subject_entity_id? FK, subject_group_id? FK, obligation_profile_id? FK, jurisdiction_code FK, tax_type_code, regime_code?, period_start DATE, period_end DATE, profile_version INT, context_hash TEXT UNIQUE, confirmed_by FK, confirmed_at)`; CHECK exactly-one-subject; CHECK period; immutable via REVOKE UPDATE after first RuleRun (enforced in app + trigger guard).
- `engagement ADD COLUMN tax_context_id FK NULL (backfill, then NOT NULL for tax work)`; `document ADD COLUMN legal_entity_id? FK, tax_context_id? FK, source_jurisdiction_code? FK, import_profile_ref?`; `dataset_version ADD COLUMN tax_context_hash?`; `normalized_entry ADD COLUMN issuer_entity_id? FK, supply_country_code? CHAR(2), destination_country_code? CHAR(2)` (nullable, evidence-only); `rule_version ADD COLUMN jurisdiction_code, tax_type_code, regime_code?, pack_version`; `rule_run ADD COLUMN tax_context_hash, pack_version`; `report ADD COLUMN tax_context_snapshot JSONB NOT NULL (for new reports)`; `tax_context_audit_event(...)` append-only.
- Constraints: every tenant row has `tenant_id`; composite FKs `(tenant_id, parent_id)` to block cross-tenant references; `context_hash = sha256(canonical subject+jurisdiction+tax_type+regime+period+profile_version)`; money NUMERIC only; currency/country codes validated against ISO lists (code validity ≠ legal applicability).

## Indexes
(client tenant,name), (entity tenant,client), (presence tenant,entity), (obligation tenant,entity,jurisdiction), (registration tenant,obligation), (group tenant,jurisdiction), (context tenant,client,jurisdiction,period), (engagement tenant,context), (finding tenant,engagement,state), (report tenant,engagement,version).

## Migration (forward, tested; down/roll-forward included)
1. Create catalog + seed JO/AE/SA; create new tables empty; add nullable columns.
2. Backfill per tenant/client: one LegalEntity (JO, JOD) from client name/meta → one obligation per evident tax type (status PENDING unless verified) → one TaxContext per open engagement (period copied) marked `NEEDS_CONFIRMATION`.
3. Gate: any `runReconciliation`/`resolveEligibleRules` on unconfirmed context returns `TAX_CONTEXT_REQUIRED` until user confirms (UX-05 selector); issued reports untouched.
4. Reconcile row counts (clients=entities for JO-only; engagements=contexts for open); anonymized dry-run required.
5. Rollback: drop added FKs/columns/tables in reverse; issued-report snapshots retained (they embed context JSON, independent of new tables).

## Test mapping (schema-level)
Multi-entity (JO/AE/SA, no mixing), presence-not-entity, multi-obligation numbers, group explicitness + non-overlap, 2-tenant isolation, dated memberships, immutability trigger, migration row-count + confirmation gate. Full 18-case plan in `GOLDEN-TEST-PLAN-JUR.md`.

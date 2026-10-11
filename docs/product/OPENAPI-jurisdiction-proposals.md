> **PROPOSALS SUPERSEDED WHERE THEY CONFLICT — FOLLOW MASTER §§6/11.**
> Preserved as design history. **REJECTED:** presenting tax-context creation as CONFIRMED without
> explicit verification (corrected: `NEEDS_CONFIRMATION` gate blocks tax runs until a human confirms).
> Endpoint shapes here are proposals only; JUR-01/02 implementation stays blocked until the unified
> baseline is approved. Governing contracts: `TAXPILOT_MASTER_SRS.md` §§6/11.

# OpenAPI jurisdiction proposals (JUR-01/02, #28/#29; versioned `/api/v1`)

Conventions: server-derived tenant (never trust client `tenant_id`); cursor/offset max 100 + allowlisted sort/filter; Idempotency-Key on POST creates; money as strings; UUIDs; errors `{error:{code,message,details,request_id}}`.

## Endpoints
- `GET /jurisdictions` → `[{code,name_en,name_ar,availability,release_pack_version}]`. JO ACTIVE; AE/SA PLANNED. Perm: member.
- `GET /clients/{id}/legal-entities` / `POST /clients/{id}/legal-entities` (Accountant+; body `{legal_name, incorporation_country_code, entity_type, base_currency, fiscal_start, parent_legal_entity_id?}` → 201). Errors: 422 invalid country/currency, 409 duplicate.
- `PATCH /legal-entities/{id}` (Accountant+; same-tenant enforced).
- `GET/POST /legal-entities/{id}/presences` (Accountant+; `{country_code, kind, from_date, to_date?, evidence_ref?}`).
- `GET/POST /legal-entities/{id}/tax-obligations` (Accountant+ draft; `{jurisdiction_code, tax_type_code, regime_code?, valid_from, valid_to?, registration_status}` → 201; REGISTERED requires evidence ref or Reviewer confirm per firm policy).
- `PATCH /tax-obligations/{id}` (status/version bump; changing verified fields creates new version, old preserved).
- `GET/POST /tax-obligations/{id}/registrations` (Owner/Admin create with ciphertext; reads return `{last4, authority, status}` only; Accountant sees masked unless granted). 403 on unscoped viewer.
- `GET /clients/{id}/tax-contexts` / `POST /clients/{id}/tax-contexts` (Accountant+; `{subject_kind, subject_entity_id?, subject_group_id?, obligation_profile_id?, jurisdiction_code, tax_type_code, regime_code?, period_start, period_end}` → 201 `{id, context_hash, status: CONFIRMED|DRAFT}`; DRAFT allowed for unverified/incomplete, cannot execute tax rules).
- `GET /jurisdictions/{code}/capabilities?tax_type&date` → `{jurisdiction, pack_version, status, supported_tax_types, capabilities:{file_import[], rules[]}, approvals_required[]}`; AE/SA return `status: PLANNED, rules: []`.
- Extended `POST /engagements` requires `tax_context_id` for `type` in tax scopes (`jofotara_reconciliation`, etc.); legacy JO drafts without context get `TAX_CONTEXT_REQUIRED` at rule-run time, not at read time.
- RAG (with EP-16): `POST /knowledge/search {query, language, jurisdiction, as_of_date, entity_context?, source_tiers?}` (jurisdiction-filtered); `POST /knowledge/answer {query, jurisdiction, tax_period, entity_context, mode: AUTHORITATIVE|RESEARCH}` (cross-border must return per-jurisdiction sections + review flag).

## Errors (actionable, no legal conclusions)
- `JURISDICTION_NOT_SUPPORTED` 422/409: AE/SA tax run attempted → lists planned status + what IS available (JO) without offering JO as fallback execution.
- `TAX_CONTEXT_REQUIRED` 409: run without confirmed context → returns how to confirm (entity/context/period picker link).
- `TAX_PROFILE_UNVERIFIED` 422: DRAFT/unverified profile used for authoritative step → draft-save allowed, execution blocked.
- `PACK_NOT_APPROVED` 403/409: retired/disabled or unapproved pack → blocks new runs, history intact.
- `CROSS_ENTITY_SCOPE_CONFLICT` 409: dataset/entity/jurisdiction mismatch → names offending refs + correction action.
- Standard 401/403/404(not-visible)/429 preserved; registration reads 403 if role lacks sensitive-field grant.

## Examples
Create context → `{"subject_kind":"LEGAL_ENTITY","subject_entity_id":"uuid","jurisdiction_code":"JO","tax_type_code":"GENERAL_SALES_TAX","period_start":"2026-01-01","period_end":"2026-12-31"}` → 201 `{"id":"uuid","context_hash":"sha256:…","status":"CONFIRMED"}`.
Run recon → `POST /engagements/{id}/run-reconciliation {"tax_context_hash":"sha256:…","rule_set":["REC-001",…]}` → 202 `{"job_id":"uuid","status":"QUEUED"}` or 409 `TAX_CONTEXT_REQUIRED`.
Capabilities AE → `{"jurisdiction":"AE","status":"PLANNED","rules":[],"message":"Planned — tax checks not available."}`.
Worker enforcement: resolver runs in API AND worker; direct worker call with PLANNED context rejected before any rule loads (JUR-02 acceptance).

## Migration compat
Old clients list unchanged; new sub-resources additive. `POST /engagements` without `tax_context_id` accepted only for non-tax types or legacy JO drafts (flagged `NEEDS_CONFIRMATION`); first tax execution enforces confirmation. No breaking removal in v1 contract.

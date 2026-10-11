> **STATUS: CONDITIONAL ON UNIFIED-BASELINE APPROVAL (not yet approved).**
> Preserved with full reasoning intact. Where this ADR differs from `TAXPILOT_MASTER_SRS.md` §6
> (snapshot hash coverage, snapshot-vs-status separation, UNKNOWN-safe scope, encryption design),
> the Master governs. See also `docs/architecture/CORRECTIONS-jurisdiction-review.md`.

# ADR-003 — Multi-jurisdiction domain model and jurisdiction packs

**Status:** Proposed (awaits PO + Tech Lead approval). **Date:** 2026-10-09.
**Owners:** Product Owner / Architecture Team + Technical Lead. **Epics:** #27 (EP-17), tasks #28 (JUR-01), #29 (JUR-02), #30 (JUR-03), #31 (JUR-04).
**Relates:** SRS v1.1 PR #15 (reconciliation-first, JO MVP), EP-15 #16 (JoFotara/REC), EP-16 #17 / KIE #18–#25 (Intelligence Engine), EP-08 #8 / EP-09 #9 (RAG/adapter), Team Protocol #26.
**Numbering note:** ADR-001 (data residency) and ADR-002 (AI provider) exist on PR #15 branch (`docs/srs-v1.1-reconciliation-scope`, unmerged). This file intentionally uses ADR-003 to avoid collision; it branches from `main` and does not modify PR #15.

## 1. Context
SRS v1.1 (PR #15, docs-only, still OPEN, 0 code-review comments at audit) models `Client → Engagement → Document/Dataset → Rule/Report` with an implicit single jurisdiction: Jordan. RuleVersion carries a jurisdiction field (FR-RULE-JUR-001) but there is no LegalEntity, presence, obligation, registration, group, context, catalog, or pack registry. Product decision now requires: launch JO, then AE, then SA, then global — with a global-ready architecture from day one but executable tax features restricted to approved JO capabilities in the MVP. Without this ADR, the first multi-country client or AE/SA request forces a redesign or, worse, silent JO-rule fallback.

## 2. Decision
Adopt the 8-object domain plus pack interface from issue #27, extended onto (not replacing) the SRS v1.1 Client/Engagement architecture:

- **Tenant/FirmWorkspace** stays the sole security boundary. Never use company country as tenant boundary.
- **Client/Business Portfolio** (existing) gains children; display parent group optional.
- **NEW LegalEntity** — separately identified juridical person (incorporation country, entity type, legal identifier encrypted, base currency ISO-4217, fiscal year, optional parent link). One client may own JO + AE + SA entities. A branch is never auto-created as an entity.
- **NEW BusinessPresence** — branch/office/establishment/other linked to exactly one LegalEntity, with country, kind, dates, applicability_status (NOT_ASSESSED/REVIEW_PENDING/REVIEWED), evidence ref. Informational until expert-verified; implies no registration.
- **NEW TaxObligationProfile** — exactly one subject (entity XOR approved group) + jurisdiction + tax_type + regime? + valid_from/to + registration_status (UNKNOWN/NOT_REGISTERED/PENDING/REGISTERED/ENDED) + verified_by/at + source_ref + version. One entity may hold many profiles (e.g. AE VAT + AE CT; JO sales + income). `REGISTERED ≠ compliant`.
- **NEW TaxRegistration** — belongs to exactly one obligation; authority, kind, ciphertext number + last4, validity, status, version. Ciphertext never in logs/URLs; masked reads.
- **NEW TaxGroup + TaxGroupMembership** — jurisdiction + tax-type-specific, with group_status (DRAFT/APPLICATION_PENDING/VERIFIED_ACTIVE/ENDED), effective dates, evidence; members reference LegalEntities with non-overlapping dated memberships, same-tenant enforced. Never inferred from common ownership. Managed via collapsed advanced UI in MVP.
- **NEW TaxContext** — explicit frozen combination: client + subject (entity XOR validated group) + obligation? + jurisdiction + tax_type + regime? + period + profile_version + context_hash + confirmed_by/at. Immutable once rules execute or a report issues; edits create new revision with supersession of unissued findings.
- **NEW JurisdictionCatalog + JurisdictionPack** — catalog row per ISO-3166-1 alpha-2 code (names EN/AR, availability PLANNED/IN_REVIEW/BETA/ACTIVE/RETIRED, release_pack_version). Pack = versioned manifest (formats/parsers, rule sets, source registries, tax types, UI copy, validations, adapters) behind a provider-independent interface: capability discovery, context validation, tax-category discovery, import-profile selection, deterministic rule resolution, source retrieval, eligibility/effective-date validation, feature activation, versioned reports/audit. Seed `JO=ACTIVE` (only for individually expert-approved accounting/REC capabilities), `AE=PLANNED`, `SA=PLANNED` with zero executable rules.
- **Engagement rule (P0):** one standard review operates under exactly one explicit validated TaxContext. Future portfolio reviews orchestrate child engagements; never blend JO/AE/SA rules in one task. Context snapshot frozen at first execution; preference changes cannot rewrite history.
- **Execution safety:** rules execute only when pack + tax type + sources + input profiles + effective dates + approvals all hold. No JO fallback when another jurisdiction is selected. Planned ≠ supported in UI/API/workers. Disabling/retiring a pack blocks new runs, preserves history.

## 3. Options considered
1. **Single `country` column on Client/Engagement (rejected):** collapses entity vs presence vs registration vs group vs context; cannot represent JO company with Dubai presence, multi-entity groups, VAT-vs-CT profiles, or dated memberships; invites `if country ==` scatter and cross-country total mixing; forces redesign at AE.
2. **Full generic tax ontology now (rejected):** dozens of country-specific columns and subnational modeling up front delays JO MVP (REC-001..005) for speculative generality.
3. **Chosen: normalized 8-object core + versioned extension JSON only where necessary + pack interfaces (adopted):** minimal P0 schema/interface readiness, JO-only executability, AE/SA as registered-but-disabled metadata. Defers group-management UI depth, subnational zones, and portfolio orchestration to P1+ as well-defined extensions.

## 4. Consequences
- Positive: add countries via approved versioned packs; JO/AE/SA data never mix; residence/PE/registration/liability never auto-established; RAG segmented by jurisdiction/period/tenant (coordinates EP-16); reports carry context/version; migration keeps JO history with explicit confirmation where metadata insufficient.
- Costs: 8 new concepts + context picker + Tax & Countries page + resolver + migration + 18 acceptance tests before JO code may rely on the model. JO onboarding must stay simple (default-suggested JO entity with explicit confirmation, no wizard) or the P0 cost exceeds its benefit — mitigation in §6 and UI spec.
- Non-goals now: AE VAT/CT and SA VAT/Zakat/FATOORA rules, integrations, rates (no hardcoded rates/penalties anywhere), subnational zones, portfolio multi-execution.

## 5. Compliance / safety invariants (P0)
User preference ≠ residence/PE/place-of-supply/registration/liability. VAT/sales/income/zakat are distinct categories, never a generic `tax_rate`. Legislation is date- and subject-specific; cross-border unknowns route to expert review, never auto-classified by currency/address. Data residency (ADR-001) is orthogonal to tax jurisdiction. All tenant rows carry `tenant_id` + composite same-tenant FK + backend authZ; money uses NUMERIC/Decimal; country selection errors are explicit (`JURISDICTION_NOT_SUPPORTED`, `TAX_CONTEXT_REQUIRED`, `TAX_PROFILE_UNVERIFIED`, `PACK_NOT_APPROVED`, `CROSS_ENTITY_SCOPE_CONFLICT`).

## 6. Trade-off vs JO MVP speed
If full TaxGroup management UI or portfolio orchestration threatens EP-15 (REC-001..005) dates, narrow to: catalog + entity + presence + obligation + registration + context + JO pack + minimal Tax & Countries page + context selector, with groups as data-model-only + collapsed advanced section. Documented here pre-approval so PO can approve the narrower foundation without revisiting the decision.

## 7. Approval requested
PO + Tech Lead approve domain relationships, minimum UX, and gate behavior in this ADR and the companion amendment/ERD/API/UI/test docs (same branch, PR to follow). Phase C implementation (JUR-01..04) starts only after approval, in small test-driven PRs. Revenue milestones never auto-activate packs; each pack needs expert, sources, fixtures, UAT, security/legal signoff, and rollback.

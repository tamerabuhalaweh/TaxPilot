# TAXPILOT — Master Software Requirements Specification (Unified Baseline)

| Field | Value |
|---|---|
| Status | **THE single authoritative normative baseline** (pending PO approval via PR). All other requirements documents are supporting history or traceability only. |
| Version | v2.0-unified-draft (supersedes v1.1 file + v1.1a amendment as normative sources; they remain as history) |
| Date | 2026-10-11 (draft) |
| Repository | https://github.com/tamerabuhalaweh/TaxPilot |
| Canonical file | `docs/product/TAXPILOT_MASTER_SRS.md` (this file) |
| Authority | Product Owner (final). Approvals required: Tech Lead, Jordanian tax expert (per tax rule), Legal/Privacy counsel, QA/Security leads |
| Classification | Internal / confidential aspiration — REPOSITORY IS PUBLIC (decision OPEN, DEC-13 — see Section 10). No customer data, secrets, or proprietary fixtures anywhere herein. |

## 0.1 Normative map (what counts)
- **Normative:** this file ONLY.
- **Supporting (design detail, non-normative on conflict):** `adrs/ADR-001` (residency), `ADR-002` (AI provider), `ADR-003` (jurisdiction domain), `product/ERD-jurisdiction.md`, `product/OPENAPI-jurisdiction-proposals.md`, `product/UI-TAX-COUNTRIES.md`, `product/GOLDEN-TEST-PLAN-JUR.md`, `product/ROADMAP-country-expansion.md`, `docs/architecture/CORRECTIONS-jurisdiction-review.md` (review provenance incl. addendum).
- **Historical (superseded, preserved):** `product/TAXPILOT_MASTER_SRS_V1.1.md`, `product/SRS-AMENDMENT-JURISDICTION-v1.1a.md`, `product/superseded/*.docx` (v1.0).
- **Priority key:** P0 = controlled-MVP required; P1 = conditional/post-pilot; P2 = excluded. SHALL/SHOULD/MAY per RFC 2119 sense. P0 deferral needs documented scope decision + PO approval.
- **Implementation truth:** Sprint 0 (merged `c0d5e94`) + Sprint 1 (merged `c8db3c6`) are DONE and reflected as AS-BUILT in §§12–14. Everything else is specified, not implemented. No statement here claims otherwise.

## 0.2 Change history
- v1.0 (2026-10-09, `.docx`): AI-assisted tax audit & compliance review; 99 FRs, AQ/TX catalog, 8-week plan.
- v1.1-draft (PR #15 `bb21439`, unmerged): reconciliation-first pivot — Sales Register + file-based JoFotara + GL, REC-001..005, reusable mappings P0, TB supporting, broad PDF/OCR→P1, RAG/narrative→P1, telemetry + unit economics + liability gates, 16-week estimate.
- v1.1a amendment (PR #32 `7de4741`, unmerged): EP-17 global-ready jurisdiction architecture (8-object domain, packs, 11 FR-JUR, ERD/API/UX/test-plan/roadmap).
- Corrections (PR #33 `e948c40` + addendum `12571b9`, unmerged): ten review items + snapshot-vs-status and hash-coverage refinements; follow-up review items recorded below as normative.
- **v2.0-unified-draft (this branch):** merges the three lines, resolves all flagged contradictions (§23), folds review corrections + follow-ups, cross-references EP-16 (P1), and grounds contracts in as-built Sprint 0/1.

## 1. Vision and product promise
TaxPilot Jordan is an AI-assisted tax reconciliation and financial review platform for Jordanian accounting firms: compare accounting records, sales registers, and government e-invoice exports; identify discrepancies; investigate source-linked evidence; issue accountant-ready bilingual reconciliation reports.
Accountant journey: sign in → select/create client → start tax review → upload Sales Register + JoFotara Export + GL → confirm mappings → run reconciliation → investigate → confirm/dismiss/document → bilingual PDF/XLSX. Understandable with zero AI/engineering/DB knowledge.
Positioning: Jordan launch (MVP); then UAE; then Saudi Arabia; then global — decided expansion SEQUENCE, never automatic activation. Global-ready architecture from day one; executable tax features restricted to approved Jordanian capabilities until each pack completes its gate.
Differentiation hypothesis (to validate, not established): Jordan-specific JoFotara workflows, AR/EN RTL, easy onboarding, source-linked evidence, faster report prep — versus manual Excel, native checks, Caseware IDEA, DataSnipper, MindBridge.
NOT: ERP replacement, tax authority, return submitter, gov-portal automator, legal adviser, fraud determiner, multi-country engine in MVP, mobile-native app, BI suite.

## 2. MVP scope (P0) and deferrals
**P0:** email auth + sessions + RBAC + CSRF + tenant isolation; client + review workflow; private CSV/XLSX for Sales Register + JoFotara Excel (file-based ONLY, profiled versions) + GL (+ TB supporting); reusable mapping profiles + validation + drift handling + mapping-time telemetry; deterministic REC-001..005 + supporting AQ regression; evidence-linked findings + decisions/comments/approvals; bilingual PDF/XLSX recon reports; audit history, usage/cost telemetry, job progress/recovery with fenced leases; AR/EN RTL; security/privacy/residency gates; discovery + pilot runbook + DPA/terms review gates; 8-object jurisdiction domain model + JO pack interfaces (schema/API deferred to JUR-01/02 implementation AFTER this baseline is approved — NO jurisdiction tables in the MVP database yet).
**Conditional P0 (blocked until format + fields + basis + expert approval):** sales-tax-return import/recon. No fabricated schemas/formulas.
**P1:** broad PDF extraction, scanned OCR, bank templates, narrative explanations, broad RAG QA (EP-16 workstream), semantic classification, anomaly models, TX-004, threshold UI, auto-billing, sophisticated quotas, status page, AE pack (after JO revenue validation), then SA pack.
**P2:** autonomous filing, gov credentials/API integration, legal advice, fraud determinations, auto-amendments/journals, multi-country engines in MVP, mobile-native, bespoke model training, autonomous source updates, dark-mode gate, benchmarking, hidden second AI in rules.

## 3. Personas, roles, AS-BUILT authorization (Sprint 1, merged)
Owner, Admin, Accountant, Reviewer, Viewer (+ platform Publisher/Operator). Backend-enforced matrix (UI hiding ≠ security):
- Ownership is DISTINCT from administration: invites/patches can never grant, demote, or deactivate owners (`OWNER_PROTECTED`); ownership moves only through explicit audited transfer (confirm flag, row-locked, last-owner invariant verified pre-commit; concurrent transfers serialize, never empty ownership).
- Owner/Admin manage non-owner members; Owner/Accountant/Reviewer… write clients per WRITE set; Viewer read-only; all tenant reads filter tenant_id; cross-tenant object access is 404.
- Sessions: bcrypt-sha256 passwords, httpOnly SameSite session cookie + Bearer alternative, single-use expiring verification/invite tokens, revocation + rotation, per-email Redis rate limits (fail-closed, Retry-After), session-bound CSRF tokens + exact Origin match on cookie mutations (Bearer-only exempt), explicit CORS allowlist, BFF allowlist proxy with body caps, dev-only token exposure (staging/production refuse; Secure cookies nonlocal).
- Break-glass support access: scoped, expiring, audited. No blanket content access.

## 4. Core journeys and state machines
Dashboard → New Review → Upload → Map & Validate → Reconcile → Review Findings → Report. Engagement: DRAFT→DOCUMENTS_UPLOADED→PROCESSING→REVIEW_REQUIRED→UNDER_REVIEW→READY_FOR_APPROVAL→APPROVED→CLOSED (+FAILED→retry; invalid→409; post-approval source change → new revision, never silent mutate). Job: QUEUED→RUNNING→SUCCEEDED|FAILED|CANCELLED with attempts, fencing owner, retry policy, idempotency, terminal-failure retention. Finding: OPEN→UNDER_REVIEW→CONFIRMED_ISSUE|NOT_AN_ISSUE|NEEDS_MORE_EVIDENCE→RESOLVED; SUPERSEDED on input/rule change; append-only decisions; confirmed discrepancy ≠ legal violation.
Exceptions: unsupported file (guidance, no phantom job); missing data (NOT RUN — INSUFFICIENT INPUT); failure (retryable, no double charge); no findings (list checks run; never claim compliant); conflicting version (stale + rerun); insufficient source (abstain + manual route).

## 5. UX direction (accountant-first; wireframes before major frontend build)
Primary nav: Dashboard, Clients, Reviews, Reports, Settings. Documents/findings/evidence live inside the review workspace; `Clients → Client Detail → Tax & Countries` hosts legal entities, presences, obligation profiles, registrations, and pack status (JO Supported vs AE/SA Planned, planned never shows RUN). New Review: short form (client + period + type) then three upload sections with required-vs-optional per check; two sources run eligible checks + list skipped. Mapping: spreadsheet preview (original | mapped | samples | validation | correction) + raw/normalized/corrected + drift confirmation. Results: processed/matched/unmatched/diffs/duplicates/skipped/attention; match % always states denominator + coverage, never a compliance score. Finding detail: 7-part (what/compared/differ/why/evidence/how-to-review/status). Reports distinguish detected/confirmed/unresolved/missing/skipped/limitations; clean result ≠ compliance; no government-approval claims. Light-first, 8px scale, design-system components, keyboard + focus + no-color-only + SR alerts, RTL preserving account/invoice/URL/sign direction, one primary action per view, no placeholder buttons as working features, progressive disclosure, no internal model jargon. AR/EN with shared keys + locale toggles on auth/client surfaces.


## 6. Domain model — global-ready, Jordan-first (CORRECTED; implements ADR-003 as amended)
Concepts MUST NOT be collapsed into one `country` column. Selecting a country asserts business context only — never residence, PE, place of supply, registration duty, grouping, or liability.

- **Tenant / FirmWorkspace:** the sole security boundary. Never use company country as a boundary. Every tenant-owned row carries `tenant_id` with composite same-tenant FKs + backend authorization.
- **Client / Business Portfolio:** firm's customer; owns one or more legal entities; optional display group.
- **LegalEntity:** separately identified juridical person — incorporation country (ISO-3166-1 alpha-2), entity type, encrypted legal identifier, base currency (ISO-4217, display aid only), fiscal year, optional parent link. One client may hold JO + AE + SA entities. A branch is NEVER auto-created as an entity.
- **BusinessPresence:** branch/office/establishment/other linked to exactly one entity — country, kind, dates, applicability_status (NOT_ASSESSED/REVIEW_PENDING/REVIEWED), evidence ref. Informational until expert-verified; implies no registration.
- **TaxObligationProfile:** exactly one subject (entity XOR approved group) + jurisdiction + tax_type + regime? + valid_from/to + registration_status (UNKNOWN/NOT_REGISTERED/PENDING/REGISTERED/ENDED) + verified_by/at + source_ref + version. One entity may hold many (e.g. AE VAT + AE CT). REGISTERED ≠ compliant. **UNKNOWN (missing/unverified registration) NEVER blocks plain accounting reconciliation** — accounting-only scope runs on valid accounting inputs with an explicit scope banner and no compliance claim; authoritative tax treatment stays gated.
- **TaxRegistration:** belongs to exactly one obligation — authority, kind, ciphertext number + last4, validity, status, version. Plaintext never in logs/URLs/downloads. Encryption design (§11): AES-256-GCM, random 96-bit nonce per value (never reused), tenant+context associated data (AAD), key IDs stored per record, managed rotation with re-encryption window, field-level read grants, access logging.
- **TaxGroup + Membership:** jurisdiction + tax-type-specific, group_status (DRAFT/APPLICATION_PENDING/VERIFIED_ACTIVE/ENDED), effective dates, evidence; dated non-overlapping memberships, same tenant/client-or-authorized-portfolio, never inferred from common ownership. Data-model capability now; administration UI deferred past the JO happy path (collapsed advanced section).
- **TaxContext (CORRECTED identity):** stable UUID PK + tenant + client + subject (entity XOR validated group) + jurisdiction + tax_type + regime? + obligation profile id + profile version + period + context_revision + pack_version + confirmation (by/at/status DRAFT|CONFIRMED) + immutable `snapshot` JSONB. Integrity: `context_hash = sha256` over the CANONICAL serialization of the ENTIRE frozen snapshot — every confirmed value above (UTF-8 JSON, lexicographic keys, no whitespace, uppercased codes, lowercase UUIDs, ISO dates, `snapshot_version` included; format changes bump the version, old hashes verify under theirs). Tenant-scoped UNIQUE(tenant_id, context_hash). The hash verifies integrity; it is NEVER an authorization token. Equivalent contexts MAY be referenced by many engagements; any edit mints a new UUID revision (supersession), never mutates.
- **Engagement:** EXACTLY ONE explicit validated TaxContext per standard review (P0). Future portfolio reviews orchestrate child engagements; mixed-country single execution is forbidden.
- **JurisdictionCatalog + JurisdictionPack:** catalog row per country (names EN/AR, availability PLANNED/IN_REVIEW/BETA/ACTIVE/RETIRED, release pack version). Seed JO=ACTIVE (only for individually approved capabilities), AE/SA=PLANNED with zero executable rules. Pack = versioned manifest (formats/parsers, rule sets, source registries, tax types, UI copy, validations, adapters) behind a provider-independent interface: capability discovery, context validation, tax-category discovery, import-profile selection, deterministic rule resolution, source retrieval, eligibility/effective-date validation, feature activation, versioned reports/audit. No `if country ==` scatter; no JO fallback under any other jurisdiction; disabling/retiring blocks new runs, preserves history.
- **Execution separation (CORRECTED):** immutable `ExecutionSnapshot` (context hash + dataset/mapping/rule/pack versions + inputs, write-once at enqueue) vs MUTABLE run status via append-only transitions (QUEUED→RUNNING→SUCCEEDED|FAILED|CANCELLED + attempts/claims/errors). Workers verify snapshot hash pre-execution; mismatch supersedes without executing. Post-start context edits create revisions; issued reports (which embed the snapshot) never change.

## 7. JoFotara-first reconciliation (commercial P0)
Inputs: Sales Register (CSV/XLSX) + JoFotara Excel (FILE-BASED ONLY; no gov API, no credentials, profiled versions from authorized samples; unsupported → actionable guidance) + GL (CSV/XLSX); TB supporting. Narrow tested mappings first; generic parsing forbidden until validated. Tax-return import is conditional-P0 (format + fields + basis + expert approval; no fabricated schemas).
Rules: REC-001 Sales→JoFotara unmatched; REC-002 JoFotara→Sales unmatched; REC-003 matched amount/field diffs (net/tax/gross, inclusive/exclusive, currency, rounding — only available + compatible fields, tolerance + version in evidence); REC-004 duplicates (exact deterministic vs heuristic candidates; suspicious ≠ fraud); REC-005 Sales→GL (mappings/periods/currencies/adjustments/tolerances). Matching MUST distinguish exact/unmatched/ambiguous/diff/unsupported; preserve issuer + invoice identity (number + issuer/scope, never number alone); honor corrections/notes/returns/cancels; forbid many-to-one auto-match; exact decimals; never silent zero/FX; surface timing/period diffs; record strategy + versions + tolerances; allow authorized ambiguous-match review + audit; flag incomplete coverage. Missing fields → NOT RUN — INSUFFICIENT INPUT. 11 fixtures per REC (exact/unmatched/mismatch/duplicate/ambiguous/missing/credit/period/currency/idempotency/traceability). Catalog rule template (jurisdiction keys, algorithm, evidence contract, tests, approvals) + publication gate (draft→tests→accounting review→tax review where tax-concluding→publisher→signed→dry-run→tenant enablement). Math recon ≠ legal interpretation; any required/permitted/disallowed/taxable/exempt conclusion needs expert gate + effective dates; unapproved tax rules never run authoritatively. Secondary regression: AQ checks + TB golden (e.g. 10,250.375 vs 10,200.375 → 50.000 variance).
Mapping (P0): first upload detect→suggest→preview→approve-uncertain→validate; later uploads reuse profiles where safe, detect drift, confirm critical diffs, keep version history; show raw/normalized/corrected; never silently rewrite; track mapping/correction time (onboarding-cost metric, no financial contents in events).

## 8. Tax knowledge, AI, and EP-16 shared contracts
Principle: deterministic engine calculates/detects; AI assists understanding; accountants decide. P0: validation, deterministic recon, provenance, versioned rules, human review, explicit uncertainty, AI data-processing security where external models are used. MVP works with NO provider configured. P1: narrative explanations, broad RAG QA, semantic classification, scanned OCR, anomaly models (EP-16 workstream, separate branches/PRs).
Registry + approval controls are P0; full RAG experiences P1. Official refs are discovery-only (ISTD income/GST/e-invoicing, MoDEE PDPL Law 24/2023 eff. 2024-03-17, Gazette, IFRS profiles); the expert retrieves current full text/amendments/regs and confirms version/applicability/dates pre-publish. Allowed AI: suggest mappings, extract with links, explain deterministic findings, summarize verified passages, flag anomalies, translate with review. Prohibited as authoritative: change raw values, invent ledger numbers, override calcs, cite invented law, declare fraud/liability, publish rules, submit returns.
EP-16 (TaxPilot Intelligence Engine, #17–#25) is a P1 PARALLEL subsystem: broad discovery, strictly governed evidence; three surfaces (official / professional-research / tenant-private, tenant-isolated); authority tiers T1–T6; no training on customer data by default; no corpus-completeness claims. Module ownership: EP-08 official source lifecycle + EP-09 provider/budgets + EP-16 research/monitoring; ONE shared RAG — EP-16 consumes the same jurisdiction/effective-period/tenant filter contracts (`searchKnowledge`, `getApplicableSources`, `answerTaxQuestion` with AUTHORITATIVE vs RESEARCH modes); JO question → JO sources only; cross-border answers label each jurisdiction and require qualified review; RAG never publishes rules.

## 9. Jurisdiction activation and expansion
JO: ACTIVE for approved accounting/REC capabilities only (each rule individually gated). AE: PLANNED (future: FTA VAT + CT separately, registration distinctions, e-invoicing, grouping, classifications). SA: PLANNED (future: ZATCA VAT, Zakat/income distinctions, FATOORA). Global: approved pack templates; subnational zones as defined extensions.
Per-capability controls (import formats, recon rules, tax-treatment rules, RAG guidance, reports, filing, AI explanations) each carry version + availability + dependencies + approvals. Catalog ACTIVE ≠ rule approval. Per-pack gate: source inventory, local expert, effective windows, formats, golden fixtures, migration safety, tenancy, RAG segmentation, reports, locale/currency, signoff, rollback, flag. Commercial revenue is a decision point, NEVER auto-activation. AE/SA show as Planned (no RUN) in UI/API/workers.

## 10. Security, privacy, residency, liability
P0, unweakened: TLS + at-rest (DB/storage/backups/secrets) + rotation; presigned ≤15m post-authZ, no listing; least privilege; non-root containers + resource caps + sanitized names + no embedded-code exec; OWASP ASVS + API Top-10 pre-paid-pilot; incident runbook (triage/contain/investigate/authorized-comms/postmortem; legal reviews external notice); exercised backups (RPO≤24h/RTO≤8h with drill proof, not SLA-assumed).
Threats→controls: IDOR (server ctx + object authZ + negative tests every resource/link); malicious files (sig/quarantine/decompression caps/no-macro/sandbox/formula safety); prompt injection (untrusted marking, allowlisted tools, no admin tools in AI ctx); log/provider minimization + safe traces; compromised accounts (rotation/revocation, rate limits, strong passwords, MFA recommended); stale legal (signed/versioned/dates/expert); billing growth (quotas/caps); loss/ransomware (encrypted backups, restore tests, limited creds, immutable history).
Privacy (counsel-gated, PDPL 24/2023 framework): privacy-by-design; contracts follow counsel-approved interpretation (controller/processor, sensitive financial data, notice/consent/basis, cross-border, breach, retention, subject rights); purpose/scope agreements; minimal collection + encrypted sensitive IDs; tenant export/deletion workflows; retention defaults + legal-hold exceptions (exact durations OPEN DEC-02 — developers SHALL NOT invent); rights intake/routing; region/transfer review pre-onboarding; no training on tenant docs without explicit lawful process. Pilot retention default: retain while active + contractual interval; soft-delete immediately inaccessible; scheduled erasure; time-bound backup expiry; minimal tombstones.
Data-residency ADR (required, DEC-03/DEC-12): app servers, DB, documents, backups, AI processing location(s), subprocessors, cross-border flows, contractual/regulatory reviews. No Jordan-only or PDPL-compliant claims without verification/assessment.
Liability (counsel review required): scope, reliance limits, upload authorization, DPA, confidentiality, retention/deletion, human-review responsibility, ToS, liability allocation/indemnities, insurance assessment, incident-notification duties. No invented enforceable terms; reports never claim government approval.
Public-repo governance (decision OPEN for PO): repo is PUBLIC while SRS claims internal/confidential — make private or formally declassify a redacted subset; meanwhile synthetic-or-approved fixtures only, never customer data/secrets/keys/`.env`/proprietary samples.

## 11. Architecture, data, API, and as-built truth
Modular monolith + separately scaled workers (no premature mesh). Next.js UI; FastAPI `/api/v1`; PostgreSQL (tenant data + source indexes); S3-compatible private storage; Redis queue (worker-crash-only durability; production processing blocked by #35); AI adapters under data-use restrictions. Module ownership enforced (UI owns views, never authZ truth/tax math/secrets; AI adapter never DB-admin/tenant-switch/financial decisions; etc.). CI order: format/lint/typecheck→unit→integration/DB→golden→SAST/deps→build→staging→E2E→approvals→prod→health; immutable SHA artifacts; flags disable unapproved capabilities per tenant. Envs: Dev (synthetic/masked), Staging (synthetic/approved + recovery validation), Prod (least privilege, encrypted backups, alerts, reviewed deploys).
AS-BUILT (Sprint 0 `c0d5e94`, Sprint 1 `c8db3c6`): health/readiness (bounded probes, 503 semantics), correlation IDs, error envelope, env-only config + production guards, redacted JSON logs, SQLAlchemy helpers + DI boundaries; fenced-lease Redis queue (Lua-atomic claim/renew/finish/requeue/recover, per-attempt tokens, server-time leases, max-attempts terminal, heartbeats, periodic auto-recovery; worker-crash-only durability; production worker gate pending #35); versioned-SQL migrations (0001 ledger, 0002 auth/tenancy/clients, 0003 CSRF) + idempotent runner; authN/Z/RBAC/CSRF as §3; tenant-scoped clients + audit; Next.js 16 + strict TS + EN/AR RTL + design tokens + same-origin BFF proxy (fixed host, header allowlist, 1MB/10MB caps, bounded streaming reads, explicit set-cookie forwarding) + honest placeholders; compose (postgres/redis/minio/api/worker/web); 5-job CI + fail-closed security gate.
PROPOSED (JUR-01/02, blocked until this baseline is approved — NOT in the database): the §6 tables/columns, `tax_context_id` on engagements, context-scoped documents/datasets/runs/reports, pack registry endpoints (`/jurisdictions`, `/legal-entities`, `/presences`, `/tax-obligations`, `/registrations`, `/tax-contexts`, `/capabilities`), extended run-reconciliation with context hash + skip reasons (`JURISDICTION_NOT_SUPPORTED`, `TAX_CONTEXT_REQUIRED`, `TAX_PROFILE_UNVERIFIED`, `PACK_NOT_APPROVED`, `CROSS_ENTITY_SCOPE_CONFLICT`), idempotent creates, server-derived tenancy, masked registration reads. Migration safety: nullable backfill → explicit user confirmation (`NEEDS_CONFIRMATION` gate on first tax run); issued reports never rewritten; dry-run row-count reconciliation; down/roll-forward path.


## 12. Performance, reliability, localization, observability
Targets (prove on staging): dashboard/list p95 <500ms excl. WAN; upload-init p95 <1s excl. transfer; async 202 without parser wait; ordinary recon report <30s; limits 25MB/100pp/100k rows configurable; 5 concurrent analyses/tenant + backpressure; 99.5% monthly post-stabilization; RPO≤24h/RTO≤8h with drill proof. WCAG 2.2 AA target + regression checklist; AR first-class (RTL, translations, AR/EN search, mixed-direction values, font-safe bilingual PDFs — DEC-07 typefaces + screenshot corpus); locale formatting without semantic change; AR/Latin numerals preserved on import. Observability: structured logs, request/job trace IDs, latency, worker errors, upload reasons, rule distribution, AI error/cost, backlog; coverage/skipped as product-health metrics; monthly avail + processing SLOs measured independently. Versioned APIs, forward-compatible migrations, reviewed dep updates, rollback docs, IaC. No feature complete without tests + a11y review + error docs + isolation checks.

## 13. Test strategy and release gates
Layers: unit/property (math, validators, transitions, comparators, match keys); integration (isolation, storage, queue, provider failure, retrieval); contract (OpenAPI gen: schemas/auth/errors/Decimal); E2E browser (full recon flow EN+AR); security (IDOR/RBAC/upload/injection/session/rate/leaks); AI bench (extraction/cite/abstention/injection); financial golden (exact recon, signed rows, multi-currency); UAT (3–5 firms: onboarding/usefulness/reports/timings). Per-REC 11 fixtures; AQ/TB regression retained secondary; 18 JUR cases (multi-entity, presence≠entity, multi-profile numbers, explicit groups, JO-only execution, history freeze, revision/supersession, wrong-country conflict, currency segregation, AR/RTL, RAG segmentation, cross-border routing, roles/masking, flag enforcement, migration safety, no-false-compliance, invalid combos); lease/CAS queue cases; auth/CSRF/isolation cases. Freeze corpora before sign-off.
Release gates (ALL must pass): (1) all P0 mapped + tested (blocking exceptions PO+Tech(+tax) approved); (2) zero known cross-tenant disclosures/unauthorized approvals/critical file vulns; (3) golden recon + arithmetic 100%, no precision loss; (4) tax checks only where expert-approved/versioned/period-safe; (5) all findings evidence-linked + versioned, skips visible; (6) EN primary + AR surfaces pass UX + PDF; (7) backup/restore demo + alerts + access-control + DPAs/terms complete; (8) pilot firm completes independently. Done per story: review + static/type + unit/integration + E2E where apt + UX/errors + RBAC/tenant + security + logs/metrics + migration + docs + CI green; AI +eval evidence; tax rule +expert + dated source. Sign-off: PO, Tech, Tax Expert (per TX), QA, Legal/Privacy — in tracker or signed decision with SRS version+SHA. SRS availability ≠ legal/security/finished proof.

## 14. Commercial validation and unit economics
Discovery 10–15 firms (size/buyer/process/software/JoFotara flow/volume/hours/problems/willingness/security); 3 paid pilots = validation target, never represent interest as demand. Unit-econ as assumptions until measured (revenue/customer, engagements, compute/AI/storage/support per engagement, mapping effort from telemetry, contribution, CAC, breakeven). Pricing hypothesis only, never hardcoded (Starter ~49 / Professional ~129 / Firm ~249+ JOD/mo; plan IDs + limits config-driven; DEC-05 quotas, DEC-08 manual vs gateway). Telemetry P0 without financial contents (upload success, correction time, time-to-first-recon, completion, useful findings, FP/rule, coverage, cost/engagement, feedback/renewal). Go/no-go: willingness to pay, repeated completion, measured time cut (30–50% hypothesis, not marketing), trusted findings, reasonable corrections, safe ops, sustainable unit cost; else narrow to highest-value workflow. 90-day: stability/correction/time → reuse/quality/renewal → pricing/margin/acquisition.

## 15. Epics, milestones, and critical path
EP-01 foundation ✅ done; EP-02/03 auth/tenancy/clients ✅ done; EP-04 uploads, EP-05 mapping (profiles P0), EP-06 financial core, EP-07 rule engine (REC over AQ), EP-08 registry/approval (full RAG P1), EP-09 guardrails (models P1), EP-10 findings, EP-11 bilingual recon reports, EP-12 security/ops (+residency gates), EP-13 basic telemetry (sophisticated billing P1), EP-14 UAT + commercial/cost metrics, EP-15 JoFotara + REC ownership (NEW), EP-16 Intelligence Engine P1 (#17–#25, shared contracts only), EP-17 jurisdiction architecture (#27; JUR-01 schema, JUR-02 packs, JUR-03 UX, JUR-04 gates — ALL blocked until this baseline is approved).
Plan (estimate, not commitment): W1–2 validation + foundation; W3–4 ingestion + normalization; W5–8 recon engine + usable MVP (vertical slices); W9–12 pilot hardening; W13–16 conditional buffer. Critical path: auth/tenancy → uploads (+JoFotara profiles) → mapping → deterministic REC → review → report → security/UAT. Under pressure defer OCR breadth, bank templates, advanced tax rules, billing integration, dashboards, assignment extras, export customization — never correctness/isolation/evidence.

## 16. Risks, assumptions, decisions
Risks: low conversion; variable exports (H/H — narrow profiles); wrong tax interpretation (M/Critical — expert+versioned+abstain); FP overload; disclosure (L/Critical — default-deny + tests); AR OCR; provider mismatch; creep (P0 lock + gates); processing cost; missing samples/hosting/pilots/return-format (all OPEN blockers). Assumptions: Jordanian Excel/CSV exports; expert access + authorized samples precondition TX/JoFotara rules; managed cloud; manual invoices MAY start billing; ASR≠OCR; match % always denoms-stated; single-Redis-instance fencing for leases.
Decisions: DEC-01 templates/fixtures (pre-Sprint 2); DEC-02 retention/roles/transfers (pre-real-data); DEC-03 hosting + AI subprocessor + policies (pre-real-data); DEC-04 recon/TX targets + sources (pre-enable); DEC-05 quotas (pre-pricing); DEC-06 blocker/SoD (pre-approval-impl); DEC-07 AR typefaces/corpus (pre-report); DEC-08 payment route (pre-paid-pilot); DEC-09 scan-vs-digital (pre-OCR); DEC-10 JoFotara profiles/versions (pre-REC); DEC-11 AI provider ADR (pre-AI-prod); DEC-12 residency ADR (pre-pilot); DEC-13 repo classification private-vs-redacted (OPEN, pre-real-data); DEC-14 single-master approval of THIS document (next).

## 17. Acceptance-test scenarios (primary = recon; TB = secondary)
ATR-001 E2E recon (Client→Review→Sales+JoFotara+GL→Mappings→REC-001..005→Diffs→Decisions→Bilingual report, no manual DB). ATR-002 both-direction unmatched; ATR-003 ambiguous (no many-to-one, audited resolution); ATR-004 dupes separated, never fraud; ATR-005 credit/correction honored; ATR-006 incl/excl compatible-only + tolerance; ATR-007 GL-mapping diffs skip + listed; ATR-008 incomplete coverage → NOT RUN + report; ATR-009 JoFotara versions (supported maps, unsupported guided); ATR-010 missing-GL partial run; ATR-011 reuse/drift + history; ATR-012 cost/timing without financial contents. Secondary: isolation, TB golden (50.000 variance / balanced pass), blank≠zero, ambiguous dates, FX segregation, idempotency, stale→new version, TX gate, historical dates, unsupported citation, injection, propose-vs-finalize, report immutability, AR PDF, file abuse, blocker 409, provider outage, retention/delete. JUR-01..18 as §13. Auth/CSRF/isolation/queue-lease suites as built. Example (synthetic, not legal guidance): Al-Nahda → Example Trading LLC 2026 → Sales 120 rows 15,000.000 JOD + JoFotara profile-JO-2026.1 + mapped GL → REC-001 2 missing-JoFotara (450.000), REC-002 1 missing-sales (credit-note matched), REC-003 1 presentation diff (resolved), REC-004 1 exact + 1 candidate duplicate, REC-005 passes → reviewer confirms/dismisses/requests → v1 bilingual report distinguishing six outcome classes; no liability inferred.

## 18. Traceability and supersession record (v1.0 → v1.1 → v1.1a → corrections → v2.0)
Comparison basis: full v1.0 `.docx` (434 paras/41 tables), v1.1 file (349 lines), v1.1a amendment + ADR-003/ERD/OpenAPI/UI/test-plan/roadmap, CORRECTIONS + addendum + follow-up review — all extracted and compared; nothing unavailable.
| Old statement | Disposition | Unified rule |
|---|---|---|
| AI-audit-assistant positioning (v1.0) | Replaced (v1.1, kept) | §1 reconciliation-first platform; hypothesis-marked differentiation |
| TB-central inputs; broad PDF/OCR P0 (v1.0) | Modified | §2/§7: Sales+JoFotara+GL P0; TB supporting; PDF/OCR P1 |
| FR-EXT-010 profiles P1 | Promoted P0 | §7 mapping + telemetry |
| AQ catalog as commercial core | Demoted to regression | §7 REC-001..005 commercial P0 |
| RAG/narrative/classify/anomaly/OCR P0-assist | Split | §8 guardrails P0; EP-16 P1 workstream, shared contracts only |
| Flat `country` thinking (implicit) | Replaced (v1.1a + corrections) | §6 eight objects; single-column collapse forbidden |
| `UNIQUE(context_hash)`, hash of subset (ERD) | Corrected | §6: UUID PK, tenant-scoped unique, hash over full canonical frozen snapshot |
| `REVOKE UPDATE` immutability (ERD) | Corrected | §6/§11: ExecutionSnapshot (write-once) vs append-only run-status transitions |
| Backfilled verified JO obligations (ERD) | Corrected | §6: UNKNOWN default; explicit confirmation; accounting-only scope unblocked |
| Cross-border ⇒ document mismatch (draft) | Corrected | §6/§7: preserve + route to review; reject only ownership/context conflict |
| Group admin/eligibility in MVP (draft) | Deferred | §6 model now, UI later; never inferred |
| Catalog ACTIVE = rule approval (draft) | Corrected | §9 per-capability version/availability/deps/approvals |
| `registration_number` plaintext-adjacent (draft) | Corrected | §6/§10 AES-256-GCM + nonce/AAD/key-IDs/rotation/access-logging design |
| Amendment as second normative source | Demoted to history | §0.1: this file sole normative; amendment preserved as traceability |
| ADR-003/ERD/OpenAPI as decided contracts | Supporting | Normative only as folded into §§6/9/11 here; JUR-01/02 code still blocked |
| 8-week firm launch | Replaced (estimate) | §15 phased estimate; vertical slices |
| AT-002 TB+GL primary E2E | Demoted | §17 ATR-001 recon primary |
| DEC-01..12 | Kept + DEC-13/14 new | §16 |
**Counts (v2.0-draft):** ~15 added (JOF/REC/MAP-TIME/TEL/JUR/AI-P1/EP-15), ~14 modified, ~9 deferred to P1, 2 replaced, 6 corrected post-review. No history erased.
**Validation limits:** no JoFotara/sales/GL samples; no tax-expert sign-off; no hosting/residency choice; no pilots; return format unverified; repo privacy undecided — all explicit blockers. No CI run for this docs change; no prod code added.

## Appendix A. Glossary
Tenant, Client/Portfolio, LegalEntity, BusinessPresence, TaxObligationProfile (UNKNOWN ≠ no-obligation), TaxRegistration (ciphertext + last4), TaxGroup/Membership, TaxContext (frozen, hashed), Engagement (one context), JurisdictionCatalog/Pack (PLANNED→ACTIVE per capability), ExecutionSnapshot vs run status, Finding (not conviction/liability), Evidence, Reviewer, RAG AUTHORITATIVE vs RESEARCH, JoFotara (file import only), P0/P1/P2, Stale/superseded, Golden fixture, Coverage (with denominator), Ambiguous match, Fencing token/lease (jobs), CSRF synchronizer.

## Appendix B. Official sources (discovery only; expert confirms before any production use)
ISTD Income Tax Law; ISTD GST legislation; ISTD Billing_system (context); MoDEE PDPL Unit + FAQs (Law 24/2023 eff. 2024-03-17); Gazette; IFRS Jordan profile + licensing; UAE FTA CT/VAT/group references; ZATCA VAT-group/FATOORA references (architecture context only — NO AE/SA rules authorized).


## Appendix C. Normative requirements matrix (lossless restoration of v1.1 §§9 + v1.1a FR-JUR)

Every row below is normative and testable, with stable ID, priority, responsible module/epic, preconditions, input/output, measurable acceptance, verification method, and current implementation status. Statuses: IMPLEMENTED (merged + tested), PARTIAL (some acceptance met), NOT_STARTED (specified, awaiting build), BLOCKED (explicit external precondition), DEFERRED-P1 (intentionally post-pilot). No ID from v1.1 or v1.1a is dropped without a disposition in Appendix I.

### C.1 Identity, sessions, tenancy — module Identity & Tenancy — epic EP-02 #2
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-ID-001 | P0 | None | email+password+firm → unverified user + tenant + owner membership | Unverified user cannot access tenant data; duplicate emails handled without oracle | Integration: register/verify/login/me/logout journey | IMPLEMENTED (PR #37) |
| FR-ID-002 | P0 | Registered user | credentials → session (cookie + Bearer), logout revokes | Logout invalidates; expiry re-authenticates; rotation on tenant switch | Integration journey + revocation test | IMPLEMENTED |
| FR-ID-003 | P0 | Registered user | reset request → single-use expiring token → new password | Tokens single-use + expiring; unknown email gets neutral response | Integration (not yet written) | NOT_STARTED — see B-11 |
| FR-ID-004 | P0 | Any authed call | any object reference → data or 403/404 | IDOR manipulation returns 403/404 with no leak, every resource | Security sweep per resource | PARTIAL (proven on auth/session/member/client/audit paths; no tenant-authenticated job endpoint exists; files/evidence/exports absent — enforcement required per new resource) |
| FR-ID-005 | P0 | Owner/Admin caller | invite email+role → token; accept → membership | Token expires; removal revokes future access; replay idempotent-200 | Integration invite/accept/replay/concurrency | IMPLEMENTED |
| FR-ID-006 | P0 | Tenant membership | any list/get/download/job/evidence/export | Negative tests on all paths show no cross-tenant data | Security matrix A-vs-B | PARTIAL (auth/client/member/audit isolation implemented; queue keys are global with no tenant-scoped job API; file/evidence/export enforcement NOT_STARTED and required per new resource) |
| FR-ID-007 | P0 | Reachable login endpoint | 5 bad password attempts → 429 + Retry-After | Abuse simulation cannot bypass; per-account only (no shared-IP bucket) | Integration lockout + fail-closed tests | IMPLEMENTED (backend per-email + BFF caps; edge limiting gated #36) |
| FR-ID-008 | P1 | Privileged role | MFA enroll/recover/enforce | MFA tests if delivered | — | DEFERRED-P1 |
| FR-ID-009 | P0 | Support request | break-glass grant with scope + expiry | Scoped grant, expiration, audit event; no blanket access | Security review | NOT_STARTED (no support tooling yet) |

### C.2 Firm, client, engagement — module Client & Engagement — epic EP-03 #3
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-WRK-001 | P0 | None | firm name → isolated workspace + owner | Provisioning creates tenant + owner, invisible to others | Integration onboard | IMPLEMENTED |
| FR-WRK-002 | P0 | Membership | create/search/edit/archive clients | Tenant-scoped search; archive preserves history; IDs tenant-unique only | Integration CRUD + isolation | PARTIAL (create/list/edit/archive via API exist; UI search absent; API filters by status, not full-text search) |
| FR-WRK-003 | P0 | Membership | optional business/tax ref, sector, contact, owner | Missing optionals never block draft creation | Contract + integration | PARTIAL (fields stored; optional tax-ref/owner metadata not validated or surfaced; client UI pending) |
| FR-WRK-004 | P0 | Client exists | client + period + type + staff → engagement (201, DRAFT) | End<start rejected; stable unique ID; duplicate same-period warned | Integration (to write) | NOT_STARTED — engagements deferred to Sprint 2 pending SRS consolidation |
| FR-WRK-005 | P0 | Engagement exists | transition request → new state or 409 | Invalid → 409 STATE_CONFLICT; history shows actor/time, prior/new | Unit (transition table) + integration | NOT_STARTED |
| FR-WRK-006 | P0 | Engagement exists | dashboard query → readiness/rule/finding/status counts | Counts reconcile to stored jobs/results under tenant filter | Integration | NOT_STARTED |
| FR-WRK-007 | P0 | Membership | assign/change staff | Unassigned restricted users cannot open the engagement | Security matrix | NOT_STARTED |
| FR-WRK-008 | P1 | Owner/Admin | branding/preferred mappings config | New version recorded; existing reports unchanged | — | DEFERRED-P1 |

### C.3 File ingestion and storage — module Ingestion — epics EP-04 #4 + EP-15 #16
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-FILE-001 | P0 | Membership | UTF-8 CSV/XLSX upload → stored document | Fixture imports; malformed encodings get actionable errors | Integration fixtures | NOT_STARTED (upload endpoints absent) |
| FR-FILE-002 | P1 | Membership | text PDF supported; scanned beta-gated | Text passes; low-confidence scans route to review | P1 suite when built | DEFERRED-P1 (was P0 in v1.0; rationale: recon-first, App. I) |
| FR-FILE-003 | P0 | Upload attempt | MIME/signature/ext/size/integrity/archive-risk validation | Mismatch + decompression-bomb fixtures rejected | Security fixtures | NOT_STARTED |
| FR-FILE-004 | P0 | Config present | over-limit file → 413 + limit stated | Defaults 25MB/100pp/100k rows server-enforced; config change needs no code | Boundary tests | NOT_STARTED (JSON body caps proven; file limits pending) |
| FR-FILE-005 | P0 | Validated file | private storage + hash + metadata + immutable version | Replace creates v2; lineage retained per policy | Integration | NOT_STARTED |
| FR-FILE-006 | P0 | Stored file | user-confirmable classification (incl. jofotara_export) | AI guess correctable, never silently final | E2E | NOT_STARTED |
| FR-FILE-007 | P0 | Upload attempt | malware scan where available; unscanned stay quarantined | Quarantined files never reach parser/download | Security | NOT_STARTED |
| FR-FILE-008 | P0 | Upload attempt | visible state + resume/retry | Pending/Processing/Ready/Needs-review/Failed; safe retry | E2E | NOT_STARTED |
| FR-FILE-009 | P0 | Engagement scope | identical re-upload → reuse-or-version offer | Warning + explicit action; no double counting | Integration | NOT_STARTED |
| FR-FILE-010 | P0 | Stored file | authorized short-lived links (≤15m proposed) | Expired denied; no bucket listing/guessable keys | Security | NOT_STARTED |
| FR-FILE-011 | P1 | Labeled validation | bank/OCR templates | Type-specific gold datasets pass thresholds | — | DEFERRED-P1 |

### C.4 Extraction, mapping, validation — module Ingestion & Extraction — epic EP-05 #5
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-EXT-001 | P0 | Extracted file | rows with parser version + sheet/page/row/cell + confidence | Every row navigates to source | Integration | NOT_STARTED |
| FR-EXT-002 | P0 | Extracted file | suggested (never assumed) column mapping | User confirms; ambiguous blocks finalization | E2E | NOT_STARTED |
| FR-EXT-003 | P0 | Mapped file | raw vs normalized vs corrected views | Preview shows all three; audit persists editor | Integration | NOT_STARTED |
| FR-EXT-004 | P0 | Mapped file | invalid/ambiguous dates/separators/currencies flagged | `01/02/2026` never silently interpreted | Unit + E2E | NOT_STARTED |
| FR-EXT-005 | P0 | Mapped file | unrecognized numerics raise row errors | Never silent zero; totals exclude only with explicit reason | Unit | NOT_STARTED |
| FR-EXT-006 | P0 | Mapped file | preview + validation summary gate analysis | Checks cannot start until required mappings approved | E2E gate test | NOT_STARTED |
| FR-EXT-007 | P0 | Mapped file | stable dataset version + source identity | Rerun on identical version reproduces canonical records | Integration | NOT_STARTED |
| FR-EXT-008 | P0 | Processing run | row success/warning/failure counts | Dashboard reconciles to analyzed total | Integration | NOT_STARTED |
| FR-EXT-009 | P0 | AI extraction used | schema-validated output; unreliable → human review | Invalid/ungrounded output never becomes ledger data | AI bench | NOT_STARTED |
| FR-EXT-010 | P0 | Client + doctype | saved reusable mapping profiles + drift confirm + version history | Safe reuse; schema drift blocks critical diffs until confirmed | Integration ATR-011 | NOT_STARTED — PROMOTED P1→P0 in v1.1 (App. I) |
| FR-MAP-TIME-001 | P0 | Upload/mapping activity | mapping/correction time telemetry (no financial contents) | Onboarding-cost metric recorded per upload/profile | Integration ATR-012 | NOT_STARTED |

### C.5 Financial normalization and checks — module Financial Core — epic EP-06 #6
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-FIN-001 | P0 | Normalized entries | Decimal/NUMERIC + currency + quantization policy | Reference totals match fixtures exactly; no float drift | Golden arithmetic | NOT_STARTED |
| FR-FIN-002 | P0 | Journal entries | debit + credit kept independently; reversals preserved | Reversal fixture stays traceable and reconcilable | Golden | NOT_STARTED |
| FR-FIN-003 | P0 | Trial balance | debit/credit totals vs currency tolerance | Unbalanced sample yields exact-difference finding | Golden AT-003/004 | NOT_STARTED (secondary regression track) |
| FR-FIN-004 | P0 | Mapped GL + TB | same-period/currency reconciliation | Missing mapping skips (never fabricated mismatch) | Golden | NOT_STARTED |
| FR-FIN-005 | P0 | GL/register rows | exact vs candidate duplicate classification | Exact deterministic; suspicious labeled potential | Unit + golden | NOT_STARTED |
| FR-FIN-006 | P0 | Account mappings | engagement-versioned user-approved mappings; unmapped listed | Update triggers fresh run; prior reports unchanged | Integration | NOT_STARTED |
| FR-FIN-007 | P0 | Multi-currency books | segregated totals absent approved FX | UI never sums JOD+USD | Golden AT-007 | NOT_STARTED |
| FR-FIN-008 | P0 | Engagement period | out-of-range entries flagged, never deleted | Exact source references on flags | Golden | NOT_STARTED |
| FR-FIN-009 | P0 | Any calculation | inputs + rule version + tolerance + result recorded | Auditor reconstructs from stored evidence | Lineage tests | NOT_STARTED |
| FR-FIN-010 | P0 | Missing inputs | SKIPPED_INPUT_MISSING with absent sources/columns | No inference where inputs missing | Integration | NOT_STARTED |

### C.6 Rule definition, publication, execution — module Rule Engine — epic EP-07 #7
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-RULE-001 | P0 | Rule exists | immutable key/version/category/jurisdiction/logic/prereqs/severity/window | Metadata persisted + visible to auditors | Integration | NOT_STARTED |
| FR-RULE-002 | P0 | Approved datasets | executed/skipped/failed/passed ledger | Ledger totals match eligible rules at run time | Integration | NOT_STARTED |
| FR-RULE-003 | P0 | P0 rule | positive/negative/boundary/missing-input fixtures | CI fails if any required fixture fails | CI golden | NOT_STARTED |
| FR-RULE-004 | P0 | Tax rule draft | named expert review + approval before publish | Unapproved tax rule never runs in production | Gate test AT-010 | NOT_STARTED (gate specified; no engine yet) |
| FR-RULE-005 | P0 | Dated rule + engagement | applicability respects legal/source-effective dates | 2024 engagement never silently uses 2026-only rule | Gate test AT-011 | NOT_STARTED |
| FR-RULE-006 | P0 | Published rule | change creates new version, history kept | Old runs reproducible on original version | Integration | NOT_STARTED |
| FR-RULE-007 | P0 | Rule failure | isolated error; never presented as passed/compliant | Partial state explicit; other results valid | Integration | NOT_STARTED |
| FR-RULE-008 | P0 | Any rule output | phrased possible-issue/review-required, never legal judgment | No evasion/violation/liability assertions | Content review | NOT_STARTED |
| FR-RULE-009 | P1 | Firm-authorized setting | threshold customization with version audit | Old reports stable | — | DEFERRED-P1 |
| FR-RULE-JUR-001 | P0 | Any rule definition | jurisdiction_code, rule_code, version, effective_from/to, tax_category, source_reference, approval_status | JO-only in MVP; later jurisdictions cannot corrupt JO history; no ZATCA/FTA code | Contract tests | NOT_STARTED — NEW in v1.1 (App. I) |



### C.7 AI services and verified knowledge — modules Tax Knowledge + AI Adapter — epics EP-08 #8, EP-09 #9, EP-16 #17 (P1)
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-AI-001 | P0 | Allowed workflow only | classify/extract/explain assistance | No writes to bookkeeping or submission endpoints | Security review | NOT_STARTED (no AI calls exist) |
| FR-AI-002 | P0 | Provider configured | adapter timeouts, capped retries, budget limits | Outage never invalidates completed deterministic checks | Integration AT-019 pattern | NOT_STARTED |
| FR-AI-003 | P0 | System-consumed output | JSON-schema validation; invalid rejected/quarantined | Bounded retries recorded | Unit | NOT_STARTED |
| FR-AI-004 | P0 | Tax explanation | cites source ID/section/period + link | Click-through matches claim and period | Bench AT-012 pattern | NOT_STARTED |
| FR-AI-005 | P0 | Missing/invalid source | abstain + caveat + manual route | No legal-treatment conclusions without source | Bench | NOT_STARTED |
| FR-AI-006 | P0 | Any file/retrieved text | treated as untrusted data, never instructions | Injection fixture gains nothing | Security AT-013 pattern | NOT_STARTED |
| FR-AI-007 | P0 | Any numeric output | figures from deterministic engine, not LLM math | LLM contradiction cannot alter persisted calc | Unit | NOT_STARTED |
| FR-AI-008 | P0 | Any AI call | provider/model/prompt version + redacted trace + cost + eval status | No raw sensitive bodies by default | Review | NOT_STARTED (redacted JSON logging pattern exists in backend) |
| FR-AI-009 | P0 | Any customer data | no training by default; retention/transfer terms approved | Config + contracts reviewed pre-upload | Legal review (DEC-03) | NOT_STARTED — BLOCKED on provider decision |
| FR-AI-010 | P1 | Labeled benchmark | retrieval + Arabic reasoning evaluation | Citation + abstention correctness measured | — | DEFERRED-P1 |
| FR-AI-P1-001 | P1 | Approved need | advanced narrative explanations | Eval-gated | — | DEFERRED-P1 (MVP works provider-free) |
| FR-AI-P1-002 | P1 | Approved need | broad RAG question-answering | Eval-gated; EP-16 workstream | — | DEFERRED-P1 |
| FR-AI-P1-003 | P1 | Approved need | semantic transaction classification | Eval-gated | — | DEFERRED-P1 |
| FR-AI-P1-004 | P1 | Approved need | scanned-invoice OCR | Per-template gates (DEC-09) | — | DEFERRED-P1 |
| FR-AI-P1-005 | P1 | Approved need | anomaly-detection models | Eval-gated | — | DEFERRED-P1 |

### C.8 Findings, comments, review, approval — module Findings & Review — epic EP-10 #10
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-FND-001 | P0 | Rule run exists | finding with category/severity/status/owner/time/evidence/rule+version | API returns complete lineage | Contract | NOT_STARTED |
| FR-FND-002 | P0 | Extractable source | evidence refs dataset version + exact location | Click opens sheet/row or PDF page | E2E | NOT_STARTED |
| FR-FND-003 | P0 | Finding exists | explanation + calc + inputs + rule + limits | Reviewer understands without logs/chat | UX review | NOT_STARTED |
| FR-FND-004 | P0 | Authorized reviewer | confirm/dismiss/need-evidence + justification | Append-only ReviewDecision + timeline | Integration | NOT_STARTED |
| FR-FND-005 | P0 | Accountant member | comment/propose without bypass | Unauthorized finalize rejected by backend | Security | NOT_STARTED |
| FR-FND-006 | P0 | New source/mapping/rule | stale/superseded findings; approval blocked on stale criticals | `finding.superseded` event; blockers listed | Integration AT-009 pattern | NOT_STARTED |
| FR-FND-007 | P0 | Findings exist | filter/sort by category/severity/status/date | Paginated, tenant-scoped, matched count, accessible table | Contract | NOT_STARTED |
| FR-FND-008 | P0 | Resolved review | explicit authorized attributable approval + snapshot hash | Immutable record with timestamp + version hash | Integration | NOT_STARTED |
| FR-FND-009 | P0 | Unresolved highs | disclosure; default blocks until authorized acknowledgment | 409 APPROVAL_BLOCKED + blocker list | Integration AT-018 pattern | NOT_STARTED |
| FR-FND-010 | P1 | Core decisions work | assignment/due dates/mentions | Notifications respect permissions | — | DEFERRED-P1 |

### C.9 Reports and exports — module Reports — epic EP-11 #11
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-REP-001 | P0 | Approved snapshot | summary (firm/client/period/quality/coverage/counts/actor) | Golden fixture has all sections | Golden | NOT_STARTED |
| FR-REP-002 | P0 | Approved snapshot | detail (category/evidence/amounts/dispositions/limits) | Matches approved snapshot exactly | Golden | NOT_STARTED |
| FR-REP-003 | P0 | Report content | PDF + XLSX with formula-injection safety | Malicious strings exported as inert text | Security fixtures | NOT_STARTED |
| FR-REP-004 | P0 | Issued report | immutable versioned artifact + snapshot link | Rerun cannot rewrite old downloads | Integration AT-015 pattern | NOT_STARTED |
| FR-REP-005 | P0 | Any report | AI disclaimer + no-compliance-guarantee | Footer + executive summary contain both | Content check | NOT_STARTED |
| FR-REP-006 | P0 | Arabic content | correct AR + RTL rendering in PDF | Mixed-script reference screenshots pass (DEC-07) | Visual | NOT_STARTED |
| FR-REP-007 | P0 | Issued report | permission + short-lived authorized download | Foreign-tenant + expired links denied | Security | NOT_STARTED |
| FR-REP-008 | P1 | Pilot feedback | configurable branding/templates (new reports only) | Brand settings never alter issued reports | — | DEFERRED-P1 |

### C.10 Subscription, cost, usage — module Subscriptions — epic EP-13 #13
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-USE-001 | P0 | Plan configured | quotas for seats/files/storage/processing/AI | Limit triggers without data deletion | Unit | NOT_STARTED |
| FR-USE-002 | P0 | Metered operation | idempotent per-tenant usage records | Retry never double-charges/counts | Integration | NOT_STARTED |
| FR-USE-003 | P0 | Approaching quota | UI shows usage + pre-block explanation | Message has quota/used/next-action | E2E | NOT_STARTED |
| FR-USE-004 | P0 | Expired subscription | new work restricted per policy; read/export preserved | Suspended data never silently deleted | Integration | NOT_STARTED |
| FR-USE-005 | P0 | Pilot commercial | manual invoices allowed; status securely managed | Operator activation with audited approval | UAT | NOT_STARTED |
| FR-USE-006 | P1 | Approved JO provider | card/recurring billing integration | Webhook idempotency + reconciled payments | — | DEFERRED-P1 (was P0-conditional; App. I) |
| FR-USE-007 | P0 | Metered AI/compute | per-tenant + aggregate cost observability | Dashboard shows no raw docs | Integration | NOT_STARTED |
| FR-TEL-001 | P0 | Any review activity | 9-metric telemetry without financial contents | Upload success, correction/first-recon/completion times, findings, FP/rule, coverage, cost, feedback | Integration ATR-012 | NOT_STARTED — NEW in v1.1 |

### C.11 Platform operations — module Operations — epic EP-12 #12
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-OPS-001 | P0 | Async operation | durable idempotent bounded-attempt job record | Duplicate key returns same logical job/no-op | Integration AT-008 | PARTIAL (worker-crash-resilient dev queue only: atomic leases, attempts, idempotency proven; Redis-crash durability absent; production processing blocked #35) |
| FR-OPS-002 | P0 | Any auditable action | actor/action/tenant/resource/time event, no secrets | Auth/permission/doc/rule/finding/approval/report-access coverage | Integration | PARTIAL (auth/member/client events implemented; rule/finding/report/approval/file coverage pending with those domains) |
| FR-OPS-003 | P0 | Running system | health/queue/failure metrics + alertable counters | Injected worker failure alerts in staging | Staging drill | PARTIAL (health/ready/depth endpoints exist; alerting not wired) |
| FR-OPS-004 | P0 | Deletion request | manifest covering originals/derived/backups | Completed/blocked states recorded | Integration AT-020 pattern | NOT_STARTED — exact periods OPEN DEC-02 |
| FR-OPS-005 | P0 | Backed-up infra | tested DB restore with documented times | RPO≤24h/RTO≤8h evidenced by drill | Drill evidence | NOT_STARTED |
| FR-OPS-006 | P0 | Any release | automated checks + staging smoke + SHA + rollback runbook | Pipeline gate enforced | CI (5 jobs green on main) | PARTIAL (CI gates exist; staging deploy + runbook pending) |
| FR-OPS-007 | P1 | Paid launch | public status/incident surface | Reveals no tenant info | — | DEFERRED-P1 |

### C.12 JoFotara import — modules Ingestion & Financial Core — epic EP-15 #16
| ID | Pri | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-JOF-001 | P0 | Customer Excel file | first-class `jofotara_export` dataset + profile match | File-based ONLY (no gov API/credentials); unsupported versions get guidance | Integration ATR-009 | NOT_STARTED — BLOCKED on authorized samples (DEC-10) |
| FR-JOF-002 | P0 | Approved samples | narrow tested format profiles before generic parsing | Unprofiled versions route to review, never auto-map | Fixture gate | NOT_STARTED — BLOCKED (DEC-10) |
| FR-JOF-003 | P0 | JoFotara rows | issuer/seller context + invoice identity preserved | Same number across issuers never conflated | Golden | NOT_STARTED |
| FR-JOF-004 | P0 | Source permits | corrections/credit notes/returns/cancels honored | Correction fixtures pass; nothing silently dropped | Golden ATR-005 | NOT_STARTED |
| FR-JOF-005 | P0 | Any import | explicit incomplete-coverage report | Affected checks NOT RUN — INSUFFICIENT INPUT | Integration ATR-008 | NOT_STARTED |
| FR-JOF-006 | cond-P0 | Format + fields + basis + expert approval, all evidenced | tax-return import enabled | Disabled until all four evidenced; no fabricated schemas | Gate review | BLOCKED (unverified return format) |

### C.13 Reconciliation rules — module Rule/Recon Engine — epics EP-07 #7 + EP-15 #16
| ID | Pri | Name / scope | Acceptance | Verification | Status |
|---|---|---|---|---|---|
| REC-001 | P0 | Sales Register → JoFotara unmatched | Sales txns lacking JoFotara counterpart identified with evidence | 11 golden fixtures each (exact/unmatched/mismatch/duplicate/ambiguous/missing/credit/period/currency/idempotency/traceability) | NOT_STARTED |
| REC-002 | P0 | JoFotara → Sales Register unmatched | JoFotara invoices lacking sales counterpart identified | Same fixture battery | NOT_STARTED |
| REC-003 | P0 | Matched amount/field differences | Net/tax/gross + inclusive/exclusive + currency + rounding compared only where compatible; tolerance + version in evidence | Same battery + presentation fixtures | NOT_STARTED |
| REC-004 | P0 | Duplicate candidates | Exact vs heuristic separated; suspicious never labeled fraud/evasion | Same battery | NOT_STARTED |
| REC-005 | P0 | Sales Register → GL | Mapped totals vs GL with mappings/periods/currencies/adjustments/tolerances | Same battery | NOT_STARTED |
Matching MUSTs (normative): distinguish exact/unmatched/ambiguous/diff/unsupported; preserve issuer + identity; honor corrections; forbid many-to-one auto-match; handle cross-issuer duplicate numbers; preserve originals + provenance; exact decimals; never silent zero/FX; surface timing/period diffs; record strategy + rule/jurisdiction version + tolerances + mapping versions; authorized ambiguous-match review + audit; flag incomplete coverage.



## Appendix D. Screen specifications UX-01..UX-13 (normative; P0 unless noted)
| ID | Contents | Primary action | Key states | Acceptance | Status |
|---|---|---|---|---|---|
| UX-01 | Email+password, show/hide, reset, locale switch, session errors | Sign in | Signing-in, invalid creds, unverified, expired link, session-expired | No tenant data pre-login; labels; no enumeration | PARTIAL (login built; reset flow missing — B-11) |
| UX-02 | 4 summaries (active, waiting on me, high-sev unresolved, recent) + recent table | New Review | First-use empty, no clients, API error, skeleton | No meaningless graphs; date period on counts | PARTIAL (status shell + clients; 4-summary dashboard pending) |
| UX-03 | Searchable clients table + drawer add (name + optional ID/sector) | Add Client | None, no results, duplicate ID, save fail | Minimal fields only | PARTIAL (client list + create exist; searchable table + drawer + duplicate handling NOT implemented) |
| UX-04 | Client summary/profile/engagements/docs + report history | Start Review | None, archived, denied | Tenant-scoped; history by client | NOT_STARTED (no detail page yet) |
| UX-05 | Short form (client + period + type) + 3 upload sections with required-vs-optional per check | Create Review | Validation, invalid dates, duplicate-period warning | One concise form; 2-source uploads run eligible + list skipped | NOT_STARTED (honest placeholder at /reviews/new) |
| UX-06 | Drag/drop per-type labels, status, progress, retry, replace-with-version | Continue to Data Check | Unsupported, virus, encrypted, duplicate, interrupted | Formats + limits shown BEFORE upload | NOT_STARTED |
| UX-07 | Spreadsheet preview (original/mapped/samples/validation/correction) + 20 rows + totals + source links | Confirm Dataset | Ambiguous headers, missing debit/credit, currency/date issue, partial, schema drift | AI suggestion never auto-approved | NOT_STARTED |
| UX-08 | Timeline + progress; summary (processed/matched/unmatched/diffs/dupes/skipped/attention) | Review Findings | Queued, delayed, provider n/a, partial, none runnable | Match % states denominator + coverage; never compliance score | NOT_STARTED |
| UX-09 | Filters (category/severity/status/assignee), counts, per-currency amounts, evidence flags | Open Finding | None, insufficient source, stale, loading/error | No composite risk score unless defensible | NOT_STARTED |
| UX-10 | 7-part finding (what/compared/differ/why/evidence/how/status) + calc + rule/version + citations + timeline | Record Decision | Missing evidence, insufficient rights, superseded | Understandable without logs/chat | NOT_STARTED |
| UX-11 | Quality/coverage/run-skipped/unresolved/firm/client/period/version/preview | Approve & Generate | Blockers, queued export, prior versions, failure | Explicit reviewer + time; immutable copies | NOT_STARTED |
| UX-12 | Invites/roles/language/firm/usage/plan/retention request | Invite Member | Expired invite, quota, denied | Short forms; safe deactivation | PARTIAL (members API exists; UI pending) |
| UX-13 | Source upload/metadata/drafts/tests/windows/approver/publish gate (hidden from tenants) | Submit for Approval | Unverifiable source, tests fail, denied, overlapping versions | AI cannot invoke publish | NOT_STARTED |

## Appendix E. Deterministic rule catalogs (P0 unless noted; TX gated on expert approval)
AQ-001 TB debit/credit equality (Σ debits vs Σ credits by currency/period, |delta|>tolerance → finding) · P0 secondary. AQ-002 missing required fields by row/column + refs · P0 secondary. AQ-003 invalid/out-of-period dates, never dropped · P0 secondary. AQ-004 exact canonical duplicate key match + all refs · P0 secondary. AQ-005 candidate invoice dupes (party + ref + amount/currency or reviewed similarity) → review candidate · P0 secondary. AQ-006 GL↔TB account-level closing balances, mapped, same period · P0 secondary. AQ-007 missing-mapping list; misleading aggregates forbidden · P0 secondary. AQ-008 invalid debit-credit pairs/nonnumeric/unexpected signs; no intent guessing · P0 secondary. AQ-009 invoice-vs-register totals where parser validated · P0 secondary. AQ-010 spreadsheet/PDF subtotal vs declared total, explicit currency/rounding · P0 secondary. ALL NOT_STARTED (engine absent; retained as regression track, not MVP bar).
TX-001 sales-vs-mapped-revenue (potential review only) · P0 gated. TX-002 purchases-vs-mapped-expenses + missing documents · P0 gated. TX-003 invoice tax-field presence/mismatch where verified · P0 gated. TX-004 period-treatment mismatch · P1 until expert-confirmed. TX-005 expense evidence gap (non-statutory; never deductibility conclusion) · P0 gated. ALL NOT_STARTED — BLOCKED on tax-expert approval + source versions (DEC-04). No output may assert evasion/violation/liability.
Severity (all catalogs): Critical (untrustworthy totals / isolation-security), High (material unexplained), Medium (suspicious/unsupported), Low (info). Stable per published version; severity is operational priority, NOT legal probability.

## Appendix F. Acceptance tests (normative; TB = secondary regression, recon = primary)
AT-001 isolation (B reads A's objects → nothing) — PARTIAL (IDOR matrix proven on existing list/get/patch/audit/member paths; download isolation untestable — no download endpoint exists). AT-002 full TB+GL E2E — retained secondary, NOT_STARTED (primary is ATR-001). AT-003 TB 10,250.375 vs 10,200.375 → 50.000 variance — NOT_STARTED. AT-004 balanced TB passes — NOT_STARTED. AT-005 blank/invalid amount → validation, never zero — NOT_STARTED. AT-006 ambiguous `01/02/2026` blocks affected checks — NOT_STARTED. AT-007 JOD+USD never combined — NOT_STARTED. AT-008 idempotent rerun (same key → same output, no double bill) — PARTIAL (queue proven; API idempotency pending). AT-009 source replace → stale + old report immutable — NOT_STARTED. AT-010 draft TX unpublishable/unrunnable — NOT_STARTED (gate specified). AT-011 2026-rule skipped on 2024 engagement — NOT_STARTED. AT-012 unknown section withheld, no fabrication — NOT_STARTED. AT-013 injection PDF ignored — NOT_STARTED. AT-014 propose-vs-finalize roles — PARTIAL (RBAC proven; decisions absent). AT-015 post-approval change → new version — NOT_STARTED. AT-016 RTL + AR PDF — NOT_STARTED. AT-017 abuse files rejected/quarantined — NOT_STARTED (JSON caps proven; file types pending). AT-018 unacked high blocker → 409 + list — NOT_STARTED. AT-019 LLM outage leaves financial checks valid — NOT_APPLICABLE until a provider exists (fallback contract specified). AT-020 deletion manifest + holds — NOT_STARTED.
ATR-001 E2E recon (3-source → mappings → REC-001..005 → decisions → bilingual report, no manual DB) — NOT_STARTED. ATR-002 both-direction unmatched — NOT_STARTED. ATR-003 ambiguous, no many-to-one — NOT_STARTED. ATR-004 dupes separated — NOT_STARTED. ATR-005 credit/correction honored — NOT_STARTED. ATR-006 incl/excl compatible-only — NOT_STARTED. ATR-007 GL-mapping diffs skip + listed — NOT_STARTED. ATR-008 incomplete coverage → NOT RUN — NOT_STARTED. ATR-009 JoFotara version gating — NOT_STARTED. ATR-010 missing-GL partial run — NOT_STARTED. ATR-011 reuse/drift + history — NOT_STARTED. ATR-012 cost/timing without financial contents — NOT_STARTED.



## Appendix G. Jurisdiction requirements FR-JUR-001..011 (normative; P0 foundation, AE/SA non-executable)
| ID | Capability | Preconditions | Input → Output | Acceptance | Verification | Status |
|---|---|---|---|---|---|---|
| FR-JUR-001 | Catalog + pack registration | None | ISO code + names + status + manifest → registered entry | JO ACTIVE (approved caps only); AE/SA PLANNED with zero executable rules; planned never offers RUN | Contract + unit | NOT_STARTED — BLOCKED on v2 approval |
| FR-JUR-002 | LegalEntity + presences | Tenant member + client | entity/presence CRUD → scoped records | One client holds JO+AE+SA without mixing; Dubai presence on JO entity creates presence, not entity | Integration JUR-01 tests | NOT_STARTED — BLOCKED |
| FR-JUR-003 | Obligation profiles + registrations | Entity or verified group, same tenant | profiles + encrypted registrations | One entity holds VAT+CT with distinct numbers; numbers encrypted/masked, never in logs/URLs | Security + integration | NOT_STARTED — BLOCKED |
| FR-JUR-004 | Tax groups explicit-only | Same tenant/portfolio/jurisdiction/tax-type/dates | group + dated memberships | Common ownership never auto-creates groups; overlaps rejected | Unit + integration | NOT_STARTED — BLOCKED |
| FR-JUR-005 | TaxContext create/confirm/freeze | Validated subject + jurisdiction + type + period + profile version + confirmer | immutable context_hash + revision | Post-execution edits create new revision; unissued findings supersede; issued reports immutable | Integration + E2E | NOT_STARTED — BLOCKED |
| FR-JUR-006 | Engagement scoping (one review = one context) | Validated context | engagements require tax_context_id for tax work | Mixed-country single execution impossible; legacy JO drafts need explicit confirmation (never silent rewrite) | Contract + E2E | NOT_STARTED — BLOCKED |
| FR-JUR-007 | Pack-gated resolution, no fallback | Resolved context | eligible rules or explicit skip reasons | AE/SA return JURISDICTION_NOT_SUPPORTED with 0 executions via API AND worker | Unit + integration + worker tests | NOT_STARTED — BLOCKED |
| FR-JUR-008 | Context-aware docs/evidence/reports | Executed review | entity/context/jurisdiction/profile/pack versions on artifacts | Provenance reconstructable per context; reports print entity/jurisdiction/type/period/currency/skips | Integration | NOT_STARTED — BLOCKED |
| FR-JUR-009 | Context-aware RAG contracts (with EP-16) — P0 covers the filter **interface** (jurisdiction + tenant + effective-period parameters on search/answer contracts); actual EP-16 retrieval implementation and its bench are **P1** and must never block Jordan deterministic REC-001..005 nor trigger any AE/SA runtime | Question + context | jurisdiction/period/tier/tenant-filtered retrieval + answers | JO→JO sources only; cross-border labeled per jurisdiction + qualified review | Interface contract tests (P0) + retrieval bench (P1, EP-16) | NOT_STARTED — BLOCKED |
| FR-JUR-010 | Tax & Countries UX + review-start selector | Client with entities | JO one-click confirm; progressive multi-country disclosure; planned cards without RUN | Empty/loading/validation/saved/unsupported/denied states; one CTA; keyboard; AR/EN RTL | E2E | NOT_STARTED — BLOCKED |
| FR-JUR-011 | Per-pack activation gates | Candidate pack | sources/expert/windows/formats/fixtures/migration/tenancy/RAG/reports/locale/signoff/rollback/flag checklist | Revenue never auto-activates; AE checklist (FTA VAT+CT) then SA (ZATCA/FATOORA) | UAT + security/legal | NOT_STARTED — BLOCKED |

## Appendix H. Epics, decisions, knowledge tasks
EP-01 foundation ✅ IMPLEMENTED (merged `c0d5e94`). EP-02 auth/tenancy ✅ IMPLEMENTED (merged `c8db3c6`). EP-03 workflow PARTIAL (clients done; engagements + dashboard depth pending). EP-04 uploads NOT_STARTED. EP-05 mapping NOT_STARTED (profiles P0 specified). EP-06 financial core NOT_STARTED. EP-07 rule engine NOT_STARTED (REC prioritized over AQ). EP-08 knowledge registry PARTIAL (specified; pipeline absent). EP-09 AI adapter PARTIAL (guardrails specified; redacted-logging pattern exists). EP-10 findings NOT_STARTED. EP-11 reports NOT_STARTED. EP-12 security/ops PARTIAL (hygiene + isolation + audit + CI gates done; backups/drills/branches pending). EP-13 usage NOT_STARTED (basic telemetry specified). EP-14 UAT NOT_STARTED. EP-15 JoFotara+REC NOT_STARTED (BLOCKED samples DEC-10). EP-16 Intelligence Engine P1 NOT_STARTED (KIE-01..08 specified in #17; shared contracts per §8). EP-17 jurisdiction P1-spec NOT_STARTED (JUR-01..04 blocked on v2 approval).
DEC-01 templates/fixtures OPEN (pre-Sprint 2). DEC-02 retention/roles/transfers OPEN (pre-real-data). DEC-03 hosting + AI subprocessor OPEN (pre-real-data). DEC-04 recon/TX targets + sources OPEN (pre-enable). DEC-05 quotas OPEN (pre-pricing). DEC-06 blocker/SoD OPEN (pre-approval-impl). DEC-07 AR typefaces OPEN (pre-report). DEC-08 payment route OPEN (pre-paid-pilot). DEC-09 scan-vs-digital OPEN (pre-OCR). DEC-10 JoFotara profiles OPEN (pre-REC). DEC-11 AI provider ADR OPEN (pre-AI-prod). DEC-12 residency ADR OPEN (pre-pilot). DEC-13 repo classification OPEN (pre-real-data). DEC-14 single-master approval of this document OPEN (this PR).

## Appendix I. Disposition map (every intentional change/deferral; PO decisions pending where noted)
| Old ID / statement | New disposition | Rationale / controlling decision |
|---|---|---|
| FR-FILE-002 P0 (broad PDF/OCR) | P1 | Recon-first: Sales+JoFotara+GL cover MVP (PO direction) |
| FR-EXT-010 P1 (reusable profiles) | P0 | Onboarding cost + JoFotara variance require reuse (PO direction) |
| AQ-001..010 as commercial core | Secondary regression track | REC-001..005 are the commercial P0 (PO direction) |
| TX rules P0-expert | Unchanged gate | Math recon ≠ legal interpretation; expert gate stands |
| Full RAG QA / narrative / classify / anomaly / OCR as P0-assist | P1 (EP-16 workstream) | MVP valuable provider-free (PO direction) |
| FR-USE-006 card billing P0-conditional | P1 | Safe pilot without auto-billing (PO direction) |
| Single `country` column thinking | Replaced by §6 eight objects | EP-17 approved direction |
| `UNIQUE(context_hash)` global; hash of subset (ERD) | Corrected §6: UUID PK, tenant-scoped unique, hash over full canonical frozen snapshot | PR #33 review + follow-up |
| `REVOKE UPDATE` immutability (ERD) | Corrected §6/§11: ExecutionSnapshot vs append-only run-status | PR #33 review + follow-up |
| Backfilled verified JO obligations (ERD) | Corrected §6: UNKNOWN default + explicit confirmation + accounting-only scope | PR #33 review |
| Foreign-txn ⇒ document mismatch (draft) | Corrected §7: preserve + review-route; reject only ownership/conflict | PR #33 review |
| Group admin/eligibility in MVP (draft) | Deferred past JO happy path | PR #33 review; model retained |
| Catalog ACTIVE = rule approval (draft) | Corrected §9 per-capability gates | PR #33 review |
| Plaintext-adjacent registrations (draft) | Corrected §6/§10 encryption design | PR #33 follow-up |
| Amendment as second normative source | Demoted to history (§0.1) | Single-master policy (PO checkpoint) |
| ADR-003/ERD/OpenAPI as decided contracts | Supporting only; JUR-01/02 code blocked | This review round |
| 8-week firm launch | Replaced by §15 phased estimate | PO direction |
| AT-002 TB+GL as primary E2E | Demoted; ATR-001 recon primary | PO direction |
| FR-ID-003 password reset as “done” | Corrected: NOT_STARTED, B-11 | Review: Sprint-1 slice has no reset flow |
| FR-FILE-007 quarantine as “done” | Corrected: NOT_STARTED (JSON caps only) | Review: file types absent |
| “Redis durable queue” (§11 line) | Corrected: worker-crash-only, prod blocked #35 | Review factual fix |
| “No CI run for this docs change” (§18) | Corrected: CI runs on every PR head (this head's run ID cited on push) | Review factual fix |
| “See §22” classification pointer | Corrected to §10 / DEC-13 | Review factual fix (no §22 exists) |
| BFF in-memory IP throttle (prior correction) | REMOVED (not kept) | Review R1: untrusted without proxy config |
No other ID is dropped, renamed, or reprioritized. Any ID absent from Appendices C–H is a defect in this draft — the verifier enforces zero unexplained absences.


*END OF TAXPILOT MASTER SRS v2.0 UNIFIED DRAFT — pending PO approval (DEC-14). No JUR-01/02 coding, no production processing, all gates intact.*


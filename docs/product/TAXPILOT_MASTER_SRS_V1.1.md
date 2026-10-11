# TAXPILOT JORDAN — Master Software Requirements Specification v1.1
**Reconciliation-first, accountant-focused SaaS | Jordan | JOD | Arabic/English**

| Field | Value |
|---|---|
| Version | 1.1 (reconciliation-first baseline; supersedes v1.0 for MVP priority) |
| Issue date | 2026-10-09 (draft for PO approval; DO NOT build scope-dependent features until approved) |
| Authority | Product Owner (approved direction change); Tech Lead, Jordanian tax expert, Legal/Privacy counsel (pending sign-off per §25) |
| Repository | https://github.com/tamerabuhalaweh/TaxPilot |
| Canonical file | `docs/product/TAXPILOT_MASTER_SRS_V1.1.md` (this file — complete replacement baseline, not a change summary) |
| Superseded | `docs/product/superseded/TaxPilot_Jordan_Master_SRS_v1.0.docx` retained verbatim. Full v1.0 text (434 paragraphs, 41 tables) was extracted and compared for §28. |
| Classification | Internal / confidential |
| Priority key | P0 = controlled-MVP required; P1 = conditional/post-pilot; P2 = excluded. P0 deferral needs documented scope decision + PO approval. |
| Language | SHALL = mandatory for its priority; SHOULD = preference; MAY = optional. |

> Critical: v1.0 architecture remains sound; v1.1 corrects MVP priorities to solve a real expensive firm problem first. Preserve what is valuable, revise what is misprioritized, avoid duplicating work. No scope-dependent coding until PO approves this baseline (§15 in instruction).

---
## 1. Document governance, versioning, and change history
**Owner:** Product Owner / Founder. **Approvals:** Technical Lead (arch/feasibility/security), qualified Jordanian tax expert (per-TX-rule logic/sources/applicability), QA Lead (acceptance plan), Legal/Privacy counsel (terms/processing/retention).
**Change control:** record change ID, sections affected, UX/API/schema/test/tax/rollout impact before implementation. Implementation artifacts (OpenAPI, migrations, designs, ADRs, tests, issues) derive from this SRS, not independent authority. Official source pages are references, never blanket approval for rates/treatments. Security + accounting correctness beat convenience; raise a decision rather than assuming.
**History:**
- v1.0 (2026-10-09): AI-assisted tax audit & compliance review; 99 FRs, 13 screens, 15 checks (AQ/TX), 23 entities, 31 APIs, 20 ATs, 8-week launch plan.
- v1.1-draft (2026-10-09): reconciliation-first per PO instruction §§1–17. New P0: Sales Register + JoFotara file import + GL recon (REC-001..005); reusable mappings P0; TB demoted to supporting; broad PDF/OCR→P1; RAG/narrative/anomaly→P1; tax-return conditional P0; telemetry + unit-economics + liability + data-residency ADR gates; 16-week estimated runway (8+4+4); new EP-15 JoFotara ownership; primary E2E rewritten. See §28 traceability.
**Reading guide:** §§2–4 vision/commercial/goals; §§5–8 users/MVP/journey/screens; §§9–12 functional/JoFotara/mapping/recon; §§13–14 tax/AI; §§15–18 arch/data/API/security; §§19–21 perf/tests/reports; §§22–24 commercial/epics/plan; §§25–28 gates/risks/AT/traceability.

## 2. Executive summary and product vision
**New positioning (replaces v1.0 §1.1):** TaxPilot Jordan is an AI-assisted tax reconciliation and financial review platform that enables Jordanian accounting firms to compare accounting records, sales registers, and government e-invoice exports, identify discrepancies, investigate supporting evidence, and generate accountant-ready reconciliation reports.
**Promise:** accountant signs in → selects/creates client → starts tax review → uploads accounting + e-invoice exports → confirms mappings/quality → runs automated reconciliation → investigates → confirms/dismisses/documents → generates PDF/XLSX — with no knowledge of AI/engineering/DB.
**Principles (non-negotiable):** accountant-first simplicity; deterministic calculations; accurate import/mapping; traceable evidence; human-controlled conclusions; strict isolation; versioned validated rules; safe AI boundaries; AR/EN; modular maintainability; test-driven correctness; commercial MVP focus; no premature microservices; no hidden tax-law assumptions; code-compile ≠ done.
**What it is NOT:** ERP replacement, tax authority, return submitter, gov-portal automator, legal adviser, fraud determiner, amendment filer, multi-country engine (Jordan only in MVP), mobile-native app, BI suite.

## 3. Commercial positioning and competitive alternatives
**Competes against:** manual Excel reconciliations, accounting-system-native checks, Caseware IDEA, DataSnipper, MindBridge, other audit/data tools.
**Differentiation hypothesis (to validate, not established):** Jordan-specific workflows + JoFotara reconciliation + AR/EN + easy onboarding + source-linked evidence + much faster report prep.
**Discovery (target 10–15 Jordanian firms):** firm size, buyer, current recon process, accounting software, JoFotara workflow, monthly volume, manual hours/engagement, repeated problems, willingness to pay, security concerns. Seek 3 paid pilots as validation target; never represent unsigned interest as paid demand.
**Buyer:** firm Owner (confidentiality/efficiency/cost/oversight); users: Admin, Accountant (fast workflow, few false alarms), Reviewer (evidence/versions/accountability), Viewer (clarity, no edits). Platform: Tax Rule Publisher (validity/periods), Operator (uptime, no default content access).

## 4. Business goals and success metrics
| Outcome | Pilot measure | Target / condition (hypothesis) |
|---|---|---|
| Adoption | activated firms, WAU, completed engagements | 3–5 design partners; 3 paid pilots (goal, not guarantee) |
| Time saved | median equivalent-task time vs baseline (mapping + recon + report) | 30–50% reduction hypothesis to validate, not marketing |
| Evidence integrity | REC findings with navigable evidence | 100% |
| Financial correctness | golden recon + arithmetic fixtures | 100% must pass |
| Isolation | cross-tenant tests | zero unauthorized reads/writes/downloads |
| Trust | FP rate per rule, acceptance, reassessment | measured per rule/input; no blanket accuracy promise |
| Coverage | % records/amounts reconciled vs skipped | reported with denominator; never a compliance score |
| Unit cost | compute+AI+storage+support per engagement | measured; breakeven modeled (§22) |
Telemetry in §22; no customer financial contents in analytics events.

## 5. Personas and user roles
| Persona | Job | Concern |
|---|---|---|
| Owner | clients/team/plan/portfolio | confidentiality, efficiency, cost |
| Admin | users/engagements/config | controlled access |
| Accountant | upload/correct/map/run/draft | speed, useful findings, low FP |
| Reviewer | validate/approve | evidence, versions, accountability |
| Viewer | read permitted items | clarity, no edits |
| Tax Rule Publisher (platform) | curate sources, publish expert-approved rules | validity, periods |
| Operator | uptime/subs/incidents | no default content access |
**RBAC (firm-side, backend-enforced; UI hiding ≠ security):** create/edit client, create engagement, upload/map/correct, run/rerun, comment/triage: Owner/Admin/Accountant/Reviewer Y, Viewer N. Confirm/dismiss: Owner/Admin/Reviewer Y (Owner/Admin only if assigned approval perm; SoD configurable/encouraged), Accountant proposes only, Viewer N. Approve report: Reviewer/designated Owner Y, Accountant/Viewer N. Download authorized report: all assigned Y. Invite/manage: Owner/Admin. Billing config: Owner/Admin (Admin restrictable). Delete/export tenant data: Owner only. Publisher separate + independent approver. Support: no blanket access; break-glass scoped + expiring + audited. Assignment never expands beyond membership.

## 6. Revised MVP and explicitly deferred features
**P0 (controlled MVP):** email auth, team invites, tenant workspaces, RBAC, sessions; client + date-bounded review workflow + immutable history; private CSV/XLSX for Sales Register + JoFotara Excel + GL (+ TB supporting); reusable mapping profiles + validation preview + schema-drift handling + mapping-time telemetry; deterministic REC-001..005 + supporting AQ checks (regression, not commercial focus); evidence-linked findings + decisions/comments/approvals; bilingual PDF/XLSX recon reports; audit history, usage/cost telemetry, job progress/recovery; AR/EN RTL; security/privacy/residency gates (§18); discovery + pilot-runbook + DPA/terms review gates.
**Conditional P0 (needs format + fields + basis + expert before enabled):** sales-tax-return import/recon. Do not fabricate schemas/formulas.
**P1 (defer):** broad PDF extraction, scanned OCR, bank templates, advanced narrative explanations, broad RAG QA, semantic classification, anomaly models, sophisticated quotas/plan UI/auto-billing (basic telemetry P0), TX-004 period-treatment until expert-confirmed, threshold customization, status page, custom dashboards, workflow assignment extras, export customization extras, multi-JoFotara-version breadth beyond validated profiles.
**P2 (excluded):** autonomous filing, gov-credential collection/storage, gov API integration, legal advice, fraud determinations, auto-amendments, mobile-native, multi-country (ZATCA/FTA), auto book edits/journals, bespoke model training, autonomous source updates, dark-mode gate, benchmarking, hidden second AI in rules.

## 7. Core user journey and UX principles
**Flow:** Dashboard → New Review → Upload → Map & Validate → Reconcile → Review Findings → Report.
| Step | Intent | System gate |
|---|---|---|
| Sign in | enter workspace | auth + tenant ctx, action-first dashboard |
| Client | find quickly | tenant-scoped search or minimal create (name + optional ID/sector) |
| Start review | period + type | validate dates; warn duplicate same-period; Draft |
| Upload | attach Sales + JoFotara + GL | validate file; per-doc progress/type; required vs optional per check |
| Map & validate | confirm interpretation | mapping preview + row errors + quality summary; block recon until required approved |
| Reconcile | run REC-001..005 | idempotent job; eligible-only + skipped list (NOT RUN — INSUFFICIENT INPUT) |
| Investigate | understand/resolve | what/compared/differ/why/evidence/how-to-review/status |
| Approve/export | issue paper | perm + blockers cleared; immutable version |
**States:** Engagement DRAFT→DOCUMENTS_UPLOADED→PROCESSING→REVIEW_REQUIRED→UNDER_REVIEW→READY_FOR_APPROVAL→APPROVED→CLOSED; FAILED→retry→PROCESSING (no fresh engagement); DOCUMENTS_UPLOADED→DRAFT only pre-processing; post-approval source change → new revision, never silent mutate; invalid→409 STATE_CONFLICT. Job QUEUED→RUNNING→SUCCEEDED|FAILED|CANCELLED (progress/retries/error class; retry = new attempt, no dup datasets/findings; timeout≠success). Finding OPEN→UNDER_REVIEW→CONFIRMED_ISSUE|NOT_AN_ISSUE|NEEDS_MORE_EVIDENCE→RESOLVED; SUPERSEDED on input/rule change; append-only decisions; confirmed discrepancy ≠ legal violation.
**Exceptions:** unsupported file (explain + template, no phantom job); missing data (identify sheet/field; blocked = Not run); failure (explain retry, preserve files, no double charge); no findings (list checks run; never claim compliant); conflicting version (stale + rerun required); insufficient source (Unable to verify + manual route).
**UX north star:** nontechnical accountant; one primary action/view; direct language; predictable transitions; short forms; no mandatory AI chat; no decorative overload; always-visible next step; modern accounting SaaS, not ERP. Light-first, navy/teal restrained, 8px scale, design-system components, locale-correct numbers/dates (store semantics unchanged; preserve AR/Latin numerals), keyboard + focus + semantics + no color-only + SR alerts, RTL reverses layout but preserves account/invoice/URL/sign direction, async in-progress + no double-submit + no fake %, progressive disclosure, no placeholder buttons as working, no internal model jargon, traceability without clutter. Wireframes before major frontend build.


## 8. Screen-by-screen UI specifications
**Routes:** `/app` Dashboard; `/app/clients`, `/app/reviews`, `/app/reports`, `/app/settings`; `/app/reviews/{id}` workspace (Upload, Map, Reconcile, Findings, Report tabs); `/internal/...` restricted (sources/rules/ops, no firm nav).
**UX-01 Login/Reset:** email+password, show/hide, reset, locale switch, session errors. Primary: Sign in. States: signing, invalid, unverified, expired link, session-expired. Accept: no tenant data pre-login; labels; no enumeration.
**UX-02 Dashboard:** active reviews, awaiting action, unresolved high-priority, recent completions + recent table. Primary: New Review. States: first-use empty, no clients, API error, skeleton. No decorative charts; date period on counts.
**UX-03 Clients:** searchable table (name/sector/owner/active/last) + drawer add. Primary: Add Client. States: none, no results, duplicate, save fail. Min fields only.
**UX-04 Client Detail:** summary/profile/engagements/docs grouped. Primary: Start Review. States: none, archived, denied. Tenant-scoped; report history.
**UX-05 New Review (v1.1 recon):** short form client + period + type (+assignee optional) then three upload sections: Sales Register (required for REC-001/002/003/005), JoFotara Export (required for REC-001/002/003/004), GL (required for REC-005; optional otherwise). Each section states required vs optional per check. If only 2 sources, run eligible + list skipped. Primary: Create Review. States: validation, invalid dates, duplicate-period warning. One form, not wizard.
**UX-06 Upload & doc list:** drag/drop per-type labels, status, size progress, retry, replace-with-new-version. Primary: Continue to Data Check. States: unsupported, virus, encrypted, duplicate, interrupted. Show formats + limits (25MB/file, 100 PDF ppITT, 100k rows/file configurable) before upload. JoFotara section lists supported export profiles/versions; unsupported version → actionable guidance + sample request.
**UX-07 Map & Validate (spreadsheet-like):** columns: Original column | Mapped TaxPilot field | Sample values | Validation result | Correction action. Preview 20 rows, invalid markers, totals + source links. Primary: Confirm Dataset. States: ambiguous headers, missing debit/credit-equivalent, currency/date issue, partial extraction, schema drift (saved profile mismatch → confirm critical diffs). Never treat AI suggestion as approved. Must show raw/normalized/corrected; never silently rewrite.
**UX-08 Reconcile/Results:** timeline (extract→validate→match→evidence) + progress; summary: records processed, matched, unmatched, amount differences, duplicate candidates, checks skipped, items needing attention. Match % states denominator + coverage; not a compliance score. Skipped: “Not checked: JoFotara export is missing.” / “NOT RUN — INSUFFICIENT INPUT”. States: queued, delayed, provider n/a (AI optional), partial, none runnable. Bounded auto-refresh + static accessible status.
**UX-09 Findings list:** filters category/severity/status/assignee; counts + affected amounts per currency + evidence availability. Primary: Open Finding. States: none, insufficient source, stale, loading/error. No composite risk score unless defensible.
**UX-10 Finding detail (7-part):** (1) what detected, (2) records compared, (3) values differing, (4) why flagged, (5) source records, (6) how to review, (7) confirmed/dismissed status. Shows calc, highlighted rows/pages, rule ID/version, citations (if tax), timeline. Primary: Record Decision (Confirm issue / Not an issue / Need evidence). States: missing evidence, insufficient rights, superseded. AI uncertainty + stale microcopy per §7.
**UX-11 Report/Approval:** quality, coverage, run/skipped, unresolved, firm/client/period/version, preview. Primary: Approve & Generate. States: blockers, queued export, prior versions, failure. Explicit reviewer + time; immutable copies.
**UX-12 Team & Settings:** invites/roles/language/firm/usage/plan/retention request. Primary: Invite Member. Short forms; safe deactivation; usage bars + limit explanations (basic in MVP).
**UX-13 Internal console:** source upload/metadata/drafts/tests/windows/approver/publish gate. Primary: Submit for Approval. Hidden from tenants; AI cannot publish.
**Microcopy:** success “Review created. Upload financial documents to begin.”; no-findings “No issues were detected by the checks completed. This does not confirm tax compliance.”; skipped “Not checked: … is missing.”; AI “This explanation could not be verified against an approved source. Please review manually.”; stale “This finding was generated from an earlier document version. Run the checks again.”; reject “This file could not be read. Upload CSV, XLSX or a supported JoFotara Excel profile (limits shown above).”; denied “You do not have permission to approve this review. Ask a firm reviewer or administrator.”

## 9. Functional requirements and priorities
Every row testable; IDs stable in issues/PRs/tests. All P0 backend-enforced + UI unless internal-only. Each P0 below lists module, preconditions/deps, I/O, acceptance, verification, epic.
### 9.1 Identity, sessions, tenancy (EP-02)
- FR-ID-001 P0 User register via verified email + secure password / approved managed identity. Mod: Identity & Tenancy. Pre: none. In: email+credential. Out: unverified user. Accept: unverified cannot access tenant data; dupes safe. Ver: integration/UAT. Epic EP-02.
- FR-ID-002 P0 Secure sessions + revocation. Accept: logout invalidates; expiry re-auths. Ver: integration/security. EP-02.
- FR-ID-003 P0 Single-use expiring reset, no enumeration. Accept: no reuse; unknown→neutral. Ver: security. EP-02.
- FR-ID-004 P0 Authorize every endpoint (user/tenant/role/assignment). Accept: IDOR→403/404 no leak. Ver: security. EP-02.
- FR-ID-005 P0 Invite/deactivate/manage (Owner/Admin). Accept: expiry; removal revokes. Ver: integration. EP-02.
- FR-ID-006 P0 Tenant-scope all records/queues/files incl. derived. Accept: negative tests on search/download/jobs/evidence/exports. Ver: security. EP-02.
- FR-ID-007 P0 Rate-limit login/invite/reset. Accept: abuse sim blocked. Ver: security. EP-02.
- FR-ID-008 P1 MFA for privileged; SSO MAY later. Ver: if delivered. EP-02.
- FR-ID-009 P0 No blanket support access; break-glass scoped/expiring/audited. Ver: security/UAT. EP-02.
### 9.2 Firm, client, engagement (EP-03)
- FR-WRK-001 P0 Isolated workspace + membership + usage policy. Accept: provisioning creates tenant+owner invisibly. EP-03.
- FR-WRK-002 P0 Create/search/edit/archive clients (IDs tenant-unique). Accept: tenant search; archive preserves history. EP-03.
- FR-WRK-003 P0 Optional business/tax ref/sector/contact/owner. Accept: missing optionals don't block draft. EP-03.
- FR-WRK-004 P0 Engagements (client/period/type/staff). In: `{client_id,period_start,period_end,type}` →201 `{id,status:DRAFT}`. Accept: end<start rejected; stable ID. EP-03.
- FR-WRK-005 P0 State machine + actor/time (§7). Accept: invalid→409; history prior/new. EP-03.
- FR-WRK-006 P0 Dashboard readiness/rule counts/findings/status match stored jobs/results + tenant filter. EP-03.
- FR-WRK-007 P0 Assignment never expands beyond membership. EP-03.
- FR-WRK-008 P1 Branding/preferred mappings versioned (new reports only). EP-11.
### 9.3 File ingestion/storage (EP-04 + new EP-15)
- FR-FILE-001 P0 UTF-8 CSV + XLSX; explicit unsupported-encoding error. EP-04.
- FR-FILE-002 P1 (was P0; RATIONALE: recon-first; broad text-PDF + scanned OCR deferred; JoFotara Excel + registers cover MVP) Text-PDF limited; scanned beta until evaluated. EP-04.
- FR-FILE-003 P0 MIME/sig/ext/size/integrity/archive-risk validation; mismatch/bomb rejected. EP-04.
- FR-FILE-004 P0 Configurable limits 25MB/100pp/100k rows server-enforced; exceed→413+limit; no-code change. EP-04.
- FR-FILE-005 P0 Private hash/metadata/immutable versions; replace→v2 lineage per policy. EP-04.
- FR-FILE-006 P0 User-confirmable classification (sales_register, jofotara_export, general_ledger, trial_balance, sales_return(if cond), other). AI guess correctable. EP-04/15.
- FR-FILE-007 P0 Malware scan where available; unscanned stay quarantined, never parser/download. EP-04.
- FR-FILE-008 P0 Visible state + resume/retry (Pending/Processing/Ready/Needs review/Failed). EP-04.
- FR-FILE-009 P0 Identical-content detect + reuse/version offer; no double-count. EP-04.
- FR-FILE-010 P0 Authorized short-lived links (≤15m proposed), no guessable keys/listing. EP-04.
- FR-FILE-011 P1 Bank/OCR templates after labeled validation. EP-04.
### 9.4 Extraction, mapping, validation (EP-05; FR-EXT-010 P1→P0)
- FR-EXT-001..009 P0 unchanged (parser version+loc+confidence; suggest-not-assume; raw/norm/corrected; flag ambiguous dates/currencies e.g. 01/02/2026; never silent zero; preview gate; stable versions; row counts; AI schema-validated + human review). EP-05.
- FR-EXT-010 P0 (was P1; RATIONALE: onboarding cost + JoFotara variance require reuse) Save reusable mapping profiles per client+doctype; application shows changes; still requires validation; version history; schema-drift → confirm critical diffs. Accept: reuse safe; drift blocked until confirmed. Ver: integration/E2E. EP-05.
- FR-MAP-TIME-001 P0 Record mapping/correction time per upload/profile for onboarding-cost metric (no financial contents in event). EP-05/13.
### 9.5 Financial normalization + checks (EP-06)
- FR-FIN-001..010 P0 unchanged (Decimal/NUMERIC+currency+quantization; debit/credit independent + reversals kept; TB tolerance check as supporting; mapped GL↔TB same-period/currency or skip (not fabricated); exact vs candidate dupes; versioned approved mappings; FX segregated; period flagged not deleted; inputs/version/tolerance/result recorded; missing→SKIPPED_INPUT_MISSING). EP-06. Note: TB checks retained as secondary regression; commercial focus is §12 REC.
### 9.6 Rule definition/publication/execution (EP-07; scope shift to REC)
- FR-RULE-001..008 P0 unchanged (immutable key/version/category/jurisdiction/logic/prereqs/severity/window; approved datasets + executed/skipped/failed/passed ledger; fixtures per P0 rule; tax needs named expert pre-publish; period/source-date respect; version-not-overwrite; isolate errors; possible-issue phrasing). EP-07.
- FR-RULE-009 P1 Threshold customization (firm-authorized + audit) unchanged. EP-07.
- FR-RULE-JUR-001 P0 Jurisdiction-keyed defs from start: `jurisdiction_code,rule_code,rule_version,effective_from,effective_to,tax_category,source_reference,approval_status`. Jordan only; no ZATCA/FTA in MVP; later jurisdictions must not corrupt Jordan history. EP-07.
### 9.7 AI services + knowledge (EP-08/09; complexity reduced)
- FR-AI-001..009 P0 retained as guardrails (allowed-only; adapter timeouts/retries/budgets; schema validation; cite source/section/period/link; abstain without source; untrusted inputs; deterministic figures; redacted traces/no raw bodies; no training by default + retention/transfer approval). EP-09. P0 scope: validation, deterministic recon, provenance, versioning, human review, uncertainty, AI security if external model used.
- FR-AI-010 P1 Benchmark (retrieval + AR reasoning) unchanged. EP-09.
- FR-AI-P1-001 P1 Advanced narrative explanations; FR-AI-P1-002 P1 Broad RAG QA; FR-AI-P1-003 P1 Semantic classification; FR-AI-P1-004 P1 Scanned OCR; FR-AI-P1-005 P1 Anomaly models. RATIONALE: MVP valuable with no AI provider; defer until proven useful. EP-09.
### 9.8 Findings/comments/review/approval (EP-10)
- FR-FND-001..009 P0 unchanged (lineage; dataset+loc evidence; explanation+calc+limits; reviewer confirm/dismiss/need-evidence append-only; accountant propose w/o bypass; stale/superseded blocks approval; filter/sort paginated tenant-scoped; explicit attributable approval + hash; highs disclosed, default blocks until acknowledged →409 APPROVAL_BLOCKED). Optimized for recon-difference review + ambiguous-match adjudication. EP-10. FR-FND-010 P1 assignments/macro MAY later.
### 9.9 Reports/exports (EP-11)
- FR-REP-001..007 P0 unchanged (summary/detail sections; PDF+XLSX + injection safety; immutable versioned + snapshot link; AI + no-compliance disclaimer; AR RTL rendering; perm + short-lived download). Primary output = bilingual reconciliation report distinguishing detected differences / confirmed issues / unresolved / missing evidence / skipped / limitations; clean result ≠ compliance guarantee. EP-11. FR-REP-008 P1 branding.
### 9.10 Subscription/cost/usage (EP-13; sophisticated→P1)
- FR-USE-001 P0 Plans + configurable quotas (seats/files/storage/processing/AI). EP-13.
- FR-USE-002 P0 Idempotent per-tenant usage (`tenant.usage_recorded`; retry no double). EP-13.
- FR-USE-003 P0 UI shows usage + pre-block explanation (quota/used/next). EP-13.
- FR-USE-004 P0 Expired restricts new work per policy, preserves agreed read/export; never silently delete. EP-13.
- FR-USE-005 P0 Manual pilot invoices MAY; status securely managed + audited activation. EP-13.
- FR-USE-006 P1 Card/recurring only after Jordan-approved provider (was P0-conditional; RATIONALE: pilot-safe without auto-billing). EP-13.
- FR-USE-007 P0 AI/compute cost observable per tenant + aggregate, no raw docs. EP-13.
- FR-TEL-001 P0 Telemetry events (upload success, correction time, time-to-first-recon, completion time, useful findings, FP per rule, coverage, cost/engagement, feedback/renewal) without financial contents. EP-13/14.
### 9.11 Platform ops/auditability (EP-12)
- FR-OPS-001..006 P0 unchanged (async idempotent bounded jobs; audit actor/action/tenant/resource/time no secrets; health/queue/failure alerts; retention/deletion manifest; backed-up config + tested restore RPO≤24h/RTO≤8h; gated releases + smoke + SHA + rollback). EP-12. FR-OPS-007 P1 status page.
### 9.12 Traceability (all)
Every ticket refs FR-IDs + verification (unit/integration/E2E/UAT/security/tax-expert). Every P0 has owner + passing evidence. Open items stay open even if UI looks done. P1 cannot block P0 unless documented dependency.

## 10. JoFotara import requirements (EP-15 + EP-04/05)
- FR-JOF-001 P0 First-class `jofotara_export` doctype (Excel file-based ONLY). No gov API, no credential collection/storage, no assumed identical columns or full line details. Mod: Ingestion. Pre: approved sample profiles. In: customer Excel. Out: versioned dataset + profile match result. Accept: unsupported version → actionable guidance + profile list. Ver: integration/E2E + fixtures. Epic EP-15.
- FR-JOF-002 P0 Supported format profiles: obtain representative authorized samples; establish narrow tested mappings first; generic parsing forbidden until validated. Each profile: issuer scope, columns, types, version marker, sample hash, known limitations. Accept: only profiled versions auto-map; others route to review. EP-15.
- FR-JOF-003 P0 Preserve issuer/seller context + invoice identity (number + issuer/scope key, not number alone); handle duplicate numbers across issuers. Accept: no cross-issuer false matches. EP-15/06.
- FR-JOF-004 P0 Corrections/credit notes/returns/cancellations/reversals honored where source permits; never silently drop. Accept: correction fixtures pass. EP-15/06.
- FR-JOF-005 P0 Incomplete coverage explicitly identified (gaps, date ranges, missing sequences) → affected checks NOT RUN — INSUFFICIENT INPUT. Accept: coverage report per import. EP-15/07.
- FR-JOF-006 P0 Tax-return import (sales tax return data) conditional P0: needs supported format + required fields + recon basis + expert approval before enabled; no fabricated schemas/formulas. Accept: disabled until all four evidenced. EP-15.
- Security: JoFotara files follow FR-FILE-003/007 quarantine + tenant-private storage + short-lived links; no cross-border claim without ADR.

## 11. File mapping and data normalization (EP-05)
Pipeline: RECEIVED→QUARANTINED→VALIDATED→CLASSIFIED→EXTRACTED→MAPPING_REQUIRED→NORMALIZED→READY_FOR_CHECKS (FAILED anywhere non-terminal). Friendly UI labels; explicit enum; CPU/mem/time caps; no macro/script eval.
Conventions: money = original string + Decimal + currency (≥orig precision; JOD display typically 3dp; tax rounding separately approved); debit/credit nonnegative separate where supported, corrections keep sign; TB sign needs explicit rep+mapping (no string-match class); tolerance default zero, per-rule/currency logged, tax tolerance expert-approved; dates ISO DATE (periods) / UTC (activity) / Asia/Amman display, orig text kept, ambiguous numerics need confirmation; currency ISO4217, unknown blocks aggregates, JOD/USD/EUR separate unless sourced FX + approval; IDs keep leading zeros (never int); blank≠zero≠malformed≠N/A; raw retained, corrections = immutable revision + author/time/reason.
Canonical sales/JoFotara/GL fields (profile-dependent; examples): `source_invoice_no, issuer_id/issuer_name, invoice_date, buyer_id/buyer_name, line_no, quantity, unit_price, net_amount, tax_amount, gross_amount, tax_inclusive_flag, currency_code, invoice_status (original/corrected/cancelled/credit_note), gl_account_code, posting_date, debit_amount, credit_amount, document_number, description`. Only compare available + semantically compatible fields.
Mapping behavior (§5 instruction): first upload detect→suggest→preview→require approval for uncertain/critical→validate dates/numerics/accounts/currencies→allow save profile. Later: detect compatible profile→reuse where safe→detect schema drift→require confirm on critical diffs→preserve version history. Show raw/norm/corrected; never silently rewrite; track mapping time.
Dedup: exact = same tenant/engagement/type/source-identity + normalized financial/date excl. row pos (deterministic); candidate = issuer+number+date+amount/currency subset or reviewed similarity (always review-required). Cross-file dupes ≠ wrongdoing.

## 12. Reconciliation rules and matching semantics (EP-07 + EP-15; AQ retained secondary)
**P0 commercial catalog:**
- REC-001 Sales Register → JoFotara: sales txns lacking JoFotara counterpart. Needs: sales + JoFotara approved mappings + period/currency scoping.
- REC-002 JoFotara → Sales Register: JoFotara invoices lacking sales counterpart.
- REC-003 Matched amount/field differences: for reliably matched records compare net/tax/gross + inclusive/exclusive presentation + currency + rounding. Only available + compatible fields; explicit tolerance/version in evidence.
- REC-004 Duplicate candidates: exact invoice identities + possible duplicate postings; deterministic vs heuristic separated; suspicious ≠ fraud/evasion.
- REC-005 Sales Register → GL: normalized mapped sales totals vs corresponding GL amounts with account mappings, periods, currencies, adjustments, tolerances.
**Matching MUST:** distinguish exact / unmatched / ambiguous / field-diff / unsupported; preserve issuer + identity; honor corrections/notes/returns/cancels where permitted; avoid many-to-one auto-match to same unique target; handle dup numbers across issuers/scopes; preserve originals + provenance; exact decimals; never silent zero; never silent cross-currency; surface timing/period diffs; record strategy + rule/jurisdiction version + tolerances + mapping versions; allow authorized ambiguous-match review + audit; flag incomplete coverage. Missing fields → NOT RUN — INSUFFICIENT INPUT, never unsupported discrepancy.
**Rule template (mandatory):** jurisdiction_code, rule_code, rule_version (semver/int), description/category, effective_from/to, applicability/preconditions (datasets/cols/attrs/mappings), algorithm/comparator (formula, sign, comparator, tolerance, group-bys, match keys + tie-breaks), severity/title, evidence contract (dataset IDs, refs, grouped totals, affected amounts), references (URL/section/issuance/effective/verified if tax), tests (11 cases §4 instruction), approvals (author, accounting reviewer, tax expert if tax, timestamp), lifecycle DRAFT→TESTED→EXPERT_APPROVED(tax)→PUBLISHED→RETIRED.
**Publication:** draft→auto tests→accounting review→tax review (if tax conclusion: required/permitted/disallowed/taxable/exempt)→publisher scope/dates→signed/published→dry-run fixtures→tenant enablement; reject→Draft. Model may suggest language, never approve/publish/broaden dates. Math recon alone ≠ legal interpretation; any tax-treatment conclusion needs expert gate; unapproved tax rule never runs as authoritative guidance.
**Secondary (regression, not MVP bar):** AQ-001 TB equality, AQ-002 missing fields, AQ-003 dates, AQ-004 exact dupes, AQ-006 GLvsTB, AQ-007 unmapped, AQ-008 invalid patterns, AQ-009 invoice-vs-register (if parser validated), AQ-010 subtotals; TX-001/002/003/005 only with written expert sign-off + dates; TX-004 P1. Preserved for financial hygiene; do not let them define MVP success.
**Fixtures per REC (11):** exact-match, unmatched-source, amount-mismatch, duplicate, ambiguous, missing-field, credit-note/correction, period-boundary, currency-mismatch, rerun/idempotency, traceability. Controlled golden fixtures with signed source rows.


## 13. Tax expert review and legal-source governance (EP-08)
Retain v1.0 gates: expert approval pre-publish; source verification; effective dates; versioning; reproducibility; citation integrity; uncertainty; non-autonomous decisions.
**Boundaries:** never infer rates/exemptions/deadlines/deductibles/withholding/thresholds/penalties from LLM/undated web. Each legal check: exact statute/section, applicability, period, calc, exceptions, samples + written sign-off. Where registration/sector/period/zone matters: collect verified metadata or mark N/A/needs-evidence. Account→revenue/expense mapping ≠ legal treatment. Finding text distinguishes input discrepancy vs possible treatment issue vs professional conclusion. Source changes never retro-alter approved results. JoFotara review from customer docs/exports only.
**RAG (P0 = registry + approval controls; full QA experiences P1):** (1) intake allowlisted official/approved-licensed only; (2) metadata URL/publisher/title/type/article/retrieval/issue/effective-start-end/lang/checksum/owner; (3) chunk by article/para, hierarchy + xref; (4) retrieve with Jordan + date + status + relevance (lexical + optional vector, never embedding-only); (5) compose only from verified passages + assumptions, abstain if insufficient; (6) validate claim→citation, log eval, link passage; (7) update → manual review queue, never auto-publish. Official refs (discovery only): ISTD Income Tax Law, GST legislation, E-Invoicing Billing_system (context, not integration auth), MoDEE PDPL Unit (Law 24/2023 eff. 2024-03-17) + FAQs — checked Oct 2026; expert retrieves current full text/amendments/regs/instructions + confirms version/applicability/dates pre-publish.
**Jurisdiction keys:** jurisdiction_code (JO initial), rule_code, rule_version, effective_from/to, tax_category, source_reference, approval_status. No SA ZATCA / AE FTA in MVP; arch must allow later jurisdictions without corrupting JO history.

## 14. AI architecture and permitted model behavior (EP-09)
Principle: deterministic engine calculates/detects; AI assists understanding/explanations; accountants decide.
**P0:** structured validation, deterministic recon, provenance, versioned rules, human review, explicit uncertainty, AI data-processing security if external model used. Minimal adapter may exist, but MVP valuable with NO provider configured.
**P1:** narrative explanations, broad RAG QA, semantic classification, scanned OCR, anomaly models.
**Allowed:** suggest doctype/header map; extract with page/row link; explain deterministic finding; retrieve/summarize verified passage; suggest anomaly for review; translate with review.
**Prohibited as authoritative:** silently change raw values; generate untraceable ledger numbers; override calc/amount/status; cite invented/unofficial as official; declare fraud/evasion/illegality/amount due; publish rules/submit returns.
**Boundary:** adapters get task-minimum fields; system denies admin/cross-tenant; retrieved/file text = data, never instructions/creds/DB/API refs; AI workers have NO perms to publish/approve/report/bill/file.
**Degradation:** AI down → deterministic + manual mapping work; only enrichment unavailable. Caps → retryable + clear message. Traced + schema-validated I/O, no sensitive logging. Suppress low-quality explanations pending review.
**Provider ADR (required):** compare approved-external vs self-hosted vs hybrid on AR quality, accuracy, inference/infra cost, hosting location, privacy/retention, ops complexity, exposure. Note: existing AI infra may offer reusable components, but no cross-project runtime dep without explicit ADR. Do NOT assume ASR ⇒ OCR.
**Gates:** zero failed golden arithmetic; zero invented citations in UAT (human-labeled); 100% machine-consumed AI objects schema-valid; 100% P0 findings have loc or explicit block; digital-text numeric accuracy ≥98% provisional (frozen corpus); scanned scored separately; FP per rule/class (no global threshold); AR usefulness via rubric.

## 15. Multi-tenant architecture and technical stack (EP-01)
Modular monolith + separately scaled workers (no premature mesh). Next.js UI; FastAPI APIs; PostgreSQL (tenant/business + source indexes); S3-compatible private storage; Redis durable queue (parse/match/report); AI adapters under data-use restrictions. Modules independently testable; ownership Table: Web (views/forms/i18n/cache; NOT authZ truth/tax calcs/secrets), Identity & Tenancy (sessions/RBAC/boundary; NOT accounting policy), Client & Engagement (profile/period/state; NOT parser/rules), Ingestion & Extraction (upload/validation/provenance/mapping; NOT legal treatment), Financial Core (canonical decimals/recon/mappings; NOT opaque AI balances), Rule/Recon Engine (versioned deterministic exec; NOT unverified legal claims/auto-publish), Tax Knowledge (source lifecycle/citations; NOT final approval), AI Adapter (prompts/calls/validation/caps; NOT DB admin/tenant-switch/financial decisions), Findings & Review (evidence/decisions/snapshot; NOT raw/rule mutation), Reports (immutable PDF/XLSX; NOT history rewrite), Subs (metering/quotas; NOT file deletion for nonpay), Ops (metrics/alerts/audit/support grants; NOT blanket file access).
Sequence: authorized upload→doc record + session→S3→quarantine→document.uploaded→worker extract (capped) + parser/OCR meta→preview→user approves mappings/corrections→dataset.ready→engine loads approved versions for period→deterministic calcs persisted transactionally→AI grounded summaries only→reviewer resolves→approval snapshot→report worker immutable PDF/XLSX→short-lived download.
Repo: `apps/web, apps/api, workers/ingestion, workers/reconciliation, workers/reports, packages/contracts (OpenAPI gen), packages/shared, db/migrations, rules/jordan (REC + AQ defs/tests), docs/product (+adrs/ux), tests/e2e, infrastructure/`. SRS authoritative even if code splits.
Conventions: TS strict + Py hints; lint/format; reviewed migrations; CI checks mandatory; no financial math in React (backend authoritative; frontend formats); typed adapters + timeout/retry/budget; no hardcoded keys; idempotent create/approve/report + DB uniqueness; exported Decimals as strings + schema version; migration rollback/forward path; no PII in telemetry/crash/issues. CI order: format/lint/typecheck→unit→integration/DB→golden recon→SAST/deps→build→staging→E2E smoke→approvals→prod→health. Immutable artifacts + SHA; flags disable unapproved tax rules/unsupported JoFotara profiles per tenant.
Envs: Dev (synthetic/masked only), Staging (synthetic or specially approved pilot + recovery validation), Prod (least privilege, encrypted backups, alerts, reviewed deploys).

## 16. Logical database model (EP-01/03/04/05/06/07/10/11/13/15)
Entities (mandatory core; UUID PKs; `tenant_id` on every tenant entity + composite-FK same-tenant check; NUMERIC for amounts + raw literal; UTC timestamps + DATE period bounds + Asia/Amman display; provenance chain doc→dataset→rulever→run→finding→report; uniques `(tenant,engagement,idempotency)`, `(rule jurisdiction,code,version)`, report version per engagement; approvals/reports immutable via revision/supersession; deletes leave minimal tombstone, no readable derived beyond policy):
Tenant, User, TenantMembership(tenant,user unique,role,status), Invitation(token_hash/exp), Client(tenant-unique, tax_ref_encrypted, sector/status; archive≠delete), Engagement(tenant/client/period/type/status/revision), EngagementAssignment, Document(tenant/engagement/kind[+jofotara_export]/filename/version/hash/storage_key/profile_id), ProcessingJob(tenant/engagement/type/state/attempts/idempotency/error), DatasetVersion(tenant/doc/schema/parser/state/hash), FieldMapping(dataset/source_header/canonical/approver), MappingProfile(tenant/client/doctype/columns/version/author/history) [P0-new], NormalizedEntry(tenant/dataset/source_row/date/account/debit/credit/currency) + SalesEntry/JoFotaraEntry/GLEntry extensions (issuer/invoice/amounts/status), Rule(key unique/jurisdiction/category/status/current_version), RuleVersion(rule/version/definition_json/valid_from-to/approver/jurisdiction_code/tax_category/source_ref), RuleRun(tenant/engagement/rule_version/dataset_set_hash/state/result_json/match_strategy/tolerances), Finding(tenant/engagement/run/category/severity/state/fingerprint), FindingEvidence(finding/doc/dataset/location/payload), ReviewDecision(tenant/finding/reviewer/decision/comment) append-only incl. ambiguous-match adjudication, Report(tenant/engagement/version/snapshot_hash/path/approver), TaxSource(issuer/URL/title/article/lang/effective/verified/checksum) + chunks, AuditEvent(tenant/actor/action/resource/request/time), UsageRecord(tenant/job/metric/qty/units/billed_key/time) + TelemetryEvent(mapping time, recon timing, coverage w/o financial contents), Subscription(tenant/plan/status/limits/starts-ends).
Indexes: Client(tenant,name), Engagement(tenant,status,created), Document(tenant,engagement), Job(tenant,engagement,state), Finding(tenant,engagement,state,severity), Report(tenant,engagement,version). Page lists, cap sizes, no client-SQL interpolation. RLS optional; app checks mandatory.

## 17. API contracts and error behavior (EP-01/02/03/04/05/07/10/11/13/15)
Base `/api/v1`; JSON; UTC ISO timestamps; ISO dates; monetary strings; UUIDs; server-derived tenant ctx (never trust client `tenant_id`); cursor/offset max 100 + allowlisted sort/filter + stable totals; Idempotency-Key on expensive POSTs; 201 create / 202 + `job_id` async / 204 no-body; errors `{error:{code,message,details,request_id}}` (401/403/404-not-visible/409/422/429); OpenAPI from backend + CI compat; per-endpoint actor/ownership docs.
Catalog (min perm): POST /workspaces (init), GET /workspaces/current (member), GET /users/me (auth), GET/POST /members/invitations + PATCH /members/{id} (Owner/Admin), GET/POST /clients (member / Accountant+ create), GET/PATCH /clients/{id}, GET/POST /engagements, GET /engagements/{id} (assigned), POST /engagements/{id}/transition (role+state), POST /engagements/{id}/documents + GET .../documents (Accountant+ upload / assigned read) with `kind=jofotara_export` + `profile_id`, GET /documents/{id}/download (assigned, short-lived), GET /mapping/profiles + POST /mapping/profiles + POST /mapping/profiles/{id}/apply (Accountant+; drift check), GET /datasets/{id}/preview + PUT .../mapping + POST .../corrections, POST /engagements/{id}/run-reconciliation (Accountant+; body `{rule_set: REC-001..005, dataset_set_hash}` →202 `{job_id,status:QUEUED}`), GET /jobs/{id} (`{job_id,status,phase,progress_percent,retryable}`), GET /engagements/{id}/rule-runs (executed/skipped with NOT RUN reasons), GET .../findings + GET /findings/{id} (assigned), POST /findings/{id}/comments (Accountant+), POST /findings/{id}/decisions incl. ambiguous-match resolution (Reviewer/authorized), POST /engagements/{id}/approval (Reviewer/owner), POST .../reports (approver →202), GET /reports/{id}/download (assigned), GET /usage + GET /plans/current (Owner/Admin), GET /internal/tax-sources + POST /internal/rules/{id}/submit (Author) + POST .../publish (Publisher).
Examples: create review req `{"client_id":"uuid","period_start":"2026-01-01","period_end":"2026-12-31","type":"jofotara_reconciliation"}` →201 `{id,status:DRAFT}`; run →202; finding `{"id":"uuid","status":"OPEN","category":"RECONCILIATION_DIFFERENCE","severity":"HIGH","rule_version":"JO/REC-001/1","amount":{"value":"125.375","currency":"JOD"},"evidence":[...]}`; error 409 `{"error":{"code":"APPROVAL_BLOCKED","message":"Resolve or acknowledge required review items before approval.","details":{"blocking_findings":2},"request_id":"uuid"}}`; skipped `{"rule":"REC-002","state":"SKIPPED_INPUT_MISSING","reason":"JoFotara export missing"}`.
Events (durable outbox, idempotent consumers): document.uploaded, dataset.ready, mapping.profile_applied, rules.run_requested{tenant,engagement,hash,idempotency}, rules.run_completed{counts}, finding.superseded, review.approved{snapshot_hash}, report.generated, tenant.usage_recorded, telemetry.recorded (no financial contents).

## 18. Security, privacy, retention, and data residency (EP-12; P0 unweakened)
Baseline: TLS + at-rest (DB/storage/backups/secrets) + rotation on compromise; presigned ≤15m post-authZ, no listing; admin elevated + SoD + logging + env restrictions; non-root containers where practical + CPU/mem/time caps + sanitized filenames + no embedded-code exec; OWASP ASVS + API Top-10 pre-paid-pilot + exceptions doc; incident triage/containment/investigation/authorized-comms/postmortem (legal reviews external notice); backups exercised with runbook + evidence (not SLA-assumed).
Threats→controls: IDOR (server ctx + object authZ + negative tests every resource/link); malicious sheets (sig/quarantine/decompression caps/no-macro/sandbox/formula safety); prompt injection (untrusted marking, allowlisted tools, no admin/approval tools in AI ctx); sensitive logs/provider (no raw docs, approved subprocessors, minimization, safe trace IDs); compromised account (rotation/revocation, rate limits, strong passwords, MFA recommended); stale legal (signed/versioned/dates/expert); billing growth (quotas/caps/ceilings); loss/ransomware (encrypted backups, restore tests, limited creds, immutable history).
Jordan/PDPL: Law 24/2023 eff. 2024-03-17 per MoDEE is applicable framework — requires privacy-by-design but NOT substitute for counsel on controller/processor, sensitive financial personal data, notice/consent/basis, cross-border, breach, retention, subject rights. Contracts follow counsel-approved interpretation. ISTD Income/GST/E-Invoicing pages are research sources, not hardcode auth; expert certifies exact text/period pre-TX-enable.
Operational rights: agreements state purpose/scope; collect only necessary contacts/IDs (encrypt sensitive); tenant export/deletion workflows; retention defaults + legal-hold exceptions with contract/counsel (exact durations OPEN DEC-02; devs SHALL NOT invent); rights intake/routing aligned to controller/processor duties; review cloud + AI locations pre-onboarding; document transfer basis + provider terms; no training on tenant docs without explicit lawful separate process.
Pilot retention default: retain while engagement/sub active + configurable contractual interval; soft-delete → immediately inaccessible; scheduled erasure active/derived; backups time-bound expiry; tombstone minimal.
**Data-residency ADR (required, DEC-03):** document (1) app servers, (2) DB, (3) docs, (4) backups, (5) AI processing location(s), (6) subprocessors with customer-data access, (7) cross-border flows, (8) contractual/regulatory reviews. Do NOT claim Jordan-only or PDPL-compliant without verification/assessment.

## 19. Performance, reliability, and localization (EP-12/14)
Targets (initial; prove on staging): dashboard/list p95 <500ms excl. WAN; upload-init p95 <1s excl. transfer; 202 without parser wait; ordinary recon report <30s; limits 25MB/100pp/100k rows configurable; 5 concurrent analyses/tenant configurable + backpressure; 99.5% monthly post-stabilization; RPO≤24h / RTO≤8h with drill proof.
A11y/i18n: keyboard primary flows, focus order, semantics/labels, contrast, WCAG 2.2 AA target + regression checklist; AR first-class (RTL, status/action/error translations, AR/EN client search, mixed-direction values, font-safe bilingual PDFs — DEC-07 typefaces + screenshot corpus); number/date locale formatting without semantic change; preserve AR/Latin numerals on import.
Observability: structured logs, request/job trace IDs, latency, worker errors, upload reasons, rule distribution, AI error/cost, backlog, coverage/skipped as product-health (not hidden errors). Monthly avail + processing SLOs independently measured.
Maintainability: versioned APIs, forward-compatible migrations, reviewed dep updates, rollback docs, IaC. No feature complete without tests + a11y review + error docs + isolation checks.


## 20. Test plans and golden fixtures (EP-14; EP-07 owns rule fixtures)
Layers (owner/evidence/min): unit/property (eng/CI: math, validators, transitions, comparators, match keys); integration (BE/AI+QA: isolation, storage, queue, provider failure, retrieval); contract (FE/BE OpenAPI gen: schemas/auth/errors/Decimal); E2E (QA browser: full recon flow EN+AR); security (Tech: IDOR/RBAC/upload/injection/session/rate/leaks); AI bench (AI+tax reviewer: extraction/cite/abstention/injection); financial golden (Accounting SME: exact recon, signed rows, multi-curr); UAT (3–5 firms: onboarding/usefulness/reports/timings).
Per-REC 11 fixtures (§12) + AQ regression + TB golden retained secondary (e.g. TB 10,250.375 vs 10,200.375 → 50.000 variance) + App. B-style recon example. Freeze corpora/samples before release sign-off. Provisional thresholds (§14) recorded with scope/sample.
Traceability: every P0 ↔ test ↔ epic; release-blocking exceptions need PO+Tech (+tax expert if relevant).

## 21. Professional approval and reporting (EP-10/11)
Findings distinguish detected differences vs confirmed issues vs unresolved vs missing evidence vs skipped vs limitations. Approval explicit/authorized/attributable (actor + snapshot hash + time); immutable record; default blocks on unacked highs (409 + blocker list). Reports: firm/client/period/quality/coverage/rule counts/actor + detail (category/evidence/amounts-currency/dispositions/limits) + AI + no-compliance disclaimer (footer + exec summary) + AR RTL correctness + injection-safe XLSX + short-lived authorized download. Post-approval source/comment change → new version; original immutable. Never claim gov approval; never describe clean recon as compliance guarantee.

## 22. Commercial validation, pricing hypotheses, and unit economics (EP-14)
Discovery log (10–15 firms): size/buyer/process/software/JoFotara flow/volume/hours/problems/willingness/security. 3 paid pilots = validation target.
Unit-econ (assumptions until measured): revenue/customer; engagements/customer; compute/engagement; AI/engagement; storage; support; mapping/onboarding effort (from FR-MAP-TIME-001); gross contribution; CAC; monthly breakeven. Formulas + assumptions documented; labeled preliminary.
Pricing hypothesis only (NOT approved rates; do NOT hardcode): Starter ~49 / Professional ~129 / Firm ~249+ JOD/mo. Plan IDs + limits config-driven. DEC-05 quotas from test volumes; DEC-08 manual vs gateway before paid pilot.
Telemetry (P0, no financial contents): upload success, correction time, time-to-first-recon, completion time, useful findings, FP/rule, coverage, cost/engagement, feedback/renewal. Cost dashboard per tenant + aggregate.
Go/no-go: willingness to pay, repeated completion, measured time cut, trusted findings, reasonable corrections, safe ops, sustainable unit cost. If weak → narrow to highest-value workflow before more AI/integrations. 90-day: D1–30 stability/correction/time; D31–60 reuse/quality/renewal intent; D61–90 pricing/margin/acquisition.

## 23. Development epics and dependencies (EP-01..EP-15)
| Epic | v1.1 action | Depends |
|---|---|---|
| EP-01 Foundation | Keep P0. Point to v1.1; add residency/AI-provider ADRs + recon flow wireframes. | — |
| EP-02 Auth/Tenancy | Keep P0. Preserve restrictions; avoid admin bloat. | EP-01 |
| EP-03 Client/Review | Keep P0. Reorient creation around recon (3 upload sections + eligible/skipped). | EP-01/02 |
| EP-04 Uploads | CSV/XLSX + security P0; broad PDF/OCR→P1; add JoFotara doctype (joint with EP-15). | EP-01..03 |
| EP-05 Mapping | Keep P0. Profiles P1→P0 + drift + time metric. | EP-04/15 |
| EP-06 Financial Core | Keep P0. Prioritize sales/GL + decimals; TB after core. | EP-04/05/15 |
| EP-07 Rule Engine | Keep P0 infra. Prioritize REC-001..005 over broad AQ. | EP-05/06/15 |
| EP-08 Tax Knowledge | Registry + approval P0; full RAG→P1. | EP-07 |
| EP-09 AI Adapter | Safe interfaces P0; nonessential models→P1; work with no provider. | EP-05/08 |
| EP-10 Findings | Keep P0. Optimize recon-diff + ambiguous-match review. | EP-06/07/09 |
| EP-11 Reports | Keep P0. Bilingual recon primary. | EP-10 |
| EP-12 Security/Ops | Keep P0. Add location/privacy gates + residency ADR. | continuous |
| EP-13 Usage/Billing | Basic telemetry P0; sophisticated quotas/billing→P1. | EP-12 |
| EP-14 UAT/Pilots | Rewrite around JoFotara/sales/GL + commercial/cost metrics. | all |
| EP-15 JoFotara import & reconciliation (NEW) | Own JOF-001..006 + REC-001..005 delivery across EP-04/05/06/07; profiles, matching, corrections, coverage, conditional return. Prevents ownership confusion. | EP-04/05/06/07 |
Critical path: auth/tenancy → uploads (incl. JoFotara profiles) → mapping/normalization → deterministic REC → review → report → security/UAT. Pressure: defer OCR breadth, bank templates, advanced tax rules, billing integration, dashboards, assignment extras, export customization before weakening correctness/isolation/evidence. Vertical slices over backend-before-UI.

## 24. Revised milestone plan (estimate, not commitment)
8-week launch NO LONGER firm. Baseline (needs capacity/samples/evidence):
- W1–2 validation+foundation: discovery, approved export samples (Sales/JoFotara/GL), tax-expert engagement, scope freeze, UI/UX designs, arch+security foundation.
- W3–4 ingestion+normalization: secure uploads, JoFotara profiles, sales/GL import, reusable mappings, validation previews.
- W5–8 recon engine + usable MVP: REC-001..005, matching, exceptions, evidence nav, review, bilingual reporting, controlled demo.
- W9–12 pilot hardening: real-fixture eval, FP reduction, security testing, perf/cost measurement, supervised pilots.
- W13–16 conditional buffer: critical feedback, more mappings, prod controls, onboarding/legal finalization.
Milestones in tracker will be revised to this order after v1.1 approval; old Week1..8 titles retained temporarily with updated descriptions to preserve history.

## 25. Release gates and Definition of Done
Gates (all must pass): (1) all P0 mapped + tests; blocking exceptions PO+Tech (+tax if relevant) approved. (2) zero known cross-tenant disclosures/unauthorized approvals/critical file vulns. (3) golden recon + arithmetic 100%, no precision loss. (4) tax checks only where expert-approved/versioned/period-safe. (5) all findings have evidence + version; skips visible. (6) EN primary + AR surfaces pass UX + PDF. (7) backup/restore demo + alerts + access-control + DPAs/terms complete. (8) pilot firm completes independently.
Done per story: review + static/type + unit/integration + E2E where apt + UX/error states + RBAC/tenant + security + logging/metrics + migration + docs + CI green. AI +eval evidence. Tax rule +accounting/tax expert + dated source.
Sign-off: PO (scope/UI/commercial), Tech (arch/security), Tax Expert (per TX), QA (quality), Legal/Privacy (terms) — in tracker or signed decision with SRS version+SHA. SRS availability ≠ legal/security/finished proof.

## 26. Risks, assumptions, and unresolved decisions
Risks: low conversion (M/H; discovery + paid pilots; PO); variable exports (H/H; narrow profiles + mapping UX; Eng); wrong tax interpretation (M/Critical; expert+versioned+abstain; Tax Expert); FP overload (H/H; per-rule rates; AI/QA); disclosure (L/Critical; default-deny + tests; Tech); AR OCR (H/M; limited-label + corrections; AI); provider mismatch (M/Critical; legal/security review; Prod/Sec); creep (H/H; P0 lock + deferral + gates; PO); processing cost (M/M; quotas + deterministic-first; Tech); missing JoFotara/sales/GL samples (H/H; block recon fixtures; PO); hosting/residency unchosen (M/Critical; ADR; Tech+Legal); no pilots (M/H; discovery; PO); return-format unverified (M/M; conditional gate).
Assumptions: Jordanian Excel/CSV exports; expert access + authorized samples precondition TX/JoFotara rules; managed cloud assumed; manual invoices MAY start billing; ASR≠OCR; match% denominator always shown.
Decisions: DEC-01 first 2–3 export templates + fixtures (PO+Acct, pre-Sprint2); DEC-02 retention/roles/transfers (Legal+Sec+Prod, pre-real-data); DEC-03 hosting region + AI provider/subprocessor + data policies (Tech+Legal, pre-real-data); DEC-04 initial validated recon/TX targets + source versions (Tax expert, pre-enable); DEC-05 quotas from volumes (Eng+Prod, pre-pricing); DEC-06 blocker + SoD policy (Prod+reviewer, pre-Sprint6 approval); DEC-07 AR typefaces + corpus (UI/QA, pre-report); DEC-08 payment route manual vs gateway (Prod+Fin, pre-paid-pilot); DEC-09 scan vs digital applicability (AI+QA+Acct, pre-OCR exposure); DEC-10 JoFotara supported profiles/versions (PO+Tax+Eng, pre-REC enable); DEC-11 AI provider ADR external/self/hybrid (Tech+Legal, pre-AI prod); DEC-12 data-residency ADR (Tech+Legal, pre-pilot).

## 27. Acceptance-test scenarios (primary = recon; TB = secondary regression)
- ATR-001 E2E recon: Client→Review(jofotara_reconciliation)→Upload Sales+JoFotara+GL→Approve mappings→Reconcile REC-001..005→Review diffs→Decisions→Bilingual report. No manual DB.
- ATR-002 Unmatched both directions: sales-only + JoFotara-only surfaced (REC-001/002).
- ATR-003 Ambiguous match: two candidates → review queue, no auto many-to-one; authorized resolution audited.
- ATR-004 Duplicates: exact + heuristic candidates separated; suspicious ≠ fraud.
- ATR-005 Credit/correction: credit note/cancel/reversal honored, not dropped.
- ATR-006 Tax incl/excl: net/tax/gross compared only where compatible + tolerance; incompatible → NOT RUN.
- ATR-007 GL mapping diff: unmapped accounts → skip (not fabricated) + listed.
- ATR-008 Incomplete coverage: gapped JoFotara range → coverage report + affected NOT RUN.
- ATR-009 JoFotara versions: supported profile maps; unsupported → guidance, no phantom finding.
- ATR-010 Missing GL: eligible REC-001/002/004 run; REC-005 skipped with reason.
- ATR-011 Mapping reuse/drift: compatible reuse; schema change → confirm critical diffs; history kept.
- ATR-012 Cost/timing: mapping + recon timing + cost/engagement recorded without financial contents.
- Retained secondary: AT-001 isolation, AT-003/004 TB golden (50.000 variance / balanced pass), AT-005 blank≠zero, AT-006 ambiguous date, AT-007 FX segregation, AT-008 idempotency, AT-009 stale→new version, AT-010 TX gate, AT-011 historical dates, AT-012 unsupported citation, AT-013 injection, AT-014 propose vs finalize, AT-015 report immutability, AT-016 AR PDF, AT-017 file abuse, AT-018 blocker 409, AT-019 provider outage, AT-020 retention/delete.

## 28. SRS v1.0-to-v1.1 traceability and migration table
Comparison basis: full v1.0 `.docx` extracted (434 paras/41 tables: §§1–17 + App. A–D; 99 FRs Tables 8–18; UX-01..13; AQ/TX Table 21; entities Table 25; APIs Table 26; AT-001..020 Table 33). No sections unavailable.
| Old | Existing issue/code | New priority | Change | Tests affected |
|---|---|---|---|---|
| §1 positioning AI-audit | EP-01/14 | Replaced | Recon-first platform; compete Excel/IDEA/DataSnipper/MindBridge; hypothesis not advantage | ATR-001 replaces AT-002 as primary |
| P0 inputs CSV/XLSX+PDF/scan, TB central | EP-04/05/06 | Modified | P0 = Sales + JoFotara Excel + GL; TB supporting; PDF/OCR→P1; JoFotara first-class | AT-017 kept; ATR-009/010 new |
| FR-FILE-002 P0 | EP-04 #4 | P0→P1 | Broad PDF/OCR deferred | PDF fixtures → P1 suite |
| FR-EXT-010 P1 | EP-05 #5 | P1→P0 | Reusable profiles + drift + time metric | ATR-011 new |
| AQ-001..010 P0 core | EP-06/07 #6/#7 | Modified | Retained secondary/regression; REC-001..005 commercial P0 | Golden TB kept; 11 REC fixtures new |
| TX-001..003/005 P0-expert | EP-07/08 | Unchanged gate | Math recon ≠ legal; jurisdiction keys added; ZATCA/FTA excluded | AT-010/011 kept |
| TX-004 P1 | EP-07 | P1 kept | Still needs expert | — |
| FR-RULE infra P0 | EP-07 | Keep | Add JUR keys; REC template | REC fixtures |
| RAG full P0 | EP-08 #8 | Modified | Registry + approval P0; QA experiences P1 | Bench narrowed |
| AI narrative/classify/anomaly/OCR P0-assist | EP-09 #9 | P0→P1 (guardrails P0 kept) | MVP works with no provider; ADR required | AT-019 kept; narrative suite P1 |
| FR-FND P0 | EP-10 #10 | Keep + optimize | Recon-diff + ambiguous-match review | ATR-003/004 |
| FR-REP P0 | EP-11 #11 | Keep + focus | Bilingual recon primary; 6-way distinction | ATR-001/012 |
| FR-USE quotas/billing P0 | EP-13 #13 | Modified | Basic telemetry P0; sophisticated quotas/billing→P1; pricing hypotheses not hardcoded | ATR-012 |
| 8-week launch commitment | Milestones 1–8 | Replaced (estimate) | W1–2 validate, W3–4 ingest, W5–8 MVP, W9–12 harden, W13–16 buffer; vertical slices | Milestone descriptions updated |
| AT-002 TB+GL primary | EP-14 #14 | Demoted | ATR-001 recon primary; TB secondary | ATR suite new |
| DEC-01..09 | — | Kept + DEC-10..12 new | JoFotara profiles, AI provider, residency | Gates |
| Entities/APIs | EP-01.. | Extended | + MappingProfile, JoFotara/Sales/GL entries, jurisdiction fields, mapping/profile + run-recon endpoints, coverage/skipped semantics | Contract tests updated |
**Counts (v1.1-draft):** added ~15 (JOF-001..006, REC functional 5, MAP-TIME, TEL, JUR, AI-P1 ×5, EP-15); modified ~12 (FILE-002, EXT-010, rule scope, AI scope, USE-006, milestones, E2E, reports focus); deferred to P1 ~9 (PDF/OCR breadth, narrative, RAG QA, classify, anomaly, bank templates, TX-004, threshold UI, auto-billing); replaced 2 (positioning, schedule commitment). No v1.0 history erased; superseded file retained.
**Validation limits:** no JoFotara/sales/GL samples yet; no tax-expert sign-off; no residency/hosting choice; no pilots; return format unverified — all explicit blockers (§26/§16F). No CI run for docs change; no prod code to test.

---
## Appendices
**A. Glossary:** Tenant, Engagement/Review, DatasetVersion, MappingProfile, RuleRun, Finding (not conviction/liability), Evidence, Reviewer, RAG (verified + citations), JoFotara (JO e-invoicing; file import only in MVP), P0/P1/P2, Stale/superseded, Golden fixture, Coverage (reconciled vs skipped with denominator), Ambiguous match.
**B. Example recon (synthetic, not legal guidance):** Al-Nahda → Example Trading LLC 2026-01-01..2026-12-31 → Sales.csv (120 rows, 15,000.000 JOD net) + JoFotara.xlsx vProfile-JO-2026.1 (118 invoices) + GL.csv (mapped revenue 15,000.000) → REC-001 finds 2 sales w/o JoFotara (450.000), REC-002 finds 1 JoFotara w/o sales (200.000 credit-note later matched), REC-003 flags 1 gross/net presentation diff (resolved via inclusive flag), REC-004 lists 1 exact duplicate pair + 1 candidate, REC-005 passes after mapping fix. Reviewer confirms 2, dismisses 1 with note, requests evidence on 1 → approves snapshot → report v1 bilingual distinguishing confirmed/unresolved/missing/skipped/limits. No liability inferred.
**C. Sources:** ISTD Income Tax Law; ISTD GST legislation; ISTD Billing_system (context); MoDEE PDPL Unit + FAQs. Discovery only; expert confirms full text/amendments/regs/dates pre-publish.
**D. Handoff:** SRS accepted by PO/Tech; FR-IDs in stories; UX-01..13 recon wireframes AR/EN; Decimal/tenant/lineage contracts; OpenAPI/migrations reviewed pre-parallel; REC golden + AT/ATR automated; gate owners named; release blocked until sec/privacy/acct/tax gates evidenced; samples + experts + residency + pilots tracked as blockers.

*END OF TAXPILOT MASTER SRS v1.1 DRAFT — pending PO approval. Do not implement scope-dependent features until approved.*

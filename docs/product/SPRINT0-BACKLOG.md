# Sprint 0 / Sprint 1 plan (v1.1 readiness — DO NOT START scope coding until PO approves SRS v1.1)

Source: SRS v1.1 §§23–24 + instruction §§13/15. Vertical slices; docs-first.

## Sprint 0 (W1–2): validation + foundation gates
1. Customer discovery 10–15 firms — log size/buyer/process/software/JoFotara flow/volume/hours/problems/willingness/security. Deliverable: discovery log. DoD: 10+ interviews or explicit waiver. (EP-14)
2. Representative authorized samples: Sales Register + JoFotara Excel (+versions) + GL. Deliverable: approved fixture set + MappingProfile drafts (DEC-01/DEC-10). DoD: ≥2 sales + ≥1 JoFotara profile + ≥1 GL checked in as golden inputs. BLOCKS REC work if missing.
3. Tax-expert engagement + initial REC/TX targets + source versions (DEC-04). DoD: named expert + written scope.
4. Scope freeze + UI/UX recon wireframes (Dashboard/New Review w/ 3 sections/Map spreadsheet/Results/Finding 7-part/Report) AR/EN. DoD: clickable flows reviewed by accountant.
5. Arch + security foundation (EP-01/02/12): monorepo scaffold, OpenAPI base, tenant/RBAC skeleton, quarantine pipeline stub, residency + AI-provider ADR drafts. DoD: fresh-clone CI green (lint/typecheck/unit), staging deploys with SHA, no secrets, isolation smoke passes.
6. Legal/privacy intake: DPA/terms/retention counsel review started (DEC-02). DoD: issue log + counsel engagement, no invented terms.

Exit gate: PO + Tech sign scope; tax expert signs recon scope; no unresolved critical data flow; samples approved.

## Sprint 1 (W3–4): ingestion + normalization slice
1. Secure uploads for 3 doctypes + JoFotara profile detection + actionable unsupported guidance (EP-04/15, FR-JOF-001/002).
2. Reusable mapping profiles P0 + drift handling + raw/norm/corrected preview + time metric (EP-05, FR-EXT-010/MAP-TIME).
3. Decimal normalization + issuer-aware canonical entries + coverage reporting (EP-06/15).
4. First vertical E2E stub: Upload Sales+JoFotara → Map → Preview (no REC yet) in EN+AR, tenant-isolated, audited.

DoD per story (§25): review + static/type + unit/integration + tenant checks + logging/metrics + migration/docs + CI. Financial stories + golden fixtures. No prod tax conclusions without approvals.

## Testing expectations
- Contract tests for new mapping/profile + run-recon schemas before UI build.
- Golden inputs frozen; 11 REC fixtures planned (exact/unmatched/mismatch/duplicate/ambiguous/missing/credit/period/currency/idempotency/traceability).
- Security: IDOR + upload-abuse + injection suites from Sprint 0.
- Telemetry (no financial contents): upload success, correction time, time-to-first-recon, cost/engagement.

## Blockers (must clear before REC engine Sprint)
Missing JoFotara/sales/GL samples; no tax expert; no hosting/residency choice; no pilots; unverified return format. See SRS §§26–27.

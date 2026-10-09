# TaxPilot Jordan

AI-assisted tax reconciliation and financial review platform for Jordanian accounting firms.

**Authoritative spec:** [`docs/product/TAXPILOT_MASTER_SRS_V1.1.md`](docs/product/TAXPILOT_MASTER_SRS_V1.1.md) (SRS v1.1, reconciliation-first baseline — pending PO approval via PR).

**Superseded:** SRS v1.0 `.docx` retained under `docs/product/superseded/` for change history. Do not build new scope from v1.0 alone.

## Product promise (v1.1)
Sign in → Select/create client → Start tax review → Upload Sales Register + JoFotara Export + GL → Confirm mappings → Run reconciliation (REC-001..005) → Investigate → Record decisions → Bilingual PDF/XLSX report.

- Reconciliation-first, accountant-focused. Deterministic engine calculates; AI assists; accountants decide.
- File-based JoFotara import in MVP. No government API integration, no portal credentials.
- Arabic/English + RTL. Light-mode-first, one primary action per screen.
- Strict tenant isolation, versioned rules, evidence traceability, expert-gated tax conclusions.

## Repo map (planned)
- `docs/product/` — SRS v1.1, ADRs, UX flows, golden-test plans
- `apps/web/` — Next.js (planned, not yet implemented)
- `apps/api/` — FastAPI (planned)
- `workers/` — ingestion / reconciliation / reports (planned)
- `rules/jordan/` — versioned REC + AQ rule definitions + fixtures (planned)

## Status
SRS v1.1 change-control in progress. No feature code yet. See GitHub Issues EP-01..EP-15 and open PR for v1.1 baseline. Do not start scope-dependent coding until PO approves v1.1.

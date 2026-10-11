> **STATUS: UNRESOLVED — DEC-03/DEC-12 pending.** No hosting, region, subprocessor, or transfer
> decision has been made. Governing requirements: `TAXPILOT_MASTER_SRS.md` §10.

# ADR-001 — Data residency and subprocessors (DECISION REQUIRED, blocks pilot)

Status: Proposed (SRS v1.1 §18, DEC-03/DEC-12). Owner: Tech Lead + Legal. Must be signed before real customer data onboarding.

## Required answers
1. App servers location (region/provider).
2. Database location.
3. Uploaded documents location.
4. Backups location.
5. AI processing location(s) (including any external provider regions).
6. Subprocessors with customer-data access + DPA status.
7. Cross-border flows (does customer info leave Jordan? on what basis?).
8. Contractual + regulatory reviews required (PDPL Law 24/2023 assessment, counsel opinion).

## Constraints
- Do NOT claim data stays in Jordan unless verified.
- Do NOT claim PDPL compliance without assessment + legal review.
- Retention/deletion exact periods need DEC-02; this ADR must reference them, not invent them.

## Options (to evaluate)
- Managed cloud region closest to JO vs JO-local hosting (cost/latency/compliance trade-offs).
- Single-region vs multi-region backups (RPO ≤24h / RTO ≤8h proof required).

## Decision log
- [ ] Region(s) chosen + rationale
- [ ] Subprocessor list + DPAs
- [ ] Transfer basis documented
- [ ] Counsel sign-off + date

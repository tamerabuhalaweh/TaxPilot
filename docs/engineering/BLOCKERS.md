# Blocker register (visible, per directive §10 — updated 2026-10-09)

Independent foundation work proceeds; these restrict production readiness, not the scaffold.

| # | Blocker | Restricts | Status |
|---|---|---|---|
| B-01 | Representative JoFotara exports (authorized) | Import profiles, REC fixtures, format support claims | OPEN — no samples in repo |
| B-02 | Representative Sales Register files | Same as B-01 | OPEN |
| B-03 | Representative General Ledger files | Same as B-01 | OPEN |
| B-04 | Tax-domain expert engagement + rule approval | Any TX rule, REC legal interpretation, pack activation | OPEN |
| B-05 | Hosting + data-residency decisions (ADR-001) | Staging/prod targets, subprocessors, cross-border basis | OPEN |
| B-06 | AI provider + processing location (ADR-002) | Any external-model use; MVP runs provider-free | OPEN |
| B-07 | Pilot accounting firms (10–15 discovery, 3 paid-pilot goal) | UAT, time-saved/cost validation | OPEN |
| B-08 | Tax-return formats (fields/basis) | Conditional return recon | OPEN — gated conditional-P0 |
| B-09 | Repository classification (public vs private/redacted) | What docs/fixtures may enter the repo | OPEN — asked of PO in PR #33 |
| B-10 | SRS v1.1 (PR #15) + jurisdiction amendment (PR #32 + corrections PR #33) approval | JUR schema/API coding, then domain slices | OPEN — foundation only until approved |

## Security notes (Sprint 0, 2026-10-09)
- Backend: `pip-audit` initially found 14 advisories in transitive `starlette 0.41.3` (via `fastapi 0.115.6`); upgraded to `fastapi==0.143.0` (starlette 1.7.0) — re-audit clean, full suite re-green. Pinned in `apps/api/requirements.txt`.
- Frontend: `npm audit` reports 2 postcss advisories (high+critical) reachable only via build-time CSS processing; fix requires breaking `next@16`. Stayed on latest `next@14.2.35` (React 18.3.1). Accepted risk for Sprint 0: no attacker-controlled CSS exists anywhere in the product pipeline (all styles authored); CI `security` job reports it on every PR; revisit (upgrade or override) before any production deployment.
- No secrets committed (`.env.example` only; `.env`/`.venv`/`node_modules` ignored).

Synthetic fixtures are for engineering tests only. Real import support needs authorized representative exports; no parser-accuracy claims from synthetic data alone.

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

## Security notes (Sprint 0, 2026-10-09; corrections round)
- Backend: `pip-audit` initially found 14 advisories in transitive `starlette 0.41.3` (via `fastapi 0.115.6`); upgraded to `fastapi==0.143.0` (starlette 1.7.0) — re-audit clean, full suite re-green. Pinned in `apps/api/requirements.txt`.
- Frontend: `npm audit` showed the Next 14 line itself carrying 20+ advisories (critical aggregate; GHSA-9g9p-9gw9-jx7f, GHSA-h25m-26qc-wcjf, GHSA-p293-qw3h-jr36 RCE on Windows hosts, GHSA-p9j2-gv94-2wf4 SSRF in rewrites, plus postcss GHSA-qx2v-qp2m-jg93 / GHSA-6g55-p6wh-862q / GHSA-fxqj-rqcc-2cmp). Fix required semver-major `next@16.4.0`; migration evaluated on our minimal surface and adopted (React 19.3.0; typecheck/tests/build/dev/e2e re-verified). Prod `npm audit`: **0 vulnerabilities**. No exception filed.
- CI security job now fails on non-exempt findings (pip: any; npm: high/critical) via `.github/scripts/security_gate.py` + `.github/security-exceptions.json` (currently empty). Gate negative-control verified (synthetic critical → exit 1). `npm ci` everywhere (CI + Dockerfile share the committed lockfile graph).
- No secrets committed (`.env.example` only; `.env`/`.venv`/`node_modules` ignored).

Synthetic fixtures are for engineering tests only. Real import support needs authorized representative exports; no parser-accuracy claims from synthetic data alone.

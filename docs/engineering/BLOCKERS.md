# Blocker register (visible, per directive §10 — updated 2026-10-09)

Independent foundation work proceeds; these restrict production readiness, not the scaffold.

| # | Blocker | Restricts | Status |
|---|---|---|---|
| B-01 | Representative JoFotara exports (authorized) | Import profiles, REC fixtures, format support claims | OPEN — no samples in repo; REC-JOFO-01 delivered a fail-closed profile foundation only (no layout enabled, DEC-10 still OPEN) |
| B-02 | Representative Sales Register files | Same as B-01 | OPEN |
| B-03 | Representative General Ledger files | Same as B-01 | OPEN |
| B-04 | Tax-domain expert engagement + rule approval | Any TX rule, REC legal interpretation, pack activation | OPEN |
| B-05 | Hosting + data-residency decisions (ADR-001) | Staging/prod targets, subprocessors, cross-border basis | OPEN |
| B-06 | AI provider + processing location (ADR-002) | Any external-model use; MVP runs provider-free | OPEN |
| B-07 | Pilot accounting firms (10–15 discovery, 3 paid-pilot goal) | UAT, time-saved/cost validation | OPEN |
| B-08 | Tax-return formats (fields/basis) | Conditional return recon | OPEN — gated conditional-P0 |
| B-09 | Repository classification (public vs private/redacted) | What docs/fixtures may enter the repo | OPEN — asked of PO in PR #33 |
| B-10 | SRS v1.1 (PR #15) + jurisdiction amendment (PR #32 + corrections PR #33) approval | JUR schema/API coding, then domain slices | OPEN — foundation only until approved |
| B-11 | Email delivery + password reset + MFA | Production user onboarding completeness (FR-ID-003) | OPEN — dev-token flow only; do not claim onboarding complete |

## Security notes (Sprint 0, 2026-10-09; corrections round 2)
- Backend: `pip-audit` initially found 14 advisories in transitive `starlette 0.41.3` (via `fastapi 0.115.6`); upgraded to `fastapi==0.143.0` (starlette 1.7.0) — re-audit clean, full suite re-green. Pinned in `apps/api/requirements.txt`.
- Frontend prod: Next 14 line carried 20+ advisories (GHSA-9g9p…2xp9 incl. RCE/SSRF + postcss triple) → upgraded to `next==16.4.0` + React 19.3.0; prod `npm audit --omit=dev`: **0 vulnerabilities**. No exception filed.
- Frontend dev-only (full-tree `npm audit`): tinypool critical (GHSA-5gmw-xhrv-c9v3, GHSA-85c8-ppgw-ccpr), vite high, vitest critical aggregate — all reachable only via local/CI test tooling (vitest worker pool, vite dev/build); vitest bumped 2.1.5→2.1.9 (non-breaking); full fix needs breaking vitest 5.0.3. Pre-production gate (evaluate before release); NOT in shipped runtime image (`npm ci --omit=dev` verified: serves 200, no vitest/vite/typescript; transitive `playwright` npm package ships via next itself with 0 advisories and no browsers). Not remotely exploitable in any deployed artifact.
- CI security job fails closed: `security_gate.py` rejects unknown severity, advisory-less high/critical, malformed audits, unsigned/expired exceptions (8 unit tests); audit steps capture output with `|| true` so scanner crashes reach the gate as failures while approved findings pass through signed time-bounded exceptions (none granted; file empty).
- Queue durability: worker-crash-only on single-node default Redis; production processing blocked (`JOBS_DURABILITY_APPROVED` gate) until OPS-JOBS-01 #35. Pre-auth/upload BFF allowlist + migration checksum/lock recorded as gates under CI-SEC-01 #36.
- No secrets committed (`.env.example` only; `.env`/`.venv`/`node_modules` ignored).

Synthetic fixtures are for engineering tests only. Real import support needs authorized representative exports; no parser-accuracy claims from synthetic data alone.

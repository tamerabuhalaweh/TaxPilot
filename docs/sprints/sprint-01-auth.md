# Sprint 1 — auth, tenancy, RBAC, clients (EP-02 #2, EP-03 #3)

Branch: `feature/sprint-01-auth-tenancy-clients`. Backend contracts first, then a small vertical slice. No engagements/JUR-01-02 (deferred pending SRS consolidation in PRs #15/#32/#33); queue stays prod-blocked (#35); synthetic `example.com` data only.

## Delivered
- Migration `0002`: tenants, users (lowercased unique email, bcrypt-sha256 passwords), memberships (unique per tenant), invitations (single-use expiring token hashes), sessions (hashed tokens, tenant binding, expiry/revocation), verifications, clients (tenant-scoped, archive-not-delete), audit events.
- Auth: register (neutral duplicate response) → verify (single-use) → login (generic 401, 403 unverified) → httpOnly SameSite=Lax session cookie + Bearer alternative → logout revocation → tenant switch with rotation. Rate limits (5/15min per email+IP, Redis, fail-closed, Retry-After). Dev-only token exposure forced off in production.
- Membership: invite/accept (email match, expiry, idempotent), role/status changes (no self-deactivation), owner/admin-only management.
- Clients: list/create/get/patch + archive; cross-tenant reads return 404.
- RBAC: owner/admin > manage; owner/admin/accountant/reviewer > write clients; owner/admin/reviewer reserved for decisions (future); viewer read-only. All backend-enforced.
- Frontend: /login (login/register + dev auto-verify), session-gated dashboard (me, role, clients, create, logout), /reviews/new placeholder retained. BFF proxy hardened per #36-before-auth: header allowlist, 1MB/10MB caps, fixed-host origin, explicit set-cookie forwarding.
- Tests: 6 integration (journey, dup/enumeration, lockout, invites/roles, isolation matrix, switch/rotation) + 4 unit + 5 Playwright (incl. full register→client→logout→login journey) + proxy policy vitests.

## Known follow-ups (not blockers for this slice)
- Email delivery (verification/invite) is dev-token based; production needs a mail provider + templates.
- Sessions are fixed 24h, no sliding refresh or "remember me".
- No MFA/SSO (P1 per SRS).
- No password reset flow yet (FR-ID-003 incomplete) — tracked in BLOCKERS.
- BFF edge throttle is per-process memory (correct tier, generous 20/15min); platform edge limiting is the production answer.

## Security correction round (PR #37 review → this branch)
- P0-A: ownership separated from administration — invites/patches can never grant or touch owner; explicit audited `transfer-ownership` (confirm flag, row-locked, last-owner invariant checked); concurrent transfers serialize, never empty ownership.
- P0-B: backend login limiting is per-email only (shared BFF-IP bucket removed — it locked out unrelated customers and reset across users); BFF tier throttles per observed peer (last-XFF, 20/15min); spoofed forwarding headers ignored; Retry-After reflects the blocking key; limiter-down fails closed.
- P0-C: session-bound CSRF tokens (synchronizer: hashed server-side, readable companion cookie for SPA survival) required on cookie-ambient mutations incl. logout/switch/invite/clients; exact-match Origin check when supplied; Bearer-only clients exempt; proxy forwards only allowlisted headers (x-csrf-token included, x-forwarded-* dropped) with 1MB/10MB caps.
- P0-D: invitation/verification consumption is SELECT FOR UPDATE + conditional update in one transaction (ON CONFLICT membership insert); replays are idempotent-success (accept) or single-use-422 (verify); no swallowed IntegrityError.
- Extras: strict environment enum; token exposure dev-only default (staging/prod refuse, Secure cookies nonlocal); explicit table metadata + schema-conformance test + concurrent-request test; backend body cap independent of Content-Length; archive filtering default; login/client AR strings + toggles; total AppError→status map test.

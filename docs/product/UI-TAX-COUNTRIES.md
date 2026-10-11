# UI/UX — Tax & Countries + context-aware Review Start (JUR-03, #30)

**Location:** Clients → Client Detail → **Tax & Countries** (primary; no new top-level nav in JO MVP; Settings shows support list only). **Lang:** AR/EN + correct RTL; keyboard navigable; one primary CTA per view; real backend-backed controls; no charts overload; planned packs never show RUN.

## Screen 1 — Tax & Countries (per client)
- Header: client name + portfolio note (optional display group).
- **Legal entities** cards: name, incorporation country flag/code, entity type, obligations summary (e.g. `JO · 2 profiles`), status pill. Actions: View entity, Add presence, Manage obligations.
- **Operating presence** rows under entity: country, kind (Branch/Office/Establishment), dates, applicability pill (Not assessed / Pending / Reviewed).
- **Tax obligation profiles** per entity/group: jurisdiction, tax type (Sales/Income/VAT/CT/Zakat…), regime?, period, registration status pill, verified-by where set, masked registration (`••••1234`).
- **Country features** strip: JO `Supported` (subject to enabled rules/formats) / AE `Planned — tax checks not available` / SA same. Planned cards are informational; no RUN button; no direct-API hint.
- Primary CTA: `Add country or presence`. Secondary: `New review with this context` (per context row).
- States: empty (no entities → suggest JO confirm), loading skeleton, validation errors (explicit country/type/period messages), saved toast, unsupported (planned card), permission-denied (Viewer/role without grant).
- Advanced (collapsed): Tax groups + memberships (DRAFT/PENDING/VERIFIED/ENDED, dated members, evidence). Hidden unless needed in MVP.

## Flow — Add country / presence (progressive disclosure)
1. Q: `Is this a separate registered company or a presence of an existing entity?` → radio (Separate company / Presence of [entity picker]).
2. Country select (ISO list;乔丹/AE/SA + others as registered-location only) + tax category select (optional; `Unknown` allowed) + registration status (Unknown/Not registered/Pending/Registered/Ended).
3. If Registered: optional protected registration ID input (password-type, masked on save) + authority + dates + optional evidence ref.
4. Effective dates + notes. CTA: `Save draft` always available; `Save and use for review` only when required fields valid. Copy: entering a country never claims to activate its tax rules (explicit helper text).

## Screen 2 — New Review context selector (extends UX-05)
- Compact selector order: Legal entity → Country/tax context (shows status: Supported/Planned/Draft) → Tax type/review objective → Period.
- JO-only fast path: client with single JO entity shows pre-selected `JO · [Entity] · Sales/JoFotara reconciliation · [period]` with `Confirm and continue` (one click, no wizard).
- Planned context (AE/SA): selectable for record-keeping but CTA becomes `Save location (no tax checks)`; RUN disabled with reason `Planned — tax checks not available (JURISDICTION_NOT_SUPPORTED)`.
- Unverified/DRAFT obligation: allows plain accounting comparison only with explicit scope banner (`No tax-compliance claim`); authoritative tax step blocked with `TAX_PROFILE_UNVERIFIED` guidance.
- Multi-country client: each review scoped to one context; portfolio summary (future) segregates counts/currencies, never nets JOD/AED/SAR.

## Illustrative journeys
- **JO-only:** Create client `Example Trading LLC` → suggested JO entity → Confirm → Upload Sales+JoFotara+GL → Map → Reconcile REC-001..005 → Report. Two clicks to first upload.
- **Multi:** `Example Group` → JO Trading LLC (JO, Supported) + UAE Trading FZ-LLC (AE, Planned) + Saudi Trading LLC (SA, Planned); JO review runs; AE/SA cards explain coming later. JO company + Dubai Branch presence: same entity row + presence row; JO review allowed; AE treatment explicitly not inferred.
- **Cross-border:** source rows with foreign countries → banner `Cross-border items need expert review; no automatic tax treatment applied` + route to reviewer queue.

## Acceptance (JUR-03)
First-run/empty/invalid/in-review/disabled/denied states present; keyboard path JO-create→confirm→upload completable; AR + RTL verified with mixed-script numerals preserved; wrong-entity/unsupported-country/permission/profile-change cases tested (changed profile locks issued reports, supersedes unissued); no unsupported capability rendered as functional.

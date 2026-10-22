# TaxPilot Premium UI v2 — Design Specification

- **Status:** Design proposal, awaiting founder and GPT-6 acceptance
- **Date:** 22 October 2026
- **Local branch:** `design/premium-ui-v2`
- **PR #83 head branch:** `feat/premium-accountant-ui`
- **Scope:** Six static screens, responsive rules, accessibility, truthful data contracts, and a gated implementation plan
- **Not in scope:** Production deployment, merge, customer onboarding, real-data processing, persisted approval workflow, Arabic PDF/XLSX exports

---

## 1. Purpose

Premium UI v2 makes the existing TaxPilot review workflow feel credible, calm, and evidence-first for an accountant. It is a design direction, not a claim that the running application already looks or behaves this way.

The proposal deliberately preserves the working product boundaries:

- One client and three draft synthetic reviews remain the honest current workspace state.
- No financial total is inferred on the dashboard.
- No approval, dismissal, or resolution action is shown when the API cannot persist it.
- No USD comparison is shown when coverage is incomplete.
- PDF and XLSX exports remain English-only and carry the synthetic label.
- Static mockups are labelled **“Design proposal v2 — not the running app.”**

Implementation starts only after explicit design acceptance. The current functional implementation must not be rewritten speculatively.

---

## 2. Evidence Base

The screens are grounded in the current workspace API, the local synthetic workspace, the deterministic demo fixture, and the current export contracts.

| Area | Source of truth | Design consequence |
| --- | --- | --- |
| Client | `GET /api/v1/clients` | One active client: Founder Synthetic Client. No sector is invented. |
| Reviews | `GET /api/v1/engagements` | Three `SALES_GL` reviews, all `DRAFT`, periods 2024, 2025, 2026. |
| Review history | `GET /api/v1/engagements/{id}/history` | Activity is shown as stored events, not inferred workflow progress. |
| Synthetic scenario | Deterministic fixture `synthetic-sales-gl-v1` | JOD differs; USD coverage is incomplete. |
| Findings | Ordered synthetic result | Review-required findings lead; informational findings follow. |
| Exports | PDF/XLSX contract | English-only, synthetic-labelled, bound to the displayed run identity. |
| Arabic | Existing `i18n.ts` labels plus narrow new copy | Arabic covers the reconciliation workspace only in this proposal. |

### 2.1 Actual synthetic values used

- Client: `Founder Synthetic Client`
- Client ID: `44d28803-2281-43f3-adb7-8ef965f539dc`
- Reviews: three `SALES_GL` engagements for 2024, 2025, and 2026
- Status: `DRAFT` for all three
- Created: 21 October 2026 at 10:13, 10:20, and 10:25 UTC
- Engagement used in the workspace screens: `b57b9d4a-5bf1-4b09-938d-eec6d4962164`
- Fixture: `synthetic-sales-gl-v1`
- Policy: `DEMO-GL-POL-1` version `1`
- Jurisdiction: `JO`
- Rules version: `1`
- Account scope: `4100`
- Currencies: `JOD`, `USD`
- Basis: `AGGREGATE_PERIOD`
- Measure: `NET`
- Convention: `CREDIT_POSITIVE`
- Tolerance: `0`
- Scenario period: `2026-01-01` to `2026-12-31`
- JOD sales total: `3,500.000`
- JOD GL total: `3,400.000`
- JOD delta: `100.000`
- Findings: five total; three review-required; two informational
- Reconciliation fingerprint: `89dbedf9108cb00fa26a92c88d3f00b51acc10db18afb25d46067810ffa34302`
- Findings fingerprint: `4798d515f0ca2cf9c03c44504328d85f57b09626367e90ea33fc12836e0b760b`

### 2.2 Finding order

1. Sales and GL totals differ (JOD) — high, review required, `RECONCILIATION_DIFFERENCE`
2. Possible duplicate sales invoice rows — medium, review required, `REVIEW_CANDIDATE`
3. Reconciliation inconclusive (USD): incomplete coverage — medium, review required, `DATA_QUALITY`
4. Reversal preserved — low, informational
5. Credit note preserved — low, informational

The selected JOD finding uses finding ID `89dbedf9108c-0003`, rule `JO/REC-005/1`, outcome `DIFFERENCE`, rationale `TOTALS_DIFFER`, and review state `PENDING_REVIEW`. Its six displayed evidence rows are:

| Side | Dataset | Row | Reference |
| --- | --- | --- | --- |
| General ledger | `SYNTHETIC-GL-v1` | 2 | `J-1-1` |
| General ledger | `SYNTHETIC-GL-v1` | 3 | `J-2-1` |
| General ledger | `SYNTHETIC-GL-v1` | 4 | `J-3-1` |
| Sales register | `SYNTHETIC-SALES-v1` | 2 | `INV-1001` |
| Sales register | `SYNTHETIC-SALES-v1` | 3 | `INV-1002` |
| Sales register | `SYNTHETIC-SALES-v1` | 4 | `INV-1003` |

---

## 3. Design Principles

1. **Truth before visual completeness.** Sparse history stays sparse. Missing sector, missing USD totals, absent approvals, and absent completion rates are explicit.
2. **Evidence before opinion.** Findings keep the rule, method, source rows, and run identity adjacent to the conclusion.
3. **Calm density.** The interface is information-rich but uses restrained color, clear grouping, and predictable spacing.
4. **One decision surface.** Reconciliation, coverage, findings, and report handoff should not feel like unrelated pages.
5. **No decorative finance theatre.** No cursor-driven gradients, fake stock charts, invented risk scores, or ornamental document previews.
6. **Arabic is structural.** RTL is a layout direction, not a translated sticker placed over an English screen.
7. **Accessible by default.** Charts have table equivalents. Focus is visible. Badges never rely on color alone.

---

## 4. Information Architecture

### 4.1 Desktop shell

- Fixed-width left sidebar, 248px, navy/petrol.
- Primary navigation: Overview, Clients, Reviews, Reports, Settings.
- Workspace switcher: `Founder workspace`.
- Persistent design flag above the shell: design proposal only.
- Main content uses a maximum readable width with room for wide evidence tables.
- Contextual actions sit in the page header; destructive or irreversible actions are absent.

### 4.2 Mobile shell

- Top app bar with brand, workspace context, and account control.
- Horizontal workflow strip for the five review stages.
- Bottom navigation for Overview, Clients, Reviews, Reports, Settings.
- Tables become scrollable regions or stacked detail cards.
- Touch targets are at least 44px wherever the design introduces new controls.

### 4.3 Existing route mapping

The proposal works with the existing Next.js App Router structure rather than introducing unnecessary routes.

| Design screen | Current route | Implementation note |
| --- | --- | --- |
| Dashboard | `/` | Replace the current dashboard presentation; retain data fetching. |
| Clients and periods | `/clients`, `/clients/[id]` | Preserve add-client and review-creation behavior. |
| Reconciliation | `/reviews/[id]` | Keep the review workspace as the single detail route; use tabs/anchors for sections. |
| Findings | `/reviews/[id]` | Render as a workspace tab/section. |
| Reports | `/reviews/[id]` and `/reports` | Keep workspace handoff and the global reports list. |
| Arabic reconciliation | `/reviews/[id]` with Arabic locale | Use the existing locale provider and RTL direction. |

---

## 5. Screen Specifications

### 5.1 Dashboard

**Purpose:** Give the accountant a truthful operational overview of the current book.

**Hierarchy**

1. Page title and date/context.
2. Sparse-state introduction: three draft reviews, one client, no completed work.
3. Attention card: three open reviews, all draft, no completion or approval rate.
4. Four KPIs: active clients, reviews, open reviews, completed.
5. Review volume by engagement period.
6. Review status distribution.
7. Review queue ordered by status and age.
8. Recent activity from stored engagement events.
9. Client book summary.

**Truth constraints**

- Counts derive only from stored records.
- “Open” currently means `DRAFT` or `ACTIVE`; “Completed” is `CLOSED`. This mapping must be explicit in code and tests.
- No completion percentage is rendered when the denominator or workflow state is absent.
- The 2023 column is shown only because the chart communicates zero honestly; it is not presented as a historical trend.
- The chart includes an accessible table equivalent.
- Recent activity must not invent run, finding, approval, or export events that the API has not stored.

**Mobile**

- KPIs stack into two columns, then one column below 430px.
- Charts stay full width with readable labels.
- Queue rows become compact stacked cards or horizontally scrollable table rows.
- The attention card moves above the KPI grid.

---

### 5.2 Clients and Review Periods

**Purpose:** Move from the client book into a specific review period without losing entity context.

**Hierarchy**

1. Client book count and archived-state control.
2. Add-client action.
3. Client identity and status.
4. Review-period list for the selected client.
5. Direct workspace entry per engagement.

**Truth constraints**

- Missing sector appears as “Not recorded.”
- Review status is the actual engagement status.
- The client card does not imply revenue, filings, or risk.
- Archived clients remain visually distinct and must not be mixed into active counts.

**Mobile**

- Single-column client card.
- Review rows become stacked rows with the period and status before secondary metadata.
- Primary review action remains reachable without horizontal scrolling.

---

### 5.3 Reconciliation Workspace

**Purpose:** Present the deterministic result at currency level while separating conclusion, method, identity, and evidence.

**Hierarchy**

1. Client and engagement context.
2. Engagement period and scenario period shown separately.
3. Scenario selector and run availability.
4. Synthetic-data warning.
5. Five-step workflow strip.
6. Workspace tabs.
7. Result summary: review required, with JOD difference and USD coverage badges.
8. Result counts: five findings, three review required, two informational, one no-conclusion currency.
9. JOD comparison: sales, difference, GL.
10. USD coverage block with no totals or verdict.
11. Method metadata and policy/rule chips.
12. Currency results table.
13. “What to check next” guidance.
14. Run context, fingerprints, report handoff.

**Truth constraints**

- USD totals remain blank with an explicit `INCOMPLETE_COVERAGE` explanation.
- The JOD difference is labelled exact and beyond tolerance.
- The scenario period is not conflated with the engagement period.
- Fingerprints are displayed as run identity, not decoration.
- “Equal totals are not proof of completeness” remains visible.
- No approval action is shown.

**Mobile**

- Context cards stack.
- The comparison grid becomes a vertical sequence: sales, difference, GL.
- JOD and USD coverage states must remain visible before secondary method metadata.
- Fingerprints wrap without truncating the identifying value.
- Tabs scroll horizontally but retain keyboard focus.

---

### 5.4 Findings Investigation

**Purpose:** Let the accountant investigate one finding without losing the order and source context of the run.

**Hierarchy**

1. Run inspected and findings fingerprint prefix.
2. Finding counts and review-required split.
3. Search and filter controls.
4. Ordered findings list.
5. Selected finding detail:
   - severity, kind, review state
   - what happened
   - why it matters
   - what was compared
   - what to check next
   - coverage warning
   - source evidence table
   - technical details
6. Explicit note that approval/resolution is not persisted.

**Truth constraints**

- Review-required findings appear before informational findings.
- Severity labels are presented only where the engine provides them.
- No “resolve,” “approve,” or “dismiss” control is shown.
- The selected finding’s evidence rows match the engine output exactly.
- Mobile details use disclosure elements so the full evidence remains available without a split-pane layout.

---

### 5.5 Reports

**Purpose:** Make the export package understandable before download and bind it to the displayed run.

**Hierarchy**

1. Report package heading and purpose.
2. Synthetic report identity.
3. Export formats: PDF and XLSX.
4. Manifest of contents:
   - conclusion
   - currency outcomes
   - coverage notes
   - ordered findings
   - evidence references
   - engagement and scenario periods
   - policy and rules metadata
   - both fingerprints
5. Language boundary: English-only exports.
6. Download state and stale-run rejection explanation.

**Truth constraints**

- No fake document preview.
- No claim that Arabic exports exist.
- No approval signature or filing status.
- No customer identity beyond the stored client name.

**Mobile**

- Export cards stack.
- Manifest rows remain legible without hiding fingerprints.
- Download controls stay above the fold or in a sticky action area.

---

### 5.6 Arabic Reconciliation Workspace

**Purpose:** Prove the core workspace can be localized for Arabic without damaging financial meaning.

**Hierarchy**

- Mirrored sidebar and content order.
- Arabic page title, description, tabs, summary, comparison, coverage, and guidance.
- English synthetic contract string retained exactly.
- LTR-isolated amounts, dates, IDs, fingerprints, dataset names, and technical codes.

**Truth constraints**

- Arabic copy uses the product’s actual labels and does not add stronger claims than the English screen.
- Financial values keep Western digits and LTR direction.
- The synthetic warning remains unambiguous.
- PDF/XLSX language limitation is stated in the interface where exports are offered.
- The design flag remains English and LTR for audit clarity.

**Mobile**

- Mirrored mobile navigation and workflow strip.
- Amount blocks remain LTR internally while aligning to the RTL reading order.
- Long technical strings wrap without overflowing the viewport.

---

## 6. Visual System

### 6.1 Color tokens

| Token | Value | Use |
| --- | --- | --- |
| `--canvas` | `#f3f7f6` | App background |
| `--canvas-deep` | `#e9f0ee` | Secondary background |
| `--surface` | `#ffffff` | Panels and cards |
| `--surface-2` | `#f7faf9` | Subtle inset surfaces |
| `--ink` | `#10282d` | Primary text |
| `--ink-2` | `#2c454b` | Secondary text |
| `--muted` | `#5d7378` | Supporting text |
| `--line` | `#d9e5e2` | Default border |
| `--nav` | `#0a2429` | Sidebar |
| `--jade` | `#0d766a` | Primary action and active state |
| `--jade-soft` | `#e8f5f1` | Selected surface |
| `--danger` | `#a63a3a` | Difference and destructive emphasis |
| `--warning` | `#9a6114` | Review attention |
| `--success` | `#1a6c49` | Reconciled/preserved states |
| `--info` | `#315f99` | Informational state |
| `--coverage` | `#5a568e` | Incomplete coverage |

Semantic color must be paired with text or an icon. Color alone is never the only carrier of meaning.

### 6.2 Typography

- UI: IBM Plex Sans.
- Arabic: IBM Plex Sans Arabic.
- Numeric, code, periods, IDs, and fingerprints: IBM Plex Mono, tabular numerals.
- H1: 32px, weight 650, tight tracking.
- H2: 18px, weight 640.
- Body: 14px with 1.5 line-height.
- Small: 12px.
- Tiny: 11px.
- Uppercase labels: 9–12px, increased tracking, used sparingly.

### 6.3 Spacing and shape

- Base unit: 8px.
- Panel padding: 16–20px desktop; 12–16px mobile.
- Card radius: 12px.
- Control radius: 8px.
- Small chip radius: 6px.
- Borders: 1px using `--line` or `--line-strong`.
- Shadow: subtle single-layer elevation; no floating glass panels.

### 6.4 Iconography

- Single inline SVG icon set injected by `assets/icons.js`.
- Default icon size: 16px.
- Icons are decorative unless paired with accessible text.
- Icon-only controls require an accessible name.
- No mixed icon families.

### 6.5 Data density

- Tables keep numeric columns right-aligned and tabular.
- Badges use short labels.
- Long identifiers wrap or scroll rather than truncating to an ambiguous token.
- Repeated metadata is grouped into a side panel or disclosure rather than spread across the page.

---

## 7. Responsive Behavior

| Breakpoint | Behavior |
| --- | --- |
| `> 1100px` | Full sidebar, split reconciliation/findings layouts, all tables visible. |
| `861–1100px` | Sidebar retained; analytics and side panels narrow; tables scroll. |
| `431–860px` | Sidebar collapses; mobile top bar and bottom navigation appear; two-column cards. |
| `<= 430px` | Single-column cards; stacked comparison; compact tabs; mobile finding disclosures. |

Requirements at every breakpoint:

- No horizontal document overflow at 390px or 1440px.
- No clipped fingerprints or amounts.
- No hidden conclusion or coverage state.
- Touch targets at least 44px for new controls.
- Tables either fit, scroll within a labelled region, or convert to cards.
- Sticky elements must not cover focused controls.

Captured viewports:

- Desktop: 1440 × 1000, full page.
- Mobile: 390 × 844, full page.

---

## 8. Accessibility

Target: WCAG 2.2 AA for the implemented interface.

- Preserve semantic landmarks: header, nav, main, aside, footer.
- One visible H1 per screen.
- Use real tables for tabular data; do not simulate tables with divs.
- Provide equivalent tables for charts.
- Ensure text and meaningful icon contrast meets AA.
- Keep a visible `:focus-visible` outline on all interactive elements.
- Support keyboard navigation for tabs, search, filters, and disclosure controls.
- Announce async run/export states with appropriate live regions in implementation.
- Do not rely on hover for essential information.
- Respect `prefers-reduced-motion`; the proposal only needs subtle transitions.
- Keep design-flag and synthetic-warning text readable at both viewports.
- Arabic content must set `lang="ar"` and `dir="rtl"` at the document or workspace root.

---

## 9. Internationalization and RTL

- The Arabic screen proves the reconciliation workspace only.
- Arabic UI copy must come from the shared locale layer, not hard-coded screen strings in production.
- New keys require English and Arabic values plus tests.
- Amounts, dates, IDs, fingerprints, currency codes, and technical enums stay LTR.
- Use logical CSS properties (`margin-inline`, `padding-inline`, `border-inline`) rather than left/right.
- The English synthetic contract string is not translated.
- Export language remains English-only until a separate Arabic export contract exists.
- The design reference flag stays English and LTR in both locales.

---

## 10. Truthful Data Contract

### 10.1 Current state

There is no dashboard analytics endpoint. The dashboard proposal uses counts derivable from stored clients and engagements. It does not display run, finding, approval, or export summaries that are not persisted.

### 10.2 Proposed summary endpoint

If dashboard aggregation moves server-side, add a tenant-scoped endpoint:

`GET /api/v1/dashboard/summary`

Proposed response:

```json
{
  "counts": {
    "clients": 1,
    "reviews": 3,
    "open_reviews": 3,
    "completed_reviews": 0
  },
  "status_distribution": [
    { "status": "DRAFT", "count": 3 },
    { "status": "ACTIVE", "count": 0 },
    { "status": "CLOSED", "count": 0 },
    { "status": "ARCHIVED", "count": 0 }
  ],
  "reviews_by_period": [
    { "period": 2024, "count": 1 },
    { "period": 2025, "count": 1 },
    { "period": 2026, "count": 1 }
  ],
  "latest_event": {
    "event_type": "engagement.created",
    "engagement_id": "b57b9d4a-5bf1-4b09-938d-eec6d4962164",
    "occurred_at": "2026-10-21T10:25:00Z"
  },
  "generated_at": "2026-10-22T00:00:00Z"
}
```

Rules:

- Tenant scoping is mandatory.
- Counts must come from stored records only.
- No revenue, liability, risk score, or tax outcome belongs in this contract.
- Sparse data must return zeros and empty arrays, not fabricated history.
- The frontend must still render an honest empty state if the endpoint is unavailable.
- `completed_reviews` means `CLOSED`; the meaning must be documented and tested.

### 10.3 Run identity

The reconciliation and findings screens bind to the displayed run:

- Reconciliation fingerprint
- Findings fingerprint
- Fixture ID
- Policy and rules version

Exports must reject stale run identity rather than silently exporting different data.

---

## 11. Component Plan

Reuse and extend the existing web components where possible.

| Design component | Implementation direction |
| --- | --- |
| App shell and sidebar | Extend `components/Nav.tsx` and the root layout. |
| Page header | Extend `components/PageHeader.tsx`. |
| Buttons | Extend `components/Button.tsx` with size/icon variants. |
| Status pills | Extend `components/StatusPill.tsx` with semantic variants. |
| Alerts and synthetic warnings | Extend `components/Alert.tsx`. |
| Empty and sparse states | Extend `components/EmptyState.tsx`. |
| Tabs | Extend `components/Tabs.tsx` with keyboard semantics. |
| Icons | Consolidate on `components/Icon.tsx`; do not duplicate SVG sources. |
| KPI cards | Extend `components/StatCard.tsx`. |
| Tables | Keep semantic tables; add a shared scroll container. |
| Charts | Add a shared accessible chart wrapper with a table fallback. |
| Findings split view | New workspace component composed from panels and disclosures. |
| Report manifest | New component using the existing export contract. |

Avoid a wholesale CSS replacement. Move shared tokens and primitives first, then migrate one screen at a time behind visual review.

---

## 12. Implementation Plan

### Phase 0 — Acceptance gate

- Founder and GPT-6 review all six screens at 1440 and 390.
- Confirm the visual direction, information hierarchy, and Arabic treatment.
- Resolve any requested changes in the static package before touching the app.

**Exit:** Written design acceptance.

### Phase 1 — Foundation

- Extract design tokens from `app.css` into the app theme.
- Establish typography, spacing, focus, radius, and semantic color variables.
- Build the desktop and mobile shell.
- Consolidate icon rendering.
- Add visual regression baselines for the existing working screens.

**Exit:** Shell and tokens pass existing tests; no functional route changes.

### Phase 2 — Shared primitives

- Page header, buttons, status pills, alerts, tabs, table container, KPI card, disclosure, and empty state.
- Document keyboard and focus behavior.
- Add component-level tests where behavior changes.

**Exit:** Primitives reviewed in isolation and in one live screen.

### Phase 3 — Dashboard

- Implement the truthful KPI and sparse-state model.
- Add the accessible review-volume chart and status distribution.
- Implement queue and recent activity.
- Add `GET /api/v1/dashboard/summary` only if server-side aggregation is required; otherwise derive client-side and document the choice.
- Test empty, single-client, and sparse-history states.

**Exit:** Dashboard counts match stored records; no invented metrics.

### Phase 4 — Clients and review navigation

- Migrate client book and client detail presentation.
- Preserve add-client and review-creation flows.
- Keep archived-client behavior intact.

**Exit:** Existing client flows pass end-to-end tests.

### Phase 5 — Reconciliation workspace

- Migrate context, run bar, conclusion, comparison, coverage, method, currency table, next checks, and side panels.
- Preserve synthetic-run behavior and exact server values.
- Verify mobile stacking and evidence accessibility.

**Exit:** JOD difference and USD coverage match the API byte-for-byte; no approvals added.

### Phase 6 — Findings

- Migrate the ordered list and selected detail.
- Keep mobile disclosures and evidence tables.
- Preserve the absence of persisted review actions.
- Add search/filter behavior only if it works against loaded data and is accessible.

**Exit:** All five findings and six evidence rows match the contract.

### Phase 7 — Reports

- Migrate report identity, export cards, and manifest.
- Preserve PDF/XLSX behavior and stale-run rejection.
- Confirm the English-only export limitation is visible.

**Exit:** Export downloads and hashes still match existing tests.

### Phase 8 — Arabic and RTL

- Move new copy into the shared locale layer.
- Apply logical properties across migrated components.
- Verify LTR isolation for amounts, dates, IDs, and fingerprints.
- Test the Arabic reconciliation workspace at 390 and 1440.

**Exit:** No overflow, no reversed numbers, no untranslated production labels.

### Phase 9 — Quality and cleanup

- Run typecheck, lint, unit tests, integration tests, and end-to-end tests.
- Check keyboard paths, focus order, contrast, chart tables, and screen-reader labels.
- Verify no horizontal overflow at 320, 390, 768, 1024, and 1440.
- Capture final implementation screenshots and compare against this package.
- Remove obsolete CSS only after all screens are migrated.

**Exit:** Full CI green; design acceptance documented.

---

## 13. Acceptance Criteria

The design package is accepted when:

- All six screens and twelve captures are present and render without missing icons or console errors.
- No screen overflows horizontally at 1440 or 390.
- Dashboard metrics are derived from stored records with explicit sparse-state language.
- Reconciliation shows the exact JOD difference and refuses to invent USD totals.
- Findings are ordered correctly and carry the real evidence rows and identifiers.
- Report content matches the export contract and states the English-only limitation.
- Arabic is genuinely mirrored, not merely translated, and keeps financial values LTR.
- No approval, risk score, customer record, or production claim is fabricated.
- The founder and GPT-6 explicitly accept the direction.

Implementation acceptance requires all existing functional and security tests to remain green and all Phase 9 checks to pass.

---

## 14. Risks and Open Questions

- **Dashboard aggregation:** client-side derivation is acceptable for the current small book, but a server summary endpoint needs a separate contract review.
- **Review-state semantics:** the UI must not call a review “completed” unless the engagement is `CLOSED`; this mapping needs tests.
- **Arabic scope:** this package covers only reconciliation. Extending Arabic to every screen and export needs separate design and copy review.
- **Font delivery:** the static screens use Google Fonts. Production should self-host or use the existing approved font strategy to avoid layout shifts and third-party dependency.
- **Design flag placement:** keep the proposal flag visible in review artifacts, but do not ship it into the running app.
- **Responsive evidence tables:** wide evidence tables may still need horizontal scrolling on small screens; confirm that the scroll region is labelled and keyboard reachable.
- **Reports route:** decide whether the workspace report screen and global `/reports` list share one component or remain separate presentations.
- **No hosted preview:** the static package is available in the branch only; there is no connected hosted API to demonstrate.

---

## 15. Static Package

| File | Purpose |
| --- | --- |
| `index.html` | Review gallery with links to all screens and captures |
| `DESIGN_SPEC.md` | This specification and implementation plan |
| `assets/app.css` | Shared visual system and responsive rules |
| `assets/icons.js` | Inline SVG icon injector |
| `screens/dashboard.html` | Dashboard proposal |
| `screens/clients.html` | Clients and review-period proposal |
| `screens/reconciliation.html` | English reconciliation workspace |
| `screens/findings.html` | Findings investigation |
| `screens/reports.html` | Report package |
| `screens/reconciliation-ar.html` | Arabic RTL reconciliation workspace |
| `screenshots/*-1440.png` | Full-page desktop captures |
| `screenshots/*-390.png` | Full-page mobile captures |

All static screens use the same shared CSS and icon script. They are design artifacts only and must remain clearly labelled as such.

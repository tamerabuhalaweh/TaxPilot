# REC-UI-02 — Accountant demo script

Audience: Jordanian accounting-firm partners and senior accountants.
Goal: show a safe, honest reconciliation walkthrough and collect feedback on
usefulness — not to imply production tax processing.

All figures come from the built-in `synthetic-sales-gl-v1` scenario. Nothing is
read from, or written to, a customer ledger.

## Before the call

1. Start the web app in demo mode (build-time flag) for a backend-free visual
   walkthrough:
   ```bash
   NEXT_PUBLIC_PREVIEW_MODE=demo npm run build
   npm start -- --port 3001
   ```
2. For the real synthetic scenario (run, exports, fingerprints), start the API
   with the restricted demo flag and the web app against it:
   ```bash
   TAXPILOT_DEMO_RECON_ENABLED=1 python -m uvicorn app.main:app --port 8000 --app-dir apps/api
   API_INTERNAL_URL=http://127.0.0.1:8000 npm start -- --port 3000
   ```
3. Use a desktop browser at 100% zoom. Keep the Arabic toggle available to show
   RTL on request.

The demo flag is development/staging-only; production forces it off.

## 10-minute walkthrough

1. **Dashboard** — point out measured counts (clients, reviews, open/completed),
   recent reviews, and the persistent `SYNTHETIC DEMO DATA` banner. No invented
   KPIs.
2. **Clients → client → Reviews** — open the seeded client and review. Show that
   the sidebar highlights the section and the review row exposes period, type,
   and status.
3. **Review workspace** — show client, period, review type, status, and the
   synthetic scenario/period. Then select `Synthetic sales ↔ GL v1` and press
   **Run reconciliation**.
4. **Result summary** — read the conclusion aloud: *Review required — 3
   findings need a person; 1 currency differs beyond tolerance: JOD.* Point out
   the plain-language coverage reason: USD coverage is incomplete because rows
   were dropped as duplicates. Emphasise: equal totals do not prove
   completeness.
5. **Currency results** — JOD sales 3,500.000 vs GL 3,400.000 → difference
   100.000; USD marked inconclusive for coverage, not “matched”.
6. **Findings** — default order is review-required first. Show HIGH `Sales and
   GL totals differ`, then the USD duplicate-coverage finding, then the
   informational low-severity notes. Open **What to check next** and the
   evidence rows. Use the severity/kind filter to show the two informational
   notes.
7. **Reports** — explain that exports are bound to the displayed run and its
   fingerprints; a stale tab gets a conflict instead of the wrong file. Export
   **PDF** and **XLSX**, and show the report summary, findings, evidence, page
   numbers, and footer `not customer records / not a tax filing`.
8. **Honest gaps** — open **Documents** and **New Review**: uploads are disabled
   in this version; a synthetic scenario is built in. No approval or filing
   action exists.
9. **Arabic + mobile** — toggle العربية: UI labels, result summary, guidance,
   and coverage reasons translate; engine text stays English and is marked as
   such. At 390 px, evidence becomes stacked cards, not a squeezed table.
10. **Close** — ask the feedback questions below. Do not promise dates or
    Jordanian legal conclusions.

Expected v1 numbers: 5 findings (3 review-required, 2 informational), JOD
100.000 difference, USD `INCONCLUSIVE_COVERAGE`, summary status
`REVIEW_REQUIRED`.

## Known limitations to state plainly

- Synthetic scenario data only; no customer file intake or mapping approval
  until SEC-SOURCE-02 gates are approved.
- One deterministic rule set (REC-005) for sales ↔ GL; not a full tax engine.
- PDF/XLSX are English-only. No approval workflow, e-signature, or filing
  export.
- Nothing here is tax advice or a filing.

## Feedback questions (5–8)

1. Would this conclusion and per-currency table let you brief a client without
   re-reading the raw data?
2. Is “what to check next” specific enough for a junior accountant to act on?
3. Which finding would you investigate first, and why?
4. Are the coverage and low-severity notes clear without accounting jargon?
5. What is missing before you would trust this in a real engagement?
6. Do the PDF/XLSX layouts match what you hand to a client or reviewer?
7. Is the Arabic UI sufficient for your team, and which engine terms must be
   translated next?
8. What would make the next demo a clear yes/no for a pilot?

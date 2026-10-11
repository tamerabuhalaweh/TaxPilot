# Country expansion roadmap (JUR-04, #31; P0 foundation vs P1/P2 activation)

**Rule:** commercial revenue milestones are decision points, never auto-activation. Each pack needs the gate below + signed release + rollback before production tax use. No AE/SA rules, rates, or integrations in this PR.

## P0 now (this branch, JO-safe)
Catalog (JO ACTIVE / AE,SA PLANNED) + 8-object model + context freeze + pack interface + JO pack manifest (only individually expert-approved REC/accounting capabilities) + minimal Tax & Countries UX + migration + 18 tests planned. JO onboarding stays one-click-confirmed.

## P1 — UAE (after JO revenue validation + readiness)
Checklist: FTA VAT + corporate-tax requirements researched separately (they are distinct); registration distinctions; e-invoicing requirements; tax grouping semantics; business classifications; representative AE customer files; official source verification (examples only, expert must validate: FTA CT guides https://tax.gov.ae/en/taxes/corporate.tax/corporate.tax.guides.references.aspx, VAT group https://tax.gov.ae/en/services/tax.group.registration.aspx, CT registration https://www.tax.gov.ae/en/services/corporate.tax.registration.aspx); local AE tax-expert approval; golden fixtures + historical-date tests; RAG AE segmentation; AE accountant UAT; data/privacy/legal gates; activation flag + rollback. Domestic branch ≠ separate CT registration (verify per case).

## P2 — Saudi Arabia (after AE)
Checklist: ZATCA VAT + Zakat/income-tax distinctions (SA is not VAT-only); FATOORA formats/validation (ref https://www.zatca.gov.sa/en/E-Invoicing/Pages/default.aspx; VAT groups https://zatca.gov.sa/en/eServices/Pages/eservices-003.aspx); obligations; representative SA files; official verification; local SA expert; fixtures + historical tests; RAG SA segmentation; UAT; gates; flag + rollback.

## Global later
Approved pack templates + supported regimes; subnational/special zones as well-defined extensions (not flat country field). Same gate per country. Discovery URLs above are architecture references only, not legal approval.

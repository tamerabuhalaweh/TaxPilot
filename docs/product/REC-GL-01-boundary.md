# REC-GL-01 / REC-005 — Sales Register ↔ General Ledger reconciliation boundary

Status: **foundation (pure contracts + default-deny engine), synthetic-only.**
No production reconciliation, no migration, no HTTP endpoint, no worker wiring,
no live GL parsing. This document records what is implemented, what is
deliberately blocked, and the accounting decisions required before any real
REC-005 run may occur.

Baseline: `main` merge commit `3b5c3e71843e55bdf80b8e4b1ef8d7b37d2a980e`
(PR #66). Issue #67. Predecessors: REC-001..004 (sales↔JoFotara) unchanged.

## 1. Why this slice is default-deny

SRS Master v2.0 defines REC-005 as *"Sales Register → GL; mapped totals vs GL
with mappings/periods/currencies/adjustments/tolerances."* The approved
normalized GL contract (`app/normalization/contracts.py`, `GL_FIELDS`) exposes
only:

> `account_code, transaction_date, debit_amount, credit_amount, currency,
> description` (required: `account_code`, `transaction_date`).

There is **no** verified GL reference/invoice column, **no** account taxonomy,
and **no** approved sales→account mapping anywhere in the repository or SRS.
Those are **accounting decisions**, not engineering defaults. Per the issue, the
engine therefore never invents a scope, measure, sign convention, or FX rule: it
runs only under an explicit approved policy and refuses otherwise.

## 2. Comparison level supported by grounded fields

| Level | Grounded? | Status |
|---|---|---|
| Aggregate totals by currency/period over an approved account scope | Yes — needs only the six GL fields + a declared policy | **Implemented** (`BASIS_AGGREGATE_PERIOD`) |
| Invoice-to-GL-line matching | No — no grounded GL reference field / mapping | **Declared, refused** (`BASIS_INVOICE_REFERENCE` → `POLICY_UNSUPPORTED_BASIS`) |
| Per-account closing-balance / TB reconciliation (AQ-006) | Needs an approved account taxonomy + closing-balance source | **Blocked** (decision request below) |

## 3. Implemented vs blocked

| Area | Implemented | Blocked / deferred |
|---|---|---|
| GL input contracts | `GLLine`, `GLEntryProvenance`, `SalesRegisterEntry` (immutable, exact Decimal, verbatim identifiers, genuine positive-int provenance rows) | — |
| Policy contract | `GLComparisonPolicy` + `GLPolicyProvenance` + `validate_policy` + `GLPolicyRegistry` (default **empty**) | Trusted/independently verified policy source (real approval) |
| Default-deny | `NO_APPROVED_POLICY` + typed dimension reasons; blocked report with empty outcomes | — |
| Engine | deterministic aggregate comparison per currency; exact integer-scaled arithmetic; stable fingerprints | Invoice-level basis; FX; tax/refund/credit-mapping rules |
| Findings | `project_gl` review projection (review-required wording, evidence, rule/version/tolerance metadata); default-deny item | Decisions/persistence/reports (later slices) |
| Wiring | none | normalization adapter for GL; dataset-version/mapping approval; release gate; HTTP; queue |

## 4. Policy dimensions (all caller-supplied, validated)

`GLComparisonPolicy` requires, with no defaults for the accounting choices:

- `comparison_basis` — `AGGREGATE_PERIOD` (supported) or `INVOICE_REFERENCE`
  (refused). **Which accounts represent the sales-side postings** is not encoded
  anywhere; the caller approves the scope.
- `gl_account_scope` — explicit account-code allow-list (no wildcard). Codes
  stay verbatim (leading zeros preserved).
- `sales_measure` — `NET` / `TAX` / `GROSS` (the policy chooses; the engine
  reads the selected measure from each sales row).
- `debit_credit_convention` — `DEBIT_POSITIVE` or `CREDIT_POSITIVE`. A line's
  `debit`/`credit` columns are combined only under this declared convention,
  never by an implicit `debit − credit`.
- `currency_scope` — explicit currency allow-list (no default JOD, no FX).
- `tolerance` — exact `Decimal ≥ 0`, finite.
- `status` = `APPROVED` + `approved_by` + `GLPolicyProvenance`.

### Default-deny reason codes

`NO_APPROVED_POLICY`, `POLICY_NOT_APPROVED`, `POLICY_MISSING_PROVENANCE`,
`POLICY_MISSING_BASIS`, `POLICY_UNSUPPORTED_BASIS`,
`POLICY_MISSING_ACCOUNT_SCOPE`, `POLICY_MISSING_CURRENCY_SCOPE`,
`POLICY_MISSING_SALES_MEASURE`, `POLICY_MISSING_CONVENTION`.

A blocked run returns a `GLComparisonReport` with `blocked=True`, the reasons,
and **no outcomes**; `project_gl` renders a single review-required
`INSUFFICIENT_CONTRACT` item rather than fabricating a comparison.

## 5. Rules that hold on every path

- **Debit/credit independence.** Missing values are never zero; a line with
  both a debit and a credit is reported (`INVALID_DEBIT_CREDIT_PAIR`, per
  AQ-008) and excluded, never netted.
- **Currency segregation.** Currencies never combine; an out-of-scope currency
  is refused (`CURRENCY_NOT_IN_SCOPE`), never converted (no FX).
- **Duplicates.** Duplicate GL identity (`journal_id`, `line_number`) or sales
  key (issuer+number) are reported (`DUPLICATE_GL`/`DUPLICATE_SALES`) and
  excluded; a currency bucket touched by a duplicate gets **no**
  `RECONCILED`/`DIFFERENCE` verdict (never a false conclusion).
- **Credit notes & reversals** link ONLY through an explicit reference to an
  existing document; otherwise preserved as relationship-unverified. Amounts are
  never netted (`CREDIT_NOTE_LINKED/…UNVERIFIED`, `REVERSAL_NOTED/…UNVERIFIED`).
- **Period.** Out-of-period (`PERIOD_OUTSIDE`) and dateless (`PERIOD_UNKNOWN`)
  rows are surfaced and excluded, never silently netted.
- **Exactness & determinism.** Aggregation is integer-scaled and independent of
  the ambient decimal context; outcomes and fingerprints are stable under any
  input permutation.
- **Coverage.** Out-of-scope accounts are counted (`gl_out_of_scope`), never
  silently attributed.

## 6. Declared-claim trust model

As with REC-DATA-02 and REC-JOFO-01: a caller-constructed `GLComparisonPolicy`
carrying `status="APPROVED"` and a `GLPolicyProvenance` is a **declared claim,
not authorization**. It must never be treated as a real accounting approval.
`DEFAULT_GL_POLICY_REGISTRY` is empty and there is no global/ambient policy;
genuine authorization requires a trusted, independently verified policy source
populated through the accounting approval gate (accounting review → tax review
where tax-concluding → publish → signed dry-run → tenant enablement).

## 7. Compatibility

REC-001..004 (sales↔JoFotara) contracts, engine, and findings are **unchanged**;
the GL domain is a separate package (`app/recon/gl/`) that reuses only
`InvoiceProvenance`/`SalesRegisterEntry` shapes and the established exact-decimal
and evidence conventions. All existing unit and integration tests remain green.

## 8. Blockers and decision requests

Existing blockers (see `docs/engineering/BLOCKERS.md`): **B-03** (no authorized
General Ledger samples), **B-01/B-02** (no authorized JoFotara/Sales samples),
**B-04** (tax-domain expert), **B-09/DEC-13** (repo classification),
**B-10** (SRS amendment approval). Recorded decisions that gate enabling REC-005
for real data: **DEC-04** (validated recon targets + source versions),
**DEC-01** (templates/fixtures), **DEC-02/03** (retention/residency),
**DEC-06** (blocker/SoD), **DEC-10** (JoFotara profiles).

**New decision requests (owner: PO + accountant + tax expert; needed before any
real REC-005 run):**

1. **GL comparison policy** — for each engagement/client: which GL accounts
   constitute the sales-side postings, the sales measure to compare (net/tax/
   gross), the debit/credit sign convention, and the approved tolerance.
2. **GL coverage rule** — how to treat GL periods/accounts with no sales
   activity and sales with no in-scope GL posting (coverage vs. timing vs.
   error), including late-posting and reversal/netting treatment.
3. **Multi-currency / FX** — whether any FX translation is authorized (today:
   none; currencies are segregated and out-of-scope currencies are refused).
4. **TB / account-closing reconciliation (AQ-006)** — taxonomy and
   closing-balance source, if in scope for REC-005 or a later slice.
5. **Invoice-level basis** — whether a verified GL document-reference field
   will exist to enable invoice-to-line matching (`BASIS_INVOICE_REFERENCE`).

## 9. Evidence

- `apps/api/app/recon/gl/{contracts,policy,matching,findings}.py` — pure domain.
- `apps/api/tests/test_recon_gl_contracts.py`,
  `test_recon_gl_matching_golden.py`, `test_recon_gl_findings_golden.py` — 41
  synthetic tests: default-deny, reconciled/difference/tolerance, coverage,
  malformed/missing values, currency segregation, period, duplicates, credit
  notes/reversals, permutation-stable fingerprints, long-precision exactness.
- Full `apps/api/tests` suite green; `ruff check`, `ruff format --check`, and
  `mypy apps/api` clean.

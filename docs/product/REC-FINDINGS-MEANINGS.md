# Reconciliation findings — accountant-facing outcome meanings (REC-SLICE-02)

Read model only. Projection code: `apps/api/app/recon/findings.py`
(policy version `1`); tests: `apps/api/tests/test_recon_findings_golden.py`.
No persistence, no review decisions, no report rendering in this slice.

## What each outcome means (plain language, no tax or legal conclusions)

| Outcome | Review? | Meaning for the accountant |
|---|---|---|
| `EXACT_MATCH` | No (informational) | Both sides agree on identity and amount. Kept for completeness and audit traceability. Flags such as `WITHIN_TOLERANCE` or `PERIOD_OUTSIDE` are context, not discrepancies. |
| `AMOUNT_MISMATCH` | Yes — HIGH | Same invoice, different amounts. The finding states the exact sales-minus-JoFotara difference. Confirm which source amount is correct. |
| `UNMATCHED_SALES` | Yes — HIGH | Invoice is in the sales register but has no JoFotara counterpart. Check whether the JoFotara export is missing it. |
| `UNMATCHED_JOFOTARA` | Yes — HIGH | Invoice is in the JoFotara export but has no sales counterpart. Check whether the sales register is missing it. |
| `DUPLICATE_SALES` / `DUPLICATE_JOFOTARA` | Yes — MEDIUM | The same issuer and invoice number appears more than once on one side. Treated as a *possible* duplicate pending review — never asserted as wrongdoing. Confirm repeated export vs. distinct records. |
| `AMBIGUOUS` | Yes — MEDIUM | No single automatic answer: duplicate counterparts, a currency mismatch (no difference is ever computed across currencies), or values missing for comparison (missing values are never zero). Resolve from the source rows, then re-run. |
| `INSUFFICIENT_DATA` | Yes — MEDIUM | A row lacks fields needed for matching or comparison. Complete the source data and re-run; nothing is zero-filled. |
| `CREDIT_NOTE_LINKED` / `REVERSAL_NOTED` | No (informational) | Linked to its original document through an explicit reference. Amounts are not netted. |
| `CREDIT_NOTE_UNVERIFIED` / `REVERSAL_UNVERIFIED` | No (informational) | Preserved with its reference problem stated (`NO_REFERENCE`, `REFERENCE_UNRESOLVED`, `AMBIGUOUS_TARGET`). No link is asserted. |

Every finding carries: rule reference (e.g. `JO/REC-001/1`), exact-amount
views, dataset + row + raw-invoice evidence pointers, rationale codes, flags,
and a review-required marker. Exact matches never become open discrepancies.

## Missing dependencies for downstream slices (REC-SLICE-03 / EP-10 UI / EP-11)

1. Engagement/client persistence and scoping (no engagement model on main).
2. Findings + `ReviewDecision` persistence (append-only decision log, FR-FND-004).
3. Review-decision API (confirm / dismiss / need-evidence with justification).
4. Stale/superseded handling on new source, mapping, or rule versions (FR-FND-006).
5. Reconcile execution wiring (jobs/outbox trigger from approved dataset versions).
6. Review workspace UI (filters, evidence drill-down, bilingual strings).
7. Report rendering (PDF/XLSX) over approved snapshots.

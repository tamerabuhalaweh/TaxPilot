# Golden-test plan — jurisdiction (JUR-01/02/03, #28/#29/#30; 18 cases from instruction §10)

Each case: fixture (seed tenants/clients/entities/profiles/contexts/datasets) → action (API/worker/UI) → expected (exact errors, 0-executions where required, isolation, immutability). JO recon suite (ATR-001..012) unchanged and must still pass.

1. **Cross-tenant isolation:** Tenant A reads/modifies B entity/presence/profile/registration/context/report by ID → 403/404, no leak, audit logged. (Security gate.)
2. **Multi-entity client:** one client → JO + AE + SA entities; create engagement per entity; assert no cross-entity joins in findings/reports/exports.
3. **Presence ≠ entity:** JO entity + Dubai presence → still one entity; no AE obligation auto-created; JO accounting review runnable; AE treatment absent.
4. **Multi-profile + numbers:** one entity → VAT + CT (AE-style) or sales + income (JO-style) profiles with distinct numbers → numbers never cross categories; masked reads.
5. **Group explicitness:** common ownership of 3 entities → no group exists until created with jurisdiction+tax-type+dates+evidence; overlapping membership rejected; unverified group cannot scope execution.
6. **JO-only execution:** confirmed JO context + eligible datasets → REC rules run; AE/SA planned contexts → `JURISDICTION_NOT_SUPPORTED`, 0 executions, no JO fallback (API + worker paths).
7. **History freeze:** JO 2024 engagement executed; change profile in 2026 → 2024 report/findings byte-identical; new work uses new revision.
8. **Revision on change:** edit registration/period → new context revision; unissued affected findings SUPERSEDED; issued reports immutable; approval re-required.
9. **Wrong-country dataset:** AE-source file attached to JO context (or vice versa) → `CROSS_ENTITY_SCOPE_CONFLICT` + actionable correction; nothing silently imported.
10. **Currency segregation:** JOD + AED + SAR amounts in one client → never aggregated; reports show per-currency buckets; no FX netting without versioned approved policy.
11. **AR/EN + RTL:** entity/country/tax-type forms + selector render in AR (RTL) and EN; mixed-script invoice IDs preserved; validation messages localized.
12. **RAG segmentation:** JO question → JO sources only; AE question → AE-eligible sources only (or explicit none-planned); historical as-of honored; no cross-tenant passage leak. (Coordinates #21/#22.)
13. **Cross-border review routing:** dataset with uncertain foreign treatment → `NEEDS_MORE_EVIDENCE`/reviewer queue; no auto domicile/rate assignment.
14. **Roles:** Owner/Admin manage registrations; Accountant drafts/suggests; Reviewer confirms where configured; Viewer denied writes; sensitive fields masked per grant. Matrix test.
15. **Flag enforcement:** disable JO pack (or retire version) → new runs blocked (`PACK_NOT_APPROVED`) via API and direct worker call; history readable.
16. **Migration safety:** legacy JO client+engagement (no context) → backfill creates entity+profiles+`NEEDS_CONFIRMATION` context; confirmation unblocks runs; issued reports never rewritten; row counts reconciled.
17. **No false compliance:** unsupported jurisdiction review → report shows explicit coverage limitations + skipped packs; never a "compliant" verdict.
18. **Invalid combos:** bad country/tax-type/entity/registration/period permutations → explicit 422 errors naming the invalid field (not silent defaults).

**Gates:** financial correctness (exact decimals), tenant isolation, and historical reproducibility remain release-blocking alongside these 18. Fixtures versioned with pack/profile/context versions; failures surfaced with evidence, never claimed green without runs.

> **STATUS: UNRESOLVED — DEC-11 pending.** No provider selected; the MVP runs provider-free.
> Governing requirements: `TAXPILOT_MASTER_SRS.md` §8.

# ADR-002 — AI provider (DECISION REQUIRED, blocks AI prod use)

Status: Proposed (SRS v1.1 §14, DEC-11). Owner: Tech Lead + Legal. MVP must work with NO provider configured.

## Options
1. Approved external provider(s).
2. Self-hosted model(s).
3. Hybrid (deterministic + minimal external assist).

Existing AI infra may offer reusable components — no cross-project runtime dependency without explicit decision here.

Do NOT assume ASR provides OCR.

## Comparison criteria
- Arabic quality + reasoning (human rubric + citation correctness + abstention).
- Processing accuracy (extraction numeric ≥98% digital-text target, provisional).
- Inference cost + infra cost per engagement.
- Hosting location + privacy/retention terms + transfer basis.
- Operational complexity + security exposure (prompt-injection surface, tool allowlist).

## P0 vs P1 split (enforced regardless of choice)
- P0: validation, deterministic recon, provenance, versioning, human review, uncertainty, AI security.
- P1: narrative explanations, broad RAG QA, semantic classification, scanned OCR, anomaly models.

## Decision log
- [ ] Option chosen + rationale + cost model
- [ ] Provider DPA / retention terms approved
- [ ] Eval corpus frozen + results
- [ ] Fallback (no-provider) verified in E2E

"""REC-DATA-02 unit contracts: default-deny human-confirmed mapping approval.

Proof obligations (issue #63):

- no approval without an explicit human APPROVED decision by a verified reviewer;
- AI suggestions and caller-supplied fingerprints/booleans can never count;
- absent trusted source headers => SOURCE_HEADERS_UNAVAILABLE;
- any dataset/header/mapping/normalization/schema/engagement drift => stale;
- the latest decision wins, and revocation is a new decision, not a rewrite.

Golden maps cover English and Arabic headers plus an ambiguous (unmappable)
header shape; real-PG integrity/concurrency is covered by the integration suite.
"""

from app.mapping import (
    APPROVED,
    DECISION_APPROVED,
    DECISION_REJECTED,
    DECISION_SUPERSEDED,
    FOREIGN_DECISION_PROPOSAL,
    FOREIGN_DECISION_TENANT,
    INVALID_MAPPING,
    MAPPING_APPROVAL_NOT_ENABLED,
    MAPPING_REJECTED,
    MAPPING_SUPERSEDED,
    MISSING_APPROVAL,
    MISSING_PROPOSAL,
    SOURCE_HEADERS_UNAVAILABLE,
    STALE_DATASET_VERSION,
    STALE_ENGAGEMENT_REVISION,
    STALE_HEADER_FINGERPRINT,
    STALE_MAPPING_VERSION,
    STALE_NORMALIZATION_VERSION,
    STALE_SCHEMA_VERSION,
    UNCONFIRMED_PROPOSAL,
    UNKNOWN_SCHEMA_VERSION,
    UNTRUSTED_REVIEWER,
    ApprovalCoordinates,
    MappingDecision,
    MappingProposal,
    ReviewerAuthorization,
    evaluate_mapping_approval,
    latest_decision,
    proposal_fingerprint,
    staleness_reason,
)
from app.normalization.mapping import fingerprint_headers
from app.normalization.suggest import suggest_mapping

EN_HEADERS = (
    "Invoice Number",
    "Transaction Date",
    "Net Amount",
    "Tax Amount",
    "Gross Amount",
    "Currency",
    "Description",
)
EN_MAP = {
    "invoice_number": "Invoice Number",
    "transaction_date": "Transaction Date",
    "net_amount": "Net Amount",
    "tax_amount": "Tax Amount",
    "gross_amount": "Gross Amount",
    "currency": "Currency",
}
AR_HEADERS = ("رقم الفاتورة", "التاريخ", "صافي المبلغ", "الضريبة", "الإجمالي", "العملة")
AR_MAP = {
    "invoice_number": "رقم الفاتورة",
    "transaction_date": "التاريخ",
    "net_amount": "صافي المبلغ",
    "tax_amount": "الضريبة",
    "gross_amount": "الإجمالي",
    "currency": "العملة",
}

SCHEMA_VERSION = "mapping-v1"


def _coords(**overrides: object) -> ApprovalCoordinates:
    base: dict = {
        "dataset_version_id": "dv-1",
        "engagement_revision": 1,
        "mapping_version": "m1",
        "normalization_version": "n1",
        "canonical_schema_version": SCHEMA_VERSION,
    }
    base.update(overrides)
    return ApprovalCoordinates(**base)


def _proposal(
    headers: tuple[str, ...] = EN_HEADERS,
    mapping: dict[str, str] | None = None,
    **overrides: object,
) -> MappingProposal:
    base: dict = {
        "proposal_id": "p-1",
        "tenant_id": "t-1",
        "client_id": "c-1",
        "engagement_id": "e-1",
        "dataset_version_id": "dv-1",
        "doc_type": "sales_register",
        "header_fingerprint": fingerprint_headers(headers),
        "field_map": mapping if mapping is not None else EN_MAP,
        "mapping_version": "m1",
        "normalization_version": "n1",
        "canonical_schema_version": SCHEMA_VERSION,
        "engagement_revision": 1,
        "confirmed": True,
    }
    base.update(overrides)
    return MappingProposal(**base)


def _decision(decision: str, **overrides: object) -> MappingDecision:
    base: dict = {
        "decision_id": "d-1",
        "tenant_id": "t-1",
        "proposal_id": "p-1",
        "decision": decision,
        "reviewer_id": "u-reviewer",
        "decided_at": "2026-01-01T00:00:00Z",
    }
    base.update(overrides)
    return MappingDecision(**base)


def _authorization(*reviewers: str) -> ReviewerAuthorization:
    return ReviewerAuthorization(frozenset(reviewers or ("u-reviewer",)))


def _eval(**overrides: object):  # type: ignore[no-untyped-def]
    kwargs: dict = {
        "proposal": _proposal(),
        "decisions": (_decision(DECISION_APPROVED),),
        "coordinates": _coords(),
        "trusted_headers": EN_HEADERS,
        "approval_enabled": True,
        "reviewer_authorization": _authorization(),
    }
    kwargs.update(overrides)
    return evaluate_mapping_approval(**kwargs)


# -- master default-deny --------------------------------------------------------


def test_master_default_deny_with_complete_evidence() -> None:
    outcome = _eval(approval_enabled=False)
    assert (outcome.approved, outcome.reason) == (False, MAPPING_APPROVAL_NOT_ENABLED)


def test_trusted_headers_absent_refuses() -> None:
    outcome = _eval(trusted_headers=None)
    assert (outcome.approved, outcome.reason) == (False, SOURCE_HEADERS_UNAVAILABLE)


def test_missing_proposal_refuses() -> None:
    outcome = _eval(proposal=None)
    assert outcome.reason == MISSING_PROPOSAL


def test_ai_suggestion_is_not_approval() -> None:
    # suggest_mapping is advisory; an unconfirmed proposal can never approve.
    suggestions = suggest_mapping(EN_HEADERS, "sales_register")
    assert all(s.canonical is not None for s in suggestions)  # helpful, still not approval
    outcome = _eval(proposal=_proposal(confirmed=False))
    assert outcome.reason == UNCONFIRMED_PROPOSAL


def test_unknown_schema_version_refuses() -> None:
    outcome = _eval(coordinates=_coords(canonical_schema_version="mapping-v0"))
    assert outcome.reason == UNKNOWN_SCHEMA_VERSION


# -- caller cannot forge a fingerprint -----------------------------------------


def test_forged_header_fingerprint_is_stale() -> None:
    outcome = _eval(proposal=_proposal(header_fingerprint="0" * 64))
    assert outcome.reason == STALE_HEADER_FINGERPRINT


# -- staleness ------------------------------------------------------------------


def test_each_coordinate_drift_is_stale() -> None:
    assert _eval(proposal=_proposal(dataset_version_id="dv-2")).reason == STALE_DATASET_VERSION
    assert _eval(proposal=_proposal(mapping_version="m2")).reason == STALE_MAPPING_VERSION
    assert _eval(proposal=_proposal(normalization_version="n2")).reason == STALE_NORMALIZATION_VERSION
    assert _eval(proposal=_proposal(canonical_schema_version="mapping-v0")).reason == STALE_SCHEMA_VERSION
    assert _eval(proposal=_proposal(engagement_revision=2)).reason == STALE_ENGAGEMENT_REVISION
    # header shape drift (same field names, different trusted headers).
    drifted = EN_HEADERS + ("Extra Column",)
    assert (
        _eval(proposal=_proposal(headers=EN_HEADERS), trusted_headers=drifted).reason
        == STALE_HEADER_FINGERPRINT
    )


def test_staleness_reason_helper_is_pure() -> None:
    proposal = _proposal()
    fp = proposal.header_fingerprint
    assert staleness_reason(proposal, _coords(), header_fingerprint=fp) == ""
    assert staleness_reason(proposal, _coords(dataset_version_id="dv-x"), header_fingerprint=fp) == (
        STALE_DATASET_VERSION
    )


# -- invalid / conflicting mapping ---------------------------------------------


def test_invalid_mapping_reports_issue_codes() -> None:
    # required net_amount missing for sales_register.
    outcome = _eval(proposal=_proposal(mapping={"invoice_number": "Invoice Number"}))
    assert outcome.reason == INVALID_MAPPING
    assert "MISSING_REQUIRED_FIELD" in outcome.issues


def test_conflicting_mapping_refused() -> None:
    outcome = _eval(
        proposal=_proposal(
            mapping={
                "invoice_number": "Invoice Number",
                "transaction_date": "Transaction Date",
                "net_amount": "Net Amount",
                "tax_amount": "Net Amount",  # same source column as net_amount
            }
        )
    )
    assert outcome.reason == INVALID_MAPPING
    assert "CONFLICTING_MAPPING" in outcome.issues


def test_ambiguous_header_shape_refused() -> None:
    ambiguous = ("Col A", "Col B", "Col C")
    proposal = _proposal(headers=ambiguous, mapping={"invoice_number": "Col A"})
    outcome = _eval(proposal=proposal, trusted_headers=ambiguous)
    assert outcome.reason == INVALID_MAPPING


# -- decisions ------------------------------------------------------------------


def test_missing_approval_refused() -> None:
    outcome = _eval(decisions=())
    assert outcome.reason == MISSING_APPROVAL


def test_rejection_and_supersede_refused() -> None:
    assert _eval(decisions=(_decision(DECISION_REJECTED),)).reason == MAPPING_REJECTED
    assert _eval(decisions=(_decision(DECISION_SUPERSEDED),)).reason == MAPPING_SUPERSEDED


def test_latest_decision_wins() -> None:
    # approve then reject (later timestamp) => rejected.
    decisions = (
        _decision(DECISION_APPROVED, decision_id="d-1", decided_at="2026-01-01T00:00:00Z"),
        _decision(DECISION_REJECTED, decision_id="d-2", decided_at="2026-01-02T00:00:00Z"),
    )
    assert _eval(decisions=decisions).reason == MAPPING_REJECTED
    # reject then approve (later) => approved.
    decisions = (
        _decision(DECISION_REJECTED, decision_id="d-1", decided_at="2026-01-01T00:00:00Z"),
        _decision(DECISION_APPROVED, decision_id="d-2", decided_at="2026-01-02T00:00:00Z"),
    )
    assert _eval(decisions=decisions).approved is True


def test_untrusted_reviewer_refused() -> None:
    outcome = _eval(decisions=(_decision(DECISION_APPROVED, reviewer_id=""),))
    assert outcome.reason == UNTRUSTED_REVIEWER


# -- decisions must be bound to the exact proposal (F1) --------------------------


def test_foreign_tenant_approved_decision_cannot_authorize() -> None:
    outcome = _eval(decisions=(_decision(DECISION_APPROVED, tenant_id="t-2"),))
    assert (outcome.approved, outcome.reason) == (False, FOREIGN_DECISION_TENANT)


def test_foreign_proposal_approved_decision_cannot_authorize() -> None:
    outcome = _eval(decisions=(_decision(DECISION_APPROVED, proposal_id="p-2"),))
    assert (outcome.approved, outcome.reason) == (False, FOREIGN_DECISION_PROPOSAL)


def test_mixed_valid_and_foreign_decisions_fail_closed() -> None:
    valid = _decision(DECISION_APPROVED, decision_id="d-1", decided_at="2026-01-01T00:00:00Z")
    foreign_tenant = _decision(
        DECISION_APPROVED, decision_id="d-2", tenant_id="t-2", decided_at="2026-01-02T00:00:00Z"
    )
    foreign_proposal = _decision(
        DECISION_APPROVED, decision_id="d-3", proposal_id="p-9", decided_at="2026-01-03T00:00:00Z"
    )
    # A foreign APPROVED cannot be "won" by a valid one, whichever is latest.
    mixed = _eval(decisions=(valid, foreign_tenant))
    assert (mixed.approved, mixed.reason) == (False, FOREIGN_DECISION_TENANT)
    mixed = _eval(decisions=(foreign_tenant, valid))
    assert mixed.approved is False
    mixed = _eval(decisions=(valid, foreign_proposal))
    assert (mixed.approved, mixed.reason) == (False, FOREIGN_DECISION_PROPOSAL)


def test_master_gate_precedes_foreign_decisions() -> None:
    # Default-deny master gate stays first, independent of decision scope.
    outcome = _eval(approval_enabled=False, decisions=(_decision(DECISION_APPROVED, tenant_id="t-2"),))
    assert (outcome.approved, outcome.reason) == (False, MAPPING_APPROVAL_NOT_ENABLED)


# -- reviewer trust is a server-verified fact, not a nonempty id (F2) ------------


def test_nonempty_reviewer_without_authorization_fact_refused() -> None:
    outcome = _eval(reviewer_authorization=None)
    assert (outcome.approved, outcome.reason) == (False, UNTRUSTED_REVIEWER)


def test_nonempty_but_untrusted_reviewer_refused() -> None:
    outcome = _eval(
        decisions=(_decision(DECISION_APPROVED, reviewer_id="u-stranger"),),
        reviewer_authorization=_authorization("u-reviewer"),
    )
    assert (outcome.approved, outcome.reason) == (False, UNTRUSTED_REVIEWER)


def test_authorized_reviewer_approves() -> None:
    outcome = _eval(
        decisions=(_decision(DECISION_APPROVED, reviewer_id="u-ok"),),
        reviewer_authorization=_authorization("u-ok"),
    )
    assert (outcome.approved, outcome.reason) == (True, APPROVED)


def test_latest_decision_deterministic_on_ties() -> None:
    a = _decision(DECISION_APPROVED, decision_id="d-a", decided_at="2026-01-01T00:00:00Z")
    b = _decision(DECISION_REJECTED, decision_id="d-b", decided_at="2026-01-01T00:00:00Z")
    assert latest_decision((a, b)) == b  # tie broken by decision_id
    assert latest_decision(()) is None


# -- happy path (English + Arabic) ---------------------------------------------


def test_approved_english_map() -> None:
    outcome = _eval()
    assert (outcome.approved, outcome.reason) == (True, APPROVED)


def test_approved_arabic_map() -> None:
    outcome = _eval(proposal=_proposal(AR_HEADERS, AR_MAP), trusted_headers=AR_HEADERS)
    assert (outcome.approved, outcome.reason) == (True, APPROVED)


# -- fingerprint helper ---------------------------------------------------------


def test_proposal_fingerprint_stable_and_sensitive() -> None:
    base = proposal_fingerprint(
        dataset_version_id="dv-1",
        doc_type="sales_register",
        header_fingerprint="a" * 64,
        field_map={"invoice_number": "Invoice Number", "net_amount": "Net Amount"},
        mapping_version="m1",
        normalization_version="n1",
        canonical_schema_version=SCHEMA_VERSION,
    )
    reordered = proposal_fingerprint(
        dataset_version_id="dv-1",
        doc_type="sales_register",
        header_fingerprint="a" * 64,
        field_map={"net_amount": "Net Amount", "invoice_number": "Invoice Number"},
        mapping_version="m1",
        normalization_version="n1",
        canonical_schema_version=SCHEMA_VERSION,
    )
    changed = proposal_fingerprint(
        dataset_version_id="dv-2",
        doc_type="sales_register",
        header_fingerprint="a" * 64,
        field_map={"invoice_number": "Invoice Number", "net_amount": "Net Amount"},
        mapping_version="m1",
        normalization_version="n1",
        canonical_schema_version=SCHEMA_VERSION,
    )
    assert base == reordered
    assert base != changed

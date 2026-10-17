"""REC-DATA-03 unit contracts: default-deny source-release policy (pure).

Every gate, precedence rule, and boundary invariant from issue #61 is pinned
here. Proof obligations of this slice:

- No supplied evidence, however clean-looking, is ever released under the
  shipped (unapproved) policy: ``RELEASE_NOT_ENABLED`` unconditionally.
- Evidence a client could construct (``transport_verified=False``) is refused.
- Non-clean / unknown verdicts, provider outages, stale evidence, integrity
  mismatches, missing/incomplete/expired/revoked authorizations all fail closed.
- The release decision concerns the raw source object hash only; it never uses
  or substitutes the normalized ``dataset_fingerprint``.

Persistence/DB evidence (append-only tables, composite-FK isolation) is
deliberately out of scope until the security decisions are approved; see
`docs/product/REC-DATA-03-boundary.md`.
"""

from dataclasses import FrozenInstanceError, fields

import pytest

from app.release import (
    AUTHORIZATION_BINDING_MISMATCH,
    DEFAULT_RELEASE_POLICY,
    INCOMPLETE_APPROVALS,
    INTAKE_NOT_QUARANTINED,
    INTEGRITY_MISMATCH,
    INVALID_AUTHORIZATION_TIME,
    INVALID_POLICY_FRESHNESS,
    INVALID_SCAN_EVIDENCE_TIME,
    INVALID_SERVER_TIME,
    MISSING_ENGINE_PROVENANCE,
    MISSING_RELEASE_AUTHORIZATION,
    MISSING_SCAN_EVIDENCE,
    NOT_EXPOSED_BY_VENDOR,
    POLICY_VERSION_MISMATCH,
    PROVIDER_OUTAGE,
    RELEASE_AUTHORIZED,
    RELEASE_EXPIRED,
    RELEASE_NOT_ENABLED,
    RELEASE_REVOKED,
    SCAN_VERDICT_NOT_CLEAN,
    SOURCE_REJECTED,
    STALE_SCAN_EVIDENCE,
    UNKNOWN_SCAN_VERDICT,
    UNSUPPORTED_FILE_TYPE,
    UNSUPPORTED_RELEASE_SCOPE,
    UNTRUSTED_RELEASE_AUTHORITY,
    UNTRUSTED_SCANNER,
    UNVERIFIED_EVIDENCE,
    ReleaseAuthorization,
    ReleasePolicy,
    ScanEvidence,
    SourceFacts,
    evaluate_release,
    source_released,
)

NOW = 1_000_000.0
SHA = "a" * 64
OTHER_SHA = "b" * 64
OBJECT_VERSION = "obj-version-1"
POLICY_VERSION = "release-policy-2026.10"


def _policy(**overrides: object) -> ReleasePolicy:
    base: dict = {
        "policy_version": POLICY_VERSION,
        "approved": True,
        "trusted_providers": frozenset({"guardduty-s3"}),
        "trusted_authorities": frozenset({"release-policy-engine"}),
        "max_evidence_age_seconds": 3600,
        "require_engine_provenance": False,
        "require_two_person": False,
        "minimum_approvals": 0,
    }
    base.update(overrides)
    return ReleasePolicy(**base)


def _source(**overrides: object) -> SourceFacts:
    base: dict = {
        "tenant_id": "t1",
        "client_id": "c1",
        "intake_id": "i1",
        "intake_status": "QUARANTINED",
        "declared_type": "csv",
        "object_sha256": SHA,
        "object_version": OBJECT_VERSION,
    }
    base.update(overrides)
    return SourceFacts(**base)


def _scan(**overrides: object) -> ScanEvidence:
    base: dict = {
        "evidence_id": "ev1",
        "provider": "guardduty-s3",
        "verdict": "NO_THREATS_FOUND",
        "object_sha256": SHA,
        "object_version": OBJECT_VERSION,
        "scanned_at": NOW - 10,
        "transport_verified": True,
        "policy_version": POLICY_VERSION,
        "engine_version": NOT_EXPOSED_BY_VENDOR,
        "signature_version": None,
        "outage": False,
    }
    base.update(overrides)
    return ScanEvidence(**base)


def _auth(**overrides: object) -> ReleaseAuthorization:
    base: dict = {
        "authorization_id": "auth1",
        "verdict_evidence_id": "ev1",
        "authority": "release-policy-engine",
        "scope": "extract",
        "issued_at": NOW - 5,
        "expires_at": NOW + 3600,
        "approvals": (),
        "revoked": False,
    }
    base.update(overrides)
    return ReleaseAuthorization(**base)


def _decide(policy: ReleasePolicy, **kwargs: object):  # type: ignore[no-untyped-def]
    kwargs.setdefault("source", _source())
    kwargs.setdefault("scan", _scan())
    kwargs.setdefault("authorization", _auth())
    kwargs.setdefault("now", NOW)
    return evaluate_release(policy=policy, **kwargs)  # type: ignore[arg-type]


# -- master default-deny --------------------------------------------------------


def test_default_policy_is_closed() -> None:
    assert DEFAULT_RELEASE_POLICY.approved is False
    assert DEFAULT_RELEASE_POLICY.trusted_providers == frozenset()
    assert DEFAULT_RELEASE_POLICY.max_evidence_age_seconds is None


def test_default_policy_denies_even_clean_verified_evidence() -> None:
    decision = evaluate_release(
        policy=DEFAULT_RELEASE_POLICY,
        source=_source(),
        scan=_scan(),
        authorization=_auth(),
        now=NOW,
    )
    assert (decision.released, decision.reason) == (False, RELEASE_NOT_ENABLED)


def test_unapproved_policy_denies_when_all_evidence_present() -> None:
    decision = _decide(_policy(approved=False))
    assert (decision.released, decision.reason) == (False, RELEASE_NOT_ENABLED)


def test_source_released_helper_is_closed_by_default() -> None:
    assert source_released(source=_source(), scan=_scan(), authorization=_auth()) is False


# -- happy path (contract can express release without any production policy) ---


def test_approved_policy_with_complete_evidence_releases() -> None:
    decision = _decide(_policy())
    assert (decision.released, decision.reason) == (True, RELEASE_AUTHORIZED)


# -- file type and intake status ------------------------------------------------


def test_unsupported_file_type_refused() -> None:
    decision = _decide(_policy(), source=_source(declared_type="pdf"))
    assert decision.reason == UNSUPPORTED_FILE_TYPE


def test_rejected_intake_never_released() -> None:
    decision = _decide(_policy(), source=_source(intake_status="REJECTED"))
    assert decision.reason == SOURCE_REJECTED


def test_non_quarantined_intake_refused() -> None:
    decision = _decide(_policy(), source=_source(intake_status="PROCESSING"))
    assert decision.reason == INTAKE_NOT_QUARANTINED


def test_rejected_intake_outranks_missing_evidence() -> None:
    decision = _decide(_policy(), source=_source(intake_status="REJECTED"), scan=None, authorization=None)
    assert decision.reason == SOURCE_REJECTED


# -- scan evidence presence and trust boundary ----------------------------------


def test_missing_scan_evidence_refused() -> None:
    decision = _decide(_policy(), scan=None)
    assert decision.reason == MISSING_SCAN_EVIDENCE


def test_client_constructible_evidence_is_refused() -> None:
    # transport_verified defaults to False: exactly what a client payload could set.
    assert ScanEvidence.__dataclass_fields__["transport_verified"].default is False
    decision = _decide(_policy(), scan=_scan(transport_verified=False))
    assert decision.reason == UNVERIFIED_EVIDENCE


def test_untrusted_provider_refused() -> None:
    decision = _decide(_policy(), scan=_scan(provider="unknown-scanner"))
    assert decision.reason == UNTRUSTED_SCANNER


def test_provider_outage_never_releases() -> None:
    decision = _decide(_policy(), scan=_scan(outage=True))
    assert decision.reason == PROVIDER_OUTAGE


def test_unknown_verdict_refused() -> None:
    decision = _decide(_policy(), scan=_scan(verdict="SOMETHING_NEW"))
    assert decision.reason == UNKNOWN_SCAN_VERDICT


@pytest.mark.parametrize(
    "verdict",
    ["THREATS_FOUND", "UNSUPPORTED", "ACCESS_DENIED", "FAILED", "TIMEOUT"],
)
def test_non_clean_verdicts_never_release(verdict: str) -> None:
    decision = _decide(_policy(), scan=_scan(verdict=verdict))
    assert (decision.released, decision.reason) == (False, SCAN_VERDICT_NOT_CLEAN)


# -- freshness ------------------------------------------------------------------


def test_stale_evidence_refused() -> None:
    decision = _decide(_policy(), scan=_scan(scanned_at=NOW - 7200))
    assert decision.reason == STALE_SCAN_EVIDENCE


def test_future_dated_evidence_refused() -> None:
    decision = _decide(_policy(), scan=_scan(scanned_at=NOW + 60))
    assert decision.reason == STALE_SCAN_EVIDENCE


def test_no_freshness_window_means_nothing_is_fresh() -> None:
    decision = _decide(_policy(max_evidence_age_seconds=None))
    assert decision.reason == STALE_SCAN_EVIDENCE


# -- integrity binding (swapped object / raw hash) ------------------------------


def test_object_sha_mismatch_refused() -> None:
    decision = _decide(_policy(), scan=_scan(object_sha256=OTHER_SHA))
    assert decision.reason == INTEGRITY_MISMATCH


def test_swapped_object_version_refused() -> None:
    decision = _decide(_policy(), scan=_scan(object_version="obj-version-2"))
    assert decision.reason == INTEGRITY_MISMATCH


def test_missing_stored_object_version_refused() -> None:
    decision = _decide(_policy(), source=_source(object_version=None), scan=_scan(object_version=None))
    assert decision.reason == INTEGRITY_MISMATCH


def test_engine_provenance_required_but_missing() -> None:
    decision = _decide(_policy(require_engine_provenance=True), scan=_scan(engine_version=None))
    assert decision.reason == MISSING_ENGINE_PROVENANCE


def test_policy_version_mismatch_refused() -> None:
    decision = _decide(_policy(), scan=_scan(policy_version="old-policy"))
    assert decision.reason == POLICY_VERSION_MISMATCH


# -- authorization --------------------------------------------------------------


def test_missing_authorization_refused() -> None:
    decision = _decide(_policy(), authorization=None)
    assert decision.reason == MISSING_RELEASE_AUTHORIZATION


def test_authorization_binding_mismatch_refused() -> None:
    decision = _decide(_policy(), authorization=_auth(verdict_evidence_id="ev-other"))
    assert decision.reason == AUTHORIZATION_BINDING_MISMATCH


def test_untrusted_authority_refused() -> None:
    decision = _decide(_policy(), authorization=_auth(authority="random-user"))
    assert decision.reason == UNTRUSTED_RELEASE_AUTHORITY


def test_unsupported_release_scope_refused() -> None:
    decision = _decide(_policy(), authorization=_auth(scope="download"))
    assert decision.reason == UNSUPPORTED_RELEASE_SCOPE


def test_revoked_authorization_refused() -> None:
    decision = _decide(_policy(), authorization=_auth(revoked=True))
    assert decision.reason == RELEASE_REVOKED


def test_two_person_required_incomplete_refused() -> None:
    decision = _decide(_policy(require_two_person=True), authorization=_auth(approvals=("u1",)))
    assert decision.reason == INCOMPLETE_APPROVALS


def test_two_person_satisfied_with_two_distinct_approvals() -> None:
    decision = _decide(_policy(require_two_person=True), authorization=_auth(approvals=("u1", "u2")))
    assert decision.released is True


def test_expired_authorization_refused() -> None:
    decision = _decide(_policy(), authorization=_auth(expires_at=NOW - 1))
    assert decision.reason == RELEASE_EXPIRED


# -- determinism and hash separation -------------------------------------------


def test_evaluation_is_deterministic_and_idempotent() -> None:
    first = _decide(_policy())
    second = _decide(_policy())
    assert first == second == (first.__class__(True, RELEASE_AUTHORIZED))


def test_decision_is_frozen() -> None:
    decision = _decide(_policy())
    with pytest.raises(FrozenInstanceError):
        decision.released = False  # type: ignore[misc]


def test_release_never_touches_dataset_fingerprint() -> None:
    # The release boundary binds raw source bytes only; the normalized dataset
    # fingerprint is a separate identity (REC-DATA-01/02) and must not appear here.
    names = {f.name for f in fields(ScanEvidence)} | {f.name for f in fields(SourceFacts)}
    assert "dataset_fingerprint" not in names
    assert "object_sha256" in names


# -- F1: non-finite / malformed time values must fail closed --------------------

_NON_FINITE = [float("nan"), float("inf"), float("-inf"), True, False, "1000", None]
# None is excluded for expiry: an open-ended authorization is a documented
# pending policy decision (F3), not a malformed timestamp.
_NON_FINITE_EXCLUDING_NONE = [float("nan"), float("inf"), float("-inf"), True, False, "1000"]


def test_default_policy_master_deny_holds_for_nan_server_time() -> None:
    # The unconditional default-deny gate outranks any time validation.
    decision = evaluate_release(
        policy=DEFAULT_RELEASE_POLICY,
        source=_source(),
        scan=_scan(scanned_at=float("nan")),
        authorization=_auth(expires_at=float("nan")),
        now=float("nan"),
    )
    assert (decision.released, decision.reason) == (False, RELEASE_NOT_ENABLED)


def test_nan_time_bypass_is_closed() -> None:
    # The three original F1 exploit vectors: each previously reached
    # RELEASE_AUTHORIZED under an approved policy.
    assert _decide(_policy(), now=float("nan")).reason == INVALID_SERVER_TIME
    assert _decide(_policy(), scan=_scan(scanned_at=float("nan"))).reason == INVALID_SCAN_EVIDENCE_TIME
    assert (
        _decide(_policy(), authorization=_auth(expires_at=float("nan"))).reason == INVALID_AUTHORIZATION_TIME
    )


@pytest.mark.parametrize("value", _NON_FINITE)
def test_invalid_server_time_refused(value: object) -> None:
    decision = _decide(_policy(), now=value)
    assert (decision.released, decision.reason) == (False, INVALID_SERVER_TIME)


@pytest.mark.parametrize("value", _NON_FINITE)
def test_invalid_scan_timestamp_refused(value: object) -> None:
    decision = _decide(_policy(), scan=_scan(scanned_at=value))
    assert (decision.released, decision.reason) == (False, INVALID_SCAN_EVIDENCE_TIME)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf"), True, False, "60", 60.0, -1, -3600],
)
def test_invalid_policy_freshness_refused(value: object) -> None:
    decision = _decide(_policy(max_evidence_age_seconds=value))
    assert (decision.released, decision.reason) == (False, INVALID_POLICY_FRESHNESS)


@pytest.mark.parametrize("value", _NON_FINITE)
def test_invalid_authorization_issued_at_refused(value: object) -> None:
    decision = _decide(_policy(), authorization=_auth(issued_at=value))
    assert (decision.released, decision.reason) == (False, INVALID_AUTHORIZATION_TIME)


@pytest.mark.parametrize("value", _NON_FINITE_EXCLUDING_NONE)
def test_invalid_authorization_expiry_refused(value: object) -> None:
    decision = _decide(_policy(), authorization=_auth(expires_at=value))
    assert (decision.released, decision.reason) == (False, INVALID_AUTHORIZATION_TIME)


def test_inverted_expiry_window_refused() -> None:
    decision = _decide(_policy(), authorization=_auth(issued_at=NOW, expires_at=NOW - 1))
    assert (decision.released, decision.reason) == (False, INVALID_AUTHORIZATION_TIME)


# -- F1 positive controls: genuine finite values still release ------------------


def test_finite_boundary_age_still_releases() -> None:
    # age exactly equal to the approved window is fresh (only > is stale).
    decision = _decide(_policy(max_evidence_age_seconds=3600), scan=_scan(scanned_at=NOW - 3600))
    assert (decision.released, decision.reason) == (True, RELEASE_AUTHORIZED)


def test_integer_timestamps_are_accepted() -> None:
    decision = _decide(
        _policy(),
        source=_source(),
        scan=_scan(scanned_at=900),
        authorization=_auth(issued_at=910, expires_at=2000),
        now=1000,
    )
    assert (decision.released, decision.reason) == (True, RELEASE_AUTHORIZED)


def test_expiry_exactly_at_now_is_refused() -> None:
    decision = _decide(_policy(), authorization=_auth(expires_at=NOW))
    assert (decision.released, decision.reason) == (False, RELEASE_EXPIRED)

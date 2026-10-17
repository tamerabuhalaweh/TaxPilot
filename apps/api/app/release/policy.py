"""REC-DATA-03 source-release policy (pure, default-deny).

This module is the **evidence and policy boundary** between quarantined
`document_intakes` and immutable `dataset_versions`. It is a pure contract: no
database, HTTP, filesystem, network, scanner SDK, or financial contents.

Design invariants (issue #61; `docs/architecture/EP04C_SECURITY_ARCHITECTURE.md`
§4/§4.1; SRS FR-FILE-007/010):

- **Default-deny.** The default policy is fully closed and *master*-denied:
  ``ReleasePolicy.approved`` is ``False``, so :func:`evaluate_release` returns
  ``RELEASE_NOT_ENABLED`` unconditionally, no matter how clean the supplied
  evidence looks. Nothing here can set a quarantined file RELEASED.
- **Provider-aware, never fabricated.** Scanner evidence carries a provider
  identity, the verbatim verdict, the exact object version, and the whole-object
  SHA-256 binding. Engine/signature version is recorded only when the provider
  supplies it (otherwise the literal ``not exposed by vendor``); it is never
  invented, and never substituted for freshness.
- **Trusted boundary only.** Evidence/authorization objects are constructed only
  by a future trusted scanner boundary (SigV4/queue/control-plane verified).
  Client-submitted verdicts cannot pass: an unverified evidence object is
  refused, and a client request body can never set the trusted transport flag.
- **Two distinct hashes.** Release concerns the *raw source bytes*
  (``object_sha256``) only. It never computes or stands in for the normalized
  ``dataset_fingerprint`` (REC-DATA-01/02).
- **No inference.** Release is never inferred from raw intake status, a
  user-provided hash, the mere existence of a registry row, or a self-reported
  object tag. ``UNSUPPORTED``/``ACCESS_DENIED``/``FAILED``/``TIMEOUT``/unknown
  verdicts and provider outages never mean clean.
- **Time is finite or refused.** Freshness and expiry compare against genuine
  finite numeric timestamps only. NaN, ±infinity, booleans, strings and inverted
  expiry windows fail closed with typed reasons instead of slipping past a
  comparison (``nan < 0``/``nan > x``/``nan >= x`` are all false).

The implementation that persists evidence and drives this policy is deliberately
**not** in this slice: DEC-S1 (object store), DEC-S2 (scanner + verdict trust),
DEC-02 (retention), DEC-03 (region/transfer) and DEC-R1 (pre-prod security) are
all BLOCKED. See `docs/product/REC-DATA-03-boundary.md`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# --- scanner verdicts (verbatim provider values; never reinterpreted) ----------
VERDICT_NO_THREATS_FOUND = "NO_THREATS_FOUND"
VERDICT_THREATS_FOUND = "THREATS_FOUND"
VERDICT_UNSUPPORTED = "UNSUPPORTED"
VERDICT_ACCESS_DENIED = "ACCESS_DENIED"
VERDICT_FAILED = "FAILED"
VERDICT_TIMEOUT = "TIMEOUT"
VERDICT_UNKNOWN = "UNKNOWN"

KNOWN_VERDICTS = frozenset(
    {
        VERDICT_NO_THREATS_FOUND,
        VERDICT_THREATS_FOUND,
        VERDICT_UNSUPPORTED,
        VERDICT_ACCESS_DENIED,
        VERDICT_FAILED,
        VERDICT_TIMEOUT,
        VERDICT_UNKNOWN,
    }
)
CLEAN_VERDICTS = frozenset({VERDICT_NO_THREATS_FOUND})

#: Recorded when a managed scanner does not expose an engine/signature version.
#: Never fabricated, and never treated as a valid freshness/provenance signal.
NOT_EXPOSED_BY_VENDOR = "not exposed by vendor"

# --- release refusal reasons (typed; first failure wins) -----------------------
RELEASE_NOT_ENABLED = "RELEASE_NOT_ENABLED"
UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
SOURCE_REJECTED = "SOURCE_REJECTED"
INTAKE_NOT_QUARANTINED = "INTAKE_NOT_QUARANTINED"
MISSING_SCAN_EVIDENCE = "MISSING_SCAN_EVIDENCE"
UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"
UNTRUSTED_SCANNER = "UNTRUSTED_SCANNER"
PROVIDER_OUTAGE = "PROVIDER_OUTAGE"
UNKNOWN_SCAN_VERDICT = "UNKNOWN_SCAN_VERDICT"
SCAN_VERDICT_NOT_CLEAN = "SCAN_VERDICT_NOT_CLEAN"
STALE_SCAN_EVIDENCE = "STALE_SCAN_EVIDENCE"
INVALID_SERVER_TIME = "INVALID_SERVER_TIME"
INVALID_POLICY_FRESHNESS = "INVALID_POLICY_FRESHNESS"
INVALID_SCAN_EVIDENCE_TIME = "INVALID_SCAN_EVIDENCE_TIME"
INTEGRITY_MISMATCH = "INTEGRITY_MISMATCH"
MISSING_ENGINE_PROVENANCE = "MISSING_ENGINE_PROVENANCE"
POLICY_VERSION_MISMATCH = "POLICY_VERSION_MISMATCH"
MISSING_RELEASE_AUTHORIZATION = "MISSING_RELEASE_AUTHORIZATION"
AUTHORIZATION_BINDING_MISMATCH = "AUTHORIZATION_BINDING_MISMATCH"
UNTRUSTED_RELEASE_AUTHORITY = "UNTRUSTED_RELEASE_AUTHORITY"
UNSUPPORTED_RELEASE_SCOPE = "UNSUPPORTED_RELEASE_SCOPE"
RELEASE_REVOKED = "RELEASE_REVOKED"
INCOMPLETE_APPROVALS = "INCOMPLETE_APPROVALS"
INVALID_AUTHORIZATION_TIME = "INVALID_AUTHORIZATION_TIME"
RELEASE_EXPIRED = "RELEASE_EXPIRED"
RELEASE_AUTHORIZED = "RELEASE_AUTHORIZED"

# Evaluation precedence (documented; first failure wins).
PRECEDENCE = (
    RELEASE_NOT_ENABLED,
    UNSUPPORTED_FILE_TYPE,
    SOURCE_REJECTED,
    INTAKE_NOT_QUARANTINED,
    MISSING_SCAN_EVIDENCE,
    UNVERIFIED_EVIDENCE,
    UNTRUSTED_SCANNER,
    PROVIDER_OUTAGE,
    UNKNOWN_SCAN_VERDICT,
    SCAN_VERDICT_NOT_CLEAN,
    INVALID_SERVER_TIME,
    INVALID_POLICY_FRESHNESS,
    INVALID_SCAN_EVIDENCE_TIME,
    STALE_SCAN_EVIDENCE,
    INTEGRITY_MISMATCH,
    MISSING_ENGINE_PROVENANCE,
    POLICY_VERSION_MISMATCH,
    MISSING_RELEASE_AUTHORIZATION,
    AUTHORIZATION_BINDING_MISMATCH,
    UNTRUSTED_RELEASE_AUTHORITY,
    UNSUPPORTED_RELEASE_SCOPE,
    RELEASE_REVOKED,
    INCOMPLETE_APPROVALS,
    INVALID_AUTHORIZATION_TIME,
    RELEASE_EXPIRED,
)

SUPPORTED_FILE_TYPES = ("csv", "xlsx")
EXPECTED_INTAKE_STATUS = "QUARANTINED"
SUPPORTED_RELEASE_SCOPES = ("extract",)
REJECTED_STATUS = "REJECTED"


def _is_finite_number(value: object) -> bool:
    """True only for a genuine finite ``int``/``float``.

    Rejects ``bool`` (an ``int`` subclass), NaN, ±infinity, strings/None, and
    integers too large to represent as a float — all of which would otherwise
    slip past ``<``/``>``/``>=`` comparisons.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _is_valid_max_age(value: object) -> bool:
    """True only for a nonnegative finite ``int`` (rejects bool/float/None/NaN)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return value >= 0


@dataclass(frozen=True)
class SourceFacts:
    """Server-read facts about one quarantined intake (never caller-supplied).

    ``object_sha256`` is the trusted whole-object hash of the stored bytes;
    ``object_version`` is the provider object version bound at upload (or None
    under the local dev/test adapter, which has no object versioning).
    """

    tenant_id: str
    client_id: str
    intake_id: str
    intake_status: str
    declared_type: str
    object_sha256: str
    object_version: str | None = None


@dataclass(frozen=True)
class ScanEvidence:
    """Provider-aware scan evidence. Constructed ONLY by the trusted boundary.

    ``transport_verified`` is set True exclusively by the future trusted scanner
    boundary after SigV4/queue/control-plane verification (EP-04C §4.1). The
    default (what a client could ever construct) is ``False``, which is refused.
    """

    evidence_id: str
    provider: str
    verdict: str
    object_sha256: str
    object_version: str | None
    scanned_at: float
    transport_verified: bool = False
    policy_version: str | None = None
    engine_version: str | None = None
    signature_version: str | None = None
    outage: bool = False


@dataclass(frozen=True)
class ReleaseAuthorization:
    """A versioned release decision that binds one exact verdict evidence row."""

    authorization_id: str
    verdict_evidence_id: str
    authority: str
    scope: str
    issued_at: float
    expires_at: float | None
    approvals: tuple[str, ...] = ()
    revoked: bool = False


@dataclass(frozen=True)
class ReleasePolicy:
    """Approved release policy. The default is fully closed (master default-deny).

    ``approved=False`` (with an empty sentinel version, no trusted providers,
    no trusted authorities, and no freshness trust) means every evaluation
    returns ``RELEASE_NOT_ENABLED``. A policy can only become usable once
    DEC-S1/DEC-S2/DEC-03/DEC-R1 are approved and this object is populated by an
    approved configuration surface — none of which exists yet.
    """

    policy_version: str = "unapproved-none"
    approved: bool = False
    trusted_providers: frozenset[str] = frozenset()
    trusted_authorities: frozenset[str] = frozenset()
    max_evidence_age_seconds: int | None = None  # None -> no evidence is fresh
    require_engine_provenance: bool = False
    require_two_person: bool = False
    minimum_approvals: int = 0


#: The closed policy used everywhere until security decisions are approved.
DEFAULT_RELEASE_POLICY = ReleasePolicy()


@dataclass(frozen=True)
class ReleaseDecision:
    """Outcome of :func:`evaluate_release` (``released`` iff RELEASE_AUTHORIZED)."""

    released: bool
    reason: str


def evaluate_release(
    *,
    policy: ReleasePolicy,
    source: SourceFacts,
    scan: ScanEvidence | None,
    authorization: ReleaseAuthorization | None,
    now: float,
) -> ReleaseDecision:
    """Default-deny evaluation of one source-release request (pure).

    Returns the first unmet gate in :data:`PRECEDENCE`. The only path to
    ``released=True`` is a fully approved policy plus verified, clean, fresh,
    integrity-bound evidence and a live, unrevoked, sufficiently-approved
    authorization binding that exact verdict.
    """
    # 0. Master default-deny: an unapproved policy releases nothing, ever.
    if not policy.approved:
        return ReleaseDecision(False, RELEASE_NOT_ENABLED)
    # 1. Only supported source formats are eligible.
    if source.declared_type not in SUPPORTED_FILE_TYPES:
        return ReleaseDecision(False, UNSUPPORTED_FILE_TYPE)
    # 2. A rejected intake is terminal and never released.
    if source.intake_status == REJECTED_STATUS:
        return ReleaseDecision(False, SOURCE_REJECTED)
    # 3. Only a still-quarantined intake can be released.
    if source.intake_status != EXPECTED_INTAKE_STATUS:
        return ReleaseDecision(False, INTAKE_NOT_QUARANTINED)
    # 4. Scan evidence is mandatory; no evidence is never release.
    if scan is None:
        return ReleaseDecision(False, MISSING_SCAN_EVIDENCE)
    # 5. Evidence must have arrived through the trusted boundary.
    if not scan.transport_verified:
        return ReleaseDecision(False, UNVERIFIED_EVIDENCE)
    # 6. The provider must be explicitly trusted.
    if scan.provider not in policy.trusted_providers:
        return ReleaseDecision(False, UNTRUSTED_SCANNER)
    # 7. Provider outage never releases.
    if scan.outage:
        return ReleaseDecision(False, PROVIDER_OUTAGE)
    # 8. Unknown verdicts are refused (never inferred clean).
    if scan.verdict not in KNOWN_VERDICTS:
        return ReleaseDecision(False, UNKNOWN_SCAN_VERDICT)
    # 9. Only an explicit clean verdict releases.
    if scan.verdict not in CLEAN_VERDICTS:
        return ReleaseDecision(False, SCAN_VERDICT_NOT_CLEAN)
    # 10. Freshness. Server time, the scan timestamp, and the policy's freshness
    #     window must all be genuine finite numbers: a non-finite or malformed
    #     value (NaN/±inf/bool/string) fails closed instead of slipping past the
    #     comparison. ``None`` max-age means no evidence is fresh (default-closed).
    if not _is_finite_number(now):
        return ReleaseDecision(False, INVALID_SERVER_TIME)
    if not _is_finite_number(scan.scanned_at):
        return ReleaseDecision(False, INVALID_SCAN_EVIDENCE_TIME)
    if policy.max_evidence_age_seconds is None:
        return ReleaseDecision(False, STALE_SCAN_EVIDENCE)
    if not _is_valid_max_age(policy.max_evidence_age_seconds):
        return ReleaseDecision(False, INVALID_POLICY_FRESHNESS)
    age = now - scan.scanned_at
    if age < 0 or age > policy.max_evidence_age_seconds:
        return ReleaseDecision(False, STALE_SCAN_EVIDENCE)
    # 11. Integrity: the scanned object must be the exact stored bytes/version.
    if scan.object_sha256 != source.object_sha256:
        return ReleaseDecision(False, INTEGRITY_MISMATCH)
    if scan.object_version is None or scan.object_version != source.object_version:
        return ReleaseDecision(False, INTEGRITY_MISMATCH)
    # 12. Engine/signature provenance only if policy demands it.
    if policy.require_engine_provenance and not scan.engine_version:
        return ReleaseDecision(False, MISSING_ENGINE_PROVENANCE)
    # 13. Evidence must have been produced under the current policy version.
    if scan.policy_version != policy.policy_version:
        return ReleaseDecision(False, POLICY_VERSION_MISMATCH)
    # 14. A release authorization is mandatory.
    if authorization is None:
        return ReleaseDecision(False, MISSING_RELEASE_AUTHORIZATION)
    # 15. The authorization must bind this exact verdict evidence.
    if authorization.verdict_evidence_id != scan.evidence_id:
        return ReleaseDecision(False, AUTHORIZATION_BINDING_MISMATCH)
    # 16. The authorizing authority must be trusted.
    if authorization.authority not in policy.trusted_authorities:
        return ReleaseDecision(False, UNTRUSTED_RELEASE_AUTHORITY)
    # 17. Only supported scopes are released (extract-only).
    if authorization.scope not in SUPPORTED_RELEASE_SCOPES:
        return ReleaseDecision(False, UNSUPPORTED_RELEASE_SCOPE)
    # 18. Revoked authorizations never release.
    if authorization.revoked:
        return ReleaseDecision(False, RELEASE_REVOKED)
    # 19. Separation-of-duties approvals when policy requires them.
    if policy.require_two_person:
        required = max(2, policy.minimum_approvals)
        if len(set(authorization.approvals)) < required:
            return ReleaseDecision(False, INCOMPLETE_APPROVALS)
    # 20. Authorization chronology must be genuine finite server time; malformed
    #     timestamps or an inverted window (expiry before issue) fail closed. A
    #     finite release TTL is a pending production-policy decision (F3); it is
    #     documented, not silently adopted here.
    if not _is_finite_number(authorization.issued_at):
        return ReleaseDecision(False, INVALID_AUTHORIZATION_TIME)
    if authorization.expires_at is not None:
        if not _is_finite_number(authorization.expires_at):
            return ReleaseDecision(False, INVALID_AUTHORIZATION_TIME)
        if authorization.expires_at < authorization.issued_at:
            return ReleaseDecision(False, INVALID_AUTHORIZATION_TIME)
        # 21. Expiry is enforced against server time.
        if now >= authorization.expires_at:
            return ReleaseDecision(False, RELEASE_EXPIRED)
    return ReleaseDecision(True, RELEASE_AUTHORIZED)


def source_released(
    *,
    policy: ReleasePolicy = DEFAULT_RELEASE_POLICY,
    source: SourceFacts,
    scan: ScanEvidence | None = None,
    authorization: ReleaseAuthorization | None = None,
    now: float = 0.0,
) -> bool:
    """Boolean convenience for future wiring (registration/eligibility gates).

    With the default (closed) policy this is always False, so callers that adopt
    it inherit default-deny without a release path existing.
    """
    return evaluate_release(
        policy=policy, source=source, scan=scan, authorization=authorization, now=now
    ).released

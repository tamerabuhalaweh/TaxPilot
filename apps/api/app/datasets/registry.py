"""REC-DATA-01 dataset-version registry contracts (pure, immutable).

A dataset version is the client-scoped, durable identity of one source document
intake normalized for a declared document type. This module owns the *identity*
and the *registration precondition* only: no database, HTTP, file, network, or
financial contents.

Registration is NOT approval and NOT release. Two hashes stay strictly distinct
and are never substituted:

- ``source_content_sha256`` — trusted hash of the raw upload, taken from the
  immutable ``document_intakes`` record.
- ``dataset_fingerprint`` — normalized content identity computed only later,
  after authorized reading + validation + approved mapping. It is ``None``
  until then, and an absent fingerprint blocks any derived eligibility (the raw
  source hash is never a substitute for the normalized identity).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

SALES_REGISTER = "sales_register"
GENERAL_LEDGER = "general_ledger"
JOFOTARA_EXPORT = "jofotara_export"
KNOWN_DOCUMENT_TYPES = (SALES_REGISTER, GENERAL_LEDGER, JOFOTARA_EXPORT)

KNOWN_FORMATS = ("csv", "xlsx")

# Registration refusal reasons (default-deny; first failure wins).
UNSUPPORTED_DOCUMENT_TYPE = "UNSUPPORTED_DOCUMENT_TYPE"
UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
SOURCE_NOT_RELEASED = "SOURCE_NOT_RELEASED"

# Derived eligibility reasons (distinct-hash rule; never a compliance claim).
ELIGIBLE = "ELIGIBLE"
MISSING_DATASET_FINGERPRINT = "MISSING_DATASET_FINGERPRINT"
UNAPPROVED_MAPPING = "UNAPPROVED_MAPPING"


@dataclass(frozen=True)
class RegistrationDecision:
    """Outcome of the registration precondition (``reason`` == "" iff allowed)."""

    allowed: bool
    reason: str


def evaluate_registration(
    *,
    doc_type: str,
    declared_format: str,
    source_status: str,
    source_released: bool = False,
) -> RegistrationDecision:
    """Default-deny precondition for registering a dataset version.

    Order (first failure wins): supported document type, supported declared
    format, then trusted source release. ``source_released`` must come from
    persisted release evidence (REC-DATA-03); until that exists it stays
    ``False``, so real registration refuses with ``SOURCE_NOT_RELEASED``. A
    ``REJECTED`` intake is never released either.
    """
    if doc_type not in KNOWN_DOCUMENT_TYPES:
        return RegistrationDecision(False, UNSUPPORTED_DOCUMENT_TYPE)
    if declared_format not in KNOWN_FORMATS:
        return RegistrationDecision(False, UNSUPPORTED_FORMAT)
    if not source_released or source_status == "REJECTED":
        return RegistrationDecision(False, SOURCE_NOT_RELEASED)
    return RegistrationDecision(True, "")


def registration_identity(
    *,
    tenant_id: str,
    client_id: str,
    source_intake_id: str,
    doc_type: str,
    declared_format: str,
    source_content_sha256: str,
    parser_version: str | None = None,
    normalization_version: str | None = None,
    mapping_revision: str | None = None,
    dataset_fingerprint: str | None = None,
) -> str:
    """Stable sha256 identity of one registration intent (idempotency anchor).

    The same identity converges on the existing row; a different identity for
    the same (source intake, document type) is a hard conflict, never an
    overwrite.
    """
    payload = {
        "tenant": tenant_id,
        "client": client_id,
        "source": source_intake_id,
        "doc_type": doc_type,
        "format": declared_format,
        "source_sha256": source_content_sha256,
        "parser": parser_version,
        "normalization": normalization_version,
        "mapping_revision": mapping_revision,
        "dataset_fingerprint": dataset_fingerprint,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EligibilityOutcome:
    """Derived eligibility of a registered version (never a compliance claim)."""

    eligible: bool
    reason: str


def derive_eligibility(
    *,
    dataset_fingerprint: str | None,
    mapping_approved: bool,
    source_released: bool,
) -> EligibilityOutcome:
    """Derive whether a registered version may feed a run (first failure wins).

    An absent ``dataset_fingerprint`` always blocks: registration alone is not
    an eligibility certificate, and the raw source hash is never substituted
    for the validated normalized identity.
    """
    if not dataset_fingerprint:
        return EligibilityOutcome(False, MISSING_DATASET_FINGERPRINT)
    if not mapping_approved:
        return EligibilityOutcome(False, UNAPPROVED_MAPPING)
    if not source_released:
        return EligibilityOutcome(False, SOURCE_NOT_RELEASED)
    return EligibilityOutcome(True, ELIGIBLE)

"""REC-DATA-01 client-scoped dataset-version registry (identity contracts).

Registration is not approval and not release: the authenticated write path is
default-deny until trusted source-release evidence exists (REC-DATA-03), while
read routes expose immutable registration metadata only.
"""

from app.datasets.registry import (
    ELIGIBLE,
    GENERAL_LEDGER,
    JOFOTARA_EXPORT,
    KNOWN_DOCUMENT_TYPES,
    KNOWN_FORMATS,
    MISSING_DATASET_FINGERPRINT,
    SALES_REGISTER,
    SOURCE_NOT_RELEASED,
    UNAPPROVED_MAPPING,
    UNSUPPORTED_DOCUMENT_TYPE,
    UNSUPPORTED_FORMAT,
    EligibilityOutcome,
    RegistrationDecision,
    derive_eligibility,
    evaluate_registration,
    registration_identity,
)

__all__ = [
    "ELIGIBLE",
    "GENERAL_LEDGER",
    "JOFOTARA_EXPORT",
    "KNOWN_DOCUMENT_TYPES",
    "KNOWN_FORMATS",
    "MISSING_DATASET_FINGERPRINT",
    "SALES_REGISTER",
    "SOURCE_NOT_RELEASED",
    "UNAPPROVED_MAPPING",
    "UNSUPPORTED_DOCUMENT_TYPE",
    "UNSUPPORTED_FORMAT",
    "EligibilityOutcome",
    "RegistrationDecision",
    "derive_eligibility",
    "evaluate_registration",
    "registration_identity",
]

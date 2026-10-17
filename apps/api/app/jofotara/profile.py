"""REC-JOFO-01 default-deny JoFotara import-profile contracts (pure, no I/O).

JoFotara is a **file-based-only** first-class dataset (``jofotara_export``); the
SRS forbids a government-API integration and forbids guessing any layout
(FR-JOF-001/002, EP-15). As of this slice there are **no authorized sample
exports and no documented official format** (blocker B-01 OPEN, decision DEC-10
OPEN), so nothing here is enabled: the shipped registry is empty and recognition
fails closed. This module owns only the *contract* that a genuinely approved,
evidence-grounded profile will use later.

Trust invariants:

- **No invented layout.** The default registry (:data:`DEFAULT_JOFOTARA_REGISTRY`)
  contains no profile; a future profile may only be registered with declared
  provenance (issuing source, authority, extraction date, redistribution
  permission) and an explicit approval.
- **Master default-deny.** :func:`recognize_jofotara_profile` refuses when no
  approved profile matches, distinguishing "no approved profile at all",
  unsupported worksheet, unapproved (draft) profile, header drift, ambiguous
  matches and duplicate/empty headers — each with a stable reason code.
- **Exact values only.** Money is exact :class:`~decimal.Decimal` (never float),
  identifiers stay verbatim strings (leading zeros preserved), currency is an
  explicit 3-letter code (unknown is never assumed JOD), blanks are missing
  (never zero), and formula/external-reference cells are refused.
- **Provenance retained.** Every value can carry worksheet/row/column anchors.

No database, HTTP, network, file I/O, or financial processing is performed here.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from types import MappingProxyType

from app.normalization.mapping import fingerprint_headers
from app.normalization.suggest import normalize_header

JOFOTARA_DOC_TYPE = "jofotara_export"

# Declared authority of a profile's evidence (never inferred).
AUTHORITY_OFFICIAL = "OFFICIAL"
AUTHORITY_AUTHORIZED_SAMPLE = "AUTHORIZED_SAMPLE"
KNOWN_AUTHORITY_TYPES = (AUTHORITY_OFFICIAL, AUTHORITY_AUTHORIZED_SAMPLE)

PROFILE_APPROVED = "APPROVED"
PROFILE_DRAFT = "DRAFT"
KNOWN_PROFILE_STATUSES = (PROFILE_APPROVED, PROFILE_DRAFT)

CURRENCY_REQUIRED_PER_ROW = "REQUIRED_PER_ROW"
KNOWN_CURRENCY_POLICIES = (CURRENCY_REQUIRED_PER_ROW,)

# Canonical JoFotara fields a profile may declare. Nothing about their presence
# or meaning is asserted until an approved, evidence-grounded profile says so.
KNOWN_JOFOTARA_FIELDS = (
    "invoice_number",
    "issuer",
    "issue_date",
    "currency",
    "net_amount",
    "tax_amount",
    "gross_amount",
    "credit_note_flag",
    "reference_number",
)

# Recognition / validation reasons (first failure wins).
RECOGNIZED = "RECOGNIZED"
EMPTY_HEADERS = "EMPTY_HEADERS"
DUPLICATE_HEADER = "DUPLICATE_HEADER"
NO_APPROVED_PROFILE = "NO_APPROVED_PROFILE"
UNSUPPORTED_WORKSHEET = "UNSUPPORTED_WORKSHEET"
PROFILE_NOT_APPROVED = "PROFILE_NOT_APPROVED"
HEADER_DRIFT = "HEADER_DRIFT"
AMBIGUOUS_PROFILE_MATCH = "AMBIGUOUS_PROFILE_MATCH"
MISSING_COLUMN = "MISSING_COLUMN"
MISSING_REQUIRED_COLUMN = "MISSING_REQUIRED_COLUMN"
UNKNOWN_FIELD = "UNKNOWN_FIELD"
MISSING_PROFILE_PROVENANCE = "MISSING_PROFILE_PROVENANCE"

# Value-level rejection reasons.
MISSING_VALUE = "MISSING_VALUE"
FORMULA_CELL = "FORMULA_CELL"
EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"
MALFORMED_NUMBER = "MALFORMED_NUMBER"
NON_FINITE_NUMBER = "NON_FINITE_NUMBER"
UNKNOWN_CURRENCY = "UNKNOWN_CURRENCY"
MISSING_CURRENCY = "MISSING_CURRENCY"
NOT_RECOGNIZED = "NOT_RECOGNIZED"

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_MONEY_CHARS_RE = re.compile(r"^[+-]?[0-9]*\.?[0-9]+$|^[+-]?[0-9]+\.?$")


class JoFotaraContractError(ValueError):
    """A value or profile violates the JoFotara contract. Carries a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ProfileProvenance:
    """Declared origin/authority of a profile's evidence (never inferred).

    Required for an approved profile; a profile without provenance can never be
    treated as authorized.
    """

    issuing_source: str
    authority_type: str
    extracted_at: str
    redistribution_permission: str
    reference_url: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.issuing_source.strip():
            raise ValueError("provenance.issuing_source must be non-blank")
        if self.authority_type not in KNOWN_AUTHORITY_TYPES:
            raise ValueError(f"authority_type must be one of {KNOWN_AUTHORITY_TYPES}")
        if not self.extracted_at.strip():
            raise ValueError("provenance.extracted_at must be non-blank (when the evidence was obtained)")
        if not self.redistribution_permission.strip():
            raise ValueError("provenance.redistribution_permission must be non-blank")


@dataclass(frozen=True)
class MoneySemantics:
    """Explicit numeric convention. No default: a profile must state it."""

    decimal_separator: str
    grouping_separator: str | None
    currency_policy: str = CURRENCY_REQUIRED_PER_ROW

    def __post_init__(self) -> None:
        if len(self.decimal_separator) != 1 or self.decimal_separator.isdigit():
            raise ValueError("decimal_separator must be a single non-digit character")
        if self.grouping_separator is not None:
            if len(self.grouping_separator) != 1 or self.grouping_separator.isdigit():
                raise ValueError("grouping_separator must be a single non-digit character or None")
            if self.grouping_separator == self.decimal_separator:
                raise ValueError("decimal and grouping separators must differ (ambiguous)")
        if self.currency_policy not in KNOWN_CURRENCY_POLICIES:
            raise ValueError(f"currency_policy must be one of {KNOWN_CURRENCY_POLICIES}")


@dataclass(frozen=True)
class JoFotaraProfile:
    """One immutable, versioned JoFotara import-profile manifest.

    A profile is a *claim of layout knowledge*. An ``APPROVED`` profile must
    carry declared provenance and an approver; a ``DRAFT`` profile is inert
    (recognition refuses it as ``PROFILE_NOT_APPROVED``).
    """

    profile_id: str
    profile_version: str
    worksheet_names: tuple[str, ...]
    header_fingerprint: str
    column_map: Mapping[str, str]
    required_fields: tuple[str, ...]
    money: MoneySemantics
    date_format: str
    status: str = PROFILE_DRAFT
    approved_by: str = ""
    approved_at: str = ""
    provenance: ProfileProvenance | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("date_format", self.date_format),
        ):
            if not value.strip():
                raise ValueError(f"{label} must be non-blank")
        if not self.worksheet_names or any(not w.strip() for w in self.worksheet_names):
            raise ValueError("worksheet_names must be a non-empty tuple of non-blank names")
        if self.status not in KNOWN_PROFILE_STATUSES:
            raise ValueError(f"status must be one of {KNOWN_PROFILE_STATUSES}")
        if not isinstance(self.column_map, Mapping):
            raise TypeError(f"column_map must be a mapping, got {type(self.column_map).__name__}")
        for canonical, source in self.column_map.items():
            if canonical not in KNOWN_JOFOTARA_FIELDS:
                raise ValueError(f"unknown canonical field {canonical!r} for a JoFotara profile")
            if not isinstance(source, str) or not source.strip():
                raise ValueError(f"column_map[{canonical!r}] must map to a non-blank source header")
        for required in self.required_fields:
            if required not in self.column_map:
                raise ValueError(f"required field {required!r} is not present in column_map")
        if self.status == PROFILE_APPROVED:
            if self.provenance is None:
                raise ValueError("an APPROVED profile requires declared provenance")
            if not self.approved_by.strip() or not self.approved_at.strip():
                raise ValueError("an APPROVED profile requires approved_by and approved_at")
        object.__setattr__(self, "column_map", MappingProxyType(dict(self.column_map)))

    def matches_worksheet(self, worksheet: str) -> bool:
        folded = worksheet.strip().casefold()
        return any(folded == name.strip().casefold() for name in self.worksheet_names)


@dataclass(frozen=True)
class JoFotaraProfileRegistry:
    """Immutable set of declared profiles (default is empty / no approved profile)."""

    profiles: tuple[JoFotaraProfile, ...] = ()

    def __post_init__(self) -> None:
        seen: set[tuple[str, str]] = set()
        for profile in self.profiles:
            if not isinstance(profile, JoFotaraProfile):
                raise TypeError(f"profiles must hold JoFotaraProfile, got {type(profile).__name__}")
            key = (profile.profile_id, profile.profile_version)
            if key in seen:
                raise ValueError(
                    f"duplicate profile {profile.profile_id!r} version {profile.profile_version!r}"
                )
            seen.add(key)

    def approved_profiles(self) -> tuple[JoFotaraProfile, ...]:
        return tuple(p for p in self.profiles if p.status == PROFILE_APPROVED)

    def matching_worksheet(self, worksheet: str) -> tuple[JoFotaraProfile, ...]:
        return tuple(p for p in self.profiles if p.matches_worksheet(worksheet))


#: The shipped registry is deliberately empty: no authorized samples exist (B-01).
DEFAULT_JOFOTARA_REGISTRY = JoFotaraProfileRegistry(())


@dataclass(frozen=True)
class ProfileRecognition:
    """Recognition outcome: a matched approved profile or a fail-closed reason."""

    recognized: bool
    reason: str
    profile: JoFotaraProfile | None = None
    details: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProfileIssue:
    """One profile-validation diagnostic (all are blocking)."""

    code: str
    message: str


@dataclass(frozen=True)
class ProfileValidation:
    """Result of validating declared columns against extracted headers."""

    ok: bool
    column_index: dict[str, int]
    issues: tuple[ProfileIssue, ...] = field(default_factory=tuple)
    header_fingerprint: str = ""


def _has_formula(raw: str) -> bool:
    return raw.lstrip().startswith("=")


def _has_external_reference(raw: str) -> bool:
    return "[" in raw or "]" in raw


def normalize_identifier(raw: object) -> str:
    """Return a verbatim identifier string (leading zeros preserved).

    Never coerces to a number; blanks and formula/external-reference cells are
    refused. Case and internal characters are otherwise significant.
    """
    if not isinstance(raw, str):
        raise TypeError(f"identifier must be text, got {type(raw).__name__}")
    text = raw.strip()
    if not text:
        raise JoFotaraContractError(MISSING_VALUE, "identifier is blank (missing, never empty)")
    if _has_formula(raw):
        raise JoFotaraContractError(FORMULA_CELL, "formula cells are not accepted as identifiers")
    if _has_external_reference(raw):
        raise JoFotaraContractError(EXTERNAL_REFERENCE, "external workbook references are not accepted")
    return text


def normalize_currency(raw: object) -> str:
    """Return an explicit upper-case 3-letter currency code; never assume JOD."""
    if not isinstance(raw, str):
        raise TypeError(f"currency must be text, got {type(raw).__name__}")
    text = raw.strip().upper()
    if not text:
        raise JoFotaraContractError(MISSING_CURRENCY, "currency is blank; it is never assumed (e.g. JOD)")
    if not _CURRENCY_RE.match(text):
        raise JoFotaraContractError(UNKNOWN_CURRENCY, f"unsupported currency {raw!r} (need 3 letters)")
    return text


def parse_money(raw: object, money: MoneySemantics) -> Decimal:
    """Parse an exact :class:`~decimal.Decimal` under an explicit convention.

    Rejects non-text input (no float path), blanks (missing, never zero),
    formula/external-reference cells, thousands/decimal ambiguity, malformed
    text, and non-finite values. The original ledger text is never mutated.
    """
    if not isinstance(raw, str):
        raise TypeError(f"money must be text, got {type(raw).__name__} (no float/int path)")
    if not isinstance(money, MoneySemantics):
        raise TypeError(f"money must be MoneySemantics, got {type(money).__name__}")
    text = raw.strip()
    if not text:
        raise JoFotaraContractError(MISSING_VALUE, "amount is blank (missing, never zero)")
    if _has_formula(raw):
        raise JoFotaraContractError(FORMULA_CELL, "formula cells are not accepted as amounts")
    if _has_external_reference(raw):
        raise JoFotaraContractError(EXTERNAL_REFERENCE, "external workbook references are not accepted")
    cleaned = text.replace(" ", "")
    if money.grouping_separator:
        cleaned = cleaned.replace(money.grouping_separator, "")
    cleaned = cleaned.replace(money.decimal_separator, ".")
    if not _MONEY_CHARS_RE.match(cleaned):
        raise JoFotaraContractError(MALFORMED_NUMBER, f"unrecognized numeric value {raw!r}")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise JoFotaraContractError(MALFORMED_NUMBER, f"unrecognized numeric value {raw!r}") from None
    if value.is_nan() or value.is_infinite():
        raise JoFotaraContractError(NON_FINITE_NUMBER, "non-finite amount rejected")
    return value


def validate_jofotara_profile(profile: JoFotaraProfile, headers: tuple[str, ...]) -> ProfileValidation:
    """Strictly validate a profile's declared columns against extracted headers.

    Fails closed on duplicate/empty headers, header drift from the profile's
    recorded fingerprint, unknown canonical fields, missing declared columns,
    missing required fields, and an approved profile without provenance.
    """
    if not isinstance(profile, JoFotaraProfile):
        raise TypeError(f"profile must be JoFotaraProfile, got {type(profile).__name__}")
    if not isinstance(headers, tuple) or any(not isinstance(h, str) for h in headers):
        raise TypeError("headers must be a tuple of str")
    fingerprint = fingerprint_headers(headers)
    issues: list[ProfileIssue] = []
    if not headers:
        return ProfileValidation(False, {}, (ProfileIssue(EMPTY_HEADERS, "worksheet has no header row"),), "")
    if profile.status == PROFILE_APPROVED and profile.provenance is None:
        issues.append(ProfileIssue(MISSING_PROFILE_PROVENANCE, "approved profile has no declared provenance"))

    seen: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalize_header(header)
        if key in seen:
            issues.append(
                ProfileIssue(
                    DUPLICATE_HEADER,
                    f"duplicate column {header!r} at positions {seen[key]} and {index}",
                )
            )
        else:
            seen[key] = index
    if fingerprint != profile.header_fingerprint:
        issues.append(
            ProfileIssue(
                HEADER_DRIFT,
                "headers do not match the profile fingerprint (altered or drifted layout)",
            )
        )

    index_by_header = {normalize_header(h): i for i, h in enumerate(headers)}
    column_index: dict[str, int] = {}
    for canonical, source in profile.column_map.items():
        if canonical not in KNOWN_JOFOTARA_FIELDS:
            issues.append(ProfileIssue(UNKNOWN_FIELD, f"{canonical!r} is not a known JoFotara field"))
            continue
        key = normalize_header(source)
        if key not in index_by_header:
            issues.append(ProfileIssue(MISSING_COLUMN, f"declared column {source!r} is absent"))
            continue
        column_index[canonical] = index_by_header[key]
    for required in profile.required_fields:
        if required not in column_index:
            issues.append(
                ProfileIssue(MISSING_REQUIRED_COLUMN, f"required column {required!r} is not resolved")
            )
    if issues:
        return ProfileValidation(False, {}, tuple(issues), fingerprint)
    return ProfileValidation(True, column_index, (), fingerprint)


def recognize_jofotara_profile(
    *,
    worksheet: str,
    headers: tuple[str, ...],
    registry: JoFotaraProfileRegistry = DEFAULT_JOFOTARA_REGISTRY,
) -> ProfileRecognition:
    """Strictly recognize a worksheet/header layout against approved profiles.

    Fail-closed order: empty headers, duplicate headers, no approved profile in
    the registry, unsupported worksheet, an unapproved (draft) profile matching
    the layout, header drift, and ambiguous multi-profile matches. With the
    shipped (empty) registry every input returns ``NO_APPROVED_PROFILE``.
    """
    if not isinstance(worksheet, str) or not worksheet.strip():
        raise ValueError("worksheet must be a non-blank string")
    if not isinstance(headers, tuple) or any(not isinstance(h, str) for h in headers):
        raise TypeError("headers must be a tuple of str")
    if not isinstance(registry, JoFotaraProfileRegistry):
        raise TypeError(f"registry must be JoFotaraProfileRegistry, got {type(registry).__name__}")
    if not headers:
        return ProfileRecognition(False, EMPTY_HEADERS)
    keys = [normalize_header(h) for h in headers]
    if len(keys) != len(set(keys)):
        return ProfileRecognition(False, DUPLICATE_HEADER)

    approved = registry.approved_profiles()
    if not approved:
        return ProfileRecognition(False, NO_APPROVED_PROFILE)
    candidates = tuple(p for p in approved if p.matches_worksheet(worksheet))
    if not candidates:
        return ProfileRecognition(False, UNSUPPORTED_WORKSHEET, details=(worksheet,))
    fingerprint = fingerprint_headers(headers)
    on_worksheet = tuple(p for p in candidates if p.header_fingerprint == fingerprint)
    if not on_worksheet:
        # A draft that matches the exact layout is actionable guidance, not a match.
        draft = tuple(
            p
            for p in registry.profiles
            if p.status != PROFILE_APPROVED
            and p.matches_worksheet(worksheet)
            and p.header_fingerprint == fingerprint
        )
        if draft:
            return ProfileRecognition(False, PROFILE_NOT_APPROVED, details=tuple(p.profile_id for p in draft))
        return ProfileRecognition(False, HEADER_DRIFT)
    if len(on_worksheet) > 1:
        return ProfileRecognition(
            False, AMBIGUOUS_PROFILE_MATCH, details=tuple(p.profile_id for p in on_worksheet)
        )
    profile = on_worksheet[0]
    validation = validate_jofotara_profile(profile, headers)
    if not validation.ok:
        return ProfileRecognition(
            False, validation.issues[0].code, details=tuple(i.code for i in validation.issues)
        )
    return ProfileRecognition(True, RECOGNIZED, profile=profile)


@dataclass(frozen=True)
class JoFotaraRowProvenance:
    """Source anchor for one JoFotara row or value (worksheet/row/column)."""

    dataset_id: str
    worksheet: str
    row_number: int

    def __post_init__(self) -> None:
        if not self.dataset_id.strip():
            raise ValueError("dataset_id must be non-blank")
        if not self.worksheet.strip():
            raise ValueError("worksheet must be non-blank")
        if self.row_number < 1:
            raise ValueError("row_number must be >= 1 (header is row 1)")


@dataclass(frozen=True)
class JoFotaraInvoice:
    """One JoFotara invoice under a recognized, approved profile.

    Values are exact; missing money is ``None`` (never zero) and identifiers are
    verbatim strings. Credit notes/reversals are linked records (reference), not
    netted. Constructed only via :func:`build_jofotara_invoice`, which requires a
    successful recognition from an approved profile.
    """

    issuer: str
    number: str
    currency: str | None
    net_amount: Decimal | None
    tax_amount: Decimal | None
    gross_amount: Decimal | None
    issue_date: date | None = None
    is_credit_note: bool = False
    reference_number: str | None = None
    provenance: JoFotaraRowProvenance | None = None

    def __post_init__(self) -> None:
        for label, text in (("issuer", self.issuer), ("number", self.number)):
            if not isinstance(text, str) or not text:
                raise TypeError(f"{label} must be a non-empty string (identifiers stay verbatim)")
        if self.currency is not None:
            object.__setattr__(self, "currency", normalize_currency(self.currency))
        for label, amount in (
            ("net_amount", self.net_amount),
            ("tax_amount", self.tax_amount),
            ("gross_amount", self.gross_amount),
        ):
            if amount is not None:
                if not isinstance(amount, Decimal):
                    raise TypeError(f"{label} must be Decimal, got {type(amount).__name__}")
                if amount.is_nan() or amount.is_infinite():
                    raise ValueError(f"{label} must be finite")
        if not isinstance(self.is_credit_note, bool):
            raise TypeError("is_credit_note must be bool")


def build_jofotara_invoice(
    *,
    recognition: ProfileRecognition,
    issuer: str,
    number: str,
    currency: str | None,
    net_amount: Decimal | None,
    tax_amount: Decimal | None,
    gross_amount: Decimal | None,
    issue_date: date | None = None,
    is_credit_note: bool = False,
    reference_number: str | None = None,
    provenance: JoFotaraRowProvenance | None = None,
) -> JoFotaraInvoice:
    """Build an invoice only from an approved, recognized profile (defense in depth)."""
    if not isinstance(recognition, ProfileRecognition):
        raise TypeError("recognition must be ProfileRecognition")
    if not recognition.recognized or recognition.profile is None:
        raise JoFotaraContractError(
            NOT_RECOGNIZED,
            "no approved JoFotara profile recognized this layout; import is refused",
        )
    if recognition.profile.status != PROFILE_APPROVED:
        raise JoFotaraContractError(PROFILE_NOT_APPROVED, "recognized profile is not approved")
    return JoFotaraInvoice(
        issuer=normalize_identifier(issuer),
        number=normalize_identifier(number),
        currency=currency,
        net_amount=net_amount,
        tax_amount=tax_amount,
        gross_amount=gross_amount,
        issue_date=issue_date,
        is_credit_note=is_credit_note,
        reference_number=reference_number,
        provenance=provenance,
    )

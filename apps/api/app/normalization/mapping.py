"""Explicit mapping approval gate + header drift detection.

The gate fails closed: duplicate/conflicting source columns, missing required
fields, unknown fields or headers, and unconfirmed mappings all block with
actionable diagnostics. Suggestions (see ``suggest``) never satisfy it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.normalization.contracts import (
    DRIFT_CHANGED,
    DRIFT_CURRENT,
    FIELDS_BY_DOCUMENT,
    GENERAL_LEDGER,
    GL_AMOUNT_FIELDS,
    REQUIRED_BY_DOCUMENT,
    ConfirmedMapping,
    DriftReport,
    MappingProfile,
)
from app.normalization.suggest import normalize_header


@dataclass(frozen=True)
class MappingIssue:
    """One blocking mapping diagnostic (all mapping issues block)."""

    code: str
    message: str


@dataclass(frozen=True)
class MappingReport:
    """Gate outcome: ``ok`` with column indexes, or blocking issues."""

    ok: bool
    column_index: dict[str, int]
    issues: tuple[MappingIssue, ...] = field(default_factory=tuple)
    header_fingerprint: str = ""


def fingerprint_headers(headers: tuple[str, ...]) -> str:
    """Stable sha256 over normalized headers (drift detection anchor)."""
    for header in headers:
        if not isinstance(header, str):
            raise TypeError(f"headers must be str, got {type(header).__name__}")
    canonical = "|".join(normalize_header(h) for h in headers)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_mapping(
    headers: tuple[str, ...],
    mapping: ConfirmedMapping,
    doc_type: str,
) -> MappingReport:
    """Validate an explicitly confirmed mapping against extracted headers."""
    if not isinstance(mapping, ConfirmedMapping):
        raise TypeError(f"mapping must be ConfirmedMapping, got {type(mapping).__name__}")
    fingerprint = fingerprint_headers(headers)
    issues: list[MappingIssue] = []
    known = FIELDS_BY_DOCUMENT.get(doc_type)
    if known is None:
        return MappingReport(
            ok=False,
            column_index={},
            issues=(MappingIssue("UNKNOWN_DOCUMENT_TYPE", f"unknown document type {doc_type!r}"),),
            header_fingerprint=fingerprint,
        )

    seen: dict[str, int] = {}
    for index, header in enumerate(headers):
        key = normalize_header(header)
        if key in seen:
            issues.append(
                MappingIssue(
                    "DUPLICATE_HEADER",
                    f"duplicate source column {header!r} at positions {seen[key]} and {index}",
                )
            )
        else:
            seen[key] = index

    if not mapping.confirmed:
        issues.append(
            MappingIssue(
                "UNCONFIRMED_MAPPING",
                "mapping suggestions are advisory only; an explicitly confirmed mapping is required",
            )
        )

    index_by_header = {normalize_header(h): i for i, h in enumerate(headers)}
    used_headers: dict[str, str] = {}
    column_index: dict[str, int] = {}
    for canonical_name, source_header in mapping.field_map.items():
        if canonical_name not in known:
            issues.append(
                MappingIssue("UNKNOWN_FIELD", f"field {canonical_name!r} is not valid for {doc_type}")
            )
            continue
        if not isinstance(source_header, str):
            issues.append(
                MappingIssue(
                    "MISSING_SOURCE_COLUMN",
                    f"field {canonical_name!r} maps to a non-text header",
                )
            )
            continue
        key = normalize_header(source_header)
        if key not in index_by_header:
            issues.append(
                MappingIssue(
                    "MISSING_SOURCE_COLUMN",
                    f"field {canonical_name!r} maps to missing column {source_header!r}",
                )
            )
            continue
        if key in used_headers:
            issues.append(
                MappingIssue(
                    "CONFLICTING_MAPPING",
                    f"columns conflict: {used_headers[key]!r} and {canonical_name!r} "
                    f"both map to {source_header!r}",
                )
            )
            continue
        used_headers[key] = canonical_name
        column_index[canonical_name] = index_by_header[key]

    for required in REQUIRED_BY_DOCUMENT[doc_type]:
        if required not in column_index:
            issues.append(
                MappingIssue(
                    "MISSING_REQUIRED_FIELD",
                    f"required field {required!r} is not mapped for {doc_type}",
                )
            )
    if doc_type == GENERAL_LEDGER and not any(f in column_index for f in GL_AMOUNT_FIELDS):
        issues.append(
            MappingIssue(
                "MISSING_REQUIRED_FIELD",
                "general_ledger requires at least one of debit_amount / credit_amount",
            )
        )
    if issues:
        return MappingReport(ok=False, column_index={}, issues=tuple(issues), header_fingerprint=fingerprint)
    return MappingReport(ok=True, column_index=column_index, issues=(), header_fingerprint=fingerprint)


def build_profile(
    *,
    profile_id: str,
    tenant_id: str,
    client_id: str,
    doc_type: str,
    headers: tuple[str, ...],
    mapping: ConfirmedMapping,
) -> MappingProfile:
    """Bind an approved mapping to its header shape for later reuse."""
    report = validate_mapping(headers, mapping, doc_type)
    if not report.ok:
        codes = ", ".join(i.code for i in report.issues)
        raise ValueError(f"cannot version an invalid mapping for reuse: {codes}")
    return MappingProfile(
        profile_id=profile_id,
        tenant_id=tenant_id,
        client_id=client_id,
        doc_type=doc_type,
        header_fingerprint=report.header_fingerprint,
        field_map=dict(mapping.field_map),
        mapping_version=mapping.mapping_version,
        approved_by=mapping.approved_by,
        approved_at=mapping.approved_at,
    )


def detect_drift(saved: MappingProfile, current_headers: tuple[str, ...]) -> DriftReport:
    """Compare current headers against a saved profile (pure, deterministic).

    Any shape change requires reconfirmation; reuse without it is unsafe.
    """
    if not isinstance(saved, MappingProfile):
        raise TypeError(f"saved must be MappingProfile, got {type(saved).__name__}")
    current_fp = fingerprint_headers(current_headers)
    if current_fp == saved.header_fingerprint:
        return DriftReport(status=DRIFT_CURRENT, message="headers match the approved profile")
    saved_keys = {normalize_header(h) for h in saved.field_map.values()}
    current_keys = {normalize_header(h) for h in current_headers}
    added = tuple(sorted(current_keys - saved_keys))
    removed = tuple(sorted(saved_keys - current_keys))
    return DriftReport(
        status=DRIFT_CHANGED,
        added=added,
        removed=removed,
        requires_reconfirmation=True,
        message=f"schema drift: {len(added)} new, {len(removed)} removed columns; reconfirm mapping",
    )

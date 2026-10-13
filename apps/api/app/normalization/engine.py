"""Deterministic dataset normalization engine (pure, no I/O).

Pipeline: mapping gate -> per-field normalization (dates strict, money via
``app.finance`` exact Decimal core, identifiers verbatim, GL debit/credit
independent) -> counts/readiness/preview/fingerprint/segregated totals.

Fail-closed rules: bad mappings produce no rows; invalid/ambiguous values
produce field errors (never zeros, never inferred formats or currencies);
out-of-period rows warn without being dropped; ``jofotara_export`` without an
approved format profile is refused outright (no invented layouts).

Totals policy: per-(field, currency) totals aggregate VALID + WARNING rows
only; FAILED rows never contribute, and ``eligible_rows``/``excluded_rows``
state the coverage so totals are never mistaken for full-period figures.

Row policy: a general-ledger row normalizes to VALID only with at least one
valid monetary value; mapped-but-blank debit/credit with no other amount is
a blocking MISSING_GL_AMOUNTS error (whether one or both sides are mapped).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date
from decimal import Decimal

from app.finance import (
    MoneyParseError,
    ParsedMoney,
    ParseProfile,
    parse_amount,
    total_by_currency,
)
from app.normalization.contracts import (
    FIELD_KIND,
    FIELDS_BY_DOCUMENT,
    GENERAL_LEDGER,
    JOFOTARA_EXPORT,
    NOT_READY,
    READY_FOR_CHECKS,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    STATUS_FAILED,
    STATUS_VALID,
    STATUS_WARNING,
    ConfirmedMapping,
    DatasetResult,
    ExtractedRow,
    ExtractedSheet,
    FieldIssue,
    FieldTotal,
    MappingRevision,
    NormalizationOptions,
    NormalizedField,
    NormalizedRow,
    RowCounts,
    SourceDocument,
    SourceLocation,
)
from app.normalization.dates import DATE_FORMATS, parse_strict_date
from app.normalization.mapping import fingerprint_headers, validate_mapping
from app.normalization.suggest import normalize_header

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_PREVIEW_LIMIT = 20


def _location(doc: SourceDocument, row_number: int, column_index: int, header: str) -> SourceLocation:
    return SourceLocation(
        doc_id=doc.doc_id,
        content_hash=doc.content_hash,
        worksheet=doc.worksheet,
        row_number=row_number,
        column_index=column_index,
        header=header,
    )


def _norm_currency(value: str) -> str | None:
    normalized = value.strip().upper()
    return normalized if _CURRENCY_RE.match(normalized) else None


def _money_field(
    raw: str,
    *,
    currency: str | None,
    numbers: ParseProfile,
    location: SourceLocation,
    required: bool,
) -> tuple[ParsedMoney | None, tuple[FieldIssue, ...]]:
    if raw.strip() == "":
        if not required:
            return None, ()
        return None, (FieldIssue("MISSING_AMOUNT", "blank amount is not zero", SEVERITY_ERROR, location),)
    if currency is None:
        return None, (
            FieldIssue(
                "MISSING_CURRENCY",
                "no currency column mapped and no explicitly approved default currency",
                SEVERITY_ERROR,
                location,
            ),
        )
    try:
        return parse_amount(raw, currency=currency, profile=numbers), ()
    except MoneyParseError as exc:
        return None, (FieldIssue(f"INVALID_AMOUNT [{exc.code}]", str(exc), SEVERITY_ERROR, location),)


def _date_field(
    raw: str,
    *,
    date_format: str | None,
    period: tuple[date | None, date | None],
    location: SourceLocation,
) -> tuple[date | None, tuple[FieldIssue, ...]]:
    if raw.strip() == "":
        return None, (FieldIssue("MISSING_DATE", "blank date", SEVERITY_ERROR, location),)
    if date_format is None:
        return None, (
            FieldIssue(
                "AMBIGUOUS_DATE_FORMAT",
                f"no explicit date format selected; {raw!r} stays unresolved "
                "(e.g. 01/02/2026 is never guessed as DMY or MDY)",
                SEVERITY_ERROR,
                location,
            ),
        )
    try:
        value = parse_strict_date(raw, date_format)
    except ValueError as exc:
        return None, (FieldIssue("INVALID_DATE", str(exc), SEVERITY_ERROR, location),)
    start, end = period
    if (start is not None and value < start) or (end is not None and value > end):
        return value, (
            FieldIssue(
                "OUT_OF_PERIOD",
                f"{value.isoformat()} outside period; flagged, not discarded",
                SEVERITY_WARNING,
                location,
            ),
        )
    return value, ()


def _identifier_field(raw: str, *, location: SourceLocation) -> tuple[str | None, tuple[FieldIssue, ...]]:
    if raw.strip() == "":
        return None, (FieldIssue("MISSING_IDENTIFIER", "blank identifier", SEVERITY_ERROR, location),)
    return raw.strip(), ()  # verbatim: leading zeros preserved, never coerced


def _resolve_row_currency(
    cells: tuple[str, ...],
    column_index: dict[str, int],
    default_currency: str | None,
    headers: tuple[str, ...],
    doc: SourceDocument,
    row_number: int,
) -> tuple[str | None, NormalizedField | None]:
    """Resolve the row currency; returns (code, currency-field-or-None)."""
    if "currency" not in column_index:
        return default_currency, None
    idx = column_index["currency"]
    loc = _location(doc, row_number, idx, headers[idx])
    code = _norm_currency(cells[idx])
    if code is None:
        if cells[idx].strip() == "":
            issue = FieldIssue("MISSING_CURRENCY", "blank currency cell", SEVERITY_ERROR, loc)
        else:
            issue = FieldIssue(
                "INVALID_CURRENCY",
                f"unrecognized currency {cells[idx]!r}; explicit 3-letter code required",
                SEVERITY_ERROR,
                loc,
            )
        failed = NormalizedField(
            canonical="currency",
            raw=cells[idx],
            normalized=None,
            currency=None,
            location=loc,
            issues=(issue,),
        )
        return None, failed
    return code, NormalizedField(
        canonical="currency",
        raw=cells[idx],
        normalized=code,
        currency=code,
        location=loc,
        issues=(),
    )


def _normalize_row(
    cells: tuple[str, ...],
    row_number: int,
    doc: SourceDocument,
    headers: tuple[str, ...],
    column_index: dict[str, int],
    doc_type: str,
    numbers: ParseProfile,
    date_format: str | None,
    period: tuple[date | None, date | None],
    default_currency: str | None,
) -> tuple[NormalizedRow, list[tuple[str, ParsedMoney]]]:
    fields: list[NormalizedField] = []
    money: list[tuple[str, ParsedMoney]] = []
    row_currency, currency_field = _resolve_row_currency(
        cells, column_index, default_currency, headers, doc, row_number
    )
    if currency_field is not None:
        fields.append(currency_field)

    for canonical_name in FIELDS_BY_DOCUMENT[doc_type]:
        if canonical_name not in column_index or canonical_name == "currency":
            continue
        idx = column_index[canonical_name]
        loc = _location(doc, row_number, idx, headers[idx])
        raw = cells[idx]
        kind = FIELD_KIND[canonical_name]
        used_currency: str | None = None
        normalized: Decimal | date | str | None
        if kind == "MONEY":
            pm, issues = _money_field(
                raw,
                currency=row_currency,
                numbers=numbers,
                location=loc,
                required=(canonical_name == "net_amount"),
            )
            normalized = pm.amount if pm else None
            used_currency = pm.currency if pm else (row_currency if raw.strip() != "" else None)
            if pm is not None:
                money.append((canonical_name, pm))
        elif kind == "DATE":
            normalized, issues = _date_field(raw, date_format=date_format, period=period, location=loc)
        elif kind == "IDENTIFIER":
            normalized, issues = _identifier_field(raw, location=loc)
        else:  # TEXT
            normalized, issues = raw.strip(), ()
        fields.append(
            NormalizedField(
                canonical=canonical_name,
                raw=raw,
                normalized=normalized,
                currency=used_currency,
                location=loc,
                issues=issues,
            )
        )

    row_issues: list[FieldIssue] = []
    if doc_type == GENERAL_LEDGER:
        amount_fields = [f for f in fields if f.canonical in ("debit_amount", "credit_amount")]
        has_value = any(isinstance(f.normalized, Decimal) for f in amount_fields)
        has_amount_error = any(i.severity == SEVERITY_ERROR for f in amount_fields for i in f.issues)
        # No financial data in any mapped amount column: the row carries
        # nothing reconcilable, so it fails whether one or both sides are
        # mapped. (Invalid-but-present amounts already fail via field errors.)
        if amount_fields and not has_value and not has_amount_error:
            row_issues.append(
                FieldIssue(
                    "MISSING_GL_AMOUNTS",
                    "no debit or credit value; a ledger row without an amount "
                    "is not reconcilable and cannot be READY",
                    SEVERITY_ERROR,
                    _location(doc, row_number, -1, ""),
                )
            )
    if any(i.severity == SEVERITY_ERROR for f in fields for i in f.issues) or any(
        i.severity == SEVERITY_ERROR for i in row_issues
    ):
        status = STATUS_FAILED
    elif any(i.severity == SEVERITY_WARNING for f in fields for i in f.issues) or row_issues:
        status = STATUS_WARNING
    else:
        status = STATUS_VALID
    return (
        NormalizedRow(
            row_number=row_number, status=status, fields=tuple(fields), row_issues=tuple(row_issues)
        ),
        money,
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _dataset_fingerprint(
    doc: SourceDocument,
    doc_type: str,
    mapping: ConfirmedMapping,
    header_fp: str,
    options: NormalizationOptions,
    sheet: ExtractedSheet,
    rows: tuple[NormalizedRow, ...],
) -> str:
    payload = {
        "doc": {"id": doc.doc_id, "hash": doc.content_hash, "worksheet": doc.worksheet},
        "doc_type": doc_type,
        "mapping": {
            "version": mapping.mapping_version,
            "map": dict(sorted(mapping.field_map.items())),
            "header_fp": header_fp,
        },
        "options": {
            "dec": options.decimal_separator,
            "grp": options.grouping_separator,
            "date": options.date_format,
            "cur": options.default_currency.upper() if options.default_currency else None,
            "period": [
                options.period_start.isoformat() if options.period_start else None,
                options.period_end.isoformat() if options.period_end else None,
            ],
        },
        "rows": [{"n": r.row_number, "cells": list(r.cells)} for r in sheet.rows],
        "normalized": [
            {
                "n": r.row_number,
                "fields": [
                    [
                        f.canonical,
                        f.raw,
                        f.normalized.isoformat()
                        if isinstance(f.normalized, date)
                        else (str(f.normalized) if f.normalized is not None else None),
                        f.currency,
                        [i.code for i in f.issues],
                    ]
                    for f in r.fields
                ],
            }
            for r in rows
        ],
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _segregated_totals(money: list[tuple[str, ParsedMoney]]) -> tuple[FieldTotal, ...]:
    grouped: dict[tuple[str, str], list[ParsedMoney]] = {}
    for canonical_name, pm in money:
        grouped.setdefault((canonical_name, pm.currency), []).append(pm)
    totals: list[FieldTotal] = []
    for (canonical_name, currency), items in sorted(grouped.items()):
        totals.append(
            FieldTotal(field=canonical_name, currency=currency, total=total_by_currency(items)[currency])
        )
    return tuple(totals)


def _refused_result(
    doc_type: str,
    blocking: tuple[FieldIssue, ...],
    mapping: ConfirmedMapping,
    header_fp: str,
    sheet: ExtractedSheet,
    doc: SourceDocument,
    options: NormalizationOptions,
) -> DatasetResult:
    """Refused datasets produce no rows; counts stay zero and reconcile.

    The blocking issue carries the refused input-row count for traceability.
    """
    annotated: tuple[FieldIssue, ...] = blocking
    if blocking:
        first, *rest = blocking
        annotated = (
            FieldIssue(
                first.code,
                first.message + f" (refused {len(sheet.rows)} input rows; no rows normalized)",
                first.severity,
                first.location,
            ),
            *rest,
        )
    return DatasetResult(
        doc_type=doc_type,
        readiness=NOT_READY,
        rows=(),
        preview=(),
        counts=RowCounts(total=0, valid=0, warning=0, failed=0),
        eligible_rows=0,
        excluded_rows=0,
        blocking_issues=annotated,
        warnings=(),
        totals=(),
        fingerprint=_dataset_fingerprint(doc, doc_type, mapping, header_fp, options, sheet, ()),
        mapping_revision=MappingRevision(
            mapping_version=mapping.mapping_version,
            header_fingerprint=header_fp,
            approved_by=mapping.approved_by,
        ),
        timings_ms={},
    )


def normalize_dataset(
    doc: SourceDocument,
    sheet: ExtractedSheet,
    mapping: ConfirmedMapping,
    options: NormalizationOptions,
) -> DatasetResult:
    """Normalize extracted rows into validated canonical rows (deterministic).

    Never raises for data problems (they become issues + NOT_READY); raises
    ``TypeError`` only for wrong Python types. Never mutates its inputs.
    """
    total_start = time.perf_counter()
    if not isinstance(doc, SourceDocument):
        raise TypeError(f"doc must be SourceDocument, got {type(doc).__name__}")
    if not isinstance(sheet, ExtractedSheet):
        raise TypeError(f"sheet must be ExtractedSheet, got {type(sheet).__name__}")
    if not isinstance(mapping, ConfirmedMapping):
        raise TypeError(f"mapping must be ConfirmedMapping, got {type(mapping).__name__}")
    if not isinstance(options, NormalizationOptions):
        raise TypeError(f"options must be NormalizationOptions, got {type(options).__name__}")
    if not isinstance(options.doc_type, str):
        raise TypeError("options.doc_type must be an explicit document-type string")
    if not isinstance(sheet.headers, tuple) or any(not isinstance(h, str) for h in sheet.headers):
        raise TypeError("sheet.headers must be a tuple of str")
    for row in sheet.rows:
        if not isinstance(row, ExtractedRow) or not isinstance(row.cells, tuple):
            raise TypeError("sheet.rows must hold ExtractedRow with tuple cells")
        if any(not isinstance(c, str) for c in row.cells):
            raise TypeError(f"row {row.row_number} cells must all be str (no coercion)")

    doc_type = options.doc_type
    header_fp = fingerprint_headers(sheet.headers)

    if doc_type == JOFOTARA_EXPORT:
        return _refused_result(
            doc_type,
            (
                FieldIssue(
                    "UNSUPPORTED_PROFILE",
                    "jofotara_export has no approved format profile in this build; "
                    "normalization refused (no invented layouts, rates, or versions). "
                    "Supply real representative exports and an approved profile later.",
                    SEVERITY_ERROR,
                    None,
                ),
            ),
            mapping,
            header_fp,
            sheet,
            doc,
            options,
        )

    map_start = time.perf_counter()
    report = validate_mapping(sheet.headers, mapping, doc_type)
    mapping_ms = (time.perf_counter() - map_start) * 1000.0
    if not report.ok:
        return _refused_result(
            doc_type,
            tuple(FieldIssue(f"MAPPING_{i.code}", i.message, SEVERITY_ERROR, None) for i in report.issues),
            mapping,
            header_fp,
            sheet,
            doc,
            options,
        )

    if options.date_format is not None and options.date_format not in DATE_FORMATS:
        return _refused_result(
            doc_type,
            (
                FieldIssue(
                    "INVALID_DATE_PROFILE",
                    f"unknown date_format {options.date_format!r}; "
                    f"choose one of {sorted(DATE_FORMATS)} or leave unset",
                    SEVERITY_ERROR,
                    None,
                ),
            ),
            mapping,
            header_fp,
            sheet,
            doc,
            options,
        )

    default_currency: str | None = None
    if options.default_currency is not None:
        default_currency = _norm_currency(options.default_currency)
        if default_currency is None:
            return _refused_result(
                doc_type,
                (
                    FieldIssue(
                        "INVALID_DEFAULT_CURRENCY",
                        f"default_currency {options.default_currency!r} is not an explicit "
                        "3-letter code; no JOD assumption is ever applied",
                        SEVERITY_ERROR,
                        None,
                    ),
                ),
                mapping,
                header_fp,
                sheet,
                doc,
                options,
            )

    blocking: list[FieldIssue] = []
    if not sheet.rows:
        blocking.append(FieldIssue("EMPTY_DATASET", "no data rows extracted", SEVERITY_ERROR, None))
    if "currency" not in report.column_index and default_currency is None:
        blocking.append(
            FieldIssue(
                "MISSING_CURRENCY_SOURCE",
                "no currency column mapped and no explicitly approved default_currency; "
                "money fields cannot normalize without an explicit currency",
                SEVERITY_ERROR,
                None,
            )
        )

    numbers = ParseProfile(
        decimal_separator=options.decimal_separator, grouping_separator=options.grouping_separator
    )
    norm_start = time.perf_counter()
    rows: list[NormalizedRow] = []
    all_money: list[tuple[str, ParsedMoney]] = []
    for row in sheet.rows:
        if len(row.cells) != len(sheet.headers):
            rows.append(
                NormalizedRow(
                    row_number=row.row_number,
                    status=STATUS_FAILED,
                    fields=(),
                    row_issues=(
                        FieldIssue(
                            "ROW_SHAPE_MISMATCH",
                            f"row has {len(row.cells)} cells for {len(sheet.headers)} headers; "
                            "kept as failed, never realigned by guessing",
                            SEVERITY_ERROR,
                            _location(doc, row.row_number, -1, ""),
                        ),
                    ),
                )
            )
            continue
        normalized_row, row_money = _normalize_row(
            row.cells,
            row.row_number,
            doc,
            sheet.headers,
            report.column_index,
            doc_type,
            numbers,
            options.date_format,
            (options.period_start, options.period_end),
            default_currency,
        )
        rows.append(normalized_row)
        # R1: only eligible rows (VALID/WARNING) feed totals; FAILED rows
        # never contribute, even when individual money fields parsed cleanly.
        if normalized_row.status != STATUS_FAILED:
            all_money.extend(row_money)
    normalization_ms = (time.perf_counter() - norm_start) * 1000.0

    valid = sum(1 for r in rows if r.status == STATUS_VALID)
    warning = sum(1 for r in rows if r.status == STATUS_WARNING)
    failed = sum(1 for r in rows if r.status == STATUS_FAILED)
    assert valid + warning + failed == len(rows)

    used = {normalize_header(sheet.headers[i]) for i in report.column_index.values()}
    unmapped = [h for h in sheet.headers if normalize_header(h) not in used]
    warnings: list[FieldIssue] = []
    if unmapped:
        warnings.append(
            FieldIssue(
                "UNMAPPED_COLUMNS",
                f"ignored unmapped columns: {', '.join(unmapped)}",
                SEVERITY_WARNING,
                None,
            )
        )

    readiness = READY_FOR_CHECKS if rows and not blocking and failed == 0 else NOT_READY

    rows_t = tuple(rows)
    fingerprint = _dataset_fingerprint(doc, doc_type, mapping, header_fp, options, sheet, rows_t)
    return DatasetResult(
        doc_type=doc_type,
        readiness=readiness,
        rows=rows_t,
        preview=rows_t[:_PREVIEW_LIMIT],
        counts=RowCounts(total=len(rows_t), valid=valid, warning=warning, failed=failed),
        eligible_rows=valid + warning,
        excluded_rows=failed,
        blocking_issues=tuple(blocking),
        warnings=tuple(warnings),
        totals=_segregated_totals(all_money),
        fingerprint=fingerprint,
        mapping_revision=MappingRevision(
            mapping_version=mapping.mapping_version,
            header_fingerprint=header_fp,
            approved_by=mapping.approved_by,
        ),
        timings_ms={
            "mapping_ms": mapping_ms,
            "normalization_ms": normalization_ms,
            "total_ms": (time.perf_counter() - total_start) * 1000.0,
        },
    )

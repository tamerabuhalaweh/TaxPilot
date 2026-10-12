"""Advisory header suggestions (EN + AR). Never authoritative (FR-EXT-002).

Suggestions only propose candidate canonical fields for source headers. The
mapping gate requires an explicitly confirmed mapping regardless of what is
suggested; suggestions alone can never produce a READY_FOR_CHECKS dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.normalization.contracts import FIELDS_BY_DOCUMENT

# Canonical field -> known header variants (English + Arabic). Curated,
# minimal, and explicit: unknown headers yield no suggestion rather than a
# guess. This table proposes labels only; it carries no tax or JoFotara
# semantics and invents no government layouts.
_HEADER_VARIANTS: dict[str, tuple[str, ...]] = {
    "invoice_number": (
        "Invoice Number",
        "Invoice No",
        "Invoice No.",
        "Inv No",
        "Inv Number",
        "Invoice #",
        "Bill Number",
        "رقم الفاتورة",
        "رقم الفاتوره",
        "رقم الفاتورة الضريبية",
    ),
    "transaction_date": (
        "Invoice Date",
        "Date",
        "Transaction Date",
        "Posting Date",
        "GL Date",
        "التاريخ",
        "تاريخ الفاتورة",
        "تاريخ القيد",
        "تاريخ العملية",
    ),
    "net_amount": (
        "Net Amount",
        "Net",
        "Net Value",
        "Net Sales",
        "صافي المبلغ",
        "الصافي",
        "المبلغ الصافي",
        "صافي المبيعات",
    ),
    "tax_amount": (
        "Tax Amount",
        "VAT Amount",
        "Tax",
        "VAT",
        "مبلغ الضريبة",
        "الضريبة",
        "ضريبة القيمة المضافة",
    ),
    "gross_amount": (
        "Gross Amount",
        "Total Amount",
        "Total",
        "Grand Total",
        "المبلغ الإجمالي",
        "الإجمالي",
        "المبلغ الكلي",
    ),
    "account_code": (
        "Account No.",
        "Account Number",
        "Account No",
        "Account Code",
        "GL Account",
        "Acct No",
        "رقم الحساب",
        "رمز الحساب",
        "الحساب",
    ),
    "debit_amount": (
        "Debit",
        "Dr",
        "Debit Amount",
        "مدين",
    ),
    "credit_amount": (
        "Credit",
        "Cr",
        "Credit Amount",
        "دائن",
    ),
    "currency": (
        "Currency",
        "Curr",
        "Cur",
        "العملة",
    ),
    "description": (
        "Description",
        "Details",
        "Narration",
        "Particulars",
        "الوصف",
        "البيان",
        "التفاصيل",
    ),
}

_PUNCTUATION = frozenset("._-#/\\:()")


def normalize_header(header: str) -> str:
    """Normalize a header for comparison: casefold, unify Arabic alefs,
    strip punctuation/extra spaces. Comparison helper only."""
    text = header.strip().casefold()
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ـ", "").replace("ة", "ه")
    text = "".join(" " if ch in _PUNCTUATION else ch for ch in text)
    return " ".join(text.split())


_LOOKUP: dict[str, str] = {}
for _canonical, _variants in _HEADER_VARIANTS.items():
    for _variant in _variants:
        _LOOKUP.setdefault(normalize_header(_variant), _canonical)


@dataclass(frozen=True)
class HeaderSuggestion:
    """Advisory proposal for one header; ``canonical`` None means unknown."""

    header: str
    canonical: str | None


def suggest_mapping(headers: tuple[str, ...], doc_type: str) -> tuple[HeaderSuggestion, ...]:
    """Propose canonical fields for headers (advisory only, deterministic).

    Unknown document types or headers yield ``None`` suggestions rather than
    guesses. When two headers suggest the same canonical field, both keep
    their suggestion here; the mapping gate rejects the conflict.
    """
    allowed = FIELDS_BY_DOCUMENT.get(doc_type)
    suggestions: list[HeaderSuggestion] = []
    for header in headers:
        if not isinstance(header, str):
            raise TypeError(f"suggest_mapping expects str headers, got {type(header).__name__}")
        canonical = _LOOKUP.get(normalize_header(header))
        if allowed is None or canonical not in allowed:
            canonical = None
        suggestions.append(HeaderSuggestion(header=header, canonical=canonical))
    return tuple(suggestions)

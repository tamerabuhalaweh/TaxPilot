"""EP-04A CSV extraction unit tests (synthetic bytes built in-test)."""

import hashlib
import io

import pytest

from app.extraction import (
    CsvSettings,
    ExtractionError,
    ExtractionLimits,
    ExtractionResult,
    XlsxSettings,
    extract_bytes,
    extract_stream,
)

SALES_CSV = (
    "Invoice Number,Invoice Date,Net Amount,Currency\n"
    'INV-0001,05/01/2026,"1,234.500",JOD\n'
    "000123,06/01/2026,-100.000,JOD\n"
)


def extract(data: bytes, **kwargs: object) -> ExtractionResult:
    settings = CsvSettings(delimiter=",")
    return extract_bytes(data, declared_format="csv", doc_id="SYN-CSV-1", csv=settings, **kwargs)  # type: ignore[arg-type]


def test_sales_csv_happy_path_provenance_and_hash() -> None:
    data = SALES_CSV.encode("utf-8")
    result = extract(data)
    assert result.doc.content_hash == hashlib.sha256(data).hexdigest()
    assert result.doc.worksheet == "CSV" and result.doc.doc_id == "SYN-CSV-1"
    assert result.sheet.headers == ("Invoice Number", "Invoice Date", "Net Amount", "Currency")
    assert [r.row_number for r in result.sheet.rows] == [2, 3]
    assert result.sheet.rows[0].cells[2] == "1,234.500"  # quoted comma kept
    assert result.sheet.rows[1].cells[0] == "000123"  # leading zeros, no coercion
    assert (result.stats.data_rows, result.stats.skipped_blank_rows) == (2, 0)


def test_bom_accepted_identically() -> None:
    plain = extract(SALES_CSV.encode("utf-8"))
    bom = extract(b"\xef\xbb\xbf" + SALES_CSV.encode("utf-8"))
    assert bom.sheet == plain.sheet


def test_quoted_newlines_keep_row_positions() -> None:
    data = b'A,B\n"line1\nline2",x\ny,z\n'
    result = extract(data)
    assert [r.row_number for r in result.sheet.rows] == [2, 4]
    assert result.sheet.rows[0].cells == ("line1\nline2", "x")


def test_semicolon_delimiter_explicit_no_sniffing() -> None:
    data = b"A;B\n1;2\n"
    result = extract_bytes(data, declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=";"))
    assert result.sheet.headers == ("A", "B")
    # Comma content under ';' never magically splits (no sniffing):
    single = extract_bytes(b"A,B\n1,2\n", declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=";"))
    assert single.sheet.headers == ("A,B",) and single.sheet.rows[0].cells == ("1,2",)


def test_header_row_selection_skips_preamble() -> None:
    data = b"Report title\nGenerated 2026\nA,B\n1,2\n"
    result = extract_bytes(
        data, declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=",", header_row=3)
    )
    assert result.sheet.headers == ("A", "B")
    assert result.sheet.rows[0].row_number == 4


def test_blank_lines_skipped_with_gaps() -> None:
    data = b"A,B\n1,2\n\n   \n3,4\n"
    result = extract(data)
    assert [r.row_number for r in result.sheet.rows] == [2, 5]
    assert result.stats.skipped_blank_rows == 2


def test_arabic_headers_and_values_verbatim() -> None:
    data = "رقم الفاتورة,صافي المبلغ\n000077,300.00\n".encode()
    result = extract(data)
    assert result.sheet.headers == ("رقم الفاتورة", "صافي المبلغ")
    assert result.sheet.rows[0].cells[0] == "000077"


def test_hash_reproducible_and_sensitive() -> None:
    first = extract(SALES_CSV.encode())
    assert extract(SALES_CSV.encode()).doc.content_hash == first.doc.content_hash
    assert extract((SALES_CSV + " ").encode()).doc.content_hash != first.doc.content_hash


def test_stream_matches_bytes_path() -> None:
    data = SALES_CSV.encode()
    via_stream = extract_stream(
        io.BytesIO(data), declared_format="csv", doc_id="S", csv=CsvSettings(delimiter=",")
    )
    assert via_stream.sheet == extract(data).sheet
    assert via_stream.doc.content_hash == hashlib.sha256(data).hexdigest()


def test_stream_over_cap_aborts() -> None:
    limits = ExtractionLimits(max_file_bytes=10)
    with pytest.raises(ExtractionError) as exc:
        extract_stream(
            io.BytesIO(b"x" * 5000),
            declared_format="csv",
            doc_id="D",
            csv=CsvSettings(delimiter=","),
            limits=limits,
        )
    assert exc.value.code == "FILE_TOO_LARGE"


# Failure modes: every malformed shape fails closed with a typed code.
def test_zip_bytes_declared_csv_rejected() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract(b"PK\x03\x04" + b"\x00" * 100)
    assert exc.value.code == "FORMAT_MISMATCH"


def test_latin1_and_utf16_rejected_without_fallback() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract("Aé\n".encode("latin-1"))
    assert exc.value.code == "MALFORMED_ENCODING"
    with pytest.raises(ExtractionError):
        extract("A,B\n1,2\n".encode("utf-16"))


def test_bad_quoting_rejected() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract(b'A,B\n"unclosed,2\n')
    assert exc.value.code == "MALFORMED_CSV"


def test_ragged_long_row_reports_line() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract(b"A,B\n1,2,EXTRA\n")
    assert exc.value.code == "RAGGED_ROW"
    assert exc.value.detail["row_number"] == 2


def test_short_rows_padded_not_failed() -> None:
    result = extract(b"A,B,C\n1,2\n")
    assert result.sheet.rows[0].cells == ("1", "2", "")


def test_blank_line_only_file_has_empty_headers() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract(b"\n")
    assert exc.value.code == "EMPTY_HEADERS"


def test_header_row_beyond_file() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract_bytes(
            b"A,B\n", declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=",", header_row=5)
        )
    assert exc.value.code == "HEADER_ROW_MISSING"


def test_blank_header_cell_rejected() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract(b"A,,C\n1,2,3\n")
    assert exc.value.code == "BLANK_HEADER"


def test_empty_file_rejected() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract(b"")
    assert exc.value.code == "EMPTY_FILE"


def test_limits_enforced() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract(b"A,B\n1,2\n", limits=ExtractionLimits(max_file_bytes=5))
    assert exc.value.code == "FILE_TOO_LARGE"
    with pytest.raises(ExtractionError) as exc:
        extract(b"A,B\n1,2\n3,4\n", limits=ExtractionLimits(max_rows=1))
    assert exc.value.code == "TOO_MANY_ROWS"
    with pytest.raises(ExtractionError) as exc:
        extract(b"A,B,C\n1,2,3\n", limits=ExtractionLimits(max_columns=2))
    assert exc.value.code == "TOO_MANY_COLUMNS"
    with pytest.raises(ExtractionError) as exc:
        extract(b"ABCDEFGH\n12345678\n", limits=ExtractionLimits(max_cell_chars=5))
    assert exc.value.code == "CELL_TOO_LARGE"


def test_config_and_type_errors() -> None:
    with pytest.raises(ExtractionError) as exc:
        extract_bytes(b"A,B\n1,2\n", declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=":"))
    assert exc.value.code == "INVALID_DELIMITER"
    with pytest.raises(ExtractionError):
        extract_bytes(
            b"A,B\n1,2\n", declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=",", header_row=0)
        )
    with pytest.raises(ExtractionError) as exc:
        extract_bytes(b"A,B\n", declared_format="parquet", doc_id="D")
    assert exc.value.code == "UNSUPPORTED_FORMAT"
    with pytest.raises(ExtractionError) as exc:
        extract_bytes(
            b"A,B\n",
            declared_format="csv",
            doc_id="D",
            csv=CsvSettings(delimiter=","),
            xlsx=XlsxSettings(sheet_name="Sheet1"),
        )
    assert exc.value.code == "SETTINGS_MISMATCH"
    with pytest.raises(TypeError):
        extract_bytes("not-bytes", declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=","))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        extract_stream("not-a-stream", declared_format="csv", doc_id="D", csv=CsvSettings(delimiter=","))  # type: ignore[arg-type]

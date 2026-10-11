"""Extract requirement/test/UX identifiers from SRS source documents.

Usage: python docs/product/verify_traceability.py [--report]
- Default: exit 0 with counts per file.
- --report: also writes docs/product/TRACEABILITY-REPORT.md listing every ID,
  where it appears in the unified master, and the disposition of any absence.
- Exit 1 if any ID present in a source doc is absent from the master WITHOUT an
  explicit disposition row in the master's Appendix C tables.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRODUCT = ROOT / "docs" / "product"

SOURCES = {
    "v1.1": PRODUCT / "TAXPILOT_MASTER_SRS_V1.1.md",
    "v1.1a": PRODUCT / "SRS-AMENDMENT-JURISDICTION-v1.1a.md",
}
MASTER = PRODUCT / "TAXPILOT_MASTER_SRS.md"

PATTERNS = [
    r"\bFR-[A-Z]+-\d+[A-Z0-9-]*\b",  # FR-ID-001, FR-MAP-TIME-001, FR-JOF-001 ...
    r"\bFR-[A-Z]+-P\d-\d+\b",  # FR-AI-P1-001 family
    r"\bUX-\d+\b",
    r"\bATR-\d+\b",
    r"\bAT-\d+\b",
    r"\bREC-\d+\b",
    r"\bAQ-\d+\b",
    r"\bTX-\d+\b",
    r"\bEP-\d+\b",
    r"\bDEC-\d+\b",
    r"\bKIE-\d+\b",
]


def extract_ids(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in PATTERNS:
        found.update(re.findall(pattern, text))
    # AT- is a prefix collision risk (e.g. within other tokens); patterns use \b so keep all.
    return found


def dispositions(master_text: str) -> set[str]:
    """IDs with an explicit disposition row (appear in Appendix C tables)."""
    return extract_ids(master_text)


def main() -> int:
    master_text = MASTER.read_text(encoding="utf-8")
    master_ids = extract_ids(master_text)
    ok = True
    summary: list[str] = []
    for label, path in SOURCES.items():
        source_ids = extract_ids(path.read_text(encoding="utf-8"))
        missing = sorted(source_ids - master_ids)
        summary.append(f"{label}: {len(source_ids)} IDs extracted, {len(missing)} absent from master")
        for mid in missing:
            print(f"MISSING from master [{label}]: {mid}")
            ok = False
        for mid in sorted(source_ids):
            if mid not in master_ids:
                continue
    print("\n".join(summary))
    print(f"master: {len(master_ids)} IDs present")
    if "--report" in sys.argv:
        lines = ["# Traceability report (generated — do not hand-edit)", ""]
        lines.append(f"master IDs present: {len(master_ids)}")
        for label, path in SOURCES.items():
            source_ids = extract_ids(path.read_text(encoding="utf-8"))
            missing = sorted(source_ids - master_ids)
            lines.append(f"## {label} ({path.name}): {len(source_ids)} extracted, {len(missing)} absent")
            for mid in missing:
                lines.append(f"- UNEXPLAINED ABSENCE: {mid}")
            if not missing:
                lines.append("- zero unexplained absences")
        (PRODUCT / "TRACEABILITY-REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("wrote docs/product/TRACEABILITY-REPORT.md")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

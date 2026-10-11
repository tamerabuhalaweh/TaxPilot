"""Unit tests for the fail-closed security gate (CI-SEC-01 #36 evidence).

Covers: clean audits pass; unexempt high/critical blocks; findings without advisory
URLs block; missing severity blocks; malformed audit blocks; expired/unsigned
exceptions do not suppress; valid signed unexpired exceptions suppress.
"""

import json
import subprocess
import sys
from pathlib import Path

GATE = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "security_gate.py"


def run_gate(audit: object, exceptions: object, eco: str | None = None) -> subprocess.CompletedProcess[str]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        audit_p = Path(tmp) / "audit.json"
        exc_p = Path(tmp) / "exc.json"
        audit_p.write_text(json.dumps(audit), encoding="utf-8")
        exc_p.write_text(json.dumps(exceptions), encoding="utf-8")
        if eco is None:
            eco = "npm" if isinstance(audit, dict) and "vulnerabilities" in audit else "pip"
        return subprocess.run(
            [
                sys.executable,
                str(GATE),
                "--ecosystem",
                eco,
                "--audit",
                str(audit_p),
                "--exceptions",
                str(exc_p),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )


def npm_audit(*items: dict) -> dict:
    return {"vulnerabilities": {f"pkg{i}": item for i, item in enumerate(items)}}


def test_clean_audits_pass():
    assert run_gate(npm_audit(), {"npm": [], "pip": []}).returncode == 0
    assert run_gate([], {"npm": [], "pip": []}).returncode == 0


def test_unexempt_critical_blocks():
    audit = npm_audit(
        {
            "severity": "critical",
            "range": "<9",
            "via": [{"url": "https://github.com/advisories/GHSA-test-1", "title": "x"}],
        }
    )
    proc = run_gate(audit, {"npm": [], "pip": []})
    assert proc.returncode == 1 and "BLOCKING" in proc.stdout


def test_high_without_advisory_url_blocks():
    audit = npm_audit({"severity": "high", "range": "<9", "via": ["postcss"]})
    proc = run_gate(audit, {"npm": [], "pip": []})
    assert proc.returncode == 1 and "no advisory URL" in proc.stdout


def test_missing_severity_blocks():
    audit = npm_audit({"range": "<9", "via": []})
    proc = run_gate(audit, {"npm": [], "pip": []})
    assert proc.returncode == 1 and "unrecognized severity" in proc.stdout


def test_malformed_audit_blocks():
    proc = run_gate({"nope": 1}, {"npm": [], "pip": []}, eco="npm")
    assert proc.returncode == 1 and "fails closed" in proc.stdout


def test_expired_or_unsigned_exception_does_not_suppress():
    audit = npm_audit(
        {
            "severity": "critical",
            "range": "<9",
            "via": [{"url": "https://github.com/advisories/GHSA-test-1", "title": "x"}],
        }
    )
    expired = {
        "ghsa": "https://github.com/advisories/GHSA-test-1",
        "approved_by": "po",
        "expires": "2000-01-01",
    }
    assert run_gate(audit, {"npm": [expired], "pip": []}).returncode == 1
    unsigned = {"ghsa": "https://github.com/advisories/GHSA-test-1", "expires": "2999-01-01"}
    proc = run_gate(audit, {"npm": [unsigned], "pip": []})
    assert proc.returncode == 1 and "invalid exception" in proc.stdout


def test_valid_signed_exception_suppresses_only_its_advisory():
    audit = npm_audit(
        {
            "severity": "critical",
            "range": "<9",
            "via": [{"url": "https://github.com/advisories/GHSA-test-1", "title": "x"}],
        },
        {
            "severity": "critical",
            "range": "<9",
            "via": [{"url": "https://github.com/advisories/GHSA-other-2", "title": "y"}],
        },
    )
    good = {
        "ghsa": "https://github.com/advisories/GHSA-test-1",
        "approved_by": "po+security",
        "expires": "2999-01-01",
    }
    proc = run_gate(audit, {"npm": [good], "pip": []})
    assert proc.returncode == 1 and "GHSA-other-2" in proc.stdout and "GHSA-test-1" not in proc.stdout


def test_below_threshold_ignored_and_pip_blocks_unexempt():
    audit = npm_audit({"severity": "moderate", "range": "<9", "via": []})
    assert run_gate(audit, {"npm": [], "pip": []}).returncode == 0
    pip_audit = [{"name": "p", "version": "1.0", "vulns": [{"id": "PYSEC-1", "fix_versions": ["2.0"]}]}]
    assert run_gate(pip_audit, {"npm": [], "pip": []}).returncode == 1

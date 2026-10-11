"""Security gate: fail on non-exempt findings above threshold. No success masking.

Usage:
  python security_gate.py --ecosystem npm --audit audit.json --exceptions ../security-exceptions.json
  python security_gate.py --ecosystem pip --audit pip-audit.json --exceptions ../security-exceptions.json

Fail-closed rules:
- Exit 0: no non-exempt findings at/above threshold.
- Exit 1: blocking findings, malformed/missing audit data, unrecognized severe
  findings, or invalid exception entries (missing id/url, approver, or expiry).
- An exception suppresses ONLY its matching advisory id/URL while unexpired and
  signed (approved_by + expires required). Scanner output that cannot be parsed
  never passes: scan failure itself always fails.
npm threshold: high + critical. pip threshold: any reported vulnerability.
"""

import argparse
import datetime
import json

SEVERITY_RANK = {"low": 0, "moderate": 1, "high": 2, "critical": 3}


class GateError(Exception):
    """Malformed input or invalid exception: always fails closed."""


def _today() -> str:
    return datetime.date.today().isoformat()


def _valid_exception(entry: object, key: str) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get(key), str)
        and bool(entry[key])
        and isinstance(entry.get("approved_by"), str)
        and bool(entry["approved_by"])
        and isinstance(entry.get("expires"), str)
        and bool(entry["expires"])
    )


def _load_exceptions(doc: object, ecosystem: str, key: str) -> set[str]:
    if not isinstance(doc, dict) or not isinstance(doc.get(ecosystem), list):
        raise GateError(f"exceptions file must contain a '{ecosystem}' list")
    allowed = set()
    for entry in doc[ecosystem]:
        if not _valid_exception(entry, key):
            raise GateError(
                f"invalid exception entry (needs {key}+approved_by+expires): {entry!r}"
            )
        if entry["expires"] >= _today():
            allowed.add(entry[key])
    return allowed


def check_npm(audit: object, exceptions: set[str]) -> list[str]:
    if not isinstance(audit, dict) or not isinstance(
        audit.get("vulnerabilities"), dict
    ):
        raise GateError(
            "npm audit JSON missing 'vulnerabilities' mapping (scan failure fails closed)"
        )
    blocking = []
    for name, item in audit["vulnerabilities"].items():
        if not isinstance(item, dict):
            raise GateError(
                f"malformed npm finding for {name!r} (scan failure fails closed)"
            )
        severity = item.get("severity")
        if severity not in SEVERITY_RANK:
            raise GateError(
                f"unrecognized severity {severity!r} for {name!r} (fails closed)"
            )
        if SEVERITY_RANK[severity] < SEVERITY_RANK["high"]:
            continue
        via = item.get("via", [])
        if not isinstance(via, list):
            raise GateError(f"malformed 'via' for {name!r} (fails closed)")
        urls = [v.get("url", "") for v in via if isinstance(v, dict)]
        if not urls:
            blocking.append(
                f"{name} [{severity}] range={item.get('range')}: no advisory URL (fails closed)"
            )
            continue
        unexempt = [u for u in urls if u not in exceptions]
        if unexempt:
            blocking.append(
                f"{name} [{severity}] range={item.get('range')} unexempt={unexempt}"
            )
    return blocking


def check_pip(audit: object, exceptions: set[str]) -> list[str]:
    rows = (
        audit
        if isinstance(audit, list)
        else audit.get("dependencies", [])
        if isinstance(audit, dict)
        else None
    )
    if rows is None or not isinstance(rows, list):
        raise GateError(
            "pip-audit JSON missing dependency list (scan failure fails closed)"
        )
    blocking = []
    for dep in rows:
        if not isinstance(dep, dict):
            raise GateError(f"malformed pip finding {dep!r} (fails closed)")
        for vuln in dep.get("vulns", []):
            if not isinstance(vuln, dict) or not vuln.get("id"):
                raise GateError(f"unrecognized pip finding {vuln!r} (fails closed)")
            vid = vuln["id"]
            if vid not in exceptions:
                blocking.append(
                    f"{dep.get('name')} {dep.get('version')} {vid} fix={vuln.get('fix_versions')}"
                )
    return blocking


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecosystem", required=True, choices=["npm", "pip"])
    parser.add_argument("--audit", required=True)
    parser.add_argument("--exceptions", required=True)
    args = parser.parse_args()
    try:
        with open(args.audit, encoding="utf-8-sig") as fh:
            audit = json.load(fh)
        with open(args.exceptions, encoding="utf-8-sig") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read audit/exceptions input (scan failure fails closed): {exc}")
        return 1
    key = "ghsa" if args.ecosystem == "npm" else "id"
    try:
        allowed = _load_exceptions(doc, args.ecosystem, key)
        check = check_npm if args.ecosystem == "npm" else check_pip
        blocking = check(audit, allowed)
    except GateError as exc:
        print(f"gate input invalid (fails closed): {exc}")
        return 1
    if blocking:
        print("BLOCKING security findings (no valid exception):")
        for line in blocking:
            print(" -", line)
        print(
            "Remediate (preferred: upgrade) or record a PO+Security-approved expiring exception."
        )
        return 1
    print(
        f"security gate passed ({args.ecosystem}): no non-exempt findings above threshold."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

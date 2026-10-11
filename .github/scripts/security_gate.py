"""Security gate: fail on non-exempt findings above threshold. No success masking.

Usage:
  python security_gate.py --ecosystem npm --audit audit.json --exceptions ../security-exceptions.json
  python security_gate.py --ecosystem pip --audit pip-audit.json --exceptions ../security-exceptions.json

Exit 0: no non-exempt findings at/above threshold. Exit 1: blocking findings listed.
npm threshold: high + critical. pip threshold: any reported vulnerability.
Exceptions match by GHSA URL (npm) or PYSEC id (pip) and must be unexpired.
"""

import argparse
import datetime
import json

SEVERITY_RANK = {"low": 0, "moderate": 1, "high": 2, "critical": 3}


def _expired(entry: dict, today: str) -> bool:
    return bool(entry.get("expires")) and entry["expires"] < today


def check_npm(audit: dict, exceptions: list, today: str) -> list[str]:
    allowed = {e["ghsa"] for e in exceptions if not _expired(e, today)}
    blocking = []
    for name, item in audit.get("vulnerabilities", {}).items():
        if not isinstance(item, dict):
            continue
        if SEVERITY_RANK.get(item.get("severity", ""), 0) < SEVERITY_RANK["high"]:
            continue
        urls = [v.get("url", "") for v in item.get("via", []) if isinstance(v, dict)]
        unexempt = [u for u in urls if u not in allowed]
        if unexempt:
            blocking.append(
                f"{name} [{item.get('severity')}] range={item.get('range')} unexempt={unexempt}"
            )
    return blocking


def check_pip(audit: list | dict, exceptions: list, today: str) -> list[str]:
    allowed = {e["id"] for e in exceptions if not _expired(e, today)}
    rows = audit if isinstance(audit, list) else audit.get("dependencies", [])
    blocking = []
    for dep in rows:
        for vuln in dep.get("vulns", []):
            vid = vuln.get("id", "")
            if vid not in allowed:
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
    with open(args.audit, encoding="utf-8-sig") as fh:
        audit = json.load(fh)
    with open(args.exceptions, encoding="utf-8-sig") as fh:
        entries = json.load(fh).get(args.ecosystem, [])
    today = datetime.date.today().isoformat()
    blocking = (
        check_npm(audit, entries, today)
        if args.ecosystem == "npm"
        else check_pip(audit, entries, today)
    )
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

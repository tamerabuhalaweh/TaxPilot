"""Versioned SQL migration runner (stdlib + psycopg only).

- Applies `db/migrations/versions/*.sql` in lexicographic order, one transaction each.
- R4 transaction contract (verified by tests, not merely documented): EACH
  version file applies atomically — its statements plus its ledger INSERT commit
  together, or roll back together leaving no trace. There is deliberately NO
  cross-version transaction: a broken later migration aborts its own version
  only, while earlier versions in the same run stay committed; the fixed rerun
  then applies exactly the remainder (ledger-gated, never double-applied).
- Records applied versions in schema_migrations; re-runs are no-ops (idempotent).
- Rejects badly named files, duplicate version identifiers, and records nothing for
  failed migrations (the failed statement rolls back; the version stays unapplied).
- Single-migrator serialization: a session-level PostgreSQL advisory lock is held
  for the whole run, so concurrent runners serialize across discovery, checksum
  verification, and application (an xact-scoped lock would release at the first
  COMMIT and is deliberately NOT used).
- Tamper evidence: every migration file must be listed with its sha256 in the
  sibling CHECKSUMS manifest; files are hash-verified before apply, and applied
  rows are re-verified against current files on every run (mismatch aborts).
  Legacy rows without a recorded hash are backfilled from the manifest once.
- Connection failures propagate to the caller (loud, never swallowed).
- Usage: `python db/migrate.py --database-url postgresql+psycopg://...` or DATABASE_URL.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

VERSIONS = Path(__file__).parent / "migrations" / "versions"
CHECKSUMS = VERSIONS / "CHECKSUMS"
# Single-migrator lock key. Session-level (held to disconnect), NOT xact-scoped:
# pg_advisory_xact_lock would release at the first COMMIT and leave the rest of
# the run unserialized.
ADVISORY_LOCK_SQL = (
    "SELECT pg_advisory_lock(hashtext('taxpilot-schema-migrations')::bigint)"
)


def _to_libpq(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    return url


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover(versions_dir: Path = VERSIONS) -> list[Path]:
    """Return migration files in apply order; reject bad names and duplicate versions."""
    files = sorted(versions_dir.glob("*.sql"), key=lambda p: p.name)
    seen: dict[str, str] = {}
    for path in files:
        match = re.fullmatch(r"(\d{4})_.+\.sql", path.name)
        if not match:
            raise ValueError(f"bad migration name (want NNNN_name.sql): {path.name}")
        version = match.group(1)
        if version in seen:
            raise ValueError(
                f"duplicate migration version {version}: {seen[version]} and {path.name}"
            )
        seen[version] = path.name
    return files


def load_checksums(versions_dir: Path = VERSIONS) -> dict[str, str]:
    """Read the CHECKSUMS manifest (version -> sha256). Missing manifest or
    entries fail loudly: every migration file must be checksummed."""
    manifest = versions_dir / "CHECKSUMS"
    if not manifest.exists():
        raise ValueError(f"CHECKSUMS manifest missing in {versions_dir}")
    entries: dict[str, str] = {}
    for lineno, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if (
            len(parts) != 3
            or not re.fullmatch(r"\d{4}", parts[0])
            or not re.fullmatch(r"[0-9a-f]{64}", parts[1])
        ):
            raise ValueError(f"malformed CHECKSUMS line {lineno}: {line!r}")
        entries[parts[0]] = parts[1]
    return entries


def migrate(
    database_url: str, versions_dir: Path = VERSIONS, connect_timeout: int = 10
) -> list[str]:
    import psycopg

    files = discover(versions_dir)
    checksums = load_checksums(versions_dir)
    for path in files:
        version = path.stem.split("_")[0]
        if version not in checksums:
            raise ValueError(f"migration {path.name} has no CHECKSUMS entry")
        if _sha256(path) != checksums[version]:
            raise ValueError(
                f"migration {path.name} checksum mismatch (file changed after approval?)"
            )
    applied: list[str] = []
    with psycopg.connect(
        _to_libpq(database_url), connect_timeout=connect_timeout
    ) as conn:
        conn.execute(ADVISORY_LOCK_SQL)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            conn.execute(
                "ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS sha256 TEXT"
            )
            conn.commit()  # bootstrap survives even if a later migration statement fails
            rows = {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT version, sha256 FROM schema_migrations"
                ).fetchall()
            }
            for path in files:
                version = path.stem.split("_")[0]
                recorded = rows.get(version, "ABSENT")
                if (
                    recorded != "ABSENT"
                    and recorded is not None
                    and recorded != checksums[version]
                ):
                    raise ValueError(
                        f"applied migration {version} differs from current file "
                        "(tampered or replaced after apply?)"
                    )
                if recorded != "ABSENT":
                    if recorded is None:
                        # Legacy row predating hash recording: backfill once from manifest.
                        conn.execute(
                            "UPDATE schema_migrations SET sha256 = %s WHERE version = %s",
                            (checksums[version], version),
                        )
                        conn.commit()
                    continue
                sql = path.read_text(encoding="utf-8")
                # R4 (PR #41 review): genuine per-version atomicity. The file's
                # statements plus its ledger INSERT commit TOGETHER; on failure
                # the version rolls back alone while earlier versions in this
                # run stay committed. (A `with conn.transaction()` savepoint
                # block here was insufficient: savepoint release is not
                # durable, so a later failure rolled back earlier versions on
                # connection close. Explicit commit per version is the contract
                # the tests verify.)
                try:
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations(version, sha256) VALUES (%s, %s)",
                        (version, checksums[version]),
                    )
                except Exception:
                    conn.rollback()
                    raise
                else:
                    conn.commit()
                applied.append(version)
        finally:
            try:
                conn.execute(
                    "SELECT pg_advisory_unlock(hashtext('taxpilot-schema-migrations')::bigint)"
                )
            except Exception:
                pass  # connection already gone; never mask the real outcome
    return applied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    import os

    url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not url:
        print("DATABASE_URL or --database-url is required", file=sys.stderr)
        return 2
    done = migrate(url)
    print(f"applied: {done if done else 'nothing pending'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

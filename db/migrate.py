"""Versioned SQL migration runner (stdlib + psycopg only).

- Applies `db/migrations/versions/*.sql` in lexicographic order, one transaction each.
- Records applied versions in schema_migrations; re-runs are no-ops (idempotent).
- Rejects badly named files, duplicate version identifiers, and records nothing for
  failed migrations (the failed statement rolls back; the version stays unapplied).
- Connection failures propagate to the caller (loud, never swallowed).
- Usage: `python db/migrate.py --database-url postgresql+psycopg://...` or DATABASE_URL.
"""

import argparse
import re
import sys
from pathlib import Path

VERSIONS = Path(__file__).parent / "migrations" / "versions"


def _to_libpq(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return "postgresql://" + url[len("postgresql+psycopg://") :]
    return url


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


def migrate(
    database_url: str, versions_dir: Path = VERSIONS, connect_timeout: int = 10
) -> list[str]:
    import psycopg

    files = discover(versions_dir)
    applied: list[str] = []
    with psycopg.connect(
        _to_libpq(database_url), connect_timeout=connect_timeout
    ) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {
            r[0]
            for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for path in files:
            version = path.stem.split("_")[0]
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)", (version,)
                )
            applied.append(version)
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

"""Versioned SQL migration runner (stdlib + psycopg only).

- Applies `db/migrations/versions/*.sql` in lexicographic order inside one transaction each.
- Records applied versions in schema_migrations; re-runs are no-ops (idempotent).
- Usage: `python db/migrate.py --database-url postgresql+psycopg://...` (psycopg scheme
  is translated to libpq `dbname=` form) or set DATABASE_URL.
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


def pending_versions(applied: set[str]) -> list[Path]:
    files = sorted(VERSIONS.glob("*.sql"))
    return [f for f in files if f.stem.split("_")[0] not in applied]


def migrate(database_url: str) -> list[str]:
    import psycopg

    applied: list[str] = []
    with psycopg.connect(_to_libpq(database_url)) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
        done = {r[0] for r in rows}
        for path in sorted(VERSIONS.glob("*.sql")):
            version = path.stem.split("_")[0]
            if not re.fullmatch(r"\d{4}", version):
                raise ValueError(
                    f"bad migration name (want NNNN_name.sql): {path.name}"
                )
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

"""Migration validation.

Service-gating contract: when REQUIRE_SERVICES=1 (CI integration job), an unreachable
database FAILS these tests. Locally, service-dependent tests skip with an explicit
reason (documented optional local mode) instead of silently passing.

TEST-SAFETY-01: the tests below that destroy state (dropping the ledger,
applying migrations) run against the DEDICATED DISPOSABLE database from
TAXPILOT_DESTRUCTIVE_DATABASE_URL via the dbsafety guard — never DATABASE_URL.
Pure file/manifest tests and the unreachable-host test need no database.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root
sys.path.insert(0, os.path.dirname(__file__))  # sibling dbsafety module

import dbsafety

psycopg = pytest.importorskip("psycopg")

from db.migrate import _to_libpq, discover, migrate  # noqa: E402

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"


def _db_or_skip() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        if REQUIRE_SERVICES:
            pytest.fail("DATABASE_URL is required when REQUIRE_SERVICES=1")
        pytest.skip("DATABASE_URL not set (documented optional local mode)")
    try:
        with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"postgres unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"postgres unreachable (documented optional local mode): {exc}")
    return url


_DURL: str | None = None


def _destructive_or_skip() -> str:
    """Resolve + verify the disposable destructive target (TEST-SAFETY-01).

    Guard failure skips locally but fails hard with REQUIRE_SERVICES=1.
    """
    _db_or_skip()
    global _DURL
    if _DURL is None:
        candidate = dbsafety.destructive_url()
        try:
            dbsafety.require_destructive_db(candidate)
        except ValueError as exc:
            if REQUIRE_SERVICES:
                pytest.fail(f"destructive-test safeguard refused target: {exc}")
            pytest.skip(f"destructive-test safeguard refused target: {exc}")
        _DURL = candidate
    return _DURL


def test_migration_discovery_exact_and_ordered():
    names = [p.name for p in discover()]
    assert names == [
        "0001_schema_migrations.sql",
        "0002_auth_tenancy_clients.sql",
        "0003_session_csrf.sql",
        "0004_jurisdiction_foundation.sql",
        "0005_document_intakes.sql",
    ]


def test_discover_rejects_bad_names(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "oops.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(ValueError, match="bad migration name"):
        discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "0007_one.sql").write_text("SELECT 1", encoding="utf-8")
    (tmp_path / "0007_two.sql").write_text("SELECT 2", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate migration version"):
        discover(tmp_path)


def test_first_migration_applies_and_rerun_is_noop():
    # TEST-SAFETY-01: drops the ledger, so it runs on the disposable database.
    url = _destructive_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
    assert migrate(url) == ["0001", "0002", "0003", "0004", "0005"]
    assert migrate(url) == []


def _sha_of(path):  # type: ignore[no-untyped-def]
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_failed_sql_records_nothing_and_leaves_clean_state(tmp_path):  # type: ignore[no-untyped-def]
    # TEST-SAFETY-01: exercises the real runner (ledger writes), so it runs
    # on the disposable database.
    url = _destructive_or_skip()
    (tmp_path / "0099_broken.sql").write_text(
        "THIS IS NOT VALID SQL;", encoding="utf-8"
    )
    (tmp_path / "CHECKSUMS").write_text(
        "0099  " + _sha_of(tmp_path / "0099_broken.sql") + "  0099_broken.sql\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        migrate(url, versions_dir=tmp_path)
    # Restore via the real runner, then assert the broken version left no trace.
    migrate(url)
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    assert "0099" not in {r[0] for r in rows}
    # Restore the real ledger for later tests in this session (whatever is pending).
    migrate(url)


def test_unreachable_database_raises():
    with pytest.raises(Exception):
        migrate("postgresql://u:p@127.0.0.1:9/db")

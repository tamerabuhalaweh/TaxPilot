"""Migration validation.

Service-gating contract: when REQUIRE_SERVICES=1 (CI integration job), an unreachable
database FAILS these tests. Locally, service-dependent tests skip with an explicit
reason (documented optional mode) instead of silently passing.
"""

import os

import pytest

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


def test_migration_discovery_exact_and_ordered():
    names = [p.name for p in discover()]
    assert names == [
        "0001_schema_migrations.sql",
        "0002_auth_tenancy_clients.sql",
        "0003_session_csrf.sql",
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
    url = _db_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
    assert migrate(url) == ["0001", "0002", "0003"]
    assert migrate(url) == []


def test_failed_sql_records_nothing_and_leaves_clean_state(tmp_path):  # type: ignore[no-untyped-def]
    url = _db_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
    (tmp_path / "0002_broken.sql").write_text(
        "THIS IS NOT VALID SQL;", encoding="utf-8"
    )
    with pytest.raises(Exception):
        migrate(url, versions_dir=tmp_path)
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    assert "0002" not in {r[0] for r in rows}
    # Restore the real ledger for later tests in this session.
    assert migrate(url) == ["0001", "0002", "0003"]


def test_unreachable_database_raises():
    with pytest.raises(Exception):
        migrate("postgresql://u:p@127.0.0.1:9/db")

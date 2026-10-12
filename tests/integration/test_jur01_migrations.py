"""PR-A JUR-01 foundation tests: migration 0004, constraints, immutability, isolation.

Service-gating: REQUIRE_SERVICES=1 (CI) turns unreachable services into FAILURE.
Destructive setup (dropping jur tables/ledger) always restores via migrate() in a
finally block so later tests in the session keep a working schema.
"""

import os
import threading
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

from db.migrate import _to_libpq, migrate  # noqa: E402

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
)

JUR_TABLES = [
    "tax_contexts",
    "tax_registrations",
    "tax_obligation_profiles",
    "legal_entities",
    "jurisdiction_catalog",
]


def _db_or_skip() -> str:
    if not URL:
        if REQUIRE_SERVICES:
            pytest.fail("DATABASE_URL is required when REQUIRE_SERVICES=1")
        pytest.skip("DATABASE_URL not set (documented optional local mode)")
    try:
        with psycopg.connect(_to_libpq(URL), connect_timeout=5) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"postgres unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"postgres unreachable (documented optional local mode): {exc}")
    return URL


def _exec(sql: str, params: tuple = ()) -> list:
    with psycopg.connect(_to_libpq(URL), connect_timeout=5) as conn:
        rows = (
            conn.execute(sql, params).fetchall()
            if sql.strip().upper().startswith("SELECT")
            else []
        )
        if not sql.strip().upper().startswith("SELECT"):
            conn.execute(sql, params)
            conn.commit()
            return []
        return rows


def _count(table: str) -> int:
    return _exec(f"SELECT COUNT(*) FROM {table}")[0][0]


def _reset_jur() -> None:
    # Full unwind of 0004 (tables + clients candidate key + ledger row) so the
    # next migrate() rebuilds current DDL from scratch — never a stale mix of
    # old tables with a fresh ledger row.
    with psycopg.connect(_to_libpq(URL), connect_timeout=10) as conn:
        for table in JUR_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.execute(
            "ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_tenant_id_key CASCADE"
        )
        conn.execute("DELETE FROM schema_migrations WHERE version = '0004'")
        conn.commit()


@pytest.fixture()
def clean_jur():  # type: ignore[no-untyped-def]
    _db_or_skip()
    _reset_jur()
    try:
        yield
    finally:
        _reset_jur()
        migrate(URL)


def _tenant_and_client(conn, tag: str = "t"):  # type: ignore[no-untyped-def]
    tid = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    conn.execute("INSERT INTO tenants (id, name) VALUES (%s, %s)", (tid, f"jur-{tag}"))
    conn.execute(
        "INSERT INTO clients (id, tenant_id, name) VALUES (%s, %s, %s)",
        (cid, tid, f"c-{tag}"),
    )
    return tid, cid


def test_1_fresh_install_applies_all_versions_with_seeds():
    url = _db_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=10) as conn:
        for table in JUR_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.execute("DELETE FROM schema_migrations WHERE version = '0004'")
        conn.commit()
    try:
        applied = migrate(url)
        assert "0004" in applied
        rows = _exec(
            "SELECT code, availability FROM jurisdiction_catalog ORDER BY code"
        )
        assert (
            ("AE", "PLANNED") in rows
            and ("JO", "ACTIVE") in rows
            and ("SA", "PLANNED") in rows
        )
        caps = _exec("SELECT capabilities FROM jurisdiction_catalog WHERE code = 'JO'")[
            0
        ][0]
        assert (
            caps["rules"] == [] and caps["tax_types"] == []
        )  # ACTIVE catalog, zero executables
    finally:
        migrate(url)


def test_2_upgrade_keeps_existing_sprint1_data(clean_jur):
    url = _db_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=10) as conn:
        tid, cid = _tenant_and_client(conn, "keep")
        conn.commit()
    assert migrate(url) == ["0004"]
    assert _count("clients") >= 1
    assert _exec("SELECT COUNT(*) FROM clients WHERE id = %s", (cid,))[0][0] == 1


def test_3_no_fabricated_backfill(clean_jur):
    url = _db_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=10) as conn:
        before = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        _tenant_and_client(conn, "plain")
        conn.commit()
    migrate(url)
    with psycopg.connect(_to_libpq(url), connect_timeout=10) as conn:
        after = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        assert after == before + 1  # only our own row added
        assert _count("legal_entities") == 0
        assert _count("tax_obligation_profiles") == 0
        assert _count("tax_registrations") == 0
        assert _count("tax_contexts") == 0


def _entity(conn, tid, cid, country="JO", name=None):  # type: ignore[no-untyped-def]
    eid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO legal_entities (id, tenant_id, client_id, legal_name,"
        " incorporation_country_code, base_currency) VALUES (%s,%s,%s,%s,%s,%s)",
        (eid, tid, cid, name or f"e-{eid[:6]}", country, "JOD"),
    )
    return eid


def test_4_cross_tenant_references_rejected(clean_jur):
    url = _db_or_skip()
    migrate(url)
    import psycopg as _pg

    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        ta, ca = _tenant_and_client(conn, "A")
        tb, cb = _tenant_and_client(conn, "B")
        ea = _entity(conn, ta, ca)
        conn.commit()
        # Entity of tenant A cannot be attached under tenant B's client.
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO legal_entities (id, tenant_id, client_id, legal_name,"
                    " incorporation_country_code, base_currency) VALUES (%s,%s,%s,%s,%s,%s)",
                    (str(uuid.uuid4()), tb, cb, "x", "JO", "JOD"),
                )
                conn.execute(
                    "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
                    " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
                    " period_end) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,'JO','ACCOUNTING_ONLY',"
                    " '2026-01-01','2026-12-31')",
                    (str(uuid.uuid4()), tb, cb, ea),
                )
        conn.rollback()


def test_5_same_tenant_different_client_rejected(clean_jur):
    url = _db_or_skip()
    migrate(url)
    import psycopg as _pg

    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        tid = str(uuid.uuid4())
        conn.execute("INSERT INTO tenants (id, name) VALUES (%s, 'multi')", (tid,))
        c1, c2 = str(uuid.uuid4()), str(uuid.uuid4())
        conn.execute(
            "INSERT INTO clients (id, tenant_id, name) VALUES (%s,%s,'c1'),(%s,%s,'c2')",
            (c1, tid, c2, tid),
        )
        e1 = _entity(conn, tid, c1)
        conn.commit()
        # Context for client c2 referencing c1's entity: same tenant, wrong client.
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
                    " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
                    " period_end) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,'JO','ACCOUNTING_ONLY',"
                    " '2026-01-01','2026-12-31')",
                    (str(uuid.uuid4()), tid, c2, e1),
                )
        conn.rollback()
        # Obligation bound to c1 cannot back a context scoped to c2: same tenant,
        # wrong client — rejected by the composite obligation FK.
        oid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tax_obligation_profiles (id, tenant_id, client_id, legal_entity_id,"
            " jurisdiction_code, tax_type_code, valid_from) VALUES (%s,%s,%s,%s,'JO','VAT','2026-01-01')",
            (oid, tid, c1, e1),
        )
        conn.commit()
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
                    " subject_entity_id, obligation_profile_id, jurisdiction_code, tax_type_code,"
                    " period_start, period_end) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,%s,'JO','VAT',"
                    " '2026-01-01','2026-12-31')",
                    (str(uuid.uuid4()), tid, c2, e1, oid),
                )
        conn.rollback()


def test_6_unique_and_composite_keys(clean_jur):
    url = _db_or_skip()
    migrate(url)
    import psycopg as _pg

    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        tid, cid = _tenant_and_client(conn, "keys")
        e1 = _entity(conn, tid, cid, name="dup")
        conn.commit()
        # Duplicate active entity name in same client+tenant fails.
        with pytest.raises(Exception):
            with conn.transaction():
                _entity(conn, tid, cid, name="dup")
        conn.rollback()
        # Same context hash twice in one tenant fails; across tenants it is allowed.
        h = "sha256:" + "a" * 64
        for _ in range(1):
            conn.execute(
                "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
                " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
                " period_end, context_hash) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,'JO',"
                " 'ACCOUNTING_ONLY','2026-01-01','2026-12-31',%s)",
                (str(uuid.uuid4()), tid, cid, e1, h),
            )
        conn.commit()
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
                    " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
                    " period_end, context_hash) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,'JO',"
                    " 'ACCOUNTING_ONLY','2026-01-01','2026-12-31',%s)",
                    (str(uuid.uuid4()), tid, cid, e1, h),
                )
        conn.rollback()
        tid2, cid2 = _tenant_and_client(conn, "keys2")
        e2 = _entity(conn, tid2, cid2)
        conn.execute(
            "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
            " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
            " period_end, context_hash) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,'JO',"
            " 'ACCOUNTING_ONLY','2026-01-01','2026-12-31',%s)",
            (str(uuid.uuid4()), tid2, cid2, e2, h),
        )
        conn.commit()


def test_7_confirmed_context_freeze(clean_jur):
    url = _db_or_skip()
    migrate(url)
    import psycopg as _pg

    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        tid, cid = _tenant_and_client(conn, "freeze")
        eid = _entity(conn, tid, cid)
        xid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
            " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
            " period_end, confirmation_status) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,'JO',"
            " 'ACCOUNTING_ONLY','2026-01-01','2026-12-31','DRAFT')",
            (xid, tid, cid, eid),
        )
        conn.commit()
        # Draft rows remain editable.
        conn.execute(
            "UPDATE tax_contexts SET period_end = '2026-09-30' WHERE id = %s", (xid,)
        )
        conn.commit()
        conn.execute(
            "UPDATE tax_contexts SET confirmation_status = 'CONFIRMED' WHERE id = %s",
            (xid,),
        )
        conn.commit()
        # Frozen columns reject in-place mutation...
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET period_end = '2026-06-30' WHERE id = %s",
                    (xid,),
                )
        conn.rollback()
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET confirmation_status = 'DRAFT' WHERE id = %s",
                    (xid,),
                )
        conn.rollback()
        # ...while new revisions insert cleanly.
        conn.execute(
            "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
            " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
            " period_end, context_revision, confirmation_status) VALUES (%s,%s,%s,"
            " 'LEGAL_ENTITY',%s,'JO','ACCOUNTING_ONLY','2026-01-01','2026-06-30',2,'CONFIRMED')",
            (str(uuid.uuid4()), tid, cid, eid),
        )
        conn.commit()


def test_8_crypto_column_constraints(clean_jur):
    url = _db_or_skip()
    migrate(url)
    import psycopg as _pg

    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        tid, cid = _tenant_and_client(conn, "crypto")
        eid = _entity(conn, tid, cid)
        oid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tax_obligation_profiles (id, tenant_id, client_id, legal_entity_id,"
            " jurisdiction_code, tax_type_code, valid_from) VALUES (%s,%s,%s,%s,'JO','VAT','2026-01-01')",
            (oid, tid, cid, eid),
        )
        # Collection-disabled shape (all NULL) is allowed...
        conn.execute(
            "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
            " authority_code, registration_kind) VALUES (%s,%s,%s,'JO-ISTD','VAT')",
            (str(uuid.uuid4()), tid, oid),
        )
        conn.commit()  # anchor valid rows before the negative sub-transactions below
        # ...ciphertext without nonce/key fails...
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
                    " authority_code, registration_kind, number_ciphertext)"
                    " VALUES (%s,%s,%s,'JO-ISTD','VAT',%s)",
                    (str(uuid.uuid4()), tid, oid, b"\x01\x02"),
                )
        conn.rollback()
        # ...wrong-length nonce fails...
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
                    " authority_code, registration_kind, number_ciphertext, number_nonce, key_id)"
                    " VALUES (%s,%s,%s,'JO-ISTD','VAT',%s,%s,'k1')",
                    (str(uuid.uuid4()), tid, oid, b"\x01\x02", b"\x01\x02"),
                )
        conn.rollback()
        # ...valid 12-byte nonce + key passes, last4 is separate plaintext.
        conn.execute(
            "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
            " authority_code, registration_kind, number_ciphertext, number_nonce, key_id, number_last4)"
            " VALUES (%s,%s,%s,'JO-ISTD','VAT',%s,%s,'k1','1234')",
            (str(uuid.uuid4()), tid, oid, b"\x00" * 32, b"\x01" * 12),
        )
        conn.commit()
        cols = _exec(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'tax_registrations' AND column_name IN "
            "('number_ciphertext','number_nonce')"
        )
        assert sorted(cols) == [
            ("number_ciphertext", "bytea"),
            ("number_nonce", "bytea"),
        ]


def test_10_concurrent_migrators_serialize(clean_jur):
    url = _db_or_skip()
    migrate(url)
    results: list = []
    errors: list = []

    def run() -> None:
        try:
            results.append(migrate(url))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not errors, errors
    assert (
        _exec("SELECT COUNT(*) FROM schema_migrations WHERE version = '0004'")[0][0]
        == 1
    )


def test_11_failure_rollback_and_rerun(tmp_path):  # type: ignore[no-untyped-def]
    url = _db_or_skip()
    (tmp_path / "0011_broken.sql").write_text(
        "THIS IS NOT VALID SQL;", encoding="utf-8"
    )
    import hashlib as _hashlib

    digest = _hashlib.sha256((tmp_path / "0011_broken.sql").read_bytes()).hexdigest()
    (tmp_path / "CHECKSUMS").write_text(
        f"0011  {digest}  0011_broken.sql\n", encoding="utf-8"
    )
    with pytest.raises(Exception):
        migrate(url, versions_dir=tmp_path)
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    assert "0011" not in {r[0] for r in rows}
    (tmp_path / "0011_broken.sql").write_text(
        "CREATE TABLE IF NOT EXISTS probe_tmp (id INTEGER PRIMARY KEY);",
        encoding="utf-8",
    )
    digest = _hashlib.sha256((tmp_path / "0011_broken.sql").read_bytes()).hexdigest()
    (tmp_path / "CHECKSUMS").write_text(
        f"0011  {digest}  0011_broken.sql\n", encoding="utf-8"
    )
    assert migrate(url, versions_dir=tmp_path) == ["0011"]
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        conn.execute("DROP TABLE IF EXISTS probe_tmp")
        conn.execute("DELETE FROM schema_migrations WHERE version = '0011'")
        conn.commit()


def test_12_schema_matches_definitions():
    url = _db_or_skip()
    migrate(url)
    from sqlalchemy import create_engine

    from app.store import assert_schema_matches

    engine = create_engine(
        _to_libpq(url).replace("postgresql://", "postgresql+psycopg://")
    )
    try:
        assert_schema_matches(engine)
    finally:
        engine.dispose()

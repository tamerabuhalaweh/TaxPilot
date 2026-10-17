"""PR-A JUR-01 foundation tests: migration 0004, constraints, immutability, isolation.

Service-gating: REQUIRE_SERVICES=1 (CI) turns unreachable services into FAILURE.
Destructive setup (dropping jur tables/ledger) always restores via migrate() in a
finally block so later tests in the session keep a working schema.

TEST-SAFETY-01: every test in this module runs against the DEDICATED
DISPOSABLE database from TAXPILOT_DESTRUCTIVE_DATABASE_URL, guarded by
dbsafety.require_destructive_db (explicit opt-in + designated *_test name +
local/CI host). These tests NEVER touch DATABASE_URL, so they cannot destroy
staging, production, or a shared development database.
"""

import os
import sys
import threading
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root
sys.path.insert(0, os.path.dirname(__file__))  # sibling dbsafety module

import dbsafety

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

_DURL: str | None = None


def _destructive_or_skip() -> str:
    """Service-gate, then resolve + verify the disposable destructive target.

    The guard failure is a SKIP in optional local mode but a hard FAILURE with
    REQUIRE_SERVICES=1 — CI must prove the safety wiring on every run.
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
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=5) as conn:
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
    # R1 (PR #41 review): unwind 0004 tables + ledger row ONLY. The clients
    # candidate key is NEVER dropped here (no CASCADE against it): dropping
    # the jur tables removes the dependent FKs while the key persists, and the
    # next migrate() exercises the verify-only path on the surviving key.
    # TEST-SAFETY-01: runs against the guarded disposable database only.
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=10) as conn:
        for table in JUR_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.execute("DELETE FROM schema_migrations WHERE version = '0004'")
        conn.commit()


@pytest.fixture()
def clean_jur():  # type: ignore[no-untyped-def]
    url = _destructive_or_skip()
    _reset_jur()
    try:
        yield
    finally:
        _reset_jur()
        migrate(url)


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
    # R4: GENUINE fresh installation — the entire schema is destroyed first, so
    # this proves 0001..0004 build a working database from nothing (not merely
    # that 0004 layers onto surviving Sprint 1 tables).
    url = _destructive_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=10) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
    try:
        applied = migrate(url)
        assert applied == ["0001", "0002", "0003", "0004", "0005", "0006", "0007"]
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
        # R4: every applied version's recorded hash matches the approved manifest.
        from db.migrate import load_checksums

        manifest = load_checksums()
        recorded = _exec("SELECT version, sha256 FROM schema_migrations")
        assert {v for v, _ in recorded} == {
            "0001",
            "0002",
            "0003",
            "0004",
            "0005",
            "0006",
            "0007",
        }
        for version, digest in recorded:
            assert manifest[version] == digest, version
    finally:
        migrate(url)


def test_2_upgrade_keeps_existing_sprint1_data(clean_jur):
    url = _destructive_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=10) as conn:
        tid, cid = _tenant_and_client(conn, "keep")
        conn.commit()
    assert migrate(url) == ["0004"]
    assert _count("clients") >= 1
    assert _exec("SELECT COUNT(*) FROM clients WHERE id = %s", (cid,))[0][0] == 1


def test_3_no_fabricated_backfill(clean_jur):
    url = _destructive_or_skip()
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
    url = _destructive_or_skip()
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
    url = _destructive_or_skip()
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
    url = _destructive_or_skip()
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
    url = _destructive_or_skip()
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
        # R2: even a no-op write to a CONFIRMED row is rejected.
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET period_end = period_end WHERE id = %s",
                    (xid,),
                )
        conn.rollback()
        # R2: identity and attribution are frozen from birth, even pre-confirmation.
        yid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
            " subject_entity_id, jurisdiction_code, tax_type_code, period_start,"
            " period_end, confirmation_status) VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,'JO',"
            " 'ACCOUNTING_ONLY','2026-01-01','2026-12-31','DRAFT')",
            (yid, tid, cid, eid),
        )
        conn.commit()
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET client_id = %s WHERE id = %s",
                    (tid, yid),
                )
        conn.rollback()
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET confirmed_by = %s WHERE id = %s",
                    (tid, yid),
                )
        conn.rollback()
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET created_at = now() WHERE id = %s",
                    (yid,),
                )
        conn.rollback()
        # R2: the privileged confirmation transition carries actor/time only —
        # smuggling a content change alongside confirmation is rejected.
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET confirmation_status = 'CONFIRMED',"
                    " confirmed_by = %s, confirmed_at = now(), period_end = '2026-06-30'"
                    " WHERE id = %s",
                    (tid, yid),
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
    url = _destructive_or_skip()
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
        # R3: nonce alone (no ciphertext) fails bidirectionally...
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
                    " authority_code, registration_kind, number_nonce)"
                    " VALUES (%s,%s,%s,'JO-ISTD','VAT',%s)",
                    (str(uuid.uuid4()), tid, oid, b"\x01" * 12),
                )
        conn.rollback()
        # R3: ...key metadata alone fails...
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
                    " authority_code, registration_kind, key_id)"
                    " VALUES (%s,%s,%s,'JO-ISTD','VAT','k-orphan')",
                    (str(uuid.uuid4()), tid, oid),
                )
        conn.rollback()
        # R3: ...partial identifier alone fails...
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
                    " authority_code, registration_kind, number_last4)"
                    " VALUES (%s,%s,%s,'JO-ISTD','VAT','1234')",
                    (str(uuid.uuid4()), tid, oid),
                )
        conn.rollback()
        # R3: ...ciphertext without its key id fails...
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
                    " authority_code, registration_kind, number_ciphertext, number_nonce)"
                    " VALUES (%s,%s,%s,'JO-ISTD','VAT',%s,%s)",
                    (str(uuid.uuid4()), tid, oid, b"\x00" * 32, b"\x01" * 12),
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
    url = _destructive_or_skip()
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
    url = _destructive_or_skip()
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
    url = _destructive_or_skip()
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


def _constraint_names(conn) -> set:  # type: ignore[no-untyped-def]
    rows = conn.execute(
        "SELECT c.conname FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid "
        "WHERE t.relname IN ('clients','legal_entities','tax_obligation_profiles',"
        "'tax_registrations','tax_contexts')"
    ).fetchall()
    return {r[0] for r in rows}


def test_13_rerun_without_ledger_row_preserves_key_and_constraints(clean_jur):
    # R1: re-applying 0004 against an existing schema with the ledger entry
    # deliberately missing must VERIFY (never drop) the clients candidate key,
    # leaving tenant isolation, same-client bindings, and every FK intact.
    url = _destructive_or_skip()
    assert migrate(url) == ["0004"]
    import psycopg as _pg

    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        tid, cid = _tenant_and_client(conn, "r1keep")
        eid = _entity(conn, tid, cid)
        conn.commit()
        before = _constraint_names(conn)
        assert "clients_tenant_id_key" in before
        assert "legal_entities_tenant_client_fk" in before
        # Simulate a lost ledger entry: tables + key survive, history does not.
        conn.execute("DELETE FROM schema_migrations WHERE version = '0004'")
        conn.commit()
    assert migrate(url) == ["0004"]
    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        # Nothing was removed or renamed by the rerun.
        assert _constraint_names(conn) == before
        # Tenant isolation still enforced through the surviving key.
        other_tid, _ = _tenant_and_client(conn, "r1other")
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO legal_entities (id, tenant_id, client_id, legal_name,"
                    " incorporation_country_code, base_currency)"
                    " VALUES (%s,%s,%s,'X','JO','JOD')",
                    (str(uuid.uuid4()), other_tid, cid),
                )
        conn.rollback()
        # Same-client binding still enforced.
        with pytest.raises(Exception):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO tax_obligation_profiles (id, tenant_id, client_id,"
                    " legal_entity_id, jurisdiction_code, tax_type_code, valid_from)"
                    " VALUES (%s,%s,%s,%s,'JO','VAT','2026-01-01')",
                    (str(uuid.uuid4()), tid, cid, eid),
                )
                conn.execute(
                    "INSERT INTO tax_contexts (id, tenant_id, client_id, subject_kind,"
                    " subject_entity_id, obligation_profile_id, jurisdiction_code,"
                    " tax_type_code, period_start, period_end, confirmation_status)"
                    " VALUES (%s,%s,%s,'LEGAL_ENTITY',%s,"
                    " (SELECT id FROM tax_obligation_profiles WHERE client_id = %s LIMIT 1),"
                    " 'JO','VAT','2026-01-01','2026-12-31','DRAFT')",
                    (str(uuid.uuid4()), tid, str(uuid.uuid4()), eid, cid),
                )
        conn.rollback()
    # Fail-closed: a conflicting key definition under the same name refuses.
    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        conn.execute(
            "ALTER TABLE clients RENAME CONSTRAINT clients_tenant_id_key TO zz_tmp_key"
        )
        conn.execute(
            "ALTER TABLE clients ADD CONSTRAINT clients_tenant_id_key UNIQUE (id)"
        )
        conn.execute("DELETE FROM schema_migrations WHERE version = '0004'")
        conn.commit()
    try:
        with pytest.raises(Exception, match="unexpected definition"):
            migrate(url)
    finally:
        with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
            conn.execute("ALTER TABLE clients DROP CONSTRAINT clients_tenant_id_key")
            conn.execute(
                "ALTER TABLE clients RENAME CONSTRAINT zz_tmp_key TO clients_tenant_id_key"
            )
            conn.commit()
    assert migrate(url) == ["0004"]


def test_14_concurrent_runners_single_pending_winner(clean_jur):
    # R4: several runners racing to apply a genuinely PENDING 0004 must
    # serialize on the advisory lock — exactly one applies, the rest observe.
    url = _destructive_or_skip()
    assert migrate(url) == ["0004"]
    import psycopg as _pg

    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        for table in JUR_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
        conn.execute("DELETE FROM schema_migrations WHERE version = '0004'")
        conn.commit()
    results: list = []
    errors: list = []

    def run() -> None:
        try:
            results.append(migrate(url))
        except Exception as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=180)
    assert not errors, errors
    assert len(results) == 6
    assert sorted(v for r in results for v in r) == ["0004"]
    assert (
        _exec("SELECT COUNT(*) FROM schema_migrations WHERE version = '0004'")[0][0]
        == 1
    )
    assert _exec("SELECT COUNT(*) FROM jurisdiction_catalog")[0][0] == 3


def test_15_later_failure_keeps_earlier_version_and_reruns_clean(tmp_path):  # type: ignore[no-untyped-def]
    # R4: per-version atomicity — a broken later migration aborts its OWN
    # version only; earlier versions in the same run stay committed, and a
    # fixed rerun applies exactly the remainder.
    url = _destructive_or_skip()
    import hashlib as _hashlib
    import psycopg as _pg

    def _manifest(*names: str) -> None:
        (tmp_path / "CHECKSUMS").write_text(
            "".join(
                f"{n[:4]}  {_hashlib.sha256((tmp_path / n).read_bytes()).hexdigest()}  {n}\n"
                for n in names
            ),
            encoding="utf-8",
        )

    (tmp_path / "0090_good.sql").write_text(
        "CREATE TABLE probe_r4 (id INTEGER PRIMARY KEY);\nINSERT INTO probe_r4 VALUES (1);",
        encoding="utf-8",
    )
    (tmp_path / "0091_broken.sql").write_text(
        "THIS IS NOT VALID SQL;", encoding="utf-8"
    )
    _manifest("0090_good.sql", "0091_broken.sql")
    with pytest.raises(Exception):
        migrate(url, versions_dir=tmp_path)
    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        versions = {
            r[0]
            for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        assert "0090" in versions and "0091" not in versions
        assert conn.execute("SELECT COUNT(*) FROM probe_r4").fetchone()[0] == 1
        conn.commit()
    (tmp_path / "0091_broken.sql").write_text(
        "CREATE TABLE probe_r4b (id INTEGER PRIMARY KEY);", encoding="utf-8"
    )
    _manifest("0090_good.sql", "0091_broken.sql")
    assert migrate(url, versions_dir=tmp_path) == ["0091"]
    with _pg.connect(_to_libpq(url), connect_timeout=10) as conn:
        conn.execute("DROP TABLE IF EXISTS probe_r4")
        conn.execute("DROP TABLE IF EXISTS probe_r4b")
        conn.execute("DELETE FROM schema_migrations WHERE version IN ('0090','0091')")
        conn.commit()

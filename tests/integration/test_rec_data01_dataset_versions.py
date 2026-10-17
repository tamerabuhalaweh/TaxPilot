"""REC-DATA-01 integration: client-scoped dataset-version registry (real PG + API).

Service-gating and harness mirror test_rec03_engagement_execution.py:
REQUIRE_SERVICES=1 (CI) turns unreachable services into FAILURE; all state lands
in the DEDICATED DISPOSABLE database (dbsafety-guarded). Synthetic data and
RFC-reserved example.com identities only.

Boundary under test (issue #59, decisions A + b2):
- registration is default-deny: the authenticated POST refuses 409
  SOURCE_NOT_RELEASED and persists nothing (no fabricated rows);
- registry rows are client-scoped immutable evidence: cross-tenant/cross-client
  bindings are rejected by composite FKs, and UPDATE/DELETE are trigger-refused;
- reads are tenant/client scoped; out-of-scope ids are indistinguishable 404s;
- the two hashes stay distinct (source_content_sha256 vs dataset_fingerprint).
"""

import os
import sys
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root
sys.path.insert(0, os.path.dirname(__file__))  # sibling dbsafety module

import dbsafety  # noqa: E402

psycopg = pytest.importorskip("psycopg")

from app.deps import settings_singleton  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import assert_schema_matches, tables  # noqa: E402
from db.migrate import _to_libpq, discover, migrate  # noqa: E402

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
PASSWORD = "correct horse battery staple"
CSV_BYTES = b'Invoice Number,Net Amount\nINV-0001,"1,234.500"\n'
SHA_A = "a" * 64
FP_B = "b" * 64
SHA_C = "c" * 64
FP_D = "d" * 64


def _services_or_gate() -> None:
    try:
        with psycopg.connect(
            "postgresql://taxpilot:taxpilot@localhost:5432/taxpilot", connect_timeout=5
        ) as conn:
            conn.execute("SELECT 1")
        import redis as redis_lib

        redis_lib.Redis.from_url("redis://127.0.0.1:6379/0", socket_timeout=2).ping()
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"services unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"services unreachable (documented optional local mode): {exc}")


_DURL: str | None = None


def _scratch_or_skip() -> str:
    _services_or_gate()
    global _DURL
    if _DURL is None:
        candidate = dbsafety.destructive_url()
        try:
            dbsafety.require_destructive_db(candidate)
        except ValueError as exc:
            if REQUIRE_SERVICES:
                pytest.fail(f"destructive-test safeguard refused target: {exc}")
            pytest.skip(f"destructive-test safeguard refused target: {exc}")
        migrate(candidate)
        _DURL = candidate
    else:
        migrate(_DURL)
    return _DURL


@pytest.fixture()
def api(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    url = _scratch_or_skip()
    store_root = tmp_path / "quarantine"
    store_root.mkdir()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("QUARANTINE_ROOT", str(store_root))
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    settings_singleton.cache_clear()
    try:
        yield TestClient(create_app(), raise_server_exceptions=False)
    finally:
        settings_singleton.cache_clear()


def _email(tag: str) -> str:
    return f"recdata01-{tag}-{uuid.uuid4().hex[:8]}@example.com"


def _onboard(client: TestClient, tag: str) -> dict:
    email = _email(tag)
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "firm_name": "Synthetic Firm"},
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["verification_token"]
    assert client.post("/api/v1/auth/verify", json={"token": token}).status_code == 200
    logged = client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    client.headers.update({"X-CSRF-Token": logged.json()["csrf_token"]})
    return {"email": email, "tenant_id": logged.json()["active_tenant_id"]}


def _make_client(api_client: TestClient, name: str = "Synthetic Client") -> dict:
    r = api_client.post("/api/v1/clients", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _member_client(
    owner: TestClient, role: str, tag: str, owner_tenant_id: str
) -> TestClient:
    email = _email(f"{tag}-{role}")
    inv = owner.post("/api/v1/members/invitations", json={"email": email, "role": role})
    assert inv.status_code == 201, inv.text
    other = TestClient(owner.app, raise_server_exceptions=False)
    reg = other.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "firm_name": "Synthetic Firm"},
    )
    assert reg.status_code == 201
    assert (
        other.post(
            "/api/v1/auth/verify", json={"token": reg.json()["verification_token"]}
        ).status_code
        == 200
    )
    logged = other.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert logged.status_code == 200
    other.headers.update({"X-CSRF-Token": logged.json()["csrf_token"]})
    accept = other.post(
        "/api/v1/members/invitations/accept", json={"token": inv.json()["token"]}
    )
    assert accept.status_code == 200, accept.text
    switched = other.post("/api/v1/auth/tenant", json={"tenant_id": owner_tenant_id})
    assert switched.status_code == 200, switched.text
    other.headers.update({"X-CSRF-Token": switched.json()["csrf_token"]})
    return other


def _intake(client: TestClient, client_id: str, key: str = "intake-key-1") -> dict:
    r = client.post(
        f"/api/v1/clients/{client_id}/document-intakes",
        params={"declared_type": "csv", "filename": "sales-register.csv"},
        content=CSV_BYTES,
        headers={"Content-Type": "text/csv", "Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _count_versions(url: str) -> int:
    with psycopg.connect(_to_libpq(url)) as conn:
        return conn.execute("SELECT count(*) FROM dataset_versions").fetchone()[0]


def _count_versions_for_client(url: str, client_id: str) -> int:
    with psycopg.connect(_to_libpq(url)) as conn:
        return conn.execute(
            "SELECT count(*) FROM dataset_versions WHERE client_id = %s", (client_id,)
        ).fetchone()[0]


def _insert_version(
    conn,  # type: ignore[no-untyped-def]
    tenant_id,
    client_id,
    source_intake_id,
    *,
    doc_type="sales_register",
    version=1,
    source_sha=SHA_A,
    reg_fp=FP_B,
    dataset_fp=None,
):  # type: ignore[no-untyped-def]
    return conn.execute(
        "INSERT INTO dataset_versions (tenant_id, client_id, source_intake_id, doc_type,"
        " declared_format, version, source_content_sha256, registration_fingerprint,"
        " dataset_fingerprint) VALUES (%s, %s, %s, %s, 'csv', %s, %s, %s, %s) RETURNING id",
        (
            tenant_id,
            client_id,
            source_intake_id,
            doc_type,
            version,
            source_sha,
            reg_fp,
            dataset_fp,
        ),
    ).fetchone()[0]


# -- registration is default-deny (decision b2) ---------------------------------


def test_registration_default_denied_and_persists_nothing(api):  # type: ignore[no-untyped-def]
    _onboard(api, "deny")
    firm_client = _make_client(api)
    intake = _intake(api, firm_client["id"])
    url = _scratch_or_skip()
    before = _count_versions(url)
    r = api.post(
        f"/api/v1/clients/{firm_client['id']}/dataset-versions",
        json={"source_intake_id": intake["id"], "doc_type": "sales_register"},
    )
    assert r.status_code == 409, r.text
    body = r.json()["error"]
    assert body["code"] == "SOURCE_NOT_RELEASED"
    assert "Traceback" not in r.text
    assert _count_versions(url) == before


def test_registration_rejects_unsupported_document_type(api):  # type: ignore[no-untyped-def]
    _onboard(api, "badtype")
    firm_client = _make_client(api)
    intake = _intake(api, firm_client["id"])
    r = api.post(
        f"/api/v1/clients/{firm_client['id']}/dataset-versions",
        json={"source_intake_id": intake["id"], "doc_type": "bank_statement"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_registration_is_denied_for_unknown_source(api):  # type: ignore[no-untyped-def]
    _onboard(api, "nosource")
    firm_client = _make_client(api)
    r = api.post(
        f"/api/v1/clients/{firm_client['id']}/dataset-versions",
        json={"source_intake_id": str(uuid.uuid4()), "doc_type": "sales_register"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "NOT_FOUND"


# -- auth / RBAC ---------------------------------------------------------------


def test_registration_requires_authentication(api):  # type: ignore[no-untyped-def]
    _onboard(api, "authz")
    firm_client = _make_client(api)
    intake = _intake(api, firm_client["id"])
    anon = TestClient(api.app, raise_server_exceptions=False)
    r = anon.post(
        f"/api/v1/clients/{firm_client['id']}/dataset-versions",
        json={"source_intake_id": intake["id"], "doc_type": "sales_register"},
    )
    assert r.status_code == 401, r.text


def test_viewer_can_read_but_cannot_register(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "viewer")
    firm_client = _make_client(api)
    intake = _intake(api, firm_client["id"])
    viewer = _member_client(api, "viewer", "viewer", me["tenant_id"])
    assert (
        viewer.get(f"/api/v1/clients/{firm_client['id']}/dataset-versions").status_code
        == 200
    )
    denied = viewer.post(
        f"/api/v1/clients/{firm_client['id']}/dataset-versions",
        json={"source_intake_id": intake["id"], "doc_type": "sales_register"},
    )
    assert denied.status_code == 403, denied.text


# -- reads are tenant/client scoped --------------------------------------------


def test_list_and_get_are_scoped_to_client_and_tenant(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "read")
    client_a = _make_client(api, "Client A")
    client_b = _make_client(api, "Client B")
    intake_a = _intake(api, client_a["id"], key="read-a")
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        version_a = str(
            _insert_version(conn, me["tenant_id"], client_a["id"], intake_a["id"])
        )
        conn.commit()
    # Client A lists its version; client B is empty (no cross-client leakage).
    listed_a = api.get(f"/api/v1/clients/{client_a['id']}/dataset-versions")
    assert listed_a.status_code == 200, listed_a.text
    assert [v["id"] for v in listed_a.json()] == [version_a]
    assert api.get(f"/api/v1/clients/{client_b['id']}/dataset-versions").json() == []
    # Direct get works for the owning tenant.
    fetched = api.get(f"/api/v1/dataset-versions/{version_a}")
    assert fetched.status_code == 200 and fetched.json()["id"] == version_a
    assert fetched.json()["source_content_sha256"] == SHA_A
    assert fetched.json()["dataset_fingerprint"] is None  # distinct-hash rule
    # A different tenant cannot see it: indistinguishable 404, no oracle.
    other = TestClient(api.app, raise_server_exceptions=False)
    _onboard(other, "read-b")
    assert other.get(f"/api/v1/dataset-versions/{version_a}").status_code == 404
    assert (
        other.get(f"/api/v1/clients/{client_a['id']}/dataset-versions").status_code
        == 404
    )


# -- store primitive: idempotent registration + conflict (internal) -------------


def test_store_register_is_idempotent_and_conflicts_fail_closed(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "store")
    firm_client = _make_client(api)
    intake = _intake(api, firm_client["id"])
    url = _scratch_or_skip()
    from sqlalchemy import create_engine

    from app.store import Store

    engine = create_engine(url)
    conn = engine.connect()
    try:
        store = Store(conn, tables())
        row, created = store.register_dataset_version(
            tenant_id=me["tenant_id"],
            client_id=firm_client["id"],
            source_intake_id=intake["id"],
            doc_type="sales_register",
            declared_format="csv",
            source_content_sha256=SHA_A,
            registration_fingerprint=FP_B,
        )
        assert (
            created is True and row["version"] == 1 and row["parent_version_id"] is None
        )
        conn.commit()
        # Exact same identity converges: no new row.
        again, created2 = store.register_dataset_version(
            tenant_id=me["tenant_id"],
            client_id=firm_client["id"],
            source_intake_id=intake["id"],
            doc_type="sales_register",
            declared_format="csv",
            source_content_sha256=SHA_A,
            registration_fingerprint=FP_B,
        )
        assert created2 is False and str(again["id"]) == str(row["id"])
        conn.commit()
        # Different identity for the same (source intake, document type): refuse.
        with pytest.raises(ValueError):
            store.register_dataset_version(
                tenant_id=me["tenant_id"],
                client_id=firm_client["id"],
                source_intake_id=intake["id"],
                doc_type="sales_register",
                declared_format="csv",
                source_content_sha256=SHA_C,
                registration_fingerprint=FP_D,
            )
        conn.rollback()
    finally:
        conn.close()
        engine.dispose()


# -- concurrency: version allocation is serialized at the sequence scope --------


def _reg_args(tenant_id, client_id, intake_id, *, reg_fp, source_sha=SHA_A):
    return dict(
        tenant_id=tenant_id,
        client_id=client_id,
        source_intake_id=intake_id,
        doc_type="sales_register",
        declared_format="csv",
        source_content_sha256=source_sha,
        registration_fingerprint=reg_fp,
    )


def test_concurrent_distinct_intakes_allocate_distinct_versions(api):  # type: ignore[no-untyped-def]
    """F1: distinct intakes in one lineage never allocate the same version."""
    me = _onboard(api, "concur")
    firm_client = _make_client(api)
    intakes = [
        _intake(api, firm_client["id"], key=f"concur-{i}")["id"] for i in range(4)
    ]
    url = _scratch_or_skip()
    from sqlalchemy import create_engine

    from app.store import Store

    engine = create_engine(url)
    results: list[tuple] = []
    lock = threading.Lock()
    barrier = threading.Barrier(len(intakes))

    def worker(idx: int, intake_id: str) -> None:
        conn = engine.connect()
        try:
            store = Store(conn, tables())
            barrier.wait(timeout=15)
            row, created = store.register_dataset_version(
                **_reg_args(
                    me["tenant_id"],
                    firm_client["id"],
                    intake_id,
                    reg_fp=f"{idx + 1:064d}",
                )
            )
            conn.commit()
            with lock:
                results.append(
                    (created, row["version"], str(row["id"]), row["parent_version_id"])
                )
        except Exception as exc:  # noqa: BLE001 - surfaced as a test failure below
            conn.rollback()
            with lock:
                results.append(("error", repr(exc), None, None))
        finally:
            conn.close()

    threads = [
        threading.Thread(target=worker, args=(i, intake_id))
        for i, intake_id in enumerate(intakes)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    engine.dispose()

    errors = [r for r in results if r[0] == "error"]
    assert errors == [], errors
    assert all(r[0] is True for r in results)
    versions = sorted(r[1] for r in results)
    assert versions == [1, 2, 3, 4]  # distinct + monotonic, no collision
    by_version = {r[1]: r for r in results}
    assert by_version[1][3] is None
    for version in (2, 3, 4):
        assert str(by_version[version][3]) == by_version[version - 1][2]
    assert _count_versions_for_client(url, firm_client["id"]) == 4


def test_sequence_lock_serializes_different_intakes(api):  # type: ignore[no-untyped-def]
    """F1: a held sequence lock blocks a *different* intake for the same lineage."""
    me = _onboard(api, "lockseq")
    firm_client = _make_client(api)
    _intake(api, firm_client["id"], key="lockseq-a")
    intake_b = _intake(api, firm_client["id"], key="lockseq-b")["id"]
    url = _scratch_or_skip()
    from sqlalchemy import create_engine, text

    from app.store import Store

    engine = create_engine(url)
    holder = engine.connect()
    try:
        Store(holder, tables()).lock_dataset_sequence(
            me["tenant_id"], firm_client["id"], "sales_register"
        )
        started = threading.Event()
        done = threading.Event()
        result: dict = {}

        def worker() -> None:
            conn = engine.connect()
            try:
                store = Store(conn, tables())
                started.set()
                row, created = store.register_dataset_version(
                    **_reg_args(
                        me["tenant_id"], firm_client["id"], intake_b, reg_fp=FP_B
                    )
                )
                conn.commit()
                result["version"] = row["version"]
                result["created"] = created
            finally:
                conn.close()
                done.set()

        thread = threading.Thread(target=worker)
        thread.start()
        assert started.wait(timeout=10)
        # Bounded wait for the second connection to register as a lock waiter.
        waiting = False
        deadline = time.time() + 10
        while time.time() < deadline:
            with engine.connect() as probe:
                pending = probe.execute(
                    text(
                        "SELECT count(*) FROM pg_locks"
                        " WHERE locktype = 'advisory' AND NOT granted"
                    )
                ).scalar()
            if pending:
                waiting = True
                break
            time.sleep(0.1)
        assert waiting, "expected a blocked advisory-lock waiter on the sequence lock"
        assert (
            not done.is_set()
        ), "registration completed while the sequence lock was held"
        holder.commit()  # release the sequence lock
        assert done.wait(timeout=10), "registration did not proceed after lock release"
        thread.join(timeout=10)
        assert result == {"version": 1, "created": True}
    finally:
        holder.close()
        engine.dispose()


def test_concurrent_same_intake_replay_converges(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "replay")
    firm_client = _make_client(api)
    intake_id = _intake(api, firm_client["id"], key="replay-1")["id"]
    url = _scratch_or_skip()
    from sqlalchemy import create_engine

    from app.store import Store

    engine = create_engine(url)
    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker() -> None:
        conn = engine.connect()
        try:
            store = Store(conn, tables())
            barrier.wait(timeout=15)
            _, created = store.register_dataset_version(
                **_reg_args(me["tenant_id"], firm_client["id"], intake_id, reg_fp=FP_B)
            )
            conn.commit()
            with lock:
                results.append(created)
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            with lock:
                results.append(("error", repr(exc)))
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    engine.dispose()

    assert [r for r in results if r == "error" or isinstance(r, tuple)] == []
    assert results.count(True) == 1
    assert results.count(False) == 3
    assert _count_versions_for_client(url, firm_client["id"]) == 1


def test_version_sequences_isolated_per_client_and_tenant(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "iso-a")
    client_a = _make_client(api, "Client A")
    client_b = _make_client(api, "Client B")
    intake_a = _intake(api, client_a["id"], key="iso-a")["id"]
    intake_b = _intake(api, client_b["id"], key="iso-b")["id"]
    other = TestClient(api.app, raise_server_exceptions=False)
    tenant_b = _onboard(other, "iso-b")["tenant_id"]
    other_client = _make_client(other, "Other Client")
    intake_ob = _intake(other, other_client["id"], key="iso-ob")["id"]
    url = _scratch_or_skip()
    from sqlalchemy import create_engine

    from app.store import Store

    engine = create_engine(url)
    conn = engine.connect()
    try:
        store = Store(conn, tables())
        r_a, _ = store.register_dataset_version(
            **_reg_args(me["tenant_id"], client_a["id"], intake_a, reg_fp=FP_B)
        )
        r_b, _ = store.register_dataset_version(
            **_reg_args(
                me["tenant_id"], client_b["id"], intake_b, reg_fp=FP_D, source_sha=SHA_C
            )
        )
        r_ob, _ = store.register_dataset_version(
            **_reg_args(tenant_b, other_client["id"], intake_ob, reg_fp=FP_D)
        )
        conn.commit()
        # Same document type, independent scopes: each lineage starts at version 1.
        assert (r_a["version"], r_b["version"], r_ob["version"]) == (1, 1, 1)
        assert r_a["parent_version_id"] is None
        assert r_b["parent_version_id"] is None
        assert r_ob["parent_version_id"] is None
    finally:
        conn.close()
        engine.dispose()


# -- immutability + scoped lineage (database-enforced) --------------------------


def test_registry_rows_are_immutable(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "immut")
    firm_client = _make_client(api)
    intake = _intake(api, firm_client["id"])
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        version_id = _insert_version(
            conn, me["tenant_id"], firm_client["id"], intake["id"]
        )
        conn.commit()
        with pytest.raises(Exception):
            conn.execute(
                "UPDATE dataset_versions SET dataset_fingerprint = %s WHERE id = %s",
                (FP_D, version_id),
            )
        conn.rollback()
        with pytest.raises(Exception):
            conn.execute("DELETE FROM dataset_versions WHERE id = %s", (version_id,))
        conn.rollback()
        kept = conn.execute(
            "SELECT dataset_fingerprint FROM dataset_versions WHERE id = %s",
            (version_id,),
        ).fetchone()
        assert kept is not None and kept[0] is None


def test_scoped_keys_reject_spoofed_lineage(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "lin-a")
    client_a = _make_client(api, "Client A")
    client_b = _make_client(api, "Client B")
    intake_a = _intake(api, client_a["id"], key="lin-a")
    other = TestClient(api.app, raise_server_exceptions=False)
    tenant_b = _onboard(other, "lin-b")["tenant_id"]
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        # Cross-tenant source binding: tenant B claiming tenant A's intake.
        with pytest.raises(Exception):
            _insert_version(conn, tenant_b, client_a["id"], intake_a["id"])
        conn.rollback()
        # Same-tenant wrong client: client B claiming client A's intake.
        with pytest.raises(Exception):
            _insert_version(conn, me["tenant_id"], client_b["id"], intake_a["id"])
        conn.rollback()
        # Positive control: a correctly scoped row persists.
        version_id = _insert_version(
            conn, me["tenant_id"], client_a["id"], intake_a["id"]
        )
        kept = conn.execute(
            "SELECT client_id FROM dataset_versions WHERE id = %s", (version_id,)
        ).fetchone()
        assert str(kept[0]) == client_a["id"]
        conn.rollback()


# -- migration census + schema parity ------------------------------------------


def test_migration_census_includes_latest(api):  # type: ignore[no-untyped-def]
    _onboard(api, "census")
    assert [p.name for p in discover()][-1] == "0009_mapping_approvals.sql"


def test_schema_matches_definitions(api):  # type: ignore[no-untyped-def]
    _onboard(api, "schema")
    url = _scratch_or_skip()
    from sqlalchemy import create_engine

    engine = create_engine(url)
    try:
        assert_schema_matches(engine)
    finally:
        engine.dispose()

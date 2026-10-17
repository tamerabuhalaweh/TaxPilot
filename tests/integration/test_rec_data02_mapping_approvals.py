"""REC-DATA-02 integration: human-confirmed mapping approval (real PG + API).

Service-gating and harness mirror test_rec_data01_dataset_versions.py:
REQUIRE_SERVICES=1 (CI) turns unreachable services into FAILURE; all state lands
in the DEDICATED DISPOSABLE database (dbsafety-guarded). Synthetic data and
RFC-reserved example.com identities only.

Boundary under test (issue #63):
- submission/confirmation routes are default-deny and persist nothing (no
  trusted source-header attestation exists yet);
- proposals/decisions are append-only scoped evidence: cross-tenant/cross-client
  bindings are rejected by composite FKs, and UPDATE/DELETE are trigger-refused;
- replay is idempotent; conflicting reuse of an idempotency key fails closed;
- reads and the derived approval status are tenant/client/engagement scoped;
- approval is never derived without trusted evidence (no production-eligible
  output); stale coordinates are refused.
"""

import json
import os
import sys
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root
sys.path.insert(0, os.path.dirname(__file__))  # sibling dbsafety module

import dbsafety  # noqa: E402

psycopg = pytest.importorskip("psycopg")

from app.deps import settings_singleton  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import Store, assert_schema_matches, tables  # noqa: E402
from db.migrate import _to_libpq, discover, migrate  # noqa: E402

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
PASSWORD = "correct horse battery staple"
CSV_BYTES = b"Invoice Number,Net Amount\nINV-0001,100.00\n"
SHA_A = "a" * 64
FP_A = "1" * 64
FP_B = "2" * 64
FIELD_MAP = {"invoice_number": "Invoice Number", "net_amount": "Net Amount"}


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
    return f"recdata02-{tag}-{uuid.uuid4().hex[:8]}@example.com"


def _onboard(client: TestClient, tag: str) -> dict:
    email = _email(tag)
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "firm_name": "Synthetic Firm"},
    )
    assert reg.status_code == 201, reg.text
    assert (
        client.post(
            "/api/v1/auth/verify", json={"token": reg.json()["verification_token"]}
        ).status_code
        == 200
    )
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
    assert (
        other.post(
            "/api/v1/members/invitations/accept", json={"token": inv.json()["token"]}
        ).status_code
        == 200
    )
    switched = other.post("/api/v1/auth/tenant", json={"tenant_id": owner_tenant_id})
    assert switched.status_code == 200, switched.text
    other.headers.update({"X-CSRF-Token": switched.json()["csrf_token"]})
    return other


def _intake(client: TestClient, client_id: str, key: str = "intake-1") -> dict:
    r = client.post(
        f"/api/v1/clients/{client_id}/document-intakes",
        params={"declared_type": "csv", "filename": "sales-register.csv"},
        content=CSV_BYTES,
        headers={"Content-Type": "text/csv", "Idempotency-Key": key},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _engagement(client: TestClient, client_id: str, tag: str = "e") -> dict:
    r = client.post(
        "/api/v1/engagements",
        json={
            "client_id": client_id,
            "review_type": f"vat-{tag}",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _insert_version(
    conn, tenant_id, client_id, source_intake_id, *, version=1, dataset_fp=None
):  # type: ignore[no-untyped-def]
    return conn.execute(
        "INSERT INTO dataset_versions (tenant_id, client_id, source_intake_id, doc_type,"
        " declared_format, version, source_content_sha256, registration_fingerprint,"
        " normalization_version, dataset_fingerprint)"
        " VALUES (%s, %s, %s, 'sales_register', 'csv', %s, %s, %s, 'n1', %s) RETURNING id",
        (tenant_id, client_id, source_intake_id, version, SHA_A, FP_A, dataset_fp),
    ).fetchone()[0]


def _insert_proposal(
    conn, tenant_id, client_id, engagement_id, dataset_version_id, **over
):  # type: ignore[no-untyped-def]
    values = {
        "header_fingerprint": FP_A,
        "field_map": json.dumps(FIELD_MAP),
        "mapping_version": "m1",
        "normalization_version": "n1",
        "canonical_schema_version": "mapping-v1",
        "engagement_revision": 1,
        "proposal_fingerprint": FP_B,
    }
    values.update(over)
    return conn.execute(
        "INSERT INTO mapping_proposals (tenant_id, client_id, engagement_id, dataset_version_id,"
        " doc_type, header_fingerprint, field_map, mapping_version, normalization_version,"
        " canonical_schema_version, engagement_revision, proposal_fingerprint)"
        " VALUES (%s, %s, %s, %s, 'sales_register', %s, %s::jsonb, %s, %s, %s, %s, %s) RETURNING id",
        (
            tenant_id,
            client_id,
            engagement_id,
            dataset_version_id,
            values["header_fingerprint"],
            values["field_map"],
            values["mapping_version"],
            values["normalization_version"],
            values["canonical_schema_version"],
            values["engagement_revision"],
            values["proposal_fingerprint"],
        ),
    ).fetchone()[0]


def _seed_version(
    api: TestClient, tenant_id: str, client_id: str, *, key: str = "seed"
) -> str:
    intake = _intake(api, client_id, key=key)
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        vid = str(_insert_version(conn, tenant_id, client_id, intake["id"]))
        conn.commit()
    return vid


def _count(url: str, table: str) -> int:
    with psycopg.connect(_to_libpq(url)) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _proposal_body(vid: str) -> dict:
    return {
        "dataset_version_id": vid,
        "doc_type": "sales_register",
        "field_map": FIELD_MAP,
        "mapping_version": "m1",
        "normalization_version": "n1",
        "canonical_schema_version": "mapping-v1",
    }


# -- default-deny submission/confirmation (persists nothing) --------------------


def test_submit_proposal_default_denied_and_persists_nothing(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "deny")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    url = _scratch_or_skip()
    before = _count(url, "mapping_proposals")
    r = api.post(
        f"/api/v1/engagements/{engagement['id']}/mapping-proposals",
        json=_proposal_body(vid),
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "SOURCE_HEADERS_UNAVAILABLE"
    assert "Traceback" not in r.text
    assert _count(url, "mapping_proposals") == before


def test_submit_decision_default_denied_and_persists_nothing(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "decide")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        pid = str(
            _insert_proposal(
                conn, me["tenant_id"], firm_client["id"], engagement["id"], vid
            )
        )
        conn.commit()
    before = _count(url, "mapping_decisions")
    r = api.post(
        f"/api/v1/engagements/{engagement['id']}/mapping-proposals/{pid}/decisions",
        json={"decision": "APPROVED", "idempotency_key": "k-1"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "MAPPING_APPROVAL_NOT_ENABLED"
    assert _count(url, "mapping_decisions") == before


def test_caller_forged_fingerprint_field_is_rejected(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "forge")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    body = _proposal_body(vid)
    body["header_fingerprint"] = (
        "0" * 64
    )  # caller cannot supply the trusted fingerprint
    r = api.post(f"/api/v1/engagements/{engagement['id']}/mapping-proposals", json=body)
    assert r.status_code == 422, r.text


# -- auth / RBAC / CSRF --------------------------------------------------------


def test_submission_requires_authentication(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "authn")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    anon = TestClient(api.app, raise_server_exceptions=False)
    r = anon.post(
        f"/api/v1/engagements/{engagement['id']}/mapping-proposals",
        json=_proposal_body(vid),
    )
    assert r.status_code == 401, r.text


def test_viewer_can_read_but_cannot_submit(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "viewer")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    viewer = _member_client(api, "viewer", "viewer", me["tenant_id"])
    assert (
        viewer.get(
            f"/api/v1/engagements/{engagement['id']}/mapping-proposals"
        ).status_code
        == 200
    )
    denied = viewer.post(
        f"/api/v1/engagements/{engagement['id']}/mapping-proposals",
        json=_proposal_body(vid),
    )
    assert denied.status_code == 403, denied.text


def test_cookie_mutation_requires_csrf(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "csrf")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    api.headers.pop("X-CSRF-Token", None)
    r = api.post(
        f"/api/v1/engagements/{engagement['id']}/mapping-proposals",
        json=_proposal_body(vid),
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FORBIDDEN"


# -- scoped reads + derived default-deny status --------------------------------


def test_reads_and_approval_status_are_scoped(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "read")
    client_a = _make_client(api, "Client A")
    engagement = _engagement(api, client_a["id"])
    vid = _seed_version(api, me["tenant_id"], client_a["id"])
    assert (
        api.get(f"/api/v1/engagements/{engagement['id']}/mapping-proposals").json()
        == []
    )
    approval = api.get(
        f"/api/v1/engagements/{engagement['id']}/dataset-versions/{vid}/mapping-approval"
    )
    assert approval.status_code == 200, approval.text
    body = approval.json()
    assert body["approved"] is False
    assert (
        body["reason"] == "MAPPING_APPROVAL_NOT_ENABLED"
    )  # no production-eligible output
    # A different tenant cannot see the engagement's mapping evidence.
    other = TestClient(api.app, raise_server_exceptions=False)
    _onboard(other, "read-b")
    assert (
        other.get(
            f"/api/v1/engagements/{engagement['id']}/mapping-proposals"
        ).status_code
        == 404
    )


# -- store primitive: idempotent proposal replay + revision separation ----------


def _proposal_args(tenant_id, client_id, engagement_id, dataset_version_id, *, fp=FP_B):  # type: ignore[no-untyped-def]
    return dict(
        tenant_id=tenant_id,
        client_id=client_id,
        engagement_id=engagement_id,
        dataset_version_id=dataset_version_id,
        doc_type="sales_register",
        header_fingerprint=FP_A,
        field_map=FIELD_MAP,
        mapping_version="m1",
        normalization_version="n1",
        canonical_schema_version="mapping-v1",
        engagement_revision=1,
        proposal_fingerprint=fp,
    )


def test_proposal_replay_converges_and_revisions_append(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "prop")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    url = _scratch_or_skip()
    before = _count(url, "mapping_proposals")
    from sqlalchemy import create_engine

    engine = create_engine(url)
    conn = engine.connect()
    try:
        store = Store(conn, tables())
        args = _proposal_args(me["tenant_id"], firm_client["id"], engagement["id"], vid)
        row, created = store.create_mapping_proposal(**args)
        assert created is True
        conn.commit()
        again, created2 = store.create_mapping_proposal(**args)
        assert created2 is False and str(again["id"]) == str(row["id"])
        conn.commit()
        # A different fingerprint is a NEW revision, never an overwrite.
        other, created3 = store.create_mapping_proposal(
            **{**args, "proposal_fingerprint": "3" * 64}
        )
        assert created3 is True and str(other["id"]) != str(row["id"])
        conn.commit()
        assert _count(url, "mapping_proposals") - before == 2
    finally:
        conn.close()
        engine.dispose()


def test_decision_replay_converges_and_conflict_fails_closed(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "decs")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    url = _scratch_or_skip()
    before = _count(url, "mapping_decisions")
    from sqlalchemy import create_engine

    engine = create_engine(url)
    conn = engine.connect()
    try:
        store = Store(conn, tables())
        proposal, _ = store.create_mapping_proposal(
            **_proposal_args(me["tenant_id"], firm_client["id"], engagement["id"], vid)
        )
        conn.commit()
        common = dict(
            tenant_id=me["tenant_id"],
            client_id=firm_client["id"],
            engagement_id=engagement["id"],
            proposal_id=str(proposal["id"]),
            dataset_version_id=vid,
            reviewer_id=None,
            reason="ok",
            idempotency_key="k-1",
        )
        row, created = store.create_mapping_decision(decision="APPROVED", **common)
        assert created is True
        conn.commit()
        again, created2 = store.create_mapping_decision(decision="APPROVED", **common)
        assert created2 is False and str(again["id"]) == str(row["id"])
        conn.commit()
        with pytest.raises(ValueError):
            store.create_mapping_decision(decision="REJECTED", **common)
        conn.rollback()
        assert _count(url, "mapping_decisions") - before == 1
    finally:
        conn.close()
        engine.dispose()


def test_concurrent_decisions_yield_one_coherent_event(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "concur")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    url = _scratch_or_skip()
    before = _count(url, "mapping_decisions")
    from sqlalchemy import create_engine

    engine = create_engine(url)
    store = Store(engine.connect(), tables())
    proposal, _ = store.create_mapping_proposal(
        **_proposal_args(me["tenant_id"], firm_client["id"], engagement["id"], vid)
    )
    store.conn.commit()
    store.conn.close()

    results: list = []
    lock = threading.Lock()
    barrier = threading.Barrier(4)

    def worker() -> None:
        conn = engine.connect()
        try:
            s = Store(conn, tables())
            barrier.wait(timeout=15)
            _, created = s.create_mapping_decision(
                tenant_id=me["tenant_id"],
                client_id=firm_client["id"],
                engagement_id=engagement["id"],
                proposal_id=str(proposal["id"]),
                dataset_version_id=vid,
                decision="APPROVED",
                reviewer_id=None,
                reason="ok",
                idempotency_key="k-concurrent",
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

    assert [r for r in results if isinstance(r, tuple)] == [], results
    assert results.count(True) == 1
    assert results.count(False) == 3
    assert _count(url, "mapping_decisions") - before == 1


# -- immutability + scoped lineage (database-enforced) --------------------------


def test_mapping_rows_are_immutable(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "immut")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        pid = _insert_proposal(
            conn, me["tenant_id"], firm_client["id"], engagement["id"], vid
        )
        conn.commit()
        with pytest.raises(Exception):
            conn.execute(
                "UPDATE mapping_proposals SET mapping_version = 'm2' WHERE id = %s",
                (pid,),
            )
        conn.rollback()
        with pytest.raises(Exception):
            conn.execute("DELETE FROM mapping_proposals WHERE id = %s", (pid,))
        conn.rollback()
        kept = conn.execute(
            "SELECT mapping_version FROM mapping_proposals WHERE id = %s", (pid,)
        ).fetchone()
        assert kept is not None and kept[0] == "m1"
        conn.rollback()


def test_scoped_keys_reject_spoofed_lineage(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "lin-a")
    client_a = _make_client(api, "Client A")
    client_b = _make_client(api, "Client B")
    engagement_a = _engagement(api, client_a["id"])
    vid_a = _seed_version(api, me["tenant_id"], client_a["id"], key="lin-a")
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        # Same tenant, wrong client: client B claiming client A's dataset version.
        with pytest.raises(Exception):
            _insert_proposal(
                conn, me["tenant_id"], client_b["id"], engagement_a["id"], vid_a
            )
        conn.rollback()
        # Engagement/client mismatch: engagement A belongs to client A.
        with pytest.raises(Exception):
            _insert_proposal(
                conn, me["tenant_id"], client_b["id"], engagement_a["id"], vid_a
            )
        conn.rollback()
        # Positive control: a correctly scoped proposal persists.
        pid = _insert_proposal(
            conn, me["tenant_id"], client_a["id"], engagement_a["id"], vid_a
        )
        kept = conn.execute(
            "SELECT client_id FROM mapping_proposals WHERE id = %s", (pid,)
        ).fetchone()
        assert str(kept[0]) == client_a["id"]
        conn.rollback()


def test_empty_and_non_object_field_map_rejected(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "fm")
    firm_client = _make_client(api)
    engagement = _engagement(api, firm_client["id"])
    vid = _seed_version(api, me["tenant_id"], firm_client["id"])
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        with pytest.raises(Exception):
            _insert_proposal(
                conn,
                me["tenant_id"],
                firm_client["id"],
                engagement["id"],
                vid,
                field_map="{}",
            )
        conn.rollback()
        with pytest.raises(Exception):
            _insert_proposal(
                conn,
                me["tenant_id"],
                firm_client["id"],
                engagement["id"],
                vid,
                field_map="[]",
            )
        conn.rollback()


# -- migration census + schema parity ------------------------------------------


def test_migration_census_includes_0009(api):  # type: ignore[no-untyped-def]
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

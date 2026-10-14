"""EP-04B integration: authenticated quarantine intake (real PG + FastAPI).

Service-gating: REQUIRE_SERVICES=1 (CI) turns unreachable services into FAILURE.
All state lands in the DEDICATED DISPOSABLE database (dbsafety-guarded, never
DATABASE_URL) with private quarantine roots under tmp_path. Synthetic bytes and
RFC-reserved example.com identities only; nothing real, nothing committed.
"""

import hashlib
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
from db.migrate import _to_libpq, migrate  # noqa: E402

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
PASSWORD = "correct horse battery staple"
CSV_BYTES = b'Invoice Number,Net Amount\nINV-0001,"1,234.500"\n'
XLSX_MAGIC_BYTES = b"PK\x03\x04synthetic-quarantined-xlsx-never-parsed"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _services_or_gate() -> None:
    # NOTE: loopback families differ per service on some Windows hosts here:
    # postgres answers on localhost (::1) while the published redis port RSTs
    # IPv6 and needs 127.0.0.1. (CI Linux is unaffected either way.)
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
    """Fresh app bound to the disposable DB + a private tmp quarantine root."""
    url = _scratch_or_skip()
    store_root = tmp_path / "quarantine"
    store_root.mkdir()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("QUARANTINE_ROOT", str(store_root))
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    settings_singleton.cache_clear()
    try:
        yield TestClient(create_app(), raise_server_exceptions=False), store_root
    finally:
        settings_singleton.cache_clear()


def _email(tag: str) -> str:
    return f"ep04b-{tag}-{uuid.uuid4().hex[:8]}@example.com"


def _onboard(client: TestClient, tag: str) -> dict:
    email = _email(tag)
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "firm_name": "Synthetic Firm"},
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["verification_token"]
    assert token, "dev token exposure required for test onboarding"
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
    verify_token = reg.json()["verification_token"]
    assert (
        other.post("/api/v1/auth/verify", json={"token": verify_token}).status_code
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
    # Accept does not move the session: switch into the owner's workspace explicitly.
    switched = other.post("/api/v1/auth/tenant", json={"tenant_id": owner_tenant_id})
    assert switched.status_code == 200, switched.text
    other.headers.update({"X-CSRF-Token": switched.json()["csrf_token"]})
    return other


def _upload(
    client, client_id, data, filename, declared, content_type, key, extra_params=None
):
    params = {"declared_type": declared, "filename": filename}
    if extra_params:
        params.update(extra_params)
    return client.post(
        f"/api/v1/clients/{client_id}/document-intakes",
        params=params,
        content=data,
        headers={"Content-Type": content_type, "Idempotency-Key": key},
    )


def _csv_upload(
    client,
    client_id,
    key,
    data=CSV_BYTES,
    filename="sales-register.csv",
    declared="csv",
    content_type="text/csv",
    extra_params=None,
):
    return _upload(
        client, client_id, data, filename, declared, content_type, key, extra_params
    )


# -- happy paths ------------------------------------------------------------
def test_csv_quarantined_with_metadata_and_no_download(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "happy")
    firm_client = _make_client(client)
    r = _csv_upload(client, firm_client["id"], "key-happy-1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 1 and body["parent_id"] is None
    assert body["sha256"] == hashlib.sha256(CSV_BYTES).hexdigest()
    assert body["byte_count"] == len(CSV_BYTES)
    assert body["quarantine"]["status"] == "QUARANTINED"
    assert body["quarantine"]["downloadable"] is False
    assert "storage_key" not in r.text  # opaque key never disclosed
    assert client.get(
        f"/api/v1/document-intakes/{body['id']}/download"
    ).status_code in (404, 405)


def test_xlsx_magic_accepted_without_parsing(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "xlsx")
    firm_client = _make_client(client)
    r = _upload(
        client,
        firm_client["id"],
        XLSX_MAGIC_BYTES,
        "sheet.xlsx",
        "xlsx",
        XLSX_CONTENT_TYPE,
        "key-xlsx-1",
    )
    assert r.status_code == 201, r.text
    assert r.json()["quarantine"]["extractable"] is False


def test_list_and_get_scoped_to_client(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "list")
    first = _make_client(client, "First")
    second = _make_client(client, "Second")
    _csv_upload(client, first["id"], "key-list-1")
    listed = client.get(f"/api/v1/clients/{first['id']}/document-intakes")
    assert listed.status_code == 200 and len(listed.json()) == 1
    assert client.get(f"/api/v1/clients/{second['id']}/document-intakes").json() == []
    intake_id = listed.json()[0]["id"]
    assert client.get(f"/api/v1/document-intakes/{intake_id}").json()["id"] == intake_id


# -- auth / RBAC / CSRF ------------------------------------------------------
def test_unauthenticated_denied(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "noauth-owner")
    firm_client = _make_client(client)
    naked = TestClient(client.app, raise_server_exceptions=False)
    assert _csv_upload(naked, firm_client["id"], "key-noauth").status_code == 401


def test_viewer_denied_and_write_roles_allowed(api):  # type: ignore[no-untyped-def]
    client, _root = api
    owner = _onboard(client, "rbac-owner")
    firm_client = _make_client(client)
    viewer = _member_client(client, "viewer", "v", owner["tenant_id"])
    assert _csv_upload(viewer, firm_client["id"], "key-viewer").status_code == 403
    for role in ("accountant", "reviewer"):
        member = _member_client(client, role, f"ok-{role}", owner["tenant_id"])
        assert _csv_upload(member, firm_client["id"], f"key-{role}").status_code == 201


def test_cookie_csrf_required(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "csrf")
    firm_client = _make_client(client)
    client.headers.pop("X-CSRF-Token", None)
    assert _csv_upload(client, firm_client["id"], "key-csrf").status_code == 403


def test_bearer_session_token_exempt_from_csrf(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "bearer")
    firm_client = _make_client(client)
    session_cookie = client.cookies.get("tp_session")
    assert session_cookie
    bare = TestClient(client.app, raise_server_exceptions=False)
    r = bare.post(
        f"/api/v1/clients/{firm_client['id']}/document-intakes",
        params={"declared_type": "csv", "filename": "a.csv"},
        content=CSV_BYTES,
        headers={
            "Content-Type": "text/csv",
            "Idempotency-Key": "key-bearer-ok",
            "Authorization": f"Bearer {session_cookie}",
        },
    )
    assert r.status_code == 201, r.text


# -- cross-tenant / cross-client isolation ------------------------------------
def test_cross_tenant_idor_returns_404_without_leak(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "tenant-a")
    client_a = _make_client(client, "A")
    intake = _csv_upload(client, client_a["id"], "key-a-1").json()
    other = TestClient(client.app, raise_server_exceptions=False)
    _onboard(other, "tenant-b")
    missing = other.get(f"/api/v1/document-intakes/{intake['id']}")
    assert missing.status_code == 404
    assert "storage_key" not in missing.text and intake["sha256"] not in missing.text
    assert (
        other.get(f"/api/v1/clients/{client_a['id']}/document-intakes").status_code
        == 404
    )
    assert _csv_upload(other, client_a["id"], "key-evil").status_code == 404
    assert other.get("/api/v1/clients/not-a-uuid/document-intakes").status_code == 404


# -- validation negatives -----------------------------------------------------
def test_content_and_name_validation(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "neg")
    firm_client = _make_client(client)
    cid = firm_client["id"]
    counter = {"n": 0}

    def nxt(**kw) -> int:
        counter["n"] += 1
        return _csv_upload(client, cid, f"key-neg-{counter['n']}", **kw).status_code

    assert nxt(filename="sheet.xlsx") == 422  # extension conflicts with csv
    assert (
        nxt(
            data=XLSX_MAGIC_BYTES,
            filename="s.xlsx",
            declared="xlsx",
            content_type="text/csv",
        )
        == 422
    )  # forged content type
    assert (
        nxt(
            data=b"plain text",
            filename="s.xlsx",
            declared="xlsx",
            content_type=XLSX_CONTENT_TYPE,
        )
        == 422
    )  # bad xlsx signature
    assert (
        nxt(
            data=XLSX_MAGIC_BYTES,
            filename="s.csv",
            declared="csv",
            content_type="text/csv",
        )
        == 422
    )  # zip magic as csv
    assert nxt(content_type="application/json") == 422  # content type not allowlisted
    assert nxt(declared="json") == 422  # declared type not supported
    assert nxt(data=b"") == 422  # empty body
    assert nxt(filename="x" * 300 + ".csv") == 422  # filename too long
    assert nxt(filename="bad\x00name.csv") == 422  # NUL in filename
    r = client.post(
        f"/api/v1/clients/{cid}/document-intakes",
        params={"declared_type": "csv", "filename": "s.csv"},
        content=CSV_BYTES,
        headers={"Content-Type": "text/csv"},
    )
    assert r.status_code == 422  # missing Idempotency-Key
    r = client.post(
        f"/api/v1/clients/{cid}/document-intakes",
        params={"declared_type": "csv", "filename": "s.csv"},
        content=CSV_BYTES,
        headers={"Content-Type": "text/csv", "Idempotency-Key": "bad key!"},
    )
    assert r.status_code == 422  # malformed Idempotency-Key


def test_path_traversal_filename_neutralized(api):  # type: ignore[no-untyped-def]
    client, root = api
    _onboard(client, "traversal")
    firm_client = _make_client(client)
    evil = "../../evil-traversal.csv"
    r = _csv_upload(client, firm_client["id"], "key-traversal", filename=evil)
    assert r.status_code == 201, r.text
    assert r.json()["filename"] == evil  # metadata preserved verbatim
    assert not (root.parent / "evil-traversal.csv").exists()  # nothing escaped
    assert list(root.rglob("*evil-traversal*")) == []  # key carries no filename


def test_oversize_rejected_declared_and_lying_lengths(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "big")
    firm_client = _make_client(client)
    from app.deps import settings_singleton as singleton

    cap = singleton().upload_max_bytes
    oversized = b"x" * (cap + 1)
    r = client.post(
        f"/api/v1/clients/{firm_client['id']}/document-intakes",
        params={"declared_type": "csv", "filename": "big.csv"},
        content=oversized,
        headers={"Content-Type": "text/csv", "Idempotency-Key": "key-big-declared"},
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

    # No trustworthy Content-Length (chunked): the streaming cap still wins.
    def flood():
        yield b"x" * (cap // 2)
        yield b"x" * (cap // 2 + 1)

    chunked = client.post(
        f"/api/v1/clients/{firm_client['id']}/document-intakes",
        params={"declared_type": "csv", "filename": "big.csv"},
        content=flood(),
        headers={"Content-Type": "text/csv", "Idempotency-Key": "key-big-chunked"},
    )
    assert chunked.status_code == 413


def test_chunked_upload_without_length_is_stream_capped(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "chunked")
    firm_client = _make_client(client)

    def chunks():
        yield CSV_BYTES[:10]
        yield CSV_BYTES[10:]

    r = client.post(
        f"/api/v1/clients/{firm_client['id']}/document-intakes",
        params={"declared_type": "csv", "filename": "s.csv"},
        content=chunks(),
        headers={"Content-Type": "text/csv", "Idempotency-Key": "key-chunked"},
    )
    assert r.status_code == 201, r.text


def test_json_body_cap_untouched_by_upload_bypass(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "jsoncap")
    r = client.post("/api/v1/clients", json={"name": "x" * (2 * 1024 * 1024)})
    assert r.status_code == 413


def test_storage_unconfigured_fails_closed(api, monkeypatch):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "noroot")
    firm_client = _make_client(client)
    monkeypatch.delenv("QUARANTINE_ROOT")
    from app.deps import settings_singleton as singleton

    singleton.cache_clear()
    try:
        r = _csv_upload(client, firm_client["id"], "key-noroot")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    finally:
        singleton.cache_clear()


# -- idempotency / versions / duplicates ---------------------------------------
def test_same_key_same_payload_replays_same_record(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "idem")
    firm_client = _make_client(client)
    first = _csv_upload(client, firm_client["id"], "key-replay")
    assert first.status_code == 201
    second = _csv_upload(client, firm_client["id"], "key-replay")
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["version"] == 1


def test_same_key_different_payload_conflicts_then_versions(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "conflict")
    firm_client = _make_client(client)
    first = _csv_upload(client, firm_client["id"], "key-clash")
    assert first.status_code == 201
    other = b"Invoice Number,Net Amount\nDIFFERENT,9.99\n"
    clash = _csv_upload(client, firm_client["id"], "key-clash", data=other)
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "STATE_CONFLICT"
    assert clash.json()["error"]["details"]["intake_id"] == first.json()["id"]
    upgraded = _csv_upload(
        client,
        firm_client["id"],
        "key-clash",
        data=other,
        extra_params={"new_version": "true"},
    )
    assert upgraded.status_code == 201, upgraded.text
    assert upgraded.json()["version"] == 2
    assert upgraded.json()["parent_id"] == first.json()["id"]
    listed = client.get(f"/api/v1/clients/{firm_client['id']}/document-intakes").json()
    assert sorted(v["version"] for v in listed) == [1, 2]


def test_same_bytes_new_key_flagged_duplicate(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "dup")
    firm_client = _make_client(client)
    first = _csv_upload(client, firm_client["id"], "key-dup-a").json()
    second = _csv_upload(client, firm_client["id"], "key-dup-b")
    assert second.status_code == 201
    assert second.json()["duplicate_of"] == first["id"]
    assert second.json()["id"] != first["id"]


def _authed_worker_client(app, cookie, csrf):  # type: ignore[no-untyped-def]
    worker = TestClient(app, raise_server_exceptions=False)
    worker.headers.update({"Cookie": f"tp_session={cookie}", "X-CSRF-Token": csrf})
    return worker


def test_concurrent_same_key_single_version(api):  # type: ignore[no-untyped-def]
    client, root = api
    _onboard(client, "race")
    firm_client = _make_client(client)
    cookie = client.cookies.get("tp_session")
    csrf = client.headers.get("X-CSRF-Token")
    app = client.app
    barrier = threading.Barrier(8)
    outcomes: list = []

    def attempt() -> None:
        worker = _authed_worker_client(app, cookie, csrf)
        barrier.wait(timeout=10)
        outcomes.append(_csv_upload(worker, firm_client["id"], "key-race"))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(outcomes) == 8
    assert all(t.status_code in (200, 201) for t in outcomes)
    assert len({t.json()["id"] for t in outcomes}) == 1  # one logical record
    listed = client.get(f"/api/v1/clients/{firm_client['id']}/document-intakes").json()
    assert [v["version"] for v in listed] == [1]
    assert len([p for p in root.rglob("*") if p.is_file()]) == 1  # no orphan blobs


def test_concurrent_new_versions_serialize(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "race2")
    firm_client = _make_client(client)
    assert _csv_upload(client, firm_client["id"], "key-race2").status_code == 201
    cookie = client.cookies.get("tp_session")
    csrf = client.headers.get("X-CSRF-Token")
    app = client.app
    barrier = threading.Barrier(2)
    outcomes: list = []

    def attempt(n: int) -> None:
        worker = _authed_worker_client(app, cookie, csrf)
        barrier.wait(timeout=10)
        outcomes.append(
            _csv_upload(
                worker,
                firm_client["id"],
                "key-race2",
                data=f"Invoice Number,Net Amount\nV{n},1.00\n".encode(),
                filename=f"v{n}.csv",
                extra_params={"new_version": "true"},
            )
        )

    threads = [threading.Thread(target=attempt, args=(n,)) for n in (2, 3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(t.status_code for t in outcomes) == [201, 201]
    assert sorted(t.json()["version"] for t in outcomes) == [2, 3]  # no double version


# -- failure atomicity ----------------------------------------------------------
def test_storage_failure_leaves_no_row_or_blob(api, monkeypatch):  # type: ignore[no-untyped-def]
    client, root = api
    _onboard(client, "storfail")
    firm_client = _make_client(client)
    import app.routers.intakes as intakes

    def boom(self, key, data) -> int:  # type: ignore[no-untyped-def]
        raise OSError("synthetic disk failure")

    monkeypatch.setattr(intakes.LocalQuarantine, "put", boom)
    r = _csv_upload(client, firm_client["id"], "key-boom")
    assert r.status_code == 503
    assert (
        client.get(f"/api/v1/clients/{firm_client['id']}/document-intakes").json() == []
    )
    assert [p for p in root.rglob("*") if p.is_file()] == []


def test_db_failure_after_write_cleans_blob(api, monkeypatch):  # type: ignore[no-untyped-def]
    client, root = api
    _onboard(client, "dbfail")
    firm_client = _make_client(client)
    import app.store as store_module

    real_create = store_module.Store.create_intake
    calls = {"n": 0}

    def fail_once(self, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic post-write DB failure")
        return real_create(self, **kwargs)

    monkeypatch.setattr(store_module.Store, "create_intake", fail_once)
    r = _csv_upload(client, firm_client["id"], "key-dbfail")
    assert r.status_code == 500
    assert [p for p in root.rglob("*") if p.is_file()] == []
    assert (
        client.get(f"/api/v1/clients/{firm_client['id']}/document-intakes").json() == []
    )


# -- audit ----------------------------------------------------------------------
def test_audit_trail_without_contents_or_keys(api):  # type: ignore[no-untyped-def]
    client, _root = api
    _onboard(client, "audit")
    firm_client = _make_client(client)
    first = _csv_upload(client, firm_client["id"], "key-audit").json()
    _csv_upload(client, firm_client["id"], "key-audit")  # duplicate replay
    _csv_upload(client, firm_client["id"], "key-audit-bad", data=b"")  # rejected: empty
    events = client.get("/api/v1/audit").json()
    actions = [e["action"] for e in events]
    assert "document_intake.received" in actions
    assert "document_intake.duplicate" in actions
    assert "document_intake.rejected" in actions
    blob = " ".join(f"{e['action']} {e.get('resource')}" for e in events)
    assert "INV-0001" not in blob
    assert first["sha256"] not in blob  # hash never lands in the audit trail
    resources = [
        e["resource"] for e in events if e["action"].startswith("document_intake")
    ]
    assert all(r.startswith(("intake:", "client:")) for r in resources)


# -- R1 database lineage isolation + immutability ----------------------------------
def _pg_scope(tag: str):  # type: ignore[no-untyped-def]
    """Create tenant+client rows directly; returns ids. Caller manages cleanup."""
    url = _scratch_or_skip()
    tenant_id = str(uuid.uuid4())
    client_id = str(uuid.uuid4())
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s)", (tenant_id, f"t-{tag}")
        )
        conn.execute(
            "INSERT INTO clients (id, tenant_id, name) VALUES (%s, %s, %s)",
            (client_id, tenant_id, f"c-{tag}"),
        )
        conn.commit()
    return tenant_id, client_id


def _pg_intake(tenant_id: str, client_id: str, key: str, token: str, **overrides):  # type: ignore[no-untyped-def]
    """Insert one intake row directly; returns id. Rolls back on any failure."""
    url = _scratch_or_skip()
    fields = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "client_id": client_id,
        "idempotency_key": key,
        "storage_key": f"{tenant_id}/ab/{token}",
        "content_sha256": "cc" * 32,
        "byte_count": 3,
        "filename": "s.csv",
        "declared_type": "csv",
        "uploaded_by": None,
    }
    fields.update(overrides)
    columns = ", ".join(fields)
    placeholders = ", ".join(["%s"] * len(fields))
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        try:
            conn.execute(
                f"INSERT INTO document_intakes ({columns}) VALUES ({placeholders})",
                tuple(fields.values()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return fields["id"]


def test_lineage_parent_rejects_cross_tenant_and_cross_client():  # type: ignore[no-untyped-def]
    t1, c1 = _pg_scope("lin-a")
    t2, c2 = _pg_scope("lin-b")
    parent = _pg_intake(t1, c1, "k-parent", "t" * 43)
    with pytest.raises(Exception, match="(?i)(foreign key|violates)"):
        _pg_intake(t2, c2, "k-evil-tenant", "u" * 43, parent_id=parent)
    c1b = str(uuid.uuid4())
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        conn.execute(
            "INSERT INTO clients (id, tenant_id, name) VALUES (%s, %s, %s)",
            (c1b, t1, "c-lin-a2"),
        )
        conn.commit()
    with pytest.raises(Exception, match="(?i)(foreign key|violates)"):
        _pg_intake(t1, c1b, "k-evil-client", "v" * 43, parent_id=parent)
    # Same-scope lineage is accepted (control proves the FK, not the test, rejects).
    child = _pg_intake(t1, c1, "k-child", "w" * 43, parent_id=parent, version=2)
    assert child != parent


def test_duplicate_of_rejects_cross_scope():  # type: ignore[no-untyped-def]
    t1, c1 = _pg_scope("dup-a")
    t2, c2 = _pg_scope("dup-b")
    original = _pg_intake(t1, c1, "k-orig", "t" * 43)
    with pytest.raises(Exception, match="(?i)(foreign key|violates)"):
        _pg_intake(t2, c2, "k-evil-dup", "u" * 43, duplicate_of=original)


def test_accepted_metadata_immutable_at_database_layer():  # type: ignore[no-untyped-def]
    t1, c1 = _pg_scope("imm")
    row_id = _pg_intake(t1, c1, "k-imm", "t" * 43)
    url = _scratch_or_skip()
    for column, value in [
        ("filename", "renamed.csv"),
        ("content_sha256", "dd" * 32),
        ("storage_key", f"{t1}/ab/{'z' * 43}"),
        ("version", 99),
        ("byte_count", 12345),
    ]:
        with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
            with pytest.raises(
                Exception, match="(?i)(immutable|permission denied|violates)"
            ):
                conn.execute(
                    f"UPDATE document_intakes SET {column} = %s WHERE id = %s",
                    (value, row_id),
                )
            conn.rollback()


def test_authorized_status_transition_policy():  # type: ignore[no-untyped-def]
    """Future scan gate may move QUARANTINED -> REJECTED (terminal); all else refused."""
    t1, c1 = _pg_scope("trans")
    row_id = _pg_intake(t1, c1, "k-trans", "t" * 43)
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=5) as conn:
        conn.execute(
            "UPDATE document_intakes SET status = 'REJECTED', reason = 'synthetic scan verdict' "
            "WHERE id = %s",
            (row_id,),
        )
        conn.commit()
        status = conn.execute(
            "SELECT status, reason FROM document_intakes WHERE id = %s", (row_id,)
        ).fetchone()
        assert status[0] == "REJECTED" and "synthetic" in status[1]
        with pytest.raises(Exception, match="(?i)(not authorized|immutable)"):
            conn.execute(
                "UPDATE document_intakes SET status = 'QUARANTINED' WHERE id = %s",
                (row_id,),
            )
        conn.rollback()
        with pytest.raises(Exception, match="(?i)(not authorized|immutable)"):
            conn.execute(
                "UPDATE document_intakes SET status = 'CLEAN' WHERE id = %s", (row_id,)
            )
        conn.rollback()


# -- R3 commit-uncertainty ---------------------------------------------------------
def test_commit_ack_loss_preserves_blob_and_record(api, monkeypatch):  # type: ignore[no-untyped-def]
    """COMMIT succeeds server-side but its acknowledgement is lost: the row is
    committed, so the blob must be PRESERVED (never deleted) for reconciliation."""
    from sqlalchemy.engine import Connection

    client, root = api
    _onboard(client, "ackloss")
    firm_client = _make_client(client)
    real_commit = Connection.commit
    calls = {"n": 0}

    def commit_then_lose_ack(self):  # type: ignore[no-untyped-def]
        real_commit(self)
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic COMMIT acknowledgement loss")

    monkeypatch.setattr(Connection, "commit", commit_then_lose_ack)
    r = _csv_upload(client, firm_client["id"], "key-ackloss")
    assert r.status_code == 500  # honest failure surfaced, not a false success
    listed = client.get(f"/api/v1/clients/{firm_client['id']}/document-intakes").json()
    assert len(listed) == 1  # the committed record survived
    assert listed[0]["sha256"] == hashlib.sha256(CSV_BYTES).hexdigest()
    assert (
        len([p for p in root.rglob("*") if p.is_file()]) == 1
    )  # blob preserved with it


# -- R2 POSIX permission enforcement -------------------------------------------------
def test_quarantine_blob_and_dirs_owner_only_posix(tmp_path):  # type: ignore[no-untyped-def]
    if os.name == "nt":
        pytest.skip("POSIX permission bits verified on non-Windows CI")
    import stat as stat_module

    from app.quarantine import LocalQuarantine, new_storage_key

    store = LocalQuarantine(str(tmp_path))
    tenant = str(uuid.uuid4())
    key = new_storage_key(tenant, "ab" * 32)
    store.put(key, b"secret-bytes")
    assert stat_module.S_IMODE(os.stat(tmp_path).st_mode) == 0o700
    shard = tmp_path / tenant / "ab"
    assert stat_module.S_IMODE(os.stat(shard).st_mode) == 0o700
    assert store.blob_mode(key) == 0o600


def test_loose_root_tightened_and_symlink_shard_refused(tmp_path):  # type: ignore[no-untyped-def]
    if os.name == "nt":
        pytest.skip("POSIX permission bits verified on non-Windows CI")
    import stat as stat_module

    from app.quarantine import LocalQuarantine, StorageUnavailable, new_storage_key

    os.chmod(tmp_path, 0o755)
    store = LocalQuarantine(str(tmp_path))
    tenant = str(uuid.uuid4())
    store.put(new_storage_key(tenant, "ab" * 32), b"x")
    assert (
        stat_module.S_IMODE(os.stat(tmp_path).st_mode) == 0o700
    )  # repaired, not refused
    shard = tmp_path / tenant / "ab"
    link = tmp_path / tenant / "cd"
    try:
        link.symlink_to(shard, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    evil_key = f"{tenant}/cd/" + "y" * 43
    with pytest.raises(StorageUnavailable):
        store.put(evil_key, b"evil")
    assert not (shard / ("y" * 43)).exists()


def test_migration_0005_applied_and_conformant():  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine

    from app.store import assert_schema_matches
    from db.migrate import discover, load_checksums

    url = _scratch_or_skip()
    names = [p.name for p in discover()]
    assert "0005_document_intakes.sql" in names
    assert names == sorted(names) and len(names) == len(
        {n.split("_")[0] for n in names}
    )
    manifest = load_checksums()
    assert set(manifest) >= {"0001", "0002", "0003", "0004", "0005"}
    assert migrate(url) == []  # ledger matches manifest: old SHAs unchanged
    engine = create_engine(url)
    try:
        assert_schema_matches(engine)
    finally:
        engine.dispose()


# -- storage unit behavior (no DB) --------------------------------------------------
def test_storage_readiness_matrix() -> None:
    from app.quarantine import storage_readiness

    assert storage_readiness("development", "local", "/tmp/q")[0] is True
    assert storage_readiness("test", "local", "/tmp/q")[0] is True
    ok, _reason = storage_readiness("staging", "local", "/tmp/q")
    assert ok is False
    assert storage_readiness("production", "local", "/tmp/q")[0] is False
    assert storage_readiness("development", "local", None)[0] is False
    assert storage_readiness("development", "s3", "/tmp/q")[0] is False


def test_storage_keys_opaque_and_traversal_safe(tmp_path):  # type: ignore[no-untyped-def]
    from app.quarantine import LocalQuarantine, StorageUnavailable, new_storage_key

    store = LocalQuarantine(str(tmp_path))
    tenant = str(uuid.uuid4())
    key = new_storage_key(tenant, "ab" * 32)
    assert "secret.csv" not in key
    assert new_storage_key(tenant, "ab" * 32) != key  # unpredictable per put
    store.put(key, b"bytes")
    assert store.exists(key) is True
    assert store.exists(f"{tenant}/ab/" + "x" * 43) is False
    store.delete("../../escape")  # malformed key: safe no-op
    store.delete(key)
    assert store.exists(key) is False
    with pytest.raises(ValueError):
        store.put("../escape", b"x")
    if os.name != "nt":
        link = tmp_path / "linkroot"
        try:
            link.symlink_to(tmp_path, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks unavailable")
        with pytest.raises(StorageUnavailable):
            LocalQuarantine(str(link))

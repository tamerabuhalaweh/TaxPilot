"""REC-SLICE-03 integration: engagements + run boundary (real PG + FastAPI).

Service-gating and harness mirror test_ep04b_intake.py: REQUIRE_SERVICES=1
(CI) turns unreachable services into FAILURE; all state lands in the
DEDICATED DISPOSABLE database (dbsafety-guarded). Synthetic data and
RFC-reserved example.com identities only.

Acceptance mapping (§9): 1 create/retrieve, 2 cross-tenant denied, 3
cross-client context denied, 4 unauthorized mutation denied, 5 invalid
periods, 6 unconfirmed jurisdiction blocks runs, 7-10 dataset gates (endpoint
stops at the first dataset gate — no registries exist yet; the remaining
codes are pinned by apps/api/tests/test_rec_execution_contracts.py), 11
stable replay, 12 conflicting reuse, 13 concurrent single record, 14 version
change gives new identity, 15 runs immutable/never approved + archive
preserves history, 16 no sensitive contents in refusals. 17 is the existing
PR #56/#57 golden suites (run in CI alongside this file).
"""

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
PERIOD = ("2026-01-01", "2026-12-31")


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
    return f"rec03-{tag}-{uuid.uuid4().hex[:8]}@example.com"


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


def _authed_worker_client(app, cookie, csrf):  # type: ignore[no-untyped-def]
    worker = TestClient(app, raise_server_exceptions=False)
    worker.headers.update({"Cookie": f"tp_session={cookie}", "X-CSRF-Token": csrf})
    return worker


def _make_engagement(api_client, client_id, **kw):  # type: ignore[no-untyped-def]
    body = {
        "client_id": client_id,
        "review_type": "reconciliation",
        "period_start": PERIOD[0],
        "period_end": PERIOD[1],
    }
    body.update(kw)
    r = api_client.post("/api/v1/engagements", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _activate(api_client, engagement_id):  # type: ignore[no-untyped-def]
    r = api_client.patch(
        "/api/v1/engagements/" + engagement_id, json={"status": "ACTIVE"}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _request_run(
    api_client, engagement_id, key="run-key-1", sales="SALES-v1", jofo="JOFO-v1"
):  # type: ignore[no-untyped-def]
    return api_client.post(
        "/api/v1/engagements/" + engagement_id + "/recon-runs",
        json={
            "sales_dataset_version_id": sales,
            "jofo_dataset_version_id": jofo,
            "idempotency_key": key,
        },
    )


def _insert_context(url, tenant_id, client_id, confirmation):  # type: ignore[no-untyped-def]
    """Raw-SQL fixture: jurisdiction writes belong to that slice (no API on main)."""
    with psycopg.connect(_to_libpq(url)) as conn:
        entity = conn.execute(
            "INSERT INTO legal_entities (tenant_id, client_id, legal_name,"
            " incorporation_country_code, entity_type, base_currency, fiscal_start, status)"
            " VALUES (%s, %s, 'Synthetic Entity', 'JO', 'LLC', 'JOD', '01-01', 'DRAFT')"
            " RETURNING id",
            (tenant_id, client_id),
        ).fetchone()[0]
        context = conn.execute(
            "INSERT INTO tax_contexts (tenant_id, client_id, subject_entity_id,"
            " jurisdiction_code, tax_type_code, period_start, period_end, confirmation_status)"
            " VALUES (%s, %s, %s, 'JO', 'VAT', '2026-01-01', '2026-12-31', %s) RETURNING id",
            (tenant_id, client_id, entity, confirmation),
        ).fetchone()[0]
        conn.commit()
    return str(context)


# -- acceptance 1: create + retrieve -------------------------------------------


def test_create_and_retrieve_engagement(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "create")
    firm_client = _make_client(api)
    created = _make_engagement(api, firm_client["id"])
    assert created["status"] == "DRAFT"
    assert created["revision"] == 1
    fetched = api.get("/api/v1/engagements/" + created["id"])
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == created["id"]
    history = api.get("/api/v1/engagements/" + created["id"] + "/history")
    assert history.status_code == 200
    assert [e["action"] for e in history.json()] == ["created"]
    audit = api.get("/api/v1/audit")
    assert audit.status_code == 200
    assert "engagement.created" in [e["action"] for e in audit.json()]
    assert me["tenant_id"]


def test_duplicate_same_period_conflicts(api):  # type: ignore[no-untyped-def]
    _onboard(api, "dupe")
    firm_client = _make_client(api)
    first = _make_engagement(api, firm_client["id"])
    r = api.post(
        "/api/v1/engagements",
        json={
            "client_id": firm_client["id"],
            "review_type": "reconciliation",
            "period_start": PERIOD[0],
            "period_end": PERIOD[1],
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "STATE_CONFLICT"
    assert r.json()["error"]["details"]["existing_engagement_id"] == first["id"]


# -- acceptance 2: cross-tenant denied ------------------------------------------


def test_cross_tenant_access_denied(api):  # type: ignore[no-untyped-def]
    _onboard(api, "tenant-a")
    firm_client = _make_client(api)
    engagement = _make_engagement(api, firm_client["id"])
    other = TestClient(api.app, raise_server_exceptions=False)
    _onboard(other, "tenant-b")
    assert other.get("/api/v1/engagements/" + engagement["id"]).status_code == 404
    assert other.get("/api/v1/clients/" + firm_client["id"]).status_code == 404
    assert (
        other.get("/api/v1/engagements/" + engagement["id"] + "/history").status_code
        == 404
    )
    assert (
        other.get("/api/v1/engagements/" + engagement["id"] + "/recon-runs").status_code
        == 404
    )
    assert _request_run(other, engagement["id"]).status_code == 404
    assert (
        other.patch(
            "/api/v1/engagements/" + engagement["id"], json={"status": "ACTIVE"}
        ).status_code
        == 404
    )


# -- acceptance 3: cross-client context denied -----------------------------------


def test_cross_client_context_denied(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "xclient")
    client_a = _make_client(api, "Client A")
    client_b = _make_client(api, "Client B")
    url = _scratch_or_skip()
    foreign = _insert_context(url, me["tenant_id"], client_b["id"], "CONFIRMED")
    r = api.post(
        "/api/v1/engagements",
        json={
            "client_id": client_a["id"],
            "review_type": "reconciliation",
            "period_start": PERIOD[0],
            "period_end": PERIOD[1],
            "tax_context_id": foreign,
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


# -- acceptance 4: unauthorized mutation denied ----------------------------------


def test_unauthorized_mutation_denied(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "owner4")
    firm_client = _make_client(api)
    engagement = _make_engagement(api, firm_client["id"])
    viewer = _member_client(api, "viewer", "vwr", me["tenant_id"])
    assert (
        viewer.post(
            "/api/v1/engagements",
            json={
                "client_id": firm_client["id"],
                "review_type": "reconciliation",
                "period_start": PERIOD[0],
                "period_end": PERIOD[1],
            },
        ).status_code
        == 403
    )
    assert (
        viewer.patch(
            "/api/v1/engagements/" + engagement["id"], json={"status": "ACTIVE"}
        ).status_code
        == 403
    )
    assert (
        viewer.post(
            "/api/v1/engagements/" + engagement["id"] + "/recon-runs",
            json={
                "sales_dataset_version_id": "S",
                "jofo_dataset_version_id": "J",
                "idempotency_key": "k",
            },
        ).status_code
        == 403
    )
    naked = TestClient(api.app, raise_server_exceptions=False)
    assert (
        naked.patch(
            "/api/v1/engagements/" + engagement["id"], json={"status": "ACTIVE"}
        ).status_code
        == 401
    )
    assert naked.get("/api/v1/engagements").status_code == 401


# -- acceptance 5: invalid periods rejected --------------------------------------


def test_invalid_periods_rejected(api):  # type: ignore[no-untyped-def]
    _onboard(api, "period")
    firm_client = _make_client(api)
    r = api.post(
        "/api/v1/engagements",
        json={
            "client_id": firm_client["id"],
            "review_type": "reconciliation",
            "period_start": "2026-12-31",
            "period_end": "2026-01-01",
        },
    )
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_invalid_transitions_rejected(api):  # type: ignore[no-untyped-def]
    _onboard(api, "trans")
    firm_client = _make_client(api)
    engagement = _make_engagement(api, firm_client["id"])
    eid = engagement["id"]
    assert (
        api.patch("/api/v1/engagements/" + eid, json={"status": "CLOSED"}).status_code
        == 409
    )
    same = api.patch("/api/v1/engagements/" + eid, json={"status": "DRAFT"})
    assert same.status_code == 200  # same-status is a no-op, not a transition
    assert same.json()["status"] == "DRAFT"
    assert same.json()["revision"] == 1
    _activate(api, eid)
    closed = api.patch("/api/v1/engagements/" + eid, json={"status": "CLOSED"})
    assert closed.status_code == 200, closed.text
    assert closed.json()["revision"] == 3
    archived = api.patch("/api/v1/engagements/" + eid, json={"status": "ARCHIVED"})
    assert archived.status_code == 200, archived.text
    frozen = api.patch("/api/v1/engagements/" + eid, json={"status": "ACTIVE"})
    assert frozen.status_code == 409, frozen.text
    history = api.get("/api/v1/engagements/" + eid + "/history").json()
    assert [(e["action"], e["prior_status"], e["new_status"]) for e in history] == [
        ("created", None, "DRAFT"),
        ("status_changed", "DRAFT", "ACTIVE"),
        ("status_changed", "ACTIVE", "CLOSED"),
        ("status_changed", "CLOSED", "ARCHIVED"),
    ]


# -- acceptance 6: jurisdiction gate ----------------------------------------------


def test_unconfirmed_jurisdiction_blocks_run(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "juris")
    firm_client = _make_client(api)
    bare = _activate(api, _make_engagement(api, firm_client["id"])["id"])
    r = _request_run(api, bare["id"])
    assert r.status_code == 409, r.text
    assert r.json()["blocked_reason"] == "UNCONFIRMED_JURISDICTION"
    url = _scratch_or_skip()
    draft_ctx = _insert_context(url, me["tenant_id"], firm_client["id"], "DRAFT")
    with_ctx = _make_engagement(
        api, firm_client["id"], tax_context_id=draft_ctx, review_type="review"
    )
    _activate(api, with_ctx["id"])
    r2 = _request_run(api, with_ctx["id"], key="run-key-2")
    assert r2.status_code == 409, r2.text
    assert r2.json()["blocked_reason"] == "UNCONFIRMED_JURISDICTION"


# -- acceptance 7-10: dataset gates (first gate trips; rest are unit-pinned) ------


def test_missing_dataset_version_blocks_run(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "dsver")
    firm_client = _make_client(api)
    url = _scratch_or_skip()
    confirmed = _insert_context(url, me["tenant_id"], firm_client["id"], "CONFIRMED")
    engagement = _make_engagement(api, firm_client["id"], tax_context_id=confirmed)
    _activate(api, engagement["id"])
    r = _request_run(api, engagement["id"])
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["blocked_reason"] == "MISSING_DATASET_VERSION"
    assert body["status"] == "BLOCKED"
    assert body["operation"] == "rec.reconcile.v1"
    assert body["jurisdiction_code"] == "JO"
    listed = api.get("/api/v1/engagements/" + engagement["id"] + "/recon-runs").json()
    assert [run["id"] for run in listed] == [body["id"]]


def test_inactive_engagement_cannot_request_runs(api):  # type: ignore[no-untyped-def]
    _onboard(api, "inactive")
    firm_client = _make_client(api)
    engagement = _make_engagement(api, firm_client["id"])
    r = _request_run(api, engagement["id"])
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "STATE_CONFLICT"
    assert r.json()["error"]["details"]["reason"] == "ENGAGEMENT_NOT_ACTIVE"


# -- acceptance 11/12: idempotent replay vs conflicting reuse ----------------------


def test_identical_replay_is_stable(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "replay")
    firm_client = _make_client(api)
    url = _scratch_or_skip()
    confirmed = _insert_context(url, me["tenant_id"], firm_client["id"], "CONFIRMED")
    engagement = _make_engagement(api, firm_client["id"], tax_context_id=confirmed)
    _activate(api, engagement["id"])
    first = _request_run(api, engagement["id"])
    second = _request_run(api, engagement["id"])
    assert first.status_code == 409 and second.status_code == 409
    assert first.json() == second.json()
    listed = api.get("/api/v1/engagements/" + engagement["id"] + "/recon-runs").json()
    assert len(listed) == 1


def test_conflicting_key_reuse_rejected(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "conflict")
    firm_client = _make_client(api)
    url = _scratch_or_skip()
    confirmed = _insert_context(url, me["tenant_id"], firm_client["id"], "CONFIRMED")
    engagement = _make_engagement(api, firm_client["id"], tax_context_id=confirmed)
    _activate(api, engagement["id"])
    first = _request_run(api, engagement["id"], key="same-key")
    assert first.status_code == 409
    clash = _request_run(api, engagement["id"], key="same-key", sales="SALES-v2")
    assert clash.status_code == 409, clash.text
    assert clash.json()["error"]["code"] == "STATE_CONFLICT"
    assert clash.json()["error"]["details"]["existing_run_id"] == first.json()["id"]


# -- acceptance 13: concurrent requests converge ------------------------------------


def test_concurrent_run_requests_single_record(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "race")
    firm_client = _make_client(api)
    url = _scratch_or_skip()
    confirmed = _insert_context(url, me["tenant_id"], firm_client["id"], "CONFIRMED")
    engagement = _make_engagement(api, firm_client["id"], tax_context_id=confirmed)
    _activate(api, engagement["id"])
    cookie = api.cookies.get("tp_session")
    csrf = api.headers.get("X-CSRF-Token")
    app = api.app
    barrier = threading.Barrier(6)
    outcomes: list = []

    def attempt() -> None:
        worker = _authed_worker_client(app, cookie, csrf)
        barrier.wait(timeout=10)
        outcomes.append(_request_run(worker, engagement["id"], key="race-key"))

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(outcomes) == 6
    assert all(t.status_code == 409 for t in outcomes)
    assert len({t.json()["id"] for t in outcomes}) == 1  # one logical record
    listed = api.get("/api/v1/engagements/" + engagement["id"] + "/recon-runs").json()
    assert len(listed) == 1


# -- acceptance 14: version change gives new identity --------------------------------


def test_version_change_produces_new_run_identity(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "newid")
    firm_client = _make_client(api)
    url = _scratch_or_skip()
    confirmed = _insert_context(url, me["tenant_id"], firm_client["id"], "CONFIRMED")
    engagement = _make_engagement(api, firm_client["id"], tax_context_id=confirmed)
    _activate(api, engagement["id"])
    first = _request_run(
        api, engagement["id"], key="key-a", sales="SALES-v1", jofo="JOFO-v1"
    )
    second = _request_run(
        api, engagement["id"], key="key-b", sales="SALES-v2", jofo="JOFO-v1"
    )
    assert first.status_code == 409 and second.status_code == 409
    assert first.json()["id"] != second.json()["id"]
    assert (
        first.json()["source_set_fingerprint"]
        != second.json()["source_set_fingerprint"]
    )


# -- acceptance 15: immutable, never approved; archive preserves history --------------


def test_runs_immutable_and_never_approved(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "immut")
    firm_client = _make_client(api)
    url = _scratch_or_skip()
    confirmed = _insert_context(url, me["tenant_id"], firm_client["id"], "CONFIRMED")
    engagement = _make_engagement(api, firm_client["id"], tax_context_id=confirmed)
    _activate(api, engagement["id"])
    created = _request_run(api, engagement["id"])
    run_id = created.json()["id"]
    # No mutation route exists for runs: every method/shape misses.
    assert api.patch(
        "/api/v1/engagements/" + engagement["id"], json={"status": "DRAFT"}
    ).status_code in (404, 405, 409)
    assert api.delete(
        "/api/v1/engagements/" + engagement["id"] + "/recon-runs/" + run_id
    ).status_code in (404, 405)
    listed = api.get("/api/v1/engagements/" + engagement["id"] + "/recon-runs").json()
    assert [(r["id"], r["status"], r["blocked_reason"]) for r in listed] == [
        (run_id, "BLOCKED", "MISSING_DATASET_VERSION")
    ]
    # Direct UPDATE is rejected by the trigger guard.
    with psycopg.connect(_to_libpq(url)) as conn:
        with pytest.raises(Exception):
            conn.execute(
                "UPDATE recon_runs SET blocked_reason = 'X' WHERE id = %s", (run_id,)
            )
        conn.rollback()
    # Archiving the client preserves engagement + run history.
    assert (
        api.patch(
            "/api/v1/clients/" + firm_client["id"], json={"status": "archived"}
        ).status_code
        == 200
    )
    assert api.get("/api/v1/engagements/" + engagement["id"]).status_code == 200
    assert (
        len(api.get("/api/v1/engagements/" + engagement["id"] + "/history").json()) >= 2
    )
    assert (
        len(api.get("/api/v1/engagements/" + engagement["id"] + "/recon-runs").json())
        == 1
    )


def test_migration_guards_hold(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "guards")
    firm_client = _make_client(api)
    engagement = _make_engagement(api, firm_client["id"])
    url = _scratch_or_skip()
    with psycopg.connect(_to_libpq(url)) as conn:
        with pytest.raises(Exception):
            conn.execute(
                "INSERT INTO engagements (tenant_id, client_id, review_type,"
                " period_start, period_end, status) VALUES (%s, %s, 'x', '2026-01-01', '2026-12-31', 'BOGUS')",
                (me["tenant_id"], firm_client["id"]),
            )
        conn.rollback()
        # RESTRICT fires because a child engagement references this client.
        with pytest.raises(Exception):
            conn.execute("DELETE FROM clients WHERE id = %s", (firm_client["id"],))
        conn.rollback()
        with pytest.raises(Exception):
            conn.execute("DELETE FROM engagements WHERE id = %s", (engagement["id"],))
        conn.rollback()


# -- acceptance 16: refusals carry codes, never contents -------------------------------


def test_refusals_carry_no_sensitive_contents(api):  # type: ignore[no-untyped-def]
    me = _onboard(api, "clean")
    firm_client = _make_client(api)
    url = _scratch_or_skip()
    confirmed = _insert_context(url, me["tenant_id"], firm_client["id"], "CONFIRMED")
    engagement = _make_engagement(api, firm_client["id"], tax_context_id=confirmed)
    _activate(api, engagement["id"])
    r = _request_run(api, engagement["id"], sales="SALES-v9", jofo="JOFO-v9")
    body = r.json()
    assert r.status_code == 409
    assert body["sales_dataset_version_id"] == "SALES-v9"
    assert "Traceback" not in r.text
    for key in ("blocked_reason", "blocked_detail", "status", "operation"):
        assert isinstance(body[key], str)
    assert body["blocked_reason"] == "MISSING_DATASET_VERSION"

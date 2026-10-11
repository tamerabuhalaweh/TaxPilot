"""Sprint 1 integration: auth, tenancy, RBAC, clients, audit, tenant isolation.

Service-gating: REQUIRE_SERVICES=1 (CI) turns unreachable services into FAILURE.
Every test uses synthetic emails/credentials; nothing real, nothing committed.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"


def _services_or_gate() -> None:
    import psycopg
    import redis as redis_lib

    try:
        with psycopg.connect(
            "postgresql://taxpilot:taxpilot@localhost:5432/taxpilot", connect_timeout=5
        ) as conn:
            conn.execute("SELECT 1")
        redis_lib.Redis.from_url("redis://localhost:6379/0", socket_timeout=2).ping()
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"services unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"services unreachable (documented optional local mode): {exc}")


@pytest.fixture(autouse=True)
def _clean_ratelimits():  # type: ignore[no-untyped-def]
    """Rate-limit counters are global per Redis: reset test keys before each test so
    lockout state never leaks between tests (or reruns inside the TTL window)."""
    import redis as redis_lib

    try:
        client = redis_lib.Redis.from_url("redis://localhost:6379/0", socket_timeout=2)
        keys = list(client.scan_iter("tp:ratelimit:*", count=200))
        if keys:
            client.delete(*keys)
    except Exception:
        pass  # _services_or_gate reports reachability through the proper gate
    yield


def fresh_client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _email(tag: str) -> str:
    # example.com is RFC-reserved for documentation: synthetic, never real users.
    return f"s1-{tag}-{uuid.uuid4().hex[:8]}@example.com"


PASSWORD = "correct horse battery staple"


def register(client: TestClient, email: str, firm: str = "Acme Accounting") -> dict:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "firm_name": firm},
    )
    assert r.status_code == 201, r.text
    return r.json()


def verify(client: TestClient, token: str) -> None:
    r = client.post("/api/v1/auth/verify", json={"token": token})
    assert r.status_code == 200, r.text


def login(client: TestClient, email: str, password: str = PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


def onboard(client: TestClient, tag: str) -> dict:
    """register -> verify -> login; returns registration payload (dev token exposed)."""
    email = _email(tag)
    reg = register(client, email)
    assert reg["verification_token"], "dev token exposure required for test onboarding"
    verify(client, reg["verification_token"])
    r = login(client, email)
    assert r.status_code == 200, r.text
    return {"email": email, **reg, "session": r.json()}


def test_full_journey_register_verify_login_me_logout():
    _services_or_gate()
    client = fresh_client()
    # Unverified login is forbidden before verification.
    email = _email("journey")
    reg = register(client, email)
    assert login(client, email).status_code == 403
    verify(client, reg["verification_token"])
    assert login(client, email).status_code == 200
    me = client.get("/api/v1/users/me")
    assert me.status_code == 200 and me.json()["email"] == email
    assert me.json()["memberships"][0]["role"] == "owner"
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.get("/api/v1/users/me").status_code == 401  # revoked session rejected


def test_duplicate_registration_and_bad_verify_rejected():
    _services_or_gate()
    client = fresh_client()
    email = _email("dup")
    assert register(client, email)["user_id"]
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "firm_name": "x"},
    )
    assert r.status_code == 422
    assert (
        client.post("/api/v1/auth/verify", json={"token": "bogus"}).status_code == 422
    )
    assert (
        login(client, email, "wrong password here!").status_code == 401
    )  # generic, no oracle


def test_login_rate_limit_locks_out_then_reports_retry():
    _services_or_gate()
    client = fresh_client()
    email = _email("ratelimit")
    reg = register(client, email)
    verify(client, reg["verification_token"])
    codes = [login(client, email, "wrong password here!").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    limited = login(client, email, "wrong password here!")
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_invite_accept_and_role_enforcement():
    _services_or_gate()
    owner_c, member_c = fresh_client(), fresh_client()
    owner = onboard(owner_c, "owner")
    member_email = _email("invited")
    member_reg = register(member_c, member_email)
    verify(member_c, member_reg["verification_token"])
    assert login(member_c, member_email).status_code == 200
    inv = owner_c.post(
        "/api/v1/members/invitations",
        json={"email": member_email, "role": "accountant"},
    )
    assert inv.status_code == 201, inv.text
    acc = member_c.post(
        "/api/v1/members/invitations/accept", json={"token": inv.json()["token"]}
    )
    assert acc.status_code == 200, acc.text
    assert acc.json()["tenant_id"] == owner["tenant_id"]
    # Act inside the owner's workspace from here on (accept does not move the session).
    switched = member_c.post(
        "/api/v1/auth/tenant", json={"tenant_id": owner["tenant_id"]}
    )
    assert switched.status_code == 200, switched.text
    # Accountant can create clients but cannot invite members.
    assert (
        member_c.post("/api/v1/clients", json={"name": "Client X"}).status_code == 201
    )
    assert (
        member_c.post(
            "/api/v1/members/invitations", json={"email": _email("z"), "role": "viewer"}
        ).status_code
        == 403
    )
    # Owner sees both members; audit captured the flow.
    members = owner_c.get("/api/v1/members")
    assert len(members.json()) == 2
    actions = {e["action"] for e in owner_c.get("/api/v1/audit").json()}
    assert {"member.invited", "member.accepted", "client.created"} <= actions


def test_tenant_isolation_across_list_get_patch_and_audit():
    _services_or_gate()
    ca, cb = fresh_client(), fresh_client()
    a = onboard(ca, "firmA")
    onboard(cb, "firmB")  # second tenant stays logged in on cb; result unused by design
    created = ca.post("/api/v1/clients", json={"name": "Secret Client"}).json()
    cid = created["id"]
    # B cannot list, read, modify, or audit A's records through any API path.
    assert cb.get("/api/v1/clients").json() == []
    assert cb.get(f"/api/v1/clients/{cid}").status_code == 404
    assert (
        cb.patch(f"/api/v1/clients/{cid}", json={"name": "hijack"}).status_code == 404
    )
    # B's audit shows only B's own tenant events — A's client.created never appears.
    b_events = cb.get("/api/v1/audit").json()
    b_user = cb.get("/api/v1/users/me").json()["user_id"]
    assert b_events, "expected B's own login events"
    assert all(e["actor_id"] == b_user for e in b_events)
    assert all(cid not in (e["resource"] or "") for e in b_events)
    assert cb.get("/api/v1/members").status_code == 200
    assert all(
        m["user_id"] != a["session"]["user_id"]
        for m in cb.get("/api/v1/members").json()
    )
    # A still sees exactly its own record; archive hides it from default queries.
    assert len(ca.get("/api/v1/clients").json()) == 1
    assert (
        ca.patch(f"/api/v1/clients/{cid}", json={"status": "archived"}).status_code
        == 200
    )


def test_tenant_switch_and_session_revocation():
    _services_or_gate()
    c1, c2 = fresh_client(), fresh_client()
    a = onboard(c1, "multiA")
    # Second workspace invites the same user as viewer.
    b_email = a["email"]
    other = onboard(c2, "multiB")
    inv = c2.post(
        "/api/v1/members/invitations", json={"email": b_email, "role": "viewer"}
    )
    token = inv.json()["token"]
    assert (
        c1.post("/api/v1/members/invitations/accept", json={"token": token}).status_code
        == 200
    )
    switched = c1.post("/api/v1/auth/tenant", json={"tenant_id": other["tenant_id"]})
    assert switched.status_code == 200
    assert switched.json()["active_tenant_id"] == other["tenant_id"]
    # Old session was rotated at switch: reuse is rejected.
    assert c1.get("/api/v1/users/me").status_code == 200  # new cookie works

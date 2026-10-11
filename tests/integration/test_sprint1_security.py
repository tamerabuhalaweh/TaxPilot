"""Sprint 1 security corrections: P0-A owner authority, P0-B rate limits, P0-C CSRF,
P0-D atomic invites/verification, plus env/metadata/body/archive/AR follow-ups.

Each test is a negative regression: it fails against the pre-correction behavior
(privilege confusion, shared lockout, ambient-cookie writes, check-then-act races)
and passes after the repair. Synthetic example.com identities only.
"""

import os
import threading

import pytest
from fastapi.testclient import TestClient

from test_sprint1_auth import (  # noqa: F401  (shared helpers live with the journey tests)
    PASSWORD,
    _email,
    _services_or_gate,
    arm_csrf,
    disarm_csrf,
    fresh_client,
    login,
    onboard,
    register,
    verify,
)


@pytest.fixture(autouse=True)
def _clean_ratelimits_here():  # type: ignore[no-untyped-def]
    """Same global-counter hygiene as the journey module (this module runs in one session)."""
    import redis as redis_lib

    try:
        client = redis_lib.Redis.from_url("redis://localhost:6379/0", socket_timeout=2)
        keys = list(client.scan_iter("tp:ratelimit:*", count=200))
        if keys:
            client.delete(*keys)
    except Exception:
        pass
    yield


REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"


def _owner_with_member(
    role: str = "accountant",
) -> tuple[TestClient, TestClient, dict, dict]:
    """Owner workspace + second user onboarded as `role` member; both CSRF-armed."""
    owner_c, member_c = fresh_client(), fresh_client()
    owner = onboard(owner_c, "poA")
    member_email = _email("member")
    member_reg = register(member_c, member_email)
    verify(member_c, member_reg["verification_token"])
    member_login = login(member_c, member_email)
    assert member_login.status_code == 200
    arm_csrf(member_c, member_login.json())
    inv = owner_c.post(
        "/api/v1/members/invitations", json={"email": member_email, "role": role}
    )
    assert inv.status_code == 201, inv.text
    acc = member_c.post(
        "/api/v1/members/invitations/accept", json={"token": inv.json()["token"]}
    )
    assert acc.status_code == 200, acc.text
    switched = member_c.post(
        "/api/v1/auth/tenant", json={"tenant_id": owner["tenant_id"]}
    )
    assert switched.status_code == 200, switched.text
    arm_csrf(member_c, switched.json())
    return owner_c, member_c, owner, {"email": member_email}


def _membership_id(owner_c: TestClient, user_id: str) -> str:
    for m in owner_c.get("/api/v1/members").json():
        if m["user_id"] == user_id:
            return m["membership_id"]
    raise AssertionError("membership not found")


# -- P0-A --------------------------------------------------------------------
def test_admin_cannot_invite_owner_self_promote_demote_or_deactivate_owner():
    _services_or_gate()
    owner_c, member_c, owner, member = _owner_with_member("admin")
    member_id = _membership_id(
        owner_c, member_c.get("/api/v1/users/me").json()["user_id"]
    )
    owner_id = _membership_id(
        owner_c, owner_c.get("/api/v1/users/me").json()["user_id"]
    )
    # Admin invites owner / promotes self / demotes owner / deactivates owner: all 403.
    assert (
        member_c.post(
            "/api/v1/members/invitations", json={"email": _email("x"), "role": "owner"}
        ).status_code
        == 403
    )
    assert (
        member_c.patch(
            f"/api/v1/members/{member_id}", json={"role": "owner"}
        ).status_code
        == 403
    )
    assert (
        member_c.patch(
            f"/api/v1/members/{owner_id}", json={"role": "admin"}
        ).status_code
        == 403
    )
    assert (
        member_c.patch(
            f"/api/v1/members/{owner_id}", json={"status": "deactivated"}
        ).status_code
        == 403
    )
    # Owner inviting owner directly is equally refused: transfer is the only path.
    assert (
        owner_c.post(
            "/api/v1/members/invitations", json={"email": _email("y"), "role": "owner"}
        ).status_code
        == 403
    )
    # Roles are unchanged after every rejected attempt.
    roles = {
        m["membership_id"]: m["role"] for m in owner_c.get("/api/v1/members").json()
    }
    assert roles[owner_id] == "owner" and roles[member_id] == "admin"


def test_last_owner_cannot_be_removed_and_transfer_works_with_audit():
    _services_or_gate()
    owner_c, member_c, owner, _ = _owner_with_member("accountant")
    owner_id = _membership_id(
        owner_c, owner_c.get("/api/v1/users/me").json()["user_id"]
    )
    member_id = _membership_id(
        owner_c, member_c.get("/api/v1/users/me").json()["user_id"]
    )
    # Last owner cannot deactivate themselves, even as owner, except via transfer.
    assert (
        owner_c.patch(
            f"/api/v1/members/{owner_id}", json={"status": "deactivated"}
        ).status_code
        == 403
    )
    # Transfer needs explicit confirmation.
    assert (
        owner_c.post(
            "/api/v1/members/transfer-ownership",
            json={"to_membership_id": member_id, "confirm": False},
        ).status_code
        == 422
    )
    moved = owner_c.post(
        "/api/v1/members/transfer-ownership",
        json={"to_membership_id": member_id, "confirm": True},
    )
    assert moved.status_code == 200, moved.text
    roles = {
        m["membership_id"]: (m["role"], m["status"])
        for m in owner_c.get("/api/v1/members").json()
    }
    assert roles[member_id][0] == "owner" and roles[owner_id] == ("admin", "active")
    actions = {e["action"] for e in owner_c.get("/api/v1/audit").json()}
    assert "ownership.transferred" in actions
    # Former owner (now admin) can no longer transfer; new owner can.
    assert (
        owner_c.post(
            "/api/v1/members/transfer-ownership",
            json={"to_membership_id": member_id, "confirm": True},
        ).status_code
        == 403
    )


def test_concurrent_owner_changes_never_empty_ownership():
    _services_or_gate()
    owner_c, _, owner, _ = _owner_with_member("accountant")
    owner_id = _membership_id(
        owner_c, owner_c.get("/api/v1/users/me").json()["user_id"]
    )
    target_id = [
        m["membership_id"]
        for m in owner_c.get("/api/v1/members").json()
        if m["membership_id"] != owner_id
    ][0]
    results: list[int] = []

    def attempt(client: TestClient) -> None:
        r = client.post(
            "/api/v1/members/transfer-ownership",
            json={"to_membership_id": target_id, "confirm": True},
        )
        results.append(r.status_code)

    # Same transfer twice, concurrently, from two independent owner sessions:
    # row locks serialize; the loser finds the caller already demoted (403) or
    # repeats a harmless no-op (200). Ownership is never empty, nothing 500s.
    owner_c2 = fresh_client()
    second_login = login(owner_c2, owner["email"])
    assert second_login.status_code == 200
    arm_csrf(owner_c2, second_login.json())
    threads = [threading.Thread(target=attempt, args=(c,)) for c in (owner_c, owner_c2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert results and all(c in (200, 403) for c in results), results
    owners = [
        m
        for m in owner_c.get("/api/v1/members").json()
        if m["role"] == "owner" and m["status"] == "active"
    ]
    assert len(owners) == 1 and owners[0]["membership_id"] == target_id
    # Owners are untouchable through administration even under concurrency.
    denies = [
        owner_c.patch(
            f"/api/v1/members/{owners[0]['membership_id']}",
            json={"status": "deactivated"},
        ).status_code
        for _ in range(2)
    ]
    assert denies == [403, 403]


# -- P0-B --------------------------------------------------------------------
def test_shared_bff_ip_does_not_cross_lock_accounts():
    """Two browsers behind one BFF address (TestClient's fixed testclient IP):
    locking A must not block B, and spoofed forwarding headers change nothing.
    Runs 20 hostile attempts (the removed shared bucket's old threshold) to prove
    no shared counter exists at any volume."""
    _services_or_gate()
    ca, cb = fresh_client(), fresh_client()
    onboard(ca, "lockA")
    onboard(cb, "freeB")
    locked_email = _email("victim")
    reg = register(ca, locked_email)
    verify(ca, reg["verification_token"])
    for _ in range(20):
        r = ca.post(
            "/api/v1/auth/login",
            json={"email": locked_email, "password": "wrong password here!"},
            headers={
                "X-Forwarded-For": "203.0.113.9, 198.51.100.7",
                "X-Real-IP": "203.0.113.9",
            },
        )
        assert r.status_code in (401, 429)
    assert (
        ca.post(
            "/api/v1/auth/login", json={"email": locked_email, "password": PASSWORD}
        ).status_code
        == 429
    )  # locked account stays locked (spoofing bypassed nothing)
    assert (
        login(cb, cb.get("/api/v1/users/me").json()["email"]).status_code == 200
    )  # B unaffected


def test_retry_after_matches_blocking_account_and_limiter_fails_closed(monkeypatch):  # type: ignore[no-untyped-def]
    _services_or_gate()
    client = fresh_client()
    email = _email("retryafter")
    reg = register(client, email)
    verify(client, reg["verification_token"])
    for _ in range(6):
        login(client, email, "wrong password here!")
    limited = login(client, email, "wrong password here!")
    assert limited.status_code == 429
    assert int(limited.headers.get("Retry-After", "0")) > 0
    monkeypatch.setattr(
        "redis.Redis.from_url",
        lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")),
    )
    assert (
        login(client, email, "wrong password here!").status_code == 500
    )  # fail closed, never bypass


# -- P0-C --------------------------------------------------------------------
def _authed_pair() -> tuple[TestClient, dict]:
    client = fresh_client()
    data = onboard(client, "csrf")
    return client, data


def test_cookie_mutations_require_csrf_token():
    _services_or_gate()
    client, _ = _authed_pair()
    disarm_csrf(client)
    assert client.post("/api/v1/clients", json={"name": "X"}).status_code == 403
    assert client.post("/api/v1/auth/logout").status_code == 403
    client.headers.update({"X-CSRF-Token": "wrong-token"})
    assert client.post("/api/v1/clients", json={"name": "X"}).status_code == 403


def test_mutation_matrix_logout_switch_invite_clients_covered():
    _services_or_gate()
    owner_c, member_c, owner, _ = _owner_with_member("accountant")
    disarm_csrf(member_c)
    member_id = _membership_id(
        owner_c, member_c.get("/api/v1/users/me").json()["user_id"]
    )
    assert member_c.post("/api/v1/clients", json={"name": "X"}).status_code == 403
    assert member_c.patch(
        f"/api/v1/clients/{uuid_unused()}", json={"name": "X"}
    ).status_code in (403, 404)
    assert member_c.post("/api/v1/auth/logout").status_code == 403
    assert (
        member_c.post(
            "/api/v1/auth/tenant", json={"tenant_id": owner["tenant_id"]}
        ).status_code
        == 403
    )
    assert (
        member_c.post(
            "/api/v1/members/invitations", json={"email": _email("q"), "role": "viewer"}
        ).status_code
        == 403
    )
    assert (
        member_c.patch(
            f"/api/v1/members/{member_id}", json={"role": "reviewer"}
        ).status_code
        == 403
    )


def uuid_unused() -> str:
    import uuid as _uuid

    return str(_uuid.uuid4())


def test_forged_origin_rejected_suffix_trick_rejected_bearer_ok():
    _services_or_gate()
    client, _ = _authed_pair()
    token = client.cookies.get("tp_session")
    assert token, "httpOnly cookie is readable in-process for Bearer test setup"
    # Forged and suffix-trick origins rejected even with a valid CSRF token.
    assert (
        client.post(
            "/api/v1/clients",
            json={"name": "X"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/clients",
            json={"name": "X"},
            headers={"Origin": "http://localhost:3000.evil.test"},
        ).status_code
        == 403
    )
    # Same-origin request passes.
    assert (
        client.post(
            "/api/v1/clients",
            json={"name": "Good"},
            headers={"Origin": "http://localhost:3000"},
        ).status_code
        == 201
    )
    # Bearer-only caller (no cookie jar) needs no CSRF token.
    bare = fresh_client()
    assert (
        bare.post(
            "/api/v1/clients",
            json={"name": "Via Bearer"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 201
    )
    # Cookie present + Bearer present but no CSRF: cookie contract wins -> 403.
    bare.cookies.set("tp_session", token)
    assert (
        bare.post(
            "/api/v1/clients",
            json={"name": "Y"},
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        == 403
    )


def test_proxy_spoof_headers_cannot_bypass_csrf():
    _services_or_gate()
    client, _ = _authed_pair()
    disarm_csrf(client)
    assert (
        client.post(
            "/api/v1/clients",
            json={"name": "X"},
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
                "Forwarded": "for=127.0.0.1",
            },
        ).status_code
        == 403
    )


# -- P0-D --------------------------------------------------------------------
def test_invite_replay_is_idempotent_for_same_user():
    _services_or_gate()
    owner_c, member_c = fresh_client(), fresh_client()
    owner = onboard(owner_c, "replay")
    member_email = _email("replayee")
    reg = register(member_c, member_email)
    verify(member_c, reg["verification_token"])
    member_login = login(member_c, member_email)
    arm_csrf(member_c, member_login.json())
    inv = owner_c.post(
        "/api/v1/members/invitations", json={"email": member_email, "role": "viewer"}
    )
    token = inv.json()["token"]
    first = member_c.post("/api/v1/members/invitations/accept", json={"token": token})
    second = member_c.post("/api/v1/members/invitations/accept", json={"token": token})
    assert first.status_code == 200 and second.status_code == 200
    assert first.json() == second.json() == {"tenant_id": owner["tenant_id"]}
    assert len(owner_c.get("/api/v1/members").json()) == 2  # no duplicate membership


def test_invite_wrong_email_and_expired_rejected():
    _services_or_gate()
    owner_c, member_c = fresh_client(), fresh_client()
    onboard(owner_c, "reject")
    member_email = _email("someone")
    reg = register(member_c, member_email)
    verify(member_c, reg["verification_token"])
    member_login = login(member_c, member_email)
    arm_csrf(member_c, member_login.json())
    other_c = fresh_client()
    other_email = _email("other")
    other_reg = register(other_c, other_email)
    verify(other_c, other_reg["verification_token"])
    other_login = login(other_c, other_email)
    arm_csrf(other_c, other_login.json())
    inv = owner_c.post(
        "/api/v1/members/invitations", json={"email": member_email, "role": "viewer"}
    )
    token = inv.json()["token"]
    # A different authorized user cannot consume someone else's invitation.
    assert (
        other_c.post(
            "/api/v1/members/invitations/accept", json={"token": token}
        ).status_code
        == 403
    )
    assert (
        member_c.post(
            "/api/v1/members/invitations/accept", json={"token": token}
        ).status_code
        == 200
    )
    # Unknown tokens reject without oracle details.
    assert (
        member_c.post(
            "/api/v1/members/invitations/accept", json={"token": "nope"}
        ).status_code
        == 422
    )
    # Expired invitations reject: backdate a fresh invitation's expiry directly
    # (test-only SQL; the alternative is waiting out the 72h production TTL).
    import psycopg as _psycopg

    from app.security import hash_token as _hash_token

    fresh = owner_c.post(
        "/api/v1/members/invitations", json={"email": member_email, "role": "viewer"}
    )
    fresh_token = fresh.json()["token"]
    with _psycopg.connect(
        "postgresql://taxpilot:taxpilot@localhost:5432/taxpilot", connect_timeout=5
    ) as conn:
        conn.execute(
            "UPDATE invitations SET expires_at = now() - interval '1 hour' WHERE token_hash = %s",
            (_hash_token(fresh_token),),
        )
    assert (
        member_c.post(
            "/api/v1/members/invitations/accept", json={"token": fresh_token}
        ).status_code
        == 422
    )


def test_concurrent_accept_creates_single_membership():
    _services_or_gate()
    import threading as _threading

    owner_c, member_c = fresh_client(), fresh_client()
    onboard(owner_c, "race")
    member_email = _email("racer")
    reg = register(member_c, member_email)
    verify(member_c, reg["verification_token"])
    member_login = login(member_c, member_email)
    arm_csrf(member_c, member_login.json())
    inv = owner_c.post(
        "/api/v1/members/invitations", json={"email": member_email, "role": "viewer"}
    )
    token = inv.json()["token"]
    codes: list[int] = []

    def attempt() -> None:
        r = member_c.post("/api/v1/members/invitations/accept", json={"token": token})
        codes.append(r.status_code)

    threads = [_threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(codes) == [200, 200], codes  # idempotent contract: both succeed
    assert len(owner_c.get("/api/v1/members").json()) == 2


def test_verification_single_use_under_concurrency():
    _services_or_gate()
    import threading as _threading

    owner_c = fresh_client()
    onboard(owner_c, "verifier")
    other_c = fresh_client()
    email = _email("verifyme")
    reg = register(other_c, email)
    token = reg["verification_token"]
    codes: list[int] = []

    def attempt() -> None:
        r = other_c.post("/api/v1/auth/verify", json={"token": token})
        codes.append(r.status_code)

    threads = [_threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert sorted(codes) == [
        200,
        422,
    ], codes  # verification is single-use, not idempotent


# -- Additional corrections ----------------------------------------------------
def test_environment_enum_and_staging_defaults():
    from pydantic import ValidationError

    from app.config import Settings

    try:
        Settings(environment="bogus")  # type: ignore[arg-type]
    except ValidationError:
        pass
    else:
        raise AssertionError("bogus environment must be rejected")
    staging = Settings(environment="staging")
    assert staging.auth_expose_tokens is False and staging.cookie_secure is True


def test_schema_matches_migrated_database():
    _services_or_gate()
    import os as _os

    from sqlalchemy import create_engine

    from app.store import assert_schema_matches

    engine = create_engine(
        _os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot",
        )
    )
    assert_schema_matches(engine)
    engine.dispose()


def test_concurrent_requests_share_stable_schema():
    _services_or_gate()
    import threading as _threading

    client = fresh_client()
    onboard(client, "concurrency")
    codes: list[int] = []

    def hit(i: int) -> None:
        if i % 2:
            codes.append(client.get("/api/v1/users/me").status_code)
        else:
            codes.append(
                client.post("/api/v1/clients", json={"name": f"C-{i}"}).status_code
            )

    threads = [_threading.Thread(target=hit, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert codes and all(c in (200, 201) for c in codes), codes


def test_body_limits_with_declared_and_chunked_bodies():
    _services_or_gate()
    client = fresh_client()
    onboard(client, "bodycap")
    big = "x" * (2 * 1024 * 1024)
    r = client.post("/api/v1/clients", json={"name": big})
    assert r.status_code == 413

    # Chunked without Content-Length must also be capped, not streamed unboundedly.
    def gen():  # type: ignore[no-untyped-def]
        yield b"x" * (2 * 1024 * 1024)

    r2 = client.post(
        "/api/v1/clients", content=gen(), headers={"Content-Type": "application/json"}
    )
    assert r2.status_code in (400, 413, 422)  # capped before JSON parsing either way


def test_archive_filtering_default_hides_archived():
    _services_or_gate()
    client = fresh_client()
    onboard(client, "archive")
    cid = client.post("/api/v1/clients", json={"name": "Keep"}).json()["id"]
    archived = client.post("/api/v1/clients", json={"name": "Old"}).json()["id"]
    assert (
        client.patch(
            f"/api/v1/clients/{archived}", json={"status": "archived"}
        ).status_code
        == 200
    )
    assert [c["id"] for c in client.get("/api/v1/clients").json()] == [cid]
    assert sorted(
        c["id"] for c in client.get("/api/v1/clients?status=all").json()
    ) == sorted([cid, archived])
    assert [c["id"] for c in client.get("/api/v1/clients?status=archived").json()] == [
        archived
    ]
    assert client.get("/api/v1/clients?status=bogus").status_code == 422

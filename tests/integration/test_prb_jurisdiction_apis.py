"""PR-B integration: LegalEntity/TaxContext APIs over real FastAPI + PostgreSQL.

Covers issue #46 §7: entity CRUD, IDOR, RBAC, transitions, concurrency,
idempotency, snapshot/hash, trigger immutability, audit, fail-closed
registration writes, no-invention. Synthetic data only (example.com).

Service-gating mirrors the suite: REQUIRE_SERVICES=1 fails closed, locally the
DATABASE_URL/REDIS_URL environment selects the target (isolated scratch DBs).
"""

import os
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
)
PASSWORD = "correct horse battery staple"


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _services_or_gate() -> None:
    import psycopg

    try:
        with psycopg.connect(_libpq(DATABASE_URL), connect_timeout=5) as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"postgres unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"postgres unreachable (documented optional local mode): {exc}")


def fresh_client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _email(tag: str) -> str:
    return f"prb-{tag}-{uuid.uuid4().hex[:8]}@example.com"


def register(client: TestClient, email: str, firm: str = "PRB Firm") -> dict:
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "firm_name": firm},
    )
    assert r.status_code == 201, r.text
    return r.json()


def verify(client: TestClient, token: str) -> None:
    r = client.post("/api/v1/auth/verify", json={"token": token})
    assert r.status_code == 200, r.text


def login(client: TestClient, email: str):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )


def arm_csrf(client: TestClient, login_body: dict) -> None:
    token = login_body.get("csrf_token")
    assert token, "login must issue a CSRF token"
    client.headers.update({"X-CSRF-Token": token})


def onboard(tag: str) -> dict:
    """Fresh firm (owner) with armed CSRF + one client. Returns ids + client."""
    _services_or_gate()
    client = fresh_client()
    email = _email(tag)
    reg = register(client, email)
    assert reg["verification_token"], "dev token exposure required for test onboarding"
    verify(client, reg["verification_token"])
    r = login(client, email)
    assert r.status_code == 200, r.text
    arm_csrf(client, r.json())
    session = r.json()
    tenant_id = session["active_tenant_id"]
    r = client.post("/api/v1/clients", json={"name": f"client-{tag}"})
    assert r.status_code == 201, r.text
    return {
        "client": client,
        "email": email,
        "user_id": session["user_id"],
        "tenant_id": tenant_id,
        "client_id": r.json()["id"],
    }


def invite(client: TestClient, email: str, role: str) -> str:
    r = client.post("/api/v1/members/invitations", json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert token, "dev invitation token required"
    return token


def join_as(tag: str, owner: dict, role: str) -> dict:
    """Second user joins owner's firm with the given role (armed client)."""
    client = fresh_client()
    email = _email(tag)
    reg = register(client, email, firm="Joiner Firm")
    verify(client, reg["verification_token"])
    token = invite(owner["client"], email, role)
    r = login(client, email)
    assert r.status_code == 200, r.text
    arm_csrf(client, r.json())
    r = client.post("/api/v1/members/invitations/accept", json={"token": token})
    assert r.status_code == 200, r.text
    assert r.json()["tenant_id"] == owner["tenant_id"]
    # Switch into the joined workspace (login alone may land on the joiner's own firm).
    r = client.post("/api/v1/auth/tenant", json={"tenant_id": owner["tenant_id"]})
    assert r.status_code == 200, r.text
    arm_csrf(client, r.json())
    assert r.json()["active_tenant_id"] == owner["tenant_id"]
    return {
        "client": client,
        "email": email,
        "user_id": r.json()["user_id"],
        "tenant_id": owner["tenant_id"],
    }


def clone_client(src: TestClient) -> TestClient:
    """Independent TestClient carrying the same session cookies + CSRF (concurrency)."""
    client = fresh_client()
    for cookie in src.cookies.jar:
        client.cookies.set(
            cookie.name, cookie.value, domain=cookie.domain, path=cookie.path
        )
    if "X-CSRF-Token" in src.headers:
        client.headers.update({"X-CSRF-Token": src.headers["X-CSRF-Token"]})
    return client


def make_entity(
    owner: dict,
    client_id: str | None = None,
    name: str | None = None,
    country: str = "JO",
    currency: str = "JOD",
    extra: dict | None = None,
):
    body = {
        "client_id": client_id or owner["client_id"],
        "legal_name": name or f"Entity {uuid.uuid4().hex[:8]}",
        "incorporation_country_code": country,
        "base_currency": currency,
    }
    if extra:
        body.update(extra)
    return owner["client"].post("/api/v1/legal-entities", json=body)


def make_context(
    owner: dict,
    entity_id: str,
    client_id: str | None = None,
    period_start: str = "2026-01-01",
    period_end: str = "2026-12-31",
    extra: dict | None = None,
):
    body = {
        "client_id": client_id or owner["client_id"],
        "subject_entity_id": entity_id,
        "jurisdiction_code": "JO",
        "tax_type_code": "ACCOUNTING_ONLY",
        "period_start": period_start,
        "period_end": period_end,
    }
    if extra:
        body.update(extra)
    return owner["client"].post("/api/v1/tax-contexts", json=body)


def confirm_flow(owner: dict, context_id: str):
    c = owner["client"]
    r = c.post(f"/api/v1/tax-contexts/{context_id}/request-confirmation")
    assert r.status_code == 200, r.text
    r = c.post(f"/api/v1/tax-contexts/{context_id}/confirm")
    assert r.status_code == 200, r.text
    return r.json()


def sql_count(table: str, where: str = "", params: tuple = ()) -> int:
    import psycopg

    with psycopg.connect(_libpq(DATABASE_URL), connect_timeout=5) as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table} {where}", params).fetchone()
        assert row is not None
        return int(row[0])


def sql_insert_obligation(
    tenant_id: str,
    client_id: str,
    entity_id: str,
    jurisdiction: str = "JO",
    tax_type: str = "VAT",
    valid_from: str = "2026-01-01",
    valid_to: str | None = None,
    status: str = "UNKNOWN",
) -> str:
    import psycopg

    oid = str(uuid.uuid4())
    with psycopg.connect(_libpq(DATABASE_URL), connect_timeout=10) as conn:
        conn.execute(
            "INSERT INTO tax_obligation_profiles (id, tenant_id, client_id, legal_entity_id,"
            " jurisdiction_code, tax_type_code, valid_from, valid_to, registration_status)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                oid,
                tenant_id,
                client_id,
                entity_id,
                jurisdiction,
                tax_type,
                valid_from,
                valid_to,
                status,
            ),
        )
        conn.commit()
    return oid


def sql_insert_registration(
    tenant_id: str,
    obligation_id: str,
    ciphertext: bytes = b"\x00" * 32,
    nonce: bytes = b"\x01" * 12,
    key_id: str = "k-prb-1",
    last4: str = "4321",
) -> str:
    import psycopg

    rid = str(uuid.uuid4())
    with psycopg.connect(_libpq(DATABASE_URL), connect_timeout=10) as conn:
        conn.execute(
            "INSERT INTO tax_registrations (id, tenant_id, obligation_profile_id,"
            " authority_code, registration_kind, number_ciphertext, number_nonce, key_id, number_last4)"
            " VALUES (%s,%s,%s,'JO-ISTD','VAT',%s,%s,%s,%s)",
            (rid, tenant_id, obligation_id, ciphertext, nonce, key_id, last4),
        )
        conn.commit()
    return rid


# -- legal entities ------------------------------------------------------------
def test_entity_crud_happy_path():
    owner = onboard("entity-crud")
    r = make_entity(owner, name="Acme JO LLC")
    assert r.status_code == 201, r.text
    entity = r.json()
    assert entity["incorporation_country_code"] == "JO"
    assert entity["base_currency"] == "JOD"
    assert entity["status"] == "SUGGESTED"
    assert "legal_identifier_ciphertext" not in entity
    eid = entity["id"]
    r = owner["client"].get(f"/api/v1/legal-entities/{eid}")
    assert r.status_code == 200 and r.json()["legal_name"] == "Acme JO LLC"
    r = owner["client"].get(
        "/api/v1/legal-entities", params={"client_id": owner["client_id"]}
    )
    assert r.status_code == 200 and any(e["id"] == eid for e in r.json())
    r = owner["client"].patch(
        f"/api/v1/legal-entities/{eid}",
        json={"legal_name": "Acme JO Ltd", "status": "DRAFT"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["legal_name"] == "Acme JO Ltd"
    assert r.json()["status"] == "DRAFT"


def test_entity_validation_errors():
    owner = onboard("entity-validation")
    # Bad currency.
    r = make_entity(owner, currency="JODD")
    assert r.status_code == 422, r.text
    r = make_entity(owner, currency="jod")
    assert r.status_code == 201, r.text  # normalized to uppercase
    assert r.json()["base_currency"] == "JOD"
    # Unknown country.
    r = make_entity(owner, country="XX")
    assert r.status_code == 422, r.text
    # Empty name.
    r = make_entity(owner, name="   ")
    assert r.status_code == 422, r.text
    # Bad fiscal start.
    r = make_entity(owner, extra={"fiscal_start": "13-99"})
    assert r.status_code == 422, r.text
    # Unknown client.
    r = make_entity(owner, client_id=str(uuid.uuid4()))
    assert r.status_code == 404, r.text
    # AE incorporation is a user-supplied fact (allowed; non-executable).
    r = make_entity(owner, country="AE")
    assert r.status_code == 201, r.text


def test_entity_identifier_rejected_fail_closed():
    owner = onboard("entity-identifier")
    before = sql_count("legal_entities")
    r = make_entity(owner, extra={"legal_identifier": "national-id-SECRET-123"})
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FEATURE_DISABLED"
    assert sql_count("legal_entities") == before  # nothing persisted
    import psycopg

    with psycopg.connect(_libpq(DATABASE_URL), connect_timeout=5) as conn:
        rows = conn.execute(
            "SELECT legal_identifier_ciphertext FROM legal_entities"
        ).fetchall()
    assert all(row[0] is None for row in rows)
    # Audit records the rejection WITHOUT the secret value anywhere.
    r = owner["client"].get("/api/v1/audit")
    assert r.status_code == 200
    actions = [e["action"] for e in r.json()]
    assert "legalentity.identifier_rejected" in actions
    assert "SECRET" not in r.text


def test_entity_name_conflict_and_status_terminal():
    owner = onboard("entity-conflict")
    assert make_entity(owner, name="DupCo").status_code == 201
    r = make_entity(owner, name="DupCo")
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "STATE_CONFLICT"
    eid = make_entity(owner, name="EndCo").json()["id"]
    assert (
        owner["client"]
        .patch(f"/api/v1/legal-entities/{eid}", json={"status": "ENDED"})
        .status_code
        == 200
    )
    r = owner["client"].patch(f"/api/v1/legal-entities/{eid}", json={"status": "DRAFT"})
    assert r.status_code == 422, r.text  # ENDED is terminal
    # Same name reusable after ENDED (partial unique index excludes ENDED).
    assert make_entity(owner, name="EndCo").status_code == 201


def test_entity_parent_rules():
    owner = onboard("entity-parent")
    other = onboard("entity-parent-other")
    parent = make_entity(owner, name="ParentCo").json()
    r = make_entity(
        owner, name="ChildCo", extra={"parent_legal_entity_id": parent["id"]}
    )
    assert r.status_code == 201, r.text
    # Cross-tenant parent invisible.
    r = make_entity(
        owner,
        name="OrphanCo",
        extra={"parent_legal_entity_id": make_entity(other).json()["id"]},
    )
    assert r.status_code == 404, r.text
    child_id = make_entity(owner, name="SelfCo").json()["id"]
    r = owner["client"].patch(
        f"/api/v1/legal-entities/{child_id}", json={"parent_legal_entity_id": child_id}
    )
    assert r.status_code == 422, r.text
    # Identity immutable via patch.
    r = owner["client"].patch(
        f"/api/v1/legal-entities/{child_id}", json={"client_id": other["client_id"]}
    )
    assert r.status_code == 422, r.text


def test_entity_idor_across_tenants():
    owner_a = onboard("entity-idor-a")
    owner_b = onboard("entity-idor-b")
    eid = make_entity(owner_a, name="SecretCo").json()["id"]
    assert owner_b["client"].get(f"/api/v1/legal-entities/{eid}").status_code == 404
    r = owner_b["client"].get("/api/v1/legal-entities")
    assert r.status_code == 200
    assert all(e["id"] != eid for e in r.json())
    assert (
        owner_b["client"]
        .patch(f"/api/v1/legal-entities/{eid}", json={"legal_name": "X"})
        .status_code
        == 404
    )
    # Cross-tenant client reference invisible.
    r = make_entity(owner_b, client_id=owner_a["client_id"])
    assert r.status_code == 404, r.text


def test_entity_rbac_anonymous_and_viewer():
    owner = onboard("entity-rbac")
    viewer = join_as("entity-viewer", owner, "viewer")
    eid = make_entity(owner, name="RBACCo").json()["id"]
    # Anonymous: 401 everywhere.
    anon = fresh_client()
    assert anon.get("/api/v1/legal-entities").status_code == 401
    assert anon.get(f"/api/v1/legal-entities/{eid}").status_code == 401
    assert anon.post("/api/v1/legal-entities", json={}).status_code == 401
    # Viewer reads, never mutates.
    assert viewer["client"].get("/api/v1/legal-entities").status_code == 200
    assert viewer["client"].get(f"/api/v1/legal-entities/{eid}").status_code == 200
    assert make_entity(viewer, client_id=owner["client_id"]).status_code == 403
    assert (
        viewer["client"]
        .patch(f"/api/v1/legal-entities/{eid}", json={"legal_name": "Y"})
        .status_code
        == 403
    )


# -- tax contexts: lifecycle ---------------------------------------------------
def test_context_create_and_get():
    owner = onboard("ctx-create")
    eid = make_entity(owner).json()["id"]
    r = make_context(owner, eid)
    assert r.status_code == 201, r.text
    ctx = r.json()
    assert ctx["confirmation_status"] == "DRAFT"
    assert ctx["context_revision"] == 1
    assert ctx["context_hash"] is None
    assert ctx["snapshot"] is None
    assert ctx["subject_kind"] == "LEGAL_ENTITY"
    assert (
        ctx["accounting_only_disclaimer"]
        and "ACCOUNTING_ONLY" in ctx["accounting_only_disclaimer"]
    )
    xid = ctx["id"]
    r = owner["client"].get(f"/api/v1/tax-contexts/{xid}")
    assert r.status_code == 200 and r.json()["id"] == xid
    r = owner["client"].get(
        "/api/v1/tax-contexts", params={"client_id": owner["client_id"]}
    )
    assert r.status_code == 200 and any(c["id"] == xid for c in r.json())


def test_context_create_validation():
    owner = onboard("ctx-validation")
    eid = make_entity(owner).json()["id"]
    # Non-JO jurisdiction: honest non-execution boundary.
    r = make_context(owner, eid, extra={"jurisdiction_code": "AE"})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "JURISDICTION_NOT_SUPPORTED"
    r = make_context(owner, eid, extra={"jurisdiction_code": "XX"})
    assert r.status_code == 422, r.text
    # Invented statutory tax type rejected.
    r = make_context(owner, eid, extra={"tax_type_code": "VAT"})
    assert r.status_code == 422, r.text
    # Inverted period rejected.
    r = make_context(owner, eid, period_start="2026-12-31", period_end="2026-01-01")
    assert r.status_code == 422, r.text
    # Unknown entity / foreign client.
    r = make_context(owner, str(uuid.uuid4()))
    assert r.status_code == 404, r.text
    other = onboard("ctx-validation-other")
    other_eid = make_entity(other).json()["id"]
    r = make_context(owner, other_eid)  # cross-tenant entity invisible
    assert r.status_code == 404, r.text
    # Same tenant, other client entity cannot back another client's context.
    r = owner["client"].post("/api/v1/clients", json={"name": "second"})
    assert r.status_code == 201
    cid2 = r.json()["id"]
    eid2 = make_entity(owner, client_id=cid2).json()["id"]
    r = make_context(owner, eid2)  # entity of client2 under client1
    assert r.status_code == 404, r.text


def test_context_obligation_match_validation():
    owner = onboard("ctx-obligation")
    eid = make_entity(owner).json()["id"]
    eid_other = make_entity(owner, name="OtherEnt").json()["id"]
    oid = sql_insert_obligation(owner["tenant_id"], owner["client_id"], eid)
    # Happy path with UNKNOWN registration status (UNKNOWN never blocks).
    r = make_context(owner, eid, extra={"obligation_profile_id": oid})
    assert r.status_code == 201, r.text
    assert r.json()["obligation_profile_id"] == oid
    assert r.json()["profile_version"] == 1
    # Obligation bound to a different entity.
    r = make_context(owner, eid_other, extra={"obligation_profile_id": oid})
    assert r.status_code == 422, r.text
    # Obligation in another jurisdiction.
    oid_ae = sql_insert_obligation(
        owner["tenant_id"], owner["client_id"], eid, jurisdiction="AE"
    )
    r = make_context(owner, eid, extra={"obligation_profile_id": oid_ae})
    assert r.status_code == 422, r.text
    # Context period outside the obligation window.
    oid_narrow = sql_insert_obligation(
        owner["tenant_id"],
        owner["client_id"],
        eid,
        valid_from="2026-06-01",
        valid_to="2026-06-30",
    )
    r = make_context(owner, eid, extra={"obligation_profile_id": oid_narrow})
    assert r.status_code == 422, r.text
    # Cross-client obligation invisible.
    r = owner["client"].post("/api/v1/clients", json={"name": "c2"})
    cid2 = r.json()["id"]
    eid2 = make_entity(owner, client_id=cid2).json()["id"]
    oid2 = sql_insert_obligation(owner["tenant_id"], cid2, eid2)
    r = make_context(owner, eid, extra={"obligation_profile_id": oid2})
    assert r.status_code == 404, r.text
    # Unknown obligation id.
    r = make_context(owner, eid, extra={"obligation_profile_id": str(uuid.uuid4())})
    assert r.status_code == 404, r.text


def test_context_transitions_and_idempotency():
    owner = onboard("ctx-transitions")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    c = owner["client"]
    # Confirm requires the review step.
    assert c.post(f"/api/v1/tax-contexts/{xid}/confirm").status_code == 409
    # Request twice: idempotent.
    assert c.post(f"/api/v1/tax-contexts/{xid}/request-confirmation").status_code == 200
    r = c.post(f"/api/v1/tax-contexts/{xid}/request-confirmation")
    assert (
        r.status_code == 200 and r.json()["confirmation_status"] == "NEEDS_CONFIRMATION"
    )
    # Confirm twice (same actor): idempotent, byte-identical.
    first = c.post(f"/api/v1/tax-contexts/{xid}/confirm").json()
    assert first["confirmation_status"] == "CONFIRMED"
    second = c.post(f"/api/v1/tax-contexts/{xid}/confirm").json()
    assert second == first
    # Request on a confirmed row conflicts.
    assert c.post(f"/api/v1/tax-contexts/{xid}/request-confirmation").status_code == 409
    # Patch on a confirmed row conflicts (trigger would too).
    assert (
        c.patch(
            f"/api/v1/tax-contexts/{xid}", json={"period_end": "2026-06-30"}
        ).status_code
        == 409
    )
    # Revise on a non-confirmed row conflicts.
    xid2 = make_context(owner, eid).json()["id"]
    assert c.post(f"/api/v1/tax-contexts/{xid2}/revise").status_code == 409


def test_context_patch_working_fields_and_frozen_rejects():
    owner = onboard("ctx-patch")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    c = owner["client"]
    r = c.patch(f"/api/v1/tax-contexts/{xid}", json={"period_end": "2026-09-30"})
    assert r.status_code == 200 and r.json()["period_end"] == "2026-09-30"
    r = c.patch(f"/api/v1/tax-contexts/{xid}", json={"period_start": "2027-01-01"})
    assert r.status_code == 422  # inverted after merge
    for frozen in (
        "client_id",
        "subject_entity_id",
        "obligation_profile_id",
        "jurisdiction_code",
        "tax_type_code",
    ):
        r = c.patch(f"/api/v1/tax-contexts/{xid}", json={frozen: str(uuid.uuid4())})
        assert r.status_code == 422, frozen


def test_context_confirm_idempotent_across_actors_conflicts():
    owner = onboard("ctx-actors")
    partner = join_as("ctx-partner", owner, "accountant")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    confirm_flow(owner, xid)
    # A different authorized actor cannot re-confirm someone else's frozen row.
    r = partner["client"].post(f"/api/v1/tax-contexts/{xid}/confirm")
    assert r.status_code == 409, r.text
    # ...but reads it fine.
    assert partner["client"].get(f"/api/v1/tax-contexts/{xid}").status_code == 200


def test_concurrent_confirm_same_actor_serializes():
    owner = onboard("ctx-conc-same")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    owner["client"].post(f"/api/v1/tax-contexts/{xid}/request-confirmation")
    results = []
    lock = threading.Lock()

    def run() -> None:
        client = clone_client(owner["client"])
        r = client.post(f"/api/v1/tax-contexts/{xid}/confirm")
        with lock:
            results.append((r.status_code, r.json()))

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(results) == 6
    assert all(code == 200 for code, _ in results)
    hashes = {body["context_hash"] for _, body in results}
    assert len(hashes) == 1 and None not in hashes
    # Exactly one confirmation audit (replays add none).
    audits = owner["client"].get("/api/v1/audit").json()
    confirms = [
        a
        for a in audits
        if a["action"] == "taxcontext.confirmed" and xid in (a["resource"] or "")
    ]
    assert len(confirms) == 1


def test_concurrent_confirm_distinct_actors_single_winner():
    owner = onboard("ctx-conc-diff")
    partner = join_as("ctx-conc-partner", owner, "accountant")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    owner["client"].post(f"/api/v1/tax-contexts/{xid}/request-confirmation")
    results = []
    lock = threading.Lock()

    def run(client_bundle: dict) -> None:
        client = clone_client(client_bundle["client"])
        r = client.post(f"/api/v1/tax-contexts/{xid}/confirm")
        with lock:
            results.append(r.status_code)

    threads = [
        threading.Thread(target=run, args=(b,))
        for b in (owner, partner)
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(results) == 6
    # Whoever commits first wins for their whole side (same-actor replays are
    # idempotent 200s); the other side re-reads CONFIRMED-by-other → 409.
    assert sorted(results) == [200, 200, 200, 409, 409, 409]
    # Exactly one winner overall: a single confirm audit, single frozen hash.
    audits = owner["client"].get("/api/v1/audit").json()
    confirms = [
        a
        for a in audits
        if a["action"] == "taxcontext.confirmed" and xid in (a["resource"] or "")
    ]
    assert len(confirms) == 1
    final = owner["client"].get(f"/api/v1/tax-contexts/{xid}").json()
    assert final["confirmation_status"] == "CONFIRMED"


def test_revise_creates_new_row_preserving_old():
    owner = onboard("ctx-revise")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    old = confirm_flow(owner, xid)
    r = owner["client"].post(f"/api/v1/tax-contexts/{xid}/revise")
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["id"] != xid
    assert new["confirmation_status"] == "DRAFT"
    assert new["context_revision"] == old["context_revision"] + 1
    assert new["context_hash"] is None and new["snapshot"] is None
    # Old row byte-identical (frozen snapshot + hash untouched).
    again = owner["client"].get(f"/api/v1/tax-contexts/{xid}").json()
    assert again == old
    # The revision confirms independently with a different hash.
    owner["client"].patch(
        f"/api/v1/tax-contexts/{new['id']}", json={"period_end": "2026-06-30"}
    )
    new_confirmed = confirm_flow(owner, new["id"])
    assert new_confirmed["context_hash"] != old["context_hash"]


# -- snapshot + hash -----------------------------------------------------------
def test_snapshot_hash_deterministic_and_sensitive():
    from app.snapshot import canonical_json, snapshot_from_row, snapshot_hash

    owner = onboard("ctx-hash")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    confirmed = confirm_flow(owner, xid)
    stored = confirmed["snapshot"]
    assert stored["snapshot_version"] == 1
    assert stored["obligation_profile_id"] is None and stored["profile_version"] is None
    assert stored["confirmed_by"] == owner["user_id"]
    assert set(stored) == {
        "snapshot_version",
        "tenant_id",
        "client_id",
        "subject_kind",
        "subject_entity_id",
        "jurisdiction_code",
        "tax_type_code",
        "regime_code",
        "obligation_profile_id",
        "profile_version",
        "period_start",
        "period_end",
        "context_revision",
        "pack_version",
        "confirmation_status",
        "confirmed_by",
        "confirmed_at",
        "created_at",
    }
    # Rebuild from the API shape (+ tenant, implicit in responses) reproduces the stored hash.
    rebuilt = snapshot_from_row({**confirmed, "tenant_id": owner["tenant_id"]})
    assert snapshot_hash(rebuilt) == confirmed["context_hash"]
    assert canonical_json(rebuilt) == canonical_json(stored)
    # Any frozen input change alters the hash.
    altered = dict(rebuilt)
    altered["period_end"] = "2026-06-30"
    assert snapshot_hash(altered) != confirmed["context_hash"]
    altered2 = dict(rebuilt)
    altered2["confirmed_by"] = str(uuid.uuid4())
    assert snapshot_hash(altered2) != confirmed["context_hash"]


def test_hash_is_not_an_authorization_token():
    owner = onboard("ctx-hashauth")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    confirmed = confirm_flow(owner, xid)
    anon = fresh_client()
    # Knowledge of id + hash grants nothing without a session.
    assert anon.get(f"/api/v1/tax-contexts/{xid}").status_code == 401
    assert anon.post(f"/api/v1/tax-contexts/{xid}/confirm").status_code == 401
    assert confirmed["context_hash"]


def test_confirmed_row_rejected_at_database():
    import psycopg

    owner = onboard("ctx-trigger")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    confirm_flow(owner, xid)
    with psycopg.connect(_libpq(DATABASE_URL), connect_timeout=5) as conn:
        with pytest.raises(Exception, match="immutable"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tax_contexts SET period_end = '2026-06-30' WHERE id = %s",
                    (xid,),
                )
        conn.rollback()


# -- registrations: fail-closed + masked reads ---------------------------------
def test_registration_writes_disabled():
    owner = onboard("reg-disabled")
    before = sql_count("tax_registrations")
    r = owner["client"].post(
        "/api/v1/tax-registrations",
        json={
            "authority_code": "JO-ISTD",
            "registration_kind": "VAT",
            "number_last4": "1234",
        },
    )
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "FEATURE_DISABLED"
    r = owner["client"].post("/api/v1/tax-registrations", json={})
    assert r.status_code == 403, r.text
    assert sql_count("tax_registrations") == before
    audits = owner["client"].get("/api/v1/audit").json()
    assert any(a["action"] == "registration.create_rejected" for a in audits)


def test_registration_masked_reads_hide_crypto():
    owner = onboard("reg-masked")
    other = onboard("reg-masked-other")
    eid = make_entity(owner).json()["id"]
    oid = sql_insert_obligation(owner["tenant_id"], owner["client_id"], eid)
    rid = sql_insert_registration(owner["tenant_id"], oid)
    r = owner["client"].get(f"/api/v1/tax-registrations/{rid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["number_last4"] == "4321"
    assert body["authority_code"] == "JO-ISTD"
    for hidden in ("number_ciphertext", "number_nonce", "key_id"):
        assert hidden not in body, hidden
    r = owner["client"].get(
        "/api/v1/tax-registrations", params={"obligation_profile_id": oid}
    )
    assert r.status_code == 200 and any(x["id"] == rid for x in r.json())
    # Cross-tenant invisibility + unknown obligation filter.
    assert other["client"].get(f"/api/v1/tax-registrations/{rid}").status_code == 404
    assert (
        owner["client"]
        .get(
            "/api/v1/tax-registrations",
            params={"obligation_profile_id": str(uuid.uuid4())},
        )
        .status_code
        == 404
    )


# -- catalog, audit, no-invention, walkthrough ---------------------------------
def test_jurisdiction_catalog_honest_availability():
    owner = onboard("catalog")
    r = owner["client"].get("/api/v1/jurisdictions")
    assert r.status_code == 200
    by_code = {j["code"]: j for j in r.json()}
    assert by_code["JO"]["availability"] == "ACTIVE"
    assert by_code["JO"]["capabilities"]["tax_types"] == []
    assert by_code["JO"]["capabilities"]["rules"] == []
    assert by_code["AE"]["availability"] == "PLANNED"
    assert by_code["SA"]["availability"] == "PLANNED"
    assert fresh_client().get("/api/v1/jurisdictions").status_code == 401


def test_audit_actor_time_action_correctness():
    owner = onboard("audit")
    eid = make_entity(owner, name="AuditCo").json()["id"]
    xid = make_context(owner, eid).json()["id"]
    confirm_flow(owner, xid)
    audits = owner["client"].get("/api/v1/audit").json()
    by_action: dict = {}
    for a in audits:
        by_action.setdefault(a["action"], []).append(a)
    for action in (
        "legalentity.created",
        "taxcontext.created",
        "taxcontext.confirmation_requested",
        "taxcontext.confirmed",
    ):
        assert action in by_action, action
        for entry in by_action[action]:
            assert entry["actor_id"] == owner["user_id"]
            assert entry["request_id"], "correlation id required"
            assert entry["created_at"]
    # Tenant B sees none of tenant A's actions.
    other = onboard("audit-other")
    other_audits = other["client"].get("/api/v1/audit").json()
    assert not any(xid in (a.get("resource") or "") for a in other_audits)


def test_no_invented_rows_on_reads_and_creates():
    owner = onboard("no-invent")
    eid = make_entity(owner).json()["id"]
    base = {
        "obligations": sql_count("tax_obligation_profiles"),
        "registrations": sql_count("tax_registrations"),
        "contexts": sql_count("tax_contexts"),
    }
    c = owner["client"]
    c.get("/api/v1/legal-entities")
    c.get("/api/v1/tax-contexts")
    c.get("/api/v1/jurisdictions")
    c.post("/api/v1/clients", json={"name": "extra"})
    assert sql_count("tax_obligation_profiles") == base["obligations"]
    assert sql_count("tax_registrations") == base["registrations"]
    assert sql_count("tax_contexts") == base["contexts"]
    # Explicit user creation is the ONLY writer.
    make_context(owner, eid)
    assert sql_count("tax_contexts") == base["contexts"] + 1
    assert sql_count("tax_obligation_profiles") == base["obligations"]
    assert sql_count("tax_registrations") == base["registrations"]


def test_context_rbac_and_idor():
    owner = onboard("ctx-rbac")
    viewer = join_as("ctx-viewer", owner, "viewer")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    anon = fresh_client()
    assert anon.get("/api/v1/tax-contexts").status_code == 401
    assert (
        anon.post(f"/api/v1/tax-contexts/{xid}/request-confirmation").status_code == 401
    )
    assert anon.post(f"/api/v1/tax-contexts/{xid}/confirm").status_code == 401
    assert viewer["client"].get(f"/api/v1/tax-contexts/{xid}").status_code == 200
    assert viewer["client"].post("/api/v1/tax-contexts", json={}).status_code in (
        403,
        422,
    )
    assert (
        viewer["client"]
        .post(f"/api/v1/tax-contexts/{xid}/request-confirmation")
        .status_code
        == 403
    )
    other = onboard("ctx-rbac-other")
    assert other["client"].get(f"/api/v1/tax-contexts/{xid}").status_code == 404
    assert (
        other["client"]
        .post(f"/api/v1/tax-contexts/{xid}/request-confirmation")
        .status_code
        == 404
    )
    assert (
        other["client"].post(f"/api/v1/tax-contexts/{xid}/confirm").status_code == 404
    )
    # Cross-tenant client reference invisible at create.
    r = make_context(other, eid, client_id=other["client_id"])
    assert r.status_code == 404, r.text


def test_confirm_vs_mutation_race_serializes():
    """A PATCH racing a confirmation cannot interleave mid-confirm: the row
    lock orders them strictly. Either the edit lands first (confirm freezes
    the edited content) or the confirm lands first (edit gets 409)."""
    import time

    owner = onboard("ctx-race")
    eid = make_entity(owner).json()["id"]
    xid = make_context(owner, eid).json()["id"]
    owner["client"].post(f"/api/v1/tax-contexts/{xid}/request-confirmation")
    barrier = threading.Barrier(2)
    outcomes: dict = {}

    def do_confirm() -> None:
        client = clone_client(owner["client"])
        barrier.wait(timeout=30)
        r = client.post(f"/api/v1/tax-contexts/{xid}/confirm")
        outcomes["confirm"] = (r.status_code, r.json())

    def do_patch() -> None:
        client = clone_client(owner["client"])
        barrier.wait(timeout=30)
        # Small delay desync so arrival order varies run to run; both orders valid.
        time.sleep(0.05)
        r = client.patch(
            f"/api/v1/tax-contexts/{xid}", json={"period_end": "2026-06-30"}
        )
        outcomes["patch"] = (r.status_code, r.json() if r.status_code == 200 else None)

    threads = [threading.Thread(target=do_confirm), threading.Thread(target=do_patch)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert outcomes["confirm"][0] == 200
    final = owner["client"].get(f"/api/v1/tax-contexts/{xid}").json()
    assert final["confirmation_status"] == "CONFIRMED"
    patch_code, _ = outcomes["patch"]
    assert patch_code in (200, 409)
    if patch_code == 200:
        # Edit won: the frozen snapshot carries the edited period.
        assert final["snapshot"]["period_end"] == "2026-06-30"
    else:
        assert final["snapshot"]["period_end"] == "2026-12-31"
    from app.snapshot import snapshot_from_row, snapshot_hash

    assert (
        snapshot_hash(snapshot_from_row({**final, "tenant_id": owner["tenant_id"]}))
        == final["context_hash"]
    )


def test_entity_status_filter():
    owner = onboard("entity-filter")
    active = make_entity(owner, name="FilterActive").json()["id"]
    ended = make_entity(owner, name="FilterEnded").json()["id"]
    owner["client"].patch(f"/api/v1/legal-entities/{ended}", json={"status": "ENDED"})
    all_rows = owner["client"].get("/api/v1/legal-entities").json()
    assert {active, ended} <= {e["id"] for e in all_rows}  # default lists all
    filtered = (
        owner["client"].get("/api/v1/legal-entities", params={"status": "ENDED"}).json()
    )
    assert ended in {e["id"] for e in filtered} and active not in {
        e["id"] for e in filtered
    }
    r = owner["client"].get("/api/v1/legal-entities", params={"status": "BOGUS"})
    assert r.status_code == 422


def test_full_walkthrough_freeze_and_retrieve():
    """PO walkthrough: firm → client → entity → context → review → confirm → frozen retrieve."""
    owner = onboard("walkthrough")
    c = owner["client"]
    eid = make_entity(
        owner, name="Walkthrough SARL", country="JO", currency="JOD"
    ).json()["id"]
    ctx = make_context(
        owner, eid, period_start="2026-04-01", period_end="2026-06-30"
    ).json()
    assert ctx["confirmation_status"] == "DRAFT"
    review = c.get(f"/api/v1/tax-contexts/{ctx['id']}").json()
    assert (
        review["period_start"] == "2026-04-01" and review["period_end"] == "2026-06-30"
    )
    assert review["context_hash"] is None  # nothing frozen before confirmation
    assert (
        c.post(f"/api/v1/tax-contexts/{ctx['id']}/request-confirmation").status_code
        == 200
    )
    confirmed = c.post(f"/api/v1/tax-contexts/{ctx['id']}/confirm").json()
    assert confirmed["confirmation_status"] == "CONFIRMED"
    assert confirmed["confirmed_by"] == owner["user_id"]
    assert confirmed["snapshot"]["snapshot_version"] == 1
    frozen = c.get(f"/api/v1/tax-contexts/{ctx['id']}").json()
    assert frozen == confirmed  # frozen retrieve is byte-identical
    listed = c.get("/api/v1/tax-contexts", params={"status": "CONFIRMED"}).json()
    assert any(x["id"] == ctx["id"] for x in listed)
    audits = c.get("/api/v1/audit").json()
    assert any(
        a["action"] == "taxcontext.confirmed" and a["actor_id"] == owner["user_id"]
        for a in audits
    )

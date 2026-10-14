"""EP-04C1 integration: PG-authoritative durable jobs, real PG 16 + Redis 7.

All fault tests run against the DEDICATED DISPOSABLE database (dbsafety-guard,
never DATABASE_URL) with synthetic tenants/payloads and no-op handlers. No
quarantined bytes, scans, extraction, or financial effects anywhere here.
"""

import os
import sys
import threading
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))  # repo root
sys.path.insert(0, os.path.dirname(__file__))  # sibling dbsafety module

import dbsafety  # noqa: E402

psycopg = pytest.importorskip("psycopg")

from app.jobs import (  # noqa: E402
    JobConflictError,
    RetryableError,
    WakeupBus,
    serve,
    session,
)
from app.store import assert_schema_matches, tables  # noqa: E402
from db.migrate import _to_libpq, discover, load_checksums, migrate  # noqa: E402

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
REDIS_TEST_URL = os.environ.get("TAXPILOT_TEST_REDIS_URL", "redis://localhost:6379/0")
URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://taxpilot:taxpilot@localhost:5432/taxpilot"
)

_DURL: str | None = None
_ENGINE = None


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


def _destructive_or_skip() -> str:
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
        migrate(candidate)
        _DURL = candidate
    else:
        migrate(_DURL)
    return _DURL


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from sqlalchemy import create_engine

        # Keep the postgresql+psycopg:// scheme: SQLAlchemy then selects the
        # psycopg3 dialect. Converting to libpq form would select psycopg2.
        _ENGINE = create_engine(_destructive_or_skip())
    return _ENGINE


def _factory():
    return session(_engine(), tables())


def _scope(tag: str) -> tuple[str, str]:
    tenant_id, client_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=5) as conn:
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, %s)", (tenant_id, f"j-{tag}")
        )
        conn.execute(
            "INSERT INTO clients (id, tenant_id, name) VALUES (%s, %s, %s)",
            (client_id, tenant_id, f"c-{tag}"),
        )
        conn.commit()
    return tenant_id, client_id


def _key(tag: str) -> str:
    return f"ep04c1-{tag}-{uuid.uuid4().hex[:8]}"


def _enqueue(
    tenant: str, client: str, key: str, payload: dict | None = None, **kw
) -> dict:
    with _factory() as dao:
        row = dao.enqueue(
            tenant, client, "synthetic.noop", key, payload or {"n": key}, **kw
        )
        dao.commit()
        return row


def _effect_table(name: str) -> None:
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=5) as conn:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {name} (job_id TEXT PRIMARY KEY, runs INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(f"DELETE FROM {name}")
        conn.commit()


def _effect_runs(name: str) -> dict[str, int]:
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=5) as conn:
        rows = conn.execute(f"SELECT job_id, runs FROM {name}").fetchall()
    return {r[0]: r[1] for r in rows}


# -- migration ------------------------------------------------------------------
def test_fresh_install_applies_0001_to_0006_with_checksums():
    url = _destructive_or_skip()
    with psycopg.connect(_to_libpq(url), connect_timeout=10) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.commit()
    try:
        assert migrate(url) == ["0001", "0002", "0003", "0004", "0005", "0006"]
        assert [p.name for p in discover()][-1] == "0006_extraction_jobs.sql"
        manifest = load_checksums()
        recorded = {
            r[0]: r[1]
            for r in psycopg.connect(_to_libpq(url), connect_timeout=5)
            .execute("SELECT version, sha256 FROM schema_migrations")
            .fetchall()
        }
        assert set(recorded) == {"0001", "0002", "0003", "0004", "0005", "0006"}
        for version, digest in recorded.items():
            assert manifest[version] == digest, version
        from sqlalchemy import create_engine

        engine = create_engine(url)
        try:
            assert_schema_matches(engine)
        finally:
            engine.dispose()
    finally:
        migrate(url)


# -- idempotency ------------------------------------------------------------------
def test_enqueue_idempotent_conflict_and_cross_tenant_independence():
    tenant_a, client_a = _scope("idem-a")
    tenant_b, client_b = _scope("idem-b")
    key = _key("same")
    first = _enqueue(tenant_a, client_a, key, {"v": 1})
    again = _enqueue(tenant_a, client_a, key, {"v": 1})
    assert again["id"] == first["id"]  # same logical job
    with pytest.raises(JobConflictError):
        _enqueue(tenant_a, client_a, key, {"v": 2})  # same key, different payload
    other_tenant = _enqueue(tenant_b, client_b, key, {"v": 1})
    assert other_tenant["id"] != first["id"]  # no cross-tenant coupling


# -- happy path ------------------------------------------------------------------
def test_claim_heartbeat_settle_happy_path():
    tenant, client = _scope("happy")
    _enqueue(tenant, client, _key("happy"))
    seen: list = []

    def handler(job: dict) -> None:
        seen.append(job["id"])
        assert job["tenant_id"] == tenant

    stats = serve(
        _factory,
        handler,
        tenant_id=tenant,
        lease_ttl=30.0,
        stop_after_jobs=1,
        idle_timeout=10.0,
    )
    assert stats["completed"] == 1 and seen
    with _factory() as dao:
        row = dao.get(seen[0], tenant)
        assert row is not None and row["status"] == "SUCCEEDED" and row["attempts"] == 1
        assert dao.get(seen[0], "00000000-0000-0000-0000-000000000000") is None


# -- crash + recovery --------------------------------------------------------------
def _abandon_claim(
    tenant: str, client: str, key: str, lease_ttl: float = 600.0
) -> dict:
    _enqueue(tenant, client, key)
    with _factory() as dao:
        claimed = dao.claim(tenant, "worker-crasher", lease_ttl)
        assert claimed is not None
        dao.commit()
    return claimed  # never settled: simulates SIGKILL mid-run (lease held, then lapses)


def _force_expire(job_id: str) -> None:
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=5) as conn:
        conn.execute(
            "UPDATE extraction_jobs SET lease_expires_at = clock_timestamp() - make_interval(secs => 5) "
            "WHERE id = %s",
            (job_id,),
        )
        conn.commit()


def test_crash_recovery_redelivers_and_completes():
    tenant, client = _scope("crash")
    abandoned = _abandon_claim(tenant, client, _key("crash"), lease_ttl=3600.0)
    _force_expire(abandoned["id"])
    with _factory() as dao:
        moved = dao.recover_stale(tenant)
        dao.commit()
    assert [(m["id"], m["status"]) for m in moved] == [(abandoned["id"], "QUEUED")]
    done: list = []
    stats = serve(
        _factory,
        lambda job: done.append(job["id"]),
        tenant_id=tenant,
        lease_ttl=30.0,
        stop_after_jobs=1,
        idle_timeout=10.0,
    )
    assert stats["completed"] == 1 and done == [abandoned["id"]]
    with _factory() as dao:
        assert dao.get(abandoned["id"], tenant)["attempts"] == 2


def test_heartbeat_prevents_theft_during_slow_work():
    tenant, client = _scope("slow")
    row = _enqueue(tenant, client, _key("slow"))
    finished: list = []

    def slow_handler(job: dict) -> None:
        time.sleep(4)  # longer than the 2s lease: only heartbeats keep ownership
        finished.append(job["id"])

    stats = serve(
        _factory,
        slow_handler,
        tenant_id=tenant,
        lease_ttl=2.0,
        stop_after_jobs=1,
        idle_timeout=30.0,
    )
    assert stats["completed"] == 1 and finished == [row["id"]]
    with _factory() as dao:
        assert dao.recover_stale(tenant) == []  # nothing leaked as stale


def test_expired_lease_invalidates_settlement_before_sweeper():
    tenant, client = _scope("expiry")
    claimed = _abandon_claim(tenant, client, _key("expiry"), lease_ttl=1.0)
    time.sleep(1.5)
    with _factory() as dao:
        assert (
            dao.renew(claimed["id"], "worker-crasher", claimed["fencing_token"], 60.0)
            is False
        )
        assert (
            dao.finish(claimed["id"], "worker-crasher", claimed["fencing_token"], True)
            is False
        )
        assert (
            dao.get(claimed["id"], tenant)["status"] == "RUNNING"
        )  # sweeper hasn't run
        dao.commit()


def test_stale_token_rejected_after_reclaim():
    tenant, client = _scope("stale")
    first = _abandon_claim(tenant, client, _key("stale"), lease_ttl=1.0)
    time.sleep(1.5)
    with _factory() as dao:
        assert dao.recover_stale(tenant)
        dao.commit()
    with _factory() as dao:
        second = dao.claim(tenant, "worker-b", 60.0)
        dao.commit()
    assert second is not None and second["fencing_token"] != first["fencing_token"]
    with _factory() as dao:
        assert (
            dao.finish(first["id"], "worker-crasher", first["fencing_token"], True)
            is False
        )
        dao.commit()


def test_two_workers_single_claim():
    tenant, client = _scope("race")
    _enqueue(tenant, client, _key("race"))
    barrier = threading.Barrier(8)
    wins: list = []

    def attempt() -> None:
        barrier.wait(timeout=10)
        with _factory() as dao:
            claimed = dao.claim(tenant, "worker-x", 60.0)
            dao.commit()
            if claimed is not None:
                wins.append(claimed["id"])

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(wins) == 1


def test_two_sweepers_single_recovery():
    tenant, client = _scope("sweep")
    ids = []
    for i in range(3):
        claimed = _abandon_claim(tenant, client, _key(f"sweep-{i}"), lease_ttl=1.0)
        ids.append(claimed["id"])
    time.sleep(1.5)
    barrier = threading.Barrier(2)
    recovered: list = []

    def sweep() -> None:
        barrier.wait(timeout=10)
        with _factory() as dao:
            recovered.extend(dao.recover_stale(tenant))
            dao.commit()

    threads = [threading.Thread(target=sweep) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(m["id"] for m in recovered) == sorted(ids)  # each exactly once


def test_max_attempts_dead_letter_is_terminal():
    tenant, client = _scope("dead")
    row = _enqueue(tenant, client, _key("dead"), max_attempts=2)
    for _ in range(2):  # two crashes consume both attempts
        with _factory() as dao:
            claimed = dao.claim(tenant, "worker-c", 3600.0)
            assert claimed is not None
            dao.commit()
        _force_expire(row["id"])
        with _factory() as dao:
            dao.recover_stale(tenant)
            dao.commit()
    # Second recovery already exhausted attempts=2 >= max=2: DEAD, and a
    # further sweep finds nothing eligible.
    with _factory() as dao:
        assert dao.recover_stale(tenant) == []
        final = dao.get(row["id"], tenant)
        dao.commit()
    assert (
        final["status"] == "DEAD"
        and final["terminal_error_class"] == "MaxAttemptsExhausted"
    )
    with _factory() as dao:  # DEAD jobs are never served again
        assert dao.claim(tenant, "worker-d", 60.0) is None
        dao.commit()


# -- duplicate delivery, single effect ----------------------------------------------
def test_duplicate_delivery_single_committed_effect():
    table = "ep04c1_effects_dup"
    _effect_table(table)
    tenant, client = _scope("dupfx")
    row = _enqueue(tenant, client, _key("dupfx"))

    def handler(job: dict) -> None:
        with psycopg.connect(
            _to_libpq(_destructive_or_skip()), connect_timeout=5
        ) as conn:
            conn.execute(
                f"INSERT INTO {table} (job_id, runs) VALUES (%s, 1) ON CONFLICT (job_id) DO NOTHING",
                (job["id"],),
            )
            conn.commit()
        raise RetryableError("synthetic crash after effect")

    with _factory() as dao:  # first delivery: effect + transient failure
        claimed = dao.claim(tenant, "worker-e1", 60.0)
        dao.commit()
    assert claimed is not None
    with pytest.raises(RetryableError):  # effect commits, then the crash
        handler(claimed)
    with _factory() as dao:  # redelivery after requeue
        assert dao.fail_transient(
            claimed["id"], "worker-e1", claimed["fencing_token"], "x", "RetryableError"
        )
        dao.commit()
    _make_job_due(row["id"])  # backoff is real; force eligibility deterministically
    with _factory() as dao:
        again = dao.claim(tenant, "worker-e2", 60.0)
        dao.commit()
    assert again is not None and again["id"] == row["id"]
    assert _effect_runs(table) == {row["id"]: 1}  # effect ran twice, committed once


def test_retry_then_success_records_backoff_and_attempts():
    tenant, client = _scope("settle")
    row = _enqueue(tenant, client, _key("flaky"))
    calls = {"n": 0}

    def flaky(job: dict) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RetryableError("transient wobble")

    stats = serve(
        _factory,
        flaky,
        tenant_id=tenant,
        lease_ttl=30.0,
        stop_after_jobs=1,
        idle_timeout=30.0,
    )
    assert stats == {
        "completed": 1,
        "retried": 1,
        "failed": 0,
        "stale": 0,
        "recovered": 0,
        "recover_runs": stats["recover_runs"],
    }
    with _factory() as dao:
        final = dao.get(row["id"], tenant)
        assert final["status"] == "SUCCEEDED" and final["attempts"] == 2
        assert "wobble" in (final["last_error"] or "")
        dao.commit()


def test_terminal_and_unexpected_settlement_paths():
    tenant, client = _scope("paths")
    doomed = _enqueue(tenant, client, _key("doomed"))
    with _factory() as dao:
        claimed = dao.claim(tenant, "worker-t", 60.0)
        assert claimed is not None
        assert (
            dao.finish(
                doomed["id"],
                "worker-t",
                claimed["fencing_token"],
                False,
                "TerminalError: no",
                "TerminalError",
            )
            is True
        )
        dao.commit()
    with _factory() as dao:
        final = dao.get(doomed["id"], tenant)
        assert (
            final["status"] == "FAILED"
            and final["terminal_error_class"] == "TerminalError"
        )
        assert final["attempts"] == 1  # terminal failure spends no extra attempt
        dao.commit()
    via_serve = _enqueue(tenant, client, _key("boom"))

    def unexpected(job: dict) -> None:
        raise RuntimeError("unforeseen bug")

    stats = serve(
        _factory,
        unexpected,
        tenant_id=tenant,
        lease_ttl=30.0,
        deadline_seconds=4.0,
        sweep_interval=60.0,
    )
    assert stats["retried"] >= 1  # unexpected faults retry transiently, never terminal
    with _factory() as dao:
        assert dao.get(via_serve["id"], tenant)["status"] == "QUEUED"
        dao.commit()


# -- Redis loss is delay-only ----------------------------------------------------------
def _redis():
    import redis as redis_lib

    return redis_lib.Redis.from_url(REDIS_TEST_URL, socket_timeout=5)


def test_redis_flush_and_outage_lose_nothing():
    tenant, client = _scope("rloss")
    bus = WakeupBus(REDIS_TEST_URL)
    ids = []
    for i in range(3):
        row = _enqueue(tenant, client, _key(f"rloss-{i}"))
        ids.append(row["id"])
        assert bus.notify(row["id"]) is True
    _redis().flushall()  # total wakeup loss, mid-flight
    done: list = []
    stats = serve(
        _factory,
        lambda job: done.append(job["id"]),
        tenant_id=tenant,
        lease_ttl=30.0,
        stop_after_jobs=3,
        idle_timeout=15.0,
        wakeups=bus,
    )
    assert stats["completed"] == 3 and sorted(done) == sorted(ids)
    dead = WakeupBus("redis://127.0.0.1:9/0")
    assert dead.notify("x") is False and dead.wait(0.1) is None


# -- PG outage + ack ambiguity ------------------------------------------------------------
def test_pg_outage_fails_closed_without_phantom():
    from sqlalchemy import create_engine

    engine = create_engine(
        "postgresql+psycopg://taxpilot:taxpilot@127.0.0.1:9/taxpilot",
        connect_args={"connect_timeout": 2},
    )
    with pytest.raises(Exception):  # connect itself refuses: no phantom success
        with session(engine, tables()) as dao:
            dao.enqueue("t", "c", "op", "k", {})
    engine.dispose()


def test_ambiguous_commit_ack_converges_without_double():
    tenant, client = _scope("ack")
    key = _key("ack")
    first = _enqueue(tenant, client, key, {"v": 1})
    # The acknowledgement was "lost": re-query + idempotent retry converge.
    again = _enqueue(tenant, client, key, {"v": 1})
    assert again["id"] == first["id"]
    with _factory() as dao:
        rows = dao.get(first["id"], tenant)
        assert rows is not None
        all_ids = [r["id"] for r in [rows]]
    assert len(all_ids) == 1


# -- tenant isolation ------------------------------------------------------------------
def test_cross_tenant_claims_and_keys_isolated():
    tenant_a, client_a = _scope("iso-a")
    tenant_b, client_b = _scope("iso-b")
    row = _enqueue(tenant_a, client_a, _key("iso"))
    with _factory() as dao:
        assert dao.claim(tenant_b, "worker-z", 60.0) is None
        assert dao.get(row["id"], tenant_b) is None
        metrics_b = dao.metrics(tenant_b)
        assert metrics_b["jobs"]["QUEUED"]["count"] == 0
        dao.commit()


# -- outbox -------------------------------------------------------------------------------
def test_outbox_atomic_publish_claim_ack_lifecycle():
    tenant, client = _scope("outbox")
    with _factory() as dao:
        job = dao.enqueue(tenant, client, "synthetic.noop", _key("ob"), {"v": 1})
        event = dao.outbox_publish(
            tenant, job["id"], _key("ev"), "scan.requested", {"job": job["id"]}
        )
        dao.commit()
    with _factory() as dao:
        first_publish = dao.outbox_publish(
            tenant, job["id"], _key("ev2"), "scan.requested", {"job": job["id"]}
        )
        replay = dao.outbox_publish(
            tenant,
            job["id"],
            first_publish["event_key"],
            "scan.requested",
            {"job": job["id"]},
        )
        assert replay["id"] == first_publish["id"]  # same logical event
        dao.commit()
    with _factory() as dao:
        claimed = dao.outbox_claim(tenant, limit=10)
        assert sorted(e["id"] for e in claimed) == sorted(
            [event["id"], first_publish["id"]]
        )
        assert dao.outbox_ack(event["id"], True) is True
        assert dao.outbox_ack(event["id"], True) is False  # already published: fenced
        dao.commit()
    with _factory() as dao:
        assert [e["id"] for e in dao.outbox_claim(tenant)] == [first_publish["id"]]
        dao.commit()


def _make_due(event_id: str) -> None:
    """Force an outbox row due now (backoff is real; tests must not sleep on it)."""
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=5) as conn:
        conn.execute(
            "UPDATE job_outbox SET next_attempt_at = clock_timestamp() WHERE id = %s",
            (event_id,),
        )
        conn.commit()


def _make_job_due(job_id: str) -> None:
    """Force a requeued job eligible now (same deterministic backoff bypass)."""
    with psycopg.connect(_to_libpq(_destructive_or_skip()), connect_timeout=5) as conn:
        conn.execute(
            "UPDATE extraction_jobs SET not_before = clock_timestamp() WHERE id = %s",
            (job_id,),
        )
        conn.commit()


def test_outbox_backoff_and_dead_and_cross_tenant():
    tenant, client = _scope("obfail")
    row = _enqueue(tenant, client, _key("obf"))
    with _factory() as dao:
        event = dao.outbox_publish(
            tenant, row["id"], _key("obev"), "t", {}, max_attempts=2
        )
        dao.commit()
    for _ in range(2):
        with _factory() as dao:
            assert len(dao.outbox_claim(tenant)) == 1
            assert dao.outbox_ack(event["id"], False, "downstream down") is True
            dao.commit()
        _make_due(event["id"])  # backoff is real: force due deterministically
    with _factory() as dao:
        assert dao.outbox_claim(tenant) == []
        other_tenant, _other_client = _scope("obother")
        assert dao.outbox_claim(other_tenant) == []
        dao.commit()


def test_outbox_survives_redis_loss():
    tenant, client = _scope("obloss")
    row = _enqueue(tenant, client, _key("obl"))
    with _factory() as dao:
        event = dao.outbox_publish(tenant, row["id"], _key("oblev"), "t", {})
        dao.commit()
    _redis().flushall()
    with _factory() as dao:
        assert [e["id"] for e in dao.outbox_claim(tenant)] == [event["id"]]
        dao.commit()


# -- metrics carry no content ---------------------------------------------------------------
def test_metrics_metadata_only():
    tenant, client = _scope("metrics")
    marker = f"SYNTHETIC-MARKER-{uuid.uuid4().hex}"
    _enqueue(tenant, client, _key("m"), {"note": marker})
    with _factory() as dao:
        metrics = dao.metrics(tenant)
        assert metrics["jobs"]["QUEUED"]["count"] >= 1
        assert marker not in str(metrics)
        dao.commit()


# -- synthetic load numbers --------------------------------------------------------------------
def test_synthetic_load_reports_throughput():
    import time as time_module

    tenant, client = _scope("load")
    total = 200
    for i in range(total):
        _enqueue(tenant, client, _key(f"load-{i}"))
    barrier = threading.Barrier(4)
    started = time_module.time()
    results: list = []

    def work() -> dict:
        barrier.wait(timeout=10)
        return serve(
            _factory,
            lambda job: None,
            tenant_id=tenant,
            lease_ttl=60.0,
            poll_interval=0.05,
            sweep_interval=30.0,
            idle_timeout=10.0,
        )

    threads = [
        threading.Thread(target=lambda: results.append(work())) for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)
    elapsed = time_module.time() - started
    completed = sum(r["completed"] for r in results)
    print(
        f"\nSYNTHETIC LOAD: {completed}/{total} jobs, 4 workers, {elapsed:.1f}s "
        f"({completed / max(elapsed, 0.01):.0f} jobs/s)"
    )
    assert completed == total
    with _factory() as dao:
        assert dao.metrics(tenant)["jobs"]["QUEUED"]["count"] == 0
        dao.commit()

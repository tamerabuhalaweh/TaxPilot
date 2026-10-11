"""Sprint 0 backend tests: health/readiness, errors, correlation IDs, config guards,
queue semantics, lifespan. No external services required (probes are stubbed)."""

import re

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.errors import AppError
from app.logging_setup import redact
from app.main import create_app
from app.middleware import coerce_correlation_id
from worker.jobs import (
    CANCELLED,
    FAILED,
    OUT_COMPLETED,
    OUT_FAILED,
    OUT_RETRIED,
    QUEUED,
    RUNNING,
    Job,
    MemoryBackend,
    process_one,
)

SAFE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def make_client(monkeypatch=None, db_up=True, queue_state="up"):  # type: ignore[no-untyped-def]
    app = create_app()
    if monkeypatch is not None:
        monkeypatch.setattr("app.routers.health.probe_database", lambda _app: db_up)
        monkeypatch.setattr("app.routers.health.probe_queue", lambda _app: queue_state)
    return TestClient(app, raise_server_exceptions=False)


def test_health_contract():
    client = make_client()
    with client:
        r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "taxpilot-api", "version": "0.1.0"}
    assert r.headers["X-Request-ID"]


def test_ready_ok_when_dependencies_up(monkeypatch):  # type: ignore[no-untyped-def]
    client = make_client(monkeypatch, db_up=True, queue_state="up")
    with client:
        r = client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ready", "environment": "development", "database": "up", "queue": "up"}


def test_ready_503_when_database_down_and_leaks_nothing(monkeypatch):  # type: ignore[no-untyped-def]
    client = make_client(monkeypatch, db_up=False, queue_state="up")
    with client:
        r = client.get("/api/v1/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded" and body["database"] == "down"
    assert "taxpilot" not in r.text and "5432" not in r.text and "localhost" not in r.text


def test_ready_503_when_queue_down(monkeypatch):  # type: ignore[no-untyped-def]
    client = make_client(monkeypatch, db_up=True, queue_state="down")
    with client:
        r = client.get("/api/v1/ready")
    assert r.status_code == 503
    assert r.json()["queue"] == "down"


def test_ready_accepts_explicit_memory_fallback_with_environment_flag(monkeypatch):  # type: ignore[no-untyped-def]
    client = make_client(monkeypatch, db_up=True, queue_state="memory-fallback")
    with client:
        r = client.get("/api/v1/ready")
    assert r.status_code == 200
    assert r.json()["environment"] == "development"


def test_correlation_id_validation():
    assert coerce_correlation_id("abc-123_XY") == "abc-123_XY"
    replaced = coerce_correlation_id("x" * 129)
    assert replaced != "x" * 129 and SAFE.match(replaced)
    assert SAFE.match(coerce_correlation_id(None))
    assert coerce_correlation_id("a b") != "a b"  # spaces rejected, never echoed


def test_correlation_roundtrip_and_replacement_in_app():
    client = make_client()
    with client:
        ok = client.get("/api/v1/health", headers={"X-Request-ID": "test-123"})
        assert ok.headers["X-Request-ID"] == "test-123"
        evil = client.get("/api/v1/health", headers={"X-Request-ID": "<script>alert(1)</script>"})
        assert evil.headers["X-Request-ID"] != "<script>alert(1)</script>"
        assert SAFE.match(evil.headers["X-Request-ID"])


def test_lifespan_sets_state_and_disposes():
    app = create_app()
    with TestClient(app):
        assert app.state.settings is not None
        assert hasattr(app.state, "engine")


def test_production_config_rejects_dev_defaults():
    with pytest.raises(ValidationError):
        Settings(environment="production")
    with pytest.raises(ValidationError):
        Settings(environment="production", queue_backend="memory")
    ok = Settings(
        environment="production",
        database_url="postgresql+psycopg://u:p@db:5432/t",
        redis_url="redis://redis:6379/0",
        cors_allowed_origins=["https://app.example.com"],
    )
    assert ok.environment == "production"


def test_cors_allowlist_no_wildcard():
    client = make_client()
    with client:
        r = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    with client:
        evil = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers


def test_unhandled_errors_use_envelope_without_internals():
    app = create_app()

    @app.get("/__boom")  # type: ignore[misc]
    def _boom():  # type: ignore[no-untyped-def]
        raise RuntimeError("secret internals must not leak")

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/__boom")
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "secret internals" not in r.text
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/__boom"]


def test_app_error_codes_map_to_status():
    app = create_app()

    @app.get("/__teapot")  # type: ignore[misc]
    def _teapot():  # type: ignore[no-untyped-def]
        raise AppError("TAX_CONTEXT_REQUIRED", "Confirm a tax context first.", {"x": 1})

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/__teapot")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "TAX_CONTEXT_REQUIRED"
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/__teapot"]


def test_redaction():
    assert redact({"password": "x", "ok": 1}) == {"password": "***", "ok": 1}
    assert redact({"registration_number": "123"}) == {"registration_number": "***"}


def test_queue_idempotent_enqueue_and_retry_then_fail():
    backend = MemoryBackend()
    first = backend.enqueue(Job(kind="echo", idempotency_key="k-1", max_attempts=2))
    again = backend.enqueue(Job(kind="echo", idempotency_key="k-1", max_attempts=2))
    assert first.id == again.id
    assert backend.depth() == 1

    def fail(job):  # type: ignore[no-untyped-def]
        raise ValueError("boom")

    _job, first_out = process_one(backend, fail, "w-1", 60.0)  # attempt 1 -> requeued
    assert first_out == OUT_RETRIED
    assert backend.get(first.id).status == QUEUED
    _job, second_out = process_one(backend, fail, "w-1", 60.0)  # attempt 2 -> FAILED
    assert second_out == OUT_FAILED
    done = backend.get(first.id)
    assert done.status == FAILED
    assert done.error_class == "ValueError" and "boom" in (done.error or "")
    assert done.attempts == 2


def test_queue_success_path():
    backend = MemoryBackend()
    backend.enqueue(Job(kind="noop"))
    out, outcome = process_one(backend, lambda j: None, "w-1", 60.0)
    assert outcome == OUT_COMPLETED
    assert out is not None and out.status == "SUCCEEDED"
    assert backend.depth() == 0


def test_queue_claim_sets_owner_lease_and_attempt():
    backend = MemoryBackend()
    backend.enqueue(Job(kind="echo"))
    claimed = backend.claim("w-a", 60.0)
    assert claimed is not None and claimed.status == RUNNING
    assert claimed.owner == "w-a" and claimed.lease_expires_at > claimed.created_at
    assert claimed.attempts == 1


def test_queue_renew_keeps_live_worker_and_rejects_stranger():
    backend = MemoryBackend()
    backend.enqueue(Job(kind="echo"))
    claimed = backend.claim("w-a", 60.0)
    assert claimed is not None
    assert backend.renew(claimed, "w-a", 60.0) is True
    assert backend.renew(claimed, "w-b", 60.0) is False


def test_queue_stale_finish_is_rejected_without_overwrite():
    backend = MemoryBackend()
    job = backend.enqueue(Job(kind="echo"))
    first = backend.claim("w-old", 60.0)
    assert first is not None
    # Simulate lease loss + legitimate reclaim: force-expire then requeue+reclaim.
    first.lease_expires_at = 0.0
    assert backend.recover_stale() == 1
    second = backend.claim("w-new", 60.0)
    assert second is not None and second.owner == "w-new" and second.attempts == 2
    assert backend.finish(first, "w-old", True) is False  # stale attempt touches nothing
    current = backend.get(job.id)
    assert current.status == RUNNING and current.owner == "w-new"
    assert backend.finish(second, "w-new", True) is True
    assert backend.get(job.id).status == "SUCCEEDED"


def test_queue_recover_stale_requeues_crashed_claims():
    backend = MemoryBackend()
    job = backend.enqueue(Job(kind="echo"))
    claimed = backend.claim("w-a", 60.0)
    assert claimed is not None and claimed.status == RUNNING
    job.lease_expires_at = 0.0  # simulate a claim from long ago (crashed worker)
    assert backend.recover_stale() == 1
    assert backend.get(job.id).status == QUEUED
    out, outcome = process_one(backend, lambda j: None, "w-b", 60.0)
    assert outcome == OUT_COMPLETED
    assert out is not None and out.status == "SUCCEEDED"


def test_states_are_distinct_constants():
    assert len({CANCELLED, FAILED, QUEUED}) == 3


def test_production_worker_use_blocked_until_durability_approved(monkeypatch):  # type: ignore[no-untyped-def]
    from worker.runner import recover_and_serve

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/t")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.delenv("JOBS_DURABILITY_APPROVED", raising=False)
    with pytest.raises(RuntimeError, match="OPS-JOBS-01"):
        recover_and_serve()
    # Explicit approval lifts the block at settings level (the loop itself is not started here).
    approved = Settings(
        environment="production",
        database_url="postgresql+psycopg://u:p@db:5432/t",
        redis_url="redis://redis:6379/0",
        cors_allowed_origins=["https://app.example.com"],
        jobs_durability_approved=True,
    )
    assert approved.jobs_durability_approved is True


def test_serve_recovers_automatically_without_operator():
    from worker.runner import serve

    backend = MemoryBackend()
    job = backend.enqueue(Job(kind="echo"))
    claimed = backend.claim("crashed-worker", 0.2)  # dies holding the claim, no heartbeat
    assert claimed is not None
    stats = serve(
        backend,
        lambda j: None,
        worker_id="w-b",
        lease_ttl=5.0,
        recover_interval=0.1,
        stop_after_jobs=1,
        idle_timeout=10.0,
    )
    assert stats["completed"] == 1 and stats["recovered"] >= 1
    final = backend.get(job.id)
    assert final.status == "SUCCEEDED" and final.attempts == 2


def test_heartbeat_prevents_recovery_of_live_worker():
    import threading
    import time as _time

    from worker.runner import _heartbeat

    backend = MemoryBackend()
    job = backend.enqueue(Job(kind="echo"))
    claimed = backend.claim("w-live", 0.6)
    assert claimed is not None
    stop = threading.Event()
    beat = threading.Thread(target=_heartbeat, args=(backend, job.id, "w-live", 0.6, stop), daemon=True)
    beat.start()
    _time.sleep(1.5)  # well past the original lease, while heartbeats renew
    try:
        assert backend.recover_stale() == 0
        assert backend.get(job.id).owner == "w-live"
    finally:
        stop.set()
        beat.join(timeout=5.0)

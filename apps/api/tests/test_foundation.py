"""Sprint 0 backend tests: health, error envelope, correlation IDs, queue semantics, redaction."""

from fastapi.testclient import TestClient

from app.errors import AppError
from app.logging_setup import redact
from app.main import create_app
from worker.jobs import CANCELLED, FAILED, QUEUED, Job, MemoryBackend, process_one

app = create_app()
client = TestClient(app, raise_server_exceptions=False)


def test_health_contract():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "taxpilot-api", "version": "0.1.0"}
    assert r.headers["X-Request-ID"]


def test_ready_reports_flags_without_crashing():
    r = client.get("/api/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "database", "queue"}


def test_correlation_id_roundtrip():
    r = client.get("/api/v1/health", headers={"X-Request-ID": "test-123"})
    assert r.headers["X-Request-ID"] == "test-123"


def test_unhandled_errors_use_envelope_without_internals():
    @app.get("/__boom")  # type: ignore[misc]
    def _boom():  # type: ignore[no-untyped-def]
        raise RuntimeError("secret internals must not leak")

    try:
        r = client.get("/__boom")
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "secret internals" not in r.text
    finally:
        app.router.routes = [rt for rt in app.router.routes if getattr(rt, "path", "") != "/__boom"]


def test_app_error_codes_map_to_status():
    @app.get("/__teapot")  # type: ignore[misc]
    def _teapot():  # type: ignore[no-untyped-def]
        raise AppError("TAX_CONTEXT_REQUIRED", "Confirm a tax context first.", {"x": 1})

    try:
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

    process_one(backend, fail)  # attempt 1 -> requeued
    assert backend.get(first.id).status == QUEUED
    process_one(backend, fail)  # attempt 2 -> FAILED
    done = backend.get(first.id)
    assert done.status == FAILED
    assert done.error_class == "ValueError"
    assert done.attempts == 2


def test_queue_success_path_and_cancel_state_exists():
    assert CANCELLED == "CANCELLED" and FAILED == "FAILED" and QUEUED == "QUEUED"
    backend = MemoryBackend()
    backend.enqueue(Job(kind="noop"))
    out = process_one(backend, lambda j: None)
    assert out and out.status == "SUCCEEDED"
    assert backend.depth() == 0

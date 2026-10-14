"""PostgreSQL-authoritative durable jobs + transactional outbox (EP-04C1, #35).

Authority model: every committed job/outbox row survives Redis loss — Redis
carries wakeups only (notification acceleration), never truth. All lease math
uses the DB server clock (``clock_timestamp()``); worker clocks never decide
ownership. Every claim/renew/settle/recover transition is a SINGLE conditional
SQL statement (no check-then-write): stale owners, expired leases, and
concurrent sweepers cannot overwrite newer truth.

Delivery is at-least-once; handlers MUST be idempotent. Exactly-once is never
claimed. No handler in this slice touches quarantined bytes, scans, extraction,
or financial effects (synthetic no-op handlers only in tests).

Transaction discipline: no method here commits — the caller owns commit/
rollback (serve loop commits per operation; tests control boundaries).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

log = logging.getLogger(__name__)

RETRYABLE = "retryable"
TERMINAL = "terminal"

_STATUSES = ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "DEAD")
_OUTBOX_STATUSES = ("PENDING", "PUBLISHED", "FAILED")
_MAX_PAYLOAD_CHARS = 60000


class JobConflictError(ValueError):
    """Same tenant+client+operation+key already holds different payload identity."""


class OutboxConflictError(ValueError):
    """Same tenant+job+event key already holds a different event payload/type."""


class RetryableError(Exception):
    """Handler asks for a bounded retry (requeue with backoff)."""


class TerminalError(Exception):
    """Handler declares terminal failure (no further attempts)."""


def fingerprint_payload(payload: dict[str, Any]) -> str:
    """Stable sha256 over canonical JSON (sorted keys, compact separators)."""
    if not isinstance(payload, dict):
        raise ValueError(f"payload must be a dict, got {type(payload).__name__}")
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"payload is not JSON-serializable: {exc}") from exc
    if len(canonical) > _MAX_PAYLOAD_CHARS:
        raise ValueError(f"payload exceeds {_MAX_PAYLOAD_CHARS} canonical chars")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def new_worker_id() -> str:
    return f"worker-{uuid.uuid4().hex[:12]}"


def _mint_token(worker_id: str) -> str:
    """Unique fencing token per claim attempt (never a bare reusable id)."""
    return f"{worker_id}:{secrets.token_hex(8)}"


def _row(mapping: Any) -> dict[str, Any]:
    data = dict(mapping)
    for key, value in list(data.items()):
        if isinstance(value, uuid.UUID):
            data[key] = str(value)
    return data


class DurableJobs:
    """Durable job/outbox data access over one connection (caller commits)."""

    def __init__(self, conn: Connection, table_defs: dict) -> None:
        self.conn = conn
        self.t = table_defs

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    # -- producer ---------------------------------------------------------
    def enqueue(
        self,
        tenant_id: str,
        client_id: str,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
        max_attempts: int = 5,
    ) -> dict[str, Any]:
        """Insert a job, or return the identical existing one (scope-bound).

        Scope is (tenant, client, operation, key): the same key in another
        scope is an independent job. Same scope + same payload hash: idempotent
        replay, same logical job. Same scope + different hash: JobConflictError,
        never silent overwrite. Concurrent duplicates serialize on the scoped
        UNIQUE index: the loser re-reads inside a savepoint and converges.
        """
        if not operation or len(operation) > 64:
            raise ValueError("operation must be 1-64 chars")
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("idempotency_key must be 1-128 chars")
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        payload_hash = fingerprint_payload(payload)
        table = self.t["extraction_jobs"]
        scope = {"tenant": tenant_id, "client": client_id, "operation": operation, "key": idempotency_key}
        existing = (
            self.conn.execute(
                text(
                    "SELECT * FROM extraction_jobs WHERE tenant_id = :tenant "
                    "AND client_id = :client AND operation = :operation AND idempotency_key = :key"
                ),
                scope,
            )
            .mappings()
            .first()
        )
        if existing is not None:
            data = _row(existing)
            if data["payload_hash"] != payload_hash:
                raise JobConflictError(
                    f"idempotency key {idempotency_key!r} holds different payload"
                ) from None
            return data
        try:
            with self.conn.begin_nested():
                row = (
                    self.conn.execute(
                        table.insert()
                        .values(
                            id=uuid.uuid4(),
                            tenant_id=tenant_id,
                            client_id=client_id,
                            operation=operation,
                            idempotency_key=idempotency_key,
                            payload_hash=payload_hash,
                            payload=payload,
                            max_attempts=max_attempts,
                        )
                        .returning(table)
                    )
                    .mappings()
                    .first()
                )
                assert row is not None
                return _row(row)
        except IntegrityError:
            # Lost a concurrent race: the winner is authoritative — replay it
            # when identical, conflict otherwise. Savepoint kept us usable.
            existing = (
                self.conn.execute(
                    text(
                        "SELECT * FROM extraction_jobs WHERE tenant_id = :tenant "
                        "AND client_id = :client AND operation = :operation "
                        "AND idempotency_key = :key"
                    ),
                    scope,
                )
                .mappings()
                .first()
            )
            if existing is None:  # pragma: no cover - defensive; constraint says otherwise
                raise
            data = _row(existing)
            if data["payload_hash"] != payload_hash:
                raise JobConflictError(
                    f"idempotency key {idempotency_key!r} holds different payload"
                ) from None
            return data

    # -- consumer ---------------------------------------------------------
    def claim(self, tenant_id: str | None, worker_id: str, lease_ttl_seconds: float) -> dict | None:
        """Atomically claim the oldest eligible job (tenant-scoped when given).

        Single UPDATE with FOR UPDATE SKIP LOCKED: concurrent claimants never
        double-claim. Attempts increment and a fresh fencing token is minted.
        """
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        row = (
            self.conn.execute(
                text(
                    "UPDATE extraction_jobs AS j SET status = 'RUNNING', "
                    "lease_owner = :owner, fencing_token = :token, "
                    "lease_expires_at = clock_timestamp() + make_interval(secs => :ttl), "
                    "attempts = j.attempts + 1, updated_at = clock_timestamp() "
                    "WHERE j.id = (SELECT id FROM extraction_jobs "
                    "WHERE status = 'QUEUED' AND not_before <= clock_timestamp() "
                    "AND (CAST(:tenant AS UUID) IS NULL OR tenant_id = CAST(:tenant AS UUID)) "
                    "ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED) "
                    "RETURNING j.*"
                ),
                {
                    "owner": worker_id,
                    "token": _mint_token(worker_id),
                    "ttl": lease_ttl_seconds,
                    "tenant": tenant_id,
                },
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    def renew(self, job_id: str, worker_id: str, fencing_token: str, lease_ttl_seconds: float) -> bool:
        """Extend a live claim. Expired leases are dead: only recovery may move them."""
        return (
            self.conn.execute(
                text(
                    "UPDATE extraction_jobs SET "
                    "lease_expires_at = clock_timestamp() + make_interval(secs => :ttl), "
                    "updated_at = clock_timestamp() "
                    "WHERE id = :id AND status = 'RUNNING' AND lease_owner = :owner "
                    "AND fencing_token = :token AND lease_expires_at > clock_timestamp()"
                ),
                {"id": job_id, "owner": worker_id, "token": fencing_token, "ttl": lease_ttl_seconds},
            ).rowcount
            == 1
        )

    def finish(
        self,
        job_id: str,
        worker_id: str,
        fencing_token: str,
        ok: bool,
        error: str | None = None,
        error_class: str | None = None,
    ) -> bool:
        """Settle terminally. Stale or superseded claims are rejected (False)."""
        status = "SUCCEEDED" if ok else "FAILED"
        return (
            self.conn.execute(
                text(
                    "UPDATE extraction_jobs SET status = :status, "
                    "terminal_error = :error, terminal_error_class = :error_class, "
                    "lease_owner = '', fencing_token = '', lease_expires_at = NULL, "
                    "updated_at = clock_timestamp() "
                    "WHERE id = :id AND status = 'RUNNING' AND lease_owner = :owner "
                    "AND fencing_token = :token AND lease_expires_at > clock_timestamp()"
                ),
                {
                    "id": job_id,
                    "owner": worker_id,
                    "token": fencing_token,
                    "status": status,
                    "error": error,
                    "error_class": error_class,
                },
            ).rowcount
            == 1
        )

    def fail_transient(
        self, job_id: str, worker_id: str, fencing_token: str, error: str, error_class: str
    ) -> str | None:
        """Requeue with exponential backoff (cap 1h), or terminal DEAD at max.

        Attempts were spent at claim, so a handler failing on its last allowed
        attempt exhausts HERE — retries cannot outlive max_attempts even with
        heartbeats holding the lease forever. Returns the new status
        ('QUEUED' | 'DEAD'), or None when the claim is stale/superseded.
        """
        row = (
            self.conn.execute(
                text(
                    "UPDATE extraction_jobs SET "
                    "status = CASE WHEN attempts >= max_attempts THEN 'DEAD' ELSE 'QUEUED' END, "
                    "last_error = :error, last_error_class = :error_class, "
                    "terminal_error = CASE WHEN attempts >= max_attempts "
                    "THEN 'attempts exhausted after ' || attempts || ' attempt(s)' "
                    "ELSE terminal_error END, "
                    "terminal_error_class = CASE WHEN attempts >= max_attempts "
                    "THEN 'MaxAttemptsExhausted' ELSE terminal_error_class END, "
                    "not_before = CASE WHEN attempts >= max_attempts THEN not_before "
                    "ELSE clock_timestamp() + "
                    "make_interval(secs => LEAST(power(2, attempts), 3600)::double precision) END, "
                    "lease_owner = '', fencing_token = '', lease_expires_at = NULL, "
                    "updated_at = clock_timestamp() "
                    "WHERE id = :id AND status = 'RUNNING' AND lease_owner = :owner "
                    "AND fencing_token = :token AND lease_expires_at > clock_timestamp() "
                    "RETURNING status"
                ),
                {
                    "id": job_id,
                    "owner": worker_id,
                    "token": fencing_token,
                    "error": error,
                    "error_class": error_class,
                },
            )
            .mappings()
            .first()
        )
        return row["status"] if row else None

    def recover_stale(self, tenant_id: str | None = None, batch: int = 100) -> list[dict[str, str]]:
        """Requeue expired RUNNING leases; exhaust attempts to DEAD. Atomic batch.

        Concurrent sweepers serialize on row locks (SKIP LOCKED): each expired
        lease transitions exactly once. Returns [{id, status}] for wakeups.
        """
        rows = (
            self.conn.execute(
                text(
                    "UPDATE extraction_jobs AS j "
                    "SET status = CASE WHEN j.attempts >= j.max_attempts THEN 'DEAD' ELSE 'QUEUED' END, "
                    "lease_owner = '', fencing_token = '', lease_expires_at = NULL, "
                    "not_before = clock_timestamp(), "
                    "last_error = CASE WHEN j.attempts >= j.max_attempts "
                    "THEN 'attempts exhausted after ' || j.attempts || ' attempt(s)' "
                    "ELSE j.last_error END, "
                    "terminal_error = CASE WHEN j.attempts >= j.max_attempts "
                    "THEN 'attempts exhausted after ' || j.attempts || ' attempt(s)' "
                    "ELSE j.terminal_error END, "
                    "terminal_error_class = CASE WHEN j.attempts >= j.max_attempts "
                    "THEN 'MaxAttemptsExhausted' ELSE j.terminal_error_class END, "
                    "updated_at = clock_timestamp() "
                    "WHERE j.id IN (SELECT id FROM extraction_jobs "
                    "WHERE status = 'RUNNING' AND lease_expires_at <= clock_timestamp() "
                    "AND (CAST(:tenant AS UUID) IS NULL OR tenant_id = CAST(:tenant AS UUID)) "
                    "ORDER BY lease_expires_at LIMIT :batch FOR UPDATE SKIP LOCKED) "
                    "RETURNING j.id, j.status"
                ),
                {"tenant": tenant_id, "batch": batch},
            )
            .mappings()
            .all()
        )
        return [{"id": str(r["id"]), "status": r["status"]} for r in rows]

    def get(self, job_id: str, tenant_id: str) -> dict | None:
        """Tenant-scoped read (no cross-tenant metadata exposure)."""
        row = (
            self.conn.execute(
                text("SELECT * FROM extraction_jobs WHERE id = :id AND tenant_id = :tenant"),
                {"id": job_id, "tenant": tenant_id},
            )
            .mappings()
            .first()
        )
        return _row(row) if row else None

    # -- outbox -----------------------------------------------------------
    def outbox_publish(
        self,
        tenant_id: str,
        job_id: str,
        event_key: str,
        event_type: str,
        payload: dict[str, Any],
        max_attempts: int = 10,
    ) -> dict[str, Any]:
        """Idempotent event insert scoped to (tenant, job, key).

        Same scope + same event identity: converge on the existing row.
        Same scope + different identity (type or payload): OutboxConflictError,
        never silent convergence. Same transaction as job creation when called
        before the caller's commit: no lost events.
        """
        fingerprint_payload(payload)  # validate shape/size early
        if not event_key or len(event_key) > 128:
            raise ValueError("event_key must be 1-128 chars")
        if not event_type or len(event_type) > 64:
            raise ValueError("event_type must be 1-64 chars")
        fingerprint_payload({"type": event_type, "payload": payload})  # validate shape/size
        table = self.t["job_outbox"]
        try:
            with self.conn.begin_nested():
                row = (
                    self.conn.execute(
                        table.insert()
                        .values(
                            id=uuid.uuid4(),
                            tenant_id=tenant_id,
                            job_id=job_id,
                            event_key=event_key,
                            event_type=event_type,
                            payload=payload,
                            max_attempts=max_attempts,
                        )
                        .returning(table)
                    )
                    .mappings()
                    .first()
                )
                assert row is not None
                return _row(row)
        except IntegrityError:
            existing = (
                self.conn.execute(
                    text(
                        "SELECT * FROM job_outbox WHERE tenant_id = :t AND job_id = :j " "AND event_key = :k"
                    ),
                    {"t": tenant_id, "j": job_id, "k": event_key},
                )
                .mappings()
                .first()
            )
            if existing is None:  # pragma: no cover - defensive
                raise
            data = _row(existing)
            if data["event_type"] != event_type or data["payload"] != payload:
                raise OutboxConflictError(
                    f"event key {event_key!r} already holds a different event"
                ) from None
            return data

    def outbox_claim(
        self, tenant_id: str | None, owner: str, lease_ttl_seconds: float, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Crash-safe publisher claim: ownership + fencing token assigned atomically.

        A publisher that dies mid-publish holds an expired lease; the sweeper
        releases it and a new fencing token invalidates the old owner — a late
        ack from the crashed publisher is rejected, never double-published.

        Rows under a LIVE lease are never re-claimed (only expired ones are,
        with a fresh token): concurrent publishers cannot share one event.
        """
        if lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        rows = (
            self.conn.execute(
                text(
                    "UPDATE job_outbox AS o SET lease_owner = :owner, "
                    # Per-row token (not one per batch): each claimed event owns
                    # an independent fence, mirroring per-attempt job tokens.
                    "fencing_token = :owner || ':' || gen_random_uuid(), "
                    "lease_expires_at = clock_timestamp() + make_interval(secs => :ttl) "
                    "WHERE o.id IN (SELECT id FROM job_outbox WHERE status = 'PENDING' "
                    "AND next_attempt_at <= clock_timestamp() "
                    "AND (lease_expires_at IS NULL OR lease_expires_at <= clock_timestamp()) "
                    "AND (CAST(:tenant AS UUID) IS NULL OR tenant_id = CAST(:tenant AS UUID)) "
                    "ORDER BY created_at, id LIMIT :limit FOR UPDATE SKIP LOCKED) "
                    "RETURNING o.*"
                ),
                {"owner": owner, "ttl": lease_ttl_seconds, "tenant": tenant_id, "limit": limit},
            )
            .mappings()
            .all()
        )
        return [_row(r) for r in rows]

    def outbox_renew(self, event_id: str, owner: str, fencing_token: str, lease_ttl_seconds: float) -> bool:
        """Extend a live publisher claim; expired leases are dead."""
        return (
            self.conn.execute(
                text(
                    "UPDATE job_outbox SET "
                    "lease_expires_at = clock_timestamp() + make_interval(secs => :ttl) "
                    "WHERE id = :id AND status = 'PENDING' AND lease_owner = :owner "
                    "AND fencing_token = :token AND lease_expires_at > clock_timestamp()"
                ),
                {"id": event_id, "owner": owner, "token": fencing_token, "ttl": lease_ttl_seconds},
            ).rowcount
            == 1
        )

    def outbox_ack(
        self, event_id: str, owner: str, fencing_token: str, ok: bool, error: str | None = None
    ) -> bool:
        """Fenced ack: only the current fenced owner of a PENDING row transitions.

        Failures back off to FAILED at max attempts; success publishes once.
        """
        return (
            self.conn.execute(
                text(
                    "UPDATE job_outbox SET "
                    "status = CASE WHEN :ok THEN 'PUBLISHED' "
                    "WHEN attempts + 1 >= max_attempts THEN 'FAILED' ELSE 'PENDING' END, "
                    "attempts = attempts + 1, "
                    "next_attempt_at = CASE WHEN :ok OR attempts + 1 >= max_attempts THEN next_attempt_at "
                    "ELSE clock_timestamp() + make_interval(secs => "
                    "LEAST(power(2, attempts + 1), 3600)::double precision) END, "
                    "published_at = CASE WHEN :ok THEN clock_timestamp() ELSE published_at END, "
                    "lease_owner = '', fencing_token = '', lease_expires_at = NULL "
                    "WHERE id = :id AND status = 'PENDING' AND lease_owner = :owner "
                    "AND fencing_token = :token AND lease_expires_at > clock_timestamp()"
                ),
                {"id": event_id, "owner": owner, "token": fencing_token, "ok": ok},
            ).rowcount
            == 1
        )

    def outbox_sweep(self, tenant_id: str | None = None, batch: int = 100) -> list[str]:
        """Release expired publisher leases back to PENDING (no attempt spent).

        Concurrent sweepers serialize on row locks: each lease released once.
        """
        rows = (
            self.conn.execute(
                text(
                    "UPDATE job_outbox SET lease_owner = '', fencing_token = '', "
                    "lease_expires_at = NULL, next_attempt_at = clock_timestamp() "
                    "WHERE id IN (SELECT id FROM job_outbox WHERE status = 'PENDING' "
                    "AND lease_expires_at IS NOT NULL AND lease_expires_at <= clock_timestamp() "
                    "AND (CAST(:tenant AS UUID) IS NULL OR tenant_id = CAST(:tenant AS UUID)) "
                    "ORDER BY lease_expires_at LIMIT :batch FOR UPDATE SKIP LOCKED) "
                    "RETURNING id"
                ),
                {"tenant": tenant_id, "batch": batch},
            )
            .mappings()
            .all()
        )
        return [str(r["id"]) for r in rows]

    # -- observability (metadata only: counts + ages, never payloads/hashes) --
    def metrics(self, tenant_id: str | None = None) -> dict[str, Any]:
        job_rows = self.conn.execute(
            text(
                "SELECT status, COUNT(*), "
                "MAX(EXTRACT(EPOCH FROM (clock_timestamp() - created_at))) "
                "FROM extraction_jobs "
                "WHERE (CAST(:tenant AS UUID) IS NULL OR tenant_id = CAST(:tenant AS UUID)) "
                "GROUP BY status"
            ),
            {"tenant": tenant_id},
        ).all()
        outbox_rows = self.conn.execute(
            text(
                "SELECT status, COUNT(*), "
                "MAX(EXTRACT(EPOCH FROM (clock_timestamp() - created_at))) "
                "FROM job_outbox WHERE (CAST(:tenant AS UUID) IS NULL OR tenant_id = CAST(:tenant AS UUID)) "
                "GROUP BY status"
            ),
            {"tenant": tenant_id},
        ).all()
        jobs: dict[str, Any] = {s: {"count": 0, "oldest_seconds": None} for s in _STATUSES}
        for status, count, oldest in job_rows:
            jobs[status] = {"count": int(count), "oldest_seconds": float(oldest) if oldest else 0.0}
        outbox: dict[str, Any] = {s: {"count": 0, "oldest_seconds": None} for s in _OUTBOX_STATUSES}
        for status, count, oldest in outbox_rows:
            outbox[status] = {"count": int(count), "oldest_seconds": float(oldest) if oldest else 0.0}
        return {"jobs": jobs, "outbox": outbox}


class WakeupBus:
    """Non-authoritative Redis wakeups: acceleration only, loss is harmless.

    Every method fails soft (False/None): the PG sweeper/poller always covers.
    Redis outage, restart, or flush only delays workers, never loses jobs.
    """

    def __init__(self, redis_url: str | None, key: str = "tp:pgwake") -> None:
        self._url = redis_url
        self._key = key

    def notify(self, job_id: str) -> bool:
        if not self._url:
            return False
        try:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(self._url, socket_timeout=2)
            client.lpush(self._key, job_id)
            client.close()
            return True
        except Exception:
            log.warning("wakeup notify failed (non-fatal)", exc_info=False)
            return False

    def wait(self, timeout_seconds: float) -> str | None:
        if not self._url or timeout_seconds <= 0:
            return None
        try:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(self._url, socket_timeout=timeout_seconds + 2)
            try:
                found: Any = client.brpop([self._key], timeout=max(1, int(timeout_seconds)))
            finally:
                client.close()
            if not found:
                return None
            value = found[1]
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)
        except Exception:
            return None


def _heartbeat(
    factory: Callable[[], Any],
    job_id: str,
    worker_id: str,
    token: str,
    lease_ttl: float,
    stop: threading.Event,
) -> None:
    """Renew until stopped or lease lost (lost lease is logged, not fatal)."""
    while not stop.wait(lease_ttl / 3.0):
        try:
            with factory() as dao:
                alive = dao.renew(job_id, worker_id, token, lease_ttl)
                dao.commit()
            if not alive:
                log.warning("durable heartbeat lost lease (job=%s)", job_id)
                return
        except Exception:
            log.exception("durable heartbeat error (job=%s)", job_id)
            return


def serve(
    factory: Callable[[], Any],
    handler: Callable[[dict[str, Any]], None],
    *,
    worker_id: str | None = None,
    tenant_id: str | None = None,
    lease_ttl: float = 60.0,
    poll_interval: float = 1.0,
    sweep_interval: float = 10.0,
    recover_batch: int = 100,
    stop_after_jobs: int | None = None,
    idle_timeout: float | None = None,
    deadline_seconds: float | None = None,
    wakeups: WakeupBus | None = None,
) -> dict[str, int]:
    """Serve PG-authoritative jobs until limits hit. Returns observable stats.

    Per-tick connections are short-lived (never shared across threads); the
    handler runs conn-free on a plain dict. Stale settlements are rejected by
    fencing tokens and counted, never applied.
    """
    wid = worker_id or new_worker_id()
    stats = {"completed": 0, "retried": 0, "failed": 0, "stale": 0, "recovered": 0, "recover_runs": 0}
    last_sweep = 0.0
    idle_since: float | None = None
    started_at = time.time()

    def sweep() -> None:
        try:
            with factory() as dao:
                moved = dao.recover_stale(tenant_id, recover_batch)
                dao.commit()
            if moved and wakeups is not None:
                for entry in moved:
                    if entry["status"] == "QUEUED":
                        wakeups.notify(entry["id"])
        except Exception:
            log.exception("durable sweep failed worker=%s", wid)

    sweep()
    stats["recover_runs"] += 1
    while True:
        now = time.time()
        if now - last_sweep >= sweep_interval:
            last_sweep = now
            sweep()
            stats["recover_runs"] += 1
        with factory() as dao:
            job = dao.claim(tenant_id, wid, lease_ttl)
            dao.commit()
        if job is None:
            if wakeups is not None:
                wakeups.wait(poll_interval)
            else:
                time.sleep(poll_interval)
            idle_since = idle_since or now
            if idle_timeout is not None and now - idle_since >= idle_timeout:
                break
            continue
        idle_since = None
        stop = threading.Event()
        beat = threading.Thread(
            target=_heartbeat,
            args=(factory, str(job["id"]), wid, job["fencing_token"], lease_ttl, stop),
            daemon=True,
        )
        beat.start()
        try:
            try:
                handler(job)
            except RetryableError as exc:
                settled = _settle(factory, str(job["id"]), wid, job["fencing_token"], "retry", exc)
            except TerminalError as exc:
                settled = _settle(factory, str(job["id"]), wid, job["fencing_token"], "fail", exc)
            except Exception as exc:  # unexpected handler faults retry transiently
                settled = _settle(factory, str(job["id"]), wid, job["fencing_token"], "retry", exc)
            else:
                settled = _settle(factory, str(job["id"]), wid, job["fencing_token"], "ok", None)
        finally:
            stop.set()
            beat.join(timeout=lease_ttl)
        stats[settled] += 1
        done = stats["completed"] + stats["failed"] + stats["stale"]
        if stop_after_jobs is not None and done >= stop_after_jobs:
            break
        if deadline_seconds is not None and time.time() - started_at >= deadline_seconds:
            break
    return stats


def _safe_diagnostic(exc: Exception) -> tuple[str | None, str | None]:
    """Bound handler-fault diagnostics: class name + first 500 chars, one line.

    Persistent job rows must never absorb unbounded arbitrary exception text
    (future handlers process untrusted content; faults could embed it). Control
    characters become spaces so diagnostics cannot smuggle log lines either.
    """
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(exc))[:500]
    return (f"{type(exc).__name__}: {text}".strip(), type(exc).__name__)


def _settle(
    factory: Callable[[], Any], job_id: str, worker_id: str, token: str, outcome: str, exc: Exception | None
) -> str:
    message, error_class = _safe_diagnostic(exc) if exc else (None, None)
    with factory() as dao:
        if outcome == "ok":
            applied: bool | str | None = dao.finish(job_id, worker_id, token, True)
        elif outcome == "fail":
            applied = dao.finish(job_id, worker_id, token, False, message, error_class)
        else:
            # fail_transient reports its terminal state: retried, or failed at max.
            new_status = dao.fail_transient(job_id, worker_id, token, message or "", error_class or "")
            dao.commit()
            if new_status is None:
                log.warning("durable stale settlement rejected (job=%s)", job_id)
                return "stale"
            return "failed" if new_status == "DEAD" else "retried"
        dao.commit()
    if not applied:
        log.warning("durable stale settlement rejected (job=%s)", job_id)
        return "stale"
    return {"ok": "completed", "fail": "failed", "retry": "retried"}[outcome]


@contextlib.contextmanager
def session(engine: Engine, table_defs: dict) -> Iterator[DurableJobs]:
    """Yield a DurableJobs bound to one short-lived connection (tests/services)."""
    with engine.connect() as conn:
        yield DurableJobs(conn, table_defs)

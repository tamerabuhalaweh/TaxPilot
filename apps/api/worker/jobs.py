"""Minimal queued-job mechanism (Sprint 0 foundation).

Contract: every job has identity, status, attempt count, retry policy, idempotency key,
explicit failure reporting, correlation ID, and health visibility.

Persistence guarantees (honest):
- RedisBackend is DURABLE once Redis acknowledges the enqueue (job hash + idempotency
  record + queue push are applied atomically via Lua). A worker restart never loses an
  acknowledged QUEUED job; a crash mid-RUNNING is recovered by `recover_stale`, which
  requeues RUNNING jobs whose heartbeat expired.
- Delivery is AT-LEAST-ONCE by design. This module never claims exactly-once:
  retries and recovery can redeliver; handlers MUST be idempotent.
- MemoryBackend is process-local, non-durable, and exists for unit tests plus explicit
  local development (`QUEUE_BACKEND=memory`). Production refuses it (see config).

Reconciliation handlers are explicitly out of scope here (Sprint 4, approved contracts).
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger(__name__)

QUEUED = "QUEUED"
RUNNING = "RUNNING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

_JOB_PREFIX = "tp:job:"
_QUEUE_KEY = "tp:queue"
_IDEM_PREFIX = "tp:idem:"
_IDEM_TTL_SECONDS = 7 * 24 * 3600

_CLAIM_LUA = """
local id = redis.call('RPOP', KEYS[1])
while id do
  local key = ARGV[1] .. id
  local status = redis.call('HGET', key, 'status')
  if status == 'QUEUED' then
    redis.call('HSET', key, 'status', 'RUNNING', 'updated_at', ARGV[2])
    redis.call('HINCRBY', key, 'attempts', 1)
    return redis.call('HGETALL', key)
  end
  id = redis.call('RPOP', KEYS[1])
end
return nil
"""

_ENQUEUE_LUA = """
if ARGV[1] ~= '' then
  local existing = redis.call('GET', ARGV[2])
  if existing then
    return redis.call('HGETALL', ARGV[3] .. existing)
  end
end
redis.call('HSET', ARGV[3] .. ARGV[4], 'id', ARGV[4], 'kind', ARGV[5],
           'status', 'QUEUED', 'attempts', '0', 'max_attempts', ARGV[6],
           'idempotency_key', ARGV[1], 'payload', ARGV[7],
           'error', '', 'error_class', '',
           'correlation_id', ARGV[8], 'created_at', ARGV[9], 'updated_at', ARGV[9])
if ARGV[1] ~= '' then
  redis.call('SET', ARGV[2], ARGV[4], 'NX', 'EX', ARGV[10])
end
redis.call('LPUSH', KEYS[1], ARGV[4])
return redis.call('HGETALL', ARGV[3] .. ARGV[4])
"""


@dataclass
class Job:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "noop"
    status: str = QUEUED
    attempts: int = 0
    max_attempts: int = 5
    idempotency_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_class: str | None = None
    correlation_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class MemoryBackend:
    """Process-local FIFO + idempotency index. NOT durable. Tests + explicit local dev only."""

    durable = False

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._by_idempotency: dict[str, str] = {}
        self._queue: list[str] = []

    def enqueue(self, job: Job) -> Job:
        if job.idempotency_key and job.idempotency_key in self._by_idempotency:
            return self._jobs[self._by_idempotency[job.idempotency_key]]
        job.updated_at = time.time()
        self._jobs[job.id] = job
        if job.idempotency_key:
            self._by_idempotency[job.idempotency_key] = job.id
        self._queue.append(job.id)
        return job

    def claim(self) -> Job | None:
        while self._queue:
            job = self._jobs[self._queue.pop(0)]
            if job.status == QUEUED:
                job.status = RUNNING
                job.attempts += 1
                job.updated_at = time.time()
                return job
        return None

    def finish(self, job: Job, ok: bool, error: str | None = None, error_class: str | None = None) -> Job:
        job.status = SUCCEEDED if ok else FAILED
        job.error = error
        job.error_class = error_class
        job.updated_at = time.time()
        return job

    def requeue(self, job: Job, error: str) -> Job:
        job.status = QUEUED
        job.error = error
        job.updated_at = time.time()
        self._queue.append(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def depth(self) -> int:
        return sum(1 for j in self._jobs.values() if j.status == QUEUED)

    def recover_stale(self, max_age_seconds: float) -> int:
        now = time.time()
        recovered = 0
        for job in self._jobs.values():
            if job.status == RUNNING and now - job.updated_at > max_age_seconds:
                job.status = QUEUED
                job.updated_at = now
                self._queue.append(job.id)
                recovered += 1
        return recovered

    def ping(self) -> bool:
        return True


class RedisBackend:
    """Shared Redis queue. DURABLE once enqueue is acknowledged. Redis errors propagate."""

    durable = True

    def __init__(self, url: str, socket_timeout: float = 2.0):
        import redis as redis_lib

        # Any: redis-py ships async-overloaded stubs that mypy cannot narrow for the
        # sync client; runtime behaviour is verified by cross-process integration tests.
        self._redis: Any = redis_lib.Redis.from_url(url, socket_timeout=socket_timeout)
        self._redis.ping()  # fail loudly here; never silently fall back
        self._claim = self._redis.register_script(_CLAIM_LUA)
        self._enqueue_script = self._redis.register_script(_ENQUEUE_LUA)
        log.info("redis queue backend connected")

    @staticmethod
    def _to_job(fields: dict[bytes, bytes]) -> Job:
        raw = {k.decode(): v.decode() for k, v in fields.items()}
        import json as _json

        return Job(
            id=raw["id"],
            kind=raw.get("kind", "noop"),
            status=raw.get("status", QUEUED),
            attempts=int(raw.get("attempts", "0")),
            max_attempts=int(raw.get("max_attempts", "5")),
            idempotency_key=raw.get("idempotency_key") or None,
            payload=_json.loads(raw.get("payload") or "{}"),
            error=raw.get("error") or None,
            error_class=raw.get("error_class") or None,
            correlation_id=raw.get("correlation_id") or None,
            created_at=float(raw.get("created_at", "0")),
            updated_at=float(raw.get("updated_at", "0")),
        )

    def enqueue(self, job: Job) -> Job:
        import json as _json

        now = repr(time.time())
        idem = job.idempotency_key or ""
        result = self._enqueue_script(
            keys=[_QUEUE_KEY],
            args=[
                idem,
                _IDEM_PREFIX + idem if idem else "",
                _JOB_PREFIX,
                job.id,
                job.kind,
                str(job.max_attempts),
                _json.dumps(job.payload),
                job.correlation_id or "",
                now,
                str(_IDEM_TTL_SECONDS),
            ],
        )
        fields = dict(zip(result[::2], result[1::2], strict=False))
        return self._to_job(fields)

    def claim(self) -> Job | None:
        result = self._claim(keys=[_QUEUE_KEY], args=[_JOB_PREFIX, repr(time.time())])
        if not result:
            return None
        fields = dict(zip(result[::2], result[1::2], strict=False))
        return self._to_job(fields)

    def finish(self, job: Job, ok: bool, error: str | None = None, error_class: str | None = None) -> Job:
        now = repr(time.time())
        self._redis.hset(
            _JOB_PREFIX + job.id,
            mapping={
                "status": SUCCEEDED if ok else FAILED,
                "error": error or "",
                "error_class": error_class or "",
                "updated_at": now,
            },
        )
        job.status = SUCCEEDED if ok else FAILED
        job.error = error
        job.error_class = error_class
        return job

    def requeue(self, job: Job, error: str) -> Job:
        now = repr(time.time())
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(_JOB_PREFIX + job.id, mapping={"status": QUEUED, "error": error, "updated_at": now})
        pipe.lpush(_QUEUE_KEY, job.id)
        pipe.execute()
        job.status = QUEUED
        job.error = error
        return job

    def get(self, job_id: str) -> Job | None:
        fields = self._redis.hgetall(_JOB_PREFIX + job_id)
        if not fields:
            return None
        return self._to_job(fields)

    def depth(self) -> int:
        return int(self._redis.llen(_QUEUE_KEY) or 0)

    def recover_stale(self, max_age_seconds: float) -> int:
        cutoff = time.time() - max_age_seconds
        recovered = 0
        for key in self._redis.scan_iter(_JOB_PREFIX + "*", count=100):
            status, updated = self._redis.hmget(key, "status", "updated_at")
            if status == b"RUNNING" and float(updated or 0) < cutoff:
                job_id = key.decode()[len(_JOB_PREFIX) :]
                pipe = self._redis.pipeline(transaction=True)
                pipe.hset(key, mapping={"status": QUEUED, "updated_at": repr(time.time())})
                pipe.lpush(_QUEUE_KEY, job_id)
                pipe.execute()
                recovered += 1
        return recovered

    def ping(self) -> bool:
        self._redis.ping()
        return True


def process_one(backend: Any, handler: Callable[[Job], None]) -> Job | None:
    """Claim one job, run handler(job) -> None (raises on failure), record outcome.

    Retry while attempts remain; terminal FAILED keeps error + class inspectable.
    """
    job = backend.claim()
    if job is None:
        return None
    try:
        handler(job)
    except Exception as exc:  # explicit failure reporting; retry while attempts remain
        message = f"{type(exc).__name__}: {exc}"
        if job.attempts < job.max_attempts:
            backend.requeue(job, f"retryable: {message}")
        else:
            backend.finish(job, False, error=message, error_class=type(exc).__name__)
        return job
    backend.finish(job, True)
    return job


def job_to_dict(job: Job) -> dict[str, Any]:
    return asdict(job)

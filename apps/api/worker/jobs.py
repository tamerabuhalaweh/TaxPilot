"""Minimal queued-job mechanism with fenced leases (Sprint 0 foundation).

Ownership model: every claim mints a unique fencing token (`owner`, one per attempt —
never reused across attempts). Every mutating transition is a SINGLE atomic Lua
script that verifies (status=RUNNING, exact owner token, and lease validity where
required) AND performs the mutation inside the same script. There is deliberately
no separate check-then-write path: a stale worker whose lease expired and whose job
was reclaimed cannot overwrite newer truth — its finish/requeue/renew is rejected
and logged. Heartbeats renew only live, unexpired, still-owned claims.

Lease time comes from the Redis server clock (`TIME` inside Lua), so workers and
the queue never disagree because of client clock skew. This assumes a single Redis
instance; a multi-node deployment would need cross-node fencing (tracked under #35).

Crash recovery: `recover_stale()` atomically transitions each RUNNING job whose
lease expired — requeueing below max attempts, or terminal FAILED with an
exhaustion error at/above max attempts (never requeued past the limit). The runner
invokes it on a bounded interval; no operator action or fleet restart is needed.

Persistence honesty (Sprint 0):
- The queue survives WORKER crashes/restarts while Redis is up.
- It does NOT survive a Redis crash/restart: the shipped compose Redis is a single
  node with default persistence, so acknowledged jobs can be lost if Redis itself
  dies. Exactly-once is never claimed: delivery is at-least-once; handlers MUST be
  idempotent. Production worker use is BLOCKED until OPS-JOBS-01 (#35) closes.

MemoryBackend mirrors the same fencing/lease/CAS semantics for unit tests and
explicit local development only (`QUEUE_BACKEND=memory`; refused in production).

Reconciliation handlers are out of scope (Sprint 4, approved contracts).
"""

import logging
import threading
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

OUT_COMPLETED = "completed"
OUT_RETRIED = "retried"
OUT_FAILED = "failed"
OUT_STALE = "stale"
OUT_EMPTY = "empty"

_JOB_PREFIX = "tp:job:"
_QUEUE_KEY = "tp:queue"
_IDEM_PREFIX = "tp:idem:"
_IDEM_TTL_SECONDS = 7 * 24 * 3600

_NOW_LUA = "local _t = redis.call('TIME'); local now = tonumber(_t[1]) + tonumber(_t[2]) / 1000000 "

_CLAIM_LUA = (
    _NOW_LUA
    + """
local id = redis.call('RPOP', KEYS[1])
while id do
  local key = ARGV[1] .. id
  if redis.call('HGET', key, 'status') == 'QUEUED' then
    redis.call('HSET', key, 'status', 'RUNNING', 'owner', ARGV[2],
               'lease_expires_at', now + tonumber(ARGV[3]), 'updated_at', now)
    redis.call('HINCRBY', key, 'attempts', 1)
    return redis.call('HGETALL', key)
  end
  id = redis.call('RPOP', KEYS[1])
end
return nil
"""
)

# Renew only a live claim: RUNNING + exact owner + lease not yet expired.
_RENEW_LUA = (
    _NOW_LUA
    + """
local key = ARGV[1]
if redis.call('HGET', key, 'status') == 'RUNNING'
   and redis.call('HGET', key, 'owner') == ARGV[2]
   and tonumber(redis.call('HGET', key, 'lease_expires_at') or '0') >= now then
  redis.call('HSET', key, 'lease_expires_at', now + tonumber(ARGV[3]), 'updated_at', now)
  return 1
end
return 0
"""
)

_FINISH_LUA = (
    _NOW_LUA
    + """
local key = ARGV[1]
if redis.call('HGET', key, 'status') == 'RUNNING'
   and redis.call('HGET', key, 'owner') == ARGV[2] then
  redis.call('HSET', key, 'status', ARGV[3], 'error', ARGV[4],
             'error_class', ARGV[5], 'updated_at', now)
  return 1
end
return 0
"""
)

_REQUEUE_LUA = (
    _NOW_LUA
    + """
local key = ARGV[1]
if redis.call('HGET', key, 'status') == 'RUNNING'
   and redis.call('HGET', key, 'owner') == ARGV[2] then
  redis.call('HSET', key, 'status', 'QUEUED', 'owner', '',
             'lease_expires_at', '0', 'error', ARGV[3], 'updated_at', now)
  redis.call('LPUSH', KEYS[1], ARGV[4])
  return 1
end
return 0
"""
)

# Expired RUNNING lease: requeue below max attempts, else terminal FAILED.
# Returns 1 on any transition, 0 when nothing was eligible.
_RECOVER_LUA = (
    _NOW_LUA
    + """
local key = KEYS[1]
if redis.call('HGET', key, 'status') ~= 'RUNNING' then return 0 end
if tonumber(redis.call('HGET', key, 'lease_expires_at') or '0') >= now then return 0 end
local attempts = tonumber(redis.call('HGET', key, 'attempts') or '0')
local max_attempts = tonumber(redis.call('HGET', key, 'max_attempts') or '0')
local id = redis.call('HGET', key, 'id')
local owner = redis.call('HGET', key, 'owner') or ''
if attempts >= max_attempts then
  redis.call('HSET', key, 'status', 'FAILED', 'owner', '',
             'lease_expires_at', '0',
             'error', 'attempts exhausted after ' .. attempts ..
                      ' attempt(s) (max ' .. max_attempts .. '); last owner ' .. owner,
             'error_class', 'MaxAttemptsExhausted', 'updated_at', now)
  return 1
end
redis.call('HSET', key, 'status', 'QUEUED', 'owner', '',
           'lease_expires_at', '0', 'updated_at', now)
redis.call('LPUSH', KEYS[2], id)
return 1
"""
)

_ENQUEUE_LUA = (
    _NOW_LUA
    + """
if ARGV[1] ~= '' then
  local existing = redis.call('GET', ARGV[2])
  if existing then
    return redis.call('HGETALL', ARGV[3] .. existing)
  end
end
redis.call('HSET', ARGV[3] .. ARGV[4], 'id', ARGV[4], 'kind', ARGV[5],
           'status', 'QUEUED', 'attempts', '0', 'max_attempts', ARGV[6],
           'idempotency_key', ARGV[1], 'payload', ARGV[7],
           'error', '', 'error_class', '', 'owner', '', 'lease_expires_at', '0',
           'correlation_id', ARGV[8], 'created_at', now, 'updated_at', now)
if ARGV[1] ~= '' then
  redis.call('SET', ARGV[2], ARGV[4], 'NX', 'EX', ARGV[9])
end
redis.call('LPUSH', KEYS[1], ARGV[4])
return redis.call('HGETALL', ARGV[3] .. ARGV[4])
"""
)


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
    owner: str = ""
    lease_expires_at: float = 0.0
    correlation_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def new_worker_id() -> str:
    return f"worker-{uuid.uuid4().hex[:12]}"


def _mint_token(worker_id: str) -> str:
    """Unique fencing token per claim attempt. Proves which attempt owns the job;
    a bare worker id reused across attempts could validate a stale attempt."""
    return f"{worker_id}:{uuid.uuid4().hex[:8]}"


class MemoryBackend:
    """Process-local fenced-lease queue. NOT durable. Unit tests + explicit local dev only."""

    durable = False

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._by_idempotency: dict[str, str] = {}
        self._queue: list[str] = []
        self._lock = threading.Lock()

    def enqueue(self, job: Job) -> Job:
        with self._lock:
            if job.idempotency_key and job.idempotency_key in self._by_idempotency:
                return self._jobs[self._by_idempotency[job.idempotency_key]]
            job.updated_at = time.time()
            self._jobs[job.id] = job
            if job.idempotency_key:
                self._by_idempotency[job.idempotency_key] = job.id
            self._queue.append(job.id)
            return job

    def claim(self, worker_id: str, lease_ttl: float) -> Job | None:
        now = time.time()
        with self._lock:
            while self._queue:
                job = self._jobs[self._queue.pop(0)]
                if job.status == QUEUED:
                    job.status = RUNNING
                    job.owner = _mint_token(worker_id)
                    job.lease_expires_at = now + lease_ttl
                    job.attempts += 1
                    job.updated_at = now
                    return job
            return None

    def _live(self, job: Job, owner: str) -> bool:
        current = self._jobs.get(job.id)
        return current is not None and current.status == RUNNING and current.owner == owner

    def renew(self, job: Job, owner: str, lease_ttl: float) -> bool:
        now = time.time()
        with self._lock:
            if not self._live(job, owner):
                return False
            current = self._jobs[job.id]
            if current.lease_expires_at < now:
                return False  # expired leases are dead; only recovery may transition
            current.lease_expires_at = now + lease_ttl
            current.updated_at = now
            job.lease_expires_at = current.lease_expires_at
            return True

    def finish(
        self, job: Job, owner: str, ok: bool, error: str | None = None, error_class: str | None = None
    ) -> bool:
        """True when applied; False when rejected as stale. Never overwrites newer truth."""
        with self._lock:
            if not self._live(job, owner):
                return False
            current = self._jobs[job.id]
            current.status = SUCCEEDED if ok else FAILED
            current.error = error
            current.error_class = error_class
            current.updated_at = time.time()
            job.status, job.error, job.error_class = current.status, error, error_class
            return True

    def requeue(self, job: Job, owner: str, error: str) -> bool:
        with self._lock:
            if not self._live(job, owner):
                return False
            current = self._jobs[job.id]
            current.status = QUEUED
            current.owner = ""
            current.lease_expires_at = 0.0
            current.error = error
            current.updated_at = time.time()
            self._queue.append(job.id)
            job.status = QUEUED
            job.error = error
            return True

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def depth(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.status == QUEUED)

    def recover_stale(self) -> int:
        """Atomically transition each expired RUNNING lease: requeue below max
        attempts, terminal FAILED at/above max. Returns transitions made."""
        now = time.time()
        recovered = 0
        with self._lock:
            for job in self._jobs.values():
                if job.status == RUNNING and job.lease_expires_at < now:
                    if job.attempts >= job.max_attempts:
                        job.status = FAILED
                        job.error = (
                            f"attempts exhausted after {job.attempts} attempt(s) "
                            f"(max {job.max_attempts}); last owner {job.owner}"
                        )
                        job.error_class = "MaxAttemptsExhausted"
                    else:
                        job.status = QUEUED
                        self._queue.append(job.id)
                    job.owner = ""
                    job.lease_expires_at = 0.0
                    job.updated_at = now
                    recovered += 1
        return recovered

    def ping(self) -> bool:
        return True


class RedisBackend:
    """Shared Redis queue. Survives worker crashes while Redis is up; NOT Redis-crash
    safe on the default single-node configuration. Redis errors propagate (visible)."""

    durable = False  # Honest: worker-crash resilient only; see module docstring.

    def __init__(self, url: str, socket_timeout: float = 2.0):
        import redis as redis_lib

        # Any: redis-py ships async-overloaded stubs mypy cannot narrow for sync use;
        # runtime behaviour is verified by cross-process integration tests.
        self._redis: Any = redis_lib.Redis.from_url(url, socket_timeout=socket_timeout)
        self._redis.ping()  # fail loudly here; never silently fall back
        self._claim = self._redis.register_script(_CLAIM_LUA)
        self._enqueue_script = self._redis.register_script(_ENQUEUE_LUA)
        self._renew = self._redis.register_script(_RENEW_LUA)
        self._finish = self._redis.register_script(_FINISH_LUA)
        self._requeue = self._redis.register_script(_REQUEUE_LUA)
        self._recover = self._redis.register_script(_RECOVER_LUA)
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
            owner=raw.get("owner") or "",
            lease_expires_at=float(raw.get("lease_expires_at") or 0.0),
            correlation_id=raw.get("correlation_id") or None,
            created_at=float(raw.get("created_at", "0")),
            updated_at=float(raw.get("updated_at", "0")),
        )

    @staticmethod
    def _fields(result: list) -> dict[bytes, bytes]:
        return dict(zip(result[::2], result[1::2], strict=False))

    def enqueue(self, job: Job) -> Job:
        import json as _json

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
                str(_IDEM_TTL_SECONDS),
            ],
        )
        return self._to_job(self._fields(result))

    def claim(self, worker_id: str, lease_ttl: float) -> Job | None:
        result = self._claim(keys=[_QUEUE_KEY], args=[_JOB_PREFIX, _mint_token(worker_id), str(lease_ttl)])
        if not result:
            return None
        return self._to_job(self._fields(result))

    def renew(self, job: Job, owner: str, lease_ttl: float) -> bool:
        return bool(self._renew(keys=[], args=[_JOB_PREFIX + job.id, owner, str(lease_ttl)]))

    def finish(
        self, job: Job, owner: str, ok: bool, error: str | None = None, error_class: str | None = None
    ) -> bool:
        return bool(
            self._finish(
                keys=[],
                args=[
                    _JOB_PREFIX + job.id,
                    owner,
                    SUCCEEDED if ok else FAILED,
                    error or "",
                    error_class or "",
                ],
            )
        )

    def requeue(self, job: Job, owner: str, error: str) -> bool:
        return bool(self._requeue(keys=[_QUEUE_KEY], args=[_JOB_PREFIX + job.id, owner, error, job.id]))

    def get(self, job_id: str) -> Job | None:
        fields = self._redis.hgetall(_JOB_PREFIX + job_id)
        if not fields:
            return None
        return self._to_job(fields)

    def depth(self) -> int:
        return int(self._redis.llen(_QUEUE_KEY) or 0)

    def recover_stale(self) -> int:
        """Atomically transition each expired RUNNING lease (requeue or terminal
        FAILED at max attempts). Returns transitions made."""
        recovered = 0
        for key in self._redis.scan_iter(_JOB_PREFIX + "*", count=100):
            key_s = key.decode() if isinstance(key, bytes) else str(key)
            if self._recover(keys=[key_s, _QUEUE_KEY], args=[]):
                recovered += 1
        return recovered

    def ping(self) -> bool:
        self._redis.ping()
        return True


def process_one(
    backend: Any, handler: Callable[[Job], None], worker_id: str, lease_ttl: float
) -> tuple[Any, str]:
    """Claim (minting a per-attempt token), run handler, settle with ownership CAS.

    Returns (job_or_None, outcome) with outcome in completed|retried|failed|stale|empty.
    `stale` means the lease was lost mid-handling: the job was legitimately reclaimed
    elsewhere, so this attempt touches nothing (logged, counted, never overwrites).
    No heartbeat here — for handlers that may outrun the lease use runner.serve().
    """
    job = backend.claim(worker_id, lease_ttl)
    if job is None:
        return None, OUT_EMPTY
    owner = job.owner
    try:
        handler(job)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if job.attempts < job.max_attempts:
            if backend.requeue(job, owner, f"retryable: {message}"):
                return job, OUT_RETRIED
        else:
            if backend.finish(job, owner, False, error=message, error_class=type(exc).__name__):
                return job, OUT_FAILED
        log.warning("stale attempt discarded (job=%s owner=%s)", job.id, owner)
        return job, OUT_STALE
    if backend.finish(job, owner, True):
        return job, OUT_COMPLETED
    log.warning("stale completion rejected (job=%s owner=%s)", job.id, owner)
    return job, OUT_STALE


def job_to_dict(job: Job) -> dict[str, Any]:
    return asdict(job)

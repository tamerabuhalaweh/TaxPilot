"""Minimal queued-job mechanism with leases (Sprint 0 foundation).

Ownership model: every claim carries a fencing token (`owner`) plus a lease deadline.
All mutating transitions are atomic compare-and-set against (status=RUNNING, owner):
a stale worker whose lease expired — and whose job was legitimately reclaimed —
cannot overwrite newer truth; its finish/requeue is rejected and logged.

Persistence honesty (Sprint 0):
- The queue survives WORKER crashes/restarts while Redis is up (jobs live in Redis,
  recovery requeues expired leases automatically on a bounded interval).
- It does NOT survive a Redis crash/restart: the shipped compose Redis is a
  single node with default persistence (RDB snapshots only), so acknowledged jobs
  can be lost if Redis itself dies. Nothing here is "crash-safe durable-on-ack"
  across Redis failures, and exactly-once is never claimed: delivery is
  at-least-once; handlers MUST be idempotent.
- Production worker use is BLOCKED until OPS-JOBS-01 (#35) closes: the runner
  refuses to start in production without explicit durability approval, and the
  development-only limits are documented (not mistakable for guarantees).

MemoryBackend mirrors the same lease/CAS semantics for unit tests and explicit
local development only (`QUEUE_BACKEND=memory`; refused in production).

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

_CLAIM_LUA = """
local id = redis.call('RPOP', KEYS[1])
while id do
  local key = ARGV[1] .. id
  if redis.call('HGET', key, 'status') == 'QUEUED' then
    redis.call('HSET', key, 'status', 'RUNNING', 'owner', ARGV[2],
               'lease_expires_at', ARGV[3], 'updated_at', ARGV[4])
    redis.call('HINCRBY', key, 'attempts', 1)
    return redis.call('HGETALL', key)
  end
  id = redis.call('RPOP', KEYS[1])
end
return nil
"""

_GUARDED_LUA = """
local key = ARGV[1]
if redis.call('HGET', key, 'status') == 'RUNNING'
   and redis.call('HGET', key, 'owner') == ARGV[2] then
  return 1
end
return 0
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
           'error', '', 'error_class', '', 'owner', '', 'lease_expires_at', '0',
           'correlation_id', ARGV[8], 'created_at', ARGV[9], 'updated_at', ARGV[9])
if ARGV[1] ~= '' then
  redis.call('SET', ARGV[2], ARGV[4], 'NX', 'EX', ARGV[10])
end
redis.call('LPUSH', KEYS[1], ARGV[4])
return redis.call('HGETALL', ARGV[3] .. ARGV[4])
"""

_RECOVER_LUA = """
local key = KEYS[1]
if redis.call('HGET', key, 'status') == 'RUNNING'
   and tonumber(redis.call('HGET', key, 'lease_expires_at') or '0') < tonumber(ARGV[1]) then
  local id = redis.call('HGET', key, 'id')
  redis.call('HSET', key, 'status', 'QUEUED', 'owner', '',
             'lease_expires_at', '0', 'updated_at', ARGV[2])
  redis.call('LPUSH', KEYS[2], id)
  return 1
end
return 0
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
    owner: str = ""
    lease_expires_at: float = 0.0
    correlation_id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


def new_worker_id() -> str:
    return f"worker-{uuid.uuid4().hex[:12]}"


class MemoryBackend:
    """Process-local lease queue. NOT durable. Unit tests + explicit local dev only."""

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

    def claim(self, owner: str, lease_ttl: float) -> Job | None:
        now = time.time()
        with self._lock:
            while self._queue:
                job = self._jobs[self._queue.pop(0)]
                if job.status == QUEUED:
                    job.status = RUNNING
                    job.owner = owner
                    job.lease_expires_at = now + lease_ttl
                    job.attempts += 1
                    job.updated_at = now
                    return job
            return None

    def _guarded(self, job: Job, owner: str) -> bool:
        current = self._jobs.get(job.id)
        return current is not None and current.status == RUNNING and current.owner == owner

    def renew(self, job: Job, owner: str, lease_ttl: float) -> bool:
        with self._lock:
            if not self._guarded(job, owner):
                return False
            current = self._jobs[job.id]
            current.lease_expires_at = time.time() + lease_ttl
            current.updated_at = time.time()
            job.lease_expires_at = current.lease_expires_at
            return True

    def finish(
        self, job: Job, owner: str, ok: bool, error: str | None = None, error_class: str | None = None
    ) -> bool:
        """True when applied; False when rejected as stale (owner/lease lost). Never overwrites."""
        with self._lock:
            if not self._guarded(job, owner):
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
            if not self._guarded(job, owner):
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
        """Requeue RUNNING jobs whose lease expired. Returns count. Atomic per job."""
        now = time.time()
        recovered = 0
        with self._lock:
            for job in self._jobs.values():
                if job.status == RUNNING and job.lease_expires_at < now:
                    job.status = QUEUED
                    job.owner = ""
                    job.lease_expires_at = 0.0
                    job.updated_at = now
                    self._queue.append(job.id)
                    recovered += 1
        return recovered

    def ping(self) -> bool:
        return True


class RedisBackend:
    """Shared Redis queue. Survives worker crashes while Redis is up; NOT Redis-crash
    safe on the default single-node configuration. Redis errors propagate (visible)."""

    durable = False  # Honest default: worker-crash resilient only; see module docstring.

    def __init__(self, url: str, socket_timeout: float = 2.0):
        import redis as redis_lib

        # Any: redis-py ships async-overloaded stubs mypy cannot narrow for sync use;
        # runtime behaviour is verified by cross-process integration tests.
        self._redis: Any = redis_lib.Redis.from_url(url, socket_timeout=socket_timeout)
        self._redis.ping()  # fail loudly here; never silently fall back
        self._claim = self._redis.register_script(_CLAIM_LUA)
        self._enqueue_script = self._redis.register_script(_ENQUEUE_LUA)
        self._guarded = self._redis.register_script(_GUARDED_LUA)
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
        return self._to_job(self._fields(result))

    def claim(self, owner: str, lease_ttl: float) -> Job | None:
        now = time.time()
        result = self._claim(keys=[_QUEUE_KEY], args=[_JOB_PREFIX, owner, repr(now + lease_ttl), repr(now)])
        if not result:
            return None
        return self._to_job(self._fields(result))

    def renew(self, job: Job, owner: str, lease_ttl: float) -> bool:
        now = time.time()
        key = _JOB_PREFIX + job.id
        ok = self._guarded(keys=[], args=[key, owner])
        if not ok:
            return False
        self._redis.hset(key, mapping={"lease_expires_at": repr(now + lease_ttl), "updated_at": repr(now)})
        job.lease_expires_at = now + lease_ttl
        return True

    def finish(
        self, job: Job, owner: str, ok: bool, error: str | None = None, error_class: str | None = None
    ) -> bool:
        key = _JOB_PREFIX + job.id
        if not self._guarded(keys=[], args=[key, owner]):
            return False
        self._redis.hset(
            key,
            mapping={
                "status": SUCCEEDED if ok else FAILED,
                "error": error or "",
                "error_class": error_class or "",
                "updated_at": repr(time.time()),
            },
        )
        job.status = SUCCEEDED if ok else FAILED
        job.error = error
        job.error_class = error_class
        return True

    def requeue(self, job: Job, owner: str, error: str) -> bool:
        key = _JOB_PREFIX + job.id
        if not self._guarded(keys=[], args=[key, owner]):
            return False
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(
            key,
            mapping={
                "status": QUEUED,
                "owner": "",
                "lease_expires_at": "0",
                "error": error,
                "updated_at": repr(time.time()),
            },
        )
        pipe.lpush(_QUEUE_KEY, job.id)
        pipe.execute()
        job.status = QUEUED
        job.error = error
        return True

    def get(self, job_id: str) -> Job | None:
        fields = self._redis.hgetall(_JOB_PREFIX + job_id)
        if not fields:
            return None
        return self._to_job(fields)

    def depth(self) -> int:
        return int(self._redis.llen(_QUEUE_KEY) or 0)

    def recover_stale(self) -> int:
        """Atomically requeue each RUNNING job whose lease expired. Returns count."""
        now = repr(time.time())
        recovered = 0
        for key in self._redis.scan_iter(_JOB_PREFIX + "*", count=100):
            key_s = key.decode() if isinstance(key, bytes) else str(key)
            if self._recover(keys=[key_s, _QUEUE_KEY], args=[now, now]):
                recovered += 1
        return recovered

    def ping(self) -> bool:
        self._redis.ping()
        return True


def process_one(
    backend: Any, handler: Callable[[Job], None], owner: str, lease_ttl: float
) -> tuple[Any, str]:
    """Claim (as owner), run handler, settle with ownership CAS.

    Returns (job_or_None, outcome) with outcome in completed|retried|failed|stale|empty.
    `stale` means the lease was lost mid-handling: the job was legitimately reclaimed
    elsewhere, so this attempt touches nothing (logged, counted, never overwrites).
    """
    job = backend.claim(owner, lease_ttl)
    if job is None:
        return None, OUT_EMPTY
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

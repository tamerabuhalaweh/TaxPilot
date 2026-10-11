"""Cross-process Redis queue tests (P0-A mandatory evidence).

Producer and worker run in SEPARATE operating-system processes against real Redis.
Same-process claim/process testing is covered by unit tests; it proves nothing here.

Service-gating: REQUIRE_SERVICES=1 (CI) turns an unreachable Redis into a FAILURE.
Locally without Redis these skip with an explicit reason (documented optional mode).
"""

import json
import os
import subprocess
import sys
import uuid

import pytest

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
API_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api")

PRODUCER = """
import json, sys
sys.path.insert(0, {api_dir!r})
from worker.jobs import Job, RedisBackend
b = RedisBackend({redis_url!r})
j = b.enqueue(Job(kind={kind!r}, idempotency_key={idem!r}, max_attempts={attempts!r}))
print(json.dumps({{"id": j.id, "status": j.status}}))
"""

GET_STATUS = """
import json, sys
sys.path.insert(0, {api_dir!r})
from worker.jobs import RedisBackend
b = RedisBackend({redis_url!r})
j = b.get({job_id!r})
print(json.dumps({{"status": j.status if j else None,
                   "attempts": j.attempts if j else None,
                   "error": j.error if j else None,
                   "error_class": j.error_class if j else None}}))
"""

WORKER = """
import sys, time
sys.path.insert(0, {api_dir!r})
from worker.runner import handle
from worker.jobs import RedisBackend, process_one
b = RedisBackend({redis_url!r})
deadline = time.time() + {budget!r}
done = 0
while time.time() < deadline:
    j = process_one(b, handle)
    if j is None:
        time.sleep(0.05)
        continue
    done += 1
    print("DONE", j.id, j.status, flush=True)
    if done >= {limit!r}:
        break
"""

HOLD_THEN_DIE = """
import sys, time
sys.path.insert(0, {api_dir!r})
from worker.jobs import RedisBackend
b = RedisBackend({redis_url!r})
j = b.claim()
print("CLAIMED", j.id if j else None, flush=True)
time.sleep({hold!r})
"""


def _redis_or_gate() -> None:
    try:
        import redis as redis_lib

        redis_lib.Redis.from_url(REDIS_URL, socket_timeout=2).ping()
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"redis unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"redis unreachable (documented optional local mode): {exc}")


def _run(code: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            code.format(api_dir=API_DIR, redis_url=REDIS_URL, **kwargs),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _produce(kind: str = "echo", attempts: int = 5) -> dict:
    idem = f"t-{uuid.uuid4().hex}"
    proc = _run(PRODUCER, kind=kind, idem=idem, attempts=attempts)
    assert (
        proc.returncode == 0
    ), f"producer failed loudly (not silently): {proc.stderr[-2000:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _status(job_id: str) -> dict:
    proc = _run(GET_STATUS, job_id=job_id)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_cross_process_enqueue_then_worker_completes():
    _redis_or_gate()
    produced = _produce()
    assert produced["status"] == "QUEUED"
    worker = _run(WORKER, budget=12, limit=1)
    assert worker.returncode == 0, worker.stderr[-2000:]
    assert f"DONE {produced['id']} SUCCEEDED" in worker.stdout
    assert _status(produced["id"])["status"] == "SUCCEEDED"


def test_duplicate_enqueue_returns_same_logical_job():
    _redis_or_gate()
    idem = f"t-{uuid.uuid4().hex}"
    first = json.loads(
        _run(PRODUCER, kind="echo", idem=idem, attempts=5)
        .stdout.strip()
        .splitlines()[-1]
    )
    second = json.loads(
        _run(PRODUCER, kind="echo", idem=idem, attempts=5)
        .stdout.strip()
        .splitlines()[-1]
    )
    assert first["id"] == second["id"]
    worker = _run(WORKER, budget=12, limit=1)
    assert worker.returncode == 0, worker.stderr[-2000:]
    final = _status(first["id"])
    assert final["status"] == "SUCCEEDED" and final["attempts"] == 1


def test_concurrent_workers_never_double_claim():
    _redis_or_gate()
    ids = [_produce()["id"] for _ in range(6)]
    procs = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                WORKER.format(api_dir=API_DIR, redis_url=REDIS_URL, budget=15, limit=6),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    try:
        for proc in procs:
            proc.wait(timeout=90)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    states = [_status(i) for i in ids]
    assert all(s["status"] == "SUCCEEDED" for s in states), states
    assert (
        sum(s["attempts"] for s in states) == 6
    )  # each logical job attempted exactly once


def test_crashed_worker_claim_recovers_without_loss():
    _redis_or_gate()
    produced = _produce()
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            HOLD_THEN_DIE.format(api_dir=API_DIR, redis_url=REDIS_URL, hold=60),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = holder.stdout.readline() if holder.stdout else ""
        assert f"CLAIMED {produced['id']}" in line
        holder.kill()  # simulate crash before finish: RUNNING with dead owner
        holder.wait(timeout=30)
    finally:
        if holder.poll() is None:
            holder.kill()
    recover = _run(
        "import sys; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "print(RedisBackend({redis_url!r}).recover_stale(0))",
    )
    assert recover.returncode == 0, recover.stderr[-2000:]
    assert recover.stdout.strip().splitlines()[-1] == "1"
    worker = _run(WORKER, budget=12, limit=1)
    assert worker.returncode == 0, worker.stderr[-2000:]
    final = _status(produced["id"])
    assert final["status"] == "SUCCEEDED" and final["attempts"] == 2


def test_retry_exhaustion_keeps_inspectable_failure():
    _redis_or_gate()
    produced = _produce(kind="boom-unsupported-kind", attempts=2)
    worker = _run(WORKER, budget=12, limit=3)
    assert worker.returncode == 0, worker.stderr[-2000:]
    final = _status(produced["id"])
    assert final["status"] == "FAILED"
    assert final["attempts"] == 2
    assert final["error_class"] == "ValueError" and final["error"]


def test_redis_unavailable_fails_loudly_without_silent_fallback():
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, "
            + repr(API_DIR)
            + "); from worker.jobs import RedisBackend; "
            + "RedisBackend('redis://127.0.0.1:9/0', socket_timeout=1)",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode != 0
    assert proc.stderr.strip() != ""
    # production explicitly refuses the memory backend (no silent downgrade path)
    guard = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; os.environ['APP_ENV'] = 'x'; "
            "import sys; sys.path.insert(0, " + repr(API_DIR) + "); "
            "from app.config import Settings; "
            "Settings(environment='production', queue_backend='memory')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert guard.returncode != 0

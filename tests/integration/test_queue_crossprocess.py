"""Cross-process Redis queue tests: leases, auto-recovery, fencing (RQ-1 evidence).

Producer and worker(s) run in SEPARATE operating-system processes against real Redis.
No test calls recover_stale() manually except the double-recovery race itself, which
asserts atomicity — unattended recovery is proven through serve() loops.

Service-gating: REQUIRE_SERVICES=1 (CI) turns an unreachable Redis into a FAILURE.
Locally without Redis these skip with an explicit reason (documented optional mode).
"""

import json
import os
import subprocess
import sys
import time
import uuid

import pytest

REQUIRE_SERVICES = os.environ.get("REQUIRE_SERVICES") == "1"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Test isolation: integration tests use Redis DB 15 (flushed per session) so leftover
# jobs from other runs or engineers sharing localhost can never pollute assertions.
# Production code paths are identical; only the database number differs.
TEST_REDIS_URL = REDIS_URL.rsplit("/", 1)[0] + "/15"
API_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "apps", "api")


@pytest.fixture(scope="session", autouse=True)
def _isolated_redis_db():  # type: ignore[no-untyped-def]
    import redis as redis_lib

    try:
        client = redis_lib.Redis.from_url(TEST_REDIS_URL, socket_timeout=5)
        client.flushdb()
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"test redis unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"test redis unreachable (documented optional local mode): {exc}")
    yield


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
                   "owner": j.owner if j else None,
                   "error": j.error if j else None,
                   "error_class": j.error_class if j else None}}))
"""

# Full serve() loop: periodic auto-recovery + heartbeat + settle. Prints STATS at end.
SERVE = """
import json, sys
sys.path.insert(0, {api_dir!r})
from worker.runner import handle, serve
from worker.jobs import RedisBackend
b = RedisBackend({redis_url!r})
stats = serve(b, handle, worker_id={worker!r}, lease_ttl={lease!r},
              recover_interval={interval!r}, stop_after_jobs={stop!r},
              idle_timeout={idle!r})
print("STATS " + json.dumps(stats), flush=True)
"""

# Claim-and-hold without heartbeat: simulates a crashed worker (lease expires).
HOLD_THEN_DIE = """
import sys, time
sys.path.insert(0, {api_dir!r})
from worker.jobs import RedisBackend
b = RedisBackend({redis_url!r})
j = b.claim({owner!r}, {lease!r})
print("CLAIMED", j.id if j else None, flush=True)
time.sleep({hold!r})
"""


def _redis_or_gate() -> None:
    try:
        import redis as redis_lib

        redis_lib.Redis.from_url(TEST_REDIS_URL, socket_timeout=2).ping()
    except Exception as exc:
        if REQUIRE_SERVICES:
            pytest.fail(f"redis unreachable with REQUIRE_SERVICES=1: {exc}")
        pytest.skip(f"redis unreachable (documented optional local mode): {exc}")


def _run(code: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            code.format(api_dir=API_DIR, redis_url=TEST_REDIS_URL, **kwargs),
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
    worker = _run(SERVE, worker="w-1", lease=30, interval=5, stop=1, idle=30)
    assert worker.returncode == 0, worker.stderr[-2000:]
    assert '"completed": 1' in worker.stdout
    final = _status(produced["id"])
    assert final["status"] == "SUCCEEDED" and final["attempts"] == 1


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
    worker = _run(SERVE, worker="w-1", lease=30, interval=5, stop=1, idle=30)
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
                SERVE.format(
                    api_dir=API_DIR,
                    redis_url=TEST_REDIS_URL,
                    worker=f"w-{n}",
                    lease=30,
                    interval=5,
                    stop=6,
                    idle=25,
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for n in range(2)
    ]
    try:
        for proc in procs:
            proc.wait(timeout=100)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
    assert all(p.returncode == 0 for p in procs)
    states = [_status(i) for i in ids]
    assert all(s["status"] == "SUCCEEDED" for s in states), states
    assert (
        sum(s["attempts"] for s in states) == 6
    )  # each logical job attempted exactly once


def test_crashed_worker_recovers_automatically_while_other_runs():
    """Worker A dies holding a claim (no heartbeat); worker B's serve() loop must
    recover + complete it with NO manual recover_stale() call anywhere in this test."""
    _redis_or_gate()
    produced = _produce()
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            HOLD_THEN_DIE.format(
                api_dir=API_DIR,
                redis_url=TEST_REDIS_URL,
                owner="worker-A",
                lease=2,
                hold=60,
            ),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = holder.stdout.readline() if holder.stdout else ""
        assert f"CLAIMED {produced['id']}" in line
        holder.kill()  # crash before finish; B keeps running throughout
        holder.wait(timeout=30)
    finally:
        if holder.poll() is None:
            holder.kill()
    worker_b = _run(SERVE, worker="worker-B", lease=2, interval=0.5, stop=1, idle=30)
    assert worker_b.returncode == 0, worker_b.stderr[-2000:]
    assert '"recovered": 1' in worker_b.stdout  # unattended recovery observed in logs
    final = _status(produced["id"])
    assert final["status"] == "SUCCEEDED" and final["attempts"] == 2


def test_long_running_worker_with_heartbeat_is_not_stolen():
    _redis_or_gate()
    produced = _produce()
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys, time; sys.path.insert(0, {api_dir!r}); "
                "from worker.jobs import RedisBackend; "
                "from worker.runner import _heartbeat; "
                "import threading; "
                "b = RedisBackend({redis_url!r}); "
                "j = b.claim('worker-live', 2); print('CLAIMED', j.id, j.owner, flush=True); "
                "stop = threading.Event(); "
                "t = threading.Thread(target=_heartbeat, args=(b, j.id, j.owner, 2, stop)); "
                "t.start(); time.sleep(8); stop.set(); t.join(); print('ALIVE-DONE', flush=True)"
            ).format(api_dir=API_DIR, redis_url=TEST_REDIS_URL),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        line = holder.stdout.readline() if holder.stdout else ""
        assert f"CLAIMED {produced['id']} worker-live:" in line
        time.sleep(5)  # past several lease windows; heartbeats must defend the claim
        mid = _status(produced["id"])
        assert mid["status"] == "RUNNING" and mid["owner"].startswith(
            "worker-live:"
        ), mid
        holder.wait(timeout=30)
    finally:
        if holder.poll() is None:
            holder.kill()
    assert holder.returncode == 0, holder.stderr.read()[-2000:] if holder.stderr else ""
    # Cleanup: settle our job so no live RUNNING leftover pollutes later tests.
    settled = _run(
        "import sys; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "b = RedisBackend({redis_url!r}); "
        "j = b.get({job_id!r}); print(b.finish(j, j.owner, True))",
        job_id=produced["id"],
    )
    assert settled.returncode == 0, settled.stderr[-2000:]
    assert _status(produced["id"])["status"] == "SUCCEEDED"


def test_concurrent_recovery_yields_single_claim():
    """Two simultaneous recover_stale() calls on one expired lease: total == 1,
    and exactly one follow-up claim succeeds."""
    _redis_or_gate()
    produced = _produce()
    holder = _run(
        HOLD_THEN_DIE.format(
            api_dir=API_DIR, redis_url=TEST_REDIS_URL, owner="gone", lease=0.5, hold=0.1
        )
    )
    assert holder.returncode == 0, holder.stderr[-2000:]
    time.sleep(1.0)  # let the half-second lease expire
    rec = _run(
        "import sys, threading; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "b = RedisBackend({redis_url!r}); "
        "out = []; "
        "ts = [threading.Thread(target=lambda: out.append(b.recover_stale())) for _ in range(2)]; "
        "[t.start() for t in ts]; [t.join() for t in ts]; print(sum(out))",
    )
    assert rec.returncode == 0, rec.stderr[-2000:]
    assert rec.stdout.strip().splitlines()[-1] == "1"
    c1 = _run(
        "import sys; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "b = RedisBackend({redis_url!r}); "
        "j = b.claim('w-1', 30); print(j.id if j else 'NONE')",
    )
    c2 = _run(
        "import sys; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "b = RedisBackend({redis_url!r}); "
        "j = b.claim('w-2', 30); print(j.id if j else 'NONE')",
    )
    got = sorted(
        line for proc in (c1, c2) for line in proc.stdout.strip().splitlines()[-1:]
    )
    assert got == sorted(["NONE", produced["id"]]), got


def test_stale_finish_cannot_overwrite_newer_attempt():
    """Old owner finishes after its lease was reclaimed: rejected; newer attempt wins."""
    _redis_or_gate()
    produced = _produce()
    expired = _run(
        "import sys, time; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "b = RedisBackend({redis_url!r}); "
        "old = b.claim('w-old', 0.5); print('OLD-OWNER:', old.owner); "
        "time.sleep(1.0); "
        "rec = b.recover_stale(); print('REC:', rec); "
        "new = b.claim('w-new', 30); print('SAME:', new.id == old.id); print('NEW-OWNER:', new.owner); "
        "late = b.finish(old, old.owner, True); "
        "print('LATE:', late); "
        "cur = b.get(old.id); print('STATE:', cur.status, cur.owner, cur.attempts); "
        "ok = b.finish(new, new.owner, True); print('NEWER:', ok)",
    )
    assert expired.returncode == 0, expired.stderr[-2000:]
    lines = expired.stdout.strip().splitlines()
    assert "REC: 1" in lines, lines
    assert "SAME: True" in lines, lines
    assert "LATE: False" in lines, lines
    state = [line for line in lines if line.startswith("STATE:")][0]
    assert state.startswith("STATE: RUNNING w-new:") and state.endswith(" 2"), lines
    assert "NEWER: True" in lines, lines
    assert _status(produced["id"])["status"] == "SUCCEEDED"


def test_old_requeue_cannot_duplicate_a_reclaimed_attempt():
    """Expired attempt requeued by recovery, reclaimed by B; the old worker's late
    requeue must be rejected and must not insert a second queued copy."""
    _redis_or_gate()
    produced = _produce()
    script = (
        "import sys, time; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "import redis as redis_lib; "
        "b = RedisBackend({redis_url!r}); "
        "old = b.claim('w-old', 0.5); "
        "time.sleep(1.0); "
        "print('REC:', b.recover_stale()); "
        "new = b.claim('w-new', 30); "
        "late = b.requeue(old, old.owner, 'late retry'); print('LATE-REQUEUE:', late); "
        "raw = redis_lib.Redis.from_url({redis_url!r}); "
        "print('QUEUED-COPIES:', raw.lrange('tp:queue', 0, -1).count(new.id.encode())); "
        "print('STATE:', b.get(old.id).status, b.get(old.id).owner); "
        "print('FINISH-NEW:', b.finish(new, new.owner, True))"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = proc.stdout.strip().splitlines()
    assert "LATE-REQUEUE: False" in lines, lines
    assert "QUEUED-COPIES: 0" in lines, lines  # claimed by B; no duplicate reinserted
    assert "FINISH-NEW: True" in lines, lines
    assert _status(produced["id"])["status"] == "SUCCEEDED"


def test_old_renewal_cannot_extend_anothers_lease():
    """After reclaim, the old token's heartbeat renewals fail and the new lease is intact."""
    _redis_or_gate()
    produced = _produce()
    script = (
        "import sys, time; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "b = RedisBackend({redis_url!r}); "
        "old = b.claim('w-old', 0.5); "
        "time.sleep(1.0); "
        "b.recover_stale(); "
        "new = b.claim('w-new', 30); print('LEASE-NEW:', new.lease_expires_at); "
        "print('RENEW-OLD:', b.renew(old, old.owner, 30)); "
        "cur = b.get(old.id); print('LEASE-NOW:', cur.lease_expires_at); "
        "print('FINISH-NEW:', b.finish(new, new.owner, True))"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = proc.stdout.strip().splitlines()
    assert "RENEW-OLD: False" in lines, lines
    before = [line for line in lines if line.startswith("LEASE-NEW:")][0].split(":", 1)[
        1
    ]
    after = [line for line in lines if line.startswith("LEASE-NOW:")][0].split(":", 1)[
        1
    ]
    assert before == after, lines  # old renewal extended nothing
    assert _status(produced["id"])["status"] == "SUCCEEDED"


def test_interleaved_finish_vs_reclaim_keeps_single_truth():
    """Force guard/write interleaving: an old finish racing recovery+reclaim must
    leave exactly one truth — old-won (SUCCEEDED, no second attempt) or new-won
    (old rejected, newer RUNNING with attempts==2)."""
    _redis_or_gate()
    script = (
        (
            "import sys, threading; sys.path.insert(0, '@@API@@'); "
            "from worker.jobs import RedisBackend; "
            "import redis as redis_lib; "
            "raw = redis_lib.Redis.from_url('@@REDIS@@'); "
            "raw.hset('tp:job:race', mapping={'id': 'race', 'kind': 'echo', 'status': 'QUEUED', "
            "'attempts': '0', 'max_attempts': '5', 'idempotency_key': '', 'payload': '{}', "
            "'error': '', 'error_class': '', 'owner': '', 'lease_expires_at': '0', "
            "'correlation_id': '', 'created_at': '0', 'updated_at': '0'}); "
            "raw.lpush('tp:queue', 'race'); "
            "b = RedisBackend('@@REDIS@@'); "
            "old = b.claim('w-old', 0.05); "
            "import time; time.sleep(0.3); "  # lease deterministically expired
            "bar = threading.Barrier(2); out = {}\n"
            "def do_finish():\n"
            "    bar.wait(); out['old'] = b.finish(old, old.owner, True)\n"
            "def do_reclaim():\n"
            "    bar.wait(); out['rec'] = b.recover_stale(); "
            "n = b.claim('w-new', 30); out['new'] = (n.id, n.owner, n.attempts) if n else None\n"
            "t1 = threading.Thread(target=do_finish); t2 = threading.Thread(target=do_reclaim); "
            "[t.start() for t in (t1, t2)]; [t.join() for t in (t1, t2)]; "
            "cur = b.get('race'); "
            "print('OLD:', out['old'], 'REC:', out['rec'], 'NEW:', out['new']); "
            "print('FINAL:', cur.status, cur.owner, cur.attempts); "
            "raw.delete('tp:job:race')"
        )
        .replace("@@API@@", repr(API_DIR)[1:-1])
        .replace("@@REDIS@@", TEST_REDIS_URL)
    )
    for _ in range(3):
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        lines = proc.stdout.strip().splitlines()
        final = [line for line in lines if line.startswith("FINAL:")][0]
        first = [line for line in lines if line.startswith("OLD:")][0]
        if "OLD: True" in first:
            # Old won: its SUCCEEDED stands, nothing was requeued/reclaimed.
            assert "FINAL: SUCCEEDED w-old:" in final and final.endswith(" 1"), lines
        else:
            # Recovery won: old rejected, newer attempt owns the job.
            assert "FINAL: RUNNING w-new:" in final and final.endswith(" 2"), lines


def test_two_consecutive_crashes_terminate_at_max_attempts():
    """Two worker crashes with max_attempts=2 and NO handler ever running: the second
    recovery must transition the job to terminal FAILED (not requeue it)."""
    _redis_or_gate()
    produced = _produce(attempts=2)
    script = (
        "import sys, time; sys.path.insert(0, {api_dir!r}); "
        "from worker.jobs import RedisBackend; "
        "b = RedisBackend({redis_url!r}); "
        "first = b.claim('crasher-1', 0.3); print('CLAIMED-1:', first.id); "
        "time.sleep(0.6); "
        "print('RECOVER-1:', b.recover_stale()); "
        "second = b.claim('crasher-2', 0.3); print('ATTEMPTS-2:', second.attempts); "
        "time.sleep(0.6); "
        "print('RECOVER-2:', b.recover_stale())"
    )
    proc = _run(script)
    assert proc.returncode == 0, proc.stderr[-2000:]
    lines = proc.stdout.strip().splitlines()
    assert f"CLAIMED-1: {produced['id']}" in lines, lines
    assert "RECOVER-1: 1" in lines, lines  # attempts 1 < 2 -> requeued
    assert "ATTEMPTS-2: 2" in lines, lines
    assert "RECOVER-2: 1" in lines, lines  # attempts 2 >= 2 -> terminal, counted
    final = _status(produced["id"])
    assert final["status"] == "FAILED", final
    assert final["attempts"] == 2, final
    assert final["error_class"] == "MaxAttemptsExhausted", final
    assert "attempts exhausted" in (final["error"] or ""), final


def test_repeated_crash_recovery_respects_max_attempts():
    _redis_or_gate()
    produced = _produce(kind="boom-unsupported-kind", attempts=2)
    # Crash on first attempt (claim, die), recover via serve loop, then handler fails:
    # attempts hits max -> terminal FAILED, never requeued again.
    holder = _run(
        HOLD_THEN_DIE.format(
            api_dir=API_DIR,
            redis_url=TEST_REDIS_URL,
            owner="crasher",
            lease=1,
            hold=0.1,
        )
    )
    assert holder.returncode == 0, holder.stderr[-2000:]
    assert f"CLAIMED {produced['id']}" in holder.stdout
    worker = _run(SERVE, worker="w-1", lease=2, interval=0.5, stop=1, idle=30)
    assert worker.returncode == 0, worker.stderr[-2000:]
    assert '"failed": 1' in worker.stdout
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
    guard = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, " + repr(API_DIR) + "); "
            "from app.config import Settings; "
            "Settings(environment='production', queue_backend='memory')",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert guard.returncode != 0

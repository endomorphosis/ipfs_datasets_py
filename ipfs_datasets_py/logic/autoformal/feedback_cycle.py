"""Control one local training/repair workflow without replacing its authorities.

Native accelerate owns task claims, edits, validation and completion. The model
registry owns training runs and candidate versions. This journal records phase
execution only; it cannot mark a repair complete or promote a model.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid

from .supervisor_queue import NAMESPACE


class FeedbackCycleError(RuntimeError):
    pass


# These names describe lifecycle state only. Eligibility (including backoff and
# dependencies) must come from the native selector, never these sets alone.
PENDING_STATUSES = frozenset({"proposed", "admitted", "pending", "ready", "todo", "queued", "retrying"})
ACTIVE_STATUSES = frozenset({"in_progress", "claimed", "running"})
UNSUCCESSFUL_STATUSES = frozenset({"blocked", "failed", "quarantined", "cancelled", "skipped", "rejected"})
COMPLETED_STATUSES = frozenset({"complete", "completed", "done"})


def queue_observation(source) -> dict:
    counts, cursor = {}, ""
    while True:
        page = source.list_tasks(cursor=cursor, limit=100)
        for task in page.tasks:
            if task.body.get("board_namespace") != NAMESPACE:
                raise FeedbackCycleError("feedback runner requires a dedicated repair task database")
            counts[task.status] = counts.get(task.status, 0) + 1
        cursor = page.next_cursor
        if not cursor:
            break
    ready = source.ready_tasks(limit=1)
    revision = source.snapshot().revision
    if page.revision != revision or ready.revision != revision:
        raise FeedbackCycleError("queue changed during observation; retry a consistent native snapshot")
    return {"counts": counts, "revision": revision, "has_eligible_task": bool(ready.tasks)}


def next_phase(observation: dict, input_identity: str, previous_training: dict | None) -> str:
    """An empty ready queue is neither task completion nor model improvement."""
    counts = observation["counts"]
    allowed = PENDING_STATUSES | ACTIVE_STATUSES | UNSUCCESSFUL_STATUSES | COMPLETED_STATUSES
    if any(status not in allowed and count for status, count in counts.items()):
        raise FeedbackCycleError("unknown native task status; cannot infer queue completion")
    if any(counts.get(status, 0) for status in ACTIVE_STATUSES):
        raise FeedbackCycleError("existing task execution requires native reconciliation before another owner")
    eligible = observation.get("has_eligible_task")
    if type(eligible) is not bool:
        raise FeedbackCycleError("native task eligibility is required; status counts are not readiness")
    pending = any(counts.get(status, 0) for status in PENDING_STATUSES)
    if eligible and not pending:
        raise FeedbackCycleError("native eligibility conflicts with observed task statuses")
    if eligible:
        return "supervise"
    if any(counts.get(status, 0) for status in UNSUCCESSFUL_STATUSES):
        raise FeedbackCycleError("queue has unresolved/unsuccessful tasks; an empty ready set is not success")
    if pending:
        return "waiting"  # Native backoff/dependencies still govern admission.
    if previous_training is None or previous_training["input_identity"] != input_identity:
        return "train"
    if previous_training["discrepancies"]:
        raise FeedbackCycleError("fresh compiler discrepancies remain despite no ready repair tasks")
    return "idle"


@contextmanager
def exclusive_loop(runtime: Path):
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / "feedback-loop.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FeedbackCycleError("another feedback runner owns this runtime") from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def check_storage(runtime: Path, limit: int, *, reserve: int = 0) -> int:
    if not 1_000_000_000 <= limit <= 50_000_000_000 or reserve < 0:
        raise FeedbackCycleError("invalid storage bounds")
    # Do not traverse directory symlinks or delete any prior result/cache.
    used = sum(path.stat().st_size for path in runtime.rglob("*") if path.is_file())
    if used + reserve >= limit or shutil.disk_usage(runtime).free < reserve:
        raise FeedbackCycleError("storage budget reached; retained artifacts are untouched")
    return used


class PhaseJournal:
    """DuckDB phase bookkeeping, separate from the native task lifecycle."""

    def __init__(self, path: Path):
        import duckdb
        self.connection = duckdb.connect(str(path))
        self.connection.execute("""CREATE TABLE IF NOT EXISTS autoformal_phases (
            id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, status VARCHAR NOT NULL,
            started_at DOUBLE NOT NULL, finished_at DOUBLE, input_identity VARCHAR NOT NULL,
            command_json VARCHAR NOT NULL, log_path VARCHAR NOT NULL, result_json VARCHAR
        )""")

    def close(self):
        self.connection.close()

    def require_no_interrupted_phase(self):
        row = self.connection.execute(
            "SELECT id FROM autoformal_phases WHERE status = 'running' LIMIT 1").fetchone()
        if row:
            raise FeedbackCycleError("unfinished phase requires live-process and receipt reconciliation: " + row[0])

    def start(self, kind: str, input_identity: str, command: list[str], log_path: Path, *, phase_id: str):
        self.connection.execute("INSERT INTO autoformal_phases VALUES (?, ?, 'running', ?, NULL, ?, ?, ?, NULL)",
                                [phase_id, kind, time.time(), input_identity, json.dumps(command), str(log_path)])

    def finish(self, phase_id: str, status: str, result: dict):
        if status not in {"finished", "failed", "stopped"}:
            raise FeedbackCycleError("invalid phase status")
        changed = self.connection.execute(
            "UPDATE autoformal_phases SET status = ?, finished_at = ?, result_json = ? "
            "WHERE id = ? AND status = 'running' RETURNING id",
            [status, time.time(), json.dumps(result, sort_keys=True, allow_nan=False), phase_id]).fetchone()
        if changed is None:
            raise FeedbackCycleError("phase is absent or already terminal")

    def previous_training(self) -> dict | None:
        row = self.connection.execute(
            "SELECT input_identity, result_json FROM autoformal_phases "
            "WHERE kind = 'train' AND status = 'finished' ORDER BY finished_at DESC LIMIT 1").fetchone()
        return {**json.loads(row[1]), "input_identity": row[0]} if row else None


def run_phase(command: list[str], *, cwd: Path, log: Path, runtime: Path,
              storage_limit: int, wall_timeout: float, poll_seconds: float = 5) -> dict:
    """A real child process, bounded and observed until its handle is terminal."""
    if not 0 < wall_timeout <= 7200 or not 0 < poll_seconds <= 30:
        raise FeedbackCycleError("invalid execution time bounds")
    check_storage(runtime, storage_limit, reserve=2_000_000_000)
    if (runtime / "STOP").exists():
        return {"returncode": None, "stop_reason": "operator_stop_before_launch", "launched": False}
    started = time.monotonic()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "IPFS_DATASETS_PY_LAZY_INSTALL_ERGOAI": "0",
           "IPFS_DATASETS_LEGAL_IR_METRIC_DISK_CACHE": "0", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    reason = ""
    def stop_owned_child(child):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=30)
        except subprocess.TimeoutExpired:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
            child.wait()

    with log.open("xb") as stream:
        child = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while child.poll() is None:
                if (runtime / "STOP").exists():
                    reason = "operator_stop"
                elif time.monotonic() - started >= wall_timeout:
                    reason = "phase_wall_timeout"
                try:
                    check_storage(runtime, storage_limit)
                except FeedbackCycleError:
                    reason = "storage_limit"
                if reason:
                    stop_owned_child(child)
                    break
                try:
                    child.wait(timeout=poll_seconds)
                except subprocess.TimeoutExpired:
                    pass  # Observation timeout is not a terminal process.
        except BaseException:
            stop_owned_child(child)
            raise
    return {"returncode": child.returncode, "stop_reason": reason, "launched": True,
            "elapsed_seconds": time.monotonic() - started, "log_path": str(log)}


def phase_id() -> str:
    return "cycle-" + uuid.uuid4().hex

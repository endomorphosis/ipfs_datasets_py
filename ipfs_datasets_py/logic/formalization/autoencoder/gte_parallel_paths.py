"""Dispatch trusted, independent local workers for the 8D/384D/768D paths.

This coordinator imports no model runtimes. The supplied argv is trusted code;
environment identities do not enforce checkpoint checks or filesystem isolation.
Workers must verify their pinned checkpoint and enforce their resource budgets.
``max_parallel`` is a process count, not accelerator or memory admission.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import threading
import time


SCHEMA = "gte-parallel-path-dispatch/v1"
LANE_DIMENSIONS = {"legacy_8d": 8, "source_384d": 384, "multilingual_768d": 768}
JOB_FIELDS = frozenset(("lane_id", "dimension", "runtime_id", "representation_id",
                        "checkpoint_sha256", "state_directory", "output_directory", "command"))
MAX_REPORT_LOG_BYTES = 64 * 1024
_HASH = re.compile(r"[0-9a-fA-F]{64}\Z")


def _string(value, label):
    if type(value) is not str or not value.strip() or "\0" in value:
        raise ValueError("nonempty " + label + " string required")
    return value


def _validate(jobs, max_parallel, timeout_seconds):
    if type(max_parallel) is not int or not 1 <= max_parallel <= 3:
        raise ValueError("max_parallel must be an integer between 1 and 3")
    if timeout_seconds is not None:
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("timeout_seconds must be finite and positive") from error
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
    if type(jobs) is not list or not 1 <= len(jobs) <= 3:
        raise ValueError("one to three JSON jobs required")
    prepared, seen = [], set()
    for job in jobs:
        if type(job) is not dict or set(job) != JOB_FIELDS:
            raise ValueError("closed parallel job fields required")
        lane = job["lane_id"]
        if type(lane) is not str or lane not in LANE_DIMENSIONS or lane in seen:
            raise ValueError("unique supported lane_id required")
        seen.add(lane)
        if type(job["dimension"]) is not int or job["dimension"] != LANE_DIMENSIONS[lane]:
            raise ValueError("dimension differs from lane identity")
        for field in ("runtime_id", "representation_id"):
            _string(job[field], field)
        command = job["command"]
        if command is not None:
            if type(command) is not list or not command:
                raise ValueError("command must be a nonempty argv list or None")
            for argument in command:
                _string(argument, "command argument")
        checkpoint = job["checkpoint_sha256"]
        if not (command is None and checkpoint is None):
            if type(checkpoint) is not str or _HASH.fullmatch(checkpoint) is None:
                raise ValueError("runnable worker requires a full checkpoint SHA256")
        state = Path(_string(job["state_directory"], "state_directory")).resolve()
        output = Path(_string(job["output_directory"], "output_directory")).resolve()
        if state == output:
            raise ValueError("state and output directories must be distinct")
        if state.exists() and not state.is_dir():
            raise ValueError("state_directory must be a directory")
        if command is not None and output.exists():
            raise ValueError("runnable worker requires a fresh output_directory")
        for previous in prepared:
            for path in (state, output):
                for other in (previous["state_directory"], previous["output_directory"]):
                    if path == other or path.is_relative_to(other) or other.is_relative_to(path):
                        raise ValueError("lane directories must not collide or nest across lanes")
        prepared.append({**job, "command": None if command is None else list(command),
                         "state_directory": state, "output_directory": output})
    return prepared


def _base(job):
    return {"lane_id": job["lane_id"], "dimension": job["dimension"],
            "runtime_id": job["runtime_id"], "representation_id": job["representation_id"],
            "checkpoint_sha256": job["checkpoint_sha256"],
            "state_directory": str(job["state_directory"]),
            "output_directory": str(job["output_directory"]),
            "exit_code": None, "stdout": "", "stderr": "", "stdout_bytes": 0,
            "stderr_bytes": 0, "stdout_truncated": False, "stderr_truncated": False,
            "process_launched": False, "worker_checkpoint_verified": False,
            "proof_authority": False, "model_numerics_verified": False}


def _logs(job, report):
    # Files capture full worker output without pipe deadlocks. Only bounded
    # excerpts enter the returned JSON; workers own disk/resource budgets.
    for name in ("stdout", "stderr"):
        path = job["output_directory"] / (name + ".log")
        if not path.exists():
            continue
        size = path.stat().st_size
        with path.open("rb") as stream:
            raw = stream.read(MAX_REPORT_LOG_BYTES)
        report[name] = raw.decode("utf-8", errors="replace")
        report[name + "_bytes"] = size
        report[name + "_truncated"] = size > MAX_REPORT_LOG_BYTES
        report[name + "_path"] = str(path)


def _start(job, register):
    job["output_directory"].mkdir(parents=True, exist_ok=False)
    job["state_directory"].mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    fields = {"LANE": "lane_id", "DIMENSION": "dimension", "RUNTIME": "runtime_id",
              "REPRESENTATION": "representation_id", "CHECKPOINT_SHA256": "checkpoint_sha256",
              "STATE_DIRECTORY": "state_directory", "OUTPUT_DIRECTORY": "output_directory"}
    environment.update({"GTE_PATH_" + name: str(job[field]) for name, field in fields.items()})
    process = None
    try:
        with (job["output_directory"] / "stdout.log").open("xb") as stdout, \
                (job["output_directory"] / "stderr.log").open("xb") as stderr:
            process = subprocess.Popen(job["command"], shell=False, stdin=subprocess.DEVNULL,
                                       stdout=stdout, stderr=stderr, env=environment,
                                       start_new_session=(os.name == "posix"))
            # Transfer ownership before closing handles or returning: a wrapper
            # or interruption immediately after _start remains fully tracked.
            register(process)
        return process
    except BaseException:
        if process is not None:
            _stop(process)
        raise


def _stop(process):
    """Reap workers and terminate descendants remaining in their POSIX group.

    A trusted worker must manage any descendant that detaches from that group.
    Non-POSIX cleanup is limited to the direct worker process.
    """
    def send(sig):
        try:
            if os.name == "posix":
                os.killpg(process.pid, sig)
            elif sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except ProcessLookupError:
            pass

    send(signal.SIGTERM)
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        send(signal.SIGKILL)
        process.wait()
    # A parent may exit on TERM before its children. Ensure the private group
    # cannot retain a worker that continues writing after cleanup.
    if os.name == "posix":
        send(signal.SIGKILL)


@contextmanager
def _defer_launch_sigint(active):
    """Replay the original Python handler after constructor ownership is safe.

    This changes only the main-thread Python handler temporarily. OS signal
    masks remain unchanged, so children do not inherit blocked SIGINT.
    """
    previous = signal.getsignal(signal.SIGINT)
    if previous == signal.SIG_IGN:
        # Preserve ignored disposition in children as well as the caller.
        # An ignored signal cannot interrupt the constructor.
        yield
        return
    deferred = []
    def record(signum, frame):
        deferred.append((signum, frame))
    signal.signal(signal.SIGINT, record)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)
        for signum, frame in deferred:
            if previous == signal.SIG_DFL:
                # Native default termination cannot execute Python cleanup.
                # Stop owned groups, then preserve the original OS disposition.
                for _, process, _ in active:
                    _stop(process)
                os.kill(os.getpid(), signum)
            else:
                previous(signum, frame)


def run_parallel_paths(jobs, *, max_parallel=3, timeout_seconds=None):
    """Run closed trusted argv jobs, preserving each lane's declared identity.

    ``timeout_seconds`` applies separately from each worker's launch. A failed
    or unavailable lane does not stop other lanes. ``command=None`` means
    unavailable and may have no checkpoint hash. Such lanes never launch or
    receive output directories. State directories may exist for explicit resume.
    All declarations are validated before filesystem mutation or worker launch.
    Runnable dispatch requires the main thread so launch SIGINT handling can
    be deferred until ownership is registered, then faithfully restored/replayed.
    On interruption or an unexpected coordinator error, launched groups stop
    before the original exception is raised. Workers own detached descendants.
    Log files are retained in full;
    the returned excerpts are bounded by ``MAX_REPORT_LOG_BYTES`` per stream.
    """
    prepared = _validate(jobs, max_parallel, timeout_seconds)
    if any(job["command"] is not None for job in prepared) and threading.current_thread() is not threading.main_thread():
        raise ValueError("runnable parallel dispatch requires the main thread for safe SIGINT ownership")
    reports = {job["lane_id"]: _base(job) for job in prepared}
    pending, active = [], []
    for job in prepared:
        if job["command"] is None:
            reports[job["lane_id"]].update(status="unavailable", reason="worker_command_not_configured")
        else:
            pending.append(job)
    started = time.monotonic()
    try:
        while pending or active:
            while pending and len(active) < max_parallel:
                job = pending.pop(0)
                report = reports[job["lane_id"]]
                def register(process):
                    report["process_launched"] = True
                    active.append((job, process, time.monotonic()))
                # Python 3.12 Popen construction can be interrupted after fork
                # before its object reaches the caller. Defer actual SIGINT
                # until _start has registered ownership; replay outside the
                # launch-error handler to preserve custom-handler exceptions.
                with _defer_launch_sigint(active):
                    try:
                        _start(job, register)
                    except (OSError, ValueError) as error:
                        # _start reaps any process it launched before failing.
                        active[:] = [entry for entry in active if entry[0] is not job]
                        report.update(status="failed", reason="worker_launch_failed", launch_error=str(error))
                        _logs(job, report)
                        continue
            for entry in list(active):
                job, process, launch_time = entry
                exit_code = process.poll()
                timed_out = exit_code is None and timeout_seconds is not None and time.monotonic() - launch_time >= timeout_seconds
                if timed_out:
                    _stop(process)
                    exit_code = process.returncode
                if exit_code is None:
                    continue
                # A successful/nonzero parent may leave children alive. Finish
                # its entire private group before freeing a concurrency slot or
                # capturing logs, so descendants cannot write after completion.
                if not timed_out:
                    _stop(process)
                report = reports[job["lane_id"]]
                report.update(exit_code=exit_code,
                              status="timed_out" if timed_out else "succeeded" if exit_code == 0 else "failed",
                              elapsed_seconds=time.monotonic() - launch_time)
                _logs(job, report)
                active.remove(entry)
            if active:
                time.sleep(0.01)
    except BaseException:
        for _, process, _ in active:
            _stop(process)
        raise
    lanes = [reports[job["lane_id"]] for job in prepared]
    successes = sum(report["status"] == "succeeded" for report in lanes)
    status = "success" if successes == len(lanes) else "partial" if successes else "failed"
    declaration = [{**job, "state_directory": str(job["state_directory"]),
                    "output_directory": str(job["output_directory"])} for job in prepared]
    binding = hashlib.sha256(json.dumps(declaration, sort_keys=True, allow_nan=False,
                                       separators=(",", ":")).encode()).hexdigest()
    return {"schema": SCHEMA, "status": status, "lanes": lanes,
            "jobs_sha256": binding, "max_parallel": max_parallel,
            "timeout_seconds": timeout_seconds, "elapsed_seconds": time.monotonic() - started,
            "proof_authority": False, "model_numerics_verified": False,
            "child_checkpoint_pin_check_required": True, "filesystem_isolation_enforced": False,
            "resource_admission_enforced": False, "predictions_merged": False,
            "runnable_dispatch_requires_main_thread": True,
            "launch_sigint_deferral": "main_thread_Python_handler_no_OS_mask",
            "cleanup_scope": ("worker_and_descendants_remaining_in_its_POSIX_process_group"
                              if os.name == "posix" else "direct_worker_only_non_POSIX"),
            "scope": "trusted_local_subprocess_dispatch_only"}

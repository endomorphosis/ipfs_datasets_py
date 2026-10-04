"""Bounded workers for independent conditional integer-offset checks.

Only immutable captured bytes, contracts and revision identities cross this
boundary. Database ownership, current-source observations, cache publication
and CAS publication remain the calling thread's responsibility. This module
never treats an aggregate as proof of current repository behavior.
"""
from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import math
import threading
import time
from typing import Any

from .codebase_integer_profile import (
    IntegerOffsetContract, UnsupportedIntegerProfile,
    compile_integer_offset, execute_integer_offset,
)
from .content import cid_for_bytes, cid_for_structured
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane, ResourceLease,
)

MAX_JOBS = 64
MAX_WORKERS = 32
MAX_SOURCE_BYTES = 64 * 1024
MAX_TOTAL_SOURCE_BYTES = 4 * 1024 * 1024
OWNER_MEMORY_MB = 512
WORKER_MEMORY_MB = 512


class IntegerWorkerError(ValueError):
    """Malformed jobs or an insufficient declared batch resource envelope."""


@dataclass(frozen=True, slots=True)
class IntegerCheckJob:
    job_id: str
    source: bytes
    contract: IntegerOffsetContract
    revision: str

    def __post_init__(self) -> None:
        if (type(self.job_id) is not str or not self.job_id or self.job_id != self.job_id.strip()
                or len(self.job_id.encode("utf-8")) > 256
                or any(ord(char) < 32 or ord(char) == 127 for char in self.job_id)):
            raise IntegerWorkerError("job_id must be a bounded nonempty identifier")
        if type(self.source) is not bytes or len(self.source) > MAX_SOURCE_BYTES:
            raise IntegerWorkerError("job source must be exact bytes of at most 64 KiB")
        if type(self.contract) is not IntegerOffsetContract:
            raise IntegerWorkerError("job contract must be an exact IntegerOffsetContract")
        if (type(self.revision) is not str or not self.revision
                or len(self.revision.encode("utf-8")) > 1024
                or any(ord(char) < 32 or ord(char) == 127 for char in self.revision)):
            raise IntegerWorkerError("job revision must be a bounded nonempty identity")

    @property
    def identity(self) -> str:
        """Job content identity deliberately excludes the caller's display ID."""
        return cid_for_structured({"schema": "integer-check-job@1", "source_cid": cid_for_bytes(self.source),
                                   "contract_cid": self.contract.cid, "revision": self.revision})


class _Cancellation:
    def __init__(self, stop: threading.Event, external: Any) -> None:
        self.stop, self.external = stop, external

    def is_set(self) -> bool:
        return self.stop.is_set() or (self.external is not None and self.external.is_set())


def run_integer_checks(
    jobs: list[IntegerCheckJob] | tuple[IntegerCheckJob, ...], *, parent_lease: ResourceLease,
    max_workers: int, cancel_event: Any = None, timeout_seconds: float = 60.0,
    per_check_timeout_seconds: float = 10.0,
) -> list[dict[str, Any]]:
    """Return results in request order after all owned work has joined.

    At most ``min(max_workers, len(jobs))`` futures are submitted at once. Each
    worker reserves one CPU/process slot and 512 MiB before compilation. The
    native profile reserves 256 MiB descendants for sequential Z3/CVC5 checks.
    Pressure denies new worker/solver admissions through the supplied scheduler;
    already-running native processes retain their hard process limits.

    Cancellation, total deadline or an unexpected worker failure cancels sibling
    work and joins it before raising. An individual checker timeout, unavailable
    tool, refutation or unsupported source remains an explicit per-job outcome.
    Source parsing is cooperatively checked between bounded stages; Python work
    is not forcibly preempted. The caller owns and must release the parent lease.
    """
    if type(jobs) not in {list, tuple} or not 1 <= len(jobs) <= MAX_JOBS:
        raise IntegerWorkerError("jobs must be a finite nonempty list/tuple of at most 64 jobs")
    jobs = tuple(jobs)
    if any(type(job) is not IntegerCheckJob for job in jobs):
        raise IntegerWorkerError("each job must be an exact IntegerCheckJob")
    if type(max_workers) is not int or not 1 <= max_workers <= MAX_WORKERS:
        raise IntegerWorkerError("max_workers must be an exact integer from 1 to 32")
    if not isinstance(parent_lease, ResourceLease):
        raise IntegerWorkerError("a shared parent ResourceLease is required")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise IntegerWorkerError("cancel_event must provide is_set")
    for name, value, maximum in (("timeout_seconds", timeout_seconds, 600),
                                 ("per_check_timeout_seconds", per_check_timeout_seconds, 120)):
        if type(value) not in {int, float} or not math.isfinite(value) or not 0 < value <= maximum:
            raise IntegerWorkerError(f"{name} must be finite, positive and at most {maximum}")
    if sum(len(job.source) for job in jobs) > MAX_TOTAL_SOURCE_BYTES:
        raise IntegerWorkerError("batch source exceeds the 4 MiB bound")
    if len({job.job_id for job in jobs}) != len(jobs) or len({job.identity for job in jobs}) != len(jobs):
        raise IntegerWorkerError("duplicate job ID or source/contract/revision identity")
    width = min(max_workers, len(jobs))
    if (parent_lease.cpu_slots < width or parent_lease.child_process_slots < width
            or parent_lease.memory_mb < OWNER_MEMORY_MB + width * WORKER_MEMORY_MB):
        raise IntegerWorkerError("parent requires W CPU/process slots and 512 + 512*W MiB")

    deadline = time.monotonic() + timeout_seconds
    stop = threading.Event()
    cancelled = parent_lease.combined_cancellation_signal(_Cancellation(stop, cancel_event))
    failures: list[BaseException] = []
    failure_lock = threading.Lock()

    def remaining() -> float:
        if cancelled.is_set():
            raise LeaseCancelledError("integer check batch cancelled")
        duration = deadline - time.monotonic()
        if duration <= 0:
            raise LeaseTimeoutError("integer check batch deadline exceeded")
        return duration

    def check(job: IntegerCheckJob) -> dict[str, Any]:
        try:
            with parent_lease.acquire_child(
                lane=ResourceLane.VALIDATION, cpu_slots=1, memory_mb=WORKER_MEMORY_MB,
                child_process_slots=1, timeout=remaining(), cancel_event=cancelled,
                request_id="integer-check:" + job.job_id,
            ) as lease:
                remaining()
                try:
                    compiled = compile_integer_offset(job.source, job.contract, revision=job.revision)
                except UnsupportedIntegerProfile as error:
                    remaining()
                    return {"job_id": job.job_id, "status": "unsupported", "compiled": None,
                            "checks": None, "diagnostics": [str(error)]}
                remaining()
                checks = execute_integer_offset(compiled, parent_lease=lease, cancel_event=cancelled,
                    timeout_seconds=min(per_check_timeout_seconds, remaining()))
                remaining()
                return {"job_id": job.job_id, "status": checks["status"],
                        "compiled": compiled.to_dict(), "checks": checks, "diagnostics": []}
        except BaseException as error:
            with failure_lock:
                if not failures:
                    failures.append(error)
            stop.set()
            raise

    remaining()
    results: list[dict[str, Any] | None] = [None] * len(jobs)
    executor = ThreadPoolExecutor(max_workers=width, thread_name_prefix="integer-check")
    pending = {}
    next_job = 0
    try:
        while pending or next_job < len(jobs):
            with failure_lock:
                if failures:
                    raise failures[0]
            remaining()
            while len(pending) < width and next_job < len(jobs):
                remaining()
                pending[executor.submit(check, jobs[next_job])] = next_job
                next_job += 1
            finished, _ = wait(pending, timeout=min(0.05, remaining()), return_when=FIRST_COMPLETED)
            for future in sorted(finished, key=lambda item: pending[item]):
                ordinal = pending.pop(future)
                results[ordinal] = future.result()
        remaining()
    except BaseException as error:
        stop.set()
        for future in pending:
            future.cancel()
        # A sibling observes the shared stop flag just after the first failing
        # worker records its cause. Preserve that cause rather than reporting
        # the resulting cancellation as an unrelated external cancellation.
        with failure_lock:
            primary = failures[0] if failures else None
        if isinstance(error, LeaseCancelledError) and primary is not None and primary is not error:
            raise primary
        raise
    finally:
        # Native descendants observe stop through their combined cancellation
        # signals. Never leave children running behind a returned partial batch.
        executor.shutdown(wait=True, cancel_futures=True)
    if any(item is None for item in results):
        raise IntegerWorkerError("batch did not produce one result per requested job")
    return results


__all__ = ["IntegerWorkerError", "IntegerCheckJob", "run_integer_checks"]

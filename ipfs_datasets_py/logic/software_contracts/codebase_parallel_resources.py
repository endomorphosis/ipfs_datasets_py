"""One shared reservation for bounded parallel CodebaseIR workers.

The extra control slot lets source observation run while all numerical workers
hold their child leases. Observation uses only the control memory allowance and
serializes the native source connection. The reservation is admission accounting;
the existing numerical runner remains responsible for process RSS enforcement.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
import threading
import time

from ipfs_datasets_py.duckdb_control.codebase_catalog import CodebaseHead
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError,
)
from .codebase_ir import RepositoryCodebaseIndex
from .codebase_resources import acquire_codebase_resources
from . import codebase_source_training as source


@contextmanager
def parallel_codebase_resources(
    index, repository, head, *, workers, worker_memory_mb=1024,
    control_memory_mb=1024, scheduler=None, parent_lease=None,
    cancel_event=None, admission_timeout_seconds=30.0,
    timeout_seconds=120.0, limits=None,
):
    """Yield the root lease, combined cancellation, deadline and source guard.

    Each numerical invocation must acquire its existing one-slot child from the
    yielded lease. The caller must stop and join those invocations before leaving
    this context. A supplied parent remains the sole scheduler authority. Full
    observations are serialized, including their native DuckDB reads, so the
    returned guard may safely be called by local worker threads.
    """
    limits = source.CodebaseFeatureTrainingLimits() if limits is None else limits
    source._require(type(index) is RepositoryCodebaseIndex and index.catalog is not None,
                    "exact native source owner required")
    source._require(type(head) is CodebaseHead,
                    "exact source head required")
    source._require(type(limits) is source.CodebaseFeatureTrainingLimits,
                    "native feature training limits required")
    source._require(type(workers) is int and 1 <= workers <= 8,
                    "one to eight bounded parallel workers required")
    for name, value in (("worker_memory_mb", worker_memory_mb),
                        ("control_memory_mb", control_memory_mb)):
        source._require(type(value) is int and value >= 512,
                        name + " must reserve at least 512 MB")
    source._require(type(timeout_seconds) in {int, float}
                    and math.isfinite(timeout_seconds) and 0 < timeout_seconds <= 600,
                    "bounded parallel deadline required")
    source._require(type(admission_timeout_seconds) in {int, float}
                    and math.isfinite(admission_timeout_seconds)
                    and admission_timeout_seconds >= 0,
                    "finite nonnegative admission deadline required")
    source._require(limits.max_ancestry_bytes + 2 * limits.max_candidate_bytes
                    + limits.max_target_bytes <= control_memory_mb * 1024 * 1024 // 4,
                    "retained byte bounds exceed control admission envelope")
    source._require(limits.max_candidate_bytes <= worker_memory_mb * 1024 * 1024 // 4,
                    "candidate byte bound exceeds worker admission envelope")
    deadline = time.monotonic() + timeout_seconds
    observation_lock = threading.RLock()
    with acquire_codebase_resources(
        scheduler=scheduler, parent_lease=parent_lease, cancel_event=cancel_event,
        timeout_seconds=min(admission_timeout_seconds, timeout_seconds),
        memory_mb=workers * worker_memory_mb + control_memory_mb,
        cpu_slots=workers + 1, child_process_slots=workers + 1,
    ) as lease:
        signal = lease.combined_cancellation_signal(cancel_event)

        def remaining():
            if signal.is_set():
                raise LeaseCancelledError("parallel CodebaseIR training cancelled")
            available = deadline - time.monotonic()
            if available <= 0:
                raise LeaseTimeoutError("parallel CodebaseIR training deadline exceeded")
            return available

        def observe():
            remaining()
            with observation_lock, index.catalog.store._lock:
                available = remaining()
                result = index.observe_current(
                    repository, expected_head=head, parent_lease=lease,
                    cancel_event=signal, timeout_seconds=available,
                    admission_timeout_seconds=min(admission_timeout_seconds, available),
                    memory_mb=control_memory_mb,
                )
                remaining()
                return result

        observe()
        yield lease, signal, remaining, observe
        observe()


__all__ = ["parallel_codebase_resources"]

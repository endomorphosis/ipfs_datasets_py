"""Shared admission for bounded repository snapshot and index preparation.

A caller with an existing datasets lease supplies that lease as the parent.
Otherwise preparation obtains one root from the shared default scheduler.
This is admission accounting, not an active process-memory limit: callers must
bound their input, configure native-library limits and observe cancellation and
their overall deadline while doing work.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
from typing import Iterator

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    CancellationSignal,
    GlobalResourceScheduler,
    ResourceConfigurationError,
    ResourceLane,
    ResourceLease,
    default_proof_admission_timeout_seconds,
    get_global_resource_scheduler,
)


def codebase_admission_timeout(
    timeout_seconds: float | None = None, *, remaining_seconds: float,
) -> float:
    """Resolve the operator default without expanding a caller's work budget.

    Explicit waits, including zero, retain their meaning. The local benchmark
    profile permits transient memory pressure to settle for up to 90 seconds;
    ordinary callers retain the 30 second admission default.
    """
    value = default_proof_admission_timeout_seconds() if timeout_seconds is None else timeout_seconds
    for name, duration in (("timeout_seconds", value), ("remaining_seconds", remaining_seconds)):
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0:
            raise ResourceConfigurationError(f"{name} must be finite and non-negative")
    return min(value, remaining_seconds)


@contextmanager
def acquire_codebase_resources(
    *,
    scheduler: GlobalResourceScheduler | None = None,
    parent_lease: ResourceLease | None = None,
    cancel_event: CancellationSignal | None = None,
    timeout_seconds: float | None = None,
    memory_mb: int = 512,
    cpu_slots: int = 1,
    child_process_slots: int = 1,
) -> Iterator[ResourceLease]:
    """Acquire and release only this preparation's root or child lease.

    ``timeout_seconds`` bounds admission waiting, not execution; omission uses
    the selected profile default. Callers with an execution deadline must pass
    a wait bounded by ``codebase_admission_timeout``. Snapshotting
    launches Git, so even sequential preparation reserves one child-process
    slot. Bounded batches may reserve additional slots for independent native
    workers. A parent already binds the scheduler authority; passing both forms
    is rejected. Independent accelerate budget objects cannot substitute for
    an actual datasets lease.
    """
    if scheduler is not None and parent_lease is not None:
        raise ResourceConfigurationError("choose scheduler or parent_lease, not both")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise TypeError("scheduler must be a datasets GlobalResourceScheduler")
    if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
        raise TypeError("parent_lease must be a datasets ResourceLease")
    if timeout_seconds is None:
        timeout_seconds = default_proof_admission_timeout_seconds()
    for name, value in (("memory_mb", memory_mb), ("cpu_slots", cpu_slots),
                        ("child_process_slots", child_process_slots)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ResourceConfigurationError(f"{name} must be a positive integer")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds < 0
    ):
        raise ResourceConfigurationError("timeout_seconds must be finite and non-negative")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise TypeError("cancel_event must provide is_set()")

    request = dict(
        lane=ResourceLane.SNAPSHOT_EVALUATION,
        cpu_slots=cpu_slots,
        memory_mb=memory_mb,
        child_process_slots=child_process_slots,
        timeout=timeout_seconds,
        cancel_event=cancel_event,
        request_id="codebase-ir:prepare",
    )
    if parent_lease is not None:
        lease = parent_lease.acquire_child(**request)
    else:
        owner = scheduler if scheduler is not None else get_global_resource_scheduler()
        lease = owner.acquire(**request)
    with lease:
        yield lease


__all__ = ["acquire_codebase_resources", "codebase_admission_timeout"]

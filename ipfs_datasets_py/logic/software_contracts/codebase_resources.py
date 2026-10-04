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
    get_global_resource_scheduler,
)


@contextmanager
def acquire_codebase_resources(
    *,
    scheduler: GlobalResourceScheduler | None = None,
    parent_lease: ResourceLease | None = None,
    cancel_event: CancellationSignal | None = None,
    timeout_seconds: float = 30.0,
    memory_mb: int = 512,
    cpu_slots: int = 1,
    child_process_slots: int = 1,
) -> Iterator[ResourceLease]:
    """Acquire and release only this preparation's root or child lease.

    ``timeout_seconds`` bounds admission waiting, not execution. Snapshotting
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


__all__ = ["acquire_codebase_resources"]

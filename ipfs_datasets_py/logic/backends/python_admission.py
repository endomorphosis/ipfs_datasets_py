"""Cooperative scheduler admission for bounded, in-process proof work.

Reservations limit concurrent demand; they do not impose a Python RSS ceiling
or pause an admitted computation when host pressure later changes. Native
runner ownership is independent. Configuration is context-local and inert.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
import threading
import time

from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    LeaseCancelledError,
    ResourceConfigurationError,
    ResourceLease,
    ResourceUnavailableError,
    get_global_resource_scheduler,
)
from .smt.operation_budget import (
    MAX_OPERATION_TIMEOUT_MS,
    current_proof_operation,
    proof_operation_scope,
)


@dataclass(frozen=True)
class _Ownership:
    scheduler: GlobalResourceScheduler | None = None
    parent: ResourceLease | None = None


@dataclass(frozen=True)
class _ActiveWork:
    ownership: _Ownership
    lease: ResourceLease
    signal: "_LeaseSignal"
    pid: int
    thread: int
    memory_mb: int


_OWNERSHIP = ContextVar("python_proof_resource_ownership", default=_Ownership())
_ACTIVE = ContextVar("python_proof_resource_work", default=None)


class _LeaseSignal:
    """Latch revocation, with bounded polling cost during tight Python loops."""

    def __init__(self, lease: ResourceLease):
        self.lease = lease
        self.stopped = False
        self.next_poll = 0.0

    def is_set(self):
        if not self.stopped and time.monotonic() >= self.next_poll:
            self.force()
        return self.stopped

    def force(self):
        self.stopped = self.stopped or self.lease.released or self.lease.cancelled
        self.next_poll = time.monotonic() + 0.05
        return self.stopped


class _Stopped:
    def is_set(self):
        return True


@contextmanager
def python_admission_context(*, scheduler=None, parent_lease=None):
    """Select an independent pool or existing envelope for Python proof work.

    Only actual scheduler/lease objects are accepted. This context neither
    acquires resources nor changes native runner configuration. An omitted
    owner selects the lazy shared default. Explicit parent reservations are
    never released by this context or charged a second time globally.
    """
    if scheduler is not None and parent_lease is not None:
        raise ResourceConfigurationError("supply only scheduler or parent_lease")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise TypeError("scheduler must be an actual GlobalResourceScheduler")
    if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
        raise TypeError("parent_lease must be an actual ResourceLease")
    token = _OWNERSHIP.set(_Ownership(scheduler, parent_lease))
    try:
        yield
    finally:
        _OWNERSHIP.reset(token)


@contextmanager
def admitted_python_work(*, memory_bytes: int):
    """Reserve one CPU and finite memory inside the current proof operation.

    Yield the operation checkpoint for the evaluator's cooperative callbacks.
    The reservation remains live through the caller's entire block, including
    witness construction. Same-thread nested work can reuse the envelope if
    its demand fits. A copied context in another thread acquires its own root
    or a child of the explicitly configured parent, never reuses the active
    thread's one-CPU allocation. No process slots are requested.
    """
    if type(memory_bytes) is not int or memory_bytes <= 0:
        raise ResourceConfigurationError("Python admission requires positive integer memory_bytes")
    operation = current_proof_operation()
    if operation is None:
        raise ResourceConfigurationError("Python admission requires a proof operation scope")
    operation.checkpoint("before Python resource admission")
    memory_mb = (memory_bytes + 1024**2 - 1) // 1024**2
    ownership = _OWNERSHIP.get()
    active = _ACTIVE.get()
    if active is not None and active.pid == os.getpid() and active.thread == threading.get_ident():
        if ownership != active.ownership:
            raise ResourceConfigurationError("cannot switch Python resource ownership inside active work")
        if memory_mb > active.memory_mb:
            raise ResourceUnavailableError("nested Python work exceeds its active memory envelope")
        active.signal.force()
        operation.checkpoint("before nested Python work")
        try:
            yield operation.checkpoint
        except Exception:
            active.signal.force()
            operation.checkpoint("after nested Python failure")
            raise
        else:
            active.signal.force()
            operation.checkpoint("after nested Python work")
        return

    parent = ownership.parent
    if parent is not None:
        if parent.owner_pid != os.getpid():
            raise ResourceConfigurationError("Python admission refuses a foreign parent lease")
        if parent.released or parent.cancelled:
            with proof_operation_scope(timeout_ms=MAX_OPERATION_TIMEOUT_MS, cancellation=_Stopped()):
                pass
        owner = parent._scheduler
    else:
        operation.checkpoint("before Python scheduler resolution")
        owner = ownership.scheduler if ownership.scheduler is not None else get_global_resource_scheduler()
    remaining = operation.checkpoint("before Python resource acquisition")
    try:
        lease = owner.acquire("validation", cpu_slots=1, memory_mb=memory_mb,
            child_process_slots=0, parent_lease=parent, timeout=remaining,
            cancel_event=operation, request_id="python-proof:hyper-fallback")
    except LeaseCancelledError:
        operation.checkpoint("Python admission cancellation")
        # Parent revocation is a cancellation even when the caller's token
        # itself remains clear. Latch it in the existing operation hierarchy.
        with proof_operation_scope(timeout_ms=MAX_OPERATION_TIMEOUT_MS, cancellation=_Stopped()):
            pass
        raise
    signal = _LeaseSignal(lease)
    with lease:
        signal.force()
        with proof_operation_scope(timeout_ms=MAX_OPERATION_TIMEOUT_MS, cancellation=signal) as admitted:
            token = _ACTIVE.set(_ActiveWork(ownership, lease, signal, os.getpid(),
                                           threading.get_ident(), memory_mb))
            try:
                admitted.checkpoint("before admitted Python work")
                try:
                    yield admitted.checkpoint
                except Exception:
                    signal.force()
                    admitted.checkpoint("after admitted Python failure")
                    raise
                else:
                    signal.force()
                    admitted.checkpoint("after admitted Python work")
            finally:
                _ACTIVE.reset(token)
    # Released leases intentionally report cancellation. Do not poll the
    # lease again; only the independent caller/ambient operation remains.
    operation.checkpoint("after Python reservation release")


__all__ = ["python_admission_context", "admitted_python_work"]

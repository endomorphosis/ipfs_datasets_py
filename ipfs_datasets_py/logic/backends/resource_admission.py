"""Default admission for direct native prover adapters.

The plain bounded lifecycle remains available to adapters that already own a
reservation. This subclass adds one actual root or child reservation per native
invocation. Reservations estimate CPU/process use; they are not cgroup limits.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import process
from .process import (
    BoundedToolRunner, ProcessExecutor, ProcessInvocation, RawProcessResult,
    ToolRunLimits, ToolRunRequest, ToolRunResult, ToolRuntime,
)
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, LeaseCancelledError, LeaseTimeoutError,
    ResourceConfigurationError, ResourceLease, ResourceSchedulerError,
    get_global_resource_scheduler,
)


class _Cancellation:
    """Per-invocation sticky signal; native polling never raises scope stops."""

    def __init__(self, signal: Any | None, operation: Any | None = None) -> None:
        self.signal = signal
        self.operation = operation
        self.cancelled = False
        self.ambient_kind = ""

    def is_set(self) -> bool:
        # Always observe the ambient scope, even if the explicit token is set:
        # that scope owns its own latched reason and must survive Event.clear().
        if self.operation is not None and self.operation.is_set():
            from .smt.operation_budget import ProofOperationInterrupted

            try:
                self.operation.checkpoint("admitted native lifecycle")
            except ProofOperationInterrupted as error:
                self.ambient_kind = error.kind
        self.cancelled = process._is_cancelled(self.signal) or self.cancelled
        return self.cancelled or bool(self.ambient_kind)


class ResourceAdmittedToolRunner(BoundedToolRunner):
    """Bounded lifecycle with lazy, default-on shared resource admission.

    Supply ``parent_lease`` to allocate a child inside an existing envelope, or
    ``scheduler`` to select an explicit pool. With neither, execution resolves
    the default shared scheduler. Construction and executable discovery never
    create scheduler state. Injected executors on this class still receive
    admission; callers that already manage admission can inject a plain
    ``BoundedToolRunner`` into a backend instead.

    Memory is the explicit RSS ceiling when supplied, otherwise the explicit
    address-space ceiling. A request with neither is refused. One wall deadline
    covers admission, workspace preparation and execution. Native descendant
    cleanup completes before the reservation is released. An ambient proof
    operation tightens the wall deadline and is observed during admission and
    native execution. Local-only cancellation/timeouts do not revoke a live
    ambient operation. Cleanup may take additional time after interruption.
    """

    def __init__(
        self,
        *,
        scheduler: GlobalResourceScheduler | None = None,
        parent_lease: ResourceLease | None = None,
        cpu_slots: int = 1,
        child_process_slots: int = 1,
        executor: ProcessExecutor
        | Callable[[ProcessInvocation, Any | None], RawProcessResult]
        | None = None,
        workspace_root: str | Path | None = None,
        base_environment: Mapping[str, str] | None = None,
        executable_roots: Sequence[str | Path] = (),
    ) -> None:
        if scheduler is not None and parent_lease is not None:
            raise ResourceConfigurationError("supply only scheduler or parent_lease")
        if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
            raise TypeError("scheduler must be an actual GlobalResourceScheduler")
        if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
            raise TypeError("parent_lease must be an actual ResourceLease")
        for name, value in (("cpu_slots", cpu_slots), ("child_process_slots", child_process_slots)):
            if type(value) is not int or value <= 0:
                raise ResourceConfigurationError(f"{name} must be a positive integer")
        super().__init__(executor=executor, workspace_root=workspace_root,
                         base_environment=base_environment, executable_roots=executable_roots)
        self._resource_scheduler = scheduler
        self._parent_lease = parent_lease
        self.cpu_slots = cpu_slots
        self.child_process_slots = child_process_slots
        self._deadline: ContextVar[float | None] = ContextVar(
            "native_prover_admission_deadline", default=None,
        )
        self._signal: ContextVar[_Cancellation | None] = ContextVar(
            "native_prover_admission_signal", default=None,
        )

    def _failure(self, request: ToolRunRequest, started: float, message: str, *,
                 timed_out: bool = False, cancelled: bool = False) -> ToolRunResult:
        secrets = self._secret_values(request)
        return self._result(
            request, command=process._redact_command(request.argv, secrets),
            raw=RawProcessResult(returncode=None, elapsed_seconds=time.monotonic() - started,
                timed_out=timed_out, cancelled=cancelled,
                resource_exhausted=not (timed_out or cancelled), error=message),
            outputs={}, secrets=secrets, workspace_cleaned=True,
        )

    @staticmethod
    def _stop_flags(
        signal: _Cancellation, deadline: float, combined: Any | None = None,
    ) -> tuple[bool, bool]:
        signal.is_set()
        if combined is not None and process._is_cancelled(combined) and not signal.is_set():
            # A lease-only revocation must remain visible after lease release,
            # but must not revoke a separate, still-live ambient operation.
            signal.cancelled = True
        return (time.monotonic() >= deadline or signal.ambient_kind == "timeout",
                signal.cancelled or signal.ambient_kind == "cancelled")

    @classmethod
    def _mark_stopped(
        cls, result: ToolRunResult, signal: _Cancellation, deadline: float,
        combined: Any | None = None,
    ) -> ToolRunResult:
        timed_out, cancelled = cls._stop_flags(signal, deadline, combined)
        if not (timed_out or cancelled):
            return result
        reason = "cancelled" if cancelled else "timeout"
        return replace(result, timed_out=result.timed_out or timed_out,
            cancelled=result.cancelled or cancelled,
            termination_reason=result.termination_reason or reason,
            error=result.error or ("cancelled during native execution" if cancelled
                                  else "native execution exceeded its shared deadline"))

    @staticmethod
    def _remaining_limits(limits: ToolRunLimits, remaining: float, signal: _Cancellation) -> ToolRunLimits:
        # Preserve the historical no-ambient CPU profile, and never invent a
        # CPU ceiling for callers that left it unspecified. RLIMIT_CPU itself
        # rounds to whole seconds; this is not an aggregate CPU-time budget.
        cpu = limits.cpu_seconds
        if signal.operation is not None and cpu is not None:
            cpu = min(cpu, remaining)
        return replace(limits, timeout_seconds=min(limits.timeout_seconds, remaining), cpu_seconds=cpu)

    def run(
        self,
        request: ToolRunRequest | Sequence[str],
        *,
        cancellation: Any | None = None,
        runtime: ToolRuntime = ToolRuntime.NATIVE,
        limits: ToolRunLimits | None = None,
        stdin: bytes | str | None = None,
        input_files: Mapping[str, bytes | str] | None = None,
        output_paths: Sequence[str] = (),
        environment: Mapping[str, str] | None = None,
        secrets: Sequence[str] = (),
    ) -> ToolRunResult:
        # Import and capture at execution time, never construction or probing.
        from .smt.operation_budget import current_proof_operation

        started = time.monotonic()
        operation = current_proof_operation()
        if not isinstance(request, ToolRunRequest):
            request = ToolRunRequest(argv=request, runtime=runtime,
                limits=limits or ToolRunLimits(), stdin=stdin, input_files=input_files or {},
                output_paths=tuple(output_paths), environment=environment or {}, secrets=tuple(secrets))
        self._validate_request(request)
        signal = _Cancellation(cancellation, operation)
        deadline = started + request.limits.timeout_seconds
        if operation is not None:
            deadline = min(deadline, operation.deadline)

        def refused(message: str, *, timed_out: bool = False,
                    cancelled: bool = False) -> ToolRunResult:
            observed_timeout, observed_cancel = self._stop_flags(signal, deadline)
            return self._failure(request, started, message,
                timed_out=timed_out or observed_timeout,
                cancelled=cancelled or observed_cancel)

        timed_out, cancelled = self._stop_flags(signal, deadline)
        if timed_out or cancelled:
            return refused("operation stopped before resource admission")
        memory_bytes = request.limits.resident_memory_bytes
        if memory_bytes is None:
            memory_bytes = request.limits.memory_bytes
        if memory_bytes is None:
            return refused("resource admission requires a finite memory bound")
        memory_mb = (memory_bytes + 1024**2 - 1) // 1024**2
        deadline_token = self._deadline.set(deadline)
        signal_token = self._signal.set(signal)
        try:
            # Only prelaunch admission failures are normalized here. Errors
            # from execution/workspace cleanup/lease release must propagate.
            parent = self._parent_lease
            try:
                if parent is not None:
                    if parent.owner_pid != os.getpid() or parent.released or parent.cancelled:
                        return refused("inactive or foreign parent lease", cancelled=True)
                    owner = parent._scheduler
                else:
                    timed_out, cancelled = self._stop_flags(signal, deadline)
                    if timed_out or cancelled:
                        return refused("operation stopped before scheduler resolution")
                    owner = self._resource_scheduler or get_global_resource_scheduler()
            except (ResourceSchedulerError, OSError, ValueError) as error:
                return refused(f"resource admission failed: {type(error).__name__}: {error}")
            timed_out, cancelled = self._stop_flags(signal, deadline)
            if timed_out or cancelled:
                return refused("operation stopped before resource acquisition")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return refused("deadline exhausted before admission", timed_out=True)
            try:
                lease = owner.acquire("validation", cpu_slots=self.cpu_slots, memory_mb=memory_mb,
                    child_process_slots=self.child_process_slots, parent_lease=parent,
                    timeout=remaining, cancel_event=signal,
                    request_id="native-prover:" + request.runtime.value)
            except LeaseTimeoutError as error:
                return refused(f"resource admission timed out: {error}", timed_out=True)
            except LeaseCancelledError as error:
                timed_out, cancelled = self._stop_flags(signal, deadline)
                return refused(f"resource admission cancelled: {error}",
                               cancelled=cancelled or not timed_out)
            except (ResourceSchedulerError, OSError, ValueError) as error:
                return refused(f"resource admission failed: {type(error).__name__}: {error}")
            with lease:
                combined = lease.combined_cancellation_signal(signal)
                timed_out, cancelled = self._stop_flags(signal, deadline, combined)
                if timed_out or cancelled:
                    result = refused("operation stopped after resource admission")
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        result = refused("deadline exhausted during admission", timed_out=True)
                    else:
                        bounded = replace(request, limits=self._remaining_limits(request.limits, remaining, signal))
                        result = super().run(bounded, cancellation=combined)
                # BoundedToolRunner has collected outputs and removed the
                # workspace before returning. Keep all actual lifecycle flags.
                result = self._mark_stopped(result, signal, deadline, combined)
            # A released lease deliberately polls as cancelled. Never consult
            # that lease signal here; only captured caller/ambient state remains.
            result = self._mark_stopped(result, signal, deadline)
            return replace(result, elapsed_seconds=max(result.elapsed_seconds, time.monotonic() - started))
        finally:
            self._signal.reset(signal_token)
            self._deadline.reset(deadline_token)

    def _execute(self, invocation: ProcessInvocation, cancellation: Any | None) -> RawProcessResult:
        # Workspace materialization also consumes the single request deadline.
        deadline = self._deadline.get()
        signal = self._signal.get()
        if deadline is None or signal is None:
            raise ResourceConfigurationError("native execution requires an admitted operation")
        timed_out, cancelled = self._stop_flags(signal, deadline, cancellation)
        remaining = deadline - time.monotonic()
        if timed_out or cancelled or remaining <= 0:
            return RawProcessResult(returncode=None, timed_out=timed_out or remaining <= 0,
                                    cancelled=cancelled, error="operation stopped before native launch")
        invocation = replace(invocation, limits=self._remaining_limits(invocation.limits, remaining, signal))
        return super()._execute(invocation, cancellation)


__all__ = ["ResourceAdmittedToolRunner"]

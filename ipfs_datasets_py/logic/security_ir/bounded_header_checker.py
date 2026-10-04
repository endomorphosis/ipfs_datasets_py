"""Explicit Linux leased profile for local header-model Z3 checks.

This adapter leaves the optional legacy checker unchanged. It uses the common
process owner: per-process RLIMIT_AS/CPU, bounded pipe capture, sampled process-
tree RSS (which can overshoot), and termination of the owned process group.
It is not a hard aggregate-memory sandbox or protection against descendants
escaping that group. Cleanup can extend a decision deadline; a late result is
rejected after cleanup. No solver output grants source or mutation authority.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import sys
import threading
import time
from collections.abc import Callable

from ..backends import codebase_process
from ..backends.codebase_process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
from ..backends.smt.differential import SmtRawSolverOutput, SmtSolverRunner
from ..ir_core.protocols import ExecutionBounds
from ..software_contracts.codebase_resources import codebase_admission_timeout
from ...optimizers.logic_theorem_optimizer.resource_scheduler import (
    LeaseCancelledError, LeaseTimeoutError, ResourceLane, ResourceLease,
)

HEADER_EXECUTION_PROFILE = "native-leased-bounded-header-checker@1"
MAX_SCRIPT_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 65_536
MAX_MEMORY_BYTES = 128 * 1024 * 1024
MAX_QUERY_SECONDS = 5.0


class BoundedHeaderCheckerError(ValueError):
    """The required native checker profile could not complete soundly."""


class _FailClosedCancellation:
    """Convert a failed lease-status sample into the owner's cleanup path."""

    def __init__(self, signal):
        self.signal = signal
        self.failed = False

    def is_set(self):
        try:
            return self.failed or bool(self.signal.is_set())
        except Exception:
            self.failed = True
            return True


def _supported_platform() -> None:
    if os.name != "posix" or not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file():
        raise BoundedHeaderCheckerError("required header checker needs Linux procfs and RLIMIT_AS")
    # Same helper selected by the shared owner; no independent launch machinery.
    codebase_process._linux_prlimit_path()


def _seconds(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise BoundedHeaderCheckerError("remaining_seconds must return finite seconds")
    if value <= 0:
        raise LeaseTimeoutError("bounded header checker deadline exceeded")
    return float(value)


def bounded_header_runner(executable: str, *, parent_lease: ResourceLease,
                          remaining_seconds: Callable[[], float],
                          cancel_event=None) -> SmtSolverRunner:
    """Return a sequential solver runner under one caller-owned deadline.

    The caller owns the native parent lease and source/executable provenance.
    This factory starts no process. Each call acquires one validation child and
    bounds admission by the selected resource profile and the caller's remaining
    time. After admission, the first cached version probe and query share
    ExecutionBounds.timeout_ms (at most five seconds). Admission never renews the
    enclosing deadline or changes the query's execution/resource limits.
    The SMT-LIB string is forwarded unchanged. The Z3 resource counter receives
    max_steps through its argv option, not by rewriting the source-bound script.
    """
    if not isinstance(parent_lease, ResourceLease):
        raise TypeError("bounded header checker requires a native datasets parent lease")
    if not callable(remaining_seconds):
        raise TypeError("remaining_seconds must be callable")
    if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
        raise TypeError("cancel_event must provide is_set")
    if type(executable) is not str or not executable or executable != executable.strip() or "\x00" in executable:
        raise BoundedHeaderCheckerError("a local Z3 executable is required")
    deadline = time.monotonic() + _seconds(remaining_seconds())
    _supported_platform()
    selected = shutil.which(executable)
    if selected is None:
        raise FileNotFoundError("required header checker executable is unavailable")
    selected = str(Path(selected).resolve(strict=True))
    runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
    parent_cancel = parent_lease.combined_cancellation_signal(cancel_event)
    lock = threading.Lock()
    version = None

    def remaining(local_deadline=deadline):
        if parent_cancel.is_set():
            raise LeaseCancelledError("bounded header checker cancelled")
        return _seconds(min(deadline - time.monotonic(), local_deadline - time.monotonic(),
                            _seconds(remaining_seconds())))

    def run(smtlib: str, bounds: ExecutionBounds) -> SmtRawSolverOutput:
        nonlocal version
        if type(bounds) is not ExecutionBounds:
            raise TypeError("native ExecutionBounds required")
        if type(smtlib) is not str or not smtlib.strip() or "\x00" in smtlib:
            raise BoundedHeaderCheckerError("SMT-LIB must be a nonempty string without NUL")
        if len(smtlib) > MAX_SCRIPT_BYTES or len(smtlib.encode("utf-8")) > MAX_SCRIPT_BYTES:
            raise BoundedHeaderCheckerError("SMT-LIB exceeds the header profile input bound")
        if bounds.max_memory_bytes > MAX_MEMORY_BYTES or bounds.max_output_bytes > MAX_OUTPUT_BYTES:
            raise BoundedHeaderCheckerError("requested bounds exceed the header profile")
        if not lock.acquire(blocking=False):
            raise BoundedHeaderCheckerError("one header runner cannot execute concurrently")
        phase = "child_admission"
        try:
            started = time.monotonic()
            with parent_lease.acquire_child(lane=ResourceLane.VALIDATION, cpu_slots=1,
                    memory_mb=max(1, math.ceil(bounds.max_memory_bytes / (1024 * 1024))),
                    child_process_slots=1,
                    timeout=codebase_admission_timeout(remaining_seconds=remaining()),
                    cancel_event=parent_cancel, request_id="header-model:z3") as lease:
                local_deadline = time.monotonic() + min(MAX_QUERY_SECONDS, bounds.timeout_ms / 1000, remaining())
                cancellation = _FailClosedCancellation(lease.combined_cancellation_signal(cancel_event))

                def invoke(arguments, text):
                    if cancellation.is_set():
                        raise LeaseCancelledError("bounded header checker cancelled")
                    seconds = remaining(local_deadline)
                    limits = ToolRunLimits(timeout_seconds=seconds,
                        cpu_seconds=max(1, math.ceil(seconds)),
                        memory_bytes=bounds.max_memory_bytes,
                        resident_memory_bytes=bounds.max_memory_bytes,
                        max_input_bytes=MAX_SCRIPT_BYTES,
                        max_output_bytes=bounds.max_output_bytes,
                        max_workspace_bytes=MAX_SCRIPT_BYTES,
                        termination_grace_seconds=0.1)
                    result = run_bounded_stdin_tool([selected, *arguments], text,
                        runner=runner, limits=limits, cancellation=cancellation)
                    if result.cancelled or cancellation.is_set():
                        raise LeaseCancelledError("bounded header checker cancelled")
                    remaining(local_deadline)
                    if result.timed_out:
                        raise LeaseTimeoutError("bounded header checker deadline exceeded")
                    if (result.returncode != 0 or result.unavailable or result.error
                            or result.output_truncated or result.resource_exhausted
                            or result.process_tree_terminated or not result.workspace_cleaned):
                        raise BoundedHeaderCheckerError("bounded native header checker failed")
                    # The owner caps each pipe separately. Accepted combined output
                    # obeys the declared cap; retained pipe bytes are at most twice it.
                    if len(result.stdout.encode()) + len(result.stderr.encode()) > bounds.max_output_bytes:
                        raise BoundedHeaderCheckerError("combined solver output exceeds the declared bound")
                    return result

                if version is None:
                    phase = "version_probe"
                    observed = invoke(["-version"], "")
                    candidate = (observed.stdout or observed.stderr).strip()
                    if not candidate or len(candidate.encode()) > 1024 or "\n" in candidate:
                        raise BoundedHeaderCheckerError("native solver version is missing or malformed")
                    version = candidate
                phase = "query"
                observed = invoke(["-in", "-smt2", f"rlimit={bounds.max_steps}"], smtlib)
                phase = "child_release"
            remaining(local_deadline)  # Includes the child's normal release/cleanup.
            return SmtRawSolverOutput(stdout=observed.stdout, stderr=observed.stderr,
                returncode=0, elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                solver_version=version)
        except Exception as error:
            # A closed phase label describes this invocation, never a guessed
            # host-pressure cause. Preserve the original typed exception and
            # its native admission observation for the enclosing error chain.
            reason = ("cancelled" if isinstance(error, (LeaseCancelledError, InterruptedError))
                else "admission_timeout" if phase == "child_admission"
                    and isinstance(error, LeaseTimeoutError) and error.admission_observation is not None
                else "deadline" if isinstance(error, TimeoutError)
                else "tool_refusal")
            error.header_checker_diagnostic = dict(schema="bounded-header-checker-failure@1",
                phase=phase, reason=reason)
            raise
        finally:
            lock.release()

    remaining()
    return run


__all__ = ["HEADER_EXECUTION_PROFILE", "BoundedHeaderCheckerError", "bounded_header_runner"]

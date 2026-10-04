"""Shared-resource execution for Isabelle goal capture and reconstruction.

One finite deadline covers admission, optional explicit installation, readiness
and the supplied theory. Each native phase uses the installed-runtime profile
and bounded runner. The source is preserved exactly. Operational completion is
not kernel acceptance: the calling adapter owns goal parsing and theorem audits.
Installed tools and source are trusted native programs, not a security sandbox.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import sys
import time

from ...ir_core.claims import FrozenMap, stable_digest
from ...external_provers.isabelle_runtime import theory_command, theory_name
from ..process import BoundedToolRunner, ToolRunLimits, ToolRunRequest, ToolRunResult
from . import isabelle_profile as profile
from .isabelle_preparation import IsabelleRuntimePreparation, prepare_isabelle_runtime
from ....optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLease, LeaseCancelledError, LeaseTimeoutError,
    ResourceUnavailableError, get_global_resource_scheduler,
)

SCHEMA = "isabelle-shared-execution@1"
# Private settings share the profile's aggregate 1 MiB input allowance.
MAX_SOURCE_BYTES = profile.MAX_INPUT_BYTES - 4096
MAX_OUTPUT_BYTES = 1024**2


@dataclass(frozen=True, slots=True)
class IsabelleExecutionResult:
    status: str
    reason_code: str
    mode: str
    elapsed_seconds: float
    resource_lease_id: str
    parent_lease_id: str
    source_sha256: str
    source_bytes: int
    theory_name: str
    preparation: IsabelleRuntimePreparation | None
    observation: ToolRunResult | None
    runtime: FrozenMap
    phase: FrozenMap
    limits: FrozenMap
    installation: FrozenMap
    ownership: FrozenMap
    runtime_unchanged: bool

    @property
    def completed(self) -> bool:
        return self.status == "completed"

    @property
    def native_runtime(self) -> dict:
        return self.runtime.to_dict()

    @property
    def probes(self):
        return self.preparation.probes if self.preparation is not None else ()

    def to_dict(self):
        return {"schema_version": SCHEMA, "status": self.status, "reason_code": self.reason_code,
            "mode": self.mode, "completed": self.completed, "elapsed_seconds": self.elapsed_seconds,
            "resource_lease_id": self.resource_lease_id, "parent_lease_id": self.parent_lease_id,
            "source_sha256": self.source_sha256, "source_bytes": self.source_bytes, "theory_name": self.theory_name,
            "preparation": self.preparation.to_dict() if self.preparation is not None else None,
            "observation": self.observation.to_dict() if self.observation is not None else None,
            "native_runtime": self.native_runtime, "phase": self.phase.to_dict(), "limits": self.limits.to_dict(),
            "installation": self.installation.to_dict(), "ownership": self.ownership.to_dict(),
            "runtime_unchanged": self.runtime_unchanged, "grants_proof_authority": False,
            "grants_repository_authority": False, "requires_fresh_proof_check": True,
            "source_semantics_verified": False, "behavior_authority": False,
            "execution_authority": False, "completion_authority": False,
            "scope": "Exact caller theory under trusted installed Isabelle; operational result only. No source sandbox, proof interpretation or repository correspondence."}


class _OperationFailure(Exception):
    def __init__(self, reason: str, status: str = "error"):
        self.reason, self.status = reason, status


def validate_isabelle_source(source: object) -> bytes:
    """Return bounded UTF-8 input before callers scan or copy source text.

    The cheap character limit precedes scanning and encoding, so rejecting a
    large caller value does not first allocate another large string or buffer.
    Callers that instrument the source must validate the resulting input too.
    """
    if type(source) is not str:
        raise ValueError("source must be exact text without NUL")
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError(f"source must contain 1..{MAX_SOURCE_BYTES} UTF-8 bytes")
    if "\0" in source:
        raise ValueError("source must be exact text without NUL")
    try:
        data = source.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("source must be valid UTF-8 text") from exc
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(f"source must contain 1..{MAX_SOURCE_BYTES} UTF-8 bytes")
    return data


def run_isabelle_operation(
    *, mode: str = "command", source: str | None = None,
    executable: str | Path | None = None, install_root: str | Path | None = None,
    auto_install: bool = False, parent_lease: ResourceLease | None = None,
    scheduler: GlobalResourceScheduler | None = None, cancellation=None,
    timeout_seconds: float = 30, memory_mb: int = 2048, cpu_seconds: float | None = None,
) -> IsabelleExecutionResult:
    """Observe commands, capture a goal, or run a caller-audited exact theory.

    ``command`` mode never installs and rejects source/auto_install. The other
    modes require a simple named theory within MAX_SOURCE_BYTES. Installation
    is explicit and only attempted for a statically missing runtime, never for
    pressure, a malformed runtime or a failed native probe. An explicit missing
    executable is never redirected to a different installation. cpu_seconds
    conservatively caps the entire wall budget as well as each native CPU cap.
    Supplied parents remain live; only this operation's child envelope is owned.
    """
    if type(mode) is not str or mode not in {"command", "capture", "check"}:
        raise ValueError("mode must be command, capture or check")
    if type(auto_install) is not bool:
        raise TypeError("auto_install must be bool")
    if mode == "command" and (source is not None or auto_install):
        raise ValueError("command mode does not accept source or automatic installation")
    for label, value, maximum in (("timeout_seconds", timeout_seconds, 3600), ("cpu_seconds", cpu_seconds, None)):
        if value is None and label == "cpu_seconds":
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0 or (maximum is not None and value > maximum)):
            raise ValueError(f"{label} must be finite and positive" + (f", at most {maximum}" if maximum else ""))
    if type(memory_mb) is not int or not 1024 <= memory_mb <= 4096:
        raise ValueError("memory_mb must be an exact integer in [1024, 4096]")
    if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
        raise TypeError("parent_lease must be an actual datasets ResourceLease")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise TypeError("scheduler must be an actual datasets GlobalResourceScheduler")
    if parent_lease is not None and scheduler is not None:
        raise ValueError("supply only parent_lease or scheduler")
    if executable is not None and install_root is not None:
        raise ValueError("supply only executable or install_root")
    if cancellation is not None and not callable(getattr(cancellation, "is_set", None)):
        raise TypeError("cancellation must supply is_set()")
    source_data, name = b"", ""
    if mode != "command":
        source_data = validate_isabelle_source(source)
        name = theory_name(source)
    started = time.monotonic()
    wall_budget = min(timeout_seconds, cpu_seconds) if cpu_seconds is not None else timeout_seconds
    deadline = started + wall_budget
    signal, envelope = cancellation, None
    preparation, observation = None, None
    runtime, phase, installation, ownership = {}, {}, {}, {}
    lease_id, runtime_unchanged = "", False
    status, reason = "error", "isabelle_operation_failed"
    limits = {"profile": profile.PROFILE, "timeout_seconds": timeout_seconds,
        "effective_wall_timeout_seconds": wall_budget, "cpu_seconds": cpu_seconds,
        "cpu_scope": "Optional CPU budget conservatively caps operation wall time; native per-process CPU uses remaining wall time rounded up by the OS.",
        "cpu_slots": profile.CPU_SLOTS, "process_slots": profile.PROCESS_SLOTS,
        "reservation_memory_mb": memory_mb + profile.OVERHEAD_MB,
        "resident_memory_bytes": memory_mb * 1024**2, "address_space_bytes": profile.ADDRESS_SPACE_BYTES,
        "max_source_bytes": MAX_SOURCE_BYTES, "max_input_bytes": profile.MAX_INPUT_BYTES,
        "max_output_bytes": MAX_OUTPUT_BYTES, "max_workspace_bytes": profile.MAX_WORKSPACE_BYTES,
        "memory_scope": "Sampled process-tree RSS, per-process address space; not an aggregate cgroup ceiling."}

    def remaining():
        if signal is not None and signal.is_set():
            raise LeaseCancelledError("Isabelle execution cancelled")
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise LeaseTimeoutError("Isabelle execution deadline exceeded")
        return seconds

    try:
        remaining()
        if not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file():
            raise _OperationFailure("linux_resource_guards_required", "unsupported")
        owner = parent_lease._scheduler if parent_lease is not None else scheduler or get_global_resource_scheduler()
        if not owner.config.proof_safety_enabled:
            raise _OperationFailure("pressure_aware_scheduler_required", "admission_denied")
        if parent_lease is not None:
            if parent_lease.owner_pid != os.getpid() or parent_lease.released or parent_lease.cancelled:
                raise _OperationFailure("inactive_parent_lease", "admission_denied")
            if (parent_lease.cpu_slots < profile.CPU_SLOTS or parent_lease.child_process_slots < profile.PROCESS_SLOTS
                    or parent_lease.memory_mb < limits["reservation_memory_mb"]):
                raise _OperationFailure("underfunded_parent_lease", "admission_denied")
        envelope = owner.acquire("validation", cpu_slots=profile.CPU_SLOTS,
            memory_mb=limits["reservation_memory_mb"], child_process_slots=profile.PROCESS_SLOTS,
            parent_lease=parent_lease, timeout=remaining(), cancel_event=cancellation,
            request_id="isabelle:shared-" + mode)
        lease_id = envelope.lease_id
        signal = envelope.combined_cancellation_signal(cancellation)
        ownership = {"operation_lease_id": lease_id, "parent_lease_id": envelope.parent_lease_id,
            "owner_pid": envelope.owner_pid, "scheduler_state_path": str(owner.state_path),
            "cpu_slots": envelope.cpu_slots, "memory_mb": envelope.memory_mb,
            "child_process_slots": envelope.child_process_slots}
        remaining()  # Admission can finish after the caller's deadline.
        try:
            launcher, runtime = profile.resolve_runtime(checkpoint=remaining, install_root=install_root, executable=executable)
        except FileNotFoundError as exc:
            # A missing selected file inside an existing distribution is a
            # malformed runtime, not permission to replace it automatically.
            if (not auto_install or executable is not None
                    or str(exc) != "supported installed Isabelle distribution is missing"):
                raise
            from .isabelle_installation import ensure_isabelle_installation
            installed = ensure_isabelle_installation(yes=True, strict=False, install_root=install_root,
                parent_lease=envelope, cancellation=signal, timeout_seconds=min(3600, remaining()), memory_mb=memory_mb)
            installation = installed.to_dict()
            remaining()
            if not installed.usable:
                raise _OperationFailure("explicit_first_use_installation_failed", "unavailable")
            launcher, runtime = profile.resolve_runtime(checkpoint=remaining, install_root=install_root)
        preparation = prepare_isabelle_runtime(mode="command" if mode == "command" else "hol",
            executable=launcher, parent_lease=envelope, cancellation=signal,
            timeout_seconds=min(300, remaining()), memory_mb=memory_mb)
        remaining()
        if not preparation.usable:
            raise _OperationFailure(preparation.reason_code, preparation.status)
        if stable_digest(preparation.to_dict().get("native_runtime")) != stable_digest(runtime):
            raise _OperationFailure("preparation_runtime_identity_mismatch")
        if mode != "command":
            command = tuple(theory_command(launcher, name, "{workspace}", capture=mode == "capture"))
            request = ToolRunRequest(argv=command, input_files={name + ".thy": source_data},
                limits=ToolRunLimits(timeout_seconds=remaining(), max_output_bytes=MAX_OUTPUT_BYTES))
            runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})
            observation, phase = profile.run_admitted_phase(request, parent_lease=envelope,
                version=runtime["version"], memory_mb=memory_mb, remaining=remaining,
                cancellation=signal, run=runner.run, phase="theory_" + mode)
            remaining()
            if observation.cancelled:
                raise LeaseCancelledError("Isabelle native theory cancelled")
            if observation.timed_out:
                raise LeaseTimeoutError("Isabelle native theory timed out")
            if (observation.command != command or observation.error or observation.unavailable
                    or observation.resource_exhausted or observation.output_truncated
                    or observation.workspace_limit_exceeded or not observation.workspace_cleaned
                    or any(type(getattr(observation, flag)) is not bool for flag in (
                        "cancelled", "timed_out", "unavailable", "resource_exhausted", "output_truncated",
                        "workspace_limit_exceeded", "workspace_cleaned", "process_tree_terminated"))
                    or type(observation.returncode) is not int):
                raise _OperationFailure("bounded_theory_execution_incomplete")
        _, after = profile.resolve_runtime(checkpoint=remaining, install_root=install_root, executable=executable)
        if stable_digest(runtime) != stable_digest(after):
            raise _OperationFailure("isabelle_runtime_identity_changed")
        runtime_unchanged = True
        remaining()
        status, reason = "completed", "bounded_isabelle_operation_completed"
    except LeaseCancelledError:
        status, reason = "cancelled", "isabelle_operation_cancelled"
    except LeaseTimeoutError:
        status, reason = "timed_out", "isabelle_operation_deadline_exceeded"
    except ResourceUnavailableError:
        status, reason = "admission_denied", "resource_admission_unavailable"
    except FileNotFoundError:
        status, reason = "unavailable", "installed_artifact_missing"
    except _OperationFailure as exc:
        status, reason = exc.status, exc.reason
    except (OSError, ValueError, KeyError):
        status, reason = "error", "isabelle_operation_artifact_or_io_invalid"
    finally:
        if envelope is not None:
            envelope.release()
            ownership["operation_release_requested"] = envelope.released
            ownership["supplied_parent_release_requested"] = parent_lease.released if parent_lease is not None else None
    return IsabelleExecutionResult(status, reason, mode, max(0., time.monotonic()-started), lease_id,
        parent_lease.lease_id if parent_lease is not None else "", hashlib.sha256(source_data).hexdigest() if source_data else "",
        len(source_data), name, preparation, observation, FrozenMap(runtime), FrozenMap(phase),
        FrozenMap(limits), FrozenMap(installation), FrozenMap(ownership), runtime_unchanged)


__all__ = ["SCHEMA", "MAX_SOURCE_BYTES", "MAX_OUTPUT_BYTES", "IsabelleExecutionResult",
           "validate_isabelle_source", "run_isabelle_operation"]

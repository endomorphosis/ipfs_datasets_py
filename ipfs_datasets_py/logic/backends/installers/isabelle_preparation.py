"""Admitted observation of an installed Isabelle runtime and optional fixed smoke.

There are no downloads, explicit heap builds, arbitrary theories or injectable
runners. A no-build HOL preflight precedes smoke. Isabelle's process_theories may
still attempt a private bounded rebuild if the trusted installation changes
after that preflight; this is not a filesystem sandbox or an immutable heap
attestation. A successful observation grants no repository or proof authority.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import sys
import time

from ...ir_core.claims import FrozenMap, stable_digest
from ..process import BoundedToolRunner, ToolRunLimits, ToolRunRequest
from . import isabelle_profile as profile
from ....optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceLease, LeaseCancelledError, LeaseTimeoutError,
    ResourceUnavailableError, get_global_resource_scheduler,
)

PREPARATION_SCHEMA = "isabelle-runtime-preparation@1"
SMOKE_PROFILE = "isabelle-installed-true-smoke@1"
SMOKE_SOURCE = 'theory IPFSSetupCheck\nimports Main\nbegin\nlemma ready: "True" by simp\nend\n'
MAX_OUTPUT_BYTES = 32768


@dataclass(frozen=True, slots=True)
class IsabelleRuntimePreparation:
    status: str
    reason_code: str
    mode: str
    readiness_level: str
    elapsed_seconds: float
    resource_lease_id: str
    bindings: FrozenMap
    probes: tuple[FrozenMap, ...]
    limits: FrozenMap

    @property
    def usable(self) -> bool:
        return self.status == "usable"

    @property
    def ready(self) -> bool:
        return self.usable

    @property
    def command_available(self) -> bool:
        return self.readiness_level in {"command", "hol_ready", "kernel_smoke"}

    @property
    def hol_ready(self) -> bool:
        return self.readiness_level in {"hol_ready", "kernel_smoke"}

    @property
    def smoke_accepted(self) -> bool:
        return self.usable and self.readiness_level == "kernel_smoke"

    def to_dict(self):
        return {"schema_version": PREPARATION_SCHEMA, "tool_id": "isabelle",
                "status": self.status, "reason_code": self.reason_code, "mode": self.mode,
                "usable": self.usable, "ready": self.ready, "readiness_level": self.readiness_level,
                "command_available": self.command_available, "hol_ready": self.hol_ready,
                "smoke_accepted": self.smoke_accepted,
                "native_runtime": self.bindings.to_dict().get("runtime"),
                "executable": self.bindings.to_dict().get("runtime", {}).get("executable"),
                "elapsed_seconds": self.elapsed_seconds, "resource_lease_id": self.resource_lease_id,
                "bindings": self.bindings.to_dict(), "probes": [row.to_dict() for row in self.probes],
                "limits": self.limits.to_dict(), "installation_performed": False,
                "explicit_heap_build_requested": False, "grants_proof_authority": False,
                "grants_repository_authority": False, "requires_fresh_proof_check": True,
                "smoke_scope": "Fixed True theorem under trusted installed Main/HOL/Pure; no-oracle audit does not establish HOL is axiom-free.",
                "heap_scope": "No-build HOL preflight; process_theories may attempt a bounded private rebuild if the trusted installation changes afterward."}

    @property
    def digest(self):
        return stable_digest(self.to_dict())


class _PreparationFailure(Exception):
    def __init__(self, reason, status="error"):
        self.reason, self.status = reason, status


def prepare_isabelle_runtime(
    *, mode: str = "command", install_root: str | Path | None = None,
    executable: str | Path | None = None,
    parent_lease: ResourceLease | None = None,
    scheduler: GlobalResourceScheduler | None = None,
    cancellation=None, timeout_seconds: float = 120, memory_mb: int = 2048,
    on_progress: Callable[[str, str], None] | None = None,
) -> IsabelleRuntimePreparation:
    """Observe command, HOL readiness, or a fixed smoke under default admission.

    The one total deadline includes static reads, all admission and all native
    work. Each phase acquires a fresh native child; supplied parents remain live
    and charged exactly once. Explicit roots/executables must select a pinned
    distribution or its installer wrapper; no bad selection falls back to PATH.
    """
    if type(mode) is not str or mode not in {"command", "hol", "smoke"}:
        raise ValueError("mode must be command, hol, or smoke")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300):
        raise ValueError("timeout_seconds must be finite in (0, 300]")
    if type(memory_mb) is not int or not 1024 <= memory_mb <= 4096:
        raise ValueError("memory_mb must be an exact integer in [1024, 4096]")
    if parent_lease is not None and not isinstance(parent_lease, ResourceLease):
        raise TypeError("parent_lease must be an actual datasets ResourceLease")
    if scheduler is not None and not isinstance(scheduler, GlobalResourceScheduler):
        raise TypeError("scheduler must be a datasets GlobalResourceScheduler")
    if parent_lease is not None and scheduler is not None:
        raise ValueError("supply only parent_lease or scheduler")
    if install_root is not None and executable is not None:
        raise ValueError("supply only install_root or executable")
    if cancellation is not None and not callable(getattr(cancellation, "is_set", None)):
        raise TypeError("cancellation must supply is_set()")
    if on_progress is not None and not callable(on_progress):
        raise TypeError("on_progress must be callable")
    started = time.monotonic()
    deadline = started + timeout_seconds
    signal, envelope = cancellation, None
    probes, bindings = [], {}
    status, reason, readiness, lease_id = "error", "preparation_failed", "unavailable", ""
    limits = {"profile": profile.PROFILE, "timeout_seconds": timeout_seconds,
              "cpu_slots": profile.CPU_SLOTS, "process_slots": profile.PROCESS_SLOTS,
              "computation_thread_slots": profile.CPU_SLOTS,
              "reservation_memory_mb": memory_mb + profile.OVERHEAD_MB,
              "resident_memory_bytes": memory_mb * 1024**2,
              "address_space_bytes": profile.ADDRESS_SPACE_BYTES,
              "max_input_bytes": profile.MAX_INPUT_BYTES, "max_output_bytes": MAX_OUTPUT_BYTES,
              "max_workspace_bytes": profile.MAX_WORKSPACE_BYTES,
              "bootstrap_jvm_options": profile.BOOTSTRAP_JAVA_OPTIONS,
              "rss_scope": "sampled process-tree RSS; not an aggregate cgroup ceiling",
              "process_scope": "reservation; not a kernel process or OS thread ceiling"}

    def remaining():
        if signal is not None and signal.is_set():
            raise LeaseCancelledError("Isabelle preparation cancelled")
        duration = deadline - time.monotonic()
        if duration <= 0:
            raise LeaseTimeoutError("Isabelle preparation deadline exceeded")
        return duration

    def announce(phase):
        if on_progress is not None:
            on_progress(phase, "Observing installed Isabelle; no download or explicit heap build")
        remaining()

    try:
        remaining()
        if not sys.platform.startswith("linux") or not Path("/proc/self/stat").is_file():
            raise _PreparationFailure("linux_resource_guards_required", "unsupported")
        owner = parent_lease._scheduler if parent_lease is not None else scheduler or get_global_resource_scheduler()
        if not owner.config.proof_safety_enabled:
            raise _PreparationFailure("pressure_aware_scheduler_required", "admission_denied")
        if parent_lease is not None:
            if parent_lease.owner_pid != os.getpid() or parent_lease.released or parent_lease.cancelled:
                raise _PreparationFailure("inactive_parent_lease", "admission_denied")
            if (parent_lease.cpu_slots < profile.CPU_SLOTS
                    or parent_lease.child_process_slots < profile.PROCESS_SLOTS
                    or parent_lease.memory_mb < limits["reservation_memory_mb"]):
                raise _PreparationFailure("underfunded_parent_lease", "admission_denied")
        announce("admission")
        envelope = owner.acquire("validation", cpu_slots=profile.CPU_SLOTS,
            memory_mb=limits["reservation_memory_mb"], child_process_slots=profile.PROCESS_SLOTS,
            parent_lease=parent_lease, timeout=remaining(), cancel_event=cancellation,
            request_id="isabelle:runtime-preparation")
        lease_id = envelope.lease_id
        signal = envelope.combined_cancellation_signal(cancellation)
        announce("admitted")
        launcher, runtime = profile.resolve_runtime(checkpoint=remaining,
            install_root=install_root, executable=executable)
        bindings["runtime"] = runtime
        version = runtime["version"]
        runner = BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"})

        def native(phase, args, inputs=None, phase_timeout=120):
            announce(phase)
            request = ToolRunRequest(argv=(launcher, *args), input_files=inputs or {},
                limits=ToolRunLimits(timeout_seconds=min(phase_timeout, remaining()), max_output_bytes=MAX_OUTPUT_BYTES))
            observed, record = profile.run_admitted_phase(request,
                parent_lease=envelope, version=version, memory_mb=memory_mb,
                remaining=remaining, cancellation=signal, run=runner.run, phase=phase)
            probes.append(record)
            remaining()
            if observed.cancelled:
                raise LeaseCancelledError("Isabelle process cancelled")
            if observed.timed_out:
                raise LeaseTimeoutError("Isabelle process timed out")
            if (observed.command != request.argv or observed.error or observed.unavailable
                    or observed.resource_exhausted or observed.output_truncated
                    or observed.workspace_limit_exceeded or not observed.workspace_cleaned):
                raise _PreparationFailure("bounded_probe_incomplete")
            return observed

        observed = native("version", ("version",), phase_timeout=15)
        if observed.returncode != 0 or observed.stdout.strip() != version:
            raise _PreparationFailure("isabelle_version_mismatch", "unavailable")
        help_result = native("theory_help", ("process_theories", "-?"), phase_timeout=15)
        if (help_result.returncode not in (0, 1)
                or "Usage: isabelle process_theories" not in help_result.stdout + help_result.stderr):
            raise _PreparationFailure("isabelle_theory_processor_unavailable", "unavailable")
        readiness = "command"
        if mode in {"hol", "smoke"}:
            hol = native("hol_no_build", ("build", "-n", "-b", "-j", "1", "-o", "threads=1", "HOL"))
            if hol.returncode != 0:
                raise _PreparationFailure("hol_heap_build_required", "unavailable")
            readiness = "hol_ready"
        if mode == "smoke":
            from ...external_provers.isabelle_runtime import add_kernel_audit, theory_command
            from ..kernel.isabelle import evaluate_isabelle_kernel_output
            audited = add_kernel_audit(SMOKE_SOURCE, "ready")
            command = theory_command(launcher, "IPFSSetupCheck", "{workspace}")
            bindings["smoke"] = {"profile": SMOKE_PROFILE, "theorem": "ready", "statement": "True",
                "source_sha256": hashlib.sha256(SMOKE_SOURCE.encode()).hexdigest(),
                "audited_source_sha256": hashlib.sha256(audited.encode()).hexdigest(),
                "command": command, "accepted": False}
            smoke = native("smoke", tuple(command[1:]), {"IPFSSetupCheck.thy": audited})
            accepted, axiom, diagnostics = evaluate_isabelle_kernel_output(smoke, declaration="ready", source=SMOKE_SOURCE)
            accepted = bool(accepted and smoke.ok and axiom is not None
                            and axiom.declaration == "ready" and not axiom.contains_sorry
                            and not axiom.contains_unreviewed_axiomatization and not axiom.residual_axioms)
            bindings["smoke"].update(accepted=accepted, diagnostics=list(diagnostics),
                axiom_report=axiom.to_dict() if axiom is not None else None)
            if not accepted:
                raise _PreparationFailure("smoke_not_accepted", "unavailable")
            readiness = "kernel_smoke"
        _, after = profile.resolve_runtime(checkpoint=remaining, install_root=install_root, executable=executable)
        if stable_digest(runtime) != stable_digest(after):
            raise _PreparationFailure("isabelle_runtime_identity_changed")
        bindings["runtime_unchanged"] = True
        announce("complete")
        status, reason = "usable", "bounded_installed_runtime_observed"
    except LeaseCancelledError:
        status, reason = "cancelled", "preparation_cancelled"
    except LeaseTimeoutError:
        status, reason = "timed_out", "preparation_deadline_exceeded"
    except ResourceUnavailableError:
        status, reason = "admission_denied", "resource_admission_unavailable"
    except _PreparationFailure as exc:
        status, reason = exc.status, exc.reason
    except FileNotFoundError:
        status, reason = "unavailable", "installed_artifact_missing"
    except (OSError, ValueError, KeyError):
        status, reason = "error", "preparation_artifact_or_io_invalid"
    finally:
        if envelope is not None:
            envelope.release()
    return IsabelleRuntimePreparation(status, reason, mode, readiness,
        max(0., time.monotonic() - started), lease_id, FrozenMap(bindings),
        tuple(FrozenMap(probe) for probe in probes), FrozenMap(limits))


__all__ = ["prepare_isabelle_runtime", "IsabelleRuntimePreparation", "PREPARATION_SCHEMA"]

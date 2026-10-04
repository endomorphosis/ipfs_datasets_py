"""Admitted native processes for the closed conditional Codebase SMT profile.

Every phase uses the existing bounded tool lifecycle and a fresh child of the
actual producer lease. Address-space limits apply per process; the process-tree
RSS guard is sampled and is not a kernel aggregate memory limit. Historical
receipts describe recorded execution without attesting that it really occurred.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import sys
import time
from typing import Any

from ..backends.process import BoundedToolRunner, ToolRunLimits, run_bounded_stdin_tool
from ..backends.smt.differential import SmtRawSolverOutput
from ..ir_core.claims import FrozenMap
from ..ir_core.protocols import ExecutionBounds
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    ResourceLease, ResourceLane, LeaseCancelledError, LeaseTimeoutError,
)
from .content import canonical_dag_json_bytes
from .codebase_smt_protocol import split_smt_script, parse_verdict, artifact_script, validate_artifact_response

SCHEMA = "codebase-smt-execution@1"
_MIB = 1024 * 1024
_POLICY = {
    "schema": "codebase-smt-execution-policy@1", "protocol": "verdict-then-applicable-artifact",
    "fresh_child_per_phase": True, "deadline_includes_admission": True,
    "per_process_address_space_limit": True, "sampled_tree_rss_guard": True,
    "kernel_aggregate_memory_limit": False, "hard_parent_rss_limit": False,
    "output_capture_scope": "per-stream-with-combined-retention-check",
    "environment": {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
        "HOME": "private-workspace", "TMPDIR": "private-workspace", "TMP": "private-workspace", "TEMP": "private-workspace"},
    "historical_execution_attested": False,
}
_FLAGS = ("timed_out", "cancelled", "unavailable", "resource_exhausted", "output_truncated")
_PHASE_FIELDS = {"kind", "argv", "input_sha256", "limits", "stdout", "stderr", "returncode",
                 "elapsed_ms", *_FLAGS, "workspace_cleaned", "process_tree_terminated", "error"}
_LIMIT_FIELDS = {"timeout_ms", "cpu_seconds", "memory_bytes", "resident_memory_bytes", "max_output_bytes",
                 "max_input_bytes", "max_workspace_bytes", "max_file_bytes", "termination_grace_ms"}


class CodebaseSmtExecutionError(ValueError):
    """A process did not finish inside the closed native execution contract."""

    def __init__(self, message: str, execution: Any = None):
        super().__init__(message)
        self.execution = FrozenMap(execution or {})


@dataclass(frozen=True, slots=True)
class BoundedCodebaseSmtOutput(SmtRawSolverOutput):
    execution: FrozenMap = field(default_factory=FrozenMap)

    def __post_init__(self) -> None:
        SmtRawSolverOutput.__post_init__(self)
        if type(self.execution) is not FrozenMap:
            raise CodebaseSmtExecutionError("bounded SMT output requires immutable execution evidence")


def execution_policy() -> dict[str, Any]:
    return FrozenMap(_POLICY).to_dict()


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CodebaseSmtExecutionError(message)


def _script(value: Any, maximum: int) -> str:
    _require(type(value) is str and 0 < len(value) <= maximum and "\x00" not in value,
             "SMT source exceeds the finite input profile")
    _require(len(value.encode("utf-8")) <= maximum, "SMT source exceeds the UTF-8 input bound")
    return value


def _argv(solver: str, executable: str, kind: str, bounds: ExecutionBounds, timeout_ms: int) -> list[str]:
    if kind == "version":
        return [executable, "-version" if solver == "z3" else "--version"]
    if solver == "z3":
        return [executable, "-in", "-smt2", f"rlimit={bounds.max_steps}",
                f"timeout={timeout_ms}", "smt.threads=1", "sat.threads=1"]
    return [executable, "--lang=smt2", f"--tlimit-per={timeout_ms}", f"--rlimit={bounds.max_steps}"]


def _limits(bounds: ExecutionBounds, kind: str, timeout_ms: int, max_script_bytes: int) -> dict[str, int]:
    return {"timeout_ms": timeout_ms, "cpu_seconds": max(1, math.ceil(timeout_ms / 1000)),
        "memory_bytes": bounds.max_memory_bytes, "resident_memory_bytes": bounds.max_memory_bytes,
        "max_output_bytes": min(4096, bounds.max_output_bytes) if kind == "version" else bounds.max_output_bytes,
        "max_input_bytes": max_script_bytes, "max_workspace_bytes": 16 * _MIB,
        "max_file_bytes": 16 * _MIB, "termination_grace_ms": 250}


def _tool_limits(value: dict[str, int]) -> ToolRunLimits:
    return ToolRunLimits(timeout_seconds=value["timeout_ms"] / 1000,
        cpu_seconds=value["cpu_seconds"], memory_bytes=value["memory_bytes"],
        resident_memory_bytes=value["resident_memory_bytes"], max_output_bytes=value["max_output_bytes"],
        max_input_bytes=value["max_input_bytes"], max_workspace_bytes=value["max_workspace_bytes"],
        max_file_bytes=value["max_file_bytes"], termination_grace_seconds=value["termination_grace_ms"] / 1000)


def _clean(phase: dict[str, Any]) -> bool:
    return (phase["returncode"] == 0 and not any(phase[name] for name in _FLAGS)
            and phase["workspace_cleaned"] is True and not phase["error"]
            and not phase["process_tree_terminated"]
            and len(phase["stdout"]) + len(phase["stderr"]) <= phase["limits"]["max_output_bytes"]
            and len(phase["stdout"].encode()) + len(phase["stderr"].encode()) <= phase["limits"]["max_output_bytes"])


def make_codebase_smt_runner(solver: str, executable: str, *, parent_lease: ResourceLease,
                             cancel_event: Any = None, deadline: float,
                             max_script_bytes: int = 256 * 1024):
    """Return the native runner for an already admitted producer operation.

    The logical call budget includes all phase admissions, version discovery,
    verdict and evidence execution. Failure stops the logical call and retains
    a diagnostic receipt; the producer must not publish a completed proof.
    """
    _require(type(solver) is str and solver in {"z3", "cvc5"}, "unsupported native SMT solver")
    _require(type(executable) is str and 0 < len(executable) <= 4096 and "\x00" not in executable
             and Path(executable).is_absolute(), "SMT executable must be an absolute bounded path")
    _require(isinstance(parent_lease, ResourceLease), "native SMT execution requires an actual parent lease")
    _require(type(deadline) in {int, float} and math.isfinite(deadline), "finite absolute SMT deadline required")
    _require(type(max_script_bytes) is int and 0 < max_script_bytes <= _MIB, "invalid native SMT input limit")
    _require(cancel_event is None or callable(getattr(cancel_event, "is_set", None)), "cancellation signal must provide is_set")
    _require(sys.platform.startswith("linux"), "bounded Codebase SMT execution requires Linux resource limits")
    executable = str(Path(executable).resolve())
    signal = parent_lease.combined_cancellation_signal(cancel_event)

    def run(smtlib: str, bounds: ExecutionBounds) -> BoundedCodebaseSmtOutput:
        _require(type(bounds) is ExecutionBounds, "native SMT execution requires exact ExecutionBounds")
        _require(bounds.max_output_bytes <= min(4 * _MIB, bounds.max_memory_bytes // 16),
                 "SMT output cap exceeds the native memory envelope")
        _require(max_script_bytes <= bounds.max_memory_bytes // 16, "SMT input cap exceeds the native memory envelope")
        _script(smtlib, max_script_bytes)
        base, model_requested, core_requested = split_smt_script(smtlib)
        started = time.monotonic()
        call_deadline = min(deadline, started + bounds.timeout_ms / 1000)
        receipt = {"schema": SCHEMA, "status": "failed", "solver": solver, "executable": executable,
            "input_sha256": _digest(smtlib), "bounds": bounds.to_dict(), "policy": execution_policy(),
            "phases": [], "elapsed_ms": 0}

        def checkpoint() -> float:
            if signal.is_set():
                raise LeaseCancelledError("native Codebase SMT execution cancelled")
            remaining = call_deadline - time.monotonic()
            if remaining <= 0:
                raise CodebaseSmtExecutionError("native Codebase SMT execution deadline exceeded")
            return remaining

        def phase(kind: str, text: str) -> dict[str, Any]:
            if text:
                _script(text, max_script_bytes)
            remaining = checkpoint()
            with parent_lease.acquire_child(lane=ResourceLane.VALIDATION, cpu_slots=1,
                    memory_mb=max(1, math.ceil(bounds.max_memory_bytes / _MIB)), child_process_slots=1,
                    timeout=remaining, cancel_event=signal, request_id=f"codebase-smt:{solver}:{kind}") as child:
                # Admission can consume most of the budget under external load.
                remaining = checkpoint()
                milliseconds = math.floor(min(2.0 if kind == "version" else remaining, remaining) * 1000)
                _require(milliseconds > 0, "native phase has no execution budget after admission")
                limits = _limits(bounds, kind, milliseconds, max_script_bytes)
                argv = _argv(solver, executable, kind, bounds, milliseconds)
                observation = run_bounded_stdin_tool(argv, text,
                    runner=BoundedToolRunner(base_environment={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}),
                    limits=_tool_limits(limits), cancellation=child.combined_cancellation_signal(signal))
                recorded = {"kind": kind, "argv": argv, "input_sha256": _digest(text), "limits": limits,
                    **{name: getattr(observation, name) for name in _PHASE_FIELDS - {"kind", "argv", "input_sha256", "limits"}}}
                receipt["phases"].append(recorded)
                if observation.cancelled or signal.is_set():
                    raise LeaseCancelledError("native Codebase SMT phase cancelled after bounded cleanup")
                _require(_clean(recorded), "native Codebase SMT phase failed: " + kind + ": " +
                         (observation.error or observation.termination_reason or "nonzero/truncated/unclean process"))
                checkpoint()
                return recorded

        try:
            version = phase("version", "")
            version_lines = (version["stdout"] or version["stderr"]).strip().splitlines()
            _require(bool(version_lines) and len(version_lines[0].encode()) <= 4096, "native SMT version is unavailable")
            first = phase("verdict", base)
            verdict = parse_verdict(first["stdout"])
            _require(not first["stderr"].strip(), "native SMT verdict has unexpected stderr")
            followup = artifact_script(base, verdict, model_requested, core_requested)
            final = first
            if followup is not None:
                kind = "model" if verdict == "sat" else "unsat_core"
                final = phase(kind, followup)
                _require(not final["stderr"].strip(), "native SMT artifact has unexpected stderr")
                validate_artifact_response(final["stdout"], verdict, kind)
            checkpoint()
            receipt["elapsed_ms"] = max(0, int((time.monotonic() - started) * 1000))
            receipt["status"] = "completed"
            raw = BoundedCodebaseSmtOutput(stdout=final["stdout"], stderr=final["stderr"],
                returncode=final["returncode"], elapsed_ms=receipt["elapsed_ms"], solver_version=version_lines[0],
                execution=FrozenMap(receipt))
            validate_execution_receipt(raw.execution, solver=solver, executable=executable,
                smtlib=smtlib, bounds=bounds, raw=raw)
            checkpoint()
            return raw
        except BaseException as error:
            receipt["status"] = "failed"
            receipt["elapsed_ms"] = max(0, int((time.monotonic() - started) * 1000))
            retained = FrozenMap(receipt)
            if isinstance(error, LeaseCancelledError):
                error.execution = retained
                raise
            if isinstance(error, (CodebaseSmtExecutionError, LeaseTimeoutError, ValueError)):
                raise CodebaseSmtExecutionError(str(error), receipt) from error
            # Preserve interrupts/controller exceptions after the common runner
            # has drained owned work. Attach bounded diagnostic evidence only.
            try:
                error.execution = retained
            except (AttributeError, TypeError):
                pass
            raise

    return run


def validate_execution_receipt(execution: Any, *, solver: str, executable: str,
                               smtlib: str, bounds: ExecutionBounds, raw: SmtRawSolverOutput) -> None:
    """Replay a completed transport binding without launching any process."""
    value = execution.to_dict() if type(execution) is FrozenMap else execution
    _require(type(bounds) is ExecutionBounds and isinstance(raw, SmtRawSolverOutput),
             "execution replay requires native bounds and raw observation")
    _require(type(solver) is str and solver in {"z3", "cvc5"}, "unsupported recorded SMT solver")
    _require(bounds.max_output_bytes <= min(4 * _MIB, bounds.max_memory_bytes // 16),
             "recorded output cap exceeds the native memory envelope")
    _require(type(value) is dict and set(value) == {"schema", "status", "solver", "executable",
        "input_sha256", "bounds", "policy", "phases", "elapsed_ms"}, "invalid SMT execution receipt fields")
    _require(value["schema"] == SCHEMA and value["status"] == "completed"
        and value["solver"] == solver and value["executable"] == executable
        and value["input_sha256"] == _digest(smtlib)
        and canonical_dag_json_bytes(value["bounds"]) == canonical_dag_json_bytes(bounds.to_dict())
        and canonical_dag_json_bytes(value["policy"]) == canonical_dag_json_bytes(execution_policy()),
        "SMT execution identity/policy differs")
    phases = value["phases"]
    _require(type(phases) is list and 2 <= len(phases) <= 3, "invalid native SMT phase inventory")
    _require(type(value["elapsed_ms"]) is int and 0 <= value["elapsed_ms"] <= bounds.timeout_ms
        and raw.elapsed_ms == value["elapsed_ms"], "native SMT elapsed time differs from its call budget")
    base, model_requested, core_requested = split_smt_script(smtlib)
    verdict = None
    for ordinal, phase in enumerate(phases):
        _require(type(phase) is dict and set(phase) == _PHASE_FIELDS, "invalid native phase fields")
        limits = phase["limits"]
        _require(type(limits) is dict and set(limits) == _LIMIT_FIELDS
            and all(type(v) is int and v > 0 for v in limits.values()), "invalid recorded native limits")
        kind = "version" if ordinal == 0 else "verdict" if ordinal == 1 else "model" if verdict == "sat" else "unsat_core"
        _require(phase["kind"] == kind and 0 < limits["max_input_bytes"] <= _MIB
            and limits["max_input_bytes"] <= bounds.max_memory_bytes // 16
            and limits["max_input_bytes"] == phases[0]["limits"]["max_input_bytes"]
            and limits["timeout_ms"] <= (min(2000, bounds.timeout_ms) if ordinal == 0 else bounds.timeout_ms)
            and limits == _limits(bounds, kind, limits["timeout_ms"], limits["max_input_bytes"]),
            "native phase kind or effective limits changed")
        _require(phase["argv"] == _argv(solver, executable, kind, bounds, limits["timeout_ms"]),
                 "native phase command differs from solver policy")
        text = "" if ordinal == 0 else base if ordinal == 1 else artifact_script(base, verdict, model_requested, core_requested)
        _require(text is not None and phase["input_sha256"] == _digest(text), "native phase script binding differs")
        if text:
            _script(text, limits["max_input_bytes"])
        _require(all(type(phase[name]) is bool for name in (*_FLAGS, "workspace_cleaned", "process_tree_terminated"))
            and type(phase["returncode"]) is int and type(phase["elapsed_ms"]) is int
            and 0 <= phase["elapsed_ms"] <= value["elapsed_ms"]
            and all(type(phase[name]) is str for name in ("stdout", "stderr", "error")), "invalid native phase observation")
        _require(_clean(phase), "failed native process cannot substantiate a completed execution")
        if ordinal == 1:
            verdict = parse_verdict(phase["stdout"])
        if ordinal > 0:
            _require(not phase["stderr"].strip(), "native query has unexpected stderr")
        if ordinal == 2:
            validate_artifact_response(phase["stdout"], verdict, kind)
    needs_artifact = artifact_script(base, verdict, model_requested, core_requested) is not None
    _require(len(phases) == (3 if needs_artifact else 2), "native artifact phase is missing or unexpected")
    version_lines = (phases[0]["stdout"] or phases[0]["stderr"]).strip().splitlines()
    _require(bool(version_lines) and raw.solver_version == version_lines[0], "native version binding differs")
    _require(raw.stdout == phases[-1]["stdout"] and raw.stderr == phases[-1]["stderr"]
        and raw.returncode == 0 and raw.timed_out is False and raw.unavailable is False,
        "raw result differs from the completed native execution")
    _require(sum(phase["elapsed_ms"] for phase in phases) <= value["elapsed_ms"],
             "native phase durations exceed recorded total duration")
    _script(smtlib, phases[0]["limits"]["max_input_bytes"])
    # Enforce the same strict scalar/CID serialization used by sidecar storage.
    canonical_dag_json_bytes(value)

"""Native Isabelle/HOL proof reconstruction and independent kernel checking.

Candidate-referenced local premises inform a deterministic portfolio of Isar
methods. process_theories checks the rewritten theory with quick_and_dirty
mode disabled and one worker. Shared pressure-aware admission, bounded native
execution, and one deadline cover preparation and the kernel check. A generated ML audit
requires the named theorem to exist and have no oracle dependencies; exit
status alone never establishes kernel acceptance. No toolchain installs during
capability discovery. Optional auto_install=True requests first-use setup.
"""

from __future__ import annotations

import hashlib
import math
import re
from ipfs_datasets_py.logic.external_provers.isabelle_runtime import CHECK_MARKER, add_kernel_audit, theory_command, theory_name as validate_theory_name
from ipfs_datasets_py.logic.backends.installers.isabelle_execution import run_isabelle_operation, validate_isabelle_source
from ipfs_datasets_py.logic.backends.kernel.isabelle import evaluate_isabelle_kernel_output
from ipfs_datasets_py.logic.backends.process import ToolRunResult
from typing import Any, List, Optional, Tuple

from ..corpus import compute_content_digest
from ..frontends.base import CapabilityEvidence, GoalSnapshot
from ..frontends.isabelle import IsabelleFrontend, _capability_from_operation
from ..portfolio import SolverProcessOutcome
from ..models import (
    EnvironmentLockRecord,
    HammerRequest,
    ITPKind,
    ProofCandidateRecord,
    ReconstructionRecord,
    _utcnow,
)
from ..reconstruction import (
    DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS,
    KernelUnavailableError,
    ReconstructionEvidence,
    ReconstructionInputError,
    build_environment_lock,
    build_reconstruction_records,
    require_matching_ids,
    require_single_marker,
    select_hypothesis_names,
)

__all__ = ["IsabelleReconstructor"]

_SORRY_RE = re.compile(r"\bsorry\b")
_ERROR_MARKER_RE = re.compile(r"\*\*\*")
_COMMAND_TEMPLATE = "{isabelle} process_theories -D {dir} -O -l HOL -o threads=1 -o parallel_proofs=0 -o quick_and_dirty=false {theory_name}"

#: Fixed, deterministic set of Isabelle/HOL classical proof methods tried
#: after any candidate-referenced hypothesis names (as ``metis`` fact
#: arguments). No extra imports are required beyond ``Main`` (already
#: assumed by the HAMMER-006 Isabelle frontend contract).
_GENERIC_ISABELLE_METHODS: Tuple[str, ...] = (
    "simp",
    "auto",
    "blast",
    "force",
    "fastforce",
    "assumption",
)


class IsabelleReconstructor:
    """Native Isabelle/HOL proof reconstructor implementing
    :class:`~ipfs_datasets_py.logic.hammers.reconstruction.Reconstructor`."""

    itp = ITPKind.ISABELLE

    def __init__(self, *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS, auto_install: bool = False,
                 executable: str = "isabelle", install_root=None, parent_lease=None, scheduler=None,
                 cancellation=None, memory_mb: int = 2048):
        self._timeout = timeout
        self._execution_options = {"parent_lease": parent_lease, "scheduler": scheduler,
                                   "cancellation": cancellation, "memory_mb": memory_mb, "install_root": install_root}
        self._frontend = IsabelleFrontend(timeout=timeout, executable=executable, **self._execution_options)
        self._auto_install = auto_install
        self._executable = None if executable == "isabelle" else executable

    # -- capability ---------------------------------------------------

    def capability(self) -> CapabilityEvidence:
        # Reconstruction needs exactly the same `isabelle` executable the
        # HAMMER-006 frontend needs, so this reuses its capability probe.
        return self._frontend.capability()

    # -- reconstruction --------------------------------------------------

    def reconstruct(
        self,
        *,
        request: HammerRequest,
        candidate: ProofCandidateRecord,
        goal_snapshot: GoalSnapshot,
        native_source: str,
        environment_lock: Optional[EnvironmentLockRecord] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[ReconstructionRecord, ReconstructionEvidence, EnvironmentLockRecord]:
        try:
            validate_isabelle_source(native_source)
        except ValueError as exc:
            raise ReconstructionInputError(str(exc)) from exc
        require_matching_ids(
            request=request,
            candidate=candidate,
            goal_snapshot=goal_snapshot,
            expected_itp=ITPKind.ISABELLE,
        )

        if environment_lock is not None and environment_lock.itp is not ITPKind.ISABELLE:
            raise ReconstructionInputError(
                "environment_lock.itp must be ITPKind.ISABELLE for IsabelleReconstructor"
            )

        marker_match = require_single_marker(native_source, _SORRY_RE, marker_name="sorry")
        theory_name = _extract_theory_name(native_source)
        referenced, _all_names = select_hypothesis_names(goal_snapshot, candidate)
        methods = _build_isabelle_methods(referenced)

        instrumented, reconstructed_proof_text = _instrument_isabelle_reconstruction(
            native_source, marker_match, methods
        )
        try:
            checked_source = add_kernel_audit(instrumented, request.theorem_id)
            validate_isabelle_source(checked_source)
        except ValueError as exc:
            raise ReconstructionInputError(str(exc)) from exc

        reconstruction_id = compute_content_digest(
            {
                "request_id": request.request_id,
                "candidate_id": candidate.candidate_id,
                "itp": "isabelle",
                "checked_source": checked_source,
            }
        )

        resolved_timeout = timeout if timeout is not None else self._timeout
        if (isinstance(resolved_timeout, bool) or not isinstance(resolved_timeout, (int, float))
                or not math.isfinite(resolved_timeout) or resolved_timeout <= 0):
            raise ReconstructionInputError("reconstruction timeout must be finite and positive")
        if (isinstance(request.policy.timeout_seconds, bool)
                or not math.isfinite(request.policy.timeout_seconds) or request.policy.timeout_seconds <= 0):
            raise ReconstructionInputError("policy timeout must be finite and positive")
        options = dict(self._execution_options)
        if request.policy.memory_mb is not None:
            if type(request.policy.memory_mb) is not int or request.policy.memory_mb < 1024:
                raise ReconstructionInputError("Isabelle policy memory must fund at least 1024 MiB")
            options["memory_mb"] = min(options["memory_mb"], request.policy.memory_mb)
        started_at = _utcnow()
        operation = run_isabelle_operation(mode="check", source=checked_source,
            executable=self._executable, auto_install=self._auto_install and request.policy.network_allowed,
            timeout_seconds=min(resolved_timeout, request.policy.timeout_seconds),
            cpu_seconds=request.policy.cpu_seconds, **options)
        finished_at = _utcnow()
        capability = _capability_from_operation(operation)
        observation = operation.observation
        if observation is None:
            raise KernelUnavailableError(
                f"Isabelle kernel unavailable for reconstruction: {operation.reason_code}", capability=capability)
        if type(observation) is not ToolRunResult:
            raise ReconstructionInputError("Isabelle execution requires a native ToolRunResult")
        historical_capability = capability
        if not capability.available:
            # A failed native check can follow successful preparation. Retain
            # that historical tool identity without making current capability
            # available or upgrading the failed execution.
            if operation.preparation is None or operation.preparation.command_available is not True:
                raise KernelUnavailableError("Isabelle check has no observed prepared runtime", capability=capability)
            historical_capability = CapabilityEvidence(itp=ITPKind.ISABELLE, available=True,
                executables=capability.executables, notes="Historical preparation identity for this rejected check only.")
        live_lock = build_environment_lock(ITPKind.ISABELLE, historical_capability,
            kernel_command_template=_COMMAND_TEMPLATE, primary_executable="isabelle", policy=request.policy)
        lock = environment_lock or live_lock
        if environment_lock is not None:
            lock.validate()
            if (lock.itp_version != live_lock.itp_version or lock.kernel_command_template != _COMMAND_TEMPLATE
                    or lock.executable_paths.get("isabelle") != live_lock.executable_paths["isabelle"]
                    or lock.policy_digest != live_lock.policy_digest):
                raise ReconstructionInputError("environment_lock differs from the observed Isabelle environment or policy")
            payload = {"itp": lock.itp.value, "itp_version": lock.itp_version,
                "kernel_command_template": lock.kernel_command_template, "solver_versions": lock.solver_versions,
                "executable_paths": lock.executable_paths, "os_info": lock.os_info,
                "container_digest": lock.container_digest, "policy_digest": lock.policy_digest}
            if compute_content_digest(payload) != lock.lock_id:
                raise ReconstructionInputError("environment_lock content digest mismatch")
        outcome = SolverProcessOutcome(command=list(observation.command), returncode=observation.returncode,
            stdout=observation.stdout, stderr=observation.stderr, timed_out=observation.timed_out,
            cancelled=observation.cancelled, wall_time_seconds=operation.elapsed_seconds, error=observation.error)
        expected_command = tuple(theory_command(live_lock.executable_paths["isabelle"], theory_name, "{workspace}"))
        if (operation.status != "completed" or not operation.runtime_unchanged
                or operation.source_sha256 != hashlib.sha256(checked_source.encode()).hexdigest()
                or operation.theory_name != theory_name or observation.command != expected_command):
            kernel_accepted, failure_reason = False, "Isabelle execution is incomplete or differs from the checked source/command"
        else:
            kernel_accepted, failure_reason = _evaluate_isabelle_outcome(observation)
            if kernel_accepted:
                accepted, axiom, diagnostics = evaluate_isabelle_kernel_output(
                    observation, declaration=request.theorem_id, source=instrumented)
                kernel_accepted = bool(accepted and axiom is not None and axiom.declaration == request.theorem_id)
                if not kernel_accepted:
                    failure_reason = "; ".join(diagnostics) or "Isabelle named-theorem audit rejected the reconstructed source"

        record, evidence = build_reconstruction_records(
            reconstruction_id=reconstruction_id,
            request=request,
            candidate=candidate,
            itp=ITPKind.ISABELLE,
            environment_lock=lock,
            checked_source=checked_source,
            reconstructed_proof_text=reconstructed_proof_text,
            outcome=outcome,
            kernel_accepted=kernel_accepted,
            failure_reason=failure_reason,
            started_at=started_at,
            finished_at=finished_at,
        )
        evidence.execution = operation.to_dict()
        return record, evidence, lock


# ---------------------------------------------------------------------------
# Method reconstruction
# ---------------------------------------------------------------------------


def _build_isabelle_methods(referenced: List[str]) -> List[str]:
    methods: List[str] = []
    for name in referenced:
        methods.append(f"metis {name}")
        methods.append(f"rule {name}")
    methods.extend(_GENERIC_ISABELLE_METHODS)
    return methods


def _instrument_isabelle_reconstruction(
    source: str, match: "re.Match[str]", methods: List[str]
) -> Tuple[str, str]:
    """Substitute the single ``sorry`` ``match`` with a
    ``by (m1 | m2 | ...)`` Isar proof built from ``methods``.

    Returns ``(instrumented_source, replacement_text)``.
    """

    guarded = " | ".join(methods)
    replacement = f"by ({guarded})"
    instrumented = source[: match.start()] + replacement + source[match.end() :]
    return instrumented, replacement


def _extract_theory_name(source: str) -> str:
    try:
        return validate_theory_name(source)
    except ValueError as exc:
        raise ReconstructionInputError(
            "IsabelleReconstructor.reconstruct requires a `theory NAME` "
            "header in native_source to derive the required matching file name"
        ) from exc


# ---------------------------------------------------------------------------
# Kernel-output evaluation
# ---------------------------------------------------------------------------


def _evaluate_isabelle_outcome(outcome: Any) -> Tuple[bool, Optional[str]]:
    """Decide whether ``outcome`` represents an accepted, sorry-free
    Isabelle reconstruction.

    Require a clean exit and the named-theorem oracle audit emitted by Isabelle.
    """

    if outcome.error:
        return False, f"isabelle process_theories invocation failed: {outcome.error}"
    if getattr(outcome, "cancelled", False):
        return False, "isabelle process_theories invocation was cancelled"
    if outcome.timed_out:
        return (
            False,
            "isabelle process_theories invocation timed out under its bounded wall-clock budget",
        )
    if (getattr(outcome, "unavailable", False) or getattr(outcome, "resource_exhausted", False)
            or getattr(outcome, "output_truncated", False) or getattr(outcome, "workspace_limit_exceeded", False)
            or not getattr(outcome, "workspace_cleaned", True)):
        return False, "isabelle process_theories invocation did not complete its bounded lifecycle"

    combined = outcome.stdout + "\n" + outcome.stderr

    if type(outcome.returncode) is not int or outcome.returncode != 0:
        return False, f"isabelle process_theories exited with non-zero status {outcome.returncode}"
    if _ERROR_MARKER_RE.search(combined):
        return False, "isabelle process_theories reported an error diagnostic (`*** ...`)"
    if "Failed" in combined:
        return False, "isabelle process_theories reported a failure diagnostic"
    if _SORRY_RE.search(combined):
        return False, "isabelle process_theories output still references `sorry`"
    if CHECK_MARKER not in combined:
        return False, "Isabelle kernel audit did not confirm the named theorem"
    return True, None

"""Native Isabelle/HOL proof reconstructor and kernel verification
(HAMMER-010).

Reconstructs a genuine Isabelle/Isar proof method from *untrusted* candidate
evidence and asks a real ``isabelle process`` invocation to independently
check it, following the same non-fabrication discipline as
:mod:`~ipfs_datasets_py.logic.hammers.frontends.isabelle`: the exact
incomplete-proof marker (``sorry``) that a
:class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot` was
captured from is substituted with a real Isar method, and Isabelle's own
kernel is the sole arbiter of whether it discharges the goal.

Reconstruction mechanism
------------------------
The substituted proof is::

    by (m1 | m2 | ... | mN)

where each ``mi`` is either a ``metis``/``rule`` invocation naming a local
hypothesis the *untrusted* candidate specifically claimed to have used (a
:attr:`~ipfs_datasets_py.logic.hammers.models.ProofCandidateRecord.
premise_ids` entry that exactly matches a genuine local hypothesis name
already present in the caller-supplied
:class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot` — never
a fabricated identifier), or one of a small, fixed set of Isabelle/HOL
classical proof methods (``simp``, ``auto``, ``blast``, ``force``,
``fastforce``, ``assumption``).

Environment status
-------------------
Per ``docs/logic/itp_hammer_capability_inventory.md`` (HAMMER-002) and
:mod:`~ipfs_datasets_py.logic.hammers.frontends.isabelle`, this repository's
probed environments have **no** ``isabelle`` executable at all. This
reconstructor therefore cannot be exercised against a live Isabelle
toolchain in this checkout; :meth:`IsabelleReconstructor.capability`
reflects that honestly (``available=False`` with a structured reason)
rather than ever short-circuiting to a fabricated acceptance, and its
kernel-output evaluation logic is exercised in
``tests/integration/logic/hammers/test_reconstruction.py`` against a
synthetic, format-accurate ``isabelle process`` transcript with the real
subprocess call replaced — never against invented "available" behavior in
this environment. Unlike the Lean/Coq reconstructors (whose anti-cheating
checks — ``#print axioms`` / ``Print Assumptions`` — were verified
empirically against a real toolchain), this reconstructor's acceptance
check is a conservative, documented best effort: it requires a zero exit
status, no Isabelle error marker (``*** ...``) in the combined output, and
no residual ``sorry`` token — but has not been validated against a live
Isabelle kernel's exact ``sorry``-reporting behavior the way the Lean/Coq
checks were.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..corpus import compute_content_digest
from ..frontends.base import CapabilityEvidence, GoalSnapshot
from ..frontends.isabelle import IsabelleFrontend
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
    run_kernel_check,
    select_hypothesis_names,
)

__all__ = ["IsabelleReconstructor"]

_SORRY_RE = re.compile(r"\bsorry\b")
_THEORY_NAME_RE = re.compile(r"^\s*theory\s+(\S+)", re.MULTILINE)
_ERROR_MARKER_RE = re.compile(r"\*\*\*")

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

    def __init__(self, *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS):
        self._timeout = timeout
        self._frontend = IsabelleFrontend(timeout=timeout)

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
        require_matching_ids(
            request=request,
            candidate=candidate,
            goal_snapshot=goal_snapshot,
            expected_itp=ITPKind.ISABELLE,
        )

        capability = self.capability()
        if not capability.available:
            raise KernelUnavailableError(
                "Isabelle kernel unavailable for reconstruction", capability=capability
            )

        lock = environment_lock
        if lock is None:
            lock = build_environment_lock(
                ITPKind.ISABELLE,
                capability,
                kernel_command_template="{isabelle} process -T {theory_name} -d {dir}",
                primary_executable="isabelle",
                policy=request.policy,
            )
        elif lock.itp is not ITPKind.ISABELLE:
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
        checked_source = instrumented

        reconstruction_id = compute_content_digest(
            {
                "request_id": request.request_id,
                "candidate_id": candidate.candidate_id,
                "itp": "isabelle",
                "checked_source": checked_source,
            }
        )

        isabelle_path = capability.executables["isabelle"]["path"]
        resolved_timeout = timeout if timeout is not None else self._timeout
        started_at = _utcnow()
        with tempfile.TemporaryDirectory(prefix="hammer-isabelle-recon-") as tmpdir:
            source_path = Path(tmpdir) / f"{theory_name}.thy"
            source_path.write_text(checked_source, encoding="utf-8")
            command = [isabelle_path, "process", "-T", theory_name, "-d", tmpdir]
            outcome = run_kernel_check(
                command, cwd=tmpdir, timeout=resolved_timeout, policy=request.policy
            )
        finished_at = _utcnow()

        kernel_accepted, failure_reason = _evaluate_isabelle_outcome(outcome)

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
    match = _THEORY_NAME_RE.search(source)
    if match is None:
        raise ReconstructionInputError(
            "IsabelleReconstructor.reconstruct requires a `theory NAME` "
            "header in native_source to derive the required matching file name"
        )
    return match.group(1)


# ---------------------------------------------------------------------------
# Kernel-output evaluation
# ---------------------------------------------------------------------------


def _evaluate_isabelle_outcome(outcome: Any) -> Tuple[bool, Optional[str]]:
    """Decide whether ``outcome`` represents an accepted, sorry-free
    Isabelle reconstruction.

    See the module docstring's "Environment status" section: this check is
    a conservative, documented best effort (zero exit status, no Isabelle
    error marker, no residual ``sorry``) rather than one verified against a
    live Isabelle kernel.
    """

    if outcome.error:
        return False, f"isabelle process invocation failed: {outcome.error}"
    if outcome.timed_out:
        return (
            False,
            "isabelle process invocation timed out under its bounded wall-clock budget",
        )

    combined = outcome.stdout + "\n" + outcome.stderr

    if outcome.returncode != 0:
        return False, f"isabelle process exited with non-zero status {outcome.returncode}"
    if _ERROR_MARKER_RE.search(combined):
        return False, "isabelle process reported an error diagnostic (`*** ...`)"
    if "Failed" in combined:
        return False, "isabelle process reported a failure diagnostic"
    if _SORRY_RE.search(combined):
        return False, "isabelle process output still references `sorry`"
    return True, None

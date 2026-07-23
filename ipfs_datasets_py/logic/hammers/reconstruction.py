"""Native proof reconstruction and kernel verification (HAMMER-010).

This module implements the ``## HAMMER-010`` entry of
``docs/logic/itp_hammer_taskboard.todo.md``: *"Reconstruct native tactic or
proof terms from candidate evidence and invoke the target kernel in a pinned
environment. Store the checked source, kernel stdout/stderr, exit status, and
digest. Confirm that deliberately corrupted traces and theorem statements
cannot produce ``verified``."*

Where this sits in the pipeline
--------------------------------
- HAMMER-006 (:mod:`.frontends`) captures a genuine native
  :class:`~.frontends.base.GoalSnapshot` for an incomplete goal by
  instrumenting real source text and parsing the target ITP's own
  diagnostic output.
- HAMMER-008/HAMMER-009 (:mod:`.portfolio`, :mod:`.provenance`) run an
  *untrusted* external solver portfolio and normalize its raw output into a
  content-addressed :class:`~.models.ProofCandidateRecord` /
  :class:`~.provenance.NormalizedEvidence` — never a verified result.
- **This module** is the only place a hammer run can cross from "an
  untrusted solver said something" to :attr:`~.models.HammerResultStatus.
  VERIFIED`: it reconstructs a genuine native tactic script/term from that
  candidate evidence, substitutes it for the *exact* incomplete-proof marker
  a :class:`~.frontends.base.GoalSnapshot` was captured from, and asks the
  target ITP's own kernel/elaborator — in a pinned, versioned environment —
  to check it. Only :attr:`~.models.ReconstructionRecord.kernel_accepted`
  being ``True`` (set here, from a real subprocess exit status and output,
  never assumed) can ever promote a :class:`~.models.HammerResult` to
  ``VERIFIED`` (enforced independently by :meth:`~.models.HammerResult.
  validate`).

Reconstruction strategy
------------------------
None of this module's concrete reconstructors (:mod:`.reconstructors.lean`,
:mod:`.reconstructors.coq`, :mod:`.reconstructors.isabelle`) attempt to
structurally translate a TSTP/SMT-LIB resolution proof into a native proof
term — that is an open research problem (it is, in essence, what tools like
Isabelle's Sledgehammer proof-reconstruction pipeline exist to do, and
implementing a sound general version of it is out of scope here). Instead,
each reconstructor:

1. Uses the untrusted candidate's ``premise_ids`` only as a *hint*: any
   caller-supplied premise id that exactly matches a real local hypothesis
   name already present in the genuine :class:`~.frontends.base.
   GoalSnapshot` (never a fabricated identifier) is tried first via a native
   ``exact``/``apply``-style tactic.
2. Falls back to a small, fixed, deterministic set of native closing
   tactics/methods built into the target ITP itself (e.g. Lean's ``rfl``,
   ``decide``, ``simp_all``, ``assumption``; Coq's ``reflexivity``,
   ``assumption``, ``auto``; Isabelle's ``simp``, ``auto``, ``blast``).
3. Combines every alternative into a single native "try each in turn"
   construct (Lean's ``first | ... | ...``, Coq's ``first [ ... | ... ]``,
   Isabelle's ``( ... | ... )`` method alternation) and asks the real kernel
   to elaborate it exactly once.

The result is never trusted because the *solver* proposed it — it is
trusted only because the target ITP's own kernel independently accepted the
reconstructed script, exactly as it would accept any other hand-written
proof. A solver that "guessed" the wrong premises, or a caller that supplies
a corrupted/unrelated theorem statement, simply causes every alternative to
fail and the kernel to reject the reconstruction — see the module's test
suite (``tests/integration/logic/hammers/test_reconstruction.py``) for
adversarial coverage of exactly this.

Anti-cheating checks
--------------------
A naive "exit code 0" check is insufficient and actively unsafe for two of
the three target ITPs:

- Lean accepts a compilation that still contains ``sorry`` with exit code
  ``0`` (only a warning is emitted). This module therefore always appends a
  ``#print axioms <decl>`` command and requires the resulting axiom list to
  be free of ``sorryAx``.
- Coq/Rocq's ``admit.`` tactic also compiles with exit code ``0`` while
  silently discharging the goal via a hidden axiom. This module therefore
  always appends a ``Print Assumptions <decl>.`` command and requires its
  output to be exactly ``Closed under the global context`` (verbatim Coq
  output meaning no extra axiom, including no ``admit``-introduced one, was
  used).
- Every reconstruction also requires ``native_source`` to contain *exactly
  one* incomplete-proof marker (see :func:`require_single_marker`) so a
  second, un-reconstructed ``sorry``/``admit.`` elsewhere in the source can
  never be silently left unchecked.

These checks were verified empirically against this repository's installed
Lean 4 and Rocq/Coq toolchains (see the reconstructor modules' docstrings).
"""

from __future__ import annotations

import platform
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from .corpus import compute_content_digest
from .frontends.base import CapabilityEvidence, GoalSnapshot
from .models import (
    SCHEMA_VERSION,
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    ITPKind,
    ProofCandidateRecord,
    ReconstructionRecord,
    _require_nonempty_str,
    _require_schema_version,
)
from .policy import SolverBudget
from .portfolio import SolverProcessOutcome, run_bounded_solver_process

__all__ = [
    "SCHEMA_VERSION",
    "DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS",
    "MAX_REFERENCED_HYPOTHESES",
    "ReconstructionInputError",
    "KernelUnavailableError",
    "ReconstructionEvidence",
    "Reconstructor",
    "build_environment_lock",
    "run_kernel_check",
    "require_matching_ids",
    "require_single_marker",
    "select_hypothesis_names",
    "build_reconstruction_records",
    "get_reconstructor",
    "iter_reconstructors",
    "reconstruct_candidate",
]

#: Default wall-clock budget (seconds) for a single kernel-check subprocess
#: invocation. Concrete reconstructors accept an override at construction
#: and call time; nothing hard-codes a different value at call sites.
DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS = 30.0

#: Maximum number of candidate-referenced hypothesis names tried explicitly
#: (via ``exact``/``apply``/``metis``-style tactics) before falling back to
#: the fixed generic closing-tactic set. Bounds the size of the generated
#: "try each in turn" command regardless of how many premises a solver
#: reported using.
MAX_REFERENCED_HYPOTHESES = 8


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReconstructionInputError(ValueError):
    """Raised for misuse of the reconstruction API: a candidate/goal
    snapshot that does not belong to the given request or target ITP, or a
    ``native_source`` with zero or more than one incomplete-proof marker.

    This is never raised for an ordinary "the kernel rejected the
    reconstruction" outcome (that is reported via
    :attr:`~.models.ReconstructionRecord.kernel_accepted` being ``False``) —
    it is reserved for call-site errors that would otherwise silently
    reconstruct the wrong theorem or leave a second incomplete-proof
    obligation unchecked.
    """


class KernelUnavailableError(RuntimeError):
    """Raised when a target ITP's native kernel/toolchain is not available
    in this environment.

    Always carries the :class:`~.frontends.base.CapabilityEvidence` that
    backs the refusal, mirroring
    :class:`~.frontends.base.FrontendUnavailableError` — a caller never has
    to guess *why* reconstruction could not be attempted.
    """

    def __init__(self, message: str, *, capability: CapabilityEvidence):
        super().__init__(message)
        self.capability = capability


# ---------------------------------------------------------------------------
# Out-of-band reconstruction evidence
# ---------------------------------------------------------------------------


@dataclass
class ReconstructionEvidence:
    """Out-of-band evidence for one :class:`~.models.ReconstructionRecord`
    that does not belong on the trust-contract record itself: the exact
    checked source text, the reconstructed tactic/term snippet substituted
    into it, the exact argv invoked, and the kernel's raw stdout/stderr.

    Attributes:
        schema_version: Schema version of this record.
        reconstruction_id: The owning :class:`~.models.ReconstructionRecord`
            id.
        request_id: Owning :class:`~.models.HammerRequest` id.
        candidate_id: The :class:`~.models.ProofCandidateRecord` id that was
            reconstructed.
        itp: The target ITP the kernel check ran against.
        command: The exact argv actually executed (never a shell string;
            never interpolates candidate/theorem content directly — only a
            resolved executable path and a file path pointing at
            ``checked_source``).
        checked_source: The full native source text actually submitted to
            the kernel (the caller's original source with the reconstructed
            tactic/term substituted for its single incomplete-proof
            marker).
        checked_source_digest: Content digest of ``checked_source``
            (computed automatically if left blank).
        reconstructed_proof_text: Just the tactic/term snippet that was
            substituted in (a strict substring of ``checked_source``, kept
            separately for quick inspection/audit).
        stdout: The kernel's raw stdout.
        stderr: The kernel's raw stderr.
        returncode: The kernel process's exit code, if it ran to
            completion.
        timed_out: Whether the kernel invocation was killed for exceeding
            its wall-clock budget.
        wall_time_seconds: Observed wall-clock duration of the invocation.
        raw_output_digest: Content digest of ``stdout``/``stderr`` together
            (computed automatically if left blank) — this is exactly the
            digest also stored as
            :attr:`~.models.ReconstructionRecord.kernel_output_digest`.
    """

    schema_version: str = SCHEMA_VERSION
    reconstruction_id: str = ""
    request_id: str = ""
    candidate_id: str = ""
    itp: ITPKind = ITPKind.LEAN
    command: List[str] = field(default_factory=list)
    checked_source: str = ""
    checked_source_digest: str = ""
    reconstructed_proof_text: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: Optional[int] = None
    timed_out: bool = False
    wall_time_seconds: float = 0.0
    raw_output_digest: str = ""

    def __post_init__(self) -> None:
        self.validate()
        if not self.checked_source_digest:
            self.checked_source_digest = compute_content_digest(
                {"checked_source": self.checked_source}
            )
        if not self.raw_output_digest:
            self.raw_output_digest = compute_content_digest(
                {"stdout": self.stdout, "stderr": self.stderr}
            )

    def validate(self) -> None:
        _require_schema_version(self.schema_version, owner="ReconstructionEvidence")
        _require_nonempty_str(
            self.request_id, field_name="request_id", owner="ReconstructionEvidence"
        )
        _require_nonempty_str(
            self.candidate_id, field_name="candidate_id", owner="ReconstructionEvidence"
        )
        if not isinstance(self.itp, ITPKind):
            raise ValueError("ReconstructionEvidence.itp must be an ITPKind")
        if not isinstance(self.command, list) or not all(
            isinstance(c, str) for c in self.command
        ):
            raise ValueError("ReconstructionEvidence.command must be a list of strings")
        _require_nonempty_str(
            self.checked_source, field_name="checked_source", owner="ReconstructionEvidence"
        )
        if not isinstance(self.timed_out, bool):
            raise ValueError("ReconstructionEvidence.timed_out must be a boolean")
        if self.wall_time_seconds < 0:
            raise ValueError("ReconstructionEvidence.wall_time_seconds must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["itp"] = self.itp.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReconstructionEvidence":
        data = dict(data)
        if isinstance(data.get("itp"), str):
            data["itp"] = ITPKind(data["itp"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Reconstructor protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Reconstructor(Protocol):
    """Common protocol every native ITP proof reconstructor implements.

    Attributes:
        itp: The :class:`~.models.ITPKind` this reconstructor targets.
    """

    itp: ITPKind

    def capability(self) -> CapabilityEvidence:
        """Return structured evidence for whether this reconstructor's
        target kernel/toolchain is available in this environment right
        now. Must never run a proof search and must never raise for the
        "not available" case — that is a normal, expected, structured
        outcome."""

        ...

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
        """Reconstruct a native tactic/proof term from ``candidate`` and
        independently check it with the target ITP's own kernel.

        Args:
            request: The owning :class:`~.models.HammerRequest`.
            candidate: The *untrusted* :class:`~.models.ProofCandidateRecord`
                to reconstruct.
            goal_snapshot: The genuine :class:`~.frontends.base.GoalSnapshot`
                (HAMMER-006) captured for the same theorem, used to source
                real local hypothesis names — never fabricated ones.
            native_source: The exact native source text containing exactly
                one incomplete-proof marker to substitute the
                reconstruction into.
            environment_lock: A previously pinned
                :class:`~.models.EnvironmentLockRecord` to reuse; if
                ``None``, a fresh one is captured from the current
                environment.
            timeout: Optional override of the bounded wall-clock budget for
                the kernel invocation (defaults to
                ``request.policy.timeout_seconds``).

        Returns:
            A tuple of the trust-contract
            :class:`~.models.ReconstructionRecord`, its out-of-band
            :class:`ReconstructionEvidence`, and the
            :class:`~.models.EnvironmentLockRecord` the check ran under.

        Raises:
            ReconstructionInputError: If ``candidate``/``goal_snapshot``
                do not belong to ``request``/this reconstructor's ITP, or
                ``native_source`` does not contain exactly one
                incomplete-proof marker.
            KernelUnavailableError: If :meth:`capability` reports this
                reconstructor's kernel unavailable.
        """

        ...


# ---------------------------------------------------------------------------
# Shared validation helpers
# ---------------------------------------------------------------------------


def require_matching_ids(
    *,
    request: HammerRequest,
    candidate: ProofCandidateRecord,
    goal_snapshot: GoalSnapshot,
    expected_itp: ITPKind,
) -> None:
    """Raise :class:`ReconstructionInputError` unless ``candidate`` and
    ``goal_snapshot`` genuinely belong to ``request`` and ``expected_itp``.

    This prevents a caller from ever (accidentally or otherwise) wiring an
    untrusted candidate proof up to a *different* theorem's goal snapshot or
    kernel — the reconstruction the kernel checks must be for the exact
    theorem the candidate/snapshot claim to be for.
    """

    if request.itp is not expected_itp:
        raise ReconstructionInputError(
            f"request.itp is {request.itp.value!r} but this reconstructor "
            f"targets {expected_itp.value!r}"
        )
    if goal_snapshot.itp is not expected_itp:
        raise ReconstructionInputError(
            f"goal_snapshot.itp is {goal_snapshot.itp.value!r} but this "
            f"reconstructor targets {expected_itp.value!r}"
        )
    if candidate.request_id != request.request_id:
        raise ReconstructionInputError(
            f"candidate.request_id={candidate.request_id!r} does not match "
            f"request.request_id={request.request_id!r}"
        )
    if goal_snapshot.theorem_id != request.theorem_id:
        raise ReconstructionInputError(
            f"goal_snapshot.theorem_id={goal_snapshot.theorem_id!r} does not "
            f"match request.theorem_id={request.theorem_id!r}"
        )


def require_single_marker(
    source: str, pattern: "re.Pattern[str]", *, marker_name: str
) -> "re.Match[str]":
    """Return the sole match of ``pattern`` in ``source``.

    Raises:
        ReconstructionInputError: If ``pattern`` matches zero or more than
            one time. A reconstruction may only ever fill in *the* single
            incomplete-proof obligation it was asked to check — never
            guess which of several holes to fill, and never silently leave
            a second one unchecked while reporting the first as verified.
    """

    matches = list(pattern.finditer(source))
    if not matches:
        raise ReconstructionInputError(
            f"native_source contains no `{marker_name}` marker to reconstruct"
        )
    if len(matches) > 1:
        raise ReconstructionInputError(
            f"native_source contains {len(matches)} `{marker_name}` markers; "
            "reconstruction requires exactly one so no second incomplete "
            "proof obligation can be silently left unchecked"
        )
    return matches[0]


def select_hypothesis_names(
    goal_snapshot: GoalSnapshot, candidate: ProofCandidateRecord
) -> Tuple[List[str], List[str]]:
    """Return ``(referenced, all_names)`` local hypothesis names to drive
    tactic reconstruction.

    ``all_names`` is every local hypothesis binder name observed in
    ``goal_snapshot.hypotheses`` (genuine native names — never invented).
    ``referenced`` is the subset of ``all_names`` that also appears,
    verbatim, in ``candidate.premise_ids`` — i.e. names the *untrusted*
    solver specifically claimed to have used, used only as an ordering hint
    for which native tactic alternative to try first. A candidate premise id
    that does not exactly match a real local hypothesis name is simply not
    included; it is never treated as evidence of anything on its own.
    """

    seen: set = set()
    all_names: List[str] = []
    for hyp in goal_snapshot.hypotheses:
        for name in hyp.names:
            if name not in seen:
                seen.add(name)
                all_names.append(name)

    premise_id_set = set(candidate.premise_ids)
    referenced = [name for name in all_names if name in premise_id_set]
    return referenced[:MAX_REFERENCED_HYPOTHESES], all_names


# ---------------------------------------------------------------------------
# Environment lock
# ---------------------------------------------------------------------------


def build_environment_lock(
    itp: ITPKind,
    capability: CapabilityEvidence,
    *,
    kernel_command_template: str,
    primary_executable: str,
    policy: Optional[HammerPolicy] = None,
    extra_solver_versions: Optional[Dict[str, str]] = None,
    container_digest: Optional[str] = None,
) -> EnvironmentLockRecord:
    """Build a pinned, versioned :class:`~.models.EnvironmentLockRecord`
    from live :class:`~.frontends.base.CapabilityEvidence`.

    Args:
        itp: The target ITP this lock applies to.
        capability: Live capability evidence (must report ``available``).
        kernel_command_template: Template of the command used to invoke the
            kernel (placeholders only, e.g.
            ``"{lean} --json {source_file}"`` — never a fabricated example
            with concrete values baked in).
        primary_executable: The executable name (a key of
            ``capability.executables``) whose resolved version is recorded
            as ``itp_version``.
        policy: The governing :class:`~.models.HammerPolicy`, if any; its
            digest is recorded so a lock can be tied back to the budget it
            was captured under.
        extra_solver_versions: Any additional external solver versions to
            fold into ``solver_versions`` (e.g. from a HAMMER-008 portfolio
            run sharing this environment).
        container_digest: Optional content digest of a container image or
            filesystem snapshot backing this lock.

    Raises:
        KernelUnavailableError: If ``capability.available`` is ``False`` —
            an environment lock can only ever pin a genuinely available
            kernel, never a hypothetical one.
    """

    if not capability.available:
        raise KernelUnavailableError(
            f"cannot build an environment lock for {itp.value}: kernel unavailable",
            capability=capability,
        )

    executable_paths: Dict[str, str] = {
        name: info["path"]
        for name, info in capability.executables.items()
        if isinstance(info, dict) and info.get("path")
    }
    primary_info = capability.executables.get(primary_executable) or {}
    itp_version = primary_info.get("version") or "unknown"

    solver_versions: Dict[str, str] = dict(extra_solver_versions or {})
    os_info = platform.platform()
    policy_digest = compute_content_digest(policy.to_dict()) if policy is not None else None

    lock_payload = {
        "itp": itp.value,
        "itp_version": itp_version,
        "kernel_command_template": kernel_command_template,
        "solver_versions": solver_versions,
        "executable_paths": executable_paths,
        "os_info": os_info,
        "container_digest": container_digest,
        "policy_digest": policy_digest,
    }
    lock_id = compute_content_digest(lock_payload)

    return EnvironmentLockRecord(
        lock_id=lock_id,
        itp=itp,
        itp_version=itp_version,
        kernel_command_template=kernel_command_template,
        solver_versions=solver_versions,
        executable_paths=executable_paths,
        os_info=os_info,
        container_digest=container_digest,
        policy_digest=policy_digest,
    )


# ---------------------------------------------------------------------------
# Bounded kernel invocation
# ---------------------------------------------------------------------------


def run_kernel_check(
    command: List[str],
    *,
    cwd: Optional[str] = None,
    timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS,
    policy: Optional[HammerPolicy] = None,
) -> SolverProcessOutcome:
    """Run ``command`` (a literal argv list — never a shell string) as a
    bounded kernel-check subprocess, reusing the HAMMER-008 portfolio's
    battle-tested process-group-aware bounded runner
    (:func:`~.portfolio.run_bounded_solver_process`) so kernel invocations
    get the exact same wall-clock deadline, POSIX CPU/memory ``rlimit``
    enforcement, and full-process-tree kill-on-timeout behavior that
    external solver attempts get.
    """

    budget = SolverBudget(
        timeout_seconds=timeout,
        cpu_seconds=policy.cpu_seconds if policy is not None else None,
        memory_mb=policy.memory_mb if policy is not None else None,
    )
    return run_bounded_solver_process(command, budget=budget, cwd=cwd)


# ---------------------------------------------------------------------------
# Record assembly
# ---------------------------------------------------------------------------


def build_reconstruction_records(
    *,
    reconstruction_id: str,
    request: HammerRequest,
    candidate: ProofCandidateRecord,
    itp: ITPKind,
    environment_lock: EnvironmentLockRecord,
    checked_source: str,
    reconstructed_proof_text: str,
    outcome: SolverProcessOutcome,
    kernel_accepted: bool,
    failure_reason: Optional[str],
    started_at: Any,
    finished_at: Any,
) -> Tuple[ReconstructionRecord, ReconstructionEvidence]:
    """Assemble the paired trust-contract
    :class:`~.models.ReconstructionRecord` and out-of-band
    :class:`ReconstructionEvidence` for one kernel-check invocation.

    Both records are built from the same ``outcome`` so their digests are
    guaranteed consistent
    (``record.kernel_output_digest == evidence.raw_output_digest``).
    """

    evidence = ReconstructionEvidence(
        reconstruction_id=reconstruction_id,
        request_id=request.request_id,
        candidate_id=candidate.candidate_id,
        itp=itp,
        command=list(outcome.command),
        checked_source=checked_source,
        reconstructed_proof_text=reconstructed_proof_text,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        returncode=outcome.returncode,
        timed_out=outcome.timed_out,
        wall_time_seconds=outcome.wall_time_seconds,
    )

    record = ReconstructionRecord(
        reconstruction_id=reconstruction_id,
        request_id=request.request_id,
        candidate_id=candidate.candidate_id,
        target_itp=itp,
        environment_lock_id=environment_lock.lock_id,
        kernel_command=" ".join(outcome.command) if outcome.command else "",
        kernel_accepted=kernel_accepted,
        kernel_output_digest=evidence.raw_output_digest,
        started_at=started_at,
        finished_at=finished_at,
        failure_reason=failure_reason,
    )
    return record, evidence


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def get_reconstructor(
    itp: ITPKind, *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS
) -> Reconstructor:
    """Return the concrete :class:`Reconstructor` for ``itp``.

    The concrete implementations live in :mod:`.reconstructors` and are
    imported lazily here (rather than at module load time) so this module
    and :mod:`.reconstructors` — which imports shared helpers back out of
    this module — never form a load-time circular import.

    Raises:
        ValueError: If ``itp`` has no registered reconstructor.
    """

    from . import reconstructors as _reconstructors

    return _reconstructors.get_reconstructor(itp, timeout=timeout)


def iter_reconstructors(
    *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS
) -> Dict[ITPKind, Reconstructor]:
    """Return a mapping of every registered :class:`~.models.ITPKind` to a
    fresh concrete :class:`Reconstructor` instance."""

    from . import reconstructors as _reconstructors

    return _reconstructors.iter_reconstructors(timeout=timeout)


def reconstruct_candidate(
    *,
    request: HammerRequest,
    candidate: ProofCandidateRecord,
    goal_snapshot: GoalSnapshot,
    native_source: str,
    environment_lock: Optional[EnvironmentLockRecord] = None,
    timeout: Optional[float] = None,
) -> Tuple[ReconstructionRecord, ReconstructionEvidence, EnvironmentLockRecord]:
    """Convenience entry point: resolve the :class:`Reconstructor` for
    ``request.itp`` and reconstruct ``candidate`` against it.

    Equivalent to
    ``get_reconstructor(request.itp).reconstruct(request=request, ...)``.
    """

    reconstructor = get_reconstructor(request.itp, timeout=timeout or DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS)
    return reconstructor.reconstruct(
        request=request,
        candidate=candidate,
        goal_snapshot=goal_snapshot,
        native_source=native_source,
        environment_lock=environment_lock,
        timeout=timeout,
    )

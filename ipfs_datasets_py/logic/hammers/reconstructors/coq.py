"""Native Coq/Rocq proof reconstructor and kernel verification (HAMMER-010).

Reconstructs a genuine Coq/Rocq tactic script from *untrusted* candidate
evidence and asks a real ``coqtop`` invocation to independently check it,
following the same non-fabrication discipline as
:mod:`~ipfs_datasets_py.logic.hammers.frontends.coq`: the exact incomplete-
proof marker (``admit.``/``Admitted.``) that a
:class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot` was
captured from is substituted with a real tactic, and Coq's own kernel is the
sole arbiter of whether it type-checks.

Reconstruction mechanism
------------------------
The substituted tactic is::

    solve [ t1 | t2 | ... | tN ].

where each ``ti`` is either an ``exact``/``apply`` of a local hypothesis
name the *untrusted* candidate specifically claimed to have used (a
:attr:`~ipfs_datasets_py.logic.hammers.models.ProofCandidateRecord.
premise_ids` entry that exactly matches a genuine local hypothesis name
already present in the caller-supplied
:class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot` — never
a fabricated identifier), or one of a small, fixed set of Coq-stdlib closing
tactics (``reflexivity``, ``assumption``, ``now auto``, ``now easy``,
``lia``, ``trivial``). Coq's ``solve [ ... ]`` combinator (unlike a bare
``first [ ... ]``) was verified empirically against this repository's
installed Rocq 9.1.1 toolchain to require each alternative to *fully* close
the goal or fail cleanly — exactly the guarantee a raw ``first [ ... ]``
does not give (a partially-simplifying tactic like ``simpl`` can "succeed"
without closing the goal, silently discarding the remaining alternatives).
A ``Require Import Lia.`` line is always prepended so ``lia`` (linear
integer/natural arithmetic) is available even when the caller's source did
not import it.

After that, a ``Print Assumptions <decl>.`` command is appended and its
output inspected: this was also verified empirically to be necessary
because Coq's ``admit.`` tactic compiles with **exit code 0** and produces
no error, silently discharging the goal via a hidden axiom — the
reconstruction is only accepted when the assumptions report contains the
verbatim string ``Closed under the global context`` (Coq's own way of
saying "no extra axioms, including no ``admit``-introduced one, were
used").
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Tuple

from ..corpus import compute_content_digest
from ..frontends.base import CapabilityEvidence, GoalSnapshot
from ..frontends.coq import CoqFrontend
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

__all__ = ["CoqReconstructor"]

_MARKER_RE = re.compile(r"\badmit\s*\.|\bAdmitted\s*\.")
_DECL_NAME_RE = re.compile(
    r"^\s*(?:Theorem|Lemma|Fact|Corollary|Remark|Proposition|Example)\s+"
    r"([A-Za-z_][A-Za-z0-9_']*)",
    re.MULTILINE,
)

_CLOSED_UNDER_GLOBAL_CONTEXT = "Closed under the global context"

#: Fixed, deterministic set of Coq/Rocq stdlib closing tactics tried after
#: any candidate-referenced hypothesis names. ``lia`` requires the
#: ``Require Import Lia.`` this module always prepends; every other entry
#: is available with no extra imports, verified empirically against this
#: repository's installed toolchain.
_GENERIC_COQ_TACTICS: Tuple[str, ...] = (
    "reflexivity",
    "assumption",
    "now auto",
    "now easy",
    "lia",
    "trivial",
)


class CoqReconstructor:
    """Native Coq/Rocq proof reconstructor implementing
    :class:`~ipfs_datasets_py.logic.hammers.reconstruction.Reconstructor`."""

    itp = ITPKind.COQ

    def __init__(self, *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS):
        self._timeout = timeout
        self._frontend = CoqFrontend(timeout=timeout)

    # -- capability ---------------------------------------------------

    def capability(self) -> CapabilityEvidence:
        # Reconstruction needs exactly the same `coqtop` executable the
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
            expected_itp=ITPKind.COQ,
        )

        capability = self.capability()
        if not capability.available:
            raise KernelUnavailableError(
                "Coq/Rocq kernel unavailable for reconstruction", capability=capability
            )

        lock = environment_lock
        if lock is None:
            lock = build_environment_lock(
                ITPKind.COQ,
                capability,
                kernel_command_template="{coqtop} -batch -load-vernac-source {source_file}",
                primary_executable="coqtop",
                policy=request.policy,
            )
        elif lock.itp is not ITPKind.COQ:
            raise ReconstructionInputError(
                "environment_lock.itp must be ITPKind.COQ for CoqReconstructor"
            )

        marker_match = require_single_marker(
            native_source, _MARKER_RE, marker_name="admit./Admitted."
        )
        decl_name = _extract_coq_decl_name(native_source)
        referenced, _all_names = select_hypothesis_names(goal_snapshot, candidate)
        alternatives = _build_coq_alternatives(referenced)

        instrumented, reconstructed_proof_text = _instrument_coq_reconstruction(
            native_source, marker_match, alternatives, decl_name
        )
        checked_source = "Require Import Lia.\n" + instrumented

        reconstruction_id = compute_content_digest(
            {
                "request_id": request.request_id,
                "candidate_id": candidate.candidate_id,
                "itp": "coq",
                "checked_source": checked_source,
            }
        )

        coqtop_path = capability.executables["coqtop"]["path"]
        resolved_timeout = timeout if timeout is not None else self._timeout
        started_at = _utcnow()
        with tempfile.TemporaryDirectory(prefix="hammer-coq-recon-") as tmpdir:
            source_path = Path(tmpdir) / "Reconstruction.v"
            source_path.write_text(checked_source, encoding="utf-8")
            command = [coqtop_path, "-batch", "-load-vernac-source", str(source_path)]
            outcome = run_kernel_check(
                command, cwd=tmpdir, timeout=resolved_timeout, policy=request.policy
            )
        finished_at = _utcnow()

        kernel_accepted, failure_reason = _evaluate_coq_outcome(outcome)

        record, evidence = build_reconstruction_records(
            reconstruction_id=reconstruction_id,
            request=request,
            candidate=candidate,
            itp=ITPKind.COQ,
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
# Tactic reconstruction
# ---------------------------------------------------------------------------


def _build_coq_alternatives(referenced: List[str]) -> List[str]:
    alternatives: List[str] = []
    for name in referenced:
        alternatives.append(f"exact {name}")
        alternatives.append(f"apply {name}")
    alternatives.extend(_GENERIC_COQ_TACTICS)
    return alternatives


def _instrument_coq_reconstruction(
    source: str, match: "re.Match[str]", alternatives: List[str], decl_name: str
) -> Tuple[str, str]:
    """Substitute the single ``admit.``/``Admitted.`` ``match`` with a
    ``solve [ ... ].`` tactic built from ``alternatives``, then append a
    ``Print Assumptions <decl_name>.`` diagnostic at the very end of the
    file (after ``Qed.`` — the original one when ``match`` was a mid-proof
    ``admit.``, or one newly inserted immediately after the substituted
    tactic when ``match`` was ``Admitted.``).

    Returns ``(instrumented_source, replacement_text)``. ``Print
    Assumptions`` must run *after* the enclosing ``Qed.`` — Coq cannot
    report a declaration's axioms before it has actually been admitted to
    the global context — so it is always appended last, never spliced in
    at the marker's original position.
    """

    marker_text = match.group(0).strip()
    is_admitted = marker_text.startswith("Admitted")

    guarded = " | ".join(alternatives)
    replacement = f"solve [ {guarded} ]."
    closing = "\nQed." if is_admitted else ""

    instrumented = source[: match.start()] + replacement + closing + source[match.end() :]
    instrumented = instrumented.rstrip("\n") + f"\nPrint Assumptions {decl_name}.\n"
    return instrumented, replacement


def _extract_coq_decl_name(source: str) -> str:
    match = _DECL_NAME_RE.search(source)
    if match is None:
        raise ReconstructionInputError(
            "CoqReconstructor.reconstruct requires a `Theorem NAME`/`Lemma "
            "NAME` declaration in native_source to target with `Print "
            "Assumptions`"
        )
    return match.group(1)


# ---------------------------------------------------------------------------
# Kernel-output evaluation
# ---------------------------------------------------------------------------


def _first_error_excerpt(text: str) -> str:
    for line in text.splitlines():
        if "Error:" in line:
            return line.strip()[:200]
    return text.strip()[:200]


def _evaluate_coq_outcome(outcome: Any) -> Tuple[bool, Optional[str]]:
    """Decide whether ``outcome`` genuinely represents an accepted,
    admit-free Coq/Rocq reconstruction.

    Deliberately checks *both* a hard failure signal (``"Error:"`` in the
    output, or a non-zero exit status) *and* the ``Print Assumptions``
    report for the verbatim ``"Closed under the global context"`` string —
    exit code ``0`` alone is not sufficient, since ``coqtop`` reports it
    even when the compiled proof used ``admit.`` to silently discharge the
    goal via a hidden axiom.
    """

    if outcome.error:
        return False, f"coqtop invocation failed: {outcome.error}"
    if outcome.timed_out:
        return False, "coqtop invocation timed out under its bounded wall-clock budget"

    combined = outcome.stdout + "\n" + outcome.stderr
    if "Error:" in combined:
        return False, f"coqtop reported a compilation error: {_first_error_excerpt(combined)}"

    if outcome.returncode != 0:
        return False, f"coqtop exited with non-zero status {outcome.returncode}"

    if _CLOSED_UNDER_GLOBAL_CONTEXT not in outcome.stdout:
        return False, (
            "coqtop's `Print Assumptions` output did not confirm "
            f"{_CLOSED_UNDER_GLOBAL_CONTEXT!r}; the reconstructed proof may "
            "depend on an admitted or otherwise extra axiom"
        )
    return True, None

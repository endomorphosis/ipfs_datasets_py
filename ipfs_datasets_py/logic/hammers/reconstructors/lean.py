"""Native Lean 4 proof reconstructor and kernel verification (HAMMER-010).

Reconstructs a genuine Lean 4 tactic script from *untrusted* candidate
evidence and asks a real ``lean`` invocation to independently check it,
following the same non-fabrication discipline as
:mod:`~ipfs_datasets_py.logic.hammers.frontends.lean`: the exact incomplete-
proof marker (``sorry``) that a
:class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot` was
captured from is substituted with a real tactic sequence, and Lean's own
elaborator is the sole arbiter of whether it type-checks.

Reconstruction mechanism
------------------------
The substituted tactic sequence is::

    first | (t1; done) | (t2; done) | ... | (tN; done)

where each ``ti`` is either an ``exact``/``apply`` of a local hypothesis
name the *untrusted* candidate specifically claimed to have used (a
:attr:`~ipfs_datasets_py.logic.hammers.models.ProofCandidateRecord.
premise_ids` entry that exactly matches a genuine local hypothesis name
already present in the caller-supplied
:class:`~ipfs_datasets_py.logic.hammers.frontends.base.GoalSnapshot` — never
a fabricated identifier), or one of a small, fixed set of Lean-core closing
tactics (``rfl``, ``trivial``, ``decide``, ``omega``, ``simp_all``,
``assumption``).

The ``(ti; done)`` guard on every alternative is not cosmetic: it was
verified empirically against this repository's installed Lean 4.31.0
toolchain that Lean's ``first`` combinator only backtracks into the next
alternative when the current one *raises*, not merely when it leaves the
goal unsolved — ``simp_all`` in particular can silently succeed without
closing a goal, which without the ``done`` guard would cause ``first`` to
"accept" the wrong branch and the surrounding ``by`` block to report
``unsolved goals`` instead of giving ``first`` a chance to try the next
alternative. ``done`` forces every alternative to either fully close the
goal or fail cleanly.

After that, a ``#print axioms <decl>`` command is appended and its result
parsed: this was also verified empirically to be the only reliable way to
detect a hidden ``sorry`` here, because Lean happily reports **exit code
0** for a compilation that still contains an unresolved ``sorry`` (only a
``hasSorry`` *warning* is emitted) — the reconstruction is only accepted
when the axiom report exists and does **not** mention ``sorryAx``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..corpus import compute_content_digest
from ..frontends.base import CapabilityEvidence, GoalSnapshot
from ..frontends.lean import LeanFrontend
from ..models import (
    EnvironmentLockRecord,
    HammerRequest,
    ITPKind,
    ProofCandidateRecord,
    ReconstructionRecord,
    _utcnow,
)
from ..process_lifecycle import supervised_temporary_directory
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

__all__ = ["LeanReconstructor"]

_SORRY_RE = re.compile(r"\bsorry\b")
_DECL_NAME_RE = re.compile(r"^\s*(?:theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_'.]*)", re.MULTILINE)

#: Fixed, deterministic set of Lean-core closing tactics tried after any
#: candidate-referenced hypothesis names. Every entry is a real tactic
#: built into Lean 4 itself (no Mathlib dependency), verified empirically
#: against this repository's installed toolchain.
_GENERIC_LEAN_TACTICS: Tuple[str, ...] = (
    "rfl",
    "trivial",
    "decide",
    "omega",
    "simp_all",
    "assumption",
)


class LeanReconstructor:
    """Native Lean 4 proof reconstructor implementing
    :class:`~ipfs_datasets_py.logic.hammers.reconstruction.Reconstructor`."""

    itp = ITPKind.LEAN

    def __init__(self, *, timeout: float = DEFAULT_RECONSTRUCTION_TIMEOUT_SECONDS):
        self._timeout = timeout
        self._frontend = LeanFrontend(timeout=timeout)

    # -- capability ---------------------------------------------------

    def capability(self) -> CapabilityEvidence:
        # Reconstruction needs exactly the same `lean` executable the
        # HAMMER-006 frontend needs to capture a goal in the first place, so
        # this reuses (rather than reimplements) its capability probe.
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
            expected_itp=ITPKind.LEAN,
        )

        capability = self.capability()
        if not capability.available:
            raise KernelUnavailableError(
                "Lean kernel unavailable for reconstruction", capability=capability
            )

        lock = environment_lock
        if lock is None:
            lock = build_environment_lock(
                ITPKind.LEAN,
                capability,
                kernel_command_template="{lean} --json {source_file}",
                primary_executable="lean",
                policy=request.policy,
            )
        elif lock.itp is not ITPKind.LEAN:
            raise ReconstructionInputError(
                "environment_lock.itp must be ITPKind.LEAN for LeanReconstructor"
            )

        marker_match = require_single_marker(native_source, _SORRY_RE, marker_name="sorry")
        decl_name = _extract_lean_decl_name(native_source)
        referenced, _all_names = select_hypothesis_names(goal_snapshot, candidate)
        alternatives = _build_lean_alternatives(referenced)

        instrumented, reconstructed_proof_text = _instrument_lean_reconstruction(
            native_source, marker_match, alternatives
        )
        checked_source = instrumented.rstrip("\n") + f"\n\n#print axioms {decl_name}\n"

        reconstruction_id = compute_content_digest(
            {
                "request_id": request.request_id,
                "candidate_id": candidate.candidate_id,
                "itp": "lean",
                "checked_source": checked_source,
            }
        )

        lean_path = capability.executables["lean"]["path"]
        resolved_timeout = timeout if timeout is not None else self._timeout
        started_at = _utcnow()
        with supervised_temporary_directory(prefix="hammer-lean-recon-") as tmpdir:
            source_path = Path(tmpdir) / "Reconstruction.lean"
            source_path.write_text(checked_source, encoding="utf-8")
            command = [lean_path, "--json", str(source_path)]
            outcome = run_kernel_check(
                command, cwd=tmpdir, timeout=resolved_timeout, policy=request.policy
            )
        finished_at = _utcnow()

        kernel_accepted, failure_reason = _evaluate_lean_outcome(outcome, decl_name)

        record, evidence = build_reconstruction_records(
            reconstruction_id=reconstruction_id,
            request=request,
            candidate=candidate,
            itp=ITPKind.LEAN,
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


def _build_lean_alternatives(referenced: List[str]) -> List[str]:
    alternatives: List[str] = []
    for name in referenced:
        alternatives.append(f"exact {name}")
        alternatives.append(f"apply {name}")
    alternatives.extend(_GENERIC_LEAN_TACTICS)
    return alternatives


def _instrument_lean_reconstruction(
    source: str, match: "re.Match[str]", alternatives: List[str]
) -> Tuple[str, str]:
    """Substitute the single ``sorry`` ``match`` with a guarded
    ``first | ... `` tactic sequence built from ``alternatives``.

    Returns ``(instrumented_source, replacement_text)``. Handles both term
    position (``:= sorry``, wrapped as ``(by first | ...)``) and tactic
    position (``by ... sorry``, substituted as a bare ``first | ...``),
    detected the same way
    :func:`ipfs_datasets_py.logic.hammers.frontends.lean._instrument_lean_source`
    does: by checking whether a ``by`` keyword appears between the nearest
    preceding ``:=`` and the marker.
    """

    start, end = match.span()
    preceding = source[:start]
    last_assign = preceding.rfind(":=")
    between = preceding[last_assign + 2 :] if last_assign != -1 else preceding
    tactic_mode = re.search(r"\bby\b", between) is not None

    guarded = " | ".join(f"({alt}; done)" for alt in alternatives)
    if tactic_mode:
        replacement = f"first | {guarded}"
    else:
        replacement = f"(by first | {guarded})"

    instrumented = source[:start] + replacement + source[end:]
    return instrumented, replacement


def _extract_lean_decl_name(source: str) -> str:
    match = _DECL_NAME_RE.search(source)
    if match is None:
        raise ReconstructionInputError(
            "LeanReconstructor.reconstruct requires a `theorem NAME`/`lemma "
            "NAME` declaration in native_source to target with `#print axioms`"
        )
    return match.group(1).rstrip(".")


# ---------------------------------------------------------------------------
# Kernel-output evaluation
# ---------------------------------------------------------------------------


def _parse_json_lines(stdout: str) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for raw_line in stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            messages.append(payload)
    return messages


def _find_axiom_message(messages: List[Dict[str, Any]], decl_name: str) -> Optional[str]:
    marker = f"'{decl_name}'"
    for message in messages:
        data = str(message.get("data", ""))
        if marker in data and (
            "depends on axioms" in data or "does not depend on any axioms" in data
        ):
            return data
    return None


def _evaluate_lean_outcome(outcome: Any, decl_name: str) -> Tuple[bool, Optional[str]]:
    """Decide whether ``outcome`` genuinely represents an accepted,
    sorry-free Lean reconstruction.

    Deliberately checks *both* a hard failure signal (any ``error``-severity
    diagnostic, or a non-zero exit status) *and* the ``#print axioms``
    report for ``sorryAx`` — exit code ``0`` alone is not sufficient, since
    Lean reports it even when the compiled declaration still contains an
    unresolved ``sorry``.
    """

    if outcome.error:
        return False, f"lean invocation failed: {outcome.error}"
    if outcome.timed_out:
        return False, "lean invocation timed out under its bounded wall-clock budget"

    messages = _parse_json_lines(outcome.stdout)
    error_messages = [m for m in messages if m.get("severity") == "error"]
    if error_messages:
        excerpt = "; ".join(str(m.get("data", ""))[:200] for m in error_messages)
        return False, f"lean reported error diagnostics: {excerpt}"

    if outcome.returncode != 0:
        return False, f"lean exited with non-zero status {outcome.returncode}"

    axiom_message = _find_axiom_message(messages, decl_name)
    if axiom_message is None:
        return False, (
            f"lean produced no `#print axioms {decl_name}` result; cannot "
            "confirm the reconstruction is free of `sorry`"
        )
    if "sorryAx" in axiom_message:
        return False, (
            f"`#print axioms {decl_name}` reports sorryAx: {axiom_message!r}; the "
            "reconstructed proof still depends on an unresolved `sorry`"
        )
    return True, None

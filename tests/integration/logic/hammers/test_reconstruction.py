"""Integration tests for native proof reconstruction and kernel verification
(HAMMER-010).

These tests cover:

- :class:`~ipfs_datasets_py.logic.hammers.reconstruction.ReconstructionEvidence`
  validation, automatic digest computation, and ``to_dict``/``from_dict``
  round trips.
- :func:`~ipfs_datasets_py.logic.hammers.reconstruction.build_environment_lock`
  producing a deterministic ``lock_id`` from live capability evidence, and
  refusing to pin an unavailable kernel.
- :func:`~ipfs_datasets_py.logic.hammers.reconstruction.require_matching_ids`
  and :func:`~ipfs_datasets_py.logic.hammers.reconstruction.
  require_single_marker` rejecting mismatched/ambiguous reconstruction
  inputs before any kernel is ever invoked.
- :func:`~ipfs_datasets_py.logic.hammers.reconstruction.
  select_hypothesis_names` only ever using genuine local hypothesis names,
  never a fabricated candidate-supplied identifier.
- Whenever the underlying executable is genuinely present (gated with
  ``pytest.mark.skipif``, matching ``test_itp_frontends.py``'s convention),
  the :class:`~ipfs_datasets_py.logic.hammers.reconstructors.lean.
  LeanReconstructor` and :class:`~ipfs_datasets_py.logic.hammers.
  reconstructors.coq.CoqReconstructor` reconstruct a real native tactic
  script from untrusted candidate evidence and invoke a real ``lean``/
  ``coqtop`` kernel to check it — accepting a genuinely provable theorem and
  rejecting, every time, a deliberately corrupted theorem statement, a
  deliberately corrupted/hallucinated candidate premise trace, and a
  Coq ``admit.``-abuse attempt that would otherwise silently compile with
  exit code 0.
- :class:`~ipfs_datasets_py.logic.hammers.reconstructors.isabelle.
  IsabelleReconstructor` is confirmed unavailable in this repository's
  environment (matching the HAMMER-002/HAMMER-006 capability inventory), so
  its acceptance/rejection logic is exercised via a mocked kernel-check
  call — never against invented "available" behavior.
- The hard trust-boundary invariant already enforced by
  :meth:`~ipfs_datasets_py.logic.hammers.models.HammerResult.validate`: a
  rejected :class:`~ipfs_datasets_py.logic.hammers.models.
  ReconstructionRecord` produced by this module can never be wired into a
  :attr:`~ipfs_datasets_py.logic.hammers.models.HammerResultStatus.VERIFIED`
  :class:`~ipfs_datasets_py.logic.hammers.models.HammerResult`.
- The reconstructor registry (:func:`get_reconstructor`/
  :func:`iter_reconstructors`) and the :func:`reconstruct_candidate`
  convenience entry point.
"""

from __future__ import annotations

import shutil

import pytest

from ipfs_datasets_py.logic.hammers.frontends import CoqFrontend, LeanFrontend
from ipfs_datasets_py.logic.hammers.frontends.base import (
    CapabilityEvidence,
    GoalSnapshot,
    LocalHypothesis,
    SourcePosition,
    UniverseContext,
)
from ipfs_datasets_py.logic.hammers.frontends import coq as coq_frontend_module
from ipfs_datasets_py.logic.hammers.frontends import lean as lean_frontend_module
from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy,
    HammerRequest,
    HammerResult,
    HammerResultStatus,
    ITPKind,
    ProofCandidateRecord,
)
from ipfs_datasets_py.logic.hammers.portfolio import SolverProcessOutcome
from ipfs_datasets_py.logic.hammers.reconstruction import (
    KernelUnavailableError,
    ReconstructionEvidence,
    ReconstructionInputError,
    build_environment_lock,
    get_reconstructor,
    iter_reconstructors,
    reconstruct_candidate,
    require_matching_ids,
    require_single_marker,
    select_hypothesis_names,
)
from ipfs_datasets_py.logic.hammers.reconstructors import isabelle as isabelle_reconstructor_module
from ipfs_datasets_py.logic.hammers.reconstructors import lean as lean_reconstructor_module
from ipfs_datasets_py.logic.hammers.reconstructors.coq import CoqReconstructor
from ipfs_datasets_py.logic.hammers.reconstructors.isabelle import IsabelleReconstructor
from ipfs_datasets_py.logic.hammers.reconstructors.lean import LeanReconstructor

LEAN_AVAILABLE = shutil.which("lean") is not None
COQ_AVAILABLE = shutil.which("coqtop") is not None

# ---------------------------------------------------------------------------
# Lean fixtures
# ---------------------------------------------------------------------------

LEAN_GOOD_SOURCE = """theorem hammer_recon_good (n : Nat) (h : n = n) : n = n := by
  sorry
"""

LEAN_HYP_SOURCE = """theorem hammer_recon_hyp (n m : Nat) (h : n = m) : n = m := by
  sorry
"""

LEAN_CORRUPT_SOURCE = """theorem hammer_recon_corrupt (n : Nat) (h : n = n) : n + 1 = n + 2 := by
  sorry
"""

LEAN_COMPLETE_SOURCE = """theorem hammer_recon_no_marker (n : Nat) : n = n := rfl
"""

# ---------------------------------------------------------------------------
# Coq fixtures
# ---------------------------------------------------------------------------

COQ_GOOD_SOURCE = """Theorem hammer_recon_coq_good (n : nat) (h : n = n) : n = n.
Proof.
  intros.
Admitted.
"""

COQ_CORRUPT_SOURCE = """Theorem hammer_recon_coq_corrupt (n : nat) (h : n = n) : n + 1 = n + 2.
Proof.
  intros.
Admitted.
"""

COQ_ADMIT_ABUSE_SOURCE = """Theorem hammer_recon_coq_admit_abuse (n : nat) : n = n + 1.
Proof.
  admit.
Qed.
"""

# ---------------------------------------------------------------------------
# Isabelle fixtures (synthetic transcripts only; Isabelle is unavailable here)
# ---------------------------------------------------------------------------

ISABELLE_SOURCE = """theory HammerReconGoal
imports Main
begin

lemma hammer_recon_isabelle_goal: "(n::nat) = n"
  sorry

end
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_policy(**overrides) -> HammerPolicy:
    defaults = dict(timeout_seconds=20.0, allowed_solvers=[])
    defaults.update(overrides)
    return HammerPolicy(**defaults)


def make_request(**overrides) -> HammerRequest:
    defaults = dict(
        request_id="recon-req-1",
        itp=ITPKind.LEAN,
        theorem_id="hammer_recon_good",
        goal_statement="n = n",
        corpus_revision="corpus-rev-1",
        policy=make_policy(),
    )
    defaults.update(overrides)
    return HammerRequest(**defaults)


def make_candidate(**overrides) -> ProofCandidateRecord:
    defaults = dict(
        candidate_id="recon-candidate-1",
        request_id="recon-req-1",
        solver_attempt_id="recon-attempt-1",
        premise_ids=["h"],
    )
    defaults.update(overrides)
    return ProofCandidateRecord(**defaults)


def make_goal_snapshot(**overrides) -> GoalSnapshot:
    defaults = dict(
        itp=ITPKind.LEAN,
        itp_version="synthetic",
        theorem_id="hammer_recon_good",
        goal_text="n = n",
        hypotheses=[
            LocalHypothesis(names=["n"], type_text="Nat", raw="n : Nat"),
            LocalHypothesis(names=["h"], type_text="n = n", raw="h : n = n"),
        ],
        imports=[],
        universe_context=UniverseContext(),
        source_position=SourcePosition(file="Goal.lean", line=1, column=0),
        native_command=["lean", "Goal.lean"],
        raw_native_output="context:\nn : Nat\nh : n = n\n\u22a2 n = n",
    )
    defaults.update(overrides)
    return GoalSnapshot(**defaults)


def make_available_capability(itp: ITPKind, executable_name: str) -> CapabilityEvidence:
    return CapabilityEvidence(
        itp=itp,
        available=True,
        executables={
            executable_name: {
                "found": True,
                "path": f"/fake/{executable_name}",
                "version": "synthetic-version",
            }
        },
    )


# ---------------------------------------------------------------------------
# ReconstructionEvidence
# ---------------------------------------------------------------------------


class TestReconstructionEvidence:
    def test_validate_requires_checked_source(self):
        with pytest.raises(ValueError):
            ReconstructionEvidence(
                request_id="r1", candidate_id="c1", checked_source=""
            )

    def test_digests_computed_automatically(self):
        evidence = ReconstructionEvidence(
            request_id="r1",
            candidate_id="c1",
            itp=ITPKind.LEAN,
            command=["lean", "Goal.lean"],
            checked_source="theorem foo : True := trivial",
            stdout="ok",
            stderr="",
        )
        assert evidence.checked_source_digest
        assert evidence.raw_output_digest
        # Re-supplying the identical fields must reproduce the identical
        # digests (content-addressed, not random).
        evidence2 = ReconstructionEvidence(
            request_id="r1",
            candidate_id="c1",
            itp=ITPKind.LEAN,
            command=["lean", "Goal.lean"],
            checked_source="theorem foo : True := trivial",
            stdout="ok",
            stderr="",
        )
        assert evidence.checked_source_digest == evidence2.checked_source_digest
        assert evidence.raw_output_digest == evidence2.raw_output_digest

    def test_to_dict_from_dict_round_trip(self):
        evidence = ReconstructionEvidence(
            reconstruction_id="recon-1",
            request_id="r1",
            candidate_id="c1",
            itp=ITPKind.COQ,
            command=["coqtop", "-batch"],
            checked_source="Theorem foo : True. Proof. exact I. Qed.",
            reconstructed_proof_text="exact I.",
            stdout="Closed under the global context",
            stderr="",
            returncode=0,
            wall_time_seconds=0.42,
        )
        restored = ReconstructionEvidence.from_dict(evidence.to_dict())
        assert restored == evidence

    def test_command_must_be_list_of_strings(self):
        with pytest.raises(ValueError):
            ReconstructionEvidence(
                request_id="r1", candidate_id="c1", checked_source="x", command=[1, 2]
            )


# ---------------------------------------------------------------------------
# build_environment_lock
# ---------------------------------------------------------------------------


class TestBuildEnvironmentLock:
    def test_raises_when_capability_unavailable(self):
        capability = CapabilityEvidence(
            itp=ITPKind.LEAN, available=False, unavailable_reason="not found"
        )
        with pytest.raises(KernelUnavailableError) as excinfo:
            build_environment_lock(
                ITPKind.LEAN,
                capability,
                kernel_command_template="{lean} --json {source_file}",
                primary_executable="lean",
            )
        assert excinfo.value.capability is capability

    def test_deterministic_lock_id_for_same_inputs(self):
        capability = make_available_capability(ITPKind.LEAN, "lean")
        lock1 = build_environment_lock(
            ITPKind.LEAN,
            capability,
            kernel_command_template="{lean} --json {source_file}",
            primary_executable="lean",
        )
        lock2 = build_environment_lock(
            ITPKind.LEAN,
            capability,
            kernel_command_template="{lean} --json {source_file}",
            primary_executable="lean",
        )
        assert lock1.lock_id == lock2.lock_id
        assert lock1.itp_version == "synthetic-version"
        assert lock1.executable_paths == {"lean": "/fake/lean"}
        lock1.validate()

    def test_policy_changes_the_lock_id(self):
        capability = make_available_capability(ITPKind.LEAN, "lean")
        lock_no_policy = build_environment_lock(
            ITPKind.LEAN,
            capability,
            kernel_command_template="{lean} --json {source_file}",
            primary_executable="lean",
        )
        lock_with_policy = build_environment_lock(
            ITPKind.LEAN,
            capability,
            kernel_command_template="{lean} --json {source_file}",
            primary_executable="lean",
            policy=make_policy(timeout_seconds=99.0),
        )
        assert lock_no_policy.lock_id != lock_with_policy.lock_id


# ---------------------------------------------------------------------------
# require_matching_ids / require_single_marker / select_hypothesis_names
# ---------------------------------------------------------------------------


class TestRequireMatchingIds:
    def test_passes_for_consistent_inputs(self):
        request = make_request()
        candidate = make_candidate()
        snapshot = make_goal_snapshot()
        # Must not raise.
        require_matching_ids(
            request=request, candidate=candidate, goal_snapshot=snapshot, expected_itp=ITPKind.LEAN
        )

    def test_raises_for_itp_mismatch(self):
        request = make_request(itp=ITPKind.COQ)
        candidate = make_candidate()
        snapshot = make_goal_snapshot()
        with pytest.raises(ReconstructionInputError):
            require_matching_ids(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                expected_itp=ITPKind.LEAN,
            )

    def test_raises_for_goal_snapshot_itp_mismatch(self):
        request = make_request()
        candidate = make_candidate()
        snapshot = make_goal_snapshot(itp=ITPKind.COQ)
        with pytest.raises(ReconstructionInputError):
            require_matching_ids(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                expected_itp=ITPKind.LEAN,
            )

    def test_raises_for_candidate_request_id_mismatch(self):
        request = make_request()
        candidate = make_candidate(request_id="some-other-request")
        snapshot = make_goal_snapshot()
        with pytest.raises(ReconstructionInputError):
            require_matching_ids(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                expected_itp=ITPKind.LEAN,
            )

    def test_raises_for_theorem_id_mismatch(self):
        request = make_request(theorem_id="some_other_theorem")
        candidate = make_candidate()
        snapshot = make_goal_snapshot()
        with pytest.raises(ReconstructionInputError):
            require_matching_ids(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                expected_itp=ITPKind.LEAN,
            )


class TestRequireSingleMarker:
    def test_raises_for_no_marker(self):
        with pytest.raises(ReconstructionInputError):
            require_single_marker(LEAN_COMPLETE_SOURCE, lean_reconstructor_module._SORRY_RE, marker_name="sorry")

    def test_raises_for_multiple_markers(self):
        two_sorries = LEAN_GOOD_SOURCE + "\n" + LEAN_HYP_SOURCE
        with pytest.raises(ReconstructionInputError):
            require_single_marker(two_sorries, lean_reconstructor_module._SORRY_RE, marker_name="sorry")

    def test_returns_the_sole_match(self):
        match = require_single_marker(
            LEAN_GOOD_SOURCE, lean_reconstructor_module._SORRY_RE, marker_name="sorry"
        )
        assert match.group(0) == "sorry"


class TestSelectHypothesisNames:
    def test_referenced_only_includes_genuine_hypothesis_names(self):
        snapshot = make_goal_snapshot()
        candidate = make_candidate(premise_ids=["h", "totally_fabricated_identifier"])
        referenced, all_names = select_hypothesis_names(snapshot, candidate)
        assert referenced == ["h"]
        assert all_names == ["n", "h"]
        assert "totally_fabricated_identifier" not in referenced

    def test_referenced_bounded_to_maximum(self):
        many_names = [f"hyp{i}" for i in range(20)]
        snapshot = make_goal_snapshot(
            hypotheses=[
                LocalHypothesis(names=[name], type_text="Nat", raw=f"{name} : Nat")
                for name in many_names
            ]
        )
        candidate = make_candidate(premise_ids=many_names)
        referenced, all_names = select_hypothesis_names(snapshot, candidate)
        from ipfs_datasets_py.logic.hammers.reconstruction import MAX_REFERENCED_HYPOTHESES

        assert len(referenced) == MAX_REFERENCED_HYPOTHESES
        assert len(all_names) == 20


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestReconstructorRegistry:
    def test_get_reconstructor_returns_expected_types(self):
        assert isinstance(get_reconstructor(ITPKind.LEAN), LeanReconstructor)
        assert isinstance(get_reconstructor(ITPKind.COQ), CoqReconstructor)
        assert isinstance(get_reconstructor(ITPKind.ISABELLE), IsabelleReconstructor)

    def test_iter_reconstructors_covers_every_itp(self):
        reconstructors = iter_reconstructors()
        assert set(reconstructors.keys()) == set(ITPKind)
        for itp, reconstructor in reconstructors.items():
            assert reconstructor.itp is itp


# ---------------------------------------------------------------------------
# Lean reconstructor — real subprocess invocation (skipped if lean absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean executable not available in this environment")
class TestLeanReconstructorReal:
    def _snapshot(self, source: str, theorem_id: str) -> GoalSnapshot:
        return LeanFrontend().snapshot_goal(source, theorem_id=theorem_id)

    def test_accepts_a_genuinely_provable_theorem(self):
        snapshot = self._snapshot(LEAN_GOOD_SOURCE, "hammer_recon_good")
        request = make_request(theorem_id="hammer_recon_good", goal_statement=snapshot.goal_text)
        candidate = make_candidate(premise_ids=["h"])

        record, evidence, lock = LeanReconstructor().reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=LEAN_GOOD_SOURCE,
        )

        assert record.kernel_accepted is True
        assert record.failure_reason is None
        assert record.target_itp is ITPKind.LEAN
        assert record.environment_lock_id == lock.lock_id
        assert record.kernel_output_digest == evidence.raw_output_digest
        assert "first |" in evidence.reconstructed_proof_text
        assert "#print axioms hammer_recon_good" in evidence.checked_source
        assert evidence.returncode == 0
        assert "sorryAx" not in evidence.stdout

        # The trust boundary is real: a HammerResult can legitimately reach
        # VERIFIED using exactly these records.
        result = HammerResult(
            result_id="result-good",
            request=request,
            status=HammerResultStatus.VERIFIED,
            corpus_revision=request.corpus_revision,
            environment_lock=lock,
            proof_candidate=candidate,
            reconstruction=record,
        )
        assert result.is_verified()

    def test_rejects_a_corrupted_theorem_statement(self):
        snapshot = self._snapshot(LEAN_CORRUPT_SOURCE, "hammer_recon_corrupt")
        request = make_request(
            theorem_id="hammer_recon_corrupt", goal_statement=snapshot.goal_text
        )
        candidate = make_candidate(
            candidate_id="corrupt-candidate", request_id=request.request_id, premise_ids=["h"]
        )

        record, evidence, lock = LeanReconstructor().reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=LEAN_CORRUPT_SOURCE,
        )

        assert record.kernel_accepted is False
        assert record.failure_reason

        # And, independent of this module, the models.py trust invariant
        # refuses to let this rejected reconstruction back a VERIFIED result.
        with pytest.raises(ValueError):
            HammerResult(
                result_id="result-corrupt",
                request=request,
                status=HammerResultStatus.VERIFIED,
                corpus_revision=request.corpus_revision,
                environment_lock=lock,
                proof_candidate=candidate,
                reconstruction=record,
            )

    def test_rejects_a_hallucinated_candidate_premise_on_an_unrelated_goal(self):
        """A candidate that names a hypothesis-shaped identifier the solver
        never actually derived anything from must not help a genuinely
        false theorem get accepted — the real kernel is still the sole
        arbiter."""

        snapshot = self._snapshot(LEAN_CORRUPT_SOURCE, "hammer_recon_corrupt")
        request = make_request(
            theorem_id="hammer_recon_corrupt", goal_statement=snapshot.goal_text
        )
        candidate = make_candidate(
            candidate_id="hallucinated-candidate",
            request_id=request.request_id,
            premise_ids=["h", "totally_made_up_lemma_name"],
        )

        record, evidence, lock = LeanReconstructor().reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=LEAN_CORRUPT_SOURCE,
        )
        assert record.kernel_accepted is False

    def test_raises_for_ambiguous_multiple_markers(self):
        snapshot = self._snapshot(LEAN_GOOD_SOURCE, "hammer_recon_good")
        request = make_request(theorem_id="hammer_recon_good", goal_statement=snapshot.goal_text)
        candidate = make_candidate()
        two_sorries = LEAN_GOOD_SOURCE + "\n" + LEAN_HYP_SOURCE
        with pytest.raises(ReconstructionInputError):
            LeanReconstructor().reconstruct(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                native_source=two_sorries,
            )

    def test_raises_for_no_marker(self):
        snapshot = self._snapshot(LEAN_GOOD_SOURCE, "hammer_recon_good")
        request = make_request(theorem_id="hammer_recon_good", goal_statement=snapshot.goal_text)
        candidate = make_candidate()
        with pytest.raises(ReconstructionInputError):
            LeanReconstructor().reconstruct(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                native_source=LEAN_COMPLETE_SOURCE,
            )

    def test_raises_for_mismatched_request(self):
        snapshot = self._snapshot(LEAN_GOOD_SOURCE, "hammer_recon_good")
        request = make_request(theorem_id="a_totally_different_theorem")
        candidate = make_candidate()
        with pytest.raises(ReconstructionInputError):
            LeanReconstructor().reconstruct(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                native_source=LEAN_GOOD_SOURCE,
            )

    def test_kernel_unavailable_raises_before_any_invocation(self, monkeypatch):
        monkeypatch.setattr(lean_frontend_module, "find_executable", lambda name: None)
        snapshot = make_goal_snapshot()
        request = make_request()
        candidate = make_candidate()
        with pytest.raises(KernelUnavailableError) as excinfo:
            LeanReconstructor().reconstruct(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                native_source=LEAN_GOOD_SOURCE,
            )
        assert excinfo.value.capability.available is False

    def test_reconstruct_candidate_convenience_entry_point(self):
        snapshot = self._snapshot(LEAN_GOOD_SOURCE, "hammer_recon_good")
        request = make_request(theorem_id="hammer_recon_good", goal_statement=snapshot.goal_text)
        candidate = make_candidate()
        record, evidence, lock = reconstruct_candidate(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=LEAN_GOOD_SOURCE,
        )
        assert record.kernel_accepted is True


# ---------------------------------------------------------------------------
# Coq reconstructor — real subprocess invocation (skipped if coqtop absent)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not COQ_AVAILABLE, reason="coqtop executable not available in this environment")
class TestCoqReconstructorReal:
    def _snapshot(self, source: str, theorem_id: str) -> GoalSnapshot:
        return CoqFrontend().snapshot_goal(source, theorem_id=theorem_id)

    def _coq_request(self, **overrides):
        defaults = dict(itp=ITPKind.COQ)
        defaults.update(overrides)
        return make_request(**defaults)

    def test_accepts_a_genuinely_provable_theorem(self):
        snapshot = self._snapshot(COQ_GOOD_SOURCE, "hammer_recon_coq_good")
        request = self._coq_request(
            theorem_id="hammer_recon_coq_good", goal_statement=snapshot.goal_text
        )
        candidate = make_candidate(premise_ids=["h"])

        record, evidence, lock = CoqReconstructor().reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=COQ_GOOD_SOURCE,
        )

        assert record.kernel_accepted is True
        assert record.failure_reason is None
        assert record.target_itp is ITPKind.COQ
        assert "Closed under the global context" in evidence.stdout
        assert "solve [" in evidence.reconstructed_proof_text

        result = HammerResult(
            result_id="coq-result-good",
            request=request,
            status=HammerResultStatus.VERIFIED,
            corpus_revision=request.corpus_revision,
            environment_lock=lock,
            proof_candidate=candidate,
            reconstruction=record,
        )
        assert result.is_verified()

    def test_rejects_a_corrupted_theorem_statement(self):
        snapshot = self._snapshot(COQ_CORRUPT_SOURCE, "hammer_recon_coq_corrupt")
        request = self._coq_request(
            theorem_id="hammer_recon_coq_corrupt", goal_statement=snapshot.goal_text
        )
        candidate = make_candidate(
            candidate_id="coq-corrupt-candidate", request_id=request.request_id
        )

        record, evidence, lock = CoqReconstructor().reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=COQ_CORRUPT_SOURCE,
        )
        assert record.kernel_accepted is False
        assert record.failure_reason

        with pytest.raises(ValueError):
            HammerResult(
                result_id="coq-result-corrupt",
                request=request,
                status=HammerResultStatus.VERIFIED,
                corpus_revision=request.corpus_revision,
                environment_lock=lock,
                proof_candidate=candidate,
                reconstruction=record,
            )

    def test_rejects_admit_abuse_that_would_otherwise_exit_zero(self):
        """`admit.` alone compiles with exit code 0 in coqtop; this proves
        the reconstructor's `Print Assumptions` check — not the exit code —
        is what actually gates acceptance."""

        snapshot = self._snapshot(COQ_ADMIT_ABUSE_SOURCE, "hammer_recon_coq_admit_abuse")
        request = self._coq_request(
            theorem_id="hammer_recon_coq_admit_abuse", goal_statement=snapshot.goal_text
        )
        candidate = make_candidate(
            candidate_id="coq-admit-abuse-candidate", request_id=request.request_id
        )

        record, evidence, lock = CoqReconstructor().reconstruct(
            request=request,
            candidate=candidate,
            goal_snapshot=snapshot,
            native_source=COQ_ADMIT_ABUSE_SOURCE,
        )
        assert record.kernel_accepted is False
        assert "Closed under the global context" not in evidence.stdout

    def test_kernel_unavailable_raises_before_any_invocation(self, monkeypatch):
        monkeypatch.setattr(coq_frontend_module, "find_executable", lambda name: None)
        snapshot = make_goal_snapshot(itp=ITPKind.COQ)
        request = self._coq_request()
        candidate = make_candidate()
        with pytest.raises(KernelUnavailableError):
            CoqReconstructor().reconstruct(
                request=request,
                candidate=candidate,
                goal_snapshot=snapshot,
                native_source=COQ_GOOD_SOURCE,
            )


# ---------------------------------------------------------------------------
# Isabelle reconstructor — mocked kernel check (unavailable in this env)
# ---------------------------------------------------------------------------


class TestIsabelleReconstructorMocked:
    def _isabelle_snapshot(self) -> GoalSnapshot:
        return make_goal_snapshot(
            itp=ITPKind.ISABELLE,
            itp_version="synthetic",
            theorem_id="hammer_recon_isabelle_goal",
            goal_text="n = n",
            hypotheses=[],
            imports=["Main"],
            native_command=["isabelle", "process"],
            raw_native_output="goal (1 subgoal):\n 1. n = n\n",
        )

    def _isabelle_request(self, **overrides) -> HammerRequest:
        defaults = dict(
            itp=ITPKind.ISABELLE,
            theorem_id="hammer_recon_isabelle_goal",
            goal_statement="n = n",
        )
        defaults.update(overrides)
        return make_request(**defaults)

    def test_real_capability_is_unavailable_here(self):
        assert IsabelleReconstructor().capability().available is False

    def test_real_reconstruct_raises_kernel_unavailable(self):
        with pytest.raises(KernelUnavailableError):
            IsabelleReconstructor().reconstruct(
                request=self._isabelle_request(),
                candidate=make_candidate(),
                goal_snapshot=self._isabelle_snapshot(),
                native_source=ISABELLE_SOURCE,
            )

    def test_mocked_kernel_accepts_clean_output(self, monkeypatch):
        monkeypatch.setattr(
            isabelle_reconstructor_module.IsabelleReconstructor,
            "capability",
            lambda self: make_available_capability(ITPKind.ISABELLE, "isabelle"),
        )
        monkeypatch.setattr(
            isabelle_reconstructor_module,
            "run_kernel_check",
            lambda command, **kwargs: SolverProcessOutcome(
                command=command, returncode=0, stdout="Successfully checked.", stderr=""
            ),
        )
        record, evidence, lock = IsabelleReconstructor().reconstruct(
            request=self._isabelle_request(),
            candidate=make_candidate(),
            goal_snapshot=self._isabelle_snapshot(),
            native_source=ISABELLE_SOURCE,
        )
        assert record.kernel_accepted is True
        assert "by (" in evidence.reconstructed_proof_text

    def test_mocked_kernel_rejects_failure_marker(self, monkeypatch):
        monkeypatch.setattr(
            isabelle_reconstructor_module.IsabelleReconstructor,
            "capability",
            lambda self: make_available_capability(ITPKind.ISABELLE, "isabelle"),
        )
        monkeypatch.setattr(
            isabelle_reconstructor_module,
            "run_kernel_check",
            lambda command, **kwargs: SolverProcessOutcome(
                command=command,
                returncode=1,
                stdout="*** Failed to finish proof",
                stderr="",
            ),
        )
        record, evidence, lock = IsabelleReconstructor().reconstruct(
            request=self._isabelle_request(),
            candidate=make_candidate(),
            goal_snapshot=self._isabelle_snapshot(),
            native_source=ISABELLE_SOURCE,
        )
        assert record.kernel_accepted is False
        assert record.failure_reason

    def test_mocked_kernel_rejects_residual_sorry(self, monkeypatch):
        monkeypatch.setattr(
            isabelle_reconstructor_module.IsabelleReconstructor,
            "capability",
            lambda self: make_available_capability(ITPKind.ISABELLE, "isabelle"),
        )
        monkeypatch.setattr(
            isabelle_reconstructor_module,
            "run_kernel_check",
            lambda command, **kwargs: SolverProcessOutcome(
                command=command,
                returncode=0,
                stdout="theory uses sorry somewhere",
                stderr="",
            ),
        )
        record, evidence, lock = IsabelleReconstructor().reconstruct(
            request=self._isabelle_request(),
            candidate=make_candidate(),
            goal_snapshot=self._isabelle_snapshot(),
            native_source=ISABELLE_SOURCE,
        )
        assert record.kernel_accepted is False

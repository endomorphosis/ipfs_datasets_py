"""Tests for native-automation and decomposition recovery fallbacks
(HAMMER-011).

These tests cover:

- The three new, opt-in :class:`~ipfs_datasets_py.logic.hammers.models.
  HammerPolicy` fields this module gates on
  (``allow_native_automation_fallback``, ``allow_llm_decomposition_hints``,
  ``max_decomposition_subgoals``), including their validation.
- :func:`split_top_level_conjuncts`'s deterministic, bracket-depth-aware
  conjunction splitting and its bounding behavior.
- :func:`redact_llm_text` never leaking the raw suggestion text and being
  deterministic for identical input.
- :class:`NativeAutomationAttempt`'s ``attempted``/``recovered`` invariant
  matrix.
- :func:`attempt_native_automation`: refusing to run when policy-disabled,
  reporting a structured skip when the target kernel is unavailable, and
  (gated on a real ``lean``/``coqtop`` toolchain being installed) genuinely
  recovering a trivially-true goal and genuinely failing to recover a false
  one via a real kernel invocation — exactly mirroring HAMMER-010's own
  anti-fabrication discipline.
- :class:`DecompositionSubgoal`'s validation invariants: an LLM-suggested
  subgoal always carries a redacted placeholder and always starts pending
  review; a native-structural subgoal never does; ``VERIFIED`` requires a
  ``reconstruction_id`` and (for an LLM-suggested subgoal) an approving
  review.
- :func:`build_decomposition_plan`: native-structural-first ordering,
  bounding to ``max_decomposition_subgoals`` (folding excess conjuncts into
  the last subgoal), and LLM suggestions being ignored unless both supplied
  *and* policy-enabled, always redacted and left at ``PENDING_REVIEW``.
- :func:`review_decomposition_subgoal`'s mandatory human-review gate:
  refusing native-structural subgoals, refusing an empty reviewer, and
  refusing a second review.
- :func:`verify_decomposition_subgoal`'s fail-closed gating: refusing an
  unreviewed or review-rejected LLM-suggested subgoal, refusing a mismatched
  or already-verified subgoal, reporting ``SKIPPED`` when the kernel is
  unavailable, and (gated on real toolchains) genuinely kernel-checking
  synthetic per-subgoal native sources built from the caller's own
  hypotheses — including a hypothesis-dependent subgoal and a deliberately
  false one that the kernel must reject.
- :func:`attempt_fallback`'s end-to-end orchestration: mismatched
  goal/request refusal, native-automation recovery short-circuiting
  decomposition, and decomposition being built (with an explanatory note or
  error) when native automation is skipped or rejected.
- ``to_dict``/``from_dict`` round-trips for every new record type.
"""

from __future__ import annotations

import shutil

import pytest

from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
from ipfs_datasets_py.logic.hammers.frontends.base import (
    CapabilityEvidence,
    GoalSnapshot,
    LocalHypothesis,
)
from ipfs_datasets_py.logic.hammers.models import (
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    ITPKind,
    ProofCandidateRecord,
    ReconstructionRecord,
)
from ipfs_datasets_py.logic.hammers.reconstruction import (
    KernelUnavailableError,
    ReconstructionEvidence,
    ReconstructionInputError,
)
from ipfs_datasets_py.logic.hammers.reconstructors.coq import CoqReconstructor
from ipfs_datasets_py.logic.hammers.reconstructors.lean import LeanReconstructor
from ipfs_datasets_py.logic.hammers import fallbacks as fb

LEAN_AVAILABLE = shutil.which("lean") is not None
COQ_AVAILABLE = shutil.which("coqtop") is not None


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_policy(**overrides) -> HammerPolicy:
    defaults = dict(timeout_seconds=20.0, allowed_solvers=[])
    defaults.update(overrides)
    return HammerPolicy(**defaults)


def make_request(**overrides) -> HammerRequest:
    defaults = dict(
        request_id="req-1",
        itp=ITPKind.LEAN,
        theorem_id="hammer_fallback_thm",
        goal_statement="n = n",
        corpus_revision="corpus-rev-1",
        policy=make_policy(),
    )
    defaults.update(overrides)
    return HammerRequest(**defaults)


def make_goal_snapshot(**overrides) -> GoalSnapshot:
    defaults = dict(
        itp=ITPKind.LEAN,
        itp_version="Lean (test)",
        theorem_id="hammer_fallback_thm",
        goal_text="n = n",
        hypotheses=[LocalHypothesis(names=["n"], type_text="Nat", raw="n : Nat")],
        imports=[],
        native_command=["lean", "Goal.lean"],
        raw_native_output="synthetic test fixture",
    )
    defaults.update(overrides)
    return GoalSnapshot(**defaults)


LEAN_SORRY_SOURCE = (
    "theorem hammer_fallback_thm (n : Nat) : n = n := by\n  sorry\n"
)
LEAN_FALSE_SOURCE = (
    "theorem hammer_fallback_thm (n : Nat) : n + 1 = n + 2 := by\n  sorry\n"
)
COQ_SORRY_SOURCE = (
    "Theorem hammer_fallback_thm (n : nat) : n = n.\nProof.\n  intros.\nAdmitted.\n"
)


class FakeReconstructor:
    """A deterministic, in-memory stand-in for a
    :class:`~ipfs_datasets_py.logic.hammers.reconstruction.Reconstructor`,
    used so most of this module's tests do not depend on a real ``lean``/
    ``coqtop`` toolchain being installed. Never claims a fabricated
    ``kernel_accepted`` — its behavior is fully controlled by the test that
    constructs it."""

    def __init__(
        self,
        *,
        itp: ITPKind = ITPKind.LEAN,
        available: bool = True,
        accept: bool = True,
        raise_input_error: bool = False,
        raise_kernel_unavailable: bool = False,
    ):
        self.itp = itp
        self._available = available
        self._accept = accept
        self._raise_input_error = raise_input_error
        self._raise_kernel_unavailable = raise_kernel_unavailable
        self.reconstruct_calls: list = []

    def capability(self) -> CapabilityEvidence:
        if self._available:
            return CapabilityEvidence(
                itp=self.itp,
                available=True,
                executables={
                    "fake": {"found": True, "path": "/fake/bin", "version": "fake-1.0"}
                },
            )
        return CapabilityEvidence(
            itp=self.itp,
            available=False,
            unavailable_reason="fake kernel unavailable for testing",
        )

    def reconstruct(
        self,
        *,
        request,
        candidate,
        goal_snapshot,
        native_source,
        environment_lock=None,
        timeout=None,
    ):
        self.reconstruct_calls.append(
            (request, candidate, goal_snapshot, native_source)
        )
        if self._raise_input_error:
            raise ReconstructionInputError("fake input error")
        if self._raise_kernel_unavailable:
            raise KernelUnavailableError(
                "fake kernel unavailable", capability=self.capability()
            )

        lock = environment_lock or EnvironmentLockRecord(
            lock_id="fake-lock",
            itp=self.itp,
            itp_version="fake-1.0",
            kernel_command_template="{fake} {source_file}",
            executable_paths={"fake": "/fake/bin"},
            os_info="fake-os",
        )
        reconstruction_id = compute_content_digest(
            {
                "request_id": request.request_id,
                "candidate_id": candidate.candidate_id,
                "native_source": native_source,
            }
        )
        record = ReconstructionRecord(
            reconstruction_id=reconstruction_id,
            request_id=request.request_id,
            candidate_id=candidate.candidate_id,
            target_itp=self.itp,
            environment_lock_id=lock.lock_id,
            kernel_command="fake-kernel --check",
            kernel_accepted=self._accept,
            kernel_output_digest="sha256:fake",
            failure_reason=None if self._accept else "fake kernel rejected the reconstruction",
        )
        evidence = ReconstructionEvidence(
            reconstruction_id=reconstruction_id,
            request_id=request.request_id,
            candidate_id=candidate.candidate_id,
            itp=self.itp,
            command=["fake-kernel", "--check"],
            checked_source=native_source,
            reconstructed_proof_text="fake-tactic",
            stdout="fake stdout",
            stderr="",
            returncode=0 if self._accept else 1,
        )
        return record, evidence, lock


# ---------------------------------------------------------------------------
# HammerPolicy fallback fields
# ---------------------------------------------------------------------------


class TestHammerPolicyFallbackFields:
    def test_defaults(self):
        policy = HammerPolicy()
        assert policy.allow_native_automation_fallback is False
        assert policy.allow_llm_decomposition_hints is False
        assert policy.max_decomposition_subgoals == 4

    def test_validate_rejects_non_bool_native_automation_flag(self):
        policy = make_policy(allow_native_automation_fallback="yes")
        with pytest.raises(ValueError):
            policy.validate()

    def test_validate_rejects_non_bool_llm_decomposition_flag(self):
        policy = make_policy(allow_llm_decomposition_hints="yes")
        with pytest.raises(ValueError):
            policy.validate()

    def test_validate_rejects_non_positive_max_decomposition_subgoals(self):
        policy = make_policy(max_decomposition_subgoals=0)
        with pytest.raises(ValueError):
            policy.validate()

    def test_round_trip(self):
        policy = make_policy(
            allow_native_automation_fallback=True,
            allow_llm_decomposition_hints=True,
            max_decomposition_subgoals=7,
        )
        restored = HammerPolicy.from_dict(policy.to_dict())
        assert restored == policy


# ---------------------------------------------------------------------------
# split_top_level_conjuncts
# ---------------------------------------------------------------------------


class TestSplitTopLevelConjuncts:
    def test_no_connective_returns_empty(self):
        assert fb.split_top_level_conjuncts("n = n", max_parts=4) == []

    def test_empty_text_returns_empty(self):
        assert fb.split_top_level_conjuncts("   ", max_parts=4) == []

    def test_max_parts_below_two_returns_empty(self):
        assert fb.split_top_level_conjuncts("n = n ∧ m = m", max_parts=1) == []

    def test_simple_two_way_unicode_split(self):
        assert fb.split_top_level_conjuncts("n = n ∧ m = m", max_parts=4) == [
            "n = n",
            "m = m",
        ]

    def test_simple_two_way_ascii_split(self):
        assert fb.split_top_level_conjuncts("n = n /\\ m = m", max_parts=4) == [
            "n = n",
            "m = m",
        ]

    def test_three_way_split_within_bound(self):
        assert fb.split_top_level_conjuncts(
            "a = a ∧ b = b ∧ c = c", max_parts=4
        ) == ["a = a", "b = b", "c = c"]

    def test_bound_folds_excess_conjuncts_into_final_subgoal(self):
        result = fb.split_top_level_conjuncts(
            "a = a ∧ b = b ∧ c = c ∧ d = d", max_parts=2
        )
        # Only 2 parts allowed: first conjunct alone, everything else folded.
        assert result == ["a = a", "b = b ∧ c = c ∧ d = d"]

    def test_nested_parens_are_not_split(self):
        result = fb.split_top_level_conjuncts(
            "(a = a ∧ b = b) ∧ c = c", max_parts=4
        )
        assert result == ["(a = a ∧ b = b)", "c = c"]

    def test_single_conjunct_inside_parens_only_returns_empty(self):
        assert fb.split_top_level_conjuncts("(a = a ∧ b = b)", max_parts=4) == []


# ---------------------------------------------------------------------------
# redact_llm_text
# ---------------------------------------------------------------------------


class TestRedactLlmText:
    def test_never_contains_raw_text(self):
        raw = "this is a secret proposed subgoal, do not leak me"
        redacted = fb.redact_llm_text(raw)
        assert raw not in redacted

    def test_deterministic_for_identical_input(self):
        raw = "n = n"
        assert fb.redact_llm_text(raw) == fb.redact_llm_text(raw)

    def test_differs_for_different_input(self):
        assert fb.redact_llm_text("n = n") != fb.redact_llm_text("m = m")

    def test_contains_length(self):
        raw = "abcdefgh"
        redacted = fb.redact_llm_text(raw)
        assert f"length={len(raw)}" in redacted


# ---------------------------------------------------------------------------
# NativeAutomationAttempt
# ---------------------------------------------------------------------------


class TestNativeAutomationAttempt:
    def test_valid_skipped_attempt(self):
        attempt = fb.NativeAutomationAttempt(
            request_id="req-1",
            itp=ITPKind.LEAN,
            attempted=False,
            recovered=False,
            skipped_reason="disabled by policy",
        )
        attempt.validate()

    def test_attempted_requires_skipped_reason_none(self):
        attempt = fb.NativeAutomationAttempt(
            request_id="req-1",
            attempted=True,
            recovered=False,
            skipped_reason="should not be set",
        )
        with pytest.raises(ValueError):
            attempt.validate()

    def test_not_attempted_requires_skipped_reason(self):
        attempt = fb.NativeAutomationAttempt(
            request_id="req-1", attempted=False, recovered=False, skipped_reason=None
        )
        with pytest.raises(ValueError):
            attempt.validate()

    def test_not_attempted_forbids_recovered_true(self):
        attempt = fb.NativeAutomationAttempt(
            request_id="req-1",
            attempted=False,
            recovered=True,
            skipped_reason="disabled by policy",
        )
        with pytest.raises(ValueError):
            attempt.validate()

    def test_round_trip(self):
        attempt = fb.NativeAutomationAttempt(
            request_id="req-1",
            attempted=False,
            recovered=False,
            skipped_reason="disabled by policy",
        )
        restored = fb.NativeAutomationAttempt.from_dict(attempt.to_dict())
        assert restored == attempt


# ---------------------------------------------------------------------------
# attempt_native_automation
# ---------------------------------------------------------------------------


class TestAttemptNativeAutomation:
    def test_disabled_by_policy_skips_without_calling_reconstructor(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=False))
        snapshot = make_goal_snapshot()
        reconstructor = FakeReconstructor(accept=True)

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert attempt.attempted is False
        assert attempt.recovered is False
        assert "disabled by policy" in attempt.skipped_reason
        assert reconstructor.reconstruct_calls == []

    def test_unavailable_kernel_is_skipped(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()
        reconstructor = FakeReconstructor(available=False)

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert attempt.attempted is False
        assert attempt.recovered is False
        assert "unavailable" in attempt.skipped_reason
        assert reconstructor.reconstruct_calls == []

    def test_reconstruction_input_error_is_reported_as_skip(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()
        reconstructor = FakeReconstructor(raise_input_error=True)

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert attempt.attempted is False
        assert "fake input error" in attempt.skipped_reason

    def test_kernel_unavailable_error_is_reported_as_skip(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()
        reconstructor = FakeReconstructor(raise_kernel_unavailable=True)

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert attempt.attempted is False
        assert "fake kernel unavailable" in attempt.skipped_reason

    def test_fake_kernel_accepts(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()
        reconstructor = FakeReconstructor(accept=True)

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert attempt.attempted is True
        assert attempt.recovered is True
        assert attempt.reconstruction is not None
        assert attempt.reconstruction.kernel_accepted is True
        assert attempt.proof_candidate is not None
        assert attempt.proof_candidate.premise_ids == []
        assert len(reconstructor.reconstruct_calls) == 1

    def test_fake_kernel_rejects(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()
        reconstructor = FakeReconstructor(accept=False)

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert attempt.attempted is True
        assert attempt.recovered is False
        assert attempt.reconstruction.kernel_accepted is False
        assert attempt.reconstruction.failure_reason is not None

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean toolchain not installed")
    def test_real_lean_recovers_trivial_goal(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=LeanReconstructor(timeout=20.0),
        )

        assert attempt.attempted is True
        assert attempt.recovered is True
        assert attempt.reconstruction.kernel_accepted is True

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean toolchain not installed")
    def test_real_lean_rejects_false_goal(self):
        request = make_request(
            policy=make_policy(allow_native_automation_fallback=True),
            goal_statement="n + 1 = n + 2",
        )
        snapshot = make_goal_snapshot(goal_text="n + 1 = n + 2")

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=LEAN_FALSE_SOURCE,
            reconstructor=LeanReconstructor(timeout=20.0),
        )

        assert attempt.attempted is True
        assert attempt.recovered is False
        assert attempt.reconstruction.kernel_accepted is False

    @pytest.mark.skipif(not COQ_AVAILABLE, reason="coqtop toolchain not installed")
    def test_real_coq_recovers_trivial_goal(self):
        request = make_request(
            itp=ITPKind.COQ, policy=make_policy(allow_native_automation_fallback=True)
        )
        snapshot = make_goal_snapshot(
            itp=ITPKind.COQ,
            itp_version="Coq (test)",
            hypotheses=[LocalHypothesis(names=["n"], type_text="nat", raw="n : nat")],
            native_command=["coqtop", "Goal.v"],
        )

        attempt = fb.attempt_native_automation(
            request=request,
            goal_snapshot=snapshot,
            native_source=COQ_SORRY_SOURCE,
            reconstructor=CoqReconstructor(timeout=20.0),
        )

        assert attempt.attempted is True
        assert attempt.recovered is True


# ---------------------------------------------------------------------------
# DecompositionSubgoal
# ---------------------------------------------------------------------------


class TestDecompositionSubgoal:
    def _native(self, **overrides) -> "fb.DecompositionSubgoal":
        defaults = dict(
            subgoal_id="sg-native-1",
            request_id="req-1",
            rank=0,
            source=fb.DecompositionSource.NATIVE_STRUCTURAL,
            statement="n = n",
            content_digest="sha256:abc",
        )
        defaults.update(overrides)
        return fb.DecompositionSubgoal(**defaults)

    def _llm(self, **overrides) -> "fb.DecompositionSubgoal":
        defaults = dict(
            subgoal_id="sg-llm-1",
            request_id="req-1",
            rank=0,
            source=fb.DecompositionSource.LLM_SUGGESTED,
            statement="n = n",
            redacted_suggestion=fb.redact_llm_text("n = n"),
            review_status=fb.ReviewStatus.PENDING_REVIEW,
            content_digest="sha256:abc",
        )
        defaults.update(overrides)
        return fb.DecompositionSubgoal(**defaults)

    def test_native_subgoal_is_valid_by_default(self):
        self._native().validate()

    def test_llm_subgoal_is_valid_by_default(self):
        self._llm().validate()

    def test_native_forbids_redacted_suggestion(self):
        subgoal = self._native(redacted_suggestion="should not be set")
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_native_forbids_non_default_review_status(self):
        subgoal = self._native(review_status=fb.ReviewStatus.PENDING_REVIEW)
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_llm_requires_redacted_suggestion(self):
        subgoal = self._llm(redacted_suggestion=None)
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_llm_forbids_not_required_review_status(self):
        subgoal = self._llm(review_status=fb.ReviewStatus.NOT_REQUIRED)
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_verified_requires_reconstruction_id(self):
        subgoal = self._native(status=fb.SubgoalStatus.VERIFIED)
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_verified_native_with_reconstruction_id_is_valid(self):
        subgoal = self._native(
            status=fb.SubgoalStatus.VERIFIED, reconstruction_id="recon-1"
        )
        subgoal.validate()

    def test_llm_verified_requires_reviewed_status(self):
        subgoal = self._llm(
            status=fb.SubgoalStatus.VERIFIED,
            reconstruction_id="recon-1",
            review_status=fb.ReviewStatus.PENDING_REVIEW,
        )
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_rejected_review_forbids_verified_status(self):
        subgoal = self._llm(
            status=fb.SubgoalStatus.VERIFIED,
            reconstruction_id="recon-1",
            review_status=fb.ReviewStatus.REJECTED,
        )
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_reviewed_by_and_reviewed_at_must_be_set_together(self):
        subgoal = self._llm(reviewed_by="alice")
        with pytest.raises(ValueError):
            subgoal.validate()

    def test_round_trip(self):
        subgoal = self._llm(
            review_status=fb.ReviewStatus.REVIEWED,
            reviewed_by="alice",
            reviewed_at=fb._utcnow(),
            review_notes="looks reasonable",
            status=fb.SubgoalStatus.VERIFIED,
            reconstruction_id="recon-1",
        )
        restored = fb.DecompositionSubgoal.from_dict(subgoal.to_dict())
        assert restored == subgoal


# ---------------------------------------------------------------------------
# DecompositionPlan
# ---------------------------------------------------------------------------


class TestDecompositionPlan:
    def test_rejects_exceeding_max_subgoals(self):
        subgoals = [
            fb.DecompositionSubgoal(
                subgoal_id=f"sg-{i}",
                request_id="req-1",
                rank=i,
                statement=f"stmt-{i}",
                content_digest=f"sha256:{i}",
            )
            for i in range(3)
        ]
        plan = fb.DecompositionPlan(
            plan_id="plan-1",
            request_id="req-1",
            max_subgoals=2,
            subgoals=subgoals,
        )
        with pytest.raises(ValueError):
            plan.validate()

    def test_rejects_duplicate_subgoal_ids(self):
        subgoals = [
            fb.DecompositionSubgoal(
                subgoal_id="sg-dup",
                request_id="req-1",
                rank=0,
                statement="a",
                content_digest="sha256:a",
            ),
            fb.DecompositionSubgoal(
                subgoal_id="sg-dup",
                request_id="req-1",
                rank=1,
                statement="b",
                content_digest="sha256:b",
            ),
        ]
        plan = fb.DecompositionPlan(
            plan_id="plan-1", request_id="req-1", max_subgoals=4, subgoals=subgoals
        )
        with pytest.raises(ValueError):
            plan.validate()

    def test_rejects_duplicate_ranks(self):
        subgoals = [
            fb.DecompositionSubgoal(
                subgoal_id="sg-a",
                request_id="req-1",
                rank=0,
                statement="a",
                content_digest="sha256:a",
            ),
            fb.DecompositionSubgoal(
                subgoal_id="sg-b",
                request_id="req-1",
                rank=0,
                statement="b",
                content_digest="sha256:b",
            ),
        ]
        plan = fb.DecompositionPlan(
            plan_id="plan-1", request_id="req-1", max_subgoals=4, subgoals=subgoals
        )
        with pytest.raises(ValueError):
            plan.validate()

    def test_rejects_subgoal_from_different_request(self):
        subgoal = fb.DecompositionSubgoal(
            subgoal_id="sg-a",
            request_id="other-request",
            rank=0,
            statement="a",
            content_digest="sha256:a",
        )
        plan = fb.DecompositionPlan(
            plan_id="plan-1", request_id="req-1", max_subgoals=4, subgoals=[subgoal]
        )
        with pytest.raises(ValueError):
            plan.validate()

    def test_is_fully_verified_false_when_empty(self):
        plan = fb.DecompositionPlan(plan_id="plan-1", request_id="req-1")
        assert plan.is_fully_verified() is False

    def test_is_fully_verified_true_only_when_all_verified(self):
        verified = fb.DecompositionSubgoal(
            subgoal_id="sg-a",
            request_id="req-1",
            rank=0,
            statement="a",
            content_digest="sha256:a",
            status=fb.SubgoalStatus.VERIFIED,
            reconstruction_id="recon-a",
        )
        pending = fb.DecompositionSubgoal(
            subgoal_id="sg-b",
            request_id="req-1",
            rank=1,
            statement="b",
            content_digest="sha256:b",
        )
        plan = fb.DecompositionPlan(
            plan_id="plan-1",
            request_id="req-1",
            max_subgoals=4,
            subgoals=[verified, pending],
        )
        assert plan.is_fully_verified() is False

        plan.subgoals = [verified]
        assert plan.is_fully_verified() is True

    def test_round_trip(self):
        subgoal = fb.DecompositionSubgoal(
            subgoal_id="sg-a",
            request_id="req-1",
            rank=0,
            statement="a",
            content_digest="sha256:a",
        )
        plan = fb.DecompositionPlan(
            plan_id="plan-1",
            request_id="req-1",
            trigger=fb.FallbackTrigger.SEARCH_FAILURE,
            max_subgoals=4,
            subgoals=[subgoal],
            notes=["a note"],
        )
        restored = fb.DecompositionPlan.from_dict(plan.to_dict())
        assert restored == plan


# ---------------------------------------------------------------------------
# build_decomposition_plan
# ---------------------------------------------------------------------------


class TestBuildDecompositionPlan:
    def test_no_conjunction_yields_empty_plan_with_note(self):
        request = make_request(policy=make_policy(max_decomposition_subgoals=4))
        snapshot = make_goal_snapshot(goal_text="n = n")

        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
        )

        assert plan.subgoals == []
        assert any("no top-level conjunction" in note for note in plan.notes)

    def test_native_structural_subgoals_are_extracted(self):
        request = make_request(policy=make_policy(max_decomposition_subgoals=4))
        snapshot = make_goal_snapshot(goal_text="n = n ∧ m = m")

        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
        )

        assert [s.statement for s in plan.subgoals] == ["n = n", "m = m"]
        assert all(
            s.source is fb.DecompositionSource.NATIVE_STRUCTURAL
            for s in plan.subgoals
        )
        assert all(
            s.review_status is fb.ReviewStatus.NOT_REQUIRED for s in plan.subgoals
        )
        assert [s.rank for s in plan.subgoals] == [0, 1]

    def test_llm_ignored_when_policy_disabled(self):
        request = make_request(
            policy=make_policy(
                max_decomposition_subgoals=4, allow_llm_decomposition_hints=False
            )
        )
        snapshot = make_goal_snapshot(goal_text="n = n")

        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=lambda gs: ["m = m"],
        )

        assert plan.subgoals == []
        assert any(
            "allow_llm_decomposition_hints is False" in note for note in plan.notes
        )

    def test_llm_used_when_policy_enabled(self):
        request = make_request(
            policy=make_policy(
                max_decomposition_subgoals=4, allow_llm_decomposition_hints=True
            )
        )
        snapshot = make_goal_snapshot(goal_text="n = n")

        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=lambda gs: ["m = m"],
        )

        assert len(plan.subgoals) == 1
        subgoal = plan.subgoals[0]
        assert subgoal.source is fb.DecompositionSource.LLM_SUGGESTED
        assert subgoal.statement == "m = m"
        assert "m = m" not in subgoal.redacted_suggestion
        assert subgoal.review_status is fb.ReviewStatus.PENDING_REVIEW
        assert subgoal.status is fb.SubgoalStatus.PENDING

    def test_native_subgoals_take_priority_over_llm_within_bound(self):
        request = make_request(
            policy=make_policy(
                max_decomposition_subgoals=2, allow_llm_decomposition_hints=True
            )
        )
        snapshot = make_goal_snapshot(goal_text="n = n ∧ m = m")

        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=lambda gs: ["p = p"],
        )

        # The native split alone already fills max_subgoals=2; no room left
        # for the LLM suggestion.
        assert len(plan.subgoals) == 2
        assert all(
            s.source is fb.DecompositionSource.NATIVE_STRUCTURAL
            for s in plan.subgoals
        )
        assert any("already reached" in note for note in plan.notes)

    def test_llm_suggestions_beyond_remaining_budget_are_truncated_with_note(self):
        request = make_request(
            policy=make_policy(
                max_decomposition_subgoals=2, allow_llm_decomposition_hints=True
            )
        )
        snapshot = make_goal_snapshot(goal_text="n = n")

        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            llm_decomposition_provider=lambda gs: ["a = a", "b = b", "c = c"],
        )

        assert len(plan.subgoals) == 2
        assert any("only 2 were accepted" in note for note in plan.notes)

    def test_bounded_native_split_folds_remainder(self):
        request = make_request(policy=make_policy(max_decomposition_subgoals=2))
        snapshot = make_goal_snapshot(goal_text="a = a ∧ b = b ∧ c = c")

        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
        )

        assert len(plan.subgoals) == 2
        assert plan.subgoals[0].statement == "a = a"
        assert plan.subgoals[1].statement == "b = b ∧ c = c"

    def test_invalid_trigger_raises(self):
        request = make_request()
        snapshot = make_goal_snapshot()
        with pytest.raises(fb.FallbackInputError):
            fb.build_decomposition_plan(
                request=request, trigger="not-a-trigger", goal_snapshot=snapshot  # type: ignore[arg-type]
            )


# ---------------------------------------------------------------------------
# review_decomposition_subgoal
# ---------------------------------------------------------------------------


class TestReviewDecompositionSubgoal:
    def _llm_subgoal(self) -> "fb.DecompositionSubgoal":
        return fb.DecompositionSubgoal(
            subgoal_id="sg-llm-1",
            request_id="req-1",
            rank=0,
            source=fb.DecompositionSource.LLM_SUGGESTED,
            statement="n = n",
            redacted_suggestion=fb.redact_llm_text("n = n"),
            review_status=fb.ReviewStatus.PENDING_REVIEW,
            content_digest="sha256:abc",
        )

    def test_refuses_native_structural_subgoal(self):
        subgoal = fb.DecompositionSubgoal(
            subgoal_id="sg-native-1",
            request_id="req-1",
            rank=0,
            statement="n = n",
            content_digest="sha256:abc",
        )
        with pytest.raises(fb.FallbackInputError):
            fb.review_decomposition_subgoal(subgoal, approve=True, reviewer="alice")

    def test_refuses_empty_reviewer(self):
        subgoal = self._llm_subgoal()
        with pytest.raises(fb.FallbackInputError):
            fb.review_decomposition_subgoal(subgoal, approve=True, reviewer="   ")

    def test_approve_sets_reviewed_status(self):
        subgoal = self._llm_subgoal()
        updated = fb.review_decomposition_subgoal(
            subgoal, approve=True, reviewer="alice", notes="looks fine"
        )
        assert updated.review_status is fb.ReviewStatus.REVIEWED
        assert updated.reviewed_by == "alice"
        assert updated.reviewed_at is not None
        assert updated.review_notes == "looks fine"
        assert updated.status is fb.SubgoalStatus.PENDING

    def test_reject_sets_rejected_status(self):
        subgoal = self._llm_subgoal()
        updated = fb.review_decomposition_subgoal(subgoal, approve=False, reviewer="bob")
        assert updated.review_status is fb.ReviewStatus.REJECTED
        assert updated.status is fb.SubgoalStatus.REJECTED

    def test_refuses_double_review(self):
        subgoal = self._llm_subgoal()
        fb.review_decomposition_subgoal(subgoal, approve=True, reviewer="alice")
        with pytest.raises(fb.FallbackInputError):
            fb.review_decomposition_subgoal(subgoal, approve=True, reviewer="alice")


# ---------------------------------------------------------------------------
# verify_decomposition_subgoal
# ---------------------------------------------------------------------------


class TestVerifyDecompositionSubgoal:
    def _native_subgoal(self, **overrides) -> "fb.DecompositionSubgoal":
        defaults = dict(
            subgoal_id="sg-native-1",
            request_id="req-1",
            rank=0,
            statement="n = n",
            content_digest="sha256:abc",
        )
        defaults.update(overrides)
        return fb.DecompositionSubgoal(**defaults)

    def _llm_subgoal(self, **overrides) -> "fb.DecompositionSubgoal":
        defaults = dict(
            subgoal_id="sg-llm-1",
            request_id="req-1",
            rank=0,
            source=fb.DecompositionSource.LLM_SUGGESTED,
            statement="n = n",
            redacted_suggestion=fb.redact_llm_text("n = n"),
            review_status=fb.ReviewStatus.PENDING_REVIEW,
            content_digest="sha256:abc",
        )
        defaults.update(overrides)
        return fb.DecompositionSubgoal(**defaults)

    def test_refuses_mismatched_request(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._native_subgoal(request_id="other-request")
        with pytest.raises(fb.FallbackInputError):
            fb.verify_decomposition_subgoal(
                subgoal, request=request, goal_snapshot=snapshot
            )

    def test_refuses_already_verified(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._native_subgoal(
            status=fb.SubgoalStatus.VERIFIED, reconstruction_id="recon-1"
        )
        with pytest.raises(fb.FallbackInputError):
            fb.verify_decomposition_subgoal(
                subgoal, request=request, goal_snapshot=snapshot
            )

    def test_refuses_review_rejected(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._llm_subgoal(
            review_status=fb.ReviewStatus.REJECTED, status=fb.SubgoalStatus.REJECTED
        )
        with pytest.raises(fb.FallbackInputError):
            fb.verify_decomposition_subgoal(
                subgoal, request=request, goal_snapshot=snapshot
            )

    def test_refuses_unreviewed_llm_subgoal(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._llm_subgoal()
        with pytest.raises(fb.FallbackInputError):
            fb.verify_decomposition_subgoal(
                subgoal, request=request, goal_snapshot=snapshot
            )

    def test_kernel_unavailable_marks_skipped(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._native_subgoal()
        reconstructor = FakeReconstructor(available=False)

        updated, record, evidence = fb.verify_decomposition_subgoal(
            subgoal, request=request, goal_snapshot=snapshot, reconstructor=reconstructor
        )

        assert updated.status is fb.SubgoalStatus.SKIPPED
        assert record is None
        assert evidence is None

    def test_fake_kernel_accepts_marks_verified(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._native_subgoal()
        reconstructor = FakeReconstructor(accept=True)

        updated, record, evidence = fb.verify_decomposition_subgoal(
            subgoal, request=request, goal_snapshot=snapshot, reconstructor=reconstructor
        )

        assert updated.status is fb.SubgoalStatus.VERIFIED
        assert updated.reconstruction_id == record.reconstruction_id
        assert record.kernel_accepted is True

    def test_fake_kernel_rejects_marks_rejected(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._native_subgoal()
        reconstructor = FakeReconstructor(accept=False)

        updated, record, evidence = fb.verify_decomposition_subgoal(
            subgoal, request=request, goal_snapshot=snapshot, reconstructor=reconstructor
        )

        assert updated.status is fb.SubgoalStatus.REJECTED
        assert record.kernel_accepted is False

    def test_reviewed_llm_subgoal_can_be_verified(self):
        request = make_request(request_id="req-1")
        snapshot = make_goal_snapshot()
        subgoal = self._llm_subgoal()
        fb.review_decomposition_subgoal(subgoal, approve=True, reviewer="alice")
        reconstructor = FakeReconstructor(accept=True)

        updated, record, evidence = fb.verify_decomposition_subgoal(
            subgoal, request=request, goal_snapshot=snapshot, reconstructor=reconstructor
        )

        assert updated.status is fb.SubgoalStatus.VERIFIED
        assert updated.review_status is fb.ReviewStatus.REVIEWED

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean toolchain not installed")
    def test_real_lean_verifies_closed_conjunct_subgoal(self):
        request = make_request(
            request_id="req-lean-closed",
            theorem_id="hammer_fallback_closed",
            policy=make_policy(max_decomposition_subgoals=4),
        )
        snapshot = make_goal_snapshot(
            theorem_id="hammer_fallback_closed", goal_text="2 = 2 ∧ 3 = 3", hypotheses=[]
        )
        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
        )
        assert [s.statement for s in plan.subgoals] == ["2 = 2", "3 = 3"]

        for subgoal in plan.subgoals:
            updated, record, evidence = fb.verify_decomposition_subgoal(
                subgoal,
                request=request,
                goal_snapshot=snapshot,
                reconstructor=LeanReconstructor(timeout=20.0),
            )
            assert updated.status is fb.SubgoalStatus.VERIFIED
            assert record.kernel_accepted is True

        assert plan.is_fully_verified() is True

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean toolchain not installed")
    def test_real_lean_rejects_false_subgoal(self):
        request = make_request(
            request_id="req-lean-false",
            theorem_id="hammer_fallback_false_subgoal",
            policy=make_policy(max_decomposition_subgoals=4),
        )
        snapshot = make_goal_snapshot(
            theorem_id="hammer_fallback_false_subgoal",
            goal_text="2 = 2 ∧ 3 = 4",
            hypotheses=[],
        )
        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
        )
        false_subgoal = next(s for s in plan.subgoals if s.statement == "3 = 4")

        updated, record, evidence = fb.verify_decomposition_subgoal(
            false_subgoal,
            request=request,
            goal_snapshot=snapshot,
            reconstructor=LeanReconstructor(timeout=20.0),
        )
        assert updated.status is fb.SubgoalStatus.REJECTED
        assert record.kernel_accepted is False
        assert plan.is_fully_verified() is False

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean toolchain not installed")
    def test_real_lean_verifies_hypothesis_dependent_subgoal(self):
        request = make_request(
            request_id="req-lean-hyp",
            theorem_id="hammer_fallback_hyp",
            policy=make_policy(max_decomposition_subgoals=4),
        )
        snapshot = make_goal_snapshot(
            theorem_id="hammer_fallback_hyp",
            goal_text="n = n ∧ n + 0 = n",
            hypotheses=[LocalHypothesis(names=["n"], type_text="Nat", raw="n : Nat")],
        )
        plan = fb.build_decomposition_plan(
            request=request,
            trigger=fb.FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
        )

        for subgoal in plan.subgoals:
            updated, record, evidence = fb.verify_decomposition_subgoal(
                subgoal,
                request=request,
                goal_snapshot=snapshot,
                reconstructor=LeanReconstructor(timeout=20.0),
            )
            assert updated.status is fb.SubgoalStatus.VERIFIED

        assert plan.is_fully_verified() is True


# ---------------------------------------------------------------------------
# attempt_fallback (end-to-end orchestration)
# ---------------------------------------------------------------------------


class TestAttemptFallback:
    def test_rejects_mismatched_itp(self):
        request = make_request(itp=ITPKind.LEAN)
        snapshot = make_goal_snapshot(itp=ITPKind.COQ)
        with pytest.raises(fb.FallbackInputError):
            fb.attempt_fallback(
                request=request,
                trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
                goal_snapshot=snapshot,
                native_source=LEAN_SORRY_SOURCE,
            )

    def test_rejects_mismatched_theorem_id(self):
        request = make_request(theorem_id="thm-a")
        snapshot = make_goal_snapshot(theorem_id="thm-b")
        with pytest.raises(fb.FallbackInputError):
            fb.attempt_fallback(
                request=request,
                trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
                goal_snapshot=snapshot,
                native_source=LEAN_SORRY_SOURCE,
            )

    def test_invalid_trigger_raises(self):
        request = make_request()
        snapshot = make_goal_snapshot()
        with pytest.raises(fb.FallbackInputError):
            fb.attempt_fallback(
                request=request,
                trigger="not-a-trigger",  # type: ignore[arg-type]
                goal_snapshot=snapshot,
                native_source=LEAN_SORRY_SOURCE,
            )

    def test_native_automation_recovery_skips_decomposition(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()
        reconstructor = FakeReconstructor(accept=True)

        outcome = fb.attempt_fallback(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert outcome.recovered is True
        assert outcome.decomposition_plan is None
        assert outcome.native_automation.attempted is True
        assert any("no decomposition plan was needed" in n for n in outcome.notes)

    def test_disabled_native_automation_builds_decomposition(self):
        request = make_request(
            policy=make_policy(
                allow_native_automation_fallback=False, max_decomposition_subgoals=4
            )
        )
        snapshot = make_goal_snapshot(goal_text="n = n ∧ m = m")

        outcome = fb.attempt_fallback(
            request=request,
            trigger=fb.FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
        )

        assert outcome.recovered is False
        assert outcome.decomposition_plan is not None
        assert [s.statement for s in outcome.decomposition_plan.subgoals] == [
            "n = n",
            "m = m",
        ]
        assert any("was not attempted" in n for n in outcome.notes)

    def test_rejected_native_automation_records_error_and_builds_decomposition(self):
        request = make_request(
            policy=make_policy(
                allow_native_automation_fallback=True, max_decomposition_subgoals=4
            )
        )
        snapshot = make_goal_snapshot(goal_text="n = n ∧ m = m")
        reconstructor = FakeReconstructor(accept=False)

        outcome = fb.attempt_fallback(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=reconstructor,
        )

        assert outcome.recovered is False
        assert outcome.native_automation.attempted is True
        assert outcome.decomposition_plan is not None
        assert any("kernel rejected" in e for e in outcome.errors)

    def test_round_trip(self):
        request = make_request(
            policy=make_policy(
                allow_native_automation_fallback=False, max_decomposition_subgoals=4
            )
        )
        snapshot = make_goal_snapshot(goal_text="n = n ∧ m = m")

        outcome = fb.attempt_fallback(
            request=request,
            trigger=fb.FallbackTrigger.SEARCH_FAILURE,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
        )

        restored = fb.FallbackOutcome.from_dict(outcome.to_dict())
        assert restored.to_dict() == outcome.to_dict()

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean toolchain not installed")
    def test_real_lean_end_to_end_recovery(self):
        request = make_request(policy=make_policy(allow_native_automation_fallback=True))
        snapshot = make_goal_snapshot()

        outcome = fb.attempt_fallback(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            native_source=LEAN_SORRY_SOURCE,
            reconstructor=LeanReconstructor(timeout=20.0),
        )

        assert outcome.recovered is True
        assert outcome.native_automation.reconstruction.kernel_accepted is True
        assert outcome.decomposition_plan is None

    @pytest.mark.skipif(not LEAN_AVAILABLE, reason="lean toolchain not installed")
    def test_real_lean_end_to_end_decomposition_after_rejection(self):
        request = make_request(
            theorem_id="hammer_fallback_reject_thm",
            policy=make_policy(
                allow_native_automation_fallback=True, max_decomposition_subgoals=4
            ),
            goal_statement="n + 1 = n + 2",
        )
        snapshot = make_goal_snapshot(
            theorem_id="hammer_fallback_reject_thm", goal_text="n + 1 = n + 2"
        )

        outcome = fb.attempt_fallback(
            request=request,
            trigger=fb.FallbackTrigger.RECONSTRUCTION_FAILURE,
            goal_snapshot=snapshot,
            native_source=LEAN_FALSE_SOURCE,
            reconstructor=LeanReconstructor(timeout=20.0),
        )

        assert outcome.recovered is False
        assert outcome.native_automation.attempted is True
        assert outcome.native_automation.recovered is False
        # No top-level conjunction in "n + 1 = n + 2": decomposition is
        # still returned, but honestly empty.
        assert outcome.decomposition_plan is not None
        assert outcome.decomposition_plan.subgoals == []

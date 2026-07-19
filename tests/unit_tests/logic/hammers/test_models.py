"""Tests for the ITP hammer trust contract and result schema (HAMMER-001).

These tests cover:
- All eight required `HammerResultStatus` states exist with the expected
  values.
- Validation of each versioned record (policy, request, premise,
  translation, solver-attempt, proof-candidate, reconstruction,
  environment-lock).
- The core trust-boundary invariant: only a successful kernel
  `ReconstructionRecord` may produce `HammerResultStatus.VERIFIED`, and a
  successful reconstruction may never be attached to a non-verified result.
- Serialization round-trips (`to_dict` / `from_dict`) for every record type.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from ipfs_datasets_py.logic.hammers.models import (
    SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    HammerResult,
    HammerResultStatus,
    ITPKind,
    PremiseRecord,
    ProofCandidateRecord,
    ReconstructionRecord,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def make_policy(**overrides) -> HammerPolicy:
    defaults = dict(
        timeout_seconds=30.0,
        network_allowed=False,
        allowed_solvers=["z3", "cvc5"],
    )
    defaults.update(overrides)
    return HammerPolicy(**defaults)


def make_request(**overrides) -> HammerRequest:
    defaults = dict(
        request_id="req-1",
        itp=ITPKind.LEAN,
        theorem_id="Nat.add_comm",
        goal_statement="forall a b : Nat, a + b = b + a",
        corpus_revision="corpus-rev-1",
        policy=make_policy(),
    )
    defaults.update(overrides)
    return HammerRequest(**defaults)


def make_premise(premise_id="premise-1", rank=0, **overrides) -> PremiseRecord:
    defaults = dict(
        premise_id=premise_id,
        statement="forall a : Nat, a + 0 = a",
        source_itp=ITPKind.LEAN,
        corpus_revision="corpus-rev-1",
        rank=rank,
        score=1.0,
    )
    defaults.update(overrides)
    return PremiseRecord(**defaults)


def make_supported_translation(**overrides) -> TranslationRecord:
    defaults = dict(
        translation_id="trans-1",
        request_id="req-1",
        target=TranslationTarget.TPTP,
        status=TranslationStatus.SUPPORTED,
        source_construct="goal:Nat.add_comm",
        translated_text="fof(goal, conjecture, ![A,B]: add(A,B) = add(B,A)).",
    )
    defaults.update(overrides)
    return TranslationRecord(**defaults)


def make_unsupported_translation(**overrides) -> TranslationRecord:
    defaults = dict(
        translation_id="trans-unsupported-1",
        request_id="req-1",
        target=TranslationTarget.TPTP,
        status=TranslationStatus.UNSUPPORTED,
        source_construct="goal:HigherOrder.example",
        unsupported_reason="goal contains a higher-order quantifier",
    )
    defaults.update(overrides)
    return TranslationRecord(**defaults)


def make_solver_attempt(**overrides) -> SolverAttemptRecord:
    defaults = dict(
        attempt_id="attempt-1",
        request_id="req-1",
        translation_id="trans-1",
        solver_name="z3",
        solver_version="4.13.0",
        target=TranslationTarget.TPTP,
        timeout_seconds=30.0,
        verdict=SolverVerdict.PROVED,
        wall_time_seconds=1.5,
    )
    defaults.update(overrides)
    return SolverAttemptRecord(**defaults)


def make_candidate(**overrides) -> ProofCandidateRecord:
    defaults = dict(
        candidate_id="candidate-1",
        request_id="req-1",
        solver_attempt_id="attempt-1",
        premise_ids=["premise-1"],
        certificate="(proof ...)",
        certificate_format="tstp",
    )
    defaults.update(overrides)
    return ProofCandidateRecord(**defaults)


def make_environment_lock(**overrides) -> EnvironmentLockRecord:
    defaults = dict(
        lock_id="lock-1",
        itp=ITPKind.LEAN,
        itp_version="4.9.0",
        kernel_command_template="lean --check {proof_file}",
        solver_versions={"z3": "4.13.0"},
        executable_paths={"lean": "/usr/bin/lean", "z3": "/usr/bin/z3"},
        os_info="Linux x86_64",
    )
    defaults.update(overrides)
    return EnvironmentLockRecord(**defaults)


def make_accepted_reconstruction(**overrides) -> ReconstructionRecord:
    defaults = dict(
        reconstruction_id="recon-1",
        request_id="req-1",
        candidate_id="candidate-1",
        target_itp=ITPKind.LEAN,
        environment_lock_id="lock-1",
        kernel_command="lean --check candidate-1.lean",
        kernel_accepted=True,
    )
    defaults.update(overrides)
    return ReconstructionRecord(**defaults)


def make_rejected_reconstruction(**overrides) -> ReconstructionRecord:
    defaults = dict(
        reconstruction_id="recon-2",
        request_id="req-1",
        candidate_id="candidate-1",
        target_itp=ITPKind.LEAN,
        environment_lock_id="lock-1",
        kernel_command="lean --check candidate-1.lean",
        kernel_accepted=False,
        failure_reason="kernel type-checking failed: universe mismatch",
    )
    defaults.update(overrides)
    return ReconstructionRecord(**defaults)


def make_verified_result(**overrides) -> HammerResult:
    defaults = dict(
        result_id="result-1",
        request=make_request(),
        status=HammerResultStatus.VERIFIED,
        corpus_revision="corpus-rev-1",
        environment_lock=make_environment_lock(),
        premises=[make_premise()],
        translations=[make_supported_translation()],
        solver_attempts=[make_solver_attempt()],
        proof_candidate=make_candidate(),
        reconstruction=make_accepted_reconstruction(),
    )
    defaults.update(overrides)
    return HammerResult(**defaults)


# ---------------------------------------------------------------------------
# HammerResultStatus enum
# ---------------------------------------------------------------------------


class TestHammerResultStatus:
    def test_all_required_states_present(self):
        expected = {
            "verified",
            "candidate",
            "counterexample",
            "unknown",
            "timeout",
            "unsupported_translation",
            "unavailable",
            "policy_denied",
        }
        actual = {status.value for status in HammerResultStatus}
        assert actual == expected

    def test_status_is_str_enum(self):
        assert HammerResultStatus.VERIFIED == "verified"
        assert isinstance(HammerResultStatus.VERIFIED.value, str)


# ---------------------------------------------------------------------------
# HammerPolicy
# ---------------------------------------------------------------------------


class TestHammerPolicy:
    def test_valid_policy(self):
        policy = make_policy()
        policy.validate()  # should not raise

    def test_default_schema_version(self):
        assert HammerPolicy().schema_version == SCHEMA_VERSION

    @pytest.mark.parametrize(
        "overrides,message",
        [
            ({"timeout_seconds": 0}, "timeout_seconds"),
            ({"timeout_seconds": -1}, "timeout_seconds"),
            ({"cpu_seconds": 0}, "cpu_seconds"),
            ({"memory_mb": -5}, "memory_mb"),
            ({"network_allowed": "yes"}, "network_allowed"),
            ({"allowed_solvers": ["z3", "z3"]}, "duplicates"),
            ({"allowed_solvers": ["", "z3"]}, "allowed_solvers"),
            ({"max_premises": 0}, "max_premises"),
        ],
    )
    def test_invalid_policy_raises(self, overrides, message):
        policy = make_policy(**overrides)
        with pytest.raises(ValueError, match=message):
            policy.validate()

    def test_permits_solver(self):
        policy = make_policy(allowed_solvers=["z3"])
        assert policy.permits_solver("z3")
        assert not policy.permits_solver("cvc5")

    def test_round_trip(self):
        policy = make_policy()
        restored = HammerPolicy.from_dict(policy.to_dict())
        assert restored == policy


# ---------------------------------------------------------------------------
# HammerRequest
# ---------------------------------------------------------------------------


class TestHammerRequest:
    def test_valid_request(self):
        make_request().validate()

    def test_bad_schema_version_rejected(self):
        request = make_request(schema_version="0.0.1")
        with pytest.raises(ValueError, match="schema_version"):
            request.validate()

    def test_empty_request_id_rejected(self):
        request = make_request(request_id="")
        with pytest.raises(ValueError, match="request_id"):
            request.validate()

    def test_wrong_itp_type_rejected(self):
        request = make_request(itp="lean")  # plain string, not ITPKind
        with pytest.raises(ValueError, match="itp"):
            request.validate()

    def test_invalid_nested_policy_propagates(self):
        request = make_request(policy=make_policy(timeout_seconds=-1))
        with pytest.raises(ValueError, match="timeout_seconds"):
            request.validate()

    def test_round_trip(self):
        request = make_request()
        restored = HammerRequest.from_dict(request.to_dict())
        assert restored.request_id == request.request_id
        assert restored.itp == request.itp
        assert restored.policy == request.policy
        assert restored.corpus_revision == request.corpus_revision


# ---------------------------------------------------------------------------
# PremiseRecord
# ---------------------------------------------------------------------------


class TestPremiseRecord:
    def test_valid_premise(self):
        make_premise().validate()

    def test_negative_rank_rejected(self):
        with pytest.raises(ValueError, match="rank"):
            make_premise(rank=-1).validate()

    def test_non_finite_score_rejected(self):
        with pytest.raises(ValueError, match="score"):
            make_premise(score=float("nan")).validate()

    def test_empty_corpus_revision_rejected(self):
        with pytest.raises(ValueError, match="corpus_revision"):
            make_premise(corpus_revision="").validate()

    def test_round_trip(self):
        premise = make_premise()
        restored = PremiseRecord.from_dict(premise.to_dict())
        assert restored == premise


# ---------------------------------------------------------------------------
# TranslationRecord
# ---------------------------------------------------------------------------


class TestTranslationRecord:
    def test_supported_requires_text(self):
        translation = make_supported_translation(translated_text=None)
        with pytest.raises(ValueError, match="translated_text"):
            translation.validate()

    def test_supported_forbids_unsupported_reason(self):
        translation = make_supported_translation(unsupported_reason="nope")
        with pytest.raises(ValueError, match="unsupported_reason"):
            translation.validate()

    def test_valid_supported_translation(self):
        make_supported_translation().validate()

    def test_unsupported_requires_reason(self):
        translation = make_unsupported_translation(unsupported_reason=None)
        with pytest.raises(ValueError, match="unsupported_reason"):
            translation.validate()

    def test_unsupported_forbids_translated_text(self):
        translation = make_unsupported_translation(translated_text="fof(...).")
        with pytest.raises(ValueError, match="translated_text"):
            translation.validate()

    def test_valid_unsupported_translation(self):
        make_unsupported_translation().validate()

    def test_partial_requires_obligations(self):
        translation = TranslationRecord(
            translation_id="trans-partial",
            request_id="req-1",
            target=TranslationTarget.SMTLIB,
            status=TranslationStatus.PARTIAL,
            source_construct="goal:PartialExample",
            translated_text="(assert (partial-encoding))",
            obligations=[],
        )
        with pytest.raises(ValueError, match="obligations"):
            translation.validate()

    def test_valid_partial_translation(self):
        translation = TranslationRecord(
            translation_id="trans-partial",
            request_id="req-1",
            target=TranslationTarget.SMTLIB,
            status=TranslationStatus.PARTIAL,
            source_construct="goal:PartialExample",
            translated_text="(assert (partial-encoding))",
            obligations=["monomorphized instance List Nat"],
        )
        translation.validate()

    def test_round_trip(self):
        translation = make_supported_translation()
        restored = TranslationRecord.from_dict(translation.to_dict())
        assert restored == translation


# ---------------------------------------------------------------------------
# SolverAttemptRecord
# ---------------------------------------------------------------------------


class TestSolverAttemptRecord:
    def test_valid_attempt(self):
        make_solver_attempt().validate()

    def test_negative_timeout_rejected(self):
        with pytest.raises(ValueError, match="timeout_seconds"):
            make_solver_attempt(timeout_seconds=0).validate()

    def test_finished_before_started_rejected(self):
        started = datetime.now(timezone.utc)
        finished = started - timedelta(seconds=5)
        attempt = make_solver_attempt(started_at=started, finished_at=finished)
        with pytest.raises(ValueError, match="finished_at"):
            attempt.validate()

    def test_timeout_verdict_requires_full_wall_time(self):
        attempt = make_solver_attempt(
            verdict=SolverVerdict.TIMEOUT,
            timeout_seconds=30.0,
            wall_time_seconds=1.0,
        )
        with pytest.raises(ValueError, match="TIMEOUT"):
            attempt.validate()

    def test_valid_timeout_attempt(self):
        attempt = make_solver_attempt(
            verdict=SolverVerdict.TIMEOUT,
            timeout_seconds=30.0,
            wall_time_seconds=30.2,
        )
        attempt.validate()

    def test_round_trip(self):
        attempt = make_solver_attempt()
        restored = SolverAttemptRecord.from_dict(attempt.to_dict())
        assert restored.attempt_id == attempt.attempt_id
        assert restored.verdict == attempt.verdict
        assert restored.target == attempt.target


# ---------------------------------------------------------------------------
# ProofCandidateRecord
# ---------------------------------------------------------------------------


class TestProofCandidateRecord:
    def test_valid_candidate(self):
        make_candidate().validate()

    def test_no_verified_field_exists(self):
        # The candidate record must never itself assert verification status;
        # only a ReconstructionRecord may do that.
        candidate = make_candidate()
        assert not hasattr(candidate, "verified")
        assert not hasattr(candidate, "kernel_accepted")

    def test_certificate_format_requires_certificate(self):
        candidate = make_candidate(certificate=None, certificate_format="tstp")
        with pytest.raises(ValueError, match="certificate"):
            candidate.validate()

    def test_empty_premise_ids_allowed(self):
        candidate = make_candidate(premise_ids=[])
        candidate.validate()

    def test_round_trip(self):
        candidate = make_candidate()
        restored = ProofCandidateRecord.from_dict(candidate.to_dict())
        assert restored == candidate


# ---------------------------------------------------------------------------
# ReconstructionRecord
# ---------------------------------------------------------------------------


class TestReconstructionRecord:
    def test_valid_accepted_reconstruction(self):
        make_accepted_reconstruction().validate()

    def test_valid_rejected_reconstruction(self):
        make_rejected_reconstruction().validate()

    def test_accepted_forbids_failure_reason(self):
        recon = make_accepted_reconstruction(failure_reason="should not be set")
        with pytest.raises(ValueError, match="failure_reason"):
            recon.validate()

    def test_rejected_requires_failure_reason(self):
        recon = make_rejected_reconstruction(failure_reason=None)
        with pytest.raises(ValueError, match="failure_reason"):
            recon.validate()

    def test_round_trip(self):
        recon = make_accepted_reconstruction()
        restored = ReconstructionRecord.from_dict(recon.to_dict())
        assert restored == recon


# ---------------------------------------------------------------------------
# EnvironmentLockRecord
# ---------------------------------------------------------------------------


class TestEnvironmentLockRecord:
    def test_valid_lock(self):
        make_environment_lock().validate()

    def test_empty_lock_id_rejected(self):
        with pytest.raises(ValueError, match="lock_id"):
            make_environment_lock(lock_id="").validate()

    def test_bad_solver_versions_type_rejected(self):
        lock = make_environment_lock(solver_versions={"z3": 4.13})  # not a str
        with pytest.raises(ValueError, match="solver_versions"):
            lock.validate()

    def test_round_trip(self):
        lock = make_environment_lock()
        restored = EnvironmentLockRecord.from_dict(lock.to_dict())
        assert restored.lock_id == lock.lock_id
        assert restored.itp == lock.itp
        assert restored.solver_versions == lock.solver_versions


# ---------------------------------------------------------------------------
# HammerResult — the trust-boundary invariant
# ---------------------------------------------------------------------------


class TestHammerResultVerifiedInvariant:
    def test_verified_with_full_chain_succeeds(self):
        result = make_verified_result()
        assert result.status is HammerResultStatus.VERIFIED
        assert result.is_verified()

    def test_verified_without_reconstruction_rejected(self):
        with pytest.raises(ValueError, match="reconstruction"):
            make_verified_result(reconstruction=None)

    def test_verified_with_rejected_reconstruction_rejected(self):
        with pytest.raises(ValueError, match="kernel_accepted"):
            make_verified_result(reconstruction=make_rejected_reconstruction())

    def test_verified_without_proof_candidate_rejected(self):
        with pytest.raises(ValueError, match="proof_candidate"):
            make_verified_result(proof_candidate=None)

    def test_verified_without_environment_lock_rejected(self):
        with pytest.raises(ValueError, match="environment_lock"):
            make_verified_result(environment_lock=None)

    def test_verified_candidate_id_mismatch_rejected(self):
        mismatched = make_accepted_reconstruction(candidate_id="some-other-candidate")
        with pytest.raises(ValueError, match="candidate_id"):
            make_verified_result(reconstruction=mismatched)

    def test_verified_environment_lock_id_mismatch_rejected(self):
        mismatched = make_accepted_reconstruction(environment_lock_id="other-lock")
        with pytest.raises(ValueError, match="environment_lock_id"):
            make_verified_result(reconstruction=mismatched)

    def test_accepted_reconstruction_with_non_verified_status_rejected(self):
        # A solver cannot smuggle a successful kernel check under any other
        # status label — this is the converse of the main invariant.
        with pytest.raises(ValueError, match="VERIFIED"):
            make_verified_result(status=HammerResultStatus.CANDIDATE)

    def test_validate_is_called_at_construction_time(self):
        # __post_init__ must call validate() so the invariant cannot be
        # bypassed by constructing first and validating later.
        with pytest.raises(ValueError):
            HammerResult(
                result_id="bad-result",
                request=make_request(),
                status=HammerResultStatus.VERIFIED,
                corpus_revision="corpus-rev-1",
                # No reconstruction, no proof_candidate, no environment_lock.
            )


class TestHammerResultOtherStatuses:
    def test_candidate_requires_proof_candidate(self):
        with pytest.raises(ValueError, match="proof_candidate"):
            HammerResult(
                result_id="result-candidate",
                request=make_request(),
                status=HammerResultStatus.CANDIDATE,
                corpus_revision="corpus-rev-1",
                solver_attempts=[make_solver_attempt()],
                proof_candidate=None,
            )

    def test_valid_candidate_result(self):
        result = HammerResult(
            result_id="result-candidate",
            request=make_request(),
            status=HammerResultStatus.CANDIDATE,
            corpus_revision="corpus-rev-1",
            solver_attempts=[make_solver_attempt()],
            proof_candidate=make_candidate(),
        )
        assert not result.is_verified()

    def test_counterexample_requires_solver_attempts(self):
        with pytest.raises(ValueError, match="solver_attempts"):
            HammerResult(
                result_id="result-ce",
                request=make_request(),
                status=HammerResultStatus.COUNTEREXAMPLE,
                corpus_revision="corpus-rev-1",
                solver_attempts=[],
            )

    def test_valid_counterexample_result(self):
        attempt = make_solver_attempt(verdict=SolverVerdict.DISPROVED)
        result = HammerResult(
            result_id="result-ce",
            request=make_request(),
            status=HammerResultStatus.COUNTEREXAMPLE,
            corpus_revision="corpus-rev-1",
            solver_attempts=[attempt],
        )
        assert result.status is HammerResultStatus.COUNTEREXAMPLE

    def test_valid_unknown_result(self):
        result = HammerResult(
            result_id="result-unknown",
            request=make_request(),
            status=HammerResultStatus.UNKNOWN,
            corpus_revision="corpus-rev-1",
            solver_attempts=[make_solver_attempt(verdict=SolverVerdict.UNKNOWN)],
        )
        assert result.status is HammerResultStatus.UNKNOWN

    def test_timeout_requires_solver_attempts(self):
        with pytest.raises(ValueError, match="solver_attempts"):
            HammerResult(
                result_id="result-timeout",
                request=make_request(),
                status=HammerResultStatus.TIMEOUT,
                corpus_revision="corpus-rev-1",
                solver_attempts=[],
            )

    def test_valid_timeout_result(self):
        attempt = make_solver_attempt(
            verdict=SolverVerdict.TIMEOUT,
            wall_time_seconds=30.5,
            timeout_seconds=30.0,
        )
        result = HammerResult(
            result_id="result-timeout",
            request=make_request(),
            status=HammerResultStatus.TIMEOUT,
            corpus_revision="corpus-rev-1",
            solver_attempts=[attempt],
        )
        assert result.status is HammerResultStatus.TIMEOUT

    def test_unsupported_translation_requires_unsupported_record(self):
        with pytest.raises(ValueError, match="UNSUPPORTED"):
            HammerResult(
                result_id="result-unsupported",
                request=make_request(),
                status=HammerResultStatus.UNSUPPORTED_TRANSLATION,
                corpus_revision="corpus-rev-1",
                translations=[make_supported_translation()],
            )

    def test_valid_unsupported_translation_result(self):
        result = HammerResult(
            result_id="result-unsupported",
            request=make_request(),
            status=HammerResultStatus.UNSUPPORTED_TRANSLATION,
            corpus_revision="corpus-rev-1",
            translations=[make_unsupported_translation()],
        )
        assert result.status is HammerResultStatus.UNSUPPORTED_TRANSLATION

    def test_unsupported_translation_forbids_solver_attempts(self):
        with pytest.raises(ValueError, match="solver_attempts"):
            HammerResult(
                result_id="result-unsupported",
                request=make_request(),
                status=HammerResultStatus.UNSUPPORTED_TRANSLATION,
                corpus_revision="corpus-rev-1",
                translations=[make_unsupported_translation()],
                solver_attempts=[make_solver_attempt()],
            )

    def test_valid_unavailable_result(self):
        result = HammerResult(
            result_id="result-unavailable",
            request=make_request(),
            status=HammerResultStatus.UNAVAILABLE,
            corpus_revision="corpus-rev-1",
            errors=["lean executable not found on PATH"],
        )
        assert result.status is HammerResultStatus.UNAVAILABLE

    def test_unavailable_forbids_proof_candidate(self):
        with pytest.raises(ValueError, match="proof_candidate"):
            HammerResult(
                result_id="result-unavailable",
                request=make_request(),
                status=HammerResultStatus.UNAVAILABLE,
                corpus_revision="corpus-rev-1",
                proof_candidate=make_candidate(),
            )

    def test_policy_denied_requires_errors(self):
        with pytest.raises(ValueError, match="errors"):
            HammerResult(
                result_id="result-denied",
                request=make_request(),
                status=HammerResultStatus.POLICY_DENIED,
                corpus_revision="corpus-rev-1",
                errors=[],
            )

    def test_valid_policy_denied_result(self):
        result = HammerResult(
            result_id="result-denied",
            request=make_request(),
            status=HammerResultStatus.POLICY_DENIED,
            corpus_revision="corpus-rev-1",
            errors=["solver 'vampire' is not in policy.allowed_solvers"],
        )
        assert result.status is HammerResultStatus.POLICY_DENIED

    def test_policy_denied_forbids_reconstruction(self):
        with pytest.raises(ValueError, match="reconstruction"):
            HammerResult(
                result_id="result-denied",
                request=make_request(),
                status=HammerResultStatus.POLICY_DENIED,
                corpus_revision="corpus-rev-1",
                errors=["network access denied"],
                reconstruction=make_rejected_reconstruction(),
            )


class TestHammerResultStructuralValidation:
    def test_corpus_revision_mismatch_rejected(self):
        with pytest.raises(ValueError, match="corpus_revision"):
            HammerResult(
                result_id="result-mismatch",
                request=make_request(corpus_revision="corpus-rev-1"),
                status=HammerResultStatus.UNKNOWN,
                corpus_revision="corpus-rev-DIFFERENT",
            )

    def test_duplicate_premise_ids_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            HammerResult(
                result_id="result-dupes",
                request=make_request(),
                status=HammerResultStatus.UNKNOWN,
                corpus_revision="corpus-rev-1",
                premises=[make_premise(premise_id="p1"), make_premise(premise_id="p1")],
            )

    def test_completed_before_created_rejected(self):
        created = datetime.now(timezone.utc)
        completed = created - timedelta(seconds=1)
        with pytest.raises(ValueError, match="completed_at"):
            HammerResult(
                result_id="result-time",
                request=make_request(),
                status=HammerResultStatus.UNKNOWN,
                corpus_revision="corpus-rev-1",
                created_at=created,
                completed_at=completed,
            )

    def test_wrong_status_type_rejected(self):
        with pytest.raises(ValueError, match="status"):
            HammerResult(
                result_id="result-bad-status",
                request=make_request(),
                status="verified",  # plain string, not HammerResultStatus
                corpus_revision="corpus-rev-1",
            )


class TestHammerResultSerialization:
    def test_round_trip_verified_result(self):
        result = make_verified_result()
        restored = HammerResult.from_dict(copy.deepcopy(result.to_dict()))
        assert restored.status is HammerResultStatus.VERIFIED
        assert restored.result_id == result.result_id
        assert restored.reconstruction.kernel_accepted is True
        assert restored.proof_candidate.candidate_id == result.proof_candidate.candidate_id
        assert restored.environment_lock.lock_id == result.environment_lock.lock_id
        assert len(restored.premises) == 1
        assert len(restored.translations) == 1
        assert len(restored.solver_attempts) == 1

    def test_round_trip_policy_denied_result(self):
        result = HammerResult(
            result_id="result-denied",
            request=make_request(),
            status=HammerResultStatus.POLICY_DENIED,
            corpus_revision="corpus-rev-1",
            errors=["network access denied"],
        )
        restored = HammerResult.from_dict(result.to_dict())
        assert restored.status is HammerResultStatus.POLICY_DENIED
        assert restored.errors == ["network access denied"]
        assert restored.environment_lock is None
        assert restored.proof_candidate is None
        assert restored.reconstruction is None

    def test_to_dict_is_json_compatible(self):
        import json

        result = make_verified_result()
        # Should not raise — every value must be a JSON-serializable primitive.
        json.dumps(result.to_dict())


class TestSchemaVersioning:
    def test_supported_schema_versions_contains_current(self):
        assert SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS

    def test_unsupported_schema_version_rejected_on_result(self):
        result = make_verified_result()
        result.schema_version = "0.0.1"
        with pytest.raises(ValueError, match="schema_version"):
            result.validate()

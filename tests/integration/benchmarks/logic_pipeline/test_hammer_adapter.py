"""Integration evidence for the benchmark Hammer proof-search adapter."""

from __future__ import annotations

from dataclasses import replace

import pytest

from benchmarks.logic_pipeline import adapters, contracts

from ipfs_datasets_py.logic.hammers.models import (
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    ITPKind,
    ProofCandidateRecord,
    ReconstructionRecord,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.portfolio import PortfolioRunResult


SHA_A = "a" * 64
SHA_B = "b" * 64


def _benchmark_request(*, request_id: str = "hammer-request-1") -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id="hammer-run-1",
        case_id="hammer-case-1",
        case_manifest_sha256=SHA_A,
        input_data={"request_id": request_id, "goal": "forall n, n = n"},
        requested_identity={"request_id": request_id, "implementation": "test"},
        environment_sha256=SHA_B,
    )


def _records(*, request_id: str = "hammer-request-1", accepted: bool = False) -> dict[str, object]:
    policy = HammerPolicy(timeout_seconds=5.0, allowed_solvers=["z3"])
    hammer_request = HammerRequest(
        request_id=request_id,
        itp=ITPKind.LEAN,
        theorem_id="identity",
        goal_statement="forall n, n = n",
        corpus_revision="corpus-revision-1",
        policy=policy,
    )
    translation = TranslationRecord(
        translation_id="translation-1",
        request_id=request_id,
        target=TranslationTarget.SMTLIB,
        status=TranslationStatus.SUPPORTED,
        source_construct="goal:identity",
        translated_text="(assert (= 0 0))",
    )
    attempt = SolverAttemptRecord(
        attempt_id="attempt-1",
        request_id=request_id,
        translation_id=translation.translation_id,
        solver_name="z3",
        target=translation.target,
        timeout_seconds=5.0,
        verdict=SolverVerdict.PROVED,
        wall_time_seconds=0.1,
    )
    portfolio = PortfolioRunResult(request_id=request_id, attempts=[attempt])
    candidate = ProofCandidateRecord(
        candidate_id="candidate-1",
        request_id=request_id,
        solver_attempt_id=attempt.attempt_id,
        premise_ids=[],
        certificate="exact rfl",
        certificate_format="lean",
    )
    lock = EnvironmentLockRecord(
        lock_id="environment-lock-1",
        itp=ITPKind.LEAN,
        itp_version="test-kernel-1",
        kernel_command_template="lean --check {proof_file}",
        solver_versions={"z3": "test-z3"},
        executable_paths={"lean": "/usr/bin/lean", "z3": "/usr/bin/z3"},
        os_info="test",
    )
    reconstruction = ReconstructionRecord(
        reconstruction_id="reconstruction-1",
        request_id=request_id,
        candidate_id=candidate.candidate_id,
        target_itp=ITPKind.LEAN,
        environment_lock_id=lock.lock_id,
        kernel_command="lean --check candidate.lean",
        kernel_accepted=accepted,
        failure_reason=None if accepted else "test kernel rejection",
    )
    return {
        "request": hammer_request,
        "portfolio": portfolio,
        "proof_candidate": candidate,
        "reconstruction": reconstruction,
        "environment_lock": lock,
    }


def _run(payload: dict[str, object], request: adapters.StageRequest | None = None):
    return adapters.HammerAdapter(lambda _request: payload).run(
        request or _benchmark_request(),
        telemetry=contracts.TelemetryRecord(resource_lane=contracts.ResourceLane.SOLVER),
    )


def test_hammer_evidence_receipt_and_ast_binding_are_present() -> None:
    assert adapters.HSSLEV0335D9B() == (
        "Hammer request, bounded portfolio, normalization, reconstruction, and receipt records"
    )
    record = _run(_records())

    assert record.stage is contracts.StageName.HAMMER
    assert record.status is contracts.StageStatus.SUCCESS
    assert record.provenance.effective_identity == {"request_id": "hammer-request-1", "implementation": "test"}
    assert record.data["schema"] == adapters.HAMMER_EVIDENCE_SCHEMA
    assert record.data["request"]["request_id"] == "hammer-request-1"
    assert record.data["portfolio"]["request_id"] == "hammer-request-1"
    assert record.data["proof_candidate"]["request_id"] == "hammer-request-1"
    assert record.data["reconstruction"]["candidate_id"] == "candidate-1"
    assert record.data["status"] == "candidate"
    assert record.data["reconstruction_kernel_accepted"] is False
    assert record.kernel_accepted is False
    assert contracts.StageRecord.from_dict(record.to_dict()).digest == record.digest


def test_kernel_acceptance_is_only_descriptive_until_kernel_stage() -> None:
    record = _run(_records(accepted=True))

    assert record.data["status"] == "verified"
    assert record.data["reconstruction_kernel_accepted"] is True
    # Hammer is a solver/evidence stage.  It cannot claim final benchmark
    # authority even when its reconstruction record reports kernel acceptance.
    assert record.kernel_accepted is False
    assert record.kernel_receipt_sha256 is None


def test_solver_allowlist_and_named_ranking_variant_are_enforced() -> None:
    payload = _records()
    payload["portfolio"] = replace(
        payload["portfolio"],
        attempts=[replace(payload["portfolio"].attempts[0], solver_name="vampire")],
    )
    unauthorized = _run(payload)
    assert unauthorized.status is contracts.StageStatus.FAILED
    assert unauthorized.failure_code is contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE

    payload = _records()
    payload["request"] = replace(
        payload["request"],
        policy=replace(payload["request"].policy, allow_learned_premise_selector=True),
    )
    wrong_variant = _run(payload)
    assert wrong_variant.status is contracts.StageStatus.FAILED
    assert wrong_variant.failure_code is contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data | {"portfolio": replace(data["portfolio"], request_id="other-request")},
        lambda data: data | {"proof_candidate": replace(data["proof_candidate"], request_id="other-request")},
        lambda data: data | {"reconstruction": replace(data["reconstruction"], candidate_id="other-candidate")},
    ],
)
def test_request_candidate_and_reconstruction_identity_mismatches_fail_closed(mutator) -> None:
    record = _run(mutator(_records()))

    assert record.status is contracts.StageStatus.FAILED
    assert record.failure_code is contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE
    assert record.output_sha256 is None


def test_serialized_records_are_accepted_and_unavailable_backend_stays_explicit() -> None:
    payload = {key: value.to_dict() if hasattr(value, "to_dict") else value for key, value in _records().items()}
    record = _run(payload)
    assert record.status is contracts.StageStatus.SUCCESS

    unavailable = adapters.HammerAdapter().run(
        _benchmark_request(),
        telemetry=contracts.TelemetryRecord(resource_lane=contracts.ResourceLane.SOLVER),
    )
    assert unavailable.status is contracts.StageStatus.UNAVAILABLE
    assert unavailable.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE

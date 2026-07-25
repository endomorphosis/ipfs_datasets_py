"""Focused trust-boundary tests for stable Hammer replay projection."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace

import pytest

from benchmarks.logic_pipeline import report
from benchmarks.logic_pipeline.contracts import (
    CacheMode,
    DEFAULT_PROTOCOL_SHA256,
    FailureCode,
    ProtocolContractError,
    ResourceLane,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from benchmarks.logic_pipeline.hammer_replay import (
    HAMMER_EVIDENCE_SCHEMA,
    HAMMER_PREMISE_SELECTION_SCHEMA,
    HAMMER_TRANSLATED_ENTAILMENT_SCHEMA,
    HAMMER_TRANSLATION_TERMINAL_SCHEMA,
    HammerReplayError,
    project_hammer_data_for_replay,
    project_hammer_premise_selection_for_replay,
    project_hammer_semantic_context_for_replay,
    project_hammer_stage_for_replay,
    validate_hammer_replay_equivalence,
)
from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
from ipfs_datasets_py.logic.hammers.models import (
    EnvironmentLockRecord,
    HammerPolicy,
    HammerRequest,
    HammerResultStatus,
    ITPKind,
    ProofCandidateRecord,
    ReconstructionRecord,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.portfolio import (
    PortfolioRunResult,
    SolverAttemptEvidence,
)
from ipfs_datasets_py.logic.hammers.provenance import (
    EvidenceKind,
    NormalizedEvidence,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _stamp(value: dict[str, object], field: str) -> dict[str, object]:
    body = {key: item for key, item in value.items() if key != field}
    value[field] = hashlib.sha256(
        canonical_json(body).encode("utf-8")
    ).hexdigest()
    return value


def _semantic_binding(tag: str) -> dict[str, object]:
    return {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "semantic-stage-context.v1"
        ),
        "context_sha256": hashlib.sha256(
            f"context-{tag}".encode()
        ).hexdigest(),
        "source_text_sha256": SHA_A,
        "artifact_sha256s": [
            hashlib.sha256(f"spacy-{tag}".encode()).hexdigest(),
            hashlib.sha256(f"symai-{tag}".encode()).hexdigest(),
        ],
    }


def _premise_selection(tag: str) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema": HAMMER_PREMISE_SELECTION_SCHEMA,
        "policy": "symai_llm",
        "ranking_contract": "hssl-symai-semantic-overlap-v1",
        "translation_sha256": SHA_B,
        "source_sha256": SHA_C,
        "obligation_sha256": SHA_D,
        "candidate_set_sha256": SHA_E,
        "candidate_count": 2,
        "top_k": 2,
        "symai_invoked": True,
        "symai_artifact_sha256": hashlib.sha256(
            f"symai-artifact-{tag}".encode()
        ).hexdigest(),
        "symai_output_sha256": hashlib.sha256(
            f"symai-output-{tag}".encode()
        ).hexdigest(),
        "symai_identity_sha256": SHA_F,
        "semantic_signal_sha256": SHA_A,
        "semantic_term_count": 3,
        "selected": [
            {
                "premise_id": "premise-alpha",
                "rank": 0,
                "overlap_count": 2,
                "overlap_basis_points": 5000,
                "source_index": 0,
                "statement_sha256": SHA_B,
            },
            {
                "premise_id": "premise-beta",
                "rank": 1,
                "overlap_count": 1,
                "overlap_basis_points": 2500,
                "source_index": 1,
                "statement_sha256": SHA_C,
            },
        ],
    }
    return _stamp(receipt, "receipt_sha256")


def _direct_payload(tag: str = "one") -> dict[str, object]:
    proof = "exact rule scope_witness"
    return {
        "schema": HAMMER_TRANSLATED_ENTAILMENT_SCHEMA,
        "case_input_sha256": SHA_A,
        "translation_status": "success",
        "translation_sha256": SHA_B,
        "translation_shape": "quantified_provider",
        "source_sha256": SHA_C,
        "obligation_sha256": SHA_D,
        "solver_status": "unsat",
        "solver_command_sha256": SHA_E,
        "solver_input_sha256": SHA_F,
        "stdout_sha256": SHA_A,
        "stderr_sha256": SHA_B,
        "returncode": 0,
        "timed_out": False,
        "process_group_reaped": True,
        "termination_reason": "completed",
        "proof_success": True,
        "proof_text": proof,
        "candidate_created": True,
        "native_reconstruction": {
            "strategy": "quantified_provider",
            "certificate_sha256": hashlib.sha256(proof.encode()).hexdigest(),
            "authoritative": False,
            "requires_independent_kernel": True,
        },
        "efficacy_observed": False,
        "semantic_context": _semantic_binding(tag),
        "premise_selection": _premise_selection(tag),
    }


def _terminal_payload(tag: str) -> dict[str, object]:
    return {
        "schema": HAMMER_TRANSLATION_TERMINAL_SCHEMA,
        "case_input_sha256": SHA_A,
        "translation_status": "unsupported",
        "solver_status": "not_invoked",
        "candidate_created": False,
        "efficacy_observed": False,
        "reason": "reviewed_source_not_in_sound_translation_subset",
        "semantic_context": _semantic_binding(tag),
    }


def _failed_direct_payload(tag: str = "failed") -> dict[str, object]:
    payload = _direct_payload(tag)
    payload.update(
        {
            "solver_status": "inconclusive",
            "returncode": 1,
            "termination_reason": "nonzero_exit",
            "proof_success": False,
            "proof_text": None,
            "candidate_created": False,
            "native_reconstruction": None,
        }
    )
    return payload


def _direct_stage_identity(
    payload: dict[str, object],
) -> dict[str, object]:
    semantic = payload["semantic_context"]
    premise = payload.get("premise_selection")
    assert isinstance(semantic, dict)
    identity: dict[str, object] = {
        "implementation": "native-hammer",
        "semantic_context_sha256": semantic["context_sha256"],
    }
    if premise is not None:
        assert isinstance(premise, dict)
        identity.update(
            {
                "premise_selection_sha256": premise["receipt_sha256"],
                "premise_ranking_contract": premise[
                    "ranking_contract"
                ],
            }
        )
    return identity


def _full_stage_identity(
    payload: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    request = payload["request"]
    assert isinstance(request, dict)
    request_id = request["request_id"]
    identity = {
        "request_id": request_id,
        "hammer_request_id": request_id,
        "implementation": "native-hammer",
    }
    return dict(identity), dict(identity)


def _full_payload(
    tag: str,
    *,
    accepted: bool = True,
    environment_version: str = "lean-4.19.0",
    certificate: str = "solver certificate",
) -> dict[str, object]:
    moment = datetime(2026, 7, 25, tzinfo=timezone.utc) + timedelta(
        seconds=1 if tag == "two" else 0
    )
    request_id = f"request-{tag}"
    translation_id = f"translation-{tag}"
    attempt_id = f"{request_id}:{translation_id}:z3:0"
    candidate_id = f"candidate-{tag}"

    policy = HammerPolicy(
        timeout_seconds=5.0,
        cpu_seconds=4.0,
        memory_mb=256,
        allowed_solvers=["z3"],
    )
    request = HammerRequest(
        request_id=request_id,
        itp=ITPKind.LEAN,
        theorem_id="identity-theorem",
        goal_statement="forall n, n = n",
        corpus_revision="corpus-revision-pinned",
        policy=policy,
        created_at=moment,
        metadata={"suite": "stable-replay-test"},
    )
    raw_stdout = "unsat\n"
    raw_stderr = ""
    raw_output_digest = compute_content_digest(
        {"stdout": raw_stdout, "stderr": raw_stderr}
    )
    attempt = SolverAttemptRecord(
        attempt_id=attempt_id,
        request_id=request_id,
        translation_id=translation_id,
        solver_name="z3",
        solver_version="Z3 4.13.3",
        target=TranslationTarget.SMTLIB,
        timeout_seconds=5.0,
        verdict=SolverVerdict.UNSAT,
        exit_code=0,
        wall_time_seconds=0.1 if tag == "one" else 0.2,
        raw_output_digest=raw_output_digest,
        started_at=moment,
        finished_at=moment + timedelta(milliseconds=100),
        resource_usage={
            "cpu_seconds": 0.05 if tag == "one" else 0.1,
            "max_rss_mb": 32 if tag == "one" else 34,
            "global_lease_wait_seconds": 0.01 if tag == "one" else 0.02,
            "global_lease_cpu_slots": 1,
            "global_lease_memory_mb": 256,
        },
        network_used=False,
    )
    input_name = hashlib.sha256(attempt_id.encode()).hexdigest()[:32] + ".smt2"
    attempt_evidence = SolverAttemptEvidence(
        attempt_id=attempt_id,
        command=[
            "/usr/bin/z3",
            "-T:5",
            f"/tmp/itp_hammer_portfolio_{tag}/{input_name}",
        ],
        input_digest=compute_content_digest(
            {
                "solver_name": "z3",
                "target": "smtlib",
                "text": "(assert true)\n(check-sat)\n(exit)\n",
            }
        ),
        raw_stdout=raw_stdout,
        raw_stderr=raw_stderr,
        solver_trace="unsat",
    )
    portfolio = PortfolioRunResult(
        request_id=request_id,
        attempts=[attempt],
        evidence={attempt_id: attempt_evidence},
        denied=[],
        cancelled_attempt_ids=[],
        resource_telemetry={
            "lane": "hammer_lean",
            "portfolio_cpu_slots": 1,
            "portfolio_memory_mb": 256,
            "wait_time_seconds_before": 0.1 if tag == "one" else 0.3,
            "scheduler": {"sample": tag},
        },
    )
    candidate = ProofCandidateRecord(
        candidate_id=candidate_id,
        request_id=request_id,
        solver_attempt_id=attempt_id,
        premise_ids=["premise-alpha"],
        certificate=certificate,
        certificate_format="smtlib",
    )
    normalized = NormalizedEvidence(
        request_id=request_id,
        attempt_id=attempt_id,
        candidate_id=candidate_id,
        kind=EvidenceKind.ABSENT,
        format="smtlib",
        verdict=SolverVerdict.UNSAT,
        premise_ids=["premise-alpha"],
        translation_ids=[translation_id],
        raw_trace_digest=raw_output_digest,
        recommended_status=HammerResultStatus.CANDIDATE,
    )
    policy_digest = compute_content_digest(policy.to_dict())
    environment_payload = {
        "itp": ITPKind.LEAN.value,
        "itp_version": environment_version,
        "kernel_command_template": "lean --json {proof_file}",
        "solver_versions": {"z3": "Z3 4.13.3"},
        "executable_paths": {
            "lean": "/usr/bin/lean",
            "z3": "/usr/bin/z3",
        },
        "os_info": "Linux test-host",
        "container_digest": "sha256:" + SHA_A,
        "policy_digest": policy_digest,
    }
    environment_id = compute_content_digest(environment_payload)
    environment = EnvironmentLockRecord(
        lock_id=environment_id,
        itp=ITPKind.LEAN,
        itp_version=environment_version,
        kernel_command_template="lean --json {proof_file}",
        solver_versions={"z3": "Z3 4.13.3"},
        executable_paths={"lean": "/usr/bin/lean", "z3": "/usr/bin/z3"},
        os_info="Linux test-host",
        container_digest="sha256:" + SHA_A,
        pinned_at=moment,
        policy_digest=policy_digest,
    )
    reconstruction = ReconstructionRecord(
        reconstruction_id=f"reconstruction-{tag}",
        request_id=request_id,
        candidate_id=candidate_id,
        target_itp=ITPKind.LEAN,
        environment_lock_id=environment_id,
        kernel_command=(
            f"/usr/bin/lean --json "
            f"/tmp/hammer-lean-recon-{tag}/Reconstruction.lean"
        ),
        kernel_accepted=accepted,
        kernel_output_digest=compute_content_digest(
            {"stdout": "accepted" if accepted else "rejected"}
        ),
        started_at=moment,
        finished_at=moment + timedelta(milliseconds=50),
        failure_reason=None if accepted else "kernel rejected candidate",
    )
    record_payload: dict[str, object] = {
        "request": request.to_dict(),
        "portfolio": portfolio.to_dict(),
        "normalized_evidence": {attempt_id: normalized.to_dict()},
        "proof_candidate": candidate.to_dict(),
        "reconstruction": reconstruction.to_dict(),
        "environment_lock": environment.to_dict(),
        "reconstruction_kernel_accepted": accepted,
        "status": "verified" if accepted else "candidate",
    }
    outer: dict[str, object] = {
        "schema": HAMMER_EVIDENCE_SCHEMA,
        **record_payload,
    }
    evidence_id = hashlib.sha256(
        canonical_json(outer).encode("utf-8")
    ).hexdigest()
    return {
        "schema": HAMMER_EVIDENCE_SCHEMA,
        "evidence_id": evidence_id,
        **record_payload,
    }


def _restamp_outer(value: dict[str, object]) -> dict[str, object]:
    body = {key: item for key, item in value.items() if key != "evidence_id"}
    value["evidence_id"] = hashlib.sha256(
        canonical_json(body).encode("utf-8")
    ).hexdigest()
    return value


def _restamp_environment(value: dict[str, object]) -> dict[str, object]:
    environment = value["environment_lock"]
    reconstruction = value["reconstruction"]
    assert isinstance(environment, dict)
    assert isinstance(reconstruction, dict)
    lock_payload = {
        key: environment[key]
        for key in (
            "itp",
            "itp_version",
            "kernel_command_template",
            "solver_versions",
            "executable_paths",
            "os_info",
            "container_digest",
            "policy_digest",
        )
    }
    lock_id = compute_content_digest(lock_payload)
    environment["lock_id"] = lock_id
    reconstruction["environment_lock_id"] = lock_id
    return _restamp_outer(value)


def _full_process_failure_payload(
    tag: str,
    *,
    kind: str,
) -> dict[str, object]:
    value = deepcopy(_full_payload(tag, accepted=False))
    portfolio = value["portfolio"]
    normalized_by_attempt = value["normalized_evidence"]
    assert isinstance(portfolio, dict)
    assert isinstance(normalized_by_attempt, dict)
    attempts = portfolio["attempts"]
    assert isinstance(attempts, list) and len(attempts) == 1
    attempt = attempts[0]
    assert isinstance(attempt, dict)
    attempt_id = attempt["attempt_id"]
    normalized = normalized_by_attempt[attempt_id]
    assert isinstance(normalized, dict)

    attempt["wall_time_seconds"] = 5.0 if kind == "timeout" else 0.1
    if kind == "timeout":
        attempt.update({"verdict": "timeout", "exit_code": -15})
    elif kind == "signal":
        attempt.update({"verdict": "error", "exit_code": -11})
    elif kind == "nonzero":
        attempt.update({"verdict": "error", "exit_code": 2})
    elif kind == "cancelled":
        attempt.update({"verdict": "unknown", "exit_code": None})
        resource_usage = attempt["resource_usage"]
        assert isinstance(resource_usage, dict)
        resource_usage["cancelled"] = True
        portfolio["cancelled_attempt_ids"] = [attempt_id]
    else:  # pragma: no cover - helper is private to fixed test parameters.
        raise AssertionError(f"unsupported full failure kind: {kind}")

    normalized.update(
        {
            "candidate_id": None,
            "verdict": attempt["verdict"],
            "recommended_status": "unknown",
        }
    )
    normalized_body = {
        key: item
        for key, item in normalized.items()
        if key not in {"evidence_id", "content_digest"}
    }
    normalized_digest = compute_content_digest(normalized_body)
    normalized["evidence_id"] = normalized_digest
    normalized["content_digest"] = normalized_digest
    value.update(
        {
            "proof_candidate": None,
            "reconstruction": None,
            "environment_lock": None,
            "reconstruction_kernel_accepted": False,
            "status": "unknown",
        }
    )
    return _restamp_outer(value)


def _stage_record(
    data: dict[str, object],
    *,
    stage: StageName,
    run_id: str,
    effective_identity: dict[str, object],
    requested_identity: dict[str, object] | None = None,
    status: StageStatus = StageStatus.SUCCESS,
    failure_code: FailureCode | None = None,
) -> StageRecord:
    return StageRecord(
        schema=(
            "ipfs-datasets.logic-pipeline-benchmark.stage-record.v1"
        ),
        protocol_sha256=DEFAULT_PROTOCOL_SHA256,
        run_id=run_id,
        case_id="hammer-replay-case",
        case_manifest_sha256=SHA_A,
        variant_id="A11",
        split=Split.PILOT,
        cache_mode=CacheMode.COLD,
        stage=stage,
        adapter_version="1",
        status=status,
        provenance=StageProvenance(
            schema=(
                "ipfs-datasets.logic-pipeline-benchmark."
                "stage-provenance.v1"
            ),
            adapter_id=f"{stage.value}-adapter",
            adapter_version="1",
            source=("tests.hammer_replay",),
            requested_identity=(
                {}
                if requested_identity is None
                else requested_identity
            ),
            effective_identity=effective_identity,
            input_sha256=SHA_B,
            environment_sha256=SHA_C,
        ),
        telemetry=TelemetryRecord(resource_lane=ResourceLane.SOLVER),
        data=data,
        output_sha256=(
            hashlib.sha256(
                canonical_json(data).encode("utf-8")
            ).hexdigest()
            if status is StageStatus.SUCCESS
            else None
        ),
        failure_code=failure_code,
        failure_detail=(
            None
            if failure_code is None
            else "synthetic Hammer process failure"
        ),
    )


def _bound_graph_stages(
    *,
    drift: str | None = None,
) -> tuple[StageRecord, StageRecord]:
    symai_identity: dict[str, object] = {
        "provider": "llm_router",
        "model": "Leanstral-119B",
        "effective_provider": "llm_router",
        "effective_model": "Leanstral-119B",
        "graph_invocation_index": 0,
        "graph_invoked": True,
        "graph_policy_reason": "ambiguity_gate_open",
        "consumed_artifact_sha256": [],
    }
    symai = _stage_record(
        {
            "schema": (
                "ipfs-datasets.logic-pipeline-benchmark."
                "symai-evidence.v1"
            ),
            "candidate_ir": {"proposition": "P"},
        },
        stage=StageName.SYMAI,
        run_id="symai-graph-run",
        effective_identity=symai_identity,
    )
    symai_artifact = report._stage_artifact_digest_from_record(
        symai,
        invocation_index=0,
        invoked=True,
        policy_reason="ambiguity_gate_open",
    )
    symai_backend = {
        key: symai_identity[key]
        for key in (
            "provider",
            "model",
            "effective_provider",
            "effective_model",
        )
    }
    premise = _premise_selection("bound")
    premise["symai_artifact_sha256"] = symai_artifact
    premise["symai_output_sha256"] = symai.output_sha256
    premise["symai_identity_sha256"] = hashlib.sha256(
        canonical_json(symai_backend).encode("utf-8")
    ).hexdigest()
    if drift == "artifact":
        premise["symai_artifact_sha256"] = SHA_F
    elif drift == "output":
        premise["symai_output_sha256"] = SHA_F
    elif drift == "identity":
        premise["symai_identity_sha256"] = SHA_F
    elif drift == "invoked":
        premise["symai_invoked"] = False
        premise["symai_output_sha256"] = None
        premise["ranking_contract"] = (
            "ambiguity-gate-closed-source-order-v1"
        )
    _stamp(premise, "receipt_sha256")
    context = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "semantic-stage-context.v1"
        ),
        "context_sha256": SHA_D,
        "source_text_sha256": SHA_A,
        "artifact_sha256s": [symai_artifact],
    }
    data = _direct_payload()
    data["semantic_context"] = context
    data["premise_selection"] = premise
    hammer_identity: dict[str, object] = {
        "implementation": "test-hammer",
        "semantic_context_sha256": context["context_sha256"],
        "premise_selection_sha256": premise["receipt_sha256"],
        "premise_ranking_contract": premise["ranking_contract"],
        "graph_invocation_index": 1,
        "graph_invoked": True,
        "graph_policy_reason": "always",
        "consumed_artifact_sha256": [symai_artifact],
    }
    if drift == "ranking_identity":
        hammer_identity["premise_ranking_contract"] = "different-contract"
    hammer = _stage_record(
        data,
        stage=StageName.HAMMER,
        run_id="hammer-graph-run",
        effective_identity=hammer_identity,
    )
    return symai, hammer


def test_direct_receipts_normalize_only_upstream_addresses() -> None:
    validate_hammer_replay_equivalence(
        _direct_payload("one"),
        _direct_payload("two"),
    )
    validate_hammer_replay_equivalence(
        _terminal_payload("one"),
        _terminal_payload("two"),
    )

    projection = project_hammer_data_for_replay(_direct_payload())
    assert projection["semantic_context"]["artifact_bindings"] == [
        "@semantic-artifact-000",
        "@semantic-artifact-001",
    ]
    assert (
        "symai_artifact_sha256"
        not in projection["premise_selection"]
    )
    assert "receipt_sha256" not in projection["premise_selection"]


def test_failed_hammer_stage_uses_the_same_strict_replay_projection() -> None:
    payload = _failed_direct_payload()
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id="failed-hammer-replay",
        effective_identity=_direct_stage_identity(payload),
        status=StageStatus.FAILED,
        failure_code=(
            FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE
        ),
    )

    direct = project_hammer_stage_for_replay(stage)
    through_report = report._stable_stage_replay_projection(stage)

    assert through_report["data"] == direct["data"]
    assert through_report["data"]["returncode"] == 1
    assert (
        through_report["data"]["termination_reason"]
        == "nonzero_exit"
    )


def test_failed_hammer_stage_rejects_outer_failure_code_mismatch() -> None:
    payload = _failed_direct_payload()
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id="failed-hammer-wrong-code",
        effective_identity=_direct_stage_identity(payload),
        status=StageStatus.FAILED,
        failure_code=FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
    )

    with pytest.raises(HammerReplayError, match="process outcome"):
        report._stable_stage_replay_projection(stage)


def test_failed_hammer_stage_rejects_malformed_process_evidence() -> None:
    payload = _failed_direct_payload()
    payload["returncode"] = "one"
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id="failed-hammer-malformed",
        effective_identity=_direct_stage_identity(payload),
        status=StageStatus.FAILED,
        failure_code=(
            FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE
        ),
    )

    with pytest.raises(HammerReplayError, match="returncode"):
        report._stable_stage_replay_projection(stage)


def test_hammer_terminal_receipt_cannot_be_restamped_as_a_failure() -> None:
    payload = _terminal_payload("failed-terminal")
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id="failed-hammer-terminal",
        effective_identity=_direct_stage_identity(payload),
        status=StageStatus.FAILED,
        failure_code=FailureCode.TRANSLATION_UNSUPPORTED,
    )

    with pytest.raises(
        HammerReplayError,
        match="must remain a successful typed terminal outcome",
    ):
        report._stable_stage_replay_projection(stage)


def test_failed_full_hammer_stage_binds_reconstruction_failure() -> None:
    payload = _full_payload("failed-full-reconstruction", accepted=False)
    effective, requested = _full_stage_identity(payload)
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id="failed-full-hammer-reconstruction",
        effective_identity=effective,
        requested_identity=requested,
        status=StageStatus.FAILED,
        failure_code=FailureCode.RECONSTRUCTION_FAILURE,
    )

    direct = project_hammer_stage_for_replay(stage)
    through_report = report._stable_stage_replay_projection(stage)

    assert through_report["data"] == direct["data"]
    assert through_report["data"]["status"] == "candidate"
    assert (
        through_report["data"]["reconstruction"]["kernel_accepted"]
        is False
    )


@pytest.mark.parametrize(
    "failure_code",
    (
        FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE,
        FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        FailureCode.ORPHANED_CHILD,
    ),
)
def test_failed_full_hammer_stage_rejects_unattested_failure_codes(
    failure_code: FailureCode,
) -> None:
    payload = _full_payload("failed-full-mismatch", accepted=False)
    effective, requested = _full_stage_identity(payload)
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id="failed-full-hammer-mismatch",
        effective_identity=effective,
        requested_identity=requested,
        status=StageStatus.FAILED,
        failure_code=failure_code,
    )

    with pytest.raises(HammerReplayError, match="native records"):
        report._stable_stage_replay_projection(stage)


@pytest.mark.parametrize(
    ("kind", "failure_code"),
    (
        (
            "timeout",
            FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE,
        ),
        (
            "nonzero",
            FailureCode.SOLVER_TIMEOUT_ERROR_OR_INCONCLUSIVE,
        ),
        (
            "signal",
            FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        ),
        (
            "cancelled",
            FailureCode.RESOURCE_LEASE_CANCELLATION,
        ),
    ),
)
def test_failed_full_hammer_process_outcomes_bind_outer_failure(
    kind: str,
    failure_code: FailureCode,
) -> None:
    payload = _full_process_failure_payload(
        f"failed-full-{kind}",
        kind=kind,
    )
    effective, requested = _full_stage_identity(payload)
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id=f"failed-full-hammer-{kind}",
        effective_identity=effective,
        requested_identity=requested,
        status=StageStatus.FAILED,
        failure_code=failure_code,
    )

    projection = report._stable_stage_replay_projection(stage)

    assert projection["data"]["status"] == "unknown"
    assert projection["data"]["proof_candidate"] is None
    assert projection["data"]["reconstruction"] is None


@pytest.mark.parametrize("accepted", (False, True))
def test_full_hammer_success_stage_projection_does_not_regress(
    accepted: bool,
) -> None:
    payload = _full_payload(
        f"full-success-{accepted}",
        accepted=accepted,
    )
    effective, requested = _full_stage_identity(payload)
    stage = _stage_record(
        payload,
        stage=StageName.HAMMER,
        run_id=f"full-success-hammer-{accepted}",
        effective_identity=effective,
        requested_identity=requested,
    )

    projection = report._stable_stage_replay_projection(stage)

    assert projection["data"]["reconstruction_kernel_accepted"] is accepted
    assert projection["data"]["status"] == (
        "verified" if accepted else "candidate"
    )


@pytest.mark.parametrize(
    "field,new_value",
    [
        ("solver_command_sha256", SHA_A),
        ("source_sha256", SHA_D),
        ("proof_text", "exact another_rule"),
    ],
)
def test_direct_solver_semantic_and_certificate_drift_reject(
    field: str,
    new_value: object,
) -> None:
    original = _direct_payload()
    replayed = _direct_payload()
    replayed[field] = new_value
    if field == "proof_text":
        replayed["native_reconstruction"]["certificate_sha256"] = (
            hashlib.sha256(str(new_value).encode()).hexdigest()
        )
    with pytest.raises(HammerReplayError):
        validate_hammer_replay_equivalence(original, replayed)


@pytest.mark.parametrize(
    ("returncode", "timed_out", "reaped", "termination_reason"),
    (
        (-11, False, True, "completed"),
        (2, False, True, "completed"),
        (0, True, True, "completed"),
        (0, False, False, "completed"),
    ),
)
def test_direct_process_lifecycle_forgery_rejects(
    returncode: int,
    timed_out: bool,
    reaped: bool,
    termination_reason: str,
) -> None:
    value = _direct_payload()
    value.update(
        {
            "returncode": returncode,
            "timed_out": timed_out,
            "process_group_reaped": reaped,
            "termination_reason": termination_reason,
        }
    )

    with pytest.raises(HammerReplayError, match="termination"):
        project_hammer_data_for_replay(value)


def test_direct_signal_failure_retains_typed_process_evidence() -> None:
    value = _direct_payload()
    value.update(
        {
            "solver_status": "inconclusive",
            "returncode": -11,
            "termination_reason": "signal_exit",
            "proof_success": False,
            "proof_text": None,
            "candidate_created": False,
            "native_reconstruction": None,
        }
    )

    projection = project_hammer_data_for_replay(value)

    assert projection["returncode"] == -11
    assert projection["termination_reason"] == "signal_exit"
    assert projection["candidate_created"] is False


def test_context_and_premise_receipts_fail_closed() -> None:
    context = _semantic_binding("one")
    context["surprise"] = True
    with pytest.raises(HammerReplayError, match="unexpected schema"):
        project_hammer_semantic_context_for_replay(context)

    premise = _premise_selection("one")
    premise["semantic_term_count"] = 99
    with pytest.raises(HammerReplayError, match="does not match"):
        project_hammer_premise_selection_for_replay(premise)


def test_full_evidence_normalizes_relational_ids_and_operational_observations() -> None:
    first = project_hammer_data_for_replay(_full_payload("one"))
    second = project_hammer_data_for_replay(_full_payload("two"))

    assert first == second
    assert first["request"]["request_id"] == "@request"
    assert first["portfolio"]["attempts"][0]["attempt_id"] == "@attempt-000"
    assert (
        first["portfolio"]["evidence"]["@attempt-000"]["command"][-1]
        == "<HAMMER_INPUT>"
    )
    assert first["proof_candidate"]["candidate_id"] == "@candidate"
    assert first["environment_lock"]["lock_id"] == "@environment"
    assert first["reconstruction"]["reconstruction_id"] == "@reconstruction"
    assert "started_at" not in first["reconstruction"]


@pytest.mark.parametrize(
    "changed",
    [
        {"environment_version": "lean-4.20.0"},
        {"certificate": "different solver certificate"},
        {"accepted": False},
    ],
)
def test_full_environment_certificate_and_reconstruction_drift_reject(
    changed: dict[str, object],
) -> None:
    with pytest.raises(HammerReplayError, match="replay drifted"):
        validate_hammer_replay_equivalence(
            _full_payload("one"),
            _full_payload("two", **changed),
        )


def test_full_evidence_rejects_unknown_fields_and_broken_joins() -> None:
    unknown = _full_payload("one")
    unknown["unexpected"] = "not projected away"
    _restamp_outer(unknown)
    with pytest.raises(HammerReplayError, match="unknown"):
        project_hammer_data_for_replay(unknown)

    broken = _full_payload("one")
    broken["proof_candidate"]["request_id"] = "different-request"
    _restamp_outer(broken)
    with pytest.raises(HammerReplayError, match="another request"):
        project_hammer_data_for_replay(broken)

    corrupt = deepcopy(_full_payload("one"))
    normalized = next(iter(corrupt["normalized_evidence"].values()))
    normalized["content_digest"] = "0" * 64
    _restamp_outer(corrupt)
    with pytest.raises(HammerReplayError, match="content address"):
        project_hammer_data_for_replay(corrupt)


def test_full_stage_report_projection_normalizes_bound_request_ids() -> None:
    first_data = _full_payload("one")
    second_data = _full_payload("two")
    first_request = first_data["request"]["request_id"]
    second_request = second_data["request"]["request_id"]
    first = _stage_record(
        first_data,
        stage=StageName.HAMMER,
        run_id="full-hammer-one",
        effective_identity={
            "request_id": first_request,
            "hammer_request_id": first_request,
            "implementation": "native-hammer",
        },
        requested_identity={
            "request_id": first_request,
            "hammer_request_id": first_request,
            "implementation": "native-hammer",
        },
    )
    second = _stage_record(
        second_data,
        stage=StageName.HAMMER,
        run_id="full-hammer-two",
        effective_identity={
            "request_id": second_request,
            "hammer_request_id": second_request,
            "implementation": "native-hammer",
        },
        requested_identity={
            "request_id": second_request,
            "hammer_request_id": second_request,
            "implementation": "native-hammer",
        },
    )

    first_projection = report._stable_stage_replay_projection(first)
    second_projection = report._stable_stage_replay_projection(second)
    assert first_projection == second_projection
    assert first_projection["effective_identity"]["request_id"] == "@request"
    assert first_projection["requested_identity"]["request_id"] == "@request"

    cross_bound = _stage_record(
        first_data,
        stage=StageName.HAMMER,
        run_id="full-hammer-cross-bound",
        effective_identity={"request_id": "another-request"},
        requested_identity={"request_id": first_request},
    )
    with pytest.raises(HammerReplayError, match="cross-bound"):
        project_hammer_stage_for_replay(cross_bound)


@pytest.mark.parametrize(
    "drift",
    ("artifact", "output", "identity", "invoked", "ranking_identity"),
)
def test_report_graph_rejects_cross_bound_a11_premise_receipts(
    drift: str,
) -> None:
    valid = _bound_graph_stages()
    report._validate_result_graph_bindings(
        SimpleNamespace(stages=valid)
    )

    invalid = _bound_graph_stages(drift=drift)
    with pytest.raises(ProtocolContractError):
        report._validate_result_graph_bindings(
            SimpleNamespace(stages=invalid)
        )


def test_report_rejects_a11_projection_without_an_auditable_graph() -> None:
    _symai, graph_hammer = _bound_graph_stages()
    data = graph_hammer.to_dict()["data"]
    identity = {
        "premise_selection_sha256": data["premise_selection"][
            "receipt_sha256"
        ],
        "premise_ranking_contract": data["premise_selection"][
            "ranking_contract"
        ],
        "semantic_context_sha256": data["semantic_context"][
            "context_sha256"
        ],
    }
    legacy_hammer = _stage_record(
        data,
        stage=StageName.HAMMER,
        run_id="legacy-a11-no-graph",
        effective_identity=identity,
    )
    with pytest.raises(ProtocolContractError, match="graph-bound"):
        report._validate_result_graph_bindings(
            SimpleNamespace(stages=(legacy_hammer,))
        )


@pytest.mark.parametrize(
    "corruption",
    (
        "policy_digest",
        "lock_id",
        "input_digest",
        "raw_stdout",
        "solver_trace",
        "short_argv",
    ),
)
def test_full_native_environment_and_solver_evidence_forgery_rejects(
    corruption: str,
) -> None:
    value = deepcopy(_full_payload("one"))
    attempt_id = next(iter(value["portfolio"]["evidence"]))
    evidence = value["portfolio"]["evidence"][attempt_id]
    if corruption == "policy_digest":
        value["environment_lock"]["policy_digest"] = (
            compute_content_digest({"different": "policy"})
        )
    elif corruption == "lock_id":
        forged = compute_content_digest({"forged": "environment"})
        value["environment_lock"]["lock_id"] = forged
        value["reconstruction"]["environment_lock_id"] = forged
    elif corruption == "input_digest":
        evidence["input_digest"] = "not-a-content-address"
    elif corruption == "raw_stdout":
        evidence["raw_stdout"] = 7
    elif corruption == "solver_trace":
        evidence["solver_trace"] = {"unexpected": True}
    else:
        evidence["command"] = ["/usr/bin/z3"]
    _restamp_outer(value)

    with pytest.raises(HammerReplayError):
        project_hammer_data_for_replay(value)


@pytest.mark.parametrize(
    "corruption",
    (
        "missing_solver_version",
        "missing_solver_path",
        "kernel_command_template",
        "kernel_output_digest",
        "container_digest",
    ),
)
def test_full_native_replay_requires_complete_content_addressed_lock_bindings(
    corruption: str,
) -> None:
    value = deepcopy(_full_payload("one"))
    environment = value["environment_lock"]
    reconstruction = value["reconstruction"]
    assert isinstance(environment, dict)
    assert isinstance(reconstruction, dict)
    if corruption == "missing_solver_version":
        solver_versions = environment["solver_versions"]
        assert isinstance(solver_versions, dict)
        solver_versions.pop("z3")
        _restamp_environment(value)
    elif corruption == "missing_solver_path":
        executable_paths = environment["executable_paths"]
        assert isinstance(executable_paths, dict)
        executable_paths.pop("z3")
        _restamp_environment(value)
    elif corruption == "kernel_command_template":
        environment["kernel_command_template"] = (
            "lean --evil {proof_file}"
        )
        _restamp_environment(value)
    elif corruption == "kernel_output_digest":
        reconstruction["kernel_output_digest"] = "latest"
        _restamp_outer(value)
    else:
        environment["container_digest"] = "latest"
        _restamp_environment(value)

    with pytest.raises(HammerReplayError):
        project_hammer_data_for_replay(value)


def test_direct_solver_status_and_whitespace_proof_fail_closed() -> None:
    unknown_status = _direct_payload()
    unknown_status["solver_status"] = "probably"
    with pytest.raises(HammerReplayError, match="solver_status"):
        project_hammer_data_for_replay(unknown_status)

    whitespace_proof = _direct_payload()
    whitespace_proof["proof_text"] = "   "
    whitespace_proof["native_reconstruction"]["certificate_sha256"] = (
        hashlib.sha256(b"   ").hexdigest()
    )
    with pytest.raises(HammerReplayError, match="candidate"):
        project_hammer_data_for_replay(whitespace_proof)

"""Integration evidence for kernel- and provenance-bound case results."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json

import pytest

from benchmarks.logic_pipeline import contracts, metrics, report
from benchmarks.logic_pipeline import matrix_reassessment


SHA_MANIFEST = "a" * 64
SHA_ENVIRONMENT = "b" * 64
SHA_RECEIPT = "c" * 64
SHA_OTHER = "d" * 64
SHA_INPUT = "e" * 64

ROUTE = tuple(contracts.StageName)
LANES = {
    contracts.StageName.COMPILER: contracts.ResourceLane.CPU,
    contracts.StageName.SPACY: contracts.ResourceLane.CPU,
    contracts.StageName.SYMAI: contracts.ResourceLane.MODEL,
    contracts.StageName.HAMMER: contracts.ResourceLane.SOLVER,
    contracts.StageName.LEANSTRAL: contracts.ResourceLane.MODEL,
    contracts.StageName.KERNEL: contracts.ResourceLane.KERNEL,
}


def _hammer_payload() -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "ipfs-datasets.logic-pipeline-benchmark.hammer-evidence.v1",
        "request": {"request_id": "request-1"},
        "portfolio": {"request_id": "request-1"},
        "normalized_evidence": {},
        "proof_candidate": {
            "request_id": "request-1",
            "candidate_id": "candidate-1",
        },
        "reconstruction": {
            "request_id": "request-1",
            "candidate_id": "candidate-1",
            "environment_lock_id": "environment-1",
            "kernel_accepted": True,
        },
        "environment_lock": {"lock_id": "environment-1"},
        "reconstruction_kernel_accepted": True,
        "status": "verified",
    }
    evidence_id = hashlib.sha256(
        contracts.canonical_json(body).encode("utf-8")
    ).hexdigest()
    return {"evidence_id": evidence_id, **body}


def _native_kernel_receipt(
    *,
    case_id: str,
    environment_sha256: str,
    accepted: bool,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema": contracts.NATIVE_KERNEL_RECEIPT_SCHEMA,
        "protocol_sha256": contracts.DEFAULT_PROTOCOL_SHA256,
        "run_id": "run-001",
        "case_id": case_id,
        "case_manifest_sha256": SHA_MANIFEST,
        "variant_id": "A4",
        "split": contracts.Split.PILOT.value,
        "cache_mode": contracts.CacheMode.COLD.value,
        "input_sha256": SHA_INPUT,
        "environment_sha256": environment_sha256,
        "independent": True,
        "accepted": accepted,
        "active_process_count": 0,
    }
    if accepted:
        attempt_body = {
            "attempt_index": 0,
            "candidate_source": contracts.StageName.COMPILER.value,
            "candidate_artifact_sha256": SHA_OTHER,
            "source_sha256": hashlib.sha256(b"source").hexdigest(),
            "command_sha256": hashlib.sha256(b"command").hexdigest(),
            "stdout_sha256": hashlib.sha256(b"stdout").hexdigest(),
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "returncode": 0,
            "timed_out": False,
            "cancelled": False,
            "resource_exhausted": False,
            "termination_reason": "completed",
            "process_group_reaped": True,
            "active_process_count": 0,
            "accepted": True,
        }
        attempt = {
            **attempt_body,
            "attempt_sha256": hashlib.sha256(
                contracts.canonical_json(attempt_body).encode("utf-8")
            ).hexdigest(),
        }
        body.update(
            {
                "compiled_obligation_sha256": hashlib.sha256(
                    b"compiled"
                ).hexdigest(),
                "obligation_sha256": hashlib.sha256(
                    b"obligation"
                ).hexdigest(),
                "candidate_source": attempt["candidate_source"],
                "candidate_artifact_sha256": attempt[
                    "candidate_artifact_sha256"
                ],
                "source_sha256": attempt["source_sha256"],
                "semantic_context_sha256": hashlib.sha256(
                    b"semantic-context"
                ).hexdigest(),
                "semantic_artifact_sha256s": [SHA_OTHER],
                "command_sha256": attempt["command_sha256"],
                "stdout_sha256": attempt["stdout_sha256"],
                "stderr_sha256": attempt["stderr_sha256"],
                "returncode": attempt["returncode"],
                "timed_out": attempt["timed_out"],
                "cancelled": attempt["cancelled"],
                "resource_exhausted": attempt["resource_exhausted"],
                "termination_reason": attempt["termination_reason"],
                "process_group_reaped": attempt["process_group_reaped"],
                "candidate_attempts": [attempt],
                "candidate_attempts_sha256": hashlib.sha256(
                    contracts.canonical_json([attempt]).encode("utf-8")
                ).hexdigest(),
                "selected_attempt": {
                    key: attempt[key]
                    for key in (
                        "attempt_index",
                        "candidate_source",
                        "candidate_artifact_sha256",
                        "attempt_sha256",
                        "accepted",
                    )
                },
            }
        )
    else:
        body["reason"] = "no_proof_candidate"
    return {
        **body,
        "receipt_sha256": hashlib.sha256(
            contracts.canonical_json(body).encode("utf-8")
        ).hexdigest(),
    }


def _case_result(
    *,
    case_id: str = "case-001",
    kernel_accepted: bool = True,
    environment_sha256: str = SHA_ENVIRONMENT,
    native_kernel_receipt: bool = False,
) -> contracts.CaseResultRecord:
    stages: list[contracts.StageRecord] = []
    for index, stage_name in enumerate(ROUTE):
        provenance = contracts.StageProvenance(
            schema=contracts.STAGE_PROVENANCE_SCHEMA,
            adapter_id=f"{stage_name.value}-adapter",
            adapter_version="1",
            source=("integration-test",),
            requested_identity={
                "request_id": "request-1",
                "implementation": stage_name.value,
            },
            effective_identity={
                "request_id": "request-1",
                "implementation": stage_name.value,
                **(
                    {
                        "graph_invoked": True,
                        "consumed_artifact_sha256": [SHA_OTHER],
                    }
                    if native_kernel_receipt
                    and stage_name is contracts.StageName.KERNEL
                    else {}
                ),
            },
            input_sha256=SHA_INPUT,
            environment_sha256=environment_sha256,
            upstream_stage_digests=tuple(item.digest for item in stages),
        )
        telemetry = contracts.TelemetryRecord(
            wall_time_ms=float(index + 1),
            cpu_time_ms=0.5,
            peak_memory_bytes=1024 * (index + 1),
            input_items=1,
            output_items=1,
            model_calls=(
                1
                if stage_name
                in {contracts.StageName.SYMAI, contracts.StageName.LEANSTRAL}
                else 0
            ),
            bytes_in=20,
            bytes_out=10,
            resource_lane=LANES[stage_name],
        )
        data: object = {"stage": stage_name.value}
        if stage_name is contracts.StageName.HAMMER:
            data = _hammer_payload()
        if stage_name is contracts.StageName.KERNEL:
            data = {"accepted": kernel_accepted, "request_id": "request-1"}
            if native_kernel_receipt:
                data = _native_kernel_receipt(
                    case_id=case_id,
                    environment_sha256=environment_sha256,
                    accepted=kernel_accepted,
                )
                receipt_sha256 = str(data["receipt_sha256"])
            else:
                receipt_sha256 = SHA_RECEIPT
        stages.append(
            contracts.StageRecord.create(
                protocol_sha256=contracts.DEFAULT_PROTOCOL_SHA256,
                run_id="run-001",
                case_id=case_id,
                case_manifest_sha256=SHA_MANIFEST,
                variant_id="A4",
                split=contracts.Split.PILOT,
                cache_mode=contracts.CacheMode.COLD,
                stage=stage_name,
                adapter_version="1",
                status=contracts.StageStatus.SUCCESS,
                provenance=provenance,
                telemetry=telemetry,
                data=data,
                kernel_accepted=(
                    kernel_accepted
                    and stage_name is contracts.StageName.KERNEL
                ),
                kernel_receipt_sha256=(
                    receipt_sha256
                    if kernel_accepted
                    and stage_name is contracts.StageName.KERNEL
                    else None
                ),
            )
        )
    return contracts.CaseResultRecord.from_stages(stages)


def _with_stage_failure(
    result: contracts.CaseResultRecord,
    *,
    stage_name: contracts.StageName,
    status: contracts.StageStatus,
    failure_code: contracts.FailureCode,
) -> contracts.CaseResultRecord:
    stages: list[contracts.StageRecord] = []
    for original in result.stages:
        payload = copy.deepcopy(original.to_dict())
        payload["provenance"]["upstream_stage_digests"] = [
            item.digest for item in stages
        ]
        if original.stage is stage_name:
            payload.update(
                {
                    "status": status.value,
                    "data": {},
                    "output_sha256": None,
                    "failure_code": failure_code.value,
                    "failure_detail": f"{stage_name.value} failed in test",
                    "kernel_accepted": False,
                    "kernel_receipt_sha256": None,
                }
            )
        stages.append(contracts.StageRecord.from_dict(payload))
    return contracts.CaseResultRecord.from_stages(stages)


def _rebuild_kernel(
    original: contracts.StageRecord,
    *,
    data: object | None = None,
    provenance: contracts.StageProvenance | None = None,
    status: contracts.StageStatus | None = None,
    failure_code: contracts.FailureCode | None = None,
    failure_detail: str | None = None,
    kernel_accepted: bool | None = None,
    kernel_receipt_sha256: str | None = None,
) -> contracts.StageRecord:
    rebuilt_status = original.status if status is None else status
    rebuilt_failure_code = (
        original.failure_code if status is None else failure_code
    )
    rebuilt_failure_detail = (
        original.failure_detail if status is None else failure_detail
    )
    rebuilt_kernel_accepted = (
        original.kernel_accepted
        if kernel_accepted is None
        else kernel_accepted
    )
    rebuilt_kernel_receipt_sha256 = (
        original.kernel_receipt_sha256
        if kernel_accepted is None
        else kernel_receipt_sha256
    )
    return contracts.StageRecord.create(
        protocol_sha256=original.protocol_sha256,
        run_id=original.run_id,
        case_id=original.case_id,
        case_manifest_sha256=original.case_manifest_sha256,
        variant_id=original.variant_id,
        split=original.split,
        cache_mode=original.cache_mode,
        stage=original.stage,
        adapter_version=original.adapter_version,
        status=rebuilt_status,
        provenance=original.provenance if provenance is None else provenance,
        telemetry=original.telemetry,
        data=original.to_dict()["data"] if data is None else data,
        failure_code=rebuilt_failure_code,
        failure_detail=rebuilt_failure_detail,
        kernel_accepted=rebuilt_kernel_accepted,
        kernel_receipt_sha256=rebuilt_kernel_receipt_sha256,
    )


def _executed_kernel_rejection(
    original: contracts.StageRecord,
    *,
    lifecycle_field: str | None,
    termination_reason: str,
    status: contracts.StageStatus,
    failure_code: contracts.FailureCode | None,
    returncode: int | None = 1,
    process_group_reaped: bool = True,
) -> contracts.StageRecord:
    """Restamp an accepted synthetic receipt as an executed rejection."""

    data = copy.deepcopy(original.to_dict()["data"])
    attempt = data["candidate_attempts"][-1]
    attempt.update(
        {
            "returncode": returncode,
            "timed_out": False,
            "cancelled": False,
            "resource_exhausted": False,
            "termination_reason": termination_reason,
            "process_group_reaped": process_group_reaped,
            "active_process_count": 0,
            "accepted": False,
        }
    )
    if lifecycle_field == "active_process_count":
        attempt[lifecycle_field] = 1
    elif lifecycle_field is not None:
        attempt[lifecycle_field] = True
    attempt_body = {
        key: value
        for key, value in attempt.items()
        if key != "attempt_sha256"
    }
    attempt["attempt_sha256"] = hashlib.sha256(
        contracts.canonical_json(attempt_body).encode("utf-8")
    ).hexdigest()
    data["selected_attempt"] = {
        key: attempt[key]
        for key in (
            "attempt_index",
            "candidate_source",
            "candidate_artifact_sha256",
            "attempt_sha256",
            "accepted",
        )
    }
    for field in (
        "returncode",
        "timed_out",
        "cancelled",
        "resource_exhausted",
        "termination_reason",
        "process_group_reaped",
        "active_process_count",
        "accepted",
    ):
        data[field] = attempt[field]
    data["candidate_attempts_sha256"] = hashlib.sha256(
        contracts.canonical_json(data["candidate_attempts"]).encode("utf-8")
    ).hexdigest()
    body = {
        key: value
        for key, value in data.items()
        if key != "receipt_sha256"
    }
    data["receipt_sha256"] = hashlib.sha256(
        contracts.canonical_json(body).encode("utf-8")
    ).hexdigest()
    return _rebuild_kernel(
        original,
        data=data,
        status=status,
        failure_code=failure_code,
        failure_detail=(
            None
            if failure_code is None
            else "synthetic native-kernel lifecycle failure"
        ),
        kernel_accepted=False,
        kernel_receipt_sha256=None,
    )


def _accepted_kernel_with_termination_reason(
    original: contracts.StageRecord,
    termination_reason: str,
) -> contracts.StageRecord:
    """Rehash an accepted receipt around one claimed process termination."""

    data = copy.deepcopy(original.to_dict()["data"])
    attempt = data["candidate_attempts"][-1]
    attempt["termination_reason"] = termination_reason
    attempt_body = {
        key: value
        for key, value in attempt.items()
        if key != "attempt_sha256"
    }
    attempt["attempt_sha256"] = hashlib.sha256(
        contracts.canonical_json(attempt_body).encode("utf-8")
    ).hexdigest()
    data["selected_attempt"]["attempt_sha256"] = attempt["attempt_sha256"]
    data["termination_reason"] = termination_reason
    data["candidate_attempts_sha256"] = hashlib.sha256(
        contracts.canonical_json(data["candidate_attempts"]).encode("utf-8")
    ).hexdigest()
    body = {
        key: value
        for key, value in data.items()
        if key != "receipt_sha256"
    }
    data["receipt_sha256"] = hashlib.sha256(
        contracts.canonical_json(body).encode("utf-8")
    ).hexdigest()
    return _rebuild_kernel(
        original,
        data=data,
        kernel_accepted=True,
        kernel_receipt_sha256=str(data["receipt_sha256"]),
    )


def _serialized(result: contracts.CaseResultRecord) -> dict[str, object]:
    return json.loads(contracts.canonical_json(result.to_dict()))


def test_verified_result_binds_complete_route_receipts_and_resources() -> None:
    result = _case_result()

    assert contracts.HSSLEV0357C0D() == (
        "kernel and provenance receipts for all claimed successes"
    )
    assert metrics.HSSLEV0357C0D() == contracts.HSSLEV0357C0D()
    assert result.status is contracts.OutcomeStatus.VERIFIED
    assert result.receipt is not None
    assert result.receipt.route == ROUTE
    assert result.receipt.stage_digests == result.stage_digests
    assert result.receipt.resource_lanes == tuple(LANES[item] for item in ROUTE)
    assert result.receipt.environment_sha256 == SHA_ENVIRONMENT
    assert result.receipt.reconstruction_sha256 is not None
    assert result.receipt.kernel_stage_digest == result.stages[-1].digest
    assert result.receipt.kernel_receipt_sha256 == SHA_RECEIPT
    assert len(result.receipt.provenance_digests) == len(ROUTE)
    assert len(result.receipt.telemetry_digests) == len(ROUTE)

    restored = contracts.CaseResultRecord.from_dict(_serialized(result))
    assert restored.digest == result.digest
    assert restored.provenance_receipt_sha256 == result.provenance_receipt_sha256

    aggregate = metrics.aggregate_case_results(
        [restored], expected_environment_sha256=SHA_ENVIRONMENT
    )
    assert aggregate.verified_count == 1
    assert aggregate.kernel_verified_completion_rate == 1.0
    assert aggregate.verified_result_digests == (result.digest,)
    assert aggregate.resource_lane_measurements["kernel"]["stage_count"] == 1
    assert metrics.KernelBoundAggregate.from_dict(
        aggregate.to_dict()
    ).digest == aggregate.digest


def test_recoverable_proof_failure_is_degraded_but_kernel_verified() -> None:
    result = _with_stage_failure(
        _case_result(),
        stage_name=contracts.StageName.LEANSTRAL,
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
    )

    assert result.status is contracts.OutcomeStatus.VERIFIED
    assert result.kernel_accepted is True
    assert result.failure_code is None
    assert result.recovered_failure_codes == (
        contracts.FailureCode.LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
    )
    assert result.receipt is not None
    assert result.receipt.kernel_accepted is True
    assert contracts.CaseResultRecord.from_dict(_serialized(result)) == result
    assert metrics.aggregate_case_results([result]).verified_count == 1
    masked = _serialized(result)
    masked.update(
        {
            "status": contracts.OutcomeStatus.REJECTED.value,
            "verification_authority": (
                contracts.VerificationAuthority.NONE.value
            ),
            "kernel_accepted": False,
            "kernel_receipt_sha256": None,
        }
    )
    # Legacy v1 result envelopes must remain parseable so immutable diagnostic
    # runs can still be audited.  Current v2 ablation envelopes independently
    # require this canonical reconstruction and reject the masked projection.
    legacy_masked = contracts.CaseResultRecord.from_dict(masked)
    reconstructed = contracts.CaseResultRecord.from_stages(
        legacy_masked.stages
    )
    assert legacy_masked.status is contracts.OutcomeStatus.REJECTED
    assert reconstructed.status is contracts.OutcomeStatus.VERIFIED
    assert reconstructed.kernel_accepted is True

    metric = report._variant_metric(
        "A4",
        "cold",
        [
            {
                "variant_id": "A4",
                "cache_mode": "cold",
                "status": "verified",
                "case_result": result.to_dict(),
                "hammer": {
                    "candidate_created": True,
                    "premise_recall_numerator": None,
                    "premise_recall_denominator": None,
                    "reconstruction_attempted": True,
                    "reconstruction_succeeded": True,
                },
                "leanstral": {
                    "candidate_created": False,
                    "repair_attempted": False,
                    "repair_succeeded": False,
                },
                "total_wall_time_ms": 1.0,
                "model_calls": 1,
                "verified_source": "hammer",
            }
        ],
    )
    assert metric["kernel_verified_count"] == 1
    assert metric["reliability_status"] == "degraded_recovered"
    assert metric["recovered_failure_counts"] == {
        "leanstral_timeout_schema_or_forbidden_construct": 1
    }


def test_capability_unavailable_still_blocks_terminal_kernel_acceptance() -> None:
    result = _with_stage_failure(
        _case_result(native_kernel_receipt=True),
        stage_name=contracts.StageName.LEANSTRAL,
        status=contracts.StageStatus.UNAVAILABLE,
        failure_code=contracts.FailureCode.CAPABILITY_UNAVAILABLE,
    )

    assert result.status is contracts.OutcomeStatus.UNAVAILABLE
    assert result.kernel_accepted is False
    assert result.kernel_receipt_sha256 is None
    assert result.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE
    assert result.recovered_failures == ()
    assert result.receipt is not None
    assert result.receipt.kernel_accepted is True


@pytest.mark.parametrize(
    ("stage_name", "failure_code", "expected_status"),
    (
        (
            contracts.StageName.HAMMER,
            contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
            contracts.OutcomeStatus.INFRASTRUCTURE_FAILURE,
        ),
        (
            contracts.StageName.LEANSTRAL,
            contracts.FailureCode.RECEIPT_OR_PROVENANCE_FAILURE,
            contracts.OutcomeStatus.REJECTED,
        ),
    ),
)
def test_infrastructure_and_provenance_failures_block_kernel_acceptance(
    stage_name: contracts.StageName,
    failure_code: contracts.FailureCode,
    expected_status: contracts.OutcomeStatus,
) -> None:
    result = _with_stage_failure(
        _case_result(),
        stage_name=stage_name,
        status=contracts.StageStatus.FAILED,
        failure_code=failure_code,
    )

    assert result.status is expected_status
    assert result.failure_code is failure_code
    assert result.kernel_accepted is False
    assert result.recovered_failures == ()


def test_invalid_control_safety_reads_raw_kernel_receipt_when_status_masks_it() -> None:
    result = _with_stage_failure(
        _case_result(native_kernel_receipt=True),
        stage_name=contracts.StageName.LEANSTRAL,
        status=contracts.StageStatus.UNAVAILABLE,
        failure_code=contracts.FailureCode.CAPABILITY_UNAVAILABLE,
    )

    assert result.status is contracts.OutcomeStatus.UNAVAILABLE
    assert matrix_reassessment._invalid_control_kernel_accepted(result) is True


def test_native_kernel_validator_rejects_copied_or_tampered_receipts() -> None:
    result = _case_result(native_kernel_receipt=True)
    kernel = result.stages[-1]
    assert contracts.validate_native_kernel_stage_receipt(kernel) is True

    copied = copy.deepcopy(kernel.to_dict()["data"])
    copied["case_id"] = "case-copied"
    copied_body = {
        key: value
        for key, value in copied.items()
        if key != "receipt_sha256"
    }
    copied["receipt_sha256"] = hashlib.sha256(
        contracts.canonical_json(copied_body).encode("utf-8")
    ).hexdigest()
    copied_stage = _rebuild_kernel(kernel, data=copied)
    with pytest.raises(
        contracts.ProtocolContractError, match="coordinate|source binding"
    ):
        contracts.validate_native_kernel_stage_receipt(copied_stage)

    stale_body = copy.deepcopy(kernel.to_dict()["data"])
    stale_body["termination_reason"] = "tampered"
    with pytest.raises(
        contracts.ProtocolContractError, match="self-digest"
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(kernel, data=stale_body)
        )

    stale_digest = copy.deepcopy(kernel.to_dict()["data"])
    stale_digest["receipt_sha256"] = "0" * 64
    with pytest.raises(
        contracts.ProtocolContractError, match="self-digest"
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(kernel, data=stale_digest)
        )


def test_native_kernel_outer_attachments_are_independently_bound() -> None:
    result = _case_result(native_kernel_receipt=True)
    kernel = result.stages[-1]
    policy_body = {
        "schema": "routing-policy.v1",
        "decision": "invoke",
        "reason": "scheduled",
    }
    policy = {
        **policy_body,
        "decision_sha256": hashlib.sha256(
            contracts.canonical_json(policy_body).encode("utf-8")
        ).hexdigest(),
    }
    attached = {
        **copy.deepcopy(kernel.to_dict()["data"]),
        "routing_policy": policy,
    }
    assert contracts.validate_native_kernel_stage_receipt(
        _rebuild_kernel(kernel, data=attached)
    )

    attached["routing_policy"]["decision"] = "skip"
    with pytest.raises(
        contracts.ProtocolContractError,
        match="routing-policy self-digest",
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(kernel, data=attached)
        )

    invalid_diagnostic = copy.deepcopy(kernel.to_dict()["data"])
    invalid_diagnostic.update(
        {"diagnostic_only": True, "authority_withheld": True}
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="diagnostic authority attachment",
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(kernel, data=invalid_diagnostic)
        )


def test_native_kernel_validator_rejects_minimal_or_incoherent_execution() -> None:
    result = _case_result(native_kernel_receipt=True)
    kernel = result.stages[-1]
    complete = kernel.to_dict()["data"]
    minimal_body = {
        key: complete[key]
        for key in (
            "schema",
            "protocol_sha256",
            "run_id",
            "case_id",
            "case_manifest_sha256",
            "variant_id",
            "split",
            "cache_mode",
            "input_sha256",
            "environment_sha256",
            "independent",
            "accepted",
            "active_process_count",
        )
    }
    minimal = {
        **minimal_body,
        "receipt_sha256": hashlib.sha256(
            contracts.canonical_json(minimal_body).encode("utf-8")
        ).hexdigest(),
    }
    with pytest.raises(
        contracts.ProtocolContractError, match="executed Lean evidence"
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(kernel, data=minimal)
        )

    selected_tamper = copy.deepcopy(complete)
    selected_tamper["selected_attempt"]["attempt_sha256"] = "1" * 64
    selected_body = {
        key: value
        for key, value in selected_tamper.items()
        if key != "receipt_sha256"
    }
    selected_tamper["receipt_sha256"] = hashlib.sha256(
        contracts.canonical_json(selected_body).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        contracts.ProtocolContractError, match="selected attempt"
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(kernel, data=selected_tamper)
        )


@pytest.mark.parametrize(
    "termination_reason",
    ("completed", "completed_with_descendant_cleanup"),
)
def test_native_kernel_accepts_only_reviewed_safe_completion_reasons(
    termination_reason: str,
) -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    reviewed = _accepted_kernel_with_termination_reason(
        kernel,
        termination_reason,
    )

    assert contracts.validate_native_kernel_stage_receipt(reviewed) is True


@pytest.mark.parametrize("termination_reason", ("monitor_error", "spawn_error"))
def test_rehashed_process_errors_cannot_claim_kernel_acceptance(
    termination_reason: str,
) -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    forged = _accepted_kernel_with_termination_reason(
        kernel,
        termination_reason,
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="pre-spawn returncode|reviewed process outcome",
    ):
        contracts.validate_native_kernel_stage_receipt(forged)


def test_native_kernel_negative_receipt_and_graph_suppression_are_strict() -> None:
    negative_result = _case_result(
        native_kernel_receipt=True,
        kernel_accepted=False,
    )
    negative = negative_result.stages[-1]
    assert contracts.validate_native_kernel_stage_receipt(negative) is False

    tampered = copy.deepcopy(negative.to_dict()["data"])
    tampered["reason"] = "copied rejection"
    with pytest.raises(
        contracts.ProtocolContractError, match="self-digest"
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(negative, data=tampered)
        )

    accepted = _case_result(native_kernel_receipt=True)
    kernel = accepted.stages[-1]
    suppressed_identity = dict(kernel.provenance.effective_identity)
    suppressed_identity["graph_invoked"] = False
    suppressed = _rebuild_kernel(
        kernel,
        provenance=replace(
            kernel.provenance,
            effective_identity=suppressed_identity,
        ),
    )
    with pytest.raises(
        contracts.ProtocolContractError, match="explicit graph invocation"
    ):
        contracts.CaseResultRecord.from_stages(
            (*accepted.stages[:-1], suppressed)
        )

    markerless_identity = dict(kernel.provenance.effective_identity)
    markerless_identity.pop("graph_invoked")
    markerless = _rebuild_kernel(
        kernel,
        provenance=replace(
            kernel.provenance,
            effective_identity=markerless_identity,
        ),
    )
    with pytest.raises(
        contracts.ProtocolContractError, match="explicit graph invocation"
    ):
        contracts.CaseResultRecord.from_stages(
            (*accepted.stages[:-1], markerless)
        )

    serialized = _serialized(accepted)
    del serialized["stages"][-1]["provenance"]["effective_identity"][
        "graph_invoked"
    ]
    with pytest.raises(
        contracts.ProtocolContractError, match="explicit graph invocation"
    ):
        contracts.CaseResultRecord.from_dict(serialized)


@pytest.mark.parametrize(
    (
        "lifecycle_field",
        "termination_reason",
        "expected_failure_code",
        "returncode",
    ),
    (
        (
            "timed_out",
            "wall_clock_deadline",
            contracts.FailureCode.RESOURCE_LEASE_CANCELLATION,
            1,
        ),
        (
            "cancelled",
            "cancelled",
            contracts.FailureCode.RESOURCE_LEASE_CANCELLATION,
            1,
        ),
        (
            "cancelled",
            "cancelled_before_start",
            contracts.FailureCode.RESOURCE_LEASE_CANCELLATION,
            None,
        ),
        (
            "resource_exhausted",
            "resource_deadline",
            contracts.FailureCode.OUT_OF_MEMORY,
            1,
        ),
        (
            "active_process_count",
            "completed_with_descendant_cleanup",
            contracts.FailureCode.ORPHANED_CHILD,
            1,
        ),
    ),
)
def test_executed_kernel_lifecycle_failures_cannot_claim_success(
    lifecycle_field: str,
    termination_reason: str,
    expected_failure_code: contracts.FailureCode,
    returncode: int | None,
) -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    masked_success = _executed_kernel_rejection(
        kernel,
        lifecycle_field=lifecycle_field,
        termination_reason=termination_reason,
        status=contracts.StageStatus.SUCCESS,
        failure_code=None,
        returncode=returncode,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="lifecycle failure authority",
    ):
        contracts.validate_native_kernel_stage_receipt(masked_success)

    typed_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=lifecycle_field,
        termination_reason=termination_reason,
        status=contracts.StageStatus.FAILED,
        failure_code=expected_failure_code,
        returncode=returncode,
    )
    assert (
        contracts.validate_native_kernel_stage_receipt(typed_failure)
        is False
    )

    wrong_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=lifecycle_field,
        termination_reason=termination_reason,
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.SAFETY_CONTROL_FAILURE,
        returncode=returncode,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="lifecycle failure authority",
    ):
        contracts.validate_native_kernel_stage_receipt(wrong_failure)


@pytest.mark.parametrize(
    ("termination_reason", "returncode"),
    (("monitor_error", 1), ("spawn_error", None)),
)
def test_process_error_rejections_require_infrastructure_failure(
    termination_reason: str,
    returncode: int | None,
) -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    typed_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=None,
        termination_reason=termination_reason,
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        returncode=returncode,
    )
    assert (
        contracts.validate_native_kernel_stage_receipt(typed_failure)
        is False
    )

    masked_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=None,
        termination_reason=termination_reason,
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.KERNEL_REJECTION,
        returncode=returncode,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="lifecycle failure authority",
    ):
        contracts.validate_native_kernel_stage_receipt(masked_failure)


def test_cancelled_before_start_requires_a_null_returncode() -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    forged = _executed_kernel_rejection(
        kernel,
        lifecycle_field="cancelled",
        termination_reason="cancelled_before_start",
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.RESOURCE_LEASE_CANCELLATION,
        returncode=1,
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="pre-spawn returncode",
    ):
        contracts.validate_native_kernel_stage_receipt(forged)


def test_unreaped_process_group_requires_orphan_failure_authority() -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    typed_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=None,
        termination_reason="orphaned_process_group",
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.ORPHANED_CHILD,
        returncode=0,
        process_group_reaped=False,
    )
    assert contracts.validate_native_kernel_stage_receipt(typed_failure) is False

    forged_completion = _executed_kernel_rejection(
        kernel,
        lifecycle_field=None,
        termination_reason="completed_with_descendant_cleanup",
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.ORPHANED_CHILD,
        returncode=0,
        process_group_reaped=False,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="termination reason",
    ):
        contracts.validate_native_kernel_stage_receipt(forged_completion)

    masked_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=None,
        termination_reason="orphaned_process_group",
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        returncode=0,
        process_group_reaped=False,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="lifecycle failure authority",
    ):
        contracts.validate_native_kernel_stage_receipt(masked_failure)


def test_signal_crash_requires_infrastructure_failure_authority() -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    typed_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=None,
        termination_reason="completed",
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE,
        returncode=-11,
    )
    assert contracts.validate_native_kernel_stage_receipt(typed_failure) is False

    masked_failure = _executed_kernel_rejection(
        kernel,
        lifecycle_field=None,
        termination_reason="completed",
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.KERNEL_REJECTION,
        returncode=-11,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="lifecycle failure authority",
    ):
        contracts.validate_native_kernel_stage_receipt(masked_failure)


@pytest.mark.parametrize(
    ("lifecycle_field", "termination_reason"),
    (
        (None, "unreviewed_process_exit"),
        (None, "wall_clock_deadline"),
        ("timed_out", "completed"),
        ("timed_out", "monitor_error"),
    ),
)
def test_rehashed_rejections_require_reviewed_flag_consistent_termination(
    lifecycle_field: str | None,
    termination_reason: str,
) -> None:
    kernel = _case_result(native_kernel_receipt=True).stages[-1]
    forged = _executed_kernel_rejection(
        kernel,
        lifecycle_field=lifecycle_field,
        termination_reason=termination_reason,
        status=contracts.StageStatus.FAILED,
        failure_code=contracts.FailureCode.KERNEL_REJECTION,
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="termination reason",
    ):
        contracts.validate_native_kernel_stage_receipt(forged)


def test_pre_execution_kernel_rejection_cannot_leave_an_orphan() -> None:
    negative = _case_result(
        native_kernel_receipt=True,
        kernel_accepted=False,
    ).stages[-1]
    data = copy.deepcopy(negative.to_dict()["data"])
    data["active_process_count"] = 1
    body = {
        key: value
        for key, value in data.items()
        if key != "receipt_sha256"
    }
    data["receipt_sha256"] = hashlib.sha256(
        contracts.canonical_json(body).encode("utf-8")
    ).hexdigest()

    with pytest.raises(
        contracts.ProtocolContractError,
        match="left active processes",
    ):
        contracts.validate_native_kernel_stage_receipt(
            _rebuild_kernel(negative, data=data)
        )


def test_nested_payload_and_digest_chain_tampering_fail_deserialization() -> None:
    payload = _serialized(_case_result())
    payload["stages"][0]["data"]["stage"] = "tampered"
    with pytest.raises(contracts.ProtocolContractError, match="output_sha256"):
        contracts.CaseResultRecord.from_dict(payload)

    payload = _serialized(_case_result())
    stage = payload["stages"][1]
    stage["data"]["stage"] = "recomputed-tamper"
    stage["output_sha256"] = hashlib.sha256(
        contracts.canonical_json(stage["data"]).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        contracts.ProtocolContractError, match="digest chain|receipt"
    ):
        contracts.CaseResultRecord.from_dict(payload)


def test_mixed_request_and_reconstruction_records_fail_closed() -> None:
    payload = _serialized(_case_result())
    payload["stages"][2]["run_id"] = "other-run"
    with pytest.raises(contracts.ProtocolContractError, match="identities"):
        contracts.CaseResultRecord.from_dict(payload)

    payload = _serialized(_case_result())
    hammer = payload["stages"][3]
    hammer["data"]["reconstruction"]["request_id"] = "other-request"
    body = {
        key: value
        for key, value in hammer["data"].items()
        if key != "evidence_id"
    }
    hammer["data"]["evidence_id"] = hashlib.sha256(
        contracts.canonical_json(body).encode("utf-8")
    ).hexdigest()
    hammer["output_sha256"] = hashlib.sha256(
        contracts.canonical_json(hammer["data"]).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        contracts.ProtocolContractError, match="digest chain|reconstruction"
    ):
        contracts.CaseResultRecord.from_dict(payload)


def test_stale_or_incoherent_environment_cannot_verify_or_aggregate() -> None:
    payload = _serialized(_case_result())
    payload["stages"][4]["provenance"]["environment_sha256"] = SHA_OTHER
    with pytest.raises(
        contracts.ProtocolContractError, match="digest chain|environment"
    ):
        contracts.CaseResultRecord.from_dict(payload)

    coherent_but_stale = _case_result(environment_sha256=SHA_OTHER)
    with pytest.raises(metrics.MetricsContractError, match="stale"):
        metrics.aggregate_case_results(
            [coherent_but_stale],
            expected_environment_sha256=SHA_ENVIRONMENT,
        )


def test_route_resource_and_receipt_tampering_fail_closed() -> None:
    payload = _serialized(_case_result())
    payload["stages"][3], payload["stages"][4] = (
        payload["stages"][4],
        payload["stages"][3],
    )
    with pytest.raises(contracts.ProtocolContractError, match="canonical"):
        contracts.CaseResultRecord.from_dict(payload)

    payload = _serialized(_case_result())
    payload["stages"][5]["telemetry"]["resource_lane"] = "cpu"
    with pytest.raises(contracts.ProtocolContractError, match="resource lane"):
        contracts.CaseResultRecord.from_dict(payload)

    payload = _serialized(_case_result())
    payload["receipt"]["kernel_receipt_sha256"] = SHA_OTHER
    with pytest.raises(contracts.ProtocolContractError, match="receipt"):
        contracts.CaseResultRecord.from_dict(payload)


def test_model_and_solver_claims_do_not_enter_verified_numerator() -> None:
    result = _case_result(kernel_accepted=False)
    payload = _serialized(result)
    payload["stages"][2]["data"] = {
        "verified": True,
        "authority": "model",
    }
    payload["stages"][2]["output_sha256"] = hashlib.sha256(
        contracts.canonical_json(payload["stages"][2]["data"]).encode("utf-8")
    ).hexdigest()
    # Rebuild through the trusted constructor so the changed model payload has
    # a coherent downstream chain and receipt.  It still has no proof authority.
    stages: list[contracts.StageRecord] = []
    for stage_payload in payload["stages"]:
        stage_payload = copy.deepcopy(stage_payload)
        stage_payload["provenance"]["upstream_stage_digests"] = [
            item.digest for item in stages
        ]
        stages.append(contracts.StageRecord.from_dict(stage_payload))
    claimed = contracts.CaseResultRecord.from_stages(stages)

    assert claimed.status is contracts.OutcomeStatus.NOT_VERIFIED
    assert claimed.receipt is not None
    assert claimed.receipt.reconstruction_sha256 is not None
    aggregate = metrics.aggregate_case_results(
        [claimed], expected_environment_sha256=SHA_ENVIRONMENT
    )
    assert aggregate.verified_count == 0
    assert aggregate.nonverified_count == 1
    assert aggregate.kernel_verified_completion_rate == 0.0

    forged = _serialized(claimed)
    forged["status"] = "verified"
    forged["verification_authority"] = "external_solver"
    forged["kernel_accepted"] = True
    forged["kernel_receipt_sha256"] = SHA_RECEIPT
    with pytest.raises(contracts.ProtocolContractError):
        contracts.CaseResultRecord.from_dict(forged)


def test_aggregation_revalidates_inputs_and_rejects_duplicates_or_outcomes() -> None:
    first = _case_result()
    second = _case_result(case_id="case-002", kernel_accepted=False)
    aggregate = metrics.aggregate_case_results(
        [second, first], expected_environment_sha256=SHA_ENVIRONMENT
    )

    assert aggregate.total_count == 2
    assert aggregate.verified_count == 1
    assert aggregate.nonverified_count == 1
    assert aggregate.kernel_verified_completion_rate == 0.5
    assert aggregate.result_digests == (first.digest, second.digest)
    with pytest.raises(metrics.MetricsContractError, match="duplicate"):
        metrics.aggregate_case_results([first, first])
    with pytest.raises(metrics.MetricsContractError, match="CaseResultRecord"):
        metrics.aggregate_case_results([first.to_outcome()])  # type: ignore[list-item]


def test_case_result_and_aggregate_wire_contracts_are_strict() -> None:
    payload = _serialized(_case_result())
    payload["untrusted_success"] = True
    with pytest.raises(contracts.ProtocolContractError, match="unknown"):
        contracts.CaseResultRecord.from_dict(payload)

    aggregate = metrics.aggregate_case_results([_case_result()])
    aggregate_payload = aggregate.to_dict()
    aggregate_payload["verified_count"] = 2
    with pytest.raises(metrics.MetricsContractError, match="sum|length"):
        metrics.KernelBoundAggregate.from_dict(aggregate_payload)

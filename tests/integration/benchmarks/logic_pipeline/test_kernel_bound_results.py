"""Integration evidence for kernel- and provenance-bound case results."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from benchmarks.logic_pipeline import contracts, metrics


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


def _case_result(
    *,
    case_id: str = "case-001",
    kernel_accepted: bool = True,
    environment_sha256: str = SHA_ENVIRONMENT,
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
                    SHA_RECEIPT
                    if kernel_accepted
                    and stage_name is contracts.StageName.KERNEL
                    else None
                ),
            )
        )
    return contracts.CaseResultRecord.from_stages(stages)


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

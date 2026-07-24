"""Executable evidence for the versioned stage-adapter boundary."""

from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from benchmarks.logic_pipeline import adapters, contracts


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_RECEIPT = "c" * 64


def _request() -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id="run-001",
        case_id="case-001",
        case_manifest_sha256=SHA_A,
        variant_id="A0",
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        input_data={"source": "A policy must be obeyed."},
        requested_identity={"implementation": "injected-test"},
        environment_sha256=SHA_B,
    )


def _telemetry(
    lane: contracts.ResourceLane = contracts.ResourceLane.CPU,
) -> contracts.TelemetryRecord:
    return contracts.TelemetryRecord(
        wall_time_ms=1.25,
        cpu_time_ms=0.5,
        input_items=1,
        output_items=1,
        bytes_in=27,
        bytes_out=12,
        resource_lane=lane,
    )


def test_objective_evidence_and_default_route_are_versioned() -> None:
    assert adapters.HSSLEV0306C18() == "versioned stage adapters and deterministic telemetry"
    assert adapters.ADAPTER_VERSION == "1"
    assert adapters.STAGE_ORDER == (
        contracts.StageName.COMPILER,
        contracts.StageName.SPACY,
        contracts.StageName.SYMAI,
        contracts.StageName.HAMMER,
        contracts.StageName.LEANSTRAL,
        contracts.StageName.KERNEL,
    )
    assert tuple(adapters.build_default_adapters()) == adapters.STAGE_ORDER
    assert all(item.handler is None for item in adapters.build_default_adapters().values())


def test_successful_stage_has_bounded_provenance_telemetry_and_stable_digest() -> None:
    telemetry = _telemetry()
    record = adapters.CompilerAdapter(
        lambda request: {"ir": "compiled", "case": request.case_id}
    ).run(_request(), telemetry=telemetry)

    assert record.schema == contracts.STAGE_RECORD_SCHEMA
    assert record.status is contracts.StageStatus.SUCCESS
    assert record.provenance.requested_identity == {"implementation": "injected-test"}
    assert record.telemetry == telemetry
    assert record.output_sha256 == hashlib.sha256(
        contracts.canonical_json({"case": "case-001", "ir": "compiled"}).encode()
    ).hexdigest()
    encoded = contracts.canonical_json(record.to_dict())
    restored = contracts.StageRecord.from_dict(record.to_dict())
    assert contracts.canonical_json(restored.to_dict()) == encoded
    assert restored.digest == record.digest


def test_missing_handler_is_explicitly_unavailable_and_never_falls_back() -> None:
    record = adapters.SpacyAdapter().run(_request(), telemetry=_telemetry())

    assert record.status is contracts.StageStatus.UNAVAILABLE
    assert record.failure_code is contracts.FailureCode.CAPABILITY_UNAVAILABLE
    assert record.output_sha256 is None
    assert record.provenance.effective_identity == record.provenance.requested_identity


def test_resource_lanes_are_bound_to_the_stage() -> None:
    model_telemetry = replace(
        _telemetry(), resource_lane=contracts.ResourceLane.MODEL
    )
    record = adapters.SymaiAdapter(lambda _request: {"ir": "candidate"}).run(
        _request(), telemetry=model_telemetry
    )
    assert record.telemetry.resource_lane is contracts.ResourceLane.MODEL
    with pytest.raises(contracts.ProtocolContractError):
        adapters.KernelAdapter(lambda _request: {}).run(
            _request(), telemetry=model_telemetry
        )


def test_non_kernel_claim_is_fail_closed() -> None:
    record = adapters.SymaiAdapter(
        lambda _request: adapters.StageOutput(
            data={"claim": "proved"},
            kernel_accepted=True,
            kernel_receipt_sha256=SHA_RECEIPT,
        )
    ).run(_request(), telemetry=_telemetry(contracts.ResourceLane.MODEL))

    assert record.status is contracts.StageStatus.FAILED
    assert record.failure_code is contracts.FailureCode.SAFETY_CONTROL_FAILURE
    assert not record.kernel_accepted
    assert record.kernel_receipt_sha256 is None


def test_only_kernel_acceptance_can_create_verified_case_result() -> None:
    handlers = {
        stage: (lambda _request, stage=stage: {"stage": stage.value})
        for stage in adapters.STAGE_ORDER
    }
    handlers[contracts.StageName.KERNEL] = lambda _request: adapters.StageOutput(
        data={"accepted": True},
        kernel_accepted=True,
        kernel_receipt_sha256=SHA_RECEIPT,
    )
    result = adapters.run_stages(_request(), adapters.build_default_adapters(handlers))

    assert result.status is contracts.OutcomeStatus.VERIFIED
    assert result.verification_authority is contracts.VerificationAuthority.NATIVE_KERNEL
    assert result.kernel_accepted is True
    assert result.to_outcome().status is contracts.OutcomeStatus.VERIFIED
    assert len(result.stage_digests) == len(adapters.STAGE_ORDER)
    assert contracts.CaseResultRecord.from_dict(result.to_dict()).digest == result.digest


def test_unavailable_stage_cannot_be_promoted_to_verified_by_tampering() -> None:
    stages = [
        adapters.CompilerAdapter(lambda _request: {"ir": "ok"}).run(
            _request(), telemetry=_telemetry()
        ),
        adapters.KernelAdapter().run(
            _request(), telemetry=_telemetry(contracts.ResourceLane.KERNEL)
        ),
    ]
    result = contracts.CaseResultRecord.from_stages(stages)
    assert result.status is contracts.OutcomeStatus.UNAVAILABLE

    with pytest.raises(contracts.ProtocolContractError):
        contracts.CaseResultRecord(
            schema=result.schema,
            protocol_sha256=result.protocol_sha256,
            run_id=result.run_id,
            case_id=result.case_id,
            case_manifest_sha256=result.case_manifest_sha256,
            variant_id=result.variant_id,
            split=result.split,
            cache_mode=result.cache_mode,
            stages=result.stages,
            status=contracts.OutcomeStatus.VERIFIED,
            verification_authority=contracts.VerificationAuthority.NATIVE_KERNEL,
            kernel_accepted=True,
            kernel_receipt_sha256=SHA_RECEIPT,
        )


def test_telemetry_rejects_unbounded_or_non_finite_values() -> None:
    with pytest.raises(contracts.ProtocolContractError):
        contracts.TelemetryRecord(wall_time_ms=float("inf"))
    with pytest.raises(contracts.ProtocolContractError):
        contracts.TelemetryRecord(bytes_in=1 << 41)

"""Focused evidence for honest SyMAI warm-cache measurement."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from typing import MutableMapping

import pytest

from benchmarks.logic_pipeline import (
    adapters,
    cache_measurement,
    contracts,
    metrics,
)


MANIFEST_SHA256 = "a" * 64
ENVIRONMENT_SHA256 = "b" * 64
TEXT = "Every licensed agency must file an annual report."


def _structured_response(*, proposition: str = "MustFileAnnualReport") -> str:
    return json.dumps(
        {
            "candidate_ir": {
                "kind": "fol",
                "propositions": [proposition],
            },
            "normalized_predicates": [
                "LicensedAgency",
                "MustFileAnnualReport",
            ],
            "quantifiers": ["forall"],
            "entities": ["agency", "annual report"],
            "ambiguity_flags": [],
            "confidence": 0.95,
            "validation_errors": [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class _Engine:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[object] = []

    def forward(self, argument: object):
        self.calls.append(argument)
        if not self.responses:
            raise AssertionError("unexpected model invocation")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return (
            [response],
            {
                "backend": "llm_router",
                "effective_provider_name": "ipfs_accelerate_py",
                "effective_model_name": "Leanstral-119B",
            },
        )


class _DiscardingCache(dict[str, object]):
    """Mutable mapping that exposes a reproducible second-miss defect."""

    def __setitem__(self, key: str, value: object) -> None:
        del key, value


def _request(
    *,
    cache_mode: contracts.CacheMode = contracts.CacheMode.WARM,
    run_id: str = "symai-cache-measurement",
    deadline_unix_ms: int | None = None,
) -> adapters.StageRequest:
    return adapters.StageRequest(
        run_id=run_id,
        case_id="case-cache-001",
        case_manifest_sha256=MANIFEST_SHA256,
        variant_id="A4",
        split=contracts.Split.PILOT,
        cache_mode=cache_mode,
        input_data={"text": TEXT},
        requested_identity={
            "implementation": "symai",
            "provider": "ipfs_accelerate_py",
            "model": "Leanstral-119B",
            "backend_revision": "pinned-revision",
        },
        environment_sha256=ENVIRONMENT_SHA256,
        source=("benchmark_input",),
        deadline_unix_ms=deadline_unix_ms,
    )


def _configured(
    engine: _Engine,
    *,
    cache: MutableMapping[str, object] | None = None,
    cache_enabled: bool = True,
) -> adapters.SymaiAdapter:
    return adapters.SymaiAdapter(
        config=adapters.SymaiAdapterConfig(
            provider="ipfs_accelerate_py",
            model="Leanstral-119B",
            max_retries=0,
            cache_enabled=cache_enabled,
        ),
        engine_factory=lambda _config, _namespace: engine,
        trace_getter=lambda: {},
        cache={} if cache is None else cache,
    )


def _rehash_receipt(value: dict[str, object]) -> dict[str, object]:
    without_digest = {
        key: item
        for key, item in value.items()
        if key != "receipt_sha256"
    }
    value["receipt_sha256"] = hashlib.sha256(
        contracts.canonical_json(without_digest).encode("utf-8")
    ).hexdigest()
    return value


def _replace_embedded_receipt(
    invocation: adapters.StageInvocation,
    receipt: dict[str, object],
) -> adapters.StageInvocation:
    data = dict(invocation.output.data)
    data[cache_measurement.SYMAI_CACHE_PRIME_FIELD] = receipt
    identity = dict(invocation.output.effective_identity)
    identity[cache_measurement.SYMAI_CACHE_PRIME_DIGEST_FIELD] = (
        receipt["receipt_sha256"]
    )
    return adapters.StageInvocation(
        replace(
            invocation.output,
            data=data,
            effective_identity=identity,
        ),
        invocation.telemetry,
    )


def _record_with_copied_receipt(
    target: contracts.StageRecord,
    receipt: cache_measurement.SymaiCachePrimeReceipt,
) -> contracts.StageRecord:
    data = dict(target.to_dict()["data"])
    data[cache_measurement.SYMAI_CACHE_PRIME_FIELD] = (
        receipt.to_dict()
    )
    effective_identity = dict(
        target.provenance.effective_identity
    )
    effective_identity[
        cache_measurement.SYMAI_CACHE_PRIME_DIGEST_FIELD
    ] = receipt.receipt_sha256
    provenance = replace(
        target.provenance,
        effective_identity=effective_identity,
    )
    return contracts.StageRecord.create(
        protocol_sha256=target.protocol_sha256,
        run_id=target.run_id,
        case_id=target.case_id,
        case_manifest_sha256=target.case_manifest_sha256,
        variant_id=target.variant_id,
        split=target.split,
        cache_mode=target.cache_mode,
        stage=target.stage,
        adapter_version=target.adapter_version,
        status=target.status,
        provenance=provenance,
        telemetry=target.telemetry,
        data=data,
        failure_code=target.failure_code,
        failure_detail=target.failure_detail,
    )


def _graph_bound_result(
    record: contracts.StageRecord,
) -> contracts.CaseResultRecord:
    provenance = replace(
        record.provenance,
        effective_identity={
            **dict(record.provenance.effective_identity),
            "graph_invocation_index": 0,
            "graph_invoked": True,
            "graph_policy_reason": "scheduled",
            "consumed_artifact_sha256": (),
        },
    )
    graph_record = contracts.StageRecord.create(
        protocol_sha256=record.protocol_sha256,
        run_id=record.run_id,
        case_id=record.case_id,
        case_manifest_sha256=record.case_manifest_sha256,
        variant_id=record.variant_id,
        split=record.split,
        cache_mode=record.cache_mode,
        stage=record.stage,
        adapter_version=record.adapter_version,
        status=record.status,
        provenance=provenance,
        telemetry=record.telemetry,
        data=record.data,
        failure_code=record.failure_code,
        failure_detail=record.failure_detail,
    )
    return contracts.CaseResultRecord.from_stages((graph_record,))


def _assert_metrics_backend_invocation_count(
    result: contracts.CaseResultRecord,
    *,
    expected: int,
) -> None:
    aggregate = metrics.aggregate_case_results((result,))
    assert (
        aggregate.resource_lane_measurements["model"]["stage_count"]
        == expected
    )
    symai = result.stages[0]
    setup = cache_measurement.extract_symai_cache_setup_telemetry(symai)
    assert setup is not None
    cost = metrics.EfficiencyComponentCost(
        component_id=contracts.StageName.SYMAI.value,
        model_calls=symai.telemetry.model_calls + setup.model_calls,
        solver_processes=0,
        solver_processes_missing_reason=None,
        accelerator_minutes=0.0,
        accelerator_minutes_missing_reason=None,
        retries=symai.telemetry.retries + setup.retries,
        component_calls=expected,
        useful_component_calls=0,
        failed_attempts=1,
    )
    receipt = metrics.EfficiencyResourceReceipt(
        case_result_sha256=result.digest,
        environment_sha256=ENVIRONMENT_SHA256,
        measurement_sha256=hashlib.sha256(
            f"{result.run_id}:{expected}:metrics".encode("utf-8")
        ).hexdigest(),
        component_costs=(cost,),
    )
    assert (
        metrics.EfficiencyObservation(
            case_result=result,
            resource_receipt=receipt,
        ).resource_receipt
        == receipt
    )
    forged_receipt = metrics.EfficiencyResourceReceipt(
        case_result_sha256=result.digest,
        environment_sha256=ENVIRONMENT_SHA256,
        measurement_sha256=hashlib.sha256(
            f"{result.run_id}:{expected}:forged".encode("utf-8")
        ).hexdigest(),
        component_costs=(
            replace(cost, component_calls=3 - expected),
        ),
    )
    with pytest.raises(
        metrics.MetricsContractError,
        match="component-call attribution",
    ):
        metrics.EfficiencyObservation(
            case_result=result,
            resource_receipt=forged_receipt,
        )


def test_public_api_is_explicit_and_importable() -> None:
    expected = {
        "SYMAI_CACHE_PRIME_DIGEST_FIELD",
        "SYMAI_CACHE_PRIME_FIELD",
        "SYMAI_CACHE_PRIME_MAX_BYTES",
        "SYMAI_CACHE_PRIME_RECEIPT_SCHEMA",
        "SYMAI_CACHE_PRIME_REQUEST_SCHEMA",
        "SymaiCachePrimeReceipt",
        "extract_symai_cache_prime_receipt",
        "extract_symai_cache_setup_telemetry",
        "invoke_with_symai_cache_measurement",
        "is_symai_warm_cache_measurement_eligible",
        "symai_backend_identity",
        "symai_backend_identity_sha256",
        "symai_backend_invocation_count",
        "symai_semantic_payload",
        "symai_semantic_payload_sha256",
        "validate_symai_cache_prime_receipt",
        "validate_symai_warm_cache_measurement",
    }

    assert set(cache_measurement.__all__) == expected
    assert all(
        getattr(cache_measurement, name) is not None
        for name in cache_measurement.__all__
    )


def test_warm_setup_miss_then_measured_hit_has_source_bound_receipt() -> None:
    raw = _structured_response()
    engine = _Engine([raw])
    request = _request()
    adapter = _configured(engine)
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        adapter,
        request,
    )

    assert invocation.output.status is contracts.StageStatus.SUCCESS
    assert len(engine.calls) == 1
    assert invocation.telemetry.model_calls == 0
    assert invocation.telemetry.cache_hits == 1
    assert invocation.telemetry.cache_misses == 0
    assert invocation.telemetry.retries == 0

    receipt = cache_measurement.validate_symai_warm_cache_measurement(
        invocation,
        request=request,
    )
    assert receipt.schema == (
        cache_measurement.SYMAI_CACHE_PRIME_RECEIPT_SCHEMA
    )
    assert receipt.protocol_sha256 == request.protocol_sha256
    assert receipt.run_id == request.run_id
    assert receipt.case_id == request.case_id
    assert receipt.case_manifest_sha256 == request.case_manifest_sha256
    assert receipt.variant_id == request.variant_id
    assert receipt.split == request.split.value
    assert receipt.cache_mode == contracts.CacheMode.WARM.value
    assert receipt.input_sha256 == request.input_sha256
    assert receipt.environment_sha256 == request.environment_sha256
    assert receipt.source == (*adapter.source, *request.source)
    assert receipt.prime_status == contracts.StageStatus.SUCCESS.value
    assert receipt.prime_failure_code is None
    assert receipt.measured_invoked is True
    assert receipt.measured_status == contracts.StageStatus.SUCCESS.value
    assert receipt.measured_failure_code is None
    assert receipt.measured_failure_detail_sha256 is None
    assert receipt.measured_telemetry_sha256 == invocation.telemetry.digest
    assert receipt.setup_telemetry.model_calls == 1
    assert receipt.setup_telemetry.cache_hits == 0
    assert receipt.setup_telemetry.cache_misses == 1
    assert receipt.setup_telemetry.retries == 0
    assert (
        invocation.output.effective_identity[
            cache_measurement.SYMAI_CACHE_PRIME_DIGEST_FIELD
        ]
        == receipt.receipt_sha256
    )
    assert (
        receipt.prime_semantic_output_sha256
        == cache_measurement.symai_semantic_payload_sha256(invocation)
    )

    serialized_receipt = json.dumps(
        receipt.to_dict(), sort_keys=True
    )
    assert "raw_output" not in serialized_receipt
    assert raw not in serialized_receipt

    record = adapter.record(request, invocation)
    assert cache_measurement.symai_backend_invocation_count(record) == 2
    assert (
        cache_measurement.validate_symai_warm_cache_measurement(
            record, request=request
        ).receipt_sha256
        == receipt.receipt_sha256
    )
    assert (
        cache_measurement.extract_symai_cache_setup_telemetry(record)
        == receipt.setup_telemetry
    )


def test_stage_record_binding_accepts_warm_and_rejects_warm_receipt_on_cold() -> None:
    warm_request = _request(run_id="symai-cache-record-mode")
    warm_adapter = _configured(_Engine([_structured_response()]))
    warm_invocation = (
        cache_measurement.invoke_with_symai_cache_measurement(
            warm_adapter, warm_request
        )
    )
    warm_record = warm_adapter.record(
        warm_request, warm_invocation
    )
    warm_receipt = (
        cache_measurement.validate_symai_warm_cache_measurement(
            warm_record, request=warm_request
        )
    )
    assert (
        cache_measurement.extract_symai_cache_setup_telemetry(
            warm_record, request=warm_request
        )
        == warm_receipt.setup_telemetry
    )

    cold_request = _request(
        cache_mode=contracts.CacheMode.COLD,
        run_id=warm_request.run_id,
    )
    cold_adapter = _configured(_Engine([_structured_response()]))
    cold_invocation = (
        cache_measurement.invoke_with_symai_cache_measurement(
            cold_adapter, cold_request
        )
    )
    cold_record = cold_adapter.record(
        cold_request, cold_invocation
    )
    assert (
        cache_measurement.extract_symai_cache_prime_receipt(
            cold_record, request=cold_request
        )
        is None
    )

    forged_cold = _record_with_copied_receipt(
        cold_record, warm_receipt
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="does not bind enclosing StageRecord",
    ):
        cache_measurement.extract_symai_cache_prime_receipt(
            forged_cold
        )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="does not bind enclosing StageRecord",
    ):
        cache_measurement.extract_symai_cache_setup_telemetry(
            forged_cold
        )


def test_stage_record_rejects_receipt_copied_across_coordinates() -> None:
    source_request = _request(run_id="symai-cache-record-source")
    source_adapter = _configured(_Engine([_structured_response()]))
    source_invocation = (
        cache_measurement.invoke_with_symai_cache_measurement(
            source_adapter, source_request
        )
    )
    source_record = source_adapter.record(
        source_request, source_invocation
    )
    source_receipt = (
        cache_measurement.extract_symai_cache_prime_receipt(
            source_record, request=source_request
        )
    )
    assert source_receipt is not None

    target_request = _request(run_id="symai-cache-record-target")
    target_adapter = _configured(_Engine([_structured_response()]))
    target_invocation = (
        cache_measurement.invoke_with_symai_cache_measurement(
            target_adapter, target_request
        )
    )
    target_record = target_adapter.record(
        target_request, target_invocation
    )
    copied = _record_with_copied_receipt(
        target_record, source_receipt
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="does not bind enclosing StageRecord",
    ):
        cache_measurement.extract_symai_cache_prime_receipt(copied)
    with pytest.raises(
        contracts.ProtocolContractError,
        match="does not bind enclosing StageRecord",
    ):
        cache_measurement.validate_symai_warm_cache_measurement(
            copied
        )


def test_ablation_augmented_stage_record_preserves_cache_validation() -> None:
    request = _request(run_id="symai-cache-graph-augmented")
    adapter = _configured(_Engine([_structured_response()]))
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        adapter, request
    )
    routing_policy = {
        "schema": "routing-policy.v1",
        "decision": "invoke",
        "reason": "scheduled",
        "decision_sha256": "d" * 64,
    }
    data = {
        **dict(invocation.output.data),
        "routing_policy": routing_policy,
    }
    identity = {
        **dict(invocation.output.effective_identity),
        "graph_invocation_index": 2,
        "graph_invoked": True,
        "graph_policy_reason": "scheduled",
        "consumed_artifact_sha256": (),
        "policy_decision_sha256": "d" * 64,
        "policy_decision": "invoke",
        "routing_policy": routing_policy,
    }
    augmented = adapters.StageInvocation(
        replace(
            invocation.output,
            data=data,
            effective_identity=identity,
        ),
        invocation.telemetry,
    )
    record = adapter.record(request, augmented)
    receipt = cache_measurement.validate_symai_warm_cache_measurement(
        record, request=request
    )
    assert (
        cache_measurement.symai_semantic_payload_sha256(record)
        == receipt.prime_semantic_output_sha256
    )
    assert (
        cache_measurement.symai_backend_identity_sha256(record)
        == receipt.prime_backend_identity_sha256
    )

    drifted_identity = dict(identity)
    drifted_identity["effective_model"] = "different-model"
    drifted_record = adapter.record(
        request,
        adapters.StageInvocation(
            replace(
                augmented.output,
                effective_identity=drifted_identity,
            ),
            augmented.telemetry,
        ),
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="backend identity differs",
    ):
        cache_measurement.validate_symai_warm_cache_measurement(
            drifted_record, request=request
        )


@pytest.mark.parametrize(
    ("field", "drifted"),
    [
        ("effective_provider", "different-provider"),
        ("effective_model", "different-model"),
        ("backend_revision", "different-revision"),
    ],
)
def test_measured_backend_identity_drift_fails_but_cache_metadata_is_operational(
    field: str,
    drifted: str,
) -> None:
    request = _request(run_id=f"symai-cache-identity-{field}")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([_structured_response()])),
        request,
    )
    receipt = cache_measurement.validate_symai_warm_cache_measurement(
        invocation,
        request=request,
    )

    drifted_identity = dict(invocation.output.effective_identity)
    drifted_identity[field] = drifted
    drifted_invocation = adapters.StageInvocation(
        replace(
            invocation.output,
            effective_identity=drifted_identity,
        ),
        invocation.telemetry,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="backend identity differs",
    ):
        cache_measurement.validate_symai_warm_cache_measurement(
            drifted_invocation,
            request=request,
        )

    operational_identity = dict(
        invocation.output.effective_identity
    )
    operational_identity.update(
        {
            "cache_hit": False,
            "cache_namespace": "operationally-different",
            "cache_key": "operationally-different",
            "router_cache": "different-mode",
            "router_cache_key": "different-router-key",
            "router_cached_backend": "operational-cache-copy",
            "attempts": 99,
            "retries": 98,
        }
    )
    operational_invocation = adapters.StageInvocation(
        replace(
            invocation.output,
            effective_identity=operational_identity,
        ),
        invocation.telemetry,
    )
    assert (
        cache_measurement.validate_symai_warm_cache_measurement(
            operational_invocation,
            request=request,
        ).receipt_sha256
        == receipt.receipt_sha256
    )
    assert (
        cache_measurement.symai_backend_identity_sha256(
            operational_invocation
        )
        == receipt.prime_backend_identity_sha256
    )


@pytest.mark.parametrize(
    "drifted_identity",
    [
        {"cache_backend_revision": "untrusted-drift"},
        {"router_cache_backend_revision": "untrusted-drift"},
        {"cache-hit": False},
        {"route": {"cache_hit": False}},
        {"route": {"router_cache": "untrusted-drift"}},
    ],
)
def test_unknown_or_nested_cache_named_identity_claims_fail_closed(
    drifted_identity: dict[str, object],
) -> None:
    request = _request(run_id="symai-cache-unknown-identity")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([_structured_response()])),
        request,
    )
    identity = {
        **dict(invocation.output.effective_identity),
        **drifted_identity,
    }
    drifted = adapters.StageInvocation(
        replace(
            invocation.output,
            effective_identity=identity,
        ),
        invocation.telemetry,
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="backend identity differs",
    ):
        cache_measurement.validate_symai_warm_cache_measurement(
            drifted,
            request=request,
        )


def test_forged_failed_setup_receipt_cannot_validate_as_a_warm_hit() -> None:
    request = _request(run_id="symai-cache-forged-failed-setup")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([_structured_response()])),
        request,
    )
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation, request=request
    )
    assert receipt is not None
    forged = receipt.to_dict()
    forged.update(
        {
            "prime_status": contracts.StageStatus.FAILED.value,
            "prime_failure_code": (
                contracts.FailureCode.CACHE_CONTAMINATION.value
            ),
            "prime_failure_detail_sha256": "c" * 64,
        }
    )
    tampered = _replace_embedded_receipt(
        invocation, _rehash_receipt(forged)
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="did not bind a successful setup",
    ):
        cache_measurement.validate_symai_warm_cache_measurement(
            tampered, request=request
        )


@pytest.mark.parametrize(
    "telemetry_update",
    [
        {"model_calls": 0},
        {"cache_hits": 1},
        {"cache_misses": 0},
        {"cache_misses": 2},
    ],
)
def test_forged_non_miss_setup_telemetry_cannot_validate(
    telemetry_update: dict[str, object],
) -> None:
    request = _request(run_id="symai-cache-forged-setup-telemetry")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([_structured_response()])),
        request,
    )
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation, request=request
    )
    assert receipt is not None
    forged = receipt.to_dict()
    setup = dict(forged["setup_telemetry"])
    setup.update(telemetry_update)
    setup_record = contracts.TelemetryRecord.from_dict(setup)
    forged["setup_telemetry"] = setup_record.to_dict()
    forged["setup_telemetry_sha256"] = setup_record.digest
    tampered = _replace_embedded_receipt(
        invocation, _rehash_receipt(forged)
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="setup telemetry is not an exact miss",
    ):
        cache_measurement.validate_symai_warm_cache_measurement(
            tampered, request=request
        )


def test_nested_cache_and_telemetry_candidate_fields_remain_semantic() -> None:
    request = _request(run_id="symai-cache-nested-semantic")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([_structured_response()])),
        request,
    )
    receipt = cache_measurement.validate_symai_warm_cache_measurement(
        invocation, request=request
    )

    data = dict(invocation.output.data)
    candidate_ir = dict(data["candidate_ir"])
    candidate_ir["cache"] = {"policy": "changed-semantic-policy"}
    candidate_ir["telemetry"] = {
        "meaning": "changed-semantic-measure"
    }
    data["candidate_ir"] = candidate_ir
    assert (
        cache_measurement.symai_semantic_payload_sha256(data)
        != receipt.prime_semantic_output_sha256
    )
    tampered = adapters.StageInvocation(
        replace(invocation.output, data=data),
        invocation.telemetry,
    )
    with pytest.raises(
        contracts.ProtocolContractError,
        match="semantic output differs",
    ):
        cache_measurement.validate_symai_warm_cache_measurement(
            tampered, request=request
        )

    top_level_operational = dict(invocation.output.data)
    top_level_operational["telemetry"] = {
        "cache_hits": 100,
        "cache_misses": 100,
    }
    top_level_operational["cache_prime_future"] = {
        "setup_only": True
    }
    assert (
        cache_measurement.symai_semantic_payload_sha256(
            top_level_operational
        )
        == receipt.prime_semantic_output_sha256
    )


def test_cold_unconfigured_disabled_and_non_symai_paths_are_single_call_na() -> None:
    cold_engine = _Engine([_structured_response()])
    cold = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(cold_engine),
        _request(
            cache_mode=contracts.CacheMode.COLD,
            run_id="symai-cache-cold",
        ),
    )
    assert len(cold_engine.calls) == 1
    assert (
        cache_measurement.extract_symai_cache_prime_receipt(cold)
        is None
    )

    injected_calls: list[str] = []
    injected = cache_measurement.invoke_with_symai_cache_measurement(
        adapters.SymaiAdapter(
            lambda request: (
                injected_calls.append(request.case_id)
                or {"candidate": "injected"}
            )
        ),
        _request(run_id="symai-cache-injected"),
    )
    assert injected_calls == ["case-cache-001"]
    assert (
        cache_measurement.extract_symai_cache_prime_receipt(injected)
        is None
    )

    disabled_engine = _Engine([_structured_response()])
    disabled = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(disabled_engine, cache_enabled=False),
        _request(run_id="symai-cache-disabled"),
    )
    assert len(disabled_engine.calls) == 1
    assert (
        cache_measurement.extract_symai_cache_prime_receipt(disabled)
        is None
    )

    dry_run = cache_measurement.invoke_with_symai_cache_measurement(
        adapters.SymaiAdapter(
            config=adapters.SymaiAdapterConfig(
                model="Leanstral-119B",
                dry_run=True,
            ),
            engine_factory=lambda *_args: pytest.fail(
                "dry run must not load an engine"
            ),
        ),
        _request(run_id="symai-cache-dry-run"),
    )
    assert dry_run.output.status is contracts.StageStatus.SUCCESS
    assert (
        cache_measurement.extract_symai_cache_prime_receipt(dry_run)
        is None
    )

    non_symai_calls: list[str] = []
    non_symai = cache_measurement.invoke_with_symai_cache_measurement(
        adapters.StageAdapter(
            contracts.StageName.COMPILER,
            lambda request: (
                non_symai_calls.append(request.case_id)
                or {"candidate": "compiler"}
            ),
        ),
        _request(run_id="symai-cache-compiler"),
    )
    assert non_symai_calls == ["case-cache-001"]
    assert (
        cache_measurement.extract_symai_cache_prime_receipt(non_symai)
        is None
    )

    leanstral_calls: list[str] = []
    leanstral = cache_measurement.invoke_with_symai_cache_measurement(
        adapters.LeanstralAdapter(
            lambda request: (
                leanstral_calls.append(request.case_id)
                or {"candidate": "leanstral"}
            )
        ),
        _request(run_id="symai-cache-leanstral"),
    )
    assert leanstral_calls == ["case-cache-001"]
    assert (
        cache_measurement.extract_symai_cache_prime_receipt(leanstral)
        is None
    )


def test_prime_failure_is_retained_and_never_invoked_twice() -> None:
    raw = "not-valid-structured-json"
    engine = _Engine([raw, _structured_response()])
    request = _request(run_id="symai-cache-prime-failure")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(engine),
        request,
    )

    assert len(engine.calls) == 1
    assert invocation.output.status is contracts.StageStatus.FAILED
    assert (
        invocation.output.failure_code
        is contracts.FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE
    )
    # No measured invocation occurred; actual setup resources live solely in
    # the receipt so downstream totals cannot double-count them.
    assert invocation.telemetry.model_calls == 0
    assert invocation.telemetry.cache_hits == 0
    assert invocation.telemetry.cache_misses == 0
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation, request=request
    )
    assert receipt is not None
    assert receipt.prime_status == contracts.StageStatus.FAILED.value
    assert receipt.prime_failure_code == (
        contracts.FailureCode.SYMAI_CONTRACT_OR_JSON_FAILURE.value
    )
    assert receipt.prime_failure_detail_sha256 is not None
    assert receipt.measured_invoked is False
    assert receipt.measured_status is None
    assert receipt.measured_failure_code is None
    assert receipt.measured_failure_detail_sha256 is None
    assert receipt.measured_telemetry_sha256 is None
    assert receipt.setup_telemetry.model_calls == 1
    assert receipt.setup_telemetry.cache_misses == 1
    assert raw not in json.dumps(receipt.to_dict(), sort_keys=True)
    record = _configured(_Engine([_structured_response()])).record(
        request,
        invocation,
    )
    assert cache_measurement.symai_backend_invocation_count(record) == 1
    direct_aggregate = metrics.aggregate_case_results(
        (contracts.CaseResultRecord.from_stages((record,)),)
    )
    assert (
        direct_aggregate.resource_lane_measurements["model"][
            "stage_count"
        ]
        == 1
    )
    _assert_metrics_backend_invocation_count(
        _graph_bound_result(record),
        expected=1,
    )


def test_expired_deadline_after_prime_prevents_measured_call() -> None:
    engine = _Engine(
        [_structured_response(), _structured_response()]
    )
    request = _request(
        run_id="symai-cache-expired-after-prime",
        deadline_unix_ms=1,
    )
    adapter = _configured(engine)
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        adapter, request
    )

    assert len(engine.calls) == 1
    assert invocation.output.status is contracts.StageStatus.FAILED
    assert invocation.output.failure_code is (
        contracts.FailureCode.RESOURCE_LEASE_CANCELLATION
    )
    assert "deadline expired after setup" in (
        invocation.output.failure_detail or ""
    )
    assert invocation.telemetry.model_calls == 0
    assert invocation.telemetry.cache_hits == 0
    assert invocation.telemetry.cache_misses == 0
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation, request=request
    )
    assert receipt is not None
    assert receipt.prime_status == contracts.StageStatus.SUCCESS.value
    assert receipt.measured_invoked is False
    assert receipt.measured_status is None
    assert receipt.measured_telemetry_sha256 is None
    assert receipt.setup_telemetry.model_calls == 1
    assert receipt.setup_telemetry.cache_hits == 0
    assert receipt.setup_telemetry.cache_misses == 1

    record = adapter.record(request, invocation)
    assert cache_measurement.symai_backend_invocation_count(record) == 1
    assert (
        cache_measurement.extract_symai_cache_setup_telemetry(
            record, request=request
        )
        == receipt.setup_telemetry
    )


def test_second_miss_fails_closed_as_cache_contamination() -> None:
    engine = _Engine(
        [_structured_response(), _structured_response()]
    )
    request = _request(run_id="symai-cache-second-miss")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(engine, cache=_DiscardingCache()),
        request,
    )

    assert len(engine.calls) == 2
    assert invocation.output.status is contracts.StageStatus.FAILED
    assert (
        invocation.output.failure_code
        is contracts.FailureCode.CACHE_CONTAMINATION
    )
    assert invocation.telemetry.model_calls == 1
    assert invocation.telemetry.cache_hits == 0
    assert invocation.telemetry.cache_misses == 1
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation, request=request
    )
    assert receipt is not None
    assert receipt.prime_status == contracts.StageStatus.SUCCESS.value
    assert receipt.measured_invoked is True
    assert receipt.measured_status == contracts.StageStatus.SUCCESS.value
    assert receipt.measured_telemetry_sha256 == invocation.telemetry.digest
    assert receipt.setup_telemetry.model_calls == 1
    assert receipt.setup_telemetry.cache_misses == 1
    record = _configured(_Engine([_structured_response()])).record(
        request,
        invocation,
    )
    assert cache_measurement.symai_backend_invocation_count(record) == 2


def test_attempted_measured_failure_with_zero_cache_counters_counts_twice() -> None:
    engine = _Engine([_structured_response()])
    request = _request(run_id="symai-cache-measured-failure")
    adapter = _configured(engine)
    original_handler = adapter.handler
    assert original_handler is not None
    handler_calls = 0

    def fail_second(request: adapters.StageRequest) -> object:
        nonlocal handler_calls
        handler_calls += 1
        if handler_calls == 2:
            raise RuntimeError("synthetic measured-call failure")
        return original_handler(request)

    object.__setattr__(adapter, "handler", fail_second)
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        adapter,
        request,
    )

    assert handler_calls == 2
    assert len(engine.calls) == 1
    assert invocation.output.status is contracts.StageStatus.FAILED
    assert invocation.output.failure_code is (
        contracts.FailureCode.CACHE_CONTAMINATION
    )
    assert invocation.telemetry.cache_hits == 0
    assert invocation.telemetry.cache_misses == 0
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation,
        request=request,
    )
    assert receipt is not None
    assert receipt.measured_invoked is True
    assert receipt.measured_status == contracts.StageStatus.FAILED.value
    assert receipt.measured_failure_code == (
        contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE.value
    )
    assert receipt.measured_failure_detail_sha256 is not None
    assert receipt.measured_telemetry_sha256 == invocation.telemetry.digest
    record = adapter.record(request, invocation)
    assert cache_measurement.symai_backend_invocation_count(record) == 2
    direct_aggregate = metrics.aggregate_case_results(
        (contracts.CaseResultRecord.from_stages((record,)),)
    )
    assert (
        direct_aggregate.resource_lane_measurements["model"][
            "stage_count"
        ]
        == 2
    )
    _assert_metrics_backend_invocation_count(
        _graph_bound_result(record),
        expected=2,
    )


def test_rehashed_receipt_cannot_hide_an_invoked_measurement() -> None:
    request = _request(run_id="symai-cache-hidden-measurement")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([_structured_response()])),
        request,
    )
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation,
        request=request,
    )
    assert receipt is not None
    forged = receipt.to_dict()
    forged.update(
        {
            "measured_invoked": False,
            "measured_status": None,
            "measured_failure_code": None,
            "measured_failure_detail_sha256": None,
            "measured_telemetry_sha256": None,
        }
    )
    tampered = _replace_embedded_receipt(
        invocation,
        _rehash_receipt(forged),
    )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="does not bind enclosing StageOutput",
    ):
        cache_measurement.extract_symai_cache_prime_receipt(
            tampered,
            request=request,
        )


def test_receipt_tampering_is_rejected() -> None:
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([_structured_response()])),
        _request(run_id="symai-cache-tamper"),
    )
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation
    )
    assert receipt is not None

    changed_telemetry = receipt.to_dict()
    setup = dict(changed_telemetry["setup_telemetry"])
    setup["model_calls"] = 99
    changed_telemetry["setup_telemetry"] = setup
    with pytest.raises(
        contracts.ProtocolContractError,
        match="telemetry digest mismatch",
    ):
        cache_measurement.validate_symai_cache_prime_receipt(
            changed_telemetry
        )

    changed_digest = receipt.to_dict()
    changed_digest["receipt_sha256"] = "0" * 64
    with pytest.raises(
        contracts.ProtocolContractError,
        match="receipt digest mismatch",
    ):
        cache_measurement.validate_symai_cache_prime_receipt(
            changed_digest
        )

    with pytest.raises(
        contracts.ProtocolContractError,
        match="does not bind the supplied request",
    ):
        cache_measurement.validate_symai_cache_prime_receipt(
            receipt,
            request=_request(run_id="different-cache-run"),
        )


def test_setup_resource_extraction_is_exact_and_semantic_projection_is_stable() -> None:
    raw = _structured_response()
    request = _request(run_id="symai-cache-resources")
    invocation = cache_measurement.invoke_with_symai_cache_measurement(
        _configured(_Engine([raw])),
        request,
    )
    receipt = cache_measurement.extract_symai_cache_prime_receipt(
        invocation, request=request
    )
    setup = cache_measurement.extract_symai_cache_setup_telemetry(
        invocation, request=request
    )

    assert receipt is not None
    assert setup is not None
    assert setup.to_dict() == receipt.setup_telemetry.to_dict()
    assert setup.digest == receipt.setup_telemetry_sha256
    assert setup.wall_time_ms == receipt.setup_telemetry.wall_time_ms
    assert setup.peak_memory_bytes == (
        receipt.setup_telemetry.peak_memory_bytes
    )
    assert setup.model_calls == 1
    assert setup.retries == 0
    assert setup.cache_hits == 0
    assert setup.cache_misses == 1

    data = dict(invocation.output.data)
    data["cache_prime_future_operational_field"] = {
        "secret": "must-not-affect-semantic-digest"
    }
    assert (
        cache_measurement.symai_semantic_payload_sha256(data)
        == receipt.prime_semantic_output_sha256
    )
    nested = dict(data["semantic_context"])
    nested["cache_prime"] = {
        "future": "nested-fields-remain-semantic"
    }
    data["semantic_context"] = nested
    assert (
        cache_measurement.symai_semantic_payload_sha256(data)
        != receipt.prime_semantic_output_sha256
    )
    receipt_json = json.dumps(receipt.to_dict(), sort_keys=True)
    assert raw not in receipt_json
    assert "raw_output" not in receipt_json

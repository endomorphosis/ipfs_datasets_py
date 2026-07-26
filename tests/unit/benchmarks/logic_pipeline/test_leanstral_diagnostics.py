"""Focused tests for the additive Leanstral diagnostic projection."""

from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json

import pytest

from benchmarks.logic_pipeline import contracts
from benchmarks.logic_pipeline.adapters import (
    LEANSTRAL_GENERATION_FAILURE_SCHEMA,
)
from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.logic_pipeline.leanstral_diagnostics import (
    LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES,
    LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES,
    LeanstralDiagnosticError,
    build_leanstral_diagnostic_projection,
    validate_leanstral_diagnostic_projection,
)


SHA_MANIFEST = "a" * 64
SHA_ENVIRONMENT = "b" * 64
SHA_INPUT = "c" * 64
SHA_KERNEL = "d" * 64
SHA_REQUEST = "e" * 64


def _failure_data(
    safe_class: str,
    phase: str,
    *,
    corrupt_boundary_digest: bool = False,
) -> tuple[dict[str, object], str]:
    body: dict[str, object] = {
        "schema": LEANSTRAL_GENERATION_FAILURE_SCHEMA,
        "safe_failure_class": safe_class,
        "phase": phase,
        "http_status": None,
        "request_payload_sha256": SHA_REQUEST,
    }
    receipt_sha256 = hashlib.sha256(
        contracts.canonical_json(body).encode("utf-8")
    ).hexdigest()
    boundary = {
        **body,
        "receipt_sha256": (
            "f" * 64 if corrupt_boundary_digest else receipt_sha256
        ),
    }
    return (
        {
            "schema": LEANSTRAL_GENERATION_FAILURE_SCHEMA,
            "safe_failure_class": safe_class,
            "request_input_sha256": SHA_INPUT,
            "generation_failure_boundary": boundary,
        },
        receipt_sha256,
    )


def _result(
    case_id: str,
    *,
    safe_class: str | None = None,
    phase: str = "provider",
    wall_time_ms: float = 1.0,
    kernel_accepted: bool = False,
    graph_invoked: bool | None = True,
    corrupt_boundary_digest: bool = False,
    legacy_failure_code: contracts.FailureCode | None = None,
    success_data: object | None = None,
) -> contracts.CaseResultRecord:
    effective_identity: dict[str, object] = {
        "implementation": "leanstral-test",
    }
    if graph_invoked is not None:
        effective_identity["graph_invoked"] = graph_invoked

    if safe_class is None:
        status = contracts.StageStatus.SUCCESS
        failure_code = None
        failure_detail = None
        data = (
            {"candidate": "synthetic"}
            if success_data is None
            else success_data
        )
    else:
        data, receipt_sha256 = _failure_data(
            safe_class,
            phase,
            corrupt_boundary_digest=corrupt_boundary_digest,
        )
        effective_identity.update(
            {
                "leanstral_safe_failure_class": safe_class,
                "leanstral_failure_boundary_sha256": receipt_sha256,
            }
        )
        if safe_class == "unavailable":
            status = contracts.StageStatus.UNAVAILABLE
            expected_code = contracts.FailureCode.CAPABILITY_UNAVAILABLE
        else:
            status = contracts.StageStatus.FAILED
            expected_code = (
                contracts.FailureCode
                .LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT
            )
        failure_code = legacy_failure_code or expected_code
        failure_detail = f"synthetic {safe_class}"

    leanstral = contracts.StageRecord.create(
        protocol_sha256=contracts.DEFAULT_PROTOCOL_SHA256,
        run_id="diagnostic-run",
        case_id=case_id,
        case_manifest_sha256=SHA_MANIFEST,
        variant_id="A3",
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        stage=contracts.StageName.LEANSTRAL,
        adapter_version="1",
        status=status,
        provenance=contracts.StageProvenance(
            schema=contracts.STAGE_PROVENANCE_SCHEMA,
            adapter_id="leanstral-adapter",
            adapter_version="1",
            source=("synthetic-diagnostic-test",),
            requested_identity={"provider": "synthetic"},
            effective_identity=effective_identity,
            input_sha256=SHA_INPUT,
            environment_sha256=SHA_ENVIRONMENT,
        ),
        telemetry=contracts.TelemetryRecord(
            wall_time_ms=wall_time_ms,
            input_items=1,
            output_items=int(status is contracts.StageStatus.SUCCESS),
            model_calls=int(graph_invoked is True),
            resource_lane=contracts.ResourceLane.MODEL,
        ),
        data=data,
        failure_code=failure_code,
        failure_detail=failure_detail,
    )
    kernel = contracts.StageRecord.create(
        protocol_sha256=contracts.DEFAULT_PROTOCOL_SHA256,
        run_id="diagnostic-run",
        case_id=case_id,
        case_manifest_sha256=SHA_MANIFEST,
        variant_id="A3",
        split=contracts.Split.PILOT,
        cache_mode=contracts.CacheMode.COLD,
        stage=contracts.StageName.KERNEL,
        adapter_version="1",
        status=contracts.StageStatus.SUCCESS,
        provenance=contracts.StageProvenance(
            schema=contracts.STAGE_PROVENANCE_SCHEMA,
            adapter_id="kernel-adapter",
            adapter_version="1",
            source=("synthetic-diagnostic-test",),
            requested_identity={"implementation": "synthetic-kernel"},
            effective_identity={
                "implementation": "synthetic-kernel",
                "graph_invoked": True,
            },
            input_sha256=SHA_INPUT,
            environment_sha256=SHA_ENVIRONMENT,
            upstream_stage_digests=(leanstral.digest,),
        ),
        telemetry=contracts.TelemetryRecord(
            wall_time_ms=0.5,
            input_items=1,
            output_items=1,
            resource_lane=contracts.ResourceLane.KERNEL,
        ),
        data={"accepted": kernel_accepted},
        kernel_accepted=kernel_accepted,
        kernel_receipt_sha256=SHA_KERNEL if kernel_accepted else None,
    )
    return contracts.CaseResultRecord.from_stages((leanstral, kernel))


def _recid(value: dict[str, object]) -> dict[str, object]:
    body = copy.deepcopy(value)
    body.pop("receipt_cid")
    return {**body, "receipt_cid": cid_for_dag_json(body)}


def test_projection_covers_every_safe_class_without_sensitive_data() -> None:
    phases = tuple(LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES)
    failures = [
        _result(
            f"class-{index}",
            safe_class=safe_class,
            phase=phases[index % len(phases)],
            wall_time_ms=float(index) + 0.25,
        )
        for index, safe_class in enumerate(
            LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES,
            start=1,
        )
    ]
    secret_case_id = "sensitive-success"
    success = _result(
        secret_case_id,
        success_data={
            "prompt": "DO-NOT-SERIALIZE-PROMPT",
            "response": "DO-NOT-SERIALIZE-RESPONSE",
            "case_text": "DO-NOT-SERIALIZE-CASE-TEXT",
        },
    )

    receipt = build_leanstral_diagnostic_projection([*failures, success])

    assert receipt["source_result_count"] == 9
    assert receipt["invocation_count"] == 9
    assert receipt["success_count"] == 1
    assert receipt["failure_count"] == 8
    assert receipt["recovered_failure_count"] == 0
    assert receipt["terminal_failure_count"] == 8
    assert receipt["safe_failure_class_counts"] == {
        safe_class: 1
        for safe_class in LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES
    }
    assert receipt["failure_phase_counts"] == {
        phase: Counter(
            phases[index % len(phases)]
            for index in range(
                1,
                len(LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES) + 1,
            )
        )[phase]
        for phase in LEANSTRAL_DIAGNOSTIC_FAILURE_PHASES
    }
    assert receipt["wall_time_ms_by_safe_failure_class"] == {
        safe_class: float(index) + 0.25
        for index, safe_class in enumerate(
            LEANSTRAL_DIAGNOSTIC_SAFE_FAILURE_CLASSES,
            start=1,
        )
    }

    encoded = json.dumps(receipt, sort_keys=True)
    for forbidden in (
        secret_case_id,
        "DO-NOT-SERIALIZE-PROMPT",
        "DO-NOT-SERIALIZE-RESPONSE",
        "DO-NOT-SERIALIZE-CASE-TEXT",
    ):
        assert forbidden not in encoded
    assert not any(
        token in encoded.casefold()
        for token in ("raw_output", "source_text", "case_id")
    )


def test_projection_partitions_recovered_terminal_and_suppressed_stages() -> None:
    recovered = _result(
        "recovered",
        safe_class="timed_out",
        phase="completion_request",
        wall_time_ms=120.5,
        kernel_accepted=True,
    )
    terminal = _result(
        "terminal",
        safe_class="timed_out",
        phase="completion_request",
        wall_time_ms=80.25,
    )
    success = _result("success", wall_time_ms=4.0)
    suppressed = _result(
        "suppressed",
        graph_invoked=False,
        wall_time_ms=0.0,
    )

    receipt = build_leanstral_diagnostic_projection(
        (recovered, terminal, success, suppressed)
    )

    assert recovered.recovered_failure_codes == (
        contracts.FailureCode
        .LEANSTRAL_TIMEOUT_SCHEMA_OR_FORBIDDEN_CONSTRUCT,
    )
    assert receipt["source_result_count"] == 4
    assert receipt["invocation_count"] == 3
    assert receipt["success_count"] == 1
    assert receipt["failure_count"] == 2
    assert receipt["recovered_failure_count"] == 1
    assert receipt["terminal_failure_count"] == 1
    assert receipt["safe_failure_class_counts"]["timed_out"] == 2
    assert (
        receipt["wall_time_ms_by_safe_failure_class"]["timed_out"]
        == 200.75
    )


def test_projection_is_content_addressed_and_source_recomputed() -> None:
    sources = (
        _result(
            "content-addressed",
            safe_class="length_exhausted",
            phase="completion_response",
            wall_time_ms=42.0,
        ),
    )
    receipt = build_leanstral_diagnostic_projection(sources)
    body = copy.deepcopy(receipt)
    supplied_cid = body.pop("receipt_cid")

    assert supplied_cid == cid_for_dag_json(body)
    assert validate_leanstral_diagnostic_projection(receipt, sources) == receipt

    changed_wall = copy.deepcopy(receipt)
    changed_wall["wall_time_ms_by_safe_failure_class"][
        "length_exhausted"
    ] = 41.0
    with pytest.raises(
        LeanstralDiagnosticError,
        match="content address changed",
    ):
        validate_leanstral_diagnostic_projection(changed_wall, sources)

    rebound_wall = _recid(changed_wall)
    with pytest.raises(
        LeanstralDiagnosticError,
        match="differs from its source results",
    ):
        validate_leanstral_diagnostic_projection(rebound_wall, sources)

    changed_source = copy.deepcopy(receipt)
    changed_source["source_results_cid"] = cid_for_dag_json(
        {"different": "validated-source-set"}
    )
    changed_source = _recid(changed_source)
    with pytest.raises(
        LeanstralDiagnosticError,
        match="differs from its source results",
    ):
        validate_leanstral_diagnostic_projection(changed_source, sources)


@pytest.mark.parametrize(
    "mutator",
    (
        lambda value: value["safe_failure_class_counts"].update(
            {"unknown": 0}
        ),
        lambda value: value["failure_phase_counts"].pop("provider"),
        lambda value: value.update({"failure_count": 0}),
        lambda value: value.update({"prompt": "must-not-appear"}),
    ),
)
def test_projection_rejects_shape_and_total_tampering(mutator) -> None:
    sources = (
        _result(
            "shape",
            safe_class="provider_error",
            phase="provider",
        ),
    )
    receipt = build_leanstral_diagnostic_projection(sources)
    changed = copy.deepcopy(receipt)
    mutator(changed)
    changed = _recid(changed)

    with pytest.raises(LeanstralDiagnosticError):
        validate_leanstral_diagnostic_projection(changed, sources)


@pytest.mark.parametrize(
    ("result", "message"),
    (
        (
            lambda: _result(
                "bad-boundary",
                safe_class="malformed_response",
                phase="proposal_validation",
                corrupt_boundary_digest=True,
            ),
            "boundary content address changed",
        ),
        (
            lambda: _result(
                "bad-legacy-code",
                safe_class="timed_out",
                phase="completion_request",
                legacy_failure_code=(
                    contracts.FailureCode.BENCHMARK_INFRASTRUCTURE_FAILURE
                ),
            ),
            "legacy failure contract",
        ),
        (
            lambda: _result(
                "missing-graph-marker",
                graph_invoked=None,
            ),
            "omitted its graph invocation decision",
        ),
    ),
)
def test_projection_rejects_invalid_source_provenance(
    result,
    message: str,
) -> None:
    with pytest.raises(LeanstralDiagnosticError, match=message):
        build_leanstral_diagnostic_projection((result(),))


def test_projection_rejects_empty_and_duplicate_sources() -> None:
    source = _result("duplicate")

    with pytest.raises(LeanstralDiagnosticError, match="nonempty"):
        build_leanstral_diagnostic_projection(())
    with pytest.raises(LeanstralDiagnosticError, match="duplicate"):
        build_leanstral_diagnostic_projection((source, source))

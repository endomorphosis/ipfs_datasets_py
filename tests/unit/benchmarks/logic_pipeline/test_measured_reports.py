"""Receipt-driven evidence for measured front-end and proof reports."""

from __future__ import annotations

import copy
import hashlib
from typing import Mapping

import pytest

from benchmarks.logic_pipeline import frontend_report, report
from benchmarks.logic_pipeline.cases import FROZEN_CORPUS_MANIFEST_SHA256
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    STAGE_PROVENANCE_SCHEMA,
    CacheMode,
    CaseResultRecord,
    FailureCode,
    ResourceLane,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)
from benchmarks.logic_pipeline.variants import VARIANT_REGISTRY


RUN_ID = "measured-report-test"
ENVIRONMENT = "e" * 64
INPUT = "f" * 64
MANIFEST = FROZEN_CORPUS_MANIFEST_SHA256


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_RESOURCE_LANE = {
    StageName.COMPILER: ResourceLane.CPU,
    StageName.SPACY: ResourceLane.CPU,
    StageName.SYMAI: ResourceLane.MODEL,
    StageName.HAMMER: ResourceLane.SOLVER,
    StageName.LEANSTRAL: ResourceLane.MODEL,
    StageName.KERNEL: ResourceLane.KERNEL,
}


def _case_result(
    *,
    case_id: str,
    variant_id: str,
    split: Split,
    cache_mode: CacheMode,
    semantic_ir: Mapping[str, object] | None = None,
    unavailable: bool = False,
    suppress_symai: bool = False,
) -> CaseResultRecord:
    stages: list[StageRecord] = []
    route = VARIANT_REGISTRY[variant_id].stages
    if unavailable:
        route = route[:1]
    for stage_name in route:
        if stage_name is StageName.COMPILER:
            stage_data: Mapping[str, object] = {
                "modal_ir_sha256": hashlib.sha256(
                    canonical_json(semantic_ir or {}).encode("utf-8")
                ).hexdigest()
            }
        elif stage_name is StageName.SPACY:
            stage_data = {"modal_ir": semantic_ir or {"kind": "proof-test"}}
        elif stage_name is StageName.SYMAI:
            stage_data = {
                "candidate_ir": semantic_ir or {"kind": "proof-test"}
            }
        elif stage_name is StageName.HAMMER:
            stage_data = {
                "proof_candidate": None,
                "reconstruction": None,
            }
        elif stage_name is StageName.LEANSTRAL:
            stage_data = {
                "draft": {"proof": "by assumption"},
                "repair_attempts": 0,
            }
        else:
            receipt_body = {
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "native-kernel-receipt.v1"
                ),
                "protocol_sha256": DEFAULT_PROTOCOL_SHA256,
                "run_id": RUN_ID,
                "case_id": case_id,
                "case_manifest_sha256": MANIFEST,
                "variant_id": variant_id,
                "split": split.value,
                "cache_mode": cache_mode.value,
                "input_sha256": INPUT,
                "environment_sha256": ENVIRONMENT,
                "independent": True,
                "accepted": False,
                "active_process_count": 0,
                "reason": "no_proof_candidate",
            }
            stage_data = {
                **receipt_body,
                "receipt_sha256": hashlib.sha256(
                    canonical_json(receipt_body).encode("utf-8")
                ).hexdigest(),
            }
        stage_unavailable = unavailable and not stages
        graph_invoked = not (
            stage_name is StageName.SYMAI and suppress_symai
        )
        if not graph_invoked:
            stage_data = {
                "schema": (
                    "ipfs-datasets.logic-pipeline-benchmark."
                    "policy-decision.v1"
                ),
                "stage": "symai",
                "invoked": False,
                "reason": "frontend_ambiguity_gate_closed",
            }
        stages.append(
            StageRecord.create(
                protocol_sha256=DEFAULT_PROTOCOL_SHA256,
                run_id=RUN_ID,
                case_id=case_id,
                case_manifest_sha256=MANIFEST,
                variant_id=variant_id,
                split=split,
                cache_mode=cache_mode,
                stage=stage_name,
                adapter_version="1",
                status=(
                    StageStatus.UNAVAILABLE
                    if stage_unavailable
                    else StageStatus.SUCCESS
                ),
                provenance=StageProvenance(
                    schema=STAGE_PROVENANCE_SCHEMA,
                    adapter_id=f"{stage_name.value}-adapter",
                    adapter_version="1",
                    source=("measured-report-test",),
                    requested_identity={"component": stage_name.value},
                    effective_identity={
                        "component": stage_name.value,
                        "graph_invoked": graph_invoked,
                    },
                    input_sha256=INPUT,
                    environment_sha256=ENVIRONMENT,
                    upstream_stage_digests=tuple(
                        item.digest for item in stages
                    ),
                ),
                telemetry=TelemetryRecord(
                    wall_time_ms=2.5,
                    cpu_time_ms=1.0,
                    peak_memory_bytes=128,
                    input_items=1,
                    output_items=0 if stage_unavailable else 1,
                    model_calls=int(
                        not stage_unavailable
                        and graph_invoked
                        and stage_name
                        in {StageName.SYMAI, StageName.LEANSTRAL}
                    ),
                    resource_lane=_RESOURCE_LANE[stage_name],
                ),
                data={} if stage_unavailable else stage_data,
                failure_code=(
                    FailureCode.CAPABILITY_UNAVAILABLE
                    if stage_unavailable
                    else None
                ),
                failure_detail=(
                    "requested capability is unavailable"
                    if stage_unavailable
                    else None
                ),
            ),
        )
    return CaseResultRecord.from_stages(stages)


def _frontend_capabilities() -> dict[str, object]:
    return {
        name: {"status": "available", "reason": ""}
        for name in frontend_report.CAPABILITY_KEYS
    }


def _proof_capabilities() -> dict[str, object]:
    return {
        name: {"status": "available", "reason": ""}
        for name in report.CAPABILITY_KEYS
    }


def _frontend_observations(
    *,
    unavailable_coordinate: tuple[str, str, str, str] | None = None,
    suppressed_symai_coordinate: tuple[str, str, str, str] | None = None,
) -> list[dict[str, object]]:
    value = frontend_report.create_capability_preflight_report()
    catalog, _ = frontend_report._case_catalog()
    rows = copy.deepcopy(value["observations"])
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        coordinate = (
            str(row["split"]),
            str(row["cache_mode"]),
            str(row["variant_id"]),
            str(row["case_id"]),
        )
        missing = coordinate == unavailable_coordinate
        case = catalog[str(row["case_id"])]
        signature = hashlib.sha256(
            canonical_json(case["expected_ir"]).encode("utf-8")
        ).hexdigest()
        result = _case_result(
            case_id=str(row["case_id"]),
            variant_id=str(row["variant_id"]),
            split=Split(str(row["split"])),
            cache_mode=CacheMode(str(row["cache_mode"])),
            semantic_ir=case["expected_ir"],
            unavailable=missing,
            suppress_symai=coordinate == suppressed_symai_coordinate,
        )
        row.update(
            {
                "status": "unavailable" if missing else "semantically_correct",
                "source_receipt_sha256": result.digest,
                "case_result": result.to_dict(),
                "semantic_signature_sha256": None if missing else signature,
                "normalized_ir_exact_match": None if missing else True,
                "deterministic_semantic_equivalence": (
                    None if missing else False
                ),
                "semantic_validator_receipt_sha256": (
                    None
                    if missing
                    else _sha(f"{result.digest}:semantic-validator")
                ),
                "predicted_class": (
                    None if missing else row["expected_class"]
                ),
                "ambiguity_classification_correct": (
                    None
                    if missing or row["expected_class"] != "ambiguous"
                    else True
                ),
                "fail_closed_classification_correct": (
                    None
                    if missing
                    or row["expected_class"]
                    not in {"disproved", "unsupported"}
                    else True
                ),
                "spacy_invoked": any(
                    stage.stage is StageName.SPACY
                    and stage.provenance.effective_identity.get(
                        "graph_invoked"
                    )
                    is True
                    for stage in result.stages
                ),
                "symai_invoked": (
                    any(
                        stage.stage is StageName.SYMAI
                        and stage.provenance.effective_identity.get(
                            "graph_invoked"
                        )
                        is True
                        for stage in result.stages
                    )
                ),
                "symai_model_calls": sum(
                    stage.telemetry.model_calls
                    for stage in result.stages
                    if stage.stage is StageName.SYMAI
                ),
                "total_wall_time_ms": 2.5 * len(result.stages),
                "model_calls": sum(
                    stage.telemetry.model_calls for stage in result.stages
                ),
                "missing_reason": (
                    "requested capability is unavailable" if missing else None
                ),
            }
        )
    return rows


def _proof_observations() -> list[dict[str, object]]:
    value = report.create_capability_preflight_report()
    rows = copy.deepcopy(value["observations"])
    assert isinstance(rows, list)
    for row in rows:
        assert isinstance(row, dict)
        variant_id = str(row["variant_id"])
        result = _case_result(
            case_id=str(row["case_id"]),
            variant_id=variant_id,
            split=Split.PILOT,
            cache_mode=CacheMode(str(row["cache_mode"])),
        )
        hammer_stage = next(
            (
                stage
                for stage in result.stages
                if stage.stage is StageName.HAMMER
            ),
            None,
        )
        lean_stage = next(
            (
                stage
                for stage in result.stages
                if stage.stage is StageName.LEANSTRAL
            ),
            None,
        )
        row.update(
            {
                "status": "not_verified",
                "source_receipt_sha256": result.digest,
                "case_result": result.to_dict(),
                "verification_authority": None,
                "kernel_accepted": False,
                "kernel_receipt_sha256": None,
                "verified_source": "none",
                "model_claimed_verified": False,
                "total_wall_time_ms": 2.5 * len(result.stages),
                "model_calls": sum(
                    stage.telemetry.model_calls for stage in result.stages
                ),
                "missing_reason": None,
            }
        )
        row["hammer"].update(
            {
                "invoked": hammer_stage is not None,
                "candidate_created": False,
                "reconstruction_attempted": False,
                "reconstruction_succeeded": False,
                "wall_time_ms": (
                    0.0
                    if hammer_stage is None
                    else hammer_stage.telemetry.wall_time_ms
                ),
            }
        )
        row["leanstral"].update(
            {
                "invoked": lean_stage is not None,
                "candidate_created": lean_stage is not None,
                "repair_attempted": False,
                "repair_succeeded": False,
                "wall_time_ms": (
                    0.0
                    if lean_stage is None
                    else lean_stage.telemetry.wall_time_ms
                ),
            }
        )
    return rows


def _frontend_metric(
    value: Mapping[str, object], *, split: str, mode: str, variant: str
) -> Mapping[str, object]:
    analysis = value["analysis"]
    assert isinstance(analysis, Mapping)
    rows = analysis["variant_metrics"]
    assert isinstance(rows, list)
    record = next(
        item
        for item in rows
        if item["split"] == split
        and item["cache_mode"] == mode
        and item["variant_id"] == variant
    )
    return record["metrics"]


def test_objective_marker_exposes_receipt_driven_reports() -> None:
    assert "source-bound case receipts" in frontend_report.HSSLEV1159F06()
    assert "receipt-driven front-end" in report.HSSLEV1159F06()
    assert "pilot authorization gate" in report.HSSLEV1159F06()


def test_frontend_builder_derives_complete_nonnull_measured_evidence() -> None:
    value = frontend_report.build_frontend_report(
        RUN_ID, _frontend_capabilities(), _frontend_observations()
    )

    assert value["execution_mode"] == "measured"
    assert len(value["observations"]) == 240
    metrics = _frontend_metric(
        value, split="pilot", mode="cold", variant="A4"
    )
    assert metrics["measured_count"] == 10
    assert metrics["semantic_quality_rate"] == 1.0
    assert metrics["latency_ms_p95"] == 15.0
    assert frontend_report.validate_frontend_report(value) == value


def test_frontend_builder_retains_measured_capability_missingness() -> None:
    missing = ("pilot", "cold", "A4", "pilot-p01")
    value = frontend_report.build_frontend_report(
        RUN_ID,
        _frontend_capabilities(),
        _frontend_observations(unavailable_coordinate=missing),
    )

    metrics = _frontend_metric(
        value, split="pilot", mode="cold", variant="A4"
    )
    assert metrics["scheduled_count"] == 10
    assert metrics["measured_count"] == 9
    assert metrics["unavailable_count"] == 1
    assert metrics["semantic_quality_rate"] == 1.0
    assert metrics["latency_ms_p95"] == 15.0


def test_frontend_builder_counts_typed_gated_symai_stage_as_zero_call() -> None:
    suppressed = ("pilot", "cold", "A4", "pilot-p01")
    value = frontend_report.build_frontend_report(
        RUN_ID,
        _frontend_capabilities(),
        _frontend_observations(
            suppressed_symai_coordinate=suppressed,
        ),
    )

    row = next(
        item
        for item in value["observations"]
        if (
            item["split"],
            item["cache_mode"],
            item["variant_id"],
            item["case_id"],
        )
        == suppressed
    )
    assert row["symai_invoked"] is False
    assert row["symai_model_calls"] == 0
    assert any(
        stage["stage"] == "symai"
        for stage in row["case_result"]["stages"]
    )


def test_proof_builder_derives_latency_and_completion_from_receipts() -> None:
    value = report.build_proof_report(
        RUN_ID, _proof_capabilities(), _proof_observations()
    )

    assert value["execution_mode"] == "measured"
    assert len(value["observations"]) == 154
    metric = next(
        item
        for item in value["analysis"]["primary_metrics"]
        if item["cache_mode"] == "cold" and item["variant_id"] == "A2"
    )
    assert metric["attempt_count"] == 7
    assert metric["kernel_verified_rate"] == 0.0
    assert metric["mean_wall_time_ms"] == 10.0
    assert report.validate_proof_report(value) == value


def test_proof_validator_includes_symai_setup_in_totals_only(
    monkeypatch,
) -> None:
    setup = TelemetryRecord(
        wall_time_ms=7.0,
        model_calls=2,
        cache_misses=1,
        resource_lane=ResourceLane.MODEL,
    )

    def setup_for(stage: StageRecord) -> TelemetryRecord | None:
        return (
            setup
            if stage.stage is StageName.SYMAI
            and stage.cache_mode is CacheMode.WARM
            else None
        )

    monkeypatch.setattr(
        report,
        "extract_symai_cache_setup_telemetry",
        setup_for,
    )
    rows = _proof_observations()
    for row in rows:
        result = CaseResultRecord.from_dict(row["case_result"])
        if result.cache_mode is CacheMode.WARM and any(
            stage.stage is StageName.SYMAI for stage in result.stages
        ):
            row["total_wall_time_ms"] += 7.0
            row["model_calls"] += 2
    value = report.build_proof_report(
        RUN_ID,
        _proof_capabilities(),
        rows,
    )

    measured = next(
        row
        for row in value["observations"]
        if row["cache_mode"] == "warm"
        and row["variant_id"] == "A4"
        and row["case_id"] == "pilot-p01"
    )
    measured_result = CaseResultRecord.from_dict(measured["case_result"])
    assert measured["total_wall_time_ms"] == (
        sum(
            stage.telemetry.wall_time_ms
            for stage in measured_result.stages
        )
        + 7.0
    )
    assert measured["model_calls"] == (
        sum(
            stage.telemetry.model_calls
            for stage in measured_result.stages
        )
        + 2
    )
    assert measured["hammer"]["wall_time_ms"] == 2.5
    assert measured["leanstral"]["wall_time_ms"] == 2.5
    assert report.validate_proof_report(value) == value


def test_builders_reject_receipt_projection_and_run_identity_tampering() -> None:
    frontend_rows = _frontend_observations()
    frontend_rows[0]["total_wall_time_ms"] = 0.0
    with pytest.raises(
        frontend_report.FrontendReportError, match="latency telemetry"
    ):
        frontend_report.build_frontend_report(
            RUN_ID, _frontend_capabilities(), frontend_rows
        )

    proof_rows = _proof_observations()
    proof_rows[0]["model_calls"] = 9
    with pytest.raises(report.ProofReportError, match="model calls"):
        report.build_proof_report(
            RUN_ID, _proof_capabilities(), proof_rows
        )

    with pytest.raises(report.ProofReportError, match="run id"):
        report.build_proof_report(
            "different-run", _proof_capabilities(), _proof_observations()
        )


def test_successful_truncated_routes_are_not_complete_measured_receipts() -> None:
    rows = _frontend_observations()
    row = next(
        item
        for item in rows
        if item["split"] == "pilot"
        and item["cache_mode"] == "cold"
        and item["variant_id"] == "A4"
        and item["case_id"] == "pilot-p01"
    )
    complete = CaseResultRecord.from_dict(row["case_result"])
    truncated = CaseResultRecord.from_stages((complete.stages[0],))
    row.update(
        {
            "source_receipt_sha256": truncated.digest,
            "case_result": truncated.to_dict(),
            "spacy_invoked": False,
            "symai_invoked": False,
            "symai_model_calls": 0,
            "total_wall_time_ms": 2.5,
            "model_calls": 0,
        }
    )

    with pytest.raises(
        frontend_report.FrontendReportError, match="requested route"
    ):
        frontend_report.build_frontend_report(
            RUN_ID, _frontend_capabilities(), rows
        )

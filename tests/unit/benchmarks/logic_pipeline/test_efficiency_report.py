"""Executable evidence for delegation value and operational complexity."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import metrics, report
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    STAGE_PROVENANCE_SCHEMA,
    CacheMode,
    CaseResultRecord,
    FailureCode,
    OutcomeStatus,
    ResourceLane,
    Split,
    StageName,
    StageProvenance,
    StageRecord,
    StageStatus,
    TelemetryRecord,
    canonical_json,
)


ROOT = Path(__file__).resolve().parents[4]
MANIFEST = "a" * 64
ENVIRONMENT = "b" * 64
INPUT = "c" * 64

ROUTES = {
    "A1": (StageName.COMPILER, StageName.SPACY, StageName.KERNEL),
    "A2": (
        StageName.COMPILER,
        StageName.SPACY,
        StageName.HAMMER,
        StageName.KERNEL,
    ),
    "A3": (
        StageName.COMPILER,
        StageName.SPACY,
        StageName.HAMMER,
        StageName.LEANSTRAL,
        StageName.KERNEL,
    ),
    "A4": tuple(StageName),
}
LANES = {
    StageName.COMPILER: ResourceLane.CPU,
    StageName.SPACY: ResourceLane.CPU,
    StageName.SYMAI: ResourceLane.MODEL,
    StageName.HAMMER: ResourceLane.SOLVER,
    StageName.LEANSTRAL: ResourceLane.MODEL,
    StageName.KERNEL: ResourceLane.KERNEL,
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _case_result(
    case_id: str,
    variant_id: str,
    *,
    verified: bool,
    retries: dict[str, int] | None = None,
) -> CaseResultRecord:
    retries = retries or {}
    stages: list[StageRecord] = []
    for stage_name in ROUTES[variant_id]:
        provenance = StageProvenance(
            schema=STAGE_PROVENANCE_SCHEMA,
            adapter_id=f"{stage_name.value}-adapter",
            adapter_version="1",
            source=("efficiency-test",),
            requested_identity={"component": stage_name.value},
            effective_identity={"component": stage_name.value},
            input_sha256=INPUT,
            environment_sha256=ENVIRONMENT,
            upstream_stage_digests=tuple(item.digest for item in stages),
        )
        stages.append(
            StageRecord.create(
                protocol_sha256=DEFAULT_PROTOCOL_SHA256,
                run_id="efficiency-run",
                case_id=case_id,
                case_manifest_sha256=MANIFEST,
                variant_id=variant_id,
                split=Split.PILOT,
                cache_mode=CacheMode.COLD,
                stage=stage_name,
                adapter_version="1",
                status=StageStatus.SUCCESS,
                provenance=provenance,
                telemetry=TelemetryRecord(
                    wall_time_ms=1.0,
                    cpu_time_ms=0.25,
                    peak_memory_bytes=64,
                    input_items=1,
                    output_items=1,
                    model_calls=int(
                        stage_name in {StageName.SYMAI, StageName.LEANSTRAL}
                    ),
                    retries=retries.get(stage_name.value, 0),
                    resource_lane=LANES[stage_name],
                ),
                data={"component": stage_name.value},
                kernel_accepted=verified and stage_name is StageName.KERNEL,
                kernel_receipt_sha256=(
                    _digest(f"{case_id}:{variant_id}:kernel")
                    if verified and stage_name is StageName.KERNEL
                    else None
                ),
            )
        )
    return CaseResultRecord.from_stages(stages)


def _component_cost(
    component: str,
    *,
    useful: int = 0,
    retries: int = 0,
    failed: int = 0,
) -> metrics.EfficiencyComponentCost:
    model = int(component in {"leanstral", "symai"})
    solver = int(component == "hammer")
    accelerator = 0.25 if component == "leanstral" else (
        0.5 if component == "symai" else 0.0
    )
    return metrics.EfficiencyComponentCost(
        component_id=component,
        model_calls=model,
        solver_processes=solver,
        solver_processes_missing_reason=None,
        accelerator_minutes=accelerator,
        accelerator_minutes_missing_reason=None,
        retries=retries,
        component_calls=1,
        useful_component_calls=useful,
        failed_attempts=failed,
    )


def _observation(
    case_id: str,
    variant_id: str,
    *,
    verified: bool,
    useful: frozenset[str] = frozenset(),
    retry_component: str | None = None,
    invalid_control: bool = False,
) -> metrics.EfficiencyObservation:
    active = {
        "A1": ("spacy",),
        "A2": ("hammer", "spacy"),
        "A3": ("hammer", "leanstral", "spacy"),
        "A4": ("hammer", "leanstral", "spacy", "symai"),
    }[variant_id]
    retries = {} if retry_component is None else {retry_component: 1}
    result = _case_result(
        case_id, variant_id, verified=verified, retries=retries
    )
    costs = tuple(
        _component_cost(
            component,
            useful=int(component in useful),
            retries=retries.get(component, 0),
            failed=int(
                variant_id == "A4"
                and case_id == "case-3"
                and component == "symai"
            ),
        )
        for component in active
    )
    receipt = metrics.EfficiencyResourceReceipt(
        case_result_sha256=result.digest,
        environment_sha256=ENVIRONMENT,
        measurement_sha256=_digest(f"{case_id}:{variant_id}:meter"),
        component_costs=costs,
    )
    return metrics.EfficiencyObservation(
        case_result=result,
        resource_receipt=receipt,
        invalid_control=invalid_control,
    )


def _matrix() -> list[metrics.EfficiencyObservation]:
    status = {
        "case-1": (False, True, True, True),
        "case-2": (False, False, True, True),
        "case-3": (True, True, True, False),
    }
    result: list[metrics.EfficiencyObservation] = []
    for case_id, outcomes in status.items():
        for variant_id, verified in zip(("A1", "A2", "A3", "A4"), outcomes):
            useful: set[str] = set()
            if case_id == "case-1" and verified and variant_id != "A1":
                useful.add("hammer")
            if case_id == "case-2" and verified and variant_id in {"A3", "A4"}:
                useful.add("leanstral")
            result.append(
                _observation(
                    case_id,
                    variant_id,
                    verified=verified,
                    useful=frozenset(useful),
                    retry_component=(
                        "leanstral"
                        if case_id == "case-2" and variant_id in {"A3", "A4"}
                        else None
                    ),
                )
            )
    return result


def _redigest(value: dict[str, object]) -> None:
    value["artifact_sha256"] = hashlib.sha256(
        canonical_json(
            {key: item for key, item in value.items() if key != "artifact_sha256"}
        ).encode("utf-8")
    ).hexdigest()


def test_objective_marker_and_default_preflight_are_explicit_missingness() -> None:
    assert metrics.HSSLEV0615B24() == report.HSSLEV0615B24()
    assert "accelerator-minute" in metrics.HSSLEV0615B24()

    value = report.create_efficiency_capability_preflight_report()
    assert value["execution_mode"] == "capability_preflight"
    assert value["observations"] == []
    assert value["analysis"]["measured"] is False
    assert value["analysis"]["frontier_variant_ids"] == []
    assert value["analysis"]["scalar_complexity_score"] is None


def test_marginal_cumulative_value_resource_ratios_and_failures() -> None:
    value = report.build_efficiency_report(
        metrics.DEFAULT_EFFICIENCY_ESCALATIONS, _matrix()
    )
    rows = {
        row["variant_id"]: row for row in value["analysis"]["escalations"]
    }

    a2 = rows["A2"]["marginal"]
    assert a2["pair"]["gross_verified_gain_count"] == 1
    assert a2["pair"]["verified_regression_count"] == 0
    assert a2["incremental_cost"]["solver_processes"] == 3
    assert a2["value_per_cost"]["solver_processes"][
        "gross_verified_gains_per_unit"
    ] == pytest.approx(1 / 3)

    a3 = rows["A3"]["marginal"]
    assert a3["pair"]["gross_verified_gain_count"] == 1
    assert a3["incremental_cost"]["model_calls"] == 3
    assert a3["incremental_cost"]["accelerator_minutes"] == pytest.approx(0.75)
    assert a3["incremental_cost"]["retries"] == 1
    assert a3["value_per_cost"]["retries"][
        "gross_verified_gains_per_unit"
    ] == 1

    a4 = rows["A4"]
    assert a4["marginal"]["pair"]["gross_verified_gain_count"] == 0
    assert a4["marginal"]["pair"]["verified_regression_count"] == 1
    assert a4["cumulative"]["pair"]["gross_verified_gain_count"] == 2
    assert a4["cumulative"]["pair"]["verified_regression_count"] == 1
    assert a4["cumulative"]["pair"]["net_verified_gain_count"] == 1
    assert a4["total_cost"]["unnecessary_component_calls"] > 0
    assert a4["failure_burden"]["logical_failure_count"] == 1
    assert a4["total_cost"]["failed_attempts"] == 1
    assert value["analysis"]["scalar_complexity_score"] is None
    assert value["analysis"]["safety_is_hard_constraint"] is True


def test_zero_and_missing_denominators_are_null_with_reasons() -> None:
    value = report.build_efficiency_report(
        metrics.DEFAULT_EFFICIENCY_ESCALATIONS, _matrix()
    )
    a2 = next(
        row
        for row in value["analysis"]["escalations"]
        if row["variant_id"] == "A2"
    )
    retry_ratio = a2["marginal"]["value_per_cost"]["retries"]
    assert retry_ratio == {
        "denominator": 0,
        "gross_verified_gains_per_unit": None,
        "net_verified_gain_per_unit": None,
        "undefined_reason": "nonpositive_retries_denominator",
    }

    records = _matrix()
    target = records[4]  # A1/A2/A3/A4 then case-2 A1
    assert target.case_result.variant_id == "A1"
    a3 = next(item for item in records if item.case_result.case_id == "case-2" and item.case_result.variant_id == "A3")
    costs = list(a3.resource_receipt.component_costs)
    index = next(i for i, item in enumerate(costs) if item.component_id == "leanstral")
    costs[index] = metrics.EfficiencyComponentCost(
        component_id="leanstral",
        model_calls=1,
        solver_processes=0,
        solver_processes_missing_reason=None,
        accelerator_minutes=None,
        accelerator_minutes_missing_reason="provider meter unavailable",
        retries=1,
        component_calls=1,
        useful_component_calls=1,
        failed_attempts=0,
    )
    replacement_receipt = metrics.EfficiencyResourceReceipt(
        case_result_sha256=a3.case_result.digest,
        environment_sha256=ENVIRONMENT,
        measurement_sha256=a3.resource_receipt.measurement_sha256,
        component_costs=tuple(costs),
    )
    records[records.index(a3)] = metrics.EfficiencyObservation(
        a3.case_result, replacement_receipt
    )
    missing = report.build_efficiency_report(
        metrics.DEFAULT_EFFICIENCY_ESCALATIONS, records
    )
    a3_row = next(
        row
        for row in missing["analysis"]["escalations"]
        if row["variant_id"] == "A3"
    )
    ratio = a3_row["marginal"]["value_per_cost"]["accelerator_minutes"]
    assert ratio["denominator"] is None
    assert ratio["undefined_reason"] == "accelerator_minutes_measurement_missing"


def test_receipts_matrix_analysis_and_safety_fail_closed() -> None:
    records = _matrix()
    with pytest.raises(metrics.MetricsContractError, match="matrix"):
        metrics.analyze_delegation_efficiency(
            metrics.DEFAULT_EFFICIENCY_ESCALATIONS, records[:-1]
        )

    payload = records[0].to_dict()
    payload["resource_receipt"]["case_result_sha256"] = "f" * 64
    with pytest.raises(metrics.MetricsContractError, match="sha256|digest"):
        metrics.EfficiencyObservation.from_dict(payload)

    records = _matrix()
    unsafe = records[1]
    records[1] = metrics.EfficiencyObservation(
        unsafe.case_result, unsafe.resource_receipt, invalid_control=True
    )
    value = report.build_efficiency_report(
        metrics.DEFAULT_EFFICIENCY_ESCALATIONS, records
    )
    a2 = next(
        point
        for point in value["analysis"]["pareto_points"]
        if point["variant_id"] == "A2"
    )
    assert a2["eligible"] is False
    assert a2["ineligibility_reasons"] == ["safety_violation"]
    assert "safety_score" not in a2

    records = _matrix()
    unavailable = next(
        item
        for item in records
        if item.case_result.case_id == "case-2"
        and item.case_result.variant_id == "A2"
    )
    unavailable_result = replace(
        unavailable.case_result,
        status=OutcomeStatus.UNAVAILABLE,
        failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
        failure_detail="metered component unavailable",
    )
    unavailable_receipt = replace(
        unavailable.resource_receipt,
        case_result_sha256=unavailable_result.digest,
    )
    records[records.index(unavailable)] = metrics.EfficiencyObservation(
        unavailable_result, unavailable_receipt
    )
    missing = report.build_efficiency_report(
        metrics.DEFAULT_EFFICIENCY_ESCALATIONS, records
    )
    a2_missing = next(
        point
        for point in missing["analysis"]["pareto_points"]
        if point["variant_id"] == "A2"
    )
    assert a2_missing["eligible"] is False
    assert "incomplete_case_evidence" in a2_missing["ineligibility_reasons"]


def test_report_recomputation_canonical_loader_and_cli(tmp_path: Path) -> None:
    value = report.build_efficiency_report(
        metrics.DEFAULT_EFFICIENCY_ESCALATIONS, reversed(_matrix())
    )
    tampered = copy.deepcopy(value)
    tampered["analysis"]["escalations"][1]["marginal"]["pair"][
        "gross_verified_gain_count"
    ] = 99
    _redigest(tampered)
    with pytest.raises(report.EfficiencyReportError, match="differs"):
        report.validate_efficiency_report(tampered)

    canonical = tmp_path / "efficiency.json"
    canonical.write_text(canonical_json(value) + "\n", encoding="utf-8")
    assert report.load_efficiency_report(canonical) == value

    noncanonical = tmp_path / "pretty.json"
    noncanonical.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(report.EfficiencyReportError, match="canonical"):
        report.load_efficiency_report(noncanonical)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"a","schema":"b"}\n', encoding="utf-8")
    with pytest.raises(report.EfficiencyReportError, match="strict"):
        report.load_efficiency_report(duplicate)

    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--section",
            "efficiency",
            "--validate",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["section"] == "efficiency"
    assert summary["status"] == "valid"
    assert summary["measured"] is False
    assert summary["frontier_variant_ids"] == []

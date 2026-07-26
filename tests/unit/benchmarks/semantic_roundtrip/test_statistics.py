"""Contract tests for repeat scheduling and paired round-trip statistics."""

from __future__ import annotations

import random

import pytest

from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.semantic_roundtrip.contracts import (
    CanonicalRule,
    CanonicalRuleIR,
    ComponentStatus,
    ContractError,
    FailureReason,
    RoundTripResult,
)
from benchmarks.semantic_roundtrip.matrix import MatrixCoordinateRecord
from benchmarks.semantic_roundtrip.statistics import (
    MIN_UNCACHED_MODEL_REPEATS,
    ROUND_TRIP_PAIRED_STATISTICS_INTERFACE,
    CostMetrics,
    RoundTripObservation,
    RoundTripPairedStatistics,
    make_repeat_schedule,
)


IR = CanonicalRuleIR(
    (
        CanonicalRule(
            modality="O",
            actor="agency",
            action="file",
            object="notice",
            conditions=("under_policy",),
        ),
    )
)


def _coordinate(
    case_id: str,
    arm_id: str,
    loss: float,
    *,
    failed: bool = False,
    exact_rule_f1: float | None = None,
    facet: float | None = None,
    eligible: bool | None = None,
) -> MatrixCoordinateRecord:
    status = ComponentStatus.FAILED if failed else ComponentStatus.SUCCESS
    result = RoundTripResult(
        status=status,
        l1=None if failed else IR,
        reconstruction=None if failed else "The agency shall file notice.",
        l2=None if failed else IR,
        forward_loss=1.0 if failed else loss,
        cycle_loss=1.0 if failed else loss,
        end_to_end_loss=1.0 if failed else loss,
        failure_reason=FailureReason.TIMEOUT if failed else None,
        failure_detail="synthetic timeout" if failed else None,
    )
    effective_exact = (
        0.0 if failed else 1.0 - loss
        if exact_rule_f1 is None
        else exact_rule_f1
    )
    effective_facet = (
        0.0 if failed else 1.0 - loss if facet is None else facet
    )
    effective_eligible = not failed if eligible is None else eligible
    diagnostics = {
        "semantic_comparisons": {
            "end_to_end_gold_to_l2": (
                None
                if failed
                else {
                    "exact_rule_f1": effective_exact,
                    "exact_ir": bool(effective_exact == 1.0),
                    "exact_ir_nonvacuous": bool(effective_exact == 1.0),
                    "facet_survival": {
                        "modality": effective_facet,
                        "conditions": effective_facet,
                        "exceptions": effective_facet,
                        "temporal": effective_facet,
                    },
                }
            )
        },
        "gates": {
            "full_coverage": not failed,
            "selection_eligible": effective_eligible,
        },
    }
    return MatrixCoordinateRecord(
        case_id=case_id,
        case_cid=f"{case_id}-cid",
        cell_id=arm_id,
        constructor_id=arm_id.split("__", 1)[0],
        constructor_identity=f"{arm_id}-constructor@1",
        realizer_id=arm_id.rsplit("__", 1)[-1],
        realizer_identity=f"{arm_id}-realizer@1",
        result=result,
        l1_cid=None if failed else f"{case_id}-{arm_id}-l1",
        reconstruction_cid=None if failed else f"{case_id}-{arm_id}-t1",
        l2_cid=None if failed else f"{case_id}-{arm_id}-l2",
        diagnostics=diagnostics,
        candidate_cid=f"{case_id}-{arm_id}-candidate",
        validation={},
        record_cid=f"{case_id}-{arm_id}-record",
    )


def _observation(
    case_id: str,
    arm_id: str,
    repeat_index: int,
    loss: float,
    *,
    failed: bool = False,
    cache_mode: str = "uncached",
    cost: CostMetrics | None = None,
    exact_rule_f1: float | None = None,
    facet: float | None = None,
) -> RoundTripObservation:
    return RoundTripObservation(
        coordinate=_coordinate(
            case_id,
            arm_id,
            loss,
            failed=failed,
            exact_rule_f1=exact_rule_f1,
            facet=facet,
        ),
        repeat_index=repeat_index,
        cache_mode=cache_mode,
        cache_namespace=f"cache-{case_id}-{repeat_index}-{arm_id}",
        cost=cost or CostMetrics(),
    )


def test_schedule_is_seeded_uncached_and_counterbalanced() -> None:
    state = random.getstate()
    first = make_repeat_schedule(
        ("case-a", "case-b"),
        ("arm-a", "arm-b", "arm-c"),
        repeat_count=MIN_UNCACHED_MODEL_REPEATS,
        seed=911,
    )
    second = make_repeat_schedule(
        ("case-a", "case-b"),
        ("arm-a", "arm-b", "arm-c"),
        repeat_count=MIN_UNCACHED_MODEL_REPEATS,
        seed=911,
    )
    changed = make_repeat_schedule(
        ("case-a", "case-b"),
        ("arm-a", "arm-b", "arm-c"),
        repeat_count=MIN_UNCACHED_MODEL_REPEATS,
        seed=912,
    )

    assert first.interface == ROUND_TRIP_PAIRED_STATISTICS_INTERFACE
    assert first.to_dict() == second.to_dict()
    assert [block.arm_order for block in first.blocks] != [
        block.arm_order for block in changed.blocks
    ]
    assert random.getstate() == state
    assert all(
        max(first.position_counts[arm][position] for arm in first.arm_ids)
        - min(first.position_counts[arm][position] for arm in first.arm_ids)
        <= 1
        for position in range(len(first.arm_ids))
    )
    serialized = first.to_dict()
    coordinates = [
        coordinate
        for block in serialized["blocks"]
        for coordinate in block["coordinates"]
    ]
    assert all(item["cache_mode"] == "uncached" for item in coordinates)
    assert len({item["cache_namespace"] for item in coordinates}) == len(
        coordinates
    )


def test_model_schedule_rejects_fewer_than_five_repeats() -> None:
    with pytest.raises(ContractError, match="at least 5 uncached repeats"):
        make_repeat_schedule(
            ("case-a",),
            ("model-arm", "other-arm"),
            repeat_count=MIN_UNCACHED_MODEL_REPEATS - 1,
            seed=3,
            model_arm_ids=("model-arm",),
        )


def test_repeats_are_aggregated_within_case_before_macro_average() -> None:
    baseline = "baseline__realizer"
    candidate = "candidate__realizer"
    rows = [
        *(
            _observation("many", baseline, repeat_index, 0.0)
            for repeat_index in range(10)
        ),
        _observation("one", baseline, 0, 1.0),
        *(
            _observation("many", candidate, repeat_index, 0.2)
            for repeat_index in range(10)
        ),
        _observation("one", candidate, 0, 0.6),
    ]

    report = RoundTripPairedStatistics(
        seed=17, bootstrap_samples=100
    ).analyze(rows, baseline_arm_id=baseline)
    result = report.to_dict()
    baseline_loss = result["arm_summaries"][baseline]["metrics"]["losses"][
        "end_to_end"
    ]
    candidate_loss = result["arm_summaries"][candidate]["metrics"]["losses"][
        "end_to_end"
    ]
    paired = result["paired_comparisons"][
        f"{candidate}__vs__{baseline}"
    ]["metrics"]["losses"]["end_to_end"]

    assert baseline_loss["mean"] == 0.5
    assert candidate_loss["mean"] == 0.4
    assert paired["candidate_minus_baseline"] == -0.1
    assert paired["case_deltas"] == {
        "many": 0.2,
        "one": -0.4,
    }
    assert paired["confidence_interval"]["resampling_unit"] == (
        "case_after_within_case_repeat_aggregation"
    )


def test_failure_is_retained_with_loss_one_and_zero_coverage() -> None:
    baseline = "baseline__realizer"
    candidate = "candidate__realizer"
    rows = [
        _observation("case-a", baseline, 0, 0.0),
        _observation("case-a", candidate, 0, 0.0, failed=True),
    ]

    result = RoundTripPairedStatistics(
        bootstrap_samples=20
    ).analyze(rows, baseline_arm_id=baseline).to_dict()
    candidate_summary = result["arm_summaries"][candidate]

    assert candidate_summary["failure_count"] == 1
    assert candidate_summary["metrics"]["losses"]["end_to_end"]["mean"] == 1.0
    assert candidate_summary["metrics"]["coverage"]["success_rate"][
        "mean"
    ] == 0.0
    assert result["paired_comparisons"][
        f"{candidate}__vs__{baseline}"
    ]["metrics"]["losses"]["end_to_end"][
        "candidate_minus_baseline"
    ] == 1.0


def test_model_repeat_validation_requires_five_unique_uncached_results() -> None:
    baseline = "baseline__realizer"
    model = "model__realizer"
    complete = [
        *(
            _observation("case-a", baseline, repeat_index, 0.2)
            for repeat_index in range(MIN_UNCACHED_MODEL_REPEATS)
        ),
        *(
            _observation("case-a", model, repeat_index, 0.1)
            for repeat_index in range(MIN_UNCACHED_MODEL_REPEATS)
        ),
    ]
    report = RoundTripPairedStatistics(bootstrap_samples=20).analyze(
        complete,
        baseline_arm_id=baseline,
        model_arm_ids=(model,),
    )

    assert report.to_dict()["model_repeat_validation"]["arms"][model][
        "repeat_count_by_case"
    ] == {"case-a": MIN_UNCACHED_MODEL_REPEATS}

    with pytest.raises(ContractError, match="marked uncached"):
        RoundTripPairedStatistics(bootstrap_samples=20).analyze(
            [
                *complete[:-1],
                _observation(
                    "case-a",
                    model,
                    MIN_UNCACHED_MODEL_REPEATS - 1,
                    0.1,
                    cache_mode="not_applicable",
                ),
            ],
            baseline_arm_id=baseline,
            model_arm_ids=(model,),
        )


def test_paired_bootstrap_resamples_cases_not_repeat_coordinates() -> None:
    baseline = "baseline__realizer"
    candidate = "candidate__realizer"
    rows = []
    for case_id, candidate_loss in (("case-a", 0.2), ("case-b", 0.4)):
        for repeat_index in range(MIN_UNCACHED_MODEL_REPEATS):
            rows.append(
                _observation(case_id, baseline, repeat_index, 0.0)
            )
            rows.append(
                _observation(
                    case_id, candidate, repeat_index, candidate_loss
                )
            )

    analyzer = RoundTripPairedStatistics(seed=41, bootstrap_samples=500)
    first = analyzer.analyze(rows, baseline_arm_id=baseline).to_dict()
    second = analyzer.analyze(
        reversed(rows), baseline_arm_id=baseline
    ).to_dict()
    paired = first["paired_comparisons"][
        f"{candidate}__vs__{baseline}"
    ]["metrics"]["losses"]["end_to_end"]

    assert first == second
    assert paired["candidate_minus_baseline"] == 0.3
    assert paired["paired_case_count"] == 2
    assert paired["confidence_interval"]["low"] == 0.2
    assert paired["confidence_interval"]["high"] == 0.4


def test_exact_facets_coverage_and_cost_are_separate_report_axes() -> None:
    baseline = "baseline__realizer"
    candidate = "candidate__realizer"
    rows = [
        _observation(
            "case-a",
            baseline,
            0,
            0.1,
            exact_rule_f1=0.8,
            facet=0.7,
            cost=CostMetrics(
                model_calls=1,
                retries=0,
                input_tokens=20,
                output_tokens=10,
                wall_time_seconds=2.0,
                estimated_cost=0.01,
            ),
        ),
        _observation(
            "case-a",
            candidate,
            0,
            0.0,
            exact_rule_f1=1.0,
            facet=1.0,
            cost=CostMetrics(
                model_calls=2,
                retries=1,
                input_tokens=30,
                output_tokens=15,
                wall_time_seconds=4.0,
                estimated_cost=0.03,
            ),
        ),
    ]

    result = RoundTripPairedStatistics(
        bootstrap_samples=20
    ).analyze(rows, baseline_arm_id=baseline).to_dict()
    candidate_metrics = result["arm_summaries"][candidate]["metrics"]
    paired_metrics = result["paired_comparisons"][
        f"{candidate}__vs__{baseline}"
    ]["metrics"]

    assert set(candidate_metrics) == {
        "losses",
        "exact_rule",
        "facets",
        "coverage",
        "cost",
    }
    assert candidate_metrics["exact_rule"]["exact_rule_f1"]["mean"] == 1.0
    assert candidate_metrics["facets"]["temporal_survival"]["mean"] == 1.0
    assert candidate_metrics["coverage"]["full_coverage_rate"]["mean"] == 1.0
    assert candidate_metrics["cost"]["estimated_cost"]["mean"] == 0.03
    assert paired_metrics["losses"]["end_to_end"][
        "candidate_minus_baseline"
    ] == -0.1
    assert paired_metrics["cost"]["estimated_cost"][
        "candidate_minus_baseline"
    ] == 0.02
    assert result["analysis_policy"]["cost_folded_into_semantic_loss"] is False


def test_missing_cost_is_explicit_and_report_is_deeply_immutable() -> None:
    baseline = "baseline__realizer"
    candidate = "candidate__realizer"
    report = RoundTripPairedStatistics(bootstrap_samples=10).analyze(
        [
            _observation("case-a", baseline, 0, 0.0),
            _observation(
                "case-a",
                candidate,
                0,
                0.0,
                cost=CostMetrics(model_calls=1),
            ),
        ],
        baseline_arm_id=baseline,
    )
    serialized = report.to_dict()

    report_cid = serialized.pop("report_cid")
    assert cid_for_dag_json(serialized) == report_cid
    assert serialized["input_coordinate_count"] == 2
    assert {
        item["coordinate_record_cid"]
        for item in serialized["observation_manifest"]
    } == {
        "case-a-baseline__realizer-record",
        "case-a-candidate__realizer-record",
    }
    assert serialized["arm_summaries"][baseline]["metrics"]["cost"][
        "model_calls"
    ]["mean"] is None
    assert serialized["arm_summaries"][baseline]["metrics"]["cost"][
        "model_calls"
    ]["missing_case_count"] == 1
    with pytest.raises(TypeError):
        report.arm_summaries[baseline] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        report.arm_summaries[baseline]["metrics"]["losses"] = {}  # type: ignore[index]


def test_paired_analysis_rejects_unpaired_case_sets_and_duplicate_rows() -> None:
    baseline = "baseline__realizer"
    candidate = "candidate__realizer"
    analyzer = RoundTripPairedStatistics(bootstrap_samples=10)
    baseline_row = _observation("case-a", baseline, 0, 0.0)

    with pytest.raises(ContractError, match="same case ids"):
        analyzer.analyze(
            [
                baseline_row,
                _observation("case-b", candidate, 0, 0.0),
            ],
            baseline_arm_id=baseline,
        )
    with pytest.raises(ContractError, match="must be unique"):
        analyzer.analyze(
            [
                baseline_row,
                baseline_row,
                _observation("case-a", candidate, 0, 0.0),
            ],
            baseline_arm_id=baseline,
        )

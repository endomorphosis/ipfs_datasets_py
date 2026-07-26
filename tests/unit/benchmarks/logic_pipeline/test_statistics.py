"""Executable evidence for reproducible paired statistics and Pareto reports."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

import pytest

from benchmarks.logic_pipeline import report, statistics
from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.logic_pipeline.contracts import (
    DEFAULT_PROTOCOL_SHA256,
    OUTCOME_RECORD_SCHEMA,
    CacheMode,
    FailureCode,
    MetricCategory,
    MetricDirection,
    OutcomeRecord,
    OutcomeStatus,
    Split,
    VerificationAuthority,
    canonical_json,
)


ROOT = Path(__file__).resolve().parents[4]


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cid(value: str) -> str:
    return cid_for_dag_json({"synthetic_receipt": value})


def _spec(
    *,
    comparison_id: str = "verified-a1-vs-a0",
    kind: statistics.MetricKind = statistics.MetricKind.BINARY,
    estimator: statistics.Estimator = statistics.Estimator.MEAN,
    direction: MetricDirection | None = None,
    role: statistics.AnalysisRole = statistics.AnalysisRole.PRIMARY,
    family: str | None = None,
) -> statistics.ComparisonSpec:
    effective_direction = (
        direction
        if direction is not None
        else (
            MetricDirection.MAXIMIZE
            if kind is statistics.MetricKind.BINARY
            else MetricDirection.MINIMIZE
        )
    )
    return statistics.ComparisonSpec(
        comparison_id=comparison_id,
        metric_id=(
            "kernel_verified_completion_rate"
            if kind is statistics.MetricKind.BINARY
            else "end_to_end_latency_p95"
        ),
        category=(
            MetricCategory.PRIMARY
            if kind is statistics.MetricKind.BINARY
            else MetricCategory.RESOURCE
        ),
        direction=effective_direction,
        unit="fraction" if kind is statistics.MetricKind.BINARY else "milliseconds",
        kind=kind,
        estimator=estimator,
        baseline_variant_id="A0",
        candidate_variant_id="A1",
        domain=(
            statistics.AnalysisDomain.QUALITY
            if kind is statistics.MetricKind.BINARY
            else statistics.AnalysisDomain.LATENCY
        ),
        role=role,
        multiplicity_family=family,
    )


def _observation(
    case_id: str,
    baseline: float | None,
    candidate: float | None,
    *,
    stratum: str = "easy",
    cache_mode: CacheMode = CacheMode.COLD,
    missing_kind: statistics.MissingKind | None = None,
    missing_reason: str | None = None,
) -> statistics.PairedCaseObservation:
    return statistics.PairedCaseObservation(
        protocol_sha256=DEFAULT_PROTOCOL_SHA256,
        run_id="statistics-test-run",
        case_id=case_id,
        case_manifest_sha256=_sha("manifest"),
        split=Split.PILOT,
        cache_mode=cache_mode,
        stratum=stratum,
        baseline_variant_id="A0",
        candidate_variant_id="A1",
        baseline_result_sha256=_sha(f"{case_id}:A0"),
        candidate_result_sha256=_sha(f"{case_id}:A1"),
        baseline_value=baseline,
        candidate_value=candidate,
        missing_kind=missing_kind,
        missing_reason=missing_reason,
    )


def _plan(seed: int = 419) -> statistics.StatisticalPlan:
    return statistics.StatisticalPlan(
        seed=seed,
        bootstrap_samples=250,
        confidence_level=0.95,
    )


def _outcome(
    case_id: str,
    variant_id: str,
    status: OutcomeStatus,
    *,
    failure_code: FailureCode | None = None,
    failure_detail: str | None = None,
) -> OutcomeRecord:
    verified = status is OutcomeStatus.VERIFIED
    return OutcomeRecord(
        schema=OUTCOME_RECORD_SCHEMA,
        protocol_sha256=DEFAULT_PROTOCOL_SHA256,
        run_id="statistics-test-run",
        case_id=case_id,
        case_manifest_sha256=_sha("manifest"),
        variant_id=variant_id,
        split=Split.PILOT,
        cache_mode=CacheMode.COLD,
        status=status,
        invalid_control=False,
        verification_authority=(
            VerificationAuthority.NATIVE_KERNEL
            if verified
            else VerificationAuthority.NONE
        ),
        kernel_accepted=verified,
        kernel_receipt_sha256=_sha(f"{case_id}:kernel") if verified else None,
        failure_code=failure_code,
        failure_detail=failure_detail,
    )


def _binary_rows(
    *,
    both: int,
    baseline_only: int,
    candidate_only: int,
    neither: int,
    prefix: str = "case",
) -> tuple[statistics.PairedCaseObservation, ...]:
    values = (
        [(1.0, 1.0)] * both
        + [(1.0, 0.0)] * baseline_only
        + [(0.0, 1.0)] * candidate_only
        + [(0.0, 0.0)] * neither
    )
    return tuple(
        _observation(f"{prefix}-{index:03d}", left, right)
        for index, (left, right) in enumerate(values)
    )


def test_objective_marker_and_report_wrapper_are_stable() -> None:
    marker = statistics.HSSLEV0608F63()

    assert callable(statistics.HSSLEV0608F63)
    assert "paired bootstrap" in marker
    assert "missingness" in marker
    assert "Pareto" in marker
    assert report.HSSLEV0608F63() == marker
    assert {item.value for item in statistics.AnalysisDomain} == {
        "quality",
        "safety",
        "latency",
        "resource",
        "routing",
        "reliability",
    }
    assert {item.value for item in statistics.StratumDimension} == {
        "logic_family",
        "difficulty",
        "ambiguity",
        "proof_route",
        "joint",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", True),
        ("seed", -1),
        ("bootstrap_samples", 0),
        ("bootstrap_samples", statistics.MAX_BOOTSTRAP_SAMPLES + 1),
        ("confidence_level", 0.0),
        ("confidence_level", 0.90),
        ("confidence_level", 1.0),
        ("confidence_level", float("nan")),
    ],
)
def test_statistical_plan_rejects_nonreproducible_settings(
    field: str, value: object
) -> None:
    arguments: dict[str, object] = {
        "seed": 1,
        "bootstrap_samples": 10,
        "confidence_level": 0.95,
    }
    arguments[field] = value
    with pytest.raises(statistics.StatisticsError):
        statistics.StatisticalPlan(**arguments)  # type: ignore[arg-type]


def test_seeded_stratified_bootstrap_is_canonical_and_local() -> None:
    rows = tuple(
        _observation(
            f"case-{index:02d}",
            float(index),
            float(index + (index % 4) - 1),
            stratum="hard" if index % 2 else "easy",
        )
        for index in range(12)
    )
    spec = _spec(
        kind=statistics.MetricKind.CONTINUOUS,
        estimator=statistics.Estimator.MEAN,
    )
    state = random.getstate()
    first = statistics.analyze_paired(spec, rows, plan=_plan(73))
    second = statistics.analyze_paired(spec, reversed(rows), plan=_plan(73))

    assert first.to_dict() == second.to_dict()
    assert first.digest == second.digest
    assert random.getstate() == state
    assert [item["stratum"] for item in first.strata] == ["easy", "hard"]
    assert [item["measured_count"] for item in first.strata] == [6, 6]

    changed_seed = statistics.analyze_paired(spec, rows, plan=_plan(74))
    assert changed_seed.summary["candidate_minus_baseline"] == first.summary[
        "candidate_minus_baseline"
    ]
    assert changed_seed.case_traces == first.case_traces
    assert changed_seed.plan_sha256 != first.plan_sha256


def test_paired_bootstrap_keeps_identical_pairs_degenerate() -> None:
    rows = tuple(
        _observation(
            f"case-{index:02d}",
            float(index * 10),
            float(index * 10),
            stratum="odd" if index % 2 else "even",
        )
        for index in range(8)
    )
    analysis = statistics.analyze_paired(
        _spec(
            kind=statistics.MetricKind.CONTINUOUS,
            estimator=statistics.Estimator.MEAN,
        ),
        rows,
        plan=_plan(),
    )

    assert analysis.summary["candidate_minus_baseline"] == 0.0
    assert analysis.summary["confidence_interval_low"] == 0.0
    assert analysis.summary["confidence_interval_high"] == 0.0


def test_binary_analysis_has_hand_checkable_table_effect_and_exact_test() -> None:
    analysis = statistics.analyze_paired(
        _spec(),
        _binary_rows(both=2, baseline_only=1, candidate_only=3, neither=2),
        plan=_plan(),
    )
    binary = analysis.summary["binary"]

    assert binary["both_success_count"] == 2
    assert binary["baseline_only_success_count"] == 1
    assert binary["candidate_only_success_count"] == 3
    assert binary["neither_success_count"] == 2
    assert binary["discordant_count"] == 4
    assert binary["p_value_raw"] == 0.625
    assert analysis.summary["baseline_estimate"] == 0.375
    assert analysis.summary["candidate_estimate"] == 0.625
    assert analysis.summary["candidate_minus_baseline"] == 0.25
    assert analysis.summary["percentage_point_delta"] == 25.0
    assert analysis.summary["relative_delta"] == pytest.approx(2 / 3)
    assert analysis.p_value_raw == 0.625
    assert analysis.p_value_adjusted == 0.625
    assert analysis.multiplicity["method"] == "none_preregistered_primary"
    with pytest.raises(TypeError):
        binary["p_value_raw"] = 0.0  # type: ignore[index]


def test_binary_swap_reverses_delta_but_not_exact_p_value() -> None:
    left = statistics.analyze_paired(
        _spec(),
        _binary_rows(both=1, baseline_only=1, candidate_only=4, neither=2),
        plan=_plan(),
    )
    swapped_rows = tuple(
        _observation(
            row.case_id,
            row.candidate_value,
            row.baseline_value,
        )
        for row in _binary_rows(
            both=1, baseline_only=1, candidate_only=4, neither=2
        )
    )
    right = statistics.analyze_paired(_spec(), swapped_rows, plan=_plan())

    assert right.summary["candidate_minus_baseline"] == -left.summary[
        "candidate_minus_baseline"
    ]
    assert right.p_value_raw == left.p_value_raw


def test_no_discordance_and_zero_baseline_are_explicit() -> None:
    no_discordance = statistics.analyze_paired(
        _spec(),
        _binary_rows(both=2, baseline_only=0, candidate_only=0, neither=2),
        plan=_plan(),
    )
    zero_baseline = statistics.analyze_paired(
        _spec(comparison_id="zero-baseline"),
        _binary_rows(
            both=0,
            baseline_only=0,
            candidate_only=2,
            neither=2,
            prefix="zero",
        ),
        plan=_plan(),
    )

    assert no_discordance.summary["binary"]["test_status"] == (
        "no_discordant_pairs"
    )
    assert no_discordance.p_value_raw == 1.0
    assert zero_baseline.summary["relative_delta"] is None
    assert zero_baseline.summary["relative_delta_missing_reason"] == (
        "baseline_estimate_zero"
    )


def test_missingness_remains_null_and_preserves_strata_and_receipts() -> None:
    rows = (
        _observation("easy-measured", 0.0, 1.0, stratum="easy"),
        _observation(
            "easy-unavailable",
            None,
            None,
            stratum="easy",
            missing_kind=statistics.MissingKind.CAPABILITY_UNAVAILABLE,
            missing_reason="candidate model unavailable",
        ),
        _observation(
            "hard-infrastructure",
            None,
            None,
            stratum="hard",
            missing_kind=statistics.MissingKind.INFRASTRUCTURE_FAILURE,
            missing_reason="scheduler cancelled lease",
        ),
    )
    analysis = statistics.analyze_paired(_spec(), rows, plan=_plan())

    assert analysis.scheduled_count == 3
    assert analysis.measured_count == 1
    assert analysis.missing_count == 2
    assert analysis.summary["candidate_minus_baseline"] == 1.0
    assert analysis.missingness["missing_case_ids"] == (
        "easy-unavailable",
        "hard-infrastructure",
    )
    assert analysis.missingness["kind_counts"] == {
        "capability_unavailable": 1,
        "fixture_invalid": 0,
        "infrastructure_failure": 1,
    }
    hard = next(item for item in analysis.strata if item["stratum"] == "hard")
    assert hard["summary"]["candidate_minus_baseline"] is None
    assert hard["summary"]["relative_delta_missing_reason"] == "no_measured_pairs"
    assert all(
        trace["baseline_result_sha256"]
        and trace["candidate_result_sha256"]
        and trace["observation_sha256"]
        for trace in analysis.case_traces
    )


def test_all_missing_pairs_never_become_zero_effects() -> None:
    rows = tuple(
        _observation(
            f"missing-{index}",
            None,
            None,
            missing_kind=statistics.MissingKind.CAPABILITY_UNAVAILABLE,
            missing_reason="requested provider unavailable",
        )
        for index in range(3)
    )
    analysis = statistics.analyze_paired(_spec(), rows, plan=_plan())

    assert analysis.measured_count == 0
    assert analysis.summary["baseline_estimate"] is None
    assert analysis.summary["candidate_estimate"] is None
    assert analysis.summary["candidate_minus_baseline"] is None
    assert analysis.summary["confidence_interval_low"] is None
    assert analysis.p_value_raw is None


def test_observation_from_outcomes_includes_failures_and_excludes_only_missing() -> None:
    logical = statistics.observation_from_outcomes(
        _outcome("logical", "A0", OutcomeStatus.NOT_VERIFIED),
        _outcome(
            "logical",
            "A1",
            OutcomeStatus.REJECTED,
            failure_code=FailureCode.KERNEL_REJECTION,
            failure_detail="candidate rejected",
        ),
        stratum="hard",
        baseline_result_sha256=_sha("logical:A0"),
        candidate_result_sha256=_sha("logical:A1"),
    )
    unavailable = statistics.observation_from_outcomes(
        _outcome(
            "missing",
            "A0",
            OutcomeStatus.UNAVAILABLE,
            failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
            failure_detail="provider absent",
        ),
        _outcome(
            "missing",
            "A1",
            OutcomeStatus.UNAVAILABLE,
            failure_code=FailureCode.CAPABILITY_UNAVAILABLE,
            failure_detail="provider absent",
        ),
        stratum="hard",
        baseline_result_sha256=_sha("missing:A0"),
        candidate_result_sha256=_sha("missing:A1"),
    )

    assert logical.measured
    assert logical.baseline_value == 0.0
    assert logical.candidate_value == 0.0
    assert unavailable.baseline_value is None
    assert unavailable.missing_kind is statistics.MissingKind.CAPABILITY_UNAVAILABLE
    assert "baseline=unavailable/capability_unavailable" in unavailable.missing_reason


def test_invalid_values_duplicates_and_mixed_cache_fail_closed() -> None:
    with pytest.raises(statistics.StatisticsError, match="finite"):
        _observation("nan", float("nan"), 1.0)
    with pytest.raises(statistics.StatisticsError, match="both"):
        _observation("half", 1.0, None)
    with pytest.raises(statistics.StatisticsError, match="exactly 0 or 1"):
        statistics.analyze_paired(
            _spec(), [_observation("nonbinary", 0.5, 1.0)], plan=_plan()
        )
    row = _observation("duplicate", 0.0, 1.0)
    with pytest.raises(statistics.StatisticsError, match="duplicate case"):
        statistics.analyze_paired(_spec(), [row, row], plan=_plan())
    with pytest.raises(statistics.StatisticsError, match="preserve protocol"):
        statistics.analyze_paired(
            _spec(),
            [
                _observation("cold", 0.0, 1.0),
                _observation(
                    "warm", 0.0, 1.0, cache_mode=CacheMode.WARM
                ),
            ],
            plan=_plan(),
        )


def test_continuous_median_is_median_of_paired_deltas() -> None:
    rows = (
        _observation("case-a", 0.0, 100.0),
        _observation("case-b", 100.0, 101.0),
        _observation("case-c", 101.0, 102.0),
    )
    analysis = statistics.analyze_paired(
        _spec(
            kind=statistics.MetricKind.CONTINUOUS,
            estimator=statistics.Estimator.MEDIAN,
            direction=MetricDirection.MINIMIZE,
        ),
        rows,
        plan=_plan(),
    )

    assert analysis.summary["baseline_estimate"] == 100.0
    assert analysis.summary["candidate_estimate"] == 101.0
    assert analysis.summary["candidate_minus_baseline"] == 1.0
    assert analysis.summary["improvement"] == -1.0
    assert analysis.summary["baseline_distribution"] == {
        "p50": 100.0,
        "p95": 100.9,
        "p99": 100.98,
    }


def test_exploratory_families_are_holm_adjusted_and_labeled() -> None:
    requests = (
        statistics.AnalysisRequest(
            _spec(
                comparison_id="explore-a",
                role=statistics.AnalysisRole.EXPLORATORY,
                family="routing-family",
            ),
            _binary_rows(
                both=0,
                baseline_only=0,
                candidate_only=4,
                neither=1,
                prefix="a",
            ),
        ),
        statistics.AnalysisRequest(
            _spec(
                comparison_id="explore-b",
                role=statistics.AnalysisRole.EXPLORATORY,
                family="routing-family",
            ),
            _binary_rows(
                both=0,
                baseline_only=1,
                candidate_only=3,
                neither=1,
                prefix="b",
            ),
        ),
    )
    analyses = statistics.analyze_requests(requests, plan=_plan())

    assert [item.spec.comparison_id for item in analyses] == [
        "explore-a",
        "explore-b",
    ]
    assert analyses[0].p_value_raw == 0.125
    assert analyses[0].p_value_adjusted == 0.25
    assert analyses[1].p_value_raw == 0.625
    assert analyses[1].p_value_adjusted == 0.625
    for item in analyses:
        assert item.multiplicity == {
            "role": "exploratory",
            "family": "routing-family",
            "method": "holm",
            "family_size": 2,
            "tested_hypothesis_count": 2,
            "adjustment_status": "adjusted",
        }

    with pytest.raises(statistics.StatisticsError, match="multiplicity_family"):
        _spec(role=statistics.AnalysisRole.EXPLORATORY)


def _candidate(
    candidate_id: str,
    *,
    quality: float | None,
    latency: float | None,
    note: float = 0.0,
    safe: bool = True,
) -> statistics.ParetoCandidate:
    return statistics.ParetoCandidate(
        candidate_id=candidate_id,
        metrics={"quality": quality, "latency": latency, "note": note},
        analysis_sha256s=(_sha(f"{candidate_id}:analysis"),),
        case_result_sha256s=(_sha(f"{candidate_id}:case"),),
        safety_feasible=safe,
        safety_reason=None if safe else "invalid control verified",
    )


def test_pareto_respects_directions_ties_missingness_and_hard_safety() -> None:
    objectives = (
        statistics.ParetoObjective("quality", MetricDirection.MAXIMIZE),
        statistics.ParetoObjective("latency", MetricDirection.MINIMIZE),
        statistics.ParetoObjective("note", MetricDirection.REPORT),
    )
    result = statistics.pareto_frontier(
        [
            _candidate("balanced", quality=0.8, latency=10.0),
            _candidate("dominated", quality=0.7, latency=12.0),
            _candidate("quality", quality=0.9, latency=15.0),
            _candidate("balanced-tie", quality=0.8, latency=10.0, note=999.0),
            _candidate("missing", quality=None, latency=1.0),
            _candidate("unsafe", quality=1.0, latency=0.0, safe=False),
        ],
        reversed(objectives),
    )
    by_id = {item["candidate_id"]: item for item in result["candidates"]}

    assert result["frontier_candidate_ids"] == [
        "balanced",
        "balanced-tie",
        "quality",
    ]
    assert by_id["dominated"]["dominated_by"] == [
        "balanced",
        "balanced-tie",
    ]
    assert not by_id["missing"]["eligible"]
    assert by_id["missing"]["ineligible_reason"] == "missing_objectives:quality"
    assert not by_id["unsafe"]["eligible"]
    assert by_id["unsafe"]["ineligible_reason"].startswith("safety_infeasible:")
    assert "never scalarized" in result["safety_policy"]


def test_pareto_is_canonical_across_candidate_and_metric_order() -> None:
    objectives = (
        statistics.ParetoObjective("quality", MetricDirection.MAXIMIZE),
        statistics.ParetoObjective("latency", MetricDirection.MINIMIZE),
    )
    first = statistics.pareto_frontier(
        [
            _candidate("a", quality=0.8, latency=10),
            _candidate("b", quality=0.9, latency=12),
        ],
        objectives,
    )
    second = statistics.pareto_frontier(
        [
            _candidate("b", quality=0.9, latency=12),
            _candidate("a", quality=0.8, latency=10),
        ],
        reversed(objectives),
    )

    assert first == second


def test_statistics_report_recomputes_aggregates_pareto_and_digest() -> None:
    plan = _plan()
    request = statistics.AnalysisRequest(
        _spec(), _binary_rows(both=1, baseline_only=1, candidate_only=2, neither=1)
    )
    analysis = statistics.analyze_requests([request], plan=plan)[0]
    source_digests = tuple(
        sorted(
            {
                trace["baseline_result_sha256"]
                for trace in analysis.case_traces
            }
            | {
                trace["candidate_result_sha256"]
                for trace in analysis.case_traces
            }
        )
    )
    candidate = statistics.ParetoCandidate(
        candidate_id="A1",
        metrics={"quality": analysis.summary["candidate_estimate"]},
        analysis_sha256s=(analysis.digest,),
        case_result_sha256s=source_digests,
    )
    value = statistics.build_statistics_report(
        plan,
        [request],
        pareto_objectives=[
            statistics.ParetoObjective(
                "quality", MetricDirection.MAXIMIZE
            )
        ],
        pareto_candidates=[candidate],
    )

    assert statistics.validate_statistics_report(value) == value
    assert report.validate_statistics_report(value) == value
    assert value["evidence"] == statistics.HSSLEV0608F63()
    assert value["pareto"]["frontier_candidate_ids"] == ["A1"]
    assert statistics.statistics_summary(value) == {
        "section": "statistics",
        "status": "valid",
        "artifact_sha256": value["artifact_sha256"],
        "comparison_count": 1,
        "scheduled_pair_count": 5,
        "missing_pair_count": 0,
        "frontier_candidate_ids": ["A1"],
    }

    tampered = copy.deepcopy(value)
    tampered["analyses"][0]["summary"]["candidate_minus_baseline"] = 999.0
    with pytest.raises(statistics.StatisticsError, match="differ"):
        statistics.validate_statistics_report(tampered)

    tampered = copy.deepcopy(value)
    tampered["pareto"]["frontier_candidate_ids"] = []
    with pytest.raises(statistics.StatisticsError, match="Pareto"):
        statistics.validate_statistics_report(tampered)

    tampered = copy.deepcopy(value)
    tampered["artifact_sha256"] = "f" * 64
    with pytest.raises(statistics.StatisticsError, match="digest"):
        statistics.validate_statistics_report(tampered)


def test_canonical_statistics_loader_and_additive_cli(tmp_path: Path) -> None:
    value = statistics.build_statistics_report(
        _plan(),
        [
            statistics.AnalysisRequest(
                _spec(),
                _binary_rows(
                    both=1, baseline_only=0, candidate_only=1, neither=1
                ),
            )
        ],
    )
    path = tmp_path / "statistics.json"
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")

    assert statistics.load_statistics_report(path) == value
    process = subprocess.run(
        [
            sys.executable,
            "benchmarks/logic_pipeline/report.py",
            "--section",
            "statistics",
            "--validate",
            "--results-path",
            str(path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["section"] == "statistics"

    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(statistics.StatisticsError, match="canonical JSON"):
        statistics.load_statistics_report(noncanonical)

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema":"a","schema":"b"}\n', encoding="utf-8")
    with pytest.raises(statistics.StatisticsError, match="strict JSON"):
        statistics.load_statistics_report(duplicate)


def test_report_builder_is_canonical_for_request_and_pareto_input_order() -> None:
    plan = _plan()
    requests = [
        statistics.AnalysisRequest(
            _spec(
                comparison_id=f"comparison-{name}",
                role=statistics.AnalysisRole.EXPLORATORY,
                family="family",
            ),
            _binary_rows(
                both=1,
                baseline_only=index,
                candidate_only=2,
                neither=1,
                prefix=name,
            ),
        )
        for index, name in enumerate(("a", "b"))
    ]
    objectives = [
        statistics.ParetoObjective("quality", MetricDirection.MAXIMIZE),
        statistics.ParetoObjective("cost", MetricDirection.MINIMIZE),
    ]
    analyses = statistics.analyze_requests(requests, plan=plan)
    candidates = []
    for (name, quality, cost), analysis in zip(
        (("A1", 0.8, 1.0), ("A2", 0.9, 2.0)),
        analyses,
        strict=True,
    ):
        case_receipts = {
            str(trace["baseline_result_sha256"])
            for trace in analysis.case_traces
        } | {
            str(trace["candidate_result_sha256"])
            for trace in analysis.case_traces
        }
        candidates.append(
            statistics.ParetoCandidate(
                candidate_id=name,
                metrics={"quality": quality, "cost": cost},
                analysis_sha256s=(analysis.digest,),
                case_result_sha256s=tuple(case_receipts),
            )
        )
    first = statistics.build_statistics_report(
        plan,
        requests,
        pareto_objectives=objectives,
        pareto_candidates=candidates,
    )
    second = statistics.build_statistics_report(
        plan,
        reversed(requests),
        pareto_objectives=reversed(objectives),
        pareto_candidates=reversed(candidates),
    )

    assert first == second


def test_causal_rate_binds_explicit_event_and_population_receipts() -> None:
    population = tuple(sorted(_cid(f"case-{index}") for index in range(4)))
    events = tuple(sorted(population[1:3]))
    rate = statistics.CausalBinomialRate(
        metric_id="hammer_causal_rescue_rate",
        event_label="distinct_kernel_accepted_rescue",
        population_label="hammer_escalation_eligible",
        event_receipt_cids=events,
        population_receipt_cids=population,
    )

    assert rate.numerator == 2
    assert rate.denominator == 4
    assert rate.estimate == 0.5
    lower, upper = rate.interval
    assert lower == pytest.approx(0.150038989, abs=1e-8)
    assert upper == pytest.approx(0.849961011, abs=1e-8)
    assert statistics.CausalBinomialRate.from_dict(rate.to_dict()) == rate
    assert rate.receipt_cid.startswith("baguqeera")

    relabelled = statistics.CausalBinomialRate(
        metric_id=rate.metric_id,
        event_label=rate.event_label,
        population_label="all_scheduled_cases",
        event_receipt_cids=events,
        population_receipt_cids=population,
    )
    assert relabelled.receipt_cid != rate.receipt_cid


def test_causal_rate_empty_denominator_is_unidentifiable_not_zero() -> None:
    rate = statistics.CausalBinomialRate(
        metric_id="leanstral_causal_rescue_rate",
        event_label="distinct_kernel_accepted_rescue",
        population_label="leanstral_escalation_eligible",
        event_receipt_cids=(),
        population_receipt_cids=(),
    )

    assert rate.numerator == 0
    assert rate.denominator == 0
    assert rate.estimate is None
    assert rate.interval == (None, None)
    assert statistics.CausalBinomialRate.from_dict(rate.to_dict()) == rate


def test_causal_rate_rejects_forged_or_ambiguous_denominators() -> None:
    one, two = sorted((_cid("one"), _cid("two")))
    outside = _cid("outside")
    with pytest.raises(statistics.StatisticsError, match="subset"):
        statistics.CausalBinomialRate(
            metric_id="hammer_suppression_rate",
            event_label="eligible_but_suppressed",
            population_label="hammer_escalation_eligible",
            event_receipt_cids=(outside,),
            population_receipt_cids=(one, two),
        )
    with pytest.raises(statistics.StatisticsError, match="canonical CID order"):
        statistics.CausalBinomialRate(
            metric_id="hammer_escalation_rate",
            event_label="eligible_and_invoked",
            population_label="hammer_escalation_eligible",
            event_receipt_cids=(),
            population_receipt_cids=(two, one),
        )

    rate = statistics.CausalBinomialRate(
        metric_id="hammer_overlap_rate",
        event_label="byte_identical_overlap",
        population_label="hammer_invoked",
        event_receipt_cids=(one,),
        population_receipt_cids=(one, two),
    )
    forged = copy.deepcopy(rate.to_dict())
    forged["numerator"] = 2
    with pytest.raises(statistics.StatisticsError, match="derived fields"):
        statistics.CausalBinomialRate.from_dict(forged)

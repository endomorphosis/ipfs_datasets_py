"""PCCE-066 golden metric, pairing, and fail-closed qualification vectors."""

# The owning repository and outer superproject classify ``ipfs_datasets_py``
# into different import sections.  Keep one readable grouping in both contexts.
# ruff: noqa: I001, RUF100

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

import pytest

from ipfs_datasets_py.proof_context.benchmarks import comparison
from ipfs_datasets_py.proof_context.benchmarks import metrics as aggregation
from ipfs_datasets_py.proof_context.benchmarks import specification as spec


def _cid(label: str) -> str:
    return spec.structured_cid({"fixture": label})


CONFIGURATION_CIDS = {
    item["configuration_id"]: spec.structured_cid(item) for item in spec.configuration_catalog()
}


def _row(
    task: str,
    configuration_id: str,
    *,
    attempt: int = 1,
    status: str = "succeeded",
    provenance: str = "live",
    context: int | None = None,
    total_cost: int | None = 100,
    routine: bool = True,
    frontier: int = 0,
    environment: str = "environment",
    provider: str = "provider-fixture",
    model: str = "model-fixture",
    model_revision: str = "revision-fixture",
    seed: int = 60060,
) -> dict[str, Any]:
    values: dict[str, int | None] = {definition["name"]: 0 for definition in spec.metric_catalog()}
    if configuration_id == "A":
        rendered_context = 100 if context is None else context
        values["ordinary_retrieval_tokens"] = rendered_context
        values["context_pack_tokens"] = None
        values["capsule_tokens"] = None
        values["context_reduction_bp"] = None
    else:
        rendered_context = 40 if context is None else context
        values["ordinary_retrieval_tokens"] = None
        values["context_pack_tokens"] = rendered_context
        values["capsule_tokens"] = min(10, rendered_context - rendered_context // 2)
        values["context_reduction_bp"] = (100 - rendered_context) * 10000 // 100
    values["exact_source_tokens"] = rendered_context // 2
    values["provider_input_tokens"] = rendered_context
    values["provider_output_tokens"] = 10
    values["provider_cached_input_tokens"] = 0
    values["context_expansion_tokens"] = 0
    values["context_fallback_count"] = 0
    values["context_expansion_count"] = 0

    succeeded = status == "succeeded"
    values["eligible_task_count"] = 1
    values["patch_proposal_count"] = 1
    values["accepted_patch_count"] = int(succeeded)
    values["correct_accepted_patch_count"] = int(succeeded)
    values["hidden_test_total_count"] = 5
    values["hidden_test_pass_count"] = 5 if succeeded else 4
    values["full_test_count"] = 10
    values["full_test_pass_count"] = 10 if succeeded else 9
    values["full_test_fail_count"] = 0 if succeeded else 1
    values["semantic_outcome_match_count"] = int(succeeded)
    values["first_attempt_success_count"] = int(succeeded and attempt == 1)
    values["correct_accepted_patch_rate_bp"] = 10000 if succeeded else 0

    values["route_local_count"] = int(configuration_id in {"C", "D"} and frontier == 0)
    values["route_frontier_count"] = int(configuration_id in {"A", "B"} or frontier == 1)
    values["frontier_escalation_count"] = frontier if configuration_id in {"C", "D"} else None
    values["routine_localized_task_count"] = (
        int(routine) if configuration_id in {"C", "D"} else None
    )
    values["routine_frontier_escalation_rate_bp"] = (
        frontier * 10000 if configuration_id in {"C", "D"} and routine else None
    )

    if configuration_id in {"C", "D"}:
        values["selected_test_count"] = 1
        values["selected_test_pass_count"] = int(succeeded)
        values["selected_test_fail_count"] = int(not succeeded)
        values["proof_selected_count"] = 1
        values["proof_executed_count"] = 1
        values["proof_pass_count"] = int(succeeded)
        values["proof_fail_count"] = int(not succeeded)
        values["verification_reuse_hit_count"] = 0
        values["verification_reuse_miss_count"] = 1
        values["verification_full_fallback_count"] = 0
        values["stale_capsule_rejected_count"] = 0
        values["stale_capsule_accepted_count"] = 0
        values["stale_proof_rejected_count"] = 0
        values["stale_proof_accepted_count"] = 0
        values["controlled_selected_test_false_negative_count"] = 0
        values["route_failure_count"] = 0

    if configuration_id == "D" and succeeded:
        values["assurance_mutant_count"] = 4
        values["assurance_mutant_detected_count"] = 4
        values["assurance_mutant_survivor_count"] = 0
        values["omission_mutant_count"] = 1
        values["omission_mutant_detected_count"] = 1
        values["vacuity_mutant_count"] = 1
        values["vacuity_mutant_detected_count"] = 1
        values["context_expansion_mutant_count"] = 1
        values["context_expansion_mutant_detected_count"] = 1
        values["critical_mutant_accepted_count"] = 0
        values["assurance_sample_count"] = 4
        values["assurance_failure_count"] = 0
        values["human_review_required_count"] = 0
        values["human_review_correct_count"] = 0
        values["negative_review_autonomous_accept_count"] = 0

    values["provider_call_count"] = 1
    if total_cost is None:
        for name in (
            "inference_cost_micros",
            "verification_cost_micros",
            "proof_cost_micros",
            "assurance_cost_micros",
            "failure_cost_micros",
            "human_cost_micros",
            "total_cost_micros",
            "failed_attempt_cost_micros",
            "cost_per_correct_accepted_patch_micros",
        ):
            values[name] = None
    else:
        verification_cost = min(20, total_cost)
        values["inference_cost_micros"] = total_cost - verification_cost
        values["verification_cost_micros"] = verification_cost
        values["proof_cost_micros"] = 0
        values["assurance_cost_micros"] = 0
        values["failure_cost_micros"] = 0
        values["human_cost_micros"] = 0
        values["total_cost_micros"] = total_cost
        values["failed_attempt_cost_micros"] = 0 if succeeded else total_cost
        values["cost_per_correct_accepted_patch_micros"] = total_cost if succeeded else None
    values["total_cost_reduction_bp"] = None

    missingness = {
        name: "not-observed-or-not-applicable-fixture"
        for name, value in values.items()
        if value is None
    }
    return {
        "schema": spec.RAW_RESULT_SCHEMA,
        "run_key": (
            f"fixture/{task}/{configuration_id}/{seed}/{attempt}/{environment}/"
            f"{provider}/{model_revision}"
        ),
        "corpus_manifest_cid": _cid("manifest"),
        "task_record_cid": _cid(f"task:{task}"),
        "visible_projection_cid": _cid(f"visible:{task}"),
        "configuration_id": configuration_id,
        "configuration_cid": CONFIGURATION_CIDS[configuration_id],
        "repository_state_cid": _cid(f"repository:{task}"),
        "environment_cid": _cid(environment),
        "provider_id": provider,
        "model_id": model,
        "model_revision": model_revision,
        "seed": seed,
        "attempt": attempt,
        "provenance": provenance,
        "terminal_status": status,
        "metrics": values,
        "missingness": missingness,
        "evidence_cids": [_cid(f"evidence:{task}:{configuration_id}:{attempt}")],
    }


def _set_metric(row: dict[str, Any], name: str, value: int | None) -> dict[str, Any]:
    changed = deepcopy(row)
    changed["metrics"][name] = value
    if value is None:
        changed["missingness"][name] = "explicit-fixture-missingness"
    else:
        changed["missingness"].pop(name, None)
    return changed


def _as_failed(row: dict[str, Any]) -> dict[str, Any]:
    """Retain one held identity while making its terminal score a frozen failure zero."""

    changed = deepcopy(row)
    changed["terminal_status"] = "verification_failed"
    for name, value in (
        ("accepted_patch_count", 0),
        ("correct_accepted_patch_count", 0),
        ("semantic_outcome_match_count", 0),
        ("first_attempt_success_count", 0),
        ("correct_accepted_patch_rate_bp", 0),
        ("failed_attempt_cost_micros", changed["metrics"]["total_cost_micros"]),
        ("cost_per_correct_accepted_patch_micros", None),
    ):
        changed = _set_metric(changed, name, value)
    return changed


def _without_suite_observation(row: dict[str, Any]) -> dict[str, Any]:
    """Mirror a canonical pre-verification row without inventing suite counts."""

    changed = deepcopy(row)
    for name in (
        "full_test_count",
        "full_test_pass_count",
        "full_test_fail_count",
        "hidden_test_total_count",
        "hidden_test_pass_count",
    ):
        changed = _set_metric(changed, name, None)
    return changed


def _passing_population(*, provenance: str = "live") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(4):
        task = f"task-{index}"
        rows.append(_row(task, "A", provenance=provenance, context=100, total_cost=100))
        rows.append(
            _row(
                task,
                "D",
                provenance=provenance,
                context=40,
                total_cost=50,
                frontier=0,
            )
        )
    return rows


def _canonical_runner_zero_tolerance_shape(row: dict[str, Any]) -> dict[str, Any]:
    """Mirror structural nulls emitted by the frozen A/D runner modules."""

    changed = deepcopy(row)
    if changed["configuration_id"] == "A":
        structural_nulls = {
            "stale_capsule_accepted_count",
            "stale_proof_accepted_count",
            "simulated_success_accepted_count",
            "controlled_selected_test_false_negative_count",
            "critical_mutant_accepted_count",
            "negative_review_autonomous_accept_count",
        }
    else:
        structural_nulls = {"simulated_success_accepted_count"}
    for name in structural_nulls:
        changed = _set_metric(changed, name, None)
    return changed


def test_metric_descriptor_binds_all_78_frozen_metrics_and_no_execution() -> None:
    descriptor = aggregation.metric_set_descriptor()
    assert descriptor["metric_count"] == 78
    assert tuple(descriptor["metric_names"]) == tuple(
        definition["name"] for definition in spec.metric_catalog()
    )
    assert set(descriptor["derived_metric_names"]) == {
        "context_reduction_bp",
        "correct_accepted_patch_rate_bp",
        "routine_frontier_escalation_rate_bp",
        "cost_per_correct_accepted_patch_micros",
        "total_cost_reduction_bp",
    }
    assert descriptor["provider_calls"] is False
    assert descriptor["benchmark_results_claimed"] is False
    assert descriptor["production_qualification_claimed"] is False
    assert aggregation.METRIC_SET_DESCRIPTOR_CID == spec.structured_cid(descriptor)


def test_golden_configuration_aggregate_includes_failed_quality_and_cost() -> None:
    success = _row("one", "A", total_cost=100)
    failure = _row("two", "A", status="verification_failed", total_cost=120)
    result = aggregation.aggregate_configuration([failure, success], "A")

    assert tuple(result["metrics"]) == aggregation.METRIC_NAMES
    assert len(result["metrics"]) == 78
    assert result["metrics"]["eligible_task_count"] == 2
    assert result["metrics"]["correct_accepted_patch_count"] == 1
    assert result["metrics"]["correct_accepted_patch_rate_bp"] == 5000
    assert result["metrics"]["total_cost_micros"] == 220
    assert result["metrics"]["failed_attempt_cost_micros"] == 120
    assert result["metrics"]["cost_per_correct_accepted_patch_micros"] == 220
    assert result["metrics"]["context_reduction_bp"] is None
    assert result["missingness"]["context_reduction_bp"] == (
        "held-identity-paired-comparison-required"
    )
    trace = result["semantic_outcome_trace"]
    failed = next(item for item in trace if item["terminal_status"] != "succeeded")
    assert failed["scored_correct_accepted_patch_count"] == 0
    assert failed["failure_or_abstention_scored_zero"] is True


def test_unavailable_attempt_scores_zero_without_imputing_raw_quality() -> None:
    row = _row("unavailable", "A", status="unavailable", total_cost=80)
    row = _set_metric(row, "accepted_patch_count", None)
    row = _set_metric(row, "correct_accepted_patch_count", None)
    row = _set_metric(row, "correct_accepted_patch_rate_bp", None)
    aggregate = aggregation.aggregate_configuration([row], "A")

    assert aggregate["metrics"]["correct_accepted_patch_count"] is None
    assert aggregate["metrics"]["correct_accepted_patch_rate_bp"] == 0
    assert aggregate["metrics"]["total_cost_micros"] == 80
    trace = aggregate["semantic_outcome_trace"][0]
    assert trace["reported_correct_accepted_patch_count"] is None
    assert trace["scored_correct_accepted_patch_count"] == 0
    expected_reason_id = "sha256:" + hashlib.sha256(b"explicit-fixture-missingness").hexdigest()
    assert aggregate["metric_evidence"]["correct_accepted_patch_rate_bp"][
        "input_missing_reason_ids"
    ] == [expected_reason_id]


def test_missing_cost_stays_null_and_partial_observations_are_explicit() -> None:
    observed = _row("observed", "D", total_cost=50)
    missing = _row("missing", "D", status="infrastructure_failure", total_cost=None)
    aggregate = aggregation.aggregate_configuration([observed, missing], "D")

    assert aggregate["metrics"]["total_cost_micros"] is None
    assert aggregate["metrics"]["cost_per_correct_accepted_patch_micros"] is None
    evidence = aggregate["metric_evidence"]["total_cost_micros"]
    assert evidence["observed_result_count"] == 1
    assert evidence["missing_result_count"] == 1
    assert evidence["partial_observed_value"] == 50
    assert "input-missing" in aggregate["missingness"]["total_cost_micros"]
    derived = aggregate["metric_evidence"]["cost_per_correct_accepted_patch_micros"]
    assert derived["observed_result_count"] == 1
    assert derived["missing_result_count"] == 1
    assert (
        derived["observed_result_count"] + derived["missing_result_count"]
        == (aggregate["result_count"])
    )
    raw_reason_id = (
        "sha256:" + hashlib.sha256(b"not-observed-or-not-applicable-fixture").hexdigest()
    )
    policy_reason_id = (
        "sha256:" + hashlib.sha256(b"one-or-more-total-cost-observations-missing").hexdigest()
    )
    assert derived["input_missing_reason_ids"] == [raw_reason_id]
    assert policy_reason_id not in derived["input_missing_reason_ids"]


def test_aggregate_set_is_order_stable_and_labels_each_configuration() -> None:
    rows = [_row("one", "D"), _row("one", "A")]
    forward = aggregation.aggregate_results(rows)
    reverse = aggregation.aggregate_results(list(reversed(rows)))
    assert forward == reverse
    assert aggregation.aggregate_cid(forward) == aggregation.aggregate_cid(reverse)
    assert forward["configuration_ids"] == ["A", "D"]
    assert forward["aggregates"]["A"]["configuration_cid"] == CONFIGURATION_CIDS["A"]
    assert forward["aggregates"]["D"]["configuration_cid"] == CONFIGURATION_CIDS["D"]


def test_population_rejects_duplicate_result_and_configuration_cid_drift() -> None:
    row = _row("duplicate", "A")
    with pytest.raises(aggregation.MetricAggregationError, match="duplicate run_key"):
        aggregation.aggregate_results([row, deepcopy(row)])

    drifted = deepcopy(row)
    drifted["configuration_cid"] = _cid("not-configuration-A")
    with pytest.raises(aggregation.MetricAggregationError, match="non-frozen CID"):
        aggregation.aggregate_results([drifted])


def test_population_rejects_an_omitted_prior_failed_attempt() -> None:
    later_only = _row("retry-gap", "A", attempt=2)
    with pytest.raises(aggregation.MetricAggregationError, match="cannot be omitted"):
        aggregation.aggregate_results([later_only])


def test_population_rejects_a_retry_after_terminal_success() -> None:
    rows = [
        _row("retry-after-success", "A", attempt=1),
        _row("retry-after-success", "A", attempt=2),
    ]
    with pytest.raises(aggregation.MetricAggregationError, match="later retry"):
        aggregation.aggregate_results(rows)


def test_population_retains_null_then_observed_suite_denominators_across_retries() -> None:
    unavailable = _row(
        "canonical-ab-retry",
        "A",
        attempt=1,
        status="unavailable",
        context=126,
        total_cost=None,
    )
    unavailable = _set_metric(unavailable, "provider_call_count", 0)
    unavailable = _set_metric(unavailable, "patch_proposal_count", 0)
    unavailable = _without_suite_observation(unavailable)
    succeeded = _row(
        "canonical-ab-retry",
        "A",
        attempt=2,
        context=126,
        total_cost=400,
    )
    for name, value in (
        ("full_test_count", 12),
        ("full_test_pass_count", 12),
        ("hidden_test_total_count", 4),
        ("hidden_test_pass_count", 4),
    ):
        succeeded = _set_metric(succeeded, name, value)

    aggregate = aggregation.aggregate_configuration([unavailable, succeeded], "A")
    assert aggregate["metrics"]["full_test_count"] is None
    assert aggregate["metrics"]["hidden_test_total_count"] is None
    for name in ("full_test_count", "hidden_test_total_count"):
        evidence = aggregate["metric_evidence"][name]
        assert evidence["observed_result_count"] == 1
        assert evidence["missing_result_count"] == 1
    assert aggregate["metrics"]["correct_accepted_patch_rate_bp"] == 10000
    assert aggregate["metrics"]["total_cost_micros"] is None
    assert aggregate["metrics"]["cost_per_correct_accepted_patch_micros"] is None
    assert aggregate["missingness"]["cost_per_correct_accepted_patch_micros"] == (
        "one-or-more-total-cost-observations-missing"
    )


@pytest.mark.parametrize(
    ("denominator", "terminal_value", "terminal_passed"),
    (
        ("full_test_count", 11, "full_test_pass_count"),
        ("hidden_test_total_count", 6, "hidden_test_pass_count"),
    ),
)
def test_population_rejects_suite_denominator_drift_across_retries(
    denominator: str,
    terminal_value: int,
    terminal_passed: str,
) -> None:
    failed = _row("suite-denominator-retry-drift", "A", attempt=1, status="verification_failed")
    succeeded = _row("suite-denominator-retry-drift", "A", attempt=2)
    succeeded = _set_metric(succeeded, denominator, terminal_value)
    succeeded = _set_metric(succeeded, terminal_passed, terminal_value)

    with pytest.raises(aggregation.MetricAggregationError, match=f"{denominator} drifted"):
        aggregation.aggregate_results([failed, succeeded])


def test_failed_attempt_cost_and_component_inconsistency_fail_closed() -> None:
    failed = _row("failed", "A", status="verification_failed", total_cost=100)
    omitted = _set_metric(failed, "failed_attempt_cost_micros", None)
    with pytest.raises(aggregation.MetricAggregationError, match="must expose"):
        aggregation.aggregate_results([omitted])

    bad_total = _set_metric(failed, "total_cost_micros", 101)
    bad_total = _set_metric(bad_total, "failed_attempt_cost_micros", 101)
    with pytest.raises(aggregation.MetricAggregationError, match="components"):
        aggregation.aggregate_results([bad_total])


def test_succeeded_total_cost_cannot_hide_a_missing_component() -> None:
    row = _set_metric(
        _row("partial-success-cost", "D", total_cost=50),
        "verification_cost_micros",
        None,
    )
    with pytest.raises(aggregation.MetricAggregationError, match="missing component"):
        aggregation.aggregate_results([row])


def test_failed_partial_stage_cost_can_retain_exact_observed_sum() -> None:
    row = _row("partial-failed-cost", "A", status="verification_failed", total_cost=100)
    row = _set_metric(row, "inference_cost_micros", 100)
    for name in (
        "verification_cost_micros",
        "proof_cost_micros",
        "assurance_cost_micros",
        "human_cost_micros",
    ):
        row = _set_metric(row, name, None)
    aggregate = aggregation.aggregate_configuration([row], "A")
    assert aggregate["metrics"]["total_cost_micros"] == 100
    assert aggregate["metrics"]["failed_attempt_cost_micros"] == 100
    assert aggregate["metrics"]["verification_cost_micros"] is None


def test_first_attempt_success_must_match_the_semantic_outcome() -> None:
    failed = _row("false-first-success", "A", status="verification_failed")
    failed["metrics"]["first_attempt_success_count"] = 1
    with pytest.raises(aggregation.MetricAggregationError, match="first_attempt_success_count"):
        aggregation.aggregate_results([failed])

    succeeded = _row("hidden-first-success", "A")
    succeeded["metrics"]["first_attempt_success_count"] = 0
    with pytest.raises(aggregation.MetricAggregationError, match="first_attempt_success_count"):
        aggregation.aggregate_results([succeeded])


def test_semantic_trace_is_counts_and_cids_only() -> None:
    row = _row("trace", "A")
    row["run_key"] = "expected_patch_bytes=TOP-SECRET-HIDDEN-ANSWER"
    trace = aggregation.semantic_outcome_trace([row])
    rendered = repr(trace).lower()
    assert "hidden_test_pass_count" not in rendered
    assert "answer_bytes" not in rendered
    assert "expected_patch" not in rendered
    assert "run_key" not in trace[0]
    assert trace[0]["result_cid"].startswith("baguqeera")


def test_comparison_trace_binds_held_identity_without_disclosing_free_text() -> None:
    rows = _passing_population()
    hidden_text = "expected_patch_bytes=TOP-SECRET-HIDDEN-ANSWER"
    for row in rows:
        row["provider_id"] = hidden_text

    report = comparison.compare_frozen_ad(rows)
    assert report["qualification_status"] == "go"
    assert hidden_text not in repr(report)
    assert all(
        set(item)
        >= {
            "held_identity_cid",
            "task_record_cid",
            "baseline_attempts",
            "candidate_attempts",
        }
        and "held_identity" not in item
        for item in report["semantic_outcome_comparison_trace"]
    )
    assert all(
        "execution_binding_cid" in attempt
        for item in report["semantic_outcome_comparison_trace"]
        for arm in ("baseline_attempts", "candidate_attempts")
        for attempt in item[arm]
    )


def test_arbitrary_missingness_text_is_replaced_by_a_digest_identity() -> None:
    hidden_text = "hidden-answer-material-must-not-escape"
    row = _set_metric(_row("missing-reason", "A"), "provider_cached_input_tokens", None)
    row["missingness"]["provider_cached_input_tokens"] = hidden_text

    aggregate = aggregation.aggregate_configuration([row], "A")
    expected_reason_id = "sha256:" + hashlib.sha256(hidden_text.encode()).hexdigest()
    assert hidden_text not in repr(aggregate)
    assert aggregate["metric_evidence"]["provider_cached_input_tokens"][
        "input_missing_reason_ids"
    ] == [expected_reason_id]
    assert expected_reason_id in aggregate["missingness"]["provider_cached_input_tokens"]


@pytest.mark.parametrize(
    "name",
    (
        "route_small_count",
        "route_local_count",
        "route_human_count",
        "route_unavailable_count",
        "model_escalation_count",
        "frontier_escalation_count",
        "routine_localized_task_count",
        "routine_frontier_escalation_rate_bp",
        "route_failure_count",
        "context_pack_tokens",
        "capsule_tokens",
        "context_expansion_count",
        "context_expansion_tokens",
        "verification_reuse_hit_count",
        "assurance_sample_count",
    ),
)
def test_successful_ab_arm_rejects_non_applicable_runner_observations(
    name: str,
) -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "A")
    rows[target_index] = _set_metric(rows[target_index], name, 1)

    with pytest.raises(comparison.BenchmarkComparisonError, match="non-applicable"):
        comparison.compare_frozen_ad(rows)


@pytest.mark.parametrize(
    "name",
    (
        "context_expansion_count",
        "context_expansion_tokens",
        "assurance_sample_count",
        "critical_mutant_accepted_count",
        "human_review_required_count",
    ),
)
def test_successful_c_arm_rejects_d_only_governance_observations(name: str) -> None:
    row = _set_metric(_row("c-governance", "C"), name, 1)
    with pytest.raises(aggregation.MetricAggregationError, match="non-applicable"):
        aggregation.aggregate_configuration([row], "C")


@pytest.mark.parametrize(
    ("count", "tokens"),
    ((0, 10), (1, 0)),
)
def test_context_expansion_count_and_tokens_must_describe_the_same_event(
    count: int,
    tokens: int,
) -> None:
    row = _set_metric(_row("invalid-expansion", "D"), "context_expansion_count", count)
    row = _set_metric(row, "context_expansion_tokens", tokens)

    with pytest.raises(aggregation.MetricAggregationError, match="both be zero or both"):
        aggregation.aggregate_configuration([row], "D")


def test_derived_routing_rate_requires_observed_numerator_and_denominator() -> None:
    row = _row("unbound-routing-rate", "D", status="unavailable", total_cost=None)
    row = _set_metric(row, "routine_localized_task_count", None)
    row = _set_metric(row, "frontier_escalation_count", None)
    row = _set_metric(row, "routine_frontier_escalation_rate_bp", 10000)

    with pytest.raises(aggregation.MetricAggregationError, match="observed numerator"):
        aggregation.aggregate_configuration([row], "D")


@pytest.mark.parametrize(
    ("configuration_id", "name", "value", "message"),
    (
        ("D", "ordinary_retrieval_tokens", 100, "non-applicable"),
        ("D", "capsule_tokens", 50, "component tokens"),
        ("D", "exact_source_tokens", 50, "component tokens"),
        ("A", "exact_source_tokens", 120, "cannot exceed"),
    ),
)
def test_context_metrics_must_match_the_frozen_emitter_semantics(
    configuration_id: str,
    name: str,
    value: int,
    message: str,
) -> None:
    row = _set_metric(_row("context-emitter", configuration_id), name, value)

    with pytest.raises(aggregation.MetricAggregationError, match=message):
        aggregation.aggregate_configuration([row], configuration_id)


@pytest.mark.parametrize(
    ("observed_name", "missing_name"),
    (
        ("capsule_tokens", "exact_source_tokens"),
        ("exact_source_tokens", "capsule_tokens"),
    ),
)
def test_each_observed_context_component_is_individually_bounded_by_the_pack(
    observed_name: str,
    missing_name: str,
) -> None:
    row = _row("partial-context-component", "D", context=40)
    row = _set_metric(row, missing_name, None)
    row = _set_metric(row, observed_name, 50)

    with pytest.raises(aggregation.MetricAggregationError, match="component tokens"):
        aggregation.aggregate_configuration([row], "D")


def test_non_success_label_cannot_retain_a_complete_success_trace() -> None:
    row = _row("contradictory-failure", "A")
    row["terminal_status"] = "verification_failed"

    with pytest.raises(aggregation.MetricAggregationError, match="contradicts"):
        aggregation.aggregate_configuration([row], "A")


def test_canonical_d_invalid_acceptance_authority_row_is_retained() -> None:
    row = _row("invalid-acceptance-authority", "D", provenance="replayed")
    row["terminal_status"] = "invalid"
    for name, value in (
        ("accepted_patch_count", 0),
        ("correct_accepted_patch_count", 0),
        ("first_attempt_success_count", 0),
        ("correct_accepted_patch_rate_bp", 0),
        ("failed_attempt_cost_micros", row["metrics"]["total_cost_micros"]),
        ("cost_per_correct_accepted_patch_micros", None),
    ):
        row = _set_metric(row, name, value)

    admitted = aggregation.validate_result_population([row])
    assert admitted[0]["terminal_status"] == "invalid"
    assert admitted[0]["metrics"]["semantic_outcome_match_count"] == 1
    assert admitted[0]["metrics"]["accepted_patch_count"] == 0


def test_canonical_c_simulated_verification_complete_row_is_retained() -> None:
    row = _row("simulated-verification-complete", "C", provenance="simulated")
    row["terminal_status"] = "simulated"
    for name, value in (
        ("accepted_patch_count", 0),
        ("correct_accepted_patch_count", 0),
        ("first_attempt_success_count", 0),
        ("correct_accepted_patch_rate_bp", 0),
        ("proof_executed_count", 0),
        ("proof_pass_count", 0),
        ("verification_reuse_hit_count", 1),
        ("verification_reuse_miss_count", 0),
        ("simulated_success_accepted_count", 0),
        ("failed_attempt_cost_micros", row["metrics"]["total_cost_micros"]),
        ("cost_per_correct_accepted_patch_micros", None),
    ):
        row = _set_metric(row, name, value)

    admitted = aggregation.validate_result_population([row])
    assert admitted[0]["terminal_status"] == "simulated"
    assert admitted[0]["metrics"]["semantic_outcome_match_count"] == 1
    assert admitted[0]["metrics"]["accepted_patch_count"] == 0


def test_golden_ad_qualification_vector_hits_all_declared_thresholds() -> None:
    report = comparison.compare_frozen_ad(_passing_population())
    gates = report["gates"]

    assert report["baseline"] == {
        "configuration_id": "A",
        "configuration_cid": CONFIGURATION_CIDS["A"],
        "label": "explicit-frozen-baseline-A",
    }
    assert report["candidate"]["configuration_id"] == "D"
    assert gates["context_reduction"]["bootstrap"]["point_estimate_bp"] == 6000
    assert gates["total_cost_reduction"]["bootstrap"]["point_estimate_bp"] == 5000
    assert gates["accepted_patch_noninferiority"]["bootstrap"]["point_estimate_bp"] == 0
    assert gates["routine_frontier_escalation"]["bootstrap"]["point_estimate_bp"] == 0
    assert gates["accepted_patch_noninferiority"]["decision_confidence_side"] == ("one-sided-lower")
    assert gates["routine_frontier_escalation"]["decision_confidence_side"] == ("one-sided-upper")
    assert {gate["decision"] for gate in gates.values()} == {"pass"}
    assert {check["decision"] for check in report["zero_tolerance"].values()} == {"pass"}
    assert report["qualification_status"] == "go"
    assert report["decision_scope"].endswith("production-qualification")
    assert report["provider_calls_performed"] == 0
    assert report["benchmark_execution_performed"] is False


def test_frozen_b_vs_a_context_diagnostic_is_paired_and_descriptive_only() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(3):
        task = f"diagnostic-{index}"
        rows.extend([_row(task, "A", context=100), _row(task, "B", context=40)])
    diagnostic = comparison.compare_context_arms(rows)
    assert diagnostic["baseline"]["configuration_id"] == "A"
    assert diagnostic["candidate"]["configuration_id"] == "B"
    assert diagnostic["diagnostic_label"] == "frozen-isolated-B-vs-A"
    assert diagnostic["bootstrap"]["point_estimate_bp"] == 6000
    assert diagnostic["bootstrap"]["replicates_drawn"] == 10000
    assert diagnostic["pairing"]["paired_task_cluster_count"] == 3
    assert diagnostic["qualification_decision"] is None
    assert diagnostic["decision_scope"].endswith("only")


def test_bootstrap_is_exact_seeded_paired_and_order_deterministic() -> None:
    rows = _passing_population()
    first = comparison.compare_frozen_ad(rows)
    second = comparison.compare_frozen_ad(list(reversed(rows)))
    assert first == second
    assert comparison.comparison_cid(first) == comparison.comparison_cid(second)
    for gate in first["gates"].values():
        bootstrap = gate["bootstrap"]
        assert bootstrap["method"] == ("seeded-percentile-paired-task-cluster-bootstrap")
        assert bootstrap["seed"] == 60060
        assert bootstrap["replicates_requested"] == 10000
        assert bootstrap["replicates_drawn"] == 10000
        assert bootstrap["undefined_replicates"] == 0


def test_retry_attempts_resample_together_as_two_task_clusters() -> None:
    rows = [
        _row("one", "A", attempt=1, status="verification_failed", total_cost=30),
        _row("one", "D", attempt=1, status="verification_failed", total_cost=20),
        _row("one", "A", attempt=2, total_cost=100),
        _row("one", "D", attempt=2, total_cost=50),
        _row("two", "A", total_cost=100),
        _row("two", "D", total_cost=50),
    ]
    report = comparison.compare_frozen_ad(rows)
    assert report["pairing"]["paired_attempt_count"] == 3
    assert report["pairing"]["paired_task_cluster_count"] == 2
    assert report["gates"]["context_reduction"]["bootstrap"]["task_cluster_count"] == 2
    a = aggregation.aggregate_configuration(rows, "A")
    assert a["metrics"]["total_cost_micros"] == 230
    assert a["metrics"]["failed_attempt_cost_micros"] == 30
    assert a["metrics"]["correct_accepted_patch_rate_bp"] == 10000
    assert a["metrics"]["cost_per_correct_accepted_patch_micros"] == 115


def test_arms_with_different_contiguous_retry_counts_pair_as_one_task() -> None:
    rows = [
        _row("different-retries", "A", attempt=1, total_cost=100),
        _row(
            "different-retries",
            "D",
            attempt=1,
            status="verification_failed",
            total_cost=20,
        ),
        _row("different-retries", "D", attempt=2, total_cost=50),
    ]

    report = comparison.compare_frozen_ad(rows)
    pairing = report["pairing"]
    assert pairing["paired_task_cluster_count"] == 1
    assert pairing["baseline_attempt_count"] == 1
    assert pairing["candidate_attempt_count"] == 2
    assert pairing["differing_retry_count_task_cluster_count"] == 1
    assert pairing["unmatched_baseline_count"] == 0
    assert pairing["unmatched_candidate_count"] == 0

    trace = report["semantic_outcome_comparison_trace"][0]
    assert trace["baseline_total_cost_micros"] == 100
    assert trace["candidate_total_cost_micros"] == 70
    assert [item["total_cost_micros"] for item in trace["candidate_attempts"]] == [
        20,
        50,
    ]
    assert trace["baseline_terminal_status"] == "succeeded"
    assert trace["candidate_terminal_status"] == "succeeded"
    assert trace["baseline_scored_correct"] == 1
    assert trace["candidate_scored_correct"] == 1


def test_retry_count_does_not_reweight_task_context_or_routing_statistics() -> None:
    rows = [
        _row(
            "retried",
            "A",
            attempt=1,
            status="verification_failed",
            context=100,
            total_cost=20,
        ),
        _row(
            "retried",
            "D",
            attempt=1,
            status="verification_failed",
            context=100,
            total_cost=10,
            frontier=1,
        ),
        _row("retried", "A", attempt=2, context=100, total_cost=100),
        _row("retried", "D", attempt=2, context=100, total_cost=50, frontier=0),
        _row("first-try", "A", context=100, total_cost=100),
        _row("first-try", "D", context=0, total_cost=50, frontier=0),
    ]
    report = comparison.compare_frozen_ad(rows)
    assert report["pairing"]["paired_attempt_count"] == 3
    assert report["pairing"]["paired_task_cluster_count"] == 2
    assert report["gates"]["context_reduction"]["bootstrap"]["point_estimate_bp"] == 5000
    assert report["gates"]["routine_frontier_escalation"]["bootstrap"]["point_estimate_bp"] == 5000
    assert report["gates"]["accepted_patch_noninferiority"]["bootstrap"]["point_estimate_bp"] == 0


def test_context_measurement_cannot_drift_across_retries_for_one_task() -> None:
    rows = [
        _row("drift", "A", attempt=1, status="verification_failed", context=100),
        _row("drift", "D", attempt=1, status="verification_failed", context=40),
        _row("drift", "A", attempt=2, context=100),
        _row("drift", "D", attempt=2, context=30),
    ]
    with pytest.raises(comparison.BenchmarkComparisonError, match="drifted across retry"):
        comparison.compare_frozen_ad(rows)


def test_proportional_raw_context_drift_across_retries_is_rejected() -> None:
    rows = [
        _row(
            "proportional-drift",
            "A",
            attempt=1,
            status="verification_failed",
            context=100,
        ),
        _row(
            "proportional-drift",
            "D",
            attempt=1,
            status="verification_failed",
            context=40,
        ),
        _row("proportional-drift", "A", attempt=2, context=200),
        _row("proportional-drift", "D", attempt=2, context=80),
    ]
    rows[-1] = _set_metric(rows[-1], "context_reduction_bp", 6000)

    with pytest.raises(comparison.BenchmarkComparisonError, match="drifted across retry"):
        comparison.compare_frozen_ad(rows)


def test_one_task_is_inconclusive_despite_complete_10000_draws() -> None:
    rows = [_row("only", "A"), _row("only", "D", total_cost=50)]
    report = comparison.compare_frozen_ad(rows)
    context = report["gates"]["context_reduction"]
    assert context["bootstrap"]["replicates_drawn"] == 10000
    assert context["decision"] == "inconclusive-no-go"
    assert context["reason"] == "insufficient-paired-task-clusters"
    assert report["qualification_status"] == "no-go"


def test_zero_correct_patch_denominator_is_unavailable_not_zero_cost() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(2):
        task = f"failed-{index}"
        rows.extend(
            [
                _row(task, "A", status="verification_failed", total_cost=100),
                _row(task, "D", status="verification_failed", total_cost=50),
            ]
        )
    report = comparison.compare_frozen_ad(rows)
    cost = report["gates"]["total_cost_reduction"]
    assert cost["bootstrap"]["point_estimate_bp"] is None
    assert cost["decision"] == "unavailable-no-go"
    assert cost["reason"] == "zero-cost-or-correct-patch-denominator"


def test_missing_context_denominator_is_unavailable_and_never_dropped() -> None:
    rows = _passing_population()
    target = next(row for row in rows if row["configuration_id"] == "D")
    changed = _set_metric(target, "context_pack_tokens", None)
    changed = _set_metric(changed, "exact_source_tokens", None)
    changed = _set_metric(changed, "capsule_tokens", None)
    changed = _set_metric(changed, "context_reduction_bp", None)
    rows[rows.index(target)] = changed
    report = comparison.compare_frozen_ad(rows)
    gate = report["gates"]["context_reduction"]
    assert gate["bootstrap"]["point_estimate_bp"] is None
    assert gate["decision"] == "unavailable-no-go"
    assert report["pairing"]["paired_attempt_count"] == 4


def test_reported_context_reduction_cannot_override_paired_raw_values() -> None:
    rows = _passing_population()
    target = next(row for row in rows if row["configuration_id"] == "D")
    rows[rows.index(target)] = _set_metric(target, "context_reduction_bp", 5999)
    with pytest.raises(comparison.BenchmarkComparisonError, match="contradicts"):
        comparison.compare_frozen_ad(rows)


def test_identity_drift_is_rejected_instead_of_becoming_an_unpaired_drop() -> None:
    rows = _passing_population()
    target = next(row for row in rows if row["configuration_id"] == "D")
    drifted = deepcopy(target)
    drifted["environment_cid"] = _cid("different-environment")
    rows[rows.index(target)] = drifted
    with pytest.raises(comparison.BenchmarkComparisonError, match="identity drift"):
        comparison.compare_frozen_ad(rows)


def test_provider_model_revision_are_arm_local_reported_bindings_not_pair_identity() -> None:
    rows = _passing_population()
    for row in rows:
        if row["configuration_id"] == "A":
            row["provider_id"] = "provider/frontier"
            row["model_id"] = "frontier-model"
            row["model_revision"] = "frontier-model@immutable"
        else:
            row["provider_id"] = "provider/local"
            row["model_id"] = "local-model"
            row["model_revision"] = "local-model@immutable"

    report = comparison.compare_frozen_ad(rows)
    assert report["qualification_status"] == "go"
    pairing = report["pairing"]
    assert pairing["arm_execution_identity_fields"] == [
        "provider_id",
        "model_id",
        "model_revision",
    ]
    assert all(
        field not in pairing["held_task_identity_fields"]
        for field in pairing["arm_execution_identity_fields"]
    )
    assert all(
        item["baseline_attempts"][0]["execution_binding_cid"]
        != item["candidate_attempts"][0]["execution_binding_cid"]
        for item in report["semantic_outcome_comparison_trace"]
    )


def test_null_suite_denominators_can_pair_with_observed_other_arm() -> None:
    baseline = _row(
        "canonical-ab-unavailable-vs-d",
        "A",
        status="unavailable",
        context=126,
        total_cost=None,
    )
    baseline = _set_metric(baseline, "provider_call_count", 0)
    baseline = _set_metric(baseline, "patch_proposal_count", 0)
    baseline = _without_suite_observation(baseline)
    candidate = _row(
        "canonical-ab-unavailable-vs-d",
        "D",
        context=40,
        total_cost=50,
    )
    for name, value in (
        ("full_test_count", 12),
        ("full_test_pass_count", 12),
        ("hidden_test_total_count", 4),
        ("hidden_test_pass_count", 4),
        ("context_reduction_bp", None),
    ):
        candidate = _set_metric(candidate, name, value)

    report = comparison.compare_frozen_ad([baseline, candidate])
    cost_gate = report["gates"]["total_cost_reduction"]
    assert cost_gate["decision"] == "unavailable-no-go"
    assert cost_gate["reason"] == "one-or-more-paired-total-cost-observations-missing"
    trace = report["semantic_outcome_comparison_trace"][0]
    assert trace["full_test_denominator_evidence"] == {
        "observed_value": 12,
        "baseline_observed_attempt_count": 0,
        "baseline_missing_attempt_count": 1,
        "candidate_observed_attempt_count": 1,
        "candidate_missing_attempt_count": 0,
    }
    assert trace["hidden_test_denominator_evidence"]["observed_value"] == 4
    assert trace["hidden_test_denominator_evidence"]["baseline_missing_attempt_count"] == 1


@pytest.mark.parametrize(
    ("denominator", "passed", "changed_value"),
    (
        ("full_test_count", "full_test_pass_count", 11),
        ("hidden_test_total_count", "hidden_test_pass_count", 6),
    ),
)
def test_conflicting_observed_suite_denominators_are_rejected_across_arms(
    denominator: str,
    passed: str,
    changed_value: int,
) -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    changed = _set_metric(rows[target_index], denominator, changed_value)
    changed = _set_metric(changed, passed, changed_value)
    rows[target_index] = changed

    with pytest.raises(comparison.BenchmarkComparisonError, match=f"{denominator} denominator"):
        comparison.compare_frozen_ad(rows)


def test_unmatched_results_are_explicit_and_block_overall_go() -> None:
    rows = _passing_population()
    rows.append(_row("baseline-only", "A"))
    report = comparison.compare_frozen_ad(rows)
    assert report["pairing"]["unmatched_baseline_count"] == 1
    assert report["pairing"]["unmatched_candidate_count"] == 0
    assert "unpaired-held-identity-results" in report["qualification_blockers"]
    assert report["qualification_status"] == "no-go"


def test_replay_is_descriptive_and_cannot_satisfy_live_quality_or_cost() -> None:
    report = comparison.compare_frozen_ad(_passing_population(provenance="replayed"))
    assert report["gates"]["context_reduction"]["bootstrap"]["point_estimate_bp"] == 6000
    assert report["gates"]["accepted_patch_noninferiority"]["decision"] == ("unavailable-no-go")
    assert report["gates"]["total_cost_reduction"]["decision"] == ("unavailable-no-go")
    assert report["evidence"]["all_paired_quality_live"] is False
    assert report["evidence"]["all_paired_cost_observed_live"] is False
    assert report["evidence"]["estimated_cost_can_pass"] is False
    assert report["qualification_status"] == "no-go"


def test_live_label_without_evidence_cannot_qualify() -> None:
    rows = _passing_population()
    first_candidate = next(row for row in rows if row["configuration_id"] == "D")
    first_candidate["evidence_cids"] = []
    report = comparison.compare_frozen_ad(rows)
    assert report["evidence"]["all_paired_quality_live"] is False
    assert report["evidence"]["all_paired_cost_observed_live"] is False
    assert report["gates"]["accepted_patch_noninferiority"]["decision"] == ("unavailable-no-go")
    assert report["gates"]["total_cost_reduction"]["decision"] == ("unavailable-no-go")


def test_succeeded_live_label_without_provider_call_is_rejected() -> None:
    rows = _passing_population()
    rows[0]["metrics"]["provider_call_count"] = 0
    with pytest.raises(comparison.BenchmarkComparisonError, match="provider call"):
        comparison.compare_frozen_ad(rows)


def test_valid_undispatched_live_rows_cannot_satisfy_live_quality() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(2):
        for configuration_id in ("A", "D"):
            row = _row(
                f"undispatched-{index}",
                configuration_id,
                status="unavailable",
                total_cost=None,
            )
            row = _set_metric(row, "provider_call_count", 0)
            row = _set_metric(row, "patch_proposal_count", 0)
            rows.append(row)
    report = comparison.compare_frozen_ad(rows)
    quality = report["gates"]["accepted_patch_noninferiority"]
    assert quality["decision"] == "unavailable-no-go"
    assert quality["evidence_eligible"] is False
    assert report["evidence"]["all_paired_quality_live"] is False
    routine = report["gates"]["routine_frontier_escalation"]
    assert routine["decision"] == "unavailable-no-go"
    assert routine["evidence_eligible"] is False


def test_partial_failed_cost_is_descriptive_and_cannot_qualify_as_complete_cost() -> None:
    rows = _passing_population()
    target = next(row for row in rows if row["configuration_id"] == "D")
    target["terminal_status"] = "verification_failed"
    for name, value in (
        ("accepted_patch_count", 0),
        ("correct_accepted_patch_count", 0),
        ("semantic_outcome_match_count", 0),
        ("first_attempt_success_count", 0),
        ("correct_accepted_patch_rate_bp", 0),
        ("inference_cost_micros", target["metrics"]["total_cost_micros"]),
        ("verification_cost_micros", None),
        ("proof_cost_micros", None),
        ("assurance_cost_micros", None),
        ("human_cost_micros", None),
        ("failed_attempt_cost_micros", target["metrics"]["total_cost_micros"]),
        ("cost_per_correct_accepted_patch_micros", None),
    ):
        changed = _set_metric(target, name, value)
        target.clear()
        target.update(changed)

    report = comparison.compare_frozen_ad(rows)
    cost = report["gates"]["total_cost_reduction"]
    assert cost["bootstrap"]["point_estimate_bp"] is not None
    assert cost["evidence_eligible"] is False
    assert cost["decision"] == "unavailable-no-go"
    assert report["evidence"]["all_paired_cost_observed_live"] is False


def test_noninferiority_uses_candidate_minus_baseline_lower_bound() -> None:
    rows = _passing_population()
    for index, row in enumerate(rows):
        if row["configuration_id"] == "D":
            rows[index] = _row(
                row["task_record_cid"],
                "D",
                status="verification_failed",
                context=40,
                total_cost=50,
            )
            # Keep the original task identities; only the semantic outcome changes.
            for field in (
                "run_key",
                "task_record_cid",
                "visible_projection_cid",
                "repository_state_cid",
                "evidence_cids",
            ):
                rows[index][field] = row[field]
    report = comparison.compare_frozen_ad(rows)
    gate = report["gates"]["accepted_patch_noninferiority"]
    assert gate["bootstrap"]["point_estimate_bp"] == -10000
    assert gate["decision_threshold_bp"] == -500
    assert gate["decision"] == "fail"


@pytest.mark.parametrize(
    "name",
    tuple(spec.threshold_policy()["zero_tolerance"]),
)
def test_every_zero_tolerance_invariant_is_exact(name: str) -> None:
    rows = _passing_population()
    changed = _as_failed(rows[1])
    if name == "controlled_selected_test_false_negative_count":
        changed = _set_metric(changed, "selected_test_pass_count", 1)
        changed = _set_metric(changed, "selected_test_fail_count", 0)
        changed = _set_metric(changed, "full_test_pass_count", 9)
        changed = _set_metric(changed, "full_test_fail_count", 1)
    rows[1] = _set_metric(changed, name, 1)
    report = comparison.compare_frozen_ad(rows)
    assert report["zero_tolerance"][name]["observed"] == 1
    assert report["zero_tolerance"][name]["decision"] == "fail"
    assert report["qualification_status"] == "no-go"


def test_missing_zero_tolerance_observation_cannot_be_imputed_to_zero() -> None:
    rows = _passing_population()
    name = "controlled_selected_test_false_negative_count"
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    changed = _set_metric(_as_failed(rows[target_index]), "selected_test_count", 1)
    changed = _set_metric(changed, "selected_test_pass_count", 1)
    changed = _set_metric(changed, "full_test_pass_count", 9)
    changed = _set_metric(changed, "full_test_fail_count", 1)
    rows[target_index] = _set_metric(changed, name, None)
    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"][name]
    assert check["observed"] is None
    assert check["decision"] == "unavailable-no-go"


def test_known_zero_tolerance_violation_fails_even_with_another_missing_row() -> None:
    rows = _passing_population()
    candidate_indexes = [index for index, row in enumerate(rows) if row["configuration_id"] == "D"]
    rows[candidate_indexes[0]] = _set_metric(
        _as_failed(rows[candidate_indexes[0]]),
        "critical_mutant_accepted_count",
        1,
    )
    rows[candidate_indexes[1]] = _set_metric(
        _as_failed(rows[candidate_indexes[1]]),
        "critical_mutant_accepted_count",
        None,
    )

    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"]["critical_mutant_accepted_count"]
    assert check["observed"] == 1
    assert check["observed_result_count"] == 3
    assert check["missing_result_count"] == 1
    assert check["decision"] == "fail"
    assert check["reason"] == "known-zero-tolerance-invariant-violation"
    assert report["qualification_status"] == "no-go"


def test_empty_selected_suite_does_not_disprove_a_controlled_false_negative() -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    changed = _set_metric(_as_failed(rows[target_index]), "selected_test_count", 0)
    changed = _set_metric(changed, "selected_test_pass_count", 0)
    changed = _set_metric(changed, "selected_test_fail_count", 0)
    changed = _set_metric(changed, "full_test_pass_count", 9)
    changed = _set_metric(changed, "full_test_fail_count", 1)
    rows[target_index] = _set_metric(
        changed,
        "controlled_selected_test_false_negative_count",
        None,
    )

    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"]["controlled_selected_test_false_negative_count"]
    assert check["observed"] is None
    assert check["derived_structural_zero_count"] == 0
    assert check["missing_result_count"] == 1
    assert check["decision"] == "unavailable-no-go"
    assert report["qualification_status"] == "no-go"


@pytest.mark.parametrize(
    ("selected_passed", "selected_failed", "full_passed", "full_failed", "reported"),
    (
        (1, 0, 9, 1, 0),
        (0, 1, 9, 1, 1),
        (1, 0, 10, 0, 1),
        (0, 0, 9, 1, 0),
    ),
)
def test_explicit_controlled_false_negative_must_match_frozen_runner_predicate(
    selected_passed: int,
    selected_failed: int,
    full_passed: int,
    full_failed: int,
    reported: int,
) -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    changed = _set_metric(
        _as_failed(rows[target_index]),
        "selected_test_count",
        1 if selected_failed else 0,
    )
    if selected_passed:
        changed = _set_metric(changed, "selected_test_count", 1)
    changed = _set_metric(changed, "selected_test_pass_count", selected_passed)
    changed = _set_metric(changed, "selected_test_fail_count", selected_failed)
    changed = _set_metric(changed, "full_test_count", 10)
    changed = _set_metric(changed, "full_test_pass_count", full_passed)
    changed = _set_metric(changed, "full_test_fail_count", full_failed)
    rows[target_index] = _set_metric(
        changed,
        "controlled_selected_test_false_negative_count",
        reported,
    )

    with pytest.raises(
        comparison.BenchmarkComparisonError,
        match="controlled_selected_test_false_negative_count contradicts",
    ):
        comparison.compare_frozen_ad(rows)


@pytest.mark.parametrize(
    "updates",
    (
        {"hidden_test_pass_count": 4},
        {"full_test_pass_count": 9, "full_test_fail_count": 1},
        {"selected_test_pass_count": 0, "selected_test_fail_count": 1},
        {"proof_pass_count": 0, "proof_fail_count": 1},
        {"regression_count": 1},
        {"out_of_scope_edit_count": 1},
        {"semantic_outcome_match_count": 0},
        {
            "selected_test_count": 0,
            "selected_test_pass_count": 0,
            "selected_test_fail_count": 0,
            "proof_selected_count": 0,
            "proof_executed_count": 0,
            "proof_pass_count": 0,
            "proof_fail_count": 0,
            "verification_full_fallback_count": 0,
        },
        {"route_local_count": 0, "route_frontier_count": 0},
        {"route_local_count": 1, "route_frontier_count": 1},
        {"route_local_count": 0, "route_frontier_count": 1},
        {"model_escalation_count": 99},
        {"verification_reuse_hit_count": 1, "verification_reuse_miss_count": 0},
        {
            "verification_reuse_hit_count": 0,
            "verification_reuse_miss_count": 1,
            "proof_selected_count": 2,
        },
        {"assurance_sample_count": 0},
        {"assurance_failure_count": 1},
        {"assurance_mutant_survivor_count": 1},
        {"assurance_mutant_detected_count": 5},
        {"omission_mutant_detected_count": 2},
        {"vacuity_mutant_detected_count": 2},
        {"context_expansion_mutant_detected_count": 2},
        {"human_review_required_count": 1, "human_review_correct_count": 0},
    ),
)
def test_malformed_success_cannot_reach_the_qualification_gate(
    updates: dict[str, int],
) -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    changed = rows[target_index]
    for name, value in updates.items():
        changed = _set_metric(changed, name, value)
    rows[target_index] = changed

    with pytest.raises(comparison.BenchmarkComparisonError):
        comparison.compare_frozen_ad(rows)


@pytest.mark.parametrize(
    "updates",
    (
        {
            "full_test_count": 0,
            "full_test_pass_count": 0,
            "full_test_fail_count": 0,
        },
        {
            "full_test_count": 10,
            "full_test_pass_count": 10,
            "full_test_fail_count": 0,
        },
        {
            "selected_test_count": 1,
            "selected_test_pass_count": 0,
            "selected_test_fail_count": 1,
            "full_test_count": 10,
            "full_test_pass_count": 9,
            "full_test_fail_count": 1,
        },
    ),
)
def test_controlled_false_negative_zero_is_derived_only_when_logically_proved(
    updates: dict[str, int],
) -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    changed = _as_failed(rows[target_index])
    for name, value in updates.items():
        changed = _set_metric(changed, name, value)
    rows[target_index] = _set_metric(
        changed,
        "controlled_selected_test_false_negative_count",
        None,
    )
    if updates["full_test_count"] == 0:
        baseline_index = next(
            index
            for index, row in enumerate(rows)
            if row["configuration_id"] == "A"
            and row["task_record_cid"] == changed["task_record_cid"]
        )
        baseline = _as_failed(rows[baseline_index])
        for name in ("full_test_count", "full_test_pass_count", "full_test_fail_count"):
            baseline = _set_metric(baseline, name, 0)
        rows[baseline_index] = baseline

    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"]["controlled_selected_test_false_negative_count"]
    assert check["observed"] == 0
    assert check["derived_structural_zero_count"] == 1
    assert check["missing_result_count"] == 0
    assert check["decision"] == "pass"


def test_missing_test_counts_do_not_prove_no_controlled_false_negative() -> None:
    rows = _passing_population()
    for index, row in enumerate(rows):
        if row["configuration_id"] != "D":
            continue
        changed = _set_metric(_as_failed(row), "selected_test_count", None)
        changed = _set_metric(changed, "full_test_count", None)
        rows[index] = _set_metric(
            changed,
            "controlled_selected_test_false_negative_count",
            None,
        )
        baseline_index = next(
            baseline_index
            for baseline_index, baseline in enumerate(rows)
            if baseline["configuration_id"] == "A"
            and baseline["task_record_cid"] == row["task_record_cid"]
        )
        baseline = _as_failed(rows[baseline_index])
        for name in ("full_test_count", "full_test_pass_count", "full_test_fail_count"):
            baseline = _set_metric(baseline, name, None)
        rows[baseline_index] = baseline

    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"]["controlled_selected_test_false_negative_count"]
    assert check["observed"] is None
    assert check["derived_structural_zero_count"] == 0
    assert check["missing_result_count"] == len(rows) // 2
    assert check["decision"] == "unavailable-no-go"
    assert report["qualification_status"] == "no-go"


def test_provider_zero_does_not_prove_missing_acceptance_invariants() -> None:
    rows = _passing_population()
    candidate = _row(
        "provider-zero-positive-acceptance",
        "C",
        status="verification_failed",
    )
    candidate = _set_metric(candidate, "provider_call_count", 0)
    candidate = _set_metric(candidate, "accepted_patch_count", 1)
    names = (
        "critical_regression_accepted_count",
        "stale_capsule_accepted_count",
        "stale_proof_accepted_count",
    )
    for name in names:
        candidate = _set_metric(candidate, name, None)
    rows.append(candidate)

    report = comparison.compare_frozen_ad(rows)
    for name in names:
        check = report["zero_tolerance"][name]
        assert check["observed"] is None
        assert check["missing_result_count"] == 1
        assert check["decision"] == "unavailable-no-go"
    assert report["qualification_status"] == "no-go"


@pytest.mark.parametrize(
    "name",
    (
        "stale_capsule_accepted_count",
        "stale_proof_accepted_count",
        "critical_mutant_accepted_count",
        "negative_review_autonomous_accept_count",
    ),
)
def test_final_patch_rejection_does_not_prove_independent_invariant_zero(
    name: str,
) -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    failed = _row("task-0", "D", status="verification_failed", context=40, total_cost=50)
    rows[target_index] = _set_metric(failed, name, None)

    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"][name]
    assert check["observed"] is None
    assert check["derived_structural_zero_count"] == 0
    assert check["missing_result_count"] == 1
    assert check["decision"] == "unavailable-no-go"
    assert report["qualification_status"] == "no-go"


def test_rejected_patch_proves_no_accepted_critical_regression() -> None:
    rows = _passing_population()
    target_index = next(index for index, row in enumerate(rows) if row["configuration_id"] == "D")
    failed = _row("task-0", "D", status="verification_failed", context=40, total_cost=50)
    rows[target_index] = _set_metric(failed, "critical_regression_accepted_count", None)

    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"]["critical_regression_accepted_count"]
    assert check["observed"] == 0
    assert check["derived_structural_zero_count"] == 1
    assert check["missing_result_count"] == 0
    assert check["decision"] == "pass"


def test_provider_zero_does_not_prove_missing_simulated_success_invariant() -> None:
    rows = _passing_population()
    simulated = _row(
        "provider-zero-simulated",
        "C",
        status="simulated",
        provenance="simulated",
    )
    simulated = _set_metric(simulated, "provider_call_count", 0)
    simulated = _set_metric(simulated, "accepted_patch_count", None)
    simulated = _set_metric(simulated, "simulated_success_accepted_count", None)
    rows.append(simulated)

    report = comparison.compare_frozen_ad(rows)
    check = report["zero_tolerance"]["simulated_success_accepted_count"]
    assert check["observed"] is None
    assert check["missing_result_count"] == 1
    assert check["decision"] == "unavailable-no-go"
    assert report["qualification_status"] == "no-go"


def test_canonical_runner_structural_nulls_do_not_invent_missing_violations() -> None:
    rows = [_canonical_runner_zero_tolerance_shape(row) for row in _passing_population()]
    report = comparison.compare_frozen_ad(rows)
    assert {check["decision"] for check in report["zero_tolerance"].values()} == {"pass"}
    assert report["zero_tolerance"]["simulated_success_accepted_count"][
        "derived_structural_zero_count"
    ] == len(rows)
    assert (
        report["zero_tolerance"]["critical_mutant_accepted_count"][
            "excluded_not_applicable_result_count"
        ]
        == len(rows) // 2
    )


def test_simulated_evidence_never_upgrades_and_trips_zero_tolerance() -> None:
    rows: list[dict[str, Any]] = []
    for index in range(2):
        task = f"simulated-{index}"
        for configuration_id in ("A", "D"):
            row = _row(
                task,
                configuration_id,
                status="simulated",
                provenance="simulated",
                total_cost=50,
            )
            row = _set_metric(row, "simulated_success_accepted_count", 1)
            rows.append(row)
    report = comparison.compare_frozen_ad(rows)
    assert report["zero_tolerance"]["simulated_success_accepted_count"]["decision"] == ("fail")
    assert report["evidence"]["simulated_result_count"] == 4
    assert report["qualification_status"] == "no-go"


def test_comparison_descriptor_is_the_exact_frozen_policy() -> None:
    descriptor = comparison.comparison_descriptor()
    assert descriptor["threshold_policy"] == spec.threshold_policy()
    assert descriptor["bootstrap"] == {
        "method": "seeded-percentile-paired-task-cluster-bootstrap",
        "samples": 10000,
        "seed": 60060,
        "confidence_bp": 9500,
        "confidence_side": "one-sided-lower",
        "resampling_unit": "held-task-identity-cluster-all-attempts-together",
        "percentile_rule": "integer-nearest-rank",
        "undefined_replicate_policy": "inconclusive-no-go-never-drop-or-impute",
    }
    assert descriptor["baseline_configuration_id"] == "A"
    assert descriptor["candidate_configuration_id"] == "D"
    assert descriptor["isolated_context_diagnostic"] == "B-vs-A-descriptive-only"
    assert descriptor["provider_calls"] is False
    assert descriptor["benchmark_execution"] is False
    assert descriptor["production_qualification_claimed"] is False
    assert comparison.COMPARISON_DESCRIPTOR_CID == spec.structured_cid(descriptor)

"""Deterministic paired comparison and qualification logic for PCCE-066.

Comparisons are formed only across exact held identities and are resampled as
task clusters with the preregistered 10,000-replicate seed-60060 bootstrap.
Replayed and simulated evidence remains descriptive; primary cost evidence is
eligible only when every paired cost is observed and live.
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any, Final

from ipfs_datasets_py.proof_context.benchmarks import metrics
from ipfs_datasets_py.proof_context.benchmarks import specification as spec

COMPARISON_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-comparison@1"
CONTEXT_DIAGNOSTIC_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-context-diagnostic@1"
COMPARISON_DESCRIPTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-context.benchmark-comparison-descriptor@1"
)

_POLICY: Final[dict[str, Any]] = spec.threshold_policy()
BOOTSTRAP_SAMPLES: Final[int] = _POLICY["analysis"]["bootstrap_samples"]
BOOTSTRAP_SEED: Final[int] = _POLICY["analysis"]["bootstrap_seed"]
CONFIDENCE_BP: Final[int] = _POLICY["analysis"]["confidence_bp"]
MIN_PAIRED_TASK_CLUSTERS: Final[int] = 2
BASELINE_CONFIGURATION_ID: Final[str] = "A"
CANDIDATE_CONFIGURATION_ID: Final[str] = "D"

_ZERO_TOLERANCE_APPLICABILITY: Final[dict[str, frozenset[str]]] = {
    "critical_regression_accepted_count": frozenset({"A", "B", "C", "D"}),
    "stale_capsule_accepted_count": frozenset({"C", "D"}),
    "stale_proof_accepted_count": frozenset({"C", "D"}),
    "simulated_success_accepted_count": frozenset({"A", "B", "C", "D"}),
    "controlled_selected_test_false_negative_count": frozenset({"C", "D"}),
    "critical_mutant_accepted_count": frozenset({"D"}),
    "negative_review_autonomous_accept_count": frozenset({"D"}),
}

_CONFIGURATION_CIDS: Final[dict[str, str]] = {
    item["configuration_id"]: spec.structured_cid(item) for item in spec.configuration_catalog()
}
_COST_COMPONENT_METRICS: Final[tuple[str, ...]] = (
    "inference_cost_micros",
    "verification_cost_micros",
    "proof_cost_micros",
    "assurance_cost_micros",
    "failure_cost_micros",
    "human_cost_micros",
)


class BenchmarkComparisonError(ValueError):
    """Raised when rows are not an exact, comparable frozen population."""


def _clone(value: Any) -> Any:
    return deepcopy(value)


def _value(row: Mapping[str, Any], name: str) -> int | None:
    value = row["metrics"][name]
    assert value is None or type(value) is int
    return value


def _logical_task_slot(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Identify a task/seed before validating all frozen pair bindings."""

    return (
        row["corpus_manifest_cid"],
        row["task_record_cid"],
        row["seed"],
    )


def _task_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in metrics.HELD_IDENTITY_FIELDS if field != "attempt"}


def _execution_binding_cid(row: Mapping[str, Any]) -> str:
    return spec.structured_cid(
        {field: row[field] for field in metrics.ARM_EXECUTION_IDENTITY_FIELDS}
    )


def _clusters_for_arm(
    rows: Sequence[Mapping[str, Any]],
    configuration_id: str,
) -> dict[tuple[Any, ...], tuple[Mapping[str, Any], ...]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["configuration_id"] == configuration_id:
            grouped[_logical_task_slot(row)].append(row)

    clusters: dict[tuple[Any, ...], tuple[Mapping[str, Any], ...]] = {}
    for slot, members in grouped.items():
        held_task_keys = {metrics.task_cluster_key(row) for row in members}
        if len(held_task_keys) != 1:
            raise BenchmarkComparisonError(
                "multiple held identities occupy one task configuration slot; "
                "partition populations before comparison"
            )
        clusters[slot] = tuple(sorted(members, key=lambda row: row["attempt"]))
    return clusters


def _pair_population(
    rows: Sequence[Mapping[str, Any]],
    *,
    baseline_id: str,
    candidate_id: str,
) -> tuple[
    list[dict[str, Any]],
    list[tuple[Mapping[str, Any], ...]],
    list[tuple[Mapping[str, Any], ...]],
]:
    if baseline_id == candidate_id:
        raise BenchmarkComparisonError("baseline and candidate must be different")
    if baseline_id not in spec.CONFIGURATION_IDS or candidate_id not in spec.CONFIGURATION_IDS:
        raise BenchmarkComparisonError("comparison uses an unknown configuration label")

    by_arm = {
        baseline_id: _clusters_for_arm(rows, baseline_id),
        candidate_id: _clusters_for_arm(rows, candidate_id),
    }

    baseline_slots = set(by_arm[baseline_id])
    candidate_slots = set(by_arm[candidate_id])
    common_slots = sorted(baseline_slots & candidate_slots)
    pairs: list[dict[str, Any]] = []
    for slot in common_slots:
        baseline_attempts = by_arm[baseline_id][slot]
        candidate_attempts = by_arm[candidate_id][slot]
        baseline = baseline_attempts[0]
        candidate = candidate_attempts[0]
        changed = [
            field
            for field in metrics.HELD_IDENTITY_FIELDS
            if field != "attempt" and baseline[field] != candidate[field]
        ]
        if changed:
            raise BenchmarkComparisonError(
                f"held identity drift for paired task cluster: {changed}"
            )
        held_task_identity = _task_identity(baseline)
        pairs.append(
            {
                "baseline_attempts": baseline_attempts,
                "candidate_attempts": candidate_attempts,
                "held_identity_cid": spec.structured_cid(held_task_identity),
                "held_identity_key": metrics.task_cluster_key(baseline),
                "cluster_key": metrics.task_cluster_key(baseline),
                "baseline_result_cids": tuple(
                    spec.structured_cid(row) for row in baseline_attempts
                ),
                "candidate_result_cids": tuple(
                    spec.structured_cid(row) for row in candidate_attempts
                ),
            }
        )

    unmatched_baseline = [
        by_arm[baseline_id][slot] for slot in sorted(baseline_slots - candidate_slots)
    ]
    unmatched_candidate = [
        by_arm[candidate_id][slot] for slot in sorted(candidate_slots - baseline_slots)
    ]
    return pairs, unmatched_baseline, unmatched_candidate


def _pair_semantics(pair: Mapping[str, Any]) -> dict[str, Any]:
    baseline_attempts = pair["baseline_attempts"]
    candidate_attempts = pair["candidate_attempts"]

    baseline_context = _constant_arm_metric(
        baseline_attempts,
        "ordinary_retrieval_tokens",
        arm="baseline",
        allow_missing=True,
    )
    candidate_context = _constant_arm_metric(
        candidate_attempts,
        "context_pack_tokens",
        arm="candidate",
        allow_missing=True,
    )
    if baseline_context is None or candidate_context is None or baseline_context == 0:
        context_reduction = None
    else:
        context_reduction = (baseline_context - candidate_context) * 10000 // baseline_context
        reported = {
            _value(row, "context_reduction_bp")
            for row in candidate_attempts
            if _value(row, "context_reduction_bp") is not None
        }
        if reported and reported != {context_reduction}:
            raise BenchmarkComparisonError(
                "reported context_reduction_bp contradicts paired raw context"
            )

    eligibility = _paired_frozen_denominator(
        baseline_attempts,
        candidate_attempts,
        "eligible_task_count",
    )
    full_test_denominator = _paired_suite_denominator(
        baseline_attempts,
        candidate_attempts,
        "full_test_count",
    )
    hidden_test_denominator = _paired_suite_denominator(
        baseline_attempts,
        candidate_attempts,
        "hidden_test_total_count",
    )

    baseline_terminal_score = metrics.scored_correct_outcome(baseline_attempts[-1])
    candidate_terminal_score = metrics.scored_correct_outcome(candidate_attempts[-1])

    routine = _constant_arm_metric(
        candidate_attempts,
        "routine_localized_task_count",
        arm="candidate",
        allow_missing=True,
    )
    if routine:
        frontier_values = [_value(row, "frontier_escalation_count") for row in candidate_attempts]
        routine_frontier = (
            None
            if any(value is None for value in frontier_values)
            else int(any(value for value in frontier_values if value is not None))
        )
    else:
        routine_frontier = 0 if routine == 0 else None

    all_attempts = (*baseline_attempts, *candidate_attempts)
    live_quality = all(_live_quality_attempt(row) for row in all_attempts)
    observed_live_cost = all(_observed_live_cost_attempt(row) for row in all_attempts)
    candidate_live_routing = all(_live_quality_attempt(row) for row in candidate_attempts)

    return {
        **pair,
        "eligible": eligibility,
        "baseline_correct": (
            None if baseline_terminal_score is None else baseline_terminal_score["correct"]
        ),
        "candidate_correct": (
            None if candidate_terminal_score is None else candidate_terminal_score["correct"]
        ),
        "baseline_terminal_score": baseline_terminal_score,
        "candidate_terminal_score": candidate_terminal_score,
        "baseline_context_tokens": baseline_context,
        "candidate_context_tokens": candidate_context,
        "context_reduction_bp": context_reduction,
        "full_test_count": full_test_denominator["observed_value"],
        "hidden_test_total_count": hidden_test_denominator["observed_value"],
        "full_test_denominator_evidence": full_test_denominator,
        "hidden_test_denominator_evidence": hidden_test_denominator,
        "baseline_total_cost_micros": _summed_attempt_metric(
            baseline_attempts,
            "total_cost_micros",
        ),
        "candidate_total_cost_micros": _summed_attempt_metric(
            candidate_attempts,
            "total_cost_micros",
        ),
        "candidate_routine_count": routine,
        "candidate_routine_frontier_count": routine_frontier,
        "live_quality": live_quality,
        "observed_live_cost": observed_live_cost,
        "candidate_live_routing": candidate_live_routing,
    }


def _constant_arm_metric(
    attempts: Sequence[Mapping[str, Any]],
    name: str,
    *,
    arm: str,
    allow_missing: bool,
) -> int | None:
    values = [_value(row, name) for row in attempts]
    if any(value is None for value in values):
        if all(value is None for value in values) and allow_missing:
            return None
        raise BenchmarkComparisonError(
            f"{name} observation drifted across retry attempts in the {arm} arm"
        )
    observed = {value for value in values if value is not None}
    if len(observed) != 1:
        raise BenchmarkComparisonError(f"{name} drifted across retry attempts in the {arm} arm")
    return next(iter(observed))


def _paired_frozen_denominator(
    baseline_attempts: Sequence[Mapping[str, Any]],
    candidate_attempts: Sequence[Mapping[str, Any]],
    name: str,
) -> int | None:
    baseline = _constant_arm_metric(
        baseline_attempts,
        name,
        arm="baseline",
        allow_missing=True,
    )
    candidate = _constant_arm_metric(
        candidate_attempts,
        name,
        arm="candidate",
        allow_missing=True,
    )
    if baseline != candidate:
        raise BenchmarkComparisonError(
            f"{name} denominator drift across paired arms for one held task"
        )
    return baseline


def _paired_suite_denominator(
    baseline_attempts: Sequence[Mapping[str, Any]],
    candidate_attempts: Sequence[Mapping[str, Any]],
    name: str,
) -> dict[str, int | None]:
    """Retain null suite counts while rejecting conflicting observations."""

    baseline_values = [_value(row, name) for row in baseline_attempts]
    candidate_values = [_value(row, name) for row in candidate_attempts]
    observed = {value for value in (*baseline_values, *candidate_values) if value is not None}
    if len(observed) > 1:
        raise BenchmarkComparisonError(
            f"{name} denominator drift across paired arms or retries for one held task"
        )
    return {
        "observed_value": next(iter(observed)) if observed else None,
        "baseline_observed_attempt_count": sum(value is not None for value in baseline_values),
        "baseline_missing_attempt_count": sum(value is None for value in baseline_values),
        "candidate_observed_attempt_count": sum(value is not None for value in candidate_values),
        "candidate_missing_attempt_count": sum(value is None for value in candidate_values),
    }


def _summed_attempt_metric(
    attempts: Sequence[Mapping[str, Any]],
    name: str,
) -> int | None:
    values = [_value(row, name) for row in attempts]
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _live_quality_attempt(row: Mapping[str, Any]) -> bool:
    return bool(
        row["provenance"] == "live"
        and bool(row["evidence_cids"])
        and _value(row, "provider_call_count") == 1
    )


def _observed_live_cost_attempt(row: Mapping[str, Any]) -> bool:
    return bool(
        _live_quality_attempt(row)
        and _value(row, "total_cost_micros") is not None
        and all(_value(row, name) is not None for name in _COST_COMPONENT_METRICS)
    )


def _task_summary(pair: Mapping[str, Any]) -> dict[str, Any]:
    """Expose one paired task unit with each arm's terminal and all retry costs."""

    return {
        "cluster_key": pair["cluster_key"],
        "paired_attempt_count": min(
            len(pair["baseline_attempts"]),
            len(pair["candidate_attempts"]),
        ),
        "baseline_attempt_count": len(pair["baseline_attempts"]),
        "candidate_attempt_count": len(pair["candidate_attempts"]),
        "eligible": pair["eligible"],
        "baseline_correct": pair["baseline_correct"],
        "candidate_correct": pair["candidate_correct"],
        "context_reduction_bp": pair["context_reduction_bp"],
        "baseline_total_cost_micros": pair["baseline_total_cost_micros"],
        "candidate_total_cost_micros": pair["candidate_total_cost_micros"],
        "candidate_routine_count": pair["candidate_routine_count"],
        "candidate_routine_frontier_count": pair["candidate_routine_frontier_count"],
        "live_quality": pair["live_quality"],
        "observed_live_cost": pair["observed_live_cost"],
        "candidate_live_routing": pair["candidate_live_routing"],
    }


def _task_population(pairs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]] | None:
    summaries = [_task_summary(pair) for pair in pairs]
    if any(summary["eligible"] is None for summary in summaries):
        return None
    return [summary for summary in summaries if summary["eligible"] == 1]


def _median(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def _context_statistic(tasks: Sequence[Mapping[str, Any]]) -> int | None:
    values = [task["context_reduction_bp"] for task in tasks]
    if not values or any(value is None for value in values):
        return None
    return _median([value for value in values if value is not None])


def _quality_statistic(tasks: Sequence[Mapping[str, Any]]) -> int | None:
    if not tasks:
        return None
    baseline_correct = 0
    baseline_eligible = 0
    candidate_correct = 0
    candidate_eligible = 0
    for task in tasks:
        baseline = task["baseline_correct"]
        candidate = task["candidate_correct"]
        eligible = task["eligible"]
        if baseline is None or candidate is None or eligible is None:
            return None
        baseline_correct += baseline
        baseline_eligible += eligible
        candidate_correct += candidate
        candidate_eligible += eligible
    if baseline_eligible == 0 or candidate_eligible == 0:
        return None
    return (
        candidate_correct * 10000 // candidate_eligible
        - baseline_correct * 10000 // baseline_eligible
    )


def _cost_statistic(tasks: Sequence[Mapping[str, Any]]) -> int | None:
    if not tasks:
        return None
    baseline_total = 0
    candidate_total = 0
    baseline_correct = 0
    candidate_correct = 0
    for task in tasks:
        baseline_cost = task["baseline_total_cost_micros"]
        candidate_cost = task["candidate_total_cost_micros"]
        baseline_correct_outcome = task["baseline_correct"]
        candidate_correct_outcome = task["candidate_correct"]
        if (
            baseline_cost is None
            or candidate_cost is None
            or baseline_correct_outcome is None
            or candidate_correct_outcome is None
        ):
            return None
        baseline_total += baseline_cost
        candidate_total += candidate_cost
        baseline_correct += baseline_correct_outcome
        candidate_correct += candidate_correct_outcome
    if baseline_total == 0 or baseline_correct == 0 or candidate_correct == 0:
        return None
    # Algebraically exact ratio of cost-per-correct-patch values without float
    # or intermediate integer rounding.
    numerator = baseline_total * candidate_correct - candidate_total * baseline_correct
    denominator = baseline_total * candidate_correct
    return numerator * 10000 // denominator


def _routine_statistic(tasks: Sequence[Mapping[str, Any]]) -> int | None:
    if not tasks:
        return None
    numerator = 0
    denominator = 0
    for task in tasks:
        routine = task["candidate_routine_count"]
        frontier = task["candidate_routine_frontier_count"]
        if routine is None:
            return None
        if routine:
            if frontier is None:
                return None
            denominator += routine
            numerator += frontier
    if denominator == 0:
        return None
    return numerator * 10000 // denominator


def _nearest_rank(values: Sequence[int], probability_bp: int) -> int:
    if not values:
        raise BenchmarkComparisonError("cannot take a percentile of no values")
    ordered = sorted(values)
    rank = (probability_bp * len(ordered) + 9999) // 10000
    index = min(len(ordered) - 1, max(0, rank - 1))
    return ordered[index]


def _bootstrap(
    tasks: Sequence[Mapping[str, Any]],
    statistic: Callable[[Sequence[Mapping[str, Any]]], int | None],
) -> dict[str, Any]:
    point = statistic(tasks)
    record: dict[str, Any] = {
        "method": _POLICY["analysis"]["method"],
        "seed": BOOTSTRAP_SEED,
        "replicates_requested": BOOTSTRAP_SAMPLES,
        "replicates_drawn": 0,
        "defined_replicates": 0,
        "undefined_replicates": 0,
        "confidence_bp": CONFIDENCE_BP,
        "confidence_side": _POLICY["analysis"]["confidence_side"],
        "task_cluster_count": len(tasks),
        "paired_attempt_count": sum(task["paired_attempt_count"] for task in tasks),
        "baseline_attempt_count": sum(task["baseline_attempt_count"] for task in tasks),
        "candidate_attempt_count": sum(task["candidate_attempt_count"] for task in tasks),
        "point_estimate_bp": point,
        "lower_confidence_bound_bp": None,
        "upper_confidence_bound_bp": None,
    }
    if not tasks or point is None:
        return record

    rng = random.Random(BOOTSTRAP_SEED)
    estimates: list[int] = []
    undefined = 0
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [tasks[rng.randrange(len(tasks))] for _task_index in range(len(tasks))]
        estimate = statistic(sample)
        if estimate is None:
            undefined += 1
        else:
            estimates.append(estimate)
    record["replicates_drawn"] = BOOTSTRAP_SAMPLES
    record["defined_replicates"] = len(estimates)
    record["undefined_replicates"] = undefined
    if undefined == 0:
        alpha_bp = 10000 - CONFIDENCE_BP
        record["lower_confidence_bound_bp"] = _nearest_rank(estimates, alpha_bp)
        record["upper_confidence_bound_bp"] = _nearest_rank(estimates, CONFIDENCE_BP)
    return record


def _decision(
    bootstrap: Mapping[str, Any],
    *,
    rule: str,
    threshold_bp: int,
    evidence_eligible: bool,
    unavailable_reason: str | None = None,
) -> tuple[str, str]:
    point = bootstrap["point_estimate_bp"]
    clusters = bootstrap["task_cluster_count"]
    lower = bootstrap["lower_confidence_bound_bp"]
    upper = bootstrap["upper_confidence_bound_bp"]
    if unavailable_reason is not None or point is None:
        return (
            "unavailable-no-go",
            unavailable_reason or "zero-or-missing-denominator",
        )
    if not evidence_eligible:
        return ("unavailable-no-go", "required-live-observed-evidence-is-absent")
    if clusters < MIN_PAIRED_TASK_CLUSTERS:
        return ("inconclusive-no-go", "insufficient-paired-task-clusters")
    if bootstrap["replicates_drawn"] != BOOTSTRAP_SAMPLES:
        return ("inconclusive-no-go", "bootstrap-not-complete")
    if bootstrap["undefined_replicates"]:
        return ("inconclusive-no-go", "one-or-more-bootstrap-denominators-were-zero")
    if rule == "lower-at-least":
        passed = lower is not None and lower >= threshold_bp
    elif rule == "upper-at-most":
        passed = upper is not None and upper <= threshold_bp
    else:
        raise BenchmarkComparisonError(f"unknown decision rule: {rule}")
    return (
        ("pass", "confidence-bound-satisfies-threshold")
        if passed
        else (
            "fail",
            "confidence-bound-does-not-satisfy-threshold",
        )
    )


def _metric_gate(
    *,
    metric_name: str,
    bootstrap: dict[str, Any],
    threshold: Mapping[str, Any],
    rule: str,
    threshold_bp: int,
    evidence_class: str,
    evidence_eligible: bool,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    decision, reason = _decision(
        bootstrap,
        rule=rule,
        threshold_bp=threshold_bp,
        evidence_eligible=evidence_eligible,
        unavailable_reason=unavailable_reason,
    )
    return {
        "metric": metric_name,
        "baseline_configuration_id": BASELINE_CONFIGURATION_ID,
        "baseline_configuration_cid": _CONFIGURATION_CIDS[BASELINE_CONFIGURATION_ID],
        "candidate_configuration_id": CANDIDATE_CONFIGURATION_ID,
        "candidate_configuration_cid": _CONFIGURATION_CIDS[CANDIDATE_CONFIGURATION_ID],
        "evidence_class": evidence_class,
        "evidence_eligible": evidence_eligible,
        "threshold": _clone(threshold),
        "decision_rule_implemented": rule,
        "decision_confidence_side": (
            "one-sided-lower" if rule == "lower-at-least" else "one-sided-upper"
        ),
        "decision_threshold_bp": threshold_bp,
        "decision": decision,
        "reason": reason,
        "bootstrap": bootstrap,
    }


def _derived_zero_tolerance_value(row: Mapping[str, Any], name: str) -> int | None:
    """Derive only structural zeros proved by other admitted raw observations."""

    if name == "simulated_success_accepted_count":
        if row["provenance"] != "simulated":
            return 0
        accepted = _value(row, "accepted_patch_count")
        if accepted == 0:
            return 0
        return None
    if name == "controlled_selected_test_false_negative_count":
        selected = _value(row, "selected_test_count")
        selected_passed = _value(row, "selected_test_pass_count")
        full = _value(row, "full_test_count")
        full_passed = _value(row, "full_test_pass_count")
        # The frozen C/D runner defines this violation as:
        # selected == selected_passed and full_passed != full.  Derive zero
        # only when an observed operand proves one of those conjunctions
        # false.  In particular, selected == selected_passed == 0 does not
        # prove safety when the full suite has a failure.
        if full == 0:
            return 0
        if selected is not None and selected_passed is not None and selected != selected_passed:
            return 0
        if full is not None and full_passed is not None and full == full_passed:
            return 0
        return None

    if name == "critical_regression_accepted_count":
        # Both frozen runner families explicitly condition this metric on the
        # final accepted-patch decision.  The other acceptance-named
        # invariants describe independent stale-input, assurance, or review
        # events and cannot be inferred from final patch acceptance.
        accepted = _value(row, "accepted_patch_count")
        if accepted == 0:
            return 0
    return None


def _zero_tolerance(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, required in _POLICY["zero_tolerance"].items():
        applicable_configurations = _ZERO_TOLERANCE_APPLICABILITY[name]
        applicable_count = 0
        observed_count = 0
        derived_zero_count = 0
        excluded_count = 0
        missing_count = 0
        values: list[int] = []
        extraneous_violations: list[int] = []
        for row in rows:
            raw_value = _value(row, name)
            if row["configuration_id"] not in applicable_configurations:
                excluded_count += 1
                if raw_value not in (None, 0):
                    extraneous_violations.append(raw_value)
                continue
            applicable_count += 1
            if raw_value is not None:
                observed_count += 1
                values.append(raw_value)
                continue
            derived = _derived_zero_tolerance_value(row, name)
            if derived is None:
                missing_count += 1
            else:
                derived_zero_count += 1
                values.append(derived)

        if extraneous_violations:
            values.extend(extraneous_violations)
        known_value = sum(values)
        known_violation = known_value != required
        value = None if missing_count or applicable_count == 0 else known_value
        if extraneous_violations:
            assert sum(extraneous_violations) > 0
            decision = "fail"
            reason = "zero-tolerance-invariant-claimed-outside-applicable-configuration"
            value = known_value
        elif applicable_count == 0:
            decision = "unavailable-no-go"
            reason = "zero-tolerance-applicable-configuration-absent"
        elif known_violation:
            # Missing rows can conceal more violations, but they cannot erase
            # a violation that is already present in admitted raw evidence.
            decision = "fail"
            reason = "known-zero-tolerance-invariant-violation"
            value = known_value
        elif value is None:
            decision = "unavailable-no-go"
            reason = "one-or-more-applicable-zero-tolerance-observations-missing"
        elif value == required:
            decision = "pass"
            reason = "exact-zero-tolerance-invariant-satisfied"
        else:
            decision = "fail"
            reason = "zero-tolerance-invariant-violated"
        checks[name] = {
            "required": required,
            "observed": value,
            "applicable_configurations": sorted(applicable_configurations),
            "applicable_result_count": applicable_count,
            "observed_result_count": observed_count,
            "derived_structural_zero_count": derived_zero_count,
            "excluded_not_applicable_result_count": excluded_count,
            "missing_result_count": missing_count,
            "decision": decision,
            "reason": reason,
        }
    return checks


def _pair_trace(pairs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    def attempt_trace(row: Mapping[str, Any], result_cid: str) -> dict[str, Any]:
        score = metrics.scored_correct_outcome(row)
        return {
            "attempt": row["attempt"],
            "result_cid": result_cid,
            "execution_binding_cid": _execution_binding_cid(row),
            "terminal_status": row["terminal_status"],
            "scored_correct": None if score is None else score["correct"],
            "total_cost_micros": _value(row, "total_cost_micros"),
        }

    trace: list[dict[str, Any]] = []
    for pair in pairs:
        baseline_attempts = pair["baseline_attempts"]
        candidate_attempts = pair["candidate_attempts"]
        baseline_terminal = baseline_attempts[-1]
        candidate_terminal = candidate_attempts[-1]
        trace.append(
            {
                "held_identity_cid": pair["held_identity_cid"],
                "task_record_cid": baseline_terminal["task_record_cid"],
                "baseline_attempt_count": len(baseline_attempts),
                "candidate_attempt_count": len(candidate_attempts),
                "baseline_attempts": [
                    attempt_trace(row, result_cid)
                    for row, result_cid in zip(
                        baseline_attempts,
                        pair["baseline_result_cids"],
                        strict=True,
                    )
                ],
                "candidate_attempts": [
                    attempt_trace(row, result_cid)
                    for row, result_cid in zip(
                        candidate_attempts,
                        pair["candidate_result_cids"],
                        strict=True,
                    )
                ],
                "baseline_terminal_result_cid": pair["baseline_result_cids"][-1],
                "candidate_terminal_result_cid": pair["candidate_result_cids"][-1],
                "baseline_terminal_status": baseline_terminal["terminal_status"],
                "candidate_terminal_status": candidate_terminal["terminal_status"],
                "baseline_scored_correct": (
                    None
                    if pair["baseline_terminal_score"] is None
                    else pair["baseline_terminal_score"]["correct"]
                ),
                "candidate_scored_correct": (
                    None
                    if pair["candidate_terminal_score"] is None
                    else pair["candidate_terminal_score"]["correct"]
                ),
                "context_reduction_bp": pair["context_reduction_bp"],
                "full_test_denominator_evidence": pair["full_test_denominator_evidence"],
                "hidden_test_denominator_evidence": pair["hidden_test_denominator_evidence"],
                "baseline_total_cost_micros": pair["baseline_total_cost_micros"],
                "candidate_total_cost_micros": pair["candidate_total_cost_micros"],
                "observed_live_cost": pair["observed_live_cost"],
            }
        )
    return trace


def _pairing_record(
    pairs: Sequence[Mapping[str, Any]],
    unmatched_baseline: Sequence[Sequence[Mapping[str, Any]]],
    unmatched_candidate: Sequence[Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    baseline_attempt_count = sum(len(pair["baseline_attempts"]) for pair in pairs)
    candidate_attempt_count = sum(len(pair["candidate_attempts"]) for pair in pairs)
    return {
        "held_identity_fields": list(metrics.HELD_IDENTITY_FIELDS),
        "held_task_identity_fields": [
            field for field in metrics.HELD_IDENTITY_FIELDS if field != "attempt"
        ],
        "arm_execution_identity_fields": list(metrics.ARM_EXECUTION_IDENTITY_FIELDS),
        "paired_attempt_count": sum(
            min(len(pair["baseline_attempts"]), len(pair["candidate_attempts"])) for pair in pairs
        ),
        "baseline_attempt_count": baseline_attempt_count,
        "candidate_attempt_count": candidate_attempt_count,
        "paired_task_cluster_count": len(pairs),
        "differing_retry_count_task_cluster_count": sum(
            len(pair["baseline_attempts"]) != len(pair["candidate_attempts"]) for pair in pairs
        ),
        "unmatched_baseline_count": len(unmatched_baseline),
        "unmatched_candidate_count": len(unmatched_candidate),
        "unmatched_baseline_result_cids": sorted(
            spec.structured_cid(row) for cluster in unmatched_baseline for row in cluster
        ),
        "unmatched_candidate_result_cids": sorted(
            spec.structured_cid(row) for cluster in unmatched_candidate for row in cluster
        ),
    }


def compare_frozen_ad(
    value: Any,
) -> dict[str, Any]:
    """Compare frozen configuration D against explicit baseline A.

    The returned decision is benchmark-evidence scope only.  It is not a live
    provider run, a production release qualification, or a performance claim.
    """

    try:
        admitted = metrics.validate_result_population(value)
    except metrics.MetricAggregationError as exc:
        raise BenchmarkComparisonError(str(exc)) from exc
    raw_pairs, unmatched_baseline, unmatched_candidate = _pair_population(
        admitted,
        baseline_id=BASELINE_CONFIGURATION_ID,
        candidate_id=CANDIDATE_CONFIGURATION_ID,
    )
    pairs = [_pair_semantics(pair) for pair in raw_pairs]
    eligible = _task_population(pairs)

    if eligible is None:
        population: list[Mapping[str, Any]] = []
        eligibility_reason = "eligible-task-denominator-missing"
    else:
        population = eligible
        eligibility_reason = None if population else "zero-eligible-task-denominator"

    context_bootstrap = _bootstrap(population, _context_statistic)
    context_rule = _POLICY["primary_comparisons"]["context_reduction"]
    context_gate = _metric_gate(
        metric_name="context_reduction_bp",
        bootstrap=context_bootstrap,
        threshold=context_rule,
        rule="lower-at-least",
        threshold_bp=context_rule["minimum_bp"],
        evidence_class="identity-paired-observation",
        evidence_eligible=True,
        unavailable_reason=eligibility_reason,
    )

    quality_bootstrap = _bootstrap(population, _quality_statistic)
    quality_rule = _POLICY["primary_comparisons"]["accepted_patch_noninferiority"]
    all_live_quality = bool(population) and all(task["live_quality"] for task in population)
    quality_gate = _metric_gate(
        metric_name="correct_accepted_patch_rate_bp",
        bootstrap=quality_bootstrap,
        threshold=quality_rule,
        rule="lower-at-least",
        threshold_bp=-quality_rule["margin_bp"],
        evidence_class=("observed-live" if all_live_quality else "descriptive-nonlive"),
        evidence_eligible=all_live_quality,
        unavailable_reason=eligibility_reason,
    )

    cost_bootstrap = _bootstrap(population, _cost_statistic)
    cost_rule = _POLICY["primary_comparisons"]["total_cost_reduction"]
    all_observed_live_cost = bool(population) and all(
        task["observed_live_cost"] for task in population
    )
    if eligibility_reason is not None:
        cost_reason = eligibility_reason
    elif any(
        task["baseline_total_cost_micros"] is None or task["candidate_total_cost_micros"] is None
        for task in population
    ):
        cost_reason = "one-or-more-paired-total-cost-observations-missing"
    elif cost_bootstrap["point_estimate_bp"] is None:
        cost_reason = "zero-cost-or-correct-patch-denominator"
    else:
        cost_reason = None
    cost_gate = _metric_gate(
        metric_name="total_cost_reduction_bp",
        bootstrap=cost_bootstrap,
        threshold=cost_rule,
        rule="lower-at-least",
        threshold_bp=cost_rule["minimum_bp"],
        evidence_class=(
            "observed-live" if all_observed_live_cost else "descriptive-or-missing-cost"
        ),
        evidence_eligible=all_observed_live_cost,
        unavailable_reason=cost_reason,
    )

    routine_missing = any(
        task["candidate_routine_count"] is None
        or (task["candidate_routine_count"] and task["candidate_routine_frontier_count"] is None)
        for task in population
    )
    routine_population = [task for task in population if task["candidate_routine_count"] == 1]
    routine_bootstrap = _bootstrap(routine_population, _routine_statistic)
    routine_rule = _POLICY["primary_comparisons"]["routine_frontier_escalation"]
    routine_live = bool(routine_population) and all(
        task["candidate_live_routing"] for task in routine_population
    )
    if eligibility_reason is not None:
        routine_reason = eligibility_reason
    elif routine_missing:
        routine_reason = "routine-frontier-denominator-or-numerator-missing"
    elif not routine_population:
        routine_reason = "zero-routine-localized-denominator"
    else:
        routine_reason = None
    routine_gate = _metric_gate(
        metric_name="routine_frontier_escalation_rate_bp",
        bootstrap=routine_bootstrap,
        threshold=routine_rule,
        rule="upper-at-most",
        threshold_bp=routine_rule["maximum_bp"],
        evidence_class=("observed-live" if routine_live else "descriptive-nonlive"),
        evidence_eligible=routine_live,
        unavailable_reason=routine_reason,
    )

    zero_tolerance = _zero_tolerance(admitted)
    gates = {
        "context_reduction": context_gate,
        "accepted_patch_noninferiority": quality_gate,
        "total_cost_reduction": cost_gate,
        "routine_frontier_escalation": routine_gate,
    }
    unpaired = bool(unmatched_baseline or unmatched_candidate)
    all_gates_pass = all(gate["decision"] == "pass" for gate in gates.values())
    zero_tolerance_pass = all(check["decision"] == "pass" for check in zero_tolerance.values())
    qualification_status = (
        "go" if all_gates_pass and zero_tolerance_pass and not unpaired else "no-go"
    )
    blockers: list[str] = []
    if unpaired:
        blockers.append("unpaired-held-identity-results")
    blockers.extend(name for name, gate in gates.items() if gate["decision"] != "pass")
    blockers.extend(name for name, check in zero_tolerance.items() if check["decision"] != "pass")

    return {
        "schema": COMPARISON_SCHEMA,
        "benchmark_id": spec.BENCHMARK_ID,
        "corpus_manifest_cid": admitted[0]["corpus_manifest_cid"],
        "metric_catalog_cid": spec.catalog_cids()["metric_catalog_cid"],
        "metric_set_descriptor_cid": metrics.METRIC_SET_DESCRIPTOR_CID,
        "comparison_descriptor_cid": COMPARISON_DESCRIPTOR_CID,
        "baseline": {
            "configuration_id": BASELINE_CONFIGURATION_ID,
            "configuration_cid": _CONFIGURATION_CIDS[BASELINE_CONFIGURATION_ID],
            "label": "explicit-frozen-baseline-A",
        },
        "candidate": {
            "configuration_id": CANDIDATE_CONFIGURATION_ID,
            "configuration_cid": _CONFIGURATION_CIDS[CANDIDATE_CONFIGURATION_ID],
            "label": "explicit-frozen-candidate-D",
        },
        "pairing": _pairing_record(pairs, unmatched_baseline, unmatched_candidate),
        "gates": gates,
        "zero_tolerance": zero_tolerance,
        "evidence": {
            "all_paired_quality_live": all_live_quality,
            "all_paired_cost_observed_live": all_observed_live_cost,
            "replayed_result_count": sum(row["provenance"] == "replayed" for row in admitted),
            "simulated_result_count": sum(row["provenance"] == "simulated" for row in admitted),
            "failed_attempt_cost_policy": "complete-observed-total-retained",
            "estimated_cost_can_pass": False,
        },
        "semantic_outcome_comparison_trace": _pair_trace(pairs),
        "qualification_status": qualification_status,
        "qualification_blockers": blockers,
        "decision_scope": (
            "frozen-benchmark-evidence-only-not-live-provider-execution-or-production-qualification"
        ),
        "provider_calls_performed": 0,
        "benchmark_execution_performed": False,
    }


def compare_context_arms(
    value: Any,
    *,
    baseline_id: str = "A",
    candidate_id: str = "B",
) -> dict[str, Any]:
    """Compute a descriptive held-identity context comparison.

    PCCE-060 preregisters B-vs-A as an isolated diagnostic.  This function also
    admits C or D as the explicitly labelled candidate, but never emits a
    qualification decision.
    """

    if baseline_id != "A" or candidate_id not in {"B", "C", "D"}:
        raise BenchmarkComparisonError(
            "context diagnostics require explicit baseline A and candidate B, C, or D"
        )
    try:
        admitted = metrics.validate_result_population(value)
    except metrics.MetricAggregationError as exc:
        raise BenchmarkComparisonError(str(exc)) from exc
    raw_pairs, unmatched_baseline, unmatched_candidate = _pair_population(
        admitted,
        baseline_id=baseline_id,
        candidate_id=candidate_id,
    )
    pairs = [_pair_semantics(pair) for pair in raw_pairs]
    eligible = _task_population(pairs)
    population = [] if eligible is None else eligible
    bootstrap = _bootstrap(population, _context_statistic)
    return {
        "schema": CONTEXT_DIAGNOSTIC_SCHEMA,
        "benchmark_id": spec.BENCHMARK_ID,
        "corpus_manifest_cid": admitted[0]["corpus_manifest_cid"],
        "comparison_descriptor_cid": COMPARISON_DESCRIPTOR_CID,
        "baseline": {
            "configuration_id": baseline_id,
            "configuration_cid": _CONFIGURATION_CIDS[baseline_id],
            "label": f"explicit-frozen-baseline-{baseline_id}",
        },
        "candidate": {
            "configuration_id": candidate_id,
            "configuration_cid": _CONFIGURATION_CIDS[candidate_id],
            "label": f"explicit-frozen-candidate-{candidate_id}",
        },
        "metric": "context_reduction_bp",
        "diagnostic_label": (
            "frozen-isolated-B-vs-A" if candidate_id == "B" else "descriptive-context-arm"
        ),
        "pairing": {
            **_pairing_record(pairs, unmatched_baseline, unmatched_candidate),
            "complete": not unmatched_baseline and not unmatched_candidate,
        },
        "bootstrap": bootstrap,
        "semantic_outcome_comparison_trace": _pair_trace(pairs),
        "qualification_decision": None,
        "decision_scope": "descriptive-isolated-context-diagnostic-only",
        "provider_calls_performed": 0,
        "benchmark_execution_performed": False,
    }


def comparison_cid(value: Mapping[str, Any]) -> str:
    """Return the canonical structured identity of a comparison report."""

    return spec.structured_cid(_clone(value))


def comparison_descriptor() -> dict[str, Any]:
    """Return the immutable implementation/threshold binding descriptor."""

    return {
        "schema": COMPARISON_DESCRIPTOR_SCHEMA,
        "benchmark_id": spec.BENCHMARK_ID,
        "identity_profile": spec.IDENTITY_PROFILE,
        "metric_set_descriptor_cid": metrics.METRIC_SET_DESCRIPTOR_CID,
        "held_identity_fields": list(metrics.HELD_IDENTITY_FIELDS),
        "held_task_identity_fields": [
            field for field in metrics.HELD_IDENTITY_FIELDS if field != "attempt"
        ],
        "arm_execution_identity_fields": list(metrics.ARM_EXECUTION_IDENTITY_FIELDS),
        "bootstrap": {
            "method": _POLICY["analysis"]["method"],
            "samples": BOOTSTRAP_SAMPLES,
            "seed": BOOTSTRAP_SEED,
            "confidence_bp": CONFIDENCE_BP,
            "confidence_side": _POLICY["analysis"]["confidence_side"],
            "resampling_unit": "held-task-identity-cluster-all-attempts-together",
            "percentile_rule": "integer-nearest-rank",
            "undefined_replicate_policy": "inconclusive-no-go-never-drop-or-impute",
        },
        "minimum_paired_task_clusters_for_confidence": MIN_PAIRED_TASK_CLUSTERS,
        "baseline_configuration_id": BASELINE_CONFIGURATION_ID,
        "candidate_configuration_id": CANDIDATE_CONFIGURATION_ID,
        "isolated_context_diagnostic": "B-vs-A-descriptive-only",
        "threshold_policy": _clone(_POLICY),
        "context_denominator": "positive-A-ordinary-retrieval-tokens",
        "cost_policy": "observed-live-only-including-all-failed-attempt-total-cost",
        "quality_policy": (
            "terminal-failed-and-abstained-eligible-task-clusters-score-zero;"
            "first-attempt-success-remains-separate"
        ),
        "task_point_estimator_policy": (
            "one-unit-per-held-task-cluster;arms-validate-contiguous-retries-independently;"
            "retry-count-never-reweights-context-quality-or-routing;all-arm-costs-retained"
        ),
        "frozen_suite_denominator_policy": (
            "all-observed-full-and-hidden-suite-counts-identical-across-arms-and-retries;"
            "null-observations-retained-as-missing"
        ),
        "zero_tolerance_applicability": {
            name: sorted(configuration_ids)
            for name, configuration_ids in _ZERO_TOLERANCE_APPLICABILITY.items()
        },
        "zero_tolerance_structural_zero_policy": (
            "derive-only-from-exact-runner-semantics-that-logically-disprove-the-invariant"
        ),
        "zero_denominator_policy": "unavailable-no-go",
        "insufficient_population_policy": "inconclusive-no-go",
        "zero_tolerance_policy": "exact-zero-and-complete-observation-required",
        "unpaired_policy": "explicit-and-overall-no-go",
        "identity_drift_policy": "reject-before-statistics",
        "nonlive_policy": "descriptive-only-never-upgrade",
        "provider_calls": False,
        "benchmark_execution": False,
        "production_qualification_claimed": False,
    }


COMPARISON_DESCRIPTOR_CID: Final[str] = spec.structured_cid(comparison_descriptor())


__all__ = [
    "BASELINE_CONFIGURATION_ID",
    "BOOTSTRAP_SAMPLES",
    "BOOTSTRAP_SEED",
    "CANDIDATE_CONFIGURATION_ID",
    "COMPARISON_DESCRIPTOR_CID",
    "COMPARISON_DESCRIPTOR_SCHEMA",
    "COMPARISON_SCHEMA",
    "CONFIDENCE_BP",
    "CONTEXT_DIAGNOSTIC_SCHEMA",
    "MIN_PAIRED_TASK_CLUSTERS",
    "BenchmarkComparisonError",
    "compare_context_arms",
    "compare_frozen_ad",
    "comparison_cid",
    "comparison_descriptor",
]

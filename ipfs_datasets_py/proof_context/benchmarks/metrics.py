"""Pure, identity-bound benchmark metric aggregation for PCCE-066.

The frozen PCCE-060 raw result contains all 78 metric fields.  This module
validates those rows, preserves every explicit null and missingness reason,
and recomputes the five derived metrics from their declared denominators.
It performs no benchmark execution, provider dispatch, hidden-answer access,
threshold mutation, persistence, or result qualification.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from copy import deepcopy
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.proof_context.benchmarks import specification as spec

AGGREGATE_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-metric-aggregate@1"
AGGREGATE_SET_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-metric-aggregate-set@1"
SEMANTIC_TRACE_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-semantic-outcome-trace@1"
METRIC_SET_DESCRIPTOR_SCHEMA: Final[str] = (
    "ipfs-datasets.proof-context.benchmark-metric-set-descriptor@1"
)

_DEFINITIONS: Final[tuple[dict[str, Any], ...]] = tuple(spec.metric_catalog())
METRIC_NAMES: Final[tuple[str, ...]] = tuple(item["name"] for item in _DEFINITIONS)
DERIVED_METRIC_NAMES: Final[tuple[str, ...]] = tuple(
    item["name"] for item in _DEFINITIONS if item["source"] == "derived"
)
RAW_SUM_METRIC_NAMES: Final[tuple[str, ...]] = tuple(
    name for name in METRIC_NAMES if name not in DERIVED_METRIC_NAMES
)

_DEFINITION_BY_NAME: Final[Mapping[str, Mapping[str, Any]]] = MappingProxyType(
    {item["name"]: MappingProxyType(item) for item in _DEFINITIONS}
)
_CONFIGURATION_CIDS: Final[Mapping[str, str]] = MappingProxyType(
    {item["configuration_id"]: spec.structured_cid(item) for item in spec.configuration_catalog()}
)
_COST_COMPONENTS: Final[tuple[str, ...]] = (
    "inference_cost_micros",
    "verification_cost_micros",
    "proof_cost_micros",
    "assurance_cost_micros",
    "failure_cost_micros",
    "human_cost_micros",
)
_SUCCESS_STATUS: Final[str] = "succeeded"

# These fields, plus provenance, are frozen by the upstream paired runners.
# ``task_id`` is represented by its content-addressed ``task_record_cid`` in a
# raw result.  Configuration id/CID are deliberately absent: they are the
# treatment being compared.  Provider/model/revision are arm-local execution
# outcomes (A may route to a frontier provider while D routes locally), so they
# are retained on every raw row and reported through arm-specific binding CIDs
# rather than being used to manufacture an A<->D identity mismatch.
HELD_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "corpus_manifest_cid",
    "task_record_cid",
    "visible_projection_cid",
    "repository_state_cid",
    "environment_cid",
    "seed",
    "attempt",
    "provenance",
)
ARM_EXECUTION_IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "provider_id",
    "model_id",
    "model_revision",
)


class MetricAggregationError(ValueError):
    """Raised when raw evidence cannot support an honest aggregate."""


def _clone(value: Any) -> Any:
    return deepcopy(value)


def _configuration_cid(configuration_id: str) -> str:
    try:
        return _CONFIGURATION_CIDS[configuration_id]
    except KeyError as exc:
        raise MetricAggregationError(f"unknown configuration: {configuration_id!r}") from exc


def _metric_value(row: Mapping[str, Any], name: str) -> int | None:
    value = row["metrics"][name]
    if value is None or type(value) is int:
        return value
    raise MetricAggregationError(f"metrics.{name} is not an integer or null")


def _missing_reason_id(reason: str) -> str:
    """Bind arbitrary producer text without redisclosing it in public aggregates."""

    return "sha256:" + hashlib.sha256(reason.encode("utf-8")).hexdigest()


def _scored_correct(row: Mapping[str, Any]) -> tuple[int, int] | None:
    """Return (correct, eligible) under the preregistered failure-zero rule."""

    eligible = _metric_value(row, "eligible_task_count")
    if eligible is None:
        return None
    if eligible not in (0, 1):
        raise MetricAggregationError("eligible_task_count must be zero or one per raw attempt")
    if eligible == 0:
        return (0, 0)
    if row["terminal_status"] != _SUCCESS_STATUS:
        return (0, 1)
    correct = _metric_value(row, "correct_accepted_patch_count")
    if correct is None:
        raise MetricAggregationError(
            "a succeeded eligible attempt must observe correct_accepted_patch_count"
        )
    if correct != 1:
        raise MetricAggregationError(
            "a succeeded eligible attempt must score exactly one correct accepted patch"
        )
    return (1, 1)


def _validate_count_relation(
    row: Mapping[str, Any],
    lesser: str,
    greater: str,
) -> None:
    left = _metric_value(row, lesser)
    right = _metric_value(row, greater)
    if left is not None and right is not None and left > right:
        raise MetricAggregationError(f"{lesser} cannot exceed {greater}")


def _required_metrics(
    row: Mapping[str, Any],
    names: Sequence[str],
    *,
    context: str,
) -> dict[str, int]:
    """Return metrics whose observation is required by one frozen runner outcome."""

    values = {name: _metric_value(row, name) for name in names}
    missing = sorted(name for name, value in values.items() if value is None)
    if missing:
        raise MetricAggregationError(
            f"{context} must observe required metrics: {', '.join(missing)}"
        )
    return {name: value for name, value in values.items() if value is not None}


def _require_zero_or_missing(
    row: Mapping[str, Any],
    names: Sequence[str],
    *,
    context: str,
) -> None:
    invalid = sorted(name for name in names if _metric_value(row, name) not in (None, 0))
    if invalid:
        raise MetricAggregationError(
            f"{context} cannot claim non-applicable observations: {', '.join(invalid)}"
        )


def _validate_successful_row(row: Mapping[str, Any]) -> None:
    """Enforce observable implications of the frozen A/B and C/D success paths."""

    common = _required_metrics(
        row,
        (
            "eligible_task_count",
            "patch_proposal_count",
            "accepted_patch_count",
            "correct_accepted_patch_count",
            "full_test_count",
            "full_test_pass_count",
            "full_test_fail_count",
            "hidden_test_total_count",
            "hidden_test_pass_count",
            "regression_count",
            "critical_regression_accepted_count",
            "out_of_scope_edit_count",
            "semantic_outcome_match_count",
        ),
        context="a succeeded attempt",
    )
    for name in (
        "eligible_task_count",
        "patch_proposal_count",
        "accepted_patch_count",
        "correct_accepted_patch_count",
        "semantic_outcome_match_count",
    ):
        if common[name] != 1:
            raise MetricAggregationError(f"a succeeded attempt requires {name}=1")
    if common["full_test_count"] < 1 or common["hidden_test_total_count"] < 1:
        raise MetricAggregationError(
            "a succeeded attempt requires non-empty full and hidden suites"
        )
    if (
        common["full_test_pass_count"] != common["full_test_count"]
        or common["full_test_fail_count"] != 0
        or common["hidden_test_pass_count"] != common["hidden_test_total_count"]
        or common["regression_count"] != 0
        or common["critical_regression_accepted_count"] != 0
        or common["out_of_scope_edit_count"] != 0
    ):
        raise MetricAggregationError(
            "a succeeded attempt contradicts the frozen full-verification acceptance predicate"
        )

    configuration_id = row["configuration_id"]
    if configuration_id == "A":
        _require_zero_or_missing(
            row,
            (
                "context_pack_tokens",
                "capsule_tokens",
                "context_fallback_count",
                "context_reduction_bp",
            ),
            context="a succeeded A attempt",
        )

    if configuration_id in {"A", "B"}:
        if _metric_value(row, "route_frontier_count") != 1:
            raise MetricAggregationError(
                "a succeeded A/B attempt requires its frozen frontier route"
            )
        _require_zero_or_missing(
            row,
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
                "context_expansion_count",
                "context_expansion_tokens",
                "selected_test_count",
                "selected_test_pass_count",
                "selected_test_fail_count",
                "controlled_selected_test_false_negative_count",
                "proof_selected_count",
                "proof_executed_count",
                "proof_pass_count",
                "proof_fail_count",
                "verification_reuse_hit_count",
                "verification_reuse_miss_count",
                "verification_full_fallback_count",
                "stale_capsule_rejected_count",
                "stale_proof_rejected_count",
                "stale_capsule_accepted_count",
                "stale_proof_accepted_count",
                "assurance_mutant_count",
                "assurance_mutant_detected_count",
                "assurance_mutant_survivor_count",
                "omission_mutant_count",
                "omission_mutant_detected_count",
                "vacuity_mutant_count",
                "vacuity_mutant_detected_count",
                "context_expansion_mutant_count",
                "context_expansion_mutant_detected_count",
                "critical_mutant_accepted_count",
                "assurance_sample_count",
                "assurance_failure_count",
                "human_review_required_count",
                "human_review_correct_count",
                "negative_review_autonomous_accept_count",
            ),
            context="a succeeded A/B attempt",
        )
        return

    incremental = _required_metrics(
        row,
        (
            "selected_test_count",
            "selected_test_pass_count",
            "selected_test_fail_count",
            "proof_selected_count",
            "proof_executed_count",
            "proof_pass_count",
            "proof_fail_count",
            "verification_reuse_hit_count",
            "verification_reuse_miss_count",
            "verification_full_fallback_count",
            "stale_capsule_rejected_count",
            "stale_capsule_accepted_count",
            "stale_proof_rejected_count",
            "stale_proof_accepted_count",
            "controlled_selected_test_false_negative_count",
            "route_failure_count",
            "frontier_escalation_count",
        ),
        context="a succeeded C/D attempt",
    )
    if (
        incremental["selected_test_pass_count"] != incremental["selected_test_count"]
        or incremental["selected_test_fail_count"] != 0
        or incremental["proof_fail_count"] != 0
    ):
        raise MetricAggregationError(
            "a succeeded C/D attempt contradicts incremental-verification acceptance"
        )
    reuse_total = (
        incremental["verification_reuse_hit_count"] + incremental["verification_reuse_miss_count"]
    )
    if reuse_total != 1:
        raise MetricAggregationError("a succeeded C/D attempt requires exactly one reuse outcome")
    if incremental["verification_reuse_hit_count"] == 1 and (
        incremental["proof_selected_count"] == 0
        or incremental["proof_executed_count"] >= incremental["proof_selected_count"]
    ):
        raise MetricAggregationError(
            "a succeeded reuse hit must leave at least one selected proof unexecuted"
        )
    if (
        incremental["verification_reuse_miss_count"] == 1
        and incremental["proof_executed_count"] != incremental["proof_selected_count"]
    ):
        raise MetricAggregationError("a succeeded reuse miss must execute every selected proof")
    if incremental["verification_full_fallback_count"] not in (0, 1):
        raise MetricAggregationError("verification_full_fallback_count must be zero or one")
    if (
        incremental["selected_test_count"] + incremental["proof_selected_count"] == 0
        and incremental["verification_full_fallback_count"] == 0
    ):
        raise MetricAggregationError(
            "a succeeded C/D attempt must perform incremental verification or full fallback"
        )
    for name in (
        "stale_capsule_rejected_count",
        "stale_capsule_accepted_count",
        "stale_proof_rejected_count",
        "stale_proof_accepted_count",
        "controlled_selected_test_false_negative_count",
        "route_failure_count",
    ):
        if incremental[name] != 0:
            raise MetricAggregationError(f"a succeeded C/D attempt requires {name}=0")

    provider_route_names = (
        "route_small_count",
        "route_local_count",
        "route_frontier_count",
    )
    provider_routes = {name: _metric_value(row, name) for name in provider_route_names}
    if any(value not in (None, 0, 1) for value in provider_routes.values()):
        raise MetricAggregationError("provider route counts must be zero or one per attempt")
    if sum(value or 0 for value in provider_routes.values()) != 1:
        raise MetricAggregationError(
            "a succeeded C/D attempt requires exactly one small/local/frontier route"
        )
    model_escalation = _metric_value(row, "model_escalation_count")
    if model_escalation not in (0, 1):
        raise MetricAggregationError("model_escalation_count must be zero or one per attempt")
    for name in ("route_human_count", "route_unavailable_count"):
        if _metric_value(row, name) not in (None, 0):
            raise MetricAggregationError(f"a succeeded C/D attempt cannot use {name}")
    if incremental["frontier_escalation_count"] != (provider_routes["route_frontier_count"] or 0):
        raise MetricAggregationError(
            "frontier_escalation_count must match the selected frontier route"
        )

    if configuration_id == "C":
        _require_zero_or_missing(
            row,
            (
                "context_expansion_count",
                "context_expansion_tokens",
                "assurance_mutant_count",
                "assurance_mutant_detected_count",
                "assurance_mutant_survivor_count",
                "omission_mutant_count",
                "omission_mutant_detected_count",
                "vacuity_mutant_count",
                "vacuity_mutant_detected_count",
                "context_expansion_mutant_count",
                "context_expansion_mutant_detected_count",
                "critical_mutant_accepted_count",
                "assurance_sample_count",
                "assurance_failure_count",
                "human_review_required_count",
                "human_review_correct_count",
                "negative_review_autonomous_accept_count",
            ),
            context="a succeeded C attempt",
        )
        return

    assurance = _required_metrics(
        row,
        (
            "context_expansion_count",
            "context_expansion_tokens",
            "assurance_mutant_count",
            "assurance_mutant_detected_count",
            "assurance_mutant_survivor_count",
            "omission_mutant_count",
            "omission_mutant_detected_count",
            "vacuity_mutant_count",
            "vacuity_mutant_detected_count",
            "context_expansion_mutant_count",
            "context_expansion_mutant_detected_count",
            "critical_mutant_accepted_count",
            "assurance_sample_count",
            "assurance_failure_count",
            "human_review_required_count",
            "human_review_correct_count",
            "negative_review_autonomous_accept_count",
        ),
        context="a succeeded D attempt",
    )
    if assurance["assurance_sample_count"] < 1:
        raise MetricAggregationError("a succeeded D attempt requires assurance sampling")
    for name in (
        "critical_mutant_accepted_count",
        "assurance_failure_count",
        "negative_review_autonomous_accept_count",
    ):
        if assurance[name] != 0:
            raise MetricAggregationError(f"a succeeded D attempt requires {name}=0")
    if assurance["human_review_required_count"] not in (0, 1) or assurance[
        "human_review_correct_count"
    ] not in (0, 1):
        raise MetricAggregationError("human review counts must be zero or one per attempt")
    if assurance["human_review_required_count"] != assurance["human_review_correct_count"]:
        raise MetricAggregationError(
            "a succeeded D attempt requires a correct review exactly when review is required"
        )


def _validate_non_success_row(row: Mapping[str, Any]) -> None:
    """Reject direct success claims without inventing unobserved acceptance authority.

    The canonical C/D emitters can retain a verification-complete non-success
    row: simulation is forcibly non-authoritative, and configuration D can be
    invalid solely because neither autonomous nor human acceptance authority
    was present.  That authority bit is intentionally not reconstructed from
    the public metric surface.  Direct claims that a failed row was a correct
    accepted patch are still rejected by :func:`_validate_row_semantics`.
    """

    correct = _metric_value(row, "correct_accepted_patch_count")
    if correct not in (None, 0):
        raise MetricAggregationError(
            "a non-success terminal status cannot claim a correct accepted patch"
        )


def _validate_row_semantics(row: Mapping[str, Any]) -> None:
    """Validate cross-field facts not expressible in the frozen shape schema."""

    eligible = _metric_value(row, "eligible_task_count")
    if eligible is not None and eligible not in (0, 1):
        raise MetricAggregationError("eligible_task_count must be zero or one per raw attempt")

    _validate_count_relation(row, "correct_accepted_patch_count", "accepted_patch_count")
    _validate_count_relation(row, "accepted_patch_count", "patch_proposal_count")
    if eligible is not None:
        for name in (
            "correct_accepted_patch_count",
            "accepted_patch_count",
            "first_attempt_success_count",
        ):
            value = _metric_value(row, name)
            if value is not None and value > eligible:
                raise MetricAggregationError(f"{name} cannot exceed eligible_task_count")

    correct = _metric_value(row, "correct_accepted_patch_count")
    if row["terminal_status"] != _SUCCESS_STATUS and correct not in (None, 0):
        raise MetricAggregationError(
            "a non-success terminal status contradicts a correct accepted patch claim"
        )
    score = _scored_correct(row)
    reported_rate = _metric_value(row, "correct_accepted_patch_rate_bp")
    if score is not None:
        scored_correct, denominator = score
        if denominator == 0:
            if reported_rate is not None:
                raise MetricAggregationError(
                    "zero eligible denominator cannot report a patch success rate"
                )
        elif reported_rate is not None and reported_rate != scored_correct * 10000 // denominator:
            raise MetricAggregationError(
                "correct_accepted_patch_rate_bp contradicts the semantic outcome"
            )

    first_success = _metric_value(row, "first_attempt_success_count")
    if first_success is not None:
        expected_first_success = int(row["attempt"] == 1 and score is not None and score == (1, 1))
        if first_success != expected_first_success:
            raise MetricAggregationError(
                "first_attempt_success_count contradicts attempt and semantic outcome"
            )

    provider_calls = _metric_value(row, "provider_call_count")
    if provider_calls is not None and provider_calls not in (0, 1):
        raise MetricAggregationError("provider_call_count must be zero or one per raw attempt")
    if row["terminal_status"] == _SUCCESS_STATUS and provider_calls != 1:
        raise MetricAggregationError("a succeeded attempt must bind exactly one provider call")

    configuration_id = row["configuration_id"]
    ordinary_tokens = _metric_value(row, "ordinary_retrieval_tokens")
    context_pack_tokens = _metric_value(row, "context_pack_tokens")
    exact_source_tokens = _metric_value(row, "exact_source_tokens")
    capsule_tokens = _metric_value(row, "capsule_tokens")
    if configuration_id == "A":
        _require_zero_or_missing(
            row,
            ("context_pack_tokens", "capsule_tokens"),
            context="an A attempt",
        )
        if (
            ordinary_tokens is not None
            and exact_source_tokens is not None
            and exact_source_tokens > ordinary_tokens
        ):
            raise MetricAggregationError(
                "A exact_source_tokens cannot exceed ordinary_retrieval_tokens"
            )
    else:
        _require_zero_or_missing(
            row,
            ("ordinary_retrieval_tokens",),
            context=f"a {configuration_id} attempt",
        )
        components = (exact_source_tokens, capsule_tokens)
        if context_pack_tokens is None and any(value is not None for value in components):
            raise MetricAggregationError(
                "semantic context component tokens require observed context_pack_tokens"
            )
        if context_pack_tokens is not None:
            observed_components = [value for value in components if value is not None]
            if any(value > context_pack_tokens for value in observed_components) or (
                len(observed_components) == len(components)
                and sum(observed_components) > context_pack_tokens
            ):
                raise MetricAggregationError(
                    "semantic context component tokens cannot exceed context_pack_tokens"
                )
    if configuration_id in {"A", "B", "C"}:
        _require_zero_or_missing(
            row,
            ("context_expansion_count", "context_expansion_tokens"),
            context=f"a {configuration_id} attempt",
        )
    expansion_count = _metric_value(row, "context_expansion_count")
    expansion_tokens = _metric_value(row, "context_expansion_tokens")
    if (
        expansion_count is not None
        and expansion_tokens is not None
        and (expansion_count == 0) != (expansion_tokens == 0)
    ):
        raise MetricAggregationError(
            "context expansion count and tokens must both be zero or both be positive"
        )

    for passed, total in (
        ("hidden_test_pass_count", "hidden_test_total_count"),
        ("selected_test_pass_count", "selected_test_count"),
        ("selected_test_fail_count", "selected_test_count"),
        ("full_test_pass_count", "full_test_count"),
        ("full_test_fail_count", "full_test_count"),
        ("proof_executed_count", "proof_selected_count"),
        ("proof_pass_count", "proof_executed_count"),
        ("proof_fail_count", "proof_executed_count"),
        ("assurance_mutant_detected_count", "assurance_mutant_count"),
        ("omission_mutant_detected_count", "omission_mutant_count"),
        ("vacuity_mutant_detected_count", "vacuity_mutant_count"),
        (
            "context_expansion_mutant_detected_count",
            "context_expansion_mutant_count",
        ),
    ):
        _validate_count_relation(row, passed, total)

    assurance_total = _metric_value(row, "assurance_mutant_count")
    assurance_detected = _metric_value(row, "assurance_mutant_detected_count")
    assurance_survived = _metric_value(row, "assurance_mutant_survivor_count")
    if all(
        value is not None for value in (assurance_total, assurance_detected, assurance_survived)
    ):
        assert assurance_total is not None
        assert assurance_detected is not None
        assert assurance_survived is not None
        if assurance_detected + assurance_survived != assurance_total:
            raise MetricAggregationError(
                "assurance mutant detections plus survivors must equal mutant count"
            )

    for total, passed, failed in (
        ("selected_test_count", "selected_test_pass_count", "selected_test_fail_count"),
        ("full_test_count", "full_test_pass_count", "full_test_fail_count"),
        ("proof_executed_count", "proof_pass_count", "proof_fail_count"),
    ):
        values = tuple(_metric_value(row, name) for name in (total, passed, failed))
        if all(value is not None for value in values):
            observed_total, observed_passed, observed_failed = values
            assert observed_total is not None
            assert observed_passed is not None
            assert observed_failed is not None
            if observed_passed + observed_failed != observed_total:
                raise MetricAggregationError(f"{passed} plus {failed} must equal {total}")

    if configuration_id in {"C", "D"}:
        selected = _metric_value(row, "selected_test_count")
        selected_passed = _metric_value(row, "selected_test_pass_count")
        full = _metric_value(row, "full_test_count")
        full_passed = _metric_value(row, "full_test_pass_count")
        controlled_false_negative = _metric_value(
            row,
            "controlled_selected_test_false_negative_count",
        )
        if all(value is not None for value in (selected, selected_passed, full, full_passed)):
            expected_false_negative = int(selected == selected_passed and full_passed != full)
            if (
                controlled_false_negative is not None
                and controlled_false_negative != expected_false_negative
            ):
                raise MetricAggregationError(
                    "controlled_selected_test_false_negative_count contradicts "
                    "the frozen C/D runner predicate"
                )

    if row["terminal_status"] == _SUCCESS_STATUS:
        _validate_successful_row(row)
    else:
        _validate_non_success_row(row)

    total_cost = _metric_value(row, "total_cost_micros")
    components = tuple(_metric_value(row, name) for name in _COST_COMPONENTS)
    if total_cost is not None:
        observed_components = [value for value in components if value is not None]
        if not observed_components:
            raise MetricAggregationError(
                "an observed total cost requires at least one observed cost component"
            )
        if row["terminal_status"] == _SUCCESS_STATUS and len(observed_components) != len(
            components
        ):
            raise MetricAggregationError(
                "a succeeded attempt cannot claim complete total cost with a missing component"
            )
        if total_cost != sum(observed_components):
            raise MetricAggregationError("total_cost_micros does not equal observed components")

    failed_cost = _metric_value(row, "failed_attempt_cost_micros")
    if row["terminal_status"] == _SUCCESS_STATUS:
        if failed_cost not in (None, 0):
            raise MetricAggregationError("a succeeded attempt cannot be charged as failed")
    elif total_cost is not None:
        if failed_cost is None:
            raise MetricAggregationError(
                "a failed attempt with observed total cost must expose failed_attempt_cost_micros"
            )
        if failed_cost != total_cost:
            raise MetricAggregationError(
                "failed_attempt_cost_micros must retain the complete failed-attempt total"
            )

    cost_per_patch = _metric_value(row, "cost_per_correct_accepted_patch_micros")
    if score is not None:
        scored_correct, _ = score
        if scored_correct == 0 and cost_per_patch is not None:
            raise MetricAggregationError(
                "zero correct-patch denominator cannot report cost per correct patch"
            )
        if scored_correct and total_cost is not None:
            expected_cost = total_cost // scored_correct
            if cost_per_patch is not None and cost_per_patch != expected_cost:
                raise MetricAggregationError(
                    "cost_per_correct_accepted_patch_micros contradicts observed cost"
                )

    routine = _metric_value(row, "routine_localized_task_count")
    frontier = _metric_value(row, "frontier_escalation_count")
    routine_rate = _metric_value(row, "routine_frontier_escalation_rate_bp")
    if routine is not None and routine not in (0, 1):
        raise MetricAggregationError(
            "routine_localized_task_count must be zero or one per raw attempt"
        )
    if routine_rate is not None and (routine is None or frontier is None):
        raise MetricAggregationError(
            "a frontier escalation rate requires observed numerator and denominator"
        )
    if routine == 0 and routine_rate is not None:
        raise MetricAggregationError(
            "zero routine denominator cannot report a frontier escalation rate"
        )
    if routine == 1 and frontier is not None:
        if frontier > 1:
            raise MetricAggregationError(
                "frontier escalation count cannot exceed one on one routine attempt"
            )
        expected_rate = frontier * 10000
        if routine_rate is not None and routine_rate != expected_rate:
            raise MetricAggregationError(
                "routine_frontier_escalation_rate_bp contradicts raw routing counts"
            )

    if row["provenance"] == "simulated":
        if row["terminal_status"] == _SUCCESS_STATUS:
            raise MetricAggregationError("simulated evidence cannot be upgraded to succeeded")
        accepted = _metric_value(row, "accepted_patch_count")
        simulated_accepted = _metric_value(row, "simulated_success_accepted_count")
        if accepted not in (None, 0) and (
            simulated_accepted is None or simulated_accepted < accepted
        ):
            raise MetricAggregationError(
                "a simulated accepted patch must trip simulated_success_accepted_count"
            )


def held_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact cross-configuration identity held by paired runners."""

    admitted = spec.validate_raw_result(row)
    _validate_row_semantics(admitted)
    return {field: admitted[field] for field in HELD_IDENTITY_FIELDS}


def held_identity_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the canonical tuple form of :func:`held_identity`."""

    return tuple(row[field] for field in HELD_IDENTITY_FIELDS)


def task_cluster_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return the paired bootstrap cluster identity, excluding retry number."""

    return tuple(row[field] for field in HELD_IDENTITY_FIELDS if field != "attempt")


def raw_result_cid(row: Mapping[str, Any]) -> str:
    """Return the canonical structured CID of one admitted raw result."""

    admitted = spec.validate_raw_result(row)
    _validate_row_semantics(admitted)
    return spec.structured_cid(admitted)


def validate_result_population(value: Any) -> list[dict[str, Any]]:
    """Admit one immutable-manifest population and reject duplicate identities."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise MetricAggregationError("raw result population must be a non-empty sequence")

    admitted: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        try:
            item = spec.validate_raw_result(row)
        except (spec.BenchmarkSpecificationError, TypeError, ValueError) as exc:
            raise MetricAggregationError(f"raw result {index} is invalid: {exc}") from exc
        expected_cid = _configuration_cid(item["configuration_id"])
        if item["configuration_cid"] != expected_cid:
            raise MetricAggregationError(
                f"configuration {item['configuration_id']} has a non-frozen CID"
            )
        _validate_row_semantics(item)
        admitted.append(item)

    manifests = {item["corpus_manifest_cid"] for item in admitted}
    if len(manifests) != 1:
        raise MetricAggregationError("one aggregate cannot mix corpus manifest identities")

    run_keys: set[str] = set()
    result_cids: set[str] = set()
    arm_identities: set[tuple[Any, ...]] = set()
    for item in admitted:
        if item["run_key"] in run_keys:
            raise MetricAggregationError("duplicate run_key identity")
        run_keys.add(item["run_key"])
        result_cid = spec.structured_cid(item)
        if result_cid in result_cids:
            raise MetricAggregationError(f"duplicate raw result CID: {result_cid}")
        result_cids.add(result_cid)
        arm_identity = (item["configuration_id"], *held_identity_key(item))
        if arm_identity in arm_identities:
            raise MetricAggregationError(
                "duplicate configuration result for one held attempt identity"
            )
        arm_identities.add(arm_identity)

    rows_by_arm_cluster: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in admitted:
        cluster = (
            item["configuration_id"],
            *task_cluster_key(item),
        )
        rows_by_arm_cluster.setdefault(cluster, []).append(item)
    for cluster_rows in rows_by_arm_cluster.values():
        ordered_rows = sorted(cluster_rows, key=lambda item: item["attempt"])
        ordered_attempts = [item["attempt"] for item in ordered_rows]
        expected_attempts = list(range(1, ordered_attempts[-1] + 1))
        if ordered_attempts != expected_attempts:
            raise MetricAggregationError(
                "attempt sequence must be complete from one; failed-attempt rows cannot be omitted"
            )
        if any(item["terminal_status"] == _SUCCESS_STATUS for item in ordered_rows[:-1]):
            raise MetricAggregationError("a succeeded task cannot have a later retry attempt")
        for denominator_name in ("full_test_count", "hidden_test_total_count"):
            denominator_values = [_metric_value(item, denominator_name) for item in ordered_rows]
            observed_denominators = {value for value in denominator_values if value is not None}
            if len(observed_denominators) > 1:
                raise MetricAggregationError(f"{denominator_name} drifted across retry attempts")

    admitted.sort(
        key=lambda item: (
            item["configuration_id"],
            held_identity_key(item),
            item["run_key"],
        )
    )
    return _clone(admitted)


def scored_correct_outcome(row: Mapping[str, Any]) -> dict[str, int] | None:
    """Expose the preregistered failure/abstention-zero score for one row."""

    admitted = spec.validate_raw_result(row)
    _validate_row_semantics(admitted)
    score = _scored_correct(admitted)
    if score is None:
        return None
    correct, eligible = score
    return {"correct": correct, "eligible": eligible}


def context_tokens(row: Mapping[str, Any]) -> int | None:
    """Return the frozen rendered-context denominator for one arm."""

    admitted = spec.validate_raw_result(row)
    _validate_row_semantics(admitted)
    name = (
        "ordinary_retrieval_tokens"
        if admitted["configuration_id"] == "A"
        else "context_pack_tokens"
    )
    return _metric_value(admitted, name)


def _semantic_trace_for_admitted(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = []
    for row in rows:
        score = _scored_correct(row)
        correct, eligible = (None, None) if score is None else score
        raw_correct = _metric_value(row, "correct_accepted_patch_count")
        trace.append(
            {
                "schema": SEMANTIC_TRACE_SCHEMA,
                "result_cid": spec.structured_cid(row),
                "task_record_cid": row["task_record_cid"],
                "configuration_id": row["configuration_id"],
                "configuration_cid": row["configuration_cid"],
                "attempt": row["attempt"],
                "provenance": row["provenance"],
                "terminal_status": row["terminal_status"],
                "eligible_task_count": eligible,
                "reported_correct_accepted_patch_count": raw_correct,
                "scored_correct_accepted_patch_count": correct,
                "failure_or_abstention_scored_zero": bool(
                    eligible == 1 and row["terminal_status"] != _SUCCESS_STATUS
                ),
                "semantic_outcome_match_count": _metric_value(row, "semantic_outcome_match_count"),
                "evidence_cids": list(row["evidence_cids"]),
            }
        )
    return trace


def semantic_outcome_trace(value: Any) -> list[dict[str, Any]]:
    """Return a counts-and-CIDs trace; hidden answer bytes are never represented."""

    return _semantic_trace_for_admitted(validate_result_population(value))


def _raw_aggregate_record(
    rows: Sequence[Mapping[str, Any]],
    name: str,
) -> tuple[int | None, str | None, dict[str, Any]]:
    observed: list[int] = []
    reasons: set[str] = set()
    for row in rows:
        value = _metric_value(row, name)
        if value is None:
            reasons.add(_missing_reason_id(row["missingness"][name]))
        else:
            observed.append(value)
    missing_count = len(rows) - len(observed)
    value = sum(observed) if missing_count == 0 else None
    reason = None
    if missing_count:
        reason = "input-missing:" + "|".join(sorted(reasons))
    evidence = {
        "source": "raw-identity-bound-sum",
        "frozen_aggregation": _DEFINITION_BY_NAME[name]["aggregation"],
        "observed_result_count": len(observed),
        "missing_result_count": missing_count,
        "partial_observed_value": sum(observed) if observed else None,
        "input_missing_reason_ids": sorted(reasons),
    }
    return value, reason, evidence


def _derived_evidence(
    rows: Sequence[Mapping[str, Any]],
    name: str,
    *,
    numerator: int | None,
    denominator: int | None,
    inputs: Sequence[str],
) -> dict[str, Any]:
    input_missing_reason_ids = {
        _missing_reason_id(row["missingness"][item])
        for row in rows
        for item in inputs
        if _metric_value(row, item) is None
    }
    missing_result_count = sum(
        1 for row in rows if any(_metric_value(row, item) is None for item in inputs)
    )
    return {
        "source": "recomputed-from-identity-bound-raw-results",
        "frozen_aggregation": _DEFINITION_BY_NAME[name]["aggregation"],
        "observed_result_count": len(rows) - missing_result_count,
        "missing_result_count": missing_result_count,
        "partial_observed_value": None,
        "input_missing_reason_ids": sorted(input_missing_reason_ids),
        "numerator": numerator,
        "denominator": denominator,
        "input_metrics": list(inputs),
        "reported_derived_value_count": sum(_metric_value(row, name) is not None for row in rows),
    }


def _set_derived(
    values: dict[str, int | None],
    missingness: dict[str, str],
    evidence: dict[str, dict[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    name: str,
    *,
    value: int | None,
    reason: str | None,
    numerator: int | None,
    denominator: int | None,
    inputs: Sequence[str],
) -> None:
    values[name] = value
    if value is None:
        assert reason is not None
        missingness[name] = reason
    evidence[name] = _derived_evidence(
        rows,
        name,
        numerator=numerator,
        denominator=denominator,
        inputs=inputs,
    )


def _task_clusters(rows: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    clustered: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        clustered.setdefault(task_cluster_key(row), []).append(row)
    return [sorted(clustered[key], key=lambda row: row["attempt"]) for key in sorted(clustered)]


def _terminal_task_scores(
    clusters: Sequence[Sequence[Mapping[str, Any]]],
) -> list[tuple[int, int]] | None:
    results: list[tuple[int, int]] = []
    for cluster in clusters:
        scores = [_scored_correct(row) for row in cluster]
        if any(score is None for score in scores):
            return None
        eligibility = {score[1] for score in scores if score is not None}
        if len(eligibility) != 1:
            raise MetricAggregationError("eligible_task_count drifted across retries")
        terminal_score = scores[-1]
        assert terminal_score is not None
        results.append(terminal_score)
    return results


def _aggregate_configuration_admitted(
    rows: Sequence[Mapping[str, Any]],
    configuration_id: str,
) -> dict[str, Any]:
    selected = [row for row in rows if row["configuration_id"] == configuration_id]
    if not selected:
        raise MetricAggregationError(f"no raw rows for configuration {configuration_id}")

    values: dict[str, int | None] = {}
    missingness: dict[str, str] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for name in RAW_SUM_METRIC_NAMES:
        value, reason, record = _raw_aggregate_record(selected, name)
        values[name] = value
        if reason is not None:
            missingness[name] = reason
        evidence[name] = record

    clusters = _task_clusters(selected)
    scored = _terminal_task_scores(clusters)
    if scored is None:
        _set_derived(
            values,
            missingness,
            evidence,
            selected,
            "correct_accepted_patch_rate_bp",
            value=None,
            reason="eligible-task-denominator-missing",
            numerator=None,
            denominator=None,
            inputs=("eligible_task_count", "correct_accepted_patch_count"),
        )
        correct_total: int | None = None
        eligible_total: int | None = None
    else:
        correct_total = sum(item[0] for item in scored)
        eligible_total = sum(item[1] for item in scored)
        if eligible_total == 0:
            rate = None
            reason = "zero-eligible-task-denominator"
        else:
            rate = correct_total * 10000 // eligible_total
            reason = None
        _set_derived(
            values,
            missingness,
            evidence,
            selected,
            "correct_accepted_patch_rate_bp",
            value=rate,
            reason=reason,
            numerator=correct_total,
            denominator=eligible_total,
            inputs=("eligible_task_count", "correct_accepted_patch_count"),
        )

    routine_task_values: list[int | None] = []
    routine_frontier_task_values: list[int | None] = []
    for cluster in clusters:
        routine_values = [_metric_value(row, "routine_localized_task_count") for row in cluster]
        if any(value is None for value in routine_values):
            routine_task_values.append(None)
            routine_frontier_task_values.append(None)
            continue
        observed_routine = {value for value in routine_values if value is not None}
        if len(observed_routine) != 1:
            raise MetricAggregationError("routine_localized_task_count drifted across retries")
        routine = next(iter(observed_routine))
        routine_task_values.append(routine)
        if routine:
            frontier_values = [_metric_value(row, "frontier_escalation_count") for row in cluster]
            routine_frontier_task_values.append(
                None
                if any(value is None for value in frontier_values)
                else int(any(value for value in frontier_values if value is not None))
            )
        else:
            routine_frontier_task_values.append(0)

    if any(value is None for value in routine_task_values) or any(
        frontier is None
        for routine, frontier in zip(
            routine_task_values,
            routine_frontier_task_values,
            strict=True,
        )
        if routine
    ):
        routine_numerator = None
        routine_denominator = None
        routine_rate = None
        routine_reason = "routine-frontier-denominator-or-numerator-missing"
    else:
        routine_denominator = sum(value for value in routine_task_values if value is not None)
        routine_numerator = sum(
            frontier or 0
            for routine, frontier in zip(
                routine_task_values,
                routine_frontier_task_values,
                strict=True,
            )
            if routine
        )
        if routine_denominator == 0:
            routine_rate = None
            routine_reason = "zero-routine-localized-denominator"
        else:
            routine_rate = routine_numerator * 10000 // routine_denominator
            routine_reason = None
    _set_derived(
        values,
        missingness,
        evidence,
        selected,
        "routine_frontier_escalation_rate_bp",
        value=routine_rate,
        reason=routine_reason,
        numerator=routine_numerator,
        denominator=routine_denominator,
        inputs=("routine_localized_task_count", "frontier_escalation_count"),
    )

    total_costs = [_metric_value(row, "total_cost_micros") for row in selected]
    if any(value is None for value in total_costs):
        cost_value = None
        cost_reason = "one-or-more-total-cost-observations-missing"
        cost_numerator = None
    else:
        cost_numerator = sum(value for value in total_costs if value is not None)
        if correct_total is None:
            cost_value = None
            cost_reason = "correct-patch-denominator-missing"
        elif correct_total == 0:
            cost_value = None
            cost_reason = "zero-correct-accepted-patch-denominator"
        else:
            cost_value = cost_numerator // correct_total
            cost_reason = None
    _set_derived(
        values,
        missingness,
        evidence,
        selected,
        "cost_per_correct_accepted_patch_micros",
        value=cost_value,
        reason=cost_reason,
        numerator=cost_numerator,
        denominator=correct_total,
        inputs=("total_cost_micros", "correct_accepted_patch_count"),
    )

    for name in ("context_reduction_bp", "total_cost_reduction_bp"):
        _set_derived(
            values,
            missingness,
            evidence,
            selected,
            name,
            value=None,
            reason="held-identity-paired-comparison-required",
            numerator=None,
            denominator=None,
            inputs=(
                ("ordinary_retrieval_tokens", "context_pack_tokens")
                if name == "context_reduction_bp"
                else ("total_cost_micros", "correct_accepted_patch_count")
            ),
        )

    # Preserve the exact frozen catalog order in every public aggregate.
    ordered_values = {name: values[name] for name in METRIC_NAMES}
    ordered_missingness = {name: missingness[name] for name in METRIC_NAMES if name in missingness}
    ordered_evidence = {name: evidence[name] for name in METRIC_NAMES}
    input_cids = sorted(spec.structured_cid(row) for row in selected)
    return {
        "schema": AGGREGATE_SCHEMA,
        "benchmark_id": spec.BENCHMARK_ID,
        "corpus_manifest_cid": selected[0]["corpus_manifest_cid"],
        "metric_catalog_cid": spec.catalog_cids()["metric_catalog_cid"],
        "metric_set_descriptor_cid": METRIC_SET_DESCRIPTOR_CID,
        "configuration_id": configuration_id,
        "configuration_cid": _configuration_cid(configuration_id),
        "result_count": len(selected),
        "task_cluster_count": len(clusters),
        "input_result_cids": input_cids,
        "metrics": ordered_values,
        "missingness": ordered_missingness,
        "metric_evidence": ordered_evidence,
        "semantic_outcome_trace": _semantic_trace_for_admitted(selected),
        "aggregate_scope": "descriptive-pure-aggregation-not-benchmark-qualification",
    }


def aggregate_configuration(value: Any, configuration_id: str) -> dict[str, Any]:
    """Aggregate all rows for one explicitly labelled configuration."""

    if configuration_id not in spec.CONFIGURATION_IDS:
        raise MetricAggregationError(f"unknown configuration: {configuration_id!r}")
    return _aggregate_configuration_admitted(validate_result_population(value), configuration_id)


def aggregate_results(value: Any) -> dict[str, Any]:
    """Aggregate every represented configuration without comparing treatments."""

    rows = validate_result_population(value)
    represented = [
        configuration_id
        for configuration_id in spec.CONFIGURATION_IDS
        if any(row["configuration_id"] == configuration_id for row in rows)
    ]
    aggregates = {
        configuration_id: _aggregate_configuration_admitted(rows, configuration_id)
        for configuration_id in represented
    }
    return {
        "schema": AGGREGATE_SET_SCHEMA,
        "benchmark_id": spec.BENCHMARK_ID,
        "corpus_manifest_cid": rows[0]["corpus_manifest_cid"],
        "metric_catalog_cid": spec.catalog_cids()["metric_catalog_cid"],
        "metric_set_descriptor_cid": METRIC_SET_DESCRIPTOR_CID,
        "configuration_ids": represented,
        "aggregates": aggregates,
        "input_result_cids": sorted(spec.structured_cid(row) for row in rows),
        "comparison_required_for_cross-arm_metrics": [
            "context_reduction_bp",
            "total_cost_reduction_bp",
        ],
        "aggregate_scope": "descriptive-pure-aggregation-not-benchmark-qualification",
    }


def aggregate_cid(value: Mapping[str, Any]) -> str:
    """Return the canonical structured identity of an aggregate/report body."""

    return spec.structured_cid(_clone(value))


def metric_set_descriptor() -> dict[str, Any]:
    """Return the immutable PCCE-066 aggregation behavior descriptor."""

    return {
        "schema": METRIC_SET_DESCRIPTOR_SCHEMA,
        "benchmark_id": spec.BENCHMARK_ID,
        "identity_profile": spec.IDENTITY_PROFILE,
        "metric_catalog_cid": spec.catalog_cids()["metric_catalog_cid"],
        "metric_count": len(METRIC_NAMES),
        "metric_names": list(METRIC_NAMES),
        "raw_sum_metric_names": list(RAW_SUM_METRIC_NAMES),
        "derived_metric_names": list(DERIVED_METRIC_NAMES),
        "held_identity_fields": list(HELD_IDENTITY_FIELDS),
        "arm_execution_identity_fields": list(ARM_EXECUTION_IDENTITY_FIELDS),
        "derivations": {
            "context_reduction_bp": (
                "paired-median((A-ordinary-retrieval-tokens-minus-"
                "candidate-context-pack-tokens)*10000/A-ordinary-retrieval-tokens)"
            ),
            "correct_accepted_patch_rate_bp": (
                "terminal-task-correct-outcomes*10000/eligible-task-clusters;"
                "terminal-failures-and-abstentions-score-zero"
            ),
            "routine_frontier_escalation_rate_bp": (
                "frontier-escalated-routine-tasks*10000/routine-localized-tasks"
            ),
            "cost_per_correct_accepted_patch_micros": (
                "all-observed-total-cost-including-failed-attempts/correct-accepted-patches"
            ),
            "total_cost_reduction_bp": ("paired-population-cost-per-correct-patch-ratio-reduction"),
        },
        "missingness_policy": "any-missing-raw-addend-keeps-aggregate-null",
        "missingness_reason_disclosure": "sha256-identities-only-no-producer-free-text",
        "semantic_trace_disclosure": "counts-cids-and-closed-taxonomy-fields-only",
        "zero_denominator_policy": "unavailable-no-go-never-zero-imputed",
        "failed_attempt_policy": "zero-quality-and-complete-observed-cost-retained",
        "retry_task_policy": (
            "contiguous-attempts-clustered-by-held-task-identity;terminal-task-outcome-"
            "scores-quality;all-attempt-costs-retained;no-retry-after-success"
        ),
        "suite_denominator_policy": (
            "null-full-or-hidden-suite-counts-retain-missingness;"
            "two-or-more-conflicting-observed-counts-rejected"
        ),
        "provenance_policy": "typed-live-replayed-simulated-never-upgraded",
        "semantic_trace_policy": "counts-and-cids-only-no-hidden-answer-bytes",
        "execution_effects": "none",
        "provider_calls": False,
        "benchmark_results_claimed": False,
        "production_qualification_claimed": False,
    }


METRIC_SET_DESCRIPTOR_CID: Final[str] = spec.structured_cid(metric_set_descriptor())


__all__ = [
    "AGGREGATE_SCHEMA",
    "AGGREGATE_SET_SCHEMA",
    "ARM_EXECUTION_IDENTITY_FIELDS",
    "DERIVED_METRIC_NAMES",
    "HELD_IDENTITY_FIELDS",
    "METRIC_NAMES",
    "METRIC_SET_DESCRIPTOR_CID",
    "METRIC_SET_DESCRIPTOR_SCHEMA",
    "RAW_SUM_METRIC_NAMES",
    "SEMANTIC_TRACE_SCHEMA",
    "MetricAggregationError",
    "aggregate_cid",
    "aggregate_configuration",
    "aggregate_results",
    "context_tokens",
    "held_identity",
    "held_identity_key",
    "metric_set_descriptor",
    "raw_result_cid",
    "scored_correct_outcome",
    "semantic_outcome_trace",
    "task_cluster_key",
    "validate_result_population",
]

"""Frozen external-generalization benchmark contracts for PCCE-060.

This module is specification authority only.  It performs no repository
fetching, benchmark execution, provider dispatch, persistence, or hidden-data
access.  The benchmark runner and metric aggregator consume these immutable
records in later PCCE tasks.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import PurePosixPath
from typing import Any, Final

from ipfs_datasets_py.logic.software_contracts.content import (
    cid_for_bytes,
    cid_for_obj,
    validate_cid,
    validate_structured_value,
)

BENCHMARK_ID: Final[str] = "pcce-external-generalization-v0.1"
BOARD_NAMESPACE: Final[str] = "proof-carrying-context-engine-v0.1"
FREEZE_TASK_ID: Final[str] = "PCCE-060"
FREEZE_TASK_CID: Final[str] = "baguqeerad676dzstuii524wli6hnfdfxgsfsmxgk2behffki6xtf3udcdvdq"
IDENTITY_PROFILE: Final[str] = "software-contract-cid-profile-v1"

SCHEMA_CATALOG_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-schema-catalog@1"
TASK_CONTROL_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-task-control@1"
TASK_AGENT_VIEW_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-task-agent-view@1"
CORPUS_MANIFEST_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-corpus-manifest@1"
CONFIGURATION_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-configuration@1"
RAW_RESULT_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-raw-result@1"
METRIC_DEFINITION_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-metric-definition@1"
THRESHOLD_SET_SCHEMA: Final[str] = "ipfs-datasets.proof-context.benchmark-threshold-set@1"

REPOSITORY_CLASSES: Final[tuple[str, ...]] = (
    "typed_structured",
    "dynamic_plugins",
    "mature_python",
)
TASK_KINDS: Final[tuple[str, ...]] = (
    "historical_replay",
    "controlled_synthetic",
    "assurance_mutation",
    "negative_human_review",
)
CONFIGURATION_IDS: Final[tuple[str, ...]] = ("A", "B", "C", "D")
PROVENANCE_CLASSES: Final[tuple[str, ...]] = ("live", "replayed", "simulated")
TERMINAL_STATUSES: Final[tuple[str, ...]] = (
    "succeeded",
    "rejected",
    "verification_failed",
    "proof_failed",
    "assurance_failed",
    "context_insufficient",
    "model_escalation_required",
    "human_review_required",
    "unavailable",
    "timeout",
    "cancelled",
    "invalid",
    "stale",
    "simulated",
    "infrastructure_failure",
    "partial_effect",
    "repair_required",
)
METRIC_CATEGORIES: Final[tuple[str, ...]] = (
    "context",
    "quality",
    "routing",
    "verification",
    "assurance",
    "economics",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_OID_RE = re.compile(r"^[0-9a-f]{40}$")
_RFC3339_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


class BenchmarkSpecificationError(ValueError):
    """Raised when frozen benchmark input is incomplete or ambiguous."""


def _json_clone(value: Any) -> Any:
    return deepcopy(value)


def _reject_float(value: str) -> Any:
    raise BenchmarkSpecificationError(f"floating-point JSON is not admitted: {value}")


def _reject_constant(value: str) -> Any:
    raise BenchmarkSpecificationError(f"non-finite JSON is not admitted: {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BenchmarkSpecificationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def strict_json_loads(payload: str | bytes) -> Any:
    """Decode the reviewed JSON subset and reject duplicate keys and floats."""

    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BenchmarkSpecificationError("JSON must be UTF-8") from exc
    elif isinstance(payload, str):
        text = payload
    else:
        raise BenchmarkSpecificationError("JSON input must be exact str or bytes")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except BenchmarkSpecificationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise BenchmarkSpecificationError("invalid strict JSON") from exc
    try:
        validate_structured_value(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkSpecificationError("JSON is outside the identity profile") from exc
    return value


def raw_bytes_cid(payload: bytes) -> str:
    if type(payload) is not bytes:
        raise BenchmarkSpecificationError("raw identity requires exact bytes")
    return cid_for_bytes(payload)


def structured_cid(payload: Mapping[str, Any] | list[Any]) -> str:
    try:
        return cid_for_obj(_json_clone(payload))
    except (TypeError, ValueError) as exc:
        raise BenchmarkSpecificationError("structured identity is invalid") from exc


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BenchmarkSpecificationError(f"{field} must be an object")
    return value


def _require_exact_fields(
    value: Mapping[str, Any],
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    field: str,
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - set(value))
    unknown = sorted(set(value) - allowed)
    if missing:
        raise BenchmarkSpecificationError(f"{field} missing fields: {missing}")
    if unknown:
        raise BenchmarkSpecificationError(f"{field} has unknown fields: {unknown}")


def _require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BenchmarkSpecificationError(f"{field} must be a non-empty string")
    return value


def _require_bool(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise BenchmarkSpecificationError(f"{field} must be a boolean")
    return value


def _require_int(value: Any, field: str, *, minimum: int | None = 0) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        qualifier = (
            "an integer" if minimum is None else f"an integer greater than or equal to {minimum}"
        )
        raise BenchmarkSpecificationError(f"{field} must be {qualifier}")
    return value


def _require_sha256(value: Any, field: str) -> str:
    text = _require_text(value, field)
    if not _SHA256_RE.fullmatch(text):
        raise BenchmarkSpecificationError(f"{field} must be lowercase SHA-256")
    return text


def _require_git_oid(value: Any, field: str) -> str:
    text = _require_text(value, field)
    if not _GIT_OID_RE.fullmatch(text):
        raise BenchmarkSpecificationError(f"{field} must be a full Git object id")
    return text


def _require_cid(value: Any, field: str) -> str:
    try:
        return validate_cid(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkSpecificationError(f"{field} must be a canonical CID") from exc


def _require_timestamp(value: Any, field: str) -> str:
    text = _require_text(value, field)
    if not _RFC3339_UTC_RE.fullmatch(text):
        raise BenchmarkSpecificationError(f"{field} must be RFC3339 UTC seconds")
    return text


def _require_string_list(
    value: Any,
    field: str,
    *,
    nonempty: bool = True,
    unique: bool = True,
) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise BenchmarkSpecificationError(f"{field} must be a non-empty array")
    result = [_require_text(item, f"{field}[]") for item in value]
    if unique and len(result) != len(set(result)):
        raise BenchmarkSpecificationError(f"{field} must contain unique values")
    return result


def _require_relative_path(value: Any, field: str) -> str:
    text = _require_text(value, field)
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or ".." in path.parts
        or ".git" in path.parts
        or "\\" in text
        or "\x00" in text
    ):
        raise BenchmarkSpecificationError(f"{field} is not a safe relative path")
    return text


_TASK_CONTROL_FIELDS: Final[list[str]] = [
    "schema",
    "task_id",
    "corpus_manifest_cid",
    "repository_class",
    "source_pin_id",
    "task_kind",
    "base_commit",
    "base_tree",
    "visible_projection_cid",
    "sealed_evaluator_root_cid",
    "objective",
    "owned_paths",
    "routine_localized",
    "risk_class",
    "seed",
    "eligible_configurations",
]
_TASK_AGENT_FIELDS: Final[list[str]] = [
    "schema",
    "task_id",
    "corpus_manifest_cid",
    "repository_class",
    "source_pin_id",
    "task_kind",
    "base_commit",
    "base_tree",
    "visible_projection_cid",
    "objective",
    "owned_paths",
    "routine_localized",
    "risk_class",
    "seed",
    "eligible_configurations",
]
_RAW_RESULT_FIELDS: Final[list[str]] = [
    "schema",
    "run_key",
    "corpus_manifest_cid",
    "task_record_cid",
    "visible_projection_cid",
    "configuration_id",
    "configuration_cid",
    "repository_state_cid",
    "environment_cid",
    "provider_id",
    "model_id",
    "model_revision",
    "seed",
    "attempt",
    "provenance",
    "terminal_status",
    "metrics",
    "missingness",
    "evidence_cids",
]

_SCHEMA_CATALOG: Final[dict[str, Any]] = {
    "schema": SCHEMA_CATALOG_SCHEMA,
    "benchmark_id": BENCHMARK_ID,
    "identity_profile": IDENTITY_PROFILE,
    "unknown_fields": "rejected",
    "number_policy": "integers-basis-points-and-micros-only",
    "missingness_policy": "null-plus-typed-reason-never-imputed-zero",
    "schemas": [
        {
            "schema_id": TASK_CONTROL_SCHEMA,
            "required_fields": _TASK_CONTROL_FIELDS,
            "self_identity_field": None,
        },
        {
            "schema_id": TASK_AGENT_VIEW_SCHEMA,
            "required_fields": _TASK_AGENT_FIELDS,
            "self_identity_field": None,
        },
        {
            "schema_id": CORPUS_MANIFEST_SCHEMA,
            "required_fields": [
                "schema",
                "benchmark_id",
                "board_namespace",
                "freeze_task_id",
                "freeze_task_cid",
                "freeze_state",
                "frozen_at",
                "results_observed_before_freeze",
                "identity_profile",
                "runtime_gate",
                "catalog_bindings",
                "corpus_requirements",
                "source_pins",
                "isolation_policy",
                "materialization_policy",
                "downstream_bindings",
            ],
            "self_identity_field": None,
        },
        {
            "schema_id": CONFIGURATION_SCHEMA,
            "required_fields": [
                "schema",
                "configuration_id",
                "context_method",
                "model_policy",
                "verification_policy",
                "routing_enabled",
                "incremental_verification_enabled",
                "proof_reuse_enabled",
                "sufficiency_enabled",
                "context_expansion_enabled",
                "assurance_enabled",
                "incremental_seal_enabled",
                "human_escalation_enabled",
                "hidden_full_scoring",
                "prompt_policy",
                "seed_policy",
                "environment_policy",
                "context_estimator",
            ],
            "self_identity_field": None,
        },
        {
            "schema_id": RAW_RESULT_SCHEMA,
            "required_fields": _RAW_RESULT_FIELDS,
            "self_identity_field": None,
        },
        {
            "schema_id": METRIC_DEFINITION_SCHEMA,
            "required_fields": [
                "schema",
                "name",
                "category",
                "value_type",
                "unit",
                "source",
                "aggregation",
                "population",
                "direction",
                "observed_requirement",
                "numerator",
                "denominator",
            ],
            "self_identity_field": None,
        },
        {
            "schema_id": THRESHOLD_SET_SCHEMA,
            "required_fields": [
                "schema",
                "benchmark_id",
                "corpus_manifest_cid",
                "schema_catalog_cid",
                "frozen_at",
                "freeze_state",
                "results_observed_before_freeze",
                "primary_comparisons",
                "analysis",
                "zero_tolerance",
                "evidence_policy",
            ],
            "self_identity_field": None,
        },
    ],
    "enums": {
        "repository_classes": list(REPOSITORY_CLASSES),
        "task_kinds": list(TASK_KINDS),
        "configuration_ids": list(CONFIGURATION_IDS),
        "provenance": list(PROVENANCE_CLASSES),
        "terminal_statuses": list(TERMINAL_STATUSES),
        "metric_categories": list(METRIC_CATEGORIES),
    },
}

_COMMON_CONFIGURATION: Final[dict[str, Any]] = {
    "schema": CONFIGURATION_SCHEMA,
    "hidden_full_scoring": True,
    "prompt_policy": "pcce-benchmark-prompt-policy-v1",
    "seed_policy": "sha256-corpus-task-first-unsigned-64-v1",
    "environment_policy": "exact-pcce-056-qualified-environment-or-unavailable",
    "context_estimator": "utf8-bytes-ceiling-divide-by-four-no-calibration@1",
}


def _configuration(
    configuration_id: str,
    *,
    context_method: str,
    model_policy: str,
    verification_policy: str,
    routing: bool,
    incremental: bool,
    reuse: bool,
    sufficiency: bool,
    expansion: bool,
    assurance: bool,
    seal: bool,
    human: bool,
) -> dict[str, Any]:
    return {
        **_COMMON_CONFIGURATION,
        "configuration_id": configuration_id,
        "context_method": context_method,
        "model_policy": model_policy,
        "verification_policy": verification_policy,
        "routing_enabled": routing,
        "incremental_verification_enabled": incremental,
        "proof_reuse_enabled": reuse,
        "sufficiency_enabled": sufficiency,
        "context_expansion_enabled": expansion,
        "assurance_enabled": assurance,
        "incremental_seal_enabled": seal,
        "human_escalation_enabled": human,
    }


_CONFIGURATIONS: Final[list[dict[str, Any]]] = [
    _configuration(
        "A",
        context_method="ordinary-lexical-raw-retrieval@1",
        model_policy="execution-permit-exact-frontier-pair@1",
        verification_policy="full-runtime-verification@1",
        routing=False,
        incremental=False,
        reuse=False,
        sufficiency=False,
        expansion=False,
        assurance=False,
        seal=False,
        human=False,
    ),
    _configuration(
        "B",
        context_method="semantic-context-pack-v0.1",
        model_policy="execution-permit-exact-frontier-pair@1",
        verification_policy="full-runtime-verification@1",
        routing=False,
        incremental=False,
        reuse=False,
        sufficiency=False,
        expansion=False,
        assurance=False,
        seal=False,
        human=False,
    ),
    _configuration(
        "C",
        context_method="semantic-context-pack-v0.1",
        model_policy="execution-permit-exact-frozen-route-policy@1",
        verification_policy="incremental-tests-proofs-with-hidden-full-scoring@1",
        routing=True,
        incremental=True,
        reuse=True,
        sufficiency=False,
        expansion=False,
        assurance=False,
        seal=False,
        human=False,
    ),
    _configuration(
        "D",
        context_method="semantic-context-pack-v0.1",
        model_policy="execution-permit-exact-frozen-route-policy@1",
        verification_policy="incremental-tests-proofs-with-hidden-full-scoring@1",
        routing=True,
        incremental=True,
        reuse=True,
        sufficiency=True,
        expansion=True,
        assurance=True,
        seal=True,
        human=True,
    ),
]

CONFIGURATION_DIFF_WHITELIST: Final[dict[str, list[str]]] = {
    "A->B": ["context_method"],
    "B->C": [
        "incremental_verification_enabled",
        "model_policy",
        "proof_reuse_enabled",
        "routing_enabled",
        "verification_policy",
    ],
    "C->D": [
        "assurance_enabled",
        "context_expansion_enabled",
        "human_escalation_enabled",
        "incremental_seal_enabled",
        "sufficiency_enabled",
    ],
}


def _metric(
    name: str,
    category: str,
    *,
    value_type: str = "nonnegative_integer",
    unit: str = "count",
    source: str = "raw",
    aggregation: str = "sum",
    population: str = "all-eligible-terminal-attempts",
    direction: str = "descriptive",
    observed_requirement: str = "observed-or-null",
    numerator: str | None = None,
    denominator: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": METRIC_DEFINITION_SCHEMA,
        "name": name,
        "category": category,
        "value_type": value_type,
        "unit": unit,
        "source": source,
        "aggregation": aggregation,
        "population": population,
        "direction": direction,
        "observed_requirement": observed_requirement,
        "numerator": numerator,
        "denominator": denominator,
    }


_METRICS: Final[list[dict[str, Any]]] = [
    _metric("provider_input_tokens", "context", unit="tokens"),
    _metric("provider_output_tokens", "context", unit="tokens"),
    _metric("provider_cached_input_tokens", "context", unit="tokens"),
    _metric("ordinary_retrieval_tokens", "context", unit="tokens"),
    _metric("context_pack_tokens", "context", unit="tokens"),
    _metric("exact_source_tokens", "context", unit="tokens"),
    _metric("capsule_tokens", "context", unit="tokens"),
    _metric("context_expansion_tokens", "context", unit="tokens"),
    _metric("context_fallback_count", "context"),
    _metric("context_expansion_count", "context"),
    _metric(
        "context_reduction_bp",
        "context",
        value_type="signed_basis_points",
        unit="basis_points",
        source="derived",
        aggregation="paired-task-median",
        population="paired-eligible-tasks-with-positive-A-context",
        direction="higher-is-better",
        numerator="A-context-tokens-minus-candidate-context-tokens",
        denominator="A-context-tokens",
    ),
    _metric("eligible_task_count", "quality"),
    _metric("patch_proposal_count", "quality"),
    _metric("accepted_patch_count", "quality"),
    _metric("correct_accepted_patch_count", "quality"),
    _metric("hidden_test_pass_count", "quality"),
    _metric("hidden_test_total_count", "quality"),
    _metric("regression_count", "quality", direction="lower-is-better"),
    _metric(
        "critical_regression_accepted_count",
        "quality",
        direction="zero-tolerance",
    ),
    _metric("out_of_scope_edit_count", "quality", direction="lower-is-better"),
    _metric("human_review_required_count", "quality"),
    _metric("human_review_correct_count", "quality", direction="higher-is-better"),
    _metric("first_attempt_success_count", "quality", direction="higher-is-better"),
    _metric("semantic_outcome_match_count", "quality", direction="higher-is-better"),
    _metric(
        "correct_accepted_patch_rate_bp",
        "quality",
        value_type="basis_points",
        unit="basis_points",
        source="derived",
        aggregation="paired-task-rate",
        population="eligible-patch-bearing-tasks-failures-and-abstentions-score-zero",
        direction="higher-is-better",
        numerator="correct_accepted_patch_count",
        denominator="eligible-patch-bearing-task-count",
    ),
    _metric("route_small_count", "routing"),
    _metric("route_local_count", "routing"),
    _metric("route_frontier_count", "routing"),
    _metric("route_human_count", "routing"),
    _metric("route_unavailable_count", "routing"),
    _metric("model_escalation_count", "routing", direction="lower-is-better"),
    _metric("frontier_escalation_count", "routing", direction="lower-is-better"),
    _metric("routine_localized_task_count", "routing"),
    _metric("route_failure_count", "routing", direction="lower-is-better"),
    _metric(
        "routine_frontier_escalation_rate_bp",
        "routing",
        value_type="basis_points",
        unit="basis_points",
        source="derived",
        aggregation="population-rate",
        population="D-routine-localized-eligible-tasks",
        direction="lower-is-better",
        numerator="frontier-escalation-on-routine-localized-count",
        denominator="routine_localized_task_count",
    ),
    _metric("selected_test_count", "verification"),
    _metric("selected_test_pass_count", "verification"),
    _metric("selected_test_fail_count", "verification"),
    _metric("full_test_count", "verification"),
    _metric("full_test_pass_count", "verification"),
    _metric("full_test_fail_count", "verification"),
    _metric(
        "controlled_selected_test_false_negative_count",
        "verification",
        direction="zero-tolerance",
    ),
    _metric("proof_selected_count", "verification"),
    _metric("proof_executed_count", "verification"),
    _metric("proof_pass_count", "verification"),
    _metric("proof_fail_count", "verification"),
    _metric("verification_reuse_hit_count", "verification"),
    _metric("verification_reuse_miss_count", "verification"),
    _metric("verification_full_fallback_count", "verification"),
    _metric("stale_capsule_rejected_count", "verification"),
    _metric("stale_proof_rejected_count", "verification"),
    _metric("stale_capsule_accepted_count", "verification", direction="zero-tolerance"),
    _metric("stale_proof_accepted_count", "verification", direction="zero-tolerance"),
    _metric(
        "simulated_success_accepted_count",
        "verification",
        direction="zero-tolerance",
    ),
    _metric("assurance_mutant_count", "assurance"),
    _metric("assurance_mutant_detected_count", "assurance", direction="higher-is-better"),
    _metric("assurance_mutant_survivor_count", "assurance", direction="lower-is-better"),
    _metric("omission_mutant_count", "assurance"),
    _metric("omission_mutant_detected_count", "assurance", direction="higher-is-better"),
    _metric("vacuity_mutant_count", "assurance"),
    _metric("vacuity_mutant_detected_count", "assurance", direction="higher-is-better"),
    _metric("context_expansion_mutant_count", "assurance"),
    _metric(
        "context_expansion_mutant_detected_count",
        "assurance",
        direction="higher-is-better",
    ),
    _metric("critical_mutant_accepted_count", "assurance", direction="zero-tolerance"),
    _metric(
        "negative_review_autonomous_accept_count",
        "assurance",
        direction="zero-tolerance",
    ),
    _metric("assurance_sample_count", "assurance"),
    _metric("assurance_failure_count", "assurance", direction="lower-is-better"),
    _metric("provider_call_count", "economics", unit="calls"),
    _metric(
        "inference_cost_micros",
        "economics",
        unit="currency_micros",
        observed_requirement="observed-live-required-for-primary-cost",
    ),
    _metric("verification_cost_micros", "economics", unit="currency_micros"),
    _metric("proof_cost_micros", "economics", unit="currency_micros"),
    _metric("assurance_cost_micros", "economics", unit="currency_micros"),
    _metric("failure_cost_micros", "economics", unit="currency_micros"),
    _metric("human_cost_micros", "economics", unit="currency_micros"),
    _metric(
        "total_cost_micros",
        "economics",
        unit="currency_micros",
        observed_requirement="observed-live-required-for-primary-cost",
    ),
    _metric("failed_attempt_cost_micros", "economics", unit="currency_micros"),
    _metric(
        "cost_per_correct_accepted_patch_micros",
        "economics",
        value_type="nullable_nonnegative_integer",
        unit="currency_micros",
        source="derived",
        aggregation="total-cost-divided-by-correct-accepted-patches",
        population="eligible-patch-bearing-tasks-including-failed-attempt-costs",
        direction="lower-is-better",
        observed_requirement="observed-live-required-for-primary-cost",
        numerator="total_cost_micros",
        denominator="correct_accepted_patch_count",
    ),
    _metric(
        "total_cost_reduction_bp",
        "economics",
        value_type="signed_basis_points",
        unit="basis_points",
        source="derived",
        aggregation="paired-population-ratio",
        population="paired-eligible-patch-bearing-tasks",
        direction="higher-is-better",
        observed_requirement="observed-live-required-for-primary-cost",
        numerator="A-cost-per-patch-minus-D-cost-per-patch",
        denominator="A-cost-per-patch",
    ),
]

_ISOLATION_POLICY: Final[dict[str, Any]] = {
    "schema": "ipfs-datasets.proof-context.benchmark-isolation-policy@1",
    "agent_projection": [
        "history-stripped-baseline-tree",
        "objective",
        "owned-paths",
        "public-tests",
    ],
    "evaluator_projection": [
        "hidden-tests",
        "historical-answer",
        "negative-review-rubric",
        "assurance-mutant-outcomes",
    ],
    "agent_forbidden": [
        "future-commits",
        "expected-patch-bytes",
        "hidden-test-bytes",
        "gold-labels",
        "evaluator-paths",
        "pre-terminal-evaluator-diagnostics",
    ],
    "historical_replay": {
        "git_history": "absent-from-agent-projection",
        "remotes": "absent",
        "descendant_objects": "absent",
        "task_base": "exact-ancestor-of-class-cutoff",
    },
    "execution": {
        "hidden_mount_time": "after-patch-proposal",
        "hidden_evaluator_namespace": "separate-denied-projection",
        "network": "denied-except-explicit-provider-permit",
        "worktree": "one-disposable-worktree-per-task-arm",
        "cache": "namespaced-by-corpus-task-configuration-and-environment",
        "provider_conversation_reuse_across_arms": False,
        "symlink_hardlink_and_path_escape": "denied",
    },
    "aggregation": {
        "answer_bytes_visible": False,
        "terminal_scores_visible": True,
        "repair_feedback_from_hidden_evaluation": False,
    },
    "contamination_disposition": "invalidate-v1-and-create-new-version",
}

_CORPUS_REQUIREMENTS: Final[dict[str, Any]] = {
    "repository_classes": list(REPOSITORY_CLASSES),
    "task_kinds": list(TASK_KINDS),
    "minimum_tasks_per_kind_per_class": 1,
    "minimum_total_tasks": 12,
    "task_kind_labels_are_distinct": True,
    "historical_base_rule": "exact-ancestor-of-class-cutoff",
    "eligibility_rule": "frozen-before-first-attempt-no-result-informed-exclusions",
    "default_eligible_configurations": list(CONFIGURATION_IDS),
}

_MATERIALIZATION_POLICY: Final[dict[str, Any]] = {
    "fetch": "one-explicit-corpus-fetch-permit-then-offline",
    "execution_network": "denied",
    "archive_verification": "exact-size-sha256-commit-and-tree",
    "tag_authority": False,
    "commit_tree_and_archive_authority": True,
    "mutable_revision_allowed": False,
    "hugging_face_dataset_allowed": False,
    "repin_after_results_allowed": False,
    "shard_manifests": "created-by-PCCE-061-PCCE-062-PCCE-063-without-editing-freeze",
}

_DOWNSTREAM_BINDINGS: Final[dict[str, Any]] = {
    "typed_structured": {
        "task_id": "PCCE-061",
        "path": "benchmarks/proof_context/corpus/typed_structured",
    },
    "dynamic_plugins": {
        "task_id": "PCCE-062",
        "path": "benchmarks/proof_context/corpus/dynamic_plugins",
    },
    "mature_python": {
        "task_id": "PCCE-063",
        "path": "benchmarks/proof_context/corpus/mature_python",
    },
    "configuration_ab_task_id": "PCCE-064",
    "configuration_cd_task_id": "PCCE-065",
    "metrics_task_id": "PCCE-066",
    "execution_task_id": "PCCE-067",
    "qualification_task_id": "PCCE-068",
}

_THRESHOLD_POLICY: Final[dict[str, Any]] = {
    "primary_comparisons": {
        "context_reduction": {
            "baseline": "A",
            "candidate": "D",
            "isolated_diagnostic": "B-vs-A",
            "metric": "context_reduction_bp",
            "minimum_bp": 5000,
            "target_bp": 6000,
        },
        "total_cost_reduction": {
            "baseline": "A",
            "candidate": "D",
            "metric": "total_cost_reduction_bp",
            "minimum_bp": 3000,
            "target_bp": 5000,
            "evidence": "observed-live-only",
        },
        "accepted_patch_noninferiority": {
            "baseline": "A",
            "candidate": "D",
            "metric": "correct_accepted_patch_rate_bp",
            "direction": "candidate-minus-baseline",
            "margin_bp": 500,
            "decision_rule": "lower-confidence-bound-greater-than-or-equal-minus-margin",
        },
        "routine_frontier_escalation": {
            "configuration": "D",
            "metric": "routine_frontier_escalation_rate_bp",
            "maximum_bp": 2500,
            "target_bp": 2000,
        },
    },
    "analysis": {
        "confidence_bp": 9500,
        "confidence_side": "one-sided-lower",
        "method": "seeded-percentile-paired-task-cluster-bootstrap",
        "bootstrap_samples": 10000,
        "bootstrap_seed": 60060,
        "insufficient_population": "inconclusive-no-go",
        "zero_denominator": "unavailable-no-go",
        "failed_and_abstained_patch_tasks_score": 0,
    },
    "zero_tolerance": {
        "critical_regression_accepted_count": 0,
        "stale_capsule_accepted_count": 0,
        "stale_proof_accepted_count": 0,
        "simulated_success_accepted_count": 0,
        "controlled_selected_test_false_negative_count": 0,
        "critical_mutant_accepted_count": 0,
        "negative_review_autonomous_accept_count": 0,
    },
    "evidence_policy": {
        "live_quality_required": True,
        "observed_cost_required": True,
        "replay_counts_as_live": False,
        "simulation_counts_as_live": False,
        "estimated_cost_can_pass": False,
        "missing_live_provider": "unavailable-no-go",
        "failed_attempt_costs_included": True,
    },
}


def schema_catalog() -> dict[str, Any]:
    return _json_clone(_SCHEMA_CATALOG)


def configuration_catalog() -> list[dict[str, Any]]:
    return _json_clone(_CONFIGURATIONS)


def metric_catalog() -> list[dict[str, Any]]:
    return _json_clone(_METRICS)


def metric_completeness_matrix() -> dict[str, list[str]]:
    result = {category: [] for category in METRIC_CATEGORIES}
    for definition in _METRICS:
        result[definition["category"]].append(definition["name"])
    return result


def isolation_policy() -> dict[str, Any]:
    return _json_clone(_ISOLATION_POLICY)


def corpus_requirements() -> dict[str, Any]:
    return _json_clone(_CORPUS_REQUIREMENTS)


def materialization_policy() -> dict[str, Any]:
    return _json_clone(_MATERIALIZATION_POLICY)


def downstream_bindings() -> dict[str, Any]:
    return _json_clone(_DOWNSTREAM_BINDINGS)


def threshold_policy() -> dict[str, Any]:
    return _json_clone(_THRESHOLD_POLICY)


def catalog_cids() -> dict[str, str]:
    return {
        "schema_catalog_cid": structured_cid(schema_catalog()),
        "configuration_catalog_cid": structured_cid(configuration_catalog()),
        "metric_catalog_cid": structured_cid(metric_catalog()),
        "metric_completeness_matrix_cid": structured_cid(metric_completeness_matrix()),
        "isolation_policy_cid": structured_cid(isolation_policy()),
    }


def configuration_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> list[str]:
    keys = set(left) | set(right)
    return sorted(
        key for key in keys if key != "configuration_id" and left.get(key) != right.get(key)
    )


def validate_configuration_catalog(value: Any) -> list[dict[str, Any]]:
    if value != _CONFIGURATIONS:
        raise BenchmarkSpecificationError("configuration catalog differs from freeze")
    by_id = {item["configuration_id"]: item for item in value}
    if tuple(by_id) != CONFIGURATION_IDS:
        raise BenchmarkSpecificationError("configuration order must be A, B, C, D")
    for transition, allowed in CONFIGURATION_DIFF_WHITELIST.items():
        left_id, right_id = transition.split("->")
        actual = configuration_diff(by_id[left_id], by_id[right_id])
        if actual != allowed:
            raise BenchmarkSpecificationError(
                f"configuration difference {transition} is not frozen: {actual}"
            )
    return _json_clone(value)


def validate_metric_catalog(value: Any) -> list[dict[str, Any]]:
    if value != _METRICS:
        raise BenchmarkSpecificationError("metric catalog differs from freeze")
    names = [item["name"] for item in value]
    if len(names) != len(set(names)):
        raise BenchmarkSpecificationError("metric names must be unique")
    categories = {item["category"] for item in value}
    if categories != set(METRIC_CATEGORIES):
        raise BenchmarkSpecificationError("metric categories are incomplete")
    return _json_clone(value)


def _validate_runtime_gate(value: Any) -> None:
    gate = _require_mapping(value, "runtime_gate")
    _require_exact_fields(
        gate,
        required=[
            "dependency_task_id",
            "qualification_path",
            "receipt_path",
            "qualification_sha256",
            "qualification_cid",
            "qualification_status",
            "live_execution_eligible",
            "binding_state",
        ],
        field="runtime_gate",
    )
    if gate["dependency_task_id"] != "PCCE-056":
        raise BenchmarkSpecificationError("runtime gate must bind PCCE-056")
    _require_relative_path(gate["qualification_path"], "qualification_path")
    _require_relative_path(gate["receipt_path"], "receipt_path")
    if gate["qualification_status"] != "no-go":
        raise BenchmarkSpecificationError("PCCE-056 qualification must remain no-go")
    if _require_bool(gate["live_execution_eligible"], "live_execution_eligible"):
        raise BenchmarkSpecificationError("no-go PCCE-056 cannot enable live execution")
    if _require_text(gate["binding_state"], "binding_state") != "final-content-addressed":
        raise BenchmarkSpecificationError("runtime gate is not final content-addressed evidence")
    _require_sha256(gate["qualification_sha256"], "qualification_sha256")
    _require_cid(gate["qualification_cid"], "qualification_cid")


def _validate_source_pin(value: Any, expected_class: str) -> None:
    pin = _require_mapping(value, f"source_pin[{expected_class}]")
    _require_exact_fields(
        pin,
        required=[
            "pin_id",
            "repository_class",
            "repository",
            "origin",
            "display_tag",
            "tag_kind",
            "tag_object",
            "commit",
            "tree",
            "commit_time",
            "archive",
            "license",
            "availability_probe",
            "inventory",
            "authority",
        ],
        field=f"source_pin[{expected_class}]",
    )
    if pin["repository_class"] != expected_class:
        raise BenchmarkSpecificationError("source pin repository class order changed")
    _require_text(pin["pin_id"], "pin_id")
    _require_text(pin["repository"], "repository")
    origin = _require_text(pin["origin"], "origin")
    if not origin.startswith("https://github.com/") or not origin.endswith(".git"):
        raise BenchmarkSpecificationError("source origin must be canonical GitHub HTTPS")
    _require_text(pin["display_tag"], "display_tag")
    if pin["tag_kind"] not in {"annotated", "lightweight"}:
        raise BenchmarkSpecificationError("tag_kind must be annotated or lightweight")
    if pin["tag_kind"] == "annotated":
        _require_git_oid(pin["tag_object"], "tag_object")
    elif pin["tag_object"] is not None:
        raise BenchmarkSpecificationError("lightweight tag_object must be null")
    _require_git_oid(pin["commit"], "commit")
    _require_git_oid(pin["tree"], "tree")
    _require_timestamp(pin["commit_time"], "commit_time")
    if pin["authority"] != "commit-tree-and-exact-archive-bytes":
        raise BenchmarkSpecificationError("tag names cannot be source authority")

    archive = _require_mapping(pin["archive"], "archive")
    _require_exact_fields(
        archive,
        required=["url", "sha256", "size"],
        field="archive",
    )
    if pin["commit"] not in _require_text(archive["url"], "archive.url"):
        raise BenchmarkSpecificationError("archive URL must name the exact commit")
    _require_sha256(archive["sha256"], "archive.sha256")
    _require_int(archive["size"], "archive.size", minimum=1)

    license_record = _require_mapping(pin["license"], "license")
    _require_exact_fields(
        license_record,
        required=["path", "spdx", "sha256"],
        field="license",
    )
    _require_relative_path(license_record["path"], "license.path")
    _require_text(license_record["spdx"], "license.spdx")
    _require_sha256(license_record["sha256"], "license.sha256")

    probe = _require_mapping(pin["availability_probe"], "availability_probe")
    _require_exact_fields(
        probe,
        required=[
            "observed_at",
            "git_ls_remote",
            "commit_api",
            "archive_http_status",
            "license_http_status",
            "status",
        ],
        field="availability_probe",
    )
    _require_timestamp(probe["observed_at"], "availability_probe.observed_at")
    if probe["git_ls_remote"] != "exact-tag-and-resolved-commit-match":
        raise BenchmarkSpecificationError("git availability probe is not exact")
    if probe["commit_api"] != "exact-commit-and-tree-match":
        raise BenchmarkSpecificationError("commit API probe is not exact")
    if probe["archive_http_status"] != 200 or probe["license_http_status"] != 200:
        raise BenchmarkSpecificationError("source bytes were not available")
    if probe["status"] != "available-observational-not-execution-authority":
        raise BenchmarkSpecificationError("source availability status is invalid")

    inventory = _require_mapping(pin["inventory"], "inventory")
    _require_exact_fields(
        inventory,
        required=["blob_count", "python_file_count", "python_test_file_count"],
        field="inventory",
    )
    for key in inventory:
        _require_int(inventory[key], f"inventory.{key}", minimum=1)


def validate_corpus_manifest(value: Any) -> dict[str, Any]:
    manifest = _require_mapping(value, "corpus_manifest")
    required = _SCHEMA_CATALOG["schemas"][2]["required_fields"]
    _require_exact_fields(manifest, required=required, field="corpus_manifest")
    expected_scalars = {
        "schema": CORPUS_MANIFEST_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "board_namespace": BOARD_NAMESPACE,
        "freeze_task_id": FREEZE_TASK_ID,
        "freeze_task_cid": FREEZE_TASK_CID,
        "freeze_state": "pre-execution-design-freeze",
        "results_observed_before_freeze": False,
        "identity_profile": IDENTITY_PROFILE,
    }
    for key, expected in expected_scalars.items():
        if manifest[key] != expected:
            raise BenchmarkSpecificationError(f"corpus_manifest.{key} changed")
    _require_timestamp(manifest["frozen_at"], "frozen_at")
    _validate_runtime_gate(manifest["runtime_gate"])

    bindings = _require_mapping(manifest["catalog_bindings"], "catalog_bindings")
    if dict(bindings) != catalog_cids():
        raise BenchmarkSpecificationError("catalog CID bindings do not recompute")
    if manifest["corpus_requirements"] != _CORPUS_REQUIREMENTS:
        raise BenchmarkSpecificationError("corpus requirements changed")
    if manifest["isolation_policy"] != _ISOLATION_POLICY:
        raise BenchmarkSpecificationError("isolation policy changed")
    if manifest["materialization_policy"] != _MATERIALIZATION_POLICY:
        raise BenchmarkSpecificationError("materialization policy changed")
    if manifest["downstream_bindings"] != _DOWNSTREAM_BINDINGS:
        raise BenchmarkSpecificationError("downstream bindings changed")

    pins = manifest["source_pins"]
    if not isinstance(pins, list) or len(pins) != len(REPOSITORY_CLASSES):
        raise BenchmarkSpecificationError("exactly three source pins are required")
    for pin, expected_class in zip(pins, REPOSITORY_CLASSES, strict=True):
        _validate_source_pin(pin, expected_class)
    pin_ids = [pin["pin_id"] for pin in pins]
    if len(pin_ids) != len(set(pin_ids)):
        raise BenchmarkSpecificationError("source pin ids must be unique")
    return _json_clone(manifest)


def corpus_manifest_cid(value: Any) -> str:
    admitted = validate_corpus_manifest(value)
    return structured_cid(admitted)


def validate_threshold_set(
    value: Any,
    *,
    expected_manifest_cid: str,
    expected_schema_catalog_cid: str,
) -> dict[str, Any]:
    thresholds = _require_mapping(value, "threshold_set")
    required = _SCHEMA_CATALOG["schemas"][6]["required_fields"]
    _require_exact_fields(thresholds, required=required, field="threshold_set")
    if thresholds["schema"] != THRESHOLD_SET_SCHEMA:
        raise BenchmarkSpecificationError("threshold schema changed")
    if thresholds["benchmark_id"] != BENCHMARK_ID:
        raise BenchmarkSpecificationError("threshold benchmark id changed")
    if thresholds["corpus_manifest_cid"] != expected_manifest_cid:
        raise BenchmarkSpecificationError("thresholds bind the wrong manifest")
    _require_cid(thresholds["corpus_manifest_cid"], "corpus_manifest_cid")
    if thresholds["schema_catalog_cid"] != expected_schema_catalog_cid:
        raise BenchmarkSpecificationError("thresholds bind the wrong schema catalog")
    _require_cid(thresholds["schema_catalog_cid"], "schema_catalog_cid")
    _require_timestamp(thresholds["frozen_at"], "thresholds.frozen_at")
    if thresholds["freeze_state"] != "pre-execution-preregistered":
        raise BenchmarkSpecificationError("thresholds are not preregistered")
    if _require_bool(
        thresholds["results_observed_before_freeze"],
        "results_observed_before_freeze",
    ):
        raise BenchmarkSpecificationError("thresholds cannot follow observed results")
    for key in ("primary_comparisons", "analysis", "zero_tolerance", "evidence_policy"):
        if thresholds[key] != _THRESHOLD_POLICY[key]:
            raise BenchmarkSpecificationError(f"threshold policy changed: {key}")
    metric_names = {definition["name"] for definition in _METRICS}
    referenced = {rule["metric"] for rule in thresholds["primary_comparisons"].values()}
    if not referenced.issubset(metric_names):
        raise BenchmarkSpecificationError("threshold references an unknown metric")
    if set(thresholds["zero_tolerance"]) - metric_names:
        raise BenchmarkSpecificationError("zero-tolerance metric is unknown")
    return _json_clone(thresholds)


_AGENT_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "answer",
        "answer_bytes",
        "evaluation_data",
        "expected_patch",
        "future_patch",
        "gold_labels",
        "hidden_prompt",
        "hidden_test_bytes",
        "sealed_evaluator_root_cid",
    }
)


def _reject_forbidden_agent_keys(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in _AGENT_FORBIDDEN_KEYS:
                raise BenchmarkSpecificationError(
                    f"agent projection exposes forbidden field {path}.{key}"
                )
            _reject_forbidden_agent_keys(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_forbidden_agent_keys(item, f"{path}[{index}]")


def validate_task_control(value: Any) -> dict[str, Any]:
    task = _require_mapping(value, "task_control")
    _require_exact_fields(task, required=_TASK_CONTROL_FIELDS, field="task_control")
    if task["schema"] != TASK_CONTROL_SCHEMA:
        raise BenchmarkSpecificationError("task control schema changed")
    _require_text(task["task_id"], "task_id")
    _require_cid(task["corpus_manifest_cid"], "corpus_manifest_cid")
    if task["repository_class"] not in REPOSITORY_CLASSES:
        raise BenchmarkSpecificationError("unknown repository class")
    _require_text(task["source_pin_id"], "source_pin_id")
    if task["task_kind"] not in TASK_KINDS:
        raise BenchmarkSpecificationError("unknown task kind")
    _require_git_oid(task["base_commit"], "base_commit")
    _require_git_oid(task["base_tree"], "base_tree")
    _require_cid(task["visible_projection_cid"], "visible_projection_cid")
    _require_cid(task["sealed_evaluator_root_cid"], "sealed_evaluator_root_cid")
    _require_text(task["objective"], "objective")
    for path in _require_string_list(task["owned_paths"], "owned_paths"):
        _require_relative_path(path, "owned_paths[]")
    _require_bool(task["routine_localized"], "routine_localized")
    _require_text(task["risk_class"], "risk_class")
    _require_int(task["seed"], "seed")
    eligible = _require_string_list(task["eligible_configurations"], "eligible_configurations")
    if any(item not in CONFIGURATION_IDS for item in eligible):
        raise BenchmarkSpecificationError("unknown eligible configuration")
    return _json_clone(task)


def project_task_agent_view(value: Any) -> dict[str, Any]:
    task = validate_task_control(value)
    projected = {key: task[key] for key in _TASK_AGENT_FIELDS if key not in {"schema"}}
    projected["schema"] = TASK_AGENT_VIEW_SCHEMA
    ordered = {key: projected[key] for key in _TASK_AGENT_FIELDS}
    return validate_task_agent_view(ordered)


def validate_task_agent_view(value: Any) -> dict[str, Any]:
    task = _require_mapping(value, "task_agent_view")
    _require_exact_fields(task, required=_TASK_AGENT_FIELDS, field="task_agent_view")
    _reject_forbidden_agent_keys(task)
    if task["schema"] != TASK_AGENT_VIEW_SCHEMA:
        raise BenchmarkSpecificationError("agent view schema changed")
    control_projection = dict(task)
    control_projection["schema"] = TASK_CONTROL_SCHEMA
    control_projection["sealed_evaluator_root_cid"] = task["visible_projection_cid"]
    validate_task_control(control_projection)
    return _json_clone(task)


def validate_raw_result(value: Any) -> dict[str, Any]:
    result = _require_mapping(value, "raw_result")
    _require_exact_fields(result, required=_RAW_RESULT_FIELDS, field="raw_result")
    if result["schema"] != RAW_RESULT_SCHEMA:
        raise BenchmarkSpecificationError("raw result schema changed")
    for field in (
        "corpus_manifest_cid",
        "task_record_cid",
        "visible_projection_cid",
        "configuration_cid",
        "repository_state_cid",
        "environment_cid",
    ):
        _require_cid(result[field], field)
    _require_text(result["run_key"], "run_key")
    if result["configuration_id"] not in CONFIGURATION_IDS:
        raise BenchmarkSpecificationError("unknown result configuration")
    for field in ("provider_id", "model_id", "model_revision"):
        _require_text(result[field], field)
    _require_int(result["seed"], "seed")
    _require_int(result["attempt"], "attempt", minimum=1)
    if result["provenance"] not in PROVENANCE_CLASSES:
        raise BenchmarkSpecificationError("unknown result provenance")
    if result["terminal_status"] not in TERMINAL_STATUSES:
        raise BenchmarkSpecificationError("unknown terminal status")

    metrics = _require_mapping(result["metrics"], "metrics")
    definitions = {definition["name"]: definition for definition in _METRICS}
    if set(metrics) != set(definitions):
        raise BenchmarkSpecificationError("raw result metric fields are incomplete")
    missingness = _require_mapping(result["missingness"], "missingness")
    null_names: set[str] = set()
    for name, definition in definitions.items():
        metric_value = metrics[name]
        if metric_value is None:
            null_names.add(name)
            continue
        minimum = None if definition["value_type"] == "signed_basis_points" else 0
        _require_int(metric_value, f"metrics.{name}", minimum=minimum)
        if definition["value_type"] == "basis_points" and metric_value > 10000:
            raise BenchmarkSpecificationError(f"metrics.{name} exceeds 10000 bp")
    if set(missingness) != null_names:
        raise BenchmarkSpecificationError("missingness must name every and only null metric")
    for name, reason in missingness.items():
        _require_text(reason, f"missingness.{name}")
    evidence = _require_string_list(result["evidence_cids"], "evidence_cids", nonempty=False)
    for item in evidence:
        _require_cid(item, "evidence_cids[]")
    return _json_clone(result)


__all__ = [
    "BENCHMARK_ID",
    "BOARD_NAMESPACE",
    "BenchmarkSpecificationError",
    "CONFIGURATION_DIFF_WHITELIST",
    "CONFIGURATION_IDS",
    "CONFIGURATION_SCHEMA",
    "CORPUS_MANIFEST_SCHEMA",
    "FREEZE_TASK_CID",
    "FREEZE_TASK_ID",
    "IDENTITY_PROFILE",
    "METRIC_CATEGORIES",
    "METRIC_DEFINITION_SCHEMA",
    "PROVENANCE_CLASSES",
    "RAW_RESULT_SCHEMA",
    "REPOSITORY_CLASSES",
    "SCHEMA_CATALOG_SCHEMA",
    "TASK_AGENT_VIEW_SCHEMA",
    "TASK_CONTROL_SCHEMA",
    "TASK_KINDS",
    "TERMINAL_STATUSES",
    "THRESHOLD_SET_SCHEMA",
    "catalog_cids",
    "configuration_catalog",
    "configuration_diff",
    "corpus_manifest_cid",
    "corpus_requirements",
    "downstream_bindings",
    "isolation_policy",
    "materialization_policy",
    "metric_catalog",
    "metric_completeness_matrix",
    "project_task_agent_view",
    "raw_bytes_cid",
    "schema_catalog",
    "strict_json_loads",
    "structured_cid",
    "threshold_policy",
    "validate_configuration_catalog",
    "validate_corpus_manifest",
    "validate_metric_catalog",
    "validate_raw_result",
    "validate_task_agent_view",
    "validate_task_control",
    "validate_threshold_set",
]

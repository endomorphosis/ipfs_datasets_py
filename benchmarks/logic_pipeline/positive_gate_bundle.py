"""Source-recomputed positive gate composition for HSSL-G231.

This module joins the independently testable G234--G238 lanes.  Child receipt
CIDs are never accepted as truth: every child validator is called with its
complete source inputs before any CID enters the composite gate map.

The join is intentionally authorization-free.  A complete bundle freezes the
evaluated pilot/development population and the exact public G220 seal identity,
but it neither opens nor authorizes the replacement holdout and it never
authorizes production promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from types import MappingProxyType
from typing import Final, Mapping, Sequence, Self

from .cases import ReplacementHoldoutSeal
from .ablation import AblationPlan, AblationValidationError
from .causal_ablation import (
    CausalAblationError,
    CausalRescueManifestV2,
    build_causal_rescue_manifest_v2,
)
from .causal_runtime import (
    CausalRuntimeEvidenceV2,
    validate_causal_runtime_evidence_v2,
)
from .causal_batch import (
    CausalRuntimeBatchError,
    CausalRuntimeBatchResultV2,
    validate_causal_runtime_batch_v2,
)
from .content_addressing import cid_for_dag_json, validate_cid
from .contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    DEFAULT_PROTOCOL,
    SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2,
    SEMANTIC_PROMPT_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    CacheMode,
    CacheScope,
    Split,
    StageName,
    StageRecord,
)
from .replay_gate import (
    G238_FAILURE_SAMPLE_PER_STRATUM,
    G238_REPLAY_POLICY_V2_CID,
    G238DetachedReplayReceiptV2,
    G238ReplaySourceIndexV2,
    G238ReplaySourceRecordV2,
    G238SemanticObservationV2,
    FreshReplayGateError,
    g238_git_commit_cid,
    validate_g238_detached_replay_gate_v2,
)
from .namespace_provenance import (
    G240PrivateReplayValidationSourcesV2,
    G240RuntimeNamespaceEvidenceSetV2,
    RuntimeNamespaceProvenanceError,
    validate_g240_private_replay_sources_v2,
    validate_g240_runtime_namespace_population_v2,
)
from .resource_statistics import (
    RESOURCE_MEASUREMENT_POLICY_V2_CID,
    RESOURCE_PARETO_FRONTIER_SCHEMA_V2,
    RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID,
    IndependentResourceReceiptV2,
    ResourceStatisticsError,
    validate_independent_resource_receipt_v2,
    validate_resource_statistics_gate_v2,
)
from .reviewed_control import (
    REVIEWED_CONTROL_POLICY_V2_CID,
    ReviewedControlIndexV2,
    ReviewedControlSafetyError,
    validate_reviewed_control_safety_gate_v2,
)
from .revised_pilot_authorization import (
    G210_CACHE_MODES,
    G210_SPLITS,
    G210_VARIANT_IDS,
    G230_GATE_IDS,
    G230_IDENTITY_KEYS,
    G230_SOURCE_FREEZE_SCHEMA,
    G210RuntimeReceiptMatrixV2,
    G230SourceFreezeReceipt,
    RevisedPilotAuthorizationError,
    build_g210_runtime_receipt_matrix_v2,
    validate_g234_efficacy_gate_v2,
    validate_g234_reliability_gate_v2,
    validate_g234_routing_gate_v2,
)
from .semantic_quality import (
    G201SemanticEvidenceIndexV2,
    SemanticQualityError,
    build_g201_semantic_preflight_plan_v2,
    validate_g235_semantic_quality_gate_v2,
)
from .source_orchestration import (
    G240PrivateSourceValidationSourcesV2,
    G240SourceExecutorContractV2,
    G240SourceOrchestrationEvidenceSetV2,
    SourceRuntimeOrchestrationError,
    validate_g240_source_orchestration_evidence_set_v2,
)
from .source_executor import (
    G240SourceExecutorError,
    validate_g240_production_execution_request_v2,
)
from .statistics import StatisticalPlan
from .variants import VARIANT_REGISTRY, get_variant_definition


G202_FROZEN_RUN_INPUTS_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-frozen-run-inputs.v2"
)
G202_EXECUTION_IDENTITIES_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-pre-execution-identities.v2"
)
G202_RUNTIME_IDENTITY_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-pre-execution-runtime-identity-policy.v2"
)
G202_STAGE_IDENTITY_PROJECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-stable-stage-identity-projection.v2"
)
G202_CACHE_POLICY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-cache-namespace-policy.v2"
)
G202_SYMAI_NAMESPACE_PREIMAGE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-symai-cache-namespace-preimage.v2"
)
G202_GATE_POLICY_BUNDLE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-gate-policy-threshold-bundle.v2"
)
G202_G210_INPUT_PLAN_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-g210-input-plan.v2"
)
G202_G210_CASE_INDEX_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-g210-case-index.v2"
)
G202_G210_RESCUE_PLAN_SET_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-g210-rescue-plan-set.v2"
)
G202_RUN_PLAN_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark.g202-run-plan.v2"
)
G202_AUTHORITY_ROLE_MANIFEST_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g202-authority-role-manifest.v2"
)
G202_AUTHORITY_ROLE_KEYS: Final = (
    "source_executor",
    "namespace_authority",
    "namespace_observer",
    "source_orchestration_observer",
    "runtime_namespace_validator",
    "source_orchestration_validator",
    "resource_meter",
    "resource_validator",
    "control_reviewer",
    "replay_executor",
    "replay_namespace_observer",
    "replay_orchestration_observer",
    "freeze_producer",
    "freeze_validator",
    "runtime_identity_policy_authority",
    "artifact_validator",
)
G231_ARTIFACT_BINDINGS_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-source-artifact-bindings.v2"
)
G231_CASE_INDEX_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-pilot-development-case-index.v2"
)
G231_ROUTE_MANIFEST_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-full-route-manifest.v2"
)
G231_SEMANTIC_PLAN_SET_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-semantic-plan-set.v2"
)
G231_RUN_PLAN_SCHEMA_V2: Final = (
    G202_RUN_PLAN_SCHEMA_V2
)
G231_MODEL_IDENTITY_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-runtime-model-identity-set.v2"
)
G231_GATE_SUBSECTION_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-source-derived-gate-subsection.v2"
)
G231_POSITIVE_GATE_BUNDLE_SCHEMA_V2: Final = (
    "ipfs-datasets.logic-pipeline-benchmark."
    "g231-positive-gate-bundle.v2"
)

G231_ARTIFACT_KEYS: Final = (
    "g201_semantic_evidence_index",
    "g210_runtime_matrix",
    "g220_replacement_holdout_seal",
    "g236_reviewed_control_index",
    "g237_resource_evidence_set",
    "g238_replay_source_index",
)
G231_EVALUATED_CANDIDATE_IDS: Final = tuple(
    variant_id
    for variant_id in G210_VARIANT_IDS
    if (
        variant_id != "A0"
        and VARIANT_REGISTRY[variant_id].paired_against == "A0"
        and VARIANT_REGISTRY[variant_id].primary_candidate is True
        and VARIANT_REGISTRY[variant_id].safety_diagnostic_only is False
    )
)
G202_SEMANTIC_QUALITY_POLICY_V2_CID: Final = cid_for_dag_json(
    {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "g202-semantic-quality-policy.v2"
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "prompt_cid": SEMANTIC_PROMPT_V2_CID,
        "absolute_quality_minimum_millionths": (
            SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
        ),
        "nonvacuous_required": True,
        "complete_source_replay_required": True,
    }
)
G202_EFFICACY_EVALUATION_POLICY_V2_CID: Final = cid_for_dag_json(
    {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "g202-efficacy-evaluation-policy.v2"
        ),
        "candidate_variant_ids": list(G231_EVALUATED_CANDIDATE_IDS),
        "baseline_variant_id": "A0",
        "splits": list(G210_SPLITS),
        "cache_modes": list(G210_CACHE_MODES),
        "source_recomputed_pairs": True,
        "performance_threshold_applied": False,
        "shortlist_selection_permitted": False,
    }
)
G202_PARETO_POLICY_V2_CID: Final = cid_for_dag_json(
    {
        "schema": RESOURCE_PARETO_FRONTIER_SCHEMA_V2,
        "safety_is_hard_constraint": True,
        "direction_aware": True,
        "scalarization_permitted": False,
        "efficacy_and_cost_separate": True,
    }
)
def g202_shortlist_selection_policy_v2() -> dict[str, object]:
    """Return the exact pre-outcome policy owned by the G232 join."""

    thresholds = DEFAULT_PROTOCOL.thresholds
    return {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "g202-g232-shortlist-selection-policy.v2"
        ),
        "selection_authority_goal": "HSSL-G232",
        "baseline_variant_id": "A0",
        "candidate_variant_ids": list(
            G231_EVALUATED_CANDIDATE_IDS
        ),
        "semantic_absolute_quality_min_millionths": (
            SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
        ),
        "materiality_thresholds": thresholds.to_dict(),
        "gate_requirements": {
            "efficacy": {
                "paired_regression_floor": thresholds.paired_regression_floor,
                "hard_case_verified_gain_min": (
                    thresholds.hard_case_verified_gain_min
                ),
                "all_pairs_measured": True,
            },
            "reliability": {
                "infrastructure_failure_max": 0,
                "unavailable_or_excluded_max": 0,
                "all_coordinates_terminal": True,
            },
            "semantic_quality": {
                "absolute_quality_min_millionths": (
                    SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
                ),
                "quality_gap_from_best_max": (
                    thresholds.near_best_quality_margin_max
                ),
                "nonvacuous_complete_source_replay": True,
            },
            "cost_resource": {
                "efficiency_reduction_min": (
                    thresholds.efficiency_reduction_min
                ),
                "missing_measurement_max": 0,
                "unsafe_lifecycle_max": 0,
                "measurement_policy_cid": (
                    RESOURCE_MEASUREMENT_POLICY_V2_CID
                ),
                "scalarization_permitted": False,
            },
            "routing": {
                "fallback_or_substitution_max": 0,
                "unequal_compiler_exposure_max": 0,
            },
            "safety": {
                "invalid_control_verified_max": (
                    thresholds.invalid_control_verified_max
                ),
                "baseline_solved_regression_rate_max": (
                    thresholds.baseline_solved_regression_rate_max
                ),
                "unexplained_baseline_regressions_max": (
                    thresholds.unexplained_baseline_regressions_max
                ),
            },
            "replay": {
                "success_population": "all",
                "failure_sample_per_stratum": (
                    G238_FAILURE_SAMPLE_PER_STRATUM
                ),
                "comparison_policy_cid": (
                    RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID
                ),
                "failed_comparison_max": 0,
            },
        },
        "all_absolute_paired_safety_resource_replay_gates_required": (
            True
        ),
        "nondominated_frontier_required": True,
        "candidate_min": 1,
        "candidate_max": (
            thresholds.shortlist_candidate_max
        ),
        "ranking_permitted": False,
        "truncation_permitted": False,
        "producer_reinvocation_permitted": False,
        "g231_selection_permitted": False,
        "holdout_accessed": False,
    }


G202_SHORTLIST_SELECTION_POLICY_V2_CID: Final = cid_for_dag_json(
    g202_shortlist_selection_policy_v2()
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40,64}\Z")
_PYTHON_MODULE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z"
)

_RUNTIME_DERIVED_IDENTITY_KEYS: Final = (
    "variant_id",
    "source_cid",
    "proof_context_cid",
    "compiler_reference_exposure_cid",
    "causal_target_candidate_source",
    "causal_target_candidate_cid",
    "causal_target_candidate_artifact_cid",
    "causal_target_candidate_artifact_sha256",
    "candidate_cid",
    "causal_selection_receipt_cid",
    "consumed_artifact_sha256",
    "cache_key",
    "cache_namespace",
    "semantic_context_cid",
    "graph_invoked",
    "graph_invocation_index",
    "kernel_check_count",
    "policy_reason",
)
_RUNTIME_IDENTITY_LANES: Final = ("primary", "reviewed_control")
_EXPECTED_STAGE_IDENTITY_BASE_COORDINATES: Final = tuple(
    sorted(
        {
            f"{variant_id}:{stage.value}"
            for variant_id in G210_VARIANT_IDS
            for stage in (
                *get_variant_definition(variant_id).stages,
                StageName.KERNEL,
            )
        }
    )
)


class PositiveGateBundleError(ValueError):
    """Raised when a G231 source or child gate cannot be recomputed."""


def HSSLEV2312F74() -> str:
    """Return AST-verifiable evidence for the bounded G231 implementation."""

    return (
        "source-recomputed positive gate bundle with complete live-source "
        "and detached-replay joins"
    )


def _plain(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise PositiveGateBundleError(
                "G231 DAG-JSON objects require string keys"
            )
        return {
            str(key): _plain(member)
            for key, member in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_plain(member) for member in value]
    if value is None or type(value) in {str, bool, int, float}:
        return value
    raise PositiveGateBundleError(
        f"G231 value is not DAG-JSON: {type(value).__name__}"
    )


def _freeze(value: object) -> object:
    plain = _plain(value)
    if isinstance(plain, dict):
        return MappingProxyType(
            {
                key: _freeze(member)
                for key, member in sorted(plain.items())
            }
        )
    if isinstance(plain, list):
        return tuple(_freeze(member) for member in plain)
    return plain


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise PositiveGateBundleError(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> tuple[object, ...]:
    if (
        isinstance(value, (str, bytes, bytearray, Mapping))
        or not isinstance(value, Sequence)
    ):
        raise PositiveGateBundleError(f"{field} must be an array")
    return tuple(value)


def _exact(
    value: Mapping[str, object],
    expected: set[str],
    field: str,
) -> None:
    if set(value) != expected:
        raise PositiveGateBundleError(
            f"{field} fields changed: "
            f"missing={sorted(expected - set(value))}, "
            f"extra={sorted(set(value) - expected)}"
        )


def _cid(value: object, field: str) -> str:
    try:
        return validate_cid(value, codecs=("dag-json",))
    except (TypeError, ValueError) as exc:
        raise PositiveGateBundleError(
            f"{field} must be a canonical DAG-JSON CIDv1"
        ) from exc


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise PositiveGateBundleError(
            f"{field} must be a safe nonempty identifier"
        )
    return value


def _sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise PositiveGateBundleError(
            f"{field} must be a lowercase SHA-256 digest"
        )
    return value


def _git_commit(value: object, field: str) -> str:
    if not isinstance(value, str) or not _GIT_COMMIT.fullmatch(value):
        raise PositiveGateBundleError(
            f"{field} must be a lowercase Git object identity"
        )
    return value


def _candidate_ids(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise PositiveGateBundleError(
            "candidate_variant_ids must be an array"
        )
    candidates = tuple(value)
    if candidates != G231_EVALUATED_CANDIDATE_IDS:
        raise PositiveGateBundleError(
            "G231 must evaluate the exact complete preregistered primary "
            "A1--A12 population; G232 alone may derive a shortlist"
        )
    for candidate in candidates:
        profile = VARIANT_REGISTRY.get(candidate)
        if (
            profile is None
            or candidate in {"A0", "S1"}
            or profile.primary_candidate is not True
            or profile.paired_against != "A0"
            or profile.safety_diagnostic_only is True
        ):
            raise PositiveGateBundleError(
                "G231 candidates must be primary A0-paired arms"
            )
    return candidates


def build_g202_g201_input_plan_v2(
    *,
    target_manifest: Mapping[str, object],
    targets: Sequence[object],
    plans: Sequence[AblationPlan],
) -> Mapping[str, object]:
    """Build the source-only G201 plan frozen by G202.

    The accepted signature intentionally has no result or evidence-index
    parameter.  Full target/plan validation belongs to the G201 boundary; this
    wrapper only normalizes its errors for the composite preflight API.
    """

    try:
        return build_g201_semantic_preflight_plan_v2(
            target_manifest=target_manifest,
            targets=targets,  # type: ignore[arg-type]
            plans=plans,
        )
    except (
        SemanticQualityError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G202 could not build the source-only G201 preflight plan"
        ) from exc


def g231_semantic_plan_set_cid_v2(
    index: G201SemanticEvidenceIndexV2,
) -> str:
    """Recompute the frozen G201 input CID from complete post-run evidence."""

    if not isinstance(index, G201SemanticEvidenceIndexV2):
        raise PositiveGateBundleError(
            "semantic plan set requires G201SemanticEvidenceIndexV2"
        )
    preflight = build_g202_g201_input_plan_v2(
        target_manifest=index.target_manifest,
        targets=index.targets,
        plans=index.plans,
    )
    return _cid(
        preflight["preflight_plan_cid"],
        "G201 preflight_plan_cid",
    )


def build_g202_g210_input_plan_v2(
    *,
    run_id: str,
    plans: Sequence[AblationPlan],
    rescue_manifests: Sequence[CausalRescueManifestV2],
    legacy_environment_sha256: str,
    environment_cid: str,
) -> Mapping[str, object]:
    """Address source-only G210 cases and rescue plans before execution."""

    normalized_run_id = _safe_id(run_id, "run_id")
    normalized_environment_sha256 = _sha256(
        legacy_environment_sha256,
        "legacy_environment_sha256",
    )
    normalized_environment_cid = _cid(
        environment_cid,
        "environment_cid",
    )
    try:
        parsed_plans = tuple(
            sorted(
                (
                    AblationPlan.from_dict(_plain(item.to_dict()))
                    for item in plans
                ),
                key=lambda item: (
                    item.split.value,
                    cid_for_dag_json(_plain(item.to_dict())),
                ),
            )
        )
        manifests = tuple(
            sorted(
                (
                    CausalRescueManifestV2.from_dict(item.to_dict())
                    for item in rescue_manifests
                ),
                key=lambda item: (
                    item.cases[0].split.value,
                    item.manifest_cid,
                ),
            )
        )
    except (
        AblationValidationError,
        CausalAblationError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G202 G210 rescue sources failed canonical replay"
        ) from exc
    plan_by_cid = {
        cid_for_dag_json(_plain(plan.to_dict())): plan
        for plan in parsed_plans
    }
    manifest_split_sets = tuple(
        {case.split.value for case in item.cases}
        for item in manifests
    )
    if (
        not manifests
        or len(manifests) != len(G210_SPLITS)
        or len(parsed_plans) != len(manifests)
        or len(plan_by_cid) != len(parsed_plans)
        or set(plan_by_cid)
        != {item.plan_cid for item in manifests}
        or any(len(splits) != 1 for splits in manifest_split_sets)
        or {
            next(iter(splits))
            for splits in manifest_split_sets
        }
        != set(G210_SPLITS)
        or {case.split.value for item in manifests for case in item.cases}
        != set(G210_SPLITS)
        or len({item.manifest_cid for item in manifests})
        != len(manifests)
        or len({item.plan_cid for item in manifests}) != len(manifests)
        or len({item.source_manifest_cid for item in manifests})
        != len(manifests)
        or len({item.case_manifest_sha256 for item in manifests}) != 1
    ):
        raise PositiveGateBundleError(
            "G202 G210 input plan requires unique pilot/development rescue "
            "plans over one frozen case manifest"
        )
    for manifest in manifests:
        plan = plan_by_cid[manifest.plan_cid]
        try:
            rebuilt = build_causal_rescue_manifest_v2(
                plan,
                manifest.cases,
            )
        except (
            AblationValidationError,
            CausalAblationError,
            TypeError,
            ValueError,
        ) as exc:
            raise PositiveGateBundleError(
                "G202 G210 rescue manifest does not derive from its "
                "source-only AblationPlan"
            ) from exc
        if (
            rebuilt.to_dict() != manifest.to_dict()
            or plan.run_id != normalized_run_id
            or plan.environment_sha256
            != normalized_environment_sha256
            or tuple(plan.variant_ids) != tuple(G210_VARIANT_IDS)
            or tuple(mode.value for mode in plan.cache_modes)
            != tuple(G210_CACHE_MODES)
            or plan.holdout_access_log_id is not None
        ):
            raise PositiveGateBundleError(
                "G202 G210 plan/rescue/run identity changed before execution"
            )
    rows: list[dict[str, object]] = []
    coordinates: set[tuple[str, str]] = set()
    for manifest in manifests:
        for case in manifest.cases:
            coordinate = (case.split.value, case.case_id)
            if coordinate in coordinates:
                raise PositiveGateBundleError(
                    "G202 G210 input plan contains a duplicate case coordinate"
                )
            coordinates.add(coordinate)
            rows.append(
                {
                    "case_id": case.case_id,
                    "split": case.split.value,
                    "source_cid": case.source_cid,
                    "proof_context_cid": cid_for_dag_json(
                        _plain(case.proof_context)
                    ),
                    "case_cid": case.case_cid,
                    "plan_cid": manifest.plan_cid,
                    "source_manifest_cid": manifest.source_manifest_cid,
                    "rescue_manifest_cid": manifest.manifest_cid,
                }
            )
    rows.sort(
        key=lambda item: (
            str(item["split"]),
            str(item["case_id"]),
        )
    )
    case_body = {
        "schema": G202_G210_CASE_INDEX_SCHEMA_V2,
        "splits": list(G210_SPLITS),
        "cases": rows,
        "case_count": len(rows),
        "holdout_included": False,
    }
    rescue_body = {
        "schema": G202_G210_RESCUE_PLAN_SET_SCHEMA_V2,
        "run_id": normalized_run_id,
        "legacy_environment_sha256": normalized_environment_sha256,
        "environment_cid": normalized_environment_cid,
        "case_manifest_sha256": manifests[0].case_manifest_sha256,
        "plans": [
            {
                "plan_cid": item.plan_cid,
                "plan_source_cid": cid_for_dag_json(
                    _plain(plan_by_cid[item.plan_cid].to_dict())
                ),
                "source_manifest_cid": item.source_manifest_cid,
                "rescue_manifest_cid": item.manifest_cid,
                "case_cids": [case.case_cid for case in item.cases],
                "splits": sorted(
                    {case.split.value for case in item.cases}
                ),
            }
            for item in manifests
        ],
        "holdout_included": False,
    }
    body = {
        "schema": G202_G210_INPUT_PLAN_SCHEMA_V2,
        "run_id": normalized_run_id,
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
        "legacy_environment_sha256": normalized_environment_sha256,
        "environment_cid": normalized_environment_cid,
        "case_index_cid": cid_for_dag_json(case_body),
        "rescue_plan_set_cid": cid_for_dag_json(rescue_body),
        "result_count": 0,
        "runtime_matrix_accepted": False,
        "source_only": True,
        "holdout_included": False,
        "holdout_accessed": False,
    }
    result = {**body, "input_plan_cid": cid_for_dag_json(body)}
    frozen = _freeze(result)
    assert isinstance(frozen, Mapping)
    return frozen


def g231_case_index_cid_v2(
    matrix: G210RuntimeReceiptMatrixV2,
) -> str:
    """Derive the exact non-holdout case/source index from G210 manifests."""

    if not isinstance(matrix, G210RuntimeReceiptMatrixV2):
        raise PositiveGateBundleError(
            "case index requires G210RuntimeReceiptMatrixV2"
        )
    rows: list[dict[str, object]] = []
    for manifest in matrix.receipt_matrix.rescue_manifests:
        for case in manifest.cases:
            rows.append(
                {
                    "case_id": case.case_id,
                    "split": case.split.value,
                    "source_cid": case.source_cid,
                    "proof_context_cid": cid_for_dag_json(
                        _plain(case.proof_context)
                    ),
                    "source_manifest_cid": manifest.source_manifest_cid,
                    "rescue_manifest_cid": manifest.manifest_cid,
                }
            )
    rows.sort(
        key=lambda item: (
            str(item["split"]),
            str(item["case_id"]),
        )
    )
    body = {
        "schema": G231_CASE_INDEX_SCHEMA_V2,
        "splits": list(G210_SPLITS),
        "cases": rows,
        "case_count": len(rows),
        "holdout_included": False,
    }
    return cid_for_dag_json(body)


def g231_route_manifest_cid_v2() -> str:
    """Address every frozen A0--A12 route used by the full source matrix."""

    body = {
        "schema": G231_ROUTE_MANIFEST_SCHEMA_V2,
        "variant_ids": list(G210_VARIANT_IDS),
        "variant_profile_cids": {
            variant_id: cid_for_dag_json(
                _plain(VARIANT_REGISTRY[variant_id].to_dict())
            )
            for variant_id in G210_VARIANT_IDS
        },
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
    }
    return cid_for_dag_json(body)


def g202_run_plan_cid_v2(
    *,
    run_id: str,
    semantic_plan_set_cid: str,
    g210_input_plan_cid: str,
    g210_rescue_plan_set_cid: str,
    case_index_cid: str,
    route_manifest_cid: str,
    capability_inventory_cid: str,
    environment_cid: str,
    statistical_plan_cid: str,
    reviewed_control_index_cid: str,
    gate_policy_bundle_cid: str,
    cache_policy_cid: str,
    runtime_orchestration_policy_cid: str,
) -> str:
    """Address the immutable G201/G212 non-holdout execution plan."""

    body = {
        "schema": G202_RUN_PLAN_SCHEMA_V2,
        "run_id": _safe_id(run_id, "run_id"),
        "semantic_plan_set_cid": _cid(
            semantic_plan_set_cid, "semantic_plan_set_cid"
        ),
        "g210_input_plan_cid": _cid(
            g210_input_plan_cid,
            "g210_input_plan_cid",
        ),
        "g210_rescue_plan_set_cid": _cid(
            g210_rescue_plan_set_cid,
            "g210_rescue_plan_set_cid",
        ),
        "case_index_cid": _cid(case_index_cid, "case_index_cid"),
        "route_manifest_cid": _cid(
            route_manifest_cid, "route_manifest_cid"
        ),
        "capability_inventory_cid": _cid(
            capability_inventory_cid,
            "capability_inventory_cid",
        ),
        "environment_cid": _cid(environment_cid, "environment_cid"),
        "statistical_plan_cid": _cid(
            statistical_plan_cid, "statistical_plan_cid"
        ),
        "reviewed_control_index_cid": _cid(
            reviewed_control_index_cid,
            "reviewed_control_index_cid",
        ),
        "gate_policy_bundle_cid": _cid(
            gate_policy_bundle_cid,
            "gate_policy_bundle_cid",
        ),
        "cache_policy_cid": _cid(
            cache_policy_cid,
            "cache_policy_cid",
        ),
        "runtime_orchestration_policy_cid": _cid(
            runtime_orchestration_policy_cid,
            "runtime_orchestration_policy_cid",
        ),
        "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
        "causal_proof_protocol_cid": CAUSAL_PROOF_PROTOCOL_V2_CID,
        "splits": list(G210_SPLITS),
        "cache_modes": list(G210_CACHE_MODES),
        "variant_ids": list(G210_VARIANT_IDS),
        "holdout_included": False,
    }
    return cid_for_dag_json(body)


def g231_run_plan_cid_v2(**inputs: object) -> str:
    """Compatibility name for the source-only G202 run-plan builder."""

    return g202_run_plan_cid_v2(**inputs)  # type: ignore[arg-type]


def build_g231_observed_runtime_model_identity_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    *,
    environment_cid: str,
) -> Mapping[str, object]:
    """Derive disambiguated frontend and terminal runtime identities."""

    if not isinstance(matrix, G210RuntimeReceiptMatrixV2):
        raise PositiveGateBundleError(
            "model identity requires G210RuntimeReceiptMatrixV2"
        )
    normalized_environment_cid = _cid(
        environment_cid,
        "environment_cid",
    )
    rows: list[dict[str, object]] = []
    for evidence in matrix.runtime_evidence:
        result = evidence.case_result
        for record_set, stages in (
            ("semantic_frontend", evidence.semantic_frontend),
            ("case_result", result.stages),
        ):
            for stage_index, stage in enumerate(stages):
                coordinate = (
                    f"{result.split.value}:{result.case_id}:"
                    f"{result.cache_mode.value}:{result.variant_id}:"
                    f"{record_set}:{stage_index}:{stage.stage.value}"
                )
                rows.append(
                    {
                        "coordinate": coordinate,
                        "runtime_evidence_cid": evidence.receipt_cid,
                        "split": result.split.value,
                        "case_id": result.case_id,
                        "cache_mode": result.cache_mode.value,
                        "variant_id": result.variant_id,
                        "record_set": record_set,
                        "stage_index": stage_index,
                        "stage": stage.stage.value,
                        "adapter_id": stage.provenance.adapter_id,
                        "adapter_version": stage.adapter_version,
                        "adapter_module": (
                            stage.provenance.source[0]
                        ),
                        "source_provenance": list(
                            stage.provenance.source
                        ),
                        "legacy_environment_sha256": (
                            stage.provenance.environment_sha256
                        ),
                        "environment_cid": normalized_environment_cid,
                        "preflight_identity_cid": (
                            g202_stage_identity_cid_v2(
                                stage,
                                environment_cid=(
                                    normalized_environment_cid
                                ),
                            )
                        ),
                        "requested_identity": _plain(
                            stage.provenance.requested_identity
                        ),
                        "effective_identity": _plain(
                            stage.provenance.effective_identity
                        ),
                    }
                )
    rows.sort(
        key=lambda item: (
            str(item["split"]),
            str(item["case_id"]),
            str(item["cache_mode"]),
            str(item["variant_id"]),
            str(item["record_set"]),
            int(item["stage_index"]),
            str(item["stage"]),
        )
    )
    body = {
        "schema": G231_MODEL_IDENTITY_SCHEMA_V2,
        "runtime_matrix_cid": matrix.runtime_matrix_cid,
        "environment_cid": normalized_environment_cid,
        "semantic_frontend_included": True,
        "coordinate_disambiguation_required": True,
        "stage_identities": rows,
    }
    result = {**body, "identity_cid": cid_for_dag_json(body)}
    frozen = _freeze(result)
    assert isinstance(frozen, Mapping)
    return frozen


def g231_model_identity_cid_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    *,
    environment_cid: str,
) -> str:
    """Return the CID of the complete observed model-identity population."""

    result = build_g231_observed_runtime_model_identity_v2(
        matrix,
        environment_cid=environment_cid,
    )
    return _cid(result["identity_cid"], "identity_cid")


def _g202_symai_namespace(
    *,
    run_id: str,
    legacy_protocol_sha256: str,
    variant_id: str,
    split: str,
    cache_mode: str,
) -> str:
    scope = CacheScope(
        run_id=run_id,
        protocol_sha256=legacy_protocol_sha256,
        variant_id=variant_id,
        split=Split(split),
        mode=CacheMode(cache_mode),
    )
    return (
        f"{scope.namespace}/semantic-protocol/"
        f"{SEMANTIC_PROTOCOL_V2_CID}"
    )


@dataclass(frozen=True, slots=True)
class G202CachePolicyV2:
    """Pre-run logical cache namespaces plus unresolved physical roots."""

    run_id: str
    legacy_protocol_sha256: str
    physical_namespace_cids: Mapping[str, str]
    cross_mode_reuse: bool = False
    physical_binding_verified: bool = False
    schema: str = G202_CACHE_POLICY_SCHEMA_V2
    policy_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G202_CACHE_POLICY_SCHEMA_V2:
            raise PositiveGateBundleError(
                "unsupported G202 cache-policy schema"
            )
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        object.__setattr__(
            self,
            "legacy_protocol_sha256",
            _sha256(
                self.legacy_protocol_sha256,
                "legacy_protocol_sha256",
            ),
        )
        roots = _mapping(
            self.physical_namespace_cids,
            "physical_namespace_cids",
        )
        if set(roots) != set(G210_CACHE_MODES):
            raise PositiveGateBundleError(
                "cache policy requires exact cold/warm physical roots"
            )
        normalized = {
            mode: _cid(
                roots[mode],
                f"physical_namespace_cids.{mode}",
            )
            for mode in G210_CACHE_MODES
        }
        if len(set(normalized.values())) != len(normalized):
            raise PositiveGateBundleError(
                "cold/warm physical cache roots must be distinct"
            )
        object.__setattr__(
            self,
            "physical_namespace_cids",
            MappingProxyType(normalized),
        )
        if (
            self.cross_mode_reuse is not False
            or self.physical_binding_verified is not False
        ):
            raise PositiveGateBundleError(
                "G202 cache policy cannot claim unreceipted physical "
                "namespace reuse or verification"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.policy_cid is None:
            object.__setattr__(self, "policy_cid", expected)
        elif _cid(self.policy_cid, "policy_cid") != expected:
            raise PositiveGateBundleError(
                "G202 cache-policy CID changed"
            )

    @property
    def namespace_preimage_cids(self) -> Mapping[str, str]:
        result = {}
        for split in G210_SPLITS:
            for cache_mode in G210_CACHE_MODES:
                for variant_id in G210_VARIANT_IDS:
                    if (
                        StageName.SYMAI
                        not in get_variant_definition(variant_id).stages
                    ):
                        continue
                    coordinate = f"{split}:{cache_mode}:{variant_id}"
                    namespace = _g202_symai_namespace(
                        run_id=self.run_id,
                        legacy_protocol_sha256=(
                            self.legacy_protocol_sha256
                        ),
                        variant_id=variant_id,
                        split=split,
                        cache_mode=cache_mode,
                    )
                    result[coordinate] = cid_for_dag_json(
                        {
                            "schema": (
                                G202_SYMAI_NAMESPACE_PREIMAGE_SCHEMA_V2
                            ),
                            "coordinate": coordinate,
                            "namespace": namespace,
                        }
                    )
        return MappingProxyType(result)

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "legacy_protocol_sha256": self.legacy_protocol_sha256,
            "semantic_protocol_cid": SEMANTIC_PROTOCOL_V2_CID,
            "physical_namespace_cids": dict(
                self.physical_namespace_cids
            ),
            "namespace_preimage_cids": dict(
                self.namespace_preimage_cids
            ),
            "cross_mode_reuse": self.cross_mode_reuse,
            "physical_binding_verified": self.physical_binding_verified,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "policy_cid": self.policy_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G202 cache policy")
        expected = {
            "schema",
            "run_id",
            "legacy_protocol_sha256",
            "semantic_protocol_cid",
            "physical_namespace_cids",
            "namespace_preimage_cids",
            "cross_mode_reuse",
            "physical_binding_verified",
            "policy_cid",
        }
        _exact(data, expected, "G202 cache policy")
        if data["semantic_protocol_cid"] != SEMANTIC_PROTOCOL_V2_CID:
            raise PositiveGateBundleError(
                "G202 cache semantic protocol changed"
            )
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            run_id=data["run_id"],  # type: ignore[arg-type]
            legacy_protocol_sha256=data[
                "legacy_protocol_sha256"
            ],  # type: ignore[arg-type]
            physical_namespace_cids=_mapping(
                data["physical_namespace_cids"],
                "physical_namespace_cids",
            ),  # type: ignore[arg-type]
            cross_mode_reuse=data[
                "cross_mode_reuse"
            ],  # type: ignore[arg-type]
            physical_binding_verified=data[
                "physical_binding_verified"
            ],  # type: ignore[arg-type]
            policy_cid=data["policy_cid"],  # type: ignore[arg-type]
        )
        if _plain(data["namespace_preimage_cids"]) != _plain(
            result.namespace_preimage_cids
        ):
            raise PositiveGateBundleError(
                "G202 cache namespace preimages changed"
            )
        return result


@dataclass(frozen=True, slots=True)
class G202GatePolicyBundleV2:
    """Preregistered gate policies and thresholds, never result CIDs."""

    reviewed_control_index_cid: str
    statistical_plan_cid: str
    component_policy_cids: Mapping[str, str]
    candidate_variant_ids: tuple[str, ...] = (
        G231_EVALUATED_CANDIDATE_IDS
    )
    frozen: bool = True
    schema: str = G202_GATE_POLICY_BUNDLE_SCHEMA_V2
    bundle_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G202_GATE_POLICY_BUNDLE_SCHEMA_V2:
            raise PositiveGateBundleError(
                "unsupported G202 gate-policy schema"
            )
        for field in (
            "reviewed_control_index_cid",
            "statistical_plan_cid",
        ):
            object.__setattr__(
                self,
                field,
                _cid(getattr(self, field), field),
            )
        policies = _mapping(
            self.component_policy_cids,
            "component_policy_cids",
        )
        expected = {
            "semantic_quality",
            "efficacy_evaluation",
            "shortlist_selection",
            "reviewed_control_safety",
            "resource_measurement",
            "pareto",
            "detached_replay",
            "resource_replay_tolerance",
        }
        if set(policies) != expected:
            raise PositiveGateBundleError(
                "G202 gate-policy component set changed"
            )
        normalized = {
            key: _cid(policies[key], f"component_policy_cids.{key}")
            for key in sorted(expected)
        }
        required = {
            "semantic_quality": G202_SEMANTIC_QUALITY_POLICY_V2_CID,
            "efficacy_evaluation": (
                G202_EFFICACY_EVALUATION_POLICY_V2_CID
            ),
            "shortlist_selection": (
                G202_SHORTLIST_SELECTION_POLICY_V2_CID
            ),
            "reviewed_control_safety": REVIEWED_CONTROL_POLICY_V2_CID,
            "resource_measurement": RESOURCE_MEASUREMENT_POLICY_V2_CID,
            "pareto": G202_PARETO_POLICY_V2_CID,
            "detached_replay": G238_REPLAY_POLICY_V2_CID,
            "resource_replay_tolerance": (
                RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID
            ),
        }
        if any(normalized[key] != value for key, value in required.items()):
            raise PositiveGateBundleError(
                "G202 gate-policy identity changed"
            )
        object.__setattr__(
            self,
            "component_policy_cids",
            MappingProxyType(normalized),
        )
        candidates = tuple(self.candidate_variant_ids)
        if candidates != G231_EVALUATED_CANDIDATE_IDS:
            raise PositiveGateBundleError(
                "G202 gate policy must preregister every A1--A12 arm"
            )
        object.__setattr__(self, "candidate_variant_ids", candidates)
        if self.frozen is not True:
            raise PositiveGateBundleError(
                "G202 gate-policy bundle must be frozen"
            )
        expected_cid = cid_for_dag_json(self.identity_payload())
        if self.bundle_cid is None:
            object.__setattr__(self, "bundle_cid", expected_cid)
        elif _cid(self.bundle_cid, "bundle_cid") != expected_cid:
            raise PositiveGateBundleError(
                "G202 gate-policy bundle CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "reviewed_control_index_cid": (
                self.reviewed_control_index_cid
            ),
            "statistical_plan_cid": self.statistical_plan_cid,
            "component_policy_cids": dict(self.component_policy_cids),
            "candidate_variant_ids": list(self.candidate_variant_ids),
            "thresholds": {
                "semantic_absolute_quality_min_millionths": (
                    SEMANTIC_ABSOLUTE_QUALITY_MIN_MILLIONTHS_V2
                ),
                "materiality": DEFAULT_PROTOCOL.thresholds.to_dict(),
                "invalid_control_kernel_acceptance_maximum": 0,
                "replay_failure_sample_per_stratum": (
                    G238_FAILURE_SAMPLE_PER_STRATUM
                ),
                "resource_missing_values_permitted": False,
                "safety_scalarization_permitted": False,
            },
            "selection_policy_cid": (
                G202_SHORTLIST_SELECTION_POLICY_V2_CID
            ),
            "selection_authority_goal": "HSSL-G232",
            "g231_shortlist_selection_permitted": False,
            "frozen": self.frozen,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "bundle_cid": self.bundle_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G202 gate-policy bundle")
        expected = {
            "schema",
            "reviewed_control_index_cid",
            "statistical_plan_cid",
            "component_policy_cids",
            "candidate_variant_ids",
            "thresholds",
            "selection_policy_cid",
            "selection_authority_goal",
            "g231_shortlist_selection_permitted",
            "frozen",
            "bundle_cid",
        }
        _exact(data, expected, "G202 gate-policy bundle")
        result = cls(
            schema=data["schema"],  # type: ignore[arg-type]
            reviewed_control_index_cid=data[
                "reviewed_control_index_cid"
            ],  # type: ignore[arg-type]
            statistical_plan_cid=data[
                "statistical_plan_cid"
            ],  # type: ignore[arg-type]
            component_policy_cids=_mapping(
                data["component_policy_cids"],
                "component_policy_cids",
            ),  # type: ignore[arg-type]
            candidate_variant_ids=tuple(
                str(item)
                for item in _array(
                    data["candidate_variant_ids"],
                    "candidate_variant_ids",
                )
            ),
            frozen=data["frozen"],  # type: ignore[arg-type]
            bundle_cid=data["bundle_cid"],  # type: ignore[arg-type]
        )
        if _plain(data) != result.to_dict():
            raise PositiveGateBundleError(
                "G202 gate-policy thresholds or derived fields changed"
            )
        return result


def g202_stage_identity_coordinate_v2(
    *,
    lane: str,
    split: str,
    case_id: str,
    cache_mode: str,
    variant_id: str,
    stage: StageName,
) -> str:
    """Return one unambiguous planned runtime-stage coordinate."""

    if lane not in _RUNTIME_IDENTITY_LANES:
        raise PositiveGateBundleError(
            "runtime identity lane is unsupported"
        )
    if split not in G210_SPLITS:
        raise PositiveGateBundleError(
            "runtime identity split is unsupported"
        )
    if cache_mode not in G210_CACHE_MODES:
        raise PositiveGateBundleError(
            "runtime identity cache mode is unsupported"
        )
    normalized_case_id = _safe_id(case_id, "case_id")
    normalized_variant = _safe_id(variant_id, "variant_id")
    if normalized_variant not in G210_VARIANT_IDS:
        raise PositiveGateBundleError(
            "runtime identity variant is outside A0--A12"
        )
    if not isinstance(stage, StageName):
        raise PositiveGateBundleError(
            "runtime identity stage must be a StageName"
        )
    return (
        f"{lane}:{split}:{normalized_case_id}:{cache_mode}:"
        f"{normalized_variant}:{stage.value}"
    )


def _parse_g202_stage_identity_coordinate_v2(
    value: object,
) -> tuple[str, str, str, str, str, str]:
    if not isinstance(value, str):
        raise PositiveGateBundleError(
            "runtime stage identity coordinate must be a string"
        )
    parts = tuple(value.split(":"))
    if len(parts) != 6:
        raise PositiveGateBundleError(
            "runtime stage identity coordinate is not fully disambiguated"
        )
    lane, split, case_id, cache_mode, variant_id, stage_value = parts
    try:
        stage = StageName(stage_value)
    except ValueError as exc:
        raise PositiveGateBundleError(
            "runtime stage identity coordinate has an unsupported stage"
        ) from exc
    expected = g202_stage_identity_coordinate_v2(
        lane=lane,
        split=split,
        case_id=case_id,
        cache_mode=cache_mode,
        variant_id=variant_id,
        stage=stage,
    )
    if expected != value:
        raise PositiveGateBundleError(
            "runtime stage identity coordinate is not canonical"
        )
    return parts  # type: ignore[return-value]


def g202_stage_identity_input_cid_v2(
    *,
    variant_id: str,
    stage: StageName,
    adapter_id: str,
    adapter_version: str,
    adapter_module: str,
    source_provenance: Sequence[str],
    requested_identity: Mapping[str, object],
    effective_identity: Mapping[str, object],
    legacy_environment_sha256: str,
    environment_cid: str,
) -> str:
    """Build one stable stage identity entirely from pre-execution inputs.

    ``StageProvenance.source`` appends request-scoped runtime tokens after the
    adapter's primary source module.  Only the canonical first adapter source
    is eligible for this preflight projection; the complete observed source
    tuple remains bound by the post-run model-identity receipt.
    """

    normalized_variant = _safe_id(variant_id, "variant_id")
    if normalized_variant not in G210_VARIANT_IDS:
        raise PositiveGateBundleError(
            "stage identity variant is outside A0--A12"
        )
    if not isinstance(stage, StageName):
        raise PositiveGateBundleError(
            "stage identity stage must be a StageName"
        )
    normalized_adapter_id = _safe_id(adapter_id, "adapter_id")
    normalized_adapter_version = _safe_id(
        adapter_version,
        "adapter_version",
    )
    if (
        not isinstance(adapter_module, str)
        or not _PYTHON_MODULE.fullmatch(adapter_module)
    ):
        raise PositiveGateBundleError(
            "adapter_module must be one canonical dotted Python name"
        )
    if isinstance(source_provenance, (str, bytes, bytearray)):
        raise PositiveGateBundleError(
            "source_provenance must be an array"
        )
    sources = tuple(source_provenance)
    if (
        not sources
        or sources[0] != adapter_module
        or any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > 256
            for item in sources
        )
    ):
        raise PositiveGateBundleError(
            "source_provenance must start with its canonical adapter module"
        )
    requested = _mapping(requested_identity, "stage requested_identity")
    effective = _mapping(effective_identity, "stage effective_identity")
    variant_id = requested.get("variant_id")
    if (
        not isinstance(variant_id, str)
        or variant_id not in G210_VARIANT_IDS
        or variant_id != normalized_variant
        or (
            effective.get("variant_id") is not None
            and effective.get("variant_id") != variant_id
        )
    ):
        raise PositiveGateBundleError(
            "stage requested/effective variant identity changed"
        )
    stable_requested = {
        key: _plain(value)
        for key, value in requested.items()
        if key not in _RUNTIME_DERIVED_IDENTITY_KEYS
    }
    stable_effective = {
        key: _plain(value)
        for key, value in effective.items()
        if key not in _RUNTIME_DERIVED_IDENTITY_KEYS
    }
    source_body = {
        "schema": (
            "ipfs-datasets.logic-pipeline-benchmark."
            "g202-adapter-source-provenance.v2"
        ),
        "adapter_module": adapter_module,
        "canonical_adapter_source": adapter_module,
        "runtime_request_source_tail_excluded": True,
    }
    body = {
        "schema": G202_STAGE_IDENTITY_PROJECTION_SCHEMA_V2,
        "variant_id": normalized_variant,
        "stage": stage.value,
        "adapter_id": normalized_adapter_id,
        "adapter_version": normalized_adapter_version,
        "adapter_module": adapter_module,
        "canonical_source_provenance": [adapter_module],
        "source_provenance_cid": cid_for_dag_json(source_body),
        "legacy_environment_sha256": _sha256(
            legacy_environment_sha256,
            "legacy_environment_sha256",
        ),
        "environment_cid": _cid(environment_cid, "environment_cid"),
        "requested_identity": stable_requested,
        "effective_identity": stable_effective,
    }
    if (
        "configuration_sha256" not in body["requested_identity"]
        or not body["effective_identity"]
    ):
        raise PositiveGateBundleError(
            "stage lacks a stable preflight identity projection"
        )
    return cid_for_dag_json(body)


def g202_stage_identity_cid_v2(
    stage: StageRecord,
    *,
    environment_cid: str,
) -> str:
    """Project an observed stage onto the exact G202 input identity."""

    if not isinstance(stage, StageRecord):
        raise PositiveGateBundleError(
            "stage identity projection requires StageRecord"
        )
    provenance = stage.provenance
    if provenance.environment_sha256 is None:
        raise PositiveGateBundleError(
            "observed stage lacks its preflight environment SHA"
        )
    return g202_stage_identity_input_cid_v2(
        variant_id=stage.variant_id,
        stage=stage.stage,
        adapter_id=provenance.adapter_id,
        adapter_version=stage.adapter_version,
        adapter_module=provenance.source[0],
        source_provenance=provenance.source,
        requested_identity=provenance.requested_identity,
        effective_identity=provenance.effective_identity,
        legacy_environment_sha256=provenance.environment_sha256,
        environment_cid=environment_cid,
    )


@dataclass(frozen=True, slots=True)
class G202RuntimeIdentityPolicyV2:
    """Frozen allowlist for stable per-variant/stage runtime identities."""

    capability_inventory_cid: str
    environment_cid: str
    legacy_environment_sha256: str
    allowed_stage_identity_cids: Mapping[str, str]
    policy_authority_cid: str
    frozen: bool = True
    schema: str = G202_RUNTIME_IDENTITY_POLICY_SCHEMA_V2
    policy_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G202_RUNTIME_IDENTITY_POLICY_SCHEMA_V2:
            raise PositiveGateBundleError(
                "unsupported G202 runtime-identity policy schema"
            )
        object.__setattr__(
            self,
            "capability_inventory_cid",
            _cid(
                self.capability_inventory_cid,
                "capability_inventory_cid",
            ),
        )
        object.__setattr__(
            self,
            "policy_authority_cid",
            _cid(self.policy_authority_cid, "policy_authority_cid"),
        )
        object.__setattr__(
            self,
            "environment_cid",
            _cid(self.environment_cid, "environment_cid"),
        )
        object.__setattr__(
            self,
            "legacy_environment_sha256",
            _sha256(
                self.legacy_environment_sha256,
                "legacy_environment_sha256",
            ),
        )
        allowed = _mapping(
            self.allowed_stage_identity_cids,
            "allowed_stage_identity_cids",
        )
        if not allowed:
            raise PositiveGateBundleError(
                "runtime-identity policy must contain planned coordinates"
            )
        normalized: dict[str, str] = {}
        coverage: dict[str, set[str]] = {
            lane: set() for lane in _RUNTIME_IDENTITY_LANES
        }
        for coordinate in sorted(allowed):
            lane, _split, _case, _cache, variant_id, stage = (
                _parse_g202_stage_identity_coordinate_v2(coordinate)
            )
            coverage[lane].add(f"{variant_id}:{stage}")
            normalized[coordinate] = _cid(
                allowed[coordinate],
                f"allowed_stage_identity_cids.{coordinate}",
            )
        if any(
            observed
            != set(_EXPECTED_STAGE_IDENTITY_BASE_COORDINATES)
            for observed in coverage.values()
        ):
            raise PositiveGateBundleError(
                "runtime-identity policy must cover every preregistered "
                "A0--A12 variant/stage coordinate in each lane"
            )
        object.__setattr__(
            self,
            "allowed_stage_identity_cids",
            MappingProxyType(normalized),
        )
        if self.frozen is not True:
            raise PositiveGateBundleError(
                "runtime-identity policy must be frozen"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.policy_cid is None:
            object.__setattr__(self, "policy_cid", expected)
        elif _cid(self.policy_cid, "policy_cid") != expected:
            raise PositiveGateBundleError(
                "runtime-identity policy CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "capability_inventory_cid": self.capability_inventory_cid,
            "environment_cid": self.environment_cid,
            "legacy_environment_sha256": (
                self.legacy_environment_sha256
            ),
            "identity_projection_schema": (
                G202_STAGE_IDENTITY_PROJECTION_SCHEMA_V2
            ),
            "runtime_derived_identity_keys_excluded": list(
                _RUNTIME_DERIVED_IDENTITY_KEYS
            ),
            "allowed_stage_identity_cids": {
                coordinate: self.allowed_stage_identity_cids[coordinate]
                for coordinate in sorted(
                    self.allowed_stage_identity_cids
                )
            },
            "policy_authority_cid": self.policy_authority_cid,
            "frozen": self.frozen,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "policy_cid": self.policy_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G202 runtime identity policy")
        expected = {
            "schema",
            "capability_inventory_cid",
            "environment_cid",
            "legacy_environment_sha256",
            "identity_projection_schema",
            "runtime_derived_identity_keys_excluded",
            "allowed_stage_identity_cids",
            "policy_authority_cid",
            "frozen",
            "policy_cid",
        }
        _exact(data, expected, "G202 runtime identity policy")
        if (
            data["identity_projection_schema"]
            != G202_STAGE_IDENTITY_PROJECTION_SCHEMA_V2
            or tuple(
                _array(
                    data["runtime_derived_identity_keys_excluded"],
                    "runtime_derived_identity_keys_excluded",
                )
            )
            != _RUNTIME_DERIVED_IDENTITY_KEYS
        ):
            raise PositiveGateBundleError(
                "runtime-identity projection policy changed"
            )
        allowed = _mapping(
            data["allowed_stage_identity_cids"],
            "allowed_stage_identity_cids",
        )
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            capability_inventory_cid=data[
                "capability_inventory_cid"
            ],  # type: ignore[arg-type]
            environment_cid=data[
                "environment_cid"
            ],  # type: ignore[arg-type]
            legacy_environment_sha256=data[
                "legacy_environment_sha256"
            ],  # type: ignore[arg-type]
            allowed_stage_identity_cids={
                coordinate: str(allowed[coordinate])
                for coordinate in allowed
            },
            policy_authority_cid=data[
                "policy_authority_cid"
            ],  # type: ignore[arg-type]
            frozen=data["frozen"],  # type: ignore[arg-type]
            policy_cid=data["policy_cid"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class G202ExecutionIdentitiesV2:
    """Pre-execution identities frozen before any result artifact exists."""

    source_commit: str
    source_freeze_receipt_cid: str
    legacy_environment_sha256: str
    identity_cids: Mapping[str, str]
    frozen: bool = True
    schema: str = G202_EXECUTION_IDENTITIES_SCHEMA_V2
    bundle_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G202_EXECUTION_IDENTITIES_SCHEMA_V2:
            raise PositiveGateBundleError(
                "unsupported G202 execution-identities schema"
            )
        object.__setattr__(
            self,
            "source_commit",
            _git_commit(self.source_commit, "source_commit"),
        )
        object.__setattr__(
            self,
            "source_freeze_receipt_cid",
            _cid(
                self.source_freeze_receipt_cid,
                "source_freeze_receipt_cid",
            ),
        )
        object.__setattr__(
            self,
            "legacy_environment_sha256",
            _sha256(
                self.legacy_environment_sha256,
                "legacy_environment_sha256",
            ),
        )
        identities = _mapping(self.identity_cids, "identity_cids")
        if set(identities) != set(G230_IDENTITY_KEYS):
            raise PositiveGateBundleError(
                "G202 must bind the exact environment, capability, "
                "resource, prompt, model, and cache input identities"
            )
        object.__setattr__(
            self,
            "identity_cids",
            MappingProxyType(
                {
                    key: _cid(
                        identities[key],
                        f"identity_cids.{key}",
                    )
                    for key in G230_IDENTITY_KEYS
                }
            ),
        )
        if self.frozen is not True:
            raise PositiveGateBundleError(
                "G202 execution identities must be frozen"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.bundle_cid is None:
            object.__setattr__(self, "bundle_cid", expected)
        elif _cid(self.bundle_cid, "bundle_cid") != expected:
            raise PositiveGateBundleError(
                "G202 execution-identities CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "source_commit": self.source_commit,
            "source_freeze_receipt_cid": (
                self.source_freeze_receipt_cid
            ),
            "legacy_environment_sha256": (
                self.legacy_environment_sha256
            ),
            "identity_cids": dict(self.identity_cids),
            "frozen": self.frozen,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "bundle_cid": self.bundle_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G202 execution identities")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G202 execution identities",
        )
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            source_commit=data["source_commit"],  # type: ignore[arg-type]
            source_freeze_receipt_cid=data[
                "source_freeze_receipt_cid"
            ],  # type: ignore[arg-type]
            legacy_environment_sha256=data[
                "legacy_environment_sha256"
            ],  # type: ignore[arg-type]
            identity_cids=_mapping(
                data["identity_cids"],
                "identity_cids",
            ),  # type: ignore[arg-type]
            frozen=data["frozen"],  # type: ignore[arg-type]
            bundle_cid=data["bundle_cid"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class G202AuthorityRoleManifestV2:
    """Pre-execution identity/key-role allocation for operational evidence."""

    role_identity_cids: Mapping[str, str]
    frozen_before_execution: bool = True
    holdout_authority_included: bool = False
    schema: str = G202_AUTHORITY_ROLE_MANIFEST_SCHEMA_V2
    manifest_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G202_AUTHORITY_ROLE_MANIFEST_SCHEMA_V2:
            raise PositiveGateBundleError(
                "unsupported G202 authority-role manifest schema"
            )
        values = _mapping(
            self.role_identity_cids, "authority role identities"
        )
        if set(values) != set(G202_AUTHORITY_ROLE_KEYS):
            raise PositiveGateBundleError(
                "G202 authority manifest must allocate every exact "
                "operational role"
            )
        roles = {
            key: _cid(values[key], f"authority_role.{key}")
            for key in G202_AUTHORITY_ROLE_KEYS
        }
        if len(set(roles.values())) != len(roles):
            raise PositiveGateBundleError(
                "G202 operational authority roles must be pairwise distinct"
            )
        if (
            self.frozen_before_execution is not True
            or self.holdout_authority_included is not False
        ):
            raise PositiveGateBundleError(
                "G202 authority roles must be pre-execution and non-holdout"
            )
        object.__setattr__(
            self, "role_identity_cids", MappingProxyType(roles)
        )
        expected = cid_for_dag_json(self.identity_payload())
        if self.manifest_cid is None:
            object.__setattr__(self, "manifest_cid", expected)
        elif _cid(self.manifest_cid, "manifest_cid") != expected:
            raise PositiveGateBundleError(
                "G202 authority-role manifest CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "role_identity_cids": dict(self.role_identity_cids),
            "frozen_before_execution": self.frozen_before_execution,
            "holdout_authority_included": (
                self.holdout_authority_included
            ),
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "manifest_cid": self.manifest_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G202 authority role manifest")
        _exact(
            data,
            set(cls.__dataclass_fields__),
            "G202 authority role manifest",
        )
        return cls(
            **{
                **data,
                "role_identity_cids": _mapping(
                    data["role_identity_cids"],
                    "authority role identities",
                ),
            }
        )  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class G202FrozenRunInputsV2:
    """Typed G202 source/run/capability freeze consumed by G231."""

    run_id: str
    source_freeze: G230SourceFreezeReceipt
    source_commit_cid: str
    recursive_gitlinks_cid: str
    semantic_plan_set_cid: str
    g210_input_plan_cid: str
    g210_rescue_plan_set_cid: str
    run_plan_cid: str
    capability_inventory_cid: str
    environment_cid: str
    route_manifest_cid: str
    case_index_cid: str
    statistical_plan_cid: str
    source_worktree_cid: str
    source_executor_authority_cid: str
    runtime_orchestration_policy_cid: str
    cache_policy: G202CachePolicyV2
    gate_policy_bundle: G202GatePolicyBundleV2
    authority_role_manifest: G202AuthorityRoleManifestV2
    runtime_identity_policy: G202RuntimeIdentityPolicyV2
    execution_identities: G202ExecutionIdentitiesV2
    freeze_producer_identity_cid: str
    freeze_validator_identity_cid: str
    frozen: bool = True
    holdout_accessed: bool = False
    schema: str = G202_FROZEN_RUN_INPUTS_SCHEMA_V2
    receipt_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G202_FROZEN_RUN_INPUTS_SCHEMA_V2:
            raise PositiveGateBundleError(
                "unsupported G202 frozen-run schema"
            )
        object.__setattr__(self, "run_id", _safe_id(self.run_id, "run_id"))
        if not isinstance(self.source_freeze, G230SourceFreezeReceipt):
            raise PositiveGateBundleError(
                "G202 freeze requires G230SourceFreezeReceipt"
            )
        source = G230SourceFreezeReceipt.from_dict(
            self.source_freeze.to_dict()
        )
        if source.schema != G230_SOURCE_FREEZE_SCHEMA or not source.ready:
            raise PositiveGateBundleError(
                "G202 source must be clean, detached, and recursively clean"
            )
        object.__setattr__(self, "source_freeze", source)
        for field in (
            "source_commit_cid",
            "recursive_gitlinks_cid",
            "semantic_plan_set_cid",
            "g210_input_plan_cid",
            "g210_rescue_plan_set_cid",
            "run_plan_cid",
            "capability_inventory_cid",
            "environment_cid",
            "route_manifest_cid",
            "case_index_cid",
            "statistical_plan_cid",
            "source_worktree_cid",
            "source_executor_authority_cid",
            "runtime_orchestration_policy_cid",
            "freeze_producer_identity_cid",
            "freeze_validator_identity_cid",
        ):
            object.__setattr__(
                self, field, _cid(getattr(self, field), field)
            )
        if self.source_commit_cid != g238_git_commit_cid(
            source.source_commit
        ):
            raise PositiveGateBundleError(
                "G202 source commit CID changed"
            )
        if not isinstance(self.cache_policy, G202CachePolicyV2):
            raise PositiveGateBundleError(
                "G202 requires a typed cache policy"
            )
        cache_policy = G202CachePolicyV2.from_dict(
            self.cache_policy.to_dict()
        )
        object.__setattr__(self, "cache_policy", cache_policy)
        if cache_policy.run_id != self.run_id:
            raise PositiveGateBundleError(
                "G202 cache policy differs from the frozen run"
            )
        if not isinstance(
            self.gate_policy_bundle,
            G202GatePolicyBundleV2,
        ):
            raise PositiveGateBundleError(
                "G202 requires a typed gate-policy bundle"
            )
        gate_policy = G202GatePolicyBundleV2.from_dict(
            self.gate_policy_bundle.to_dict()
        )
        object.__setattr__(
            self,
            "gate_policy_bundle",
            gate_policy,
        )
        if gate_policy.statistical_plan_cid != self.statistical_plan_cid:
            raise PositiveGateBundleError(
                "G202 gate-policy statistics identity changed"
            )
        if not isinstance(
            self.authority_role_manifest,
            G202AuthorityRoleManifestV2,
        ):
            raise PositiveGateBundleError(
                "G202 requires a typed pre-execution authority manifest"
            )
        authority_manifest = G202AuthorityRoleManifestV2.from_dict(
            self.authority_role_manifest.to_dict()
        )
        object.__setattr__(
            self, "authority_role_manifest", authority_manifest
        )
        authorities = {
            self.source_executor_authority_cid,
            self.freeze_producer_identity_cid,
            self.freeze_validator_identity_cid,
        }
        if len(authorities) != 3:
            raise PositiveGateBundleError(
                "G202 executor, producer, and validator must be distinct"
            )
        if (
            authority_manifest.role_identity_cids["source_executor"]
            != self.source_executor_authority_cid
            or authority_manifest.role_identity_cids["freeze_producer"]
            != self.freeze_producer_identity_cid
            or authority_manifest.role_identity_cids["freeze_validator"]
            != self.freeze_validator_identity_cid
        ):
            raise PositiveGateBundleError(
                "G202 fixed authorities differ from the role manifest"
            )
        if not isinstance(
            self.runtime_identity_policy,
            G202RuntimeIdentityPolicyV2,
        ):
            raise PositiveGateBundleError(
                "G202 requires a typed pre-execution runtime policy"
            )
        identity_policy = G202RuntimeIdentityPolicyV2.from_dict(
            self.runtime_identity_policy.to_dict()
        )
        object.__setattr__(
            self,
            "runtime_identity_policy",
            identity_policy,
        )
        if (
            identity_policy.capability_inventory_cid
            != self.capability_inventory_cid
            or identity_policy.environment_cid != self.environment_cid
            or identity_policy.policy_authority_cid
            in {
                self.source_executor_authority_cid,
                self.freeze_producer_identity_cid,
                self.freeze_validator_identity_cid,
            }
        ):
            raise PositiveGateBundleError(
                "G202 runtime policy does not bind the capability freeze "
                "or an independent authority"
            )
        if (
            authority_manifest.role_identity_cids[
                "runtime_identity_policy_authority"
            ]
            != identity_policy.policy_authority_cid
        ):
            raise PositiveGateBundleError(
                "G202 runtime policy authority differs from its frozen role"
            )
        if not isinstance(
            self.execution_identities, G202ExecutionIdentitiesV2
        ):
            raise PositiveGateBundleError(
                "G202 requires typed pre-execution identities"
            )
        identities = G202ExecutionIdentitiesV2.from_dict(
            self.execution_identities.to_dict()
        )
        object.__setattr__(self, "execution_identities", identities)
        if (
            identities.source_commit != source.source_commit
            or identities.source_freeze_receipt_cid != source.receipt_cid
            or identity_policy.legacy_environment_sha256
            != identities.legacy_environment_sha256
            or identities.identity_cids["environment"]
            != self.environment_cid
            or identities.identity_cids["capability"]
            != self.capability_inventory_cid
            or identities.identity_cids["resource_policy"]
            != RESOURCE_MEASUREMENT_POLICY_V2_CID
            or identities.identity_cids["prompt_bundle"]
            != SEMANTIC_PROMPT_V2_CID
            or identities.identity_cids["model_identity"]
            != identity_policy.policy_cid
            or identities.identity_cids["cache_policy"]
            != cache_policy.policy_cid
        ):
            raise PositiveGateBundleError(
                "G202 execution identities do not match the frozen run"
            )
        expected_plan = g231_run_plan_cid_v2(
            run_id=self.run_id,
            semantic_plan_set_cid=self.semantic_plan_set_cid,
            g210_input_plan_cid=self.g210_input_plan_cid,
            g210_rescue_plan_set_cid=(
                self.g210_rescue_plan_set_cid
            ),
            case_index_cid=self.case_index_cid,
            route_manifest_cid=self.route_manifest_cid,
            capability_inventory_cid=self.capability_inventory_cid,
            environment_cid=self.environment_cid,
            statistical_plan_cid=self.statistical_plan_cid,
            reviewed_control_index_cid=(
                gate_policy.reviewed_control_index_cid
            ),
            gate_policy_bundle_cid=gate_policy.bundle_cid,
            cache_policy_cid=cache_policy.policy_cid,
            runtime_orchestration_policy_cid=(
                self.runtime_orchestration_policy_cid
            ),
        )
        if self.run_plan_cid != expected_plan:
            raise PositiveGateBundleError(
                "G202 run-plan CID changed"
            )
        if self.frozen is not True or self.holdout_accessed is not False:
            raise PositiveGateBundleError(
                "G202 freeze must be frozen and non-holdout"
            )
        expected_cid = cid_for_dag_json(self.identity_payload())
        if self.receipt_cid is None:
            object.__setattr__(self, "receipt_cid", expected_cid)
        elif _cid(self.receipt_cid, "receipt_cid") != expected_cid:
            raise PositiveGateBundleError(
                "G202 frozen-run receipt CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "run_id": self.run_id,
            "source_freeze": self.source_freeze.to_dict(),
            "source_commit_cid": self.source_commit_cid,
            "recursive_gitlinks_cid": self.recursive_gitlinks_cid,
            "semantic_plan_set_cid": self.semantic_plan_set_cid,
            "g210_input_plan_cid": self.g210_input_plan_cid,
            "g210_rescue_plan_set_cid": (
                self.g210_rescue_plan_set_cid
            ),
            "run_plan_cid": self.run_plan_cid,
            "capability_inventory_cid": self.capability_inventory_cid,
            "environment_cid": self.environment_cid,
            "route_manifest_cid": self.route_manifest_cid,
            "case_index_cid": self.case_index_cid,
            "statistical_plan_cid": self.statistical_plan_cid,
            "source_worktree_cid": self.source_worktree_cid,
            "source_executor_authority_cid": (
                self.source_executor_authority_cid
            ),
            "runtime_orchestration_policy_cid": (
                self.runtime_orchestration_policy_cid
            ),
            "cache_policy": self.cache_policy.to_dict(),
            "gate_policy_bundle": self.gate_policy_bundle.to_dict(),
            "authority_role_manifest": (
                self.authority_role_manifest.to_dict()
            ),
            "runtime_identity_policy": (
                self.runtime_identity_policy.to_dict()
            ),
            "execution_identities": self.execution_identities.to_dict(),
            "freeze_producer_identity_cid": (
                self.freeze_producer_identity_cid
            ),
            "freeze_validator_identity_cid": (
                self.freeze_validator_identity_cid
            ),
            "frozen": self.frozen,
            "holdout_accessed": self.holdout_accessed,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_payload(),
            "receipt_cid": self.receipt_cid,
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G202 frozen run inputs")
        _exact(data, set(cls.__dataclass_fields__), "G202 frozen run inputs")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            run_id=data["run_id"],  # type: ignore[arg-type]
            source_freeze=G230SourceFreezeReceipt.from_dict(
                data["source_freeze"]
            ),
            source_commit_cid=data[
                "source_commit_cid"
            ],  # type: ignore[arg-type]
            recursive_gitlinks_cid=data[
                "recursive_gitlinks_cid"
            ],  # type: ignore[arg-type]
            semantic_plan_set_cid=data[
                "semantic_plan_set_cid"
            ],  # type: ignore[arg-type]
            g210_input_plan_cid=data[
                "g210_input_plan_cid"
            ],  # type: ignore[arg-type]
            g210_rescue_plan_set_cid=data[
                "g210_rescue_plan_set_cid"
            ],  # type: ignore[arg-type]
            run_plan_cid=data["run_plan_cid"],  # type: ignore[arg-type]
            capability_inventory_cid=data[
                "capability_inventory_cid"
            ],  # type: ignore[arg-type]
            environment_cid=data[
                "environment_cid"
            ],  # type: ignore[arg-type]
            route_manifest_cid=data[
                "route_manifest_cid"
            ],  # type: ignore[arg-type]
            case_index_cid=data["case_index_cid"],  # type: ignore[arg-type]
            statistical_plan_cid=data[
                "statistical_plan_cid"
            ],  # type: ignore[arg-type]
            source_worktree_cid=data[
                "source_worktree_cid"
            ],  # type: ignore[arg-type]
            source_executor_authority_cid=data[
                "source_executor_authority_cid"
            ],  # type: ignore[arg-type]
            runtime_orchestration_policy_cid=data[
                "runtime_orchestration_policy_cid"
            ],  # type: ignore[arg-type]
            cache_policy=G202CachePolicyV2.from_dict(
                data["cache_policy"]
            ),
            gate_policy_bundle=G202GatePolicyBundleV2.from_dict(
                data["gate_policy_bundle"]
            ),
            authority_role_manifest=G202AuthorityRoleManifestV2.from_dict(
                data["authority_role_manifest"]
            ),
            runtime_identity_policy=G202RuntimeIdentityPolicyV2.from_dict(
                data["runtime_identity_policy"]
            ),
            execution_identities=G202ExecutionIdentitiesV2.from_dict(
                data["execution_identities"]
            ),
            freeze_producer_identity_cid=data[
                "freeze_producer_identity_cid"
            ],  # type: ignore[arg-type]
            freeze_validator_identity_cid=data[
                "freeze_validator_identity_cid"
            ],  # type: ignore[arg-type]
            frozen=data["frozen"],  # type: ignore[arg-type]
            holdout_accessed=data[
                "holdout_accessed"
            ],  # type: ignore[arg-type]
            receipt_cid=data["receipt_cid"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class G231ArtifactBindingsV2:
    """Frozen post-run source artifact identities joined by G231."""

    g202_freeze_cid: str
    artifact_cids: Mapping[str, str]
    validator_identity_cid: str
    frozen: bool = True
    holdout_accessed: bool = False
    schema: str = G231_ARTIFACT_BINDINGS_SCHEMA_V2
    index_cid: str | None = None

    def __post_init__(self) -> None:
        if self.schema != G231_ARTIFACT_BINDINGS_SCHEMA_V2:
            raise PositiveGateBundleError(
                "unsupported G231 artifact-bindings schema"
            )
        object.__setattr__(
            self,
            "g202_freeze_cid",
            _cid(self.g202_freeze_cid, "g202_freeze_cid"),
        )
        object.__setattr__(
            self,
            "validator_identity_cid",
            _cid(
                self.validator_identity_cid,
                "validator_identity_cid",
            ),
        )
        artifacts = _mapping(self.artifact_cids, "artifact_cids")
        if set(artifacts) != set(G231_ARTIFACT_KEYS):
            raise PositiveGateBundleError(
                "G231 artifact bindings must contain every exact source"
            )
        object.__setattr__(
            self,
            "artifact_cids",
            MappingProxyType(
                {
                    key: _cid(
                        artifacts[key],
                        f"artifact_cids.{key}",
                    )
                    for key in G231_ARTIFACT_KEYS
                }
            ),
        )
        if self.frozen is not True or self.holdout_accessed is not False:
            raise PositiveGateBundleError(
                "G231 artifact bindings must be frozen and non-holdout"
            )
        expected = cid_for_dag_json(self.identity_payload())
        if self.index_cid is None:
            object.__setattr__(self, "index_cid", expected)
        elif _cid(self.index_cid, "index_cid") != expected:
            raise PositiveGateBundleError(
                "G231 artifact-bindings CID changed"
            )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "g202_freeze_cid": self.g202_freeze_cid,
            "artifact_cids": dict(self.artifact_cids),
            "validator_identity_cid": self.validator_identity_cid,
            "frozen": self.frozen,
            "holdout_accessed": self.holdout_accessed,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "index_cid": self.index_cid}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        data = _mapping(value, "G231 artifact bindings")
        _exact(data, set(cls.__dataclass_fields__), "G231 artifact bindings")
        return cls(
            schema=data["schema"],  # type: ignore[arg-type]
            g202_freeze_cid=data[
                "g202_freeze_cid"
            ],  # type: ignore[arg-type]
            artifact_cids=_mapping(
                data["artifact_cids"], "artifact_cids"
            ),  # type: ignore[arg-type]
            validator_identity_cid=data[
                "validator_identity_cid"
            ],  # type: ignore[arg-type]
            frozen=data["frozen"],  # type: ignore[arg-type]
            holdout_accessed=data[
                "holdout_accessed"
            ],  # type: ignore[arg-type]
            index_cid=data["index_cid"],  # type: ignore[arg-type]
        )


def build_g231_replay_source_records_v2(
    matrix: G210RuntimeReceiptMatrixV2,
    candidate_variant_ids: Sequence[str],
    semantic_quality_gate: Mapping[str, object],
    resource_receipts: Sequence[IndependentResourceReceiptV2],
) -> tuple[G238ReplaySourceRecordV2, ...]:
    """Derive exact G238 records from G235, G210, and G237 sources."""

    candidates = _candidate_ids(candidate_variant_ids)
    selected = {"A0", *candidates}
    observations = _array(
        semantic_quality_gate.get("observations"),
        "semantic_quality_gate.observations",
    )
    observation_by_runtime: dict[str, Mapping[str, object]] = {}
    for value in observations:
        row = _mapping(value, "semantic observation")
        runtime_cid = _cid(
            row.get("runtime_receipt_cid"),
            "semantic observation runtime_receipt_cid",
        )
        if runtime_cid in observation_by_runtime:
            raise PositiveGateBundleError(
                "duplicate semantic observation runtime"
            )
        observation_by_runtime[runtime_cid] = row
    receipt_by_runtime: dict[str, IndependentResourceReceiptV2] = {}
    for value in resource_receipts:
        receipt = validate_independent_resource_receipt_v2(value)
        if receipt.runtime_evidence_cid in receipt_by_runtime:
            raise PositiveGateBundleError(
                "duplicate independent resource runtime"
            )
        receipt_by_runtime[receipt.runtime_evidence_cid] = receipt
    records: list[G238ReplaySourceRecordV2] = []
    for evidence in matrix.runtime_evidence:
        if evidence.case_result.variant_id not in selected:
            continue
        replayed = validate_causal_runtime_evidence_v2(
            evidence.to_dict()
        )
        observation = observation_by_runtime.get(replayed.receipt_cid)
        resource = receipt_by_runtime.get(replayed.receipt_cid)
        if observation is None or resource is None:
            raise PositiveGateBundleError(
                "selected runtime lacks semantic or resource identity"
            )
        result = replayed.case_result
        if (
            observation.get("split") != result.split.value
            or observation.get("case_id") != result.case_id
            or observation.get("cache_mode") != result.cache_mode.value
            or observation.get("variant_id") != result.variant_id
            or observation.get("source_cid")
            != replayed.compiler_exposure.source_cid
        ):
            raise PositiveGateBundleError(
                "semantic observation source coordinate changed"
            )
        _cid(
            observation.get("observation_cid"),
            "semantic observation_cid",
        )
        replay_semantic = G238SemanticObservationV2.create(replayed)
        records.append(
            G238ReplaySourceRecordV2.create(
                runtime_evidence=replayed,
                semantic_observation=replay_semantic,
                resource_receipt=resource,
            )
        )
    expected_runtime_cids = {
        evidence.receipt_cid
        for evidence in matrix.runtime_evidence
        if evidence.case_result.variant_id in selected
    }
    if (
        {record.runtime_evidence_cid for record in records}
        != expected_runtime_cids
        or set(observation_by_runtime) != expected_runtime_cids
        or set(receipt_by_runtime) != expected_runtime_cids
    ):
        raise PositiveGateBundleError(
            "semantic/resource/replay source populations differ"
        )
    return tuple(sorted(records, key=lambda item: item.record_cid))


def _require_positive(
    gate: Mapping[str, object],
    name: str,
) -> str:
    if (
        gate.get("passed") is not True
        or gate.get("status") not in {"passed", "complete"}
        or gate.get("failure_codes") not in ((), [])
    ):
        raise PositiveGateBundleError(
            f"{name} did not produce a complete positive gate"
        )
    return _cid(gate.get("receipt_cid"), f"{name}.receipt_cid")


def _g237_subsection_cids(
    resource_gate: Mapping[str, object],
) -> tuple[str, str, str]:
    analyses = _array(
        resource_gate.get("paired_cost_analyses"),
        "paired_cost_analyses",
    )
    analysis_cids: list[str] = []
    pair_cids: set[str] = set()
    for value in analyses:
        analysis = _mapping(value, "paired cost analysis")
        cid = _cid(analysis.get("analysis_cid"), "analysis_cid")
        body = {
            key: _plain(member)
            for key, member in analysis.items()
            if key != "analysis_cid"
        }
        if cid_for_dag_json(body) != cid:
            raise PositiveGateBundleError(
                "paired-statistics analysis CID changed"
            )
        analysis_cids.append(cid)
        pair_cids.update(
            _cid(item, "pair_cid")
            for item in _array(analysis.get("pair_cids"), "pair_cids")
        )
    stats_body = {
        "schema": G231_GATE_SUBSECTION_SCHEMA_V2,
        "gate_id": "paired_statistics",
        "g237_receipt_cid": resource_gate["receipt_cid"],
        "statistical_plan_cid": resource_gate["statistical_plan_cid"],
        "analysis_cids": sorted(analysis_cids),
        "pair_cids": sorted(pair_cids),
    }
    statistics_cid = cid_for_dag_json(stats_body)

    costs = _array(resource_gate.get("cost_evidence"), "cost_evidence")
    aggregate_cids: list[str] = []
    for value in costs:
        aggregate = _mapping(value, "cost aggregate")
        cid = _cid(aggregate.get("aggregate_cid"), "aggregate_cid")
        body = {
            key: _plain(member)
            for key, member in aggregate.items()
            if key != "aggregate_cid"
        }
        if cid_for_dag_json(body) != cid:
            raise PositiveGateBundleError(
                "cost aggregate CID changed"
            )
        aggregate_cids.append(cid)
    cost_body = {
        "schema": G231_GATE_SUBSECTION_SCHEMA_V2,
        "gate_id": "cost",
        "g237_receipt_cid": resource_gate["receipt_cid"],
        "resource_evidence_set_cid": resource_gate[
            "observed_resource_evidence_set_cid"
        ],
        "resource_receipt_cids": list(
            resource_gate["resource_receipt_cids"]
        ),
        "aggregate_cids": sorted(aggregate_cids),
    }
    cost_cid = cid_for_dag_json(cost_body)

    pareto = _mapping(
        resource_gate.get("pareto_evidence"), "pareto_evidence"
    )
    pareto_cid = _cid(pareto.get("pareto_cid"), "pareto_cid")
    pareto_body = {
        key: _plain(member)
        for key, member in pareto.items()
        if key != "pareto_cid"
    }
    if cid_for_dag_json(pareto_body) != pareto_cid:
        raise PositiveGateBundleError("Pareto frontier CID changed")
    return statistics_cid, cost_cid, pareto_cid


def _validate_runtime_identity_policy(
    freeze: G202FrozenRunInputsV2,
    runtime_evidence: Sequence[CausalRuntimeEvidenceV2],
    *,
    source_name: str,
    lane: str,
) -> None:
    if lane not in _RUNTIME_IDENTITY_LANES:
        raise PositiveGateBundleError(
            "unknown runtime-identity policy lane"
        )
    policy = freeze.runtime_identity_policy
    observed_coordinates: set[str] = set()
    for value in runtime_evidence:
        replayed = validate_causal_runtime_evidence_v2(value.to_dict())
        variant_id = replayed.case_result.variant_id
        for stage in (
            *replayed.semantic_frontend,
            *replayed.case_result.stages,
        ):
            if (
                stage.provenance.environment_sha256
                != policy.legacy_environment_sha256
            ):
                raise PositiveGateBundleError(
                    f"{source_name} stage environment SHA changed"
                )
            requested_variant = stage.provenance.requested_identity.get(
                "variant_id"
            )
            if requested_variant != variant_id:
                raise PositiveGateBundleError(
                    f"{source_name} stage variant identity changed"
                )
            coordinate = g202_stage_identity_coordinate_v2(
                lane=lane,
                split=stage.split.value,
                case_id=stage.case_id,
                cache_mode=stage.cache_mode.value,
                variant_id=variant_id,
                stage=stage.stage,
            )
            observed_coordinates.add(coordinate)
            allowed = policy.allowed_stage_identity_cids.get(coordinate)
            if allowed != g202_stage_identity_cid_v2(
                stage,
                environment_cid=policy.environment_cid,
            ):
                raise PositiveGateBundleError(
                    f"{source_name} runtime identity is outside the frozen "
                    "G202 preflight policy"
                )
    expected_coordinates = {
        coordinate
        for coordinate in policy.allowed_stage_identity_cids
        if coordinate.startswith(f"{lane}:")
    }
    if observed_coordinates != expected_coordinates:
        raise PositiveGateBundleError(
            f"{source_name} runtime identity population is incomplete"
        )


def _validate_g236_source_join(
    freeze: G202FrozenRunInputsV2,
    control_index: ReviewedControlIndexV2,
    control_runtime_evidence: Sequence[CausalRuntimeEvidenceV2],
) -> None:
    replayed = tuple(
        validate_causal_runtime_evidence_v2(item.to_dict())
        for item in control_runtime_evidence
    )
    if (
        not replayed
        or {item.case_result.run_id for item in replayed}
        != {freeze.run_id}
        or control_index.execution_authority_cid
        != freeze.source_executor_authority_cid
        or control_index.review_authority_cid
        != freeze.authority_role_manifest.role_identity_cids[
            "control_reviewer"
        ]
    ):
        raise PositiveGateBundleError(
            "G236 run, execution authority, or reviewer differs from G202"
        )
    environments = {
        stage.provenance.environment_sha256
        for item in replayed
        for stage in (
            *item.semantic_frontend,
            *item.case_result.stages,
        )
    }
    if environments != {
        freeze.execution_identities.legacy_environment_sha256
    }:
        raise PositiveGateBundleError(
            "G236 environment differs from G202"
        )
    _validate_runtime_identity_policy(
        freeze,
        replayed,
        source_name="G236",
        lane="reviewed_control",
    )


def _validate_symai_cache_sources(
    freeze: G202FrozenRunInputsV2,
    g201_index: G201SemanticEvidenceIndexV2,
    matrix: G210RuntimeReceiptMatrixV2,
) -> None:
    policy = freeze.cache_policy
    stages = [
        stage
        for result in g201_index.results
        for stage in result.stages
        if stage.stage is StageName.SYMAI
    ] + [
        stage
        for evidence in matrix.runtime_evidence
        for stage in (
            *evidence.semantic_frontend,
            *evidence.case_result.stages,
        )
        if stage.stage is StageName.SYMAI
    ]
    if not stages:
        raise PositiveGateBundleError(
            "G201/G210 contain no SyMAI cache-bearing stages"
        )
    for stage in stages:
        provenance = stage.provenance
        coordinate = (
            f"{stage.split.value}:"
            f"{stage.cache_mode.value}:"
            f"{stage.variant_id}"
        )
        namespace = provenance.effective_identity.get(
            "cache_namespace"
        )
        if not isinstance(namespace, str):
            raise PositiveGateBundleError(
                "SyMAI stage lacks a source-recomputed cache namespace"
            )
        expected_namespace = _g202_symai_namespace(
            run_id=freeze.run_id,
            legacy_protocol_sha256=(
                policy.legacy_protocol_sha256
            ),
            variant_id=stage.variant_id,
            split=stage.split.value,
            cache_mode=stage.cache_mode.value,
        )
        observed_cid = cid_for_dag_json(
            {
                "schema": G202_SYMAI_NAMESPACE_PREIMAGE_SCHEMA_V2,
                "coordinate": coordinate,
                "namespace": namespace,
            }
        )
        if (
            namespace != expected_namespace
            or policy.namespace_preimage_cids.get(coordinate)
            != observed_cid
        ):
            raise PositiveGateBundleError(
                "SyMAI cache namespace differs from the G202 preimage"
            )


def _source_inputs(
    g202_freeze: G202FrozenRunInputsV2,
    artifact_bindings: G231ArtifactBindingsV2,
    matrix: G210RuntimeReceiptMatrixV2,
    g201_index: G201SemanticEvidenceIndexV2,
    g210_plans: Sequence[AblationPlan],
    seal: ReplacementHoldoutSeal,
    control_index: ReviewedControlIndexV2,
    resource_receipts: Sequence[IndependentResourceReceiptV2],
    replay_index: G238ReplaySourceIndexV2,
    statistical_plan: StatisticalPlan,
) -> tuple[
    G202FrozenRunInputsV2,
    G231ArtifactBindingsV2,
    tuple[IndependentResourceReceiptV2, ...],
]:
    freeze = G202FrozenRunInputsV2.from_dict(g202_freeze.to_dict())
    artifacts = G231ArtifactBindingsV2.from_dict(
        artifact_bindings.to_dict()
    )
    if artifacts.g202_freeze_cid != freeze.receipt_cid:
        raise PositiveGateBundleError(
            "artifact index references another G202 freeze"
        )
    frozen_roles = freeze.authority_role_manifest.role_identity_cids
    if (
        artifacts.validator_identity_cid
        != frozen_roles["artifact_validator"]
    ):
        raise PositiveGateBundleError(
            "G231 artifact validator differs from its frozen G202 role"
        )
    expected_artifacts = {
        "g201_semantic_evidence_index": g201_index.index_cid,
        "g210_runtime_matrix": matrix.runtime_matrix_cid,
        "g220_replacement_holdout_seal": seal.seal_contract_cid,
        "g236_reviewed_control_index": control_index.index_cid,
        "g237_resource_evidence_set": artifacts.artifact_cids[
            "g237_resource_evidence_set"
        ],
        "g238_replay_source_index": replay_index.index_cid,
    }
    if dict(artifacts.artifact_cids) != expected_artifacts:
        raise PositiveGateBundleError(
            "G231 artifact index is stale, reduced, or rebased"
        )
    if (
        freeze.gate_policy_bundle.reviewed_control_index_cid
        != control_index.index_cid
    ):
        raise PositiveGateBundleError(
            "G236 reviewed-control population was not preregistered by G202"
        )
    semantic_input_plan = build_g202_g201_input_plan_v2(
        target_manifest=g201_index.target_manifest,
        targets=g201_index.targets,
        plans=g201_index.plans,
    )
    g210_input_plan = build_g202_g210_input_plan_v2(
        run_id=freeze.run_id,
        plans=g210_plans,
        rescue_manifests=matrix.receipt_matrix.rescue_manifests,
        legacy_environment_sha256=(
            freeze.execution_identities.legacy_environment_sha256
        ),
        environment_cid=freeze.environment_cid,
    )
    plan_cid = cid_for_dag_json(_plain(statistical_plan.to_dict()))
    if (
        freeze.semantic_plan_set_cid
        != semantic_input_plan["preflight_plan_cid"]
        or freeze.g210_input_plan_cid
        != g210_input_plan["input_plan_cid"]
        or freeze.g210_rescue_plan_set_cid
        != g210_input_plan["rescue_plan_set_cid"]
        or freeze.case_index_cid != g210_input_plan["case_index_cid"]
        or freeze.route_manifest_cid != g231_route_manifest_cid_v2()
        or freeze.statistical_plan_cid != plan_cid
    ):
        raise PositiveGateBundleError(
            "G202 semantic/G210 input plan, route, case, or statistics "
            "identity changed"
        )
    run_ids = {
        evidence.case_result.run_id
        for evidence in matrix.runtime_evidence
    }
    semantic_run_ids = {
        plan.run_id for plan in g201_index.plans
    } | {
        result.run_id for result in g201_index.results
    }
    if (
        run_ids != {freeze.run_id}
        or semantic_run_ids != {freeze.run_id}
    ):
        raise PositiveGateBundleError(
            "G202 run identity differs from G201 or full runtime sources"
        )
    environments = {
        profile.environment_sha256
        for profile in matrix.receipt_matrix.execution_profiles
    }
    if environments != {
        freeze.execution_identities.legacy_environment_sha256
    }:
        raise PositiveGateBundleError(
            "G202 legacy environment compatibility join changed"
        )
    if (
        matrix.receipt_matrix.semantic_calibration_artifact_cid
        != g201_index.calibration_report["artifact_cid"]
    ):
        raise PositiveGateBundleError(
            "post-execution G201 and G210 calibration artifacts differ"
        )
    if (
        seal.protocol_cids["semantic"] != SEMANTIC_PROTOCOL_V2_CID
        or seal.protocol_cids["causal_proof"]
        != CAUSAL_PROOF_PROTOCOL_V2_CID
    ):
        raise PositiveGateBundleError(
            "G220 seal protocol identity changed"
        )
    if (
        replay_index.source_run_id != freeze.run_id
        or replay_index.source_commit
        != freeze.source_freeze.source_commit
        or replay_index.source_commit_cid != freeze.source_commit_cid
        or replay_index.recursive_gitlinks_cid
        != freeze.recursive_gitlinks_cid
        or replay_index.environment_cid != freeze.environment_cid
        or replay_index.route_manifest_cid != freeze.route_manifest_cid
        or replay_index.case_index_cid != freeze.case_index_cid
        or replay_index.run_plan_cid != freeze.run_plan_cid
        or replay_index.source_worktree_cid
        != freeze.source_worktree_cid
        or replay_index.source_executor_authority_cid
        != freeze.source_executor_authority_cid
    ):
        raise PositiveGateBundleError(
            "G238 replay index differs from the frozen G202 source"
        )
    replayed_resources = tuple(
        validate_independent_resource_receipt_v2(item)
        for item in resource_receipts
    )
    disallowed_measurement_authorities = {
        freeze.source_executor_authority_cid,
        freeze.freeze_producer_identity_cid,
        freeze.freeze_validator_identity_cid,
        freeze.runtime_identity_policy.policy_authority_cid,
        artifacts.validator_identity_cid,
    }
    if (
        not replayed_resources
        or any(
            receipt.environment_identity_cid != freeze.environment_cid
            for receipt in replayed_resources
        )
        or {
            receipt.producer_identity_cid
            for receipt in replayed_resources
        }
        != {freeze.source_executor_authority_cid}
        or {
            receipt.meter_identity_cid
            for receipt in replayed_resources
        }
        != {frozen_roles["resource_meter"]}
        or {
            receipt.validator_identity_cid
            for receipt in replayed_resources
        }
        != {frozen_roles["resource_validator"]}
    ):
        raise PositiveGateBundleError(
            "G237 environment or producer/meter/validator authority "
            "differs from the frozen G202 run"
        )
    if (
        frozen_roles["resource_meter"]
        in disallowed_measurement_authorities
        or frozen_roles["resource_validator"]
        in disallowed_measurement_authorities
    ):
        raise PositiveGateBundleError(
            "G237 frozen measurement authorities are not independent"
        )
    _validate_runtime_identity_policy(
        freeze,
        matrix.runtime_evidence,
        source_name="G210",
        lane="primary",
    )
    _validate_symai_cache_sources(freeze, g201_index, matrix)
    return freeze, artifacts, replayed_resources


def _validate_g211_g240_operational_sources(
    *,
    freeze: G202FrozenRunInputsV2,
    artifacts: G231ArtifactBindingsV2,
    matrix: G210RuntimeReceiptMatrixV2,
    g210_plans: Sequence[AblationPlan],
    pilot_runtime_batch: object | None,
    development_runtime_batch: object | None,
    source_orchestration_validation_sources: Mapping[
        str, Sequence[G240PrivateSourceValidationSourcesV2]
    ]
    | None,
    resource_receipts: Sequence[IndependentResourceReceiptV2],
) -> tuple[
    Mapping[str, CausalRuntimeBatchResultV2],
    Mapping[str, G240RuntimeNamespaceEvidenceSetV2],
    Mapping[str, G240SourceOrchestrationEvidenceSetV2],
]:
    """Replay the persisted G211 batches and their live G240 sources.

    G202 freezes policy, source, and authority identities before execution.
    This post-run join replaces the former caller-set
    ``physical_binding_verified`` boolean with actual persisted namespace
    populations and private Git/OS source-recomputation inputs.
    """

    if not isinstance(pilot_runtime_batch, CausalRuntimeBatchResultV2) or (
        not isinstance(
            development_runtime_batch, CausalRuntimeBatchResultV2
        )
    ):
        raise PositiveGateBundleError(
            "source_process_state_cache_namespace_binding_receipts_"
            "unavailable: G231 requires persisted pilot and development "
            "G211 batches with G240 operational evidence"
        )
    private_by_split = (
        {}
        if source_orchestration_validation_sources is None
        else {
            str(split): tuple(values)
            for split, values in source_orchestration_validation_sources.items()
        }
    )
    if set(private_by_split) != set(G210_SPLITS) or any(
        not values for values in private_by_split.values()
    ):
        raise PositiveGateBundleError(
            "source_process_state_cache_namespace_binding_receipts_"
            "unavailable: G231 requires private G240 source validation "
            "inputs for both frozen splits"
        )
    try:
        for values in private_by_split.values():
            for source in values:
                if not isinstance(
                    source,
                    G240PrivateSourceValidationSourcesV2,
                ):
                    raise G240SourceExecutorError(
                        "operational source is not a private G240 bundle"
                    )
                validate_g240_production_execution_request_v2(
                    source.execution_request
                )
    except (G240SourceExecutorError, TypeError, ValueError) as exc:
        raise PositiveGateBundleError(
            "G231 production validation rejects test-only synthetic G240 "
            "execution"
        ) from exc
    plans_by_split = {
        plan.split.value: AblationPlan.from_dict(plan.to_dict())
        for plan in g210_plans
    }
    if set(plans_by_split) != set(G210_SPLITS) or len(
        plans_by_split
    ) != len(tuple(g210_plans)):
        raise PositiveGateBundleError(
            "G240 operational join requires the exact two G210 plans"
        )
    supplied = {
        "pilot": pilot_runtime_batch,
        "development": development_runtime_batch,
    }
    try:
        batches = {
            split: validate_causal_runtime_batch_v2(
                batch.plan,
                batch.rescue_manifest,
                batch.execution_profile,
                output_root=batch.output_root,
            )
            for split, batch in supplied.items()
        }
        if any(
            batch.plan != plans_by_split[split]
            or batch.plan.split.value != split
            for split, batch in batches.items()
        ):
            raise PositiveGateBundleError(
                "persisted G211 batches differ from the frozen G210 plans"
            )
        rebuilt_matrix = build_g210_runtime_receipt_matrix_v2(
            batches["pilot"],
            batches["development"],
        )
        if _plain(rebuilt_matrix.to_dict()) != _plain(matrix.to_dict()):
            raise PositiveGateBundleError(
                "G210 runtime matrix differs from persisted G211 batches"
            )
        if any(
            batch.runtime_namespace_evidence_set is None
            or batch.source_orchestration_evidence_set is None
            for batch in batches.values()
        ):
            raise PositiveGateBundleError(
                "persisted G211 batches lack complete G240 evidence"
            )
        namespace_sets = {
            split: batch.runtime_namespace_evidence_set
            for split, batch in batches.items()
        }
        assert all(
            isinstance(item, G240RuntimeNamespaceEvidenceSetV2)
            for item in namespace_sets.values()
        )
        plan_cids_by_split = {
            split: cid_for_dag_json(
                _plain(plans_by_split[split].to_dict())
            )
            for split in G210_SPLITS
        }
        validate_g240_runtime_namespace_population_v2(
            tuple(namespace_sets.values()),
            plan_cids_by_split=plan_cids_by_split,
            runtime_evidence=matrix.runtime_evidence,
            expected_environment_cid=freeze.environment_cid,
        )
        orchestration_sets: dict[
            str, G240SourceOrchestrationEvidenceSetV2
        ] = {}
        for split in G210_SPLITS:
            namespace_set = namespace_sets[split]
            orchestration_set = (
                batches[split].source_orchestration_evidence_set
            )
            assert isinstance(
                namespace_set, G240RuntimeNamespaceEvidenceSetV2
            )
            assert isinstance(
                orchestration_set,
                G240SourceOrchestrationEvidenceSetV2,
            )
            orchestration_sets[split] = (
                validate_g240_source_orchestration_evidence_set_v2(
                    orchestration_set,
                    runtime_namespace_evidence_set=namespace_set,
                    validation_sources=private_by_split[split],
                )
            )
    except PositiveGateBundleError:
        raise
    except (
        CausalRuntimeBatchError,
        RevisedPilotAuthorizationError,
        RuntimeNamespaceProvenanceError,
        SourceRuntimeOrchestrationError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G211/G240 operational evidence failed source replay"
        ) from exc

    policies = tuple(
        namespace_sets[split].policy for split in G210_SPLITS
    )
    orchestration_receipts = tuple(
        receipt
        for split in G210_SPLITS
        for receipt in orchestration_sets[split].receipts
    )
    worktree_cids = {
        receipt.worktree_safety_projection_cid
        for receipt in orchestration_receipts
    }
    if (
        any(
            policy.source_commit_cid != freeze.source_commit_cid
            or policy.recursive_gitlinks_cid
            != freeze.recursive_gitlinks_cid
            or policy.environment_cid != freeze.environment_cid
            or policy.runtime_orchestration_policy_cid
            != freeze.runtime_orchestration_policy_cid
            or policy.run_id != freeze.run_id
            for policy in policies
        )
        or {
            receipt.executor_identity_cid
            for receipt in orchestration_receipts
        }
        != {freeze.source_executor_authority_cid}
        or {
            receipt.runtime_orchestration_policy_cid
            for receipt in orchestration_receipts
        }
        != {freeze.runtime_orchestration_policy_cid}
        or worktree_cids != {freeze.source_worktree_cid}
    ):
        raise PositiveGateBundleError(
            "G240 source, environment, worktree, executor, or policy "
            "differs from the frozen G202 run"
        )

    authority_roles = {
        "namespace_authority": {
            policy.namespace_authority_cid for policy in policies
        },
        "runtime_namespace_validator": {
            namespace_sets[split].validator_identity_cid
            for split in G210_SPLITS
        },
        "namespace_observer": {
            receipt.namespace_observer_identity_cid
            for receipt in orchestration_receipts
        },
        "source_orchestration_observer": {
            receipt.orchestration_observer_identity_cid
            for receipt in orchestration_receipts
        },
        "source_orchestration_validator": {
            orchestration_sets[split].validator_identity_cid
            for split in G210_SPLITS
        },
        "resource_meter": {
            receipt.meter_identity_cid
            for receipt in resource_receipts
        },
        "resource_validator": {
            receipt.validator_identity_cid
            for receipt in resource_receipts
        },
    }
    frozen_roles = freeze.authority_role_manifest.role_identity_cids
    if any(
        observed != {frozen_roles[role]}
        for role, observed in authority_roles.items()
    ):
        raise PositiveGateBundleError(
            "G211/G237/G240 authorities differ from the frozen G202 "
            "role manifest"
        )
    authorities = {
        freeze.source_executor_authority_cid,
        freeze.freeze_producer_identity_cid,
        freeze.freeze_validator_identity_cid,
        freeze.runtime_identity_policy.policy_authority_cid,
        artifacts.validator_identity_cid,
        *(
            next(iter(observed))
            for observed in authority_roles.values()
        ),
    }
    if len(authorities) != 5 + len(authority_roles):
        raise PositiveGateBundleError(
            "G202/G211/G231 namespace, execution, measurement, and "
            "validation authorities must be pairwise independent"
        )
    return (
        MappingProxyType(dict(batches)),
        MappingProxyType(
            {
                split: namespace_sets[split]
                for split in G210_SPLITS
            }
        ),
        MappingProxyType(dict(orchestration_sets)),
    )


def _validate_g238_g240_source_execution_join(
    *,
    freeze: G202FrozenRunInputsV2,
    artifacts: G231ArtifactBindingsV2,
    replay_index: G238ReplaySourceIndexV2,
    replay_receipts: Sequence[G238DetachedReplayReceiptV2],
    operational_replay_sources: Mapping[str, object] | None,
    runtime_namespace_sets: Mapping[
        str, G240RuntimeNamespaceEvidenceSetV2
    ],
    source_orchestration_sets: Mapping[
        str, G240SourceOrchestrationEvidenceSetV2
    ],
    resource_receipts: Sequence[IndependentResourceReceiptV2],
) -> tuple[str, ...]:
    """Join every replay to the exact persisted source execution.

    G238 proves that a detached replay happened.  G231 additionally proves
    that its source policy, namespace receipt, executor contract, and command
    are the ones persisted by G211 rather than a post-hoc compatible source
    execution.
    """

    operational = (
        {}
        if operational_replay_sources is None
        else dict(operational_replay_sources)
    )
    required = {
        record.record_cid: record
        for record in replay_index.required_records
    }
    receipts = {
        receipt.target_record_cid: receipt
        for receipt in replay_receipts
    }
    if (
        set(operational) != set(required)
        or set(receipts) != set(required)
        or len(receipts) != len(tuple(replay_receipts))
    ):
        raise PositiveGateBundleError(
            "G238 operational replay population differs from its exact "
            "G211/G240 source population"
        )
    exact_source_orchestration_cids: list[str] = []
    replay_authority_roles: list[set[str]] = [set(), set(), set()]
    for target_cid in sorted(required):
        record = required[target_cid]
        receipt = receipts[target_cid]
        private = operational[target_cid]
        if not isinstance(
            private, G240PrivateReplayValidationSourcesV2
        ):
            raise PositiveGateBundleError(
                "G238 operational source is not a private G240 bundle"
            )
        if receipt.replay_runtime_evidence is None:
            raise PositiveGateBundleError(
                "G238 operational replay lacks complete runtime evidence"
            )
        result = record.runtime_evidence.case_result
        split = result.split.value
        plan_cid = runtime_namespace_sets[split].plan_cids[0]
        job_id = (
            f"j-{result.cache_mode.value}-{result.case_id}-"
            f"{result.variant_id.lower()}"
        )
        key = (plan_cid, job_id)
        exact_namespace = runtime_namespace_sets[split].receipt_map.get(key)
        exact_orchestration = (
            source_orchestration_sets[split].receipt_map.get(key)
        )
        if exact_namespace is None or exact_orchestration is None:
            raise PositiveGateBundleError(
                "G238 replay target is absent from persisted G240 source "
                "evidence"
            )
        try:
            (
                policy,
                source_namespace,
                replay_namespace,
                replay_orchestration,
            ) = validate_g240_private_replay_sources_v2(
                private,
                source_runtime_evidence=record.runtime_evidence,
                replay_runtime_evidence=(
                    receipt.replay_runtime_evidence
                ),
            )
            contract = (
                private.executor_contract
                if isinstance(
                    private.executor_contract,
                    G240SourceExecutorContractV2,
                )
                else G240SourceExecutorContractV2.from_dict(
                    private.executor_contract
                )
            )
        except (
            RuntimeNamespaceProvenanceError,
            SourceRuntimeOrchestrationError,
            TypeError,
            ValueError,
        ) as exc:
            raise PositiveGateBundleError(
                "G238 private replay failed the exact G211/G240 join"
            ) from exc
        if (
            _plain(policy.to_dict())
            != _plain(
                runtime_namespace_sets[split].policy.to_dict()
            )
            or _plain(source_namespace.to_dict())
            != _plain(exact_namespace.to_dict())
            or source_namespace.receipt_cid
            != receipt.source_namespace_receipt_cid
            or exact_orchestration.runtime_namespace_receipt_cid
            != source_namespace.receipt_cid
            or exact_orchestration.runtime_evidence_cid
            != record.runtime_evidence_cid
            or exact_orchestration.runtime_orchestration_policy_cid
            != freeze.runtime_orchestration_policy_cid
            or contract.contract_cid
            != freeze.runtime_orchestration_policy_cid
            or contract.command_template_cid
            != exact_orchestration.command_cid
            or replay_orchestration.runtime_orchestration_policy_cid
            != contract.contract_cid
            or replay_orchestration.command_cid
            != contract.command_template_cid
        ):
            raise PositiveGateBundleError(
                "G238 replay uses an unpersisted or post-hoc G240 source "
                "policy, namespace, contract, or command"
            )
        exact_source_orchestration_cids.append(
            str(exact_orchestration.receipt_cid)
        )
        replay_authority_roles[0].add(
            replay_namespace.replay_executor_identity_cid
        )
        replay_authority_roles[1].add(
            replay_namespace.replay_observer_identity_cid
        )
        replay_authority_roles[2].add(
            replay_orchestration.orchestration_observer_identity_cid
        )

    frozen_roles = freeze.authority_role_manifest.role_identity_cids
    replay_roles = {
        "replay_executor": replay_authority_roles[0],
        "replay_namespace_observer": replay_authority_roles[1],
        "replay_orchestration_observer": replay_authority_roles[2],
    }
    if any(
        observed != {frozen_roles[role]}
        for role, observed in replay_roles.items()
    ):
        raise PositiveGateBundleError(
            "G238 replay authorities differ from the frozen G202 role "
            "manifest"
        )
    upstream_authorities = {
        freeze.source_executor_authority_cid,
        freeze.freeze_producer_identity_cid,
        freeze.freeze_validator_identity_cid,
        freeze.runtime_identity_policy.policy_authority_cid,
        artifacts.validator_identity_cid,
        *(
            item.policy.namespace_authority_cid
            for item in runtime_namespace_sets.values()
        ),
        *(
            item.validator_identity_cid
            for item in runtime_namespace_sets.values()
        ),
        *(
            receipt.namespace_observer_identity_cid
            for source_set in source_orchestration_sets.values()
            for receipt in source_set.receipts
        ),
        *(
            receipt.orchestration_observer_identity_cid
            for source_set in source_orchestration_sets.values()
            for receipt in source_set.receipts
        ),
        *(
            item.validator_identity_cid
            for item in source_orchestration_sets.values()
        ),
        *(item.meter_identity_cid for item in resource_receipts),
        *(item.validator_identity_cid for item in resource_receipts),
    }
    replay_authorities = {
        next(iter(role)) for role in replay_roles.values()
    }
    if (
        len(replay_authorities) != len(replay_authority_roles)
        or replay_authorities & upstream_authorities
    ):
        raise PositiveGateBundleError(
            "G238 replay authorities overlap frozen source authorities"
        )
    return tuple(sorted(exact_source_orchestration_cids))


def build_g231_positive_gate_bundle_v2(
    *,
    g202_freeze: G202FrozenRunInputsV2,
    artifact_bindings: G231ArtifactBindingsV2,
    g201_index: G201SemanticEvidenceIndexV2,
    g210_plans: Sequence[AblationPlan],
    runtime_matrix: G210RuntimeReceiptMatrixV2,
    replacement_holdout_seal: ReplacementHoldoutSeal,
    semantic_quality_gate: object,
    efficacy_gate: object,
    reliability_gate: object,
    routing_gate: object,
    control_index: ReviewedControlIndexV2,
    control_rescue_manifests: Sequence[CausalRescueManifestV2],
    control_runtime_evidence: Sequence[CausalRuntimeEvidenceV2],
    safety_gate: object,
    resource_receipts: Sequence[IndependentResourceReceiptV2],
    resource_statistics_gate: object,
    statistical_plan: StatisticalPlan,
    replay_source_index: G238ReplaySourceIndexV2,
    detached_replay_receipts: Sequence[G238DetachedReplayReceiptV2],
    detached_replay_gate: object,
    replay_validator_authority_cid: str,
    candidate_variant_ids: Sequence[str],
    pilot_runtime_batch: CausalRuntimeBatchResultV2 | None = None,
    development_runtime_batch: CausalRuntimeBatchResultV2 | None = None,
    source_orchestration_validation_sources: Mapping[
        str, Sequence[G240PrivateSourceValidationSourcesV2]
    ]
    | None = None,
    operational_replay_sources: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    """Call every child source validator and build the exact G230 gate map."""

    candidates = _candidate_ids(candidate_variant_ids)
    if not isinstance(runtime_matrix, G210RuntimeReceiptMatrixV2):
        raise PositiveGateBundleError(
            "G231 requires a full G210 runtime matrix"
        )
    if not isinstance(g201_index, G201SemanticEvidenceIndexV2):
        raise PositiveGateBundleError(
            "G231 requires a typed G201 evidence index"
        )
    if not isinstance(replacement_holdout_seal, ReplacementHoldoutSeal):
        raise PositiveGateBundleError(
            "G231 requires a typed G220 replacement seal"
        )
    seal = ReplacementHoldoutSeal.from_dict(
        replacement_holdout_seal.to_dict()
    )
    if not isinstance(control_index, ReviewedControlIndexV2):
        raise PositiveGateBundleError(
            "G231 requires a typed G236 control index"
        )
    control_index = ReviewedControlIndexV2.from_dict(
        control_index.to_dict()
    )
    if not isinstance(replay_source_index, G238ReplaySourceIndexV2):
        raise PositiveGateBundleError(
            "G231 requires a typed G238 replay source index"
        )
    replay_index = G238ReplaySourceIndexV2.from_dict(
        replay_source_index.to_dict()
    )
    if not isinstance(statistical_plan, StatisticalPlan):
        raise PositiveGateBundleError(
            "G231 requires a pinned StatisticalPlan"
        )
    plan = StatisticalPlan.from_dict(statistical_plan.to_dict())
    freeze, artifacts, resources = _source_inputs(
        g202_freeze,
        artifact_bindings,
        runtime_matrix,
        g201_index,
        g210_plans,
        seal,
        control_index,
        resource_receipts,
        replay_index,
        plan,
    )
    (
        persisted_batches,
        runtime_namespace_sets,
        source_orchestration_sets,
    ) = _validate_g211_g240_operational_sources(
        freeze=freeze,
        artifacts=artifacts,
        matrix=runtime_matrix,
        g210_plans=g210_plans,
        pilot_runtime_batch=pilot_runtime_batch,
        development_runtime_batch=development_runtime_batch,
        source_orchestration_validation_sources=(
            source_orchestration_validation_sources
        ),
        resource_receipts=resources,
    )
    replay_source_orchestration_cids = (
        _validate_g238_g240_source_execution_join(
            freeze=freeze,
            artifacts=artifacts,
            replay_index=replay_index,
            replay_receipts=detached_replay_receipts,
            operational_replay_sources=operational_replay_sources,
            runtime_namespace_sets=runtime_namespace_sets,
            source_orchestration_sets=source_orchestration_sets,
            resource_receipts=resources,
        )
    )
    if (
        replay_validator_authority_cid
        != freeze.authority_role_manifest.role_identity_cids[
            "replay_namespace_observer"
        ]
    ):
        raise PositiveGateBundleError(
            "G238 validator differs from the frozen G202 replay observer "
            "role"
        )

    try:
        efficacy = validate_g234_efficacy_gate_v2(
            efficacy_gate, runtime_matrix
        )
        reliability = validate_g234_reliability_gate_v2(
            reliability_gate, runtime_matrix
        )
        routing = validate_g234_routing_gate_v2(
            routing_gate, runtime_matrix
        )
    except (
        RevisedPilotAuthorizationError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G234 child gate failed source replay"
        ) from exc
    for gate, name in (
        (efficacy, "efficacy"),
        (reliability, "reliability"),
        (routing, "routing"),
    ):
        if tuple(gate["candidate_variant_ids"]) != candidates:
            raise PositiveGateBundleError(
                f"{name} candidate set changed"
            )
        _require_positive(gate, name)

    try:
        safety = validate_reviewed_control_safety_gate_v2(
            safety_gate,
            control_index,
            control_rescue_manifests,
            control_runtime_evidence,
        )
    except (
        ReviewedControlSafetyError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G236 safety gate failed source replay"
        ) from exc
    try:
        _validate_g236_source_join(
            freeze,
            control_index,
            control_runtime_evidence,
        )
    except (
        PositiveGateBundleError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G236 source identities differ from frozen G202 inputs"
        ) from exc
    safety_cid = _require_positive(safety, "safety")

    try:
        resource_gate = validate_resource_statistics_gate_v2(
            resource_statistics_gate,
            runtime_matrix,
            resources,
            efficacy,
            safety,
            expected_resource_evidence_set_cid=(
                artifacts.artifact_cids[
                    "g237_resource_evidence_set"
                ]
            ),
            expected_safety_gate_receipt_cid=safety_cid,
            statistical_plan=plan,
        )
    except (
        ResourceStatisticsError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G237 resource/statistics gate failed source replay"
        ) from exc
    _require_positive(resource_gate, "resource_statistics")

    try:
        replay_gate_cid = validate_g238_detached_replay_gate_v2(
            detached_replay_gate,
            replay_index,
            detached_replay_receipts,
            validator_authority_cid=replay_validator_authority_cid,
            operational_replay_sources=operational_replay_sources,
        )
    except (
        FreshReplayGateError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G238 detached replay gate failed source replay"
        ) from exc
    replay_gate = _mapping(detached_replay_gate, "detached replay gate")
    if _require_positive(replay_gate, "replay") != replay_gate_cid:
        raise PositiveGateBundleError(
            "G238 replay validator returned another receipt"
        )

    try:
        semantic = validate_g235_semantic_quality_gate_v2(
            semantic_quality_gate,
            g201_index,
            runtime_matrix,
        )
    except (
        SemanticQualityError,
        TypeError,
        ValueError,
        KeyError,
    ) as exc:
        raise PositiveGateBundleError(
            "G235 semantic gate failed source replay"
        ) from exc
    if tuple(semantic["candidate_variant_ids"]) != candidates:
        raise PositiveGateBundleError(
            "semantic-quality candidate set changed"
        )
    semantic_cid = _require_positive(semantic, "semantic_quality")

    expected_records = build_g231_replay_source_records_v2(
        runtime_matrix,
        candidates,
        semantic,
        resources,
    )
    if tuple(record.to_dict() for record in replay_index.records) != tuple(
        record.to_dict() for record in expected_records
    ):
        raise PositiveGateBundleError(
            "G238 source records do not derive from G235/G210/G237"
        )
    statistics_cid, cost_cid, pareto_cid = _g237_subsection_cids(
        resource_gate
    )
    gate_receipt_cids = {
        "semantic_quality": semantic_cid,
        "efficacy": efficacy["receipt_cid"],
        "paired_statistics": statistics_cid,
        "cost": cost_cid,
        "reliability": reliability["receipt_cid"],
        "routing": routing["receipt_cid"],
        "pareto": pareto_cid,
        "safety": safety_cid,
        "replay": replay_gate_cid,
    }
    if tuple(gate_receipt_cids) != tuple(G230_GATE_IDS):
        raise PositiveGateBundleError(
            "G230 gate-ID map order or membership changed"
        )
    evaluated_runtime_cids = sorted(
        evidence.receipt_cid
        for evidence in runtime_matrix.runtime_evidence
        if evidence.case_result.variant_id in {"A0", *candidates}
    )
    child_receipts = {
        "g235_semantic_quality": semantic_cid,
        "g234_efficacy": efficacy["receipt_cid"],
        "g234_reliability": reliability["receipt_cid"],
        "g234_routing": routing["receipt_cid"],
        "g236_safety": safety_cid,
        "g237_resource_statistics": resource_gate["receipt_cid"],
        "g238_detached_replay": replay_gate_cid,
    }
    source_bindings = {
        "g202_freeze_cid": freeze.receipt_cid,
        "source_freeze_receipt_cid": freeze.source_freeze.receipt_cid,
        "source_commit": freeze.source_freeze.source_commit,
        "source_commit_cid": freeze.source_commit_cid,
        "source_tree_cid": freeze.source_freeze.source_tree_cid,
        "recursive_gitlinks_cid": freeze.recursive_gitlinks_cid,
        "semantic_plan_set_cid": freeze.semantic_plan_set_cid,
        "g210_input_plan_cid": freeze.g210_input_plan_cid,
        "g210_rescue_plan_set_cid": (
            freeze.g210_rescue_plan_set_cid
        ),
        "run_plan_cid": freeze.run_plan_cid,
        "capability_inventory_cid": freeze.capability_inventory_cid,
        "environment_cid": freeze.environment_cid,
        "route_manifest_cid": freeze.route_manifest_cid,
        "case_index_cid": freeze.case_index_cid,
        "statistical_plan_cid": freeze.statistical_plan_cid,
        "source_worktree_cid": freeze.source_worktree_cid,
        "source_executor_authority_cid": (
            freeze.source_executor_authority_cid
        ),
        "runtime_orchestration_policy_cid": (
            freeze.runtime_orchestration_policy_cid
        ),
        "runtime_identity_policy_cid": (
            freeze.runtime_identity_policy.policy_cid
        ),
        "cache_policy_cid": freeze.cache_policy.policy_cid,
        "gate_policy_bundle_cid": (
            freeze.gate_policy_bundle.bundle_cid
        ),
        "reviewed_control_index_cid": (
            freeze.gate_policy_bundle.reviewed_control_index_cid
        ),
        "execution_identities_cid": (
            freeze.execution_identities.bundle_cid
        ),
        "authority_role_manifest_cid": (
            freeze.authority_role_manifest.manifest_cid
        ),
        "g211_runtime_batch_receipt_cids": {
            split: persisted_batches[split].receipt_cid
            for split in G210_SPLITS
        },
        "g240_runtime_namespace_policy_cids": {
            split: runtime_namespace_sets[split].policy.policy_cid
            for split in G210_SPLITS
        },
        "g240_runtime_namespace_evidence_set_cids": {
            split: runtime_namespace_sets[split].evidence_set_cid
            for split in G210_SPLITS
        },
        "g240_source_orchestration_evidence_set_cids": {
            split: source_orchestration_sets[split].evidence_set_cid
            for split in G210_SPLITS
        },
        "g238_exact_source_orchestration_receipt_cids": list(
            replay_source_orchestration_cids
        ),
        "observed_runtime_model_identity_cid": (
            g231_model_identity_cid_v2(
                runtime_matrix,
                environment_cid=freeze.environment_cid,
            )
        ),
        "artifact_bindings_cid": artifacts.index_cid,
    }
    body = {
        "schema": G231_POSITIVE_GATE_BUNDLE_SCHEMA_V2,
        "goal_id": "HSSL-G231",
        "source_bindings": source_bindings,
        "artifact_cids": dict(artifacts.artifact_cids),
        "candidate_variant_ids": list(candidates),
        "evaluated_candidate_ids": list(candidates),
        "evaluated_runtime_evidence_cids": evaluated_runtime_cids,
        "child_gate_receipt_cids": child_receipts,
        "gate_receipt_cids": gate_receipt_cids,
        "complete": True,
        "passed": True,
        "status": "passed",
        "holdout_authorized": False,
        "holdout_accessed": False,
        "holdout_outcomes_inspected": False,
        "production_promotion_authorized": False,
        "source_recomputed": True,
    }
    result = {**body, "bundle_cid": cid_for_dag_json(body)}
    frozen = _freeze(result)
    assert isinstance(frozen, Mapping)
    return frozen


def validate_g231_positive_gate_bundle_v2(
    value: object,
    **sources: object,
) -> Mapping[str, object]:
    """Recompute every child and reject any composite derived-field change."""

    data = _mapping(value, "G231 positive gate bundle")
    rebuilt = build_g231_positive_gate_bundle_v2(
        **sources,  # type: ignore[arg-type]
    )
    if _plain(data) != _plain(rebuilt):
        raise PositiveGateBundleError(
            "G231 positive gate bundle did not source-recompute"
        )
    body = {
        key: _plain(member)
        for key, member in data.items()
        if key != "bundle_cid"
    }
    if data.get("bundle_cid") != cid_for_dag_json(body):
        raise PositiveGateBundleError(
            "G231 positive gate bundle CID changed"
        )
    return rebuilt


__all__ = [
    "G202_AUTHORITY_ROLE_KEYS",
    "G202_AUTHORITY_ROLE_MANIFEST_SCHEMA_V2",
    "G202_CACHE_POLICY_SCHEMA_V2",
    "G202_EFFICACY_EVALUATION_POLICY_V2_CID",
    "G202_EXECUTION_IDENTITIES_SCHEMA_V2",
    "G202_FROZEN_RUN_INPUTS_SCHEMA_V2",
    "G202_GATE_POLICY_BUNDLE_SCHEMA_V2",
    "G202_G210_CASE_INDEX_SCHEMA_V2",
    "G202_G210_INPUT_PLAN_SCHEMA_V2",
    "G202_G210_RESCUE_PLAN_SET_SCHEMA_V2",
    "G202_PARETO_POLICY_V2_CID",
    "G202_RUN_PLAN_SCHEMA_V2",
    "G202_RUNTIME_IDENTITY_POLICY_SCHEMA_V2",
    "G202_SEMANTIC_QUALITY_POLICY_V2_CID",
    "G202_SHORTLIST_SELECTION_POLICY_V2_CID",
    "G202_STAGE_IDENTITY_PROJECTION_SCHEMA_V2",
    "G202_SYMAI_NAMESPACE_PREIMAGE_SCHEMA_V2",
    "G202AuthorityRoleManifestV2",
    "G202CachePolicyV2",
    "G202ExecutionIdentitiesV2",
    "G202FrozenRunInputsV2",
    "G202GatePolicyBundleV2",
    "G202RuntimeIdentityPolicyV2",
    "G231_ARTIFACT_BINDINGS_SCHEMA_V2",
    "G231_ARTIFACT_KEYS",
    "G231_EVALUATED_CANDIDATE_IDS",
    "G231_CASE_INDEX_SCHEMA_V2",
    "G231_GATE_SUBSECTION_SCHEMA_V2",
    "G231_MODEL_IDENTITY_SCHEMA_V2",
    "G231_POSITIVE_GATE_BUNDLE_SCHEMA_V2",
    "G231_ROUTE_MANIFEST_SCHEMA_V2",
    "G231_RUN_PLAN_SCHEMA_V2",
    "G231_SEMANTIC_PLAN_SET_SCHEMA_V2",
    "G231ArtifactBindingsV2",
    "HSSLEV2312F74",
    "PositiveGateBundleError",
    "build_g202_g201_input_plan_v2",
    "build_g202_g210_input_plan_v2",
    "build_g231_observed_runtime_model_identity_v2",
    "build_g231_positive_gate_bundle_v2",
    "build_g231_replay_source_records_v2",
    "g202_shortlist_selection_policy_v2",
    "g202_stage_identity_cid_v2",
    "g202_stage_identity_coordinate_v2",
    "g202_stage_identity_input_cid_v2",
    "g202_run_plan_cid_v2",
    "g231_case_index_cid_v2",
    "g231_model_identity_cid_v2",
    "g231_route_manifest_cid_v2",
    "g231_run_plan_cid_v2",
    "g231_semantic_plan_set_cid_v2",
    "validate_g231_positive_gate_bundle_v2",
]

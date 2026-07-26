"""Synthetic source-replay coverage for the HSSL-G231 composite gate.

The fixture joins the independently tested G234--G238 lanes without reading a
benchmark corpus, checked-in result, or holdout.  Every child gate is built
from typed synthetic sources and the G231 validator must rebuild all of them.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import patch

import pytest

from benchmarks.logic_pipeline.ablation import (
    AblationCase,
    build_semantic_ablation_plan,
)
from benchmarks.logic_pipeline.adapters import (
    StageAdapter,
    StageOutput,
    StageRequest,
)
from benchmarks.logic_pipeline.causal_ablation import (
    CausalRescueCaseV2,
    CausalRescueManifestV2,
    build_causal_rescue_manifest_v2,
)
from benchmarks.logic_pipeline.cases import (
    REPLACEMENT_HOLDOUT_PROTOCOL_KEYS,
)
from benchmarks.logic_pipeline.content_addressing import cid_for_dag_json
from benchmarks.logic_pipeline.contracts import (
    CAUSAL_PROOF_PROTOCOL_V2_CID,
    DEFAULT_PROTOCOL,
    SEMANTIC_PROMPT_V2_CID,
    SEMANTIC_PROTOCOL_V2_CID,
    CacheMode,
    Split,
    StageName,
)
from benchmarks.logic_pipeline.positive_gate_bundle import (
    G202_AUTHORITY_ROLE_KEYS,
    G202_EFFICACY_EVALUATION_POLICY_V2_CID,
    G202_EXECUTION_IDENTITIES_SCHEMA_V2,
    G202_PARETO_POLICY_V2_CID,
    G202_SEMANTIC_QUALITY_POLICY_V2_CID,
    G202_SHORTLIST_SELECTION_POLICY_V2_CID,
    G202CachePolicyV2,
    G202AuthorityRoleManifestV2,
    G202ExecutionIdentitiesV2,
    G202FrozenRunInputsV2,
    G202GatePolicyBundleV2,
    G202RuntimeIdentityPolicyV2,
    G231ArtifactBindingsV2,
    G231_EVALUATED_CANDIDATE_IDS,
    PositiveGateBundleError,
    build_g202_g201_input_plan_v2,
    build_g202_g210_input_plan_v2,
    build_g231_observed_runtime_model_identity_v2,
    build_g231_positive_gate_bundle_v2,
    build_g231_replay_source_records_v2,
    g231_route_manifest_cid_v2,
    g231_run_plan_cid_v2,
    g202_shortlist_selection_policy_v2,
    g202_stage_identity_input_cid_v2,
    g202_stage_identity_cid_v2,
    g202_stage_identity_coordinate_v2,
)
from benchmarks.logic_pipeline.variants import get_variant_definition
from benchmarks.logic_pipeline.replay_gate import (
    G238_REPLAY_POLICY_V2_CID,
    G238ReplaySourceIndexV2,
    build_g238_detached_replay_gate_v2,
    g238_git_commit_cid,
)
from benchmarks.logic_pipeline.resource_statistics import (
    RESOURCE_MEASUREMENT_POLICY_V2_CID,
    RESOURCE_REPLAY_COMPARISON_POLICY_V2_CID,
    build_independent_resource_receipt_v2,
    build_resource_statistics_gate_v2,
    resource_evidence_set_cid_v2,
)
from benchmarks.logic_pipeline.reviewed_control import (
    REVIEWED_CONTROL_POLICY_V2_CID,
    build_reviewed_control_safety_gate_v2,
)
from benchmarks.logic_pipeline.revised_pilot_authorization import (
    G230_SOURCE_FREEZE_SCHEMA,
    G210ReceiptMatrix,
    G210RuntimeReceiptMatrixV2,
    G230SourceFreezeReceipt,
    build_g234_efficacy_gate_v2,
    build_g234_reliability_gate_v2,
    build_g234_routing_gate_v2,
)
from benchmarks.logic_pipeline.semantic_quality import (
    build_g235_semantic_quality_gate_v2,
)
from benchmarks.logic_pipeline.statistics import StatisticalPlan
from tests.integration.benchmarks.logic_pipeline._semantic_quality_support import (
    complete_g201_index,
    target_population,
)
from tests.integration.benchmarks.logic_pipeline import (
    _semantic_quality_support as semantic_quality_support,
)
from tests.integration.benchmarks.logic_pipeline.test_causal_runtime import (
    ENVIRONMENT_SHA256,
    MANIFEST_SHA256,
    SOURCE_TEXT,
)
from tests.integration.benchmarks.logic_pipeline._synthetic_seal_support import (
    _seal,
)
from tests.integration.benchmarks.logic_pipeline.test_resource_statistics_gate import (
    _component,
)
from tests.integration.benchmarks.logic_pipeline import (
    test_revised_pilot_positive_gates as positive_gate_support,
)
from tests.integration.benchmarks.logic_pipeline.test_revised_pilot_positive_gates import (
    _plain,
)
from tests.integration.benchmarks.logic_pipeline.test_reviewed_control_safety import (
    RUN_ID as CONTROL_RUN_ID,
    reviewed_population,
)


CANDIDATES = G231_EVALUATED_CANDIDATE_IDS
PLAN = StatisticalPlan(seed=231, bootstrap_samples=4)
SOURCE_COMMIT = "d" * 40


def _identity(label: str) -> str:
    return cid_for_dag_json(
        {
            "schema": "synthetic-g231-identity.v2",
            "identity": label,
        }
    )


def _authority_manifest(
    prefix: str,
    **overrides: str,
) -> G202AuthorityRoleManifestV2:
    roles = {
        role: _identity(f"{prefix}-{role.replace('_', '-')}")
        for role in G202_AUTHORITY_ROLE_KEYS
    }
    roles.update(overrides)
    return G202AuthorityRoleManifestV2(role_identity_cids=roles)


def _component_policy_cids() -> dict[str, str]:
    return {
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


def _gate_policy_bundle() -> G202GatePolicyBundleV2:
    return G202GatePolicyBundleV2(
        reviewed_control_index_cid=_identity(
            "selection-policy-control-index"
        ),
        statistical_plan_cid=_identity(
            "selection-policy-statistical-plan"
        ),
        component_policy_cids=_component_policy_cids(),
    )


def test_g202_selection_policy_freezes_every_pre_outcome_rule() -> None:
    policy = g202_shortlist_selection_policy_v2()
    requirements = policy["gate_requirements"]

    assert cid_for_dag_json(policy) == (
        G202_SHORTLIST_SELECTION_POLICY_V2_CID
    )
    assert tuple(policy["candidate_variant_ids"]) == CANDIDATES
    assert policy["materiality_thresholds"] == (
        DEFAULT_PROTOCOL.thresholds.to_dict()
    )
    assert policy["candidate_min"] == 1
    assert policy["candidate_max"] == 4
    assert policy["nondominated_frontier_required"] is True
    assert (
        policy[
            "all_absolute_paired_safety_resource_replay_gates_required"
        ]
        is True
    )
    assert set(requirements) == {
        "efficacy",
        "reliability",
        "semantic_quality",
        "cost_resource",
        "routing",
        "safety",
        "replay",
    }
    assert policy["g231_selection_permitted"] is False
    assert policy["selection_authority_goal"] == "HSSL-G232"


def test_g202_selection_policy_bundle_source_replays_exactly() -> None:
    bundle = _gate_policy_bundle()
    replayed = G202GatePolicyBundleV2.from_dict(bundle.to_dict())

    assert replayed.to_dict() == bundle.to_dict()
    assert replayed.component_policy_cids["shortlist_selection"] == (
        G202_SHORTLIST_SELECTION_POLICY_V2_CID
    )
    assert replayed.to_dict()["selection_policy_cid"] == (
        G202_SHORTLIST_SELECTION_POLICY_V2_CID
    )
    assert (
        replayed.to_dict()["g231_shortlist_selection_permitted"]
        is False
    )


def test_g202_selection_policy_rejects_post_freeze_mutation() -> None:
    bundle = _gate_policy_bundle()
    tampered = bundle.to_dict()
    thresholds = dict(tampered["thresholds"])
    materiality = dict(thresholds["materiality"])
    materiality["paired_regression_floor"] = 0.0
    thresholds["materiality"] = materiality
    tampered["thresholds"] = thresholds

    with pytest.raises(
        PositiveGateBundleError,
        match="thresholds or derived fields changed",
    ):
        G202GatePolicyBundleV2.from_dict(tampered)

    substituted = bundle.to_dict()
    policies = dict(substituted["component_policy_cids"])
    policies["shortlist_selection"] = _identity(
        "post-outcome-selection-policy"
    )
    substituted["component_policy_cids"] = policies
    with pytest.raises(
        PositiveGateBundleError,
        match="gate-policy identity changed",
    ):
        G202GatePolicyBundleV2.from_dict(substituted)


def _source_only_semantic_plans():
    targets, manifest = target_population(
        manifest_sha256=MANIFEST_SHA256
    )
    by_id = {target.case_id: target for target in targets}
    split_identities = manifest["reviewed_split_identities"]
    plans = []
    for split in (Split.PILOT, Split.DEVELOPMENT):
        case_ids = split_identities[split.value]["case_ids"]
        plans.append(
            build_semantic_ablation_plan(
                CONTROL_RUN_ID,
                tuple(
                    AblationCase.create(
                        case_id,
                        {"text": by_id[case_id].source_text},
                        split=split,
                    )
                    for case_id in case_ids
                ),
                case_manifest_sha256=MANIFEST_SHA256,
                split=split,
                seed=231,
                variant_ids=("A0", "A1", "A5", "A7", "A8"),
                cache_modes=(CacheMode.COLD,),
                environment_sha256=ENVIRONMENT_SHA256,
            )
        )
    return targets, manifest, tuple(plans)


def _source_only_g210_manifests(
    targets,
):
    by_split = {
        split: next(
            target
            for target in targets
            if f"-{split.value}" in target.case_id
        )
        for split in (Split.PILOT, Split.DEVELOPMENT)
    }
    plans = []
    manifests = []
    for split in (Split.PILOT, Split.DEVELOPMENT):
        target = by_split[split]
        plan = build_semantic_ablation_plan(
            CONTROL_RUN_ID,
            (
                AblationCase.create(
                    target.case_id,
                    {"text": target.source_text},
                    split=split,
                ),
            ),
            case_manifest_sha256=MANIFEST_SHA256,
            split=split,
            seed=233,
            variant_ids=tuple(f"A{index}" for index in range(13)),
            cache_modes=(CacheMode.COLD, CacheMode.WARM),
            environment_sha256=ENVIRONMENT_SHA256,
        )
        rescue_case = CausalRescueCaseV2(
            case_id=target.case_id,
            split=split,
            source_cid=target.source_cid,
            obligation_id=f"obligation-{split.value}",
            proof_obligation={
                "kind": "theorem",
                "logic": "deontic",
                "target": target.target,
            },
            optional_components=("hammer", "leanstral"),
            review_attestation_cid=_identity(
                f"{split.value}-rescue-review"
            ),
        )
        plans.append(plan)
        manifests.append(
            build_causal_rescue_manifest_v2(plan, (rescue_case,))
        )
    return tuple(plans), tuple(manifests)


def _source_only_runtime_identity_policy(
    *,
    capability_inventory_cid: str,
    environment_cid: str,
) -> G202RuntimeIdentityPolicyV2:
    allowed = {}
    for lane in ("primary", "reviewed_control"):
        for variant_id in (
            "A0",
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
            "A6",
            "A7",
            "A8",
            "A9",
            "A10",
            "A11",
            "A12",
        ):
            definition = get_variant_definition(variant_id)
            stages = tuple(
                sorted(
                    {*definition.stages, StageName.KERNEL},
                    key=lambda item: item.value,
                )
            )
            for stage in stages:
                requested = (
                    definition.requested_identity(stage)
                    if stage in definition.stages
                    else {
                        "variant_id": variant_id,
                        "configuration_sha256": definition.digest,
                    }
                )
                coordinate = g202_stage_identity_coordinate_v2(
                    lane=lane,
                    split="pilot",
                    case_id=f"synthetic-preflight-{lane}",
                    cache_mode="cold",
                    variant_id=variant_id,
                    stage=stage,
                )
                allowed[coordinate] = g202_stage_identity_input_cid_v2(
                    variant_id=variant_id,
                    stage=stage,
                    adapter_id=f"{stage.value}-adapter",
                    adapter_version="1",
                    adapter_module=(
                        "benchmarks.logic_pipeline.adapters"
                    ),
                    source_provenance=(
                        "benchmarks.logic_pipeline.adapters",
                        "synthetic-g202-preflight",
                    ),
                    requested_identity=requested,
                    effective_identity=requested,
                    legacy_environment_sha256=ENVIRONMENT_SHA256,
                    environment_cid=environment_cid,
                )
    return G202RuntimeIdentityPolicyV2(
        capability_inventory_cid=capability_inventory_cid,
        environment_cid=environment_cid,
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        allowed_stage_identity_cids=allowed,
        policy_authority_cid=_identity(
            "source-only-runtime-policy-authority"
        ),
    )


def test_g202_freeze_can_be_built_before_any_outcome_object_exists() -> None:
    targets, target_manifest, semantic_plans = (
        _source_only_semantic_plans()
    )
    semantic_input = build_g202_g201_input_plan_v2(
        target_manifest=target_manifest,
        targets=targets,
        plans=semantic_plans,
    )
    environment_cid = _identity("preflight-environment")
    capability_cid = _identity("preflight-capabilities")
    g210_plans, g210_manifests = _source_only_g210_manifests(
        targets
    )
    g210_input = build_g202_g210_input_plan_v2(
        run_id=CONTROL_RUN_ID,
        plans=g210_plans,
        rescue_manifests=g210_manifests,
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        environment_cid=environment_cid,
    )
    statistical_plan_cid = cid_for_dag_json(PLAN.to_dict())
    gate_policy = G202GatePolicyBundleV2(
        reviewed_control_index_cid=_identity(
            "preflight-reviewed-control"
        ),
        statistical_plan_cid=statistical_plan_cid,
        component_policy_cids=_component_policy_cids(),
    )
    caches = (
        _identity("preflight-cold-cache"),
        _identity("preflight-warm-cache"),
    )
    cache_policy = G202CachePolicyV2(
        run_id=CONTROL_RUN_ID,
        legacy_protocol_sha256=DEFAULT_PROTOCOL.digest,
        physical_namespace_cids={
            "cold": caches[0],
            "warm": caches[1],
        },
    )
    runtime_policy = _source_only_runtime_identity_policy(
        capability_inventory_cid=capability_cid,
        environment_cid=environment_cid,
    )
    source_freeze = G230SourceFreezeReceipt(
        schema=G230_SOURCE_FREEZE_SCHEMA,
        source_commit=SOURCE_COMMIT,
        source_tree_cid=_identity("preflight-source-tree"),
        detached_head=True,
        worktree_clean=True,
        submodules_clean=True,
    )
    execution_identities = G202ExecutionIdentitiesV2(
        schema=G202_EXECUTION_IDENTITIES_SCHEMA_V2,
        source_commit=SOURCE_COMMIT,
        source_freeze_receipt_cid=source_freeze.receipt_cid,
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        identity_cids={
            "environment": environment_cid,
            "capability": capability_cid,
            "resource_policy": RESOURCE_MEASUREMENT_POLICY_V2_CID,
            "prompt_bundle": SEMANTIC_PROMPT_V2_CID,
            "model_identity": runtime_policy.policy_cid,
            "cache_policy": cache_policy.policy_cid,
        },
    )
    route_manifest_cid = g231_route_manifest_cid_v2()
    orchestration_policy_cid = _identity(
        "preflight-runtime-orchestration-policy"
    )
    run_plan_cid = g231_run_plan_cid_v2(
        run_id=CONTROL_RUN_ID,
        semantic_plan_set_cid=semantic_input["preflight_plan_cid"],
        g210_input_plan_cid=g210_input["input_plan_cid"],
        g210_rescue_plan_set_cid=g210_input["rescue_plan_set_cid"],
        case_index_cid=g210_input["case_index_cid"],
        route_manifest_cid=route_manifest_cid,
        capability_inventory_cid=capability_cid,
        environment_cid=environment_cid,
        statistical_plan_cid=statistical_plan_cid,
        reviewed_control_index_cid=(
            gate_policy.reviewed_control_index_cid
        ),
        gate_policy_bundle_cid=gate_policy.bundle_cid,
        cache_policy_cid=cache_policy.policy_cid,
        runtime_orchestration_policy_cid=orchestration_policy_cid,
    )
    source_executor = _identity("preflight-executor")
    freeze_producer = _identity("preflight-freeze-producer")
    freeze_validator = _identity("preflight-freeze-validator")
    authority_manifest = _authority_manifest(
        "preflight-authority",
        source_executor=source_executor,
        freeze_producer=freeze_producer,
        freeze_validator=freeze_validator,
        runtime_identity_policy_authority=(
            runtime_policy.policy_authority_cid
        ),
    )
    freeze = G202FrozenRunInputsV2(
        run_id=CONTROL_RUN_ID,
        source_freeze=source_freeze,
        source_commit_cid=g238_git_commit_cid(SOURCE_COMMIT),
        recursive_gitlinks_cid=_identity("preflight-gitlinks"),
        semantic_plan_set_cid=semantic_input["preflight_plan_cid"],
        g210_input_plan_cid=g210_input["input_plan_cid"],
        g210_rescue_plan_set_cid=g210_input["rescue_plan_set_cid"],
        run_plan_cid=run_plan_cid,
        capability_inventory_cid=capability_cid,
        environment_cid=environment_cid,
        route_manifest_cid=route_manifest_cid,
        case_index_cid=g210_input["case_index_cid"],
        statistical_plan_cid=statistical_plan_cid,
        source_worktree_cid=_identity("preflight-worktree"),
        source_executor_authority_cid=source_executor,
        runtime_orchestration_policy_cid=orchestration_policy_cid,
        cache_policy=cache_policy,
        gate_policy_bundle=gate_policy,
        authority_role_manifest=authority_manifest,
        runtime_identity_policy=runtime_policy,
        execution_identities=execution_identities,
        freeze_producer_identity_cid=freeze_producer,
        freeze_validator_identity_cid=freeze_validator,
    )

    assert freeze.receipt_cid
    assert semantic_input["result_count"] == 0
    assert semantic_input["result_objects_accepted"] is False
    assert g210_input["result_count"] == 0
    assert g210_input["runtime_matrix_accepted"] is False
    substituted_roles = dict(
        authority_manifest.role_identity_cids
    )
    substituted_roles["source_executor"] = _identity(
        "post-freeze-substitute-executor"
    )
    with pytest.raises(
        PositiveGateBundleError,
        match="fixed authorities differ",
    ):
        replace(
            freeze,
            authority_role_manifest=G202AuthorityRoleManifestV2(
                role_identity_cids=substituted_roles
            ),
        )
    duplicate_roles = dict(
        authority_manifest.role_identity_cids
    )
    duplicate_roles["artifact_validator"] = duplicate_roles[
        "source_executor"
    ]
    with pytest.raises(
        PositiveGateBundleError,
        match="pairwise distinct",
    ):
        G202AuthorityRoleManifestV2(
            role_identity_cids=duplicate_roles
        )
    with pytest.raises(
        PositiveGateBundleError,
        match="run-plan CID changed",
    ):
        replace(
            freeze,
            runtime_orchestration_policy_cid=_identity(
                "post-freeze-arbitrary-command-policy"
            ),
        )


def test_g202_stage_identity_binds_adapter_source_and_both_environments() -> None:
    definition = get_variant_definition("A0")
    requested = definition.requested_identity(StageName.COMPILER)
    environment_cid = _identity("stage-environment")
    adapter = StageAdapter(
        StageName.COMPILER,
        handler=lambda _request: StageOutput(
            effective_identity={
                **requested,
                "implementation": "synthetic-preflight-compiler",
            }
        ),
        adapter_id="synthetic-preflight-compiler",
        source=("benchmarks.logic_pipeline.adapters",),
    )
    record = adapter.run(
        StageRequest(
            run_id=CONTROL_RUN_ID,
            case_id="synthetic-preflight-case",
            case_manifest_sha256=MANIFEST_SHA256,
            variant_id="A0",
            split=Split.PILOT,
            cache_mode=CacheMode.COLD,
            input_data={"text": SOURCE_TEXT},
            requested_identity=requested,
            environment_sha256=ENVIRONMENT_SHA256,
            source=("synthetic-g202-preflight",),
        )
    )
    expected = g202_stage_identity_input_cid_v2(
        variant_id="A0",
        stage=StageName.COMPILER,
        adapter_id="synthetic-preflight-compiler",
        adapter_version=record.adapter_version,
        adapter_module="benchmarks.logic_pipeline.adapters",
        source_provenance=record.provenance.source,
        requested_identity=record.provenance.requested_identity,
        effective_identity=record.provenance.effective_identity,
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        environment_cid=environment_cid,
    )
    assert g202_stage_identity_cid_v2(
        record,
        environment_cid=environment_cid,
    ) == expected

    changed_adapter = replace(
        record,
        provenance=replace(
            record.provenance,
            adapter_id="substituted-compiler",
        ),
    )
    changed_source = replace(
        record,
        provenance=replace(
            record.provenance,
            source=(
                "benchmarks.logic_pipeline.runtime",
                *record.provenance.source[1:],
            ),
        ),
    )
    changed_sha = replace(
        record,
        provenance=replace(
            record.provenance,
            environment_sha256="f" * 64,
        ),
    )
    for tampered in (changed_adapter, changed_source, changed_sha):
        assert g202_stage_identity_cid_v2(
            tampered,
            environment_cid=environment_cid,
        ) != expected
    assert g202_stage_identity_cid_v2(
        record,
        environment_cid=_identity("other-stage-environment"),
    ) != expected
    with pytest.raises(
        PositiveGateBundleError,
        match="canonical dotted Python name",
    ):
        g202_stage_identity_input_cid_v2(
            variant_id="A0",
            stage=StageName.COMPILER,
            adapter_id="synthetic-preflight-compiler",
            adapter_version=record.adapter_version,
            adapter_module="../adapters",
            source_provenance=record.provenance.source,
            requested_identity=record.provenance.requested_identity,
            effective_identity=record.provenance.effective_identity,
            legacy_environment_sha256=ENVIRONMENT_SHA256,
            environment_cid=environment_cid,
        )


def test_g202_g210_input_plan_rejects_unreplayed_plan_provenance() -> None:
    targets, _target_manifest, _semantic_plans = (
        _source_only_semantic_plans()
    )
    plans, manifests = _source_only_g210_manifests(targets)
    tampered_plan = replace(
        plans[0],
        environment_sha256="f" * 64,
    )

    with pytest.raises(
        PositiveGateBundleError,
        match="unique pilot/development rescue plans",
    ):
        build_g202_g210_input_plan_v2(
            run_id=CONTROL_RUN_ID,
            plans=(tampered_plan, plans[1]),
            rescue_manifests=manifests,
            legacy_environment_sha256=ENVIRONMENT_SHA256,
            environment_cid=_identity("preflight-environment"),
        )


def _semantic_bound_matrix(
    tmp_path_factory: pytest.TempPathFactory,
):
    with patch.object(
        positive_gate_support,
        "COMPLETE_RUN_ID",
        CONTROL_RUN_ID,
    ):
        base = positive_gate_support._complete_runtime_matrix(
            tmp_path_factory.mktemp("synthetic-g231-composite")
        )
    with patch.object(
        semantic_quality_support,
        "SYNTHETIC_RUN_ID",
        CONTROL_RUN_ID,
    ):
        semantic_index = complete_g201_index(
            runtime_source_text=SOURCE_TEXT,
            manifest_sha256=MANIFEST_SHA256,
            environment_sha256=ENVIRONMENT_SHA256,
        )
    calibration_cid = str(
        semantic_index.calibration_report["artifact_cid"]
    )
    g210_plans = []
    manifest_by_old_cid = {}
    for manifest in base.receipt_matrix.rescue_manifests:
        case = manifest.cases[0]
        plan = build_semantic_ablation_plan(
            CONTROL_RUN_ID,
            (
                AblationCase.create(
                    case.case_id,
                    {"text": SOURCE_TEXT},
                    split=case.split,
                ),
            ),
            case_manifest_sha256=MANIFEST_SHA256,
            split=case.split,
            seed=239,
            variant_ids=("A0", *CANDIDATES),
            cache_modes=(CacheMode.COLD, CacheMode.WARM),
            environment_sha256=ENVIRONMENT_SHA256,
        )
        rebuilt_manifest = build_causal_rescue_manifest_v2(
            plan,
            manifest.cases,
        )
        g210_plans.append(plan)
        manifest_by_old_cid[manifest.manifest_cid] = rebuilt_manifest
    profiles = tuple(
        sorted(
            (
                replace(
                    profile,
                    plan_cid=manifest_by_old_cid[
                        profile.rescue_manifest_cid
                    ].plan_cid,
                    source_manifest_cid=manifest_by_old_cid[
                        profile.rescue_manifest_cid
                    ].source_manifest_cid,
                    rescue_manifest_cid=manifest_by_old_cid[
                        profile.rescue_manifest_cid
                    ].manifest_cid,
                    semantic_calibration_artifact_cid=calibration_cid,
                )
                for profile in base.receipt_matrix.execution_profiles
            ),
            key=lambda profile: profile.rescue_manifest_cid,
        )
    )
    reduced = G210ReceiptMatrix(
        semantic_calibration_artifact_cid=calibration_cid,
        rescue_manifests=tuple(
            sorted(
                manifest_by_old_cid.values(),
                key=lambda item: item.cases[0].split.value,
            )
        ),
        execution_profiles=profiles,
        causal_aggregates=tuple(
            _plain(item)
            for item in base.receipt_matrix.causal_aggregates
        ),
    )
    matrix = G210RuntimeReceiptMatrixV2(
        receipt_matrix=reduced,
        runtime_evidence=base.runtime_evidence,
    )
    assert matrix.complete is True
    return semantic_index, tuple(g210_plans), matrix


def _runtime_identity_policy(
    *,
    capability_inventory_cid: str,
    environment_cid: str,
    matrix,
    control_evidence,
) -> G202RuntimeIdentityPolicyV2:
    allowed: dict[str, str] = {}
    for lane, population in (
        ("primary", matrix.runtime_evidence),
        ("reviewed_control", control_evidence),
    ):
        for evidence in population:
            for stage in (
                *evidence.semantic_frontend,
                *evidence.case_result.stages,
            ):
                variant_id = evidence.case_result.variant_id
                coordinate = g202_stage_identity_coordinate_v2(
                    lane=lane,
                    split=stage.split.value,
                    case_id=stage.case_id,
                    cache_mode=stage.cache_mode.value,
                    variant_id=variant_id,
                    stage=stage.stage,
                )
                identity_cid = g202_stage_identity_cid_v2(
                    stage,
                    environment_cid=environment_cid,
                )
                previous = allowed.setdefault(coordinate, identity_cid)
                assert previous == identity_cid
    return G202RuntimeIdentityPolicyV2(
        capability_inventory_cid=capability_inventory_cid,
        environment_cid=environment_cid,
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        allowed_stage_identity_cids=allowed,
        policy_authority_cid=_identity(
            "runtime-identity-policy-authority"
        ),
    )


@pytest.fixture(scope="module")
def g231_sources(
    tmp_path_factory: pytest.TempPathFactory,
    reviewed_population,
):
    semantic_index, g210_plans, matrix = _semantic_bound_matrix(
        tmp_path_factory
    )
    efficacy = build_g234_efficacy_gate_v2(matrix, CANDIDATES)
    reliability = build_g234_reliability_gate_v2(matrix, CANDIDATES)
    routing = build_g234_routing_gate_v2(matrix, CANDIDATES)
    semantic = build_g235_semantic_quality_gate_v2(
        semantic_index,
        matrix,
        CANDIDATES,
    )

    control_index = reviewed_population["index"]
    control_manifests = (reviewed_population["manifest"],)
    control_evidence = reviewed_population["evidence"]
    source_executor = control_index.execution_authority_cid
    safety = build_reviewed_control_safety_gate_v2(
        control_index,
        control_manifests,
        control_evidence,
    )

    meter = _identity("independent-resource-meter")
    resource_validator = _identity("independent-resource-validator")
    resources = tuple(
        build_independent_resource_receipt_v2(
            evidence,
            (_component(evidence.case_result.variant_id),),
            producer_identity_cid=source_executor,
            meter_identity_cid=meter,
            validator_identity_cid=resource_validator,
        )
        for evidence in matrix.runtime_evidence
        if evidence.case_result.variant_id in {"A0", *CANDIDATES}
    )
    resource_set_cid = resource_evidence_set_cid_v2(
        matrix.runtime_matrix_cid,
        CANDIDATES,
        resources,
    )
    resource_gate = build_resource_statistics_gate_v2(
        matrix,
        CANDIDATES,
        resources,
        efficacy,
        safety,
        expected_resource_evidence_set_cid=resource_set_cid,
        expected_safety_gate_receipt_cid=safety["receipt_cid"],
        statistical_plan=PLAN,
    )

    protocols = {
        key: _identity(f"replacement-holdout-protocol-{key}")
        for key in REPLACEMENT_HOLDOUT_PROTOCOL_KEYS
    }
    protocols["semantic"] = SEMANTIC_PROTOCOL_V2_CID
    protocols["causal_proof"] = CAUSAL_PROOF_PROTOCOL_V2_CID
    seal = _seal(protocol_cids=protocols)

    semantic_input_plan = build_g202_g201_input_plan_v2(
        target_manifest=semantic_index.target_manifest,
        targets=semantic_index.targets,
        plans=semantic_index.plans,
    )
    semantic_plan_set_cid = semantic_input_plan[
        "preflight_plan_cid"
    ]
    route_manifest_cid = g231_route_manifest_cid_v2()
    capability_inventory_cid = _identity("capability-inventory")
    environment_cid = resources[0].environment_identity_cid
    g210_input_plan = build_g202_g210_input_plan_v2(
        run_id=CONTROL_RUN_ID,
        plans=g210_plans,
        rescue_manifests=matrix.receipt_matrix.rescue_manifests,
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        environment_cid=environment_cid,
    )
    case_index_cid = g210_input_plan["case_index_cid"]
    statistical_plan_cid = cid_for_dag_json(PLAN.to_dict())
    cache_namespaces = (
        _identity("source-cache-cold"),
        _identity("source-cache-warm"),
    )
    cache_policy = G202CachePolicyV2(
        run_id=CONTROL_RUN_ID,
        legacy_protocol_sha256=(
            matrix.runtime_evidence[0].case_result.protocol_sha256
        ),
        physical_namespace_cids={
            mode: cache_namespaces[index]
            for index, mode in enumerate(("cold", "warm"))
        },
    )
    gate_policy = G202GatePolicyBundleV2(
        reviewed_control_index_cid=control_index.index_cid,
        statistical_plan_cid=statistical_plan_cid,
        component_policy_cids=_component_policy_cids(),
    )
    source_freeze = G230SourceFreezeReceipt(
        schema=G230_SOURCE_FREEZE_SCHEMA,
        source_commit=SOURCE_COMMIT,
        source_tree_cid=_identity("source-tree"),
        detached_head=True,
        worktree_clean=True,
        submodules_clean=True,
    )
    runtime_identity_policy = _runtime_identity_policy(
        capability_inventory_cid=capability_inventory_cid,
        environment_cid=environment_cid,
        matrix=matrix,
        control_evidence=control_evidence,
    )
    execution_identities = G202ExecutionIdentitiesV2(
        schema=G202_EXECUTION_IDENTITIES_SCHEMA_V2,
        source_commit=SOURCE_COMMIT,
        source_freeze_receipt_cid=source_freeze.receipt_cid,
        legacy_environment_sha256=ENVIRONMENT_SHA256,
        identity_cids={
            "environment": environment_cid,
            "capability": capability_inventory_cid,
            "resource_policy": RESOURCE_MEASUREMENT_POLICY_V2_CID,
            "prompt_bundle": SEMANTIC_PROMPT_V2_CID,
            "model_identity": runtime_identity_policy.policy_cid,
            "cache_policy": cache_policy.policy_cid,
        },
        frozen=True,
    )
    orchestration_policy_cid = _identity(
        "runtime-orchestration-policy"
    )
    run_plan_cid = g231_run_plan_cid_v2(
        run_id=CONTROL_RUN_ID,
        semantic_plan_set_cid=semantic_plan_set_cid,
        g210_input_plan_cid=g210_input_plan["input_plan_cid"],
        g210_rescue_plan_set_cid=(
            g210_input_plan["rescue_plan_set_cid"]
        ),
        case_index_cid=case_index_cid,
        route_manifest_cid=route_manifest_cid,
        capability_inventory_cid=capability_inventory_cid,
        environment_cid=environment_cid,
        statistical_plan_cid=statistical_plan_cid,
        reviewed_control_index_cid=control_index.index_cid,
        gate_policy_bundle_cid=gate_policy.bundle_cid,
        cache_policy_cid=cache_policy.policy_cid,
        runtime_orchestration_policy_cid=orchestration_policy_cid,
    )
    source_worktree_cid = _identity("source-worktree")
    source_executor_authority_cid = source_executor
    freeze_producer = _identity("freeze-producer")
    freeze_validator = _identity("freeze-validator")
    replay_validator = _identity("replay-validator")
    artifact_validator = _identity("artifact-validator")
    authority_manifest = _authority_manifest(
        "g231-authority",
        source_executor=source_executor_authority_cid,
        resource_meter=meter,
        resource_validator=resource_validator,
        control_reviewer=control_index.review_authority_cid,
        replay_namespace_observer=replay_validator,
        freeze_producer=freeze_producer,
        freeze_validator=freeze_validator,
        runtime_identity_policy_authority=(
            runtime_identity_policy.policy_authority_cid
        ),
        artifact_validator=artifact_validator,
    )
    freeze = G202FrozenRunInputsV2(
        run_id=CONTROL_RUN_ID,
        source_freeze=source_freeze,
        source_commit_cid=g238_git_commit_cid(SOURCE_COMMIT),
        recursive_gitlinks_cid=_identity("recursive-gitlinks"),
        semantic_plan_set_cid=semantic_plan_set_cid,
        g210_input_plan_cid=g210_input_plan["input_plan_cid"],
        g210_rescue_plan_set_cid=(
            g210_input_plan["rescue_plan_set_cid"]
        ),
        run_plan_cid=run_plan_cid,
        capability_inventory_cid=capability_inventory_cid,
        environment_cid=environment_cid,
        route_manifest_cid=route_manifest_cid,
        case_index_cid=case_index_cid,
        statistical_plan_cid=statistical_plan_cid,
        source_worktree_cid=source_worktree_cid,
        source_executor_authority_cid=source_executor_authority_cid,
        runtime_orchestration_policy_cid=orchestration_policy_cid,
        cache_policy=cache_policy,
        gate_policy_bundle=gate_policy,
        authority_role_manifest=authority_manifest,
        runtime_identity_policy=runtime_identity_policy,
        execution_identities=execution_identities,
        freeze_producer_identity_cid=freeze_producer,
        freeze_validator_identity_cid=freeze_validator,
    )

    replay_records = build_g231_replay_source_records_v2(
        matrix,
        CANDIDATES,
        semantic,
        resources,
    )
    replay_index = G238ReplaySourceIndexV2.create(
        source_run_id=freeze.run_id,
        source_commit=freeze.source_freeze.source_commit,
        recursive_gitlinks_cid=freeze.recursive_gitlinks_cid,
        environment_cid=freeze.environment_cid,
        route_manifest_cid=freeze.route_manifest_cid,
        case_index_cid=freeze.case_index_cid,
        run_plan_cid=freeze.run_plan_cid,
        source_worktree_cid=freeze.source_worktree_cid,
        source_executor_authority_cid=(
            freeze.source_executor_authority_cid
        ),
        records=replay_records,
    )
    replay_receipts = ()
    replay_gate = build_g238_detached_replay_gate_v2(
        replay_index,
        replay_receipts,
        validator_authority_cid=replay_validator,
    )

    artifact_bindings = G231ArtifactBindingsV2(
        g202_freeze_cid=freeze.receipt_cid,
        artifact_cids={
            "g201_semantic_evidence_index": semantic_index.index_cid,
            "g210_runtime_matrix": matrix.runtime_matrix_cid,
            "g220_replacement_holdout_seal": seal.seal_contract_cid,
            "g236_reviewed_control_index": control_index.index_cid,
            "g237_resource_evidence_set": resource_set_cid,
            "g238_replay_source_index": replay_index.index_cid,
        },
        validator_identity_cid=artifact_validator,
    )
    return {
        "g202_freeze": freeze,
        "artifact_bindings": artifact_bindings,
        "g201_index": semantic_index,
        "g210_plans": g210_plans,
        "runtime_matrix": matrix,
        "replacement_holdout_seal": seal,
        "semantic_quality_gate": semantic,
        "efficacy_gate": efficacy,
        "reliability_gate": reliability,
        "routing_gate": routing,
        "control_index": control_index,
        "control_rescue_manifests": control_manifests,
        "control_runtime_evidence": control_evidence,
        "safety_gate": safety,
        "resource_receipts": resources,
        "resource_statistics_gate": resource_gate,
        "statistical_plan": PLAN,
        "replay_source_index": replay_index,
        "detached_replay_receipts": replay_receipts,
        "detached_replay_gate": replay_gate,
        "replay_validator_authority_cid": replay_validator,
        "candidate_variant_ids": CANDIDATES,
    }


def test_composite_fails_closed_until_namespace_receipts_are_replayed(
    g231_sources,
) -> None:
    assert (
        g231_sources[
            "g202_freeze"
        ].cache_policy.physical_binding_verified
        is False
    )
    with pytest.raises(
        PositiveGateBundleError,
        match=(
            "source_process_state_cache_namespace_binding_receipts_"
            "unavailable"
        ),
    ):
        build_g231_positive_gate_bundle_v2(**g231_sources)


def test_g202_pre_execution_freeze_has_no_future_result_artifacts(
    g231_sources,
) -> None:
    freeze = g231_sources["g202_freeze"]
    frozen_before = freeze.receipt_cid
    execution = freeze.execution_identities.to_dict()

    assert "bound_artifact_cids" not in execution
    assert "artifact_cids" not in freeze.to_dict()
    assert freeze.receipt_cid == frozen_before
    assert set(g231_sources["artifact_bindings"].artifact_cids) == {
        "g201_semantic_evidence_index",
        "g210_runtime_matrix",
        "g220_replacement_holdout_seal",
        "g236_reviewed_control_index",
        "g237_resource_evidence_set",
        "g238_replay_source_index",
    }


def test_post_run_sources_recompute_frozen_g201_and_g210_inputs(
    g231_sources,
) -> None:
    freeze = g231_sources["g202_freeze"]
    semantic = build_g202_g201_input_plan_v2(
        target_manifest=g231_sources["g201_index"].target_manifest,
        targets=g231_sources["g201_index"].targets,
        plans=g231_sources["g201_index"].plans,
    )
    causal = build_g202_g210_input_plan_v2(
        run_id=freeze.run_id,
        plans=g231_sources["g210_plans"],
        rescue_manifests=(
            g231_sources[
                "runtime_matrix"
            ].receipt_matrix.rescue_manifests
        ),
        legacy_environment_sha256=(
            freeze.execution_identities.legacy_environment_sha256
        ),
        environment_cid=freeze.environment_cid,
    )

    assert semantic["preflight_plan_cid"] == (
        freeze.semantic_plan_set_cid
    )
    assert causal["input_plan_cid"] == freeze.g210_input_plan_cid
    assert causal["rescue_plan_set_cid"] == (
        freeze.g210_rescue_plan_set_cid
    )
    assert causal["case_index_cid"] == freeze.case_index_cid


def test_observed_model_identity_includes_disambiguated_frontend(
    g231_sources,
) -> None:
    identity = build_g231_observed_runtime_model_identity_v2(
        g231_sources["runtime_matrix"],
        environment_cid=g231_sources["g202_freeze"].environment_cid,
    )
    rows = identity["stage_identities"]
    coordinates = [row["coordinate"] for row in rows]

    assert identity["semantic_frontend_included"] is True
    assert identity["coordinate_disambiguation_required"] is True
    assert {"semantic_frontend", "case_result"} == {
        row["record_set"] for row in rows
    }
    assert len(coordinates) == len(set(coordinates))
    assert all(row["adapter_id"] for row in rows)
    assert all(row["adapter_module"] for row in rows)
    assert all(row["source_provenance"] for row in rows)
    assert all(
        row["environment_cid"]
        == g231_sources["g202_freeze"].environment_cid
        for row in rows
    )


def test_cherry_picked_candidate_population_fails_before_children(
    g231_sources,
) -> None:
    with pytest.raises(
        PositiveGateBundleError,
        match="exact complete preregistered primary",
    ):
        build_g231_positive_gate_bundle_v2(
            **{
                **g231_sources,
                "candidate_variant_ids": tuple(
                    candidate
                    for candidate in CANDIDATES
                    if candidate != "A2"
                ),
            }
        )


def test_stale_post_execution_artifact_binding_fails_closed(
    g231_sources,
) -> None:
    artifacts = g231_sources["artifact_bindings"]
    stale_artifact_cids = dict(artifacts.artifact_cids)
    stale_artifact_cids["g201_semantic_evidence_index"] = _identity(
        "substituted-g201-index"
    )
    stale_artifacts = G231ArtifactBindingsV2(
        g202_freeze_cid=artifacts.g202_freeze_cid,
        artifact_cids=stale_artifact_cids,
        validator_identity_cid=artifacts.validator_identity_cid,
    )
    with pytest.raises(
        PositiveGateBundleError,
        match="G231 artifact index is stale",
    ):
        build_g231_positive_gate_bundle_v2(
            **{
                **g231_sources,
                "artifact_bindings": stale_artifacts,
            }
        )


def test_g238_source_records_embed_and_recompute_complete_sources(
    g231_sources,
) -> None:
    index = g231_sources["replay_source_index"]
    assert len(index.records) == 52
    for record in index.records:
        assert (
            record.runtime_evidence_cid
            == record.runtime_evidence.receipt_cid
        )
        assert (
            record.semantic_observation.runtime_evidence_cid
            == record.runtime_evidence_cid
        )
        assert (
            record.resource_receipt.runtime_evidence_cid
            == record.runtime_evidence_cid
        )
        assert (
            record.resource_replay_identity_cid
            == record.resource_receipt.replay_identity_cid
        )

    rebuilt = build_g231_replay_source_records_v2(
        g231_sources["runtime_matrix"],
        CANDIDATES,
        g231_sources["semantic_quality_gate"],
        g231_sources["resource_receipts"],
    )
    assert tuple(record.to_dict() for record in rebuilt) == tuple(
        record.to_dict() for record in index.records
    )


def test_receipt_only_g238_gate_is_explicitly_incomplete(
    g231_sources,
) -> None:
    gate = g231_sources["detached_replay_gate"]
    assert gate["passed"] is False
    assert gate["status"] == "incomplete"
    assert {
        "missing_required_replay",
        "receipt_only_replay_unavailable",
    }.issubset(gate["failure_codes"])


def test_rebased_replay_source_identity_fails_closed(
    g231_sources,
) -> None:
    current = g231_sources["replay_source_index"]
    stale_index = G238ReplaySourceIndexV2.create(
        source_run_id=current.source_run_id,
        source_commit=current.source_commit,
        recursive_gitlinks_cid=current.recursive_gitlinks_cid,
        environment_cid=_identity("stale-replay-environment"),
        route_manifest_cid=current.route_manifest_cid,
        case_index_cid=current.case_index_cid,
        run_plan_cid=current.run_plan_cid,
        source_worktree_cid=current.source_worktree_cid,
        source_executor_authority_cid=(
            current.source_executor_authority_cid
        ),
        records=current.records,
    )
    artifacts = g231_sources["artifact_bindings"]
    stale_artifact_cids = dict(artifacts.artifact_cids)
    stale_artifact_cids["g238_replay_source_index"] = (
        stale_index.index_cid
    )
    stale_artifacts = G231ArtifactBindingsV2(
        g202_freeze_cid=artifacts.g202_freeze_cid,
        artifact_cids=stale_artifact_cids,
        validator_identity_cid=artifacts.validator_identity_cid,
    )
    with pytest.raises(
        PositiveGateBundleError,
        match="G238 replay index differs from the frozen G202 source",
    ):
        build_g231_positive_gate_bundle_v2(
            **{
                **g231_sources,
                "artifact_bindings": stale_artifacts,
                "replay_source_index": stale_index,
            }
        )

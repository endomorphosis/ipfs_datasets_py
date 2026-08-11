"""Planner behavior tests for LogicTactician."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.tactician import (
    GuidanceConfig,
    LogicTactician,
    PlannerError,
    RouteDisposition,
    StopDisposition,
    TacticianGoal,
    TacticianPolicy,
    TacticianReceipt,
    TacticianSource,
    TacticianValidationError,
    default_policy,
)


def test_planner_orders_by_policy_and_records_exclusions(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
    baseline_policy: TacticianPolicy,
) -> None:
    planner = LogicTactician()
    plan = planner.plan(sample_goal, sample_sources, baseline_policy)

    selected_classes = [route.source_class for route in plan.selected_routes]
    assert selected_classes[0] == "authoritative_contract"
    assert "program_graph" in selected_classes
    assert "vector_analogue" in selected_classes

    excluded_ids = {route.source_id for route in plan.excluded_routes}
    assert "src:poison" in excluded_ids
    poison = next(r for r in plan.excluded_routes if r.source_id == "src:poison")
    assert poison.disposition is RouteDisposition.EXCLUDED
    assert "denied" in poison.rationale.lower()

    assert plan.proof_gaps == sample_goal.proof_gaps
    assert plan.semantic_authority is False
    assert plan.planner_id == "logic.tactician.deterministic@1"
    assert all(sg.parent_goal_id == sample_goal.goal_id for sg in plan.subgoals)
    assert plan.stop_conditions
    assert plan.abstain_conditions


def test_planner_is_byte_stable_on_replay(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
    baseline_policy: TacticianPolicy,
) -> None:
    planner = LogicTactician()
    first = planner.plan(sample_goal, sample_sources, baseline_policy)
    second = planner.plan(sample_goal, list(reversed(sample_sources)), baseline_policy)
    assert first.to_dict() == second.to_dict()
    assert first.plan_id == second.plan_id


def test_planner_rejects_duplicate_source_identities(
    sample_goal: TacticianGoal,
    baseline_policy: TacticianPolicy,
) -> None:
    source = TacticianSource(
        source_id="dup",
        source_class="program_graph",
        precedence=1,
        rationale="x",
    )
    planner = LogicTactician()
    with pytest.raises(TacticianValidationError, match="duplicate"):
        planner.plan(sample_goal, [source, source], baseline_policy)


def test_planner_requires_config_root_binding(
    sample_sources: list[TacticianSource],
    baseline_policy: TacticianPolicy,
) -> None:
    goal = TacticianGoal(
        goal_id="g",
        statement_ref="s",
        goal_family="f",
        goal_root="gr",
        corpus_root="cr",
        config_root="not-the-policy",
        proof_gaps=[],
    )
    with pytest.raises(PlannerError, match="config_root"):
        LogicTactician().plan(goal, sample_sources, baseline_policy)


def test_learned_ranking_reorders_under_pinned_digest_with_fallback(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
) -> None:
    policy = default_policy(
        source_class_order=[
            "authoritative_contract",
            "program_graph",
            "vector_analogue",
        ],
        allow_learned_ranking=True,
        learned_model_digest="sha256:learned-model-1",
    )
    goal = TacticianGoal(
        goal_id=sample_goal.goal_id,
        statement_ref=sample_goal.statement_ref,
        goal_family=sample_goal.goal_family,
        goal_root=sample_goal.goal_root,
        corpus_root=sample_goal.corpus_root,
        config_root=policy.policy_id,
        authority_roots=sample_goal.authority_roots,
        proof_gaps=sample_goal.proof_gaps,
    )
    admitted = [s for s in sample_sources if s.source_class != "poisoned_comment"]

    def reverse_ranker(ids, _ctx):
        return list(reversed(list(ids)))

    plan = LogicTactician().plan(
        goal,
        admitted,
        policy,
        guidance=GuidanceConfig(
            learned_ranker=reverse_ranker,
            learned_model_digest="sha256:learned-model-1",
        ),
    )
    assert plan.learned_guidance_applied is True
    assert plan.learned_model_digest == "sha256:learned-model-1"
    # Policy order is contract -> graph -> vector; reverse puts vector first.
    assert plan.selected_routes[0].source_id == "src:vector"

    # Digest mismatch falls back to deterministic order.
    fallback = LogicTactician().plan(
        goal,
        admitted,
        policy,
        guidance=GuidanceConfig(
            learned_ranker=reverse_ranker,
            learned_model_digest="sha256:wrong",
        ),
    )
    assert fallback.learned_guidance_applied is False
    assert fallback.selected_routes[0].source_class == "authoritative_contract"


def test_llm_nomination_only_reprioritizes_admitted_sources(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
) -> None:
    policy = default_policy(
        source_class_order=[
            "authoritative_contract",
            "program_graph",
            "vector_analogue",
        ],
        allow_llm_nomination=True,
        llm_model_digest="sha256:llm-1",
    )
    goal = TacticianGoal(
        goal_id=sample_goal.goal_id,
        statement_ref=sample_goal.statement_ref,
        goal_family=sample_goal.goal_family,
        goal_root=sample_goal.goal_root,
        corpus_root=sample_goal.corpus_root,
        config_root=policy.policy_id,
        authority_roots=sample_goal.authority_roots,
        proof_gaps=sample_goal.proof_gaps,
    )
    admitted = [s for s in sample_sources if s.source_class != "poisoned_comment"]

    def nominate(ids, _ctx):
        return ["src:vector", "not-present"]

    plan = LogicTactician().plan(
        goal,
        admitted,
        policy,
        guidance=GuidanceConfig(
            llm_nominator=nominate,
            llm_model_digest="sha256:llm-1",
        ),
    )
    assert plan.llm_guidance_applied is True
    assert plan.selected_routes[0].source_id == "src:vector"


def test_cycle_in_nominated_deps_abstains(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
    baseline_policy: TacticianPolicy,
) -> None:
    plan = LogicTactician().plan(
        sample_goal,
        sample_sources,
        baseline_policy,
        nominated_subgoal_deps={
            "missing_arg_provenance": ["caller_update"],
            "caller_update": ["missing_arg_provenance"],
        },
    )
    assert plan.stop_disposition is StopDisposition.CYCLE_DETECTED
    assert plan.subgoals == []


def test_receipt_binds_plan_and_policy(
    sample_goal: TacticianGoal,
    sample_sources: list[TacticianSource],
    baseline_policy: TacticianPolicy,
) -> None:
    plan = LogicTactician().plan(sample_goal, sample_sources, baseline_policy)
    receipt = TacticianReceipt.from_plan(plan, baseline_policy)
    assert receipt.semantic_authority is False
    assert receipt.plan.plan_id == plan.plan_id
    restored = TacticianReceipt.from_dict(receipt.to_dict())
    assert restored.receipt_id == receipt.receipt_id

"""Model validation tests for logic.tactician@1."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.tactician import (
    SCHEMA_VERSION,
    TACTICIAN_INTERFACE,
    RouteDisposition,
    StopDisposition,
    TacticianGoal,
    TacticianPlan,
    TacticianPolicy,
    TacticianRoute,
    TacticianSource,
    TacticianSubgoal,
    TacticianValidationError,
    compute_content_digest,
    detect_cycle,
)


def test_interface_and_schema_constants() -> None:
    assert TACTICIAN_INTERFACE == "ipfs_datasets_py.logic.tactician@1"
    assert SCHEMA_VERSION == "1.0.0"


def test_goal_requires_exact_opaque_roots() -> None:
    goal = TacticianGoal(
        goal_id="g1",
        statement_ref="s1",
        goal_family="family",
        goal_root="goal-root:1",
        corpus_root="corpus-root:1",
        config_root="config-root:1",
        authority_roots={"tree": "tree:1"},
    )
    goal.validate()
    payload = goal.to_dict()
    assert payload["goal_root"] == "goal-root:1"
    assert TacticianGoal.from_dict(payload).goal_id == "g1"


def test_goal_rejects_empty_roots_and_unbounded_fields() -> None:
    with pytest.raises(TacticianValidationError):
        TacticianGoal(
            goal_id="g1",
            statement_ref="s1",
            goal_family="family",
            goal_root="",
            corpus_root="c",
            config_root="cfg",
        ).validate()

    with pytest.raises(TacticianValidationError):
        TacticianGoal(
            goal_id="g1",
            statement_ref="s1",
            goal_family="family",
            goal_root="g",
            corpus_root="c",
            config_root="cfg",
            proof_gaps=["gap"] * 300,
        ).validate()

    with pytest.raises(TacticianValidationError):
        TacticianGoal(
            goal_id="g1",
            statement_ref="s1",
            goal_family="family",
            goal_root="g",
            corpus_root="c",
            config_root="cfg",
            metadata={"semantic_authority": True},
        ).validate()


def test_source_rejects_duplicate_query_hints_and_authority_metadata() -> None:
    with pytest.raises(TacticianValidationError):
        TacticianSource(
            source_id="s1",
            source_class="cls",
            precedence=0,
            rationale="r",
            query_hints=["a", "a"],
        ).validate()

    with pytest.raises(TacticianValidationError):
        TacticianSource(
            source_id="s1",
            source_class="cls",
            precedence=0,
            rationale="r",
            metadata={"proof_authority": True},
        ).validate()


def test_policy_rejects_capability_and_authority_promotion() -> None:
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", network_allowed=True).validate()
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", write_allowed=True).validate()
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", proof_execution_allowed=True).validate()
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(policy_id="p1", semantic_authority=True).validate()
    with pytest.raises(TacticianValidationError):
        TacticianPolicy(
            policy_id="p1",
            allow_learned_ranking=True,
            learned_model_digest="",
        ).validate()


def test_subgoal_self_dependency_and_cycle_detection() -> None:
    with pytest.raises(TacticianValidationError):
        TacticianSubgoal(
            subgoal_id="sg1",
            parent_goal_id="g1",
            statement_ref="ref",
            depends_on=["sg1"],
        ).validate()

    cycle = detect_cycle({"a": ["b"], "b": ["c"], "c": ["a"]})
    assert cycle is not None
    assert cycle[0] == cycle[-1]
    assert detect_cycle({"a": ["b"], "b": []}) is None


def test_plan_rejects_cycles_duplicate_ids_and_authority() -> None:
    routes = [
        TacticianRoute(
            route_id="r1",
            source_id="s1",
            source_class="c",
            stage_index=0,
            disposition=RouteDisposition.SELECTED,
            rationale="ok",
        )
    ]
    cyclic = [
        TacticianSubgoal(
            subgoal_id="sg1",
            parent_goal_id="g1",
            statement_ref="ref1",
            depends_on=["sg2"],
        ),
        TacticianSubgoal(
            subgoal_id="sg2",
            parent_goal_id="g1",
            statement_ref="ref2",
            depends_on=["sg1"],
        ),
    ]
    with pytest.raises(TacticianValidationError, match="cyclic"):
        TacticianPlan.build(
            goal_id="g1",
            goal_root="gr",
            corpus_root="cr",
            config_root="cfg",
            authority_roots={},
            policy_id="p1",
            planner_id="planner",
            selected_routes=routes,
            excluded_routes=[],
            proof_gaps=["gap"],
            subgoals=cyclic,
            stop_conditions=["stop"],
            abstain_conditions=["abstain"],
        )

    with pytest.raises(TacticianValidationError):
        plan = TacticianPlan.build(
            goal_id="g1",
            goal_root="gr",
            corpus_root="cr",
            config_root="cfg",
            authority_roots={},
            policy_id="p1",
            planner_id="planner",
            selected_routes=routes,
            excluded_routes=[],
            proof_gaps=[],
            subgoals=[],
            stop_conditions=["stop"],
            abstain_conditions=["abstain"],
        )
        bad = TacticianPlan(
            plan_id=plan.plan_id,
            goal_id=plan.goal_id,
            goal_root=plan.goal_root,
            corpus_root=plan.corpus_root,
            config_root=plan.config_root,
            authority_roots=plan.authority_roots,
            policy_id=plan.policy_id,
            planner_id=plan.planner_id,
            selected_routes=plan.selected_routes,
            excluded_routes=plan.excluded_routes,
            proof_gaps=plan.proof_gaps,
            subgoals=plan.subgoals,
            stop_conditions=plan.stop_conditions,
            abstain_conditions=plan.abstain_conditions,
            stop_disposition=StopDisposition.CONTINUE,
            semantic_authority=True,
        )
        bad.validate()


def test_plan_content_id_is_stable_and_round_trips() -> None:
    route = TacticianRoute(
        route_id="r1",
        source_id="s1",
        source_class="authoritative_contract",
        stage_index=0,
        disposition=RouteDisposition.SELECTED,
        rationale="primary",
        addresses_gaps=["gap1"],
    )
    plan_a = TacticianPlan.build(
        goal_id="g1",
        goal_root="gr",
        corpus_root="cr",
        config_root="cfg",
        authority_roots={"tree": "t1"},
        policy_id="p1",
        planner_id="planner",
        selected_routes=[route],
        excluded_routes=[],
        proof_gaps=["gap1"],
        subgoals=[
            TacticianSubgoal(
                subgoal_id="subgoal:gap1",
                parent_goal_id="g1",
                statement_ref="stmt#gap1",
                depends_on=[],
                addresses_gaps=["gap1"],
                rationale="cover",
            )
        ],
        stop_conditions=["done"],
        abstain_conditions=["none"],
        stop_disposition=StopDisposition.CONTINUE,
    )
    plan_b = TacticianPlan.build(
        goal_id="g1",
        goal_root="gr",
        corpus_root="cr",
        config_root="cfg",
        authority_roots={"tree": "t1"},
        policy_id="p1",
        planner_id="planner",
        selected_routes=[route],
        excluded_routes=[],
        proof_gaps=["gap1"],
        subgoals=[
            TacticianSubgoal(
                subgoal_id="subgoal:gap1",
                parent_goal_id="g1",
                statement_ref="stmt#gap1",
                depends_on=[],
                addresses_gaps=["gap1"],
                rationale="cover",
            )
        ],
        stop_conditions=["done"],
        abstain_conditions=["none"],
        stop_disposition=StopDisposition.CONTINUE,
    )
    assert plan_a.plan_id == plan_b.plan_id
    assert plan_a.semantic_authority is False
    restored = TacticianPlan.from_dict(plan_a.to_dict())
    assert restored.plan_id == plan_a.plan_id
    assert restored.to_dict() == plan_a.to_dict()
    body = plan_a._body_dict()
    assert plan_a.plan_id == compute_content_digest(body)

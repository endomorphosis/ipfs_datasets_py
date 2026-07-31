"""Shared fixtures for Logic Tactician unit tests."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.tactician import (
    TacticianGoal,
    TacticianPolicy,
    TacticianSource,
    default_policy,
)


@pytest.fixture
def baseline_policy() -> TacticianPolicy:
    return default_policy(
        source_class_order=[
            "authoritative_contract",
            "type_and_effect_facts",
            "program_graph",
            "theorem_corpus",
            "vector_analogue",
            "model_hypothesis",
        ],
        denied_source_classes=["poisoned_comment"],
    )


@pytest.fixture
def sample_goal(baseline_policy: TacticianPolicy) -> TacticianGoal:
    return TacticianGoal(
        goal_id="goal:add-arg",
        statement_ref="stmt:sha256:abc",
        goal_family="caller_value_sufficiency",
        goal_root="goal-root:sha256:goal1",
        corpus_root="corpus-root:sha256:corp1",
        config_root=baseline_policy.policy_id,
        authority_roots={
            "tree": "tree:sha256:t1",
            "policy": "policy:sha256:p1",
        },
        proof_gaps=["missing_arg_provenance", "caller_update"],
        assumptions=["assume:pure_function"],
    )


@pytest.fixture
def sample_sources() -> list[TacticianSource]:
    return [
        TacticianSource(
            source_id="src:vector",
            source_class="vector_analogue",
            precedence=2,
            rationale="Semantic near-neighbors may nominate similar callers",
            query_hints=["add argument", "f(a,b)"],
            source_root="src-root:vector:1",
        ),
        TacticianSource(
            source_id="src:contract",
            source_class="authoritative_contract",
            precedence=1,
            rationale="Reviewed contract defines expected arity",
            query_hints=["signature"],
            source_root="src-root:contract:1",
        ),
        TacticianSource(
            source_id="src:graph",
            source_class="program_graph",
            precedence=1,
            rationale="Call graph enumerates resolved callers",
            query_hints=["callers of f"],
            source_root="src-root:graph:1",
        ),
        TacticianSource(
            source_id="src:poison",
            source_class="poisoned_comment",
            precedence=0,
            rationale="Comment text must not become an axiom",
            query_hints=["TODO fix"],
            source_root="src-root:comment:1",
        ),
    ]

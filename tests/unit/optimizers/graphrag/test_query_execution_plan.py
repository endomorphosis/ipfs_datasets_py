from __future__ import annotations

from typing import Any, Dict

import pytest


def _assert_step_shape(step: Dict[str, Any]) -> None:
    assert isinstance(step, dict)
    assert set(step.keys()) >= {"name", "description", "budget_ms", "params"}
    assert isinstance(step["name"], str) and step["name"]
    assert isinstance(step["description"], str)
    assert isinstance(step["budget_ms"], (int, float))
    assert step["budget_ms"] >= 0
    assert isinstance(step["params"], dict)


def test_get_execution_plan_vector_query_shape() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    optimizer = UnifiedGraphRAGQueryOptimizer()

    query = {
        "query_vector": [0.0, 0.1, 0.2],
        "vector_params": {"top_k": 3, "min_score": 0.4},
        "traversal": {"max_depth": 2, "edge_types": ["rel"], "strategy": "default"},
    }

    plan = optimizer.get_execution_plan(query, priority="normal")

    assert isinstance(plan, dict)
    assert plan["optimization_applied"] is True
    assert plan["priority"] == "normal"

    assert isinstance(plan.get("execution_steps"), list)
    assert [s.get("name") for s in plan["execution_steps"]] == [
        "vector_similarity_search",
        "graph_traversal",
        "result_ranking",
    ]

    for step in plan["execution_steps"]:
        _assert_step_shape(step)

    assert plan["estimated_time_ms"] == pytest.approx(
        sum(s["budget_ms"] for s in plan["execution_steps"])
    )

    assert isinstance(plan.get("budget"), dict)
    assert isinstance(plan.get("statistics"), dict)
    assert isinstance(plan.get("caching"), dict)


def test_get_execution_plan_direct_graph_query_shape() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    optimizer = UnifiedGraphRAGQueryOptimizer()

    query = {
        "query_text": "Find relationships between Alice and Bob",
        "entity_ids": ["e1", "e2"],
        "traversal": {"max_depth": 1, "strategy": "default"},
    }

    plan = optimizer.get_execution_plan(query, priority="high")

    assert isinstance(plan, dict)
    assert plan["optimization_applied"] is True
    assert plan["priority"] == "high"

    assert isinstance(plan.get("execution_steps"), list)
    assert len(plan["execution_steps"]) == 1
    assert plan["execution_steps"][0].get("name") == "direct_graph_query"

    _assert_step_shape(plan["execution_steps"][0])

    assert plan["estimated_time_ms"] == pytest.approx(
        sum(s["budget_ms"] for s in plan["execution_steps"])
    )

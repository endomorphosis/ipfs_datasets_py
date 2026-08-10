"""Unit tests for AST impact closures (DQK-033)."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.software_contracts.duckdb_impact import (
    BudgetExceeded,
    ImpactBudget,
    ImpactGraph,
    ImpactQueryError,
    closure,
)


def _fixture_graph() -> ImpactGraph:
    """Known fixture: A -> B -> C, A -> D; reverse refs for B."""

    g = ImpactGraph(source_revision="rev:src-42")
    g.add("mod.A", "mod.B", "import")
    g.add("mod.B", "mod.C", "call")
    g.add("mod.A", "mod.D", "reference")
    g.add("mod.E", "mod.B", "call")  # reverse into B
    return g


def test_closures_bind_exact_source_revision() -> None:
    g = _fixture_graph()
    result = closure(g, ["mod.A"], direction="forward")
    assert result.source_revision == "rev:src-42"
    assert result.to_dict()["source_revision"] == "rev:src-42"
    assert "mod.A" in result.nodes
    assert "mod.B" in result.nodes
    assert "mod.C" in result.nodes
    assert "mod.D" in result.nodes


def test_depth_row_time_budgets_enforced() -> None:
    g = _fixture_graph()
    shallow = closure(
        g, ["mod.A"], direction="forward", budget=ImpactBudget(max_depth=0)
    )
    assert shallow.nodes == ("mod.A",)
    assert shallow.depth_reached == 0

    row_limited = closure(
        g, ["mod.A"], direction="forward", budget=ImpactBudget(max_rows=2)
    )
    assert len(row_limited.nodes) <= 2
    assert row_limited.truncated is True

    with pytest.raises(BudgetExceeded) as exc:
        closure(
            g,
            ["mod.A"],
            direction="forward",
            budget=ImpactBudget(max_seconds=1e-12),
        )
    assert exc.value.kind == "time"


def test_agrees_with_known_analyzer_fixture() -> None:
    """Manual analyzer expectation for the fixture graph."""

    g = _fixture_graph()
    # Forward impact of A: A,B,C,D (order BFS)
    fwd = closure(g, ["mod.A"], direction="forward")
    assert set(fwd.nodes) == {"mod.A", "mod.B", "mod.C", "mod.D"}
    # Reverse impact of B (who depends on B): B, A, E
    rev = closure(g, ["mod.B"], direction="reverse", kinds=["import", "call"])
    assert set(rev.nodes) == {"mod.B", "mod.A", "mod.E"}
    # Call-only forward from B: B, C
    calls = closure(g, ["mod.B"], direction="forward", kinds=["call"])
    assert set(calls.nodes) == {"mod.B", "mod.C"}


def test_invalid_direction_rejected() -> None:
    g = _fixture_graph()
    with pytest.raises(ImpactQueryError):
        closure(g, ["mod.A"], direction="sideways")

"""Tests to ensure QueryExecutor does not leak state across calls.

Regression target:
- Prior implementation stored intermediate bindings on `self` (e.g., `_bindings`).
  That could leak results across subsequent query executions.

These tests validate stateless-per-execution behavior.
"""

import pytest

from ipfs_datasets_py.knowledge_graphs.core.query_executor import GraphEngine, QueryExecutor


class TestQueryExecutorStateless:
    """QueryExecutor should be stateless across independent executions."""

    @pytest.fixture
    def executor_and_engine(self):
        engine = GraphEngine()
        executor = QueryExecutor(graph_engine=engine)

        alice = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        bob = engine.create_node(labels=["Person"], properties={"name": "Bob"})
        engine.create_relationship("KNOWS", alice.id, bob.id)

        return executor, engine

    def test_no_binding_leak_between_ir_operation_runs(self, executor_and_engine):
        """GIVEN a query that produces bindings
        WHEN running a second, unrelated IR operation list
        THEN no bindings/results leak into the second run.

        This calls the internal IR executor directly to precisely exercise
        the binding/union state behavior.
        """

        executor, _engine = executor_and_engine

        ops_with_expand = [
            {"op": "ScanLabel", "label": "Person", "variable": "n"},
            {
                "op": "Expand",
                "from_variable": "n",
                "to_variable": "m",
                "rel_variable": "r",
                "direction": "out",
                "rel_types": ["KNOWS"],
                "target_labels": ["Person"],
            },
            {
                "op": "Project",
                "items": [
                    {"expression": {"property": "n.name"}, "alias": "n_name"},
                    {"expression": {"property": "m.name"}, "alias": "m_name"},
                ],
            },
        ]

        records1 = executor._execute_ir_operations(ops_with_expand, parameters={})
        assert len(records1) >= 1

        # Second run: a Project with no prior Scan/Expand should yield no results.
        ops_project_only = [
            {
                "op": "Project",
                "items": [
                    {"expression": {"property": "n.name"}, "alias": "n_name"},
                    {"expression": {"property": "m.name"}, "alias": "m_name"},
                ],
            }
        ]

        records2 = executor._execute_ir_operations(ops_project_only, parameters={})
        assert records2 == []

    def test_no_union_leak_between_ir_operation_runs(self, executor_and_engine):
        """GIVEN a run that performs a UNION
        WHEN a second run executes without UNION
        THEN UNION state does not leak across calls.
        """

        executor, _engine = executor_and_engine

        ops_union = [
            {"op": "ScanLabel", "label": "Person", "variable": "n"},
            {
                "op": "Project",
                "items": [{"expression": {"property": "n.name"}, "alias": "name"}],
            },
            {"op": "Union", "all": False},
            {"op": "ScanLabel", "label": "Person", "variable": "n"},
            {
                "op": "Project",
                "items": [{"expression": {"property": "n.name"}, "alias": "name"}],
            },
        ]

        records1 = executor._execute_ir_operations(ops_union, parameters={})
        assert len(records1) >= 1

        # Second run: no UNION, and no Scan -> should yield empty
        ops_project_only = [
            {
                "op": "Project",
                "items": [{"expression": {"property": "n.name"}, "alias": "name"}],
            }
        ]

        records2 = executor._execute_ir_operations(ops_project_only, parameters={})
        assert records2 == []

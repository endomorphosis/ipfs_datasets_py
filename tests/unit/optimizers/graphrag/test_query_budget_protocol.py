from __future__ import annotations


def test_query_budget_manager_implements_budget_protocol() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_budget import (
        BudgetManagerProtocol,
        QueryBudgetManager,
    )

    manager = QueryBudgetManager()
    assert isinstance(manager, BudgetManagerProtocol)


def test_unified_optimizer_accepts_custom_budget_manager_protocol() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    class _CustomBudgetManager:
        def __init__(self):
            self.called = False

        def allocate_budget(self, query, priority="normal"):
            self.called = True
            return {"vector_search_ms": 1, "graph_traversal_ms": 2, "ranking_ms": 3, "max_nodes": 4}

        def track_consumption(self, resource, amount):
            return None

        def get_current_consumption_report(self):
            return {"ok": True}

    budget = _CustomBudgetManager()
    optimizer = UnifiedGraphRAGQueryOptimizer(budget_manager=budget)

    plan = optimizer._create_fallback_plan({"query_text": "x"}, priority="low", error="forced")

    assert budget.called is True
    assert plan["budget"]["max_nodes"] == 4


def test_custom_budget_manager_stub_exposes_protocol_methods() -> None:
    class _BudgetStub:
        def allocate_budget(self, query, priority="normal"):
            return {}

        def track_consumption(self, resource, amount):
            return None

        def get_current_consumption_report(self):
            return {}

    stub = _BudgetStub()
    assert hasattr(stub, "allocate_budget")
    assert hasattr(stub, "track_consumption")
    assert hasattr(stub, "get_current_consumption_report")


def test_fallback_plan_uses_default_budget_on_value_error() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    class _ValueErrorBudgetManager:
        def allocate_budget(self, query, priority="normal"):
            raise ValueError("invalid budget settings")

        def track_consumption(self, resource, amount):
            return None

        def get_current_consumption_report(self):
            return {}

    optimizer = UnifiedGraphRAGQueryOptimizer(budget_manager=_ValueErrorBudgetManager())
    plan = optimizer._create_fallback_plan({"query_text": "x"}, priority="normal", error="forced")

    assert plan["budget"]["vector_search_ms"] == 500
    assert plan["budget"]["graph_traversal_ms"] == 1000
    assert plan["budget"]["ranking_ms"] == 100
    assert plan["budget"]["max_nodes"] == 100


def test_fallback_plan_does_not_swallow_base_exception() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import (
        UnifiedGraphRAGQueryOptimizer,
    )

    class _AbortSignal(BaseException):
        pass

    class _InterruptingBudgetManager:
        def allocate_budget(self, query, priority="normal"):
            raise _AbortSignal()

        def track_consumption(self, resource, amount):
            return None

        def get_current_consumption_report(self):
            return {}

    optimizer = UnifiedGraphRAGQueryOptimizer(budget_manager=_InterruptingBudgetManager())

    import pytest

    with pytest.raises(_AbortSignal):
        optimizer._create_fallback_plan({"query_text": "x"}, priority="normal", error="forced")

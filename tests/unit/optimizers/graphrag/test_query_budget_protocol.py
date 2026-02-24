from __future__ import annotations


def test_query_budget_manager_implements_budget_protocol() -> None:
    from ipfs_datasets_py.optimizers.graphrag.query_budget import (
        BudgetManagerProtocol,
        QueryBudgetManager,
    )

    manager = QueryBudgetManager()
    assert isinstance(manager, BudgetManagerProtocol)

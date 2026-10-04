"""Graph query subsystem (v1).

This package implements:
- A small graph-query IR (operators like ScanType/Seed/Expand/Limit)
- A backend adapter protocol (for sharded CAR graphs, IPLD graphs, etc.)
- An executor with strict budgets to prevent blow-ups on large graphs

Frontends (Param/SPARQL/Cypher) compile into this IR.
"""

from .budgets import ExecutionBudgets
from .errors import BudgetExceededError, QueryRejectedError
from .executor import GraphQueryExecutor
from .ir import (
    Expand,
    Limit,
    Project,
    QueryIR,
    ScanType,
    SeedEntities,
)

__all__ = [
    "BudgetExceededError",
    "ExecutionBudgets",
    "Expand",
    "GraphQueryExecutor",
    "Limit",
    "Project",
    "QueryIR",
    "QueryRejectedError",
    "ScanType",
    "SeedEntities",
]

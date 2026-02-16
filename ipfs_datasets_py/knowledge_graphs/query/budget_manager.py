"""
Budget Manager for Graph Query Execution

This module provides a wrapper around the canonical budgets implementation in
search/graph_query/budgets.py. It serves as a compatibility layer and provides
additional budget management utilities for the unified query engine.

The budget system ensures safe execution of graph queries on large graphs by:
- Enforcing timeout limits
- Capping node/edge traversal
- Limiting memory usage
- Controlling backend calls

Usage:
    from ipfs_datasets_py.knowledge_graphs.query.budget_manager import BudgetManager
    from ipfs_datasets_py.search.graph_query.budgets import budgets_from_preset
    
    manager = BudgetManager()
    budgets = budgets_from_preset('moderate')
    
    with manager.track(budgets) as tracker:
        # Execute query within budget constraints
        result = execute_query(...)
        
    # Check if budgets were exceeded
    if tracker.exceeded:
        print(f"Budget exceeded: {tracker.exceeded_reason}")
"""

import time
import logging
from typing import Any, Dict, Optional
from contextlib import contextmanager

# Import canonical budget classes
from ipfs_datasets_py.search.graph_query.budgets import (
    ExecutionBudgets,
    ExecutionCounters,
    budgets_from_preset
)
from ipfs_datasets_py.search.graph_query.errors import BudgetExceededError

logger = logging.getLogger(__name__)


class BudgetTracker:
    """
    Tracks budget usage during query execution.
    
    Attributes:
        counters: ExecutionCounters tracking actual usage
        budgets: ExecutionBudgets defining limits
        started: Start time of execution
        exceeded: Whether budgets were exceeded
        exceeded_reason: Reason for budget exceedance
    """
    
    def __init__(self, budgets: ExecutionBudgets):
        self.budgets = budgets
        self.counters = ExecutionCounters()
        self.started = time.monotonic()
        self.exceeded = False
        self.exceeded_reason: Optional[str] = None
    
    def check_timeout(self) -> None:
        """Check if timeout budget is exceeded."""
        elapsed_ms = int((time.monotonic() - self.started) * 1000)
        if elapsed_ms > self.budgets.timeout_ms:
            self.exceeded = True
            self.exceeded_reason = f"Timeout exceeded: {elapsed_ms}ms > {self.budgets.timeout_ms}ms"
            raise BudgetExceededError.exceeded(
                "timeout_ms", 
                actual=elapsed_ms, 
                limit=self.budgets.timeout_ms, 
                unit="ms"
            )
    
    def check_nodes(self) -> None:
        """Check if node visit budget is exceeded."""
        if self.counters.nodes_visited > self.budgets.max_nodes_visited:
            self.exceeded = True
            self.exceeded_reason = f"Max nodes exceeded: {self.counters.nodes_visited} > {self.budgets.max_nodes_visited}"
            raise BudgetExceededError.exceeded(
                "max_nodes_visited",
                actual=self.counters.nodes_visited,
                limit=self.budgets.max_nodes_visited
            )
    
    def check_edges(self) -> None:
        """Check if edge scan budget is exceeded."""
        if self.counters.edges_scanned > self.budgets.max_edges_scanned:
            self.exceeded = True
            self.exceeded_reason = f"Max edges exceeded: {self.counters.edges_scanned} > {self.budgets.max_edges_scanned}"
            raise BudgetExceededError.exceeded(
                "max_edges_scanned",
                actual=self.counters.edges_scanned,
                limit=self.budgets.max_edges_scanned
            )
    
    def check_depth(self) -> None:
        """Check if depth budget is exceeded."""
        if self.counters.depth > self.budgets.max_depth:
            self.exceeded = True
            self.exceeded_reason = f"Max depth exceeded: {self.counters.depth} > {self.budgets.max_depth}"
            raise BudgetExceededError.exceeded(
                "max_depth",
                actual=self.counters.depth,
                limit=self.budgets.max_depth
            )
    
    def check_all(self) -> None:
        """Check all budgets."""
        self.check_timeout()
        self.check_nodes()
        self.check_edges()
        self.check_depth()
    
    def increment_nodes(self, count: int = 1) -> None:
        """Increment node visit counter and check budget."""
        self.counters.nodes_visited += count
        self.check_nodes()
    
    def increment_edges(self, count: int = 1) -> None:
        """Increment edge scan counter and check budget."""
        self.counters.edges_scanned += count
        self.check_edges()
    
    def increment_depth(self, count: int = 1) -> None:
        """Increment depth counter and check budget."""
        self.counters.depth += count
        self.check_depth()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get execution statistics."""
        elapsed_ms = int((time.monotonic() - self.started) * 1000)
        return {
            "elapsed_ms": elapsed_ms,
            "nodes_visited": self.counters.nodes_visited,
            "edges_scanned": self.counters.edges_scanned,
            "depth": self.counters.depth,
            "shards_touched": self.counters.shards_touched,
            "exceeded": self.exceeded,
            "exceeded_reason": self.exceeded_reason,
            "budgets": {
                "timeout_ms": self.budgets.timeout_ms,
                "max_nodes_visited": self.budgets.max_nodes_visited,
                "max_edges_scanned": self.budgets.max_edges_scanned,
                "max_depth": self.budgets.max_depth,
            }
        }


class BudgetManager:
    """
    Manages budget tracking for graph query execution.
    
    This class provides a context manager interface for tracking budget usage
    during query execution. It wraps the canonical budget implementation from
    search/graph_query/budgets.py and provides additional utilities.
    
    Usage:
        manager = BudgetManager()
        budgets = budgets_from_preset('moderate')
        
        with manager.track(budgets) as tracker:
            # Execute query
            tracker.increment_nodes(10)
            tracker.increment_edges(50)
            
        print(tracker.get_stats())
    """
    
    def __init__(self):
        self.current_tracker: Optional[BudgetTracker] = None
    
    @contextmanager
    def track(self, budgets: ExecutionBudgets):
        """
        Context manager for tracking budget usage.
        
        Args:
            budgets: ExecutionBudgets defining limits
            
        Yields:
            BudgetTracker for tracking usage
            
        Example:
            with manager.track(budgets) as tracker:
                # Execute query
                tracker.increment_nodes(10)
        """
        tracker = BudgetTracker(budgets)
        self.current_tracker = tracker
        try:
            yield tracker
        finally:
            self.current_tracker = None
    
    def create_preset_budgets(
        self, 
        preset: str = 'safe',
        max_results: int = 100,
        **overrides
    ) -> ExecutionBudgets:
        """
        Create budgets from a preset with optional overrides.
        
        Args:
            preset: Preset name ('strict', 'moderate', 'permissive')
            max_results: Maximum number of results
            **overrides: Additional budget overrides
            
        Returns:
            ExecutionBudgets instance
            
        Example:
            budgets = manager.create_preset_budgets(
                'moderate',
                max_results=50,
                overrides={'max_depth': 4}
            )
        """
        return budgets_from_preset(
            preset,
            max_results=max_results,
            overrides=overrides if overrides else None
        )


# Re-export canonical classes for convenience
__all__ = [
    'BudgetManager',
    'BudgetTracker',
    'ExecutionBudgets',
    'ExecutionCounters',
    'budgets_from_preset',
    'BudgetExceededError',
]

"""Agentic optimization framework for recursive self-improvement.

This module provides the infrastructure for LLM-based agents to optimize
the codebase using various methodologies including adversarial, actor-critic,
test-driven, and chaos engineering approaches.

The framework supports two change control methods:
1. GitHub Issues + Draft PRs with API caching
2. Patch-based system with git worktrees and IPFS CIDs
"""

from .base import (
    AgenticOptimizer,
    OptimizationTask,
    OptimizationResult,
    ChangeControlMethod,
)

__all__ = [
    # Base classes
    "AgenticOptimizer",
    "OptimizationTask",
    "OptimizationResult",
    "ChangeControlMethod",
]

"""Typed result for optimizer runs.

Provides a shared return shape across optimizer implementations while
remaining backward compatible with dict-based results.
"""

from typing import Any, Dict, TypedDict


class OptimizerResult(TypedDict, total=False):
    """Common result fields returned by optimizers."""

    artifact: Any
    score: float
    iterations: int
    valid: bool
    execution_time: float
    execution_time_ms: float
    metrics: Dict[str, Any]
    feedback: Any
    metadata: Dict[str, Any]

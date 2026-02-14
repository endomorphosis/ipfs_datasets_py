"""Common optimizer framework for all optimizer types.

This module provides shared base classes and interfaces that enable code reuse
across agentic, logic theorem, and GraphRAG optimizers.

The framework follows a consistent pipeline:
    Data → Generator → Critic → Optimizer → Session → Harness → Result

All optimizer types (agentic, logic_theorem, graphrag) can extend these bases
to benefit from:
- Unified LLM integration
- Common metrics collection
- Shared visualization framework
- Distributed processing support
- Consistent interfaces and patterns
"""

from .base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
    OptimizationStrategy,
)

__all__ = [
    # Base classes
    "BaseOptimizer",
    "OptimizerConfig",
    "OptimizationContext",
    "OptimizationStrategy",
]

__version__ = "0.1.0"

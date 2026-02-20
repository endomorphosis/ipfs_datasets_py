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

from .base_critic import (
    BaseCritic,
    CriticResult,
)

from .base_session import (
    BaseSession,
    RoundRecord,
)

from .base_harness import (
    BaseHarness,
    HarnessConfig,
)

from .exceptions import (
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
)

from .performance import (
    CacheEntry,
    LLMCache,
    cached_llm_call,
    ParallelValidator,
    PerformanceMetrics,
    profile_optimizer,
    BatchFileProcessor,
    get_global_cache,
)

from .performance_monitor import (
    OptimizationCycleMetrics,
    PerformanceMetricsCollector,
    PerformanceDashboard,
    get_global_collector,
    set_global_collector,
)

__all__ = [
    # Base classes
    "BaseOptimizer",
    "OptimizerConfig",
    "OptimizationContext",
    "OptimizationStrategy",
    # Critic
    "BaseCritic",
    "CriticResult",
    # Session
    "BaseSession",
    "RoundRecord",
    # Harness
    "BaseHarness",
    "HarnessConfig",
    # Exceptions
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
    # Performance utilities
    "CacheEntry",
    "LLMCache",
    "cached_llm_call",
    "ParallelValidator",
    "PerformanceMetrics",
    "profile_optimizer",
    "BatchFileProcessor",
    "get_global_cache",
    # Performance monitoring
    "OptimizationCycleMetrics",
    "PerformanceMetricsCollector",
    "PerformanceDashboard",
    "get_global_collector",
    "set_global_collector",
]

__version__ = "0.1.0"

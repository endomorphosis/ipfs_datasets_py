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

Unified OptimizerConfig
---------------------------
BaseOptimizer now uses the unified OptimizerConfig (from optimizer_config.py)
internally, providing consistent configuration across all optimizer types.
For backward compatibility, the deprecated OptimizerConfig in base_optimizer.py
is maintained and automatically converted to the unified format via config_adapter.

New code should use:
    >>> from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
    >>> config = OptimizerConfig(domain='legal', max_rounds=5)

Legacy code can continue using the old interface:
    >>> from ipfs_datasets_py.optimizers.common import OptimizerConfig
    >>> config = OptimizerConfig(strategy=OptimizationStrategy.SGD, max_iterations=10)

Unified Extraction Contexts
---------------------------
To standardize configuration across optimizer types, this framework provides
a hierarchy of typed extraction config dataclasses:

- BaseExtractionConfig: Common fields (confidence_threshold, domain, etc.)
- GraphRAGExtractionConfig: Adds window_size, include_properties, domain_vocab
- LogicExtractionConfig: Adds extraction_mode, formalism_hint, prover_list
- AgenticExtractionConfig: Adds optimization_method, validation_level, change_control_method

These replace legacy dict-based configs and provide IDE support, validation,
and to_dict/from_dict serialization for backward compatibility.

Example:
    >>> from ipfs_datasets_py.optimizers.common import GraphRAGExtractionConfig
    >>> config = GraphRAGExtractionConfig(
    ...     confidence_threshold=0.7,
    ...     domain='legal',
    ...     min_entity_length=3
    ... )
"""

from .base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
    OptimizationStrategy,
)
from .lifecycle_hooks import LifecycleHooksMixin

from .optimizer_config import (
    OptimizerConfig as UnifiedOptimizerConfig,
)

from .config_adapter import (
    convert_to_unified_config,
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
    ExternalServiceError,
    OptimizerTimeoutError,
    RetryableBackendError,
    CircuitBreakerOpenError,
    RateLimitError,
    AuthenticationError,
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

from .optimizer_result import (
    OptimizerResult,
)
from .performance_monitor import (
    OptimizationCycleMetrics,
    PerformanceMetricsCollector,
    PerformanceDashboard,
    get_global_collector,
    set_global_collector,
)

from .extraction_contexts import (
    BaseExtractionConfig,
    GraphRAGExtractionConfig,
    LogicExtractionConfig,
    ExtractionMode,
    AgenticExtractionConfig,
    OptimizationMethod,
)

from .backend_selection import (
    BackendResolution,
    canonicalize_provider,
    detect_provider_from_environment,
    default_model_for_provider,
    resolve_backend_settings,
)
from .backend_resilience import (
    BackendCallPolicy,
    execute_with_resilience,
)
from .seed_control import (
    apply_deterministic_seed,
)

from .metrics_prometheus import (
    get_global_prometheus_metrics,
)
from .unified_config import (
    DomainType,
    BaseContext,
    GraphRAGContext,
    LogicContext,
    AgenticContext,
    create_context,
    domain_type_from_value,
    ensure_shared_context_metadata,
    ensure_shared_backend_config,
    supported_backend_config_source_aliases,
    backend_config_from_constructor_kwargs,
    context_from_optimization_context,
    context_from_ontology_generation_context,
)

__all__ = [
    # Base classes
    "BaseOptimizer",
    "LifecycleHooksMixin",
    "OptimizerConfig",
    "OptimizationContext",
    "OptimizationStrategy",
    # Unified configuration (new)
    "UnifiedOptimizerConfig",
    "convert_to_unified_config",
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
    "ExternalServiceError",
    "OptimizerTimeoutError",
    "RetryableBackendError",
    "CircuitBreakerOpenError",
    "RateLimitError",
    "AuthenticationError",
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
    # Result types
    "OptimizerResult",
    # Unified extraction contexts
    "BaseExtractionConfig",
    "GraphRAGExtractionConfig",
    "LogicExtractionConfig",
    "ExtractionMode",
    "AgenticExtractionConfig",
    "OptimizationMethod",
    # Backend selection
    "BackendResolution",
    "canonicalize_provider",
    "detect_provider_from_environment",
    "default_model_for_provider",
    "resolve_backend_settings",
    "BackendCallPolicy",
    "execute_with_resilience",
    # Seed control
    "apply_deterministic_seed",
    "get_global_prometheus_metrics",
    # Unified context types/adapters
    "DomainType",
    "BaseContext",
    "GraphRAGContext",
    "LogicContext",
    "AgenticContext",
    "create_context",
    "domain_type_from_value",
    "ensure_shared_context_metadata",
    "ensure_shared_backend_config",
    "supported_backend_config_source_aliases",
    "backend_config_from_constructor_kwargs",
    "context_from_optimization_context",
    "context_from_ontology_generation_context",
]

__version__ = "0.1.0"

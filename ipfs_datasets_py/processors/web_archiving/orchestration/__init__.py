"""Orchestration components for unified web archiving execution."""

from .executor import SearchExecutionResult, SearchExecutor
from .planner import SearchExecutionPlan, SearchPlanner
from .resilience import (
    CircuitBreakerConfig,
    CircuitBreakerRecord,
    CircuitBreakerRegistry,
    CircuitState,
    RetryPolicy,
    execute_with_retry,
)
from .scoring import (
    DEFAULT_TARGETS_BY_MODE,
    DEFAULT_WEIGHTS_BY_MODE,
    ProviderScore,
    ProviderScorer,
    ScoringTargets,
    ScoringWeights,
)

__all__ = [
    "DEFAULT_TARGETS_BY_MODE",
    "DEFAULT_WEIGHTS_BY_MODE",
    "CircuitBreakerConfig",
    "CircuitBreakerRecord",
    "CircuitBreakerRegistry",
    "CircuitState",
    "SearchExecutionPlan",
    "SearchExecutionResult",
    "SearchExecutor",
    "SearchPlanner",
    "RetryPolicy",
    "ProviderScore",
    "ProviderScorer",
    "ScoringTargets",
    "ScoringWeights",
    "execute_with_retry",
]

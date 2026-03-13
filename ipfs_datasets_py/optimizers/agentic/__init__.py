"""Agentic optimization framework for recursive self-improvement.

This module provides the infrastructure for LLM-based agents to optimize
the codebase using various methodologies including adversarial, actor-critic,
test-driven, and chaos engineering approaches.

The framework supports two change control methods:
1. GitHub Issues + Draft PRs with API caching
2. Patch-based system with git worktrees and IPFS CIDs
"""

__version__ = "0.2.0"

from .base import (
    AgenticOptimizer,
    ChangeController,
    ChangeControlMethod,
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
    ValidationResult,
)
from .coordinator import (
    AgentCoordinator,
    AgentState,
    AgentStatus,
    ConflictResolver,
)
from .methods import (
    TestDrivenOptimizer,
    AdversarialOptimizer,
    Solution,
    BenchmarkResult,
    ActorCriticOptimizer,
    Policy,
    CriticFeedback,
    ChaosEngineeringOptimizer,
    ChaosOptimizer,
    FaultType,
    FaultInjection,
    ChaosTestResult,
    Vulnerability,
    ResilienceReport,
)
from .patch_control import (
    IPFSPatchStore,
    Patch,
    PatchBasedChangeController,
    PatchManager,
    WorktreeManager,
)
from .validation import (
    OptimizationValidator,
    ValidationLevel,
    DetailedValidationResult,
    SyntaxValidator,
    TypeValidator,
    TestValidator,
    PerformanceValidator,
    SecurityValidator,
    StyleValidator,
)
from .llm_integration import (
    OptimizerLLMRouter,
    LLMProvider,
    ProviderCapability,
    PROVIDER_CAPABILITIES,
)
from .production_hardening import (
    SecurityConfig,
    InputSanitizer,
    SandboxExecutor,
    CircuitBreaker,
    RetryHandler,
    ResourceMonitor,
    get_security_config,
    get_input_sanitizer,
    get_sandbox_executor,
)

from .exceptions import (
    AgenticError,
    OptimizerError,
    ExtractionError,
    ValidationError,
    ProvingError,
    RefinementError,
    ConfigurationError,
)
from .refinement_control_loop import (
    RefinementControlLoop,
    ControlLoopConfig,
    RefinementIteration,
    BatchRefinementController,
)


_LAZY_EXPORTS = {
    # Deprecated GitHub integration symbols (kept for compatibility)
    "UnifiedGitHubAPICache": (".github_api_unified", "UnifiedGitHubAPICache"),
    "GitHubAPICache": (".github_api_unified", "GitHubAPICache"),
    "GitHubAPICounter": (".github_api_unified", "GitHubAPICounter"),
    "CacheBackend": (".github_api_unified", "CacheBackend"),
    "CacheEntry": (".github_api_unified", "CacheEntry"),
    "APICallRecord": (".github_api_unified", "APICallRecord"),
    "GitHubChangeController": (".github_control", "GitHubChangeController"),
}


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value

__all__ = [
    # Base classes
    "AgenticOptimizer",
    "ChangeController",
    "ChangeControlMethod",
    "OptimizationMethod",
    "OptimizationResult",
    "OptimizationTask",
    "ValidationResult",
    # Coordination
    "AgentCoordinator",
    "AgentState",
    "AgentStatus",
    "ConflictResolver",
    # GitHub API (Unified)
    "UnifiedGitHubAPICache",
    "GitHubAPICache",  # Backward compatibility
    "GitHubAPICounter",  # Backward compatibility
    "CacheBackend",
    "CacheEntry",
    "APICallRecord",
    # Change control
    "GitHubChangeController",
    "PatchBasedChangeController",
    "PatchManager",
    "WorktreeManager",
    "IPFSPatchStore",
    "Patch",
    # Optimization methods
    "TestDrivenOptimizer",
    "AdversarialOptimizer",
    "Solution",
    "BenchmarkResult",
    "ActorCriticOptimizer",
    "Policy",
    "CriticFeedback",
    "ChaosEngineeringOptimizer",
    "ChaosOptimizer",
    "FaultType",
    "FaultInjection",
    "ChaosTestResult",
    "Vulnerability",
    "ResilienceReport",
    # Validation
    "OptimizationValidator",
    "ValidationLevel",
    "DetailedValidationResult",
    "SyntaxValidator",
    "TypeValidator",
    "TestValidator",
    "PerformanceValidator",
    "SecurityValidator",
    "StyleValidator",
    # LLM Integration
    "OptimizerLLMRouter",
    "LLMProvider",
    "ProviderCapability",
    "PROVIDER_CAPABILITIES",
    # Production Hardening
    "SecurityConfig",
    "InputSanitizer",
    "SandboxExecutor",
    "CircuitBreaker",
    "RetryHandler",
    "ResourceMonitor",
    "get_security_config",
    "get_input_sanitizer",
    "get_sandbox_executor",
    # Exceptions
    "AgenticError",
    "OptimizerError",
    "ExtractionError",
    "ValidationError",
    "ProvingError",
    "RefinementError",
    "ConfigurationError",
    # Refinement Control
    "RefinementControlLoop",
    "ControlLoopConfig",
    "RefinementIteration",
    "BatchRefinementController",
]

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
from .github_api_unified import (
    UnifiedGitHubAPICache,
    GitHubAPICache,  # Backward compatibility alias
    GitHubAPICounter,  # Backward compatibility alias
    CacheBackend,
    CacheEntry,
    APICallRecord,
)
from .github_control import GitHubChangeController
from .methods import (
    TestDrivenOptimizer,
    AdversarialOptimizer,
    ActorCriticOptimizer,
    Policy,
    ChaosEngineeringOptimizer,
    FaultType,
    FaultInjection,
    ChaosTestResult,
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
    "ActorCriticOptimizer",
    "Policy",
    "ChaosEngineeringOptimizer",
    "FaultType",
    "FaultInjection",
    "ChaosTestResult",
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
]

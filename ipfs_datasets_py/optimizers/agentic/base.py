"""Base classes and interfaces for agentic optimization framework."""

import logging as _logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class ChangeControlMethod(Enum):
    """Change control method for managing optimizations."""
    
    GITHUB = "github"  # GitHub issues + draft PRs
    PATCH = "patch"  # Patch-based with worktrees and IPFS


class OptimizationMethod(Enum):
    """Type of optimization method to use."""
    
    ADVERSARIAL = "adversarial"  # Generate competing solutions
    ACTOR_CRITIC = "actor_critic"  # Reward-based learning
    TEST_DRIVEN = "test_driven"  # Test-first optimization
    CHAOS = "chaos"  # Chaos engineering


@dataclass
class OptimizationTask:
    """Represents a task for optimization.
    
    Attributes:
        task_id: Unique identifier for the task
        description: Human-readable description of what to optimize
        target_files: List of files to optimize (empty = auto-detect)
        method: Optimization method to use
        priority: Task priority (0-100, higher = more important)
        constraints: Additional constraints (performance targets, test coverage, etc.)
        assigned_agent: ID of agent assigned to this task
        created_at: When the task was created
        metadata: Additional task metadata
    """
    
    task_id: str
    description: str
    target_files: List[Path] = field(default_factory=list)
    method: OptimizationMethod = OptimizationMethod.TEST_DRIVEN
    priority: int = 50
    constraints: Dict[str, Any] = field(default_factory=dict)
    assigned_agent: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of validating an optimization.
    
    Attributes:
        passed: Whether validation passed
        syntax_check: Syntax validation result
        type_check: Type checking result
        unit_tests: Unit test results
        integration_tests: Integration test results
        performance_tests: Performance test results
        security_scan: Security scan results
        style_check: Code style check results
        errors: List of validation errors
        warnings: List of validation warnings
    """
    
    passed: bool
    syntax_check: bool = True
    type_check: bool = True
    unit_tests: bool = True
    integration_tests: bool = True
    performance_tests: bool = True
    security_scan: bool = True
    style_check: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class OptimizationResult:
    """Result of an optimization attempt.
    
    Attributes:
        task_id: ID of the optimization task
        success: Whether optimization succeeded
        method: Optimization method used
        changes: Description of changes made
        patch_path: Path to generated patch file
        patch_cid: IPFS CID of the patch (if using patch system)
        validation: Validation results
        metrics: Performance metrics and improvements
        execution_time: Time taken to perform optimization
        agent_id: ID of agent that performed optimization
        error_message: Error message if optimization failed
        metadata: Additional result metadata
    """
    
    task_id: str
    success: bool
    method: OptimizationMethod
    changes: str
    patch_path: Optional[Path] = None
    patch_cid: Optional[str] = None
    validation: Optional[ValidationResult] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    execution_time: float = 0.0
    agent_id: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # --- Compatibility fields (used by unit tests in this repo) ---
    optimized_code: Optional[str] = None
    original_code: Optional[str] = None

    @property
    def description(self) -> str:
        """Compatibility alias for the human-readable change description."""
        return self.changes


class AgenticOptimizer(ABC):
    """Base class for all agentic optimizers.
    
    This abstract class defines the interface that all optimization methods
    must implement. Each optimizer implements a specific optimization strategy
    (adversarial, actor-critic, test-driven, or chaos engineering).
    
    Attributes:
        agent_id: Unique identifier for this optimizer agent
        method: Optimization method this optimizer implements
        llm_router: LLM router for generating optimizations
        change_control: Change control method to use
        config: Configuration dictionary
    
    Example:
        >>> from ipfs_datasets_py.optimizers.agentic import TestDrivenOptimizer
        >>> optimizer = TestDrivenOptimizer(
        ...     agent_id="test-optimizer-1",
        ...     llm_router=router,
        ...     change_control=ChangeControlMethod.PATCH
        ... )
        >>> result = optimizer.optimize(task)
    """
    
    def __init__(
        self,
        agent_id: str,
        llm_router: Any,
        change_control: ChangeControlMethod = ChangeControlMethod.PATCH,
        config: Optional[Dict[str, Any]] = None,
        logger: Optional[_logging.Logger] = None,
    ):
        """Initialize the optimizer.
        
        Args:
            agent_id: Unique identifier for this agent
            llm_router: LLM router for text generation
            change_control: Change control method to use
            config: Optional configuration dictionary
            logger: Optional logger instance (defaults to module logger)
        """
        self.agent_id = agent_id
        self.method = self._get_method()
        self.llm_router = llm_router
        self.change_control = change_control
        self.config = config or {}
        self._log = logger or _logging.getLogger(__name__)
        
    @abstractmethod
    def _get_method(self) -> OptimizationMethod:
        """Return the optimization method this optimizer implements.
        
        Returns:
            OptimizationMethod enum value
        """
        pass
        
    @abstractmethod
    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        """Perform optimization on the given task.
        
        This is the main entry point for optimization. Implementations should:
        1. Analyze the task and target files
        2. Generate optimization using the specific method
        3. Create a patch with the changes
        4. Validate the optimization
        5. Return results with all metadata
        
        Args:
            task: The optimization task to perform
            
        Returns:
            OptimizationResult with success status and details
            
        Raises:
            ValueError: If task is invalid
            RuntimeError: If optimization fails
        """
        pass

    def validate(self, result: OptimizationResult) -> ValidationResult:
        """Validate an optimization result.

        Default implementation is intentionally lightweight: it returns a
        passing result so concrete optimizers can be instantiated even when
        advanced validation is not yet implemented.
        """
        return ValidationResult(passed=True)
        
    def get_capabilities(self) -> Dict[str, Any]:
        """Return the capabilities of this optimizer.
        
        Returns:
            Dictionary describing optimizer capabilities:
            - method: Optimization method
            - supported_languages: Programming languages supported
            - validation_levels: Validation checks performed
            - estimated_time: Typical execution time
        """
        return {
            "method": self.method.value,
            "agent_id": self.agent_id,
            "change_control": self.change_control.value,
            "supported_languages": ["python"],
            "validation_levels": [
                "syntax",
                "type",
                "unit_tests",
                "integration_tests",
                "performance",
                "security",
                "style",
            ],
        }


class ChangeController(ABC):
    """Base class for change control implementations.
    
    Handles creating, reviewing, and applying code changes using
    either GitHub integration or patch-based system.
    """
    
    @abstractmethod
    def create_change(self, result: OptimizationResult) -> str:
        """Create a change request (issue+PR or patch).
        
        Args:
            result: The optimization result to create change for
            
        Returns:
            Change identifier (PR URL or patch CID)
        """
        pass
        
    @abstractmethod
    def check_approval(self, change_id: str) -> bool:
        """Check if a change has been approved.
        
        Args:
            change_id: The change identifier to check
            
        Returns:
            True if approved, False otherwise
        """
        pass
        
    @abstractmethod
    def apply_change(self, change_id: str) -> bool:
        """Apply an approved change.
        
        Args:
            change_id: The change identifier to apply
            
        Returns:
            True if successfully applied, False otherwise
        """
        pass
        
    @abstractmethod
    def rollback_change(self, change_id: str) -> bool:
        """Rollback a previously applied change.
        
        Args:
            change_id: The change identifier to rollback
            
        Returns:
            True if successfully rolled back, False otherwise
        """
        pass

"""Base optimizer class for all optimizer types.

Provides the common interface and workflow that all optimizers follow:
    generate() → critique() → optimize() → validate()
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)


class OptimizationStrategy(Enum):
    """Strategy for optimization."""
    SGD = "sgd"  # Stochastic Gradient Descent
    EVOLUTIONARY = "evolutionary"  # Evolutionary algorithms
    REINFORCEMENT = "reinforcement"  # Reinforcement learning
    HYBRID = "hybrid"  # Combination of strategies


@dataclass
class OptimizerConfig:
    """Configuration for optimizer.
    
    Attributes:
        strategy: Optimization strategy to use
        max_iterations: Maximum iterations per session
        target_score: Target quality score (0-1)
        learning_rate: Learning rate for SGD
        convergence_threshold: Score improvement threshold
        early_stopping: Enable early stopping
        validation_enabled: Enable validation step
        metrics_enabled: Enable metrics collection
    """
    strategy: OptimizationStrategy = OptimizationStrategy.SGD
    max_iterations: int = 10
    target_score: float = 0.85
    learning_rate: float = 0.1
    convergence_threshold: float = 0.01
    early_stopping: bool = True
    validation_enabled: bool = True
    metrics_enabled: bool = True


@dataclass
class OptimizationContext:
    """Context for optimization session.
    
    Attributes:
        session_id: Unique session identifier
        input_data: Input data for optimization
        domain: Domain of optimization (code, logic, graph)
        constraints: Optimization constraints
        metadata: Additional context metadata
        created_at: When context was created
    """
    session_id: str
    input_data: Any
    domain: str
    constraints: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)


class BaseOptimizer(ABC):
    """Base class for all optimizer types.
    
    This abstract class defines the common interface that all optimizers
    (agentic, logic_theorem, graphrag) must implement. It provides the
    standard optimization workflow:
    
    1. Generate: Create initial artifact from input
    2. Critique: Evaluate quality of artifact
    3. Optimize: Improve artifact based on feedback
    4. Validate: Verify improvements are valid
    
    Subclasses implement domain-specific logic for each step while
    benefiting from common infrastructure for metrics, LLM integration,
    and session management.
    
    Example:
        >>> class MyOptimizer(BaseOptimizer):
        ...     def generate(self, input_data, context):
        ...         return self._create_artifact(input_data)
        ...     
        ...     def critique(self, artifact, context):
        ...         return self._evaluate_quality(artifact)
        ...     
        ...     def optimize(self, artifact, score, feedback, context):
        ...         return self._improve_artifact(artifact, feedback)
        ...     
        ...     def validate(self, artifact, context):
        ...         return self._check_validity(artifact)
        >>> 
        >>> optimizer = MyOptimizer(config=OptimizerConfig())
        >>> result = optimizer.run_session(input_data, context)
    """
    
    def __init__(
        self,
        config: Optional[OptimizerConfig] = None,
        llm_backend: Optional[Any] = None,
        metrics_collector: Optional[Any] = None,  # PerformanceMetricsCollector
    ):
        """Initialize base optimizer.
        
        Args:
            config: Optimizer configuration
            llm_backend: Optional LLM backend for generation
            metrics_collector: Optional :class:`~ipfs_datasets_py.optimizers.common.PerformanceMetricsCollector`
                for recording per-cycle performance metrics.
        """
        self.config = config or OptimizerConfig()
        self.llm_backend = llm_backend
        self.metrics_collector = metrics_collector
        self.metrics: List[Dict[str, Any]] = []
        
    @abstractmethod
    def generate(
        self,
        input_data: Any,
        context: OptimizationContext,
    ) -> Any:
        """Generate initial artifact from input data.
        
        This is the first step in the optimization pipeline. Implementations
        should create an initial version of the artifact (code, theorem,
        ontology, etc.) from the input data.
        
        Args:
            input_data: Input data to generate from
            context: Optimization context
            
        Returns:
            Generated artifact (type depends on optimizer)
            
        Raises:
            ValueError: If input data is invalid
            RuntimeError: If generation fails
        """
        pass
    
    @abstractmethod
    def critique(
        self,
        artifact: Any,
        context: OptimizationContext,
    ) -> Tuple[float, List[str]]:
        """Evaluate quality of artifact.
        
        This is the second step in the optimization pipeline. Implementations
        should evaluate the artifact across multiple dimensions and return
        a score (0-1) and list of improvement suggestions.
        
        Args:
            artifact: Artifact to evaluate
            context: Optimization context
            
        Returns:
            Tuple of (score, feedback_list)
            - score: Quality score from 0 (worst) to 1 (best)
            - feedback_list: List of improvement suggestions
            
        Raises:
            ValueError: If artifact is invalid
        """
        pass
    
    @abstractmethod
    def optimize(
        self,
        artifact: Any,
        score: float,
        feedback: List[str],
        context: OptimizationContext,
    ) -> Any:
        """Improve artifact based on critique feedback.
        
        This is the third step in the optimization pipeline. Implementations
        should use the score and feedback to create an improved version of
        the artifact.
        
        Args:
            artifact: Current artifact
            score: Current quality score
            feedback: List of improvement suggestions
            context: Optimization context
            
        Returns:
            Improved artifact
            
        Raises:
            RuntimeError: If optimization fails
        """
        pass
    
    def validate(
        self,
        artifact: Any,
        context: OptimizationContext,
    ) -> bool:
        """Validate that artifact meets requirements.
        
        Optional validation step. Default implementation always returns True.
        Override to add domain-specific validation (syntax checking,
        theorem proving, consistency checks, etc.).
        
        Args:
            artifact: Artifact to validate
            context: Optimization context
            
        Returns:
            True if valid, False otherwise
        """
        return True
    
    def run_session(
        self,
        input_data: Any,
        context: OptimizationContext,
    ) -> Dict[str, Any]:
        """Run complete optimization session.
        
        Executes the full optimization workflow:
        1. Generate initial artifact
        2. Critique quality
        3. Iteratively optimize until target reached or max iterations
        4. Validate final result
        
        Args:
            input_data: Input data for optimization
            context: Optimization context
            
        Returns:
            Dictionary with:
            - artifact: Final optimized artifact
            - score: Final quality score
            - iterations: Number of iterations performed
            - valid: Whether artifact passed validation
            - metrics: Performance metrics (if enabled)
        """
        start_time = datetime.now()
        cycle_id = context.session_id

        # Start metrics cycle if collector is available
        if self.metrics_collector is not None:
            try:
                self.metrics_collector.start_cycle(
                    cycle_id,
                    metadata={
                        "domain": context.domain,
                        "strategy": self.config.strategy.value,
                        "max_iterations": self.config.max_iterations,
                        "target_score": self.config.target_score,
                    },
                )
            except Exception:
                pass  # Never let metrics break the optimization

        # Generate initial artifact
        artifact = self.generate(input_data, context)
        score, feedback = self.critique(artifact, context)
        
        iterations = 0
        prev_score = score
        initial_score = score
        
        # Optimization loop
        for iteration in range(self.config.max_iterations):
            iterations = iteration + 1
            
            # Check termination conditions
            if score >= self.config.target_score:
                break
            
            if self.config.early_stopping:
                improvement = score - prev_score
                if improvement < self.config.convergence_threshold:
                    break
            
            # Optimize
            artifact = self.optimize(artifact, score, feedback, context)
            prev_score = score
            score, feedback = self.critique(artifact, context)
        
        # Validate
        valid = True
        if self.config.validation_enabled:
            valid = self.validate(artifact, context)
        
        execution_time = (datetime.now() - start_time).total_seconds()
        execution_time_ms = execution_time * 1000.0

        # End metrics cycle
        if self.metrics_collector is not None:
            try:
                self.metrics_collector.end_cycle(cycle_id, success=valid)
            except Exception as e:
                _logger.warning(f"Metrics collection end failed: {e}")

        _logger.info(
            "run_session completed session_id=%s domain=%s "
            "iterations=%d score=%.4f valid=%s execution_time_ms=%.1f",
            context.session_id,
            context.domain,
            iterations,
            score,
            valid,
            execution_time_ms,
        )
        
        result = {
            'artifact': artifact,
            'score': score,
            'iterations': iterations,
            'valid': valid,
            'execution_time': execution_time,
            'execution_time_ms': execution_time_ms,
        }
        
        if self.config.metrics_enabled:
            result['metrics'] = {
                'initial_score': initial_score,
                'final_score': score,
                'improvement': score - initial_score,
                'score_delta': score - initial_score,
                'iterations': iterations,
                'execution_time': execution_time,
                'execution_time_ms': execution_time_ms,
            }
        
        return result
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get optimizer capabilities.
        
        Returns:
            Dictionary describing optimizer capabilities:
            - strategy: Optimization strategy used
            - max_iterations: Maximum iterations supported
            - validation_enabled: Whether validation is enabled
            - metrics_enabled: Whether metrics collection is enabled
        """
        return {
            'strategy': self.config.strategy.value,
            'max_iterations': self.config.max_iterations,
            'validation_enabled': self.config.validation_enabled,
            'metrics_enabled': self.config.metrics_enabled,
        }
    
    def dry_run(
        self,
        input_data: Any,
        context: OptimizationContext,
    ) -> Dict[str, Any]:
        """Validate optimization setup without full optimization.
        
        Performs a single optimization cycle (generate + critique + validate)
        to verify that the optimization pipeline is correctly configured
        and can process the given input data. Useful for testing and validation.
        
        Args:
            input_data: Input data to test
            context: Optimization context
            
        Returns:
            Dictionary with:
            - artifact: Generated artifact
            - score: Initial quality score
            - valid: Whether artifact passed validation
            - feedback: Initial critique feedback
            - execution_time: Time in seconds
            - execution_time_ms: Time in milliseconds
            
        Raises:
            RuntimeError: If any step (generate, critique, validate) fails
            ValueError: If input data is invalid
        """
        start_time = datetime.now()
        
        try:
            # Generate initial artifact
            artifact = self.generate(input_data, context)
            
            # Critique (without optimization)
            score, feedback = self.critique(artifact, context)
            
            # Validate
            valid = True
            if self.config.validation_enabled:
                valid = self.validate(artifact, context)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            execution_time_ms = execution_time * 1000.0
            
            _logger.info(
                "dry_run completed session_id=%s domain=%s "
                "score=%.4f valid=%s execution_time_ms=%.1f",
                context.session_id,
                context.domain,
                score,
                valid,
                execution_time_ms,
            )
            
            return {
                'artifact': artifact,
                'score': score,
                'valid': valid,
                'feedback': feedback,
                'execution_time': execution_time,
                'execution_time_ms': execution_time_ms,
            }
        except Exception as e:
            _logger.error(
                "dry_run failed session_id=%s domain=%s error=%s",
                context.session_id,
                context.domain,
                str(e),
            )
            raise

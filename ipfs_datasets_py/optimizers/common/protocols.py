"""Optimizer and related protocols for type-safe interface definition.

This module defines @runtime_checkable protocols that can be used with
isinstance() checks, enabling runtime type verification for optimizer
implementations across all optimizer types (GraphRAG, LogicTheorem, Agentic).

Protocols define the contract that all optimizers must implement without
requiring inheritance or explicit interface declaration.

Example:
    >>> from ipfs_datasets_py.optimizers.common.protocols import IOptimizer
    >>> from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    >>> 
    >>> optimizer = OntologyGenerator()
    >>> if isinstance(optimizer, IOptimizer):
    ...     print("Valid optimizer implementation")
    >>> else:
    ...     print("Does not implement IOptimizer protocol")
"""

from typing import Protocol, runtime_checkable, Any, Tuple, List, Optional
from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
from ipfs_datasets_py.optimizers.common.base_optimizer import OptimizationContext


@runtime_checkable
class IOptimizer(Protocol):
    """Protocol defining the optimizer interface.
    
    Any class implementing this protocol must provide the four core methods
    of the optimization workflow: generate, critique, optimize, and validate.
    
    The @runtime_checkable decorator enables isinstance() checks at runtime,
    allowing duck-typing validation without explicit inheritance.
    
    Example:
        >>> class MyOptimizer:
        ...     config: OptimizerConfig
        ...     
        ...     def generate(self, input_data, context) -> Any:
        ...         return self._create_artifact(input_data)
        ...     
        ...     def critique(self, artifact, context) -> Tuple[float, List[str]]:
        ...         return 0.85, ["suggestion 1", "suggestion 2"]
        ...     
        ...     def optimize(self, artifact, score, feedback, context) -> Any:
        ...         return self._improve_artifact(artifact, feedback)
        ...     
        ...     def validate(self, artifact, context) -> bool:
        ...         return True
        >>> 
        >>> opt = MyOptimizer()
        >>> isinstance(opt, IOptimizer)  # True
    """
    
    @property
    def config(self) -> OptimizerConfig:
        """Optimizer configuration.
        
        Returns:
            OptimizerConfig instance with optimization parameters
        """
        ...
    
    def generate(
        self,
        input_data: Any,
        context: OptimizationContext,
    ) -> Any:
        """Generate initial artifact from input data.
        
        First step in optimization pipeline. Creates an initial version of
        the artifact (code, theorem, ontology, etc.) from input data.
        
        Args:
            input_data: Input data to generate from
            context: Optimization context (session_id, domain, constraints, etc.)
            
        Returns:
            Generated artifact (type depends on optimizer specialization)
            
        Raises:
            ValueError: If input data is invalid
            RuntimeError: If generation fails
        """
        ...
    
    def critique(
        self,
        artifact: Any,
        context: OptimizationContext,
    ) -> Tuple[float, List[str]]:
        """Evaluate quality of artifact.
        
        Second step in optimization pipeline. Evaluates the artifact across
        multiple dimensions and returns a score plus improvement suggestions.
        
        Args:
            artifact: Artifact to evaluate
            context: Optimization context
            
        Returns:
            Tuple of (score, feedback_list)
            - score: Quality score from 0.0 (worst) to 1.0 (best)
            - feedback_list: List of improvement suggestions (strings)
            
        Raises:
            ValueError: If artifact is invalid
        """
        ...
    
    def optimize(
        self,
        artifact: Any,
        score: float,
        feedback: List[str],
        context: OptimizationContext,
    ) -> Any:
        """Improve artifact based on critique feedback.
        
        Third step in optimization pipeline. Uses the score and feedback
        to create an improved version of the artifact.
        
        Args:
            artifact: Current artifact
            score: Current quality score (0-1)
            feedback: List of improvement suggestions
            context: Optimization context
            
        Returns:
            Improved artifact
            
        Raises:
            RuntimeError: If optimization fails
        """
        ...
    
    def validate(
        self,
        artifact: Any,
        context: OptimizationContext,
    ) -> bool:
        """Validate artifact correctness.
        
        Fourth step in optimization pipeline (optional). Verifies that
        the artifact is valid, syntactically correct, and meets constraints.
        
        Args:
            artifact: Artifact to validate
            context: Optimization context
            
        Returns:
            True if artifact is valid, False otherwise
            
        Raises:
            ValueError: If artifact has structural issues
        """
        ...


@runtime_checkable
class IMetricsCollector(Protocol):
    """Protocol for metrics collection during optimization.
    
    Any metrics collector implementing this protocol can be wired into
    the optimization workflow to track performance, resource usage, or
    custom metrics.
    """
    
    def record_score(self, score: float) -> None:
        """Record optimization score.
        
        Args:
            score: Quality score (0-1)
        """
        ...
    
    def record_round_completion(self) -> None:
        """Record that a round completed."""
        ...
    
    def record_error(self, error_type: str) -> None:
        """Record an error occurred.
        
        Args:
            error_type: Type of error (validation, llm, timeout, etc.)
        """
        ...


@runtime_checkable
class ILLMBackend(Protocol):
    """Protocol for LLM backend implementations.
    
    Supports various LLM providers (OpenAI, HuggingFace, local models)
    through a unified interface.
    """
    
    def generate(
        self,
        prompt: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        """Generate text from LLM.
        
        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-2)
            
        Returns:
            Generated text
        """
        ...
    
    def is_available(self) -> bool:
        """Check if backend is available.
        
        Returns:
            True if ready to use, False otherwise
        """
        ...


@runtime_checkable
class ICache(Protocol):
    """Protocol for caching implementations.
    
    Supports various cache backends (in-memory, Redis, file-based).
    """
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found
        """
        ...
    
    def put(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time-to-live in seconds (None = no expiry)
        """
        ...
    
    def clear(self) -> None:
        """Clear all cache entries."""
        ...

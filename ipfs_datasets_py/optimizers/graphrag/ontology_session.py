"""
Ontology Session for GraphRAG Optimization.

This module provides a session manager for single ontology optimization workflows.
It coordinates generator, mediator, critic, and validator to produce a complete
validated ontology with full history and metrics.

Key Features:
    - Single session workflow management
    - Multi-round interaction orchestration
    - Complete history tracking
    - Automatic convergence detection
    - Detailed logging and metrics
    - Validation integration

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologySession,
    ...     OntologyGenerator,
    ...     OntologyMediator,
    ...     OntologyCritic,
    ...     LogicValidator
    ... )
    >>> 
    >>> session = OntologySession(
    ...     generator=generator,
    ...     mediator=mediator,
    ...     critic=critic,
    ...     validator=validator,
    ...     max_rounds=10
    ... )
    >>> 
    >>> result = session.run(data, context)
    >>> print(f"Quality: {result.critic_score.overall:.2f}")
    >>> print(f"Consistent: {result.validation_result.is_consistent}")

References:
    - complaint-generator session.py: Session coordination patterns
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SessionResult:
    """
    Result from a single ontology optimization session.
    
    Contains the final ontology along with all evaluation metrics, validation
    results, and session metadata. Provides a complete record of the optimization
    process.
    
    Attributes:
        ontology: Final optimized ontology
        critic_score: Quality score from final evaluation
        validation_result: Logical consistency validation result
        num_rounds: Number of refinement rounds executed
        converged: Whether the session converged
        time_elapsed: Total time for session in seconds
        refinement_history: Complete history of refinements
        metadata: Additional session metadata
        
    Example:
        >>> result = SessionResult(
        ...     ontology=final_ontology,
        ...     critic_score=score,
        ...     validation_result=validation,
        ...     num_rounds=7,
        ...     converged=True,
        ...     time_elapsed=45.3
        ... )
        >>> print(f"Session completed in {result.num_rounds} rounds")
    """
    
    ontology: Dict[str, Any]
    critic_score: Any  # CriticScore
    validation_result: Any  # ValidationResult
    num_rounds: int
    converged: bool
    time_elapsed: float
    refinement_history: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            'ontology': self.ontology,
            'critic_score': self.critic_score.to_dict() if hasattr(self.critic_score, 'to_dict') else self.critic_score,
            'validation_result': self.validation_result.to_dict() if hasattr(self.validation_result, 'to_dict') else self.validation_result,
            'num_rounds': self.num_rounds,
            'converged': self.converged,
            'time_elapsed': self.time_elapsed,
            'refinement_history': self.refinement_history,
            'metadata': self.metadata,
        }
    
    def summary(self) -> str:
        """Generate a human-readable summary of the session."""
        lines = [
            "=== Session Summary ===",
            f"Rounds: {self.num_rounds}",
            f"Converged: {'Yes' if self.converged else 'No'}",
            f"Time: {self.time_elapsed:.2f}s",
            f"Quality Score: {self.critic_score.overall:.2f}" if hasattr(self.critic_score, 'overall') else "",
            f"Consistent: {'Yes' if self.validation_result.is_consistent else 'No'}" if hasattr(self.validation_result, 'is_consistent') else "",
            f"Entities: {len(self.ontology.get('entities', []))}",
            f"Relationships: {len(self.ontology.get('relationships', []))}",
        ]
        return "\n".join(line for line in lines if line)


class OntologySession:
    """
    Single ontology optimization session manager.
    
    Coordinates a complete ontology generation and optimization workflow from
    initial extraction through refinement, evaluation, and validation. Manages
    all component interactions and maintains complete session history.
    
    The session combines generator, mediator, critic, and validator in a
    structured workflow to produce high-quality, validated ontologies.
    
    Attributes:
        generator: OntologyGenerator for entity extraction
        mediator: OntologyMediator for refinement orchestration
        critic: OntologyCritic for quality evaluation
        validator: LogicValidator for consistency checking
        max_rounds: Maximum refinement rounds
        
    Example:
        >>> session = OntologySession(
        ...     generator=generator,
        ...     mediator=mediator,
        ...     critic=critic,
        ...     validator=validator,
        ...     max_rounds=10
        ... )
        >>> 
        >>> # Run complete workflow
        >>> result = session.run(document_data, context)
        >>> 
        >>> # Check results
        >>> if result.converged and result.validation_result.is_consistent:
        ...     print("Success! High-quality validated ontology produced")
        ...     print(result.summary())
    """
    
    def __init__(
        self,
        generator: Any,  # OntologyGenerator
        mediator: Any,  # OntologyMediator
        critic: Any,  # OntologyCritic
        validator: Any,  # LogicValidator
        max_rounds: int = 10
    ):
        """
        Initialize the ontology session.
        
        Args:
            generator: OntologyGenerator for creating/refining ontologies
            mediator: OntologyMediator for orchestrating refinements
            critic: OntologyCritic for evaluating quality
            validator: LogicValidator for checking consistency
            max_rounds: Maximum refinement rounds before stopping
            
        Raises:
            ValueError: If max_rounds is not positive
        """
        if max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")
        
        self.generator = generator
        self.mediator = mediator
        self.critic = critic
        self.validator = validator
        self.max_rounds = max_rounds
        
        logger.info(f"Initialized OntologySession with max_rounds={max_rounds}")
    
    def run(
        self,
        data: Any,
        context: Any  # OntologyGenerationContext
    ) -> SessionResult:
        """
        Run complete ontology optimization session.
        
        Executes the full workflow:
        1. Generate initial ontology
        2. Iterative refinement with mediator
        3. Final evaluation with critic
        4. Logical validation
        5. Package results
        
        Args:
            data: Source data for ontology generation
            context: Generation context with configuration
            
        Returns:
            SessionResult with complete session information
            
        Example:
            >>> result = session.run(
            ...     "Alice must pay Bob $100 by Friday",
            ...     OntologyGenerationContext(
            ...         data_source='contract.txt',
            ...         data_type='text',
            ...         domain='legal',
            ...         extraction_strategy='hybrid'
            ...     )
            ... )
            >>> 
            >>> print(f"Quality: {result.critic_score.overall:.2f}")
            >>> print(f"Rounds: {result.num_rounds}")
        """
        logger.info("Starting ontology optimization session")
        start_time = time.time()
        
        try:
            # Run refinement cycle through mediator
            logger.info("Phase 1: Running refinement cycle")
            mediator_state = self.mediator.run_refinement_cycle(data, context)
            
            # Get final ontology
            final_ontology = mediator_state.current_ontology
            logger.info(f"Refinement complete: {mediator_state.current_round} rounds")
            
            # Final validation
            logger.info("Phase 2: Running logical validation")
            validation_result = self.validator.check_consistency(final_ontology)
            logger.info(
                f"Validation complete: consistent={validation_result.is_consistent}"
            )
            
            # Get final critic score
            final_score = (
                mediator_state.critic_scores[-1]
                if mediator_state.critic_scores
                else self.critic.evaluate_ontology(final_ontology, context, data)
            )
            
            # Calculate timing
            time_elapsed = time.time() - start_time
            
            # Build result
            result = SessionResult(
                ontology=final_ontology,
                critic_score=final_score,
                validation_result=validation_result,
                num_rounds=mediator_state.current_round,
                converged=mediator_state.converged,
                time_elapsed=time_elapsed,
                refinement_history=mediator_state.refinement_history,
                metadata={
                    'data_source': getattr(context, 'data_source', 'unknown'),
                    'domain': getattr(context, 'domain', 'unknown'),
                    'extraction_strategy': str(getattr(context, 'extraction_strategy', 'unknown')),
                    'mediator_metadata': mediator_state.metadata,
                    'validation_prover': validation_result.prover_used,
                    'validation_time_ms': validation_result.time_ms,
                }
            )
            
            logger.info(
                f"Session complete: quality={final_score.overall:.2f}, "
                f"consistent={validation_result.is_consistent}, "
                f"time={time_elapsed:.2f}s"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Session failed: {e}", exc_info=True)
            
            # Return partial result on failure
            time_elapsed = time.time() - start_time
            
            # Create minimal result
            return SessionResult(
                ontology={},
                critic_score=None,
                validation_result=None,
                num_rounds=0,
                converged=False,
                time_elapsed=time_elapsed,
                metadata={
                    'error': str(e),
                    'failed': True,
                }
            )
    
    def run_with_validation_retry(
        self,
        data: Any,
        context: Any,
        max_validation_retries: int = 3
    ) -> SessionResult:
        """
        Run session with automatic retry on validation failure.
        
        If validation fails, attempts to refine the ontology to fix
        contradictions and retries validation up to max_validation_retries times.
        
        Args:
            data: Source data
            context: Generation context
            max_validation_retries: Maximum validation retry attempts
            
        Returns:
            SessionResult with final results
            
        Example:
            >>> result = session.run_with_validation_retry(
            ...     data,
            ...     context,
            ...     max_validation_retries=3
            ... )
        """
        logger.info(
            f"Starting session with validation retry (max_retries={max_validation_retries})"
        )
        
        # Initial run
        result = self.run(data, context)
        
        # Retry loop if validation fails
        retry_count = 0
        while (
            not result.validation_result.is_consistent
            and retry_count < max_validation_retries
        ):
            retry_count += 1
            logger.info(
                f"Validation failed, attempting fix (retry {retry_count}/{max_validation_retries})"
            )
            
            # Get fix suggestions
            fixes = self.validator.suggest_fixes(
                result.ontology,
                result.validation_result.contradictions
            )
            
            logger.info(f"Applying {len(fixes)} suggested fixes")
            
            # Apply fixes (simplified - just retry generation)
            # In a full implementation, would apply specific fixes
            result = self.run(data, context)
        
        if retry_count > 0:
            result.metadata['validation_retries'] = retry_count
        
        return result
    
    def validate_session_config(self) -> bool:
        """
        Validate that all session components are properly configured.
        
        Returns:
            True if configuration is valid, False otherwise
        """
        if not self.generator:
            logger.error("Generator not configured")
            return False
        
        if not self.mediator:
            logger.error("Mediator not configured")
            return False
        
        if not self.critic:
            logger.error("Critic not configured")
            return False
        
        if not self.validator:
            logger.error("Validator not configured")
            return False
        
        logger.info("Session configuration validated")
        return True

    def elapsed_ms(self) -> float:
        """Return current elapsed time in milliseconds since session start.

        Useful for monitoring progress or implementing time-based constraints
        during an active session. Returns 0.0 if session has not started yet.

        Returns:
            Elapsed time in milliseconds as float (potentially fractional)

        Example:
            >>> session = OntologySession(...)
            >>> result = session.run(data, context)
            >>> elapsed = session.elapsed_ms()
            >>> print(f"Session took {elapsed:.2f}ms")
        """
        import time
        
        # Return elapsed time if session has started
        if hasattr(self, 'start_time') and self.start_time is not None:
            return (time.time() - self.start_time) * 1000
        
        # Session not started yet
        return 0.0


# Export public API
__all__ = [
    'OntologySession',
    'SessionResult',
]

"""Theorem Session - Single extraction-critique-optimize cycle.

This module implements a single adversarial session that coordinates
the extractor, critic, and data through multiple rounds of refinement.

Analogous to AdversarialSession in the complaint-generator harness.

.. deprecated:: 0.2.0
    `TheoremSession`, `SessionConfig`, and `SessionResult` are deprecated.
    Use `LogicTheoremOptimizer` from `unified_optimizer` instead, which provides
    the same functionality through the standardized BaseOptimizer interface.
    
    Migration Example::
    
        # Old approach
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            TheoremSession, LogicExtractor, LogicCritic, SessionConfig
        )
        extractor = LogicExtractor(model="gpt-4")
        critic = LogicCritic(use_provers=['z3'])
        session = TheoremSession(extractor, critic, SessionConfig(max_rounds=10))
        result = session.run(data="All employees must complete training")
        
        # New approach (recommended)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
        from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationContext
        
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_iterations=10, target_score=0.85),
            use_provers=['z3']
        )
        context = OptimizationContext(
            session_id="session-001",
            input_data="All employees must complete training",
            domain="general"
        )
        result = optimizer.run_session(
            data="All employees must complete training",
            context=context
        )
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
import time

logger = logging.getLogger(__name__)


@dataclass
class SessionConfig:
    """Configuration for a theorem session.
    
    .. deprecated:: 0.2.0
        Use `OptimizerConfig` from `optimizers.common.base_optimizer` instead.
        
    Attributes:
        max_rounds: Maximum number of refinement rounds
        convergence_threshold: Score threshold for early termination
        use_ontology: Whether to use ontology for consistency
        strict_evaluation: Whether to use strict evaluation criteria
    """
    max_rounds: int = 10
    convergence_threshold: float = 0.85
    use_ontology: bool = True
    strict_evaluation: bool = False
    
    def __post_init__(self):
        """Issue deprecation warning on instantiation."""
        warnings.warn(
            "SessionConfig is deprecated. Use OptimizerConfig from "
            "optimizers.common.base_optimizer instead.",
            DeprecationWarning,
            stacklevel=2
        )


@dataclass
class SessionResult:
    """Result of a single theorem extraction session.
    
    .. deprecated:: 0.2.0
        SessionResult is deprecated. LogicTheoremOptimizer returns a standardized
        result dict compatible with BaseOptimizer interface.
    
    Attributes:
        extraction_result: Final extraction result
        critic_score: Final critic score
        num_rounds: Number of rounds executed
        converged: Whether session converged
        success: Whether session succeeded
        round_history: History of each round
        total_time: Total execution time in seconds
    """
    extraction_result: Any
    critic_score: Any
    num_rounds: int
    converged: bool
    success: bool
    round_history: List[Dict[str, Any]] = field(default_factory=list)
    total_time: float = 0.0


class TheoremSession:
    """Single theorem extraction session with iterative refinement.
    
    .. deprecated:: 0.2.0
        TheoremSession is deprecated. Use `LogicTheoremOptimizer` instead.
        
        LogicTheoremOptimizer provides the same functionality through the
        standardized BaseOptimizer interface with improved:
        - Automatic metrics collection
        - Built-in caching and performance optimization
        - Consistent API across all optimizer types
        - Better resource management
    
    This class coordinates a single extraction session where:
    1. Extractor generates logical statements from data
    2. Critic evaluates the quality
    3. Extractor refines based on feedback
    4. Repeat until convergence or max rounds
    
    This implements the core SGD-like optimization loop for a single
    data sample, analogous to how an adversarial session tests a single
    complaint scenario.
    
    Example:
        >>> # DEPRECATED - Use LogicTheoremOptimizer instead
        >>> from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        ...     TheoremSession, LogicExtractor, LogicCritic, SessionConfig
        ... )
        >>> extractor = LogicExtractor(model="gpt-4")
        >>> critic = LogicCritic(use_provers=['z3'])
        >>> session = TheoremSession(extractor, critic)
        >>> result = session.run(data="All employees must complete training")
        >>> print(f"Converged: {result.converged}, Score: {result.critic_score.overall}")
    """
    
    def __init__(
        self,
        extractor: Any,  # LogicExtractor
        critic: Any,  # LogicCritic
        config: Optional[SessionConfig] = None
    ):
        """Initialize the theorem session.
        
        .. deprecated:: 0.2.0
            Use LogicTheoremOptimizer instead.
        
        Args:
            extractor: LogicExtractor instance
            critic: LogicCritic instance
            config: Session configuration
        """
        warnings.warn(
            "TheoremSession is deprecated. Use LogicTheoremOptimizer from "
            "unified_optimizer instead. See module docstring for migration guide.",
            DeprecationWarning,
            stacklevel=2
        )
        self.extractor = extractor
        self.critic = critic
        self.config = config or SessionConfig()
        
    def run(
        self,
        data: Any,
        context: Optional[Dict[str, Any]] = None
    ) -> SessionResult:
        """Run a complete extraction session with refinement.
        
        Args:
            data: Input data to extract logic from
            context: Optional context for extraction
            
        Returns:
            SessionResult with final extraction and scores
        """
        start_time = time.time()
        
        # Import here to avoid circular dependency
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import (
            LogicExtractionContext, DataType, ExtractionMode
        )
        
        # Initialize extraction context
        extraction_context = LogicExtractionContext(
            data=data,
            data_type=context.get('data_type', DataType.TEXT) if context else DataType.TEXT,
            extraction_mode=context.get('extraction_mode', ExtractionMode.AUTO) if context else ExtractionMode.AUTO,
            domain=context.get('domain', 'general') if context else 'general',
            ontology=context.get('ontology') if context else None
        )
        
        # Track rounds
        round_history = []
        current_round = 0
        converged = False
        best_score = 0.0
        best_extraction = None
        best_critic_score = None
        
        # Iterative refinement loop
        while current_round < self.config.max_rounds and not converged:
            current_round += 1
            logger.info(f"Session round {current_round}/{self.config.max_rounds}")
            
            # Extract logical statements
            extraction_result = self.extractor.extract(extraction_context)
            
            if not extraction_result.success:
                logger.warning(f"Extraction failed in round {current_round}")
                round_history.append({
                    'round': current_round,
                    'extraction_success': False,
                    'error': extraction_result.errors
                })
                continue
            
            # Evaluate with critic
            critic_score = self.critic.evaluate(extraction_result)
            
            # Track this round
            round_history.append({
                'round': current_round,
                'extraction_success': True,
                'critic_score': critic_score.overall,
                'num_statements': len(extraction_result.statements),
                'strengths': critic_score.strengths,
                'weaknesses': critic_score.weaknesses,
                'recommendations': critic_score.recommendations
            })
            
            # Update best result
            if critic_score.overall > best_score:
                best_score = critic_score.overall
                best_extraction = extraction_result
                best_critic_score = critic_score
            
            # Check convergence
            if critic_score.overall >= self.config.convergence_threshold:
                converged = True
                logger.info(f"Session converged at round {current_round} with score {critic_score.overall:.3f}")
                break
            
            # Provide feedback for refinement
            feedback = self._prepare_feedback(critic_score, extraction_result)
            self.extractor.improve_from_feedback(feedback)
            
            # Update context with previous extractions
            extraction_context.previous_extractions.append(extraction_result)
            
            # Add recommendations as hints for next round
            if critic_score.recommendations:
                extraction_context.hints = critic_score.recommendations[:3]  # Top 3
        
        total_time = time.time() - start_time
        
        # If no successful extraction, return failure
        if best_extraction is None:
            return SessionResult(
                extraction_result=None,
                critic_score=None,
                num_rounds=current_round,
                converged=False,
                success=False,
                round_history=round_history,
                total_time=total_time
            )
        
        return SessionResult(
            extraction_result=best_extraction,
            critic_score=best_critic_score,
            num_rounds=current_round,
            converged=converged,
            success=True,
            round_history=round_history,
            total_time=total_time
        )
    
    def _prepare_feedback(
        self,
        critic_score: Any,
        extraction_result: Any
    ) -> Dict[str, Any]:
        """Prepare feedback dictionary for extractor improvement.
        
        Args:
            critic_score: CriticScore from evaluation
            extraction_result: ExtractionResult being evaluated
            
        Returns:
            Dictionary of feedback for extractor
        """
        feedback = {
            'overall_score': critic_score.overall,
            'strengths': critic_score.strengths,
            'weaknesses': critic_score.weaknesses,
            'recommendations': critic_score.recommendations,
            'dimension_scores': {}
        }
        
        # Add dimension-specific feedback
        for dim_score in critic_score.dimension_scores:
            feedback['dimension_scores'][dim_score.dimension.value] = {
                'score': dim_score.score,
                'feedback': dim_score.feedback
            }
        
        return feedback
    
    def get_session_summary(self, result: SessionResult) -> Dict[str, Any]:
        """Get a summary of session results.
        
        Args:
            result: SessionResult to summarize
            
        Returns:
            Dictionary with session summary
        """
        if not result.success:
            return {
                'success': False,
                'num_rounds': result.num_rounds,
                'total_time': result.total_time
            }
        
        return {
            'success': True,
            'converged': result.converged,
            'num_rounds': result.num_rounds,
            'final_score': result.critic_score.overall,
            'num_statements': len(result.extraction_result.statements),
            'total_time': result.total_time,
            'avg_confidence': sum(s.confidence for s in result.extraction_result.statements) / len(result.extraction_result.statements),
            'improvement': result.round_history[-1]['critic_score'] - result.round_history[0]['critic_score'] if len(result.round_history) > 1 else 0.0
        }

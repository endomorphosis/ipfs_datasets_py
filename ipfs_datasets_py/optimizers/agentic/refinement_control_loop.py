"""
Refinement Control Loop - Batch 239 [agentic].

Autonomous refinement control loop that automatically applies refinement strategies
until convergence, score threshold, or iteration limit is reached.

Key Features:
    - Autonomous strategy selection using suggest_refinement_strategy()
    - Configurable convergence criteria (score improvement, iteration limit)
    - Strategy application with feedback tracking
    - Early stopping on score degradation
    - Refinement history logging
    - Progress callbacks for monitoring
    - Safety limits to prevent infinite loops

Usage:
    >>> from optimizers.agentic.refinement_control_loop import (
    ...     RefinementControlLoop,
    ...     ControlLoopConfig,
    ... )
    >>> 
    >>> config = ControlLoopConfig(
    ...     max_iterations=10,
    ...     min_score_improvement=0.01,
    ...     target_score=0.9,
    ... )
    >>> 
    >>> control_loop = RefinementControlLoop(
    ...     generator=OntologyGenerator(),
    ...     mediator=OntologyMediator(),
    ...     critic=OntologyCritic(),
    ...     config=config,
    ... )
    >>> 
    >>> final_result, history = control_loop.run(
    ...     text=document,
    ...     initial_config=extraction_config,
    ... )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class ControlLoopConfig:
    """Configuration for refinement control loop.
    
    Attributes:
        max_iterations: Maximum refinement iterations
        min_score_improvement: Minimum score improvement to continue
        target_score: Target overall score (stops when reached)
        allow_score_degradation: Allow temporary score drops
        early_stop_degradation_count: Stop after N consecutive degradations
        strategy_selection_mode: Strategy selection mode ("top", "weighted", "all")
        max_strategies_per_iteration: Max strategies to try per iteration
        enable_logging: Enable detailed logging
        enable_history: Track refinement history
    """
    
    max_iterations: int = 10
    min_score_improvement: float = 0.01
    target_score: float = 0.9
    allow_score_degradation: bool = False
    early_stop_degradation_count: int = 3
    strategy_selection_mode: str = "top"
    max_strategies_per_iteration: int = 1
    enable_logging: bool = True
    enable_history: bool = True


# ============================================================================
# Refinement History
# ============================================================================


@dataclass
class RefinementIteration:
    """Single refinement iteration record.
    
    Attributes:
        iteration: Iteration number
        strategy_applied: Strategy applied in this iteration
        score_before: Score before refinement
        score_after: Score after refinement
        score_improvement: Change in score
        entities_before: Entity count before
        entities_after: Entity count after
        relationships_before: Relationship count before
        relationships_after: Relationship count after
        execution_time_ms: Iteration execution time
        metadata: Additional metadata
    """
    
    iteration: int
    strategy_applied: Dict[str, Any]
    score_before: float
    score_after: float
    score_improvement: float
    entities_before: int
    entities_after: int
    relationships_before: int
    relationships_after: int
    execution_time_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Refinement Control Loop
# ============================================================================


class RefinementControlLoop:
    """Autonomous refinement control loop.
    
    Orchestrates iterative refinement using strategy suggestions from mediator,
    applying strategies and tracking progress until convergence or limits reached.
    """
    
    def __init__(
        self,
        generator: Any,
        mediator: Any,
        critic: Any,
        config: Optional[ControlLoopConfig] = None,
    ):
        """Initialize refinement control loop.
        
        Args:
            generator: OntologyGenerator instance
            mediator: OntologyMediator instance
            critic: OntologyCritic instance
            config: Control loop configuration
        """
        self.generator = generator
        self.mediator = mediator
        self.critic = critic
        self.config = config or ControlLoopConfig()
        self.history: List[RefinementIteration] = []
    
    def run(
        self,
        text: str,
        initial_config: Any,
        progress_callback: Optional[Callable[[int, float, str], None]] = None,
    ) -> Tuple[Any, List[RefinementIteration]]:
        """Run autonomous refinement loop.
        
        Args:
            text: Input text for extraction
            initial_config: Initial extraction configuration
            progress_callback: Optional callback(iteration, score, status)
            
        Returns:
            Tuple of (final_result, refinement_history)
        """
        import time
        
        if self.config.enable_logging:
            logger.info("Starting refinement control loop")
            logger.info(f"Max iterations: {self.config.max_iterations}")
            logger.info(f"Target score: {self.config.target_score}")
        
        # Initial extraction
        current_config = initial_config
        current_result = self.generator.extract_entities(text, current_config)
        current_score = self._evaluate_result(current_result)
        
        if progress_callback:
            progress_callback(0, current_score, "initial_extraction")
        
        # Refinement loop
        iteration = 0
        consecutive_degradations = 0
        
        while iteration < self.config.max_iterations:
            iteration += 1
            iteration_start = time.time()
            
            # Check convergence criteria
            if current_score >= self.config.target_score:
                if self.config.enable_logging:
                    logger.info(
                        f"Target score {self.config.target_score} reached "
                        f"at iteration {iteration-1}"
                    )
                break
            
            # Suggest refinement strategy
            strategy = self.mediator.suggest_refinement_strategy(
                current_result,
                current_config,
                target_dimension=None,  # Auto-select
            )
            
            if not strategy or strategy["action"] == "none":
                if self.config.enable_logging:
                    logger.info("No refinement strategy suggested, stopping")
                break
            
            # Apply strategy to get new config
            new_config = self._apply_strategy(current_config, strategy)
            
            # Extract with new config
            new_result = self.generator.extract_entities(text, new_config)
            new_score = self._evaluate_result(new_result)
            
            # Calculate improvement
            score_improvement = new_score - current_score
            
            # Check for score degradation
            if score_improvement < 0:
                consecutive_degradations += 1
                
                if not self.config.allow_score_degradation:
                    if self.config.enable_logging:
                        logger.warning(
                            f"Score degraded from {current_score:.3f} to {new_score:.3f}, "
                            f"reverting strategy"
                        )
                    # Don't apply this iteration
                    continue
                
                if consecutive_degradations >= self.config.early_stop_degradation_count:
                    if self.config.enable_logging:
                        logger.warning(
                            f"Early stopping after {consecutive_degradations} "
                            f"consecutive degradations"
                        )
                    break
            else:
                consecutive_degradations = 0
            
            # Check minimum improvement threshold
            if 0 < score_improvement < self.config.min_score_improvement:
                if self.config.enable_logging:
                    logger.info(
                        f"Score improvement {score_improvement:.4f} below threshold "
                        f"{self.config.min_score_improvement}, stopping"
                    )
                break
            
            # Record iteration
            iteration_time = (time.time() - iteration_start) * 1000
            
            if self.config.enable_history:
                iteration_record = RefinementIteration(
                    iteration=iteration,
                    strategy_applied=strategy,
                    score_before=current_score,
                    score_after=new_score,
                    score_improvement=score_improvement,
                    entities_before=len(current_result.get("entities", [])),
                    entities_after=len(new_result.get("entities", [])),
                    relationships_before=len(current_result.get("relationships", [])),
                    relationships_after=len(new_result.get("relationships", [])),
                    execution_time_ms=iteration_time,
                )
                self.history.append(iteration_record)
            
            # Update current state
            current_result = new_result
            current_score = new_score
            current_config = new_config
            
            # Progress callback
            if progress_callback:
                progress_callback(iteration, current_score, strategy["action"])
            
            if self.config.enable_logging:
                logger.info(
                    f"Iteration {iteration}: score={current_score:.3f} "
                    f"(+{score_improvement:.3f}), action={strategy['action']}"
                )
        
        if self.config.enable_logging:
            logger.info(
                f"Refinement complete after {iteration} iterations, "
                f"final score: {current_score:.3f}"
            )
        
        return current_result, self.history
    
    def _evaluate_result(self, result: Any) -> float:
        """Evaluate extraction result using critic.
        
        Args:
            result: Extraction result
            
        Returns:
            Overall score (0.0-1.0)
        """
        if isinstance(result, dict):
            # Already a dict
            scores = self.critic.evaluate_ontology(result)
        else:
            # Convert to dict
            scores = self.critic.evaluate_ontology(result.to_dict())
        
        # Handle both dict and float returns from critic
        if isinstance(scores, dict):
            return scores.get("overall", 0.0)
        else:
            # Direct float return
            return float(scores)
    
    def _apply_strategy(self, config: Any, strategy: Dict[str, Any]) -> Any:
        """Apply refinement strategy to configuration.
        
        Args:
            config: Current extraction configuration
            strategy: Refinement strategy from mediator
            
        Returns:
            New configuration with strategy applied
        """
        # Create new config (immutable update)
        new_config_dict = config.to_dict() if hasattr(config, "to_dict") else vars(config).copy()
        
        action = strategy.get("action", "none")
        
        if action == "adjust_confidence_threshold":
            threshold = strategy.get("threshold", new_config_dict.get("confidence_threshold", 0.5))
            new_config_dict["confidence_threshold"] = threshold
        
        elif action == "increase_entity_limit":
            max_entities = strategy.get("max_entities", new_config_dict.get("max_entities", 1000))
            new_config_dict["max_entities"] = max_entities
        
        elif action == "expand_patterns":
            # Add custom patterns
            custom_rules = new_config_dict.get("custom_rules", [])
            new_patterns = strategy.get("patterns", [])
            new_config_dict["custom_rules"] = custom_rules + new_patterns
        
        elif action == "add_stopwords":
            stopwords = new_config_dict.get("stopwords", set())
            new_stopwords = strategy.get("stopwords", [])
            new_config_dict["stopwords"] = stopwords | set(new_stopwords)
        
        elif action == "increase_window_size":
            window_size = strategy.get("window_size", new_config_dict.get("window_size", 100))
            new_config_dict["window_size"] = window_size
        
        elif action == "enable_llm_fallback":
            new_config_dict["llm_fallback_enabled"] = True
            new_config_dict["llm_fallback_threshold"] = strategy.get("threshold", 0.5)
        
        elif action == "filter_low_confidence":
            threshold = strategy.get("threshold", new_config_dict.get("confidence_threshold", 0.5))
            new_config_dict["confidence_threshold"] = max(
                threshold,
                new_config_dict.get("confidence_threshold", 0.5),
            )
        
        # Reconstruct config object
        if hasattr(config, "from_dict"):
            return config.from_dict(new_config_dict)
        else:
            # Create new config with updated dict
            return type(config)(**new_config_dict)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get refinement summary statistics.
        
        Returns:
            Summary dictionary with statistics
        """
        if not self.history:
            return {
                "iterations": 0,
                "initial_score": 0.0,
                "final_score": 0.0,
                "total_improvement": 0.0,
            }
        
        initial_score = self.history[0].score_before
        final_score = self.history[-1].score_after
        
        return {
            "iterations": len(self.history),
            "initial_score": initial_score,
            "final_score": final_score,
            "total_improvement": final_score - initial_score,
            "avg_iteration_time_ms": sum(
                it.execution_time_ms for it in self.history
            ) / len(self.history),
            "strategies_applied": [it.strategy_applied["action"] for it in self.history],
            "entity_count_change": (
                self.history[-1].entities_after - self.history[0].entities_before
            ),
            "relationship_count_change": (
                self.history[-1].relationships_after - self.history[0].relationships_before
            ),
        }
    
    def clear_history(self):
        """Clear refinement history."""
        self.history.clear()


# ============================================================================
# Batch Refinement
# ============================================================================


class BatchRefinementController:
    """Batch refinement controller for multiple documents.
    
    Applies refinement control loop to multiple documents in parallel or sequence.
    """
    
    def __init__(
        self,
        generator: Any,
        mediator: Any,
        critic: Any,
        config: Optional[ControlLoopConfig] = None,
    ):
        """Initialize batch refinement controller.
        
        Args:
            generator: OntologyGenerator instance
            mediator: OntologyMediator instance
            critic: OntologyCritic instance
            config: Control loop configuration
        """
        self.generator = generator
        self.mediator = mediator
        self.critic = critic
        self.config = config or ControlLoopConfig()
    
    def run_batch(
        self,
        documents: List[Tuple[str, str, Any]],
        progress_callback: Optional[Callable[[int, int, float], None]] = None,
    ) -> List[Tuple[str, Any, List[RefinementIteration]]]:
        """Run refinement loop on multiple documents.
        
        Args:
            documents: List of (doc_id, text, config) tuples
            progress_callback: Optional callback(doc_index, total_docs, score)
            
        Returns:
            List of (doc_id, final_result, history) tuples
        """
        results = []
        
        for idx, (doc_id, text, config) in enumerate(documents):
            logger.info(f"Processing document {idx+1}/{len(documents)}: {doc_id}")
            
            control_loop = RefinementControlLoop(
                self.generator,
                self.mediator,
                self.critic,
                self.config,
            )
            
            final_result, history = control_loop.run(text, config)
            results.append((doc_id, final_result, history))
            
            if progress_callback:
                final_score = history[-1].score_after if history else 0.0
                progress_callback(idx + 1, len(documents), final_score)
        
        return results
    
    def get_batch_summary(
        self,
        batch_results: List[Tuple[str, Any, List[RefinementIteration]]],
    ) -> Dict[str, Any]:
        """Get summary statistics for batch refinement.
        
        Args:
            batch_results: Results from run_batch()
            
        Returns:
            Batch summary dictionary
        """
        if not batch_results:
            return {"documents_processed": 0}
        
        total_iterations = sum(len(history) for _, _, history in batch_results)
        avg_iterations = total_iterations / len(batch_results) if batch_results else 0
        
        initial_scores = [
            history[0].score_before for _, _, history in batch_results if history
        ]
        final_scores = [
            history[-1].score_after for _, _, history in batch_results if history
        ]
        
        return {
            "documents_processed": len(batch_results),
            "total_iterations": total_iterations,
            "avg_iterations_per_document": avg_iterations,
            "avg_initial_score": sum(initial_scores) / len(initial_scores) if initial_scores else 0,
            "avg_final_score": sum(final_scores) / len(final_scores) if final_scores else 0,
            "avg_score_improvement": (
                sum(final_scores) / len(final_scores) - sum(initial_scores) / len(initial_scores)
            ) if final_scores and initial_scores else 0,
        }

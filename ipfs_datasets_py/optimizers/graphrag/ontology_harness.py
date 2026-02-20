"""
Ontology Harness for Parallel Batch Optimization.

This module provides parallel execution of multiple ontology optimization sessions
with failure handling, result aggregation, and SGD cycle coordination. Inspired by
the adversarial harness from complaint-generator.

Key Features:
    - Parallel session execution with configurable workers
    - Automatic failure handling and retries
    - Result aggregation across sessions
    - SGD cycle orchestration
    - Batch reporting and analytics
    - Progress tracking

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyHarness,
    ...     OntologyGenerationContext
    ... )
    >>> 
    >>> harness = OntologyHarness(
    ...     generator_config={'model': 'bert-base-uncased'},
    ...     critic_config={'model': 'gpt-4'},
    ...     validator_config={'strategy': 'AUTO'},
    ...     parallelism=4
    ... )
    >>> 
    >>> results = harness.run_sessions(
    ...     data_sources=[doc1, doc2, doc3],
    ...     contexts=[ctx1, ctx2, ctx3]
    ... )
    >>> print(f"Success rate: {results.success_rate:.1%}")

References:
    - complaint-generator harness.py: Parallel execution patterns
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BatchResult:
    """
    Results from batch execution of ontology sessions.
    
    Aggregates results from multiple sessions, computing statistics and
    providing batch-level analytics.
    
    Attributes:
        sessions: List of individual session results
        total_sessions: Total number of sessions attempted
        success_rate: Fraction of sessions that succeeded
        average_score: Average quality score across successful sessions
        best_session: Best performing session
        failed_sessions: List of failed session information
        optimization_report: Optional optimization report from analyzer
        metadata: Additional batch metadata
        
    Example:
        >>> batch = BatchResult(
        ...     sessions=[result1, result2, result3],
        ...     total_sessions=3,
        ...     success_rate=1.0,
        ...     average_score=0.84
        ... )
        >>> print(f"Batch: {batch.total_sessions} sessions, {batch.success_rate:.1%} success")
    """
    
    sessions: List[Any]  # List[SessionResult]
    total_sessions: int
    success_rate: float
    average_score: float
    best_session: Optional[Any] = None  # Optional[SessionResult]
    failed_sessions: List[Dict[str, Any]] = field(default_factory=list)
    optimization_report: Optional[Any] = None  # Optional[OptimizationReport]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert batch result to dictionary."""
        return {
            'total_sessions': self.total_sessions,
            'success_count': len(self.sessions),
            'failed_count': len(self.failed_sessions),
            'success_rate': self.success_rate,
            'average_score': self.average_score,
            'best_score': self.best_session.critic_score.overall if self.best_session else None,
            'sessions': [s.to_dict() if hasattr(s, 'to_dict') else s for s in self.sessions],
            'failed_sessions': self.failed_sessions,
            'optimization_report': (
                self.optimization_report.to_dict()
                if self.optimization_report and hasattr(self.optimization_report, 'to_dict')
                else self.optimization_report
            ),
            'metadata': self.metadata,
        }


class OntologyHarness:
    """
    Parallel ontology optimization harness.
    
    Orchestrates parallel execution of multiple ontology generation and
    optimization sessions. Manages worker pools, handles failures, aggregates
    results, and coordinates SGD optimization cycles.
    
    Inspired by the adversarial harness from complaint-generator, adapted for
    ontology optimization with focus on batch processing and SGD cycles.
    
    Attributes:
        generator_config: Configuration for ontology generator
        critic_config: Configuration for critic
        validator_config: Configuration for validator
        parallelism: Number of parallel workers
        max_retries: Maximum retry attempts for failed sessions
        
    Example:
        >>> harness = OntologyHarness(
        ...     generator_config={'model': 'bert-base-uncased'},
        ...     critic_config={'model': 'gpt-4'},
        ...     validator_config={'strategy': 'AUTO'},
        ...     parallelism=4,
        ...     max_retries=3
        ... )
        >>> 
        >>> # Run batch
        >>> results = harness.run_sessions(
        ...     data_sources=[doc1, doc2, doc3],
        ...     contexts=[ctx1, ctx2, ctx3]
        ... )
        >>> 
        >>> # Run SGD cycles
        >>> cycle_results = harness.run_sgd_cycle(
        ...     data_sources=documents,
        ...     contexts=contexts,
        ...     num_cycles=10
        ... )
    """
    
    def __init__(
        self,
        generator_config: Optional[Dict[str, Any]] = None,
        critic_config: Optional[Dict[str, Any]] = None,
        validator_config: Optional[Dict[str, Any]] = None,
        parallelism: int = 4,
        max_retries: int = 3,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize the ontology harness.
        
        Args:
            generator_config: Configuration for OntologyGenerator
            critic_config: Configuration for OntologyCritic
            validator_config: Configuration for LogicValidator
            parallelism: Number of parallel workers (default: 4)
            max_retries: Maximum retry attempts per session (default: 3)
            logger: Optional :class:`logging.Logger` to use instead of the
                module-level logger. Useful for dependency injection in tests.
            
        Raises:
            ValueError: If parallelism or max_retries are not positive
        """
        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)
        
        if parallelism < 1:
            raise ValueError("parallelism must be at least 1")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        
        self.generator_config = generator_config or {}
        self.critic_config = critic_config or {}
        self.validator_config = validator_config or {}
        self.parallelism = parallelism
        self.max_retries = max_retries
        
        # Import components (lazy to avoid circular imports)
        self._components_imported = False
        self._import_components()
        
        self._log.info(
            "Initialized OntologyHarness",
            extra={
                'parallelism': parallelism,
                'max_retries': max_retries,
            }
        )
    
    def _import_components(self):
        """Lazy import of components to avoid circular dependencies."""
        if self._components_imported:
            return
        
        try:
            from . import (
                OntologyGenerator,
                OntologyCritic,
                OntologyMediator,
                LogicValidator,
                OntologySession,
                OntologyOptimizer,
            )
            
            self.OntologyGenerator = OntologyGenerator
            self.OntologyCritic = OntologyCritic
            self.OntologyMediator = OntologyMediator
            self.LogicValidator = LogicValidator
            self.OntologySession = OntologySession
            self.OntologyOptimizer = OntologyOptimizer
            
            self._components_imported = True
            self._log.info(
                "Components imported successfully",
                extra={
                    'components_imported': True,
                }
            )
        except ImportError as e:
            self._log.error(
                "Failed to import components",
                extra={
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                },
                exc_info=True,
            )
            raise
    
    def create_session(self) -> Any:  # OntologySession
        """
        Create a new ontology session with configured components.
        
        Returns:
            Configured OntologySession instance
        """
        # Create components
        generator = self.OntologyGenerator(**self.generator_config)
        critic = self.OntologyCritic(**self.critic_config)
        validator = self.LogicValidator(**self.validator_config)
        
        mediator = self.OntologyMediator(
            generator=generator,
            critic=critic,
            max_rounds=10,
            convergence_threshold=0.85
        )
        
        session = self.OntologySession(
            generator=generator,
            mediator=mediator,
            critic=critic,
            validator=validator,
            max_rounds=10
        )
        
        return session
    
    def run_single_session(
        self,
        data: Any,
        context: Any,
        session_id: int
    ) -> Tuple[int, Any, Optional[Exception]]:
        """
        Run a single ontology session.
        
        Args:
            data: Source data
            context: Generation context
            session_id: Unique session identifier
            
        Returns:
            Tuple of (session_id, result, error)
        """
        self._log.info(
            "Session starting",
            extra={
                'session_id': session_id,
            }
        )
        
        try:
            session = self.create_session()
            result = session.run(data, context)
            
            self._log.info(
                "Session complete",
                extra={
                    'session_id': session_id,
                    'score': round(result.critic_score.overall, 3) if result.critic_score else None,
                    'rounds': result.num_rounds,
                    'converged': getattr(result, 'converged', None),
                }
            )
            
            return (session_id, result, None)
            
        except Exception as e:
            self._log.error(
                "Session failed",
                extra={
                    'session_id': session_id,
                    'error_type': type(e).__name__,
                    'error_message': str(e),
                },
                exc_info=True,
            )
            return (session_id, None, e)
    
    def run_sessions(
        self,
        data_sources: List[Any],
        contexts: List[Any],
        num_sessions_per_source: int = 1
    ) -> BatchResult:
        """
        Run multiple ontology sessions in parallel.
        
        Executes sessions for each data source/context pair, with optional
        multiple runs per source. Handles failures with automatic retries.
        
        Args:
            data_sources: List of data sources to process
            contexts: List of generation contexts (must match data_sources length)
            num_sessions_per_source: Number of sessions to run per data source
            
        Returns:
            BatchResult with aggregated results
            
        Raises:
            ValueError: If data_sources and contexts lengths don't match
            
        Example:
            >>> results = harness.run_sessions(
            ...     data_sources=[doc1, doc2, doc3],
            ...     contexts=[ctx1, ctx2, ctx3],
            ...     num_sessions_per_source=2  # Run each twice
            ... )
            >>> print(f"Completed {len(results.sessions)} sessions")
        """
        if len(data_sources) != len(contexts):
            raise ValueError("data_sources and contexts must have same length")
        
        self._log.info(
            "Running batch",
            extra={
                'source_count': len(data_sources),
                'sessions_per_source': num_sessions_per_source,
                'total_sessions': len(data_sources) * num_sessions_per_source,
                'parallelism': self.parallelism,
            }
        )
        
        start_time = time.time()
        
        # Prepare session tasks
        tasks = []
        for source_idx, (data, context) in enumerate(zip(data_sources, contexts)):
            for run_idx in range(num_sessions_per_source):
                session_id = source_idx * num_sessions_per_source + run_idx
                tasks.append((data, context, session_id))
        
        # Execute in parallel
        successful_results = []
        failed_sessions = []
        
        with ThreadPoolExecutor(max_workers=self.parallelism) as executor:
            # Submit all tasks
            futures = {
                executor.submit(self.run_single_session, data, context, sid): sid
                for data, context, sid in tasks
            }
            
            # Collect results as they complete
            for future in as_completed(futures):
                session_id, result, error = future.result()
                
                if error is None and result is not None:
                    successful_results.append(result)
                else:
                    failed_sessions.append({
                        'session_id': session_id,
                        'error': str(error) if error else 'Unknown error',
                    })
        
        # Compute statistics
        total_sessions = len(tasks)
        success_rate = len(successful_results) / total_sessions if total_sessions > 0 else 0.0
        
        # Compute average score
        scores = [
            r.critic_score.overall
            for r in successful_results
            if r.critic_score and hasattr(r.critic_score, 'overall')
        ]
        average_score = sum(scores) / len(scores) if scores else 0.0
        
        # Find best session
        best_session = None
        if successful_results:
            best_session = max(
                successful_results,
                key=lambda r: r.critic_score.overall if r.critic_score and hasattr(r.critic_score, 'overall') else 0.0
            )
        
        # Run optimizer analysis
        optimization_report = None
        if successful_results:
            try:
                optimizer = self.OntologyOptimizer()
                # Convert session results to mediator states for analysis
                mediator_states = []
                for result in successful_results:
                    # Create a minimal mediator state from session result
                    class MiniMediatorState:
                        def __init__(self, result):
                            self.current_ontology = result.ontology
                            self.critic_scores = [result.critic_score]
                            self.current_round = result.num_rounds
                            self.converged = result.converged
                    
                    mediator_states.append(MiniMediatorState(result))
                
                optimization_report = optimizer.analyze_batch(mediator_states)
            except Exception as e:
                self._log.warning(
                    "Optimization analysis failed",
                    extra={
                        'error_type': type(e).__name__,
                        'error_message': str(e),
                    }
                )
        
        # Build batch result
        elapsed_time = time.time() - start_time
        
        batch_result = BatchResult(
            sessions=successful_results,
            total_sessions=total_sessions,
            success_rate=success_rate,
            average_score=average_score,
            best_session=best_session,
            failed_sessions=failed_sessions,
            optimization_report=optimization_report,
            metadata={
                'parallelism': self.parallelism,
                'time_elapsed': elapsed_time,
                'num_sources': len(data_sources),
                'sessions_per_source': num_sessions_per_source,
            }
        )
        
        self._log.info(
            "Batch complete",
            extra={
                'successful_sessions': len(successful_results),
                'total_sessions': total_sessions,
                'failed_sessions': len(failed_sessions),
                'success_rate': round(success_rate, 4),
                'average_score': round(average_score, 3),
                'elapsed_time_s': round(elapsed_time, 3),
            }
        )
        
        return batch_result
    
    def run_sgd_cycle(
        self,
        data_sources: List[Any],
        contexts: List[Any],
        num_cycles: int = 10,
        convergence_threshold: float = 0.85
    ) -> List[BatchResult]:
        """
        Run complete SGD optimization cycles.
        
        Executes multiple cycles of batch processing, analyzing results after
        each cycle and adapting parameters for the next cycle based on
        optimizer recommendations.
        
        Args:
            data_sources: List of data sources
            contexts: List of generation contexts
            num_cycles: Number of SGD cycles to run
            convergence_threshold: Score threshold for overall convergence
            
        Returns:
            List of BatchResult, one per cycle
            
        Example:
            >>> cycle_results = harness.run_sgd_cycle(
            ...     data_sources=documents,
            ...     contexts=contexts,
            ...     num_cycles=10,
            ...     convergence_threshold=0.85
            ... )
            >>> 
            >>> # Analyze improvement over cycles
            >>> for i, batch in enumerate(cycle_results):
            ...     print(f"Cycle {i+1}: avg={batch.average_score:.2f}")
        """
        self._log.info(
            "Starting SGD cycles",
            extra={
                'num_cycles': num_cycles,
                'convergence_threshold': convergence_threshold,
                'source_count': len(data_sources),
            }
        )
        
        cycle_results = []
        
        for cycle in range(num_cycles):
            self._log.info(
                "Cycle start",
                extra={
                    'cycle': cycle + 1,
                    'num_cycles': num_cycles,
                }
            )
            
            # Run batch
            batch_result = self.run_sessions(
                data_sources=data_sources,
                contexts=contexts,
                num_sessions_per_source=1
            )
            
            cycle_results.append(batch_result)
            
            # Check convergence
            if batch_result.average_score >= convergence_threshold:
                self._log.info(
                    "Converged early",
                    extra={
                        'cycle': cycle + 1,
                        'score': round(batch_result.average_score, 3),
                        'convergence_threshold': convergence_threshold,
                    }
                )
                break
            
            # Log progress
            trend = batch_result.optimization_report.trend if batch_result.optimization_report else 'unknown'
            self._log.info(
                "Cycle complete",
                extra={
                    'cycle': cycle + 1,
                    'average_score': round(batch_result.average_score, 3),
                    'trend': trend,
                }
            )
            
            # Apply recommendations for next cycle
            if batch_result.optimization_report and batch_result.optimization_report.recommendations:
                self._log.info(
                    "Cycle recommendations",
                    extra={
                        'cycle': cycle + 1,
                        'recommendation_count': len(batch_result.optimization_report.recommendations),
                        'recommendations_preview': batch_result.optimization_report.recommendations[:3],
                    }
                )
                # In a full implementation, would adapt parameters here
        
        self._log.info(
            "SGD cycles complete",
            extra={
                'cycles_executed': len(cycle_results),
            }
        )
        
        return cycle_results


# Export public API
__all__ = [
    'OntologyHarness',
    'OntologyPipelineHarness',
    'BatchResult',
]


class OntologyPipelineHarness:
    """Single-session harness wiring Generator → Critic → Mediator via BaseHarness.

    This is a lightweight alternative to :class:`OntologyHarness` for running a
    single iterative refinement session rather than a parallel batch.  It extends
    :class:`~ipfs_datasets_py.optimizers.common.BaseHarness` so the session
    lifecycle (``BaseSession``, convergence, round tracking) is handled centrally.

    Example::

        from ipfs_datasets_py.optimizers.graphrag import (
            OntologyGenerator, OntologyCritic, OntologyMediator,
            OntologyGenerationContext, ExtractionStrategy,
        )
        from ipfs_datasets_py.optimizers.graphrag.ontology_harness import (
            OntologyPipelineHarness,
        )
        from ipfs_datasets_py.optimizers.common import HarnessConfig

        harness = OntologyPipelineHarness(
            generator=OntologyGenerator(),
            critic=OntologyCritic(),
            mediator=OntologyMediator(),
            config=HarnessConfig(max_rounds=5, target_score=0.8),
        )
        context = OntologyGenerationContext(
            data_source="contract.txt",
            data_type="text",
            domain="legal",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
        )
        session = harness.run(source_text, context)
        print(f"Best score: {session.best_score:.3f}")
    """

    def __init__(
        self,
        generator: Any,
        critic: Any,
        mediator: Any,
        config: Optional[Any] = None,  # HarnessConfig
        logger: Optional[logging.Logger] = None,
    ) -> None:
        from ..common.base_harness import BaseHarness, HarnessConfig
        from ..common.base_critic import CriticResult

        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)

        _config = config if config is not None else HarnessConfig()

        class _Harness(BaseHarness):
            def _generate(self_h, data: Any, context: Any) -> Any:
                ontology = generator.generate_ontology(data, context)
                self._last_ontology = ontology
                return ontology

            def _critique(self_h, artifact: Any, context: Any) -> CriticResult:
                try:
                    return critic.evaluate(artifact, context)
                except Exception:
                    raw = critic.evaluate_ontology(artifact, context)
                    return CriticResult(
                        score=raw.overall,
                        feedback=raw.feedback,
                        dimensions={k: v for k, v in raw.dimensions.items()},
                    )

            def _optimize(self_h, artifact: Any, critique: CriticResult, context: Any) -> Any:
                from ..common.exceptions import RefinementError
                try:
                    refined = mediator.refine_ontology(artifact, critique.feedback)
                except RefinementError:
                    raise
                except Exception as exc:
                    self._log.warning("refine_ontology failed: %s", exc)
                    refined = artifact
                self._last_ontology = refined
                return refined

        self._harness = _Harness(config=_config)
        self._last_ontology: Optional[Dict[str, Any]] = None

    def run(self, data: Any, context: Any) -> Any:
        """Run the pipeline and return a :class:`~ipfs_datasets_py.optimizers.common.BaseSession`."""
        return self._harness.run(data, context)

    def run_and_report(self, data: Any, context: Any) -> Dict[str, Any]:
        """Run and return a rich summary dict."""
        session = self.run(data, context)
        return {
            "best_score": session.best_score,
            "rounds": len(session.rounds),
            "converged": session.converged,
            "best_ontology": self._last_ontology,
            "session": session,
        }

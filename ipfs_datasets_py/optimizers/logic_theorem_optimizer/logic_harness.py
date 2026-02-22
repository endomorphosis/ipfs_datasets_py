"""Logic Harness - Batch theorem extraction with parallelism.

This module implements the harness for running multiple theorem extraction
sessions in parallel, analogous to the AdversarialHarness in the
complaint-generator system.

.. deprecated:: 0.2.0
    `LogicHarness`, `HarnessConfig`, and `HarnessResult` are deprecated.
    Use `LogicTheoremOptimizer` with batch processing instead.
    
    Migration Example::
    
        # Old approach
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
            LogicHarness, LogicExtractor, LogicCritic, HarnessConfig
        )
        extractor = LogicExtractor(model="gpt-4")
        critic = LogicCritic(use_provers=['z3', 'cvc5'])
        harness = LogicHarness(
            extractor=extractor,
            critic=critic,
            config=HarnessConfig(parallelism=4)
        )
        data_samples = ["Sample 1", "Sample 2", "Sample 3"]
        result = harness.run_sessions(data_samples)
        
        # New approach (recommended)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import LogicTheoremOptimizer
        from ipfs_datasets_py.optimizers.common import OptimizerConfig, OptimizationContext
        
        optimizer = LogicTheoremOptimizer(
            config=OptimizerConfig(max_iterations=10, target_score=0.85),
            use_provers=['z3', 'cvc5']
        )
        
        # Process each sample
        results = []
        for i, sample in enumerate(data_samples):
            context = OptimizationContext(
                session_id=f"session-{i}",
                input_data=sample,
                domain="general"
            )
            result = optimizer.run_session(sample, context)
            results.append(result)
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from ipfs_datasets_py.optimizers.common.base_critic import CriticResult
from ipfs_datasets_py.optimizers.common.base_harness import BaseHarness, HarnessConfig as BaseHarnessConfig

logger = logging.getLogger(__name__)


@dataclass
class HarnessConfig:
    """Configuration for the logic harness.
    
    .. deprecated:: 0.2.0
        Use `OptimizerConfig` from `optimizers.common.base_optimizer` instead.
    
    Attributes:
        parallelism: Number of parallel sessions
        max_retries: Maximum retries for failed sessions
        timeout_per_session: Timeout in seconds per session
        batch_size: Number of sessions per batch
    """
    parallelism: int = 4
    max_retries: int = 3
    timeout_per_session: float = 300.0  # 5 minutes
    batch_size: int = 10
    
    def __post_init__(self):
        """Issue deprecation warning on instantiation."""
        warnings.warn(
            "HarnessConfig is deprecated. Use OptimizerConfig from "
            "optimizers.common.base_optimizer instead.",
            DeprecationWarning,
            stacklevel=2
        )


@dataclass
class HarnessResult:
    """Result of batch theorem extraction.
    
    .. deprecated:: 0.2.0
        HarnessResult is deprecated. Process batches using LogicTheoremOptimizer
        and aggregate results manually or use BaseOptimizer's built-in metrics.
    
    Attributes:
        session_results: List of individual session results
        total_sessions: Total number of sessions attempted
        successful_sessions: Number of successful sessions
        failed_sessions: Number of failed sessions
        average_score: Average critic score
        best_score: Best critic score achieved
        worst_score: Worst critic score
        total_time: Total execution time
        metrics: Additional metrics
    """
    session_results: List[Any]
    total_sessions: int
    successful_sessions: int
    failed_sessions: int
    average_score: float
    best_score: float
    worst_score: float
    total_time: float
    metrics: Dict[str, Any] = field(default_factory=dict)


class LogicHarness:
    """Batch processing harness for theorem extraction.
    
    .. deprecated:: 0.2.0
        LogicHarness is deprecated. Use `LogicTheoremOptimizer` for batch
        processing instead. The new optimizer provides better:
        - Resource management with built-in pooling
        - Automatic metrics collection via BaseOptimizer
        - Better error handling and retry logic
        - Consistent API across optimizer types
    
    This harness orchestrates multiple theorem extraction sessions in parallel,
    handles failures and retries, aggregates results, and provides comprehensive
    reporting for optimization.
    
    Features:
    - Parallel session execution
    - Automatic retry on failure
    - Progress tracking
    - Result aggregation
    - Performance metrics
    
    Example:
        >>> # DEPRECATED - Use LogicTheoremOptimizer instead
        >>> from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        ...     LogicHarness, LogicExtractor, LogicCritic, HarnessConfig
        ... )
        >>> extractor = LogicExtractor(model="gpt-4")
        >>> critic = LogicCritic(use_provers=['z3', 'cvc5'])
        >>> harness = LogicHarness(
        ...     extractor=extractor,
        ...     critic=critic,
        ...     config=HarnessConfig(parallelism=4)
        ... )
        >>> data_samples = ["Sample 1", "Sample 2", "Sample 3"]
        >>> result = harness.run_sessions(data_samples)
        >>> print(f"Success rate: {result.successful_sessions / result.total_sessions}")
    """
    
    def __init__(
        self,
        extractor: Any,  # LogicExtractor
        critic: Any,  # LogicCritic
        config: Optional[HarnessConfig] = None
    ):
        """Initialize the logic harness.
        
        .. deprecated:: 0.2.0
            Use LogicTheoremOptimizer instead.
        
        Args:
            extractor: LogicExtractor instance
            critic: LogicCritic instance
            config: Harness configuration
        """
        warnings.warn(
            "LogicHarness is deprecated. Use LogicTheoremOptimizer from "
            "unified_optimizer for batch processing. See module docstring for migration guide.",
            DeprecationWarning,
            stacklevel=2
        )
        self.extractor = extractor
        self.critic = critic
        self.config = config or HarnessConfig()
        
    def run_sessions(
        self,
        data_samples: List[Any],
        contexts: Optional[List[Dict[str, Any]]] = None,
        session_config: Optional[Any] = None
    ) -> HarnessResult:
        """Run multiple theorem extraction sessions.
        
        Args:
            data_samples: List of data samples to process
            contexts: Optional list of contexts (one per sample)
            session_config: Optional SessionConfig for all sessions
            
        Returns:
            HarnessResult with aggregated results
        """
        start_time = time.time()
        
        # Import here to avoid circular dependency
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.theorem_session import (
            TheoremSession, SessionConfig
        )
        
        # Use provided session config or default
        if session_config is None:
            session_config = SessionConfig()
        
        # Prepare contexts
        if contexts is None:
            contexts = [None] * len(data_samples)
        elif len(contexts) != len(data_samples):
            raise ValueError("contexts must have same length as data_samples")
        
        # Track results
        session_results = []
        failed_count = 0
        
        # Process in parallel
        logger.info(f"Starting {len(data_samples)} sessions with parallelism={self.config.parallelism}")
        
        with ThreadPoolExecutor(max_workers=self.config.parallelism) as executor:
            # Submit all sessions
            future_to_data = {}
            for i, (data, context) in enumerate(zip(data_samples, contexts)):
                session = TheoremSession(self.extractor, self.critic, session_config)
                future = executor.submit(
                    self._run_single_session_with_retry,
                    session,
                    data,
                    context,
                    i
                )
                future_to_data[future] = (data, context, i)
            
            # Collect results
            for future in as_completed(future_to_data, timeout=self.config.timeout_per_session * len(data_samples)):
                data, context, idx = future_to_data[future]
                try:
                    result = future.result()
                    session_results.append(result)
                    
                    if not result.success:
                        failed_count += 1
                        logger.warning(f"Session {idx} failed")
                    else:
                        logger.info(f"Session {idx} completed: score={result.critic_score.overall:.3f}")
                        
                except Exception as e:
                    logger.error(f"Session {idx} raised exception: {e}")
                    failed_count += 1
        
        total_time = time.time() - start_time
        
        # Calculate metrics
        successful_results = [r for r in session_results if r.success]
        
        if successful_results:
            scores = [r.critic_score.overall for r in successful_results]
            average_score = sum(scores) / len(scores)
            best_score = max(scores)
            worst_score = min(scores)
        else:
            average_score = 0.0
            best_score = 0.0
            worst_score = 0.0
        
        # Additional metrics
        metrics = self._calculate_metrics(session_results)
        
        return HarnessResult(
            session_results=session_results,
            total_sessions=len(data_samples),
            successful_sessions=len(successful_results),
            failed_sessions=failed_count,
            average_score=average_score,
            best_score=best_score,
            worst_score=worst_score,
            total_time=total_time,
            metrics=metrics
        )
    
    def _run_single_session_with_retry(
        self,
        session: Any,  # TheoremSession
        data: Any,
        context: Optional[Dict[str, Any]],
        session_id: int
    ) -> Any:  # SessionResult
        """Run a single session with retry logic.
        
        Args:
            session: TheoremSession instance
            data: Data to process
            context: Optional context
            session_id: Session identifier for logging
            
        Returns:
            SessionResult
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries):
            try:
                logger.debug(f"Session {session_id}, attempt {attempt + 1}")
                result = session.run(data, context)
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"Session {session_id} attempt {attempt + 1} failed: {e}")
                
                if attempt < self.config.max_retries - 1:
                    # Wait before retry (exponential backoff)
                    wait_time = 2 ** attempt
                    logger.debug(f"Retrying in {wait_time}s...")
                    time.sleep(wait_time)
        
        # All retries failed
        logger.error(f"Session {session_id} failed after {self.config.max_retries} attempts")
        
        # Import here to avoid circular dependency
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.theorem_session import SessionResult
        
        return SessionResult(
            extraction_result=None,
            critic_score=None,
            num_rounds=0,
            converged=False,
            success=False,
            round_history=[],
            total_time=0.0
        )
    
    def _calculate_metrics(self, session_results: List[Any]) -> Dict[str, Any]:
        """Calculate detailed metrics from session results.
        
        Args:
            session_results: List of session results
            
        Returns:
            Dictionary of metrics
        """
        metrics = {}
        
        successful = [r for r in session_results if r.success]
        
        if not successful:
            return metrics
        
        # Convergence metrics
        converged_count = sum(1 for r in successful if r.converged)
        metrics['convergence_rate'] = converged_count / len(successful) if successful else 0.0
        
        # Round metrics
        rounds = [r.num_rounds for r in successful]
        metrics['avg_rounds'] = sum(rounds) / len(rounds) if rounds else 0.0
        metrics['min_rounds'] = min(rounds) if rounds else 0
        metrics['max_rounds'] = max(rounds) if rounds else 0
        
        # Time metrics
        times = [r.total_time for r in successful]
        metrics['avg_time'] = sum(times) / len(times) if times else 0.0
        metrics['min_time'] = min(times) if times else 0.0
        metrics['max_time'] = max(times) if times else 0.0
        
        # Statement metrics
        statement_counts = [len(r.extraction_result.statements) for r in successful]
        metrics['avg_statements'] = sum(statement_counts) / len(statement_counts) if statement_counts else 0.0
        
        # Dimension scores
        from collections import defaultdict
        dimension_scores = defaultdict(list)
        
        for result in successful:
            for dim_score in result.critic_score.dimension_scores:
                dimension_scores[dim_score.dimension.value].append(dim_score.score)
        
        metrics['dimension_averages'] = {
            dim: sum(scores) / len(scores)
            for dim, scores in dimension_scores.items()
        }
        
        return metrics
    
    def run_sgd_cycles(
        self,
        data_samples: List[Any],
        num_cycles: int = 5,
        optimizer: Optional[Any] = None
    ) -> List[HarnessResult]:
        """Run multiple SGD optimization cycles.
        
        Args:
            data_samples: Data samples to process
            num_cycles: Number of optimization cycles
            optimizer: Optional LogicOptimizer instance
            
        Returns:
            List of HarnessResult (one per cycle)
        """
        if optimizer is None:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_optimizer import LogicOptimizer
            optimizer = LogicOptimizer()
        
        results_history = []
        
        for cycle in range(num_cycles):
            logger.info(f"SGD Cycle {cycle + 1}/{num_cycles}")
            
            # Run batch
            result = self.run_sessions(data_samples)
            results_history.append(result)
            
            # Analyze and optimize
            report = optimizer.analyze_batch(result.session_results)
            
            logger.info(f"Cycle {cycle + 1} Results:")
            logger.info(f"  Average Score: {report.average_score:.3f}")
            logger.info(f"  Trend: {report.trend}")
            logger.info(f"  Convergence: {report.convergence_status}")
            
            if report.recommendations:
                logger.info("  Top Recommendations:")
                for rec in report.recommendations[:3]:
                    logger.info(f"    - {rec}")
            
            # Check for convergence
            if report.convergence_status == "converged":
                logger.info(f"Optimization converged after {cycle + 1} cycles")
                break
            
            # Apply improvements (this would update extractor/critic configuration)
            self._apply_optimization(report)
        
        return results_history
    
    def _apply_optimization(self, report: Any) -> None:
        """Apply optimization recommendations.
        
        Args:
            report: OptimizationReport with recommendations
        """
        # This is where we would apply the recommendations to improve
        # the extractor and critic. For now, we just log.
        logger.info("Applying optimization recommendations:")
        for rec in report.recommendations:
            logger.info(f"  - {rec}")
        
        # Example: Adjust extractor parameters based on feedback
        # if 'soundness' in report.metrics and report.metrics['soundness']['average'] < 0.5:
        #     self.extractor.set_strict_mode(True)


class LogicPipelineHarness(BaseHarness):
    """BaseHarness-native logic extraction pipeline.

    This class offers a unified, lightweight harness API that composes an
    extractor and critic with :class:`BaseHarness` orchestration. It does not
    replace the deprecated :class:`LogicHarness` batch API, but provides a
    modern path for single-session refinement loops.
    """

    def __init__(
        self,
        extractor: Any,
        critic: Any,
        optimizer: Optional[Any] = None,
        config: Optional[BaseHarnessConfig] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.extractor = extractor
        self.critic = critic
        self.optimizer = optimizer
        self._last_extraction: Optional[Any] = None
        self._log = logger or logging.getLogger(__name__)
        super().__init__(config=config or BaseHarnessConfig())

    def _build_context(self, data: Any, context: Any) -> Any:
        """Normalize context so extractor always receives a LogicExtractionContext-like object."""
        if context is None:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import LogicExtractionContext

            return LogicExtractionContext(data=data)

        if hasattr(context, "data"):
            if getattr(context, "data", None) is None:
                setattr(context, "data", data)
            return context

        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.logic_extractor import LogicExtractionContext

        return LogicExtractionContext(data=data, domain=getattr(context, "domain", "general"))

    def _generate(self, data: Any, context: Any) -> Any:
        normalized = self._build_context(data, context)
        extraction = self.extractor.extract(normalized)
        self._last_extraction = extraction
        return extraction

    def _critique(self, artifact: Any, context: Any) -> CriticResult:
        if hasattr(self.critic, "evaluate_as_base"):
            return self.critic.evaluate_as_base(artifact, context)

        raw = self.critic.evaluate_extraction(artifact)
        dims = {
            ds.dimension.value if hasattr(ds.dimension, "value") else str(ds.dimension): ds.score
            for ds in getattr(raw, "dimension_scores", [])
        }
        return CriticResult(
            score=getattr(raw, "overall", 0.0),
            feedback=list(getattr(raw, "recommendations", [])),
            dimensions=dims,
            strengths=list(getattr(raw, "strengths", [])),
            weaknesses=list(getattr(raw, "weaknesses", [])),
        )

    def _optimize(self, artifact: Any, critique: CriticResult, context: Any) -> Any:
        # LogicOptimizer currently focuses on batch analysis; no in-place artifact
        # mutation contract exists here yet, so preserve artifact as-is.
        _ = critique
        _ = context
        return artifact

    def run_and_report(self, data: Any, context: Any) -> Dict[str, Any]:
        """Execute one session and return a compact report payload."""
        session = self.run(data, context)
        return {
            "best_score": session.best_score,
            "rounds": len(session.rounds),
            "converged": session.converged,
            "extraction": self._last_extraction,
            "session": session,
        }

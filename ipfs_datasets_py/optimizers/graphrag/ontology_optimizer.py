"""
Ontology Optimizer for GraphRAG using Stochastic Gradient Descent.

This module provides an SGD-based optimization engine that analyzes ontology
quality across multiple sessions and generates recommendations for improvement.
Inspired by the optimizer from complaint-generator.

The optimizer implements analysis patterns including:
- Batch analysis across multiple sessions
- Trend identification over SGD cycles
- Pattern recognition in successful ontologies
- Recommendation generation for improvement
- Performance tracking and reporting

Key Features:
    - Multi-session batch analysis
    - Trend analysis over time
    - Pattern identification
    - Adaptive recommendations
    - Performance metrics tracking

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import (
    ...     OntologyOptimizer,
    ...     OntologyHarness
    ... )
    >>> 
    >>> optimizer = OntologyOptimizer()
    >>> 
    >>> # Analyze single batch
    >>> report = optimizer.analyze_batch(session_results)
    >>> print(f"Average: {report.average_score:.2f}")
    >>> print(f"Trend: {report.trend}")
    >>> 
    >>> # Analyze trends over multiple batches
    >>> trend_report = optimizer.analyze_trends(historical_results)
    >>> print(f"Improvement rate: {trend_report['improvement_rate']:.2%}")

References:
    - complaint-generator optimizer.py: SGD analysis patterns
"""

from __future__ import annotations

import json
import logging
import time
import csv
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from opentelemetry import trace
    HAVE_OPENTELEMETRY = True
except ImportError:  # pragma: no cover
    trace = None  # type: ignore[assignment]
    HAVE_OPENTELEMETRY = False

try:
    from ipfs_datasets_py.optimizers.optimizer_learning_metrics import (
        OptimizerLearningMetricsCollector,
    )
    HAVE_LEARNING_METRICS = True
except ImportError:  # pragma: no cover
    OptimizerLearningMetricsCollector = None  # type: ignore[assignment,misc]
    HAVE_LEARNING_METRICS = False

logger = logging.getLogger(__name__)


@dataclass
class OptimizationReport:
    """
    Optimization recommendations from batch analysis.
    
    Provides comprehensive analysis of a batch of ontology generation sessions,
    including scores, trends, and actionable recommendations for improvement.
    
    Attributes:
        average_score: Average quality score across all sessions
        trend: Overall trend ('improving', 'stable', 'degrading')
        recommendations: List of optimization recommendations
        best_ontology: Best performing ontology in the batch
        worst_ontology: Worst performing ontology in the batch
        improvement_rate: Rate of improvement over previous batches
        score_distribution: Distribution of scores across dimensions
        metadata: Additional analysis metadata
        
    Example:
        >>> report = OptimizationReport(
        ...     average_score=0.78,
        ...     trend='improving',
        ...     recommendations=['Add more entities', 'Improve clarity']
        ... )
        >>> print(f"Quality: {report.average_score:.2f} ({report.trend})")
    """
    
    average_score: float
    trend: str  # 'improving', 'stable', 'degrading'
    recommendations: List[str] = field(default_factory=list)
    best_ontology: Optional[Dict[str, Any]] = None
    worst_ontology: Optional[Dict[str, Any]] = None
    improvement_rate: float = 0.0
    score_distribution: Dict[str, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            'average_score': self.average_score,
            'trend': self.trend,
            'recommendations': self.recommendations,
            'best_score': self.best_ontology.get('score') if self.best_ontology else None,
            'worst_score': self.worst_ontology.get('score') if self.worst_ontology else None,
            'improvement_rate': self.improvement_rate,
            'score_distribution': self.score_distribution,
            'metadata': self.metadata,
        }


class OntologyOptimizer:
    """
    SGD-based ontology optimization engine.
    
    Analyzes results from multiple ontology generation sessions to identify
    patterns, trends, and opportunities for improvement. Uses stochastic
    gradient descent principles to guide iterative optimization.
    
    The optimizer tracks performance across batches and generates actionable
    recommendations for improving ontology quality through parameter tuning,
    strategy adjustment, and prompt refinement.
    
    Inspired by the optimizer from complaint-generator, adapted for ontology
    optimization with focus on multi-dimensional quality metrics.
    
    Example:
        >>> optimizer = OntologyOptimizer()
        >>> 
        >>> # Run SGD cycles
        >>> for cycle in range(10):
        ...     # Generate batch of ontologies
        ...     results = harness.run_sessions(data_sources, contexts)
        ...     
        ...     # Analyze and optimize
        ...     report = optimizer.analyze_batch(results['sessions'])
        ...     
        ...     # Apply recommendations
        ...     apply_recommendations(report.recommendations)
        ...     
        ...     # Check convergence
        ...     if report.trend == 'stable' and report.average_score > 0.85:
        ...         print(f"Converged after {cycle + 1} cycles")
        ...         break
    """
    
    def __init__(
        self,
        logger: Optional[logging.Logger] = None,
        enable_tracing: bool = True,
        metrics_collector: Optional[Any] = None,
    ):
        """
        Initialize the ontology optimizer.
        
        Args:
            logger: Optional :class:`logging.Logger` to use instead of the
                module-level logger. Useful for dependency injection in tests.
            enable_tracing: If True, emit OpenTelemetry spans when available.
            metrics_collector: Optional :class:`OptimizerLearningMetricsCollector`
                instance for recording learning cycles after each batch analysis.
                If None and ``HAVE_LEARNING_METRICS`` is True a default in-memory
                collector is created automatically.
        """
        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)
        self._history: List[OptimizationReport] = []
        self._tracer = None
        if enable_tracing and HAVE_OPENTELEMETRY and trace is not None:
            self._tracer = trace.get_tracer(__name__)
        # Wire learning-metrics collector
        if metrics_collector is not None:
            self._metrics = metrics_collector
        elif HAVE_LEARNING_METRICS and OptimizerLearningMetricsCollector is not None:
            self._metrics: Any = OptimizerLearningMetricsCollector()
        else:
            self._metrics = None
        self._log.info("Initialized OntologyOptimizer")

    def _emit_trace(self, operation: str, attributes: Dict[str, Any]) -> None:
        """Emit a best-effort OpenTelemetry span with scalar attributes."""
        if self._tracer is None:
            return

        try:
            with self._tracer.start_as_current_span(operation) as span:
                for key, value in attributes.items():
                    if value is None:
                        continue
                    if isinstance(value, (str, bool, int, float)):
                        span.set_attribute(key, value)
                    else:
                        span.set_attribute(key, str(value))
        except Exception:
            # Tracing must never affect optimizer execution.
            return

    def _emit_analyze_batch_summary(self, payload: Dict[str, Any]) -> None:
        """Emit one structured JSON INFO log for ``analyze_batch`` observability."""
        summary = {
            "event": "ontology_optimizer.analyze_batch.summary",
            **payload,
        }
        self._log.info(json.dumps(summary, sort_keys=True))
    
    def analyze_batch(
        self,
        session_results: List[Any]  # List[MediatorState or SessionResult]
    ) -> OptimizationReport:
        """
        Analyze single batch of ontology generation sessions.
        
        Examines results from a batch of sessions, computing aggregate metrics,
        identifying best/worst performers, and generating recommendations for
        the next optimization cycle.
        
        Args:
            session_results: List of session results to analyze
            
        Returns:
            OptimizationReport with analysis and recommendations
            
        Example:
            >>> # Run batch of sessions
            >>> results = []
            >>> for data in data_sources:
            ...     state = mediator.run_refinement_cycle(data, context)
            ...     results.append(state)
            >>> 
            >>> # Analyze
            >>> report = optimizer.analyze_batch(results)
            >>> print(f"Avg: {report.average_score:.2f}")
            >>> for rec in report.recommendations:
            ...     print(f"- {rec}")
        """
        operation_start = time.time()

        self._log.info(
            "Analyzing batch of sessions",
            extra={
                'session_count': len(session_results),
                'batch_id': id(session_results),
            }
        )
        
        if not session_results:
            self._log.warning(
                "No session results provided for batch analysis",
                extra={
                    'batch_id': id(session_results),
                    'error_type': 'empty_batch',
                }
            )
            report = OptimizationReport(
                average_score=0.0,
                trend='insufficient_data',
                recommendations=["Need more sessions to analyze"]
            )
            self._emit_trace(
                "ontology_optimizer.analyze_batch",
                {
                    'session_count': 0,
                    'status': 'insufficient_data',
                    'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
                }
            )
            self._emit_analyze_batch_summary(
                {
                    "batch_id": id(session_results),
                    "session_count": 0,
                    "status": "insufficient_data",
                    "duration_ms": round((time.time() - operation_start) * 1000.0, 3),
                }
            )
            return report
        
        # Extract scores
        scores = []
        for result in session_results:
            if hasattr(result, 'critic_scores') and result.critic_scores:
                # MediatorState
                scores.append(result.critic_scores[-1].overall)
            elif hasattr(result, 'critic_score') and result.critic_score is not None:
                # SessionResult with valid critic_score
                scores.append(result.critic_score.overall)
        
        if not scores:
            report = OptimizationReport(
                average_score=0.0,
                trend='no_scores',
                recommendations=["No valid scores found"]
            )
            self._emit_trace(
                "ontology_optimizer.analyze_batch",
                {
                    'session_count': len(session_results),
                    'status': 'no_scores',
                    'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
                }
            )
            self._emit_analyze_batch_summary(
                {
                    "batch_id": id(session_results),
                    "session_count": len(session_results),
                    "status": "no_scores",
                    "duration_ms": round((time.time() - operation_start) * 1000.0, 3),
                }
            )
            return report
        
        # Compute statistics
        average_score = sum(scores) / len(scores)
        best_idx = scores.index(max(scores))
        worst_idx = scores.index(min(scores))
        
        # Determine trend
        trend = self._determine_trend(average_score)
        
        # Identify patterns
        patterns = self._identify_patterns(session_results)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            average_score,
            scores,
            patterns
        )
        
        # Compute score distribution
        score_distribution = self._compute_score_distribution(session_results)
        
        # Create report
        report = OptimizationReport(
            average_score=average_score,
            trend=trend,
            recommendations=recommendations,
            best_ontology=self._extract_ontology(session_results[best_idx]),
            worst_ontology=self._extract_ontology(session_results[worst_idx]),
            score_distribution=score_distribution,
            metadata={
                'num_sessions': len(session_results),
                'score_std': self._compute_std(scores),
                'score_range': (min(scores), max(scores)),
            }
        )
        
        # Add to history
        self._history.append(report)
        
        # Compute improvement rate if we have history
        if len(self._history) >= 2:
            report.improvement_rate = (
                report.average_score - self._history[-2].average_score
            )
        
        self._log.info(
            "Batch analysis complete",
            extra={
                'batch_id': id(session_results),
                'session_count': len(session_results),
                'average_score': round(average_score, 3),
                'trend': trend,
                'recommendation_count': len(recommendations),
                'score_std': round(self._compute_std(scores), 3),
                'score_min': round(min(scores), 3),
                'score_max': round(max(scores), 3),
            }
        )

        self._emit_trace(
            "ontology_optimizer.analyze_batch",
            {
                'session_count': len(session_results),
                'average_score': round(average_score, 6),
                'trend': trend,
                'recommendation_count': len(recommendations),
                'score_distribution_completeness': report.score_distribution.get('completeness', 0.0),
                'score_distribution_consistency': report.score_distribution.get('consistency', 0.0),
                'score_distribution_clarity': report.score_distribution.get('clarity', 0.0),
                'score_distribution_granularity': report.score_distribution.get('granularity', 0.0),
                'score_distribution_domain_alignment': report.score_distribution.get('domain_alignment', 0.0),
                'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
            }
        )
        self._emit_analyze_batch_summary(
            {
                "batch_id": id(session_results),
                "session_count": len(session_results),
                "status": "ok",
                "average_score": round(average_score, 6),
                "trend": trend,
                "recommendation_count": len(recommendations),
                "duration_ms": round((time.time() - operation_start) * 1000.0, 3),
            }
        )

        # Record learning cycle to metrics collector if available
        if self._metrics is not None:
            duration_s = time.time() - operation_start
            try:
                self._metrics.record_learning_cycle(
                    cycle_id=f"ontology_batch_{id(session_results)}",
                    analyzed_queries=len(session_results),
                    patterns_identified=len(patterns),
                    parameters_adjusted={"trend": trend, "average_score": round(average_score, 6)},
                    execution_time=round(duration_s, 4),
                )
            except Exception:  # metrics must never block optimization
                pass

        return report

    def analyze_batch_parallel(
        self,
        session_results: List[Any],
        max_workers: int = 4,
        json_log_path: Optional[str] = None,
    ) -> "OptimizationReport":
        """Parallel variant of :meth:`analyze_batch`.

        Runs the three independent sub-analyses — pattern identification,
        score-distribution computation, and recommendation generation — in
        separate threads using :class:`concurrent.futures.ThreadPoolExecutor`.
        For small batches the overhead is negligible; for large batches (>50
        sessions) this reduces wall-clock time on multi-core machines.

        Args:
            session_results: Same as :meth:`analyze_batch`.
            max_workers: Thread-pool size.  Defaults to 4.
            json_log_path: Optional file path.  When provided, a structured
                JSON summary of the batch is written to this path after
                analysis completes (useful for offline inspection and CI
                artefacts).  Errors writing the file are logged but do not
                propagate.

        Returns:
            ``OptimizationReport`` identical to what :meth:`analyze_batch`
            would return.
        """
        operation_start = time.time()

        self._log.info(
            "Analyzing batch of sessions (parallel)",
            extra={
                'session_count': len(session_results),
                'batch_id': id(session_results),
                'max_workers': max_workers,
            }
        )

        if not session_results:
            self._log.warning(
                "No session results provided for parallel batch analysis",
                extra={
                    'batch_id': id(session_results),
                    'error_type': 'empty_batch',
                }
            )
            report = OptimizationReport(
                average_score=0.0,
                trend="insufficient_data",
                recommendations=["Need more sessions to analyze"],
            )
            self._emit_trace(
                "ontology_optimizer.analyze_batch_parallel",
                {
                    'session_count': 0,
                    'status': 'insufficient_data',
                    'max_workers': max_workers,
                    'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
                }
            )
            return report

        # Extract scores (fast, sequential — no I/O)
        scores: List[float] = []
        for result in session_results:
            if hasattr(result, "critic_scores") and result.critic_scores:
                scores.append(result.critic_scores[-1].overall)
            elif hasattr(result, "critic_score") and result.critic_score is not None:
                scores.append(result.critic_score.overall)

        if not scores:
            report = OptimizationReport(
                average_score=0.0,
                trend="no_scores",
                recommendations=["No valid scores found"],
            )
            self._emit_trace(
                "ontology_optimizer.analyze_batch_parallel",
                {
                    'session_count': len(session_results),
                    'status': 'no_scores',
                    'max_workers': max_workers,
                    'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
                }
            )
            return report

        average_score = sum(scores) / len(scores)
        trend = self._determine_trend(average_score)
        best_idx = scores.index(max(scores))
        worst_idx = scores.index(min(scores))

        # Submit three independent analyses in parallel
        with ThreadPoolExecutor(max_workers=min(3, max_workers)) as executor:
            f_patterns = executor.submit(self._identify_patterns, session_results)
            f_dist = executor.submit(self._compute_score_distribution, session_results)
            # _generate_recommendations depends only on scalars + patterns,
            # so we wait for patterns first, then submit recommendations.
            patterns = f_patterns.result()
            f_recs = executor.submit(
                self._generate_recommendations, average_score, scores, patterns
            )
            score_distribution = f_dist.result()
            recommendations = f_recs.result()

        report = OptimizationReport(
            average_score=average_score,
            trend=trend,
            recommendations=recommendations,
            best_ontology=self._extract_ontology(session_results[best_idx]),
            worst_ontology=self._extract_ontology(session_results[worst_idx]),
            score_distribution=score_distribution,
            metadata={
                "num_sessions": len(session_results),
                "score_std": self._compute_std(scores),
                "score_range": (min(scores), max(scores)),
            },
        )

        self._history.append(report)
        if len(self._history) >= 2:
            report.improvement_rate = (
                report.average_score - self._history[-2].average_score
            )

        self._log.info(
            "Parallel batch analysis complete",
            extra={
                'batch_id': id(session_results),
                'session_count': len(session_results),
                'average_score': round(average_score, 3),
                'trend': trend,
                'recommendation_count': len(recommendations),
                'score_std': round(self._compute_std(scores), 3),
                'score_min': round(min(scores), 3),
                'score_max': round(max(scores), 3),
                'max_workers': max_workers,
            }
        )
        self._emit_trace(
            "ontology_optimizer.analyze_batch_parallel",
            {
                'session_count': len(session_results),
                'average_score': round(average_score, 6),
                'trend': trend,
                'recommendation_count': len(recommendations),
                'max_workers': max_workers,
                'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
            }
        )

        # Record learning cycle to metrics collector if available
        if self._metrics is not None:
            duration_s = time.time() - operation_start
            try:
                self._metrics.record_learning_cycle(
                    cycle_id=f"ontology_parallel_batch_{id(session_results)}",
                    analyzed_queries=len(session_results),
                    patterns_identified=len(patterns),
                    parameters_adjusted={"trend": trend, "average_score": round(average_score, 6)},
                    execution_time=round(duration_s, 4),
                )
            except Exception:  # metrics must never block optimization
                pass

        if json_log_path is not None:
            _summary = {
                "session_count": len(session_results),
                "average_score": round(average_score, 6),
                "trend": trend,
                "score_min": round(min(scores), 6),
                "score_max": round(max(scores), 6),
                "score_std": round(self._compute_std(scores), 6),
                "recommendation_count": len(recommendations),
                "recommendations": list(recommendations),
                "max_workers": max_workers,
                "duration_ms": round((time.time() - operation_start) * 1000.0, 3),
            }
            try:
                with open(json_log_path, "w", encoding="utf-8") as _fh:
                    json.dump(_summary, _fh, indent=2)
                self._log.debug("Wrote batch parallel JSON log to %s", json_log_path)
            except OSError as _exc:
                self._log.warning(
                    "Failed to write json_log_path=%s: %s", json_log_path, _exc
                )

        return report

    def analyze_trends(
        self,
        historical_results: Optional[List[OptimizationReport]] = None
    ) -> Dict[str, Any]:
        """
        Analyze trends across multiple batches over time.
        
        Examines historical optimization reports to identify long-term trends,
        compute improvement rates, and assess optimization effectiveness.
        
        Args:
            historical_results: Optional list of previous reports. If None,
                uses internal history.
                
        Returns:
            Dictionary with trend analysis:
                - 'improvement_rate': Overall rate of improvement
                - 'trend': Long-term trend
                - 'convergence_estimate': Estimated rounds to convergence
                - 'best_batch': Best performing batch
                - 'recommendations': Long-term recommendations
                
        Example:
            >>> # After multiple SGD cycles
            >>> trends = optimizer.analyze_trends()
            >>> print(f"Improving at {trends['improvement_rate']:.2%} per cycle")
            >>> print(f"Estimated convergence in {trends['convergence_estimate']} cycles")
        """
        operation_start = time.time()
        results = historical_results or self._history
        
        if len(results) < 2:
            self._log.warning(
                "Insufficient batch history for trend analysis",
                extra={
                    'batch_count': len(results),
                    'error_type': 'insufficient_history',
                    'required': 2,
                }
            )
            trend_result = {
                'improvement_rate': 0.0,
                'trend': 'insufficient_data',
                'convergence_estimate': None,
                'best_batch': None,
                'recommendations': ["Need more batches to analyze trends"]
            }
            self._emit_trace(
                "ontology_optimizer.analyze_trends",
                {
                    'batch_count': len(results),
                    'trend': 'insufficient_data',
                    'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
                }
            )
            return trend_result
        
        self._log.info(
            "Analyzing trends across batches",
            extra={
                'batch_count': len(results),
                'analysis_id': id(results),
            }
        )
        
        # Compute improvement rates
        scores = [r.average_score for r in results]
        overall_improvement = scores[-1] - scores[0]
        avg_improvement_per_batch = overall_improvement / (len(scores) - 1)
        
        # Identify trend
        recent_scores = scores[-3:] if len(scores) >= 3 else scores
        if recent_scores[-1] > recent_scores[0] + 0.05:
            trend = 'improving'
        elif recent_scores[-1] < recent_scores[0] - 0.05:
            trend = 'degrading'
        else:
            trend = 'stable'
        
        # Find best batch
        best_idx = scores.index(max(scores))
        best_batch = results[best_idx]
        
        # Estimate convergence
        convergence_estimate = None
        if avg_improvement_per_batch > 0 and scores[-1] < 0.85:
            remaining = 0.85 - scores[-1]
            convergence_estimate = int(remaining / avg_improvement_per_batch)
        
        # Generate recommendations
        recommendations = []
        if trend == 'degrading':
            recommendations.append("Consider reverting to previous configuration")
            recommendations.append("Reduce learning rate or exploration")
        elif trend == 'stable' and scores[-1] < 0.80:
            recommendations.append("Try different extraction strategies")
            recommendations.append("Increase model diversity")
        elif trend == 'improving':
            recommendations.append("Continue current optimization approach")
        
        self._log.info(
            "Trend analysis complete",
            extra={
                'analysis_id': id(results),
                'batch_count': len(results),
                'trend': trend,
                'improvement_rate': round(avg_improvement_per_batch, 4),
                'overall_improvement': round(overall_improvement, 3),
                'current_score': round(scores[-1], 3),
                'baseline_score': round(scores[0], 3),
                'convergence_estimate': convergence_estimate,
                'recommendation_count': len(recommendations),
            }
        )
        
        trend_result = {
            'improvement_rate': avg_improvement_per_batch,
            'trend': trend,
            'convergence_estimate': convergence_estimate,
            'best_batch': best_batch.to_dict(),
            'recommendations': recommendations,
            'score_history': scores,
            'metadata': {
                'num_batches': len(results),
                'overall_improvement': overall_improvement,
            }
        }
        self._emit_trace(
            "ontology_optimizer.analyze_trends",
            {
                'batch_count': len(results),
                'trend': trend,
                'improvement_rate': round(avg_improvement_per_batch, 6),
                'overall_improvement': round(overall_improvement, 6),
                'current_score': round(scores[-1], 6),
                'duration_ms': round((time.time() - operation_start) * 1000.0, 3),
            }
        )
        return trend_result
    

    def identify_patterns(
        self,
        successful_ontologies: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Identify common patterns in successful ontologies.

        Analyzes high-performing ontologies to extract common patterns that
        can be applied to improve future generations.

        Args:
            successful_ontologies: List of ontologies with high scores

        Returns:
            Dictionary with identified patterns

        Example:
            >>> patterns = optimizer.identify_patterns(successful)
            >>> print(f"Common entity types: {patterns['common_entity_types']}")
        """
        self._log.info(
            "Identifying ontology patterns",
            extra={
                'ontology_count': len(successful_ontologies),
            }
        )

        if not successful_ontologies:
            return {"error": "No successful ontologies provided"}

        from collections import Counter

        entity_type_counts: Counter[str] = Counter()
        relationship_type_counts: Counter[str] = Counter()
        property_key_counts: Counter[str] = Counter()

        entity_counts = []
        relationship_counts = []

        for ont in successful_ontologies:
            if not isinstance(ont, dict):
                continue

            entities = ont.get("entities", [])
            relationships = ont.get("relationships", [])

            if isinstance(entities, list):
                entity_counts.append(len(entities))
                for ent in entities:
                    if not isinstance(ent, dict):
                        continue
                    ent_type = ent.get("type")
                    if isinstance(ent_type, str) and ent_type:
                        entity_type_counts[ent_type] += 1

                    props = ent.get("properties")
                    if isinstance(props, dict):
                        for k in props.keys():
                            if k is None:
                                continue
                            property_key_counts[str(k)] += 1

            if isinstance(relationships, list):
                relationship_counts.append(len(relationships))
                for rel in relationships:
                    if not isinstance(rel, dict):
                        continue
                    rel_type = rel.get("type")
                    if isinstance(rel_type, str) and rel_type:
                        relationship_type_counts[rel_type] += 1

        def avg(xs: list[int]) -> float:
            return float(sum(xs)) / float(len(xs)) if xs else 0.0

        sample_size = sum(1 for ont in successful_ontologies if isinstance(ont, dict))

        patterns = {
            "common_entity_types": [t for t, _ in entity_type_counts.most_common(10)],
            "common_relationship_types": [t for t, _ in relationship_type_counts.most_common(10)],
            "avg_entity_count": avg(entity_counts),
            "avg_relationship_count": avg(relationship_counts),
            "common_properties": [k for k, _ in property_key_counts.most_common(15)],
            "sample_size": sample_size,
        }

        return patterns

    def generate_recommendations(
        self,
        current_state: Any,  # MediatorState
        patterns: Dict[str, Any]
    ) -> List[str]:
        """
        Generate specific recommendations for improvement.
        
        Args:
            current_state: Current mediator state
            patterns: Identified success patterns
            
        Returns:
            List of actionable recommendations
        """
        recommendations = []

        if hasattr(current_state, 'critic_scores') and current_state.critic_scores:
            latest_score = current_state.critic_scores[-1]

            # Dimension-specific recommendations
            dim_recs: Dict[str, str] = {
                "completeness": "Increase entity extraction coverage — add more entity types or lower confidence threshold",
                "consistency": "Improve logical consistency — run logic validation and prune dangling references",
                "clarity": "Add more detailed entity properties and normalise naming conventions",
                "granularity": "Increase relationship diversity — expand verb-frame patterns or enable hybrid extraction",
                "domain_alignment": "Align vocabulary to domain — add domain-specific term templates",
            }
            threshold = 0.7
            for dim, rec in dim_recs.items():
                val = getattr(latest_score, dim, None)
                if val is not None and val < threshold:
                    recommendations.append(rec)

        # Pattern-aware recommendations
        entity_dist = patterns.get("entity_type_distribution", {})
        rel_dist = patterns.get("relationship_type_distribution", {})
        weakness_dist = patterns.get("weakness_distribution", {})

        if entity_dist and len(entity_dist) < 3:
            recommendations.append(
                f"Low entity type diversity ({len(entity_dist)} types) — broaden NER patterns"
            )
        if rel_dist and len(rel_dist) < 2:
            recommendations.append(
                f"Low relationship type diversity ({len(rel_dist)} types) — enable relationship inference"
            )
        if weakness_dist:
            top_weakness = max(weakness_dist, key=weakness_dist.get)
            recommendations.append(
                f"Most common weakness: '{top_weakness}' — prioritise fixing this dimension"
            )

        return recommendations
    
    def _determine_trend(self, current_score: float) -> str:
        """Determine trend based on score and history."""
        if not self._history:
            return 'baseline'
        
        prev_score = self._history[-1].average_score
        
        if current_score > prev_score + 0.05:
            return 'improving'
        elif current_score < prev_score - 0.05:
            return 'degrading'
        else:
            return 'stable'
    
    def _identify_patterns(self, session_results: List[Any]) -> Dict[str, Any]:
        """Identify patterns across session results using counter-based analysis."""
        from collections import Counter

        entity_types: Counter = Counter()
        rel_types: Counter = Counter()
        convergence_rounds: list[int] = []
        final_scores: list[float] = []
        weakest_dims: Counter = Counter()

        for result in session_results:
            # Score data
            if hasattr(result, 'critic_scores') and result.critic_scores:
                latest = result.critic_scores[-1]
                if hasattr(latest, 'overall'):
                    final_scores.append(latest.overall)
                # Track weakest dimension per session
                dim_scores = {
                    d: getattr(latest, d, None)
                    for d in ('completeness', 'consistency', 'clarity', 'granularity', 'domain_alignment')
                    if getattr(latest, d, None) is not None
                }
                if dim_scores:
                    weakest = min(dim_scores, key=lambda k: dim_scores[k])
                    weakest_dims[weakest] += 1

            # Round count
            if hasattr(result, 'current_round'):
                convergence_rounds.append(result.current_round)

            # Entity / rel type distributions
            ontology = self._extract_ontology(result)
            for ent in ontology.get('entities', []):
                if isinstance(ent, dict) and ent.get('type'):
                    entity_types[ent['type']] += 1
            for rel in ontology.get('relationships', []):
                if isinstance(rel, dict) and rel.get('type'):
                    rel_types[rel['type']] += 1

        def _avg(lst: list) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        return {
            'avg_final_score': round(_avg(final_scores), 4),
            'avg_convergence_rounds': round(_avg(convergence_rounds), 2),
            'top_entity_types': [t for t, _ in entity_types.most_common(5)],
            'top_rel_types': [t for t, _ in rel_types.most_common(5)],
            'most_common_weakness': weakest_dims.most_common(1)[0][0] if weakest_dims else None,
            'weakness_distribution': dict(weakest_dims.most_common()),
            'session_count': len(session_results),
        }
    
    def _generate_recommendations(
        self,
        average_score: float,
        scores: List[float],
        patterns: Dict[str, Any]
    ) -> List[str]:
        """Generate recommendations based on scores and patterns."""
        recommendations = []
        
        if average_score < 0.6:
            recommendations.append("Consider using hybrid extraction strategy")
            recommendations.append("Increase number of refinement rounds")
        elif average_score < 0.75:
            recommendations.append("Focus on improving weakest dimension")
            recommendations.append("Add domain-specific templates")
        elif average_score < 0.85:
            recommendations.append("Fine-tune convergence threshold")
            recommendations.append("Enable logic validation")
        else:
            recommendations.append("Maintain current configuration")
        
        # Check variance
        if len(scores) > 1:
            std = self._compute_std(scores)
            if std > 0.15:
                recommendations.append("High variance detected - stabilize extraction process")
        
        return recommendations
    
    def _compute_score_distribution(
        self,
        session_results: List[Any]
    ) -> Dict[str, float]:
        """Compute distribution of scores across dimensions."""
        distribution = {
            'completeness': [],
            'consistency': [],
            'clarity': [],
            'granularity': [],
            'domain_alignment': [],
        }
        
        for result in session_results:
            if hasattr(result, 'critic_scores') and result.critic_scores:
                score = result.critic_scores[-1]
                for dim in distribution:
                    val = getattr(score, dim, None)
                    if val is not None:
                        distribution[dim].append(val)
        
        # Compute averages
        return {
            dim: sum(vals) / len(vals) if vals else 0.0
            for dim, vals in distribution.items()
        }
    
    def _extract_ontology(self, result: Any) -> Dict[str, Any]:
        """Extract ontology and score from result."""
        if hasattr(result, 'current_ontology'):
            return {
                'ontology': result.current_ontology,
                'score': result.critic_scores[-1].overall if result.critic_scores else 0.0
            }
        elif hasattr(result, 'ontology'):
            return {
                'ontology': result.ontology,
                'score': result.critic_score.overall if hasattr(result, 'critic_score') else 0.0
            }
        return {'ontology': {}, 'score': 0.0}
    
    def _compute_std(self, scores: List[float]) -> float:
        """Compute standard deviation of scores."""
        if len(scores) < 2:
            return 0.0
        
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return variance ** 0.5

    def get_history_summary(self) -> Dict[str, Any]:
        """Return descriptive statistics over all historical batch reports.

        Computes mean, standard deviation, min, and max of the
        ``average_score`` and ``improvement_rate`` fields stored in
        :attr:`_history`.

        Returns:
            Dictionary with keys:
            - ``count``: number of batch reports in history
            - ``mean_score``: arithmetic mean of per-batch average scores
            - ``std_score``: sample standard deviation of per-batch scores
            - ``min_score``: minimum per-batch average score seen
            - ``max_score``: maximum per-batch average score seen
            - ``mean_improvement_rate``: mean improvement rate across batches
            - ``trend``: ``"improving"``, ``"stable"``, or ``"degrading"``
              based on first-vs-last batch comparison
        """
        if not self._history:
            return {
                "count": 0,
                "mean_score": 0.0,
                "std_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0,
                "mean_improvement_rate": 0.0,
                "trend": "stable",
            }

        scores = [r.average_score for r in self._history]
        imp_rates = [r.improvement_rate for r in self._history]
        n = len(scores)
        mean_s = sum(scores) / n
        mean_i = sum(imp_rates) / n

        if n > 1:
            variance = sum((s - mean_s) ** 2 for s in scores) / (n - 1)
            std_s = variance ** 0.5
        else:
            std_s = 0.0

        first, last = scores[0], scores[-1]
        delta = last - first
        if delta > 0.02:
            trend = "improving"
        elif delta < -0.02:
            trend = "degrading"
        else:
            trend = "stable"

        return {
            "count": n,
            "mean_score": round(mean_s, 4),
            "std_score": round(std_s, 4),
            "min_score": round(min(scores), 4),
            "max_score": round(max(scores), 4),
            "mean_improvement_rate": round(mean_i, 4),
            "trend": trend,
        }

    def prune_history(self, keep_last_n: int) -> int:
        """Discard all but the most recent *keep_last_n* history entries.

        Useful for long-running processes where unbounded history would grow
        memory unboundedly.

        Args:
            keep_last_n: Number of most recent :class:`OptimizationReport`
                entries to retain.  Must be >= 1.

        Returns:
            Number of entries removed.

        Raises:
            ValueError: If ``keep_last_n`` is less than 1.
        """
        if keep_last_n < 1:
            raise ValueError(f"keep_last_n must be >= 1, got {keep_last_n}")
        n_removed = max(0, len(self._history) - keep_last_n)
        if n_removed > 0:
            self._history = self._history[-keep_last_n:]
        return n_removed

    def reset_history(self) -> int:
        """Clear all optimization history entries.

        Removes every :class:`OptimizationReport` from ``_history``,
        effectively resetting the optimizer to its initial empty state.

        Returns:
            Number of entries that were removed.

        Example:
            >>> optimizer.analyze_batch(sessions, domain_knowledge)
            >>> removed = optimizer.reset_history()
            >>> optimizer._history
            []
        """
        n = len(self._history)
        self._history.clear()
        return n

    def session_count(self) -> int:
        """Return total number of sessions recorded across all history entries.

        Sums ``metadata['num_sessions']`` for each
        :class:`OptimizationReport` in ``_history``.  Falls back to 0 for
        entries without that metadata key.

        Returns:
            Total session count as an integer.

        Example:
            >>> optimizer.analyze_batch(sessions, domain_knowledge)
            >>> optimizer.session_count()
            5
        """
        return sum(r.metadata.get("num_sessions", 0) for r in self._history)

    def compare_history(self) -> List[Dict[str, Any]]:
        """Compute a pairwise delta table over all history entries.

        For each consecutive pair of :class:`OptimizationReport` objects in
        ``_history``, computes the score delta and trend.

        Returns:
            List of dicts with keys:
            - ``batch_from``: 0-based index of the earlier entry.
            - ``batch_to``: 0-based index of the later entry.
            - ``score_from``: average_score of the earlier entry.
            - ``score_to``: average_score of the later entry.
            - ``delta``: score_to - score_from (positive = improvement).
            - ``direction``: ``"up"``, ``"down"``, or ``"flat"``.

        Returns an empty list if fewer than 2 history entries exist.
        """
        if len(self._history) < 2:
            return []
        rows: List[Dict[str, Any]] = []
        for i in range(len(self._history) - 1):
            a = self._history[i]
            b = self._history[i + 1]
            delta = round(b.average_score - a.average_score, 6)
            direction = "up" if delta > 0.001 else ("down" if delta < -0.001 else "flat")
            rows.append({
                "batch_from": i,
                "batch_to": i + 1,
                "score_from": round(a.average_score, 6),
                "score_to": round(b.average_score, 6),
                "delta": delta,
                "direction": direction,
            })
        return rows

    def score_trend_summary(self) -> str:
        """Return a one-word trend label based on recent score history.

        Compares the mean score of the **first half** of history entries against
        the **second half**.  Returns:

        - ``"improving"``  — second half mean > first half mean by > 0.01
        - ``"degrading"``  — second half mean < first half mean by > 0.01
        - ``"stable"``     — otherwise (or fewer than 2 history entries)
        - ``"insufficient_data"`` — 0 or 1 history entries

        Returns:
            One of: ``"improving"``, ``"degrading"``, ``"stable"``,
            ``"insufficient_data"``.
        """
        if len(self._history) < 2:
            return "insufficient_data"
        scores = [r.average_score for r in self._history]
        mid = len(scores) // 2
        first_mean = sum(scores[:mid]) / mid
        second_mean = sum(scores[mid:]) / (len(scores) - mid)
        delta = second_mean - first_mean
        if delta > 0.01:
            return "improving"
        if delta < -0.01:
            return "degrading"
        return "stable"

    def rolling_average_score(self, n: int) -> float:
        """Return the mean score of the last *n* history entries.

        Args:
            n: Number of most-recent entries to average.  Clamped to the
               actual history length.

        Returns:
            Mean score.  Returns ``0.0`` if history is empty.

        Raises:
            ValueError: If *n* is < 1.
        """
        if n < 1:
            raise ValueError(f"n must be >= 1; got {n}")
        if not self._history:
            return 0.0
        recent = self._history[-n:]
        return sum(r.average_score for r in recent) / len(recent)

    def export_history_csv(self, filepath: Optional[str] = None) -> Optional[str]:
        """Export the pairwise delta table from :meth:`compare_history` as CSV.

        Args:
            filepath: Optional path to write the CSV.  When ``None`` the CSV is
                returned as a string.

        Returns:
            CSV string when *filepath* is ``None``; ``None`` otherwise.
        """
        rows = self.compare_history()
        output = StringIO()
        fieldnames = ["batch_from", "batch_to", "score_from", "score_to", "delta", "direction"]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        csv_str = output.getvalue()
        if filepath:
            with open(filepath, "w", newline="") as fh:
                fh.write(csv_str)
            return None
        return csv_str

    def export_learning_curve_csv(self, filepath: Optional[str] = None) -> Optional[str]:
        """Export score progression history as CSV.

        Args:
            filepath: Optional file path to save CSV output.

        Returns:
            CSV string when ``filepath`` is None, else None.
        """
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                'batch_index',
                'average_score',
                'trend',
                'improvement_rate',
                'recommendation_count',
                'num_sessions',
            ],
        )
        writer.writeheader()

        for idx, report in enumerate(self._history, start=1):
            writer.writerow(
                {
                    'batch_index': idx,
                    'average_score': report.average_score,
                    'trend': report.trend,
                    'improvement_rate': report.improvement_rate,
                    'recommendation_count': len(report.recommendations),
                    'num_sessions': report.metadata.get('num_sessions', 0),
                }
            )

        if filepath:
            with open(filepath, 'w', newline='') as file_obj:
                file_obj.write(output.getvalue())
            return None

        return output.getvalue()

    def best_ontology(self) -> Optional[Dict[str, Any]]:
        """Return the ontology from the history entry with the highest average score.

        Iterates over all :class:`OptimizationReport` objects in ``_history``
        and returns the ``best_ontology`` dict from the one with the maximum
        ``average_score``.  If no history entries contain a stored ontology
        (i.e. every ``best_ontology`` field is ``None``), returns ``None``.

        Returns:
            The best ontology dict, or ``None`` if history is empty or no
            report has a stored ontology.

        Example:
            >>> optimizer.analyze_batch(sessions, domain_knowledge)
            >>> top = optimizer.best_ontology()
            >>> top is not None
            True
        """
        if not self._history:
            return None
        best_report = max(self._history, key=lambda r: r.average_score)
        return best_report.best_ontology

    def top_n_ontologies(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return up to *n* ontology dicts from the best-scoring history entries.

        History entries are sorted by ``average_score`` in descending order;
        entries without a stored ``best_ontology`` (i.e. ``None``) are skipped.

        Args:
            n: Maximum number of ontologies to return (default: 5).

        Returns:
            List of ontology dicts (at most *n* items, possibly fewer if
            fewer entries have stored ontologies).

        Raises:
            ValueError: If *n* < 1.

        Example:
            >>> top3 = optimizer.top_n_ontologies(3)
            >>> len(top3) <= 3
            True
        """
        if n < 1:
            raise ValueError(f"n must be >= 1; got {n}")
        if not self._history:
            return []
        sorted_reports = sorted(self._history, key=lambda r: r.average_score, reverse=True)
        result: List[Dict[str, Any]] = []
        for report in sorted_reports:
            if report.best_ontology is not None:
                result.append(report.best_ontology)
            if len(result) >= n:
                break
        return result

    def score_variance(self) -> float:
        """Return the variance of average scores across all history batches.

        Uses the population variance formula (``sum(xi - mean)^2 / N``).

        Returns:
            Variance as a float; ``0.0`` if history has fewer than 2 entries.

        Example:
            >>> var = optimizer.score_variance()
            >>> var >= 0.0
            True
        """
        if len(self._history) < 2:
            return 0.0
        scores = [r.average_score for r in self._history]
        mean = sum(scores) / len(scores)
        return sum((s - mean) ** 2 for s in scores) / len(scores)

    def score_stddev(self) -> float:
        """Return the population standard deviation of average scores in history.

        Returns:
            Square root of :meth:`score_variance`; ``0.0`` if fewer than 2
            history entries.

        Example:
            >>> std = optimizer.score_stddev()
            >>> std >= 0.0
            True
        """
        return self.score_variance() ** 0.5

    def recent_score_mean(self, n: int = 5) -> float:
        """Return the mean average_score over the most recent *n* history entries.

        Args:
            n: Number of most-recent entries to include. Defaults to 5.

        Returns:
            Mean of the last *n* ``average_score`` values; ``0.0`` when
            history is empty.

        Example:
            >>> optimizer.recent_score_mean(n=3)
        """
        if not self._history:
            return 0.0
        recent = self._history[-n:]
        return sum(r.average_score for r in recent) / len(recent)

    def score_range(self) -> tuple:
        """Return the ``(min, max)`` range of average scores in history.

        Returns:
            Tuple ``(min_score, max_score)``; ``(0.0, 0.0)`` when history is
            empty.

        Example:
            >>> optimizer.score_range()
            (0.3, 0.9)
        """
        if not self._history:
            return (0.0, 0.0)
        scores = [r.average_score for r in self._history]
        return (min(scores), max(scores))

    def convergence_rate(self, threshold: float = 0.01) -> float:
        """Return the fraction of consecutive history pairs where improvement < *threshold*.

        Measures how often the optimizer's score changes by less than
        *threshold* between consecutive rounds — an indicator of convergence.

        Args:
            threshold: Improvement smaller than this is considered converged.
                Defaults to 0.01.

        Returns:
            Float in [0, 1]; ``0.0`` if history has fewer than 2 entries.

        Example:
            >>> optimizer.convergence_rate()
        """
        if len(self._history) < 2:
            return 0.0
        scores = [r.average_score for r in self._history]
        converged = sum(
            1 for a, b in zip(scores, scores[1:])
            if abs(b - a) < threshold
        )
        return converged / (len(scores) - 1)

    def history_as_list(self) -> list:
        """Return a plain list of ``average_score`` floats from history.

        Returns:
            List of ``float`` in insertion order; empty list when no history.

        Example:
            >>> optimizer.history_as_list()
            [0.4, 0.6, 0.75]
        """
        return [r.average_score for r in self._history]

    def improvement_rate(self) -> float:
        """Return the fraction of consecutive history pairs where score improved.

        Compares each history entry to the previous one (in insertion order).
        The rate is ``improving_pairs / (total_pairs)``.

        Returns:
            Float in [0.0, 1.0]; ``0.0`` if history has fewer than 2 entries.

        Example:
            >>> rate = optimizer.improvement_rate()
            >>> 0.0 <= rate <= 1.0
            True
        """
        if len(self._history) < 2:
            return 0.0
        scores = [r.average_score for r in self._history]
        improving = sum(1 for a, b in zip(scores, scores[1:]) if b > a)
        return improving / (len(scores) - 1)

    def score_percentile(self, p: float) -> float:
        """Return the *p*-th percentile of average scores in history.

        Uses linear interpolation between adjacent sorted values.

        Args:
            p: Percentile in (0, 100].

        Returns:
            Interpolated score value.

        Raises:
            ValueError: If history is empty or *p* is out of range.

        Example:
            >>> median = optimizer.score_percentile(50)
        """
        if not self._history:
            raise ValueError("score_percentile requires at least one history entry")
        if not (0 < p <= 100):
            raise ValueError(f"p must be in (0, 100]; got {p}")
        scores = sorted(r.average_score for r in self._history)
        idx = (p / 100) * (len(scores) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(scores) - 1)
        frac = idx - lo
        return scores[lo] * (1 - frac) + scores[hi] * frac

    def format_history_table(self) -> str:
        """Return an ASCII table summarising each history entry.

        Columns: ``#`` (1-based index), ``avg_score``, ``trend``,
        ``improvement_rate``, ``num_sessions``.

        Returns:
            Multi-line string; a header + divider + one row per entry.
            Returns a single-line ``"(no history)"`` message if empty.

        Example:
            >>> print(optimizer.format_history_table())
            #   avg_score  trend      improvement_rate  num_sessions
            ---- ...
        """
        if not self._history:
            return "(no history)"
        header = f"{'#':>4}  {'avg_score':>9}  {'trend':<10}  {'impr_rate':>9}  {'sessions':>8}"
        divider = "-" * len(header)
        rows = [header, divider]
        for i, r in enumerate(self._history, start=1):
            sessions = r.metadata.get("num_sessions", 0)
            rows.append(
                f"{i:>4}  {r.average_score:>9.4f}  {r.trend:<10}  "
                f"{r.improvement_rate:>9.4f}  {sessions:>8}"
            )
        return "\n".join(rows)

    def average_improvement_per_batch(self) -> float:
        """Return the mean score delta between consecutive history entries.

        Returns:
            Mean of ``score[i+1] - score[i]`` for all pairs.  ``0.0`` if
            fewer than 2 entries in history.

        Example:
            >>> avg_delta = optimizer.average_improvement_per_batch()
        """
        if len(self._history) < 2:
            return 0.0
        scores = [r.average_score for r in self._history]
        deltas = [b - a for a, b in zip(scores, scores[1:])]
        return sum(deltas) / len(deltas)

    def emit_summary_log(self) -> str:
        """Return a one-line ASCII summary of the current optimizer state.

        The summary is also emitted via the logger at INFO level.

        Format::

            [OntologyOptimizer] batches=N avg=X.XX best=X.XX trend=<word> variance=X.XXXXXX

        Where:
        * ``batches`` -- number of history entries.
        * ``avg`` -- mean average score (or ``N/A`` when history is empty).
        * ``best`` -- highest average score (or ``N/A``).
        * ``trend`` -- ``"improving"`` / ``"stable"`` / ``"degrading"`` (or ``"N/A"``).
        * ``variance`` -- population score variance.

        Returns:
            The formatted one-line summary string.

        Example:
            >>> line = optimizer.emit_summary_log()
            >>> line.startswith("[OntologyOptimizer]")
            True
        """
        n = len(self._history)
        if n == 0:
            line = "[OntologyOptimizer] batches=0 avg=N/A best=N/A trend=N/A variance=0.000000"
        else:
            scores = [r.average_score for r in self._history]
            avg = sum(scores) / n
            best = max(scores)
            mean = avg
            variance = sum((s - mean) ** 2 for s in scores) / n
            if n >= 2:
                improving = sum(1 for a, b in zip(scores, scores[1:]) if b > a)
                rate = improving / (n - 1)
                trend = "improving" if rate > 0.6 else ("degrading" if rate < 0.4 else "stable")
            else:
                trend = "stable"
            line = (
                f"[OntologyOptimizer] batches={n} avg={avg:.2f} best={best:.2f} "
                f"trend={trend} variance={variance:.6f}"
            )
        self._log.info(line)
        return line

    def best_ontology(self) -> Optional[Dict[str, Any]]:
        """Return the ontology from the highest-scoring history entry.

        Iterates over :attr:`_history` and returns the ``best_ontology``
        field of the :class:`OptimizationReport` with the highest
        ``average_score``.

        Returns:
            The best ontology dict, or ``None`` if history is empty or no
            entry has a ``best_ontology`` populated.

        Example:
            >>> ont = optimizer.best_ontology()
            >>> ont is None or isinstance(ont, dict)
            True
        """
        if not self._history:
            return None
        best_report = max(self._history, key=lambda r: r.average_score)
        return best_report.best_ontology

    def worst_ontology(self) -> Optional[Dict[str, Any]]:
        """Return the ontology from the lowest-scoring :class:`OptimizationReport`.

        Returns:
            Ontology dict from the worst history entry, or ``None`` if history
            is empty.

        Example:
            >>> worst = optimizer.worst_ontology()
        """
        if not self._history:
            return None
        worst_report = min(self._history, key=lambda r: r.average_score)
        return worst_report.best_ontology

    def best_n_ontologies(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return ontologies from the top *n* history entries by ``average_score``.

        Args:
            n: Number of entries to return.

        Returns:
            List of ontology dicts, length <= n, sorted by score descending.
            Each entry is the ``best_ontology`` from an :class:`OptimizationReport`.

        Example:
            >>> top3 = optimizer.best_n_ontologies(3)
            >>> len(top3) <= 3
            True
        """
        if not self._history:
            return []
        sorted_history = sorted(self._history, key=lambda r: r.average_score, reverse=True)
        return [r.best_ontology for r in sorted_history[:n]]

    def worst_n_ontologies(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return ontologies from the bottom *n* history entries by ``average_score``.

        Args:
            n: Number of entries to return.

        Returns:
            List of ontology dicts, length <= n, sorted by score ascending
            (worst first).  Each entry is the ``worst_ontology`` from an
            :class:`OptimizationReport`.

        Example:
            >>> bottom3 = optimizer.worst_n_ontologies(3)
            >>> len(bottom3) <= 3
            True
        """
        if not self._history:
            return []
        sorted_history = sorted(self._history, key=lambda r: r.average_score)
        return [r.worst_ontology for r in sorted_history[:n]]

    def score_delta(self, i: int, j: int) -> float:
        """Return the score difference between history entries at indices *i* and *j*.

        Args:
            i: Index of the first entry (baseline).
            j: Index of the second entry (comparison).

        Returns:
            ``history[j].average_score - history[i].average_score``

        Raises:
            IndexError: If either index is out of range.

        Example:
            >>> optimizer.score_delta(0, -1)  # first vs last
        """
        return self._history[j].average_score - self._history[i].average_score

    def best_entry(self) -> Optional[Any]:
        """Return the history entry with the highest ``average_score``.

        Returns:
            :class:`OptimizationReport` (or compatible entry) with the max
            average_score; ``None`` when history is empty.

        Example:
            >>> optimizer.best_entry()
        """
        if not self._history:
            return None
        return max(self._history, key=lambda r: r.average_score)

    def worst_entry(self) -> Optional[Any]:
        """Return the history entry with the lowest ``average_score``.

        Returns:
            :class:`OptimizationReport` (or compatible entry) with the min
            average_score; ``None`` when history is empty.

        Example:
            >>> optimizer.worst_entry()
        """
        if not self._history:
            return None
        return min(self._history, key=lambda r: r.average_score)

    @property
    def history_length(self) -> int:
        """Return the number of :class:`OptimizationReport` entries in history.

        Returns:
            Integer >= 0.

        Example:
            >>> optimizer.history_length
            0
        """
        return len(self._history)

    def score_history(self) -> List[float]:
        """Return a list of average scores from all history entries.

        Useful for plotting score trends or computing statistics over
        optimization runs.

        Returns:
            List of ``float`` values, one per :class:`OptimizationReport` in
            ``_history``.  Empty list if no history.

        Example:
            >>> scores = optimizer.score_history()
            >>> all(0.0 <= s <= 1.0 for s in scores)
            True
        """
        return [r.average_score for r in self._history]

    def average_score(self) -> float:
        """Return the mean of all ``average_score`` values in history.

        Returns:
            Float mean, or 0.0 if history is empty.

        Example:
            >>> optimizer.average_score()
            0.0
        """
        scores = self.score_history()
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def last_score(self) -> float:
        """Return the ``average_score`` from the most recent history entry.

        Returns:
            Float score, or 0.0 if history is empty.

        Example:
            >>> optimizer.last_score()
            0.0
        """
        if not self._history:
            return 0.0
        return self._history[-1].average_score

    def clear_history(self) -> int:
        """Clear all optimization history entries.

        Returns:
            Number of entries that were cleared.

        Example:
            >>> optimizer.clear_history()
            0
        """
        n = len(self._history)
        self._history.clear()
        return n

    def percentile_score(self, p: float) -> float:
        """Return the *p*-th percentile of average scores across all history entries.

        Args:
            p: Percentile in the range [0, 100].

        Returns:
            The *p*-th percentile value as a float.  Returns 0.0 if history is
            empty.

        Example:
            >>> optimizer.percentile_score(50)
            0.0
        """
        if not self._history:
            return 0.0
        scores = sorted(entry.average_score for entry in self._history)
        idx = (p / 100.0) * (len(scores) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(scores) - 1)
        frac = idx - lo
        return scores[lo] + frac * (scores[hi] - scores[lo])

    def top_n_scores(self, n: int = 5) -> List[float]:
        """Return the top *n* average scores from all history entries.

        Args:
            n: Number of top scores to return.  Defaults to 5.

        Returns:
            List of up to *n* floats in descending order.

        Example:
            >>> optimizer.top_n_scores(3)
            []
        """
        scores = sorted(
            (entry.average_score for entry in self._history), reverse=True
        )
        return scores[:n]

    def score_at(self, index: int) -> float:
        """Return the ``average_score`` from history at position *index*.

        Args:
            index: Zero-based or negative index (same semantics as Python list
                indexing).

        Returns:
            ``average_score`` float at the given position.

        Raises:
            IndexError: If *index* is out of range.

        Example:
            >>> optimizer.score_at(0)  # first entry
        """
        return self._history[index].average_score

    def history_summary(self) -> Dict[str, Any]:
        """Return a summary dict with statistics about the optimization history.

        Returns:
            Dict with keys ``count``, ``min``, ``max``, ``mean``, and
            ``trend`` (string from the last entry or ``"n/a"``).
            Returns zero-values dict when history is empty.

        Example:
            >>> optimizer.history_summary()
            {'count': 0, 'min': 0.0, 'max': 0.0, 'mean': 0.0, 'trend': 'n/a'}
        """
        if not self._history:
            return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0, "trend": "n/a"}
        scores = [e.average_score for e in self._history]
        return {
            "count": len(scores),
            "min": min(scores),
            "max": max(scores),
            "mean": sum(scores) / len(scores),
            "trend": self._history[-1].trend,
        }

    def latest_batch_size(self) -> int:
        """Return the number of ontologies in the most recent batch.

        Returns:
            Integer count from ``metadata["batch_size"]`` of the last history
            entry if present, otherwise ``0``.

        Example:
            >>> optimizer.latest_batch_size()
            0
        """
        if not self._history:
            return 0
        return self._history[-1].metadata.get("batch_size", 0)

    def export_score_chart(self, filepath: Optional[str] = None) -> Optional[str]:
        """Produce a matplotlib line chart of average score across history batches.

        Requires ``matplotlib`` (``pip install matplotlib``).  Each batch is
        plotted on the x-axis; average score on the y-axis.

        Args:
            filepath: If given, save the chart to this path (PNG/PDF/SVG etc.)
                and return ``None``.  If ``None``, return the chart as a
                base64-encoded PNG string.

        Returns:
            Base64-encoded PNG string when *filepath* is ``None``; ``None``
            otherwise.

        Raises:
            ValueError: If history is empty.
            ImportError: If ``matplotlib`` is not installed.
        """
        if not self._history:
            raise ValueError("No history to plot; run analyze_batch() first.")
        try:
            import matplotlib
            matplotlib.use("Agg")  # non-interactive backend
            import matplotlib.pyplot as _plt
        except ImportError as exc:
            raise ImportError(
                "matplotlib is required for export_score_chart(); "
                "install with: pip install matplotlib"
            ) from exc

        scores = [r.average_score for r in self._history]
        batches = list(range(1, len(scores) + 1))

        fig, ax = _plt.subplots()
        ax.plot(batches, scores, marker="o")
        ax.set_xlabel("Batch")
        ax.set_ylabel("Average Score")
        ax.set_title("Ontology Optimization Score History")
        ax.set_ylim(0.0, 1.0)

        if filepath:
            fig.savefig(filepath, bbox_inches="tight")
            _plt.close(fig)
            return None

        import io, base64
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        _plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("ascii")

    def export_to_rdf(
        self,
        ontology: Optional[Dict[str, Any]] = None,
        filepath: Optional[str] = None,
        *,
        format: str = "turtle",
    ) -> Optional[str]:
        """Export ontology to RDF (Turtle or N-Triples) using rdflib.

        This is a lightweight stub that serialises the entity/relationship
        structure as RDF triples.  Requires ``rdflib`` (``pip install rdflib``).

        Args:
            ontology: Ontology dict with ``entities`` and ``relationships`` keys.
                      When *None* the most recent batch result is used.
            filepath: If given, write the RDF string to this file and return None.
            format: Serialization format passed to ``rdflib.Graph.serialize()``.
                    Common values: ``"turtle"`` (default), ``"n3"``, ``"nt"``.

        Returns:
            RDF string when *filepath* is None, else None.

        Raises:
            ImportError: If ``rdflib`` is not installed.
        """
        try:
            from rdflib import Graph, Literal, Namespace, URIRef  # type: ignore[import]
            from rdflib.namespace import RDF, RDFS, XSD  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "rdflib is required for RDF export. Install with: pip install rdflib"
            ) from exc

        if ontology is None:
            if self._history:
                ontology = self._history[-1].metadata.get("last_ontology", {})
            ontology = ontology or {}

        ONT = Namespace("urn:optimizers:ontology:")
        g = Graph()
        g.bind("ont", ONT)

        for ent in ontology.get("entities", []):
            if not isinstance(ent, dict):
                continue
            eid = ent.get("id")
            if not eid:
                continue
            node = URIRef(ONT[eid])
            g.add((node, RDF.type, URIRef(ONT["Entity"])))
            if ent.get("text"):
                g.add((node, RDFS.label, Literal(ent["text"])))
            if ent.get("type"):
                g.add((node, URIRef(ONT["entityType"]), Literal(ent["type"])))

        for rel in ontology.get("relationships", []):
            if not isinstance(rel, dict):
                continue
            src = rel.get("source_id")
            tgt = rel.get("target_id")
            rel_type = rel.get("type")
            if src and tgt and rel_type:
                g.add((
                    URIRef(ONT[src]),
                    URIRef(ONT[rel_type]),
                    URIRef(ONT[tgt]),
                ))

        serialized = g.serialize(format=format)
        if filepath:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(serialized)
            return None
        return serialized

    def export_to_graphml(
        self,
        ontology: Optional[Dict[str, Any]] = None,
        filepath: Optional[str] = None,
    ) -> Optional[str]:
        """Export ontology to GraphML XML for visualization tools.

        Produces a minimal GraphML document (no external dependencies) that
        can be opened in Gephi, yEd, or NetworkX.

        Args:
            ontology: Ontology dict with ``entities`` and ``relationships`` keys.
                      When *None* the most recent batch result is used.
            filepath: If given, write the GraphML string to this file and return None.

        Returns:
            GraphML XML string when *filepath* is None, else None.
        """
        import xml.etree.ElementTree as ET

        if ontology is None:
            if self._history:
                ontology = self._history[-1].metadata.get("last_ontology", {})
            ontology = ontology or {}

        graphml = ET.Element(
            "graphml",
            xmlns="http://graphml.graphstruct.org/graphml",
        )
        # Key declarations
        ET.SubElement(graphml, "key", id="label", **{"for": "node", "attr.name": "label", "attr.type": "string"})
        ET.SubElement(graphml, "key", id="etype", **{"for": "node", "attr.name": "entityType", "attr.type": "string"})
        ET.SubElement(graphml, "key", id="rtype", **{"for": "edge", "attr.name": "relationshipType", "attr.type": "string"})

        graph_el = ET.SubElement(graphml, "graph", id="G", edgedefault="directed")

        for ent in ontology.get("entities", []):
            if not isinstance(ent, dict):
                continue
            eid = ent.get("id")
            if not eid:
                continue
            node = ET.SubElement(graph_el, "node", id=str(eid))
            if ent.get("text"):
                d = ET.SubElement(node, "data", key="label")
                d.text = str(ent["text"])
            if ent.get("type"):
                d = ET.SubElement(node, "data", key="etype")
                d.text = str(ent["type"])

        for idx, rel in enumerate(ontology.get("relationships", [])):
            if not isinstance(rel, dict):
                continue
            src = rel.get("source_id")
            tgt = rel.get("target_id")
            if not (src and tgt):
                continue
            edge = ET.SubElement(graph_el, "edge", id=f"e{idx}", source=str(src), target=str(tgt))
            if rel.get("type"):
                d = ET.SubElement(edge, "data", key="rtype")
                d.text = str(rel["type"])

        xml_str = ET.tostring(graphml, encoding="unicode", xml_declaration=False)
        result = '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_str

        if filepath:
            with open(filepath, "w", encoding="utf-8") as fh:
                fh.write(result)
            return None
        return result


# Export public API
__all__ = [
    'OntologyOptimizer',
    'OptimizationReport',
]

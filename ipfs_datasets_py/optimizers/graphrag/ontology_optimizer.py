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
import math
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

    def __repr__(self) -> str:
        """Return a concise developer-readable summary of this optimizer."""
        return (
            f"OntologyOptimizer("
            f"history_len={len(self._history)}, "
            f"metrics={'yes' if self._metrics is not None else 'no'}, "
            f"tracing={'yes' if self._tracer is not None else 'no'})"
        )

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

    def score_median(self) -> float:
        """Return the median of ``average_score`` values in history.

        Returns:
            Median score, or ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        vals = sorted(r.average_score for r in self._history)
        n = len(vals)
        mid = n // 2
        if n % 2 == 1:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

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

    def last_entry(self) -> Optional[Any]:
        """Return the most recent history entry, or ``None`` if empty."""
        if not self._history:
            return None
        return self._history[-1]

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

    def trend_string(self, window: int = 5) -> str:
        """Return a human-readable trend label based on recent score movement.

        Looks at the last ``window`` history entries and classifies the trend
        as one of ``"improving"``, ``"declining"``, ``"flat"``, or
        ``"volatile"``.  Requires at least 2 entries; returns ``"n/a"`` when
        fewer entries are available.

        Args:
            window: Number of most-recent entries to consider (default 5).

        Returns:
            One of ``"improving"``, ``"declining"``, ``"flat"``,
            ``"volatile"``, or ``"n/a"``.
        """
        entries = self._history[-window:] if len(self._history) >= 2 else []
        if len(entries) < 2:
            return "n/a"
        scores = [e.average_score for e in entries]
        diffs = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]
        up = sum(1 for d in diffs if d > 0.005)
        down = sum(1 for d in diffs if d < -0.005)
        if up > 0 and down > 0:
            return "volatile"
        if up > down:
            return "improving"
        if down > up:
            return "declining"
        return "flat"

    def entries_above_score(self, threshold: float) -> list:
        """Return history entries whose ``average_score`` exceeds *threshold*.

        Args:
            threshold: Minimum score (exclusive) to include.

        Returns:
            List of history entry objects (may be empty).
        """
        return [e for e in self._history if e.average_score > threshold]

    def running_average(self, window: int) -> list:
        """Return a list of window-averaged scores over history.

        Each element is the mean of ``window`` consecutive history entries.
        When ``window`` is larger than the history length, an empty list is
        returned.  ``window`` must be >= 1.

        Args:
            window: Number of consecutive entries to average.

        Returns:
            List of float averages, length ``max(0, len(history) - window + 1)``.

        Raises:
            ValueError: If ``window`` < 1.
        """
        if window < 1:
            raise ValueError("window must be >= 1")
        scores = [e.average_score for e in self._history]
        if len(scores) < window:
            return []
        return [
            sum(scores[i : i + window]) / window
            for i in range(len(scores) - window + 1)
        ]

    def score_quartiles(self) -> tuple:
        """Return (Q1, Q2, Q3) of history average_scores.

        Uses linear interpolation.  Returns ``(0.0, 0.0, 0.0)`` when history
        is empty.

        Returns:
            Tuple ``(q1, q2, q3)`` of floats.
        """
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        if n == 0:
            return (0.0, 0.0, 0.0)

        def _percentile(data, pct):
            idx = (len(data) - 1) * pct / 100.0
            lo = int(idx)
            hi = lo + 1
            if hi >= len(data):
                return data[-1]
            return data[lo] + (data[hi] - data[lo]) * (idx - lo)

        return (_percentile(scores, 25), _percentile(scores, 50), _percentile(scores, 75))

    def score_iqr(self) -> float:
        """Return the interquartile range (Q3 - Q1) of history scores.

        Returns:
            Float IQR, or ``0.0`` when history has fewer than 2 entries.
        """
        q1, _, q3 = self.score_quartiles()
        return q3 - q1

    def has_improved(self, baseline: float) -> bool:
        """Return ``True`` if any history entry has ``average_score > baseline``.

        Args:
            baseline: Reference score to beat.

        Returns:
            ``True`` when at least one entry exceeds *baseline*; ``False``
            otherwise (including when history is empty).
        """
        return any(e.average_score > baseline for e in self._history)

    def rolling_best(self, window: int = 5) -> Any:
        """Return the history entry with the highest ``average_score`` within
        the last *window* entries.

        Args:
            window: Number of most-recent entries to examine (default 5).

        Returns:
            The best history entry object, or ``None`` when history is empty.

        Raises:
            ValueError: If ``window`` < 1.
        """
        if window < 1:
            raise ValueError("window must be >= 1")
        entries = self._history[-window:] if self._history else []
        if not entries:
            return None
        return max(entries, key=lambda e: e.average_score)

    def plateau_count(self, tol: float = 0.005) -> int:
        """Return the number of consecutive history pairs within *tol* of each other.

        A "plateau pair" is a pair of adjacent entries whose absolute score
        difference is ≤ *tol*.

        Args:
            tol: Tolerance for two scores to be considered the same (default 0.005).

        Returns:
            Non-negative integer count of plateau pairs.
        """
        if len(self._history) < 2:
            return 0
        count = 0
        for i in range(len(self._history) - 1):
            if abs(self._history[i + 1].average_score - self._history[i].average_score) <= tol:
                count += 1
        return count

    def best_streak(self) -> int:
        """Return the length of the longest consecutive improving run.

        An *improving* step is one where ``average_score`` strictly increases.

        Returns:
            Length of the longest consecutive improvement streak; 0 if empty or
            no improvement was ever observed.
        """
        if len(self._history) < 2:
            return 0
        best = 0
        current = 0
        for i in range(len(self._history) - 1):
            if self._history[i + 1].average_score > self._history[i].average_score:
                current += 1
                best = max(best, current)
            else:
                current = 0
        return best

    def worst_streak(self) -> int:
        """Return the length of the longest consecutive declining run.

        A *declining* step is one where ``average_score`` strictly decreases.

        Returns:
            Length of the longest consecutive decline streak; 0 if empty or
            no decline was ever observed.
        """
        if len(self._history) < 2:
            return 0
        worst = 0
        current = 0
        for i in range(len(self._history) - 1):
            if self._history[i + 1].average_score < self._history[i].average_score:
                current += 1
                worst = max(worst, current)
            else:
                current = 0
        return worst

    def score_percentile_rank(self, score: float) -> float:
        """Return the percentile rank (0–100) of *score* among history entries.

        The percentile rank is the fraction of historical scores that are
        *less than or equal to* the given score, expressed as a percentage.

        Args:
            score: Score value to rank.

        Returns:
            Float in [0.0, 100.0]; 0.0 for empty history.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        count_le = sum(1 for s in scores if s <= score)
        return count_le / len(scores) * 100.0

    def score_momentum(self, window: int = 5) -> float:
        """Return the average score change over the last *window* history entries.

        Positive means improving, negative means declining, zero means flat.

        Args:
            window: Number of most-recent entries to inspect (default 5).

        Returns:
            Mean score delta per step; ``0.0`` if fewer than 2 entries.
        """
        entries = self._history[-window:] if len(self._history) >= 2 else []
        if len(entries) < 2:
            return 0.0
        diffs = [
            entries[i + 1].average_score - entries[i].average_score
            for i in range(len(entries) - 1)
        ]
        return sum(diffs) / len(diffs)

    def history_slice(self, start: int, end: int) -> list:
        """Return a slice of the history list from *start* to *end*.

        Args:
            start: Start index (inclusive).
            end: End index (exclusive).

        Returns:
            Sub-list of history entries.
        """
        return self._history[start:end]

    def score_above_count(self, threshold: float) -> int:
        """Alias for :meth:`entries_above_score` that returns the count instead of entries.

        Args:
            threshold: Minimum ``average_score`` to count.

        Returns:
            Number of history entries with ``average_score >= threshold``.
        """
        return len(self.entries_above_score(threshold))

    def first_entry_above(self, threshold: float) -> "Any | None":
        """Return the first history entry whose ``average_score`` meets *threshold*.

        Args:
            threshold: Minimum score to match.

        Returns:
            First matching entry, or ``None`` when none found.
        """
        for entry in self._history:
            if entry.average_score >= threshold:
                return entry
        return None

    def last_entry_above(self, threshold: float) -> "Any | None":
        """Return the most-recent history entry whose ``average_score`` meets *threshold*.

        Args:
            threshold: Minimum score to match.

        Returns:
            Last matching entry, or ``None`` when none found.
        """
        for entry in reversed(self._history):
            if entry.average_score >= threshold:
                return entry
        return None

    def score_at_index(self, index: int) -> float:
        """Return the ``average_score`` at the given *index* in history.

        Supports negative indexing (e.g., ``-1`` for last entry).

        Args:
            index: Position in history list.

        Returns:
            Score float; ``0.0`` when history is empty or index is out of range.
        """
        if not self._history:
            return 0.0
        try:
            return self._history[index].average_score
        except IndexError:
            return 0.0

    def improvement_from_start(self) -> float:
        """Return the score improvement from the first to the last history entry.

        Returns:
            ``last.average_score - first.average_score``; ``0.0`` when history
            has fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        return self._history[-1].average_score - self._history[0].average_score

    def is_improving_overall(self) -> bool:
        """Return ``True`` if the overall trend is positive.

        Computed as ``last_score > first_score``.

        Returns:
            ``True`` when there is net improvement; ``False`` otherwise or when
            history has fewer than 2 entries.
        """
        if len(self._history) < 2:
            return False
        return self._history[-1].average_score > self._history[0].average_score

    def history_as_dicts(self) -> list:
        """Return the history as a list of plain dicts for easy serialization.

        Each dict has keys ``index``, ``average_score``, and ``trend``.

        Returns:
            List of dicts; empty list when no history.
        """
        return [
            {
                "index": i,
                "average_score": entry.average_score,
                "trend": getattr(entry, "trend", "stable"),
            }
            for i, entry in enumerate(self._history)
        ]

    def top_k_history(self, k: int = 3) -> list:
        """Return the *k* history entries with the highest ``average_score``.

        Args:
            k: Number of entries to return.

        Returns:
            List of up to *k* history entries, sorted highest score first.
        """
        if not self._history:
            return []
        return sorted(self._history, key=lambda e: e.average_score, reverse=True)[:k]

    def history_score_std(self) -> float:
        """Return the standard deviation of ``average_score`` across history.

        Returns:
            Float standard deviation; ``0.0`` when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return variance ** 0.5

    def count_entries_with_trend(self, trend: str) -> int:
        """Count history entries matching a specific *trend* label.

        Args:
            trend: Trend string to match (e.g. ``"improving"``, ``"stable"``).

        Returns:
            Integer count.
        """
        return sum(1 for e in self._history if getattr(e, "trend", "stable") == trend)

    def dominant_trend(self) -> str:
        """Return the most frequent trend label across history.

        Returns:
            Trend string; ``"stable"`` when history is empty.
        """
        if not self._history:
            return "stable"
        from collections import Counter
        counts = Counter(getattr(e, "trend", "stable") for e in self._history)
        return counts.most_common(1)[0][0]

    def history_range(self) -> float:
        """Return the range (max - min) of ``average_score`` across history.

        Returns:
            Float range; ``0.0`` when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        return max(scores) - min(scores)

    def min_score(self) -> float:
        """Return the minimum ``average_score`` across history.

        Returns:
            Minimum float; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        return min(e.average_score for e in self._history)

    def max_score(self) -> float:
        """Return the maximum ``average_score`` across history.

        Returns:
            Maximum float; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        return max(e.average_score for e in self._history)

    def median_score(self) -> float:
        """Return the median ``average_score`` across history.

        Returns:
            Median float; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        vals = sorted(e.average_score for e in self._history)
        n = len(vals)
        mid = n // 2
        if n % 2 == 1:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

    def convergence_score(self) -> float:
        """Measure how much the optimization history is converging.

        Convergence is defined as ``1 - (std_of_last_half / std_of_first_half)``
        clamped to [0, 1].  A value of 1.0 means perfectly converged (zero
        variance in the last half); 0.0 means no improvement in stability.

        Returns:
            Float in [0, 1]; ``0.0`` when fewer than 4 history entries.
        """
        if len(self._history) < 4:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        first_half = scores[: n // 2]
        second_half = scores[n // 2 :]

        def _std(vals):
            m = sum(vals) / len(vals)
            return (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5

        std_first = _std(first_half)
        if std_first == 0:
            return 1.0
        std_second = _std(second_half)
        return max(0.0, min(1.0, 1.0 - std_second / std_first))

    def history_entropy(self) -> float:
        """Estimate the entropy of the score distribution in history.

        Scores are discretised into 10 equal-width bins between 0 and 1.
        Shannon entropy is computed over the resulting probability mass function.

        Returns:
            Non-negative float; ``0.0`` when history is empty or all scores
            fall in the same bin.
        """
        import math
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        # 10 bins in [0, 1]
        bins = [0] * 10
        for s in scores:
            idx = min(int(s * 10), 9)
            bins[idx] += 1
        n = len(scores)
        entropy = 0.0
        for count in bins:
            if count > 0:
                p = count / n
                entropy -= p * math.log2(p)
        return entropy

    def history_mode(self) -> float:
        """Return the most common score bin (mode) across history.

        Scores are bucketed into 10 equal-width bins.  The midpoint of the
        most-populated bin is returned.

        Returns:
            Midpoint float of the most common bin; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        bins = [0] * 10
        for s in scores:
            idx = min(int(s * 10), 9)
            bins[idx] += 1
        max_idx = bins.index(max(bins))
        return (max_idx + 0.5) / 10.0

    def history_autocorrelation(self, lag: int = 1) -> float:
        """Return the lag-*k* autocorrelation of average scores in history.

        A positive autocorrelation indicates trending behaviour; negative
        suggests alternating patterns.

        Args:
            lag: Lag in number of steps (default 1).

        Returns:
            Float autocorrelation in [-1, 1]; ``0.0`` when not enough history
            or variance is zero.
        """
        if len(self._history) <= lag:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        if variance == 0:
            return 0.0
        cov = sum((scores[i] - mean) * (scores[i - lag] - mean)
                  for i in range(lag, n)) / (n - lag)
        return cov / variance

    def history_stability(self) -> float:
        """Return a stability score for history: inverse coefficient of variation.

        Stability is defined as ``1 / (1 + CV)`` where CV = std / mean.
        A value approaching 1.0 means very stable (low variance relative to
        mean); lower values indicate high variability.

        Returns:
            Float in (0, 1]; ``0.0`` when history is empty or mean is zero.
        """
        import math
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        mean = sum(scores) / n
        if mean == 0:
            return 0.0
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = math.sqrt(variance)
        cv = std / mean
        return 1.0 / (1.0 + cv)

    def window_average(self, window: int = 5) -> float:
        """Return the average ``average_score`` over the last *window* entries.

        Args:
            window: Number of most recent history entries to average.

        Returns:
            Float mean; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        recent = self._history[-window:]
        return sum(e.average_score for e in recent) / len(recent)

    def first_n_history(self, n: int) -> list:
        """Return the first *n* history entries.

        Args:
            n: Number of entries to return from the start of history.

        Returns:
            List of up to *n* history entry objects.
        """
        return self._history[:n]

    def score_above_threshold(self, threshold: float = 0.7) -> list:
        """Return history entries whose ``average_score`` exceeds *threshold*.

        Args:
            threshold: Minimum score value (exclusive). Defaults to ``0.7``.

        Returns:
            List of history entries with ``average_score > threshold``.
        """
        return [e for e in self._history if e.average_score > threshold]

    def score_momentum_delta(self, window: int = 3) -> float:
        """Return the difference between the last window average and the prior window average.

        A positive value means recent scores are higher than earlier ones
        (momentum is positive).

        Args:
            window: Window size for each half (default 3).

        Returns:
            Float delta; ``0.0`` when fewer than ``2 * window`` history entries.
        """
        if len(self._history) < 2 * window:
            return 0.0
        scores = [e.average_score for e in self._history]
        recent = scores[-window:]
        prior = scores[-(2 * window):-window]
        return sum(recent) / len(recent) - sum(prior) / len(prior)

    def score_below_threshold(self, threshold: float = 0.5) -> list:
        """Return history entries whose ``average_score`` is below *threshold*.

        Args:
            threshold: Maximum score value (exclusive). Defaults to ``0.5``.

        Returns:
            List of history entries with ``average_score < threshold``.
        """
        return [e for e in self._history if e.average_score < threshold]

    def best_history_entry(self):
        """Return the history entry with the highest ``average_score``.

        Returns:
            The history entry object with the maximum ``average_score``;
            ``None`` when history is empty.
        """
        if not self._history:
            return None
        return max(self._history, key=lambda e: e.average_score)

    def history_variance(self) -> float:
        """Return the population variance of ``average_score`` across history.

        Returns:
            Float variance; ``0.0`` when history has fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        return sum((s - mean) ** 2 for s in scores) / len(scores)

    def history_iqr(self) -> float:
        """Return the inter-quartile range (IQR) of ``average_score`` values.

        Returns:
            Float IQR (Q3 - Q1); ``0.0`` when history has fewer than 4 entries.
        """
        if len(self._history) < 4:
            return 0.0
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        q1 = scores[n // 4]
        q3 = scores[(3 * n) // 4]
        return q3 - q1

    def top_n_history(self, n: int = 3) -> list:
        """Return the top-n history entries ordered by ``average_score`` desc.

        Args:
            n: Number of entries to return. Defaults to ``3``.

        Returns:
            List of history entries (up to *n*), highest score first.
        """
        return sorted(self._history, key=lambda e: e.average_score, reverse=True)[:n]


    def score_streak(self, direction: str = "up") -> int:
        """Return the length of the current consecutive streak.

        Args:
            direction: ``"up"`` for improving scores, ``"down"`` for declining.

        Returns:
            Length of the trailing streak (minimum 1 when any history exists,
            0 when history is empty).
        """
        if not self._history:
            return 0
        scores = [e.average_score for e in self._history]
        streak = 1
        for i in range(len(scores) - 1, 0, -1):
            if direction == "up" and scores[i] > scores[i - 1]:
                streak += 1
            elif direction == "down" and scores[i] < scores[i - 1]:
                streak += 1
            else:
                break
        return streak

    def recent_best_score(self, n: int = 5) -> float:
        """Return the best ``average_score`` among the last *n* history entries.

        Args:
            n: Number of recent entries to consider. Defaults to ``5``.

        Returns:
            Max score found; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        recent = self._history[-n:]
        return max(e.average_score for e in recent)

    def history_change_count(self) -> int:
        """Return the number of times the score trend changed direction.

        A "change" occurs when consecutive ``average_score`` values switch
        from rising to falling or vice versa.

        Returns:
            Integer count of direction changes; ``0`` when history has fewer
            than 3 entries.
        """
        if len(self._history) < 3:
            return 0
        scores = [e.average_score for e in self._history]
        changes = 0
        for i in range(1, len(scores) - 1):
            prev_dir = scores[i] - scores[i - 1]
            next_dir = scores[i + 1] - scores[i]
            if prev_dir * next_dir < 0:
                changes += 1
        return changes

    def score_moving_sum(self, n: int = 5) -> float:
        """Return the sum of the last *n* history ``average_score`` values.

        Args:
            n: Window size. Defaults to ``5``.

        Returns:
            Float sum; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        return sum(e.average_score for e in self._history[-n:])

    def history_skewness(self) -> float:
        """Return the sample skewness of ``average_score`` values in history.

        Uses the standard adjusted Fisher-Pearson formula:
        ``g1 = (n / ((n-1)(n-2))) * sum((xi - mean)^3) / std^3``

        Returns:
            Float skewness; ``0.0`` when fewer than 3 entries or std is 0.
        """
        n = len(self._history)
        if n < 3:
            return 0.0
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / n
        var = sum((s - mean) ** 2 for s in scores) / n
        if var == 0.0:
            return 0.0
        std = var ** 0.5
        third_moment = sum((s - mean) ** 3 for s in scores) / n
        g1 = third_moment / (std ** 3)
        # Adjusted Fisher-Pearson correction
        adj = (n * (n - 1)) ** 0.5 / (n - 2)
        return adj * g1


    def score_plateau_length(self, tolerance: float = 0.005) -> int:
        """Return the length of the longest flat-score plateau in history.

        A plateau is a maximal consecutive run where every adjacent pair of
        scores differs by no more than *tolerance*.

        Args:
            tolerance: Max absolute difference to be considered "flat".
                Defaults to 0.005.

        Returns:
            Integer length of the longest plateau; 1 when no consecutive
            pairs are flat; 0 when history is empty.
        """
        if not self._history:
            return 0
        scores = [e.average_score for e in self._history]
        best = 1
        current = 1
        for i in range(1, len(scores)):
            if abs(scores[i] - scores[i - 1]) <= tolerance:
                current += 1
                best = max(best, current)
            else:
                current = 1
        return best

    def score_above_percentile(self, p: float = 75.0) -> int:
        """Return count of history entries whose score exceeds the p-th percentile.

        Args:
            p: Percentile in [0, 100]. Defaults to 75.0.

        Returns:
            Integer count of scores strictly above the p-th percentile value;
            ``0`` when history is empty.
        """
        if not self._history:
            return 0
        scores = sorted(e.average_score for e in self._history)
        idx = int(len(scores) * p / 100.0)
        idx = min(idx, len(scores) - 1)
        threshold = scores[idx]
        return sum(1 for e in self._history if e.average_score > threshold)

    def score_gini_coefficient(self) -> float:
        """Return the Gini coefficient of history ``average_score`` values.

        A value of 0.0 means perfect equality; 1.0 means maximum inequality.

        Returns:
            Float in [0, 1]; ``0.0`` when history has fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        total = sum(scores)
        if total == 0.0:
            return 0.0
        rank_sum = sum((i + 1) * s for i, s in enumerate(scores))
        return (2 * rank_sum) / (n * total) - (n + 1) / n

    def history_trimmed_mean(self, trim: float = 0.1) -> float:
        """Return the trimmed mean of history ``average_score`` values.

        Args:
            trim: Fraction to remove from each end (e.g., 0.1 removes 10%
                  from both the bottom and top). Defaults to 0.1.

        Returns:
            Float trimmed mean; ``0.0`` when history is empty; regular mean
            when ``trim <= 0`` or fewer entries remain after trimming.
        """
        if not self._history:
            return 0.0
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        k = int(n * trim)
        trimmed = scores[k:n - k] if k > 0 else scores
        if not trimmed:
            return sum(scores) / n
        return sum(trimmed) / len(trimmed)

    def score_z_scores(self) -> list:
        """Return a list of z-scores for each history entry's ``average_score``.

        Returns:
            List of floats; empty list when history has fewer than 2 entries
            or std is 0.
        """
        if len(self._history) < 2:
            return []
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        if variance == 0.0:
            return [0.0] * len(scores)
        std = variance ** 0.5
        return [(s - mean) / std for s in scores]

    def score_cumulative_max(self) -> list:
        """Return the running maximum of average_score across history.

        Each position *i* in the returned list is the maximum ``average_score``
        seen in entries ``[0 … i]``.

        Returns:
            List of floats with the same length as ``_history``; empty list
            when there is no history.
        """
        if not self._history:
            return []
        result = []
        current_max = float("-inf")
        for entry in self._history:
            current_max = max(current_max, entry.average_score)
            result.append(current_max)
        return result

    def score_cumulative_min(self) -> list:
        """Return the running minimum of average_score across history.

        Each position *i* in the returned list is the minimum ``average_score``
        seen in entries ``[0 … i]``.

        Returns:
            List of floats with the same length as ``_history``; empty list
            when there is no history.
        """
        if not self._history:
            return []
        result = []
        current_min = float("inf")
        for entry in self._history:
            current_min = min(current_min, entry.average_score)
            result.append(current_min)
        return result

    def history_below_median_count(self) -> int:
        """Return the number of history entries with average_score below the median.

        Returns:
            Integer count; 0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        if n % 2 == 1:
            median = scores[n // 2]
        else:
            median = (scores[n // 2 - 1] + scores[n // 2]) / 2.0
        return sum(1 for e in self._history if e.average_score < median)

    def score_trend_strength(self) -> float:
        """Return the absolute linear trend magnitude normalised to history length.

        Fits a linear regression to ``average_score`` vs. index and returns
        the absolute slope.  Useful for measuring how strongly the optimizer
        is improving or degrading over time.

        Returns:
            Non-negative float; 0.0 when fewer than 2 history entries.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        x_mean = (n - 1) / 2.0
        y_mean = sum(scores) / n
        numerator = sum((i - x_mean) * (scores[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        return abs(numerator / denominator)

    def history_kurtosis(self) -> float:
        """Return the excess kurtosis of ``average_score`` values in history.

        Uses the population formula (Fisher's definition, excess kurtosis = 0
        for a normal distribution).

        Returns:
            Float excess kurtosis; 0.0 when fewer than 4 history entries or
            when variance is zero.
        """
        if len(self._history) < 4:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        if variance == 0.0:
            return 0.0
        m4 = sum((s - mean) ** 4 for s in scores) / n
        return m4 / (variance ** 2) - 3.0

    def score_ewma(self, alpha: float = 0.3) -> float:
        """Return the exponential weighted moving average of history scores.

        Args:
            alpha: Smoothing factor (0 < alpha <= 1).

        Returns:
            Float EWMA; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        ewma = self._history[0].average_score
        for entry in self._history[1:]:
            ewma = alpha * entry.average_score + (1.0 - alpha) * ewma
        return ewma

    def history_second_derivative(self) -> list:
        """Return the second derivative (acceleration) of average_score over history.

        The first derivative is the list of consecutive differences; the second
        derivative is the differences of the differences.

        Returns:
            List of floats with length ``len(_history) - 2``; empty list when
            fewer than 3 history entries.
        """
        if len(self._history) < 3:
            return []
        scores = [e.average_score for e in self._history]
        first_deriv = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]
        return [first_deriv[i + 1] - first_deriv[i] for i in range(len(first_deriv) - 1)]

    def history_first_derivative(self) -> list:
        """Return the first derivative of ``average_score`` over history.

        The first derivative is the list of consecutive differences between
        consecutive entries.

        Returns:
            List of floats with length ``len(_history) - 1``; empty list when
            fewer than 2 history entries.
        """
        if len(self._history) < 2:
            return []
        scores = [e.average_score for e in self._history]
        return [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]

    def score_improvement_ratio(self) -> float:
        """Return the fraction of consecutive transitions that are improvements.

        An improvement is when ``average_score`` increases from one entry to
        the next.

        Returns:
            Float in [0, 1]; 0.0 when fewer than 2 history entries.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        improvements = sum(1 for i in range(1, len(scores)) if scores[i] > scores[i - 1])
        return improvements / (len(scores) - 1)

    def history_percentile(self, p: float = 50.0) -> float:
        """Return the *p*-th percentile of ``average_score`` values in history.

        Uses linear interpolation.

        Args:
            p: Percentile in [0, 100].

        Returns:
            Float; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        if n == 1:
            return scores[0]
        idx = (p / 100.0) * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return scores[lo] + (scores[hi] - scores[lo]) * (idx - lo)

    def score_below_percentile_count(self, p: float = 25.0) -> int:
        """Return the number of history entries below the *p*-th percentile.

        Args:
            p: Percentile threshold in [0, 100].

        Returns:
            Integer count.
        """
        threshold = self.history_percentile(p)
        return sum(1 for e in self._history if e.average_score < threshold)

    def history_entropy_change(self) -> float:
        """Return the change in entropy of scores between first half and second half.

        Computes a rough 5-bin histogram entropy for each half and returns
        ``entropy_second - entropy_first``.  A positive value means scores are
        becoming more spread; negative means more concentrated.

        Returns:
            Float; 0.0 when fewer than 4 history entries.
        """
        import math
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 4:
            return 0.0

        def _entropy(vals: list) -> float:
            if not vals:
                return 0.0
            mn, mx = min(vals), max(vals)
            if mx == mn:
                return 0.0
            bins = [0] * 5
            for v in vals:
                idx = min(4, int((v - mn) / (mx - mn) * 5))
                bins[idx] += 1
            total = len(vals)
            return -sum((c / total) * math.log(c / total) for c in bins if c > 0)

        mid = n // 2
        return _entropy(scores[mid:]) - _entropy(scores[:mid])

    def score_variance_trend(self) -> float:
        """Estimate whether score variance is increasing or decreasing over time.

        Splits history into halves and returns variance(second_half) - variance(first_half).
        Positive → variance growing; negative → variance shrinking.

        Returns:
            Float; 0.0 when fewer than 4 history entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 4:
            return 0.0

        def _var(vals: list) -> float:
            if len(vals) < 2:
                return 0.0
            mean = sum(vals) / len(vals)
            return sum((v - mean) ** 2 for v in vals) / len(vals)

        mid = n // 2
        return _var(scores[mid:]) - _var(scores[:mid])

    def score_above_mean_fraction(self) -> float:
        """Return fraction of history entries whose score is above the mean.

        Returns:
            Float in [0, 1]; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        return sum(1 for s in scores if s > mean) / len(scores)

    def history_gini(self) -> float:
        """Return the Gini coefficient of history scores as a disparity measure.

        A value of 0 means perfect equality (all scores equal); 1 means
        maximum inequality.

        Returns:
            Float in [0, 1); 0.0 when fewer than 2 history entries.
        """
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        if n < 2:
            return 0.0
        total = sum(scores)
        if total == 0.0:
            return 0.0
        numer = sum((i + 1) * v for i, v in enumerate(scores))
        return (2 * numer / (n * total)) - (n + 1) / n

    def history_outlier_count(self, z_thresh: float = 2.0) -> int:
        """Return the number of history entries whose z-score exceeds *z_thresh*.

        Args:
            z_thresh: Absolute z-score threshold (default 2.0).

        Returns:
            Integer count; 0 when fewer than 2 entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 2:
            return 0
        mean = sum(scores) / n
        std = (sum((s - mean) ** 2 for s in scores) / n) ** 0.5
        if std == 0.0:
            return 0
        return sum(1 for s in scores if abs((s - mean) / std) > z_thresh)

    def score_autocorrelation(self, lag: int = 1) -> float:
        """Return the lag-*lag* autocorrelation of history scores.

        Uses the Pearson correlation between ``scores[:-lag]`` and ``scores[lag:]``.

        Args:
            lag: Lag value (default 1).

        Returns:
            Float in [-1, 1]; 0.0 when insufficient data.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n <= lag:
            return 0.0
        x = scores[:-lag]
        y = scores[lag:]
        m = len(x)
        mx = sum(x) / m
        my = sum(y) / m
        num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
        dx = sum((xi - mx) ** 2 for xi in x) ** 0.5
        dy = sum((yi - my) ** 2 for yi in y) ** 0.5
        if dx == 0.0 or dy == 0.0:
            return 0.0
        return num / (dx * dy)

    def history_cross_mean_count(self) -> int:
        """Return the number of times scores cross the historical mean.

        A crossing occurs when consecutive entries straddle the mean from
        above-to-below or below-to-above.

        Returns:
            Integer count; 0 when fewer than 2 history entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 2:
            return 0
        mean = sum(scores) / n
        count = 0
        for i in range(1, n):
            if (scores[i - 1] >= mean) != (scores[i] >= mean):
                count += 1
        return count

    def score_recent_max(self, window: int = 5) -> float:
        """Return the maximum score within the most recent *window* entries.

        Args:
            window: Number of most-recent entries to consider (default 5).

        Returns:
            Float; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        recent = self._history[-window:]
        return max(e.average_score for e in recent)

    def score_recent_min(self, window: int = 5) -> float:
        """Return the minimum score within the most recent *window* entries.

        Args:
            window: Number of most-recent entries to consider (default 5).

        Returns:
            Float; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        recent = self._history[-window:]
        return min(e.average_score for e in recent)


    def history_std_ratio(self, window: int = 5) -> float:
        """Return std(recent window) / std(full history) as a volatility ratio.

        A value > 1 means recent scores are more volatile; < 1 means calmer.

        Args:
            window: Recent window size (default 5).

        Returns:
            Float; 0.0 when insufficient data.
        """
        scores = [e.average_score for e in self._history]
        if len(scores) < 4:
            return 0.0

        def _std(vals: list) -> float:
            if len(vals) < 2:
                return 0.0
            mean = sum(vals) / len(vals)
            return (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5

        global_std = _std(scores)
        if global_std == 0.0:
            return 0.0
        return _std(scores[-window:]) / global_std

    def score_turning_points(self) -> int:
        """Return the count of local minima and maxima in score history.

        A turning point is a position where consecutive differences change sign.

        Returns:
            Integer count; 0 when fewer than 3 entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 3:
            return 0
        diffs = [scores[i + 1] - scores[i] for i in range(n - 1)]
        return sum(1 for i in range(1, len(diffs)) if diffs[i - 1] * diffs[i] < 0)

    def history_momentum_score(self, window: int = 5, alpha: float = 0.5) -> float:
        """Return a momentum score: exponentially weighted sum of recent deltas.

        Positive means accelerating improvement; negative means decline.

        Args:
            window: Number of recent consecutive differences to include.
            alpha: Decay factor applied to older differences (default 0.5).

        Returns:
            Float; 0.0 when fewer than 2 history entries.
        """
        scores = [e.average_score for e in self._history]
        if len(scores) < 2:
            return 0.0
        diffs = [scores[i + 1] - scores[i] for i in range(len(scores) - 1)]
        recent_diffs = diffs[-window:]
        result = 0.0
        for i, d in enumerate(reversed(recent_diffs)):
            result += (alpha ** i) * d
        return result

    def score_signed_sum(self) -> float:
        """Return the sum of consecutive signed deltas (score[i+1] - score[i]).

        Equivalent to score_last - score_first.

        Returns:
            Float; 0.0 when fewer than 2 history entries.
        """
        scores = [e.average_score for e in self._history]
        if len(scores) < 2:
            return 0.0
        return scores[-1] - scores[0]


    def score_acceleration(self) -> float:
        """Return the mean second derivative of scores (acceleration).

        Positive means the rate of improvement is increasing; negative means
        it is slowing.

        Returns:
            Float; 0.0 when fewer than 3 history entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 3:
            return 0.0
        first_deriv = [scores[i + 1] - scores[i] for i in range(n - 1)]
        second_deriv = [first_deriv[i + 1] - first_deriv[i] for i in range(len(first_deriv) - 1)]
        return sum(second_deriv) / len(second_deriv)

    def history_peak_count(self) -> int:
        """Return the number of local maxima in score history.

        A local maximum is a point where both neighbors are lower.

        Returns:
            Integer count; 0 when fewer than 3 entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 3:
            return 0
        return sum(1 for i in range(1, n - 1) if scores[i] > scores[i - 1] and scores[i] > scores[i + 1])


    def history_valley_count(self) -> int:
        """Return the number of local minima in score history.

        A local minimum is a point where both neighbors are strictly higher.

        Returns:
            Integer count; 0 when fewer than 3 entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 3:
            return 0
        return sum(1 for i in range(1, n - 1) if scores[i] < scores[i - 1] and scores[i] < scores[i + 1])

    def score_trend_correlation(self) -> float:
        """Return Pearson correlation between time index and history scores.

        Positive → improving trend; negative → declining; near 0 → flat.

        Returns:
            Float in [-1, 1]; 0.0 when fewer than 2 history entries.
        """
        scores = [e.average_score for e in self._history]
        n = len(scores)
        if n < 2:
            return 0.0
        indices = list(range(n))
        mx = sum(indices) / n
        my = sum(scores) / n
        num = sum((i - mx) * (s - my) for i, s in zip(indices, scores))
        di = sum((i - mx) ** 2 for i in indices) ** 0.5
        ds = sum((s - my) ** 2 for s in scores) ** 0.5
        if di == 0.0 or ds == 0.0:
            return 0.0
        return num / (di * ds)


    def history_weighted_mean(self, weights: list | None = None) -> float:
        """Return weighted mean of average_score over history.

        Args:
            weights: List of floats same length as history. If None, uses
                     linearly increasing weights (more recent = higher weight).

        Returns:
            Weighted mean; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        n = len(self._history)
        if weights is None:
            weights = [float(i + 1) for i in range(n)]
        if len(weights) != n:
            weights = weights[:n] if len(weights) > n else weights + [1.0] * (n - len(weights))
        total_w = sum(weights)
        if total_w == 0:
            return 0.0
        return sum(w * e.average_score for w, e in zip(weights, self._history)) / total_w

    def score_consecutive_above(self, threshold: float = 0.7) -> int:
        """Return the length of the trailing streak of entries scoring above threshold.

        Args:
            threshold: Score threshold (exclusive). Defaults to 0.7.

        Returns:
            Integer count of consecutive recent entries with average_score > threshold.
        """
        count = 0
        for entry in reversed(self._history):
            if entry.average_score > threshold:
                count += 1
            else:
                break
        return count


    def history_min(self) -> float:
        """Return the minimum average_score across all history entries.

        Returns:
            Float minimum; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        return min(e.average_score for e in self._history)

    def history_max(self) -> float:
        """Return the maximum average_score across all history entries.

        Returns:
            Float maximum; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        return max(e.average_score for e in self._history)

    def history_rolling_mean(self, window: int = 3) -> float:
        """Return the mean of the last *window* history entries.

        Args:
            window: Number of most-recent entries to average. Defaults to 3.

        Returns:
            Float mean; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        recent = self._history[-window:]
        return sum(e.average_score for e in recent) / len(recent)


    def history_above_mean_count(self) -> int:
        """Return the number of history entries with average_score above the mean.

        Returns:
            Integer count; 0 when history is empty.
        """
        if not self._history:
            return 0
        mean = sum(e.average_score for e in self._history) / len(self._history)
        return sum(1 for e in self._history if e.average_score > mean)

    def score_delta_mean(self) -> float:
        """Return the mean of consecutive score differences (deltas) in history.

        Returns:
            Float mean delta; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        deltas = [
            self._history[i + 1].average_score - self._history[i].average_score
            for i in range(len(self._history) - 1)
        ]
        return sum(deltas) / len(deltas)

    def history_median(self) -> float:
        """Return the median of average_score across all history entries.

        Returns:
            Float median; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        vals = sorted(e.average_score for e in self._history)
        n = len(vals)
        if n % 2 == 0:
            return (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        return vals[n // 2]

    def score_above_rolling_mean(self, window: int = 3) -> int:
        """Return count of history entries above the rolling mean of the last *window* entries.

        Args:
            window: Window size for rolling mean. Defaults to 3.

        Returns:
            Integer count; 0 when history is empty.
        """
        if not self._history:
            return 0
        recent = self._history[-window:]
        rolling = sum(e.average_score for e in recent) / len(recent)
        return sum(1 for e in self._history if e.average_score > rolling)


    def history_first(self) -> float:
        """Return the average_score of the first history entry.

        Returns:
            Float score; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        return self._history[0].average_score

    def history_last(self) -> float:
        """Return the average_score of the most recent history entry.

        Returns:
            Float score; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        return self._history[-1].average_score

    def score_first(self) -> float:
        """Alias for history_first — returns the first recorded average_score.

        Returns:
            Float score; 0.0 when history is empty.
        """
        return self.history_first()

    def score_last(self) -> float:
        """Alias for history_last — returns the most recent average_score.

        Returns:
            Float score; 0.0 when history is empty.
        """
        return self.history_last()


    def history_streak_above(self, threshold: float = 0.7) -> int:
        """Return the length of the current streak of entries scoring above threshold.

        This counts from the END of history backward (most recent streak).

        Args:
            threshold: Exclusive lower bound. Defaults to 0.7.

        Returns:
            Integer streak length; 0 when no entries exceed threshold.
        """
        streak = 0
        for entry in reversed(self._history):
            if entry.average_score > threshold:
                streak += 1
            else:
                break
        return streak

    def score_volatility(self) -> float:
        """Return the standard deviation of consecutive deltas in history.

        A high value indicates erratic score behaviour.

        Returns:
            Float standard deviation of deltas; 0.0 when fewer than 3 entries.
        """
        if len(self._history) < 3:
            return 0.0
        deltas = [
            self._history[i + 1].average_score - self._history[i].average_score
            for i in range(len(self._history) - 1)
        ]
        n = len(deltas)
        mean = sum(deltas) / n
        variance = sum((d - mean) ** 2 for d in deltas) / n
        return variance ** 0.5

    def history_percentile_rank(self, value: float) -> float:
        """Return the percentile rank of *value* within history scores.

        Args:
            value: Score to rank against history.

        Returns:
            Float in [0, 100]; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        n = len(self._history)
        below = sum(1 for e in self._history if e.average_score < value)
        return (below / n) * 100.0


    def history_span(self) -> float:
        """Return the difference between max and min average_score in history.

        Returns:
            Float span (max - min); 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        vals = [e.average_score for e in self._history]
        return max(vals) - min(vals)

    def history_change_rate(self) -> float:
        """Return the fraction of consecutive pairs where score changed (non-zero delta).

        Returns:
            Float in [0, 1]; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        changes = sum(
            1 for i in range(len(self._history) - 1)
            if self._history[i + 1].average_score != self._history[i].average_score
        )
        return changes / (len(self._history) - 1)

    def history_trend_direction(self) -> str:
        """Return a string indicating the overall trend direction of history.

        Compares the mean of the second half against the first half.

        Returns:
            ``"improving"``, ``"declining"``, or ``"stable"``.
            Returns ``"stable"`` when history is empty or has 1 entry.
        """
        n = len(self._history)
        if n < 2:
            return "stable"
        mid = n // 2
        first_half = [e.average_score for e in self._history[:mid]]
        second_half = [e.average_score for e in self._history[mid:]]
        mean_first = sum(first_half) / len(first_half)
        mean_second = sum(second_half) / len(second_half)
        diff = mean_second - mean_first
        if diff > 0.01:
            return "improving"
        if diff < -0.01:
            return "declining"
        return "stable"


    def history_cumulative_sum(self) -> float:
        """Return the cumulative sum of all average_score values in history.

        Returns:
            Float sum; 0.0 when history is empty.
        """
        return sum(e.average_score for e in self._history)

    def score_normalized(self) -> float:
        """Return the last score normalized by the max score in history.

        Returns:
            Float in [0, 1]; 0.0 when history is empty or max is 0.
        """
        if not self._history:
            return 0.0
        max_score = max(e.average_score for e in self._history)
        if max_score == 0:
            return 0.0
        return self._history[-1].average_score / max_score

    def score_z_score(self) -> float:
        """Return the z-score of the most recent history entry.

        Computes z = (last - mean) / std using the population standard deviation.

        Returns:
            Float z-score; 0.0 when fewer than 2 entries or std is zero.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std = variance ** 0.5
        if std == 0.0:
            return 0.0
        return (scores[-1] - mean) / std

    def history_trimmed_mean(self, trim_fraction: float = 0.1, trim: Optional[float] = None) -> float:
        """Return trimmed mean of history scores, ignoring extremes.

        The trim removes a fraction of scores from both ends of the sorted list.

        Args:
            trim_fraction: Fraction in [0, 0.5) to trim from each tail. Defaults to 0.1.
            trim: Alias for ``trim_fraction`` (takes precedence if provided).

        Returns:
            Float trimmed mean; 0.0 when no history recorded.
        
        Raises:
            ValueError: If trim_fraction not in [0.0, 0.5).
        
        Example:
            >>> opt = OntologyOptimizer()
            >>> opt._history = [OptEntry(avg_score=0.5), OptEntry(avg_score=0.9), OptEntry(avg_score=0.6)]
            >>> opt.history_trimmed_mean(trim_fraction=0.2)
            0.7
        """
        if trim is not None:
            trim_fraction = trim
        if not self._history:
            return 0.0
        if trim_fraction < 0.0 or trim_fraction >= 0.5:
            raise ValueError("trim_fraction must be in [0.0, 0.5).")
        
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        k = int(n * trim_fraction)
        
        # If no trimming occurs or trimming would remove too much, use full mean
        if k == 0 or k * 2 >= n:
            return sum(scores) / n
        
        # Trim k elements from each tail
        trimmed = scores[k:n - k]
        return sum(trimmed) / len(trimmed)

    def history_decay_sum(self, decay: float = 0.9) -> float:
        """Return exponentially decayed sum of average_score (oldest gets most decay).

        The most recent entry has weight 1.0; each older entry multiplied by *decay*.

        Args:
            decay: Decay factor per step. Defaults to 0.9.

        Returns:
            Float weighted sum; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        entries = list(reversed(self._history))
        return sum(e.average_score * (decay ** i) for i, e in enumerate(entries))


    def score_delta_std(self) -> float:
        """Return the standard deviation of consecutive score deltas.

        Returns:
            Float std dev of deltas; 0.0 when fewer than 3 entries.
        """
        if len(self._history) < 3:
            return 0.0
        deltas = [
            self._history[i + 1].average_score - self._history[i].average_score
            for i in range(len(self._history) - 1)
        ]
        n = len(deltas)
        mean = sum(deltas) / n
        variance = sum((d - mean) ** 2 for d in deltas) / n
        return variance ** 0.5

    def history_coefficient_of_variation(self) -> float:
        """Return the coefficient of variation (std / mean) of history scores.

        Returns:
            Float CV; 0.0 when history is empty or mean is 0.
        """
        if not self._history:
            return 0.0
        vals = [e.average_score for e in self._history]
        mean = sum(vals) / len(vals)
        if mean == 0:
            return 0.0
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        return variance ** 0.5 / mean


    def history_above_threshold_rate(self, threshold: float = 0.7) -> float:
        """Return the fraction of history entries scoring above threshold.

        Args:
            threshold: Exclusive lower bound. Defaults to 0.7.

        Returns:
            Float in [0, 1]; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        return sum(1 for e in self._history if e.average_score > threshold) / len(self._history)

    def history_improving_fraction(self) -> float:
        """Return the fraction of consecutive pairs where score improved.

        Returns:
            Float in [0, 1]; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        improvements = sum(
            1 for i in range(len(self._history) - 1)
            if self._history[i + 1].average_score > self._history[i].average_score
        )
        return improvements / (len(self._history) - 1)

    def score_percentile_of_last(self) -> float:
        """Return the percentile rank of the last score within history.

        Returns:
            Float in [0, 100]; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        last = self._history[-1].average_score
        return self.history_percentile_rank(last)


    def score_z_score(self) -> float:
        """Return the z-score of the most recent average_score relative to history.

        z = (last - mean) / std

        Returns:
            Float z-score; 0.0 when history has fewer than 2 entries or std = 0.
        """
        if len(self._history) < 2:
            return 0.0
        vals = [e.average_score for e in self._history]
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = variance ** 0.5
        if std == 0:
            return 0.0
        return (vals[-1] - mean) / std

    def score_mad(self) -> float:
        """Return the median absolute deviation (MAD) of history scores.

        MAD = median(|x_i - median(x)|)

        Returns:
            Float MAD; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        vals = sorted(e.average_score for e in self._history)
        n = len(vals)
        if n % 2 == 0:
            median = (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        else:
            median = vals[n // 2]
        deviations = sorted(abs(v - median) for v in vals)
        if n % 2 == 0:
            return (deviations[n // 2 - 1] + deviations[n // 2]) / 2.0
        return deviations[n // 2]

    def history_quantile(self, q: float = 0.25) -> float:
        """Return the q-th quantile of history scores (linear interpolation).

        Args:
            q: Quantile in [0, 1]. Defaults to 0.25.

        Returns:
            Float quantile; 0.0 when history is empty.
        """
        if not self._history:
            return 0.0
        vals = sorted(e.average_score for e in self._history)
        n = len(vals)
        idx = q * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        frac = idx - lo
        return vals[lo] + frac * (vals[hi] - vals[lo])

    def score_interquartile_mean(self) -> float:
        """Return the mean of scores within the IQR (25th–75th percentile).

        Returns:
            Float mean; 0.0 when fewer than 4 entries.
        """
        if len(self._history) < 4:
            return 0.0
        vals = sorted(e.average_score for e in self._history)
        n = len(vals)
        q1_idx = n // 4
        q3_idx = (3 * n) // 4
        iqr_vals = vals[q1_idx:q3_idx + 1]
        return sum(iqr_vals) / len(iqr_vals) if iqr_vals else 0.0

    def score_bimodality_coefficient(self) -> float:
        """Return Sarle's bimodality coefficient for the history scores.

        BC = (skewness^2 + 1) / kurtosis, clipped to [0, 1].
        Returns 0.0 when fewer than 3 entries or kurtosis == 0.

        Returns:
            Float in [0.0, 1.0].
        """
        if len(self._history) < 3:
            return 0.0
        vals = [e.average_score for e in self._history]
        n = len(vals)
        mean = sum(vals) / n
        diffs = [v - mean for v in vals]
        var = sum(d ** 2 for d in diffs) / n
        if var == 0:
            return 0.0
        std = var ** 0.5
        skew = (sum(d ** 3 for d in diffs) / n) / (std ** 3)
        kurt = (sum(d ** 4 for d in diffs) / n) / (var ** 2)
        if kurt == 0:
            return 0.0
        bc = (skew ** 2 + 1) / kurt
        return float(max(0.0, min(1.0, bc)))

    def score_below_threshold_rate(self, threshold: float = 0.5) -> float:
        """Return the fraction of history scores strictly below *threshold*.

        Args:
            threshold: Score cutoff. Defaults to 0.5.

        Returns:
            Float in [0.0, 1.0]; 0.0 when no history.
        """
        if not self._history:
            return 0.0
        count = sum(1 for e in self._history if e.average_score < threshold)
        return count / len(self._history)

    def history_plateau_count(self, tolerance: float = 0.01) -> int:
        """Count runs of 2+ consecutive entries within *tolerance* of each other.

        Each qualifying run of length L contributes (L - 1) to the count.

        Args:
            tolerance: Maximum absolute difference to consider a plateau. Defaults to 0.01.

        Returns:
            Integer count of plateau step pairs; 0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0
        count = 0
        for a, b in zip(self._history, self._history[1:]):
            if abs(a.average_score - b.average_score) <= tolerance:
                count += 1
        return count

    def history_run_last_improvement(self) -> float:
        """Return the index (0-based) of the last entry where the score improved.

        An improvement is defined as score[i] > score[i-1].

        Returns:
            Float index of the last improvement; -1.0 when no improvement found or
            fewer than 2 entries.
        """
        if len(self._history) < 2:
            return -1.0
        last = -1
        for i in range(1, len(self._history)):
            if self._history[i].average_score > self._history[i - 1].average_score:
                last = i
        return float(last)

    def history_above_threshold_streak(self, threshold: float = 0.5) -> int:
        """Return the length of the current trailing run of scores above *threshold*.

        Args:
            threshold: Score cutoff. Defaults to 0.5.

        Returns:
            Integer length of the current streak from the end; 0 when no history.
        """
        streak = 0
        for entry in reversed(self._history):
            if entry.average_score > threshold:
                streak += 1
            else:
                break
        return streak

    def score_above_threshold_longest_streak(self, threshold: float = 0.5) -> int:
        """Return the length of the longest consecutive run of scores above *threshold*.

        Args:
            threshold: Score cutoff. Defaults to 0.5.

        Returns:
            Integer length of the longest such streak; 0 when no history.
        """
        max_streak = 0
        cur_streak = 0
        for entry in self._history:
            if entry.average_score > threshold:
                cur_streak += 1
                max_streak = max(max_streak, cur_streak)
            else:
                cur_streak = 0
        return max_streak

    def score_delta_abs_mean(self) -> float:
        """Return the mean of the absolute score deltas between consecutive entries.

        Returns:
            Float mean absolute delta; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        deltas = [
            abs(self._history[i].average_score - self._history[i - 1].average_score)
            for i in range(1, len(self._history))
        ]
        return sum(deltas) / len(deltas)

    def history_improving_count(self) -> int:
        """Return the number of steps where the score improved over the previous entry.

        Returns:
            Integer count; 0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0
        return sum(
            1
            for i in range(1, len(self._history))
            if self._history[i].average_score > self._history[i - 1].average_score
        )

    def score_trailing_mean(self, n: int = 5) -> float:
        """Return the mean of the last *n* history scores.

        Args:
            n: Number of trailing entries to average. Defaults to 5.

        Returns:
            Float mean; 0.0 when no history.
        """
        if not self._history:
            return 0.0
        tail = self._history[-n:]
        return sum(e.average_score for e in tail) / len(tail)

    def history_mean_last_n(self, n: int = 3) -> float:
        """Return the mean of the last *n* entries (alias with explicit param name).

        Args:
            n: Number of trailing entries. Defaults to 3.

        Returns:
            Float mean; 0.0 when no history.
        """
        return self.score_trailing_mean(n=n)

    def history_stagnation_rate(self, tolerance: float = 0.005) -> float:
        """Return the fraction of consecutive pairs where the score did not improve.

        A step is "stagnant" when |score[i] - score[i-1]| <= tolerance.

        Args:
            tolerance: Maximum absolute change to consider stagnant. Defaults to 0.005.

        Returns:
            Float in [0.0, 1.0]; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        n = len(self._history) - 1
        stagnant = sum(
            1
            for i in range(1, len(self._history))
            if abs(self._history[i].average_score - self._history[i - 1].average_score) <= tolerance
        )
        return stagnant / n

    def score_vs_baseline(self, baseline: float = 0.5) -> float:
        """Return the difference between the latest score and *baseline*.

        Args:
            baseline: Reference score. Defaults to 0.5.

        Returns:
            Float difference (latest - baseline); 0.0 when no history.
        """
        if not self._history:
            return 0.0
        return self._history[-1].average_score - baseline

    def score_mean_above_baseline(self, baseline: float = 0.5) -> float:
        """Return the mean of all history scores that are strictly above *baseline*.

        Args:
            baseline: Threshold to filter scores. Defaults to 0.5.

        Returns:
            Float mean; 0.0 when no scores above baseline.
        """
        above = [e.average_score for e in self._history if e.average_score > baseline]
        return sum(above) / len(above) if above else 0.0

    def history_volatility_ratio(self) -> float:
        """Return the ratio of score std to score mean (coefficient of variation).

        Same as ``history_coefficient_of_variation`` but computed from scratch
        as a documentation alias.

        Returns:
            Float CV; 0.0 when fewer than 2 entries or mean == 0.
        """
        if len(self._history) < 2:
            return 0.0
        vals = [e.average_score for e in self._history]
        mean = sum(vals) / len(vals)
        if mean == 0:
            return 0.0
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        return (var ** 0.5) / mean

    def score_relative_to_best(self) -> float:
        """Return the latest score as a fraction of the all-time best score.

        Returns:
            Float in [0.0, 1.0]; 0.0 when no history or best == 0.
        """
        if not self._history:
            return 0.0
        vals = [e.average_score for e in self._history]
        best = max(vals)
        if best == 0:
            return 0.0
        return vals[-1] / best

    def history_decline_rate(self, threshold: float = 0.5) -> float:
        """Return the fraction of consecutive steps where the score declined.

        A step is a "decline" when score[i] < score[i-1].

        Args:
            threshold: Unused parameter kept for API symmetry.

        Returns:
            Float in [0.0, 1.0]; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        n = len(self._history) - 1
        declines = sum(
            1
            for i in range(1, len(self._history))
            if self._history[i].average_score < self._history[i - 1].average_score
        )
        return declines / n

    def score_rebound_count(self) -> int:
        """Count rebounds: steps where score went down then back up.

        A rebound is when score[i-1] > score[i] and score[i] < score[i+1].

        Returns:
            Integer count; 0 when fewer than 3 entries.
        """
        if len(self._history) < 3:
            return 0
        count = 0
        vals = [e.average_score for e in self._history]
        for i in range(1, len(vals) - 1):
            if vals[i] < vals[i - 1] and vals[i] < vals[i + 1]:
                count += 1
        return count

    def history_zscore_last(self) -> float:
        """Return the z-score of the last entry relative to the full history.

        Uses population std (divides by N).

        Returns:
            Float z-score; 0.0 when fewer than 2 entries or std == 0.
        """
        if len(self._history) < 2:
            return 0.0
        vals = [e.average_score for e in self._history]
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = var ** 0.5
        if std == 0:
            return 0.0
        return (vals[-1] - mean) / std

    def history_top_k_mean(self, k: int = 3) -> float:
        """Return the mean of the top *k* history scores.

        Args:
            k: Number of top scores to average. Defaults to 3.

        Returns:
            Float mean; 0.0 when no history.
        """
        if not self._history:
            return 0.0
        top_k = sorted((e.average_score for e in self._history), reverse=True)[:k]
        return sum(top_k) / len(top_k)

    def score_second_derivative(self) -> float:
        """Return the second derivative (acceleration) of the score at the last entry.

        Computed as: score[-1] - 2*score[-2] + score[-3].

        Returns:
            Float second derivative; 0.0 when fewer than 3 entries.
        """
        if len(self._history) < 3:
            return 0.0
        a, b, c = (
            self._history[-3].average_score,
            self._history[-2].average_score,
            self._history[-1].average_score,
        )
        return c - 2 * b + a

    def history_rank_of_last(self) -> int:
        """Return the rank (1-based) of the last score in descending order.

        A rank of 1 means the last score is the highest.

        Returns:
            Integer rank; 0 when no history.
        """
        if not self._history:
            return 0
        vals = [e.average_score for e in self._history]
        sorted_desc = sorted(vals, reverse=True)
        last = vals[-1]
        # Find the position (1-based) of the last score in sorted list
        for i, v in enumerate(sorted_desc):
            if v == last:
                return i + 1
        return len(vals)

    def score_nearest_neighbor_delta(self) -> float:
        """Return the absolute difference between the last two history scores.

        Returns:
            Float absolute delta; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        return abs(self._history[-1].average_score - self._history[-2].average_score)

    def score_half_life_estimate(self) -> float:
        """Estimate the number of steps for the score to increase by half of the remaining gap to 1.0.

        Uses the average improvement rate: steps = 0.5 / avg_improvement.
        Returns inf when no improvement (flat or declining history).

        Returns:
            Float; 0.0 when fewer than 2 entries; float('inf') when avg_improvement <= 0.
        """
        if len(self._history) < 2:
            return 0.0
        improvements = [
            self._history[i].average_score - self._history[i - 1].average_score
            for i in range(1, len(self._history))
        ]
        avg_improvement = sum(improvements) / len(improvements)
        if avg_improvement <= 0:
            return float("inf")
        return 0.5 / avg_improvement

    def history_increasing_fraction(self) -> float:
        """Return the fraction of consecutive steps where the score increased.

        Args:
            (none)

        Returns:
            Float in [0.0, 1.0]; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        n = len(self._history) - 1
        increasing = sum(
            1
            for i in range(1, len(self._history))
            if self._history[i].average_score > self._history[i - 1].average_score
        )
        return increasing / n

    def score_gain_rate(self) -> float:
        """Return the net gain per step as (last - first) / (n - 1).

        Returns:
            Float; 0.0 when fewer than 2 entries.
        """
        if len(self._history) < 2:
            return 0.0
        first = self._history[0].average_score
        last = self._history[-1].average_score
        return (last - first) / (len(self._history) - 1)

    def history_weight_by_recency(self) -> float:
        """Return a recency-weighted mean using linearly increasing weights.

        The most-recent entry receives weight *n*, the oldest receives weight 1.

        Returns:
            Float; 0.0 when no history.
        """
        if not self._history:
            return 0.0
        n = len(self._history)
        total_weight = n * (n + 1) / 2
        weighted_sum = sum(
            (i + 1) * entry.average_score
            for i, entry in enumerate(self._history)
        )
        return weighted_sum / total_weight

    def score_mean_top_k(self, k: int = 3) -> float:
        """Return the mean of the top-*k* history scores.

        Args:
            k: Number of top entries to average. Defaults to 3.

        Returns:
            Float; 0.0 when no history.
        """
        if not self._history:
            return 0.0
        scores = sorted((e.average_score for e in self._history), reverse=True)
        top = scores[:k]
        return sum(top) / len(top)

    def history_last_n_range(self, n: int = 5) -> float:
        """Return the range (max − min) of the last *n* history scores.

        Args:
            n: Window size. Defaults to 5.

        Returns:
            Float; 0.0 when no history.
        """
        if not self._history:
            return 0.0
        window = [e.average_score for e in self._history[-n:]]
        return max(window) - min(window)

    def score_trimmed_range(self, trim: float = 0.1) -> float:
        """Return the range after trimming *trim* fraction from each tail.

        Args:
            trim: Fraction to trim from each end. Defaults to 0.1 (10%).

        Returns:
            Float; 0.0 when fewer than 3 entries.
        """
        scores = sorted(e.average_score for e in self._history)
        if len(scores) < 3:
            return 0.0
        cut = max(1, int(len(scores) * trim))
        trimmed = scores[cut:-cut]
        if not trimmed:
            return 0.0
        return max(trimmed) - min(trimmed)

    def history_geometric_mean(self) -> float:
        """Return the geometric mean of history scores.

        Only positive scores are included. Returns 0.0 when no positive scores.

        Returns:
            Float >= 0.0.
        """
        positives = [e.average_score for e in self._history if e.average_score > 0]
        if not positives:
            return 0.0
        log_sum = sum(__import__("math").log(s) for s in positives)
        return __import__("math").exp(log_sum / len(positives))

    def score_at_index(self, index: int) -> float:
        """Get the score at a specific index in history.

        Args:
            index: Position in history list (0-indexed). Supports negative indexing.

        Returns:
            Average score at the given index, or 0.0 if index out of bounds.
        """
        if not self._history:
            return 0.0
        try:
            return self._history[index].average_score
        except IndexError:
            return 0.0

    @property
    def history_length(self) -> int:
        """Return the number of entries in the history.

        Returns:
            Number of history entries (>= 0).
        """
        return len(self._history)

    def score_recent_variance(self, n: int = 5) -> float:
        """Calculate variance of the last N scores.

        Args:
            n: Number of recent entries to consider.

        Returns:
            Variance of last N scores, or 0.0 if fewer than N entries.
        """
        if n < 1:
            return 0.0
        recent = [e.average_score for e in self._history[-n:]]
        if len(recent) < 2:
            return 0.0
        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        return variance

    def score_recent_mean(self, n: int = 5) -> float:
        """Calculate mean of the last N scores.

        Args:
            n: Number of recent entries to consider.

        Returns:
            Mean of last N scores (or all if fewer than N), or 0.0 if empty.
        """
        if n < 1 or not self._history:
            return 0.0
        recent = [e.average_score for e in self._history[-n:]]
        return sum(recent) / len(recent) if recent else 0.0

    def has_regressed(self, threshold: float = 0.01) -> bool:
        """Check if current score has regressed vs best score.

        Args:
            threshold: Minimum absolute drop to count as regression.

        Returns:
            True if last score < best score - threshold, else False.
        """
        if len(self._history) < 2:
            return False
        best = max(e.average_score for e in self._history)
        last = self._history[-1].average_score
        return (best - last) >= threshold

    def improvement_ratio(self) -> float:
        """Calculate percentage improvement from first to best score.

        Returns improvement as fraction (0.0 to inf). First score of 0 returns 0.0.

        Returns:
            Improvement ratio (best - first) / first, or 0.0 if undefined.
        """
        if not self._history or len(self._history) < 2:
            return 0.0
        first = self._history[0].average_score
        if first <= 0:
            return 0.0
        best = max(e.average_score for e in self._history)
        return (best - first) / first

    def score_recovery_time(self, threshold: float = 0.7) -> int:
        """Count rounds needed to recover above threshold after dropping below.

        Finds first below-threshold score, then counts rounds to get back above.

        Returns:
            Number of rounds to recover, or -1 if never dropped or never recovered.
        """
        if not self._history:
            return -1
        
        # Find first drop below threshold
        drop_idx = -1
        for i, entry in enumerate(self._history):
            if entry.average_score < threshold:
                drop_idx = i
                break
        
        if drop_idx == -1:
            return -1  # Never dropped below threshold
        
        # Find recovery after drop
        for i in range(drop_idx + 1, len(self._history)):
            if self._history[i].average_score >= threshold:
                return i - drop_idx
        
        return -1  # Never recovered

    def score_below_baseline(self, baseline: float = 0.5) -> int:
        """Count entries with score below a baseline value.

        Args:
            baseline: Threshold score value.

        Returns:
            Count of history entries below baseline.
        """
        return sum(1 for e in self._history if e.average_score < baseline)

    def moving_median(self, window: int = 5) -> float:
        """Calculate median of the last N scores.

        Args:
            window: Window size for median calculation.

        Returns:
            Median of last N scores, or 0.0 if empty/insufficient data.
        """
        if window < 1 or not self._history:
            return 0.0
        recent = sorted([e.average_score for e in self._history[-window:]])
        if not recent:
            return 0.0
        n = len(recent)
        if n % 2 == 1:
            return recent[n // 2]
        return (recent[n // 2 - 1] + recent[n // 2]) / 2.0

    def trend_reversal_count(self) -> int:
        """Count the number of trend reversals in the score history.

        A reversal occurs when improving→declining or declining→improving.

        Returns:
            Number of trend reversals (>= 0).
        """
        if len(self._history) < 3:
            return 0
        
        reversals = 0
        improving = None
        
        for i in range(1, len(self._history)):
            current = self._history[i].average_score
            previous = self._history[i-1].average_score
            delta = current - previous
            
            if delta > 1e-6:  # Improving
                current_trend = True
            elif delta < -1e-6:  # Declining
                current_trend = False
            else:  # Flat
                continue
            
            if improving is not None and improving != current_trend:
                reversals += 1
            
            improving = current_trend
        
        return reversals


    def score_geometric_mean(self) -> float:
        """Return the geometric mean of all history ``average_score`` values.

        Returns:
            Float geometric mean in [0, 1]; ``0.0`` when any score is zero or
            when history is empty.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        if any(s <= 0.0 for s in scores):
            return 0.0
        product = 1.0
        for s in scores:
            product *= s
        return product ** (1.0 / len(scores))

    def score_harmonic_mean(self) -> float:
        """Return the harmonic mean of all history ``average_score`` values.

        Returns:
            Float harmonic mean; ``0.0`` when any score is zero or history
            is empty.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        if any(s <= 0.0 for s in scores):
            return 0.0
        return len(scores) / sum(1.0 / s for s in scores)

    def score_coefficient_of_variation(self) -> float:
        """Return the coefficient of variation (std / mean) of history scores.

        Returns:
            Float CV; ``0.0`` when history is empty or mean is zero.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        if mean == 0.0:
            return 0.0
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        return variance ** 0.5 / mean

    def score_relative_improvement(self) -> float:
        """Return the relative improvement from first to last score.

        Defined as ``(last - first) / first`` when ``first > 0``.

        Returns:
            Float; ``0.0`` when history has fewer than 2 entries or
            the first score is zero.
        """
        if len(self._history) < 2:
            return 0.0
        first = self._history[0].average_score
        last = self._history[-1].average_score
        if first == 0.0:
            return 0.0
        return (last - first) / first

    def score_to_mean_ratio(self) -> float:
        """Return the ratio of the latest score to the history mean.

        Returns:
            Float ratio; ``0.0`` when history is empty or mean is zero.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        if mean == 0.0:
            return 0.0
        return self._history[-1].average_score / mean

    def score_iqr(self) -> float:
        """Return the interquartile range (IQR) of history ``average_score`` values.

        IQR is the difference between the 75th and 25th percentile.

        Returns:
            Float IQR; ``0.0`` when fewer than 4 history entries.
        """
        if len(self._history) < 4:
            return 0.0
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        q1_idx = n // 4
        q3_idx = (3 * n) // 4
        return scores[q3_idx] - scores[q1_idx]

    def history_rolling_std(self, window: int = 3) -> list:
        """Return a list of rolling standard deviations over ``window``-sized windows.

        Args:
            window: Window size (must be >= 2).

        Returns:
            List of float std-dev values; one per valid window.  Empty list
            when history has fewer than ``window`` entries.
        """
        if window < 2:
            window = 2
        scores = [e.average_score for e in self._history]
        if len(scores) < window:
            return []
        result = []
        for i in range(len(scores) - window + 1):
            chunk = scores[i:i + window]
            mean = sum(chunk) / window
            variance = sum((v - mean) ** 2 for v in chunk) / window
            result.append(variance ** 0.5)
        return result

    def score_skewness(self) -> float:
        """Return the skewness of history ``average_score`` values.

        Uses the population skewness formula:
        ``(1/n) * sum((x - mean)^3) / std^3``.

        Returns:
            Float skewness; ``0.0`` when fewer than 3 history entries or
            standard deviation is zero.
        """
        if len(self._history) < 3:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        if variance == 0.0:
            return 0.0
        std = variance ** 0.5
        return sum((s - mean) ** 3 for s in scores) / (n * std ** 3)

    def score_entropy(self) -> float:
        """Return the Shannon entropy of history ``average_score`` values.

        Discretises scores into 10 equal bins in [0, 1] and computes
        ``H = -sum(p * log2(p))`` over non-empty bins.

        Returns:
            Float entropy in bits; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        bins = [0] * 10
        for s in scores:
            idx = min(int(s * 10), 9)
            bins[idx] += 1
        n = len(scores)
        entropy = 0.0
        for count in bins:
            if count > 0:
                p = count / n
                entropy -= p * math.log2(p)
        return entropy

    def history_above_percentile(self, p: float = 75.0) -> int:
        """Return the count of history entries with score above the ``p``-th percentile.

        Args:
            p: Percentile in [0, 100].  Default ``75``.

        Returns:
            Non-negative integer count; ``0`` when history is empty.
        """
        if not self._history:
            return 0
        scores = sorted(e.average_score for e in self._history)
        n = len(scores)
        idx = int(p / 100 * n)
        idx = min(idx, n - 1)
        threshold = scores[idx]
        return sum(1 for e in self._history if e.average_score > threshold)

    def score_gini(self) -> float:
        """Return the Gini coefficient of history ``average_score`` values.

        Alias for :meth:`score_gini_coefficient`.

        Returns:
            Float Gini coefficient in [0, 1]; ``0.0`` when history is empty.
        """
        return self.score_gini_coefficient()

    def score_trend_slope(self) -> float:
        """Return the linear regression slope of history ``average_score`` values.

        Uses ordinary least squares over the index positions (0, 1, 2, …).

        Returns:
            Float slope; positive means improving trend, negative means
            declining.  ``0.0`` when fewer than 2 history entries or when
            x-variance is zero.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(scores) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, scores))
        den = sum((x - x_mean) ** 2 for x in xs)
        if den == 0.0:
            return 0.0
        return num / den

    def score_trend_intercept(self) -> float:
        """Return the OLS intercept of history ``average_score`` values.

        Computed as ``y_mean - slope * x_mean`` where *x* are index positions.

        Returns:
            Float intercept; ``0.0`` when fewer than 2 history entries or
            x-variance is zero.
        """
        if len(self._history) < 2:
            return 0.0
        scores = [e.average_score for e in self._history]
        n = len(scores)
        xs = list(range(n))
        x_mean = sum(xs) / n
        y_mean = sum(scores) / n
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, scores))
        den = sum((x - x_mean) ** 2 for x in xs)
        if den == 0.0:
            return 0.0
        slope = num / den
        return y_mean - slope * x_mean

    def above_target_rate(self, target: float = 0.7) -> float:
        """Return the fraction of history entries with score strictly above *target*.

        Args:
            target: Score threshold.  Default ``0.7``.

        Returns:
            Float in [0, 1]; ``0.0`` when history is empty.
        """
        if not self._history:
            return 0.0
        count = sum(1 for e in self._history if e.average_score > target)
        return count / len(self._history)

    def score_mad(self) -> float:
        """Return the Mean Absolute Deviation (MAD) of history scores.

        MAD measures the average absolute distance of each score from the
        mean, and is less sensitive to outliers than variance.

        Returns:
            Float ≥ 0; ``0.0`` when history is empty or all scores are equal.

        Example::

            >>> opt.score_mad()  # non-negative
        """
        if not self._history:
            return 0.0
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        return sum(abs(s - mean) for s in scores) / len(scores)

    def score_zscore_outliers(self, threshold: float = 2.0) -> list:
        """Return the indices of history scores whose |z-score| exceeds *threshold*.

        Uses population standard deviation.  Scores with ``|z| > threshold``
        are considered outliers.

        Args:
            threshold: Minimum absolute z-score to count as an outlier.
                Default ``2.0``.

        Returns:
            List of integer indices (0-based) into the history score list.
            Empty list when history has fewer than 2 entries or standard
            deviation is zero.

        Example::

            >>> opt.score_zscore_outliers(threshold=2.0)
            [0, 4]
        """
        if len(self._history) < 2:
            return []
        scores = [e.average_score for e in self._history]
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        if variance == 0.0:
            return []
        std = variance ** 0.5
        return [i for i, s in enumerate(scores) if abs((s - mean) / std) > threshold]


# Export public API
__all__ = [
    'OntologyOptimizer',
    'OptimizationReport',
]

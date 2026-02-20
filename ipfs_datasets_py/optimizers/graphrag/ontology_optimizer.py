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
    ):
        """
        Initialize the ontology optimizer.
        
        Args:
            logger: Optional :class:`logging.Logger` to use instead of the
                module-level logger. Useful for dependency injection in tests.
        """
        import logging as _logging
        self._log = logger or _logging.getLogger(__name__)
        self._history: List[OptimizationReport] = []
        self._tracer = None
        if enable_tracing and HAVE_OPENTELEMETRY and trace is not None:
            self._tracer = trace.get_tracer(__name__)
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
        
        return report

    def analyze_batch_parallel(
        self,
        session_results: List[Any],
        max_workers: int = 4,
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
                    if hasattr(score, dim):
                        distribution[dim].append(getattr(score, dim))
        
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


# Export public API
__all__ = [
    'OntologyOptimizer',
    'OptimizationReport',
]

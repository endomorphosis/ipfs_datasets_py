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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

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
    
    def __init__(self):
        """Initialize the ontology optimizer."""
        self._history: List[OptimizationReport] = []
        logger.info("Initialized OntologyOptimizer")
    
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
        logger.info(f"Analyzing batch of {len(session_results)} sessions")
        
        if not session_results:
            return OptimizationReport(
                average_score=0.0,
                trend='insufficient_data',
                recommendations=["Need more sessions to analyze"]
            )
        
        # Extract scores
        scores = []
        for result in session_results:
            if hasattr(result, 'critic_scores') and result.critic_scores:
                # MediatorState
                scores.append(result.critic_scores[-1].overall)
            elif hasattr(result, 'critic_score'):
                # SessionResult
                scores.append(result.critic_score.overall)
        
        if not scores:
            return OptimizationReport(
                average_score=0.0,
                trend='no_scores',
                recommendations=["No valid scores found"]
            )
        
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
        
        logger.info(
            f"Batch analysis: avg={average_score:.2f}, trend={trend}, "
            f"recs={len(recommendations)}"
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
        results = historical_results or self._history
        
        if len(results) < 2:
            return {
                'improvement_rate': 0.0,
                'trend': 'insufficient_data',
                'convergence_estimate': None,
                'best_batch': None,
                'recommendations': ["Need more batches to analyze trends"]
            }
        
        logger.info(f"Analyzing trends across {len(results)} batches")
        
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
        
        return {
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
        logger.info(f"Identifying patterns in {len(successful_ontologies)} successful ontologies")

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

        patterns = {
            "common_entity_types": [t for t, _ in entity_type_counts.most_common(10)],
            "common_relationship_types": [t for t, _ in relationship_type_counts.most_common(10)],
            "avg_entity_count": avg(entity_counts),
            "avg_relationship_count": avg(relationship_counts),
            "common_properties": [k for k, _ in property_key_counts.most_common(15)],
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
        
        # TODO: Implement intelligent recommendation generation
        # This is a placeholder for Phase 2 implementation
        
        if hasattr(current_state, 'critic_scores') and current_state.critic_scores:
            latest_score = current_state.critic_scores[-1]
            
            if latest_score.completeness < 0.7:
                recommendations.append("Increase entity extraction coverage")
            if latest_score.consistency < 0.7:
                recommendations.append("Improve logical consistency validation")
            if latest_score.clarity < 0.7:
                recommendations.append("Add more detailed entity properties")
        
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
        """Identify patterns across session results."""
        # TODO: Implement pattern identification
        return {}
    
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


# Export public API
__all__ = [
    'OntologyOptimizer',
    'OptimizationReport',
]

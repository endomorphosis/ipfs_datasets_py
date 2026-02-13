"""Logic Optimizer - SGD-based improvement of logic extraction.

This module implements the optimizer that analyzes critic feedback and
generates recommendations for improving logic extraction quality.

Uses stochastic gradient descent (SGD) principles to iteratively improve
extraction performance based on critic evaluations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class OptimizationStrategy(Enum):
    """Strategy for optimization."""
    PROMPT_TUNING = "prompt_tuning"  # Optimize extraction prompts
    CONFIDENCE_ADJUSTMENT = "confidence_adjustment"  # Adjust confidence thresholds
    MODE_SELECTION = "mode_selection"  # Improve extraction mode selection
    ONTOLOGY_ALIGNMENT = "ontology_alignment"  # Improve ontology alignment
    MULTI_OBJECTIVE = "multi_objective"  # Optimize multiple objectives


@dataclass
class OptimizationReport:
    """Report of optimization analysis and recommendations.
    
    Attributes:
        average_score: Average score across evaluated sessions
        trend: Trend indicator ('improving', 'stable', 'declining')
        recommendations: Ordered list of recommendations
        insights: Key insights from analysis
        convergence_status: Whether optimization has converged
        metrics: Detailed metrics by dimension
    """
    average_score: float
    trend: str
    recommendations: List[str]
    insights: List[str] = field(default_factory=list)
    convergence_status: str = "not_converged"
    metrics: Dict[str, Any] = field(default_factory=dict)


class LogicOptimizer:
    """Optimizer for improving logic extraction quality through SGD.
    
    This optimizer analyzes critic feedback across multiple extraction
    sessions and generates actionable recommendations for improvement.
    
    It tracks:
    - Score trends over time
    - Common failure patterns
    - Successful strategies
    - Convergence toward optimal performance
    
    Example:
        >>> optimizer = LogicOptimizer()
        >>> # Run initial batch
        >>> results = harness.run_sessions(data_samples)
        >>> report = optimizer.analyze_batch(results)
        >>> print(report.recommendations)
        >>> # Apply recommendations and run again
        >>> improved_results = harness.run_sessions(data_samples)
        >>> trend_report = optimizer.analyze_trends([results, improved_results])
    """
    
    def __init__(
        self,
        convergence_threshold: float = 0.85,
        min_improvement_rate: float = 0.01,
        window_size: int = 5
    ):
        """Initialize the logic optimizer.
        
        Args:
            convergence_threshold: Score threshold for convergence
            min_improvement_rate: Minimum improvement rate to continue
            window_size: Window size for trend analysis
        """
        self.convergence_threshold = convergence_threshold
        self.min_improvement_rate = min_improvement_rate
        self.window_size = window_size
        
        # Track history for analysis
        self.score_history: List[float] = []
        self.batch_history: List[List[Any]] = []
        
    def analyze_batch(self, session_results: List[Any]) -> OptimizationReport:
        """Analyze a batch of session results.
        
        Args:
            session_results: List of SessionResult objects
            
        Returns:
            OptimizationReport with recommendations
        """
        if not session_results:
            return OptimizationReport(
                average_score=0.0,
                trend="insufficient_data",
                recommendations=["Run more sessions to analyze"]
            )
        
        # Calculate average score
        scores = [r.critic_score.overall for r in session_results if hasattr(r, 'critic_score')]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        
        # Track history
        self.score_history.append(avg_score)
        self.batch_history.append(session_results)
        
        # Analyze trends
        trend = self._analyze_trend()
        
        # Aggregate dimension scores
        dimension_metrics = self._aggregate_dimensions(session_results)
        
        # Identify patterns
        insights = self._identify_patterns(session_results)
        
        # Generate recommendations
        recommendations = self._generate_recommendations(
            dimension_metrics,
            insights,
            avg_score
        )
        
        # Check convergence
        convergence = self._check_convergence(avg_score, trend)
        
        return OptimizationReport(
            average_score=avg_score,
            trend=trend,
            recommendations=recommendations,
            insights=insights,
            convergence_status=convergence,
            metrics=dimension_metrics
        )
    
    def analyze_trends(
        self,
        historical_results: List[List[Any]]
    ) -> OptimizationReport:
        """Analyze trends across multiple batches.
        
        Args:
            historical_results: List of batches of session results
            
        Returns:
            OptimizationReport with trend analysis
        """
        if not historical_results:
            return OptimizationReport(
                average_score=0.0,
                trend="insufficient_data",
                recommendations=["Need at least one batch of results"]
            )
        
        # Calculate scores for each batch
        batch_scores = []
        for batch in historical_results:
            scores = [r.critic_score.overall for r in batch if hasattr(r, 'critic_score')]
            if scores:
                batch_scores.append(sum(scores) / len(scores))
        
        # Calculate improvement rate
        improvement_rate = 0.0
        if len(batch_scores) >= 2:
            improvement_rate = (batch_scores[-1] - batch_scores[0]) / len(batch_scores)
        
        # Determine trend
        trend = "stable"
        if improvement_rate > self.min_improvement_rate:
            trend = "improving"
        elif improvement_rate < -self.min_improvement_rate:
            trend = "declining"
        
        insights = [
            f"Processed {len(historical_results)} batches",
            f"Improvement rate: {improvement_rate:.4f} per batch",
            f"Current average: {batch_scores[-1]:.3f}" if batch_scores else "No scores"
        ]
        
        recommendations = []
        if trend == "declining":
            recommendations.append("Performance declining - review recent changes")
            recommendations.append("Consider reverting to previous configuration")
        elif trend == "stable" and batch_scores and batch_scores[-1] < self.convergence_threshold:
            recommendations.append("Performance plateaued - try different optimization strategy")
        elif trend == "improving":
            recommendations.append("Continue current approach - showing improvement")
        
        return OptimizationReport(
            average_score=batch_scores[-1] if batch_scores else 0.0,
            trend=trend,
            recommendations=recommendations,
            insights=insights,
            metrics={'improvement_rate': improvement_rate, 'batch_scores': batch_scores}
        )
    
    def _analyze_trend(self) -> str:
        """Analyze score trend from history.
        
        Returns:
            Trend indicator string
        """
        if len(self.score_history) < 2:
            return "insufficient_data"
        
        # Look at recent window
        window = self.score_history[-self.window_size:]
        
        if len(window) < 2:
            return "insufficient_data"
        
        # Calculate trend
        improvement = window[-1] - window[0]
        
        if improvement > self.min_improvement_rate:
            return "improving"
        elif improvement < -self.min_improvement_rate:
            return "declining"
        else:
            return "stable"
    
    def _aggregate_dimensions(
        self,
        session_results: List[Any]
    ) -> Dict[str, Any]:
        """Aggregate dimension scores across sessions.
        
        Args:
            session_results: List of session results
            
        Returns:
            Aggregated dimension metrics
        """
        dimension_scores = defaultdict(list)
        
        for result in session_results:
            if not hasattr(result, 'critic_score'):
                continue
            
            for dim_score in result.critic_score.dimension_scores:
                dimension_scores[dim_score.dimension.value].append(dim_score.score)
        
        # Calculate averages
        metrics = {}
        for dim, scores in dimension_scores.items():
            metrics[dim] = {
                'average': sum(scores) / len(scores) if scores else 0.0,
                'min': min(scores) if scores else 0.0,
                'max': max(scores) if scores else 0.0,
                'count': len(scores)
            }
        
        return metrics
    
    def _identify_patterns(self, session_results: List[Any]) -> List[str]:
        """Identify patterns in results.
        
        Args:
            session_results: List of session results
            
        Returns:
            List of identified patterns/insights
        """
        insights = []
        
        # Common weaknesses
        weaknesses = defaultdict(int)
        for result in session_results:
            if hasattr(result, 'critic_score'):
                for weakness in result.critic_score.weaknesses:
                    weaknesses[weakness] += 1
        
        if weaknesses:
            most_common = max(weaknesses.items(), key=lambda x: x[1])
            insights.append(f"Most common weakness: {most_common[0]} ({most_common[1]} occurrences)")
        
        # Success rate
        successful = sum(1 for r in session_results if hasattr(r, 'success') and r.success)
        total = len(session_results)
        success_rate = successful / total if total > 0 else 0.0
        insights.append(f"Success rate: {success_rate:.1%}")
        
        return insights
    
    def _generate_recommendations(
        self,
        dimension_metrics: Dict[str, Any],
        insights: List[str],
        avg_score: float
    ) -> List[str]:
        """Generate specific recommendations based on analysis.
        
        Args:
            dimension_metrics: Aggregated dimension metrics
            insights: Identified patterns
            avg_score: Average overall score
            
        Returns:
            Ordered list of recommendations
        """
        recommendations = []
        
        # Check each dimension for low scores
        for dim, metrics in dimension_metrics.items():
            if metrics['average'] < 0.5:
                if dim == 'soundness':
                    recommendations.append(
                        "CRITICAL: Improve logical soundness - use stricter validation"
                    )
                elif dim == 'completeness':
                    recommendations.append(
                        "HIGH: Extract more information from input data"
                    )
                elif dim == 'consistency':
                    recommendations.append(
                        "HIGH: Add consistency checking between statements"
                    )
                elif dim == 'ontology_alignment':
                    recommendations.append(
                        "MEDIUM: Improve ontology alignment - review terminology"
                    )
                elif dim == 'parsability':
                    recommendations.append(
                        "HIGH: Use standard formal logic syntax"
                    )
                elif dim == 'expressiveness':
                    recommendations.append(
                        "LOW: Add more detail to logical statements"
                    )
        
        # Overall score recommendations
        if avg_score < 0.4:
            recommendations.insert(0, "URGENT: Overall quality very low - review extraction approach")
        elif avg_score > 0.8:
            recommendations.append("Excellent quality - consider more challenging test cases")
        
        # Default recommendation if none generated
        if not recommendations:
            recommendations.append("Quality is good - continue monitoring performance")
        
        return recommendations
    
    def _check_convergence(self, avg_score: float, trend: str) -> str:
        """Check if optimization has converged.
        
        Args:
            avg_score: Current average score
            trend: Current trend
            
        Returns:
            Convergence status string
        """
        if avg_score >= self.convergence_threshold:
            return "converged"
        elif trend == "stable" and avg_score > 0.7:
            return "near_convergence"
        else:
            return "not_converged"
    
    def get_optimization_parameters(self) -> Dict[str, Any]:
        """Get current optimization parameters.
        
        Returns:
            Dictionary of optimization parameters
        """
        return {
            'convergence_threshold': self.convergence_threshold,
            'min_improvement_rate': self.min_improvement_rate,
            'window_size': self.window_size,
            'iterations_completed': len(self.score_history)
        }
    
    def reset_history(self) -> None:
        """Reset optimization history."""
        self.score_history.clear()
        self.batch_history.clear()
        logger.info("Optimization history reset")

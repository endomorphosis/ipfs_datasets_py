"""
Statistical analysis and metric computation for CriticScore objects.

This module provides a ScoreAnalyzer class that computes various statistical
properties and metrics from CriticScore instances. It handles dimension-based
analysis, statistical distributions, and comparative metrics.

The analyzer is designed to work independently of OntologyCritic, allowing
scores to be analyzed and compared in various contexts:

- Batch analysis: Compute statistics from multiple scores
- Trend analysis: Compare scores over time
- Threshold calibration: Recommend score thresholds
- Distribution analysis: Understand score distributions
- Comparative metrics: Rank and compare ontologies

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag import ScoreAnalyzer
    >>> analyzer = ScoreAnalyzer()
    >>> 
    >>> # Single score analysis
    >>> weakest = analyzer.weakest_dimension(score)
    >>> entropy = analyzer.score_dimension_entropy(score)
    >>> 
    >>> # Batch analysis
    >>> mean_score = analyzer.mean_overall(scores)
    >>> threshold = analyzer.percentile_overall(scores, percentile=75.0)
    >>> 
    >>> # Trend analysis
    >>> delta = analyzer.dimension_delta(before_score, after_score)
    >>> slope = analyzer.dimension_trend_slope(score1, score2)

References:
    - CriticScore: Found in ontology_critic.py
    - OntologyCritic: Uses ScoreAnalyzer for statistical analysis
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard dimension names across all critics
STANDARD_DIMENSIONS = (
    "completeness",
    "consistency", 
    "clarity",
    "granularity",
    "relationship_coherence",
    "domain_alignment",
)


@dataclass
class DimensionStats:
    """Statistics for a single dimension across multiple scores."""
    dimension: str
    overall: float = 0.0
    overall_mean: float = 0.0
    overall_std: float = 0.0
    percentile_25: float = 0.0
    percentile_50: float = 0.0
    percentile_75: float = 0.0
    min_value: float = 0.0
    max_value: float = 0.0
    count: int = 0


class ScoreAnalyzer:
    """Provides statistical analysis methods for CriticScore objects.
    
    This class encapsulates all statistical computations that were previously
    mixed into OntologyCritic. It operates on CriticScore instances and
    batches of scores to produce metrics for analysis, comparison, and reporting.
    
    All methods are stateless and thread-safe. Analysis is performed on
    scores passed as arguments with no internal state modification.
    """
    
    DIMENSIONS = STANDARD_DIMENSIONS
    
    def __init__(self, dimensions: Optional[Tuple[str, ...]] = None):
        """Initialize analyzer with optional custom dimension set.
        
        Args:
            dimensions: Tuple of dimension names to consider. Defaults to 
                standard GraphRAG dimensions if not provided.
        """
        self.DIMENSIONS = dimensions or STANDARD_DIMENSIONS
        self._log = logging.getLogger(self.__class__.__name__)
    
    # =========================================================================
    # Single Score Analysis Methods
    # =========================================================================
    
    def weakest_dimension(self, score: Any) -> str:
        """Return name of the lowest-scoring dimension in score.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Name of dimension with smallest value.
            
        Example:
            >>> analyzer.weakest_dimension(score)
            'clarity'
        """
        return min(self.DIMENSIONS, key=lambda d: getattr(score, d, 0.0))
    
    def strongest_dimension(self, score: Any) -> str:
        """Return name of the highest-scoring dimension in score.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Name of dimension with largest value.
            
        Example:
            >>> analyzer.strongest_dimension(score)
            'completeness'
        """
        return max(self.DIMENSIONS, key=lambda d: getattr(score, d, 0.0))
    
    def dimension_range(self, score: Any) -> float:
        """Return max - min dimension value (spread of scores).
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float in [0.0, 1.0] representing dimension spread.
            
        Example:
            >>> analyzer.dimension_range(score)
            0.45  # max dim is 0.95, min dim is 0.50
        """
        vals = [getattr(score, d, 0.0) for d in self.DIMENSIONS]
        return max(vals) - min(vals) if vals else 0.0
    
    def score_balance_ratio(self, score: Any) -> float:
        """Return ratio of max:min dimensions (balance metric).
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float ≥ 1.0; 1.0 means all dimensions equal.
            
        Raises:
            ValueError: If any dimension is zero.
        """
        vals = [getattr(score, d, 0.0) for d in self.DIMENSIONS]
        min_val = min(vals) if vals else 1.0
        max_val = max(vals) if vals else 1.0
        if min_val <= 0.0:
            raise ValueError("Cannot compute balance ratio with zero dimensions")
        return max_val / min_val
    
    def dimensions_above_threshold(
        self, 
        score: Any, 
        threshold: float = 0.7
    ) -> int:
        """Count how many dimensions exceed threshold.
        
        Args:
            score: A CriticScore instance.
            threshold: Comparison threshold (default 0.7).
            
        Returns:
            Integer count of dimensions above threshold.
            
        Example:
            >>> analyzer.dimensions_above_threshold(score, 0.75)
            4  # 4 out of 6 dimensions above 0.75
        """
        return sum(
            1 for d in self.DIMENSIONS 
            if getattr(score, d, 0.0) > threshold
        )
    
    def dimension_delta(self, before: Any, after: Any) -> Dict[str, float]:
        """Return per-dimension deltas between two scores.
        
        Args:
            before: Earlier CriticScore.
            after: Later CriticScore.
            
        Returns:
            Dict mapping dimension name → (after_value - before_value).
            
        Example:
            >>> deltas = analyzer.dimension_delta(score1, score2)
            >>> deltas['clarity']
            0.15  # clarity improved by 0.15
        """
        return {
            d: getattr(after, d, 0.0) - getattr(before, d, 0.0)
            for d in self.DIMENSIONS
        }
    
    def score_dimension_entropy(self, score: Any) -> float:
        """Return normalized entropy of dimension values.
        
        Measures how uniform/concentrated the dimension distribution is.
        Higher entropy = more uniform distribution.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float in [0.0, 1.0]; 0 = all dimensions equal,
            1.0 = maximally varied (one dim highly different from others).
        """
        vals = [getattr(score, d, 0.0) for d in self.DIMENSIONS]
        total = sum(vals)
        if total == 0.0:
            return 0.0
        
        # Normalize to get proportions
        probs = [v / total for v in vals]
        # Compute standard deviation of proportions as a simple entropy proxy
        mean_p = sum(probs) / len(probs)
        variance = sum((p - mean_p) ** 2 for p in probs) / len(probs)
        return min(1.0, variance ** 0.5)  # Normalized to [0, 1]
    
    def score_dimension_variance(self, score: Any) -> float:
        """Return population variance of dimensions.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float variance (zero when all dimensions equal).
        """
        vals = [getattr(score, d, 0.0) for d in self.DIMENSIONS]
        n = len(vals)
        if n < 2:
            return 0.0
        mean = sum(vals) / n
        return sum((v - mean) ** 2 for v in vals) / n
    
    def score_dimension_std(self, score: Any) -> float:
        """Return population standard deviation of dimensions.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float std dev (zero when all dimensions equal).
        """
        variance = self.score_dimension_variance(score)
        return variance ** 0.5
    
    def score_dimension_mean_abs_deviation(self, score: Any) -> float:
        """Return Mean Absolute Deviation of dimensions.
        
        Computes average of |dim_value - mean| across all dimensions.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float ≥ 0.0; 0.0 when all dimensions equal.
        """
        vals = [getattr(score, d, 0.0) for d in self.DIMENSIONS]
        n = len(vals)
        if n < 1:
            return 0.0
        mean = sum(vals) / n
        return sum(abs(v - mean) for v in vals) / n
    
    def score_dimension_max_z(self, score: Any) -> float:
        """Return maximum absolute z-score of dimensions.
        
        Each dimension is z-scored relative to distribution of all 6 dims.
        Returns max(|z_i|) — dimension furthest from mean.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float z-score; 0.0 when all dimensions equal.
        """
        vals = [getattr(score, d, 0.0) for d in self.DIMENSIONS]
        n = len(vals)
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / n
        if variance == 0.0:
            return 0.0
        std = variance ** 0.5
        return max(abs((v - mean) / std) for v in vals)
    
    def score_dimension_min_z(self, score: Any) -> float:
        """Return minimum absolute z-score of dimensions.
        
        Each dimension is z-scored relative to distribution of all 6 dims.
        Returns min(|z_i|) — dimension closest to mean.
        
        Args:
            score: A CriticScore instance.
            
        Returns:
            Float z-score; 0.0 when all dimensions equal.
        """
        vals = [getattr(score, d, 0.0) for d in self.DIMENSIONS]
        n = len(vals)
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / n
        if variance == 0.0:
            return 0.0
        std = variance ** 0.5
        return min(abs((v - mean) / std) for v in vals)
    
    # =========================================================================
    # Batch Analysis Methods
    # =========================================================================
    
    def mean_overall(self, scores: List[Any]) -> float:
        """Compute mean overall score across batch.
        
        Args:
            scores: List of CriticScore objects.
            
        Returns:
            Float mean in [0.0, 1.0]; 0.0 if batch empty.
        """
        if not scores:
            return 0.0
        overalls = [s.overall for s in scores]
        return sum(overalls) / len(overalls)
    
    def dimension_mean(self, scores: List[Any], dimension: str) -> float:
        """Compute mean score for a specific dimension.
        
        Args:
            scores: List of CriticScore objects.
            dimension: Name of dimension to analyze.
            
        Returns:
            Float mean dimension value.
        """
        if not scores:
            return 0.0
        vals = [getattr(s, dimension, 0.0) for s in scores]
        return sum(vals) / len(vals)
    
    def percentile_overall(
        self, 
        scores: List[Any], 
        percentile: float = 75.0
    ) -> float:
        """Compute percentile of overall scores.
        
        Args:
            scores: List of CriticScore objects.
            percentile: Percentile to compute (0-100).
            
        Returns:
            Float overall score at percentile.
            
        Raises:
            ValueError: If scores empty or percentile out of range.
        """
        if not scores:
            raise ValueError("Cannot compute percentile of empty list")
        if not (0 <= percentile <= 100):
            raise ValueError(f"Percentile must be in [0, 100]; got {percentile}")
        
        sorted_overalls = sorted(s.overall for s in scores)
        idx = (percentile / 100) * (len(sorted_overalls) - 1)
        lo, hi = int(idx), min(int(idx) + 1, len(sorted_overalls) - 1)
        frac = idx - lo
        
        if lo == hi:
            return sorted_overalls[lo]
        return sorted_overalls[lo] * (1 - frac) + sorted_overalls[hi] * frac
    
    def min_max_overall(self, scores: List[Any]) -> Tuple[float, float]:
        """Compute min and max overall scores.
        
        Args:
            scores: List of CriticScore objects.
            
        Returns:
            Tuple (min_overall, max_overall).
        """
        if not scores:
            return 0.0, 0.0
        overalls = [s.overall for s in scores]
        return min(overalls), max(overalls)
    
    def batch_dimension_stats(
        self, 
        scores: List[Any]
    ) -> Dict[str, DimensionStats]:
        """Compute statistics for each dimension across batch.
        
        Args:
            scores: List of CriticScore objects.
            
        Returns:
            Dict mapping dimension name → DimensionStats.
        """
        if not scores:
            return {}
        
        stats = {}
        for dim in self.DIMENSIONS:
            values = [getattr(s, dim, 0.0) for s in scores]
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            
            idx_25 = int(0.25 * (n - 1))
            idx_50 = int(0.50 * (n - 1))
            idx_75 = int(0.75 * (n - 1))
            
            stats[dim] = DimensionStats(
                dimension=dim,
                overall=sum(values) / n if n > 0 else 0.0,
                percentile_25=sorted_vals[idx_25] if idx_25 < n else 0.0,
                percentile_50=sorted_vals[idx_50] if idx_50 < n else 0.0,
                percentile_75=sorted_vals[idx_75] if idx_75 < n else 0.0,
                min_value=min(values) if values else 0.0,
                max_value=max(values) if values else 0.0,
                count=n,
            )
        
        return stats
    
    def batch_divergence(self, scores: List[Any]) -> float:
        """Compute average distance of scores from batch mean.
        
        Useful for assessing consistency of ontology quality.
        
        Args:
            scores: List of CriticScore objects.
            
        Returns:
            Float in [0.0, 1.0] (0 = all identical, 1 = max spread).
        """
        if len(scores) < 2:
            return 0.0
        
        mean_overall = self.mean_overall(scores)
        distances = sum(abs(s.overall - mean_overall) for s in scores)
        return distances / (len(scores) * 1.0)  # Normalize
    
    # =========================================================================
    # Comparative Analysis Methods
    # =========================================================================
    
    def score_improvement_percent(
        self, 
        before: Any, 
        after: Any
    ) -> float:
        """Compute percent improvement in overall score.
        
        Args:
            before: Earlier CriticScore.
            after: Later CriticScore.
            
        Returns:
            Float percent change (-100 to +100);
            Positive = improvement.
        """
        if before.overall == 0:
            return 0.0
        return ((after.overall - before.overall) / before.overall) * 100
    
    def dimension_improvement_count(
        self, 
        before: Any, 
        after: Any,
        min_improvement: float = 0.01
    ) -> int:
        """Count dimensions that improved more than threshold.
        
        Args:
            before: Earlier CriticScore.
            after: Later CriticScore.
            min_improvement: Minimum delta to count as improvement.
            
        Returns:
            Integer count of improved dimensions.
        """
        deltas = self.dimension_delta(before, after)
        return sum(1 for d in self.DIMENSIONS if deltas[d] >= min_improvement)
    
    def recommend_focus_dimensions(
        self,
        scores: List[Any],
        count: int = 2
    ) -> List[Tuple[str, float]]:
        """Recommend which dimensions to focus on for improvement.
        
        Returns dimensions with lowest average score.
        
        Args:
            scores: Batch of CriticScore objects.
            count: How many dimensions to recommend.
            
        Returns:
            List of (dimension, avg_score) tuples sorted ascending.
        """
        dim_stats = self.batch_dimension_stats(scores)
        ranked = sorted(
            [(d, stats.overall) for d, stats in dim_stats.items()],
            key=lambda x: x[1]
        )
        return ranked[:count]

"""Ontology comparison and ranking functionality."""

from __future__ import annotations

import logging
import statistics
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

STANDARD_DIMENSIONS = (
    "completeness",
    "consistency",
    "clarity",
    "granularity",
    "relationship_coherence",
    "domain_alignment",
)


class OntologyComparator:
    """Compare ontologies and their evaluation scores."""
    
    def __init__(self, dimensions: Optional[Tuple[str, ...]] = None):
        """Initialize comparator with optional custom dimension set."""
        self.DIMENSIONS = dimensions or STANDARD_DIMENSIONS
        self._log = logging.getLogger(self.__class__.__name__)
    
    # Ranking Methods
    def rank_batch(self, ontologies: List[Dict[str, Any]], scores: List[Any]) -> List[Dict[str, Any]]:
        """Rank ontologies by overall score (highest first)."""
        if not ontologies:
            return []
        
        indexed = [(i, ont, score) for i, (ont, score) in enumerate(zip(ontologies, scores))]
        sorted_indexed = sorted(indexed, key=lambda x: getattr(x[2], 'overall', 0), reverse=True)
        
        result = []
        for rank, (idx, ont, score) in enumerate(sorted_indexed, start=1):
            result.append({
                'index': idx,
                'rank': rank,
                'overall': getattr(score, 'overall', 0),
                'score': score,
                **ont
            })
        return result
    
    def rank_by_dimension(self, ontologies: List[Dict[str, Any]], scores: List[Any], dimension: str) -> List[Dict[str, Any]]:
        """Rank ontologies by specific dimension."""
        indexed = [(i, ont, score) for i, (ont, score) in enumerate(zip(ontologies, scores))]
        sorted_indexed = sorted(indexed, key=lambda x: getattr(x[2], dimension, 0), reverse=True)
        
        result = []
        for rank, (idx, ont, score) in enumerate(sorted_indexed, start=1):
            result.append({
                'index': idx,
                'rank': rank,
                dimension: getattr(score, dimension, 0),
                **ont
            })
        return result
    
    def get_top_n(self, ontologies: List[Dict[str, Any]], scores: List[Any], n: int) -> List[Dict[str, Any]]:
        """Get top N ontologies by overall score."""
        ranked = self.rank_batch(ontologies, scores)
        return ranked[:n]
    
    # Comparison Methods
    def compare_pair(self, ont1: Dict[str, Any], score1: Any, ont2: Dict[str, Any], score2: Any) -> Dict[str, Any]:
        """Compare two ontologies."""
        overall1 = getattr(score1, 'overall', 0)
        overall2 = getattr(score2, 'overall', 0)
        delta = overall1 - overall2
        
        better = 1 if overall1 > overall2 else (2 if overall2 > overall1 else 0)
        
        dimension_deltas = {}
        for dim in self.DIMENSIONS:
            val1 = getattr(score1, dim, 0)
            val2 = getattr(score2, dim, 0)
            dimension_deltas[dim] = val1 - val2
        
        return {
            'better': better,
            'overall_delta': abs(delta),
            'dimension_deltas': dimension_deltas,
        }
    
    def compare_to_baseline(self, ont: Dict[str, Any], score: Any, baseline: Dict[str, Any], baseline_score: Any) -> Dict[str, Any]:
        """Compare to baseline."""
        target_overall = getattr(score, 'overall', 0)
        baseline_overall = getattr(baseline_score, 'overall', 0)
        
        if baseline_overall == 0:
            improvement_pct = 0
        else:
            improvement_pct = ((target_overall - baseline_overall) / baseline_overall * 100)
        
        return {
            'improvement_percent': improvement_pct,
            'target_overall': target_overall,
            'baseline_overall': baseline_overall,
        }
    
    def filter_by_threshold(self, ontologies: List[Dict[str, Any]], scores: List[Any], threshold: float) -> List[Dict[str, Any]]:
        """Filter ontologies by score threshold."""
        result = []
        for ont, score in zip(ontologies, scores):
            if getattr(score, 'overall', 0) >= threshold:
                result.append({
                    'overall': getattr(score, 'overall', 0),
                    **ont
                })
        return result
    
    # Trend Detection
    def detect_trend(self, scores: List[Any], threshold: float = 0.05) -> str:
        """Detect trend in scores (improving, stable, or degrading)."""
        if len(scores) < 2:
            return "stable"
        
        overalls = [getattr(s, 'overall', 0) for s in scores]
        if len(set(overalls)) == 1:
            return "stable"
        
        # Simple trend: compare first and last
        trend_val = overalls[-1] - overalls[0]
        if trend_val > threshold * len(overalls):
            return "improving"
        elif trend_val < -threshold * len(overalls):
            return "degrading"
        else:
            return "stable"
    
    # Threshold Calibration
    def calibrate_thresholds(self, scores: List[Any], percentile: float = 75.0) -> Dict[str, float]:
        """Calibrate thresholds based on percentile."""
        if not scores:
            return {dim: 0.5 for dim in self.DIMENSIONS}
        
        thresholds = {}
        for dim in self.DIMENSIONS:
            values = [getattr(s, dim, 0) for s in scores]
            if values:
                # Calculate percentile
                sorted_vals = sorted(values)
                idx = int((percentile / 100.0) * (len(sorted_vals) - 1))
                thresholds[dim] = sorted_vals[idx]
            else:
                thresholds[dim] = 0.5
        
        return thresholds
    
    # Statistical Summaries
    def histogram_by_dimension(self, scores: List[Any], bins: int = 5) -> Dict[str, List[int]]:
        """Generate histograms by dimension."""
        if not scores:
            return {dim: [0] * bins for dim in self.DIMENSIONS}
        
        histograms = {}
        for dim in self.DIMENSIONS:
            values = [getattr(s, dim, 0) for s in scores]
            if values:
                bin_size = 1.0 / bins
                hist = [0] * bins
                for v in values:
                    bin_idx = min(int(v / bin_size), bins - 1)
                    hist[bin_idx] += 1
                histograms[dim] = hist
            else:
                histograms[dim] = [0] * bins
        
        return histograms
    
    def summary_statistics(self, scores: List[Any]) -> Dict[str, Dict[str, float]]:
        """Generate summary statistics."""
        summary = {}
        for dim in self.DIMENSIONS:
            values = [getattr(s, dim, 0) for s in scores]
            if values:
                summary[dim] = {
                    'mean': statistics.mean(values),
                    'min': min(values),
                    'max': max(values),
                    'stdev': statistics.stdev(values) if len(values) > 1 else 0,
                }
            else:
                summary[dim] = {'mean': 0, 'min': 0, 'max': 0, 'stdev': 0}
        
        return summary
    
    # Custom Scoring
    def reweight_score(self, score: Any, weights: Dict[str, float]) -> float:
        """Reweight score with custom weights."""
        weighted_sum = 0
        total_weight = 0
        for dim, weight in weights.items():
            if weight > 0:
                val = getattr(score, dim, 0)
                weighted_sum += val * weight
                total_weight += weight
        
        return weighted_sum / total_weight if total_weight > 0 else 0.5
    
    def evaluate_against_rubric(self, score: Any, rubric: Dict[str, float]) -> float:
        """Evaluate against custom rubric."""
        matches = 0
        total = 0
        for dim, target in rubric.items():
            val = getattr(score, dim, 0)
            match = 1 - abs(val - target)
            matches += match
            total += 1
        
        return matches / total if total > 0 else 0.5

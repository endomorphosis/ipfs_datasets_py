"""Batch 253: OntologyComparator Comprehensive Test Suite.

Comprehensive testing of the OntologyComparator for ranking, comparing, and
analyzing ontologies based on evaluation scores with trend detection and
threshold calibration.

Test Categories:
- Ranking ontologies by overall score and individual dimensions
- Pairwise and baseline comparison
- Filtering by score thresholds
- Trend detection in score sequences
- Threshold calibration via percentiles
- Statistical analysis and summaries
- Custom scoring and rubric evaluation
"""

import pytest
import statistics
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.graphrag.ontology_comparator import (
    OntologyComparator,
)


# Mock class for CriticScore
class MockCriticScore:
    """Mock CriticScore for testing."""
    
    def __init__(
        self,
        completeness: float = 0.8,
        consistency: float = 0.8,
        clarity: float = 0.8,
        granularity: float = 0.8,
        relationship_coherence: float = 0.8,
        domain_alignment: float = 0.8,
    ):
        self.completeness = completeness
        self.consistency = consistency
        self.clarity = clarity
        self.granularity = granularity
        self.relationship_coherence = relationship_coherence
        self.domain_alignment = domain_alignment
        # Overall is typically computed as average or max
        self.overall = (
            completeness + consistency + clarity + granularity + 
            relationship_coherence + domain_alignment
        ) / 6


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def comparator():
    """Create a fresh OntologyComparator."""
    return OntologyComparator()


@pytest.fixture
def sample_ontologies():
    """Create sample ontology dictionaries."""
    return [
        {"id": 1, "name": "ontology_1", "entity_count": 10},
        {"id": 2, "name": "ontology_2", "entity_count": 15},
        {"id": 3, "name": "ontology_3", "entity_count": 12},
        {"id": 4, "name": "ontology_4", "entity_count": 20},
        {"id": 5, "name": "ontology_5", "entity_count": 8},
    ]


@pytest.fixture
def sample_scores():
    """Create sample CriticScore objects."""
    return [
        MockCriticScore(0.85, 0.80, 0.82, 0.78, 0.81, 0.84),  # overall: 0.82
        MockCriticScore(0.70, 0.72, 0.68, 0.75, 0.71, 0.73),  # overall: 0.715
        MockCriticScore(0.90, 0.88, 0.92, 0.85, 0.89, 0.91),  # overall: 0.892
        MockCriticScore(0.60, 0.62, 0.58, 0.65, 0.61, 0.63),  # overall: 0.618
        MockCriticScore(0.95, 0.92, 0.94, 0.93, 0.95, 0.96),  # overall: 0.942
    ]


@pytest.fixture
def improving_scores():
    """Create scores showing improvement trend."""
    return [
        MockCriticScore(0.50, 0.50, 0.50, 0.50, 0.50, 0.50),  # overall: 0.50
        MockCriticScore(0.60, 0.60, 0.60, 0.60, 0.60, 0.60),  # overall: 0.60
        MockCriticScore(0.70, 0.70, 0.70, 0.70, 0.70, 0.70),  # overall: 0.70
        MockCriticScore(0.80, 0.80, 0.80, 0.80, 0.80, 0.80),  # overall: 0.80
        MockCriticScore(0.90, 0.90, 0.90, 0.90, 0.90, 0.90),  # overall: 0.90
    ]


@pytest.fixture
def degrading_scores():
    """Create scores showing degradation trend."""
    return [
        MockCriticScore(0.90, 0.90, 0.90, 0.90, 0.90, 0.90),  # overall: 0.90
        MockCriticScore(0.80, 0.80, 0.80, 0.80, 0.80, 0.80),  # overall: 0.80
        MockCriticScore(0.70, 0.70, 0.70, 0.70, 0.70, 0.70),  # overall: 0.70
        MockCriticScore(0.60, 0.60, 0.60, 0.60, 0.60, 0.60),  # overall: 0.60
        MockCriticScore(0.50, 0.50, 0.50, 0.50, 0.50, 0.50),  # overall: 0.50
    ]


@pytest.fixture
def stable_scores():
    """Create scores showing stable trend."""
    return [
        MockCriticScore(0.75, 0.75, 0.75, 0.75, 0.75, 0.75),  # overall: 0.75
        MockCriticScore(0.76, 0.74, 0.75, 0.75, 0.75, 0.75),  # overall: 0.75
        MockCriticScore(0.75, 0.75, 0.75, 0.75, 0.76, 0.74),  # overall: 0.75
        MockCriticScore(0.74, 0.76, 0.75, 0.75, 0.75, 0.75),  # overall: 0.75
    ]


# ============================================================================
# Initialization Tests
# ============================================================================

class TestInitialization:
    """Test OntologyComparator initialization."""
    
    def test_init_with_defaults(self, comparator):
        """Comparator initializes with default dimensions."""
        assert comparator.DIMENSIONS is not None
        assert len(comparator.DIMENSIONS) > 0
    
    def test_init_with_custom_dimensions(self):
        """Comparator initializes with custom dimensions."""
        custom_dims = ("dim1", "dim2", "dim3")
        custom_comparator = OntologyComparator(dimensions=custom_dims)
        
        assert custom_comparator.DIMENSIONS == custom_dims


# ============================================================================
# Ranking Tests
# ============================================================================

class TestRankBatch:
    """Test rank_batch() method."""
    
    def test_rank_batch_returns_list(self, comparator, sample_ontologies, sample_scores):
        """rank_batch returns list."""
        result = comparator.rank_batch(sample_ontologies, sample_scores)
        
        assert isinstance(result, list)
        assert len(result) == len(sample_ontologies)
    
    def test_rank_batch_highest_first(self, comparator, sample_ontologies, sample_scores):
        """rank_batch orders by highest overall score first."""
        result = comparator.rank_batch(sample_ontologies, sample_scores)
        
        # Check that overall scores are in descending order
        overalls = [r["overall"] for r in result]
        assert overalls == sorted(overalls, reverse=True)
    
    def test_rank_batch_preserves_rank_field(self, comparator, sample_ontologies, sample_scores):
        """rank_batch includes rank field starting from 1."""
        result = comparator.rank_batch(sample_ontologies, sample_scores)
        
        ranks = [r["rank"] for r in result]
        assert ranks == list(range(1, len(result) + 1))
    
    def test_rank_batch_empty(self, comparator):
        """rank_batch handles empty list."""
        result = comparator.rank_batch([], [])
        
        assert result == []
    
    def test_rank_batch_single_item(self, comparator, sample_scores):
        """rank_batch handles single item."""
        ontologies = [{"id": 1, "name": "test"}]
        scores = [sample_scores[0]]
        
        result = comparator.rank_batch(ontologies, scores)
        
        assert len(result) == 1
        assert result[0]["rank"] == 1


class TestRankByDimension:
    """Test rank_by_dimension() method."""
    
    def test_rank_by_dimension_returns_list(self, comparator, sample_ontologies, sample_scores):
        """rank_by_dimension returns list."""
        result = comparator.rank_by_dimension(sample_ontologies, sample_scores, "completeness")
        
        assert isinstance(result, list)
        assert len(result) == len(sample_ontologies)
    
    def test_rank_by_dimension_completeness(self, comparator, sample_ontologies, sample_scores):
        """rank_by_dimension ranks by completeness correctly."""
        result = comparator.rank_by_dimension(
            sample_ontologies, 
            sample_scores, 
            "completeness"
        )
        
        completeness_values = [r["completeness"] for r in result]
        assert completeness_values == sorted(completeness_values, reverse=True)
    
    def test_rank_by_dimension_consistency(self, comparator, sample_ontologies, sample_scores):
        """rank_by_dimension ranks by consistency correctly."""
        result = comparator.rank_by_dimension(
            sample_ontologies, 
            sample_scores, 
            "consistency"
        )
        
        consistency_values = [r["consistency"] for r in result]
        assert consistency_values == sorted(consistency_values, reverse=True)


class TestGetTopN:
    """Test get_top_n() method."""
    
    def test_get_top_n_returns_list(self, comparator, sample_ontologies, sample_scores):
        """get_top_n returns list."""
        result = comparator.get_top_n(sample_ontologies, sample_scores, 3)
        
        assert isinstance(result, list)
    
    def test_get_top_n_respects_limit(self, comparator, sample_ontologies, sample_scores):
        """get_top_n respects requested count."""
        top_3 = comparator.get_top_n(sample_ontologies, sample_scores, 3)
        top_2 = comparator.get_top_n(sample_ontologies, sample_scores, 2)
        
        assert len(top_3) == 3
        assert len(top_2) == 2
    
    def test_get_top_n_highest_scores(self, comparator, sample_ontologies, sample_scores):
        """get_top_n returns highest scoring ontologies."""
        result = comparator.get_top_n(sample_ontologies, sample_scores, 2)
        
        # Should be the two with highest overall scores
        assert result[0]["overall"] >= result[1]["overall"]


# ============================================================================
# Comparison Tests
# ============================================================================

class TestComparePair:
    """Test compare_pair() method."""
    
    def test_compare_pair_returns_dict(self, comparator, sample_ontologies, sample_scores):
        """compare_pair returns dictionary."""
        result = comparator.compare_pair(
            sample_ontologies[0], 
            sample_scores[0],
            sample_ontologies[1], 
            sample_scores[1]
        )
        
        assert isinstance(result, dict)
    
    def test_compare_pair_identifies_better(self, comparator):
        """compare_pair correctly identifies which is better."""
        ont1 = {"id": 1}
        score1 = MockCriticScore(0.9, 0.9, 0.9, 0.9, 0.9, 0.9)  # overall: 0.9
        
        ont2 = {"id": 2}
        score2 = MockCriticScore(0.7, 0.7, 0.7, 0.7, 0.7, 0.7)  # overall: 0.7
        
        result = comparator.compare_pair(ont1, score1, ont2, score2)
        
        # ont1 is better
        assert result["better"] == 1
    
    def test_compare_pair_delta(self, comparator):
        """compare_pair calculates delta correctly."""
        ont1 = {"id": 1}
        score1 = MockCriticScore(0.8, 0.8, 0.8, 0.8, 0.8, 0.8)  # overall: 0.8
        
        ont2 = {"id": 2}
        score2 = MockCriticScore(0.6, 0.6, 0.6, 0.6, 0.6, 0.6)  # overall: 0.6
        
        result = comparator.compare_pair(ont1, score1, ont2, score2)
        
        assert result["overall_delta"] == pytest.approx(0.2, abs=0.01)
    
    def test_compare_pair_dimension_deltas(self, comparator):
        """compare_pair includes dimension deltas."""
        ont1 = {"id": 1}
        score1 = MockCriticScore(0.9, 0.8, 0.7, 0.8, 0.9, 0.8)
        
        ont2 = {"id": 2}
        score2 = MockCriticScore(0.7, 0.9, 0.8, 0.7, 0.7, 0.9)
        
        result = comparator.compare_pair(ont1, score1, ont2, score2)
        
        assert "dimension_deltas" in result
        assert isinstance(result["dimension_deltas"], dict)


class TestCompareToBaseline:
    """Test compare_to_baseline() method."""
    
    def test_compare_to_baseline_returns_dict(self, comparator):
        """compare_to_baseline returns dictionary."""
        ont = {"id": 1}
        score = MockCriticScore(0.8, 0.8, 0.8, 0.8, 0.8, 0.8)
        
        baseline = {"id": 0}
        baseline_score = MockCriticScore(0.7, 0.7, 0.7, 0.7, 0.7, 0.7)
        
        result = comparator.compare_to_baseline(ont, score, baseline, baseline_score)
        
        assert isinstance(result, dict)
    
    def test_compare_to_baseline_improvement_percent(self, comparator):
        """compare_to_baseline calculates improvement percentage."""
        ont = {"id": 1}
        score = MockCriticScore(0.8, 0.8, 0.8, 0.8, 0.8, 0.8)  # overall: 0.8
        
        baseline = {"id": 0}
        baseline_score = MockCriticScore(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)  # overall: 0.5
        
        result = comparator.compare_to_baseline(ont, score, baseline, baseline_score)
        
        # (0.8 - 0.5) / 0.5 * 100 = 60%
        assert result["improvement_percent"] == pytest.approx(60.0, abs=0.1)
    
    def test_compare_to_baseline_zero_baseline(self, comparator):
        """compare_to_baseline handles zero baseline."""
        ont = {"id": 1}
        score = MockCriticScore(0.8, 0.8, 0.8, 0.8, 0.8, 0.8)
        
        baseline = {"id": 0}
        baseline_score = MockCriticScore(0, 0, 0, 0, 0, 0)  # overall: 0
        
        result = comparator.compare_to_baseline(ont, score, baseline, baseline_score)
        
        # Should handle division by zero
        assert result["improvement_percent"] == 0.0


# ============================================================================
# Filtering Tests
# ============================================================================

class TestFilterByThreshold:
    """Test filter_by_threshold() method."""
    
    def test_filter_by_threshold_returns_list(self, comparator, sample_ontologies, sample_scores):
        """filter_by_threshold returns list."""
        result = comparator.filter_by_threshold(sample_ontologies, sample_scores, 0.7)
        
        assert isinstance(result, list)
    
    def test_filter_by_threshold_only_above_threshold(self, comparator, sample_ontologies, sample_scores):
        """filter_by_threshold only returns items above threshold."""
        threshold = 0.8
        result = comparator.filter_by_threshold(sample_ontologies, sample_scores, threshold)
        
        # All results should have overall >= threshold
        for item in result:
            assert item["overall"] >= threshold - 0.001  # Small tolerance for float comparison


# ============================================================================
# Trend Detection Tests
# ============================================================================

class TestDetectTrend:
    """Test detect_trend() method."""
    
    def test_detect_trend_improving(self, comparator, improving_scores):
        """detect_trend identifies improving trend."""
        trend = comparator.detect_trend(improving_scores)
        
        assert trend == "improving"
    
    def test_detect_trend_degrading(self, comparator, degrading_scores):
        """detect_trend identifies degrading trend."""
        trend = comparator.detect_trend(degrading_scores)
        
        assert trend == "degrading"
    
    def test_detect_trend_stable(self, comparator, stable_scores):
        """detect_trend identifies stable trend."""
        trend = comparator.detect_trend(stable_scores)
        
        assert trend == "stable"
    
    def test_detect_trend_single_score(self, comparator, sample_scores):
        """detect_trend handles single score."""
        trend = comparator.detect_trend(sample_scores[:1])
        
        assert trend == "stable"
    
    def test_detect_trend_empty(self, comparator):
        """detect_trend handles empty scores."""
        trend = comparator.detect_trend([])
        
        assert trend == "stable"


# ============================================================================
# Threshold Calibration Tests
# ============================================================================

class TestCalibrateThresholds:
    """Test calibrate_thresholds() method."""
    
    def test_calibrate_thresholds_returns_dict(self, comparator, sample_scores):
        """calibrate_thresholds returns dictionary."""
        result = comparator.calibrate_thresholds(sample_scores)
        
        assert isinstance(result, dict)
    
    def test_calibrate_thresholds_has_dimensions(self, comparator, sample_scores):
        """calibrate_thresholds includes all dimensions."""
        result = comparator.calibrate_thresholds(sample_scores)
        
        assert "completeness" in result
        assert "consistency" in result
    
    def test_calibrate_thresholds_values_in_range(self, comparator, sample_scores):
        """calibrate_thresholds returns values in [0, 1] range."""
        result = comparator.calibrate_thresholds(sample_scores)
        
        for dim, threshold in result.items():
            assert 0.0 <= threshold <= 1.0
    
    def test_calibrate_thresholds_percentile_75(self, comparator, sample_scores):
        """calibrate_thresholds uses 75th percentile by default."""
        result = comparator.calibrate_thresholds(sample_scores, percentile=75.0)
        
        # For completeness: [0.85, 0.70, 0.90, 0.60, 0.95]
        # Sorted: [0.60, 0.70, 0.85, 0.90, 0.95]
        # 75th percentile: 0.90
        assert result["completeness"] == pytest.approx(0.90, abs=0.01)


# ============================================================================
# Statistical Analysis Tests
# ============================================================================

class TestHistogramByDimension:
    """Test histogram_by_dimension() method."""
    
    def test_histogram_by_dimension_returns_dict(self, comparator, sample_scores):
        """histogram_by_dimension returns dictionary."""
        result = comparator.histogram_by_dimension(sample_scores)
        
        assert isinstance(result, dict)
    
    def test_histogram_by_dimension_bin_count(self, comparator, sample_scores):
        """histogram_by_dimension returns correct bin count."""
        result = comparator.histogram_by_dimension(sample_scores, bins=5)
        
        for dim_hist in result.values():
            assert len(dim_hist) == 5
    
    def test_histogram_by_dimension_sum(self, comparator, sample_scores):
        """histogram_by_dimension sums to total count."""
        result = comparator.histogram_by_dimension(sample_scores, bins=5)
        
        for dim_hist in result.values():
            assert sum(dim_hist) == len(sample_scores)


class TestSummaryStatistics:
    """Test summary_statistics() method."""
    
    def test_summary_statistics_returns_dict(self, comparator, sample_scores):
        """summary_statistics returns dictionary."""
        result = comparator.summary_statistics(sample_scores)
        
        assert isinstance(result, dict)
    
    def test_summary_statistics_has_dimensions(self, comparator, sample_scores):
        """summary_statistics includes all dimensions."""
        result = comparator.summary_statistics(sample_scores)
        
        assert "completeness" in result
        assert "consistency" in result
    
    def test_summary_statistics_has_fields(self, comparator, sample_scores):
        """summary_statistics includes mean, min, max, stdev."""
        result = comparator.summary_statistics(sample_scores)
        
        for dim, stats in result.items():
            assert "mean" in stats
            assert "min" in stats
            assert "max" in stats
            assert "stdev" in stats
    
    def test_summary_statistics_correct_mean(self, comparator, sample_scores):
        """summary_statistics calculates mean correctly."""
        result = comparator.summary_statistics(sample_scores)
        
        # Check completeness mean
        expected_mean = statistics.mean([s.completeness for s in sample_scores])
        assert result["completeness"]["mean"] == pytest.approx(expected_mean, abs=0.01)


# ============================================================================
# Custom Scoring Tests
# ============================================================================

class TestReweightScore:
    """Test reweight_score() method."""
    
    def test_reweight_score_returns_float(self, comparator):
        """reweight_score returns float."""
        score = MockCriticScore(0.8, 0.7, 0.9, 0.8, 0.75, 0.85)
        weights = {"completeness": 2.0, "consistency": 1.0}
        
        result = comparator.reweight_score(score, weights)
        
        assert isinstance(result, float)
    
    def test_reweight_score_weighted_calculation(self, comparator):
        """reweight_score correctly weights dimensions."""
        score = MockCriticScore(0.8, 0.6, 0.8, 0.8, 0.8, 0.8)
        weights = {"completeness": 2.0, "consistency": 1.0}
        
        result = comparator.reweight_score(score, weights)
        
        # (0.8 * 2 + 0.6 * 1) / (2 + 1) = 1.6 / 3 = 0.533...
        expected = (0.8 * 2 + 0.6 * 1) / 3
        assert result == pytest.approx(expected, abs=0.01)
    
    def test_reweight_score_empty_weights(self, comparator):
        """reweight_score handles empty weights."""
        score = MockCriticScore()
        result = comparator.reweight_score(score, {})
        
        assert result == 0.5


class TestEvaluateAgainstRubric:
    """Test evaluate_against_rubric() method."""
    
    def test_evaluate_against_rubric_returns_float(self, comparator):
        """evaluate_against_rubric returns float."""
        score = MockCriticScore(0.8, 0.7, 0.9, 0.8, 0.75, 0.85)
        rubric = {"completeness": 0.85, "consistency": 0.75}
        
        result = comparator.evaluate_against_rubric(score, rubric)
        
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
    
    def test_evaluate_against_rubric_perfect_match(self, comparator):
        """evaluate_against_rubric gives 1.0 for perfect match."""
        score = MockCriticScore(0.8, 0.8, 0.8, 0.8, 0.8, 0.8)
        rubric = {"completeness": 0.8, "consistency": 0.8}
        
        result = comparator.evaluate_against_rubric(score, rubric)
        
        assert result == pytest.approx(1.0, abs=0.01)
    
    def test_evaluate_against_rubric_no_match(self, comparator):
        """evaluate_against_rubric handles poor match."""
        score = MockCriticScore(0.1, 0.1, 0.1, 0.1, 0.1, 0.1)
        rubric = {"completeness": 0.9, "consistency": 0.9}
        
        result = comparator.evaluate_against_rubric(score, rubric)
        
        # Should be closer to 0 than 1
        assert result < 0.5


# ============================================================================
# Integration Tests
# ============================================================================

class TestComparisonWorkflows:
    """Integration tests for comparison workflows."""
    
    def test_full_ranking_workflow(self, comparator, sample_ontologies, sample_scores):
        """Complete workflow: rank, filter, get top."""
        # 1. Rank all
        ranked = comparator.rank_batch(sample_ontologies, sample_scores)
        assert len(ranked) == len(sample_ontologies)
        
        # 2. Filter by threshold
        filtered = comparator.filter_by_threshold(sample_ontologies, sample_scores, 0.7)
        
        # 3. Get top 2
        top = comparator.get_top_n(sample_ontologies, sample_scores, 2)
        assert len(top) == 2
    
    def test_trend_analysis_workflow(self, comparator):
        """Complete workflow: detect trends in multiple sequences."""
        trends = {
            "improving": comparator.detect_trend(
                [MockCriticScore(i/10, i/10, i/10, i/10, i/10, i/10) 
                 for i in range(5, 10)]
            ),
            "degrading": comparator.detect_trend(
                [MockCriticScore((10-i)/10, (10-i)/10, (10-i)/10, (10-i)/10, (10-i)/10, (10-i)/10) 
                 for i in range(5, 10)]
            ),
        }
        
        assert trends["improving"] == "improving"
        assert trends["degrading"] == "degrading"
    
    def test_statistical_analysis_workflow(self, comparator, sample_scores):
        """Complete workflow: generate statistics and calibrate."""
        # 1. Generate summary statistics
        summary = comparator.summary_statistics(sample_scores)
        assert "completeness" in summary
        
        # 2. Calibrate thresholds
        thresholds = comparator.calibrate_thresholds(sample_scores, percentile=75.0)
        assert isinstance(thresholds, dict)
        
        # 3. Generate histograms
        histograms = comparator.histogram_by_dimension(sample_scores, bins=5)
        assert isinstance(histograms, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

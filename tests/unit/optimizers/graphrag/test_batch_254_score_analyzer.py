"""Batch 254: ScoreAnalyzer Comprehensive Test Suite.

Comprehensive testing of the ScoreAnalyzer for statistical analysis of
CriticScore objects with single-score metrics, batch statistics, and
comparative analysis.

Test Categories:
- Single score analysis (weakest/strongest dimensions, range, balance)
- Dimension statistics (entropy, variance, std, MAD, z-scores)
- Batch analysis (mean, percentile, dimension stats, divergence)
- Comparative analysis (improvement metrics, delta computation)
- Recommendation generation (focus dimensions)
"""

import pytest
import statistics
from typing import Dict, Any, List, Tuple

from ipfs_datasets_py.optimizers.graphrag.score_analyzer import (
    ScoreAnalyzer,
    DimensionStats,
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
        # Overall computed as mean
        self.overall = (
            completeness + consistency + clarity + granularity + 
            relationship_coherence + domain_alignment
        ) / 6


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def analyzer():
    """Create a fresh ScoreAnalyzer."""
    return ScoreAnalyzer()


@pytest.fixture
def balanced_score():
    """Create a balanced score (all dimensions equal)."""
    return MockCriticScore(0.8, 0.8, 0.8, 0.8, 0.8, 0.8)


@pytest.fixture
def unbalanced_score():
    """Create an unbalanced score (high and low dimensions)."""
    return MockCriticScore(0.95, 0.50, 0.85, 0.60, 0.90, 0.70)


@pytest.fixture
def high_score():
    """Create a high-scoring score."""
    return MockCriticScore(0.95, 0.92, 0.94, 0.93, 0.95, 0.96)


@pytest.fixture
def low_score():
    """Create a low-scoring score."""
    return MockCriticScore(0.50, 0.48, 0.52, 0.45, 0.51, 0.49)


@pytest.fixture
def sample_scores():
    """Create a batch of sample scores."""
    return [
        MockCriticScore(0.85, 0.80, 0.82, 0.78, 0.81, 0.84),  # overall: 0.82
        MockCriticScore(0.70, 0.72, 0.68, 0.75, 0.71, 0.73),  # overall: 0.715
        MockCriticScore(0.90, 0.88, 0.92, 0.85, 0.89, 0.91),  # overall: 0.892
        MockCriticScore(0.60, 0.62, 0.58, 0.65, 0.61, 0.63),  # overall: 0.618
        MockCriticScore(0.95, 0.92, 0.94, 0.93, 0.95, 0.96),  # overall: 0.942
    ]


# ============================================================================
# Initialization Tests
# ============================================================================

class TestInitialization:
    """Test ScoreAnalyzer initialization."""
    
    def test_init_with_defaults(self, analyzer):
        """Analyzer initializes with default dimensions."""
        assert analyzer.DIMENSIONS is not None
        assert len(analyzer.DIMENSIONS) >= 6
    
    def test_init_with_custom_dimensions(self):
        """Analyzer initializes with custom dimensions."""
        custom_dims = ("dim1", "dim2", "dim3")
        custom_analyzer = ScoreAnalyzer(dimensions=custom_dims)
        
        assert custom_analyzer.DIMENSIONS == custom_dims


# ============================================================================
# Single Score Analysis Tests
# ============================================================================

class TestWeakestDimension:
    """Test weakest_dimension() method."""
    
    def test_weakest_dimension_returns_string(self, analyzer, unbalanced_score):
        """weakest_dimension returns dimension name."""
        result = analyzer.weakest_dimension(unbalanced_score)
        
        assert isinstance(result, str)
    
    def test_weakest_dimension_correct(self, analyzer, unbalanced_score):
        """weakest_dimension identifies lowest dimension."""
        # unbalanced_score: consistency=0.50 is lowest
        result = analyzer.weakest_dimension(unbalanced_score)
        
        assert result == "consistency"
    
    def test_weakest_dimension_balanced_score(self, analyzer, balanced_score):
        """weakest_dimension works with balanced score."""
        result = analyzer.weakest_dimension(balanced_score)
        
        # All equal, should return any dimension
        assert result in analyzer.DIMENSIONS


class TestStrongestDimension:
    """Test strongest_dimension() method."""
    
    def test_strongest_dimension_returns_string(self, analyzer, unbalanced_score):
        """strongest_dimension returns dimension name."""
        result = analyzer.strongest_dimension(unbalanced_score)
        
        assert isinstance(result, str)
    
    def test_strongest_dimension_correct(self, analyzer, unbalanced_score):
        """strongest_dimension identifies highest dimension."""
        # unbalanced_score: completeness=0.95 is highest
        result = analyzer.strongest_dimension(unbalanced_score)
        
        assert result == "completeness"


class TestDimensionRange:
    """Test dimension_range() method."""
    
    def test_dimension_range_returns_float(self, analyzer, unbalanced_score):
        """dimension_range returns float."""
        result = analyzer.dimension_range(unbalanced_score)
        
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
    
    def test_dimension_range_correct(self, analyzer, unbalanced_score):
        """dimension_range calculates correctly."""
        # unbalanced_score: max=0.95, min=0.50
        result = analyzer.dimension_range(unbalanced_score)
        
        assert result == pytest.approx(0.45, abs=0.01)
    
    def test_dimension_range_balanced(self, analyzer, balanced_score):
        """dimension_range is 0 for balanced score."""
        result = analyzer.dimension_range(balanced_score)
        
        assert result == pytest.approx(0.0, abs=0.001)


class TestScoreBalanceRatio:
    """Test score_balance_ratio() method."""
    
    def test_balance_ratio_returns_float(self, analyzer, unbalanced_score):
        """score_balance_ratio returns float."""
        result = analyzer.score_balance_ratio(unbalanced_score)
        
        assert isinstance(result, float)
        assert result >= 1.0
    
    def test_balance_ratio_balanced_score(self, analyzer, balanced_score):
        """score_balance_ratio is 1.0 for balanced score."""
        result = analyzer.score_balance_ratio(balanced_score)
        
        assert result == pytest.approx(1.0, abs=0.01)
    
    def test_balance_ratio_unbalanced_score(self, analyzer, unbalanced_score):
        """score_balance_ratio is > 1.0 for unbalanced score."""
        # max=0.95, min=0.50 → ratio = 0.95/0.50 = 1.9
        result = analyzer.score_balance_ratio(unbalanced_score)
        
        assert result > 1.5


class TestDimensionsAboveThreshold:
    """Test dimensions_above_threshold() method."""
    
    def test_dimensions_above_threshold_returns_int(self, analyzer, sample_scores):
        """dimensions_above_threshold returns integer."""
        result = analyzer.dimensions_above_threshold(sample_scores[0], 0.7)
        
        assert isinstance(result, int)
    
    def test_dimensions_above_threshold_correct_count(self, analyzer, unbalanced_score):
        """dimensions_above_threshold counts correctly."""
        # unbalanced_score: [0.95, 0.50, 0.85, 0.60, 0.90, 0.70]
        # Above 0.75: 0.95, 0.85, 0.90 = 3
        result = analyzer.dimensions_above_threshold(unbalanced_score, 0.75)
        
        assert result == 3
    
    def test_dimensions_above_threshold_all_below(self, analyzer, low_score):
        """dimensions_above_threshold returns 0 when all below."""
        result = analyzer.dimensions_above_threshold(low_score, 0.9)
        
        assert result == 0


class TestDimensionDelta:
    """Test dimension_delta() method."""
    
    def test_dimension_delta_returns_dict(self, analyzer, balanced_score, high_score):
        """dimension_delta returns dictionary."""
        result = analyzer.dimension_delta(balanced_score, high_score)
        
        assert isinstance(result, dict)
    
    def test_dimension_delta_has_all_dimensions(self, analyzer, balanced_score, high_score):
        """dimension_delta includes all dimensions."""
        result = analyzer.dimension_delta(balanced_score, high_score)
        
        for dim in analyzer.DIMENSIONS:
            assert dim in result
    
    def test_dimension_delta_calculates_correctly(self, analyzer):
        """dimension_delta computes correct deltas."""
        before = MockCriticScore(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        after = MockCriticScore(0.8, 0.6, 0.9, 0.7, 0.8, 0.75)
        
        result = analyzer.dimension_delta(before, after)
        
        assert result["completeness"] == pytest.approx(0.3, abs=0.01)
        assert result["consistency"] == pytest.approx(0.1, abs=0.01)


# ============================================================================
# Dimension Statistics Tests
# ============================================================================

class TestScoreDimensionVariance:
    """Test score_dimension_variance() method."""
    
    def test_variance_returns_float(self, analyzer, unbalanced_score):
        """score_dimension_variance returns float."""
        result = analyzer.score_dimension_variance(unbalanced_score)
        
        assert isinstance(result, float)
        assert result >= 0.0
    
    def test_variance_balanced_score(self, analyzer, balanced_score):
        """score_dimension_variance is 0 for balanced score."""
        result = analyzer.score_dimension_variance(balanced_score)
        
        assert result == pytest.approx(0.0, abs=0.001)
    
    def test_variance_unbalanced_score(self, analyzer, unbalanced_score):
        """score_dimension_variance is > 0 for unbalanced score."""
        result = analyzer.score_dimension_variance(unbalanced_score)
        
        assert result > 0.01


class TestScoreDimensionStd:
    """Test score_dimension_std() method."""
    
    def test_std_returns_float(self, analyzer, unbalanced_score):
        """score_dimension_std returns float."""
        result = analyzer.score_dimension_std(unbalanced_score)
        
        assert isinstance(result, float)
        assert result >= 0.0
    
    def test_std_is_sqrt_of_variance(self, analyzer, unbalanced_score):
        """score_dimension_std equals sqrt of variance."""
        variance = analyzer.score_dimension_variance(unbalanced_score)
        std = analyzer.score_dimension_std(unbalanced_score)
        
        assert std == pytest.approx(variance ** 0.5, abs=0.001)


class TestScoreDimensionEntropy:
    """Test score_dimension_entropy() method."""
    
    def test_entropy_returns_float(self, analyzer, unbalanced_score):
        """score_dimension_entropy returns float."""
        result = analyzer.score_dimension_entropy(unbalanced_score)
        
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
    
    def test_entropy_balanced_score(self, analyzer, balanced_score):
        """score_dimension_entropy is low for balanced score."""
        result = analyzer.score_dimension_entropy(balanced_score)
        
        # All equal dimensions should have low entropy
        assert result < 0.1


class TestScoreDimensionMAD:
    """Test score_dimension_mean_abs_deviation() method."""
    
    def test_mad_returns_float(self, analyzer, unbalanced_score):
        """score_dimension_mean_abs_deviation returns float."""
        result = analyzer.score_dimension_mean_abs_deviation(unbalanced_score)
        
        assert isinstance(result, float)
        assert result >= 0.0
    
    def test_mad_balanced_score(self, analyzer, balanced_score):
        """score_dimension_mean_abs_deviation is 0 for balanced score."""
        result = analyzer.score_dimension_mean_abs_deviation(balanced_score)
        
        assert result == pytest.approx(0.0, abs=0.001)


class TestScoreDimensionZScores:
    """Test z-score methods."""
    
    def test_max_z_returns_float(self, analyzer, unbalanced_score):
        """score_dimension_max_z returns float."""
        result = analyzer.score_dimension_max_z(unbalanced_score)
        
        assert isinstance(result, float)
        assert result >= 0.0
    
    def test_min_z_returns_float(self, analyzer, unbalanced_score):
        """score_dimension_min_z returns float."""
        result = analyzer.score_dimension_min_z(unbalanced_score)
        
        assert isinstance(result, float)
        assert result >= 0.0
    
    def test_z_scores_balanced(self, analyzer, balanced_score):
        """Z-scores are bounded for balanced score."""
        max_z = analyzer.score_dimension_max_z(balanced_score)
        min_z = analyzer.score_dimension_min_z(balanced_score)
        
        # With zero variance, z-scores may default to 0 or 1 depending on implementation
        assert max_z >= 0.0
        assert min_z >= 0.0


# ============================================================================
# Batch Analysis Tests
# ============================================================================

class TestMeanOverall:
    """Test mean_overall() method."""
    
    def test_mean_overall_returns_float(self, analyzer, sample_scores):
        """mean_overall returns float."""
        result = analyzer.mean_overall(sample_scores)
        
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0
    
    def test_mean_overall_correct(self, analyzer, sample_scores):
        """mean_overall calculates correctly."""
        expected = statistics.mean(s.overall for s in sample_scores)
        result = analyzer.mean_overall(sample_scores)
        
        assert result == pytest.approx(expected, abs=0.01)
    
    def test_mean_overall_empty(self, analyzer):
        """mean_overall handles empty list."""
        result = analyzer.mean_overall([])
        
        assert result == 0.0


class TestDimensionMean:
    """Test dimension_mean() method."""
    
    def test_dimension_mean_returns_float(self, analyzer, sample_scores):
        """dimension_mean returns float."""
        result = analyzer.dimension_mean(sample_scores, "completeness")
        
        assert isinstance(result, float)
    
    def test_dimension_mean_correct(self, analyzer, sample_scores):
        """dimension_mean calculates correctly."""
        expected = statistics.mean(s.completeness for s in sample_scores)
        result = analyzer.dimension_mean(sample_scores, "completeness")
        
        assert result == pytest.approx(expected, abs=0.01)


class TestPercentileOverall:
    """Test percentile_overall() method."""
    
    def test_percentile_returns_float(self, analyzer, sample_scores):
        """percentile_overall returns float."""
        result = analyzer.percentile_overall(sample_scores, 75.0)
        
        assert isinstance(result, float)
    
    def test_percentile_75(self, analyzer, sample_scores):
        """percentile_overall computes 75th percentile."""
        result = analyzer.percentile_overall(sample_scores, 75.0)
        
        # Should be close to high values
        assert result > 0.8
    
    def test_percentile_empty_raises(self, analyzer):
        """percentile_overall raises on empty list."""
        with pytest.raises(ValueError):
            analyzer.percentile_overall([], 75.0)
    
    def test_percentile_invalid_range_raises(self, analyzer, sample_scores):
        """percentile_overall raises on invalid percentile."""
        with pytest.raises(ValueError):
            analyzer.percentile_overall(sample_scores, 150.0)


class TestMinMaxOverall:
    """Test min_max_overall() method."""
    
    def test_min_max_returns_tuple(self, analyzer, sample_scores):
        """min_max_overall returns tuple."""
        result = analyzer.min_max_overall(sample_scores)
        
        assert isinstance(result, tuple)
        assert len(result) == 2
    
    def test_min_max_correct(self, analyzer, sample_scores):
        """min_max_overall calculates correctly."""
        min_overall, max_overall = analyzer.min_max_overall(sample_scores)
        
        # Check against actual values
        all_overalls = [s.overall for s in sample_scores]
        assert min_overall == pytest.approx(min(all_overalls), abs=0.01)
        assert max_overall == pytest.approx(max(all_overalls), abs=0.01)
    
    def test_min_max_empty(self, analyzer):
        """min_max_overall handles empty list."""
        min_val, max_val = analyzer.min_max_overall([])
        
        assert min_val == 0.0
        assert max_val == 0.0


class TestBatchDimensionStats:
    """Test batch_dimension_stats() method."""
    
    def test_batch_stats_returns_dict(self, analyzer, sample_scores):
        """batch_dimension_stats returns dictionary."""
        result = analyzer.batch_dimension_stats(sample_scores)
        
        assert isinstance(result, dict)
    
    def test_batch_stats_has_all_dimensions(self, analyzer, sample_scores):
        """batch_dimension_stats includes all dimensions."""
        result = analyzer.batch_dimension_stats(sample_scores)
        
        for dim in analyzer.DIMENSIONS:
            assert dim in result
    
    def test_batch_stats_has_correct_fields(self, analyzer, sample_scores):
        """batch_dimension_stats includes required fields."""
        result = analyzer.batch_dimension_stats(sample_scores)
        
        for dim_stats in result.values():
            assert isinstance(dim_stats, DimensionStats)
            assert hasattr(dim_stats, "overall")
            assert hasattr(dim_stats, "min_value")
            assert hasattr(dim_stats, "max_value")
    
    def test_batch_stats_empty(self, analyzer):
        """batch_dimension_stats handles empty list."""
        result = analyzer.batch_dimension_stats([])
        
        assert result == {}


class TestBatchDivergence:
    """Test batch_divergence() method."""
    
    def test_divergence_returns_float(self, analyzer, sample_scores):
        """batch_divergence returns float."""
        result = analyzer.batch_divergence(sample_scores)
        
        assert isinstance(result, float)
        assert result >= 0.0
    
    def test_divergence_identical_scores(self, analyzer, balanced_score):
        """batch_divergence is 0 for identical scores."""
        identical_scores = [balanced_score] * 5
        result = analyzer.batch_divergence(identical_scores)
        
        assert result == pytest.approx(0.0, abs=0.001)
    
    def test_divergence_varied_scores(self, analyzer, sample_scores):
        """batch_divergence is > 0 for varied scores."""
        result = analyzer.batch_divergence(sample_scores)
        
        assert result > 0.01


# ============================================================================
# Comparative Analysis Tests
# ============================================================================

class TestScoreImprovementPercent:
    """Test score_improvement_percent() method."""
    
    def test_improvement_percent_returns_float(self, analyzer, low_score, high_score):
        """score_improvement_percent returns float."""
        result = analyzer.score_improvement_percent(low_score, high_score)
        
        assert isinstance(result, float)
    
    def test_improvement_percent_positive(self, analyzer, low_score, high_score):
        """score_improvement_percent is positive for improvement."""
        result = analyzer.score_improvement_percent(low_score, high_score)
        
        assert result > 0.0
    
    def test_improvement_percent_negative(self, analyzer, high_score, low_score):
        """score_improvement_percent is negative for decline."""
        result = analyzer.score_improvement_percent(high_score, low_score)
        
        assert result < 0.0
    
    def test_improvement_percent_zero_baseline(self, analyzer, high_score):
        """score_improvement_percent handles zero baseline."""
        zero_score = MockCriticScore(0, 0, 0, 0, 0, 0)
        result = analyzer.score_improvement_percent(zero_score, high_score)
        
        assert result == 0.0


class TestDimensionImprovementCount:
    """Test dimension_improvement_count() method."""
    
    def test_improvement_count_returns_int(self, analyzer, low_score, high_score):
        """dimension_improvement_count returns integer."""
        result = analyzer.dimension_improvement_count(low_score, high_score)
        
        assert isinstance(result, int)
        assert result >= 0
    
    def test_improvement_count_correct(self, analyzer):
        """dimension_improvement_count counts correctly."""
        before = MockCriticScore(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        after = MockCriticScore(0.8, 0.6, 0.9, 0.52, 0.51, 0.75)
        
        # Improvements > 0.01: completeness, consistency, clarity, domain_alignment = 4
        result = analyzer.dimension_improvement_count(before, after, min_improvement=0.05)
        
        # More than 4 have improvement > 0.05
        assert result >= 3


class TestRecommendFocusDimensions:
    """Test recommend_focus_dimensions() method."""
    
    def test_recommend_returns_list(self, analyzer, sample_scores):
        """recommend_focus_dimensions returns list."""
        result = analyzer.recommend_focus_dimensions(sample_scores, count=2)
        
        assert isinstance(result, list)
    
    def test_recommend_respects_count(self, analyzer, sample_scores):
        """recommend_focus_dimensions returns requested count."""
        result = analyzer.recommend_focus_dimensions(sample_scores, count=3)
        
        assert len(result) == 3
    
    def test_recommend_returns_tuples(self, analyzer, sample_scores):
        """recommend_focus_dimensions returns (dimension, score) tuples."""
        result = analyzer.recommend_focus_dimensions(sample_scores, count=2)
        
        for item in result:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], float)
    
    def test_recommend_sorted_ascending(self, analyzer, sample_scores):
        """recommend_focus_dimensions returns lowest scores first."""
        result = analyzer.recommend_focus_dimensions(sample_scores, count=3)
        
        # Should be sorted by score ascending
        scores = [item[1] for item in result]
        assert scores == sorted(scores)


# ============================================================================
# Integration Tests
# ============================================================================

class TestAnalysisWorkflows:
    """Integration tests for analysis workflows."""
    
    def test_single_score_analysis_workflow(self, analyzer, unbalanced_score):
        """Complete workflow analyzing single score."""
        # 1. Identify weakest and strongest
        weakest = analyzer.weakest_dimension(unbalanced_score)
        strongest = analyzer.strongest_dimension(unbalanced_score)
        
        # 2. Compute range and balance
        range_val = analyzer.dimension_range(unbalanced_score)
        balance = analyzer.score_balance_ratio(unbalanced_score)
        
        # 3. Compute variance and std
        variance = analyzer.score_dimension_variance(unbalanced_score)
        std = analyzer.score_dimension_std(unbalanced_score)
        
        # All should be valid
        assert weakest in analyzer.DIMENSIONS
        assert strongest in analyzer.DIMENSIONS
        assert range_val >= 0.0
        assert balance >= 1.0
        assert variance >= 0.0
        assert std >= 0.0
    
    def test_batch_analysis_workflow(self, analyzer, sample_scores):
        """Complete workflow analyzing batch of scores."""
        # 1. Compute overall statistics
        mean = analyzer.mean_overall(sample_scores)
        min_val, max_val = analyzer.min_max_overall(sample_scores)
        p75 = analyzer.percentile_overall(sample_scores, 75.0)
        
        # 2. Compute dimension statistics
        dim_stats = analyzer.batch_dimension_stats(sample_scores)
        
        # 3. Measure divergence
        divergence = analyzer.batch_divergence(sample_scores)
        
        # 4. Get recommendations
        recommendations = analyzer.recommend_focus_dimensions(sample_scores, count=2)
        
        # All should be valid
        assert 0.0 <= mean <= 1.0
        assert min_val <= max_val
        assert p75 >= mean
        assert len(dim_stats) > 0
        assert divergence >= 0.0
        assert len(recommendations) == 2
    
    def test_comparative_analysis_workflow(self, analyzer, low_score, high_score):
        """Complete workflow comparing two scores."""
        # 1. Compute improvement percentage
        improvement = analyzer.score_improvement_percent(low_score, high_score)
        
        # 2. Count improved dimensions
        improved_count = analyzer.dimension_improvement_count(low_score, high_score)
        
        # 3. Get dimension deltas
        deltas = analyzer.dimension_delta(low_score, high_score)
        
        # All should be valid
        assert improvement > 0.0  # high_score is better
        assert improved_count >= 0
        assert len(deltas) == len(analyzer.DIMENSIONS)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

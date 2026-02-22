"""
Unit tests for Batch 202 OntologyCritic analysis methods.

Tests new methods for cache and score distribution analysis:
- cache_hit_potential: Cache utilization ratio
- score_dimension_variance: Variance across dimensions
- dimension_range: Max - min dimension score
- weakest_dimension: Identify lowest scoring dimension
- strongest_dimension: Identify highest scoring dimension
- score_balance_ratio: Min/max dimension ratio
- dimensions_above_threshold: Count dimensions meeting threshold
- overall_vs_best_dimension: Overall vs max dimension comparison
- score_consistency_coefficient: Coefficient of variation
- recommendation_density: Recommendations per weakness
"""

import pytest
from unittest.mock import Mock
from ipfs_datasets_py.optimizers.graphrag import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


@pytest.fixture
def critic():
    """Create a test OntologyCritic instance."""
    return OntologyCritic(use_llm=False)


@pytest.fixture
def balanced_score():
    """Create a CriticScore with balanced dimension scores."""
    return CriticScore(
        completeness=0.75,
        consistency=0.75,
        clarity=0.75,
        granularity=0.75,
        relationship_coherence=0.75,
        domain_alignment=0.75,
        strengths=["balanced"],
        weaknesses=[],
        recommendations=["Maintain consistency"],
    )


@pytest.fixture
def imbalanced_score():
    """Create a CriticScore with imbalanced dimension scores."""
    return CriticScore(
        completeness=0.9,  # Strong
        consistency=0.3,  # Weak
        clarity=0.6,
        granularity=0.7,
        relationship_coherence=0.5,
        domain_alignment=0.6,
        strengths=["Good completeness"],
        weaknesses=["Poor consistency", "Moderate clarity"],
        recommendations=["Improve consistency", "Enhance clarity", "Refine relationships"],
    )


class TestCacheHitPotential:
    """Test cache_hit_potential() method."""

    def test_cache_hit_potential_empty(self, critic):
        """Test with empty cache."""
        OntologyCritic.clear_shared_cache()
        assert critic.cache_hit_potential() == 0.0

    def test_cache_hit_potential_partial(self, critic):
        """Test with partially filled cache."""
        OntologyCritic.clear_shared_cache()
        # Manually add entries to shared cache
        for i in range(128):  # Half of _SHARED_EVAL_CACHE_MAX (256)
            OntologyCritic._SHARED_EVAL_CACHE[f"key_{i}"] = Mock()
        
        potential = critic.cache_hit_potential()
        assert abs(potential - 0.5) < 0.01  # 128/256 = 0.5

    def test_cache_hit_potential_full(self, critic):
        """Test with full cache."""
        OntologyCritic.clear_shared_cache()
        for i in range(256):  # Full cache
            OntologyCritic._SHARED_EVAL_CACHE[f"key_{i}"] = Mock()
        
        potential = critic.cache_hit_potential()
        assert abs(potential - 1.0) < 0.01


class TestScoreDimensionVariance:
    """Test score_dimension_variance() method."""

    def test_variance_balanced(self, critic, balanced_score):
        """Test variance with identical dimension scores."""
        variance = critic.score_dimension_variance(balanced_score)
        assert variance == 0.0  # All scores are 0.75

    def test_variance_imbalanced(self, critic, imbalanced_score):
        """Test variance with varied dimension scores."""
        variance = critic.score_dimension_variance(imbalanced_score)
        # Scores: 0.9, 0.3, 0.6, 0.7, 0.5, 0.6
        # Mean: 0.6, variance should be > 0
        assert variance > 0.0
        assert variance < 0.1  # Reasonable bound

    def test_variance_empty_score(self, critic):
        """Test variance with score having no dimensions."""
        class EmptyScore:
            pass
        mock_score = EmptyScore()
        # All will be 0.0, variance of identical values = 0.0
        result = critic.score_dimension_variance(mock_score)
        assert result == 0.0


class TestDimensionRange:
    """Test dimension_range() method."""

    def test_range_balanced(self, critic, balanced_score):
        """Test range with identical scores."""
        assert critic.dimension_range(balanced_score) == 0.0

    def test_range_imbalanced(self, critic, imbalanced_score):
        """Test range with varied scores."""
        range_val = critic.dimension_range(imbalanced_score)
        # Max = 0.9, Min = 0.3 → Range = 0.6
        assert abs(range_val - 0.6) < 0.01

    def test_range_empty(self, critic):
        """Test range with no dimensions."""
        class EmptyScore:
            pass
        mock_score = EmptyScore()
        # All will be 0.0, so range = 0.0
        assert critic.dimension_range(mock_score) == 0.0


class TestWeakestDimension:
    """Test weakest_dimension() method."""

    def test_weakest_identified(self, critic, imbalanced_score):
        """Test identifying weakest dimension."""
        assert critic.weakest_dimension(imbalanced_score) == "consistency"  # 0.3

    def test_weakest_empty(self, critic):
        """Test with no dimensions."""
        # Create a custom object with no dimension attributes
        class EmptyScore:
            pass
        # Override getattr on the instance to properly handle missing attribs
        mock_score = EmptyScore()
        # Method should handle None by defaulting to 0.0, returning first dimension
        result = critic.weakest_dimension(mock_score)
        # All dimensions will be 0.0, so it returns the first one
        assert result in critic._DIMENSIONS 


class TestStrongestDimension:
    """Test strongest_dimension() method."""

    def test_strongest_identified(self, critic, imbalanced_score):
        """Test identifying strongest dimension."""
        assert critic.strongest_dimension(imbalanced_score) == "completeness"  # 0.9

    def test_strongest_empty(self, critic):
        """Test with no dimensions."""
        class EmptyScore:
            pass
        mock_score = EmptyScore()
        result = critic.strongest_dimension(mock_score)
        # All dimensions will be 0.0 (default), returns the first/any one
        assert result in critic._DIMENSIONS


class TestScoreBalanceRatio:
    """Test score_balance_ratio() method."""

    def test_balance_ratio_perfect(self, critic, balanced_score):
        """Test ratio with balanced scores."""
        ratio = critic.score_balance_ratio(balanced_score)
        assert abs(ratio - 1.0) < 0.01  # 0.75/0.75 = 1.0

    def test_balance_ratio_imbalanced(self, critic, imbalanced_score):
        """Test ratio with imbalanced scores."""
        ratio = critic.score_balance_ratio(imbalanced_score)
        # Min/Max = 0.3 / 0.9 = 0.333...
        assert abs(ratio - 0.333) < 0.01

    def test_balance_ratio_zero_max(self, critic):
        """Test ratio when all dimensions are zero."""
        zero_score = CriticScore(
            completeness=0.0,
            consistency=0.0,
            clarity=0.0,
            granularity=0.0,
            relationship_coherence=0.0,
            domain_alignment=0.0,
            strengths=[],
            weaknesses=[],
            recommendations=[],
        )
        assert critic.score_balance_ratio(zero_score) == 0.0


class TestDimensionsAboveThreshold:
    """Test dimensions_above_threshold() method."""

    def test_threshold_all_above(self, critic, balanced_score):
        """Test when all dimensions above threshold."""
        count = critic.dimensions_above_threshold(balanced_score, threshold=0.7)
        assert count == 6  # All 6 dimensions are 0.75

    def test_threshold_partial(self, critic, imbalanced_score):
        """Test with some dimensions above threshold."""
        count = critic.dimensions_above_threshold(imbalanced_score, threshold=0.65)
        # Above 0.65: completeness(0.9), granularity(0.7) = 2
        assert count == 2

    def test_threshold_none_above(self, critic, imbalanced_score):
        """Test when no dimensions above high threshold."""
        count = critic.dimensions_above_threshold(imbalanced_score, threshold=0.95)
        assert count == 0


class TestOverallVsBestDimension:
    """Test overall_vs_best_dimension() method."""

    def test_overall_vs_best_balanced(self, critic, balanced_score):
        """Test comparison with balanced scores."""
        diff = critic.overall_vs_best_dimension(balanced_score)
        # Overall 0.75, max dimension 0.75 → diff = 0.0
        assert abs(diff) < 0.01

    def test_overall_vs_best_imbalanced(self, critic, imbalanced_score):
        """Test comparison with imbalanced scores."""
        diff = critic.overall_vs_best_dimension(imbalanced_score)
        # Overall 0.6, max dimension 0.9 → diff = -0.3
        assert abs(diff - (-0.3)) < 0.01

    def test_overall_vs_best_empty(self, critic):
        """Test with no dimensions."""
        class EmptyScore:
            overall = 0.5
        mock_score = EmptyScore()
        # overall - max(0.0, 0.0,...) = 0.5 - 0.0 = 0.5
        assert critic.overall_vs_best_dimension(mock_score) == 0.5


class TestScoreConsistencyCoefficient:
    """Test score_consistency_coefficient() method."""

    def test_consistency_balanced(self, critic, balanced_score):
        """Test CV with balanced scores (should be 0)."""
        cv = critic.score_consistency_coefficient(balanced_score)
        assert cv == 0.0

    def test_consistency_imbalanced(self, critic, imbalanced_score):
        """Test CV with imbalanced scores."""
        cv = critic.score_consistency_coefficient(imbalanced_score)
        # Should be non-zero due to variance
        assert cv > 0.0
        assert cv < 1.0  # Reasonable bound for normalized scores

    def test_consistency_zero_mean(self, critic):
        """Test CV when mean is zero."""
        zero_score = CriticScore(
            completeness=0.0,
            consistency=0.0,
            clarity=0.0,
            granularity=0.0,
            relationship_coherence=0.0,
            domain_alignment=0.0,
            strengths=[],
            weaknesses=[],
            recommendations=[],
        )
        assert critic.score_consistency_coefficient(zero_score) == 0.0


class TestRecommendationDensity:
    """Test recommendation_density() method."""

    def test_density_high(self, critic, imbalanced_score):
        """Test density with many recommendations per weakness."""
        density = critic.recommendation_density(imbalanced_score)
        # 3 recommendations / (2 weaknesses + 1) = 1.0
        assert abs(density - 1.0) < 0.01

    def test_density_low(self, critic, balanced_score):
        """Test density with few recommendations."""
        density = critic.recommendation_density(balanced_score)
        # 1 recommendation / (0 weaknesses + 1) = 1.0
        assert abs(density - 1.0) < 0.01

    def test_density_no_recommendations(self, critic):
        """Test density with no recommendations."""
        empty_score = CriticScore(
            completeness=0.5,
            consistency=0.5,
            clarity=0.5,
            granularity=0.5,
            relationship_coherence=0.5,
            domain_alignment=0.5,
            strengths=[],
            weaknesses=["Issue 1", "Issue 2"],
            recommendations=[],
        )
        density = critic.recommendation_density(empty_score)
        # 0 recommendations / (2 weaknesses + 1) = 0.0
        assert density == 0.0


class TestBatch202Integration:
    """Integration tests combining multiple Batch 202 methods."""

    def test_comprehensive_score_analysis(self, critic, imbalanced_score):
        """Test complete analysis workflow."""
        # Analyze dimensional quality
        weakest = critic.weakest_dimension(imbalanced_score)
        strongest = critic.strongest_dimension(imbalanced_score)
        range_val = critic.dimension_range(imbalanced_score)
        variance = critic.score_dimension_variance(imbalanced_score)
        balance = critic.score_balance_ratio(imbalanced_score)
        
        assert weakest == "consistency"
        assert strongest == "completeness"
        assert range_val > 0.5
        assert variance > 0.0
        assert balance < 0.5  # Imbalanced

    def test_cache_and_recommendations(self, critic, imbalanced_score):
        """Test cache utilization and recommendation analysis."""
        OntologyCritic.clear_shared_cache()
        cache_util = critic.cache_hit_potential()
        rec_density = critic.recommendation_density(imbalanced_score)
        
        assert cache_util == 0.0  # Empty cache
        assert rec_density == 1.0  # 3 recs / (2 weak + 1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

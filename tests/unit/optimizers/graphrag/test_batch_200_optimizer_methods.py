"""
Unit tests for Batch 200 OntologyOptimizer analysis methods.

Tests new methods added to support deeper performance analysis:
- score_at_index: Access scores by position
- history_length: Query history size
- score_recent_variance: Variance of recent scores
- score_recent_mean: Mean of recent scores
- has_regressed: Regression detection
- improvement_ratio: Overall improvement tracking
- score_recovery_time: Round count to recover
- score_below_baseline: Baseline violation count
- moving_median: Median of recent values
- trend_reversal_count: Track trend changes
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyOptimizer,
    OptimizationReport,
)


class TestScoreAtIndex:
    """Test score_at_index() method."""

    def test_score_at_index_positive(self):
        """Test accessing score at valid positive index."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
        ]
        assert optimizer.score_at_index(0) == 0.5
        assert optimizer.score_at_index(1) == 0.7
        assert optimizer.score_at_index(2) == 0.6

    def test_score_at_index_negative(self):
        """Test accessing score with negative index."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
        ]
        assert optimizer.score_at_index(-1) == 0.6  # Last
        assert optimizer.score_at_index(-2) == 0.7  # Second to last
        assert optimizer.score_at_index(-3) == 0.5  # First

    def test_score_at_index_out_of_bounds(self):
        """Test accessing out-of-bounds index."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
        ]
        assert optimizer.score_at_index(10) == 0.0
        assert optimizer.score_at_index(-10) == 0.0

    def test_score_at_index_empty_history(self):
        """Test accessing when history is empty."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.score_at_index(0) == 0.0
        assert optimizer.score_at_index(-1) == 0.0


class TestHistoryLength:
    """Test history_length() method."""

    def test_history_length_positive(self):
        """Test history length with multiple entries."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
        ]
        assert optimizer.history_length() == 3

    def test_history_length_single(self):
        """Test history length with single entry."""
        optimizer = OntologyOptimizer()
        optimizer._history = [OptimizationReport(average_score=0.5, trend="stable")]
        assert optimizer.history_length() == 1

    def test_history_length_empty(self):
        """Test history length when empty."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.history_length() == 0


class TestScoreRecentVariance:
    """Test score_recent_variance() method."""

    def test_score_recent_variance_positive(self):
        """Test variance of recent scores."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.3, trend="stable"),
        ]
        variance = optimizer.score_recent_variance(n=5)
        assert variance > 0
        assert 0 <= variance <= 1

    def test_score_recent_variance_identical(self):
        """Test variance when all recent scores are identical."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
        ]
        assert optimizer.score_recent_variance(n=3) == 0.0

    def test_score_recent_variance_insufficient_data(self):
        """Test variance with insufficient data."""
        optimizer = OntologyOptimizer()
        optimizer._history = [OptimizationReport(average_score=0.5, trend="stable")]
        assert optimizer.score_recent_variance(n=5) == 0.0

    def test_score_recent_variance_empty(self):
        """Test variance with empty history."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.score_recent_variance(n=1) == 0.0


class TestScoreRecentMean:
    """Test score_recent_mean() method."""

    def test_score_recent_mean_positive(self):
        """Test mean of recent scores."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.8, trend="stable"),
        ]
        mean = optimizer.score_recent_mean(n=3)
        assert abs(mean - 0.7) < 1e-6

    def test_score_recent_mean_more_than_available(self):
        """Test mean when requesting more entries than available."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
        ]
        mean = optimizer.score_recent_mean(n=10)
        assert abs(mean - 0.6) < 1e-6

    def test_score_recent_mean_empty(self):
        """Test mean with empty history."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.score_recent_mean(n=5) == 0.0

    def test_score_recent_mean_invalid_n(self):
        """Test mean with invalid n."""
        optimizer = OntologyOptimizer()
        optimizer._history = [OptimizationReport(average_score=0.5, trend="stable")]
        assert optimizer.score_recent_mean(n=0) == 0.0
        assert optimizer.score_recent_mean(n=-1) == 0.0


class TestHasRegressed:
    """Test has_regressed() method."""

    def test_has_regressed_true(self):
        """Test when regression detected."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.8, trend="stable"),
            OptimizationReport(average_score=0.9, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
        ]
        assert optimizer.has_regressed(threshold=0.01)

    def test_has_regressed_false(self):
        """Test when no regression detected."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
        ]
        assert not optimizer.has_regressed(threshold=0.01)

    def test_has_regressed_insufficient_history(self):
        """Test regression check with insufficient history."""
        optimizer = OntologyOptimizer()
        optimizer._history = [OptimizationReport(average_score=0.5, trend="stable")]
        assert not optimizer.has_regressed()

    def test_has_regressed_empty_history(self):
        """Test regression check with empty history."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert not optimizer.has_regressed()


class TestImprovementRatio:
    """Test improvement_ratio() method."""

    def test_improvement_ratio_positive(self):
        """Test improvement ratio with positive growth."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.8, trend="stable"),
        ]
        ratio = optimizer.improvement_ratio()
        expected = (0.8 - 0.5) / 0.5  # 0.6
        assert abs(ratio - expected) < 1e-6

    def test_improvement_ratio_no_improvement(self):
        """Test improvement ratio with no improvement."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
        ]
        assert optimizer.improvement_ratio() == 0.0

    def test_improvement_ratio_zero_first(self):
        """Test improvement ratio when first score is zero."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.0, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
        ]
        assert optimizer.improvement_ratio() == 0.0

    def test_improvement_ratio_insufficient_history(self):
        """Test improvement ratio with insufficient history."""
        optimizer = OntologyOptimizer()
        optimizer._history = [OptimizationReport(average_score=0.5, trend="stable")]
        assert optimizer.improvement_ratio() == 0.0


class TestScoreRecoveryTime:
    """Test score_recovery_time() method."""

    def test_score_recovery_time_found(self):
        """Test recovery time when recovery occurs."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.8, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),  # Drop below 0.7
            OptimizationReport(average_score=0.5, trend="stable"),  # Still below
            OptimizationReport(average_score=0.75, trend="stable"),  # Recover
        ]
        recovery = optimizer.score_recovery_time(threshold=0.7)
        assert recovery == 2  # 2 rounds after the drop

    def test_score_recovery_time_never_dropped(self):
        """Test recovery time when never dropped."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.8, trend="stable"),
            OptimizationReport(average_score=0.9, trend="stable"),
        ]
        assert optimizer.score_recovery_time(threshold=0.7) == -1

    def test_score_recovery_time_never_recovered(self):
        """Test recovery time when dropped but never recovered."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.8, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
        ]
        assert optimizer.score_recovery_time(threshold=0.7) == -1

    def test_score_recovery_time_empty(self):
        """Test recovery time with empty history."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.score_recovery_time() == -1


class TestScoreBelowBaseline:
    """Test score_below_baseline() method."""

    def test_score_below_baseline_positive(self):
        """Test count of scores below baseline."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.4, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.3, trend="stable"),
            OptimizationReport(average_score=0.8, trend="stable"),
        ]
        count = optimizer.score_below_baseline(baseline=0.5)
        assert count == 2

    def test_score_below_baseline_none(self):
        """Test when no scores below baseline."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.8, trend="stable"),
        ]
        assert optimizer.score_below_baseline(baseline=0.5) == 0

    def test_score_below_baseline_all(self):
        """Test when all scores below baseline."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.3, trend="stable"),
            OptimizationReport(average_score=0.4, trend="stable"),
        ]
        assert optimizer.score_below_baseline(baseline=0.5) == 2

    def test_score_below_baseline_empty(self):
        """Test with empty history."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.score_below_baseline() == 0


class TestMovingMedian:
    """Test moving_median() method."""

    def test_moving_median_odd_window(self):
        """Test moving median with odd window size."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.3, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
        ]
        median = optimizer.moving_median(window=3)
        assert median == 0.5

    def test_moving_median_even_window(self):
        """Test moving median with even window size."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.2, trend="stable"),
            OptimizationReport(average_score=0.4, trend="stable"),
        ]
        median = optimizer.moving_median(window=2)
        assert abs(median - 0.3) < 1e-6

    def test_moving_median_more_entries(self):
        """Test moving median with more entries available."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.1, trend="stable"),
            OptimizationReport(average_score=0.2, trend="stable"),
            OptimizationReport(average_score=0.3, trend="stable"),
            OptimizationReport(average_score=0.4, trend="stable"),
        ]
        median = optimizer.moving_median(window=3)
        assert median == 0.3  # Last 3: [0.2, 0.3, 0.4] -> sorted -> median 0.3

    def test_moving_median_empty(self):
        """Test moving median with empty history."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.moving_median(window=1) == 0.0

    def test_moving_median_invalid_window(self):
        """Test moving median with invalid window."""
        optimizer = OntologyOptimizer()
        optimizer._history = [OptimizationReport(average_score=0.5, trend="stable")]
        assert optimizer.moving_median(window=0) == 0.0
        assert optimizer.moving_median(window=-1) == 0.0


class TestTrendReversalCount:
    """Test trend_reversal_count() method."""

    def test_trend_reversal_count_single(self):
        """Test with single reversal."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),  # Improving
            OptimizationReport(average_score=0.6, trend="stable"),  # Reversal to declining
        ]
        assert optimizer.trend_reversal_count() == 1

    def test_trend_reversal_count_multiple(self):
        """Test with multiple reversals."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),  # Improving
            OptimizationReport(average_score=0.6, trend="stable"),  # Reversal
            OptimizationReport(average_score=0.8, trend="stable"),  # Reversal to improving
            OptimizationReport(average_score=0.7, trend="stable"),  # Reversal
        ]
        assert optimizer.trend_reversal_count() == 3

    def test_trend_reversal_count_none(self):
        """Test with no reversals."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
        ]
        assert optimizer.trend_reversal_count() == 0

    def test_trend_reversal_count_flat(self):
        """Test with flat trend (no change)."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
        ]
        assert optimizer.trend_reversal_count() == 0

    def test_trend_reversal_count_insufficient(self):
        """Test with insufficient data."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.6, trend="stable"),
        ]
        assert optimizer.trend_reversal_count() == 0

    def test_trend_reversal_count_empty(self):
        """Test with empty history."""
        optimizer = OntologyOptimizer()
        optimizer._history = []
        assert optimizer.trend_reversal_count() == 0


# Integration tests
class TestBatch200Integration:
    """Integration tests for multiple methods working together."""

    def test_recent_metrics_consistency(self):
        """Test that recent-focused methods are consistent."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.6, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
            OptimizationReport(average_score=0.8, trend="stable"),
            OptimizationReport(average_score=0.75, trend="stable"),
            OptimizationReport(average_score=0.9, trend="stable"),
        ]
        
        # Mean of last 3 should be within bounds
        mean = optimizer.score_recent_mean(n=3)
        assert 0.75 <= mean <= 0.85
        
        # Length should be 5
        assert optimizer.history_length() == 5
        
        # Recent scores should reflect improvement
        assert not optimizer.has_regressed(threshold=0.2)

    def test_recovery_analysis(self):
        """Test recovery analysis methods together."""
        optimizer = OntologyOptimizer()
        optimizer._history = [
            OptimizationReport(average_score=0.8, trend="stable"),
            OptimizationReport(average_score=0.9, trend="stable"),
            OptimizationReport(average_score=0.5, trend="stable"),
            OptimizationReport(average_score=0.4, trend="stable"),
            OptimizationReport(average_score=0.7, trend="stable"),
        ]
        
        # Should detect regression
        assert optimizer.has_regressed(threshold=0.01)
        
        # Should find recovery time
        recovery = optimizer.score_recovery_time(threshold=0.6)
        assert recovery > 0
        
        # Should see trend reversals
        assert optimizer.trend_reversal_count() > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

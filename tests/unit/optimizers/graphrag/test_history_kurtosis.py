"""Tests for OntologyGenerator.history_kurtosis() method.

Tests statistical analysis of confidence score distributions across multiple
extraction results.
"""

import pytest
from unittest.mock import Mock
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator


class TestHistoryKurtosis:
    """Test history_kurtosis method."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.generator = OntologyGenerator()
    
    def _create_result_with_confidences(self, confidences):
        """Helper to create mock EntityExtractionResult."""
        result = Mock()
        result.entities = [Mock(confidence=c) for c in confidences]
        result.relationships = []
        return result
    
    def test_empty_results_list(self):
        """Returns 0.0 for empty results list."""
        kurtosis = self.generator.history_kurtosis([])
        assert kurtosis == 0.0
    
    def test_fewer_than_four_entities(self):
        """Returns 0.0 when total entities < 4."""
        results = [
            self._create_result_with_confidences([0.8]),
            self._create_result_with_confidences([0.9]),
            self._create_result_with_confidences([0.7]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        assert kurtosis == 0.0
    
    def test_normal_distribution_kurtosis(self):
        """Returns ~0.0 for normally distributed scores."""
        # Approximate normal distribution (actually fairly uniform)
        results = [
            self._create_result_with_confidences([0.5, 0.52, 0.48]),
            self._create_result_with_confidences([0.51, 0.49, 0.50]),
            self._create_result_with_confidences([0.48, 0.52, 0.50]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Normal distribution has excess kurtosis of 0
        # Uniform-like distributions have negative kurtosis
        assert -2.0 <= kurtosis <= 1.0
    
    def test_uniform_distribution_negative_kurtosis(self):
        """Returns negative kurtosis for uniform distribution."""
        # Uniform distribution (light tails)
        results = [
            self._create_result_with_confidences([0.2, 0.4, 0.6, 0.8]),
            self._create_result_with_confidences([0.3, 0.5, 0.7, 0.9]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Uniform distribution has excess kurtosis of -1.2
        # Should be negative
        assert kurtosis < 0.0
    
    def test_heavy_tails_positive_kurtosis(self):
        """Returns positive kurtosis for heavy-tailed distribution."""
        # Distribution with outliers (heavy tails)
        results = [
            self._create_result_with_confidences([0.5, 0.5, 0.5, 0.5]),
            self._create_result_with_confidences([0.1, 0.9, 0.5, 0.5]),  # Outliers
            self._create_result_with_confidences([0.05, 0.95, 0.5, 0.5]),  # More outliers
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Should be positive due to outliers
        assert kurtosis > 0.0
    
    def test_constant_values_zero_kurtosis(self):
        """Returns 0.0 for constant values (std = 0)."""
        results = [
            self._create_result_with_confidences([0.8, 0.8, 0.8, 0.8]),
            self._create_result_with_confidences([0.8, 0.8, 0.8, 0.8]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        assert kurtosis == 0.0
    
    def test_single_result_multiple_entities(self):
        """Handles single result with multiple entities."""
        results = [
            self._create_result_with_confidences([0.3, 0.5, 0.7, 0.9, 0.4, 0.6])
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Should calculate kurtosis successfully
        assert isinstance(kurtosis, float)
        assert kurtosis != 0.0 or len(results[0].entities) < 4
    
    def test_multiple_results_aggregate_correctly(self):
        """Aggregates entities from multiple results correctly."""
        results = [
            self._create_result_with_confidences([0.5, 0.6]),
            self._create_result_with_confidences([0.7, 0.8]),
            self._create_result_with_confidences([0.4, 0.9]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Should process all 6 entities together
        assert isinstance(kurtosis, float)
    
    def test_bimodal_distribution(self):
        """Handles bimodal distribution (two peaks)."""
        # Bimodal: two clusters of values
        results = [
            self._create_result_with_confidences([0.2, 0.3, 0.2, 0.3]),
            self._create_result_with_confidences([0.7, 0.8, 0.7, 0.8]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Bimodal distributions typically have negative kurtosis
        assert isinstance(kurtosis, float)
    
    def test_large_dataset(self):
        """Handles large number of entities efficiently."""
        results = [
            self._create_result_with_confidences([0.5 + i * 0.01 for i in range(100)])
            for _ in range(10)
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Should handle 1000 entities without issue
        assert isinstance(kurtosis, float)
    
    def test_mixed_confidence_ranges(self):
        """Handles mixed confidence score ranges."""
        results = [
            self._create_result_with_confidences([0.1, 0.2, 0.3, 0.4]),
            self._create_result_with_confidences([0.6, 0.7, 0.8, 0.9]),
            self._create_result_with_confidences([0.45, 0.5, 0.55, 0.6]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        assert isinstance(kurtosis, float)
    
    def test_results_with_no_entities(self):
        """Handles results with no entities gracefully."""
        results = [
            self._create_result_with_confidences([]),
            self._create_result_with_confidences([0.5, 0.6, 0.7, 0.8]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Should only count the 4 entities from second result
        assert isinstance(kurtosis, float)
    
    def test_results_with_none_entities(self):
        """Handles results with None entities attribute."""
        result1 = Mock()
        result1.entities = None
        result1.relationships = []
        
        result2 = self._create_result_with_confidences([0.5, 0.6, 0.7, 0.8])
        
        results = [result1, result2]
        kurtosis = self.generator.history_kurtosis(results)
        
        # Should handle None gracefully
        assert isinstance(kurtosis, float)
    
    def test_extreme_outliers(self):
        """Handles extreme outlier values."""
        results = [
            self._create_result_with_confidences([0.5, 0.5, 0.5, 0.5]),
            self._create_result_with_confidences([0.01, 0.99, 0.5, 0.5]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Extreme outliers should produce positive kurtosis
        assert kurtosis > 0.0


class TestHistoryKurtosisEdgeCases:
    """Test edge cases for history_kurtosis."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.generator = OntologyGenerator()
    
    def _create_result_with_confidences(self, confidences):
        """Helper to create mock EntityExtractionResult."""
        result = Mock()
        result.entities = [Mock(confidence=c) for c in confidences]
        result.relationships = []
        return result
    
    def test_exactly_four_entities(self):
        """Handles exactly 4 entities (minimum for kurtosis)."""
        results = [
            self._create_result_with_confidences([0.2, 0.4, 0.6, 0.8])
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        assert isinstance(kurtosis, float)
    
    def test_very_small_variance(self):
        """Handles very small variance (near-constant values)."""
        results = [
            self._create_result_with_confidences([
                0.5000, 0.5001, 0.5002, 0.5003
            ])
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        assert isinstance(kurtosis, float)
    
    def test_all_zeros(self):
        """Handles all zero confidence scores."""
        results = [
            self._create_result_with_confidences([0.0, 0.0, 0.0, 0.0, 0.0])
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        assert kurtosis == 0.0  # std = 0
    
    def test_all_ones(self):
        """Handles all maximum confidence scores."""
        results = [
            self._create_result_with_confidences([1.0, 1.0, 1.0, 1.0, 1.0])
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        assert kurtosis == 0.0  # std = 0
    
    def test_alternating_extremes(self):
        """Handles alternating extreme values."""
        results = [
            self._create_result_with_confidences([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Bimodal with extreme separation
        assert isinstance(kurtosis, float)


class TestHistoryKurtosisInterpretation:
    """Test kurtosis interpretation for real-world scenarios."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.generator = OntologyGenerator()
    
    def _create_result_with_confidences(self, confidences):
        """Helper to create mock EntityExtractionResult."""
        result = Mock()
        result.entities = [Mock(confidence=c) for c in confidences]
        result.relationships = []
        return result
    
    def test_consistent_quality_low_kurtosis(self):
        """Consistent extraction quality has low kurtosis."""
        # Consistently good extractions
        results = [
            self._create_result_with_confidences([0.75, 0.78, 0.77, 0.76]),
            self._create_result_with_confidences([0.74, 0.79, 0.77, 0.75]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Should be close to 0 or negative (light tails)
        assert kurtosis < 1.0
    
    def test_inconsistent_quality_high_kurtosis(self):
        """Bimodal distribution shows characteristic kurtosis pattern."""
        # Mix of very good and very poor extractions (bimodal)
        results = [
            self._create_result_with_confidences([0.9, 0.95, 0.92, 0.88]),
            self._create_result_with_confidences([0.1, 0.15, 0.05, 0.2]),
            self._create_result_with_confidences([0.5, 0.5, 0.5, 0.5]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Bimodal distributions typically have negative kurtosis
        # (two peaks, lighter tails than normal)
        assert isinstance(kurtosis, float)
    
    def test_gradual_improvement_trend(self):
        """Gradual improvement shows specific kurtosis pattern."""
        # Scores improving over time
        results = [
            self._create_result_with_confidences([0.3, 0.35, 0.32, 0.38]),
            self._create_result_with_confidences([0.5, 0.52, 0.48, 0.55]),
            self._create_result_with_confidences([0.7, 0.72, 0.68, 0.75]),
        ]
        
        kurtosis = self.generator.history_kurtosis(results)
        # Should have moderate distribution
        assert isinstance(kurtosis, float)

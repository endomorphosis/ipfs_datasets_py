"""
Unit tests for Batch 203 LogicValidator analysis methods.

Tests new methods for cache and validation result analysis:
- cache_size: Get number of cached results
- cache_hit_ratio: Calculate cache hit ratio
- result_has_contradictions: Check for contradictions
- result_contradiction_count: Count contradictions
- result_proof_count: Count proofs
- result_invalid_entity_count: Count invalid entities
- result_is_high_confidence: Check confidence threshold
- result_processing_speed: Calculate validation speed
- result_consistency_ratio: Ratio of consistent results
- average_validation_time: Mean validation time
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.logic_validator import (
    LogicValidator,
    ValidationResult,
)


@pytest.fixture
def validator():
    """Create a test LogicValidator instance."""
    return LogicValidator(use_cache=True)


@pytest.fixture
def validator_no_cache():
    """Create a LogicValidator with caching disabled."""
    return LogicValidator(use_cache=False)


@pytest.fixture
def consistent_result():
    """Create a consistent ValidationResult."""
    return ValidationResult(
        is_consistent=True,
        contradictions=[],
        proofs=[{"axiom1": "proof1"}, {"axiom2": "proof2"}],
        confidence=0.95,
        prover_used="z3",
        time_ms=50.0,
        invalid_entity_ids=[],
    )


@pytest.fixture
def inconsistent_result():
    """Create an inconsistent ValidationResult with contradictions."""
    return ValidationResult(
        is_consistent=False,
        contradictions=["Axiom A contradicts Axiom B", "Cycle detected in subsumption"],
        proofs=[],
        confidence=0.60,
        prover_used="cvc5",
        time_ms=120.0,
        invalid_entity_ids=["entity_1", "entity_2", "entity_3"],
    )


class TestCacheSize:
    """Test cache_size() method."""

    def test_cache_size_empty(self, validator):
        """Test with empty cache."""
        assert validator.cache_size() == 0

    def test_cache_size_with_entries(self, validator):
        """Test after adding cache entries."""
        validator._cache = {"key1": "val1", "key2": "val2", "key3": "val3"}
        assert validator.cache_size() == 3

    def test_cache_size_disabled(self, validator_no_cache):
        """Test when caching is disabled."""
        assert validator_no_cache.cache_size() == 0


class TestCacheHitRatio:
    """Test cache_hit_ratio() method."""

    def test_hit_ratio_empty_cache(self, validator):
        """Test ratio with empty cache."""
        ratio = validator.cache_hit_ratio(total_checks=10)
        assert ratio == 0.0

    def test_hit_ratio_partial_hits(self, validator):
        """Test ratio with partial cache hits."""
        validator._cache = {"k1": "v1", "k2": "v2"}
        ratio = validator.cache_hit_ratio(total_checks=10)
        # 2 cached / 10 total = 0.2
        assert abs(ratio - 0.2) < 0.01

    def test_hit_ratio_zero_checks(self, validator):
        """Test ratio with zero total checks."""
        validator._cache = {"k1": "v1"}
        assert validator.cache_hit_ratio(total_checks=0) == 0.0

    def test_hit_ratio_disabled_cache(self, validator_no_cache):
        """Test ratio when caching is disabled."""
        assert validator_no_cache.cache_hit_ratio(total_checks=10) == 0.0


class TestResultHasContradictions:
    """Test result_has_contradictions() method."""

    def test_has_contradictions_true(self, validator, inconsistent_result):
        """Test with result containing contradictions."""
        assert validator.result_has_contradictions(inconsistent_result) is True

    def test_has_contradictions_false(self, validator, consistent_result):
        """Test with result having no contradictions."""
        assert validator.result_has_contradictions(consistent_result) is False

    def test_has_contradictions_empty_list(self, validator):
        """Test with empty contradictions list."""
        empty_result = ValidationResult(
            is_consistent=True,
            contradictions=[],
        )
        assert validator.result_has_contradictions(empty_result) is False


class TestResultContradictionCount:
    """Test result_contradiction_count() method."""

    def test_contradiction_count_zero(self, validator, consistent_result):
        """Test count with no contradictions."""
        assert validator.result_contradiction_count(consistent_result) == 0

    def test_contradiction_count_multiple(self, validator, inconsistent_result):
        """Test count with multiple contradictions."""
        assert validator.result_contradiction_count(inconsistent_result) == 2

    def test_contradiction_count_one(self, validator):
        """Test count with single contradiction."""
        result = ValidationResult(
            is_consistent=False,
            contradictions=["Single issue"],
        )
        assert validator.result_contradiction_count(result) == 1


class TestResultProofCount:
    """Test result_proof_count() method."""

    def test_proof_count_zero(self, validator, inconsistent_result):
        """Test count with no proofs."""
        assert validator.result_proof_count(inconsistent_result) == 0

    def test_proof_count_multiple(self, validator, consistent_result):
        """Test count with multiple proofs."""
        assert validator.result_proof_count(consistent_result) == 2

    def test_proof_count_one(self, validator):
        """Test count with single proof."""
        result = ValidationResult(
            is_consistent=True,
            proofs=[{"axiom": "proof"}],
        )
        assert validator.result_proof_count(result) == 1


class TestResultInvalidEntityCount:
    """Test result_invalid_entity_count() method."""

    def test_invalid_entity_count_zero(self, validator, consistent_result):
        """Test count with no invalid entities."""
        assert validator.result_invalid_entity_count(consistent_result) == 0

    def test_invalid_entity_count_multiple(self, validator, inconsistent_result):
        """Test count with multiple invalid entities."""
        assert validator.result_invalid_entity_count(inconsistent_result) == 3

    def test_invalid_entity_count_one(self, validator):
        """Test count with single invalid entity."""
        result = ValidationResult(
            is_consistent=False,
            invalid_entity_ids=["entity_x"],
        )
        assert validator.result_invalid_entity_count(result) == 1


class TestResultIsHighConfidence:
    """Test result_is_high_confidence() method."""

    def test_high_confidence_true(self, validator, consistent_result):
        """Test high confidence detection (0.95 >= 0.8)."""
        assert validator.result_is_high_confidence(consistent_result) is True

    def test_high_confidence_false(self, validator, inconsistent_result):
        """Test low confidence detection (0.60 < 0.8)."""
        assert validator.result_is_high_confidence(inconsistent_result) is False

    def test_high_confidence_custom_threshold(self, validator, consistent_result):
        """Test with custom threshold."""
        # 0.95 < 0.98
        assert validator.result_is_high_confidence(consistent_result, threshold=0.98) is False
        # 0.95 >= 0.90
        assert validator.result_is_high_confidence(consistent_result, threshold=0.90) is True

    def test_high_confidence_edge_case(self, validator):
        """Test when confidence exactly equals threshold."""
        result = ValidationResult(
            is_consistent=True,
            confidence=0.80,
        )
        assert validator.result_is_high_confidence(result, threshold=0.80) is True


class TestResultProcessingSpeed:
    """Test result_processing_speed() method."""

    def test_processing_speed_normal(self, validator, consistent_result):
        """Test speed calculation with normal values."""
        # 100 formulas in 50.0 ms = 2.0 formulas/ms
        speed = validator.result_processing_speed(consistent_result, formula_count=100)
        assert abs(speed - 2.0) < 0.01

    def test_processing_speed_slow(self, validator, inconsistent_result):
        """Test speed with slower processing."""
        # 60 formulas in 120.0 ms = 0.5 formulas/ms
        speed = validator.result_processing_speed(inconsistent_result, formula_count=60)
        assert abs(speed - 0.5) < 0.01

    def test_processing_speed_zero_time(self, validator):
        """Test speed when time_ms is zero."""
        result = ValidationResult(
            is_consistent=True,
            time_ms=0.0,
        )
        assert validator.result_processing_speed(result, formula_count=100) == 0.0

    def test_processing_speed_zero_formulas(self, validator, consistent_result):
        """Test speed with zero formulas."""
        # 0 formulas / 50ms = 0.0
        speed = validator.result_processing_speed(consistent_result, formula_count=0)
        assert speed == 0.0


class TestResultConsistencyRatio:
    """Test result_consistency_ratio() method."""

    def test_consistency_ratio_all_consistent(self, validator, consistent_result):
        """Test ratio when all results are consistent."""
        results = [consistent_result] * 5
        ratio = validator.result_consistency_ratio(results)
        assert abs(ratio - 1.0) < 0.01

    def test_consistency_ratio_all_inconsistent(self, validator, inconsistent_result):
        """Test ratio when all results are inconsistent."""
        results = [inconsistent_result] * 4
        ratio = validator.result_consistency_ratio(results)
        assert abs(ratio - 0.0) < 0.01

    def test_consistency_ratio_mixed(self, validator, consistent_result, inconsistent_result):
        """Test ratio with mixed results."""
        results = [consistent_result, inconsistent_result, consistent_result, inconsistent_result, consistent_result]
        # 3 consistent / 5 total = 0.6
        ratio = validator.result_consistency_ratio(results)
        assert abs(ratio - 0.6) < 0.01

    def test_consistency_ratio_empty_list(self, validator):
        """Test ratio with empty results list."""
        assert validator.result_consistency_ratio([]) == 0.0


class TestAverageValidationTime:
    """Test average_validation_time() method."""

    def test_average_time_single(self, validator, consistent_result):
        """Test average with single result."""
        avg_time = validator.average_validation_time([consistent_result])
        assert abs(avg_time - 50.0) < 0.01

    def test_average_time_multiple(self, validator, consistent_result, inconsistent_result):
        """Test average with multiple results."""
        results = [consistent_result, inconsistent_result]
        # (50.0 + 120.0) / 2 = 85.0
        avg_time = validator.average_validation_time(results)
        assert abs(avg_time - 85.0) < 0.01

    def test_average_time_varied(self, validator):
        """Test average with varied times."""
        r1 = ValidationResult(is_consistent=True, time_ms=10.0)
        r2 = ValidationResult(is_consistent=True, time_ms=20.0)
        r3 = ValidationResult(is_consistent=True, time_ms=30.0)
        # (10 + 20 + 30) / 3 = 20.0
        avg_time = validator.average_validation_time([r1, r2, r3])
        assert abs(avg_time - 20.0) < 0.01

    def test_average_time_empty_list(self, validator):
        """Test average with empty results list."""
        assert validator.average_validation_time([]) == 0.0


class TestBatch203Integration:
    """Integration tests combining multiple Batch 203 methods."""

    def test_comprehensive_result_analysis(self, validator, inconsistent_result):
        """Test complete analysis workflow for a single result."""
        # Analyze inconsistent result
        has_contrad = validator.result_has_contradictions(inconsistent_result)
        contrad_count = validator.result_contradiction_count(inconsistent_result)
        proof_count = validator.result_proof_count(inconsistent_result)
        invalid_count = validator.result_invalid_entity_count(inconsistent_result)
        high_conf = validator.result_is_high_confidence(inconsistent_result)
        speed = validator.result_processing_speed(inconsistent_result, formula_count=60)

        assert has_contrad is True
        assert contrad_count == 2
        assert proof_count == 0
        assert invalid_count == 3
        assert high_conf is False
        assert abs(speed - 0.5) < 0.01

    def test_batch_result_analysis(self, validator, consistent_result, inconsistent_result):
        """Test analyzing a batch of results."""
        results = [
            consistent_result,
            inconsistent_result,
            consistent_result,
            consistent_result,
        ]
        
        consistency_ratio = validator.result_consistency_ratio(results)
        avg_time = validator.average_validation_time(results)
        
        # 3/4 = 0.75
        assert abs(consistency_ratio - 0.75) < 0.01
        # (50 + 120 + 50 + 50) / 4 = 67.5
        assert abs(avg_time - 67.5) < 0.01

    def test_cache_performance_tracking(self, validator):
        """Test cache performance analysis."""
        # Simulate cache usage
        validator._cache = {"ont1": "result1", "ont2": "result2"}
        
        size = validator.cache_size()
        hit_ratio = validator.cache_hit_ratio(total_checks=10)
        
        assert size == 2
        assert abs(hit_ratio - 0.2) < 0.01  # 2/10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

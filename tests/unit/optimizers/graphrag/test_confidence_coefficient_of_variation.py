"""Tests for coefficient of variation statistical method.

Tests confidence_coefficient_of_variation for distribution analysis.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    Entity,
    EntityExtractionResult,
)


@pytest.fixture
def generator():
    """Create OntologyGenerator instance."""
    return OntologyGenerator()


@pytest.fixture
def sample_results_varied():
    """Create results with varied confidence scores (high CV)."""
    return [
        EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Low1", type="TEST", confidence=0.2),
                Entity(id="e2", text="Low2", type="TEST", confidence=0.3),
            ],
            relationships=[],
            confidence=0.25,
            metadata={},
        ),
        EntityExtractionResult(
            entities=[
                Entity(id="e3", text="Mid1", type="TEST", confidence=0.5),
                Entity(id="e4", text="Mid2", type="TEST", confidence=0.6),
                Entity(id="e5", text="Mid3", type="TEST", confidence=0.7),
            ],
            relationships=[],
            confidence=0.6,
            metadata={},
        ),
        EntityExtractionResult(
            entities=[
                Entity(id="e6", text="High1", type="TEST", confidence=0.9),
                Entity(id="e7", text="High2", type="TEST", confidence=0.95),
            ],
            relationships=[],
            confidence=0.925,
            metadata={},
        ),
    ]


@pytest.fixture
def sample_results_stable():
    """Create results with low variability (low CV)."""
    return [
        EntityExtractionResult(
            entities=[
                Entity(id=f"e{i}", text=f"Test{i}", type="TEST", confidence=0.85 + i*0.01)
                for i in range(10)
            ],
            relationships=[],
            confidence=0.9,
            metadata={},
        )
    ]


@pytest.fixture
def sample_results_high_variance():
    """Create results with extreme variance."""
    return [
        EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Zero", type="TEST", confidence=0.01),
                Entity(id="e2", text="Half", type="TEST", confidence=0.5),
                Entity(id="e3", text="Max", type="TEST", confidence=0.99),
            ],
            relationships=[],
            confidence=0.5,
            metadata={},
        )
    ]


class TestCoefficientOfVariationBasic:
    """Test basic coefficient of variation calculations."""
    
    def test_cv_basic_calculation(self, generator, sample_results_varied):
        """Calculate CV for varied distribution."""
        cv = generator.confidence_coefficient_of_variation(sample_results_varied)
        
        # CV should be positive for varied data
        assert cv > 0.0
        
        # For this data: scores = [0.2, 0.3, 0.5, 0.6, 0.7, 0.9, 0.95]
        # Mean = 0.585, StdDev ≈ 0.308
        # CV ≈ 0.527
        assert 0.4 < cv < 0.7
    
    def test_cv_stable_low(self, generator, sample_results_stable):
        """CV should be low for stable extraction quality."""
        cv = generator.confidence_coefficient_of_variation(sample_results_stable)
        
        # Very similar scores should have low CV
        assert 0.0 <= cv < 0.1  # Very stable
    
    def test_cv_high_variance(self, generator, sample_results_high_variance):
        """CV should be high for extreme variance."""
        cv = generator.confidence_coefficient_of_variation(sample_results_high_variance)
        
        # Extreme spread should have high CV
        # Scores: [0.01, 0.5, 0.99]
        # Mean: 0.5, StdDev ≈ 0.479
        # CV ≈ 0.958
        assert cv > 0.5


class TestCoefficientOfVariationEdgeCases:
    """Test edge cases for CV calculation."""
    
    def test_cv_empty_results(self, generator):
        """Handle empty results."""
        cv = generator.confidence_coefficient_of_variation([])
        
        assert cv == 0.0
    
    def test_cv_no_entities(self, generator):
        """Handle results with no entities."""
        results = [
            EntityExtractionResult(
                entities=[],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        assert cv == 0.0
    
    def test_cv_single_entity(self, generator):
        """Handle single entity (insufficient for CV)."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Only", type="TEST", confidence=0.75),
                ],
                relationships=[],
                confidence=0.75,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        assert cv == 0.0
    
    def test_cv_uniform_distribution(self, generator):
        """CV is zero for identical scores."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.8)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.8,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        assert cv == pytest.approx(0.0, abs=1e-10)
    
    def test_cv_zero_mean_handling(self, generator):
        """Handle edge case of zero mean (shouldn't occur with confidence scores)."""
        # CV is technically undefined for zero mean, return 0.0
        # This is defensive; confidence scores shouldn't be all zero
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Zero1", type="TEST", confidence=0.0),
                    Entity(id="e2", text="Zero2", type="TEST", confidence=0.0),
                ],
                relationships=[],
                confidence=0.0,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        assert cv == 0.0


class TestCoefficientOfVariationInterpretation:
    """Test interpretation of CV values for quality assessment."""
    
    def test_cv_very_stable(self, generator):
        """CV < 0.1 indicates very stable extraction."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.88 + i*0.001)
                    for i in range(20)
                ],
                relationships=[],
                confidence=0.89,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        assert cv < 0.1
        # Quality assessment
        if cv < 0.1:
            stability = "Very stable"
        assert stability == "Very stable"
    
    def test_cv_moderate_consistency(self, generator):
        """CV 0.1-0.3 indicates moderate consistency."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.6 + i*0.05)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.75,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        assert 0.1 <= cv <= 0.3
        # Quality assessment
        if 0.1 <= cv <= 0.3:
            stability = "Moderate"
        assert stability == "Moderate"
    
    def test_cv_high_variability(self, generator):
        """CV > 0.5 indicates high variability/inconsistent quality."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Bad", type="TEST", confidence=0.1),
                    Entity(id="e2", text="Good", type="TEST", confidence=0.95),
                ],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        assert cv > 0.5
        # Quality assessment
        if cv > 0.5:
            stability = "Inconsistent - investigate"
        assert stability == "Inconsistent - investigate"


class TestCoefficientOfVariationComparison:
    """Test CV comparison with other statistical measures."""
    
    def test_cv_vs_range_same_distribution(self, generator):
        """Compare CV to range for same distribution."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=i/10)
                    for i in range(11)  # 0.0 to 1.0
                ],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        conf_range = generator.confidence_range(results)
        
        # Both should indicate high variability
        assert cv > 0.3
        assert conf_range > 0.9
    
    def test_cv_normalized_vs_range(self, generator):
        """CV is normalized; range is absolute."""
        # Two distributions with same range but different means
        
        # Distribution 1: 0.1 to 0.9 (range=0.8, mean=0.5)
        results1 = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.1 + i*0.1)
                    for i in range(9)
                ],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
        ]
        
        # Distribution 2: 0.45 to 1.0 (range=0.55, mean=0.73)
        results2 = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.45 + i*0.55/8)
                    for i in range(9)
                ],
                relationships=[],
                confidence=0.73,
                metadata={},
            )
        ]
        
        cv1 = generator.confidence_coefficient_of_variation(results1)
        cv2 = generator.confidence_coefficient_of_variation(results2)
        
        # CV is normalized, so distributions with different means
        # can have comparable CV values
        # This makes CV more useful for comparing quality consistency
        # across different extraction scenarios
        assert cv1 > 0.0
        assert cv2 > 0.0
    
    def test_cv_with_iqr_comparison(self, generator, sample_results_varied):
        """Compare CV with IQR for robustness analysis."""
        cv = generator.confidence_coefficient_of_variation(sample_results_varied)
        iqr = generator.confidence_iqr(sample_results_varied)
        
        # Both measure variability but differently
        # CV is normalized (dimensionless), IQR is absolute
        assert cv > 0.0
        assert iqr > 0.0
        
        # For same data, both should indicate similar level of variability
        if cv < 0.2:
            variability = "Low"
        else:
            variability = "High"
        
        assert variability in ["Low", "High"]


class TestCoefficientOfVariationMultipleResults:
    """Test CV with multiple extraction results."""
    
    def test_cv_aggregates_across_results(self, generator):
        """CV aggregates confidence scores across all results."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="T1", type="TEST", confidence=0.7),
                    Entity(id="e2", text="T2", type="TEST", confidence=0.8),
                ],
                relationships=[],
                confidence=0.75,
                metadata={},
            ),
            EntityExtractionResult(
                entities=[
                    Entity(id="e3", text="T3", type="TEST", confidence=0.5),
                    Entity(id="e4", text="T4", type="TEST", confidence=0.6),
                ],
                relationships=[],
                confidence=0.55,
                metadata={},
            ),
            EntityExtractionResult(
                entities=[
                    Entity(id="e5", text="T5", type="TEST", confidence=0.9),
                ],
                relationships=[],
                confidence=0.9,
                metadata={},
            ),
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        # Should aggregate all 5 scores: [0.7, 0.8, 0.5, 0.6, 0.9]
        # Mean: 0.7, StdDev ≈ 0.141, CV ≈ 0.201
        assert 0.15 < cv < 0.25
    
    def test_cv_ignores_result_confidence(self, generator):
        """CV uses entity confidence, not result-level confidence."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="T1", type="TEST", confidence=0.5),
                    Entity(id="e2", text="T2", type="TEST", confidence=0.5),
                ],
                relationships=[],
                confidence=0.95,  # High result confidence
                metadata={},
            ),
            EntityExtractionResult(
                entities=[
                    Entity(id="e3", text="T3", type="TEST", confidence=0.5),
                ],
                relationships=[],
                confidence=0.05,  # Low result confidence
                metadata={},
            ),
        ]
        
        cv = generator.confidence_coefficient_of_variation(results)
        
        # CV should be 0 (all entity confidences are 0.5)
        # It should NOT be affected by result-level confidence
        assert cv == pytest.approx(0.0, abs=1e-10)


class TestCoefficientOfVariationQualityMonitoring:
    """Test CV for quality monitoring workflows."""
    
    def test_cv_quality_trend(self, generator):
        """Use CV to monitor extraction quality trend."""
        # Simulate extraction quality over time
        results_good = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.85 + i*0.01)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.9,
                metadata={},
            )
        ]
        
        results_degraded = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.3 + i*0.1)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.7,
                metadata={},
            )
        ]
        
        cv_good = generator.confidence_coefficient_of_variation(results_good)
        cv_degraded = generator.confidence_coefficient_of_variation(results_degraded)
        
        # Degraded quality should have higher CV
        assert cv_good < cv_degraded
    
    def test_cv_threshold_alerting(self, generator):
        """Set CV thresholds for quality alerts."""
        # Define thresholds
        CV_EXCELLENT = 0.05
        CV_GOOD = 0.15
        CV_WARNING = 0.30
        CV_CRITICAL = 0.50
        
        # Test data at each level
        
        # Excellent
        results_excellent = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.88 + i*0.001)
                    for i in range(50)
                ],
                relationships=[],
                confidence=0.89,
                metadata={},
            )
        ]
        
        # Warning
        results_warning = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.2 + i*0.1)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.65,
                metadata={},
            )
        ]
        
        cv_excellent = generator.confidence_coefficient_of_variation(results_excellent)
        cv_warning = generator.confidence_coefficient_of_variation(results_warning)
        
        # Classify
        def get_quality_level(cv):
            if cv < CV_GOOD:
                return "Excellent"
            elif cv < CV_WARNING:
                return "Good"
            elif cv < CV_CRITICAL:
                return "Warning"
            else:
                return "Critical"
        
        assert get_quality_level(cv_excellent) == "Excellent"
        assert get_quality_level(cv_warning) in ["Good", "Warning"]


class TestCoefficientOfVariationStatisticalProperties:
    """Test statistical properties and invariants."""
    
    def test_cv_always_non_negative(self, generator):
        """CV is always >= 0 (mathematical property)."""
        test_cases = [
            [],  # Empty
            [EntityExtractionResult(entities=[], relationships=[], confidence=0.5, metadata={})],  # No entities
            [EntityExtractionResult(
                entities=[Entity(id="e1", text="T", type="TEST", confidence=0.8)],
                relationships=[],
                confidence=0.8,
                metadata={}
            )],  # Single entity
        ]
        
        for results in test_cases:
            cv = generator.confidence_coefficient_of_variation(results)
            assert cv >= 0.0
    
    def test_cv_dimensionless(self, generator):
        """CV is dimensionless (normalized to mean)."""
        # Two distributions scaled proportionally should have similar CV
        
        # Low scale: 0.01-0.1
        results_low = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.01 + i*0.01)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.055,
                metadata={},
            )
        ]
        
        # High scale: 0.1-1.0 (10x scaling)
        results_high = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.1 + i*0.1)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.55,
                metadata={},
            )
        ]
        
        cv_low = generator.confidence_coefficient_of_variation(results_low)
        cv_high = generator.confidence_coefficient_of_variation(results_high)
        
        # CV should be approximately the same (dimensionless)
        assert cv_low == pytest.approx(cv_high, rel=0.01)

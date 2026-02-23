"""Tests for confidence dimension statistical methods.

Tests confidence_min, confidence_max, confidence_range, confidence_percentile, and confidence_iqr.
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
    """Create results with varied confidence scores."""
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
def sample_results_uniform():
    """Create results with uniform confidence scores."""
    return [
        EntityExtractionResult(
            entities=[
                Entity(id=f"e{i}", text=f"Test{i}", type="TEST", confidence=0.75),
            ],
            relationships=[],
            confidence=0.75,
            metadata={},
        )
        for i in range(10)
    ]


class TestConfidenceMin:
    """Test confidence_min method."""
    
    def test_min_basic(self, generator, sample_results_varied):
        """Find minimum confidence across results."""
        min_conf = generator.confidence_min(sample_results_varied)
        
        # Minimum should be 0.2 (from first result)
        assert min_conf == pytest.approx(0.2)
    
    def test_min_empty_results(self, generator):
        """Handle empty results list."""
        min_conf = generator.confidence_min([])
        
        assert min_conf == 0.0
    
    def test_min_all_same(self, generator, sample_results_uniform):
        """Min equals max when all scores identical."""
        min_conf = generator.confidence_min(sample_results_uniform)
        
        assert min_conf == pytest.approx(0.75)
    
    def test_min_single_entity(self, generator):
        """Handle single entity."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Test", type="TEST", confidence=0.42),
            ],
            relationships=[],
            confidence=0.42,
            metadata={},
        )
        
        min_conf = generator.confidence_min([result])
        
        assert min_conf == pytest.approx(0.42)


class TestConfidenceMax:
    """Test confidence_max method."""
    
    def test_max_basic(self, generator, sample_results_varied):
        """Find maximum confidence across results."""
        max_conf = generator.confidence_max(sample_results_varied)
        
        # Maximum should be 0.95 (from third result)
        assert max_conf == pytest.approx(0.95)
    
    def test_max_empty_results(self, generator):
        """Handle empty results list."""
        max_conf = generator.confidence_max([])
        
        assert max_conf == 0.0
    
    def test_max_all_same(self, generator, sample_results_uniform):
        """Max equals min when all scores identical."""
        max_conf = generator.confidence_max(sample_results_uniform)
        
        assert max_conf == pytest.approx(0.75)
    
    def test_max_extremes(self, generator):
        """Handle extreme values."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Test1", type="TEST", confidence=0.0),
                    Entity(id="e2", text="Test2", type="TEST", confidence=1.0),
                ],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
        ]
        
        max_conf = generator.confidence_max(results)
        
        assert max_conf == pytest.approx(1.0)


class TestConfidenceRange:
    """Test confidence_range method."""
    
    def test_range_basic(self, generator, sample_results_varied):
        """Calculate confidence range."""
        conf_range = generator.confidence_range(sample_results_varied)
        
        # Range = max - min = 0.95 - 0.2 = 0.75
        assert conf_range == pytest.approx(0.75)
    
    def test_range_zero_uniform(self, generator, sample_results_uniform):
        """Range is zero for uniform scores."""
        conf_range = generator.confidence_range(sample_results_uniform)
        
        assert conf_range == pytest.approx(0.0, abs=1e-10)
    
    def test_range_empty_results(self, generator):
        """Handle empty results."""
        conf_range = generator.confidence_range([])
        
        assert conf_range == 0.0
    
    def test_range_full_spectrum(self, generator):
        """Range spans full [0, 1] spectrum."""
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Min", type="TEST", confidence=0.0),
                    Entity(id="e2", text="Max", type="TEST", confidence=1.0),
                ],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
        ]
        
        conf_range = generator.confidence_range(results)
        
        assert conf_range == pytest.approx(1.0)
    
    def test_range_interpretation(self, generator):
        """Interpret range for quality assessment."""
        # Low range = stable quality
        stable_results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="T1", type="TEST", confidence=0.88),
                    Entity(id="e2", text="T2", type="TEST", confidence=0.92),
                ],
                relationships=[],
                confidence=0.9,
                metadata={},
            )
        ]
        
        stable_range = generator.confidence_range(stable_results)
        assert stable_range < 0.1  # Stable
        
        # High range = inconsistent quality
        unstable_results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="T1", type="TEST", confidence=0.1),
                    Entity(id="e2", text="T2", type="TEST", confidence=0.9),
                ],
                relationships=[],
                confidence=0.5,
                metadata={},
            )
        ]
        
        unstable_range = generator.confidence_range(unstable_results)
        assert unstable_range > 0.5  # Unstable


class TestConfidencePercentile:
    """Test confidence_percentile method."""
    
    def test_percentile_median(self, generator, sample_results_varied):
        """Calculate 50th percentile (median)."""
        p50 = generator.confidence_percentile(sample_results_varied, 50)
        
        # Scores: [0.2, 0.3, 0.5, 0.6, 0.7, 0.9, 0.95]
        # Median (50th) ≈ 0.6
        assert 0.5 <= p50 <= 0.7
    
    def test_percentile_quartiles(self, generator, sample_results_varied):
        """Calculate Q1 and Q3."""
        q1 = generator.confidence_percentile(sample_results_varied, 25)
        q3 = generator.confidence_percentile(sample_results_varied, 75)
        
        # Q1 should be lower than Q3
        assert q1 < q3
        
        # Q1 ≈ 0.3-0.5, Q3 ≈ 0.7-0.9
        assert 0.2 <= q1 <= 0.5
        assert 0.7 <= q3 <= 0.95
    
    def test_percentile_extremes(self, generator, sample_results_varied):
        """Calculate extreme percentiles."""
        p0 = generator.confidence_percentile(sample_results_varied, 0)
        p100 = generator.confidence_percentile(sample_results_varied, 100)
        
        # 0th percentile = min
        assert p0 == pytest.approx(0.2)
        
        # 100th percentile = max
        assert p100 == pytest.approx(0.95)
    
    def test_percentile_empty_results(self, generator):
        """Handle empty results."""
        p50 = generator.confidence_percentile([], 50)
        
        assert p50 == 0.0
    
    def test_percentile_bounds_clamping(self, generator, sample_results_varied):
        """Percentile parameter is clamped to [0, 100]."""
        # Negative percentile clamped to 0
        p_negative = generator.confidence_percentile(sample_results_varied, -10)
        p0 = generator.confidence_percentile(sample_results_varied, 0)
        assert p_negative == pytest.approx(p0)
        
        # >100 percentile clamped to 100
        p_over = generator.confidence_percentile(sample_results_varied, 150)
        p100 = generator.confidence_percentile(sample_results_varied, 100)
        assert p_over == pytest.approx(p100)
    
    def test_percentile_uniform_distribution(self, generator, sample_results_uniform):
        """All percentiles equal for uniform distribution."""
        p25 = generator.confidence_percentile(sample_results_uniform, 25)
        p50 = generator.confidence_percentile(sample_results_uniform, 50)
        p75 = generator.confidence_percentile(sample_results_uniform, 75)
        
        # All should be 0.75
        assert p25 == pytest.approx(0.75)
        assert p50 == pytest.approx(0.75)
        assert p75 == pytest.approx(0.75)
    
    def test_percentile_high_quality_threshold(self, generator):
        """Use 95th percentile to identify high-quality threshold."""
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
        
        p95 = generator.confidence_percentile(results, 95)
        
        # 95th should be close to 0.95
        assert p95 > 0.9


class TestConfidenceIQR:
    """Test confidence_iqr method."""
    
    def test_iqr_basic(self, generator, sample_results_varied):
        """Calculate interquartile range."""
        iqr = generator.confidence_iqr(sample_results_varied)
        
        # IQR = Q3 - Q1
        q1 = generator.confidence_percentile(sample_results_varied, 25)
        q3 = generator.confidence_percentile(sample_results_varied, 75)
        expected_iqr = q3 - q1
        
        assert iqr == pytest.approx(expected_iqr)
    
    def test_iqr_zero_uniform(self, generator, sample_results_uniform):
        """IQR is zero for uniform distribution."""
        iqr = generator.confidence_iqr(sample_results_uniform)
        
        assert iqr == pytest.approx(0.0, abs=1e-10)
    
    def test_iqr_empty_results(self, generator):
        """Handle empty results."""
        iqr = generator.confidence_iqr([])
        
        assert iqr == 0.0
    
    def test_iqr_outlier_detection(self, generator):
        """Use IQR for outlier detection."""
        # Create data with outliers
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id="e1", text="Outlier", type="TEST", confidence=0.1),  # Outlier
                    Entity(id="e2", text="Normal1", type="TEST", confidence=0.7),
                    Entity(id="e3", text="Normal2", type="TEST", confidence=0.75),
                    Entity(id="e4", text="Normal3", type="TEST", confidence=0.8),
                    Entity(id="e5", text="Outlier2", type="TEST", confidence=0.95),  # Outlier
                ],
                relationships=[],
                confidence=0.66,
                metadata={},
            )
        ]
        
        iqr = generator.confidence_iqr(results)
        q1 = generator.confidence_percentile(results, 25)
        q3 = generator.confidence_percentile(results, 75)
        
        # Outlier fences
        lower_fence = q1 - 1.5 * iqr
        upper_fence = q3 + 1.5 * iqr
        
        # Check which values are outliers
        all_scores = [0.1, 0.7, 0.75, 0.8, 0.95]
        outliers = [s for s in all_scores if s < lower_fence or s > upper_fence]
        
        # Should detect at least one outlier
        assert len(outliers) >= 1
    
    def test_iqr_vs_range(self, generator, sample_results_varied):
        """IQR is more robust to outliers than range."""
        iqr = generator.confidence_iqr(sample_results_varied)
        conf_range = generator.confidence_range(sample_results_varied)
        
        # IQR should be smaller than range (middle 50% vs full spread)
        assert iqr < conf_range


class TestDimensionMethodsIntegration:
    """Integration tests for dimension methods."""
    
    def test_all_dimensions_consistent(self, generator, sample_results_varied):
        """All dimension methods return consistent related values."""
        min_conf = generator.confidence_min(sample_results_varied)
        max_conf = generator.confidence_max(sample_results_varied)
        conf_range = generator.confidence_range(sample_results_varied)
        p0 = generator.confidence_percentile(sample_results_varied, 0)
        p100 = generator.confidence_percentile(sample_results_varied, 100)
        
        # Consistency checks
        assert min_conf == pytest.approx(p0)
        assert max_conf == pytest.approx(p100)
        assert conf_range == pytest.approx(max_conf - min_conf)
        assert min_conf <= max_conf
    
    def test_quality_assessment_workflow(self, generator):
        """Complete quality assessment workflow."""
        # Generate sample results
        results = [
            EntityExtractionResult(
                entities=[
                    Entity(id=f"e{i}", text=f"T{i}", type="TEST", confidence=0.5 + i*0.05)
                    for i in range(10)
                ],
                relationships=[],
                confidence=0.75,
                metadata={},
            )
        ]
        
        # Collect metrics
        min_conf = generator.confidence_min(results)
        max_conf = generator.confidence_max(results)
        conf_range = generator.confidence_range(results)
        median = generator.confidence_percentile(results, 50)
        iqr = generator.confidence_iqr(results)
        
        # All metrics should be valid
        assert 0.0 <= min_conf <= 1.0
        assert 0.0 <= max_conf <= 1.0
        assert 0.0 <= conf_range <= 1.0
        assert 0.0 <= median <= 1.0
        assert 0.0 <= iqr <= 1.0
        
        # Quality assessment
        if conf_range < 0.2:
            quality = "Stable"
        elif conf_range < 0.5:
            quality = "Moderate variance"
        else:
            quality = "High variance"
        
        assert quality in ["Stable", "Moderate variance", "High variance"]
    
    def test_percentile_ordering(self, generator, sample_results_varied):
        """Percentiles are in ascending order."""
        p10 = generator.confidence_percentile(sample_results_varied, 10)
        p25 = generator.confidence_percentile(sample_results_varied, 25)
        p50 = generator.confidence_percentile(sample_results_varied, 50)
        p75 = generator.confidence_percentile(sample_results_varied, 75)
        p90 = generator.confidence_percentile(sample_results_varied, 90)
        
        # Should be monotonically increasing
        assert p10 <= p25 <= p50 <= p75 <= p90

"""Tests for confidence analysis and reporting utilities.

Tests cover:
- Statistical computation (mean, median, stdev)
- Histogram generation and binning
- Low-confidence filtering
- Markdown and JSON report generation
- Edge cases (empty lists, single value, identical values)
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.confidence_analyzer import (
    ConfidenceStats,
    ConfidenceHistogram,
    ConfidenceReport,
    compute_confidence_stats,
    compute_confidence_histogram,
    extract_entity_confidences,
    extract_relationship_confidences,
    analyze_extraction_results,
)


class TestConfidenceStats:
    """Test ConfidenceStats computation."""
    
    def test_single_value(self):
        """Single confidence value should have mean=median=value."""
        stats = compute_confidence_stats([0.75])
        
        assert stats.mean_confidence == 0.75
        assert stats.median_confidence == 0.75
        assert stats.min_confidence == 0.75
        assert stats.max_confidence == 0.75
        assert stats.count == 1
        assert stats.stdev_confidence == 0.0
    
    def test_identical_values(self):
        """Identical values should have stdev=0."""
        stats = compute_confidence_stats([0.8, 0.8, 0.8, 0.8])
        
        assert stats.mean_confidence == 0.8
        assert stats.median_confidence == 0.8
        assert stats.stdev_confidence == 0.0
        assert stats.count == 4
    
    def test_two_values(self):
        """Two values should compute median correctly."""
        stats = compute_confidence_stats([0.5, 1.0])
        
        assert stats.min_confidence == 0.5
        assert stats.max_confidence == 1.0
        assert stats.mean_confidence == 0.75
        assert stats.median_confidence == 0.75
        assert stats.count == 2
    
    def test_multiple_values(self):
        """Multiple values should compute all stats correctly."""
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        stats = compute_confidence_stats(values)
        
        assert stats.count == 10
        assert stats.min_confidence == 0.1
        assert stats.max_confidence == 1.0
        assert stats.mean_confidence == 0.55
        assert abs(stats.median_confidence - 0.55) < 0.01  # (0.5 + 0.6) / 2 = 0.55
    
    def test_empty_list_raises(self):
        """Empty list should raise ValueError."""
        with pytest.raises(ValueError):
            compute_confidence_stats([])
    
    def test_to_dict(self):
        """Stats should serialize to dict."""
        stats = compute_confidence_stats([0.5, 0.75, 1.0])
        d = stats.to_dict()
        
        assert "min" in d
        assert "max" in d
        assert "mean" in d
        assert "median" in d
        assert "stdev" in d
        assert "count" in d
        assert d["count"] == 3


class TestConfidenceHistogram:
    """Test ConfidenceHistogram generation and properties."""
    
    def test_uniform_distribution(self):
        """Uniform distribution should spread values evenly."""
        # 10 values, each 0.1 apart
        values = [0.05 + 0.1 * i for i in range(10)]
        histogram = compute_confidence_histogram(values, num_bins=10)
        
        assert len(histogram.bins) == 10
        assert len(histogram.counts) == 10
        assert sum(histogram.counts) == 10
        assert histogram.total == 10
    
    def test_single_bin(self):
        """Single bin should contain all values."""
        values = [0.5, 0.5, 0.5]
        histogram = compute_confidence_histogram(values, num_bins=1)
        
        assert len(histogram.bins) == 1
        assert histogram.counts[0] == 3
        assert histogram.total == 3
    
    def test_many_bins(self):
        """Many bins should not break."""
        values = list(range(0, 101)) 
        values = [v / 100.0 for v in values]
        histogram = compute_confidence_histogram(values, num_bins=20)
        
        assert len(histogram.bins) == 20
        assert sum(histogram.counts) == len(values)
    
    def test_empty_histogram(self):
        """Empty histogram should be valid."""
        histogram = compute_confidence_histogram([], num_bins=10)
        
        assert histogram.total == 0
        assert len(histogram.bins) == 0
        assert len(histogram.counts) == 0
    
    def test_ascii_art_generation(self):
        """ASCII art should be generated without errors."""
        values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        histogram = compute_confidence_histogram(values, num_bins=10)
        
        ascii_art = histogram.to_ascii_art(width=60)
        
        assert isinstance(ascii_art, str)
        assert len(ascii_art) > 0
        assert "█" in ascii_art or "empty" in ascii_art.lower()
    
    def test_to_dict(self):
        """Histogram should serialize to dict."""
        values = [0.5, 0.75, 1.0]
        histogram = compute_confidence_histogram(values, num_bins=2)
        d = histogram.to_dict()
        
        assert "bins" in d
        assert "counts" in d
        assert "total" in d
        assert d["total"] == 3


class TestConfidenceExtraction:
    """Test extracting confidences from entities/relationships."""
    
    def test_extract_entity_confidences(self):
        """Extract confidence from entity list."""
        entities = [
            {"id": "e1", "confidence": 0.95},
            {"id": "e2", "confidence": 0.75},
            {"id": "e3", "confidence": 0.50},
        ]
        
        confs = extract_entity_confidences(entities)
        
        assert confs == [0.95, 0.75, 0.50]
    
    def test_extract_entity_confidences_missing(self):
        """Missing confidence defaults to 1.0."""
        entities = [
            {"id": "e1", "confidence": 0.95},
            {"id": "e2"},  # Missing confidence
        ]
        
        confs = extract_entity_confidences(entities)
        
        assert confs == [0.95, 1.0]
    
    def test_extract_relationship_confidences(self):
        """Extract confidence from relationship list."""
        relationships = [
            {"id": "r1", "confidence": 0.85},
            {"id": "r2", "confidence": 0.60},
        ]
        
        confs = extract_relationship_confidences(relationships)
        
        assert confs == [0.85, 0.60]


class TestConfidenceReport:
    """Test ConfidenceReport generation and formatting."""
    
    def test_entity_only_report(self):
        """Report with entities only."""
        entities = [
            {"id": "e1", "confidence": 0.95},
            {"id": "e2", "confidence": 0.50},
            {"id": "e3", "confidence": 0.40},
        ]
        
        report = analyze_extraction_results(entities, low_confidence_threshold=0.6)
        
        assert report.entity_stats.count == 3
        assert len(report.low_confidence_entities) == 2  # e2, e3
        assert report.relationship_stats is None
    
    def test_full_report(self):
        """Report with entities and relationships."""
        entities = [
            {"id": "e1", "confidence": 0.95},
            {"id": "e2", "confidence": 0.50},
        ]
        relationships = [
            {"id": "r1", "confidence": 0.85},
            {"id": "r2", "confidence": 0.40},
        ]
        
        report = analyze_extraction_results(
            entities,
            relationships,
            low_confidence_threshold=0.6,
        )
        
        assert report.entity_stats.count == 2
        assert report.relationship_stats is not None
        assert report.relationship_stats.count == 2
        assert len(report.low_confidence_relationships) == 1
    
    def test_report_to_dict(self):
        """Report should serialize to dict."""
        entities = [
            {"id": "e1", "confidence": 0.95},
            {"id": "e2", "confidence": 0.50},
        ]
        
        report = analyze_extraction_results(entities, low_confidence_threshold=0.6)
        d = report.to_dict()
        
        assert "entity_stats" in d
        assert "entity_histogram" in d
        assert "low_confidence_threshold" in d
        assert "low_confidence_entities_count" in d
    
    def test_report_to_json(self):
        """Report should serialize to JSON."""
        entities = [
            {"id": "e1", "confidence": 0.95},
            {"id": "e2", "confidence": 0.50},
        ]
        
        report = analyze_extraction_results(entities)
        json_str = report.to_json()
        
        assert isinstance(json_str, str)
        assert len(json_str) > 0
        
        # Should be valid JSON
        import json
        parsed = json.loads(json_str)
        assert "entity_stats" in parsed
    
    def test_report_to_markdown(self):
        """Report should generate markdown."""
        entities = [
            {"id": "e1", "confidence": 0.95},
            {"id": "e2", "confidence": 0.50},
        ]
        relationships = [
            {"id": "r1", "confidence": 0.85},
        ]
        
        report = analyze_extraction_results(
            entities,
            relationships,
            low_confidence_threshold=0.6,
        )
        markdown = report.to_markdown()
        
        assert "# Confidence Analysis Report" in markdown
        assert "Entity Confidence Statistics" in markdown
        assert "Relationship Confidence Statistics" in markdown
        assert "Low Confidence Results" in markdown


class TestEdgeCases:
    """Test edge cases and boundary conditions."""
    
    def test_all_perfect_confidence(self):
        """All entities with perfect confidence."""
        entities = [{"id": "e1", "confidence": 1.0} for _ in range(5)]
        report = analyze_extraction_results(entities)
        
        assert report.entity_stats.mean_confidence == 1.0
        assert report.entity_stats.median_confidence == 1.0
        assert report.entity_stats.min_confidence == 1.0
        assert report.entity_stats.max_confidence == 1.0
        assert len(report.low_confidence_entities) == 0
    
    def test_all_zero_confidence(self):
        """All entities with zero confidence."""
        entities = [{"id": "e1", "confidence": 0.0} for _ in range(5)]
        report = analyze_extraction_results(entities, low_confidence_threshold=0.1)
        
        assert report.entity_stats.mean_confidence == 0.0
        assert report.entity_stats.median_confidence == 0.0
        assert len(report.low_confidence_entities) == 5
    
    def test_zero_threshold(self):
        """Zero threshold should flag nothing as low-confidence."""
        entities = [
            {"id": "e1", "confidence": 0.001},
            {"id": "e2", "confidence": 0.0},
        ]
        report = analyze_extraction_results(entities, low_confidence_threshold=0.0)
        
        # Nothing should be below 0.0
        assert len(report.low_confidence_entities) == 0
    
    def test_one_threshold(self):
        """Threshold of 1.0 should flag everything but perfect confidence."""
        entities = [
            {"id": "e1", "confidence": 1.0},
            {"id": "e2", "confidence": 0.999},
            {"id": "e3", "confidence": 0.5},
        ]
        report = analyze_extraction_results(entities, low_confidence_threshold=1.0)
        
        # e2 and e3 are below 1.0
        assert len(report.low_confidence_entities) == 2
    
    def test_very_small_values(self):
        """Tiny confidence values should compute correctly."""
        import math
        entities = [
            {"id": "e1", "confidence": 1e-10},
            {"id": "e2", "confidence": 1e-9},
            {"id": "e3", "confidence": 1e-8},
        ]
        report = analyze_extraction_results(entities)
        
        assert report.entity_stats.min_confidence > 0.0
        assert report.entity_stats.max_confidence < 1e-7


class TestStatisticalProperties:
    """Test statistical properties of computed values."""
    
    def test_mean_within_bounds(self):
        """Mean should be between min and max."""
        scores = [0.1, 0.2, 0.5, 0.8, 0.9]
        stats = compute_confidence_stats(scores)
        
        assert stats.min_confidence <= stats.mean_confidence <= stats.max_confidence
    
    def test_median_within_bounds(self):
        """Median should be between min and max."""
        scores = [0.1, 0.2, 0.5, 0.8, 0.9]
        stats = compute_confidence_stats(scores)
        
        assert stats.min_confidence <= stats.median_confidence <= stats.max_confidence
    
    def test_stdev_non_negative(self):
        """Standard deviation should never be negative."""
        scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
        stats = compute_confidence_stats(scores)
        
        assert stats.stdev_confidence >= 0.0
    
    def test_histogram_sum(self):
        """Sum of histogram counts should equal total."""
        scores = [0.1 * i for i in range(1, 11)]
        histogram = compute_confidence_histogram(scores, num_bins=5)
        
        assert sum(histogram.counts) == histogram.total


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

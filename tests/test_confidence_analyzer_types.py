"""Tests for confidence_analyzer type contracts.

This module tests the ConfidenceStatsDict, ConfidenceHistogramDict, and
ConfidenceReportDict TypedDict contracts to ensure proper type safety for
confidence analysis results.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.confidence_analyzer import (
    ConfidenceStats,
    ConfidenceStatsDict,
    ConfidenceHistogram,
    ConfidenceHistogramDict,
    ConfidenceReport,
    ConfidenceReportDict,
)


class TestConfidenceStatsDictType:
    """Tests for ConfidenceStatsDict TypedDict structure."""
    
    def test_confidence_stats_dict_has_correct_fields(self):
        """Verify ConfidenceStatsDict has expected field names."""
        expected_fields = {"min", "max", "mean", "median", "stdev", "count"}
        actual_fields = set(ConfidenceStatsDict.__annotations__.keys())
        assert actual_fields == expected_fields
    
    def test_confidence_stats_dict_field_types(self):
        """Verify ConfidenceStatsDict field types are correct."""
        annotations = ConfidenceStatsDict.__annotations__
        assert annotations["min"] == float
        assert annotations["max"] == float
        assert annotations["mean"] == float
        assert annotations["median"] == float
        assert annotations["stdev"] == float
        assert annotations["count"] == int
    
    def test_confidence_stats_dict_optional_fields(self):
        """Verify ConfidenceStatsDict allows partial population."""
        partial: ConfidenceStatsDict = {
            "min": 0.1,
            "max": 0.9,
            "count": 100
        }  # type: ignore
        assert partial["min"] == 0.1
        assert partial["max"] == 0.9
        assert partial["count"] == 100


class TestConfidenceHistogramDictType:
    """Tests for ConfidenceHistogramDict TypedDict structure."""
    
    def test_confidence_histogram_dict_has_correct_fields(self):
        """Verify ConfidenceHistogramDict has expected field names."""
        expected_fields = {"bins", "counts", "total"}
        actual_fields = set(ConfidenceHistogramDict.__annotations__.keys())
        assert actual_fields == expected_fields
    
    def test_confidence_histogram_dict_field_types(self):
        """Verify ConfidenceHistogramDict field types are correct."""
        annotations = ConfidenceHistogramDict.__annotations__
        # Note: List and Tuple types show as _GenericAlias in annotations
        assert "List" in str(annotations["bins"])
        assert "List" in str(annotations["counts"])
        assert annotations["total"] == int
    
    def test_confidence_histogram_dict_optional_fields(self):
        """Verify ConfidenceHistogramDict allows partial population."""
        partial: ConfidenceHistogramDict = {
            "total": 100
        }  # type: ignore
        assert partial["total"] == 100


class TestConfidenceReportDictType:
    """Tests for ConfidenceReportDict TypedDict structure."""
    
    def test_confidence_report_dict_has_correct_fields(self):
        """Verify ConfidenceReportDict has expected field names."""
        expected_fields = {
            "entity_stats", "entity_histogram", "low_confidence_threshold",
            "low_confidence_entities_count", "relationship_stats",
            "relationship_histogram", "low_confidence_relationships_count"
        }
        actual_fields = set(ConfidenceReportDict.__annotations__.keys())
        assert actual_fields == expected_fields
    
    def test_confidence_report_dict_nested_types(self):
        """Verify ConfidenceReportDict nested field types."""
        annotations = ConfidenceReportDict.__annotations__
        assert annotations["entity_stats"] == ConfidenceStatsDict
        assert annotations["entity_histogram"] == ConfidenceHistogramDict
        assert annotations["relationship_stats"] == ConfidenceStatsDict
        assert annotations["relationship_histogram"] == ConfidenceHistogramDict
    
    def test_confidence_report_dict_optional_relationship_fields(self):
        """Verify ConfidenceReportDict allows missing relationship fields."""
        partial: ConfidenceReportDict = {
            "low_confidence_threshold": 0.6,
            "low_confidence_entities_count": 10
        }  # type: ignore
        assert partial["low_confidence_threshold"] == 0.6


class TestConfidenceStatsIntegration:
    """Integration tests for ConfidenceStats.to_dict()."""
    
    def test_confidence_stats_to_dict_returns_typed_dict(self):
        """Verify ConfidenceStats.to_dict() returns ConfidenceStatsDict."""
        stats = ConfidenceStats(
            min_confidence=0.1,
            max_confidence=0.95,
            mean_confidence=0.75,
            median_confidence=0.8,
            stdev_confidence=0.15,
            count=100
        )
        
        result = stats.to_dict()
        
        # Verify structure matches ConfidenceStatsDict
        assert "min" in result
        assert "max" in result
        assert "mean" in result
        assert "median" in result
        assert "stdev" in result
        assert "count" in result
    
    def test_confidence_stats_to_dict_rounds_correctly(self):
        """Verify ConfidenceStats.to_dict() rounds floats to 4 decimals."""
        stats = ConfidenceStats(
            min_confidence=0.123456,
            max_confidence=0.987654,
            mean_confidence=0.555555,
            median_confidence=0.666666,
            stdev_confidence=0.111111,
            count=50
        )
        
        result = stats.to_dict()
        
        assert result["min"] == 0.1235
        assert result["max"] == 0.9877
        assert result["mean"] == 0.5556
        assert result["median"] == 0.6667
        assert result["stdev"] == 0.1111
        assert result["count"] == 50


class TestConfidenceHistogramIntegration:
    """Integration tests for ConfidenceHistogram.to_dict()."""
    
    def test_confidence_histogram_to_dict_returns_typed_dict(self):
        """Verify ConfidenceHistogram.to_dict() returns ConfidenceHistogramDict."""
        histogram = ConfidenceHistogram(
            bins=[(0.0, 0.2), (0.2, 0.4), (0.4, 0.6)],
            counts=[10, 20, 15],
            total=45
        )
        
        result = histogram.to_dict()
        
        assert "bins" in result
        assert "counts" in result
        assert "total" in result
        assert result["total"] == 45
    
    def test_confidence_histogram_to_dict_rounds_bins(self):
        """Verify ConfidenceHistogram.to_dict() rounds bin boundaries to 2 decimals."""
        histogram = ConfidenceHistogram(
            bins=[(0.123, 0.987), (0.555, 0.777)],
            counts=[5, 10],
            total=15
        )
        
        result = histogram.to_dict()
        
        assert result["bins"] == [(0.12, 0.99), (0.56, 0.78)]
        assert result["counts"] == [5, 10]


class TestConfidenceReportIntegration:
    """Integration tests for ConfidenceReport.to_dict()."""
    
    def test_confidence_report_to_dict_returns_typed_dict(self):
        """Verify ConfidenceReport.to_dict() returns ConfidenceReportDict."""
        entity_stats = ConfidenceStats(0.1, 0.9, 0.7, 0.75, 0.1, 100)
        entity_histogram = ConfidenceHistogram([(0.0, 1.0)], [100], 100)
        
        report = ConfidenceReport(
            entity_stats=entity_stats,
            entity_histogram=entity_histogram,
            low_confidence_threshold=0.6,
            low_confidence_entities=[("entity1", 0.4), ("entity2", 0.5)]
        )
        
        result = report.to_dict()
        
        assert "entity_stats" in result
        assert "entity_histogram" in result
        assert "low_confidence_threshold" in result
        assert "low_confidence_entities_count" in result
        assert result["low_confidence_threshold"] == 0.6
        assert result["low_confidence_entities_count"] == 2
    
    def test_confidence_report_with_relationships(self):
        """Verify ConfidenceReport.to_dict() includes relationship stats when present."""
        entity_stats = ConfidenceStats(0.1, 0.9, 0.7, 0.75, 0.1, 100)
        entity_histogram = ConfidenceHistogram([(0.0, 1.0)], [100], 100)
        relationship_stats = ConfidenceStats(0.2, 0.85, 0.65, 0.7, 0.12, 50)
        relationship_histogram = ConfidenceHistogram([(0.0, 1.0)], [50], 50)
        
        report = ConfidenceReport(
            entity_stats=entity_stats,
            entity_histogram=entity_histogram,
            relationship_stats=relationship_stats,
            relationship_histogram=relationship_histogram,
            low_confidence_threshold=0.6,
            low_confidence_entities=[],
            low_confidence_relationships=[("rel1", 0.3)]
        )
        
        result = report.to_dict()
        
        assert "relationship_stats" in result
        assert "relationship_histogram" in result
        assert "low_confidence_relationships_count" in result
        assert result["low_confidence_relationships_count"] == 1
    
    def test_confidence_report_without_relationships(self):
        """Verify ConfidenceReport.to_dict() omits relationship fields when absent."""
        entity_stats = ConfidenceStats(0.1, 0.9, 0.7, 0.75, 0.1, 100)
        entity_histogram = ConfidenceHistogram([(0.0, 1.0)], [100], 100)
        
        report = ConfidenceReport(
            entity_stats=entity_stats,
            entity_histogram=entity_histogram,
            low_confidence_threshold=0.6,
            low_confidence_entities=[]
        )
        
        result = report.to_dict()
        
        # When relationship_stats is None, fields should not be in result
        assert "relationship_stats" not in result
        assert "relationship_histogram" not in result
        assert "low_confidence_relationships_count" not in result


class TestConfidenceAnalyzerRealWorldScenarios:
    """Real-world usage scenarios for confidence analyzer types."""
    
    def test_high_confidence_scenario(self):
        """Test scenario with high confidence scores."""
        stats = ConfidenceStats(0.8, 1.0, 0.92, 0.91, 0.05, 200)
        result = stats.to_dict()
        
        assert result["min"] >= 0.8
        assert result["max"] == 1.0
        assert result["mean"] > 0.9
        assert result["stdev"] < 0.1
    
    def test_low_confidence_detection(self):
        """Test scenario identifying low confidence results."""
        entity_stats = ConfidenceStats(0.15, 0.6, 0.45, 0.48, 0.12, 50)
        entity_histogram = ConfidenceHistogram(
            bins=[(0.0, 0.3), (0.3, 0.6), (0.6, 1.0)],
            counts=[15, 30, 5],
            total=50
        )
        
        report = ConfidenceReport(
            entity_stats=entity_stats,
            entity_histogram=entity_histogram,
            low_confidence_threshold=0.6,
            low_confidence_entities=[
                ("entity1", 0.2),
                ("entity2", 0.3),
                ("entity3", 0.45)
            ]
        )
        
        result = report.to_dict()
        
        assert result["low_confidence_entities_count"] == 3
        assert result["entity_stats"]["mean"] < 0.5
    
    def test_mixed_confidence_with_relationships(self):
        """Test scenario with both entities and relationships."""
        entity_stats = ConfidenceStats(0.3, 0.95, 0.7, 0.72, 0.18, 100)
        entity_histogram = ConfidenceHistogram(
            bins=[(0.0, 0.5), (0.5, 1.0)],
            counts=[25, 75],
            total=100
        )
        relationship_stats = ConfidenceStats(0.4, 0.9, 0.68, 0.7, 0.15, 80)
        relationship_histogram = ConfidenceHistogram(
            bins=[(0.0, 0.5), (0.5, 1.0)],
            counts=[20, 60],
            total=80
        )
        
        report = ConfidenceReport(
            entity_stats=entity_stats,
            entity_histogram=entity_histogram,
            relationship_stats=relationship_stats,
            relationship_histogram=relationship_histogram,
            low_confidence_threshold=0.6,
            low_confidence_entities=[("ent1", 0.3)],
            low_confidence_relationships=[("rel1", 0.45), ("rel2", 0.55)]
        )
        
        result = report.to_dict()
        
        assert "entity_stats" in result
        assert "relationship_stats" in result
        assert result["low_confidence_entities_count"] == 1
        assert result["low_confidence_relationships_count"] == 2


class TestConfidenceStatsDictStructure:
    """Tests verifying ConfidenceStatsDict structure compliance."""
    
    def test_confidence_stats_dict_from_to_dict_matches_type(self):
        """Verify dict from to_dict() matches ConfidenceStatsDict structure."""
        stats = ConfidenceStats(0.1, 0.9, 0.5, 0.52, 0.2, 150)
        result = stats.to_dict()
        
        # Verify exact field set
        expected_fields = {"min", "max", "mean", "median", "stdev", "count"}
        assert set(result.keys()) == expected_fields
        
        # Verify types
        assert isinstance(result["min"], float)
        assert isinstance(result["max"], float)
        assert isinstance(result["mean"], float)
        assert isinstance(result["median"], float)
        assert isinstance(result["stdev"], float)
        assert isinstance(result["count"], int)
    
    def test_confidence_histogram_dict_from_to_dict_matches_type(self):
        """Verify dict from to_dict() matches ConfidenceHistogramDict structure."""
        histogram = ConfidenceHistogram(
            bins=[(0.0, 0.5), (0.5, 1.0)],
            counts=[30, 70],
            total=100
        )
        result = histogram.to_dict()
        
        # Verify exact field set
        expected_fields = {"bins", "counts", "total"}
        assert set(result.keys()) == expected_fields
        
        # Verify types
        assert isinstance(result["bins"], list)
        assert isinstance(result["counts"], list)
        assert isinstance(result["total"], int)
        
        # Verify bin structure
        for bin_tuple in result["bins"]:
            assert isinstance(bin_tuple, tuple)
            assert len(bin_tuple) == 2
            assert isinstance(bin_tuple[0], float)
            assert isinstance(bin_tuple[1], float)
    
    def test_confidence_report_dict_nested_structure(self):
        """Verify ConfidenceReportDict nested structure correctness."""
        entity_stats = ConfidenceStats(0.2, 0.95, 0.68, 0.7, 0.15, 120)
        entity_histogram = ConfidenceHistogram([(0.0, 1.0)], [120], 120)
        
        report = ConfidenceReport(
            entity_stats=entity_stats,
            entity_histogram=entity_histogram,
            low_confidence_threshold=0.6,
            low_confidence_entities=[("e1", 0.3), ("e2", 0.4)]
        )
        
        result = report.to_dict()
        
        # Verify top-level keys
        assert "entity_stats" in result
        assert "entity_histogram" in result
        assert "low_confidence_threshold" in result
        assert "low_confidence_entities_count" in result
        
        # Verify nested structures
        entity_stats_keys = {"min", "max", "mean", "median", "stdev", "count"}
        assert set(result["entity_stats"].keys()) == entity_stats_keys
        
        entity_histogram_keys = {"bins", "counts", "total"}
        assert set(result["entity_histogram"].keys()) == entity_histogram_keys

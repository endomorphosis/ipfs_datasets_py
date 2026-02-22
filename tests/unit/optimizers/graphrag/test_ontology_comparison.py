"""Unit tests for ontology comparison utilities.

Tests the compare_ontologies, compute_similarity, analyze_entity_distribution,
and other comparison functions.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_comparison import (
    compare_ontologies,
    compute_similarity,
    analyze_entity_distribution,
    analyze_relationship_distribution,
    find_entity_overlap,
    find_relationship_overlap,
    extract_type_distribution,
    format_comparison_result,
    ComparisonResult,
    DistributionStats,
)


class TestCompareOntologies:
    """Test the compare_ontologies function."""

    def test_identical_ontologies(self):
        """Test comparing two identical ontologies."""
        shared = {
            "entities": [{"id": "e1"}],
            "relationships": [{"id": "r1"}],
        }
        
        result = compare_ontologies(shared, shared)
        
        assert result.entity_similarity == 1.0
        assert result.relationship_similarity == 1.0
        assert result.overall_similarity == 1.0

    def test_completely_different_ontologies(self):
        """Test comparing completely different ontologies."""
        ont1 = {
            "entities": [{"id": "e1"}],
            "relationships": [{"id": "r1"}],
        }
        ont2 = {
            "entities": [{"id": "e2"}],
            "relationships": [{"id": "r2"}],
        }
        
        result = compare_ontologies(ont1, ont2)
        
        assert result.entity_similarity == 0.0
        assert result.relationship_similarity == 0.0
        assert result.overall_similarity == 0.0

    def test_partial_entity_overlap(self):
        """Test partial entity overlap."""
        ont1 = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [],
        }
        ont2 = {
            "entities": [{"id": "e2"}, {"id": "e3"}],
            "relationships": [],
        }
        
        result = compare_ontologies(ont1, ont2)
        
        assert result.entity_overlap == 1  # e2
        assert len(result.entity_only_left) == 1  # e1
        assert len(result.entity_only_right) == 1  # e3
        assert result.entity_similarity == pytest.approx(1.0 / 3.0)  # 1 shared, 3 total

    def test_empty_ontologies(self):
        """Test comparing two empty ontologies."""
        onto_empty = {"entities": [], "relationships": []}
        
        result = compare_ontologies(onto_empty, onto_empty)
        
        assert result.entity_similarity == 1.0
        assert result.relationship_similarity == 1.0

    def test_one_empty_one_full(self):
        """Test comparing empty with non-empty ontology."""
        onto_empty = {"entities": [], "relationships": []}
        onto_full = {
            "entities": [{"id": "e1"}],
            "relationships": [{"id": "r1"}],
        }
        
        result = compare_ontologies(onto_empty, onto_full)
        
        assert result.entity_similarity == 0.0
        assert result.relationship_similarity == 0.0

    def test_overlap_counts(self):
        """Test that overlap counts are accurate."""
        ont1 = {
            "entities": [
                {"id": "e1"},
                {"id": "e2"},
                {"id": "e3"},
                {"id": "e4"},
            ],
            "relationships": [],
        }
        ont2 = {
            "entities": [
                {"id": "e2"},
                {"id": "e3"},
                {"id": "e5"},
                {"id": "e6"},
            ],
            "relationships": [],
        }
        
        result = compare_ontologies(ont1, ont2)
        
        assert result.entity_overlap == 2  # e2, e3
        assert len(result.entity_only_left) == 2  # e1, e4
        assert len(result.entity_only_right) == 2  # e5, e6


class TestComputeSimilarity:
    """Test the compute_similarity function."""

    def test_identical_similarity(self):
        """Test similarity of identical ontologies."""
        onto = {
            "entities": [{"id": "e1"}],
            "relationships": [{"id": "r1"}],
        }
        
        similarity = compute_similarity(onto, onto)
        
        assert similarity == 1.0

    def test_different_similarity(self):
        """Test similarity returns a float between 0 and 1."""
        ont1 = {"entities": [{"id": "e1"}], "relationships": []}
        ont2 = {"entities": [{"id": "e2"}], "relationships": []}
        
        similarity = compute_similarity(ont1, ont2)
        
        assert 0.0 <= similarity <= 1.0

    def test_empty_similarity(self):
        """Test similarity of empty ontologies."""
        onto = {"entities": [], "relationships": []}
        
        similarity = compute_similarity(onto, onto)
        
        assert similarity == 1.0


class TestAnalyzeEntityDistribution:
    """Test the analyze_entity_distribution function."""

    def test_empty_entities(self):
        """Test distribution with no entities."""
        ontology = {"entities": []}
        
        stats = analyze_entity_distribution(ontology)
        
        assert stats.total_items == 0
        assert stats.unique_types == 0
        assert stats.dominant_type == ""

    def test_single_type(self):
        """Test distribution with single entity type."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
                {"id": "e3", "type": "Person"},
            ]
        }
        
        stats = analyze_entity_distribution(ontology)
        
        assert stats.total_items == 3
        assert stats.unique_types == 1
        assert stats.dominant_type == "Person"
        assert stats.dominant_type_percentage == 100.0

    def test_multiple_types(self):
        """Test distribution with multiple entity types."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
                {"id": "e3", "type": "Location"},
                {"id": "e4", "type": "Organization"},
            ]
        }
        
        stats = analyze_entity_distribution(ontology)
        
        assert stats.total_items == 4
        assert stats.unique_types == 3
        assert stats.dominant_type == "Person"
        assert stats.type_counts["Person"] == 2
        assert stats.type_counts["Location"] == 1
        assert stats.type_counts["Organization"] == 1

    def test_dominant_percentage(self):
        """Test dominant type percentage calculation."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "A"},
                {"id": "e2", "type": "A"},
                {"id": "e3", "type": "B"},
            ]
        }
        
        stats = analyze_entity_distribution(ontology)
        
        assert stats.dominant_type_percentage == pytest.approx(66.666666667, rel=0.01)


class TestAnalyzeRelationshipDistribution:
    """Test the analyze_relationship_distribution function."""

    def test_empty_relationships(self):
        """Test distribution with no relationships."""
        ontology = {"relationships": []}
        
        stats = analyze_relationship_distribution(ontology)
        
        assert stats.total_items == 0
        assert stats.unique_types == 0

    def test_relationship_types(self):
        """Test distribution over multiple relationship types."""
        ontology = {
            "relationships": [
                {"id": "r1", "type": "knows"},
                {"id": "r2", "type": "knows"},
                {"id": "r3", "type": "works_at"},
            ]
        }
        
        stats = analyze_relationship_distribution(ontology)
        
        assert stats.total_items == 3
        assert stats.unique_types == 2
        assert stats.type_counts["knows"] == 2
        assert stats.type_counts["works_at"] == 1
        assert stats.dominant_type == "knows"


class TestFindEntityOverlap:
    """Test the find_entity_overlap function."""

    def test_complete_overlap(self):
        """Test complete entity overlap."""
        ont = {"entities": [{"id": "e1"}, {"id": "e2"}]}
        
        overlap = find_entity_overlap(ont, ont)
        
        assert sorted(overlap) == ["e1", "e2"]

    def test_no_overlap(self):
        """Test no entity overlap."""
        ont1 = {"entities": [{"id": "e1"}]}
        ont2 = {"entities": [{"id": "e2"}]}
        
        overlap = find_entity_overlap(ont1, ont2)
        
        assert len(overlap) == 0

    def test_partial_overlap(self):
        """Test partial entity overlap."""
        ont1 = {"entities": [{"id": "e1"}, {"id": "e2"}]}
        ont2 = {"entities": [{"id": "e2"}, {"id": "e3"}]}
        
        overlap = find_entity_overlap(ont1, ont2)
        
        assert overlap == ["e2"]


class TestFindRelationshipOverlap:
    """Test the find_relationship_overlap function."""

    def test_complete_overlap(self):
        """Test complete relationship overlap."""
        ont = {"relationships": [{"id": "r1"}, {"id": "r2"}]}
        
        overlap = find_relationship_overlap(ont, ont)
        
        assert sorted(overlap) == ["r1", "r2"]

    def test_no_overlap(self):
        """Test no relationship overlap."""
        ont1 = {"relationships": [{"id": "r1"}]}
        ont2 = {"relationships": [{"id": "r2"}]}
        
        overlap = find_relationship_overlap(ont1, ont2)
        
        assert len(overlap) == 0

    def test_partial_overlap(self):
        """Test partial relationship overlap."""
        ont1 = {"relationships": [{"id": "r1"}, {"id": "r2"}]}
        ont2 = {"relationships": [{"id": "r2"}, {"id": "r3"}]}
        
        overlap = find_relationship_overlap(ont1, ont2)
        
        assert overlap == ["r2"]


class TestExtractTypeDistribution:
    """Test the extract_type_distribution function."""

    def test_empty_list(self):
        """Test with empty list."""
        distribution = extract_type_distribution([])
        
        assert len(distribution) == 0

    def test_single_type(self):
        """Test with single type."""
        items = [{"type": "A"}, {"type": "A"}, {"type": "A"}]
        
        distribution = extract_type_distribution(items)
        
        assert distribution == {"A": 3}

    def test_multiple_types(self):
        """Test with multiple types."""
        items = [
            {"type": "A"},
            {"type": "B"},
            {"type": "A"},
            {"type": "C"},
            {"type": "B"},
        ]
        
        distribution = extract_type_distribution(items)
        
        assert distribution == {"A": 2, "B": 2, "C": 1}

    def test_items_without_type(self):
        """Test that items without type field are ignored."""
        items = [{"type": "A"}, {"id": "e1"}, {"type": "A"}]
        
        distribution = extract_type_distribution(items)
        
        assert distribution == {"A": 2}


class TestComparisonResult:
    """Test the ComparisonResult dataclass."""

    def test_overall_similarity_empty(self):
        """Test overall similarity with 0 values."""
        result = ComparisonResult(
            entity_similarity=0.0,
            relationship_similarity=0.0,
        )
        
        assert result.overall_similarity == 0.0

    def test_overall_similarity_perfect(self):
        """Test overall similarity with 1.0 values."""
        result = ComparisonResult(
            entity_similarity=1.0,
            relationship_similarity=1.0,
        )
        
        assert result.overall_similarity == 1.0

    def test_overall_similarity_average(self):
        """Test overall similarity averaging."""
        result = ComparisonResult(
            entity_similarity=0.8,
            relationship_similarity=0.6,
        )
        
        assert result.overall_similarity == pytest.approx(0.7)

    def test_total_entities_union(self):
        """Test total entities union property."""
        result = ComparisonResult(
            entity_overlap=5,
            entity_only_left=["e1", "e2"],
            entity_only_right=["e3"],
        )
        
        assert result.total_entities_union == 8

    def test_total_relationships_union(self):
        """Test total relationships union property."""
        result = ComparisonResult(
            relationship_overlap=3,
            rel_only_left=["r1", "r2", "r3"],
            rel_only_right=["r4", "r5"],
        )
        
        # 3 overlap + 3 left + 2 right = 8
        assert result.total_relationships_union == 8

    def test_repr(self):
        """Test __repr__ method."""
        result = ComparisonResult(
            entity_overlap=5,
            relationship_overlap=3,
            entity_similarity=0.8,
            relationship_similarity=0.6,
        )
        repr_str = repr(result)
        
        assert "ComparisonResult" in repr_str
        assert "entity_overlap=5" in repr_str
        assert "rel_overlap=3" in repr_str


class TestDistributionStats:
    """Test the DistributionStats dataclass."""

    def test_empty_stats(self):
        """Test stats with no items."""
        stats = DistributionStats()
        
        assert stats.total_items == 0
        assert stats.unique_types == 0
        assert stats.dominant_type == ""
        assert stats.dominant_type_percentage == 0.0

    def test_dominant_type(self):
        """Test dominant type selection."""
        stats = DistributionStats(
            type_counts={"A": 5, "B": 3, "C": 2},
            total_items=10,
        )
        
        assert stats.dominant_type == "A"

    def test_dominant_percentage(self):
        """Test dominant type percentage."""
        stats = DistributionStats(
            type_counts={"A": 7, "B": 3},
            total_items=10,
        )
        
        assert stats.dominant_type_percentage == 70.0

    def test_unique_types(self):
        """Test unique types property."""
        stats = DistributionStats(
            type_counts={"A": 5, "B": 3, "C": 2},
        )
        
        assert stats.unique_types == 3

    def test_repr(self):
        """Test __repr__ method."""
        stats = DistributionStats(
            type_counts={"A": 7, "B": 3},
            total_items=10,
        )
        repr_str = repr(stats)
        
        assert "DistributionStats" in repr_str
        assert "total=10" in repr_str
        assert "types=2" in repr_str


class TestFormatComparisonResult:
    """Test the format_comparison_result function."""

    def test_format_summary(self):
        """Test summary formatting."""
        result = ComparisonResult(
            entity_overlap=5,
            relationship_overlap=3,
            entity_similarity=0.8,
            relationship_similarity=0.6,
        )
        formatted = format_comparison_result(result, verbose=False)
        
        assert "Ontology Comparison" in formatted
        assert "70.0%" in formatted  # Overall similarity

    def test_format_verbose(self):
        """Test verbose formatting."""
        result = ComparisonResult(
            entity_overlap=2,
            relationship_overlap=1,
            entity_similarity=0.5,
            relationship_similarity=0.5,
            entity_only_left=["e1", "e2"],
            entity_only_right=["e3"],
        )
        formatted = format_comparison_result(result, verbose=True)
        
        assert "Only in Left" in formatted
        assert "Only in Right" in formatted

    def test_format_perfect_match(self):
        """Test formatting of perfect match."""
        result = ComparisonResult(
            entity_similarity=1.0,
            relationship_similarity=1.0,
        )
        formatted = format_comparison_result(result)
        
        assert "100.0%" in formatted


class TestEdgeCases:
    """Test edge cases."""

    def test_comparison_with_missing_keys(self):
        """Test comparison with ontologies missing keys."""
        ont1 = {"entities": [{"id": "e1"}]}  # Missing relationships
        ont2 = {"entities": [{"id": "e1"}], "relationships": []}
        
        result = compare_ontologies(ont1, ont2)
        
        assert result.entity_similarity == 1.0
        assert result.relationship_similarity == 1.0

    def test_distribution_with_non_dict_items(self):
        """Test distribution with invalid items."""
        items = [{"type": "A"}, "invalid", {"type": "B"}]
        
        distribution = extract_type_distribution(items)
        
        assert distribution == {"A": 1, "B": 1}

    def test_large_ontology_comparison(self):
        """Test comparison of large ontologies."""
        entities_left = [{"id": f"e{i}"} for i in range(1000)]
        entities_right = [{"id": f"e{i}"} for i in range(500, 1500)]
        
        ont1 = {"entities": entities_left, "relationships": []}
        ont2 = {"entities": entities_right, "relationships": []}
        
        result = compare_ontologies(ont1, ont2)
        
        # 500 shared entities, 1500 total
        assert result.entity_similarity == pytest.approx(500 / 1500)

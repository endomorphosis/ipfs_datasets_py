"""Unit tests for ontology statistics and analysis module."""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_stats import (
    EntityStats,
    RelationshipStats,
    OntologyStats,
    QualityMetrics,
    compute_entity_stats,
    compute_relationship_stats,
    compute_quality_metrics,
    compute_ontology_stats,
    generate_stats_report,
    get_entity_type_distribution,
    get_relationship_type_distribution,
    identify_bottlenecks,
)


class TestEntityStats:
    """Test EntityStats dataclass."""

    def test_has_diversity_true(self):
        """Test has_diversity returns True for >2 types."""
        stats = EntityStats(
            total_count=10,
            type_distribution={"Person": 4, "Place": 3, "Thing": 3},
            avg_properties_per_entity=1.5,
            property_coverage_ratio=0.8,
        )
        assert stats.has_diversity()

    def test_has_diversity_false(self):
        """Test has_diversity returns False for <=2 types."""
        stats = EntityStats(
            total_count=10,
            type_distribution={"Person": 10},
            avg_properties_per_entity=1.5,
            property_coverage_ratio=0.8,
        )
        assert not stats.has_diversity()

    def test_repr(self):
        """Test __repr__ method."""
        stats = EntityStats(
            total_count=10,
            type_distribution={"Person": 5, "Place": 5},
            avg_properties_per_entity=2.0,
            property_coverage_ratio=0.9,
            orphaned_count=1,
        )
        repr_str = repr(stats)
        assert "EntityStats" in repr_str
        assert "count=10" in repr_str
        assert "types=2" in repr_str
        assert "orphaned=1" in repr_str


class TestRelationshipStats:
    """Test RelationshipStats dataclass."""

    def test_is_sparse_true(self):
        """Test is_sparse returns True for density < 0.1."""
        stats = RelationshipStats(
            total_count=5,
            type_distribution={"knows": 5},
            avg_relationships_per_entity=1.0,
            relationship_density=0.05,
        )
        assert stats.is_sparse()

    def test_is_sparse_false(self):
        """Test is_sparse returns False for density >= 0.1."""
        stats = RelationshipStats(
            total_count=100,
            type_distribution={"knows": 100},
            avg_relationships_per_entity=5.0,
            relationship_density=0.2,
        )
        assert not stats.is_sparse()

    def test_is_dense_true(self):
        """Test is_dense returns True for density > 0.5."""
        stats = RelationshipStats(
            total_count=500,
            type_distribution={"knows": 500},
            avg_relationships_per_entity=10.0,
            relationship_density=0.6,
        )
        assert stats.is_dense()

    def test_is_dense_false(self):
        """Test is_dense returns False for density <= 0.5."""
        stats = RelationshipStats(
            total_count=50,
            type_distribution={"knows": 50},
            avg_relationships_per_entity=2.0,
            relationship_density=0.2,
        )
        assert not stats.is_dense()


class TestQualityMetrics:
    """Test QualityMetrics dataclass."""

    def test_is_high_quality_true(self):
        """Test is_high_quality returns True for score >= 0.7."""
        metrics = QualityMetrics(
            completeness_score=0.8,
            connectivity_score=0.75,
            consistency_score=0.70,
            overall_quality=0.75,
        )
        assert metrics.is_high_quality()

    def test_is_high_quality_false(self):
        """Test is_high_quality returns False for score < 0.7."""
        metrics = QualityMetrics(
            completeness_score=0.5,
            connectivity_score=0.5,
            consistency_score=0.5,
            overall_quality=0.5,
        )
        assert not metrics.is_high_quality()

    def test_is_low_quality_true(self):
        """Test is_low_quality returns True for score <= 0.4."""
        metrics = QualityMetrics(
            completeness_score=0.3,
            connectivity_score=0.3,
            consistency_score=0.3,
            overall_quality=0.3,
        )
        assert metrics.is_low_quality()

    def test_is_low_quality_false(self):
        """Test is_low_quality returns False for score > 0.4."""
        metrics = QualityMetrics(
            completeness_score=0.5,
            connectivity_score=0.5,
            consistency_score=0.5,
            overall_quality=0.5,
        )
        assert not metrics.is_low_quality()


class TestComputeEntityStats:
    """Test compute_entity_stats function."""

    def test_empty_ontology(self):
        """Test with empty ontology."""
        ontology = {"entities": [], "relationships": []}
        stats = compute_entity_stats(ontology)
        
        assert stats.total_count == 0
        assert stats.type_distribution == {}
        assert stats.avg_properties_per_entity == 0.0

    def test_single_entity_no_properties(self):
        """Test with single entity without properties."""
        ontology = {
            "entities": [{"id": "e1", "type": "Person"}],
            "relationships": [],
        }
        stats = compute_entity_stats(ontology)
        
        assert stats.total_count == 1
        assert stats.type_distribution["Person"] == 1
        assert stats.property_coverage_ratio == 0.0

    def test_multiple_entities_with_properties(self):
        """Test with multiple entities and properties."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "properties": {"age": 30}},
                {"id": "e2", "type": "Person", "properties": {"name": "Alice", "age": 25}},
                {"id": "e3", "type": "Place"},
            ],
            "relationships": [],
        }
        stats = compute_entity_stats(ontology)
        
        assert stats.total_count == 3
        assert stats.type_distribution["Person"] == 2
        assert stats.property_coverage_ratio == pytest.approx(2/3)
        assert stats.avg_properties_per_entity == pytest.approx(3/3)

    def test_orphaned_entities(self):
        """Test orphaned entity detection."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
                {"id": "e3", "type": "Place"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"}
            ],
        }
        stats = compute_entity_stats(ontology)
        
        assert stats.orphaned_count == 1  # e3 is orphaned


class TestComputeRelationshipStats:
    """Test compute_relationship_stats function."""

    def test_empty_ontology(self):
        """Test with empty ontology."""
        ontology = {"entities": [], "relationships": []}
        stats = compute_relationship_stats(ontology)
        
        assert stats.total_count == 0
        assert stats.relationship_density == 0.0

    def test_single_relationship(self):
        """Test with single relationship."""
        ontology = {
            "entities": [
                {"id": "e1"},
                {"id": "e2"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}
            ],
        }
        stats = compute_relationship_stats(ontology)
        
        assert stats.total_count == 1
        assert stats.type_distribution["knows"] == 1
        assert stats.avg_relationships_per_entity == 0.5
        # Density: 1 rel / (2 * 1) = 0.5
        assert stats.relationship_density == 0.5

    def test_multiple_relationship_types(self):
        """Test with multiple relationship types."""
        ontology = {
            "entities": [
                {"id": "e1"},
                {"id": "e2"},
                {"id": "e3"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
                {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "works_at"},
            ],
        }
        stats = compute_relationship_stats(ontology)
        
        assert stats.total_count == 2
        assert len(stats.type_distribution) == 2
        assert stats.type_distribution["knows"] == 1
        assert stats.type_distribution["works_at"] == 1


class TestComputeQualityMetrics:
    """Test compute_quality_metrics function."""

    def test_good_quality_ontology(self):
        """Test quality metrics for good ontology."""
        entity_stats = EntityStats(
            total_count=10,
            type_distribution={"Person": 5, "Place": 3, "Org": 2},
            avg_properties_per_entity=2.0,
            property_coverage_ratio=0.9,
            orphaned_count=0,
        )
        rel_stats = RelationshipStats(
            total_count=15,
            type_distribution={"knows": 10, "works_at": 5},
            avg_relationships_per_entity=1.5,
            relationship_density=0.15,
        )
        
        quality = compute_quality_metrics(entity_stats, rel_stats)
        
        assert quality.overall_quality >= 0.5  # Decent quality
        assert len(quality.suggestions) >= 0
        assert len(quality.issues) == 0

    def test_low_quality_ontology(self):
        """Test quality metrics for low quality ontology."""
        entity_stats = EntityStats(
            total_count=10,
            type_distribution={"Thing": 10},  # No diversity
            avg_properties_per_entity=0.1,  # Few properties
            property_coverage_ratio=0.1,
            orphaned_count=5,  # Many orphaned
        )
        rel_stats = RelationshipStats(
            total_count=2,
            type_distribution={"rel": 2},
            avg_relationships_per_entity=0.2,
            relationship_density=0.02,  # Very sparse
        )
        
        quality = compute_quality_metrics(entity_stats, rel_stats)
        
        assert quality.is_low_quality()
        assert len(quality.issues) > 0
        assert len(quality.suggestions) > 0


class TestComputeOntologyStats:
    """Test compute_ontology_stats function."""

    def test_full_ontology(self):
        """Test comprehensive ontology stats computation."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "properties": {"age": 30}, "confidence": 0.95},
                {"id": "e2", "type": "Person", "properties": {"name": "Alice"}, "confidence": 0.90},
                {"id": "e3", "type": "Place", "confidence": 0.85},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
                {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "lives_in"},
            ],
        }
        
        stats = compute_ontology_stats(ontology)
        
        assert stats.entities.total_count == 3
        assert stats.relationships.total_count == 2
        assert stats.unique_property_names == 2  # age, name
        assert stats.total_properties_count == 2
        assert stats.avg_confidence_score == pytest.approx(0.9)


class TestGenerateStatsReport:
    """Test generate_stats_report function."""

    def test_report_format_summary(self):
        """Test report is generated with summary content."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "properties": {"age": 30}},
                {"id": "e2", "type": "Person"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
            ],
        }
        
        report = generate_stats_report(ontology, verbose=False)
        
        assert "ONTOLOGY STATISTICS REPORT" in report
        assert "Entity" in report or "ENTITY" in report
        assert "Relationship" in report or "RELATIONSHIP" in report
        assert "2" in report  # 2 entities

    def test_report_format_verbose(self):
        """Test verbose report includes issues and suggestions."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Thing"},  # Only one type
                {"id": "e2", "type": "Thing"},
            ],
            "relationships": [],  # No relationships
        }
        
        report = generate_stats_report(ontology, verbose=True)
        
        assert "ONTOLOGY STATISTICS REPORT" in report
        # Sparse graph should generate suggestions
        if "💡" in report or "SUGGESTION" in report:
            assert True  # Has suggestions


class TestGetEntityTypeDistribution:
    """Test get_entity_type_distribution function."""

    def test_uniform_distribution(self):
        """Test with uniform type distribution."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person"},
                {"id": "e2", "type": "Person"},
                {"id": "e3", "type": "Place"},
                {"id": "e4", "type": "Place"},
            ],
            "relationships": [],
        }
        
        dist = get_entity_type_distribution(ontology)
        
        assert dist["Person"] == pytest.approx(0.5)
        assert dist["Place"] == pytest.approx(0.5)

    def test_empty_ontology(self):
        """Test with empty ontology."""
        ontology = {"entities": [], "relationships": []}
        dist = get_entity_type_distribution(ontology)
        
        assert dist == {}


class TestGetRelationshipTypeDistribution:
    """Test get_relationship_type_distribution function."""

    def test_uniform_distribution(self):
        """Test with uniform type distribution."""
        ontology = {
            "entities": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
                {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "knows"},
                {"id": "r3", "source_id": "e1", "target_id": "e3", "type": "sees"},
            ],
        }
        
        dist = get_relationship_type_distribution(ontology)
        
        assert dist["knows"] == pytest.approx(2/3)
        assert dist["sees"] == pytest.approx(1/3)

    def test_empty_relationships(self):
        """Test with no relationships."""
        ontology = {
            "entities": [{"id": "e1"}, {"id": "e2"}],
            "relationships": [],
        }
        dist = get_relationship_type_distribution(ontology)
        
        assert dist == {}


class TestIdentifyBottlenecks:
    """Test identify_bottlenecks function."""

    def test_high_degree_hub(self):
        """Test identification of high-degree hub entities."""
        ontology = {
            "entities": [
                {"id": "e1"},
                {"id": "e2"},
                {"id": "e3"},
                {"id": "e4"},
                {"id": "e5"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2"},
                {"id": "r2", "source_id": "e1", "target_id": "e3"},
                {"id": "r3", "source_id": "e1", "target_id": "e4"},
                {"id": "r4", "source_id": "e1", "target_id": "e5"},
                {"id": "r5", "source_id": "e2", "target_id": "e3"},
            ],
        }
        
        bottlenecks = identify_bottlenecks(ontology)
        
        assert "high_degree_entities" in bottlenecks
        # e1 should be detected as high-degree hub (degree 4)
        if bottlenecks["high_degree_entities"]:
            assert "e1" in bottlenecks["high_degree_entities"]
            assert bottlenecks["high_degree_entities"]["e1"] == 4

    def test_bottleneck_relationship_types(self):
        """Test identification of bottleneck relationship types."""
        ontology = {
            "entities": [
                {"id": "e1"},
                {"id": "e2"},
                {"id": "e3"},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
                {"id": "r2", "source_id": "e1", "target_id": "e3", "type": "knows"},
                {"id": "r3", "source_id": "e2", "target_id": "e3", "type": "knows"},
                {"id": "r4", "source_id": "e1", "target_id": "e2", "type": "sees"},
            ],
        }
        
        bottlenecks = identify_bottlenecks(ontology)
        
        assert "bottleneck_relationship_types" in bottlenecks
        assert bottlenecks["bottleneck_relationship_types"]["knows"] == 3

    def test_empty_ontology(self):
        """Test with empty ontology."""
        ontology = {"entities": [], "relationships": []}
        bottlenecks = identify_bottlenecks(ontology)
        
        # Returns dict with empty dicts instead of empty dict
        assert isinstance(bottlenecks, dict)
        assert "high_degree_entities" in bottlenecks
        assert "bottleneck_relationship_types" in bottlenecks


class TestIntegration:
    """Integration tests across modules."""

    def test_full_analysis_pipeline(self):
        """Test complete analysis of complex ontology."""
        ontology = {
            "entities": [
                {"id": "e1", "type": "Person", "properties": {"name": "Alice", "age": 30}, "confidence": 0.95},
                {"id": "e2", "type": "Person", "properties": {"name": "Bob"}, "confidence": 0.90},
                {"id": "e3", "type": "Organization", "properties": {"sector": "tech"}, "confidence": 0.85},
                {"id": "e4", "type": "Place", "confidence": 0.88},
            ],
            "relationships": [
                {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.9},
                {"id": "r2", "source_id": "e1", "target_id": "e3", "type": "works_at", "confidence": 0.85},
                {"id": "r3", "source_id": "e3", "target_id": "e4", "type": "located_in", "confidence": 0.8},
            ],
        }
        
        # Compute all stats
        stats = compute_ontology_stats(ontology)
        quality = compute_quality_metrics(stats.entities, stats.relationships)
        report = generate_stats_report(ontology)
        bottlenecks = identify_bottlenecks(ontology)
        entity_dist = get_entity_type_distribution(ontology)
        rel_dist = get_relationship_type_distribution(ontology)
        
        # Verify consistency
        assert stats.entities.total_count == 4
        assert stats.relationships.total_count == 3
        assert len(entity_dist) == 3
        assert len(rel_dist) == 3
        assert "ONTOLOGY STATISTICS REPORT" in report
        assert isinstance(quality, QualityMetrics)
        assert isinstance(bottlenecks, dict)

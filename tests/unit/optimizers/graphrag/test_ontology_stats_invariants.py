"""Advanced property-based tests for ontology stats invariants.

These tests use Hypothesis to generate random ontologies and verify mathematical
invariants that should always hold, such as:
- Count bounds and non-negativity
- Percentage/ratio bounds (0.0-1.0)
- Determinism (same input = same output)
- Monotonicity under merges/additions
- Consistency between related metrics
"""

import pytest
from hypothesis import given, assume, strategies as st, settings, HealthCheck
from typing import Dict, List, Any

from ipfs_datasets_py.optimizers.graphrag.ontology_stats import (
    compute_entity_stats,
    compute_relationship_stats,
    compute_quality_metrics,
    compute_ontology_stats,
    EntityStats,
    RelationshipStats,
    QualityMetrics,
)


# Hypothesis strategies for generating ontologies
@st.composite
def random_entity(draw, entity_id_pool=None):
    """Generate a random entity DICT (not Entity dataclass)."""
    if entity_id_pool is None:
        ent_id = f"e{draw(st.integers(min_value=1, max_value=10000))}"
    else:
        ent_id = draw(st.sampled_from(entity_id_pool))
    
    entity_type = draw(st.sampled_from(["Person", "Organization", "Location", "Event", "Concept", "Product"]))
    text = draw(st.text(min_size=1, max_size=30, alphabet=st.characters(blacklist_characters="\x00\n\r")))
    
    # Generate properties with varying complexity
    num_properties = draw(st.integers(min_value=0, max_value=5))
    properties = {}
    for i in range(num_properties):
        key = f"prop_{i}"
        value = draw(st.one_of(
            st.text(max_size=20),
            st.integers(min_value=0, max_value=1000),
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        ))
        properties[key] = value
    
    confidence = draw(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    
    return {
        "id": ent_id,
        "type": entity_type,
        "text": text,
        "properties": properties,
        "confidence": confidence,
    }


@st.composite
def random_relationship(draw, entity_ids):
    """Generate a random relationship DICT between existing entities."""
    if len(entity_ids) < 2:
        return None
    
    source_id = draw(st.sampled_from(entity_ids))
    target_id = draw(st.sampled_from(entity_ids))
    
    # Allow self-loops in some cases
    rel_type = draw(st.sampled_from(["works_for", "located_in", "caused_by", "related_to", "owns", "mentions"]))
    rel_id = f"r{draw(st.integers(min_value=1, max_value=100000))}"
    
    return {
        "id": rel_id,
        "source_id": source_id,
        "target_id": target_id,
        "type": rel_type,
    }


@st.composite
def random_ontology(draw):
    """Generate a random ontology dictionary."""
    num_entities = draw(st.integers(min_value=0, max_value=30))
    entities = [draw(random_entity()) for _ in range(num_entities)]
    
    entity_ids = [e["id"] for e in entities]
    
    if len(entity_ids) >= 2:
        num_relationships = draw(st.integers(min_value=0, max_value=min(50, len(entity_ids) * 3)))
        relationships = []
        for _ in range(num_relationships):
            rel = draw(random_relationship(entity_ids))
            if rel is not None:
                relationships.append(rel)
    else:
        relationships = []
    
    return {
        "entities": entities,
        "relationships": relationships,
    }


class TestEntityStatsInvariants:
    """Test mathematical invariants for entity statistics."""
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_total_count_matches_entity_list_length(self, ontology):
        """Entity count should exactly match length of entities list."""
        stats = compute_entity_stats(ontology)
        assert stats.total_count == len(ontology.get("entities", []))
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_orphan_count_at_most_total_count(self, ontology):
        """Orphaned entities <= total entities."""
        stats = compute_entity_stats(ontology)
        assert 0 <= stats.orphaned_count <= stats.total_count
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_property_coverage_between_zero_and_one(self, ontology):
        """Property coverage ratio must be in [0.0, 1.0]."""
        stats = compute_entity_stats(ontology)
        assert 0.0 <= stats.property_coverage_ratio <= 1.0
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_avg_properties_non_negative(self, ontology):
        """Average properties per entity cannot be negative."""
        stats = compute_entity_stats(ontology)
        assert stats.avg_properties_per_entity >= 0.0
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_type_distribution_sum_at_most_total(self, ontology):
        """Sum of type distribution values <= total (some entities might lack types)."""
        stats = compute_entity_stats(ontology)
        type_sum = sum(stats.type_distribution.values())
        assert type_sum <= stats.total_count
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_determinism(self, ontology):
        """Computing stats twice on same ontology gives identical results."""
        stats1 = compute_entity_stats(ontology)
        stats2 = compute_entity_stats(ontology)
        
        assert stats1.total_count == stats2.total_count
        assert stats1.type_distribution == stats2.type_distribution
        assert stats1.avg_properties_per_entity == stats2.avg_properties_per_entity
        assert stats1.property_coverage_ratio == stats2.property_coverage_ratio
        assert stats1.orphaned_count == stats2.orphaned_count


class TestRelationshipStatsInvariants:
    """Test mathematical invariants for relationship statistics."""
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_total_count_matches_relationship_list_length(self, ontology):
        """Relationship count should exactly match length of relationships list."""
        stats = compute_relationship_stats(ontology)
        assert stats.total_count == len(ontology.get("relationships", []))
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_density_between_zero_and_one(self, ontology):
        """Relationship density must be in [0.0, 1.0]."""
        stats = compute_relationship_stats(ontology)
        assert 0.0 <= stats.relationship_density <= 1.0
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_avg_relationships_non_negative(self, ontology):
        """Average relationships per entity cannot be negative."""
        stats = compute_relationship_stats(ontology)
        assert stats.avg_relationships_per_entity >= 0.0
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_type_distribution_sum_at_most_total(self, ontology):
        """Sum of rel type distribution values <= total (some rels might lack types)."""
        stats = compute_relationship_stats(ontology)
        type_sum = sum(stats.type_distribution.values())
        assert type_sum <= stats.total_count
    
    @given(random_ontology())
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    def test_determinism(self, ontology):
        """Computing stats twice on same ontology gives identical results."""
        stats1 = compute_relationship_stats(ontology)
        stats2 = compute_relationship_stats(ontology)
        
        assert stats1.total_count == stats2.total_count
        assert stats1.type_distribution == stats2.type_distribution
        assert stats1.avg_relationships_per_entity == stats2.avg_relationships_per_entity
        assert stats1.relationship_density == stats2.relationship_density


class TestQualityMetricsInvariants:
    """Test invariants for quality assessment metrics."""
    
    @given(random_ontology())
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_all_scores_between_zero_and_one(self, ontology):
        """All quality scores must be in [0.0, 1.0]."""
        entity_stats = compute_entity_stats(ontology)
        rel_stats = compute_relationship_stats(ontology)
        quality = compute_quality_metrics(entity_stats, rel_stats)
        
        assert 0.0 <= quality.completeness_score <= 1.0
        assert 0.0 <= quality.connectivity_score <= 1.0
        assert 0.0 <= quality.consistency_score <= 1.0
        assert 0.0 <= quality.overall_quality <= 1.0
    
    @given(random_ontology())
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_overall_quality_is_weighted_average(self, ontology):
        """Overall quality should be weighted average of components (within rounding)."""
        entity_stats = compute_entity_stats(ontology)
        rel_stats = compute_relationship_stats(ontology)
        quality = compute_quality_metrics(entity_stats, rel_stats)
        
        # Weighted formula: 0.3*completeness + 0.4*connectivity + 0.3*consistency
        expected = (
            0.3 * min(1.0, quality.completeness_score)
            + 0.4 * min(1.0, quality.connectivity_score)
            + 0.3 * min(1.0, quality.consistency_score)
        )
        expected = min(1.0, expected)  # Clamped to 1.0
        
        # Allow small floating point differences
        assert abs(quality.overall_quality - expected) < 0.02
    
    @given(random_ontology())
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_issues_and_suggestions_are_strings(self, ontology):
        """Issues and suggestions must be non-empty strings."""
        entity_stats = compute_entity_stats(ontology)
        rel_stats = compute_relationship_stats(ontology)
        quality = compute_quality_metrics(entity_stats, rel_stats)
        
        for issue in quality.issues:
            assert isinstance(issue, str)
            assert len(issue) > 0
        
        for suggestion in quality.suggestions:
            assert isinstance(suggestion, str)
            assert len(suggestion) > 0


class TestOntologyStatsInvariants:
    """Test invariants for complete ontology statistics."""
    
    @given(random_ontology())
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_all_counts_non_negative(self, ontology):
        """All count metrics must be non-negative."""
        stats = compute_ontology_stats(ontology)
        
        assert stats.entities.total_count >= 0
        assert stats.relationships.total_count >= 0
        assert stats.total_properties_count >= 0
        assert stats.unique_property_names >= 0
        assert stats.entities.orphaned_count >= 0
    
    @given(random_ontology())
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_unique_properties_at_most_total_properties(self, ontology):
        """Unique property names <= total properties (unless no properties)."""
        stats = compute_ontology_stats(ontology)
        if stats.total_properties_count > 0:
            assert stats.unique_property_names <= stats.total_properties_count
        else:
            assert stats.unique_property_names == 0
    
    @given(random_ontology())
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_avg_confidence_between_zero_and_one(self, ontology):
        """Average confidence score must be in [0.0, 1.0]."""
        stats = compute_ontology_stats(ontology)
        assert 0.0 <= stats.avg_confidence_score <= 1.0
    
    @given(random_ontology())
    @settings(max_examples=150, suppress_health_check=[HealthCheck.too_slow])
    def test_determinism(self, ontology):
        """Computing stats twice on same ontology gives identical results."""
        stats1 = compute_ontology_stats(ontology)
        stats2 = compute_ontology_stats(ontology)
        
        assert stats1.entities.total_count == stats2.entities.total_count
        assert stats1.relationships.total_count == stats2.relationships.total_count
        assert stats1.total_properties_count == stats2.total_properties_count
        assert stats1.unique_property_names == stats2.unique_property_names
        assert stats1.avg_confidence_score == stats2.avg_confidence_score


class TestMonotonicityUnderMerge:
    """Test that merging ontologies behaves monotonically."""
    
    @given(random_ontology(), random_ontology())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_merge_entity_count_is_sum(self, ont1, ont2):
        """Merging two ontologies adds their entity counts (before deduplication)."""
        merged = {
            "entities": ont1["entities"] + ont2["entities"],
            "relationships": ont1["relationships"] + ont2["relationships"],
        }
        
        stats1 = compute_entity_stats(ont1)
        stats2 = compute_entity_stats(ont2)
        merged_stats = compute_entity_stats(merged)
        
        assert merged_stats.total_count == stats1.total_count + stats2.total_count
    
    @given(random_ontology(), random_ontology())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_merge_relationship_count_is_sum(self, ont1, ont2):
        """Merging two ontologies adds their relationship counts."""
        merged = {
            "entities": ont1["entities"] + ont2["entities"],
            "relationships": ont1["relationships"] + ont2["relationships"],
        }
        
        stats1 = compute_relationship_stats(ont1)
        stats2 = compute_relationship_stats(ont2)
        merged_stats = compute_relationship_stats(merged)
        
        assert merged_stats.total_count == stats1.total_count + stats2.total_count
    
    @given(random_ontology())
    @settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
    def test_empty_ontology_identity(self, ontology):
        """Merging with empty ontology doesn't change stats."""
        empty = {"entities": [], "relationships": []}
        merged = {
            "entities": ontology["entities"] + empty["entities"],
            "relationships": ontology["relationships"] + empty["relationships"],
        }
        
        original = compute_ontology_stats(ontology)
        merged_stats = compute_ontology_stats(merged)
        
        assert original.entities.total_count == merged_stats.entities.total_count
        assert original.relationships.total_count == merged_stats.relationships.total_count


class TestEdgeCaseInvariants:
    """Test edge cases to ensure robustness."""
    
    def test_completely_empty_ontology(self):
        """Empty ontology should have all counts at zero."""
        ontology = {"entities": [], "relationships": []}
        stats = compute_ontology_stats(ontology)
        
        assert stats.entities.total_count == 0
        assert stats.relationships.total_count == 0
        assert stats.total_properties_count == 0
        assert stats.unique_property_names == 0
        assert stats.entities.orphaned_count == 0
        assert stats.relationships.relationship_density == 0.0
    
    def test_single_lonely_entity(self):
        """Single entity with no relationships should be orphaned."""
        ontology = {
            "entities": [{"id": "e1", "type": "Person", "text": "Alice", "properties": {}, "confidence": 0.9}],
            "relationships": [],
        }
        stats = compute_ontology_stats(ontology)
        
        assert stats.entities.total_count == 1
        assert stats.relationships.total_count == 0
        assert stats.entities.orphaned_count == 1
    
    def test_fully_connected_triangle(self):
        """Fully connected 3-node graph should have maximum density."""
        entities = [
            {"id": "e1", "type": "Person", "text": "A", "confidence": 1.0},
            {"id": "e2", "type": "Person", "text": "B", "confidence": 1.0},
            {"id": "e3", "type": "Person", "text": "C", "confidence": 1.0},
        ]
        
        # All 6 directed edges (3 * 2)
        relationships = [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"},
            {"id": "r2", "source_id": "e1", "target_id": "e3", "type": "knows"},
            {"id": "r3", "source_id": "e2", "target_id": "e1", "type": "knows"},
            {"id": "r4", "source_id": "e2", "target_id": "e3", "type": "knows"},
            {"id": "r5", "source_id": "e3", "target_id": "e1", "type": "knows"},
            {"id": "r6", "source_id": "e3", "target_id": "e2", "type": "knows"},
        ]
        
        ontology = {"entities": entities, "relationships": relationships}
        stats = compute_ontology_stats(ontology)
        
        assert stats.relationships.relationship_density == pytest.approx(1.0)
        assert stats.entities.orphaned_count == 0
    
    def test_malformed_ontology_with_missing_keys(self):
        """Ontology with missing 'entities' or 'relationships' should not crash."""
        ontology_no_entities = {"relationships": []}
        ontology_no_rels = {"entities": []}
        ontology_empty_dict = {}
        
        # Should not crash
        stats1 = compute_ontology_stats(ontology_no_entities)
        stats2 = compute_ontology_stats(ontology_no_rels)
        stats3 = compute_ontology_stats(ontology_empty_dict)
        
        assert stats1.entities.total_count == 0
        assert stats2.relationships.total_count == 0
        assert stats3.entities.total_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--hypothesis-show-statistics"])

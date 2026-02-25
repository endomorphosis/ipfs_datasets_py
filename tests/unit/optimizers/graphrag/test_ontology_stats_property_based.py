"""Property-based tests for ontology statistics classes.

Uses Hypothesis to generate random ontology stats and verify invariants.
"""

import pytest

hypothesis = pytest.importorskip("hypothesis")
given = hypothesis.given
st = hypothesis.strategies
assume = hypothesis.assume
settings = hypothesis.settings

from ipfs_datasets_py.optimizers.graphrag.ontology_stats import (
    EntityStats,
    RelationshipStats,
    OntologyStats,
)


# ============================================================================
# Hypothesis Strategies
# ============================================================================

@st.composite
def entity_stats_strategy(draw):
    """Strategy for generating valid EntityStats instances."""
    total = draw(st.integers(min_value=1, max_value=1000))
    num_types = draw(st.integers(min_value=1, max_value=10))
    
    # Generate type distribution that sums to total
    type_counts = []
    remaining = total
    for i in range(num_types - 1):
        count = draw(st.integers(min_value=0, max_value=remaining))
        type_counts.append(count)
        remaining -= count
    type_counts.append(remaining)
    
    type_dist = {f"Type{i}": count for i, count in enumerate(type_counts) if count > 0}
    
    return EntityStats(
        total_count=total,
        type_distribution=type_dist,
        avg_properties_per_entity=draw(st.floats(min_value=0, max_value=50)),
        property_coverage_ratio=draw(st.floats(min_value=0, max_value=1)),
        orphaned_count=draw(st.integers(min_value=0, max_value=total)),
    )


@st.composite
def relationship_stats_strategy(draw):
    """Strategy for generating valid RelationshipStats instances."""
    total = draw(st.integers(min_value=0, max_value=5000))
    num_types = draw(st.integers(min_value=1, max_value=15))
    
    # Generate type distribution that sums to total
    type_counts = []
    remaining = total
    for i in range(num_types - 1):
        count = draw(st.integers(min_value=0, max_value=remaining))
        type_counts.append(count)
        remaining -= count
    type_counts.append(remaining)
    
    type_dist = {f"RelType{i}": count for i, count in enumerate(type_counts) if count > 0}
    
    return RelationshipStats(
        total_count=total,
        type_distribution=type_dist,
        avg_relationships_per_entity=draw(st.floats(min_value=0, max_value=100)),
        relationship_density=draw(st.floats(min_value=0, max_value=1)),
        connected_components=draw(st.integers(min_value=1, max_value=50)),
    )


@st.composite
def ontology_stats_strategy(draw):
    """Strategy for generating valid OntologyStats instances."""
    entities = draw(entity_stats_strategy())
    relationships = draw(relationship_stats_strategy())
    
    total_props = draw(st.integers(min_value=0, max_value=5000))
    # Ensure unique_property_names <= total_properties_count
    unique_props = draw(st.integers(min_value=0, max_value=total_props))
    
    return OntologyStats(
        entities=entities,
        relationships=relationships,
        total_properties_count=total_props,
        unique_property_names=unique_props,
        avg_confidence_score=draw(st.floats(min_value=0, max_value=1)),
    )


# ============================================================================
# Property-Based Tests for EntityStats
# ============================================================================

class TestEntityStatsProperties:
    """Property-based tests for EntityStats invariants."""
    
    @given(entity_stats_strategy())
    def test_entity_count_is_positive(self, stats: EntityStats):
        """Entity count should always be positive."""
        assert stats.total_count > 0
    
    @given(entity_stats_strategy())
    def test_type_distribution_sums_to_total(self, stats: EntityStats):
        """Sum of type counts should equal total count."""
        sum_types = sum(stats.type_distribution.values())
        # Allow small rounding errors
        assert sum_types == stats.total_count
    
    @given(entity_stats_strategy())
    def test_orphaned_count_within_bounds(self, stats: EntityStats):
        """Orphaned count should be <= total count."""
        assert 0 <= stats.orphaned_count <= stats.total_count
    
    @given(entity_stats_strategy())
    def test_property_coverage_ratio_valid_range(self, stats: EntityStats):
        """Property coverage ratio should be in [0, 1]."""
        assert 0 <= stats.property_coverage_ratio <= 1
    
    @given(entity_stats_strategy())
    def test_has_diversity_reflects_type_count(self, stats: EntityStats):
        """has_diversity should match type count > 2."""
        expected = len(stats.type_distribution) > 2
        assert stats.has_diversity() == expected
    
    @given(entity_stats_strategy())
    def test_repr_does_not_crash(self, stats: EntityStats):
        """repr should always return a string without crashing."""
        result = repr(stats)
        assert isinstance(result, str)
        assert len(result) > 0


# ============================================================================
# Property-Based Tests for RelationshipStats
# ============================================================================

class TestRelationshipStatsProperties:
    """Property-based tests for RelationshipStats invariants."""
    
    @given(relationship_stats_strategy())
    def test_relationship_density_in_valid_range(self, stats: RelationshipStats):
        """Relationship density should be in [0, 1]."""
        assert 0 <= stats.relationship_density <= 1
    
    @given(relationship_stats_strategy())
    def test_type_distribution_valid(self, stats: RelationshipStats):
        """Type distribution should sum to total count."""
        sum_types = sum(stats.type_distribution.values())
        assert sum_types == stats.total_count
    
    @given(relationship_stats_strategy())
    def test_connected_components_positive(self, stats: RelationshipStats):
        """Connected components should be positive."""
        assert stats.connected_components > 0
    
    @given(relationship_stats_strategy())
    def test_is_sparse_and_dense_mutually_exclusive(self, stats: RelationshipStats):
        """A graph cannot be both sparse and dense."""
        assert not (stats.is_sparse() and stats.is_dense())
    
    @given(relationship_stats_strategy())
    def test_is_sparse_reflects_density(self, stats: RelationshipStats):
        """is_sparse should match density < 0.1."""
        expected = stats.relationship_density < 0.1
        assert stats.is_sparse() == expected
    
    @given(relationship_stats_strategy())
    def test_is_dense_reflects_density(self, stats: RelationshipStats):
        """is_dense should match density > 0.5."""
        expected = stats.relationship_density > 0.5
        assert stats.is_dense() == expected
    
    @given(relationship_stats_strategy())
    def test_repr_does_not_crash(self, stats: RelationshipStats):
        """repr should always return a string without crashing."""
        result = repr(stats)
        assert isinstance(result, str)
        assert len(result) > 0


# ============================================================================
# Property-Based Tests for OntologyStats
# ============================================================================

class TestOntologyStatsProperties:
    """Property-based tests for OntologyStats invariants."""
    
    @given(ontology_stats_strategy())
    def test_confidence_score_in_valid_range(self, stats: OntologyStats):
        """Average confidence score should be in [0, 1]."""
        assert 0 <= stats.avg_confidence_score <= 1
    
    @given(ontology_stats_strategy())
    def test_unique_properties_within_total(self, stats: OntologyStats):
        """Unique property names should be <= total properties."""
        assert stats.unique_property_names <= stats.total_properties_count
    
    @given(ontology_stats_strategy())
    def test_entities_stats_valid(self, stats: OntologyStats):
        """Contained entity stats should be valid."""
        assert stats.entities.total_count > 0
        assert isinstance(stats.entities.type_distribution, dict)
    
    @given(ontology_stats_strategy())
    def test_relationships_stats_valid(self, stats: OntologyStats):
        """Contained relationship stats should be valid."""
        assert isinstance(stats.relationships.type_distribution, dict)
        assert 0 <= stats.relationships.relationship_density <= 1
    
    @given(ontology_stats_strategy())
    def test_repr_does_not_crash(self, stats: OntologyStats):
        """repr should always return a string without crashing."""
        result = repr(stats)
        assert isinstance(result, str)
        assert len(result) > 0
    
    @given(ontology_stats_strategy())
    @settings(max_examples=100)
    def test_ontology_consistency(self, stats: OntologyStats):
        """All components of ontology should be internally consistent."""
        # Entity stats should have valid distribution
        assert len(stats.entities.type_distribution) > 0
        assert sum(stats.entities.type_distribution.values()) == stats.entities.total_count
        
        # Relationship stats should have valid distribution
        assert sum(stats.relationships.type_distribution.values()) == stats.relationships.total_count
        
        # Confidence should always be in valid range
        assert 0 <= stats.avg_confidence_score <= 1


# ============================================================================
# Integration Property Tests
# ============================================================================

class TestOntologyStatsIntegration:
    """Integration tests combining multiple stats properties."""
    
    @given(ontology_stats_strategy())
    def test_stats_remain_valid_after_repr(self, stats: OntologyStats):
        """repr should not affect stats validity."""
        # Call repr multiple times
        repr1 = repr(stats)
        repr2 = repr(stats)
        repr3 = repr(stats)
        
        # repr should be deterministic
        assert repr1 == repr2 == repr3
        
        # Stats should still be valid
        assert stats.entities.total_count > 0
        assert 0 <= stats.relationships.relationship_density <= 1
        assert 0 <= stats.avg_confidence_score <= 1
    
    @given(st.lists(entity_stats_strategy(), min_size=1, max_size=10))
    def test_multiple_entity_stats_are_independent(self, stats_list):
        """Multiple EntityStats instances should be independent."""
        # No stat should affect others
        for i, stat in enumerate(stats_list):
            assert stat.total_count > 0
            assert all(count > 0 for count in stat.type_distribution.values())
    
    @given(st.lists(ontology_stats_strategy(), min_size=1, max_size=5))
    def test_multiple_ontology_stats_comparison(self, stats_list):
        """Multiple ontology stats should be comparable."""
        for i in range(len(stats_list) - 1):
            stats1 = stats_list[i]
            stats2 = stats_list[i + 1]
            
            # Both should have valid confidence scores
            assert isinstance(stats1.avg_confidence_score, float)
            assert isinstance(stats2.avg_confidence_score, float)
            assert 0 <= stats1.avg_confidence_score <= 1
            assert 0 <= stats2.avg_confidence_score <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

"""Test __eq__ and __hash__ functionality for Entity, Relationship, and CriticScore.

Added as part of P3-API task to enable usage in sets and dicts.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity, Relationship
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore


class TestEntityHashability:
    """Test Entity __eq__ and __hash__ methods."""

    def test_entity_equality_all_fields_match(self):
        """Entities with identical fields should be equal."""
        e1 = Entity(id="e1", type="Person", text="Alice", confidence=0.9)
        e2 = Entity(id="e1", type="Person", text="Alice", confidence=0.9)
        assert e1 == e2

    def test_entity_equality_different_properties(self):
        """Entities with different properties should not be equal."""
        e1 = Entity(id="e1", type="Person", text="Alice", properties={"age": 30})
        e2 = Entity(id="e1", type="Person", text="Alice", properties={"age": 31})
        assert e1 != e2

    def test_entity_hashability_same_id(self):
        """Entities with same ID should have same hash."""
        e1 = Entity(id="e1", type="Person", text="Alice")
        e2 = Entity(id="e1", type="Person", text="Bob")  # Different text, same ID
        assert hash(e1) == hash(e2)

    def test_entity_in_set(self):
        """Entities should be usable in sets (deduplication by ID)."""
        e1 = Entity(id="e1", type="Person", text="Alice")
        e2 = Entity(id="e1", type="Person", text="Alice")
        e3 = Entity(id="e2", type="Person", text="Bob")
        
        entity_set = {e1, e2, e3}
        assert len(entity_set) == 2  # e1 and e2 deduplicated by ID

    def test_entity_as_dict_key(self):
        """Entities should be usable as dict keys."""
        e1 = Entity(id="e1", type="Person", text="Alice")
        e2 = Entity(id="e2", type="Person", text="Bob")
        
        entity_dict = {e1: "data1", e2: "data2"}
        assert entity_dict[e1] == "data1"
        assert len(entity_dict) == 2


class TestRelationshipHashability:
    """Test Relationship __eq__ and __hash__ methods."""

    def test_relationship_equality_all_fields_match(self):
        """Relationships with identical fields should be equal."""
        r1 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns")
        r2 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns")
        assert r1 == r2

    def test_relationship_equality_different_confidence(self):
        """Relationships with different confidence should not be equal."""
        r1 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns", confidence=0.9)
        r2 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns", confidence=0.8)
        assert r1 != r2

    def test_relationship_hashability_same_id(self):
        """Relationships with same ID should have same hash."""
        r1 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns")
        r2 = Relationship(id="r1", source_id="e3", target_id="e4", type="uses")  # Different endpoints, same ID
        assert hash(r1) == hash(r2)

    def test_relationship_in_set(self):
        """Relationships should be usable in sets (deduplication by ID)."""
        r1 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns")
        r2 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns")
        r3 = Relationship(id="r2", source_id="e1", target_id="e3", type="uses")
        
        rel_set = {r1, r2, r3}
        assert len(rel_set) == 2  # r1 and r2 deduplicated by ID

    def test_relationship_as_dict_key(self):
        """Relationships should be usable as dict keys."""
        r1 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns")
        r2 = Relationship(id="r2", source_id="e1", target_id="e3", type="uses")
        
        rel_dict = {r1: "ownership", r2: "usage"}
        assert rel_dict[r1] == "ownership"
        assert len(rel_dict) == 2


class TestCriticScoreHashability:
    """Test CriticScore __eq__ and __hash__ methods."""

    def test_critic_score_equality_within_tolerance(self):
        """Scores within tolerance should be equal."""
        s1 = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.7,
            granularity=0.6,
            relationship_coherence=0.82,
            domain_alignment=0.88,
        )
        s2 = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.7,
            granularity=0.6,
            relationship_coherence=0.82,
            domain_alignment=0.88,
        )
        assert s1 == s2

    def test_critic_score_equality_different_overall(self):
        """Scores with different overall scores should not be equal."""
        s1 = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.7,
            granularity=0.6,
            relationship_coherence=0.82,
            domain_alignment=0.88,
        )
        s2 = CriticScore(
            completeness=0.7,  # Different
            consistency=0.9,
            clarity=0.7,
            granularity=0.6,
            relationship_coherence=0.82,
            domain_alignment=0.88,
        )
        assert s1 != s2

    def test_critic_score_hashability_same_dimensions(self):
        """Scores with same dimensions should have same hash."""
        s1 = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.7,
            granularity=0.6,
            relationship_coherence=0.82,
            domain_alignment=0.88,
        )
        s2 = CriticScore(
            completeness=0.8,
            consistency=0.9,
            clarity=0.7,
            granularity=0.6,
            relationship_coherence=0.82,
            domain_alignment=0.88,
            strengths=["good coverage"],  # Different metadata, same dimensions
        )
        assert hash(s1) == hash(s2)

    def test_critic_score_in_set(self):
        """CriticScores should be usable in sets."""
        s1 = CriticScore(
            completeness=0.8, consistency=0.9, clarity=0.7,
            granularity=0.6, relationship_coherence=0.82, domain_alignment=0.88,
        )
        s2 = CriticScore(
            completeness=0.8, consistency=0.9, clarity=0.7,
            granularity=0.6, relationship_coherence=0.82, domain_alignment=0.88,
        )
        s3 = CriticScore(
            completeness=0.7, consistency=0.8, clarity=0.6,  # Different
            granularity=0.5, relationship_coherence=0.75, domain_alignment=0.80,
        )
        
        score_set = {s1, s2, s3}
        assert len(score_set) == 2  # s1 and s2 deduplicated

    def test_critic_score_as_dict_key(self):
        """CriticScores should be usable as dict keys."""
        s1 = CriticScore(
            completeness=0.8, consistency=0.9, clarity=0.7,
            granularity=0.6, relationship_coherence=0.82, domain_alignment=0.88,
        )
        s2 = CriticScore(
            completeness=0.7, consistency=0.8, clarity=0.6,
            granularity=0.5, relationship_coherence=0.75, domain_alignment=0.80,
        )
        
        score_dict = {s1: "high quality", s2: "medium quality"}
        assert score_dict[s1] == "high quality"
        assert len(score_dict) == 2


class TestCrossBehavior:
    """Test interactions between hashable types."""

    def test_entity_relationship_in_same_dict(self):
        """Entities and relationships should coexist in collections."""
        e1 = Entity(id="e1", type="Person", text="Alice")
        r1 = Relationship(id="r1", source_id="e1", target_id="e2", type="owns")
        
        # This is a type error in static typing, but demonstrates runtime behavior
        # In practice, you wouldn't mix these types
        items = {e1: "entity", r1: "relationship"}
        assert len(items) == 2

    def test_entity_deduplication_across_operations(self):
        """Entity deduplication should work when entities are truly identical."""
        entities = []
        for i in range(10):
            # Create identical entities (same ID and all fields) - these will deduplicate
            entities.append(Entity(id=f"e{i % 3}", type="Person", text=f"Person{i % 3}"))
        
        unique_entities = set(entities)
        assert len(unique_entities) == 3  # Only 3 unique entities: e0, e1, e2

    def test_relationship_deduplication_across_operations(self):
        """Relationship deduplication should work when relationships are truly identical."""
        relationships = []
        for i in range(10):
            # Create identical relationships (same ID and all fields) - these will deduplicate
            relationships.append(
                Relationship(id=f"r{i % 4}", source_id=f"e{i % 4}", target_id=f"e{(i % 4) + 1}", type="conn")
            )
        
        unique_rels = set(relationships)
        assert len(unique_rels) == 4  # Only 4 unique relationships: r0, r1, r2, r3

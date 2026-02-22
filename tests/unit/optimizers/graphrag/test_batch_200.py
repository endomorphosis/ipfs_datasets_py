"""
Unit tests for Batch 200 implementations.

This module tests:
- EntityExtractionResult.entity_count property
- EntityExtractionResult.relationship_count property  
- EntityExtractionResult.from_dict() classmethod
- OntologyCritic.failing_scores() method
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
    CriticScore,
)


class TestEntityCountProperty:
    """Test EntityExtractionResult.entity_count property."""

    def test_entity_count_empty(self):
        """empty result has entity_count = 0."""
        result = EntityExtractionResult(
            entities=[],
            relationships=[],
            confidence=1.0,
        )
        assert result.entity_count == 0

    def test_entity_count_single(self):
        """single entity."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.9)
            ],
            relationships=[],
            confidence=0.9,
        )
        assert result.entity_count == 1

    def test_entity_count_multiple(self):
        """multiple entities."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                Entity(id="e2", text="Bob", type="Person", confidence=0.85),
                Entity(id="e3", text="ACME Corp", type="Organization", confidence=0.8),
            ],
            relationships=[],
            confidence=0.85,
        )
        assert result.entity_count == 3

    def test_entity_count_matches_len_entities(self):
        """entity_count is always len(entities)."""
        entities = [
            Entity(id=f"e{i}", text=f"Entity{i}", type="Type", confidence=0.9)
            for i in range(10)
        ]
        result = EntityExtractionResult(
            entities=entities,
            relationships=[],
            confidence=0.9,
        )
        assert result.entity_count == len(entities)


class TestRelationshipCountProperty:
    """Test EntityExtractionResult.relationship_count property."""

    def test_relationship_count_empty(self):
        """empty result has relationship_count = 0."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.9)
            ],
            relationships=[],
            confidence=0.9,
        )
        assert result.relationship_count == 0

    def test_relationship_count_single(self):
        """single relationship."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                Entity(id="e2", text="Bob", type="Person", confidence=0.85),
            ],
            relationships=[
                Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.7)
            ],
            confidence=0.85,
        )
        assert result.relationship_count == 1

    def test_relationship_count_multiple(self):
        """multiple relationships."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                Entity(id="e2", text="Bob", type="Person", confidence=0.85),
                Entity(id="e3", text="ACME Corp", type="Organization", confidence=0.8),
            ],
            relationships=[
                Relationship(id="r1", source_id="e1", target_id="e2", type="knows", confidence=0.7),
                Relationship(id="r2", source_id="e1", target_id="e3", type="works_for", confidence=0.75),
                Relationship(id="r3", source_id="e2", target_id="e3", type="works_for", confidence=0.65),
            ],
            confidence=0.8,
        )
        assert result.relationship_count == 3

    def test_relationship_count_matches_len_relationships(self):
        """relationship_count is always len(relationships)."""
        relationships = [
            Relationship(id=f"r{i}", source_id="e1", target_id="e2", type="rel", confidence=0.7)
            for i in range(5)
        ]
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.9),
                Entity(id="e2", text="Bob", type="Person", confidence=0.85),
            ],
            relationships=relationships,
            confidence=0.85,
        )
        assert result.relationship_count == len(relationships)


class TestEntityExtractionResultFromDict:
    """Test EntityExtractionResult.from_dict() classmethod."""

    def test_from_dict_empty(self):
        """deserialize empty result."""
        data = {
            "entities": [],
            "relationships": [],
            "confidence": 1.0,
            "metadata": {},
            "errors": [],
        }
        result = EntityExtractionResult.from_dict(data)
        assert result.entity_count == 0
        assert result.relationship_count == 0
        assert result.confidence == 1.0
        assert result.metadata == {}
        assert result.errors == []

    def test_from_dict_with_entities(self):
        """deserialize with entities."""
        data = {
            "entities": [
                {
                    "id": "e1",
                    "text": "Alice",
                    "type": "Person",
                    "confidence": 0.9,
                    "properties": {"age": "30"},
                    "source_span": [0, 5],
                }
            ],
            "relationships": [],
            "confidence": 0.9,
            "metadata": {},
            "errors": [],
        }
        result = EntityExtractionResult.from_dict(data)
        assert result.entity_count == 1
        assert result.entities[0].id == "e1"
        assert result.entities[0].text == "Alice"
        assert result.entities[0].type == "Person"
        assert result.entities[0].confidence == 0.9
        assert result.entities[0].properties == {"age": "30"}
        assert result.entities[0].source_span == (0, 5)

    def test_from_dict_with_relationships(self):
        """deserialize with relationships."""
        data = {
            "entities": [
                {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.9},
                {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.85},
            ],
            "relationships": [
                {
                    "id": "r1",
                    "source_id": "e1",
                    "target_id": "e2",
                    "type": "knows",
                    "confidence": 0.7,
                    "direction": "subject_to_object",
                    "properties": {"context": "work"},
                }
            ],
            "confidence": 0.85,
            "metadata": {},
            "errors": [],
        }
        result = EntityExtractionResult.from_dict(data)
        assert result.relationship_count == 1
        rel = result.relationships[0]
        assert rel.id == "r1"
        assert rel.source_id == "e1"
        assert rel.target_id == "e2"
        assert rel.type == "knows"
        assert rel.confidence == 0.7
        assert rel.direction == "subject_to_object"
        assert rel.properties == {"context": "work"}

    def test_from_dict_round_trip(self):
        """to_dict() -> from_dict() round trip preserves data."""
        original = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.9,
                       properties={"age": "30"}, source_span=(0, 5)),
                Entity(id="e2", text="Bob", type="Person", confidence=0.85),
            ],
            relationships=[
                Relationship(id="r1", source_id="e1", target_id="e2", type="knows",
                           confidence=0.7, direction="subject_to_object", properties={"context": "work"}),
            ],
            confidence=0.87,
            metadata={"source": "document"},
            errors=["warning1"],
        )
        
        # Convert to dict and back
        data = original.to_dict()
        restored = EntityExtractionResult.from_dict(data)
        
        # Verify all fields match
        assert restored.entity_count == original.entity_count
        assert restored.relationship_count == original.relationship_count
        assert restored.confidence == original.confidence
        assert restored.metadata == original.metadata
        assert restored.errors == original.errors
        
        for orig_e, rest_e in zip(original.entities, restored.entities):
            assert orig_e.id == rest_e.id
            assert orig_e.text == rest_e.text
            assert orig_e.type == rest_e.type
            assert orig_e.confidence == rest_e.confidence
            assert orig_e.properties == rest_e.properties
            assert orig_e.source_span == rest_e.source_span

    def test_from_dict_missing_optional_fields(self):
        """from_dict handles missing optional fields gracefully."""
        data = {
            "entities": [{"id": "e1", "text": "Alice", "type": "Person"}],
            # confidence defaults to 1.0 if missing
            # relationships defaults to []
        }
        result = EntityExtractionResult.from_dict(data)
        assert result.entity_count == 1
        assert result.relationship_count == 0
        assert result.entities[0].confidence == 1.0
        assert result.metadata == {}
        assert result.errors == []

    def test_from_dict_empty_dict(self):
        """from_dict handles empty dict."""
        result = EntityExtractionResult.from_dict({})
        assert result.entity_count == 0
        assert result.relationship_count == 0
        assert result.confidence == 1.0


class TestOntologyCriticFailingScores:
    """Test OntologyCritic.failing_scores() method."""

    def test_failing_scores_empty(self):
        """empty list returns empty."""
        critic = OntologyCritic()
        scores = []
        failing = critic.failing_scores(scores, threshold=0.6)
        assert failing == []

    def test_failing_scores_all_pass(self):
        """when all scores pass, returns []."""
        critic = OntologyCritic()
        scores = [
            CriticScore(completeness=0.8, consistency=0.7, clarity=0.8,
                       granularity=0.75, relationship_coherence=0.7, domain_alignment=0.8),
            CriticScore(completeness=0.9, consistency=0.85, clarity=0.9,
                       granularity=0.88, relationship_coherence=0.85, domain_alignment=0.9),
        ]
        failing = critic.failing_scores(scores, threshold=0.6)
        assert failing == []

    def test_failing_scores_all_fail(self):
        """when all scores fail, returns all."""
        critic = OntologyCritic()
        scores = [
            CriticScore(completeness=0.4, consistency=0.3, clarity=0.35,
                       granularity=0.4, relationship_coherence=0.35, domain_alignment=0.3),
            CriticScore(completeness=0.5, consistency=0.45, clarity=0.5,
                       granularity=0.48, relationship_coherence=0.45, domain_alignment=0.5),
        ]
        failing = critic.failing_scores(scores, threshold=0.6)
        assert len(failing) == 2
        assert failing == scores

    def test_failing_scores_mixed(self):
        """mixed pass/fail returns only failing."""
        critic = OntologyCritic()
        pass_score = CriticScore(completeness=0.8, consistency=0.7, clarity=0.8,
                               granularity=0.75, relationship_coherence=0.7, domain_alignment=0.8)
        fail_score = CriticScore(completeness=0.4, consistency=0.3, clarity=0.35,
                                granularity=0.4, relationship_coherence=0.35, domain_alignment=0.3)
        scores = [pass_score, fail_score, pass_score, fail_score]
        
        failing = critic.failing_scores(scores, threshold=0.6)
        assert len(failing) == 2
        assert fail_score in failing

    def test_failing_scores_boundary(self):
        """scores exactly at threshold are failing (<=)."""
        critic = OntologyCritic()
        threshold = 0.6
        at_threshold = CriticScore(completeness=0.6, consistency=0.6, clarity=0.6,
                                  granularity=0.6, relationship_coherence=0.6, domain_alignment=0.6)
        below_threshold = CriticScore(completeness=0.5, consistency=0.5, clarity=0.5,
                                     granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        above_threshold = CriticScore(completeness=0.7, consistency=0.7, clarity=0.7,
                                     granularity=0.7, relationship_coherence=0.7, domain_alignment=0.7)
        
        scores = [at_threshold, below_threshold, above_threshold]
        failing = critic.failing_scores(scores, threshold=threshold)
        
        # Both at_threshold and below_threshold should fail
        assert len(failing) == 2
        assert at_threshold in failing
        assert below_threshold in failing
        assert above_threshold not in failing

    def test_failing_scores_preserves_order(self):
        """failing_scores preserves original order."""
        critic = OntologyCritic()
        score1 = CriticScore(completeness=0.4, consistency=0.3, clarity=0.35,
                            granularity=0.4, relationship_coherence=0.35, domain_alignment=0.3)
        score2 = CriticScore(completeness=0.8, consistency=0.7, clarity=0.8,
                            granularity=0.75, relationship_coherence=0.7, domain_alignment=0.8)
        score3 = CriticScore(completeness=0.5, consistency=0.5, clarity=0.5,
                            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        scores = [score1, score2, score3]
        
        failing = critic.failing_scores(scores, threshold=0.6)
        assert failing == [score1, score3]

    def test_failing_scores_different_thresholds(self):
        """failing_scores respects different threshold values."""
        critic = OntologyCritic()
        scores = [
            CriticScore(completeness=0.5, consistency=0.5, clarity=0.5,
                       granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5),
            CriticScore(completeness=0.7, consistency=0.7, clarity=0.7,
                       granularity=0.7, relationship_coherence=0.7, domain_alignment=0.7),
            CriticScore(completeness=0.9, consistency=0.9, clarity=0.9,
                       granularity=0.9, relationship_coherence=0.9, domain_alignment=0.9),
        ]
        
        # Threshold=0.8: scores with overall <= 0.8 are failing
        # (0.5 <= 0.8, 0.7 <= 0.8 true; 0.9 <= 0.8 false)
        failing_high = critic.failing_scores(scores, threshold=0.8)
        assert len(failing_high) == 2
        
        # Threshold=0.4: scores with overall <= 0.4 are failing
        # (0.5 > 0.4, 0.7 > 0.4, 0.9 > 0.4) all pass
        failing_low = critic.failing_scores(scores, threshold=0.4)
        assert len(failing_low) == 0
        
        # Threshold=0.6: scores with overall <= 0.6 are failing
        # (0.5 <= 0.6 true; 0.7 > 0.6, 0.9 > 0.6 pass)
        failing_mid = critic.failing_scores(scores, threshold=0.6)
        assert len(failing_mid) == 1

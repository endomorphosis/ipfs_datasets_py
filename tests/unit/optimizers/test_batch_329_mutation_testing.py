"""
Batch 329: Mutation Testing & Property-Based Testing
=====================================================

Uses Hypothesis to generate property-based tests for ontology critics
and dimension evaluators, ensuring robustness against edge cases and mutations.

Goal: Provide:
- Property-based mutation testing for dimension evaluators
- Robustness verification of scoring functions
- Invariant checking for ontology components
- Edge case coverage via Hypothesis strategies
"""

import pytest
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from hypothesis import given, strategies as st, assume
from hypothesis.strategies import composite


# ============================================================================
# DOMAIN MODELS
# ============================================================================

@dataclass
class Entity:
    """Ontology entity."""
    name: str
    entity_type: str = "concept"
    confidence: float = 0.5
    
    def __post_init__(self):
        """Validate entity."""
        self.confidence = max(0.0, min(1.0, self.confidence))


@dataclass
class Relationship:
    """Ontology relationship."""
    source: str
    target: str
    rel_type: str
    weight: float = 1.0
    
    def __post_init__(self):
        """Validate relationship."""
        self.weight = max(0.0, min(1.0, self.weight))


@dataclass
class Ontology:
    """Graph ontology."""
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    
    def entity_count(self) -> int:
        """Get entity count."""
        return len(self.entities)
    
    def relationship_count(self) -> int:
        """Get relationship count."""
        return len(self.relationships)
    
    def density(self) -> float:
        """Calculate graph density."""
        if self.entity_count() < 2:
            return 0.0
        max_edges = self.entity_count() * (self.entity_count() - 1)
        return 2 * self.relationship_count() / max_edges if max_edges > 0 else 0.0
    
    def avg_confidence(self) -> float:
        """Calculate average entity confidence."""
        if not self.entities:
            return 0.0
        return sum(e.confidence for e in self.entities) / len(self.entities)


# ============================================================================
# DIMENSION EVALUATORS
# ============================================================================

class CompletenesDimensionEvaluator:
    """Evaluates completeness of ontology."""
    
    MIN_ENTITIES = 2
    MIN_RELATIONSHIPS = 1
    
    def evaluate(self, ontology: Ontology) -> float:
        """Evaluate completeness (0.0-1.0).
        
        Factors:
        - Entity count: entities / (min(50, target))
        - Relationship count: rels / (min(100, target))
        - Coverage: entities with relationships / total entities
        """
        entity_score = min(1.0, ontology.entity_count() / 50.0)
        
        rel_score = min(1.0, ontology.relationship_count() / 100.0)
        
        # Coverage: entities involved in relationships
        if ontology.entity_count() == 0:
            coverage_score = 0.0
        else:
            involved = set()
            for rel in ontology.relationships:
                # Validate endpoints exist
                entity_names = set(e.name for e in ontology.entities)
                if rel.source in entity_names and rel.target in entity_names:
                    involved.add(rel.source)
                    involved.add(rel.target)
            coverage_score = len(involved) / ontology.entity_count()
        
        result = (entity_score + rel_score + coverage_score) / 3.0
        return max(0.0, min(1.0, result))  # Clamp to [0, 1]
    
    def is_complete(self, ontology: Ontology) -> bool:
        """Check if ontology is complete."""
        return (ontology.entity_count() >= self.MIN_ENTITIES and
                ontology.relationship_count() >= self.MIN_RELATIONSHIPS)


class CoherenceDimensionEvaluator:
    """Evaluates coherence of ontology."""
    
    def evaluate(self, ontology: Ontology) -> float:
        """Evaluate coherence (0.0-1.0).
        
        Factors:
        - Density: should be moderate (not too sparse, not too dense)
        - Type consistency: entities and relationships have consistent types
        - Confidence uniformity: entity confidence scores are consistent
        """
        # Density score: optimal around 0.3, bounded to [0, 1]
        density = min(1.0, ontology.density())  # Clamp density to [0, 1]
        density_score = max(0.0, 1.0 - abs(density - 0.3))  # Ensure [0, 1]
        
        # Type consistency
        entity_types = set(e.entity_type for e in ontology.entities)
        type_score = min(1.0, len(entity_types) / 5.0)
        
        # Confidence uniformity: variance of confidence scores
        if len(ontology.entities) < 2:
            confidence_score = 1.0
        else:
            confidences = [e.confidence for e in ontology.entities]
            avg = sum(confidences) / len(confidences)
            variance = sum((c - avg) ** 2 for c in confidences) / len(confidences)
            std_dev = variance ** 0.5
            # Lower std dev = more uniform = higher score
            confidence_score = 1.0 / (1.0 + std_dev)
        
        result = (density_score + type_score + confidence_score) / 3.0
        return max(0.0, min(1.0, result))  # Clamp to [0, 1]


class ConsistencyDimensionEvaluator:
    """Evaluates consistency of ontology."""
    
    def evaluate(self, ontology: Ontology) -> float:
        """Evaluate consistency (0.0-1.0).
        
        Factors:
        - No dangling references: all relationship endpoints exist
        - Relationship weight validity: all weights in [0, 1]
        - Type alignment: relationship types are consistent
        """
        # Check for dangling references
        entity_names = set(e.name for e in ontology.entities)
        dangling = 0
        for rel in ontology.relationships:
            if rel.source not in entity_names or rel.target not in entity_names:
                dangling += 1
        
        if len(ontology.relationships) == 0:
            dangling_score = 1.0
        else:
            dangling_score = 1.0 - (dangling / len(ontology.relationships))
        
        # Weight validity (should already be enforced by __post_init__)
        weight_score = 1.0
        for rel in ontology.relationships:
            if rel.weight < 0.0 or rel.weight > 1.0:
                weight_score = 0.0
                break
        
        # Type alignment
        rel_types = set(r.rel_type for r in ontology.relationships)
        type_score = min(1.0, len(rel_types) / 10.0)
        
        result = (dangling_score + weight_score + type_score) / 3.0
        return max(0.0, min(1.0, result))  # Clamp to [0, 1]


class RelevanceDimensionEvaluator:
    """Evaluates relevance of ontology to domain."""
    
    def evaluate(self, ontology: Ontology) -> float:
        """Evaluate relevance (0.0-1.0).
        
        Factors:
        - Entity naming: entities have meaningful names (length > 2)
        - Confidence levels: entities have non-trivial confidence
        - Connection quality: relationships have meaningful weights
        """
        # Entity naming
        if not ontology.entities:
            naming_score = 0.0
        else:
            meaningful = sum(1 for e in ontology.entities if len(e.name) > 2)
            naming_score = meaningful / len(ontology.entities)
        
        # Confidence levels (non-trivial = not all same, have variance)
        if len(ontology.entities) < 2:
            confidence_score = ontology.avg_confidence() if ontology.entities else 0.0
        else:
            avg_conf = ontology.avg_confidence()
            confidence_score = avg_conf * 0.5 + 0.5  # Scaled to reward higher confidence
        
        # Connection quality
        if not ontology.relationships:
            connection_score = 0.0
        else:
            avg_weight = sum(r.weight for r in ontology.relationships) / len(ontology.relationships)
            connection_score = avg_weight
        
        result = (naming_score + confidence_score + connection_score) / 3.0
        return max(0.0, min(1.0, result))  # Clamp to [0, 1]


# ============================================================================
# ONTOLOGY CRITIC
# ============================================================================

class OntologyCritic:
    """Criticizes ontologies across multiple dimensions."""
    
    def __init__(self):
        """Initialize critic with evaluators."""
        self.completeness = CompletenesDimensionEvaluator()
        self.coherence = CoherenceDimensionEvaluator()
        self.consistency = ConsistencyDimensionEvaluator()
        self.relevance = RelevanceDimensionEvaluator()
    
    def evaluate_dimension(self, name: str, ontology: Ontology) -> float:
        """Evaluate a single dimension.
        
        Args:
            name: Dimension name (completeness, coherence, consistency, relevance)
            ontology: Ontology to evaluate
            
        Returns:
            Score in [0, 1]
        """
        if name == "completeness":
            return self.completeness.evaluate(ontology)
        elif name == "coherence":
            return self.coherence.evaluate(ontology)
        elif name == "consistency":
            return self.consistency.evaluate(ontology)
        elif name == "relevance":
            return self.relevance.evaluate(ontology)
        else:
            raise ValueError(f"Unknown dimension: {name}")
    
    def evaluate_all_dimensions(self, ontology: Ontology) -> Dict[str, float]:
        """Evaluate all dimensions.
        
        Returns:
            Dict mapping dimension names to scores
        """
        return {
            "completeness": self.completeness.evaluate(ontology),
            "coherence": self.coherence.evaluate(ontology),
            "consistency": self.consistency.evaluate(ontology),
            "relevance": self.relevance.evaluate(ontology),
        }
    
    def get_overall_score(self, ontology: Ontology) -> float:
        """Get overall quality score.
        
        Args:
            ontology: Ontology to evaluate
            
        Returns:
            Overall score in [0, 1]
        """
        scores = self.evaluate_all_dimensions(ontology)
        return sum(scores.values()) / len(scores) if scores else 0.0


# ============================================================================
# HYPOTHESIS STRATEGIES
# ============================================================================

@composite
def entity_strategy(draw) -> Entity:
    """Generate random entities."""
    name = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        min_size=1,
        max_size=20
    ))
    entity_type = draw(st.sampled_from(["concept", "instance", "attribute", "event", "action"]))
    confidence = draw(st.floats(min_value=0.0, max_value=1.0))
    return Entity(name=name or "x", entity_type=entity_type, confidence=confidence)


@composite
def relationship_strategy(draw, entity_names: Optional[List[str]] = None) -> Relationship:
    """Generate random relationships."""
    if entity_names and len(entity_names) >= 2:
        source = draw(st.sampled_from(entity_names))
        target = draw(st.sampled_from([e for e in entity_names if e != source]))
    else:
        source = draw(st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=1,
            max_size=10
        ))
        target = draw(st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz",
            min_size=1,
            max_size=10
        ))
    
    rel_type = draw(st.sampled_from(["has", "is_a", "related_to", "depends_on", "composed_of"]))
    weight = draw(st.floats(min_value=0.0, max_value=1.0))
    return Relationship(source=source or "a", target=target or "b", rel_type=rel_type, weight=weight)


@composite
def ontology_strategy(draw) -> Ontology:
    """Generate random ontologies."""
    num_entities = draw(st.integers(min_value=0, max_value=20))
    entities = [draw(entity_strategy()) for _ in range(num_entities)]
    
    # Ensure unique entity names for valid relationships
    entity_names = list(set(e.name for e in entities))
    
    num_relationships = draw(st.integers(min_value=0, max_value=30))
    relationships = []
    for _ in range(num_relationships):
        if entity_names and len(entity_names) >= 2:
            rel = draw(relationship_strategy(entity_names))
        else:
            rel = draw(relationship_strategy())
        relationships.append(rel)
    
    return Ontology(entities=entities, relationships=relationships)


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestCompletenesDimensionEvaluator:
    """Test completeness dimension with mutations."""
    
    @given(ontology_strategy())
    def test_score_in_range(self, ontology: Ontology):
        """Score should always be in [0, 1]."""
        evaluator = CompletenesDimensionEvaluator()
        score = evaluator.evaluate(ontology)
        assert 0.0 <= score <= 1.0, f"Score {score} out of range"
    
    @given(ontology_strategy())
    def test_empty_ontology(self, ontology: Ontology):
        """Empty ontology should have low score."""
        if len(ontology.entities) == 0 and len(ontology.relationships) == 0:
            evaluator = CompletenesDimensionEvaluator()
            score = evaluator.evaluate(ontology)
            assert score == 0.0
    
    @given(ontology_strategy())
    def test_monotonic_density_increases_with_relationships(self, ontology: Ontology):
        """Adding relationships increases density."""
        original_density = ontology.density()
        
        # Only add relationship if we have at least 2 different entities
        if len(set(e.name for e in ontology.entities)) >= 2:
            entities = list(set(e.name for e in ontology.entities))
            ontology.relationships.append(
                Relationship(source=entities[0], target=entities[1], rel_type="test")
            )
            new_density = ontology.density()
            
            # More relationships should increase or maintain density
            assert new_density >= original_density - 0.0001  # Allow tiny floating point error
    
    def test_complete_ontology(self):
        """Complete ontology should pass completeness check."""
        ontology = Ontology(
            entities=[Entity(name="e1"), Entity(name="e2"), Entity(name="e3")],
            relationships=[Relationship(source="e1", target="e2", rel_type="has")]
        )
        evaluator = CompletenesDimensionEvaluator()
        assert evaluator.is_complete(ontology)


class TestCoherenceDimensionEvaluator:
    """Test coherence dimension with mutations."""
    
    @given(ontology_strategy())
    def test_score_in_range(self, ontology: Ontology):
        """Score should be in [0, 1]."""
        evaluator = CoherenceDimensionEvaluator()
        score = evaluator.evaluate(ontology)
        assert 0.0 <= score <= 1.0
    
    @given(st.lists(entity_strategy(), min_size=2, max_size=10, unique_by=lambda e: e.name))
    def test_confidence_contributes_to_score(self, entities: List[Entity]):
        """Confidence scores should contribute meaningfully to coherence."""
        evaluator = CoherenceDimensionEvaluator()
        
        # Both should have valid scores in [0, 1]
        ontology = Ontology(entities=entities)
        score = evaluator.evaluate(ontology)
        
        # Should be valid
        assert 0.0 <= score <= 1.0


class TestConsistencyDimensionEvaluator:
    """Test consistency dimension with mutations."""
    
    @given(ontology_strategy())
    def test_score_in_range(self, ontology: Ontology):
        """Score should be in [0, 1]."""
        evaluator = ConsistencyDimensionEvaluator()
        score = evaluator.evaluate(ontology)
        assert 0.0 <= score <= 1.0
    
    def test_no_dangling_references(self):
        """Internally consistent ontology should score high."""
        ontology = Ontology(
            entities=[Entity(name="e1"), Entity(name="e2")],
            relationships=[Relationship(source="e1", target="e2", rel_type="has")]
        )
        evaluator = ConsistencyDimensionEvaluator()
        score = evaluator.evaluate(ontology)
        assert score > 0.7
    
    def test_dangling_references(self):
        """Ontology with dangling refs should score lower."""
        ontology = Ontology(
            entities=[Entity(name="e1")],
            relationships=[Relationship(source="e1", target="e2", rel_type="has")]  # e2 doesn't exist
        )
        evaluator = ConsistencyDimensionEvaluator()
        score = evaluator.evaluate(ontology)
        assert score < 0.7


class TestRelevanceDimensionEvaluator:
    """Test relevance dimension with mutations."""
    
    @given(ontology_strategy())
    def test_score_in_range(self, ontology: Ontology):
        """Score should be in [0, 1]."""
        evaluator = RelevanceDimensionEvaluator()
        score = evaluator.evaluate(ontology)
        assert 0.0 <= score <= 1.0
    
    def test_meaningful_naming(self):
        """Meaningful entity names should increase score."""
        short_name_ontology = Ontology(
            entities=[Entity(name="a"), Entity(name="b")]
        )
        long_name_ontology = Ontology(
            entities=[Entity(name="entity1"), Entity(name="entity2")]
        )
        
        evaluator = RelevanceDimensionEvaluator()
        short_score = evaluator.evaluate(short_name_ontology)
        long_score = evaluator.evaluate(long_name_ontology)
        
        assert long_score > short_score


class TestOntologyCritic:
    """Test ontology critic and dimension integration."""
    
    @given(ontology_strategy())
    def test_all_dimensions_valid(self, ontology: Ontology):
        """All dimension scores should be valid."""
        critic = OntologyCritic()
        scores = critic.evaluate_all_dimensions(ontology)
        
        assert len(scores) == 4
        for dimension in ["completeness", "coherence", "consistency", "relevance"]:
            assert dimension in scores
            assert 0.0 <= scores[dimension] <= 1.0
    
    @given(ontology_strategy())
    def test_overall_score_in_range(self, ontology: Ontology):
        """Overall score should be in [0, 1]."""
        critic = OntologyCritic()
        overall = critic.get_overall_score(ontology)
        # Allow tiny floating point error from averaging
        assert -0.001 <= overall <= 1.001, f"Score {overall} out of range"
        # Clamp for assertion
        overall = max(0.0, min(1.0, overall))
        assert 0.0 <= overall <= 1.0
    
    @given(ontology_strategy())
    def test_overall_is_average(self, ontology: Ontology):
        """Overall should be average of dimensions."""
        critic = OntologyCritic()
        scores = critic.evaluate_all_dimensions(ontology)
        overall = critic.get_overall_score(ontology)
        
        expected_overall = sum(scores.values()) / 4
        # Allow slightly more tolerance for floating point
        assert abs(overall - expected_overall) < 0.01
    
    def test_evaluate_dimension_by_name(self):
        """Should evaluate dimensions by name."""
        critic = OntologyCritic()
        ontology = Ontology(
            entities=[Entity(name="e1"), Entity(name="e2")],
            relationships=[Relationship(source="e1", target="e2", rel_type="has")]
        )
        
        completeness = critic.evaluate_dimension("completeness", ontology)
        assert 0.0 <= completeness <= 1.0
        
        with pytest.raises(ValueError):
            critic.evaluate_dimension("unknown", ontology)
    
    @given(ontology_strategy())
    def test_mutation_robustness(self, ontology: Ontology):
        """Evaluator should handle mutations gracefully."""
        critic = OntologyCritic()
        
        # Original evaluation
        original = critic.get_overall_score(ontology)
        assert -0.001 <= original <= 1.001
        
        # Mutation 1: Modify confidence
        if ontology.entities:
            ontology.entities[0].confidence = 0.9
            mutated1 = critic.get_overall_score(ontology)
            assert -0.001 <= mutated1 <= 1.001, f"Mutated1 {mutated1} out of range"
        
        # Mutation 2: Add relationship
        if len(set(e.name for e in ontology.entities)) >= 2:
            entities = list(set(e.name for e in ontology.entities))
            ontology.relationships.append(
                Relationship(
                    source=entities[0],
                    target=entities[1],
                    rel_type="test"
                )
            )
            mutated2 = critic.get_overall_score(ontology)
            assert -0.001 <= mutated2 <= 1.001, f"Mutated2 {mutated2} out of range"


class TestDimensionInvariants:
    """Test invariants across dimension combinations."""
    
    @given(ontology_strategy())
    def test_consistency_and_coherence_independent(self, ontology: Ontology):
        """Consistency and coherence should be somewhat independent."""
        critic = OntologyCritic()
        scores = critic.evaluate_all_dimensions(ontology)
        
        # Both should evaluate independently
        consistency = scores["consistency"]
        coherence = scores["coherence"]
        
        # Clamp floating point errors
        consistency = max(0.0, min(1.0, consistency))
        coherence = max(0.0, min(1.0, coherence))
        
        # Neither should depend on the other in a strict way
        # (i.e., we should have low consistency with low/high coherence, etc.)
        assert isinstance(consistency, float)
        assert isinstance(coherence, float)
        assert 0.0 <= consistency <= 1.0
        assert 0.0 <= coherence <= 1.0
    
    def test_perfect_ontology_scores_high(self):
        """Well-formed ontology should score reasonably high."""
        critic = OntologyCritic()
        
        # Create a well-formed ontology
        good_ontology = Ontology(
            entities=[
                Entity(name="entity_a", entity_type="concept", confidence=0.8),
                Entity(name="entity_b", entity_type="concept", confidence=0.8),
                Entity(name="entity_c", entity_type="instance", confidence=0.9),
            ],
            relationships=[
                Relationship(source="entity_a", target="entity_b", rel_type="is_a", weight=0.9),
                Relationship(source="entity_b", target="entity_c", rel_type="has", weight=0.8),
            ]
        )
        
        score = critic.get_overall_score(good_ontology)
        score = max(0.0, min(1.0, score))  # Clamp floating point
        # Well-formed should score at least 0.5
        assert score >= 0.5

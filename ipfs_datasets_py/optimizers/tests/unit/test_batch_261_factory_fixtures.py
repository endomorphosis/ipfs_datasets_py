"""Batch 261: Factory Fixture Migration Tests

This test suite demonstrates migrating from local helper functions to centralized
factory fixtures in conftest.py. It validates all factory patterns and provides
migration examples for common test patterns.

Test Coverage:
    - Basic ontology dict creation (replaces _make_ontology)
    - Random seeded ontologies (replaces generate_random_ontology)
    - Sparse/dense relationship patterns
    - Domain-specific ontologies (legal, medical, business)
    - Empty/minimal ontologies
    - Entity and relationship factories
    - CriticScore and extraction result factories
    - Component factories (Generator, Critic, Pipeline)

Migration Patterns:
    OLD: def _make_ontology(n, m): return {"entities": [...], "relationships": [...]}
    NEW: Use ontology_dict_factory(entity_count=n, relationship_count=m)
    
    OLD: def generate_random_ontology(n, m, seed): ...
    NEW: Use random_ontology_factory(entity_count=n, relationship_count=m, seed=seed)
    
    OLD: sparse_ont = {"entities": [...10...], "relationships": [...1...]}
    NEW: Use sparse_ontology_factory(entity_count=10, relationship_count=1)
"""

import pytest
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))


# ═══════════════════════════════════════════════════════════════════════════
# Basic Ontology Dict Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestOntologyDictFactory:
    """Test ontology_dict_factory - replaces _make_ontology, create_sample_ontology."""
    
    def test_default_ontology_creation(self, ontology_dict_factory):
        """
        GIVEN: ontology_dict_factory with no parameters
        WHEN: Creating default ontology
        THEN: Returns 3 entities, 2 relationships with sensible defaults
        
        MIGRATION: Replaces: def _make_ontology(): return {"entities": [...3...], ...}
        """
        ont = ontology_dict_factory()
        
        assert "entities" in ont
        assert "relationships" in ont
        assert len(ont["entities"]) == 3
        assert len(ont["relationships"]) == 2
        
        # Verify entity structure
        for entity in ont["entities"]:
            assert "id" in entity
            assert "text" in entity
            assert "type" in entity
            assert "confidence" in entity
            assert 0.0 <= entity["confidence"] <= 1.0
    
    def test_custom_size_ontology(self, ontology_dict_factory):
        """
        GIVEN: Entity count and relationship count parameters
        WHEN: Creating custom-sized ontology
        THEN: Returns ontology with specified sizes
        
        MIGRATION: Replaces: def _make_ontology(n_entities, n_rels): ...
        """
        ont = ontology_dict_factory(entity_count=10, relationship_count=8)
        
        assert len(ont["entities"]) == 10
        assert len(ont["relationships"]) == 8
        
        # Verify relationships reference valid entities
        entity_ids = {e["id"] for e in ont["entities"]}
        for rel in ont["relationships"]:
            assert rel["source_id"] in entity_ids
            assert rel["target_id"] in entity_ids
    
    def test_domain_specific_ontology(self, ontology_dict_factory):
        """
        GIVEN: Domain parameter
        WHEN: Creating domain-specific ontology
        THEN: Returns ontology with domain metadata
        
        MIGRATION: Replaces: def _make_legal_ontology(): ...
        """
        legal_ont = ontology_dict_factory(domain="legal")
        
        assert "metadata" in legal_ont
        assert legal_ont["metadata"]["domain"] == "legal"
    
    def test_custom_entity_types(self, ontology_dict_factory):
        """
        GIVEN: Custom entity types list
        WHEN: Creating ontology with specified types
        THEN: Returns entities with only those types
        
        MIGRATION: Replaces: entities = [{"type": random.choice(types)} for ...]
        """
        types = ["Contract", "Clause", "Party"]
        ont = ontology_dict_factory(entity_count=6, entity_types=types)
        
        entity_types = [e["type"] for e in ont["entities"]]
        assert all(t in types for t in entity_types)


# ═══════════════════════════════════════════════════════════════════════════
# Random Ontology Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRandomOntologyFactory:
    """Test random_ontology_factory - replaces generate_random_ontology."""
    
    def test_reproducible_with_seed(self, random_ontology_factory):
        """
        GIVEN: Same seed value
        WHEN: Creating two random ontologies
        THEN: Returns identical ontologies
        
        MIGRATION: Replaces: def generate_random_ontology(n, m, seed): random.seed(seed); ...
        """
        ont1 = random_ontology_factory(entity_count=5, relationship_count=3, seed=42)
        ont2 = random_ontology_factory(entity_count=5, relationship_count=3, seed=42)
        
        assert ont1["entities"] == ont2["entities"]
        assert ont1["relationships"] == ont2["relationships"]
    
    def test_different_seeds_produce_different_ontologies(self, random_ontology_factory):
        """
        GIVEN: Different seed values
        WHEN: Creating two random ontologies
        THEN: Returns different ontologies
        """
        ont1 = random_ontology_factory(entity_count=5, seed=42)
        ont2 = random_ontology_factory(entity_count=5, seed=43)
        
        # At least one entity should differ
        assert ont1["entities"] != ont2["entities"]
    
    def test_random_confidence_values(self, random_ontology_factory):
        """
        GIVEN: Random ontology with seed
        WHEN: Checking entity confidences
        THEN: Confidence values vary across entities
        """
        ont = random_ontology_factory(entity_count=10, seed=100)
        
        confidences = [e["confidence"] for e in ont["entities"]]
        assert len(set(confidences)) > 1  # At least some variation
        assert all(0.0 <= c <= 1.0 for c in confidences)


# ═══════════════════════════════════════════════════════════════════════════
# Sparse/Dense Ontology Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSparseAndDenseFactories:
    """Test sparse_ontology_factory and dense_ontology_factory."""
    
    def test_sparse_ontology_low_density(self, sparse_ontology_factory):
        """
        GIVEN: Many entities, few relationships
        WHEN: Creating sparse ontology
        THEN: Returns low relationship-to-entity ratio
        
        MIGRATION: Replaces: sparse_ont = {"entities": [...20...], "relationships": [...2...]}
        """
        ont = sparse_ontology_factory(entity_count=20, relationship_count=2)
        
        assert len(ont["entities"]) == 20
        assert len(ont["relationships"]) == 2
        
        density = len(ont["relationships"]) / len(ont["entities"])
        assert density < 0.5  # Very sparse (< 0.5 relationships per entity)
    
    def test_dense_ontology_high_density(self, dense_ontology_factory):
        """
        GIVEN: Entity count and density factor
        WHEN: Creating dense ontology
        THEN: Returns high relationship-to-entity ratio
        
        MIGRATION: Replaces: dense_ont with manual 2x-3x relationship creation
        """
        ont = dense_ontology_factory(entity_count=10, density_factor=2.5)
        
        assert len(ont["entities"]) == 10
        assert len(ont["relationships"]) == 25  # 10 * 2.5
        
        density = len(ont["relationships"]) / len(ont["entities"])
        assert density >= 2.0  # Dense (>= 2.0 relationships per entity)
    
    def test_sparse_vs_dense_comparison(self, sparse_ontology_factory, dense_ontology_factory):
        """
        GIVEN: Sparse and dense ontologies with same entity count
        WHEN: Comparing relationship counts
        THEN: Dense has significantly more relationships
        """
        sparse = sparse_ontology_factory(entity_count=15, relationship_count=3)
        dense = dense_ontology_factory(entity_count=15, density_factor=3.0)
        
        assert len(dense["relationships"]) > len(sparse["relationships"]) * 5


# ═══════════════════════════════════════════════════════════════════════════
# Domain-Specific Ontology Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestDomainSpecificOntologyFactory:
    """Test domain_specific_ontology_factory - replaces domain helper functions."""
    
    def test_legal_domain_ontology(self, domain_specific_ontology_factory):
        """
        GIVEN: Legal domain
        WHEN: Creating domain-specific ontology
        THEN: Returns legal entity types (Contract, Clause, Party, etc.)
        
        MIGRATION: Replaces: def _make_legal_ontology(): ...
        """
        legal_ont = domain_specific_ontology_factory(domain="legal", entity_count=10)
        
        assert len(legal_ont["entities"]) == 10
        assert legal_ont["metadata"]["domain"] == "legal"
        
        legal_types = {"Contract", "Clause", "Party", "Law", "Statute", "Case", "Precedent"}
        entity_types = {e["type"] for e in legal_ont["entities"]}
        assert entity_types.issubset(legal_types)
    
    def test_medical_domain_ontology(self, domain_specific_ontology_factory):
        """
        GIVEN: Medical domain
        WHEN: Creating domain-specific ontology
        THEN: Returns medical entity types (Patient, Diagnosis, Treatment, etc.)
        
        MIGRATION: Replaces: def _make_medical_ontology(): ...
        """
        medical_ont = domain_specific_ontology_factory(domain="medical", entity_count=12)
        
        assert len(medical_ont["entities"]) == 12
        assert medical_ont["metadata"]["domain"] == "medical"
        
        medical_types = {"Patient", "Diagnosis", "Treatment", "Symptom", "Medication", "Procedure", "Doctor"}
        entity_types = {e["type"] for e in medical_ont["entities"]}
        assert entity_types.issubset(medical_types)
    
    def test_business_domain_ontology(self, domain_specific_ontology_factory):
        """
        GIVEN: Business domain
        WHEN: Creating domain-specific ontology
        THEN: Returns business entity types (Company, Employee, Product, etc.)
        """
        business_ont = domain_specific_ontology_factory(domain="business", entity_count=8)
        
        assert business_ont["metadata"]["domain"] == "business"
        
        business_types = {"Company", "Employee", "Product", "Service", "Transaction", "Department", "Asset"}
        entity_types = {e["type"] for e in business_ont["entities"]}
        assert entity_types.issubset(business_types)


# ═══════════════════════════════════════════════════════════════════════════
# Empty/Minimal Ontology Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEmptyAndMinimalFactories:
    """Test empty_ontology_factory and minimal_ontology_factory."""
    
    def test_empty_ontology(self, empty_ontology_factory):
        """
        GIVEN: No parameters
        WHEN: Creating empty ontology
        THEN: Returns 0 entities, 0 relationships
        
        MIGRATION: Replaces: empty_ont = {"entities": [], "relationships": []}
        """
        ont = empty_ontology_factory()
        
        assert ont["entities"] == []
        assert ont["relationships"] == []
        assert "metadata" in ont
    
    def test_empty_ontology_with_domain(self, empty_ontology_factory):
        """
        GIVEN: Domain parameter
        WHEN: Creating empty ontology
        THEN: Returns empty ontology with domain metadata
        """
        ont = empty_ontology_factory(domain="legal")
        
        assert len(ont["entities"]) == 0
        assert ont["metadata"]["domain"] == "legal"
    
    def test_minimal_ontology_default(self, minimal_ontology_factory):
        """
        GIVEN: No parameters
        WHEN: Creating minimal ontology
        THEN: Returns 2 entities, 1 relationship
        
        MIGRATION: Replaces: def _minimal_ontology(): return {"entities": [...2...], ...}
        """
        ont = minimal_ontology_factory()
        
        assert len(ont["entities"]) == 2
        assert len(ont["relationships"]) == 1
    
    def test_minimal_ontology_custom_size(self, minimal_ontology_factory):
        """
        GIVEN: Custom entity/relationship counts
        WHEN: Creating minimal ontology
        THEN: Returns ontology with specified small size
        """
        ont = minimal_ontology_factory(entity_count=3, relationship_count=2)
        
        assert len(ont["entities"]) == 3
        assert len(ont["relationships"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Entity and Relationship Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEntityAndRelationshipFactories:
    """Test entity_factory, entities_factory, relationship_factory, relationships_factory."""
    
    def test_single_entity_creation(self, entity_factory):
        """
        GIVEN: Entity factory with custom parameters
        WHEN: Creating single entity
        THEN: Returns Entity dataclass instance
        
        MIGRATION: Replaces: def _make_entity(eid, conf): return Entity(...)
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        
        entity = entity_factory(id="e1", text="Alice", type="Person", confidence=0.95)
        
        assert isinstance(entity, Entity)
        assert entity.id == "e1"
        assert entity.text == "Alice"
        assert entity.type == "Person"
        assert entity.confidence == 0.95
    
    def test_multiple_entities_creation(self, entities_factory):
        """
        GIVEN: Entities factory with count parameter
        WHEN: Creating multiple entities
        THEN: Returns list of Entity instances with incrementing IDs
        
        MIGRATION: Replaces: entities = [_make_entity(f"e{i}") for i in range(5)]
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        
        entities = entities_factory(count=5)
        
        assert len(entities) == 5
        assert all(isinstance(e, Entity) for e in entities)
        assert [e.id for e in entities] == ["e1", "e2", "e3", "e4", "e5"]
    
    def test_single_relationship_creation(self, relationship_factory):
        """
        GIVEN: Relationship factory with source/target IDs
        WHEN: Creating single relationship
        THEN: Returns Relationship dataclass instance
        
        MIGRATION: Replaces: def _make_rel(sid, tid): return Relationship(...)
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        rel = relationship_factory(source_id="e1", target_id="e2", type="knows")
        
        assert isinstance(rel, Relationship)
        assert rel.source_id == "e1"
        assert rel.target_id == "e2"
        assert rel.type == "knows"
    
    def test_multiple_relationships_creation(self, relationships_factory):
        """
        GIVEN: Relationships factory with count parameter
        WHEN: Creating multiple relationships
        THEN: Returns list of Relationship instances
        
        MIGRATION: Replaces: rels = [_make_rel(f"e{i}", f"e{i+1}") for i in range(5)]
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        
        rels = relationships_factory(count=5, entity_count=10)
        
        assert len(rels) == 5
        assert all(isinstance(r, Relationship) for r in rels)


# ═══════════════════════════════════════════════════════════════════════════
# CriticScore Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCriticScoreFactory:
    """Test critic_score_factory - replaces manual CriticScore creation."""
    
    def test_default_critic_score(self, critic_score_factory):
        """
        GIVEN: Critic score factory with no parameters
        WHEN: Creating default critic score
        THEN: Returns CriticScore with ~0.80 dimension values
        
        MIGRATION: Replaces: score = CriticScore(completeness=0.8, consistency=0.82, ...)
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
        
        score = critic_score_factory()
        
        assert isinstance(score, CriticScore)
        assert 0.75 <= score.overall <= 0.85
        assert 0.75 <= score.completeness <= 0.85
        assert len(score.strengths) > 0
        assert len(score.weaknesses) > 0
    
    def test_custom_dimension_scores(self, critic_score_factory):
        """
        GIVEN: Custom dimension values
        WHEN: Creating critic score
        THEN: Returns CriticScore with specified dimensions
        """
        score = critic_score_factory(
            completeness=0.90,
            consistency=0.85,
            clarity=0.88,
        )
        
        assert score.completeness == 0.90
        assert score.consistency == 0.85
        assert score.clarity == 0.88


# ═══════════════════════════════════════════════════════════════════════════
# Component Factory Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestComponentFactories:
    """Test generator, critic, optimizer, and pipeline factories."""
    
    def test_ontology_generator_factory(self, ontology_generator_factory):
        """
        GIVEN: Generator factory
        WHEN: Creating generator
        THEN: Returns OntologyGenerator instance
        
        MIGRATION: Replaces: def _make_generator(): return OntologyGenerator()
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        
        generator = ontology_generator_factory()
        
        assert isinstance(generator, OntologyGenerator)
    
    def test_ontology_critic_factory(self, ontology_critic_factory):
        """
        GIVEN: Critic factory
        WHEN: Creating critic
        THEN: Returns OntologyCritic instance
        
        MIGRATION: Replaces: def _make_critic(): return OntologyCritic(use_llm=False)
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        
        critic = ontology_critic_factory(use_llm=False)
        
        assert isinstance(critic, OntologyCritic)
    
    def test_ontology_pipeline_factory(self, ontology_pipeline_factory):
        """
        GIVEN: Pipeline factory
        WHEN: Creating pipeline
        THEN: Returns OntologyPipeline instance with specified domain
        
        MIGRATION: Replaces: pipeline = OntologyPipeline(domain="legal", use_llm=False)
        """
        from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
        
        pipeline = ontology_pipeline_factory(domain="legal", use_llm=False)
        
        assert isinstance(pipeline, OntologyPipeline)
        assert pipeline.domain == "legal"


# ═══════════════════════════════════════════════════════════════════════════
# TypedDict Factory Tests (for ontology_types.py structures)
# ═══════════════════════════════════════════════════════════════════════════


class TestTypedDictFactories:
    """Test TypedDict factories for plain dict structures."""
    
    def test_entity_typeddict_factory(self, entity_typeddict_factory):
        """
        GIVEN: Entity TypedDict factory
        WHEN: Creating entity dict
        THEN: Returns plain dict conforming to Entity TypedDict schema
        
        MIGRATION: Replaces: entity_dict = {"id": "e1", "text": "Alice", "type": "Person", ...}
        """
        entity = entity_typeddict_factory(id="e1", text="Alice", type="Person")
        
        assert isinstance(entity, dict)
        assert entity["id"] == "e1"
        assert entity["text"] == "Alice"
        assert entity["type"] == "Person"
        assert "confidence" in entity
    
    def test_relationship_typeddict_factory(self, relationship_typeddict_factory):
        """
        GIVEN: Relationship TypedDict factory
        WHEN: Creating relationship dict
        THEN: Returns plain dict conforming to Relationship TypedDict schema
        """
        rel = relationship_typeddict_factory(source_id="e1", target_id="e2", type="knows")
        
        assert isinstance(rel, dict)
        assert rel["source_id"] == "e1"
        assert rel["target_id"] == "e2"
        assert rel["type"] == "knows"
    
    def test_critic_score_typeddict_factory(self, critic_score_typeddict_factory):
        """
        GIVEN: CriticScore TypedDict factory
        WHEN: Creating score dict
        THEN: Returns plain dict conforming to CriticScore TypedDict schema
        """
        score = critic_score_typeddict_factory(overall=0.85, completeness=0.90)
        
        assert isinstance(score, dict)
        assert score["overall"] == 0.85
        assert score.get("completeness") == 0.90


# ═══════════════════════════════════════════════════════════════════════════
# Integration Tests (demonstrating multi-factory workflows)
# ═══════════════════════════════════════════════════════════════════════════


class TestFactoryIntegration:
    """Test realistic workflows combining multiple factories."""
    
    def test_generate_and_critique_workflow(
        self,
        ontology_dict_factory,
        ontology_generator_factory,
        ontology_critic_factory,
        generation_context_factory
    ):
        """
        GIVEN: Generator, critic, and context factories
        WHEN: Performing generate → evaluate workflow
        THEN: Successfully generates ontology and evaluates it
        
        MIGRATION: Demonstrates replacing entire test setup with factories
        """
        # Setup using factories
        generator = ontology_generator_factory(use_ipfs_accelerate=False)
        critic = ontology_critic_factory(use_llm=False)
        context = generation_context_factory(domain="legal")
        
        # Generate ontology
        ontology = generator.generate_ontology("Alice sues Bob for breach of contract", context)
        
        # Evaluate ontology
        score = critic.evaluate_ontology(ontology, context)
        
        assert isinstance(ontology, dict)
        assert "entities" in ontology
        assert 0.0 <= score.overall <= 1.0
    
    def test_comparison_of_sparse_vs_dense_patterns(
        self,
        sparse_ontology_factory,
        dense_ontology_factory,
        ontology_critic_factory,
        generation_context_factory
    ):
        """
        GIVEN: Sparse and dense ontology factories
        WHEN: Evaluating both patterns
        THEN: Dense ontologies have higher relationship_coherence scores
        
        MIGRATION: Replaces manual sparse/dense construction
        """
        critic = ontology_critic_factory(backend_config=None, use_llm=False)
        context = generation_context_factory(domain="general")
        
        sparse_ont = sparse_ontology_factory(entity_count=10, relationship_count=2)
        dense_ont = dense_ontology_factory(entity_count=10, density_factor=2.5)
        
        sparse_score = critic.evaluate_ontology(sparse_ont, context)
        dense_score = critic.evaluate_ontology(dense_ont, context)
        
        # Dense ontology should have better relationship coherence
        assert dense_score.relationship_coherence >= sparse_score.relationship_coherence
    
    def test_domain_specific_evaluation_workflow(
        self,
        domain_specific_ontology_factory,
        ontology_critic_factory,
        generation_context_factory
    ):
        """
        GIVEN: Domain-specific ontology and context
        WHEN: Evaluating legal vs medical domains
        THEN: Domain alignment scores reflect matching domains
        """
        critic = ontology_critic_factory(use_llm=False)
        
        legal_ont = domain_specific_ontology_factory(domain="legal", entity_count=8)
        legal_ctx = generation_context_factory(domain="legal")
        
        medical_ont = domain_specific_ontology_factory(domain="medical", entity_count=8)
        medical_ctx = generation_context_factory(domain="medical")
        
        legal_score = critic.evaluate_ontology(legal_ont, legal_ctx)
        medical_score = critic.evaluate_ontology(medical_ont, medical_ctx)
        
        # Both should have decent domain alignment when matched
        assert legal_score.domain_alignment > 0.5
        assert medical_score.domain_alignment > 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

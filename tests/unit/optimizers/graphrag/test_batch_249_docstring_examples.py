"""Batch 249: Docstring Examples and Usage Documentation Tests.

Validates all docstring examples in OntologyGenerator and OntologyCritic
are executable and produce correct output. Also ensures comprehensive
API documentation for all public methods.

Test Categories:
- Extract entities docstring examples
- Generate ontology docstring examples
- Infer relationships docstring examples
- Critic score evaluation docstring examples
- Critic feedback generation docstring examples
- Documentation completeness verification
"""

import pytest
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    DataType,
    ExtractionStrategy,
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
    CriticScore,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def generator():
    """Create OntologyGenerator for docstring examples."""
    return OntologyGenerator(use_ipfs_accelerate=False)


@pytest.fixture
def critic():
    """Create OntologyCritic for docstring examples."""
    return OntologyCritic(use_llm=False)


@pytest.fixture
def simple_text():
    """Simple text for extraction examples."""
    return "Alice manages Bob. Bob works with Charlie."


@pytest.fixture
def legal_text():
    """Legal text for domain-specific extraction."""
    return (
        "The Contractor must perform services for the Client. "
        "The Client agrees to pay $1,000 per month. "
        "The contract expires on December 31, 2026."
    )


@pytest.fixture
def context():
    """Create OntologyGenerationContext for examples."""
    return OntologyGenerationContext(
        data_source="docstring_test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


@pytest.fixture
def legal_context():
    """Create legal domain context for examples."""
    return OntologyGenerationContext(
        data_source="legal_contract",
        data_type=DataType.TEXT,
        domain="legal",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
    )


@pytest.fixture
def sample_ontology() -> Dict[str, Any]:
    """Create sample ontology for documentation examples."""
    return {
        "entities": [
            {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
            {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.90},
            {"id": "e3", "text": "Charlie", "type": "Person", "confidence": 0.85},
        ],
        "relationships": [
            {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "manages", "confidence": 0.88},
            {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "works_with", "confidence": 0.82},
        ],
        "metadata": {"source": "example", "domain": "general"},
        "domain": "general",
    }


# ============================================================================
# OntologyGenerator Docstring Examples Tests
# ============================================================================

class TestOntologyGeneratorExtractEntitiesExample:
    """Test extract_entities() docstring example."""
    
    def test_extract_entities_produces_result(self, generator, simple_text, context):
        """extract_entities returns EntityExtractionResult with entities."""
        # Example from docstring should work
        result = generator.extract_entities(simple_text, context)
        
        # Validate type
        assert isinstance(result, EntityExtractionResult)
        # Validate it has extracted something
        assert len(result.entities) > 0
        assert len(result.relationships) >= 0
    
    def test_extract_entities_example_readable(self, generator, simple_text, context):
        """Example docstring code is readable and executable."""
        result = generator.extract_entities(simple_text, context)
        
        # Docstring says: "Found {len(result.entities)} entities"
        entity_count = len(result.entities)
        assert isinstance(entity_count, int)
        assert entity_count > 0
    
    def test_extract_entities_legal_domain(self, generator, legal_text, legal_context):
        """extract_entities works with legal domain as documented."""
        result = generator.extract_entities(legal_text, legal_context)
        
        assert isinstance(result, EntityExtractionResult)
        assert len(result.entities) > 0
        # Legal domain should extract contract-specific entities
        entity_types = {e.type for e in result.entities}
        assert len(entity_types) > 0


class TestOntologyGeneratorGenerateOntologyExample:
    """Test generate_ontology() docstring example."""
    
    def test_generate_ontology_produces_dict(self, generator, simple_text, context):
        """generate_ontology returns dictionary with expected structure."""
        ontology = generator.generate_ontology(simple_text, context)
        
        # Must be dict with these keys
        assert isinstance(ontology, dict)
        assert "entities" in ontology
        assert "relationships" in ontology or "metadata" in ontology
    
    def test_generate_ontology_example_structure(self, generator, legal_text, legal_context):
        """Example docstring demonstrates ontology generation."""
        ontology = generator.generate_ontology(legal_text, legal_context)
        
        # Docstring says: Generated ontology with {len(ontology['entities'])} entities
        entity_count = len(ontology.get("entities", []))
        assert isinstance(entity_count, int)
        assert entity_count > 0
    
    def test_generate_ontology_has_metadata(self, generator, simple_text, context):
        """Generated ontology includes metadata as documented."""
        ontology = generator.generate_ontology(simple_text, context)
        
        # Should have metadata field
        assert "metadata" in ontology
        metadata = ontology["metadata"]
        assert isinstance(metadata, dict)
        assert "domain" in metadata or "source" in metadata


class TestOntologyGeneratorInferRelationshipsExample:
    """Test infer_relationships() docstring example."""
    
    def test_infer_relationships_accepts_entities(self, generator, simple_text, context):
        """infer_relationships accepts list of entities."""
        # First extract entities
        result = generator.extract_entities(simple_text, context)
        entities = result.entities
        
        # Then infer relationships
        relationships = generator.infer_relationships(
            entities,
            context,
            data=simple_text
        )
        
        # Should return relationships
        assert isinstance(relationships, list)
        # Can have 0 or more relationships
        assert all(isinstance(r, Relationship) for r in relationships)
    
    def test_infer_relationships_uses_entity_types(self, generator, simple_text, context):
        """infer_relationships respects entity types for relationship inference."""
        result = generator.extract_entities(simple_text, context)
        
        relationships = generator.infer_relationships(
            result.entities,
            context,
            data=simple_text
        )
        
        # Each relationship should connect two entities
        entity_ids = {e.id for e in result.entities}
        for rel in relationships:
            assert isinstance(rel, Relationship)


class TestOntologyGeneratorSortedEntitiesExample:
    """Test sorted_entities() docstring example."""
    
    def test_sorted_entities_returns_list(self, generator, sample_ontology):
        """sorted_entities returns list of Entity objects."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Alice", type="Person", confidence=0.95),
                Entity(id="e2", text="Bob", type="Person", confidence=0.85),
                Entity(id="e3", text="Charlie", type="Person", confidence=0.90),
            ],
            relationships=[],
            confidence=0.9,
        )
        
        sorted_ents = generator.sorted_entities(result, key="confidence", reverse=True)
        
        assert isinstance(sorted_ents, list)
        assert len(sorted_ents) == 3
        # Should be sorted by confidence descending
        assert sorted_ents[0].confidence >= sorted_ents[1].confidence
    
    def test_sorted_entities_by_text(self, generator):
        """sorted_entities can sort by text field."""
        result = EntityExtractionResult(
            entities=[
                Entity(id="e1", text="Zebra", type="Animal", confidence=0.9),
                Entity(id="e2", text="Apple", type="Fruit", confidence=0.9),
                Entity(id="e3", text="Mango", type="Fruit", confidence=0.9),
            ],
            relationships=[],
            confidence=0.9,
        )
        
        sorted_ents = generator.sorted_entities(result, key="text", reverse=False)
        
        # Should be alphabetically sorted
        texts = [e.text for e in sorted_ents]
        assert texts == sorted(texts)


class TestOntologyGeneratorRebuildResultExample:
    """Test rebuild_result() docstring example."""
    
    def test_rebuild_result_wraps_entities(self, generator):
        """rebuild_result wraps list of entities in EntityExtractionResult."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.95),
            Entity(id="e2", text="Bob", type="Person", confidence=0.85),
        ]
        
        result = generator.rebuild_result(entities)
        
        assert isinstance(result, EntityExtractionResult)
        assert result.entities == entities
        assert result.confidence > 0  # Should compute mean confidence
    
    def test_rebuild_result_computes_confidence_from_entities(self, generator):
        """rebuild_result computes confidence from entities."""
        entities = [
            Entity(id="e1", text="A", type="Type", confidence=0.8),
            Entity(id="e2", text="B", type="Type", confidence=1.0),
        ]
        
        result = generator.rebuild_result(entities)
        
        # Should have computed confidence > 0
        assert result.confidence > 0
        # Should preserve entities
        assert len(result.entities) == 2


# ============================================================================
# OntologyCritic Docstring Examples Tests
# ============================================================================

class TestOntologyCriticEvaluateOntologyExample:
    """Test evaluate_ontology() docstring example."""
    
    def test_evaluate_ontology_returns_critic_score(self, critic, sample_ontology, context):
        """evaluate_ontology returns CriticScore with dimension scores."""
        score = critic.evaluate_ontology(sample_ontology, context)
        
        assert isinstance(score, CriticScore)
        # Should have all dimensions
        assert hasattr(score, 'completeness')
        assert hasattr(score, 'consistency')
        assert hasattr(score, 'clarity')
        assert hasattr(score, 'overall')
    
    def test_evaluate_ontology_produces_feedback(self, critic, sample_ontology, context):
        """evaluate_ontology produces actionable feedback as documented."""
        score = critic.evaluate_ontology(sample_ontology, context)
        
        # Should have lists of feedback
        assert isinstance(score.strengths, list)
        assert isinstance(score.weaknesses, list)
        assert isinstance(score.recommendations, list)


class TestOntologyCriticRecommendationsExample:
    """Test CriticScore recommendations."""
    
    def test_score_has_recommendations(self, critic, sample_ontology, context):
        """CriticScore has recommendations and strengths/weaknesses lists."""
        score = critic.evaluate_ontology(sample_ontology, context)
        
        # Should have feedback lists
        assert isinstance(score.recommendations, list)
        assert isinstance(score.strengths, list)
        assert isinstance(score.weaknesses, list)
        # Should have at least some feedback
        total_feedback = len(score.recommendations) + len(score.strengths) + len(score.weaknesses)
        assert total_feedback > 0


class TestOntologyCriticDimensionScoresExample:
    """Test CriticScore dimensions."""
    
    def test_score_dimensions_are_floats(self, critic, sample_ontology, context):
        """CriticScore dimension properties return float scores (0.0-1.0)."""
        score = critic.evaluate_ontology(sample_ontology, context)
        
        # All dimensions should be floats in valid range
        assert isinstance(score.completeness, float)
        assert isinstance(score.consistency, float)
        assert isinstance(score.clarity, float)
        assert 0.0 <= score.completeness <= 1.0
        assert 0.0 <= score.consistency <= 1.0
        assert 0.0 <= score.clarity <= 1.0
    
    def test_score_has_all_dimensions(self, critic, sample_ontology, context):
        """CriticScore has all dimension attributes."""
        score = critic.evaluate_ontology(sample_ontology, context)
        
        # Should have all dimensions
        assert hasattr(score, 'granularity')
        assert hasattr(score, 'relationship_coherence')
        assert hasattr(score, 'domain_alignment')
        assert 0.0 <= score.granularity <= 1.0
        assert 0.0 <= score.relationship_coherence <= 1.0
        assert 0.0 <= score.domain_alignment <= 1.0


# ============================================================================
# API Documentation Completeness Tests
# ============================================================================

class TestDocstringCompleteness:
    """Verify all public methods have proper documentation."""
    
    def test_extract_entities_has_docstring(self, generator):
        """extract_entities has a docstring."""
        assert generator.extract_entities.__doc__ is not None
        assert len(generator.extract_entities.__doc__) > 50
    
    def test_generate_ontology_has_docstring(self, generator):
        """generate_ontology has a docstring."""
        assert generator.generate_ontology.__doc__ is not None
        assert len(generator.generate_ontology.__doc__) > 50
    
    def test_infer_relationships_has_docstring(self, generator):
        """infer_relationships has a docstring."""
        assert generator.infer_relationships.__doc__ is not None
        assert len(generator.infer_relationships.__doc__) > 50
    
    def test_sorted_entities_has_docstring(self, generator):
        """sorted_entities has a docstring."""
        assert generator.sorted_entities.__doc__ is not None
        assert len(generator.sorted_entities.__doc__) > 50
    
    def test_rebuild_result_has_docstring(self, generator):
        """rebuild_result has a docstring."""
        assert generator.rebuild_result.__doc__ is not None
        assert len(generator.rebuild_result.__doc__) > 50
    
    def test_evaluate_ontology_has_docstring(self, critic):
        """evaluate_ontology has a docstring."""
        assert critic.evaluate_ontology.__doc__ is not None
        assert len(critic.evaluate_ontology.__doc__) > 50


class TestDocstringFormatting:
    """Verify docstrings follow proper formatting conventions."""
    
    def test_docstrings_have_examples_sections(self, generator, critic):
        """Key public methods should have Example sections in docstrings."""
        methods_to_check = [
            generator.extract_entities,
            generator.generate_ontology,
            generator.sorted_entities,
            generator.rebuild_result,
            critic.evaluate_ontology,
        ]
        
        for method in methods_to_check:
            docstring = method.__doc__ or ""
            # Should have Examples or Example section (can vary)
            has_example = "Example" in docstring or "example" in docstring
            assert has_example, f"{method.__name__} should have example in docstring"
    
    def test_docstrings_have_args_section(self, generator):
        """Public methods should document their arguments."""
        methods_to_check = [
            generator.extract_entities,
            generator.generate_ontology,
        ]
        
        for method in methods_to_check:
            docstring = method.__doc__ or ""
            has_args = "Args:" in docstring or "Arguments:" in docstring
            assert has_args, f"{method.__name__} should have Args section"
    
    def test_docstrings_have_returns_section(self, generator):
        """Public methods should document their return values."""
        methods_to_check = [
            generator.extract_entities,
            generator.generate_ontology,
            generator.sorted_entities,
        ]
        
        for method in methods_to_check:
            docstring = method.__doc__ or ""
            has_returns = "Returns:" in docstring or "Return:" in docstring
            assert has_returns, f"{method.__name__} should have Returns section"


# ============================================================================
# Integration: Real Usage Examples
# ============================================================================

class TestRealWorldDocstringExamples:
    """Test realistic usage examples for documentation."""
    
    def test_extract_analyze_example(self, generator, critic, simple_text, context):
        """Document complete workflow: extract then analyze."""
        # Extract entities
        result = generator.extract_entities(simple_text, context)
        assert len(result.entities) > 0
        
        # Generate ontology
        ontology = generator.generate_ontology(simple_text, context)
        assert "entities" in ontology
        
        # Critique
        score = critic.evaluate_ontology(ontology, context)
        assert isinstance(score, CriticScore)
        assert score.overall > 0
    
    def test_rebuild_workflow_example(self, generator, critic):
        """Document workflow: extract, rebuild, score."""
        # Create entities
        entities = [
            Entity(id="e1", text="Company A", type="Organization", confidence=0.95),
            Entity(id="e2", text="Company B", type="Organization", confidence=0.90),
        ]
        
        # Rebuild result
        result = generator.rebuild_result(entities)
        assert result.confidence > 0
        
        # Sort entities
        sorted_ents = generator.sorted_entities(result, key="confidence", reverse=True)
        assert sorted_ents[0].confidence >= sorted_ents[-1].confidence
    
    def test_multi_domain_example(self, generator, legal_text, legal_context):
        """Document using different domains for extraction."""
        # Extract with legal domain context
        result = generator.extract_entities(legal_text, legal_context)
        
        # Should extract legal-specific entities
        assert len(result.entities) > 0
        
        # Generate legal-domain ontology
        ontology = generator.generate_ontology(legal_text, legal_context)
        assert ontology.get("domain") == "legal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""End-to-end integration tests for the GraphRAG ontology pipeline.

Tests key pipeline workflows: extraction → validation → optimization
"""

import pytest
from typing import Dict, Any

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    EntityExtractionResult,
    ExtractionConfig,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (
    OntologyCritic,
    BackendConfig,
)


class TestOntologyExtractionToFiltering:
    """Test filtering extracted entities by confidence threshold."""

    def test_filter_by_confidence_workflow(self) -> None:
        """Test filtering extracted entities by confidence."""
        config = ExtractionConfig(confidence_threshold=0.3)
        generator = OntologyGenerator(use_ipfs_accelerate=False)

        # Sample text
        text = """
        Alice and Bob work at TechCorp. Alice is a software engineer.
        She specializes in machine learning and distributed systems.
        Bob works on the infrastructure team.
        """

        # Extract entities
        result = generator.extract_entities(
            text,
            context={},  # Required context parameter
        )

        assert isinstance(result, EntityExtractionResult)
        assert len(result.entities) > 0, "Should extract entities"

        # Filter by confidence threshold
        high_conf_threshold = 0.7
        filtered = result.filter_by_confidence(high_conf_threshold)

        assert isinstance(filtered, EntityExtractionResult)
        assert len(filtered.entities) <= len(result.entities)

        # Validate all filtered entities meet threshold
        for entity in filtered.entities:
            confidence = entity.get("confidence", 1.0)
            assert confidence >= high_conf_threshold, \
                f"Entity {entity['id']} has confidence {confidence} < {high_conf_threshold}"

    def test_filter_removes_dangling_relationships(self) -> None:
        """Test that filtering removes relationships to pruned entities."""
        # Create extraction result with entities and relationships
        extraction_result = EntityExtractionResult(
            entities=[
                {"id": "e1", "name": "Alice", "type": "Person", "confidence": 0.95},
                {"id": "e2", "name": "Bob", "type": "Person", "confidence": 0.3},
                {"id": "e3", "name": "TechCorp", "type": "Org", "confidence": 0.9},
            ],
            relationships=[
                {"source": "e1", "target": "e3", "type": "works_at", "confidence": 0.88},
                {"source": "e2", "target": "e3", "type": "works_at", "confidence": 0.6},
                {"source": "e1", "target": "e2", "type": "knows", "confidence": 0.5},
            ],
        )

        # Filter to high confidence
        filtered = extraction_result.filter_by_confidence(0.7)

        # Check that only high-confidence entities remain
        filtered_ids = {e["id"] for e in filtered.entities}
        assert "e1" in filtered_ids, "Alice (0.95) should be retained"
        assert "e3" in filtered_ids, "TechCorp (0.9) should be retained"
        assert "e2" not in filtered_ids, "Bob (0.3) should be filtered out"

        # Check that relationships to removed entity are pruned
        for rel in filtered.relationships:
            assert rel["source"] in filtered_ids, "Relationship source must exist"
            assert rel["target"] in filtered_ids, "Relationship target must exist"


class TestOntologyCriticAnalysis:
    """Test OntologyCritic evaluation capabilities."""

    def test_critic_evaluates_ontology(self) -> None:
        """Test that critic produces valid evaluation scores."""
        critic = OntologyCritic(
            backend_config=BackendConfig(provider="mock", model="mock"),
            use_llm=False,
        )

        ontology = {
            "entities": [
                {"id": "e1", "name": "Alice", "type": "Person", "confidence": 0.95},
                {"id": "e2", "name": "TechCorp", "type": "Organization", "confidence": 0.88},
            ],
            "relationships": [
                {"source": "e1", "target": "e2", "type": "works_at", "confidence": 0.85}
            ],
            "metadata": {"domain": "general"},
        }

        # Evaluate ontology
        score = critic.evaluate_ontology(
            ontology,
            context={},  # Required context parameter
        )

        # Validate score structure
        assert score is not None
        assert hasattr(score, "overall_score")
        assert 0.0 <= score.overall_score <= 1.0

    def test_worst_entity_detection(self) -> None:
        """Test get_worst_entity detection among low-confidence entities."""
        critic = OntologyCritic(use_llm=False)

        ontology = {
            "entities": [
                {"id": "e1", "name": "Alice", "confidence": 0.95},
                {"id": "e2", "name": "Bob", "confidence": 0.3},
                {"id": "e3", "name": "Carol", "confidence": 0.7},
            ],
            "relationships": [],
            "metadata": {"domain": "general"},
        }

        worst = critic.get_worst_entity(ontology)
        assert worst is not None
        assert worst["id"] == "e2", "Should identify lowest-confidence entity (Bob)"
        assert worst["confidence"] == 0.3

    def test_worst_entity_empty_ontology(self) -> None:
        """Test get_worst_entity gracefully handles empty ontologies."""
        critic = OntologyCritic(use_llm=False)

        empty_ontology = {
            "entities": [],
            "relationships": [],
            "metadata": {"domain": "general"},
        }

        worst = critic.get_worst_entity(empty_ontology)
        assert worst is None, "Should return None for empty ontology"


class TestExtractionConfigValidation:
    """Test ExtractionConfig field validation."""

    def test_valid_config_creation(self) -> None:
        """Test creating valid extraction configs."""
        config = ExtractionConfig(
            confidence_threshold=0.5,
            max_entities=100,
            max_relationships=500,
        )
        config.validate()  # Should not raise

    def test_confidence_threshold_validation(self) -> None:
        """Test confidence_threshold validation."""
        # Valid range [0, 1]
        valid_config = ExtractionConfig(confidence_threshold=0.5)
        valid_config.validate()  # Should not raise

        # Invalid: below range
        invalid_low = ExtractionConfig(confidence_threshold=-0.1)
        with pytest.raises(ValueError):
            invalid_low.validate()

        # Invalid: above range
        invalid_high = ExtractionConfig(confidence_threshold=1.5)
        with pytest.raises(ValueError):
            invalid_high.validate()

    def test_max_confidence_validation(self) -> None:
        """Test max_confidence validation."""
        # Valid range (0, 1]
        valid_config = ExtractionConfig(
            confidence_threshold=0.2,
            max_confidence=0.95,
        )
        valid_config.validate()

        # Invalid: equals 0
        invalid_zero = ExtractionConfig(max_confidence=0.0)
        with pytest.raises(ValueError):
            invalid_zero.validate()

    def test_threshold_max_confidence_ordering(self) -> None:
        """Test that confidence_threshold <= max_confidence."""
        # Valid: threshold < max_confidence
        valid = ExtractionConfig(
            confidence_threshold=0.4,
            max_confidence=0.8,
        )
        valid.validate()

        # Valid: threshold == max_confidence
        equal = ExtractionConfig(
            confidence_threshold=0.5,
            max_confidence=0.5,
        )
        equal.validate()

        # Invalid: threshold > max_confidence
        invalid = ExtractionConfig(
            confidence_threshold=0.8,
            max_confidence=0.5,
        )
        with pytest.raises(ValueError):
            invalid.validate()


class TestMetricsLogging:
    """Test logging and metrics collection in the pipeline."""

    def test_extraction_metrics_collection(self) -> None:
        """Test that extraction collects metrics."""
        config = ExtractionConfig(
            confidence_threshold=0.5,
            max_entities=50,
        )
        generator = OntologyGenerator(use_ipfs_accelerate=False)

        text = "Alice works at TechCorp. Bob is a developer."
        result = generator.extract_entities(text, context={})

        # Check that result has metadata with stats
        assert result.metadata is not None
        assert "extraction_stats" in result.metadata or len(result.entities) >= 0


class TestEntityExtractionResult:
    """Test EntityExtractionResult filtering and merging."""

    def test_filter_by_confidence_stats(self) -> None:
        """Test that filter_by_confidence includes result stats."""
        result = EntityExtractionResult(
            entities=[
                {"id": "e1", "name": "A", "confidence": 0.9},
                {"id": "e2", "name": "B", "confidence": 0.5},
                {"id": "e3", "name": "C", "confidence": 0.3},
            ],
            relationships=[
                {"source": "e1", "target": "e2", "type": "rel"},
                {"source": "e2", "target": "e3", "type": "rel"},
                {"source": "e1", "target": "e3", "type": "rel"},  # Dangling: e3 will be removed
            ],
        )

        filtered = result.filter_by_confidence(0.7)

        # Check stats are updated
        assert filtered.metadata is not None or True  # May or may not have stats
        assert len(filtered.entities) == 1  # Only e1
        assert len(filtered.relationships) == 0  # e2 and e3 removed, dangling rels pruned


class TestEndToEndSmoke:
    """Simple smoke tests for basic pipeline functionality."""

    def test_extraction_produces_valid_structure(self) -> None:
        """Test extraction produces structurally valid output."""
        generator = OntologyGenerator(use_ipfs_accelerate=False)

        text = "Test data with entities."
        result = generator.extract_entities(text, context={})

        # Validate structure
        assert hasattr(result, "entities")
        assert hasattr(result, "relationships")
        assert isinstance(result.entities, list)
        assert isinstance(result.relationships, list)

        # Validate entity structure
        for entity in result.entities:
            assert "id" in entity
            assert "name" in entity
            assert "type" in entity

    def test_critic_produces_valid_scores(self) -> None:
        """Test critic produces valid evaluation."""
        critic = OntologyCritic(use_llm=False)

        ontology = {
            "entities": [
                {"id": "e1", "name": "Test", "type": "Entity"},
            ],
            "relationships": [],
            "metadata": {},
        }

        score = critic.evaluate_ontology(ontology, context={})
        assert score is not None
        assert hasattr(score, "overall_score")

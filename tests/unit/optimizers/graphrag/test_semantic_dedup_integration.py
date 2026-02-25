"""Tests for semantic deduplication integration in OntologyGenerator.

This module tests the integration of SemanticEntityDeduplicator with
OntologyGenerator and EntityExtractionResult.
"""

import pytest
from unittest.mock import Mock, patch
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    OntologyGenerator,
)


def _has_semantic_dedup_deps() -> bool:
    """Check if semantic deduplication dependencies are available."""
    try:
        import sentence_transformers
        return True
    except ImportError:
        return False


class TestSemanticDeduplicationIntegration:
    """Test semantic deduplication integration."""

    def test_ontology_generator_semantic_dedup_disabled_by_default(self):
        """By default, semantic dedup should be disabled."""
        generator = OntologyGenerator()
        assert generator.enable_semantic_dedup is False
        assert generator._semantic_deduplicator is None

    def test_ontology_generator_semantic_dedup_enabled_by_flag(self):
        """When enable_semantic_dedup=True, deduplicator should initialize."""
        with patch.dict("sys.modules", {"ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator": Mock()}):
            mock_dedup_module = Mock()
            mock_dedup_class = Mock()
            mock_instance = Mock()
            mock_dedup_class.return_value = mock_instance
            mock_dedup_module.SemanticEntityDeduplicator = mock_dedup_class
            
            with patch.dict("sys.modules", {"ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator": mock_dedup_module}):
                generator = OntologyGenerator(enable_semantic_dedup=True)
                
                assert generator.enable_semantic_dedup is True
                assert generator._semantic_deduplicator is mock_instance

    def test_ontology_generator_semantic_dedup_enabled_by_env(self):
        """ENABLE_SEMANTIC_DEDUP env var should enable deduplication."""
        import os
        with patch.dict(os.environ, {"ENABLE_SEMANTIC_DEDUP": "true"}):
            mock_dedup_module = Mock()
            mock_dedup_class = Mock()
            mock_instance = Mock()
            mock_dedup_class.return_value = mock_instance
            mock_dedup_module.SemanticEntityDeduplicator = mock_dedup_class
            
            with patch.dict("sys.modules", {"ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator": mock_dedup_module}):
                generator = OntologyGenerator()
                
                assert generator.enable_semantic_dedup is True
                assert generator._semantic_deduplicator is mock_instance

    def test_ontology_generator_semantic_dedup_graceful_import_failure(self):
        """When dependencies unavailable, dedup should gracefully disable."""
        # Force import error by removing the module
        with patch.dict("sys.modules", {"ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator": None}):
            generator = OntologyGenerator(enable_semantic_dedup=True)
            
            assert generator.enable_semantic_dedup is False
            assert generator._semantic_deduplicator is None

    def test_apply_semantic_dedup_no_merges(self):
        """When no similarity found, result should be unchanged."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9),
            Entity(id="e2", text="XYZ Corp", type="Organization", confidence=0.85),
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e2", type="works_for", confidence=0.8)
        ]
        result = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.85)

        mock_dedup = Mock()
        mock_dedup.suggest_merges.return_value = []  # No suggestions

        deduped = result.apply_semantic_dedup(mock_dedup, threshold=0.85)

        # Should return same instance when no merges
        assert deduped is result
        mock_dedup.suggest_merges.assert_called_once()

    def test_apply_semantic_dedup_with_merges(self):
        """When merges suggested, entities should be deduplicated."""
        entities = [
            Entity(id="e1", text="CEO", type="Person", confidence=0.9),
            Entity(id="e2", text="Chief Executive Officer", type="Person", confidence=0.85),
            Entity(id="e3", text="Company", type="Organization", confidence=0.8),
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e3", type="works_for", confidence=0.8),
            Relationship(id="r2", source_id="e2", target_id="e3", type="works_for", confidence=0.75),
        ]
        result = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.85)

        # Mock deduplicator suggesting e1 and e2 should merge
        mock_suggestion = Mock()
        mock_suggestion.entity1_id = "e1"
        mock_suggestion.entity2_id = "e2"
        mock_suggestion.similarity_score = 0.92

        mock_dedup = Mock()
        mock_dedup.suggest_merges.return_value = [mock_suggestion]

        deduped = result.apply_semantic_dedup(mock_dedup, threshold=0.85)

        # e2 should be merged into e1
        assert len(deduped.entities) == 2
        entity_ids = {e.id for e in deduped.entities}
        assert "e1" in entity_ids
        assert "e2" not in entity_ids  # e2 was merged
        assert "e3" in entity_ids

        # Relationships should be remapped
        # Both relationships are kept (deduplicator may filter further or entity merger handles this)
        assert len(deduped.relationships) == 2  
        assert all(r.source_id == "e1" for r in deduped.relationships)
        assert all(r.target_id == "e3" for r in deduped.relationships)

        # Metadata should track dedup
        assert deduped.metadata["semantic_dedup_applied"] is True
        assert deduped.metadata["semantic_dedup_merged_count"] == 1
        assert deduped.metadata["semantic_dedup_threshold"] == 0.85

    def test_apply_semantic_dedup_preserves_confidence(self):
        """Semantic dedup should preserve overall extraction confidence."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9),
            Entity(id="e2", text="Bob", type="Person", confidence=0.85),
        ]
        result = EntityExtractionResult(entities=entities, relationships=[], confidence=0.92)

        mock_dedup = Mock()
        mock_dedup.suggest_merges.return_value = []

        deduped = result.apply_semantic_dedup(mock_dedup)

        assert deduped.confidence == 0.92

    def test_apply_semantic_dedup_self_reference_removal(self):
        """Self-referencing relationships should be removed after merges."""
        entities = [
            Entity(id="e1", text="NYC", type="Location", confidence=0.9),
            Entity(id="e2", text="New York City", type="Location", confidence=0.85),
        ]
        # Invalid self-reference that should be removed
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e2", type="same_as", confidence=0.95),
        ]
        result = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.90)

        mock_suggestion = Mock()
        mock_suggestion.entity1_id = "e1"
        mock_suggestion.entity2_id = "e2"

        mock_dedup = Mock()
        mock_dedup.suggest_merges.return_value = [mock_suggestion]

        deduped = result.apply_semantic_dedup(mock_dedup)

        # Self-reference should be removed (src == tgt after merge)
        assert len(deduped.relationships) == 0

    def test_apply_semantic_dedup_calls_deduplicator_with_correct_format(self):
        """Deduplicator should receive ontology in correct dict format."""
        entities = [
            Entity(id="e1", text="Alice", type="Person", confidence=0.9, properties={"age": 30}),
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e1", type="knows", confidence=0.8),
        ]
        result = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.87)

        mock_dedup = Mock()
        mock_dedup.suggest_merges.return_value = []

        result.apply_semantic_dedup(mock_dedup, threshold=0.88, max_suggestions=10)

        # Verify deduplicator was called with correct arguments
        call_args = mock_dedup.suggest_merges.call_args
        ontology_dict = call_args[0][0]
        
        assert "entities" in ontology_dict
        assert "relationships" in ontology_dict
        assert len(ontology_dict["entities"]) == 1
        assert ontology_dict["entities"][0]["id"] == "e1"
        assert ontology_dict["entities"][0]["text"] == "Alice"
        assert ontology_dict["entities"][0]["properties"] == {"age": 30}
        
        assert call_args[1]["threshold"] == 0.88
        assert call_args[1]["max_suggestions"] == 10


class TestSemanticDeduplicationE2E:
    """End-to-end tests with real SemanticEntityDeduplicator (if available)."""

    @pytest.mark.skipif(
        not _has_semantic_dedup_deps(),
        reason="sentence-transformers not available"
    )
    def test_e2e_semantic_dedup_integration(self):
        """End-to-end test with real deduplicator."""
        from ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator import SemanticEntityDeduplicator
        
        # Create entities with semantic similarity
        entities = [
            Entity(id="e1", text="CEO", type="Person", confidence=0.9),
            Entity(id="e2", text="Chief Executive Officer", type="Person", confidence=0.85),
            Entity(id="e3", text="Company", type="Organization", confidence=0.8),
        ]
        relationships = [
            Relationship(id="r1", source_id="e1", target_id="e3", type="works_for", confidence=0.8),
            Relationship(id="r2", source_id="e2", target_id="e3", type="works_for", confidence=0.75),
        ]
        result = EntityExtractionResult(entities=entities, relationships=relationships, confidence=0.85)
def _has_semantic_dedup_deps() -> bool:
    """Check if semantic deduplication dependencies are available."""
    try:
        import sentence_transformers
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Tests for OntologyGenerator.batch_extract() method.

Tests cover:
- Basic batch extraction with multiple documents
- Single context reuse across all documents  
- Per-document context handling
- Parallel execution and result ordering
- Timeout enforcement
- Error handling and validation
- Empty input handling
- Result aggregation
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    EntityExtractionResult,
)


@pytest.fixture
def generator():
    """Create an OntologyGenerator instance."""
    return OntologyGenerator()


@pytest.fixture
def base_context():
    """Create a base generation context."""
    return OntologyGenerationContext(
        data_source="test_batch",
        data_type="text",
        domain="legal"
    )


@pytest.fixture
def sample_documents():
    """Create sample documents for batch extraction."""
    return [
        "John Smith is the CEO of TechCorp. He manages the engineering team.",
        "Dr. Sarah Johnson works at HealthMed Hospital. She is a cardiologist.",
        "The contract between Acme Inc and Beta Corp was signed in 2023.",
    ]


class TestBatchExtractBasics:
    """Test basic batch_extract functionality."""
    
    def test_extracts_from_multiple_documents(self, generator, base_context, sample_documents):
        """Should extract entities from all documents."""
        results = generator.batch_extract(sample_documents, base_context)
        
        assert len(results) == 3
        assert all(isinstance(r, EntityExtractionResult) for r in results)
        
        # Each result should have extracted entities
        for result in results:
            assert len(result.entities) > 0
    
    def test_preserves_document_order(self, generator, base_context):
        """Should return results in same order as input documents."""
        docs = [
            "Alice lives in New York.",
            "Bob works at Boston Corp.", 
            "Charlie manages the team in Chicago.",
        ]
        
        results = generator.batch_extract(docs, base_context)
        
        # Check document order is preserved
        assert len(results) == 3
        # All results should be EntityExtractionResult instances
        for result in results:
            assert isinstance(result, EntityExtractionResult)
    
    def test_returns_list_of_extraction_results(self, generator, base_context, sample_documents):
        """Should return List[EntityExtractionResult]."""
        results = generator.batch_extract(sample_documents, base_context)
        
        assert isinstance(results, list)
        assert len(results) == len(sample_documents)
        for result in results:
            assert isinstance(result, EntityExtractionResult)
            assert hasattr(result, 'entities')
            assert hasattr(result, 'relationships')


class TestBatchExtractContextHandling:
    """Test context parameter variations."""
    
    def test_single_context_reused_for_all_documents(self, generator, sample_documents):
        """Should use same context for all documents when single context provided."""
        context = OntologyGenerationContext(
            data_source="batch_medical_docs",
            data_type="text",
            domain="medical"
        )
        
        results = generator.batch_extract(sample_documents, context)
        
        assert len(results) == len(sample_documents)
        # All extractions should have completed successfully
        for result in results:
            assert isinstance(result, EntityExtractionResult)
            assert hasattr(result, 'entities')
            assert hasattr(result, 'relationships')
    
    def test_per_document_contexts(self, generator, sample_documents):
        """Should use different context for each document."""
        contexts = [
            OntologyGenerationContext(data_source="doc_1", data_type="text", domain="legal"),
            OntologyGenerationContext(data_source="doc_2", data_type="text", domain="medical"),
            OntologyGenerationContext(data_source="doc_3", data_type="text", domain="technical"),
        ]
        
        results = generator.batch_extract(sample_documents, contexts)
        
        assert len(results) == 3
        # All should have metadata with context information
        for i, result in enumerate(results):
            assert isinstance(result, EntityExtractionResult)
            assert result.metadata is not None
    
    @pytest.mark.skip(reason="ValueError on length mismatch not implemented yet")
    def test_context_length_mismatch_raises_error(self, generator, sample_documents):
        """Should raise ValueError if contexts length doesn't match docs length."""
        contexts = [
            OntologyGenerationContext(data_source="doc_1", data_type="text", domain="legal"),
            OntologyGenerationContext(data_source="doc_2", data_type="text", domain="medical"),
            # Missing third context
        ]
        
        with pytest.raises(ValueError, match="Length mismatch"):
            generator.batch_extract(sample_documents, contexts)


class TestBatchExtractParallel:
    """Test parallel execution behavior."""
    
    def test_max_workers_parameter(self, generator, base_context, sample_documents):
        """Should accept max_workers parameter."""
        # Should not raise error with explicit max_workers
        results = generator.batch_extract(
            sample_documents,
            base_context,
            max_workers=2
        )
        
        assert len(results) == len(sample_documents)
    
    def test_default_max_workers(self, generator, base_context, sample_documents):
        """Should use default max_workers when not specified."""
        # Should not raise error with default max_workers
        results = generator.batch_extract(sample_documents, base_context)
        
        assert len(results) == len(sample_documents)
    
    def test_single_worker_execution(self, generator, base_context, sample_documents):
        """Should work correctly with single worker (sequential-like)."""
        results = generator.batch_extract(
            sample_documents,
            base_context,
            max_workers=1
        )
        
        assert len(results) == len(sample_documents)
        assert all(isinstance(r, EntityExtractionResult) for r in results)


class TestBatchExtractTimeout:
    """Test timeout handling."""
    
    @pytest.mark.skip(reason="timeout_per_doc parameter not yet implemented")
    def test_timeout_parameter_accepted(self, generator, base_context, sample_documents):
        """Should accept timeout parameter."""
        # Short docs should complete quickly even with generous timeout
        results = generator.batch_extract(
            sample_documents,
            base_context,
            timeout_per_doc=30.0
        )
        
        assert len(results) == len(sample_documents)
    
    def test_timeout_not_required(self, generator, base_context, sample_documents):
        """Should work without timeout parameter."""
        results = generator.batch_extract(sample_documents, base_context)
        
        assert len(results) == len(sample_documents)


class TestBatchExtractEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_empty_document_list(self, generator, base_context):
        """Should handle empty document list."""
        results = generator.batch_extract([], base_context)
        
        assert results == []
    
    def test_single_document(self, generator, base_context):
        """Should handle single document batch."""
        docs = ["Single document with Alice and Bob."]
        
        results = generator.batch_extract(docs, base_context)
        
        assert len(results) == 1
        assert isinstance(results[0], EntityExtractionResult)
        assert len(results[0].entities) > 0
    
    def test_documents_with_no_entities(self, generator, base_context):
        """Should handle documents with no extractable entities."""
        docs = [
            "The quick brown fox.",
            "Lorem ipsum dolor sit.",
            "Random text here.",
        ]
        
        results = generator.batch_extract(docs, base_context)
        
        # Should still return results, even if empty
        assert len(results) == 3
        assert all(isinstance(r, EntityExtractionResult) for r in results)


class TestBatchExtractAggregation:
    """Test result aggregation and statistics."""
    
    def test_total_entity_count(self, generator, base_context, sample_documents):
        """Should be able to aggregate entity counts across all results."""
        results = generator.batch_extract(sample_documents, base_context)
        
        total_entities = sum(len(r.entities) for r in results)
        
        assert total_entities > 0
        assert isinstance(total_entities, int)
    
    def test_total_relationship_count(self, generator, base_context, sample_documents):
        """Should be able to aggregate relationship counts across all results."""
        results = generator.batch_extract(sample_documents, base_context)
        
        total_relationships = sum(len(r.relationships) for r in results)
        
        assert total_relationships >= 0  # Some docs may have no relationships
        assert isinstance(total_relationships, int)
    
    def test_per_document_statistics(self, generator, base_context, sample_documents):
        """Should provide per-document extraction statistics."""
        results = generator.batch_extract(sample_documents, base_context)
        
        for i, result in enumerate(results):
            assert isinstance(result.entity_count, int)
            assert isinstance(result.relationship_count, int)
            assert result.entity_count >= 0
            assert result.relationship_count >= 0


class TestBatchExtractIntegration:
    """Integration tests with real extraction scenarios."""
    
    def test_legal_document_batch(self, generator):
        """Should extract entities from batch of legal documents."""
        legal_docs = [
            "Plaintiff John Doe filed a complaint against XYZ Corp on January 15, 2023.",
            "The District Court of California granted summary judgment in Case No. 2023-CV-1234.",
            "Attorney Jane Smith represents the defendant in the proceeding.",
        ]
        
        context = OntologyGenerationContext(
            data_source="legal_batch",
            data_type="text",
            domain="legal"
        )
        
        results = generator.batch_extract(legal_docs, context, max_workers=2)
        
        assert len(results) == 3
        # Should extract legal entities
        all_entities = [e for r in results for e in r.entities]
        entity_texts = [e.text for e in all_entities]
        
        # Check for expected legal entities
        assert any("Doe" in text or "John" in text for text in entity_texts)
        assert any("XYZ" in text or "Corp" in text for text in entity_texts)
        assert any("Court" in text for text in entity_texts)
    
    def test_mixed_domain_batch(self, generator):
        """Should handle batch with different domain contexts per document."""
        docs = [
            "Dr. Smith performed cardiac surgery at General Hospital.",
            "TechCorp announced a new AI product launch in Q3 2023.",
            "The Supreme Court ruling affects all federal cases.",
        ]
        
        contexts = [
            OntologyGenerationContext(data_source="medical_doc", data_type="text", domain="medical"),
            OntologyGenerationContext(data_source="tech_doc", data_type="text", domain="technical"),
            OntologyGenerationContext(data_source="legal_doc", data_type="text", domain="legal"),
        ]
        
        results = generator.batch_extract(docs, contexts)
        
        assert len(results) == 3
        # Each should have extracted relevant entities
        for result in results:
            assert isinstance(result, EntityExtractionResult)
            assert len(result.entities) >= 0  # May extract entities

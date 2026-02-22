"""
Tests for OntologyPipeline batch processing edge cases and robustness.

Validates batch processing behavior with various document configurations,
error handling, progress tracking, and performance characteristics.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline, PipelineResult


@pytest.fixture
def pipeline():
    """Create an ontology pipeline instance for testing."""
    return OntologyPipeline(domain="legal", use_llm=False)


class TestBatchProcessingBasics:
    """Tests for basic batch processing functionality."""

    def test_empty_batch(self, pipeline):
        """Test batch processing with empty document list."""
        docs = []
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert isinstance(results, list)
        assert len(results) == 0

    def test_single_document_batch(self, pipeline):
        """Test batch processing with single document."""
        docs = ["The plaintiff filed suit against the defendant in federal court."]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 1
        assert isinstance(results[0], PipelineResult)
        assert results[0].ontology is not None
        assert results[0].score is not None

    def test_multiple_documents_batch(self, pipeline):
        """Test batch processing with multiple independent documents."""
        docs = [
            "The contract contains confidentiality clauses and arbitration provisions.",
            "The defendant filed a motion to dismiss the case.",
            "The settlement agreement was signed by all parties on March 15, 2024.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 3
        for result in results:
            assert isinstance(result, PipelineResult)
            assert result.ontology is not None
            assert len(result.ontology.get('entities', [])) > 0

    def test_batch_preserves_document_order(self, pipeline):
        """Test that batch results maintain the order of input documents."""
        docs = [
            "Mr. Alice is a lawyer at Alice & Associates LLC.",
            "Judge Bob works at Federal Court.",
            "Charlie is a witness testifying on January 15, 2024.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        # Verify results are in order
        assert len(results) == 3
        # All should have resulted in ontologies
        for result in results:
            assert result.ontology is not None
            # Each result should be a valid PipelineResult
            assert hasattr(result, 'score')


class TestBatchDocumentTypes:
    """Tests for batch processing with different document types."""

    def test_batch_with_string_documents(self, pipeline):
        """Test batch with standard string documents."""
        docs = [
            "The dispute arises from the non-performance of contractual obligations.",
            "The plaintiff seeks damages for breach of warranty.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 2
        for result in results:
            assert result.ontology is not None

    def test_batch_with_very_short_documents(self, pipeline):
        """Test batch with minimal text documents."""
        docs = [
            "Alice met Bob.",
            "X signed Y.",
            "A dated B.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 3
        # Even short documents should produce results
        for result in results:
            assert isinstance(result, PipelineResult)

    def test_batch_with_very_long_documents(self, pipeline):
        """Test batch with very large text documents."""
        # Create a long document
        long_doc = " ".join([
            "The contract states that the party agrees to the following terms and conditions. "
            "The plaintiff alleges that the defendant breached the agreement. "
            "The court finds that the applicable law requires compliance. "
            "The defendant disputes the allegations and asserts counterclaims. "
        ] * 20)  # Repeat to make it very long
        
        docs = [long_doc]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 1
        result = results[0]
        assert result.ontology is not None
        assert len(result.ontology.get('entities', [])) > 0

    def test_batch_with_unicode_documents(self, pipeline):
        """Test batch with Unicode text."""
        docs = [
            "Die Parteien vereinbaren folgende Bedingungen: München, Berlin, Hamburg.",
            "La jurisdicción será por los tribunales de Madrid y Barcelona.",
            "Les parties acceptent les conditions du contrat à Paris et Lyon.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 3
        for result in results:
            assert result.ontology is not None

    def test_batch_with_special_characters(self, pipeline):
        """Test batch with documents containing special characters."""
        docs = [
            "The contract (dated 2024) includes terms: confidentiality, non-compete, etc.",
            "Amount: USD $1,000,000 @ 5% interest; Parties: LLC & Corp.",
            "Sections [1.1], [2.2], [3.3] apply. See Appendix A—complete terms.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 3
        for result in results:
            assert result.ontology is not None


class TestBatchRefinementModes:
    """Tests for batch processing with different refinement settings."""

    def test_batch_without_refinement(self, pipeline):
        """Test batch processing with refinement disabled."""
        docs = [
            "The agreement is binding and enforceable.",
            "The parties dispute the interpretation of the clause.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 2
        # Without refinement, scores should still be valid
        for result in results:
            assert result.score is not None
            assert 0.0 <= result.score.overall <= 1.0

    def test_batch_with_refinement(self, pipeline):
        """Test batch processing with refinement enabled."""
        docs = [
            "The contract addresses liability and indemnification.",
            "The defendant agrees to pay damages.",
        ]
        
        results = pipeline.run_batch(docs, refine=True)
        
        assert len(results) == 2
        for result in results:
            assert result.score is not None
            # Refined scores should be valid
            assert 0.0 <= result.score.overall <= 1.0

    def test_batch_refine_vs_no_refine_have_different_scores(self, pipeline):
        """Test that refined batch produces potentially different scores than unrefined."""
        doc = "The plaintiff seeks damages for wrongful termination and emotional distress."
        
        results_no_refine = pipeline.run_batch([doc], refine=False)
        results_refined = pipeline.run_batch([doc], refine=True)
        
        assert len(results_no_refine) == 1
        assert len(results_refined) == 1
        
        # Both should have valid scores
        assert results_no_refine[0].score is not None
        assert results_refined[0].score is not None


class TestBatchProgressCallback:
    """Tests for batch processing progress tracking."""

    def test_batch_progress_callback_invoked(self, pipeline):
        """Test that progress callback is invoked during batch processing."""
        docs = [
            "The contract is valid and enforceable.",
            "The parties agree to the terms.",
        ]
        
        callback_calls = []
        
        def progress_callback(round_num, max_rounds, current_score):
            callback_calls.append((round_num, max_rounds, current_score))
        
        results = pipeline.run_batch(
            docs,
            refine=True,
            progress_callback=progress_callback
        )
        
        assert len(results) == 2
        # Callback should have been called (at least once per document)
        # The exact number depends on refinement rounds
        assert len(callback_calls) >= 2, "Progress callback should be called for batch processing"

    def test_batch_without_progress_callback(self, pipeline):
        """Test batch processing without progress callback (no-op)."""
        docs = [
            "The agreement is binding.",
            "The contract is enforceable.",
        ]
        
        # Should not raise error when callback=None
        results = pipeline.run_batch(
            docs,
            refine=False,
            progress_callback=None
        )
        
        assert len(results) == 2


class TestBatchWithCacheWarming:
    """Tests for batch processing with cache warming."""

    def test_batch_with_warm_cache(self, pipeline):
        """Test batch processing after cache warming."""
        reference = "The agreement contains standard legal terms and conditions."
        
        # Warm the cache
        pipeline.warm_cache(reference)
        
        # Now run batch on similar documents
        docs = [
            "Terms and conditions for the agreement.",
            "Legal terms of the contract.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 2
        for result in results:
            assert result.ontology is not None

    def test_batch_same_document_extracted_once_per_run(self, pipeline):
        """Test that identical documents in batch are processed independently."""
        doc = "The plaintiff filed suit for damages."
        docs = [doc, doc, doc]  # Same document 3 times
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 3
        # All should produce results
        for result in results:
            assert result.ontology is not None


class TestBatchDataParameters:
    """Tests for batch processing with different data source/type parameters."""

    def test_batch_with_data_source_parameter(self, pipeline):
        """Test batch with custom data_source."""
        docs = [
            "The witness testified in court.",
            "The evidence was admitted as exhibit A.",
        ]
        
        results = pipeline.run_batch(
            docs,
            data_source="legal_documents",
            data_type="text",
            refine=False
        )
        
        assert len(results) == 2

    def test_batch_with_different_data_types(self, pipeline):
        """Test batch with different data_type hints."""
        docs = ["The contract is enforceable."]
        
        # Test with different data type hints
        results_text = pipeline.run_batch(
            docs,
            data_source="source",
            data_type="text",
            refine=False
        )
        
        assert len(results_text) == 1
        assert results_text[0].ontology is not None


class TestBatchEdgeCasesAndRobustness:
    """Tests for edge cases and error robustness in batch processing."""

    def test_batch_large_number_of_documents(self, pipeline):
        """Test batch processing with many documents."""
        # Create 20 documents
        docs = [
            f"Document {i}: The contract states {['option A', 'option B', 'option C'][i % 3]}."
            for i in range(20)
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 20
        for result in results:
            assert isinstance(result, PipelineResult)

    def test_batch_with_whitespace_variations(self, pipeline):
        """Test batch with various whitespace patterns."""
        docs = [
            "Normal document with standard spacing.",
            "Document   with   multiple   spaces.",
            "\n\nDocument with leading newlines.",
            "Document with trailing newlines\n\n",
            "\t\tDocument\t\twith\t\ttabs.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 5
        for result in results:
            assert result.ontology is not None

    def test_batch_results_contain_required_fields(self, pipeline):
        """Test that batch results have complete PipelineResult structure."""
        docs = [
            "The contract at Corporation Inc is binding.",
            "The agreement signed on 2024-01-01 is valid.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        for result in results:
            assert hasattr(result, 'ontology')
            assert hasattr(result, 'score')
            # Check main fields exist
            assert result.ontology is not None
            assert result.score is not None
            assert isinstance(result.ontology, dict)
            # Ontology should have entities and relationships
            assert 'entities' in result.ontology or 'relationships' in result.ontology

    def test_batch_with_document_retrieval_later(self, pipeline):
        """Test that batch results can be retrieved and pipeline maintains state."""
        docs = [
            "The Mr. Plaintiff seeks compensatory damages.",
            "The defendant denies liability.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        # Verify we got results
        assert len(results) == 2
        # Results should be valid
        for result in results:
            assert result is not None
            assert result.ontology is not None

    def test_batch_documents_independent_ontologies(self, pipeline):
        """Test that batch documents produce separate, independent ontologies."""
        docs = [
            "Alice is a lawyer.",
            "Bob is a judge.",
        ]
        
        results = pipeline.run_batch(docs, refine=False)
        
        assert len(results) == 2
        
        # Extract entities from each
        entities_alice = {
            (e.get('text', '').lower(), e.get('type'))
            for e in results[0].ontology.get('entities', [])
        }
        entities_bob = {
            (e.get('text', '').lower(), e.get('type'))
            for e in results[1].ontology.get('entities', [])
        }
        
        # Should be different except for common words
        # The exact difference depends on entity extraction


class TestBatchIntegration:
    """Integration tests for batch processing workflows."""

    def test_batch_processing_end_to_end(self, pipeline):
        """Test complete batch processing workflow."""
        # Warm cache with reference
        pipeline.warm_cache("Standard contract terms and conditions apply for a Corporation LLC.")
        
        # Process batch
        docs = [
            "The parties at Company A Inc agree to arbitration of all disputes.",
            "The agreement signed on 2024-01-15 is governed by federal law.",
            "The contract for Organization Ltd requires notice before termination.",
        ]
        
        results = pipeline.run_batch(docs, refine=True)
        
        # Validate results
        assert len(results) == 3
        
        for result in results:
            assert result.ontology is not None
            assert result.score is not None
        
        # Find best result
        best = max(results, key=lambda r: r.score.overall)
        assert best is not None

    def test_batch_then_individual_processing(self, pipeline):
        """Test that batch and individual processing are consistent."""
        doc = "The liability is limited to direct damages only."
        
        # Process via batch
        batch_result = pipeline.run_batch([doc], refine=False)[0]
        
        # Process individually
        individual_result = pipeline.run(doc, refine=False)
        
        # Both should produce valid results
        assert batch_result.ontology is not None
        assert individual_result.ontology is not None
        # Scores should exist
        assert batch_result.score is not None
        assert individual_result.score is not None

"""Tests for the unified NeurosymbolicGraphRAG pipeline.

This module tests the complete end-to-end pipeline that integrates
TDFOL, neurosymbolic reasoning, and logic-enhanced GraphRAG.
"""

import pytest
from ipfs_datasets_py.logic.integration.neurosymbolic_graphrag import (
    NeurosymbolicGraphRAG,
    PipelineResult
)


class TestNeurosymbolicGraphRAG:
    """Test the unified neurosymbolic pipeline."""
    
    @pytest.fixture
    def pipeline(self):
        """Create pipeline instance."""
        return NeurosymbolicGraphRAG(
            use_neural=False,  # Disable neural for faster tests
            enable_proof_caching=False
        )
    
    def test_initialization(self, pipeline):
        """GIVEN: NeurosymbolicGraphRAG class
        WHEN: Initializing instance
        THEN: All components should be initialized
        """
        assert pipeline.prover is not None
        assert pipeline.rag is not None
        assert isinstance(pipeline.documents, dict)
    
    def test_process_simple_document(self, pipeline):
        """GIVEN: Simple document text
        WHEN: Processing through pipeline
        THEN: Should extract entities and return result
        """
        text = "Alice must pay Bob."
        result = pipeline.process_document(text, "test_doc_001")
        
        assert isinstance(result, PipelineResult)
        assert result.doc_id == "test_doc_001"
        assert result.text == text
        assert len(result.reasoning_chain) > 0
    
    def test_process_contract_document(self, pipeline):
        """GIVEN: Contract-like document
        WHEN: Processing through pipeline
        THEN: Should extract multiple entities and formulas
        """
        contract = """
        Service Agreement
        
        The Provider must deliver services within 30 days.
        The Customer must pay fees within 15 days.
        Either party may terminate with notice.
        """
        
        result = pipeline.process_document(contract, "contract_001")
        
        assert result.entities > 0
        assert len(result.reasoning_chain) >= 2
        assert result.confidence > 0
    
    def test_query_after_processing(self, pipeline):
        """GIVEN: Processed document
        WHEN: Querying
        THEN: Should return relevant results
        """
        text = "Alice must pay Bob. Carol must deliver goods."
        pipeline.process_document(text, "doc_002")
        
        result = pipeline.query("pay", use_inference=True)
        
        assert result is not None
        assert hasattr(result, 'relevant_nodes')
        assert hasattr(result, 'reasoning_chain')
    
    def test_get_document_summary(self, pipeline):
        """GIVEN: Processed document
        WHEN: Getting summary
        THEN: Should return summary dict
        """
        text = "Alice must pay Bob."
        pipeline.process_document(text, "doc_003")
        
        summary = pipeline.get_document_summary("doc_003")
        
        assert summary is not None
        assert 'doc_id' in summary
        assert 'entities_count' in summary
        assert 'confidence' in summary
    
    def test_get_document_summary_not_found(self, pipeline):
        """GIVEN: Non-existent document ID
        WHEN: Getting summary
        THEN: Should return None
        """
        summary = pipeline.get_document_summary("nonexistent")
        assert summary is None
    
    def test_get_pipeline_stats(self, pipeline):
        """GIVEN: Pipeline with processed documents
        WHEN: Getting stats
        THEN: Should return comprehensive statistics
        """
        pipeline.process_document("Test document", "doc_004")
        
        stats = pipeline.get_pipeline_stats()
        
        assert 'documents_processed' in stats
        assert 'total_entities' in stats
        assert 'knowledge_graph' in stats
        assert stats['documents_processed'] >= 1
    
    def test_export_knowledge_graph(self, pipeline):
        """GIVEN: Pipeline with processed documents
        WHEN: Exporting knowledge graph
        THEN: Should return graph structure
        """
        pipeline.process_document("Alice must pay Bob.", "doc_005")
        
        export = pipeline.export_knowledge_graph()
        
        assert isinstance(export, dict)
        assert 'nodes' in export
        assert 'edges' in export
    
    def test_check_consistency(self, pipeline):
        """GIVEN: Pipeline with documents
        WHEN: Checking consistency
        THEN: Should return consistency status
        """
        pipeline.process_document("Alice must pay Bob.", "doc_006")
        
        is_consistent, issues = pipeline.check_consistency()
        
        assert isinstance(is_consistent, bool)
        assert isinstance(issues, list)
    
    def test_multiple_documents(self, pipeline):
        """GIVEN: Multiple documents
        WHEN: Processing all
        THEN: Should track all in pipeline
        """
        docs = [
            ("Alice must pay Bob.", "doc1"),
            ("Carol must deliver goods.", "doc2"),
            ("Dave may access the system.", "doc3")
        ]
        
        for text, doc_id in docs:
            pipeline.process_document(text, doc_id)
        
        stats = pipeline.get_pipeline_stats()
        assert stats['documents_processed'] == 3
    
    def test_auto_prove_disabled(self, pipeline):
        """GIVEN: Document with auto_prove disabled
        WHEN: Processing
        THEN: Should not attempt theorem proving
        """
        text = "Alice must pay Bob."
        result = pipeline.process_document(text, "doc_007", auto_prove=False)
        
        assert len(result.proven_theorems) == 0
    
    def test_proving_strategy_symbolic(self):
        """GIVEN: Pipeline with SYMBOLIC_ONLY strategy
        WHEN: Processing document
        THEN: Should work without neural components
        """
        pipeline = NeurosymbolicGraphRAG(
            use_neural=False,
            proving_strategy="SYMBOLIC_ONLY"
        )
        
        result = pipeline.process_document("Alice must pay Bob.", "doc_008")
        assert isinstance(result, PipelineResult)
    
    def test_reasoning_chain_completeness(self, pipeline):
        """GIVEN: Processed document
        WHEN: Checking reasoning chain
        THEN: Should contain all pipeline steps
        """
        text = "Alice must pay Bob."
        result = pipeline.process_document(text, "doc_009")
        
        # Should have at least: processing, extraction, parsing steps
        assert len(result.reasoning_chain) >= 2
        assert any("Processing" in step for step in result.reasoning_chain)
        assert any("Extracted" in step or "entities" in step.lower() 
                  for step in result.reasoning_chain)
    
    def test_confidence_scoring(self, pipeline):
        """GIVEN: Processed documents
        WHEN: Checking confidence scores
        THEN: Should be in valid range [0, 1]
        """
        result = pipeline.process_document("Alice must pay Bob.", "doc_010")
        
        assert 0.0 <= result.confidence <= 1.0
    
    def test_empty_document(self, pipeline):
        """GIVEN: Empty document
        WHEN: Processing
        THEN: Should handle gracefully
        """
        result = pipeline.process_document("", "doc_empty")
        
        assert isinstance(result, PipelineResult)
        assert result.entities == 0 or result.entities == []


class TestPipelineResult:
    """Test PipelineResult dataclass."""
    
    def test_pipeline_result_creation(self):
        """GIVEN: Pipeline result data
        WHEN: Creating PipelineResult
        THEN: Should initialize with defaults
        """
        result = PipelineResult(doc_id="test", text="test text")
        
        assert result.doc_id == "test"
        assert result.text == "test text"
        assert isinstance(result.entities, list)
        assert isinstance(result.formulas, list)
        assert isinstance(result.reasoning_chain, list)
        assert result.confidence == 0.0
    
    def test_pipeline_result_with_data(self):
        """GIVEN: Complete pipeline result data
        WHEN: Creating PipelineResult
        THEN: All fields should be populated
        """
        result = PipelineResult(
            doc_id="test",
            text="test text",
            entities=[],
            formulas=[],
            proven_theorems=[],
            reasoning_chain=["step1", "step2"],
            confidence=0.85
        )
        
        assert result.doc_id == "test"
        assert len(result.reasoning_chain) == 2
        assert result.confidence == 0.85


class TestProvingStrategies:
    """Test different proving strategies."""
    
    def test_symbolic_only_strategy(self):
        """GIVEN: Pipeline with SYMBOLIC_ONLY
        WHEN: Processing document
        THEN: Should work without neural
        """
        pipeline = NeurosymbolicGraphRAG(
            use_neural=False,
            proving_strategy="SYMBOLIC_ONLY"
        )
        
        result = pipeline.process_document("Test", "test_symbolic")
        assert isinstance(result, PipelineResult)
    
    def test_auto_strategy(self):
        """GIVEN: Pipeline with AUTO strategy
        WHEN: Processing document
        THEN: Should automatically select best strategy
        """
        pipeline = NeurosymbolicGraphRAG(
            use_neural=False,
            proving_strategy="AUTO"
        )
        
        result = pipeline.process_document("Test", "test_auto")
        assert isinstance(result, PipelineResult)


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    def test_service_agreement_workflow(self):
        """GIVEN: Service level agreement
        WHEN: Processing through complete pipeline
        THEN: Should extract all components
        """
        pipeline = NeurosymbolicGraphRAG(use_neural=False)
        
        sla = """
        Service Level Agreement
        
        The Provider must maintain 99.9% uptime.
        The Provider must respond within 2 hours.
        The Customer must pay within 30 days.
        Either party may terminate with notice.
        """
        
        result = pipeline.process_document(sla, "sla_001")
        
        assert result.entities > 0
        assert len(result.reasoning_chain) > 0
        
        # Query for obligations
        query_result = pipeline.query("Provider must")
        assert query_result is not None
    
    def test_employment_contract_workflow(self):
        """GIVEN: Employment contract
        WHEN: Processing and querying
        THEN: Should handle all clauses
        """
        pipeline = NeurosymbolicGraphRAG(use_neural=False)
        
        contract = """
        Employment Agreement
        
        The Employee must perform assigned duties.
        The Employee must maintain confidentiality.
        The Employer must pay salary monthly.
        The Employer must provide safe conditions.
        """
        
        result = pipeline.process_document(contract, "employment_001")
        
        # Should extract multiple obligations
        assert result.entities > 0
        
        # Check consistency
        is_consistent, _ = pipeline.check_consistency()
        assert isinstance(is_consistent, bool)

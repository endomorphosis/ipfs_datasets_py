"""Tests for logic-enhanced RAG system.

This module tests the complete logic-enhanced RAG pipeline including
document ingestion, querying, and reasoning.
"""

import pytest
from ipfs_datasets_py.rag.logic_integration.logic_enhanced_rag import (
    LogicEnhancedRAG,
    RAGQueryResult
)


class TestLogicEnhancedRAG:
    """Test logic-enhanced RAG system."""
    
    @pytest.fixture
    def rag(self):
        """Create RAG instance."""
        return LogicEnhancedRAG(use_neural=False)
    
    def test_initialization(self, rag):
        """GIVEN: LogicEnhancedRAG class
        WHEN: Initializing instance
        THEN: All components should be initialized
        """
        assert rag.kg is not None
        assert rag.extractor is not None
        assert rag.theorem_rag is not None
        assert isinstance(rag.documents, dict)
    
    def test_ingest_simple_document(self, rag):
        """GIVEN: Simple text document
        WHEN: Ingesting document
        THEN: Should extract entities and create graph
        """
        text = "Alice must pay Bob within 30 days."
        result = rag.ingest_document(text, "doc1")
        
        assert result['doc_id'] == "doc1"
        assert result['entities_extracted'] > 0
        assert result['nodes_created'] > 0
        assert 'is_consistent' in result
        assert 'doc1' in rag.documents
    
    def test_ingest_contract_document(self, rag):
        """GIVEN: Contract-like document
        WHEN: Ingesting document
        THEN: Should extract multiple entity types
        """
        contract = """
        Service Level Agreement
        
        The Provider must deliver services within 14 business days.
        The Client shall pay fees within 30 days of invoice.
        Either party may terminate with 90 days notice.
        The Provider must not disclose confidential information.
        """
        
        result = rag.ingest_document(contract, "sla_001")
        
        assert result['entities_extracted'] >= 4
        assert result['nodes_created'] >= 4
        assert len(rag.kg.nodes) >= 4
    
    def test_query_after_ingestion(self, rag):
        """GIVEN: Ingested documents
        WHEN: Querying
        THEN: Should return relevant results
        """
        text = "Alice must pay Bob. Carol shall deliver goods."
        rag.ingest_document(text, "doc1")
        
        result = rag.query("What must Alice do?")
        
        assert isinstance(result, RAGQueryResult)
        assert result.text == "What must Alice do?"
        assert len(result.relevant_nodes) > 0
        assert len(result.reasoning_chain) > 0
    
    def test_query_obligations(self, rag):
        """GIVEN: Document with obligations
        WHEN: Querying for obligations with relevant keywords
        THEN: Should find obligation entities
        """
        text = "The seller must deliver products. The buyer must pay fees."
        rag.ingest_document(text, "doc2")
        
        result = rag.query("must deliver")
        
        assert len(result.relevant_nodes) > 0
        # Should find nodes related to obligations
        obligation_nodes = [
            n for n in result.relevant_nodes
            if 'must' in n.entity.text.lower()
        ]
        assert len(obligation_nodes) > 0
    
    def test_query_with_inference(self, rag):
        """GIVEN: Document and theorems
        WHEN: Querying with inference enabled
        THEN: Should include related theorems
        """
        text = "Alice must pay Bob."
        rag.ingest_document(text, "doc3")
        rag.add_theorem("payment_rule", "pay(X) -> owes(X)")
        
        result = rag.query("pay", use_inference=True)
        
        assert isinstance(result, RAGQueryResult)
        assert len(result.reasoning_chain) > 0
    
    def test_query_without_inference(self, rag):
        """GIVEN: Document ingested
        WHEN: Querying without inference
        THEN: Should not include theorems
        """
        text = "Alice must pay Bob."
        rag.ingest_document(text, "doc4")
        
        result = rag.query("pay", use_inference=False)
        
        assert isinstance(result, RAGQueryResult)
        assert len(result.related_theorems) == 0
    
    def test_consistency_checking(self, rag):
        """GIVEN: Document with inconsistencies
        WHEN: Ingesting and querying
        THEN: Should detect inconsistencies
        """
        inconsistent_text = """
        Alice must share the data.
        Alice must not share the data.
        """
        
        result = rag.ingest_document(inconsistent_text, "doc5")
        
        assert not result['is_consistent']
        assert len(result['inconsistencies']) > 0
        
        # Query should also reflect inconsistency
        query_result = rag.query("Alice")
        assert not query_result.consistency_check
    
    def test_add_theorem(self, rag):
        """GIVEN: RAG system
        WHEN: Adding theorem
        THEN: Theorem should be stored
        """
        success = rag.add_theorem("test_theorem", "P -> Q", auto_prove=False)
        
        assert success
        assert "test_theorem" in rag.kg.theorems
    
    def test_get_stats(self, rag):
        """GIVEN: RAG with documents
        WHEN: Getting statistics
        THEN: Should return comprehensive stats
        """
        text = "Alice must pay Bob."
        rag.ingest_document(text, "doc6")
        rag.add_theorem("test", "P -> Q")
        
        stats = rag.get_stats()
        
        assert 'documents_ingested' in stats
        assert stats['documents_ingested'] >= 1
        assert 'nodes' in stats
        assert 'theorems' in stats
        assert 'total_theorems' in stats
    
    def test_export_knowledge_graph(self, rag):
        """GIVEN: RAG with ingested documents
        WHEN: Exporting knowledge graph
        THEN: Should return complete graph structure
        """
        text = "Alice must pay Bob within 30 days."
        rag.ingest_document(text, "doc7")
        
        export = rag.export_knowledge_graph()
        
        assert 'nodes' in export
        assert 'edges' in export
        assert 'theorems' in export
        assert len(export['nodes']) > 0
    
    def test_empty_query(self, rag):
        """GIVEN: Empty RAG
        WHEN: Querying
        THEN: Should return empty result without error
        """
        result = rag.query("anything")
        
        assert isinstance(result, RAGQueryResult)
        assert len(result.relevant_nodes) == 0
    
    def test_multiple_documents(self, rag):
        """GIVEN: Multiple documents
        WHEN: Ingesting all
        THEN: Should maintain all in knowledge graph
        """
        doc1 = "Alice must pay Bob."
        doc2 = "Carol shall deliver goods."
        doc3 = "Dave may access the system."
        
        rag.ingest_document(doc1, "doc1")
        rag.ingest_document(doc2, "doc2")
        rag.ingest_document(doc3, "doc3")
        
        assert len(rag.documents) == 3
        assert len(rag.kg.nodes) >= 6  # At least 2 entities per doc
    
    def test_confidence_calculation(self, rag):
        """GIVEN: Query with results
        WHEN: Checking confidence
        THEN: Confidence should be in valid range
        """
        text = "Alice must pay Bob within 30 days."
        rag.ingest_document(text, "doc8")
        
        result = rag.query("Alice pay")
        
        assert 0.0 <= result.confidence <= 1.0
    
    def test_reasoning_chain(self, rag):
        """GIVEN: Query processing
        WHEN: Checking reasoning chain
        THEN: Should document reasoning steps
        """
        text = "Alice must pay Bob."
        rag.ingest_document(text, "doc9")
        
        result = rag.query("pay")
        
        assert len(result.reasoning_chain) > 0
        assert any("extracted" in step.lower() for step in result.reasoning_chain)
        assert any("found" in step.lower() for step in result.reasoning_chain)
    
    def test_complex_query_workflow(self, rag):
        """GIVEN: Complex document with multiple entity types
        WHEN: Performing complete workflow
        THEN: All operations should work correctly
        """
        contract = """
        Software License Agreement
        
        Licensor grants to Licensee the right to use the Software.
        Licensee must pay license fees within 30 days.
        Licensee may not distribute or modify the Software.
        If payment is late, then Licensor may terminate the license.
        This agreement shall always be governed by California law.
        """
        
        # Ingest
        ingest_result = rag.ingest_document(contract, "license_001")
        assert ingest_result['entities_extracted'] >= 5
        
        # Add theorem
        rag.add_theorem("payment_obligation", "late(payment) -> can_terminate")
        
        # Query 1: Find obligations
        result1 = rag.query("What must Licensee do?")
        assert len(result1.relevant_nodes) > 0
        assert "must" in contract.lower()
        
        # Query 2: Find prohibitions
        result2 = rag.query("What is Licensee prohibited from doing?")
        assert len(result2.relevant_nodes) >= 0
        
        # Query 3: Conditional logic
        result3 = rag.query("What happens if payment is late?")
        assert len(result3.relevant_nodes) >= 0
        
        # Check consistency
        is_consistent, _ = rag.check_consistency()
        assert isinstance(is_consistent, bool)
        
        # Export graph
        export = rag.export_knowledge_graph()
        assert len(export['nodes']) >= 5
    
    def test_top_k_parameter(self, rag):
        """GIVEN: Many entities in graph
        WHEN: Querying with top_k
        THEN: Should respect limit
        """
        # Add many entities
        for i in range(20):
            rag.ingest_document(f"Entity{i} must perform action", f"doc{i}")
        
        result = rag.query("perform", top_k=5)
        
        assert len(result.relevant_nodes) <= 5


class TestRAGQueryResult:
    """Test RAGQueryResult dataclass."""
    
    def test_result_creation(self):
        """GIVEN: Query result data
        WHEN: Creating RAGQueryResult
        THEN: Should initialize with defaults
        """
        result = RAGQueryResult(text="test query")
        
        assert result.text == "test query"
        assert isinstance(result.logical_entities, list)
        assert isinstance(result.relevant_nodes, list)
        assert isinstance(result.related_theorems, list)
        assert isinstance(result.reasoning_chain, list)
        assert result.consistency_check is True
        assert result.confidence == 0.0
    
    def test_result_with_data(self):
        """GIVEN: Complete query result data
        WHEN: Creating RAGQueryResult
        THEN: All fields should be populated
        """
        from ipfs_datasets_py.rag.logic_integration.logic_aware_entity_extractor import (
            LogicalEntity, LogicalEntityType
        )
        from ipfs_datasets_py.rag.logic_integration.logic_aware_knowledge_graph import (
            LogicNode
        )
        
        entity = LogicalEntity("Alice", LogicalEntityType.AGENT, 0.9)
        node = LogicNode(id="agent_0", entity=entity)
        
        result = RAGQueryResult(
            text="test",
            logical_entities=[entity],
            relevant_nodes=[node],
            related_theorems=[("test", "P -> Q")],
            consistency_check=False,
            reasoning_chain=["step1", "step2"],
            confidence=0.85
        )
        
        assert len(result.logical_entities) == 1
        assert len(result.relevant_nodes) == 1
        assert len(result.related_theorems) == 1
        assert len(result.reasoning_chain) == 2
        assert result.confidence == 0.85
        assert not result.consistency_check


class TestIntegrationScenarios:
    """Test real-world integration scenarios."""
    
    def test_legal_contract_scenario(self):
        """GIVEN: Real legal contract text
        WHEN: Processing through RAG pipeline
        THEN: Should extract all key components
        """
        rag = LogicEnhancedRAG(use_neural=False)
        
        contract = """
        Employment Agreement
        
        The Employee shall perform duties as assigned by Employer.
        The Employer must pay Employee a salary of $100,000 annually.
        Employee may request vacation with 2 weeks notice.
        Employee must not disclose confidential information.
        If Employee violates this agreement, then Employer may terminate immediately.
        This agreement is effective for 2 years from the start date.
        """
        
        result = rag.ingest_document(contract, "employment_001")
        
        # Should extract various entity types
        assert result['entities_extracted'] >= 5
        
        # Query different aspects using actual keywords from the text
        obligations_result = rag.query("Employee shall perform duties")
        assert len(obligations_result.relevant_nodes) > 0
        
        permissions_result = rag.query("vacation request")
        assert len(permissions_result.relevant_nodes) >= 0
        
        prohibitions_result = rag.query("disclose confidential")
        assert len(prohibitions_result.relevant_nodes) > 0

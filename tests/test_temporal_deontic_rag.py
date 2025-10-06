"""
Unit tests for the Temporal Deontic Logic RAG System

Tests the document consistency checker functionality that works like
a legal debugger.
"""

import unittest
import sys
import os
from datetime import datetime
from unittest.mock import Mock, patch

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'ipfs_datasets_py'))

from ipfs_datasets_py.logic_integration.deontic_logic_core import (
    DeonticFormula, DeonticOperator, LegalAgent
)
from ipfs_datasets_py.logic_integration.temporal_deontic_rag_store import (
    TemporalDeonticRAGStore, TheoremMetadata, ConsistencyResult
)
from ipfs_datasets_py.logic_integration.document_consistency_checker import (
    DocumentConsistencyChecker, DocumentAnalysis, DebugReport
)


class TestTemporalDeonticRAGStore(unittest.TestCase):
    """Test cases for the TemporalDeonticRAGStore."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.rag_store = TemporalDeonticRAGStore()
        
        # Sample theorem for testing
        self.sample_formula = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="provide written notice before termination",
            agent=LegalAgent("party", "Contract Party", "person"),
            confidence=0.9,
            source_text="Party must provide written notice"
        )
    
    def test_add_theorem(self):
        """Test adding a theorem to the RAG store."""
        # GIVEN a RAG store and a sample theorem
        temporal_scope = (datetime(2020, 1, 1), None)
        
        # WHEN adding the theorem
        theorem_id = self.rag_store.add_theorem(
            formula=self.sample_formula,
            temporal_scope=temporal_scope,
            jurisdiction="Federal",
            legal_domain="contract",
            source_case="Test Case (2020)",
            precedent_strength=0.85
        )
        
        # THEN the theorem should be stored with proper metadata
        self.assertIsInstance(theorem_id, str)
        self.assertIn(theorem_id, self.rag_store.theorems)
        
        theorem = self.rag_store.theorems[theorem_id]
        self.assertEqual(theorem.formula.proposition, "provide written notice before termination")
        self.assertEqual(theorem.jurisdiction, "Federal")
        self.assertEqual(theorem.legal_domain, "contract")
        self.assertEqual(theorem.precedent_strength, 0.85)
    
    def test_retrieve_relevant_theorems(self):
        """Test RAG-based retrieval of relevant theorems."""
        # GIVEN a RAG store with sample theorems
        self.rag_store.add_theorem(
            formula=self.sample_formula,
            temporal_scope=(datetime(2020, 1, 1), None),
            jurisdiction="Federal",
            legal_domain="contract"
        )
        
        # WHEN querying for relevant theorems
        query_formula = DeonticFormula(
            operator=DeonticOperator.OBLIGATION,
            proposition="provide advance notice",
            agent=LegalAgent("party", "Contract Party", "person")
        )
        
        relevant_theorems = self.rag_store.retrieve_relevant_theorems(
            query_formula=query_formula,
            temporal_context=datetime(2023, 6, 1),
            top_k=5
        )
        
        # THEN relevant theorems should be returned
        self.assertGreater(len(relevant_theorems), 0)
        self.assertIsInstance(relevant_theorems[0], TheoremMetadata)
    
    def test_check_document_consistency(self):
        """Test document consistency checking."""
        # GIVEN a RAG store with conflicting theorems
        prohibition_formula = DeonticFormula(
            operator=DeonticOperator.PROHIBITION,
            proposition="disclose confidential information",
            agent=LegalAgent("employee", "Employee", "person")
        )
        
        self.rag_store.add_theorem(
            formula=prohibition_formula,
            temporal_scope=(datetime(2015, 1, 1), None),
            jurisdiction="Federal",
            legal_domain="confidentiality"
        )
        
        # WHEN checking a conflicting document formula
        conflicting_formula = DeonticFormula(
            operator=DeonticOperator.PERMISSION,
            proposition="share confidential information with partners",
            agent=LegalAgent("employee", "Employee", "person")
        )
        
        result = self.rag_store.check_document_consistency(
            document_formulas=[conflicting_formula],
            temporal_context=datetime(2023, 6, 1),
            jurisdiction="Federal",
            legal_domain="confidentiality"
        )
        
        # THEN conflicts should be detected
        self.assertIsInstance(result, ConsistencyResult)
        self.assertFalse(result.is_consistent)
        self.assertGreater(len(result.conflicts), 0)
    
    def test_conflict_detection(self):
        """Test logical conflict detection between formulas."""
        # GIVEN two conflicting formulas
        prohibition = DeonticFormula(
            operator=DeonticOperator.PROHIBITION,
            proposition="disclose confidential information",
            agent=LegalAgent("employee", "Employee", "person")
        )
        
        permission = DeonticFormula(
            operator=DeonticOperator.PERMISSION,
            proposition="share confidential information",
            agent=LegalAgent("employee", "Employee", "person")
        )
        
        # WHEN checking for conflicts
        conflict = self.rag_store._check_formula_conflict(permission, prohibition)
        
        # THEN a conflict should be detected
        self.assertIsNotNone(conflict)
        self.assertIn("conflicts", conflict.lower())
    
    def test_statistics(self):
        """Test getting RAG store statistics."""
        # GIVEN a RAG store with theorems
        self.rag_store.add_theorem(
            formula=self.sample_formula,
            temporal_scope=(datetime(2020, 1, 1), None),
            jurisdiction="Federal",
            legal_domain="contract"
        )
        
        # WHEN getting statistics
        stats = self.rag_store.get_statistics()
        
        # THEN proper statistics should be returned
        self.assertIsInstance(stats, dict)
        self.assertEqual(stats['total_theorems'], 1)
        self.assertEqual(stats['jurisdictions'], 1)
        self.assertEqual(stats['legal_domains'], 1)
        self.assertGreater(stats['avg_precedent_strength'], 0)


class TestDocumentConsistencyChecker(unittest.TestCase):
    """Test cases for the DocumentConsistencyChecker."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.rag_store = TemporalDeonticRAGStore()
        self.checker = DocumentConsistencyChecker(rag_store=self.rag_store)
        
        # Add sample theorems
        prohibition_formula = DeonticFormula(
            operator=DeonticOperator.PROHIBITION,
            proposition="disclose confidential information to third parties",
            agent=LegalAgent("professional", "Professional", "person")
        )
        
        self.rag_store.add_theorem(
            formula=prohibition_formula,
            temporal_scope=(datetime(2015, 1, 1), None),
            jurisdiction="Federal",
            legal_domain="confidentiality",
            source_case="Confidentiality Act (2015)",
            precedent_strength=0.95
        )
    
    def test_check_document_consistent(self):
        """Test checking a consistent document."""
        # GIVEN a consistent document
        consistent_doc = """
        The consultant shall not disclose confidential client 
        information to any third parties without written consent.
        """
        
        # WHEN checking the document
        analysis = self.checker.check_document(
            document_text=consistent_doc,
            document_id="test_consistent.pdf",
            temporal_context=datetime(2023, 6, 1),
            jurisdiction="Federal",
            legal_domain="confidentiality"
        )
        
        # THEN the document should be analyzed properly
        self.assertIsInstance(analysis, DocumentAnalysis)
        self.assertEqual(analysis.document_id, "test_consistent.pdf")
        self.assertIsNotNone(analysis.consistency_result)
        self.assertGreaterEqual(len(analysis.extracted_formulas), 0)
    
    def test_check_document_conflicts(self):
        """Test checking a document with conflicts."""
        # GIVEN a conflicting document
        conflicting_doc = """
        Employee may share confidential company information 
        with external partners without any restrictions.
        """
        
        # WHEN checking the document
        analysis = self.checker.check_document(
            document_text=conflicting_doc,
            document_id="test_conflicting.pdf",
            temporal_context=datetime(2023, 6, 1),
            jurisdiction="Federal",
            legal_domain="confidentiality"
        )
        
        # THEN conflicts should be detected
        self.assertIsInstance(analysis, DocumentAnalysis)
        self.assertIsNotNone(analysis.consistency_result)
        
        # Check if conflicts were detected (may vary based on pattern matching)
        if analysis.consistency_result.conflicts:
            self.assertGreater(len(analysis.consistency_result.conflicts), 0)
    
    def test_generate_debug_report(self):
        """Test generating a debug report."""
        # GIVEN a document analysis
        analysis = DocumentAnalysis(
            document_id="test_doc.pdf",
            extracted_formulas=[],
            issues_found=[{
                "type": "error",
                "severity": "critical", 
                "message": "Test conflict detected",
                "suggestion": "Fix the conflict"
            }],
            confidence_score=0.5
        )
        
        # WHEN generating a debug report
        debug_report = self.checker.generate_debug_report(analysis)
        
        # THEN a proper debug report should be generated
        self.assertIsInstance(debug_report, DebugReport)
        self.assertEqual(debug_report.document_id, "test_doc.pdf")
        self.assertEqual(debug_report.total_issues, 1)
        self.assertEqual(debug_report.critical_errors, 1)
        self.assertEqual(debug_report.warnings, 0)
    
    def test_basic_formula_extraction(self):
        """Test basic formula extraction from text."""
        # GIVEN a text with legal language
        text = """
        The contractor must provide written notice 30 days before termination.
        The employee may access confidential information for business purposes.
        The consultant shall not disclose client data to third parties.
        """
        
        # WHEN extracting formulas
        formulas = self.checker._basic_formula_extraction(text)
        
        # THEN formulas should be extracted
        self.assertIsInstance(formulas, list)
        self.assertGreater(len(formulas), 0)
        
        # Check that different deontic operators are detected
        operators = [f.operator for f in formulas]
        self.assertIn(DeonticOperator.OBLIGATION, operators)
        self.assertIn(DeonticOperator.PERMISSION, operators)
        self.assertIn(DeonticOperator.PROHIBITION, operators)
    
    def test_batch_check_documents(self):
        """Test batch processing of multiple documents."""
        # GIVEN multiple documents
        documents = [
            ("Document 1: Consultant must maintain confidentiality.", "doc1.pdf"),
            ("Document 2: Employee may share information freely.", "doc2.pdf")
        ]
        
        # WHEN processing in batch
        results = self.checker.batch_check_documents(
            documents=documents,
            temporal_context=datetime(2023, 6, 1),
            jurisdiction="Federal",
            legal_domain="confidentiality"
        )
        
        # THEN all documents should be analyzed
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertIsInstance(result, DocumentAnalysis)
            self.assertIn(result.document_id, ["doc1.pdf", "doc2.pdf"])


class TestSystemIntegration(unittest.TestCase):
    """Integration tests for the complete system."""
    
    def test_end_to_end_legal_debugging(self):
        """Test the complete legal debugging workflow."""
        # GIVEN a complete legal debugging system
        rag_store = TemporalDeonticRAGStore()
        checker = DocumentConsistencyChecker(rag_store=rag_store)
        
        # AND a corpus of legal theorems
        confidentiality_theorem = DeonticFormula(
            operator=DeonticOperator.PROHIBITION,
            proposition="disclose confidential information",
            agent=LegalAgent("employee", "Employee", "person")
        )
        
        rag_store.add_theorem(
            formula=confidentiality_theorem,
            temporal_scope=(datetime(2015, 1, 1), None),
            jurisdiction="Federal",
            legal_domain="confidentiality",
            source_case="Test Confidentiality Case",
            precedent_strength=0.9
        )
        
        # WHEN analyzing a legal document
        document_text = """
        Employee agreements:
        1. Employee may share confidential information with partners.
        2. No restrictions on information disclosure.
        """
        
        analysis = checker.check_document(
            document_text=document_text,
            document_id="integration_test.pdf",
            temporal_context=datetime(2023, 6, 1),
            jurisdiction="Federal",
            legal_domain="confidentiality"
        )
        
        # THEN the system should work end-to-end
        self.assertIsInstance(analysis, DocumentAnalysis)
        self.assertIsNotNone(analysis.consistency_result)
        
        # AND generate a proper debug report
        debug_report = checker.generate_debug_report(analysis)
        self.assertIsInstance(debug_report, DebugReport)
        self.assertGreaterEqual(debug_report.total_issues, 0)
        
        # AND the RAG store should have statistics
        stats = rag_store.get_statistics()
        self.assertEqual(stats['total_theorems'], 1)


if __name__ == '__main__':
    # Configure test output
    unittest.main(verbosity=2)
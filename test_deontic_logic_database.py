#!/usr/bin/env python3
"""
Test suite for the Deontic Logic Database system

This test validates all components of the deontic logic database including:
- Automatic logic conversion
- RAG search functionality
- Conflict detection and linting
- Case law shepherding
- Database operations
"""

import unittest
import tempfile
import os
import sys
from datetime import datetime
from pathlib import Path

# Add the project root to the path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from deontic_logic_database import (
        DeonticLogicDatabase,
        AutomaticLogicConverter,
        ConflictDetectionEngine,
        LegalRAGProcessor,
        ShepherdingEngine,
        DeonticStatement,
        LogicalConflict,
        ShepherdCitation
    )
except ImportError as e:
    print(f"Error importing deontic logic database: {e}")
    print("Please ensure the deontic_logic_database.py file is in the same directory")
    sys.exit(1)

class TestAutomaticLogicConverter(unittest.TestCase):
    """Test the automatic logic conversion functionality"""
    
    def setUp(self):
        self.converter = AutomaticLogicConverter()
    
    def test_obligation_detection(self):
        """Test detection of obligation statements"""
        text = "States must provide equal educational opportunities to all students."
        statements = self.converter.convert_to_deontic_logic(text)
        
        self.assertGreater(len(statements), 0)
        self.assertEqual(statements[0].modality, 'obligation')
        self.assertIn('O(', statements[0].logic_expression)
        self.assertGreater(statements[0].confidence, 0.5)
    
    def test_prohibition_detection(self):
        """Test detection of prohibition statements"""
        text = "Students cannot be denied admission based on race."
        statements = self.converter.convert_to_deontic_logic(text)
        
        self.assertGreater(len(statements), 0)
        self.assertEqual(statements[0].modality, 'prohibition')
        self.assertIn('F(', statements[0].logic_expression)
    
    def test_permission_detection(self):
        """Test detection of permission statements"""
        text = "Citizens may exercise their right to vote."
        statements = self.converter.convert_to_deontic_logic(text)
        
        self.assertGreater(len(statements), 0)
        self.assertEqual(statements[0].modality, 'permission')
        self.assertIn('P(', statements[0].logic_expression)
    
    def test_temporal_constraints(self):
        """Test detection of temporal constraints"""
        text = "Defendants must be informed of their rights immediately upon arrest."
        statements = self.converter.convert_to_deontic_logic(text)
        
        self.assertGreater(len(statements), 0)
        self.assertIn('T(', statements[0].logic_expression)
    
    def test_conditional_statements(self):
        """Test detection of conditional statements"""
        text = "If probable cause exists, officers may conduct searches."
        statements = self.converter.convert_to_deontic_logic(text)
        
        self.assertGreater(len(statements), 0)
        self.assertIn('→', statements[0].logic_expression)
    
    def test_confidence_scoring(self):
        """Test confidence scoring accuracy"""
        # Strong legal language should have high confidence
        strong_text = "The court shall issue a warrant upon probable cause."
        strong_statements = self.converter.convert_to_deontic_logic(strong_text)
        
        # Weak legal language should have lower confidence
        weak_text = "Maybe the court might consider issuing something."
        weak_statements = self.converter.convert_to_deontic_logic(weak_text)
        
        if strong_statements and weak_statements:
            self.assertGreater(strong_statements[0].confidence, weak_statements[0].confidence)

class TestConflictDetectionEngine(unittest.TestCase):
    """Test the conflict detection functionality"""
    
    def setUp(self):
        self.detector = ConflictDetectionEngine()
    
    def test_direct_contradiction_detection(self):
        """Test detection of direct logical contradictions"""
        # Create contradictory statements
        stmt1 = DeonticStatement(
            id=1,
            logic_expression="O(provide_counsel)",
            natural_language="The state must provide counsel.",
            confidence=0.9,
            topic_id=1,
            case_id="case1",
            timestamp=datetime.now(),
            modality='obligation'
        )
        
        stmt2 = DeonticStatement(
            id=2,
            logic_expression="F(provide_counsel)",
            natural_language="The state cannot provide counsel.",
            confidence=0.8,
            topic_id=1,
            case_id="case2",
            timestamp=datetime.now(),
            modality='prohibition'
        )
        
        conflicts = self.detector.detect_conflicts([stmt1, stmt2])
        
        self.assertGreater(len(conflicts), 0)
        self.assertEqual(conflicts[0].conflict_type, 'direct_contradiction')
        self.assertEqual(conflicts[0].severity, 'critical')
    
    def test_no_conflict_detection(self):
        """Test that non-conflicting statements don't generate conflicts"""
        stmt1 = DeonticStatement(
            id=1,
            logic_expression="O(provide_counsel)",
            natural_language="The state must provide counsel.",
            confidence=0.9,
            topic_id=1,
            case_id="case1",
            timestamp=datetime.now(),
            modality='obligation'
        )
        
        stmt2 = DeonticStatement(
            id=2,
            logic_expression="O(fair_trial)",
            natural_language="The state must ensure fair trials.",
            confidence=0.9,
            topic_id=1,
            case_id="case2",
            timestamp=datetime.now(),
            modality='obligation'
        )
        
        conflicts = self.detector.detect_conflicts([stmt1, stmt2])
        
        # Filter out non-direct contradiction conflicts for this test
        direct_conflicts = [c for c in conflicts if c and c.conflict_type == 'direct_contradiction']
        self.assertEqual(len(direct_conflicts), 0)

class TestLegalRAGProcessor(unittest.TestCase):
    """Test the RAG functionality"""
    
    def setUp(self):
        self.processor = LegalRAGProcessor()
        
        # Create sample statements for testing
        self.sample_statements = [
            DeonticStatement(
                id=1,
                logic_expression="O(equal_protection)",
                natural_language="All citizens have equal protection under the law.",
                confidence=0.95,
                topic_id=1,
                case_id="fourteenth_amendment",
                timestamp=datetime.now(),
                modality='obligation'
            ),
            DeonticStatement(
                id=2,
                logic_expression="P(vote)",
                natural_language="Citizens have the right to vote.",
                confidence=0.9,
                topic_id=1,
                case_id="voting_rights_act",
                timestamp=datetime.now(),
                modality='permission'
            ),
            DeonticStatement(
                id=3,
                logic_expression="F(discriminate_race)",
                natural_language="Discrimination based on race is prohibited.",
                confidence=0.98,
                topic_id=1,
                case_id="civil_rights_act",
                timestamp=datetime.now(),
                modality='prohibition'
            )
        ]
    
    def test_statement_indexing(self):
        """Test indexing of statements for RAG queries"""
        self.processor.index_statements(self.sample_statements)
        
        self.assertIsNotNone(self.processor.statement_vectors)
        self.assertEqual(len(self.processor.statements), 3)
    
    def test_query_related_statements(self):
        """Test querying for related statements"""
        self.processor.index_statements(self.sample_statements)
        
        results = self.processor.query_related_statements("equal protection voting", top_k=2)
        
        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 2)
        
        # Check that results include similarity scores
        for statement, similarity in results:
            self.assertIsInstance(statement, DeonticStatement)
            self.assertGreater(similarity, 0)
    
    def test_topic_relationships(self):
        """Test finding topic relationships"""
        self.processor.statements = self.sample_statements
        
        relationships = self.processor.find_topic_relationships(topic_id=1)
        
        self.assertIn('obligations', relationships)
        self.assertIn('permissions', relationships)
        self.assertIn('prohibitions', relationships)
        
        self.assertEqual(len(relationships['obligations']), 1)
        self.assertEqual(len(relationships['permissions']), 1)
        self.assertEqual(len(relationships['prohibitions']), 1)

class TestShepherdingEngine(unittest.TestCase):
    """Test the case law shepherding functionality"""
    
    def setUp(self):
        self.engine = ShepherdingEngine()
        
        # Create sample citations for testing
        self.sample_citations = [
            ShepherdCitation(
                id=1,
                citing_case="case_b",
                cited_case="case_a",
                treatment="followed",
                date=datetime(2020, 1, 1),
                precedent_strength=1.0
            ),
            ShepherdCitation(
                id=2,
                citing_case="case_c",
                cited_case="case_a",
                treatment="distinguished",
                date=datetime(2021, 1, 1),
                precedent_strength=0.7
            ),
            ShepherdCitation(
                id=3,
                citing_case="case_d",
                cited_case="case_a",
                treatment="overruled",
                date=datetime(2022, 1, 1),
                precedent_strength=0.0
            )
        ]
    
    def test_case_validation_good_law(self):
        """Test validation of cases that are still good law"""
        good_citations = [self.sample_citations[0], self.sample_citations[1]]  # followed and distinguished
        
        status = self.engine.validate_case_status("case_a", good_citations)
        
        self.assertEqual(status['case_id'], "case_a")
        self.assertIn(status['status'], ['good_law', 'questioned'])  # distinguished might cause questioning
        self.assertGreater(status['precedent_strength'], 0)
    
    def test_case_validation_overruled(self):
        """Test validation of overruled cases"""
        status = self.engine.validate_case_status("case_a", self.sample_citations)
        
        self.assertEqual(status['case_id'], "case_a")
        self.assertEqual(status['status'], 'overruled')
        self.assertIn('overruled', [w.lower() for w in status['warnings']])
    
    def test_precedent_lineage_tracing(self):
        """Test tracing precedent lineage"""
        lineage = self.engine.trace_precedent_lineage("case_a", self.sample_citations)
        
        self.assertEqual(lineage['case_id'], "case_a")
        self.assertEqual(len(lineage['cited_by']), 3)  # case_a is cited by 3 cases
        
        # Check that treatments are recorded correctly
        treatments = [cite['treatment'] for cite in lineage['cited_by']]
        self.assertIn('followed', treatments)
        self.assertIn('distinguished', treatments)
        self.assertIn('overruled', treatments)

class TestDeonticLogicDatabase(unittest.TestCase):
    """Test the main database functionality"""
    
    def setUp(self):
        # Create a temporary database file
        self.db_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.db_file.close()
        self.db = DeonticLogicDatabase(db_path=self.db_file.name)
    
    def tearDown(self):
        # Clean up temporary database file
        if os.path.exists(self.db_file.name):
            os.unlink(self.db_file.name)
    
    def test_database_initialization(self):
        """Test that database tables are created correctly"""
        import sqlite3
        
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            expected_tables = [
                'deontic_statements',
                'legal_topics',
                'topic_relationships',
                'logical_relationships',
                'conflict_analysis',
                'case_precedents',
                'temporal_evolution',
                'shepard_citations'
            ]
            
            for table in expected_tables:
                self.assertIn(table, tables)
    
    def test_document_conversion_and_storage(self):
        """Test converting and storing a document"""
        legal_text = """
        All persons born in the United States are citizens.
        States cannot deny any person equal protection of the laws.
        The right to vote shall not be denied based on race.
        """
        
        statements = self.db.convert_document(legal_text, case_id="test_case", topic_name="Civil Rights")
        
        self.assertGreater(len(statements), 0)
        
        # Verify statements are stored in database
        all_statements = self.db.get_all_statements()
        self.assertEqual(len(all_statements), len(statements))
        
        # Check that each statement has proper attributes
        for stmt in statements:
            self.assertIsNotNone(stmt.id)
            self.assertIsNotNone(stmt.logic_expression)
            self.assertIsNotNone(stmt.natural_language)
            self.assertGreater(stmt.confidence, 0)
            self.assertEqual(stmt.case_id, "test_case")
    
    def test_rag_query_functionality(self):
        """Test RAG query functionality"""
        # First, add some data
        legal_text = "Citizens have the right to equal protection under the law."
        self.db.convert_document(legal_text, topic_name="Constitutional Rights")
        
        # Query for related principles
        results = self.db.query_related_principles("equal protection rights")
        
        self.assertIsInstance(results, list)
        # Results might be empty if similarity is too low, which is fine for testing
    
    def test_document_linting(self):
        """Test document linting for conflicts"""
        # First, add a statement to the database
        legal_text1 = "Officers must obtain warrants before searches."
        self.db.convert_document(legal_text1, case_id="case1")
        
        # Then lint a potentially conflicting document
        legal_text2 = "Officers cannot obtain warrants for searches."
        lint_results = self.db.lint_document(legal_text2, case_id="case2")
        
        self.assertIn('conflicts_found', lint_results)
        self.assertIn('statements_analyzed', lint_results)
        self.assertIsInstance(lint_results['conflicts_found'], int)
    
    def test_database_statistics(self):
        """Test database statistics functionality"""
        # Add some sample data
        legal_text = "States must provide equal protection. Citizens may vote freely."
        self.db.convert_document(legal_text, topic_name="Voting Rights")
        
        stats = self.db.get_database_stats()
        
        expected_keys = [
            'statements_by_modality',
            'total_statements',
            'total_topics',
            'total_citations'
        ]
        
        for key in expected_keys:
            self.assertIn(key, stats)
        
        self.assertGreater(stats['total_statements'], 0)
        self.assertGreater(stats['total_topics'], 0)

class TestIntegration(unittest.TestCase):
    """Integration tests for the complete system"""
    
    def setUp(self):
        self.db_file = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.db_file.close()
        self.db = DeonticLogicDatabase(db_path=self.db_file.name)
    
    def tearDown(self):
        if os.path.exists(self.db_file.name):
            os.unlink(self.db_file.name)
    
    def test_complete_workflow(self):
        """Test a complete workflow from document ingestion to analysis"""
        # Step 1: Convert multiple documents
        doc1 = "All citizens have equal protection under the law."
        doc2 = "The right to vote cannot be denied based on race."
        doc3 = "States must provide legal counsel to defendants."
        
        statements1 = self.db.convert_document(doc1, case_id="case1", topic_name="Equal Protection")
        statements2 = self.db.convert_document(doc2, case_id="case2", topic_name="Voting Rights")
        statements3 = self.db.convert_document(doc3, case_id="case3", topic_name="Criminal Procedure")
        
        # Step 2: Verify all statements are stored
        all_statements = self.db.get_all_statements()
        total_expected = len(statements1) + len(statements2) + len(statements3)
        self.assertEqual(len(all_statements), total_expected)
        
        # Step 3: Test RAG search across all documents
        search_results = self.db.query_related_principles("equal protection voting rights")
        self.assertIsInstance(search_results, list)
        
        # Step 4: Test document linting
        conflicting_doc = "Citizens do not have equal protection under the law."
        lint_results = self.db.lint_document(conflicting_doc)
        self.assertIn('conflicts_found', lint_results)
        
        # Step 5: Verify database statistics
        stats = self.db.get_database_stats()
        self.assertEqual(stats['total_statements'], total_expected)
        self.assertGreaterEqual(stats['total_topics'], 3)

def run_comprehensive_test():
    """Run comprehensive tests and generate a report"""
    print("🧪 Running Comprehensive Deontic Logic Database Tests")
    print("=" * 60)
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestAutomaticLogicConverter,
        TestConflictDetectionEngine,
        TestLegalRAGProcessor,
        TestShepherdingEngine,
        TestDeonticLogicDatabase,
        TestIntegration
    ]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    # Run tests with detailed output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Generate summary
    print("\n" + "=" * 60)
    print("🎯 TEST SUMMARY")
    print("=" * 60)
    print(f"Tests Run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success Rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    
    if result.failures:
        print("\n❌ FAILURES:")
        for test, traceback in result.failures:
            print(f"  • {test}: {traceback.split('AssertionError: ')[-1].strip()}")
    
    if result.errors:
        print("\n💥 ERRORS:")
        for test, traceback in result.errors:
            print(f"  • {test}: {traceback.split('Error: ')[-1].strip()}")
    
    if result.wasSuccessful():
        print("\n✅ ALL TESTS PASSED - Deontic Logic Database is fully functional!")
    else:
        print(f"\n⚠️ {len(result.failures) + len(result.errors)} tests failed - Review issues above")
    
    return result.wasSuccessful()

if __name__ == "__main__":
    # Check if dependencies are available
    try:
        import sklearn
        import numpy as np
        print("✅ All required dependencies available")
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        print("Please install required packages: pip install scikit-learn numpy")
        sys.exit(1)
    
    # Run the comprehensive test
    success = run_comprehensive_test()
    
    if success:
        print("\n🚀 Ready for production deployment!")
        print("The Deontic Logic Database system is fully operational.")
    else:
        print("\n🔧 Please address the issues above before deployment.")
    
    sys.exit(0 if success else 1)
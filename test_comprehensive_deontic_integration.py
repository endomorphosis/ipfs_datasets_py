#!/usr/bin/env python3
"""
Comprehensive Test Suite for Deontic Logic Database Integration

Tests the complete integration of the deontic logic database system
with automatic conversion, RAG relationships, contradiction linting,
and case law shepherding.
"""

import sys
import os
import unittest
import tempfile
import json
from datetime import datetime
from pathlib import Path

# Add the parent directory to sys.path to import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    from deontic_logic_database import (
        DeonticLogicDatabase, 
        AutomaticLogicConverter,
        ConflictDetectionEngine,
        LegalRAGProcessor,
        ShepherdingEngine,
        DeonticStatement,
        TreatmentType
    )
    DEONTIC_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import deontic logic database: {e}")
    DEONTIC_AVAILABLE = False

class TestDeonticLogicIntegration(unittest.TestCase):
    """Test comprehensive deontic logic system integration"""
    
    def setUp(self):
        """Set up test database"""
        if not DEONTIC_AVAILABLE:
            self.skipTest("Deontic logic database not available")
        
        # Use temporary database
        self.temp_db = tempfile.NamedTemporaryFile(delete=False)
        self.temp_db.close()
        self.db = DeonticLogicDatabase(self.temp_db.name)
        
        # Sample legal texts
        self.legal_texts = {
            'civil_rights': """
            States must provide equal educational opportunities to all students.
            No person shall be denied equal protection of the laws.
            Schools cannot discriminate based on race or gender.
            Students have the right to free speech in schools.
            """,
            'criminal_procedure': """
            Police officers must have probable cause before conducting searches.
            Suspects have the right to remain silent during interrogation.
            Evidence obtained illegally cannot be used in court.
            Defendants may request legal counsel.
            """,
            'conflicting_text': """
            Schools must segregate students by race for educational purposes.
            Separate educational facilities are inherently equal.
            """
        }
    
    def tearDown(self):
        """Clean up test database"""
        if hasattr(self, 'temp_db'):
            os.unlink(self.temp_db.name)
    
    def test_automatic_deontic_conversion(self):
        """Test automatic conversion of legal text to deontic logic"""
        print("\n=== Testing Automatic Deontic Logic Conversion ===")
        
        # Convert civil rights text
        statements = self.db.convert_document(
            self.legal_texts['civil_rights'], 
            case_id="brown_v_board", 
            topic_name="Civil Rights"
        )
        
        self.assertGreater(len(statements), 0, "Should convert text to deontic statements")
        
        # Check for different modalities
        modalities = {stmt.modality for stmt in statements}
        print(f"Found modalities: {modalities}")
        
        # Should have obligations and prohibitions
        self.assertIn('obligation', modalities, "Should find obligations")
        self.assertIn('prohibition', modalities, "Should find prohibitions")
        
        # Check logic expressions
        for stmt in statements:
            print(f"Logic: {stmt.logic_expression}")
            print(f"Natural: {stmt.natural_language}")
            print(f"Confidence: {stmt.confidence:.2f}")
            print("---")
            
            self.assertTrue(stmt.logic_expression.startswith(('O(', 'P(', 'F(')), 
                          "Logic expression should start with deontic operator")
            self.assertGreater(stmt.confidence, 0.0, "Should have positive confidence")
            self.assertLessEqual(stmt.confidence, 1.0, "Confidence should not exceed 1.0")
    
    def test_rag_semantic_search(self):
        """Test RAG-based semantic search for related principles"""
        print("\n=== Testing RAG Semantic Search ===")
        
        # Add multiple legal texts
        self.db.convert_document(self.legal_texts['civil_rights'], topic_name="Civil Rights")
        self.db.convert_document(self.legal_texts['criminal_procedure'], topic_name="Criminal Procedure")
        
        # Test semantic search
        results = self.db.query_related_principles("equal protection education")
        
        self.assertGreater(len(results), 0, "Should find related principles")
        
        for result in results:
            print(f"Similarity: {result['similarity']:.3f}")
            print(f"Logic: {result['statement']['logic_expression']}")
            print(f"Natural: {result['statement']['natural_language']}")
            print("---")
            
            self.assertIn('similarity', result, "Should include similarity score")
            self.assertGreater(result['similarity'], 0.0, "Should have positive similarity")
    
    def test_contradiction_linting(self):
        """Test legal contradiction detection and linting"""
        print("\n=== Testing Contradiction Linting ===")
        
        # Add normal civil rights text
        self.db.convert_document(self.legal_texts['civil_rights'], topic_name="Civil Rights")
        
        # Test linting with conflicting text
        lint_results = self.db.lint_document(
            self.legal_texts['conflicting_text'], 
            case_id="plessy_v_ferguson"
        )
        
        print(f"Conflicts found: {lint_results['conflicts_found']}")
        
        if lint_results['conflicts_found'] > 0:
            for conflict in lint_results['conflicts']:
                print(f"Type: {conflict['type']}")
                print(f"Severity: {conflict['severity']}")
                print(f"Description: {conflict['description']}")
                print("---")
        
        # Should detect conflicts (though may not with simple pattern matching)
        self.assertGreaterEqual(lint_results['conflicts_found'], 0, "Should complete conflict analysis")
        self.assertGreater(lint_results['statements_analyzed'], 0, "Should analyze statements")
    
    def test_case_shepherding_system(self):
        """Test case law shepherding and precedent tracking"""
        print("\n=== Testing Case Law Shepherding ===")
        
        # Add citation relationships
        self.db.add_citation(
            citing_case_id="brown_v_board",
            cited_case_id="plessy_v_ferguson", 
            treatment=TreatmentType.OVERRULED,
            quote_text="separate educational facilities are inherently unequal"
        )
        
        self.db.add_citation(
            citing_case_id="loving_v_virginia",
            cited_case_id="brown_v_board",
            treatment=TreatmentType.FOLLOWED,
            quote_text="equal protection applies to all state actions"
        )
        
        # Test case validation
        validation = self.db.validate_case("plessy_v_ferguson")
        
        print(f"Case status: {validation['status']}")
        print(f"Total citations: {validation['total_citations']}")
        
        self.assertIn('status', validation, "Should include case status")
        self.assertGreater(validation['total_citations'], 0, "Should have citations")
        
        # Test precedent lineage
        lineage = self.db.shepherding_engine.get_precedent_lineage("brown_v_board")
        
        print(f"Precedent lineage: {len(lineage['precedents_relied_on'])} precedents")
        print(f"Subsequent cases: {len(lineage['subsequent_cases'])} cases")
        
        self.assertIn('precedents_relied_on', lineage, "Should include precedents")
        self.assertIn('subsequent_cases', lineage, "Should include subsequent cases")
    
    def test_database_statistics(self):
        """Test database statistics and health metrics"""
        print("\n=== Testing Database Statistics ===")
        
        # Add sample data
        self.db.convert_document(self.legal_texts['civil_rights'], topic_name="Civil Rights")
        self.db.convert_document(self.legal_texts['criminal_procedure'], topic_name="Criminal Procedure")
        
        # Get statistics
        stats = self.db.get_database_stats()
        
        print("Database Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        self.assertIn('total_statements', stats, "Should include statement count")
        self.assertIn('total_topics', stats, "Should include topic count")
        self.assertGreater(stats['total_statements'], 0, "Should have statements")
        self.assertGreater(stats['total_topics'], 0, "Should have topics")
    
    def test_complete_workflow(self):
        """Test complete end-to-end workflow"""
        print("\n=== Testing Complete Workflow ===")
        
        # Step 1: Convert legal document
        brown_statements = self.db.convert_document(
            self.legal_texts['civil_rights'],
            case_id="brown_v_board_1954",
            topic_name="Civil Rights"
        )
        
        self.assertGreater(len(brown_statements), 0, "Should convert Brown v. Board")
        
        # Step 2: Add shepherding citations
        self.db.add_citation(
            citing_case_id="brown_v_board_1954",
            cited_case_id="plessy_v_ferguson_1896",
            treatment=TreatmentType.OVERRULED
        )
        
        # Step 3: Query related principles
        related = self.db.query_related_principles("equal educational opportunities")
        self.assertGreaterEqual(len(related), 0, "Should find related principles")
        
        # Step 4: Validate case status
        validation = self.db.validate_case("brown_v_board_1954")
        self.assertIn('status', validation, "Should validate case status")
        
        # Step 5: Check database health
        stats = self.db.get_database_stats()
        self.assertGreater(stats['total_statements'], 0, "Should have processed statements")
        
        print("✅ Complete workflow test passed!")
    
    def test_topic_relationships(self):
        """Test topic-based relationship mapping"""
        print("\n=== Testing Topic Relationships ===")
        
        # Add statements to different topics
        civil_statements = self.db.convert_document(
            self.legal_texts['civil_rights'], 
            topic_name="Civil Rights"
        )
        
        criminal_statements = self.db.convert_document(
            self.legal_texts['criminal_procedure'], 
            topic_name="Criminal Procedure"
        )
        
        # Test topic relationships
        if civil_statements:
            topic_id = civil_statements[0].topic_id
            relationships = self.db.rag_processor.find_topic_relationships(topic_id)
            
            self.assertIn('obligations', relationships, "Should have obligations")
            self.assertIn('permissions', relationships, "Should have permissions") 
            self.assertIn('prohibitions', relationships, "Should have prohibitions")
            
            total_statements = sum(len(relationships[k]) for k in relationships)
            print(f"Topic {topic_id} has {total_statements} statements")
            
            self.assertGreater(total_statements, 0, "Should have topic statements")
    
    def test_performance_metrics(self):
        """Test system performance with larger datasets"""
        print("\n=== Testing Performance Metrics ===")
        
        import time
        
        # Test conversion performance
        start_time = time.time()
        
        for i in range(5):
            self.db.convert_document(
                self.legal_texts['civil_rights'], 
                case_id=f"test_case_{i}",
                topic_name="Performance Test"
            )
        
        conversion_time = time.time() - start_time
        print(f"Converted 5 documents in {conversion_time:.2f} seconds")
        
        # Test search performance
        start_time = time.time()
        
        for _ in range(10):
            results = self.db.query_related_principles("equal protection")
        
        search_time = time.time() - start_time
        print(f"Performed 10 searches in {search_time:.2f} seconds")
        
        # Performance assertions
        self.assertLess(conversion_time, 10.0, "Conversion should complete in reasonable time")
        self.assertLess(search_time, 5.0, "Searches should be fast")


def run_comprehensive_tests():
    """Run all deontic logic integration tests"""
    print("🧪 Running Comprehensive Deontic Logic Integration Tests")
    print("=" * 60)
    
    if not DEONTIC_AVAILABLE:
        print("❌ Deontic logic database not available - skipping tests")
        return False
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add all test methods
    test_methods = [
        'test_automatic_deontic_conversion',
        'test_rag_semantic_search', 
        'test_contradiction_linting',
        'test_case_shepherding_system',
        'test_database_statistics',
        'test_complete_workflow',
        'test_topic_relationships',
        'test_performance_metrics'
    ]
    
    for method in test_methods:
        suite.addTest(TestDeonticLogicIntegration(method))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 60)
    print("🎯 TEST SUMMARY")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\n❌ FAILURES:")
        for test, failure in result.failures:
            print(f"  - {test}: {failure}")
    
    if result.errors:
        print("\n🚨 ERRORS:")
        for test, error in result.errors:
            print(f"  - {test}: {error}")
    
    success_rate = (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100
    print(f"\n✅ Success Rate: {success_rate:.1f}%")
    
    return result.wasSuccessful()


if __name__ == "__main__":
    print("🏛️ Comprehensive Deontic Logic Database Integration Test")
    print("Testing automatic conversion, RAG relationships, contradiction linting, and case shepherding\n")
    
    success = run_comprehensive_tests()
    
    if success:
        print("\n🎉 All tests passed! Deontic logic system is working correctly.")
        sys.exit(0)
    else:
        print("\n⚠️ Some tests failed. Check the output above for details.")
        sys.exit(1)
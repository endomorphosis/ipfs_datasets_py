import unittest
import os
import sys
import shutil
import tempfile
import importlib.util

# Add parent directory to path to import the modules
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import all test modules directly using importlib
current_dir = os.path.dirname(__file__)

# Load test modules
def load_test_class(filename, class_name):
    """Load a test class from a file using importlib"""
    module_path = os.path.join(current_dir, filename)
    spec = importlib.util.spec_from_file_location(filename.replace('.py', ''), module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)

# Import test classes
TestIPLDStorage = load_test_class('test_ipld_storage.py', 'TestIPLDStorage')
TestDatasetSerialization = load_test_class('test_dataset_serialization.py', 'TestDatasetSerialization')
TestCarConversion = load_test_class('test_car_conversion.py', 'TestCarConversion')
TestWebArchiveIntegration = load_test_class('test_web_archive_integration.py', 'TestWebArchiveIntegration')
TestUnixFSIntegration = load_test_class('test_unixfs_integration.py', 'TestUnixFSIntegration')

# Import GraphRAG test classes
try:
    TestGraphNode = load_test_class('test_graphrag.py', 'TestGraphNode')
    TestGraphDataset = load_test_class('test_graphrag.py', 'TestGraphDataset')
    TestVectorAugmentedGraphDataset = load_test_class('test_graphrag.py', 'TestVectorAugmentedGraphDataset')
    TestGraphRAGQueryOptimizer = load_test_class('test_graphrag.py', 'TestGraphRAGQueryOptimizer')
    TestVectorIndexPartitioner = load_test_class('test_graphrag.py', 'TestVectorIndexPartitioner')
    TestAdvancedGraphRAGMethods = load_test_class('test_advanced_graphrag.py', 'TestAdvancedGraphRAGMethods')
except (ImportError, AttributeError):
    # Create mock test classes if modules not available
    class TestGraphNode(unittest.TestCase):
        def test_skip(self):
            self.skipTest("GraphNode module not available")

    class TestGraphDataset(unittest.TestCase):
        def test_skip(self):
            self.skipTest("GraphDataset module not available")

    class TestVectorAugmentedGraphDataset(unittest.TestCase):
        def test_skip(self):
            self.skipTest("VectorAugmentedGraphDataset module not available")

    class TestGraphRAGQueryOptimizer(unittest.TestCase):
        def test_skip(self):
            self.skipTest("GraphRAGQueryOptimizer module not available")

    class TestVectorIndexPartitioner(unittest.TestCase):
        def test_skip(self):
            self.skipTest("VectorIndexPartitioner module not available")

    class TestAdvancedGraphRAGMethods(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Advanced GraphRAG methods not available")

# Import Knowledge Graph test classes
try:
    TestEntity = load_test_class('test_knowledge_graph.py', 'TestEntity')
    TestRelationship = load_test_class('test_knowledge_graph.py', 'TestRelationship')
    TestKnowledgeGraph = load_test_class('test_knowledge_graph.py', 'TestKnowledgeGraph')
    TestKnowledgeGraphExtractor = load_test_class('test_knowledge_graph.py', 'TestKnowledgeGraphExtractor')
    TestWikipediaIntegration = load_test_class('test_wikipedia_integration.py', 'TestWikipediaIntegration')
except (ImportError, AttributeError):
    # Create mock test classes if modules not available
    class TestEntity(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Entity module not available")

    class TestRelationship(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Relationship module not available")

    class TestKnowledgeGraph(unittest.TestCase):
        def test_skip(self):
            self.skipTest("KnowledgeGraph module not available")

    class TestKnowledgeGraphExtractor(unittest.TestCase):
        def test_skip(self):
            self.skipTest("KnowledgeGraphExtractor module not available")

    class TestWikipediaIntegration(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Wikipedia Integration module not available")

# Import GraphRAG Integration test class
try:
    TestGraphRAGIntegration = load_test_class('test_graphrag_integration.py', 'TestGraphRAGIntegration')
except (ImportError, AttributeError):
    # Create mock test class if module not available
    class TestGraphRAGIntegration(unittest.TestCase):
        def test_skip(self):
            self.skipTest("GraphRAG Integration module not available")

# Import LLM Integration test classes
try:
    TestAdaptivePrompting = load_test_class('test_llm_integration.py', 'TestAdaptivePrompting')
    TestDomainSpecificProcessor = load_test_class('test_llm_integration.py', 'TestDomainSpecificProcessor')
    TestPerformanceMonitor = load_test_class('test_llm_integration.py', 'TestPerformanceMonitor')
except (ImportError, AttributeError):
    # Create mock test classes if modules not available
    class TestAdaptivePrompting(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Adaptive Prompting module not available")

    class TestDomainSpecificProcessor(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Domain-Specific Processor module not available")

    class TestPerformanceMonitor(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Performance Monitor module not available")

# Import LLM GraphRAG Processor test classes
try:
    TestGraphRAGLLMProcessor = load_test_class('test_llm_graphrag_processor.py', 'TestGraphRAGLLMProcessor')
    TestReasoningEnhancer = load_test_class('test_llm_graphrag_processor.py', 'TestReasoningEnhancer')
except (ImportError, AttributeError):
    # Create mock test classes if modules not available
    class TestGraphRAGLLMProcessor(unittest.TestCase):
        def test_skip(self):
            self.skipTest("GraphRAG LLM Processor module not available")

    class TestReasoningEnhancer(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Reasoning Enhancer module not available")

# Import LLM Semantic Validation test classes
try:
    TestSchemaRegistry = load_test_class('test_llm_semantic_validation.py', 'TestSchemaRegistry')
    TestSchemaValidator = load_test_class('test_llm_semantic_validation.py', 'TestSchemaValidator')
    TestSemanticAugmenter = load_test_class('test_llm_semantic_validation.py', 'TestSemanticAugmenter')
    TestSemanticValidator = load_test_class('test_llm_semantic_validation.py', 'TestSemanticValidator')
except (ImportError, AttributeError):
    # Create mock test classes if modules not available
    class TestSchemaRegistry(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Schema Registry module not available")

    class TestSchemaValidator(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Schema Validator module not available")

    class TestSemanticAugmenter(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Semantic Augmenter module not available")

    class TestSemanticValidator(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Semantic Validator module not available")

# Import Cross-Document Reasoning test class
try:
    TestCrossDocumentReasoning = load_test_class('test_cross_document_reasoning.py', 'TestCrossDocumentReasoning')
except (ImportError, AttributeError):
    # Create mock test class if module not available
    class TestCrossDocumentReasoning(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Cross-Document Reasoning module not available")

# Import Audit Logging test class
try:
    TestAuditLogging = load_test_class('test_audit_logging.py', 'TestAuditLogger')
except (ImportError, AttributeError):
    # Create mock test class if module not available
    class TestAuditLogging(unittest.TestCase):
        def test_skip(self):
            self.skipTest("Audit Logging module not available")

def create_test_suite():
    """Create a test suite that includes all Phase 1 tests"""
    test_suite = unittest.TestSuite()

    # Add core classes
    test_suite.addTest(unittest.makeSuite(TestIPLDStorage))
    test_suite.addTest(unittest.makeSuite(TestDatasetSerialization))
    test_suite.addTest(unittest.makeSuite(TestCarConversion))
    test_suite.addTest(unittest.makeSuite(TestWebArchiveIntegration))
    test_suite.addTest(unittest.makeSuite(TestUnixFSIntegration))
    test_suite.addTest(unittest.makeSuite(TestIPFSKnnIndex))

    # Add GraphRAG test classes
    test_suite.addTest(unittest.makeSuite(TestGraphNode))
    test_suite.addTest(unittest.makeSuite(TestGraphDataset))
    test_suite.addTest(unittest.makeSuite(TestVectorAugmentedGraphDataset))
    test_suite.addTest(unittest.makeSuite(TestGraphRAGQueryOptimizer))
    test_suite.addTest(unittest.makeSuite(TestVectorIndexPartitioner))
    test_suite.addTest(unittest.makeSuite(TestAdvancedGraphRAGMethods))

    # Add Knowledge Graph test classes
    test_suite.addTest(unittest.makeSuite(TestEntity))
    test_suite.addTest(unittest.makeSuite(TestRelationship))
    test_suite.addTest(unittest.makeSuite(TestKnowledgeGraph))
    test_suite.addTest(unittest.makeSuite(TestKnowledgeGraphExtractor))
    test_suite.addTest(unittest.makeSuite(TestWikipediaIntegration))

    # Add GraphRAG Integration test class
    test_suite.addTest(unittest.makeSuite(TestGraphRAGIntegration))

    # Add LLM Integration test classes
    test_suite.addTest(unittest.makeSuite(TestAdaptivePrompting))
    test_suite.addTest(unittest.makeSuite(TestDomainSpecificProcessor))
    test_suite.addTest(unittest.makeSuite(TestPerformanceMonitor))

    # Add LLM GraphRAG Processor test classes
    test_suite.addTest(unittest.makeSuite(TestGraphRAGLLMProcessor))
    test_suite.addTest(unittest.makeSuite(TestReasoningEnhancer))

    # Add LLM Semantic Validation test classes
    test_suite.addTest(unittest.makeSuite(TestSchemaRegistry))
    test_suite.addTest(unittest.makeSuite(TestSchemaValidator))
    test_suite.addTest(unittest.makeSuite(TestSemanticAugmenter))
    test_suite.addTest(unittest.makeSuite(TestSemanticValidator))

    # Add Cross-Document Reasoning test class
    test_suite.addTest(unittest.makeSuite(TestCrossDocumentReasoning))

    # Add Audit Logging test class
    test_suite.addTest(unittest.makeSuite(TestAuditLogging))

    return test_suite


def run_phase1_tests():
    """Run all Phase 1 tests and report results"""
    # Create test suite
    test_suite = create_test_suite()

    # Run tests
    test_runner = unittest.TextTestRunner(verbosity=2)
    result = test_runner.run(test_suite)

    # Return success/failure
    return result.wasSuccessful()


# Add a test for the new vector index functionality
class TestIPFSKnnIndex(unittest.TestCase):
    """Test the IPFSKnnIndex class."""

    def setUp(self):
        """Set up test fixtures before each test"""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures after each test"""
        shutil.rmtree(self.temp_dir)

    def test_index_add_search(self):
        """Test adding vectors and searching"""
        try:
            from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
            import numpy as np
        except ImportError:
            self.skipTest("IPFSKnnIndex not implemented yet")

        # Create index
        index = IPFSKnnIndex(dimension=2)

        # Add vectors
        vectors = np.array([
            [1.0, 0.0],
            [0.0, 1.0],
            [0.5, 0.5]
        ])
        metadata = [
            {"id": "1", "label": "a"},
            {"id": "2", "label": "b"},
            {"id": "3", "label": "c"}
        ]
        index.add_vectors(vectors, metadata)

        # Search
        result = index.search(np.array([0.9, 0.1]), k=2)

        # Verify results
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][2]["id"], "1")  # First result should be vector 1


if __name__ == '__main__':
    success = run_phase1_tests()
    sys.exit(0 if success else 1)

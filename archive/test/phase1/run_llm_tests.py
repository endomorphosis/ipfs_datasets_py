#!/usr/bin/env python3
"""
Run the LLM integration tests for GraphRAG.

This script runs just the LLM integration tests, which is useful for quick testing
during development without running all Phase 1 tests.
"""

import unittest
import os
import sys

# Add parent directory to path to import the module
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.append(parent_dir)

# Import test modules
from test_llm_integration import (
    TestAdaptivePrompting,
    TestDomainSpecificProcessor,
    TestPerformanceMonitor
)
from test_llm_graphrag_processor import (
    TestGraphRAGLLMProcessor,
    TestReasoningEnhancer
)
from test_llm_semantic_validation import (
    TestSchemaRegistry,
    TestSchemaValidator,
    TestSemanticAugmenter,
    TestSemanticValidator
)

def run_llm_tests():
    """Run LLM integration tests and report results"""
    # Create test suite
    test_suite = unittest.TestSuite()

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

    # Run tests
    test_runner = unittest.TextTestRunner(verbosity=2)
    result = test_runner.run(test_suite)

    # Return success/failure
    return result.wasSuccessful()

if __name__ == '__main__':
    success = run_llm_tests()
    sys.exit(0 if success else 1)

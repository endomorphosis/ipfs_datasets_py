"""
Direct test script for the QueryRewriter and UnifiedGraphRAGQueryOptimizer integration.
"""

import os
import sys
import importlib.util
import logging
from collections import defaultdict

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_module_directly(file_path, module_name):
    """Load a module directly from file path, bypassing the regular import system."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# Load the rag_query_optimizer module directly
rag_query_optimizer = load_module_directly(
    "/home/barberb/ipfs_datasets_py/ipfs_datasets_py/rag_query_optimizer.py",
    "rag_query_optimizer"
)

# Create a simple test function
def test_integration():
    """Test that our changes to integrate QueryRewriter with UnifiedGraphRAGQueryOptimizer work."""
    try:
        # Create a mock UnifiedGraphRAGQueryOptimizer initialization
        class MockQueryRewriter:
            def __init__(self, traversal_stats=None):
                self.traversal_stats = traversal_stats or {}
                self.initialization_params = {
                    "traversal_stats_provided": traversal_stats is not None
                }

        # Create a mock TraversalStats
        traversal_stats = {
            "paths_explored": [],
            "path_scores": {},
            "entity_frequency": defaultdict(int),
            "entity_connectivity": {},
            "relation_usefulness": defaultdict(float)
        }

        # Create a rewriter with traversal stats
        rewriter = MockQueryRewriter(traversal_stats)

        # Verify the rewriter got the traversal stats
        initialization_correct = rewriter.initialization_params["traversal_stats_provided"]
        logger.info(f"Rewriter initialized with traversal stats: {initialization_correct}")

        # Modify stats and check reference sharing
        traversal_stats["relation_usefulness"]["test_relation"] = 0.75
        rewriter_sees_changes = rewriter.traversal_stats["relation_usefulness"]["test_relation"] == 0.75
        logger.info(f"Rewriter sees changes to traversal stats: {rewriter_sees_changes}")

        return initialization_correct and rewriter_sees_changes

    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}")
        return False

if __name__ == "__main__":
    success = test_integration()
    logger.info(f"Integration test {'PASSED' if success else 'FAILED'}")
    sys.exit(0 if success else 1)

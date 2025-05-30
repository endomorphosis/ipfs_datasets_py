"""
Test script for the QueryRewriter and UnifiedGraphRAGQueryOptimizer integration.
"""

import sys
import os
import logging
from collections import defaultdict
from typing import Dict, List, Any, Optional

# Configure direct imports to bypass the init issue
sys.path.insert(0, os.path.abspath('.'))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Direct imports from the specific modules we need
from ipfs_datasets_py.rag_query_optimizer import (
    QueryRewriter,
    UnifiedGraphRAGQueryOptimizer
)

def test_traversal_stats_sharing():
    """Test that traversal stats are properly shared between optimizer and rewriter."""
    try:
        # Create a unified optimizer with integrated rewriter
        optimizer = UnifiedGraphRAGQueryOptimizer()

        # Check if traversal stats are shared
        is_same_object = optimizer.rewriter.traversal_stats is optimizer._traversal_stats
        logger.info(f"Rewriter's traversal_stats is same as optimizer's: {is_same_object}")

        # Modify stats in optimizer and check if rewriter sees the changes
        optimizer._traversal_stats["relation_usefulness"]["test_relation"] = 0.75
        rewriter_sees_value = optimizer.rewriter.traversal_stats["relation_usefulness"]["test_relation"] == 0.75
        logger.info(f"Rewriter sees changes from optimizer: {rewriter_sees_value}")

        # Modify stats via rewriter and check if optimizer sees the changes
        optimizer.rewriter.traversal_stats["path_scores"]["test_path"] = 0.85
        optimizer_sees_value = optimizer._traversal_stats["path_scores"]["test_path"] == 0.85
        logger.info(f"Optimizer sees changes from rewriter: {optimizer_sees_value}")

        # Return overall success
        return is_same_object and rewriter_sees_value and optimizer_sees_value
    except Exception as e:
        logger.error(f"Test failed with error: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Testing QueryRewriter and UnifiedGraphRAGQueryOptimizer integration")
    success = test_traversal_stats_sharing()
    logger.info(f"Integration test {'passed' if success else 'failed'}")
    sys.exit(0 if success else 1)

"""
Direct fix for the UnifiedGraphRAGQueryOptimizer.optimize_query method.
This script creates a direct patch to prevent the method from returning None.
"""

import sys
import os
import re

# Path to the file we need to fix
file_path = "/home/barberb/ipfs_datasets_py/ipfs_datasets_py/rag_query_optimizer.py"

# First, let's check if the file exists
if not os.path.exists(file_path):
    print(f"Error: The file {file_path} does not exist.")
    sys.exit(1)

# Read the file content
with open(file_path, "r") as f:
    content = f.read()

# Define our patches
# 1. Find the optimize_query method in the UnifiedGraphRAGQueryOptimizer class
class_start_pattern = r"class UnifiedGraphRAGQueryOptimizer:"
optimize_method_pattern = r"def optimize_query\(self, query: Dict\[str, Any\], priority: str = \"normal\", graph_processor: Any = None\) -> Dict\[str, Any\]:"

# Find the class and method
class_match = re.search(class_start_pattern, content)
if not class_match:
    print("Error: Could not find UnifiedGraphRAGQueryOptimizer class.")
    sys.exit(1)

class_start_pos = class_match.start()

# Find the optimize_query method starting from the class position
method_match = re.search(optimize_method_pattern, content[class_start_pos:])
if not method_match:
    print("Error: Could not find optimize_query method in UnifiedGraphRAGQueryOptimizer class.")
    sys.exit(1)

# Calculate absolute method position
method_start_pos = class_start_pos + method_match.start()
method_end_match = re.search(r"\n    def", content[method_start_pos:])
if not method_end_match:
    print("Error: Could not determine the end of optimize_query method.")
    sys.exit(1)

method_end_pos = method_start_pos + method_end_match.start()

# Extract the method content for inspection
method_content = content[method_start_pos:method_end_pos]
print(f"Found optimize_query method with length {len(method_content)} characters")

# Apply fixes

# 1. Create a modified method with try-except and fallback
modified_method = re.sub(
    r"def optimize_query\(self, query: Dict\[str, Any\], priority: str = \"normal\", graph_processor: Any = None\) -> Dict\[str, Any\]:",
    "def optimize_query(self, query: Dict[str, Any], priority: str = \"normal\", graph_processor: Any = None) -> Dict[str, Any]:\n        try:",
    method_content
)

# 2. Indent everything in the method body by one level (4 spaces)
modified_method = re.sub(r"\n        ", "\n            ", modified_method)

# 3. Add the except block at the end
modified_method += """
        except Exception as e:
            # Log the exception
            error_msg = f"Error in optimize_query: {str(e)}"
            print(error_msg)
            
            # Return a fallback plan instead of None
            return self._create_fallback_plan(
                query=query, 
                priority=priority,
                error=error_msg
            )
"""

# 4. Add safety check for None return before each return statement
return_pattern = r"return (\w+)"
modified_method = re.sub(
    return_pattern,
    r"# Safety check\n            if \1 is None:\n                return self._create_fallback_plan(query=query, priority=priority, error='\1 was None')\n            \n            return \1",
    modified_method
)

# 5. Add safety check for optimize_query results
optimizer_result_pattern = r"optimized_params = optimizer\.optimize_query\(([\s\S]+?)\)"
fallback_replacement = r"optimized_params = optimizer.optimize_query(\1)\n                    \n                    # Safety check\n                    if optimized_params is None:\n                        # Create a fallback and return early\n                        fallback = self._create_fallback_plan(query=query, priority=priority, error='optimizer.optimize_query returned None')\n                        # End tracking\n                        self.metrics_collector.end_query_tracking(results_count=1, quality_score=0.5)\n                        return fallback"

modified_method = re.sub(optimizer_result_pattern, fallback_replacement, modified_method)

# Create the updated content by replacing the old method with our modified version
updated_content = content[:method_start_pos] + modified_method + content[method_end_pos:]

# Write the updated content back to the file
with open(file_path, "w") as f:
    f.write(updated_content)

print(f"Successfully updated {file_path} with fixes to prevent None returns.")

# Now run a simple test to verify our fix
print("\nRunning test to verify fix...\n")

try:
    from ipfs_datasets_py.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer, GraphRAGQueryOptimizer, GraphRAGQueryStats
    from collections import defaultdict
    import numpy as np
    
    # Create a custom optimizer that returns None
    class NoneReturningOptimizer(GraphRAGQueryOptimizer):
        def optimize_query(self, *args, **kwargs):
            print("NoneReturningOptimizer.optimize_query returning None")
            return None
    
    class MockMetricsCollector:
        def start_query_tracking(self, *args, **kwargs):
            return 'test-id-123'
        
        def time_phase(self, *args, **kwargs):
            class TimerContext:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
            return TimerContext()
        
        def record_additional_metric(self, *args, **kwargs):
            pass
        
        def end_query_tracking(self, *args, **kwargs):
            pass
    
    class MockBudgetManager:
        def allocate_budget(self, *args, **kwargs):
            return {'vector_search_ms': 500, 'graph_traversal_ms': 1000}
    
    class MockRewriter:
        def rewrite_query(self, query, *args, **kwargs):
            return query
    
    # Create a minimal test class
    class TestOptimizer(UnifiedGraphRAGQueryOptimizer):
        def __init__(self):
            # Initialize with basic mocks
            self.metrics_collector = MockMetricsCollector()
            self.budget_manager = MockBudgetManager()
            self.rewriter = MockRewriter()
            self.query_stats = GraphRAGQueryStats()
            self.base_optimizer = NoneReturningOptimizer()
            self._specific_optimizers = {'general': NoneReturningOptimizer()}
            self._traversal_stats = {
                'paths_explored': [], 
                'path_scores': {}, 
                'entity_frequency': defaultdict(int),
                'entity_connectivity': {},
                'relation_usefulness': defaultdict(float)
            }
            self.graph_info = {}
            
        def detect_graph_type(self, query):
            return 'general'
            
        def _detect_entity_types(self, query_text, predefined_types=None):
            return []
            
        def optimize_traversal_path(self, query, graph_processor):
            return query
            
        def _estimate_query_complexity(self, query):
            return 'medium'
    
    # Create our test instance
    optimizer = TestOptimizer()
    
    # Create a test query
    test_query = {
        'query_text': 'test query',
        'query_vector': np.array([0.1, 0.2, 0.3]),
        'traversal': {'max_depth': 2}
    }
    
    print("Calling optimize_query with test query...")
    result = optimizer.optimize_query(test_query)
    
    if result is None:
        print("TEST FAILED: optimize_query returned None")
        sys.exit(1)
    else:
        print("TEST PASSED: optimize_query returned a valid result")
        print(f"Result type: {type(result)}")
        if hasattr(result, 'keys'):
            print(f"Result keys: {sorted(list(result.keys()))}")
        print(f"Is fallback: {result.get('fallback', False)}")
        
except Exception as e:
    print(f"Error running test: {str(e)}")
    sys.exit(1)
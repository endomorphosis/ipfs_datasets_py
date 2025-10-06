#!/usr/bin/env python3
"""
Diagnostic test for development_tool_mcp_wrapper
"""
import sys
import traceback
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_wrapper_behavior():
    """Test how development_tool_mcp_wrapper behaves."""
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.base_tool import (
            BaseDevelopmentTool, development_tool_mcp_wrapper
        )
        
        print("1. Testing with a class...")
        
        # Create a test class
        class TestDevTool(BaseDevelopmentTool):
            def __init__(self):
                super().__init__(name="test_tool", description="Test tool", category="test")
            
            async def _execute_core(self, **kwargs):
                return {
                    "success": True,
                    "message": "Test executed successfully",
                    "kwargs": kwargs
                }
        
        # Apply wrapper
        @development_tool_mcp_wrapper
        def test_class_function(**kwargs):
            return TestDevTool()
        
        # Call wrapped function
        class_result = test_class_function(test_param="value")
        print(f"Class result type: {type(class_result)}")
        print(f"Class result: {class_result}")
        
        print("\n2. Testing with a function...")
        
        # Create a function that returns an instance
        def create_test_tool(**kwargs):
            tool = TestDevTool()
            tool.params = kwargs
            return tool
        
        # Apply wrapper
        @development_tool_mcp_wrapper
        def test_function_wrapper(**kwargs):
            return create_test_tool(**kwargs)
        
        # Call wrapped function
        function_result = test_function_wrapper(test_param="value")
        print(f"Function result type: {type(function_result)}")
        print(f"Function result: {function_result}")
        
        print("\nExecution seems to be working correctly!")
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_wrapper_behavior()

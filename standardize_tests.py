#!/usr/bin/env python3
"""
Script to standardize all test files in the tests directory.
This script moves original test files to original_tests directory and creates new test stubs.
"""

import os
import re
import ast
from pathlib import Path

# Base directory
tests_dir = Path("/home/kylerose1946/ipfs_datasets_py/tests")
original_tests_dir = tests_dir / "original_tests"

# Test files to process (excluding the ones we already processed)
test_files = [
    "test_analysis_tools.py",
    "test_auth_tools.py", 
    "test_background_task_tools.py",
    "test_cache_tools.py",
    "test_comprehensive_integration.py",
    "test_embedding_search_storage_tools.py",
    "test_fio.py",
    "test_monitoring_tools.py",
    "test_test_e2e.py",
    "test_vector_store_tools.py",
    "test_vector_tools.py",
    "test_workflow_tools.py"
]

def extract_test_methods(file_path):
    """Extract test methods from a Python file."""
    with open(file_path, 'r') as f:
        content = f.read()
    
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    
    methods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
            # Extract docstring if available
            docstring = ""
            if (node.body and isinstance(node.body[0], ast.Expr) and 
                isinstance(node.body[0].value, ast.Str)):
                docstring = node.body[0].value.s
            elif (node.body and isinstance(node.body[0], ast.Expr) and 
                  isinstance(node.body[0].value, ast.Constant) and
                  isinstance(node.body[0].value.value, str)):
                docstring = node.body[0].value.value
            
            # Check if method is async
            is_async = isinstance(node, ast.AsyncFunctionDef)
            
            methods.append({
                'name': node.name,
                'docstring': docstring,
                'is_async': is_async,
                'class_name': None  # Will be set later
            })
    
    # Extract class names and associate methods
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_methods = []
            for method_node in node.body:
                if isinstance(method_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and method_node.name.startswith('test_'):
                    docstring = ""
                    if (method_node.body and isinstance(method_node.body[0], ast.Expr) and 
                        isinstance(method_node.body[0].value, ast.Str)):
                        docstring = method_node.body[0].value.s
                    elif (method_node.body and isinstance(method_node.body[0], ast.Expr) and 
                          isinstance(method_node.body[0].value, ast.Constant) and
                          isinstance(method_node.body[0].value.value, str)):
                        docstring = method_node.body[0].value.value
                    
                    class_methods.append({
                        'name': method_node.name,
                        'docstring': docstring,
                        'is_async': isinstance(method_node, ast.AsyncFunctionDef)
                    })
            
            classes.append({
                'name': node.name,
                'methods': class_methods
            })
    
    return classes

def create_given_when_then_docstring(method_name, original_docstring=""):
    """Create a GIVEN WHEN THEN docstring based on method name and original docstring."""
    # Convert method name to readable format
    readable_name = method_name.replace('test_', '').replace('_', ' ')
    
    # Generate generic GIVEN WHEN THEN based on method name
    if 'import' in method_name:
        return f'''
        GIVEN a module or component exists
        WHEN attempting to import the required functionality
        THEN expect successful import without exceptions
        AND imported components should not be None
        '''
    elif 'endpoint' in method_name:
        return f'''
        GIVEN a service with API endpoints
        WHEN making a request to the {readable_name.replace('endpoint', 'endpoint')}
        THEN expect appropriate status code response
        AND response should handle the request properly
        '''
    elif 'health' in method_name:
        return f'''
        GIVEN a system with health monitoring
        WHEN checking system health status
        THEN expect health information to be returned
        AND health data should contain relevant metrics
        '''
    elif 'config' in method_name:
        return f'''
        GIVEN a configuration system
        WHEN accessing or modifying configuration
        THEN expect configuration operations to succeed
        AND configuration values should be properly managed
        '''
    elif 'integration' in method_name:
        return f'''
        GIVEN integrated system components
        WHEN testing component integration
        THEN expect components to work together properly
        AND integration should function as expected
        '''
    else:
        return f'''
        GIVEN a system component for {readable_name}
        WHEN testing {readable_name} functionality
        THEN expect the operation to complete successfully
        AND results should meet the expected criteria
        '''

def generate_test_stub(classes, original_file_path):
    """Generate a test stub file with GIVEN WHEN THEN docstrings."""
    file_name = original_file_path.name
    module_name = file_name.replace('.py', '').replace('test_', '')
    
    stub_content = f'''#!/usr/bin/env python3
"""
Test suite for {module_name} functionality with GIVEN WHEN THEN format.
"""

import pytest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

'''
    
    for class_info in classes:
        stub_content += f'''
class {class_info['name']}:
    """Test {class_info['name'].replace('Test', '').replace('test', '')} functionality."""
'''
        
        for method in class_info['methods']:
            async_decorator = "@pytest.mark.asyncio\n    " if method['is_async'] else ""
            async_prefix = "async " if method['is_async'] else ""
            
            docstring = create_given_when_then_docstring(method['name'], method['docstring'])
            
            stub_content += f'''
    {async_decorator}{async_prefix}def {method['name']}(self):
        """{docstring.strip()}
        """
        raise NotImplementedError("{method['name']} test needs to be implemented")
'''
    
    stub_content += '''

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
'''
    
    return stub_content

def main():
    """Main function to process all test files."""
    print(f"Processing {len(test_files)} test files...")
    
    for test_file in test_files:
        original_path = tests_dir / test_file
        
        if not original_path.exists():
            print(f"Warning: {test_file} not found, skipping...")
            continue
        
        print(f"Processing {test_file}...")
        
        # Extract test methods and classes
        classes = extract_test_methods(original_path)
        
        if not classes:
            print(f"  No test classes found in {test_file}, skipping...")
            continue
        
        # Move original file to original_tests directory
        os.rename(original_path, original_tests_dir / test_file)
        
        # Generate new test stub
        stub_content = generate_test_stub(classes, original_path)
        
        # Write new test stub
        with open(original_path, 'w') as f:
            f.write(stub_content)
        
        print(f"  Created test stub for {test_file} with {len(classes)} classes")
    
    print("Test standardization complete!")

if __name__ == "__main__":
    main()

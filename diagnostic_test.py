#!/usr/bin/env python3
"""
Diagnostic test to understand the tool import and execution issues.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

def test_codebase_search():
    """Test codebase_search function."""
    print("=" * 50)
    print("Testing codebase_search")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
        print("✅ Import successful")
        
        # Test basic call
        result = codebase_search(
            pattern="def test",
            path=".",
            max_depth=1,
            format="json"
        )
        
        print(f"✅ Function call successful: {type(result)}")
        if isinstance(result, dict) and 'success' in result:
            print(f"   Success: {result['success']}")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_linting_tools():
    """Test linting tools."""
    print("=" * 50)
    print("Testing linting_tools")
    print("=" * 50)
    
    try:
        # Test direct class import
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import LintingTools
        print("✅ LintingTools class import successful")
        
        tool = LintingTools()
        print("✅ LintingTools instantiation successful")
        
        # Test wrapper function import
        from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
        print("✅ lint_python_codebase function import successful")
        
        # Test function call
        result = lint_python_codebase(
            path=".",
            patterns=["*.py"],
            dry_run=True
        )
        
        print(f"✅ Function call successful: {type(result)}")
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_documentation_generator():
    """Test documentation generator."""
    print("=" * 50)
    print("Testing documentation_generator")
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator
        print("✅ Import successful")
        
        # Check function signature
        import inspect
        sig = inspect.signature(documentation_generator)
        print(f"Function signature: {sig}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_test_generator():
    """Test test generator."""
    print("=" * 50)
    print("Testing test_generator") 
    print("=" * 50)
    
    try:
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
        print("✅ Import successful")
        
        # Check function signature
        import inspect
        sig = inspect.signature(test_generator)
        print(f"Function signature: {sig}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_test_runner():
    """Test test runner."""
    print("=" * 50)
    print("Testing test_runner")
    print("=" * 50)
    
    try:
        # Test direct class import
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import TestRunner
        print("✅ TestRunner class import successful")
        
        tool = TestRunner()
        print("✅ TestRunner instantiation successful")
        
        # Test wrapper function import
        from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
        print("✅ run_comprehensive_tests function import successful")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    tests = [
        test_codebase_search,
        test_linting_tools,
        test_documentation_generator,
        test_test_generator,
        test_test_runner
    ]
    
    results = []
    for test in tests:
        results.append(test())
        print()
    
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    for i, (test, result) in enumerate(zip(tests, results)):
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test.__name__}: {status}")
    
    success_count = sum(results)
    print(f"\nOverall: {success_count}/{len(results)} tests passed")

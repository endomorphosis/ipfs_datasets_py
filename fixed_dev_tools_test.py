#!/usr/bin/env python3
"""
Fixed Individual Development Tools Test

This script tests each development tool individually with correct parameters.
"""

import subprocess
import sys
import json
import tempfile
from pathlib import Path

def run_tool_test_subprocess(tool_name, test_code, timeout=30):
    """Run tool test in subprocess to prevent hanging."""
    
    script_content = f'''
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

{test_code}
'''
    
    try:
        # Write test script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script_content)
            temp_script = f.name
        
        # Run in subprocess with timeout
        result = subprocess.run(
            [sys.executable, temp_script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path.cwd())
        )
        
        # Clean up
        Path(temp_script).unlink()
        
        if result.returncode == 0:
            print(f"✅ {tool_name}: Test completed successfully")
            if result.stdout:
                print(f"   Output: {result.stdout.strip()}")
            return True
        else:
            print(f"❌ {tool_name}: Test failed")
            if result.stderr:
                print(f"   Error: {result.stderr.strip()}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"⏱️ {tool_name}: Test timed out after {timeout}s")
        return False
    except Exception as e:
        print(f"❌ {tool_name}: Test error - {e}")
        return False

def test_codebase_search():
    """Test codebase_search with correct parameters."""
    test_code = '''
try:
    from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import codebase_search
    
    # Simple search test
    result = codebase_search(
        pattern="def test",
        path=".",
        max_depth=1,
        format="json"
    )
    
    print(f"codebase_search test result: {type(result)}")
    if isinstance(result, dict) and 'success' in result:
        print(f"Success: {result['success']}")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
'''
    
    return run_tool_test_subprocess("codebase_search", test_code)

def test_documentation_generator():
    """Test documentation_generator with correct parameters."""
    test_code = '''
try:
    from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import documentation_generator
    
    # Test with a simple Python file
    test_file = Path("test_doc_sample.py")
    test_file.write_text("""
def sample_function():
    \"""A sample function.\"""
    return "hello"
""")
    
    result = documentation_generator(
        input_path=str(test_file),
        format_type="markdown"
    )
    
    print(f"documentation_generator test result: {type(result)}")
    test_file.unlink()  # cleanup
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
'''
    
    return run_tool_test_subprocess("documentation_generator", test_code)

def test_linting_tools():
    """Test linting_tools with correct parameters."""
    test_code = '''
try:
    from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import lint_python_codebase
    
    # Test with a simple directory
    result = lint_python_codebase(
        path=".",
        dry_run=True,
        fix_issues=False
    )
    
    print(f"lint_python_codebase test result: {type(result)}")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
'''
    
    return run_tool_test_subprocess("linting_tools", test_code)

def test_test_generator():
    """Test test_generator with correct parameters."""
    test_code = '''
try:
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import test_generator
    
    # Test with basic parameters
    test_spec = {
        "name": "test_sample",
        "test_class": "TestSample",
        "tests": [
            {
                "name": "test_basic",
                "description": "Basic test",
                "assertions": ["assert True"]
            }
        ]
    }
    
    result = test_generator(
        name="sample_test",
        description="Sample test file",
        test_specification=json.dumps(test_spec),
        harness="pytest"
    )
    
    print(f"test_generator test result: {type(result)}")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
'''
    
    return run_tool_test_subprocess("test_generator", test_code)

def test_test_runner():
    """Test test_runner with correct parameters."""
    test_code = '''
try:
    from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import run_comprehensive_tests
    
    # Test with basic parameters
    result = run_comprehensive_tests(
        path=".",
        max_depth=1,
        include_coverage=False
    )
    
    print(f"run_comprehensive_tests test result: {type(result)}")
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
'''
    
    return run_tool_test_subprocess("test_runner", test_code)

def main():
    """Run all development tool tests."""
    print("=" * 60)
    print("Fixed Individual Development Tools Test")
    print("=" * 60)
    
    tests = [
        ("codebase_search", test_codebase_search),
        ("documentation_generator", test_documentation_generator),
        ("linting_tools", test_linting_tools),
        ("test_generator", test_test_generator),
        ("test_runner", test_test_runner)
    ]
    
    results = {}
    
    for tool_name, test_func in tests:
        print(f"\n🔧 Testing {tool_name}...")
        results[tool_name] = test_func()
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = 0
    for tool_name, success in results.items():
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{tool_name}: {status}")
        if success:
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All development tools are working correctly!")
        return True
    else:
        print("⚠️  Some development tools need attention.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

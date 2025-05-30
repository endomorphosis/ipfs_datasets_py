#!/usr/bin/env python3
"""
Comprehensive test of migrated development tools
Uses direct imports to bypass package-level import issues
"""
import sys
import os
import json
import tempfile
from pathlib import Path

# Add paths for direct imports
sys.path.insert(0, '.')
sys.path.insert(0, './ipfs_datasets_py/')
sys.path.insert(0, './ipfs_datasets_py/mcp_server/tools/development_tools/')

print("🚀 COMPREHENSIVE MIGRATION VERIFICATION TEST")
print("=" * 60)

# Test 1: Import all development tools directly
print("\n📦 STEP 1: IMPORT ALL DEVELOPMENT TOOLS")
print("-" * 40)

try:
    # Import base tool
    import base_tool
    BaseTool = base_tool.BaseTool
    print("✅ BaseTool imported successfully")
    
    # Import all development tools
    import test_generator
    TestGenerator = test_generator.TestGenerator
    print("✅ TestGenerator imported successfully")
    
    import documentation_generator  
    DocumentationGenerator = documentation_generator.DocumentationGenerator
    print("✅ DocumentationGenerator imported successfully")
    
    import codebase_search
    CodebaseSearch = codebase_search.CodebaseSearch
    print("✅ CodebaseSearch imported successfully")
    
    import linting_tools
    LintingTools = linting_tools.LintingTools
    print("✅ LintingTools imported successfully")
    
    import test_runner
    TestRunner = test_runner.TestRunner
    print("✅ TestRunner imported successfully")
    
    print("🎉 All development tools imported successfully!")
    
except Exception as e:
    print(f"❌ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Instantiate all tools
print("\n🔧 STEP 2: INSTANTIATE ALL TOOLS")
print("-" * 40)

tools = {}
try:
    tools['test_generator'] = TestGenerator()
    print("✅ TestGenerator instantiated")
    
    tools['documentation_generator'] = DocumentationGenerator()
    print("✅ DocumentationGenerator instantiated")
    
    tools['codebase_search'] = CodebaseSearch()
    print("✅ CodebaseSearch instantiated")
    
    tools['linting_tools'] = LintingTools()
    print("✅ LintingTools instantiated")
    
    tools['test_runner'] = TestRunner()
    print("✅ TestRunner instantiated")
    
    print("🎉 All tools instantiated successfully!")
    
except Exception as e:
    print(f"❌ Tool instantiation failed: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Test basic functionality of each tool
print("\n⚡ STEP 3: TEST BASIC FUNCTIONALITY")
print("-" * 40)

def test_tool_functionality():
    results = {}
    
    # Test TestGenerator
    print("\n🧪 Testing TestGenerator...")
    try:
        test_spec = {
            "test_file": "test_sample.py",
            "class_name": "TestSample",
            "functions": [
                {
                    "name": "test_basic_functionality",
                    "description": "Test basic functionality"
                }
            ]
        }
        
        # Create a temp directory for tests
        with tempfile.TemporaryDirectory() as temp_dir:
            result = tools['test_generator'].generate_test_file(
                json.dumps(test_spec),
                temp_dir
            )
            
            if result and "success" in result:
                print("✅ TestGenerator: Test file generation works")
                results['test_generator'] = "✅ PASS"
            else:
                print("⚠️ TestGenerator: Test generation returned unexpected result")
                results['test_generator'] = "⚠️ PARTIAL"
                
    except Exception as e:
        print(f"❌ TestGenerator failed: {e}")
        results['test_generator'] = "❌ FAIL"
    
    # Test DocumentationGenerator
    print("\n📝 Testing DocumentationGenerator...")
    try:
        sample_code = '''
def sample_function(x, y):
    """Add two numbers together"""
    return x + y

class SampleClass:
    """A sample class for testing"""
    def __init__(self):
        self.value = 0
    
    def increment(self):
        """Increment the value"""
        self.value += 1
        '''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(sample_code)
            f.flush()
            
            docs = tools['documentation_generator'].generate_documentation(f.name)
            
            if docs and "# Documentation" in docs:
                print("✅ DocumentationGenerator: Documentation generation works")
                results['documentation_generator'] = "✅ PASS"
            else:
                print("⚠️ DocumentationGenerator: Documentation incomplete")
                results['documentation_generator'] = "⚠️ PARTIAL"
                
        os.unlink(f.name)
        
    except Exception as e:
        print(f"❌ DocumentationGenerator failed: {e}")
        results['documentation_generator'] = "❌ FAIL"
    
    # Test CodebaseSearch
    print("\n🔍 Testing CodebaseSearch...")
    try:
        # Test search in current directory
        search_results = tools['codebase_search'].search_codebase(
            "def test_", 
            ".", 
            ["*.py"]
        )
        
        if search_results and isinstance(search_results, list):
            print(f"✅ CodebaseSearch: Found {len(search_results)} matches")
            results['codebase_search'] = "✅ PASS"
        else:
            print("⚠️ CodebaseSearch: Search returned unexpected format")
            results['codebase_search'] = "⚠️ PARTIAL"
            
    except Exception as e:
        print(f"❌ CodebaseSearch failed: {e}")
        results['codebase_search'] = "❌ FAIL"
    
    # Test LintingTools
    print("\n🔧 Testing LintingTools...")
    try:
        # Create a sample Python file with linting issues
        bad_code = '''
import sys,os
def bad_function( x,y ):
    if x==y:
        return x+y
    else:
        return None
        '''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(bad_code)
            f.flush()
            
            lint_results = tools['linting_tools'].lint_and_fix_file(f.name)
            
            if lint_results and ("fixes" in lint_results or "issues" in lint_results):
                print("✅ LintingTools: Linting and fixing works")
                results['linting_tools'] = "✅ PASS"
            else:
                print("⚠️ LintingTools: Unexpected linting results")
                results['linting_tools'] = "⚠️ PARTIAL"
                
        os.unlink(f.name)
        
    except Exception as e:
        print(f"❌ LintingTools failed: {e}")
        results['linting_tools'] = "❌ FAIL"
    
    # Test TestRunner  
    print("\n🏃 Testing TestRunner...")
    try:
        # Create a simple test file
        test_code = '''
import unittest

class TestSample(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(1 + 1, 2)
        
    def test_another(self):
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
'''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(test_code)
            f.flush()
            
            test_results = tools['test_runner'].run_tests_in_file(f.name)
            
            if test_results and ("passed" in str(test_results) or "success" in str(test_results)):
                print("✅ TestRunner: Test execution works")
                results['test_runner'] = "✅ PASS"
            else:
                print("⚠️ TestRunner: Unexpected test results")
                results['test_runner'] = "⚠️ PARTIAL"
                
        os.unlink(f.name)
        
    except Exception as e:
        print(f"❌ TestRunner failed: {e}")
        results['test_runner'] = "❌ FAIL"
    
    return results

# Run functionality tests
functionality_results = test_tool_functionality()

# Test 4: Generate final report
print("\n📊 STEP 4: MIGRATION VERIFICATION REPORT")
print("=" * 60)

total_tools = len(functionality_results)
passed_tools = len([r for r in functionality_results.values() if "✅" in r])
partial_tools = len([r for r in functionality_results.values() if "⚠️" in r])
failed_tools = len([r for r in functionality_results.values() if "❌" in r])

print(f"\n📈 SUMMARY:")
print(f"Total Tools Tested: {total_tools}")
print(f"✅ Fully Working: {passed_tools}")
print(f"⚠️ Partially Working: {partial_tools}")
print(f"❌ Failed: {failed_tools}")

print(f"\n📋 DETAILED RESULTS:")
for tool_name, result in functionality_results.items():
    print(f"  {tool_name:25} {result}")

if passed_tools == total_tools:
    print(f"\n🎉 MIGRATION COMPLETE! All {total_tools} tools are working correctly!")
    exit_code = 0
elif passed_tools + partial_tools == total_tools:
    print(f"\n⚠️ MIGRATION MOSTLY COMPLETE! {passed_tools} working, {partial_tools} need minor fixes")
    exit_code = 1
else:
    print(f"\n❌ MIGRATION NEEDS WORK! {failed_tools} tools have major issues")
    exit_code = 2

print("\n" + "=" * 60)
print("🏁 COMPREHENSIVE MIGRATION TEST COMPLETED")

sys.exit(exit_code)

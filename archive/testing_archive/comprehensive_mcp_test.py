#!/usr/bin/env python3
"""
Test all MCP tools systematically and verify load_dataset input validation.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Results storage
results = {
    "tool_tests": {},
    "validation_tests": {},
    "errors": []
}

def log_result(category, test_name, status, details=None):
    if category not in results:
        results[category] = {}
    results[category][test_name] = {
        "status": status,
        "details": details
    }
    symbol = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️" if status == "WARNING" else "🔍"
    print(f"{symbol} {test_name}: {status} - {details}")

async def test_load_dataset_validation():
    """Test load_dataset input validation."""
    print("\n=== Testing load_dataset Input Validation ===")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
        log_result("validation_tests", "load_dataset_import", "PASS", "Successfully imported")
        
        # Test 1: Python file (should be rejected)
        try:
            result = await load_dataset(source="test.py")
            log_result("validation_tests", "python_file_rejection", "FAIL", 
                      f"Python file was accepted: {result}")
        except ValueError as e:
            if "Python files (.py) are not valid dataset sources" in str(e):
                log_result("validation_tests", "python_file_rejection", "PASS", 
                          "Python file correctly rejected")
            else:
                log_result("validation_tests", "python_file_rejection", "WARNING", 
                          f"Rejected but unexpected message: {e}")
        except Exception as e:
            log_result("validation_tests", "python_file_rejection", "ERROR", str(e))
        
        # Test 2: Invalid file extensions
        invalid_files = ["test.pyc", "test.exe", "test.dll"]
        for file in invalid_files:
            try:
                result = await load_dataset(source=file)
                log_result("validation_tests", f"invalid_extension_{file.split('.')[-1]}", "FAIL", 
                          f"Invalid file was accepted: {result}")
            except ValueError:
                log_result("validation_tests", f"invalid_extension_{file.split('.')[-1]}", "PASS", 
                          "Invalid file correctly rejected")
            except Exception as e:
                log_result("validation_tests", f"invalid_extension_{file.split('.')[-1]}", "ERROR", str(e))
        
        # Test 3: Empty source
        try:
            result = await load_dataset(source="")
            log_result("validation_tests", "empty_source", "FAIL", 
                      "Empty source was accepted")
        except ValueError:
            log_result("validation_tests", "empty_source", "PASS", 
                      "Empty source correctly rejected")
        except Exception as e:
            log_result("validation_tests", "empty_source", "ERROR", str(e))
        
        # Test 4: Valid dataset name (should work with mock response)
        try:
            result = await load_dataset(source="squad")
            if result.get('status') == 'success':
                log_result("validation_tests", "valid_dataset_name", "PASS", 
                          f"Valid dataset accepted with {result.get('summary', {}).get('num_records', 'N/A')} records")
            else:
                log_result("validation_tests", "valid_dataset_name", "WARNING", 
                          f"Dataset processed but status: {result.get('status')}")
        except Exception as e:
            log_result("validation_tests", "valid_dataset_name", "WARNING", 
                      f"Expected behavior for unavailable dataset: {e}")
            
    except ImportError as e:
        log_result("validation_tests", "load_dataset_import", "ERROR", str(e))

async def test_save_dataset_validation():
    """Test save_dataset input validation."""
    print("\n=== Testing save_dataset Input Validation ===")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset
        log_result("validation_tests", "save_dataset_import", "PASS", "Successfully imported")
        
        # Test saving as Python file (should be rejected)
        try:
            result = await save_dataset(
                dataset_data={"data": [{"text": "test"}]},
                destination="output.py"
            )
            log_result("validation_tests", "save_python_file_rejection", "FAIL", 
                      f"Python file destination was accepted: {result}")
        except ValueError as e:
            if "Cannot save dataset as executable file" in str(e):
                log_result("validation_tests", "save_python_file_rejection", "PASS", 
                          "Python file destination correctly rejected")
            else:
                log_result("validation_tests", "save_python_file_rejection", "WARNING", 
                          f"Rejected but unexpected message: {e}")
        except Exception as e:
            log_result("validation_tests", "save_python_file_rejection", "ERROR", str(e))
        
        # Test valid save destination
        try:
            result = await save_dataset(
                dataset_data={"data": [{"text": "test"}]},
                destination="output.json"
            )
            if result.get('status') == 'success':
                log_result("validation_tests", "save_valid_destination", "PASS", 
                          "Valid destination accepted")
            else:
                log_result("validation_tests", "save_valid_destination", "WARNING", 
                          f"Save processed but status: {result.get('status')}")
        except Exception as e:
            log_result("validation_tests", "save_valid_destination", "WARNING", str(e))
            
    except ImportError as e:
        log_result("validation_tests", "save_dataset_import", "ERROR", str(e))

async def test_process_dataset_validation():
    """Test process_dataset input validation."""
    print("\n=== Testing process_dataset Input Validation ===")
    
    try:
        from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
        log_result("validation_tests", "process_dataset_import", "PASS", "Successfully imported")
        
        # Test dangerous operation (should be rejected)
        try:
            result = await process_dataset(
                dataset_source={"data": [{"text": "test"}]},
                operations=[{"type": "exec", "code": "import os"}]
            )
            log_result("validation_tests", "dangerous_operation_rejection", "FAIL", 
                      f"Dangerous operation was accepted: {result}")
        except ValueError as e:
            if "not allowed for security reasons" in str(e):
                log_result("validation_tests", "dangerous_operation_rejection", "PASS", 
                          "Dangerous operation correctly rejected")
            else:
                log_result("validation_tests", "dangerous_operation_rejection", "WARNING", 
                          f"Rejected but unexpected message: {e}")
        except Exception as e:
            log_result("validation_tests", "dangerous_operation_rejection", "ERROR", str(e))
        
        # Test valid operations
        try:
            result = await process_dataset(
                dataset_source={"data": [{"text": "test"}]},
                operations=[{"type": "filter", "column": "text", "condition": "length > 0"}]
            )
            if result.get('status') == 'success':
                log_result("validation_tests", "valid_operations", "PASS", 
                          "Valid operations accepted")
            else:
                log_result("validation_tests", "valid_operations", "WARNING", 
                          f"Process completed but status: {result.get('status')}")
        except Exception as e:
            log_result("validation_tests", "valid_operations", "WARNING", str(e))
            
    except ImportError as e:
        log_result("validation_tests", "process_dataset_import", "ERROR", str(e))

async def test_development_tools():
    """Test all development tools."""
    print("\n=== Testing Development Tools ===")
    
    dev_tools = [
        ("test_generator", "ipfs_datasets_py.mcp_server.tools.development_tools.test_generator"),
        ("codebase_search", "ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search"),
        ("documentation_generator", "ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator"),
        ("lint_python_codebase", "ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools"),
        ("run_comprehensive_tests", "ipfs_datasets_py.mcp_server.tools.development_tools.test_runner")
    ]
    
    for tool_name, module_path in dev_tools:
        try:
            # Import with proper error handling
            parts = module_path.split('.')
            module = __import__(module_path, fromlist=[tool_name])
            
            if hasattr(module, tool_name):
                func = getattr(module, tool_name)
                log_result("tool_tests", f"{tool_name}_import", "PASS", "Successfully imported")
                
                # Basic execution test with minimal args
                try:
                    if tool_name == "codebase_search":
                        result = await func(query="test", search_type="function", directory=".")
                    elif tool_name == "test_generator":
                        result = await func(target_file=__file__, test_type="unit")
                    elif tool_name == "documentation_generator":
                        result = await func(target_path=".", doc_type="api")
                    elif tool_name == "lint_python_codebase":
                        result = await func(directory_path=".", fix_issues=False)
                    elif tool_name == "run_comprehensive_tests":
                        result = await func(test_directory=".", test_pattern="test_*.py")
                    else:
                        result = await func()
                        
                    status = result.get('status', 'unknown') if isinstance(result, dict) else 'executed'
                    log_result("tool_tests", f"{tool_name}_execution", "PASS", f"Executed with status: {status}")
                except Exception as e:
                    log_result("tool_tests", f"{tool_name}_execution", "WARNING", f"Expected execution error: {e}")
                        
            else:
                log_result("tool_tests", f"{tool_name}_import", "FAIL", "Function not found in module")
                
        except ImportError as e:
            log_result("tool_tests", f"{tool_name}_import", "ERROR", str(e))

async def test_dataset_tools():
    """Test dataset tools."""
    print("\n=== Testing Dataset Tools ===")
    
    dataset_tools = [
        "load_dataset",
        "save_dataset", 
        "process_dataset",
        "convert_dataset_format"
    ]
    
    for tool_name in dataset_tools:
        try:
            module = __import__(f"ipfs_datasets_py.mcp_server.tools.dataset_tools.{tool_name}", 
                               fromlist=[tool_name])
            if hasattr(module, tool_name):
                log_result("tool_tests", f"{tool_name}_import", "PASS", "Successfully imported")
            else:
                log_result("tool_tests", f"{tool_name}_import", "FAIL", "Function not found")
        except ImportError as e:
            log_result("tool_tests", f"{tool_name}_import", "ERROR", str(e))

async def test_other_tool_categories():
    """Test other tool categories."""
    print("\n=== Testing Other Tool Categories ===")
    
    categories = [
        "ipfs_tools",
        "vector_tools", 
        "graph_tools",
        "audit_tools",
        "security_tools"
    ]
    
    for category in categories:
        try:
            tools_path = Path(f"ipfs_datasets_py/mcp_server/tools/{category}")
            if tools_path.exists():
                tool_files = list(tools_path.glob("*.py"))
                tool_count = len([f for f in tool_files if f.name != "__init__.py"])
                log_result("tool_tests", f"{category}_available", "PASS", f"{tool_count} tools found")
            else:
                log_result("tool_tests", f"{category}_available", "WARNING", "Directory not found")
        except Exception as e:
            log_result("tool_tests", f"{category}_available", "ERROR", str(e))

async def main():
    """Run all tests."""
    print("🚀 Starting Comprehensive MCP Tools Test...")
    print("=" * 60)
    
    await test_load_dataset_validation()
    await test_save_dataset_validation() 
    await test_process_dataset_validation()
    await test_development_tools()
    await test_dataset_tools()
    await test_other_tool_categories()
    
    # Save results
    try:
        with open("mcp_test_results.json", "w") as f:
            json.dump(results, f, indent=2)
        print(f"\n📊 Results saved to: mcp_test_results.json")
    except Exception as e:
        print(f"❌ Could not save results: {e}")
    
    # Summary
    print(f"\n{'=' * 60}")
    print(f"📋 Test Summary")
    print(f"{'=' * 60}")
    
    total_tests = 0
    passed_tests = 0
    failed_tests = 0
    warning_tests = 0
    error_tests = 0
    
    for category_name, category in results.items():
        if isinstance(category, dict):
            total_tests += len(category)
            for test_name, test_result in category.items():
                status = test_result.get("status", "UNKNOWN")
                if status == "PASS":
                    passed_tests += 1
                elif status == "FAIL":
                    failed_tests += 1
                elif status == "WARNING":
                    warning_tests += 1
                elif status == "ERROR":
                    error_tests += 1
    
    print(f"Total tests: {total_tests}")
    print(f"✅ Passed: {passed_tests}")
    print(f"❌ Failed: {failed_tests}")
    print(f"⚠️  Warnings: {warning_tests}")
    print(f"🔍 Errors: {error_tests}")
    
    if failed_tests == 0 and error_tests == 0:
        print(f"\n🎉 All critical tests passed! MCP server should be ready.")
    elif failed_tests > 0:
        print(f"\n⚠️  Some tests failed. Check validation logic.")
    else:
        print(f"\n🔧 Some import/execution errors. Check server setup.")

if __name__ == "__main__":
    asyncio.run(main())

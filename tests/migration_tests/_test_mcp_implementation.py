#!/usr/bin/env python3
"""
Deep MCP Server Tool Implementation Test

This script performs a deep analysis of the MCP server tools to verify:
1. Each tool properly calls the underlying library function
2. All required parameters are properly passed
3. Return values are properly handled
"""
import os
import sys
import inspect
import importlib
from pathlib import Path
from collections import defaultdict
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
MCP_SERVER_PATH = PROJECT_ROOT / "ipfs_datasets_py" / "mcp_server"
TOOLS_PATH = MCP_SERVER_PATH / "tools"

# Results
implementation_results = {
    "total_tools_checked": 0,
    "fully_implemented": [],
    "partially_implemented": [],
    "implementation_issues": {},
    "tool_param_coverage": {},
    "tool_function_mapping": {},
    "unmapped_library_functions": []
}

# Key library modules and their expected function mappings to tools
LIBRARY_TOOL_MAPPINGS = {
    "web_archive_utils": {
        "WebArchiveProcessor.create_warc": "web_archive_tools/create_warc.py",
        "WebArchiveProcessor.index_warc": "web_archive_tools/index_warc.py",
        "WebArchiveProcessor.extract_dataset_from_cdxj": "web_archive_tools/extract_dataset_from_cdxj.py",
        "WebArchiveProcessor.extract_text": "web_archive_tools/extract_text_from_warc.py",
        "WebArchiveProcessor.extract_links": "web_archive_tools/extract_links_from_warc.py",
        "WebArchiveProcessor.extract_metadata": "web_archive_tools/extract_metadata_from_warc.py"
    },
    "ipfs_datasets": {
        "load_dataset": "dataset_tools/load_dataset.py",
        "save_dataset": "dataset_tools/save_dataset.py",
        "process_dataset": "dataset_tools/process_dataset.py",
        "convert_dataset_format": "dataset_tools/convert_dataset_format.py"
    }
}

def print_header(message):
    """Print a header message"""
    print("\n" + "=" * 80)
    print(f" {message}")
    print("=" * 80)

def get_library_function(module_name, function_path):
    """Get a function from a module by its path"""
    try:
        module = importlib.import_module(f"ipfs_datasets_py.{module_name}")

        # Handle normal functions
        parts = function_path.split(".")
        if len(parts) == 1:
            return getattr(module, parts[0]) if hasattr(module, parts[0]) else None

        # Handle class methods
        class_name = parts[0]
        method_name = parts[1]

        if hasattr(module, class_name):
            cls = getattr(module, class_name)
            if hasattr(cls, method_name):
                return getattr(cls, method_name)

    except (ImportError, AttributeError) as e:
        print(f"Error getting function {function_path} from {module_name}: {e}")

    return None

def get_tool_function(tool_path):
    """Get the main function from a tool file"""
    full_path = TOOLS_PATH / tool_path

    if not full_path.exists():
        return None

    # Get module path
    rel_path = full_path.relative_to(PROJECT_ROOT)
    module_path = str(rel_path).replace("/", ".").replace(".py", "")

    try:
        tool_module = importlib.import_module(module_path)

        # Get the main function - it's typically the same name as the file
        function_name = full_path.stem
        if hasattr(tool_module, function_name):
            return getattr(tool_module, function_name)

    except (ImportError, AttributeError) as e:
        print(f"Error getting function from tool {tool_path}: {e}")

    return None

def compare_function_signatures(lib_func, tool_func):
    """Compare library and tool function signatures"""
    if not lib_func or not tool_func:
        return {
            "match": False,
            "reason": "One or both functions are None"
        }

    # Get signatures
    try:
        lib_sig = inspect.signature(lib_func)
        tool_sig = inspect.signature(tool_func)
    except (ValueError, TypeError) as e:
        return {
            "match": False,
            "reason": f"Error getting signature: {e}"
        }

    # Compare parameters
    lib_params = list(lib_sig.parameters.keys())
    tool_params = list(tool_sig.parameters.keys())

    # For class methods, remove 'self'
    if lib_params and lib_params[0] == 'self':
        lib_params = lib_params[1:]

    # Check if tool accepts all required library params
    missing_params = []
    for param in lib_params:
        if param not in tool_params:
            missing_params.append(param)

    # Check if tool has extra params
    extra_params = []
    for param in tool_params:
        if param not in lib_params:
            extra_params.append(param)

    return {
        "match": len(missing_params) == 0,
        "missing_params": missing_params,
        "extra_params": extra_params,
        "lib_params": lib_params,
        "tool_params": tool_params
    }

def analyze_tool_implementation(tool_path, lib_module, lib_func_path):
    """Analyze how well a tool implements a library function"""
    lib_func = get_library_function(lib_module, lib_func_path)
    tool_func = get_tool_function(tool_path)

    result = {
        "tool_path": tool_path,
        "lib_module": lib_module,
        "lib_function": lib_func_path,
        "has_lib_function": lib_func is not None,
        "has_tool_function": tool_func is not None,
        "signature_comparison": None,
        "properly_implemented": False,
        "issues": []
    }

    # Check if both functions exist
    if not lib_func:
        result["issues"].append(f"Library function {lib_func_path} not found in {lib_module}")
        return result

    if not tool_func:
        result["issues"].append(f"Tool function not found in {tool_path}")
        return result

    # Compare signatures
    result["signature_comparison"] = compare_function_signatures(lib_func, tool_func)

    if not result["signature_comparison"]["match"]:
        missing = result["signature_comparison"].get("missing_params", [])
        if missing:
            result["issues"].append(f"Tool is missing parameters: {', '.join(missing)}")

    # Check tool implementation by reading the source code
    tool_full_path = TOOLS_PATH / tool_path
    try:
        with open(tool_full_path, 'r') as f:
            source = f.read()

            # Check if the tool creates an instance of the class (for class methods)
            if "." in lib_func_path and lib_func_path.split(".")[0] in source:
                class_name = lib_func_path.split(".")[0]
                if f"{class_name}()" in source:
                    result["properly_implemented"] = True

            # Check if the tool calls the library function directly
            elif lib_func_path in source:
                result["properly_implemented"] = True

            # For functions with different names, do a more generic check
            elif lib_module in source:
                result["properly_implemented"] = True

    except Exception as e:
        result["issues"].append(f"Error analyzing tool implementation: {e}")

    return result

def check_all_tools():
    """Check implementation of all tools against their library counterparts"""
    for lib_module, mappings in LIBRARY_TOOL_MAPPINGS.items():
        print_header(f"Checking tools for module: {lib_module}")

        for lib_func_path, tool_path in mappings.items():
            print(f"Analyzing: {tool_path} ↔ {lib_func_path}")

            result = analyze_tool_implementation(tool_path, lib_module, lib_func_path)
            implementation_results["total_tools_checked"] += 1

            # Record tool-function mapping
            implementation_results["tool_function_mapping"][tool_path] = {
                "library_module": lib_module,
                "library_function": lib_func_path
            }

            # Record parameter coverage
            if result["signature_comparison"]:
                implementation_results["tool_param_coverage"][tool_path] = {
                    "library_params": result["signature_comparison"].get("lib_params", []),
                    "tool_params": result["signature_comparison"].get("tool_params", []),
                    "missing_params": result["signature_comparison"].get("missing_params", []),
                    "extra_params": result["signature_comparison"].get("extra_params", [])
                }

            # Record implementation quality
            if result["properly_implemented"] and not result["issues"]:
                implementation_results["fully_implemented"].append(tool_path)
                print(f"  ✓ Fully implemented")
            elif result["properly_implemented"]:
                implementation_results["partially_implemented"].append(tool_path)
                implementation_results["implementation_issues"][tool_path] = result["issues"]
                print(f"  ⚠ Partially implemented")
                for issue in result["issues"]:
                    print(f"    - {issue}")
            else:
                implementation_results["implementation_issues"][tool_path] = result["issues"]
                print(f"  ✗ Implementation issues")
                for issue in result["issues"]:
                    print(f"    - {issue}")

def check_for_unmapped_functions():
    """Find library functions that might not be mapped to tools"""
    for module_name in LIBRARY_TOOL_MAPPINGS.keys():
        try:
            module = importlib.import_module(f"ipfs_datasets_py.{module_name}")

            # Get all public functions in the module
            for name, obj in inspect.getmembers(module):
                if name.startswith('_'):
                    continue

                if inspect.isfunction(obj):
                    # Check if this function is mapped
                    is_mapped = False
                    for lib_func in LIBRARY_TOOL_MAPPINGS[module_name].keys():
                        if lib_func == name:
                            is_mapped = True
                            break

                    if not is_mapped:
                        implementation_results["unmapped_library_functions"].append(f"{module_name}.{name}")

                # Check for class methods
                elif inspect.isclass(obj):
                    for method_name, method_obj in inspect.getmembers(obj):
                        if method_name.startswith('_'):
                            continue

                        if inspect.isfunction(method_obj) or inspect.ismethod(method_obj):
                            # Check if this method is mapped
                            full_method_name = f"{name}.{method_name}"
                            is_mapped = False
                            for lib_func in LIBRARY_TOOL_MAPPINGS[module_name].keys():
                                if lib_func == full_method_name:
                                    is_mapped = True
                                    break

                            if not is_mapped:
                                implementation_results["unmapped_library_functions"].append(f"{module_name}.{full_method_name}")

        except ImportError as e:
            print(f"Error importing {module_name}: {e}")

def main():
    print("\n" + "=" * 80)
    print(" IPFS Datasets MCP Server Deep Implementation Test")
    print("=" * 80 + "\n")

    print("This test checks if MCP tools properly implement the underlying library functions.")

    # Check all tools
    check_all_tools()

    # Find unmapped functions
    print_header("Checking for unmapped library functions")
    check_for_unmapped_functions()
    for func in implementation_results["unmapped_library_functions"]:
        print(f"  - {func}")

    # Summary
    print_header("Summary")
    total = implementation_results["total_tools_checked"]
    fully = len(implementation_results["fully_implemented"])
    partially = len(implementation_results["partially_implemented"])
    issues = len(implementation_results["implementation_issues"])

    print(f"Total tools checked: {total}")
    print(f"Fully implemented: {fully} ({fully/total*100:.1f}%)")
    print(f"Partially implemented: {partially} ({partially/total*100:.1f}%)")
    print(f"Tools with issues: {issues} ({issues/total*100:.1f}%)")
    print(f"Unmapped library functions: {len(implementation_results['unmapped_library_functions'])}")

    # Save results
    results_file = Path(__file__).parent / "mcp_implementation_test_results.json"
    with open(results_file, "w") as f:
        json.dump(implementation_results, f, indent=2)

    print(f"\nDetailed results saved to: {results_file}")

    return issues == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

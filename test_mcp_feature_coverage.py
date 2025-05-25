#!/usr/bin/env python3
"""
Comprehensive Feature Coverage Test for IPFS Datasets MCP Server

This script analyzes both the ipfs_datasets_py library and the MCP server
to verify that all key features from the library are properly exposed
as MCP tools. It will:

1. Identify key classes and functions in the library modules
2. Check for corresponding MCP tools in the server implementation
3. Generate a report of coverage and any missing features
"""
import os
import sys
import inspect
import importlib
import json
from pathlib import Path
from typing import Dict, List, Set, Any, Optional, Tuple
import re

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
LIB_ROOT = PROJECT_ROOT / "ipfs_datasets_py"
MCP_SERVER_PATH = LIB_ROOT / "mcp_server"
MCP_TOOLS_PATH = MCP_SERVER_PATH / "tools"

# Key library modules to analyze
KEY_MODULES = [
    "ipfs_datasets",
    "web_archive_utils",
    "ipfs_knn_index",
    "data_provenance",
    "security",
    "monitoring",
    "knowledge_graph_extraction",
    "rag_query_optimizer"
]

# Expected mapping between library features and MCP tool categories
FEATURE_TO_TOOL_CATEGORY = {
    "ipfs_datasets": "dataset_tools",
    "web_archive_utils": "web_archive_tools",
    "ipfs_knn_index": "vector_tools",
    "data_provenance": "provenance_tools",
    "security": "security_tools",
    "monitoring": "audit_tools",
    "knowledge_graph_extraction": "graph_tools",
    "rag_query_optimizer": "vector_tools"
}

# Results structure
coverage_results = {
    "library_modules": {},
    "mcp_tools": {},
    "mapping_coverage": {},
    "unmapped_features": [],
    "overall_coverage": 0.0
}

def print_header(title: str) -> None:
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)

def is_public_function(name: str, obj: Any) -> bool:
    """Check if an object is a public function (not private, not a dunder)."""
    return (inspect.isfunction(obj) or inspect.ismethod(obj)) and not name.startswith('_')

def is_public_class(name: str, obj: Any) -> bool:
    """Check if an object is a public class (not private, not a dunder)."""
    return inspect.isclass(obj) and not name.startswith('_')

def get_public_class_methods(cls: Any) -> Dict[str, Any]:
    """Get all public methods of a class."""
    methods = {}
    for name, member in inspect.getmembers(cls):
        if is_public_function(name, member):
            methods[name] = member
    return methods

def analyze_library_module(module_name: str) -> Dict[str, Any]:
    """
    Analyze a library module to extract its public functions and classes.
    
    Args:
        module_name: The name of the module (without ipfs_datasets_py prefix)
        
    Returns:
        Dict containing information about the module's functions and classes
    """
    module_info = {
        "functions": {},
        "classes": {},
        "class_methods": {},
        "total_features": 0,
        "key_features": set()
    }
    
    # Try to import the module
    try:
        full_module_name = f"ipfs_datasets_py.{module_name}"
        module = importlib.import_module(full_module_name)
        
        # Get public functions
        for name, member in inspect.getmembers(module):
            if is_public_function(name, member):
                module_info["functions"][name] = {
                    "name": name,
                    "doc": inspect.getdoc(member),
                    "signature": str(inspect.signature(member))
                }
                module_info["key_features"].add(name)
            
            # Get public classes
            elif is_public_class(name, member):
                class_info = {
                    "name": name,
                    "doc": inspect.getdoc(member),
                    "methods": {}
                }
                
                # Get public methods of the class
                methods = get_public_class_methods(member)
                for method_name, method in methods.items():
                    class_info["methods"][method_name] = {
                        "name": method_name,
                        "doc": inspect.getdoc(method),
                        "signature": str(inspect.signature(method))
                    }
                    module_info["key_features"].add(f"{name}.{method_name}")
                    module_info["class_methods"][f"{name}.{method_name}"] = {
                        "name": method_name,
                        "class": name,
                        "doc": inspect.getdoc(method),
                        "signature": str(inspect.signature(method))
                    }
                
                module_info["classes"][name] = class_info
                module_info["key_features"].add(name)
        
        # Calculate total features
        module_info["total_features"] = (
            len(module_info["functions"]) + 
            len(module_info["classes"]) + 
            len(module_info["class_methods"])
        )
        
        print(f"✓ Analyzed module {module_name}: {module_info['total_features']} features found")
        
    except ImportError as e:
        print(f"✗ Could not import module {module_name}: {e}")
        
    except Exception as e:
        print(f"✗ Error analyzing module {module_name}: {e}")
    
    return module_info

def get_all_mcp_tools() -> Dict[str, List[Dict[str, Any]]]:
    """
    Get information about all MCP tools in the server.
    
    Returns:
        Dict mapping tool categories to lists of tool info dictionaries
    """
    tools_by_category = {}
    
    if not MCP_TOOLS_PATH.exists():
        print(f"✗ MCP tools directory not found: {MCP_TOOLS_PATH}")
        return tools_by_category
    
    # Iterate through tool categories
    for category_dir in MCP_TOOLS_PATH.iterdir():
        if category_dir.is_dir() and not category_dir.name.startswith("__"):
            category_name = category_dir.name
            tools_by_category[category_name] = []
            
            # Find all tool files in this category
            for tool_file in category_dir.glob("*.py"):
                if tool_file.name == "__init__.py":
                    continue
                
                tool_name = tool_file.stem
                tool_info = {
                    "name": tool_name,
                    "path": str(tool_file.relative_to(MCP_SERVER_PATH)),
                    "doc": None,
                    "implements": None
                }
                
                # Try to extract documentation and implementation info
                try:
                    with open(tool_file, "r") as f:
                        content = f.read()
                        
                        # Extract docstring
                        doc_match = re.search(r'"""(.*?)"""', content, re.DOTALL)
                        if doc_match:
                            tool_info["doc"] = doc_match.group(1).strip()
                        
                        # Look for imports from the library
                        imports = re.findall(r'from\s+\.\.\.\.(\w+)\s+import', content)
                        if imports:
                            tool_info["implements"] = imports
                        
                        # Look for class instantiations
                        class_inits = re.findall(r'(\w+)\s*\(\s*\)', content)
                        if class_inits:
                            if not tool_info.get("implements"):
                                tool_info["implements"] = []
                            tool_info["implements"].extend(class_inits)
                
                except Exception as e:
                    print(f"  Warning: Error analyzing tool file {tool_file}: {e}")
                
                tools_by_category[category_name].append(tool_info)
            
            print(f"✓ Found {len(tools_by_category[category_name])} tools in category: {category_name}")
    
    return tools_by_category

def map_features_to_tools() -> Dict[str, Any]:
    """
    Map library features to MCP tools based on naming and implementation evidence.
    
    Returns:
        Dict containing mapping information
    """
    mapping_results = {
        "mapped_features": {},
        "unmapped_features": [],
        "coverage_by_module": {}
    }
    
    # Get all library features
    all_library_features = {}
    for module_name, module_info in coverage_results["library_modules"].items():
        mapping_results["coverage_by_module"][module_name] = {
            "mapped": [],
            "unmapped": [],
            "coverage_percentage": 0.0
        }
        
        # Add functions and class names
        for feature_name in module_info["key_features"]:
            all_library_features[feature_name] = {
                "module": module_name,
                "type": "function" if "." not in feature_name and feature_name in module_info["functions"] 
                        else "class" if "." not in feature_name 
                        else "method",
                "mapped_to": None
            }
    
    # Match features to tools
    for category_name, tools in coverage_results["mcp_tools"].items():
        for tool in tools:
            tool_name = tool["name"]
            tool_path = f"{category_name}/{tool_name}.py"
            
            # Try to find matching features
            matched_features = []
            
            for feature_name, feature_info in all_library_features.items():
                module_name = feature_info["module"]
                expected_category = FEATURE_TO_TOOL_CATEGORY.get(module_name)
                
                # Skip if feature is already mapped
                if feature_info["mapped_to"]:
                    continue
                
                # Check if this is in the expected category
                if expected_category and category_name == expected_category:
                    # Direct name match
                    short_name = feature_name.split(".")[-1]
                    if (tool_name == feature_name.lower() or 
                        tool_name == short_name.lower() or
                        tool_name == f"{short_name.lower()}_from_{module_name.lower()}" or
                        tool_name == f"{module_name.lower()}_{short_name.lower()}"):
                        matched_features.append(feature_name)
                        continue
                    
                    # Partial match (e.g., create_warc matches WebArchiveProcessor.create_warc)
                    if "." in feature_name and tool_name == short_name.lower():
                        matched_features.append(feature_name)
                        continue
                    
                    # Implementation evidence (if available)
                    if tool.get("implements") and (
                        module_name in tool["implements"] or 
                        feature_name in tool["implements"] or
                        (feature_name.split(".")[0] if "." in feature_name else None) in tool["implements"]):
                        matched_features.append(feature_name)
                        continue
                    
                    # Check if the tool description mentions the feature
                    if tool.get("doc") and (
                        feature_name.lower() in tool["doc"].lower() or
                        (feature_name.split(".")[0] if "." in feature_name else "").lower() in tool["doc"].lower()):
                        matched_features.append(feature_name)
                        continue
            
            # Update the mapping for matched features
            for feature_name in matched_features:
                all_library_features[feature_name]["mapped_to"] = tool_path
                
                # Also update the module coverage tracking
                module_name = all_library_features[feature_name]["module"]
                mapping_results["coverage_by_module"][module_name]["mapped"].append(feature_name)
    
    # Find unmapped features
    for feature_name, feature_info in all_library_features.items():
        if not feature_info["mapped_to"]:
            mapping_results["unmapped_features"].append(feature_name)
            
            # Update module coverage tracking
            module_name = feature_info["module"]
            mapping_results["coverage_by_module"][module_name]["unmapped"].append(feature_name)
    
    # Calculate coverage percentages by module
    for module_name, coverage_info in mapping_results["coverage_by_module"].items():
        total_features = len(coverage_info["mapped"]) + len(coverage_info["unmapped"])
        if total_features > 0:
            coverage_info["coverage_percentage"] = (len(coverage_info["mapped"]) / total_features) * 100
        else:
            coverage_info["coverage_percentage"] = 0.0
    
    mapping_results["mapped_features"] = {
        name: info for name, info in all_library_features.items() 
        if info["mapped_to"] is not None
    }
    
    return mapping_results

def run_coverage_test():
    """Run the full MCP server feature coverage test."""
    print_header("IPFS Datasets MCP Server Feature Coverage Test")
    
    # 1. Analyze library modules
    print_header("Analyzing Library Modules")
    for module_name in KEY_MODULES:
        module_info = analyze_library_module(module_name)
        coverage_results["library_modules"][module_name] = module_info
    
    # 2. Get MCP tools information
    print_header("Analyzing MCP Server Tools")
    coverage_results["mcp_tools"] = get_all_mcp_tools()
    
    # 3. Map library features to MCP tools
    print_header("Mapping Library Features to MCP Tools")
    coverage_results["mapping_coverage"] = map_features_to_tools()
    
    # 4. Calculate overall coverage
    total_features = sum(
        module_info["total_features"] 
        for module_info in coverage_results["library_modules"].values()
    )
    
    mapped_features = len(coverage_results["mapping_coverage"]["mapped_features"])
    unmapped_features = len(coverage_results["mapping_coverage"]["unmapped_features"])
    
    if total_features > 0:
        coverage_results["overall_coverage"] = (mapped_features / total_features) * 100
    
    # 5. Generate report
    print_header("Coverage Report")
    print(f"Total library features: {total_features}")
    print(f"Features mapped to MCP tools: {mapped_features}")
    print(f"Features not mapped to MCP tools: {unmapped_features}")
    print(f"Overall coverage: {coverage_results['overall_coverage']:.2f}%\n")
    
    print("Coverage by module:")
    for module_name, coverage_info in coverage_results["mapping_coverage"]["coverage_by_module"].items():
        mapped_count = len(coverage_info["mapped"])
        unmapped_count = len(coverage_info["unmapped"])
        total_count = mapped_count + unmapped_count
        print(f"  - {module_name}: {coverage_info['coverage_percentage']:.2f}% ({mapped_count}/{total_count})")
    
    # Show some unmapped features (if any)
    if unmapped_features > 0:
        print("\nSome unmapped features (up to 10):")
        for feature_name in coverage_results["mapping_coverage"]["unmapped_features"][:10]:
            for module_name, module_info in coverage_results["library_modules"].items():
                if feature_name in module_info["key_features"]:
                    if "." in feature_name:  # It's a method
                        class_name, method_name = feature_name.split(".")
                        if class_name in module_info["classes"] and method_name in module_info["classes"][class_name]["methods"]:
                            feature_type = "method"
                            feature_desc = f"Class method in module {module_name}"
                    elif feature_name in module_info["functions"]:
                        feature_type = "function"
                        feature_desc = f"Function in module {module_name}"
                    else:
                        feature_type = "class"
                        feature_desc = f"Class in module {module_name}"
                    
                    print(f"  - {feature_name} ({feature_type}): {feature_desc}")
                    break
        
        if len(coverage_results["mapping_coverage"]["unmapped_features"]) > 10:
            print(f"  ... and {len(coverage_results['mapping_coverage']['unmapped_features']) - 10} more")
    
    # Save results to a file
    with open("mcp_feature_coverage_results.json", "w") as f:
        # Convert sets to lists for JSON serialization
        serializable_results = json.loads(json.dumps(coverage_results, default=lambda o: list(o) if isinstance(o, set) else o.__dict__ if hasattr(o, "__dict__") else str(o)))
        json.dump(serializable_results, f, indent=2)
    
    print(f"\nDetailed results saved to: mcp_feature_coverage_results.json")
    
    # Return success based on coverage threshold
    COVERAGE_THRESHOLD = 80.0  # Consider success if 80% or more features are covered
    return coverage_results["overall_coverage"] >= COVERAGE_THRESHOLD

if __name__ == "__main__":
    success = run_coverage_test()
    sys.exit(0 if success else 1)

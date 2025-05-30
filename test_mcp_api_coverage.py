#!/usr/bin/env python3
"""
Comprehensive test for the IPFS Datasets MCP server API coverage.

This test ensures that all important features from the ipfs_datasets_py library
are properly exposed as tools in the Model Context Protocol server implementation.
"""
import os
import sys
import json
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Set, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Import main library and MCP server components
try:
    import ipfs_datasets_py
    from ipfs_datasets_py import web_archive_utils
    # Try different ways to import the server
    try:
        from ipfs_datasets_py.mcp_server import server
    except ImportError:
        try:
            from ipfs_datasets_py.mcp_server import simple_server as server
        except ImportError:
            print("Warning: Could not import MCP server module")
            server = None
except ImportError as e:
    print(f"Error importing ipfs_datasets_py: {e}")
    sys.exit(1)

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
MCP_SERVER_PATH = PROJECT_ROOT / "ipfs_datasets_py" / "mcp_server"
TOOLS_PATH = MCP_SERVER_PATH / "tools"

# Expected features and their corresponding MCP tools
EXPECTED_FEATURES = {
    # Core dataset operations
    "dataset_operations": {
        "library_modules": ["ipfs_datasets.py"],
        "expected_tools": [
            "dataset_tools/load_dataset.py",
            "dataset_tools/save_dataset.py",
            "dataset_tools/process_dataset.py",
            "dataset_tools/convert_dataset_format.py"
        ]
    },
    # IPFS operations
    "ipfs_operations": {
        "library_modules": ["ipfs_datasets.py"],
        "expected_tools": [
            "ipfs_tools/get_from_ipfs.py",
            "ipfs_tools/pin_to_ipfs.py"
        ]
    },
    # Vector operations
    "vector_operations": {
        "library_modules": ["ipfs_embeddings_py", "ipfs_faiss_py"],
        "expected_tools": [
            "vector_tools/create_vector_index.py",
            "vector_tools/search_vector_index.py"
        ]
    },
    # Graph operations
    "graph_operations": {
        "library_modules": ["knowledge_graph_extraction.py"],
        "expected_tools": [
            "graph_tools/query_knowledge_graph.py"
        ]
    },
    # Audit operations
    "audit_operations": {
        "library_modules": ["audit"],
        "expected_tools": [
            "audit_tools/record_audit_event.py",
            "audit_tools/generate_audit_report.py"
        ]
    },
    # Security operations
    "security_operations": {
        "library_modules": ["security.py"],
        "expected_tools": [
            "security_tools/check_access_permission.py"
        ]
    },
    # Provenance operations
    "provenance_operations": {
        "library_modules": ["data_provenance.py"],
        "expected_tools": [
            "provenance_tools/record_provenance.py"
        ]
    },
    # Web archive operations
    "web_archive_operations": {
        "library_modules": ["web_archive_utils.py"],
        "expected_tools": [
            "web_archive_tools/create_warc.py",
            "web_archive_tools/index_warc.py",
            "web_archive_tools/extract_dataset_from_cdxj.py",
            "web_archive_tools/extract_text_from_warc.py",
            "web_archive_tools/extract_links_from_warc.py",
            "web_archive_tools/extract_metadata_from_warc.py"
        ]
    }
}

def print_header(message: str) -> None:
    """Print a header message."""
    print("\n" + "=" * 80)
    print(f" {message}")
    print("=" * 80)

def check_tool_exists(tool_path: str) -> bool:
    """Check if a tool exists at the specified path."""
    full_path = TOOLS_PATH / tool_path
    return full_path.exists()

def get_tools_in_category(category: str) -> List[str]:
    """Get all tools in a category directory."""
    category_path = TOOLS_PATH / category
    if not category_path.exists():
        return []

    return [
        f.name
        for f in category_path.iterdir()
        if f.is_file() and f.name.endswith('.py') and not f.name.startswith('__')
    ]

def check_feature_coverage() -> Dict[str, Any]:
    """Check if all expected features are covered by MCP tools."""
    results = {}

    for feature_name, feature_info in EXPECTED_FEATURES.items():
        print_header(f"Checking feature: {feature_name}")

        feature_results = {
            "present_tools": [],
            "missing_tools": [],
            "coverage_percentage": 0.0
        }

        # Check each expected tool
        for tool_path in feature_info["expected_tools"]:
            if check_tool_exists(tool_path):
                feature_results["present_tools"].append(tool_path)
                print(f"✓ Tool found: {tool_path}")
            else:
                feature_results["missing_tools"].append(tool_path)
                print(f"✗ Tool missing: {tool_path}")

        # Calculate coverage percentage
        total_tools = len(feature_info["expected_tools"])
        present_tools = len(feature_results["present_tools"])

        if total_tools > 0:
            feature_results["coverage_percentage"] = (present_tools / total_tools) * 100

        print(f"Coverage: {present_tools}/{total_tools} tools ({feature_results['coverage_percentage']:.1f}%)")

        # Store the results
        results[feature_name] = feature_results

    return results

def get_all_available_tools() -> Dict[str, List[str]]:
    """Get all available tools in the MCP server."""
    tools_by_category = {}

    for category_dir in TOOLS_PATH.iterdir():
        if category_dir.is_dir() and not category_dir.name.startswith('__'):
            category_name = category_dir.name
            tools = get_tools_in_category(category_name)
            tools_by_category[category_name] = tools

    return tools_by_category

def analyze_library_coverage() -> Dict[str, Any]:
    """Analyze how well the library's functionality is covered by MCP tools."""
    results = {
        "feature_coverage": None,
        "available_tools": None,
        "overall_coverage": 0.0,
        "missing_features": []
    }

    # Get feature coverage
    results["feature_coverage"] = check_feature_coverage()

    # Get all available tools
    results["available_tools"] = get_all_available_tools()

    # Calculate overall coverage
    total_expected_tools = 0
    total_present_tools = 0

    for feature_name, feature_results in results["feature_coverage"].items():
        total_expected_tools += len(EXPECTED_FEATURES[feature_name]["expected_tools"])
        total_present_tools += len(feature_results["present_tools"])

        # Track missing features
        if feature_results["coverage_percentage"] < 100:
            results["missing_features"].append({
                "feature": feature_name,
                "coverage": feature_results["coverage_percentage"],
                "missing_tools": feature_results["missing_tools"]
            })

    if total_expected_tools > 0:
        results["overall_coverage"] = (total_present_tools / total_expected_tools) * 100

    return results

def main():
    """Main entry point."""
    print_header("IPFS Datasets MCP Server API Coverage Test")
    print(f"Checking MCP server at: {MCP_SERVER_PATH}")

    # Run the analysis
    results = analyze_library_coverage()

    # Print overall results
    print_header("Overall Results")
    print(f"Overall API coverage: {results['overall_coverage']:.1f}%")

    if results["missing_features"]:
        print("\nMissing features:")
        for feature in results["missing_features"]:
            print(f"  - {feature['feature']}: {feature['coverage']:.1f}% coverage")
            for tool in feature["missing_tools"]:
                print(f"    - Missing: {tool}")

    # Save results to JSON file
    output_file = PROJECT_ROOT / "mcp_api_coverage_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_file}")

    # Return exit code based on coverage
    if results["overall_coverage"] < 100:
        print("\nSome features are not fully covered by MCP tools.")
        return 1
    else:
        print("\nAll expected features are covered by MCP tools.")
        return 0

if __name__ == "__main__":
    sys.exit(main())

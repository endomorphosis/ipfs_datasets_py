#!/usr/bin/env python3
"""
Comprehensive test for MCP tools coverage and functionality.

This script tests all MCP tools to verify that they properly expose the
features from the ipfs_datasets_py library.
"""
import os
import sys
import json
import anyio
import logging
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mcp_tools_test")

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent
IPFS_DATASETS_PATH = PROJECT_ROOT / "ipfs_datasets_py"
MCP_SERVER_PATH = IPFS_DATASETS_PATH / "mcp_server"
TOOLS_PATH = MCP_SERVER_PATH / "tools"
TEST_RESULTS_PATH = PROJECT_ROOT / "mcp_tools_test_results.json"

# Tool categories to test
TOOL_CATEGORIES = [
    "dataset_tools",
    "ipfs_tools",
    "vector_tools",
    "graph_tools",
    "audit_tools",
    "security_tools",
    "provenance_tools",
    "web_archive_tools",
    "cli",
    "functions"
]

# Expected tools in each category
EXPECTED_TOOLS = {
    "dataset_tools": [
        "load_dataset",
        "save_dataset",
        "process_dataset",
        "convert_dataset_format"
    ],
    "ipfs_tools": [
        "get_from_ipfs",
        "pin_to_ipfs"
    ],
    "vector_tools": [
        "create_vector_index",
        "search_vector_index"
    ],
    "graph_tools": [
        "query_knowledge_graph"
    ],
    "audit_tools": [
        "record_audit_event",
        "generate_audit_report"
    ],
    "security_tools": [
        "check_access_permission"
    ],
    "provenance_tools": [
        "record_provenance"
    ],
    "web_archive_tools": [
        "create_warc",
        "index_warc",
        "extract_dataset_from_cdxj",
        "extract_text_from_warc",
        "extract_links_from_warc",
        "extract_metadata_from_warc"
    ],
    "cli": [
        "execute_command"
    ],
    "functions": [
        "execute_python_snippet"
    ]
}

def get_available_tools():
    """Get all available MCP tools."""
    available_tools = {}

    for category in TOOL_CATEGORIES:
        category_path = TOOLS_PATH / category
        print(f"Checking category path: {category_path}, exists: {category_path.exists()}")
        if not category_path.exists():
            available_tools[category] = []
            continue

        # Get all Python files in the category directory
        tools = []
        for item in category_path.glob("*.py"):
            if item.name != "__init__.py":
                tools.append(item.stem)
                print(f"Found tool: {category}/{item.stem}")

        available_tools[category] = tools

    return available_tools

def check_tool_availability():
    """Check which expected tools are available."""
    available_tools = get_available_tools()
    results = {}

    for category, expected in EXPECTED_TOOLS.items():
        category_results = {
            "expected": expected,
            "available": available_tools.get(category, []),
            "missing": []
        }

        # Find missing tools
        for tool in expected:
            if tool not in category_results["available"]:
                category_results["missing"].append(tool)

        category_results["coverage"] = (
            len(category_results["available"]) / len(expected) * 100
            if expected else 0
        )

        results[category] = category_results

    # Calculate overall coverage
    all_expected = sum(len(tools) for tools in EXPECTED_TOOLS.values())
    all_available = sum(len(tools) for tools in available_tools.values())

    results["overall"] = {
        "expected_count": all_expected,
        "available_count": all_available,
        "coverage_percentage": all_available / all_expected * 100 if all_expected else 0
    }

    return results

def print_availability_results(results):
    """Print the results of the availability check."""
    logger.info("MCP Tool Availability Results")
    logger.info("=" * 50)

    for category, data in results.items():
        if category == "overall":
            continue

        logger.info(f"\nCategory: {category}")
        logger.info(f"Coverage: {data['coverage']:.1f}%")
        logger.info(f"Available: {', '.join(data['available']) or 'None'}")
        if data["missing"]:
            logger.info(f"Missing: {', '.join(data['missing'])}")

    logger.info("\nOverall Results")
    logger.info("-" * 30)
    logger.info(f"Total expected tools: {results['overall']['expected_count']}")
    logger.info(f"Total available tools: {results['overall']['available_count']}")
    logger.info(f"Overall coverage: {results['overall']['coverage_percentage']:.1f}%")

async def test_tool_functionality(category, tool_name):
    """Test the functionality of a specific tool."""
    result = {
        "category": category,
        "tool": tool_name,
        "status": "unknown",
        "message": ""
    }

    try:
        # Attempt to dynamically import the tool
        module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"

        try:
            tool_module = __import__(module_path, fromlist=[""])
            result["status"] = "imported"

            # Check if the module has an async function with the same name as the module
            if hasattr(tool_module, tool_name) and asyncio.iscoroutinefunction(getattr(tool_module, tool_name)):
                result["status"] = "available"
                result["message"] = "Tool is properly implemented"
            else:
                result["status"] = "incomplete"
                result["message"] = "Tool does not have the expected async function"

        except ImportError as e:
            result["status"] = "import_error"
            result["message"] = f"Could not import tool: {str(e)}"

    except Exception as e:
        result["status"] = "error"
        result["message"] = f"Error during tool testing: {str(e)}"

    return result

async def test_all_tools(available_tools):
    """Test all available tools."""
    test_results = []

    for category, tools in available_tools.items():
        for tool in tools:
            result = await test_tool_functionality(category, tool)
            test_results.append(result)

    return test_results

def print_functionality_results(results):
    """Print the results of the functionality tests."""
    logger.info("\nMCP Tool Functionality Results")
    logger.info("=" * 50)

    status_counts = {
        "available": 0,
        "incomplete": 0,
        "import_error": 0,
        "error": 0
    }

    for result in results:
        status = result["status"]
        status_counts[status] = status_counts.get(status, 0) + 1

        logger.info(f"\nTool: {result['category']}/{result['tool']}")
        logger.info(f"Status: {status}")
        if result["message"]:
            logger.info(f"Message: {result['message']}")

    logger.info("\nSummary")
    logger.info("-" * 30)
    for status, count in status_counts.items():
        logger.info(f"{status}: {count}")

def save_results(availability_results, functionality_results):
    """Save the test results to a JSON file."""
    combined_results = {
        "availability": availability_results,
        "functionality": functionality_results,
        "timestamp": "__TIMESTAMP__"  # Will be replaced with actual timestamp
    }

    with open(TEST_RESULTS_PATH, "w") as f:
        json.dump(combined_results, f, indent=2)

    logger.info(f"\nResults saved to {TEST_RESULTS_PATH}")

async def main():
    """Main function."""
    logger.info("Starting MCP Tools Test")

    # Check tool availability
    availability_results = check_tool_availability()
    print_availability_results(availability_results)

    # Get available tools
    available_tools = get_available_tools()

    # Test tool functionality
    functionality_results = await test_all_tools(available_tools)
    print_functionality_results(functionality_results)

    # Save results
    save_results(availability_results, functionality_results)

    logger.info("MCP Tools Test completed")

if __name__ == "__main__":
    anyio.run(main())

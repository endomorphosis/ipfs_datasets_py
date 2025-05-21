#!/usr/bin/env python3
"""
Direct integration test for the IPFS Datasets MCP server.

This test focuses on the core MCP server components without relying on external dependencies
like the modelcontextprotocol package which may not be properly installed in all environments.
It will verify:

1. The structure of the MCP server module
2. The presence of required tools for each category
3. Basic functionality of the server configuration
4. Integration with IPFS Kit components
"""
import os
import sys
from pathlib import Path
import importlib
import inspect
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Display environment info
print(f"Running test on Python {sys.version}")
print(f"Current working directory: {os.getcwd()}")

# Define expected MCP server components
EXPECTED_COMPONENTS = [
    # Core components
    "configs.py",
    "server.py",
    "client.py",
    "logger.py",
    "utils",
    # Tool categories
    "tools/dataset_tools",
    "tools/ipfs_tools",
    "tools/vector_tools",
    "tools/graph_tools",
    "tools/audit_tools",
    "tools/security_tools",
    "tools/provenance_tools"
]

# Define expected core functions/classes
EXPECTED_CORE = [
    "IPFSDatasetsMCPServer",
    "start_server",
    "Configs",
    "SimpleIPFSDatasetsMCPServer"  # Added our simplified implementation
]

# Build the path to the MCP server module
MCP_SERVER_PATH = Path(__file__).resolve().parent / "ipfs_datasets_py" / "mcp_server"

# Test results
test_results = {
    "components": {"passed": [], "failed": []},
    "core": {"passed": [], "failed": []},
    "tools": {"present": [], "missing": []},
    "ipfs_kit_integration": {"status": "not_tested", "details": ""},
    "total_passed": 0,
    "total_failed": 0
}

def check_component_exists(component_path):
    """Check if a component exists at the given path."""
    full_path = MCP_SERVER_PATH / component_path
    exists = full_path.exists()
    component_name = component_path
    if exists:
        test_results["components"]["passed"].append(component_name)
        print(f"✓ Component exists: {component_name}")
        test_results["total_passed"] += 1
    else:
        test_results["components"]["failed"].append(component_name)
        print(f"✗ Component missing: {component_name}")
        test_results["total_failed"] += 1
    return exists

def check_tools_directory():
    """Check the structure and content of the tools directory."""
    tools_dir = MCP_SERVER_PATH / "tools"
    if not tools_dir.exists():
        print("✗ Tools directory does not exist!")
        test_results["total_failed"] += 1
        return False
    
    # Check tool categories
    for category_dir in tools_dir.iterdir():
        if category_dir.is_dir() and not category_dir.name.startswith("__"):
            category_name = category_dir.name
            # Check if there are actual tool files
            tool_files = [f for f in category_dir.iterdir() 
                         if f.is_file() and f.name.endswith(".py") and not f.name.startswith("__")]
            if tool_files:
                test_results["tools"]["present"].append(f"{category_name} ({len(tool_files)} tools)")
                print(f"✓ Tool category found: {category_name} with {len(tool_files)} tools")
                test_results["total_passed"] += 1
                
                # Print a few example tool names
                examples = [f.stem for f in tool_files[:3]]
                if examples:
                    print(f"  Example tools: {', '.join(examples)}")
            else:
                test_results["tools"]["missing"].append(category_name)
                print(f"✗ Tool category found but empty: {category_name}")
                test_results["total_failed"] += 1
    
    return True

def check_core_components():
    """Check if core components are importable."""
    # Try to import the module first
    try:
        mcp_server = importlib.import_module("ipfs_datasets_py.mcp_server")
        print("✓ Successfully imported ipfs_datasets_py.mcp_server module")
        
        # Check for expected attributes
        for attr_name in EXPECTED_CORE:
            # For the standard MCP Server implementation
            if attr_name == "IPFSDatasetsMCPServer" and hasattr(mcp_server, "server"):
                try:
                    server_module = importlib.import_module("ipfs_datasets_py.mcp_server.server")
                    if hasattr(server_module, "IPFSDatasetsMCPServer"):
                        test_results["core"]["passed"].append(attr_name)
                        print(f"✓ Core component found: {attr_name}")
                        test_results["total_passed"] += 1
                        continue
                except ImportError:
                    pass
            
            # For our simplified implementation
            if attr_name == "SimpleIPFSDatasetsMCPServer" and hasattr(mcp_server, "simple_server"):
                try:
                    server_module = importlib.import_module("ipfs_datasets_py.mcp_server.simple_server")
                    if hasattr(server_module, "SimpleIPFSDatasetsMCPServer"):
                        test_results["core"]["passed"].append(attr_name)
                        print(f"✓ Core component found: {attr_name} (simplified implementation)")
                        test_results["total_passed"] += 1
                        continue
                except ImportError:
                    pass
            
            # For other components
            if hasattr(mcp_server, attr_name):
                test_results["core"]["passed"].append(attr_name)
                print(f"✓ Core component found: {attr_name}")
                test_results["total_passed"] += 1
            else:
                test_results["core"]["failed"].append(attr_name)
                print(f"✗ Core component missing: {attr_name}")
                test_results["total_failed"] += 1
                
    except ImportError as e:
        print(f"✗ Failed to import mcp_server module: {e}")
        for attr_name in EXPECTED_CORE:
            test_results["core"]["failed"].append(attr_name)
            test_results["total_failed"] += 1
        return False
    
    return True

def check_ipfs_kit_integration():
    """Check integration with IPFS Kit."""
    has_integration = False
    integration_details = []
    
    try:
        # First check for IPFS Kit in configuration
        try:
            configs_module = importlib.import_module("ipfs_datasets_py.mcp_server.configs")
            
            if hasattr(configs_module, "configs"):
                configs = configs_module.configs
                if hasattr(configs, "ipfs_kit_integration"):
                    has_integration = True
                    integration_details.append(f"Integration type: {configs.ipfs_kit_integration}")
                if hasattr(configs, "ipfs_kit_mcp_url"):
                    has_integration = True
                    integration_details.append(f"IPFS Kit MCP URL configuration: {configs.ipfs_kit_mcp_url}")
        except ImportError as e:
            print(f"Note: Could not import configs module: {e}")
        
        # Check for IPFS Kit specific tools (this doesn't require modelcontextprotocol)
        tools_dir = MCP_SERVER_PATH / "tools" / "ipfs_tools"
        if tools_dir.exists():
            ipfs_kit_files = list(tools_dir.glob("*.py"))
            ipfs_kit_tools = [f.stem for f in ipfs_kit_files 
                             if f.is_file() 
                             and not f.name.startswith("__")]
            
            # Look for IPFS Kit related code in tool files
            for tool_file in ipfs_kit_files:
                try:
                    with open(tool_file, 'r') as f:
                        content = f.read()
                        if "ipfs_kit" in content.lower():
                            has_integration = True
                            if tool_file.stem not in integration_details:
                                integration_details.append(f"IPFS Kit integration in: {tool_file.stem}")
                except Exception:
                    pass
            
            # Check file names for ipfs_kit references
            kit_named_tools = [name for name in ipfs_kit_tools if "ipfs_kit" in name.lower()]
            if kit_named_tools:
                has_integration = True
                integration_details.append(f"IPFS Kit tool files: {', '.join(kit_named_tools)}")
        
        # Final determination
        if has_integration:
            test_results["ipfs_kit_integration"]["status"] = "found"
            test_results["ipfs_kit_integration"]["details"] = "; ".join(integration_details)
            print(f"✓ IPFS Kit integration found: {'; '.join(integration_details)}")
            test_results["total_passed"] += 1
        else:
            test_results["ipfs_kit_integration"]["status"] = "not_found"
            test_results["ipfs_kit_integration"]["details"] = "No integration configuration or specific tools found"
            print(f"✗ IPFS Kit integration not found")
            test_results["total_failed"] += 1
            
    except Exception as e:
        test_results["ipfs_kit_integration"]["status"] = "error"
        test_results["ipfs_kit_integration"]["details"] = f"Error checking integration: {str(e)}"
        print(f"✗ Error checking IPFS Kit integration: {e}")
        test_results["total_failed"] += 1
    
    return has_integration
        
    return has_integration

def main():
    print("\n" + "=" * 60)
    print("IPFS Datasets MCP Server Integration Test")
    print("=" * 60)
    
    # Check if the MCP server directory exists
    if not MCP_SERVER_PATH.exists():
        print(f"✗ MCP server directory not found at {MCP_SERVER_PATH}")
        return False
    
    print(f"\n✓ Found MCP server directory at: {MCP_SERVER_PATH}\n")
    
    print("Checking component structure...")
    for component in EXPECTED_COMPONENTS:
        check_component_exists(component)
    
    print("\nChecking core components...")
    check_core_components()
    
    print("\nChecking tools directory...")
    check_tools_directory()
    
    print("\nChecking IPFS Kit integration...")
    check_ipfs_kit_integration()
    
    # Summarize results
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Total tests passed: {test_results['total_passed']}")
    print(f"Total tests failed: {test_results['total_failed']}")
    print(f"Components checked: {len(test_results['components']['passed']) + len(test_results['components']['failed'])}")
    print(f"Core functions checked: {len(test_results['core']['passed']) + len(test_results['core']['failed'])}")
    print(f"Tool categories found: {len(test_results['tools']['present'])}")
    print(f"IPFS Kit integration: {test_results['ipfs_kit_integration']['status']}")
    
    # Save results to file
    results_file = Path(__file__).parent / "mcp_integration_test_results.json"
    with open(results_file, "w") as f:
        json.dump(test_results, f, indent=2)
    print(f"\nDetailed test results saved to: {results_file}")
    
    # Return overall success
    return test_results["total_failed"] == 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

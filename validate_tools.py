#!/usr/bin/env python3
"""
Final validation script for IPFS Datasets MCP Tools

This script validates that all MCP tools can be imported and are functional.
It serves as a quick health check for the entire system.
"""

import sys
import importlib
import asyncio
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_import_tool(category, tool_name):
    """Test importing a single tool."""
    try:
        module_path = f"ipfs_datasets_py.mcp_server.tools.{category}.{tool_name}"
        module = importlib.import_module(module_path)
        
        # Check if main function exists
        if hasattr(module, tool_name):
            func = getattr(module, tool_name)
            return True, f"✅ {category}/{tool_name}: Function available"
        else:
            return False, f"❌ {category}/{tool_name}: Function not found"
            
    except ImportError as e:
        return False, f"❌ {category}/{tool_name}: Import failed - {e}"
    except Exception as e:
        return False, f"❌ {category}/{tool_name}: Error - {e}"

def main():
    """Run the validation."""
    print("🔍 IPFS Datasets MCP Tools Validation")
    print("=" * 50)
    
    # Define all tools to test
    tools = [
        # Dataset tools
        ("dataset_tools", "load_dataset"),
        ("dataset_tools", "convert_dataset_format"),
        ("dataset_tools", "process_dataset"),
        ("dataset_tools", "save_dataset"),
        
        # Vector tools
        ("vector_tools", "create_vector_index"),
        ("vector_tools", "search_vector_index"),
        
        # Graph tools
        ("graph_tools", "query_knowledge_graph"),
        
        # Audit tools
        ("audit_tools", "record_audit_event"),
        ("audit_tools", "generate_audit_report"),
        
        # Provenance tools
        ("provenance_tools", "record_provenance"),
        
        # Security tools
        ("security_tools", "check_access_permission"),
        
        # IPFS tools
        ("ipfs_tools", "get_from_ipfs"),
        ("ipfs_tools", "pin_to_ipfs"),
        
        # CLI tools
        ("cli", "execute_command"),
        
        # Function tools
        ("functions", "execute_python_snippet"),
        
        # Web archive tools
        ("web_archive_tools", "create_warc"),
    ]
    
    results = []
    success_count = 0
    
    print(f"Testing {len(tools)} MCP tools...\n")
    
    for category, tool_name in tools:
        success, message = test_import_tool(category, tool_name)
        results.append((success, message))
        if success:
            success_count += 1
        print(message)
    
    print("\n" + "=" * 50)
    print(f"📊 VALIDATION SUMMARY")
    print(f"✅ Successful: {success_count}/{len(tools)} ({success_count/len(tools)*100:.1f}%)")
    print(f"❌ Failed: {len(tools)-success_count}/{len(tools)}")
    
    if success_count == len(tools):
        print("\n🎉 ALL TOOLS VALIDATED SUCCESSFULLY!")
        print("The IPFS Datasets MCP Tools are ready for use.")
        return 0
    else:
        print(f"\n⚠️  {len(tools)-success_count} tools need attention.")
        return 1

if __name__ == "__main__":
    exit(main())

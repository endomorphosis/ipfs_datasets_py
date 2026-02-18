"""
P2P Tool Registration Script

Automatically discovers and registers all P2P tools with the tool metadata system.
This script should be run during server startup to ensure all P2P tools are properly
registered with their metadata for runtime routing.

Author: MCP++ Integration Team
Date: 2026-02-18
Phase: 2.3 (MCP++ Integration)
"""

import logging
import importlib
import inspect
from typing import List, Dict, Any
from pathlib import Path

from ipfs_datasets_py.mcp_server.tool_metadata import (
    get_registry,
    ToolMetadata,
    RUNTIME_TRIO,
)

logger = logging.getLogger(__name__)


def discover_p2p_tools() -> List[Dict[str, Any]]:
    """
    Discover all P2P tools by scanning the tools directory.
    
    Returns:
        List of discovered tool information dictionaries
    """
    discovered = []
    
    # Modules that contain P2P tools
    p2p_modules = [
        "ipfs_datasets_py.mcp_server.tools.mcplusplus_taskqueue_tools",
        "ipfs_datasets_py.mcp_server.tools.mcplusplus_workflow_tools",
        "ipfs_datasets_py.mcp_server.tools.p2p_tools.p2p_tools",
        "ipfs_datasets_py.mcp_server.tools.p2p_tools.workflow_scheduler_tools",
    ]
    
    for module_name in p2p_modules:
        try:
            module = importlib.import_module(module_name)
            
            # Find all functions in the module
            for name, obj in inspect.getmembers(module, inspect.isfunction):
                # Check if function has tool_metadata
                if hasattr(obj, '_tool_metadata'):
                    metadata = obj._tool_metadata
                    discovered.append({
                        'module': module_name,
                        'function': name,
                        'metadata': metadata,
                        'callable': obj,
                    })
                    logger.debug(f"Discovered P2P tool: {name} from {module_name}")
        
        except ImportError as e:
            logger.warning(f"Could not import P2P module {module_name}: {e}")
        except Exception as e:
            logger.error(f"Error discovering tools in {module_name}: {e}")
    
    return discovered


def register_p2p_tools() -> Dict[str, Any]:
    """
    Register all discovered P2P tools with the tool metadata registry.
    
    Returns:
        Dictionary with registration statistics
    """
    registry = get_registry()
    discovered = discover_p2p_tools()
    
    registered = 0
    skipped = 0
    errors = 0
    
    for tool_info in discovered:
        try:
            metadata = tool_info['metadata']
            func_name = tool_info['function']
            
            # Check if already registered
            if func_name in registry._tools:
                logger.debug(f"Tool {func_name} already registered, skipping")
                skipped += 1
                continue
            
            # Register the tool
            registry.register(func_name, metadata)
            registered += 1
            logger.info(f"Registered P2P tool: {func_name} (runtime={metadata.runtime}, category={metadata.category})")
        
        except Exception as e:
            logger.error(f"Error registering tool {tool_info.get('function', 'unknown')}: {e}")
            errors += 1
    
    stats = {
        'discovered': len(discovered),
        'registered': registered,
        'skipped': skipped,
        'errors': errors,
        'total_in_registry': len(registry.list_all()),
    }
    
    logger.info(f"P2P tool registration complete: {stats}")
    return stats


def get_p2p_tool_summary() -> Dict[str, Any]:
    """
    Get a summary of all registered P2P tools.
    
    Returns:
        Dictionary with P2P tool statistics by category
    """
    registry = get_registry()
    
    # Get all Trio runtime tools (P2P tools)
    p2p_tools = [
        tool for tool in registry.list_all()
        if tool.runtime == RUNTIME_TRIO and tool.requires_p2p
    ]
    
    # Group by category
    by_category = {}
    for tool in p2p_tools:
        category = tool.category
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(tool.name)
    
    summary = {
        'total_p2p_tools': len(p2p_tools),
        'by_category': {
            cat: {'count': len(tools), 'tools': tools}
            for cat, tools in by_category.items()
        },
        'categories': list(by_category.keys()),
    }
    
    return summary


def validate_p2p_tool_metadata() -> Dict[str, Any]:
    """
    Validate that all P2P tools have proper metadata.
    
    Returns:
        Dictionary with validation results
    """
    registry = get_registry()
    p2p_tools = [
        tool for tool in registry.list_all()
        if tool.runtime == RUNTIME_TRIO and tool.requires_p2p
    ]
    
    issues = []
    valid = 0
    
    for tool in p2p_tools:
        tool_issues = []
        
        # Check required fields
        if not tool.name:
            tool_issues.append("Missing name")
        if not tool.category or tool.category == "general":
            tool_issues.append("Missing or generic category")
        if not tool.mcp_description:
            tool_issues.append("Missing MCP description")
        if tool.timeout_seconds <= 0:
            tool_issues.append("Invalid timeout")
        
        if tool_issues:
            issues.append({
                'tool': tool.name,
                'issues': tool_issues,
            })
        else:
            valid += 1
    
    return {
        'total_tools': len(p2p_tools),
        'valid': valid,
        'with_issues': len(issues),
        'issues': issues,
    }


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 80)
    print("P2P Tool Registration")
    print("=" * 80)
    
    # Register all P2P tools
    stats = register_p2p_tools()
    print(f"\n✅ Registration complete:")
    print(f"   - Discovered: {stats['discovered']}")
    print(f"   - Registered: {stats['registered']}")
    print(f"   - Skipped: {stats['skipped']}")
    print(f"   - Errors: {stats['errors']}")
    print(f"   - Total in registry: {stats['total_in_registry']}")
    
    # Get summary
    summary = get_p2p_tool_summary()
    print(f"\n📊 P2P Tool Summary:")
    print(f"   - Total P2P tools: {summary['total_p2p_tools']}")
    print(f"   - Categories: {len(summary['categories'])}")
    for category, info in summary['by_category'].items():
        print(f"     - {category}: {info['count']} tools")
    
    # Validate
    validation = validate_p2p_tool_metadata()
    print(f"\n🔍 Validation Results:")
    print(f"   - Valid tools: {validation['valid']}")
    print(f"   - Tools with issues: {validation['with_issues']}")
    
    if validation['issues']:
        print("\n⚠️  Issues found:")
        for issue in validation['issues']:
            print(f"   - {issue['tool']}: {', '.join(issue['issues'])}")
    else:
        print("   ✅ All P2P tools have valid metadata!")
    
    print("\n" + "=" * 80)

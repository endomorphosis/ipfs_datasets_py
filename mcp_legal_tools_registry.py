"""
MCP Legal Tools Registry

This module registers all legal analysis MCP tools with the core package.
"""

from ipfs_datasets_py.mcp_tools.tools.deontic_logic_tools import MCP_TOOLS as DEONTIC_TOOLS

# Registry of all legal analysis MCP tools
LEGAL_MCP_TOOLS = {
    **DEONTIC_TOOLS,
    # Additional legal tools can be registered here
}

def get_legal_tools():
    """Get all registered legal MCP tools"""
    return LEGAL_MCP_TOOLS

def register_legal_tool(name: str, tool_definition: dict):
    """Register a new legal MCP tool"""
    LEGAL_MCP_TOOLS[name] = tool_definition

def get_tool_names():
    """Get names of all registered legal tools"""
    return list(LEGAL_MCP_TOOLS.keys())
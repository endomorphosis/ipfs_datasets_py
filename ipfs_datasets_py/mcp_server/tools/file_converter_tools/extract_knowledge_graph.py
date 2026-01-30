"""
MCP Server Tool: Extract Knowledge Graph

Extract knowledge graph (entities and relationships) from a file using the file_converter package exports.
"""

from ipfs_datasets_py.file_converter.exports import extract_knowledge_graph_sync


async def extract_knowledge_graph_tool(
    input_path: str,
    enable_ipfs: bool = False
) -> dict:
    """
    Extract knowledge graph (entities and relationships) from a file or URL.
    
    Args:
        input_path: Path to file or URL
        enable_ipfs: Whether to store results on IPFS
    
    Returns:
        Dict with entities, relationships, summary, and counts
    
    Example:
        result = await extract_knowledge_graph_tool('research-paper.pdf')
        result = await extract_knowledge_graph_tool('document.pdf', enable_ipfs=True)
    """
    return extract_knowledge_graph_sync(input_path, enable_ipfs)


# Tool metadata for MCP server
TOOL_NAME = "extract_knowledge_graph"
TOOL_DESCRIPTION = "Extract knowledge graph (entities and relationships) from a file"
TOOL_CATEGORY = "file_converter_tools"

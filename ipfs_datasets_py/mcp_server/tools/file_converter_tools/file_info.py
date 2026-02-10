"""
MCP Server Tool: Get File Info

Get information about a file using the file_converter package exports.
"""

from ipfs_datasets_py.processors.file_converter.exports import get_file_info_sync


async def file_info_tool(
    input_path: str
) -> dict:
    """
    Get information about a file.
    
    Args:
        input_path: Path to file or URL
    
    Returns:
        Dict with format, mime_type, metadata, is_url, is_archive flags
    
    Example:
        result = await file_info_tool('document.pdf')
        result = await file_info_tool('unknown-file.dat')
    """
    return get_file_info_sync(input_path)


# Tool metadata for MCP server
TOOL_NAME = "file_info"
TOOL_DESCRIPTION = "Get information about a file (format, MIME type, metadata)"
TOOL_CATEGORY = "file_converter_tools"

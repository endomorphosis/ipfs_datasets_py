"""
MCP Server Tool: Download from URL

Download a file from a URL using the file_converter package exports.
"""

from ipfs_datasets_py.processors.file_converter.exports import download_from_url_export_sync


async def download_url_tool(
    url: str,
    timeout: int = 30,
    max_size_mb: int = 100
) -> dict:
    """
    Download a file from a URL.
    
    Args:
        url: URL to download from (HTTP/HTTPS)
        timeout: Download timeout in seconds
        max_size_mb: Maximum file size in MB
    
    Returns:
        Dict with local_path, content_type, content_length, and success status
    
    Example:
        result = await download_url_tool('https://example.com/document.pdf')
        result = await download_url_tool('https://example.com/large-file.zip', timeout=60, max_size_mb=500)
    """
    return download_from_url_export_sync(url, timeout, max_size_mb)


# Tool metadata for MCP server
TOOL_NAME = "download_url"
TOOL_DESCRIPTION = "Download a file from a URL (HTTP/HTTPS)"
TOOL_CATEGORY = "file_converter_tools"

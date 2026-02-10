"""
MCP Server Tool: Convert File

Convert a file or URL to text using the file_converter package exports.
"""

from ipfs_datasets_py.processors.file_converter import convert_file_sync


async def convert_file_tool(
    input_path: str,
    backend: str = 'native',
    extract_archives: bool = False,
    output_format: str = 'text'
) -> dict:
    """
    Convert a file or URL to text.
    
    Args:
        input_path: Path to file or URL to convert
        backend: Conversion backend ('native', 'markitdown', 'omni', 'auto')
        extract_archives: Whether to extract and process archive contents
        output_format: Output format ('text', 'json')
    
    Returns:
        Dict with conversion result including text, metadata, and success status
    
    Example:
        result = await convert_file_tool('document.pdf')
        result = await convert_file_tool('https://example.com/file.pdf')
        result = await convert_file_tool('archive.zip', extract_archives=True)
    """
    return convert_file_sync(input_path, backend, extract_archives, output_format)


# Tool metadata for MCP server
TOOL_NAME = "convert_file"
TOOL_DESCRIPTION = "Convert a file or URL to text (supports 30+ formats)"
TOOL_CATEGORY = "file_converter_tools"

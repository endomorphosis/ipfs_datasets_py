"""
MCP Server Tool: Batch Convert Files

Batch convert multiple files or URLs using the file_converter package exports.
"""

from ipfs_datasets_py.processors.file_converter.exports import batch_convert_files_sync
from typing import List


async def batch_convert_tool(
    input_paths: List[str],
    backend: str = 'native',
    extract_archives: bool = False,
    max_concurrent: int = 5
) -> dict:
    """
    Batch convert multiple files or URLs to text.
    
    Args:
        input_paths: List of file paths or URLs to convert
        backend: Conversion backend ('native', 'markitdown', 'omni', 'auto')
        extract_archives: Whether to extract and process archive contents
        max_concurrent: Maximum number of concurrent conversions
    
    Returns:
        Dict with results list, success_count, error_count, and total
    
    Example:
        result = await batch_convert_tool(['doc1.pdf', 'doc2.docx', 'doc3.txt'])
        result = await batch_convert_tool(['*.pdf'], extract_archives=True)
    """
    return batch_convert_files_sync(input_paths, backend, extract_archives, max_concurrent)


# Tool metadata for MCP server
TOOL_NAME = "batch_convert"
TOOL_DESCRIPTION = "Batch convert multiple files or URLs to text"
TOOL_CATEGORY = "file_converter_tools"

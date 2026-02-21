"""
MCP Server Tool: Extract Archive

Extract contents from an archive file using the file_converter package exports.
"""

from ipfs_datasets_py.processors.file_converter.exports import extract_archive_contents


async def extract_archive_tool(
    archive_path: str,
    max_depth: int = 3,
    recursive: bool = True
) -> dict:
    """
    Extract contents from an archive file.

    Args:
        archive_path: Path to archive file (ZIP, TAR, GZ, BZ2, 7Z)
        max_depth: Maximum extraction depth for nested archives
        recursive: Whether to extract nested archives

    Returns:
        Dict with extracted_files list, file_count, total_size, and extraction_path

    Example:
        result = await extract_archive_tool('documents.zip')
        result = await extract_archive_tool('nested-archives.tar.gz', max_depth=5)
    """
    return await extract_archive_contents(archive_path, max_depth, recursive)


# Tool metadata for MCP server
TOOL_NAME = "extract_archive"
TOOL_DESCRIPTION = "Extract contents from archive files (ZIP, TAR, GZ, BZ2, 7Z)"
TOOL_CATEGORY = "file_converter_tools"

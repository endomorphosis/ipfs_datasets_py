"""
MCP Server Tool: Generate Summary

Generate text summary from a file using the file_converter package exports.
"""

from ipfs_datasets_py.processors.file_converter import generate_summary_sync
from typing import Optional


async def generate_summary_tool(
    input_path: str,
    llm_model: Optional[str] = None
) -> dict:
    """
    Generate a text summary from a file or URL.
    
    Args:
        input_path: Path to file or URL
        llm_model: LLM model to use for summarization (optional)
    
    Returns:
        Dict with summary, key_entities, and success status
    
    Example:
        result = await generate_summary_tool('long-document.pdf')
        result = await generate_summary_tool('report.docx', llm_model='gpt-3.5-turbo')
    """
    return generate_summary_sync(input_path, llm_model)


# Tool metadata for MCP server
TOOL_NAME = "generate_summary"
TOOL_DESCRIPTION = "Generate text summary from a file or URL"
TOOL_CATEGORY = "file_converter_tools"

"""
File Converter Tools for MCP Server

This category provides tools for file conversion, knowledge graph extraction,
text summarization, vector embeddings, archive handling, and URL downloading.

All tools use the file_converter package exports for consistent functionality
across CLI, MCP server, and dashboard interfaces.
"""

from .convert_file import convert_file_tool
from .batch_convert import batch_convert_tool
from .extract_knowledge_graph import extract_knowledge_graph_tool
from .generate_summary import generate_summary_tool
from .generate_embeddings import generate_embeddings_tool
from .extract_archive import extract_archive_tool
from .download_url import download_url_tool
from .file_info import file_info_tool

__all__ = [
    'convert_file_tool',
    'batch_convert_tool',
    'extract_knowledge_graph_tool',
    'generate_summary_tool',
    'generate_embeddings_tool',
    'extract_archive_tool',
    'download_url_tool',
    'file_info_tool',
]

# Category metadata
CATEGORY_NAME = "file_converter_tools"
CATEGORY_DESCRIPTION = "File conversion, knowledge graphs, summaries, embeddings, archives, and URLs"
TOOL_COUNT = 8

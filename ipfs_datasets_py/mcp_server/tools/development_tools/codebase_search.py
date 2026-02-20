"""
Codebase Search Tool for Development Assistance — thin MCP wrapper.

Business logic lives in ``codebase_search_engine.py``.  This module
re-exports all public names for backward compatibility and provides the
``codebase_search`` MCP-facing entry point.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .codebase_search_engine import (  # noqa: F401 — re-export for compat
    CodebaseSearchEngine,
    CodebaseSearchResult,
    FileSearchResult,
    SearchMatch,
    SearchSummary,
)

logger = logging.getLogger(__name__)
# MCP tool wrapper function
def codebase_search(pattern: str,
                   path: str = ".",
                   case_insensitive: bool = False,
                   whole_word: bool = False,
                   regex: bool = False,
                   extensions: Optional[str] = None,
                   exclude: Optional[str] = None,
                   max_depth: Optional[int] = None,
                   context: int = 0,
                   format: str = "text",
                   output: Optional[str] = None,
                   compact: bool = False,
                   group_by_file: bool = False,
                   summary: bool = False) -> Union[str, Dict[str, Any]]:
    """
    Search codebase for patterns with structured output.

    This tool provides advanced pattern matching and code search functionality
    with support for regular expressions, file filtering, context lines, and
    multiple output formats. Enhanced with dataset-aware capabilities.

    Args:
        pattern: The pattern to search for
        path: The path to search in. Defaults to current directory
        case_insensitive: Perform case-insensitive search
        whole_word: Match whole words only
        regex: Interpret pattern as a regular expression
        extensions: Comma-separated list of file extensions to search (e.g., 'py,txt')
        exclude: Comma-separated list of glob patterns to exclude
        max_depth: Maximum directory depth to search
        context: Number of lines of context to include before and after matches
        format: Output format (text, json, xml, dict)
        output: Write output to file instead of returning string
        compact: Use compact output format (one line per match)
        group_by_file: Group results by file
        summary: Include summary information in output

    Returns:
        Formatted search results or standardized dict result
    """
    search_engine = CodebaseSearchEngine()

    try:
        # Perform the search
        results = search_engine.search_codebase(
            pattern=pattern,
            path=path,
            case_insensitive=case_insensitive,
            whole_word=whole_word,
            regex=regex,
            extensions=extensions,
            exclude=exclude,
            max_depth=max_depth,
            context=context
        )

        # Return standardized format for MCP tools when format is json and no output file
        if format.lower() == "json" and not output:
            return {
                "success": True,
                "result": asdict(results),
                "metadata": {
                    "tool": "codebase_search",
                    "total_matches": results.summary.total_matches,
                    "files_searched": results.summary.total_files_searched,
                    "search_time": results.summary.search_time_seconds
                }
            }

        # Format results as string
        formatted_output = search_engine.format_results(
            results, format, compact, group_by_file
        )

        # Write to file if specified
        if output:
            try:
                with open(output, 'w', encoding='utf-8') as f:
                    f.write(formatted_output)
                return {
                    "success": True,
                    "result": f"Search results written to {output}",
                    "metadata": {
                        "tool": "codebase_search",
                        "output_file": output,
                        "total_matches": results.summary.total_matches
                    }
                }
            except OSError as e:
                return {
                    "success": False,
                    "error": "file_write_error",
                    "message": f"Error writing to file {output}: {e}",
                    "metadata": {"tool": "codebase_search"}
                }

        return formatted_output

    except (ValueError, FileNotFoundError, OSError) as e:
        return {
            "success": False,
            "error": "search_error",
            "message": str(e),
            "metadata": {"tool": "codebase_search"}
        }


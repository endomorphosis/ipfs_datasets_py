"""
Codebase Search Tool for Development Assistance.

This tool provides advanced pattern matching and code search functionality
with support for regular expressions, file filtering, context lines, and
multiple output formats. Enhanced with dataset-aware capabilities for IPFS
and data science workflows.
"""

import os
import re
import json
import glob
import fnmatch
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Union, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from .base_tool import BaseDevelopmentTool

logger = logging.getLogger(__name__)


@dataclass
class SearchMatch:
    """Represents a single search match."""
    file_path: str
    line_number: int
    line_content: str
    match_start: int
    match_end: int
    context_before: List[str]
    context_after: List[str]


@dataclass
class FileSearchResult:
    """Represents search results for a single file."""
    file_path: str
    total_matches: int
    matches: List[SearchMatch]
    file_size: int
    encoding: str


@dataclass
class SearchSummary:
    """Summary of search operation."""
    total_files_searched: int
    total_files_with_matches: int
    total_matches: int
    search_time_seconds: float
    pattern: str
    search_path: str
    extensions_included: List[str]
    patterns_excluded: List[str]


@dataclass
class CodebaseSearchResult:
    """Complete codebase search results."""
    summary: SearchSummary
    file_results: List[FileSearchResult]
    errors: List[str]


# Standalone codebase search class (not inheriting from BaseDevelopmentTool for simplicity)
class CodebaseSearchEngine:
    """
    Advanced codebase search engine with pattern matching, filtering, and analysis.

    Features:
    - Regular expression and literal pattern matching
    - File extension and path filtering
    - Context lines around matches
    - Multiple output formats (text, JSON, XML)
    - Performance optimization with parallel processing
    - Dataset-aware search for IPFS hashes and data science patterns
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.default_exclude_patterns = [
            '*.git*', '*__pycache__*', '*.pyc', '*.pyo', '*.pyd',
            '*node_modules*', '*.npm*', '*.yarn*',
            '*.egg-info*', '*.dist-info*', '*build*', '*dist*',
            '*.ipynb_checkpoints*', '*.pytest_cache*',
            '*.coverage*', '*.tox*', '*.mypy_cache*'
        ]

        # Dataset-aware patterns for specialized search
        self.dataset_patterns = {
            'ipfs_hash': r'(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|ba[a-z2-7]{56})',
            'cid_v0': r'Qm[1-9A-HJ-NP-Za-km-z]{44}',
            'cid_v1': r'ba[a-z2-7]{56}',
            'dataframe_ops': r'(?:\.read_csv|\.to_csv|\.read_parquet|\.to_parquet|pd\.DataFrame)',
            'ml_imports': r'(?:import (?:torch|tensorflow|sklearn|numpy|pandas|scipy))',
            'async_patterns': r'(?:async def|await |asyncio\.)',
            'test_patterns': r'(?:def test_|@pytest\.|unittest\.)',
        }

    def _should_exclude_file(self, file_path: str, exclude_patterns: List[str]) -> bool:
        """Check if file should be excluded based on patterns."""
        file_str = str(file_path)

        for pattern in exclude_patterns:
            if fnmatch.fnmatch(file_str, pattern):
                return True
            if pattern in file_str:
                return True

        return False

    def _should_include_file(self, file_path: Path, extensions: Optional[List[str]]) -> bool:
        """Check if file should be included based on extension filter."""
        if not extensions:
            return True

        file_ext = file_path.suffix.lstrip('.')
        return file_ext.lower() in [ext.lower().lstrip('.') for ext in extensions]

    def _get_file_encoding(self, file_path: Path) -> str:
        """Detect file encoding."""
        try:
            # Try common encodings
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']

            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        f.read(1024)  # Read a small chunk to test
                    return encoding
                except UnicodeDecodeError:
                    continue

            return 'utf-8'  # Default fallback
        except Exception:
            return 'utf-8'

    def _compile_search_pattern(self, pattern: str, case_insensitive: bool,
                               whole_word: bool, regex: bool) -> re.Pattern:
        """Compile search pattern with specified options."""
        if not regex:
            pattern = re.escape(pattern)

        if whole_word:
            pattern = r'\b' + pattern + r'\b'

        flags = re.MULTILINE
        if case_insensitive:
            flags |= re.IGNORECASE

        try:
            return re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regular expression pattern: {e}")

    def _search_file(self, file_path: Path, compiled_pattern: re.Pattern,
                    context_lines: int) -> Optional[FileSearchResult]:
        """Search a single file for the pattern."""
        try:
            encoding = self._get_file_encoding(file_path)

            with open(file_path, 'r', encoding=encoding, errors='replace') as f:
                lines = f.readlines()

            matches = []
            file_size = file_path.stat().st_size

            for line_num, line in enumerate(lines, 1):
                line_content = line.rstrip('\n\r')

                for match in compiled_pattern.finditer(line_content):
                    # Get context lines
                    context_before = []
                    context_after = []

                    if context_lines > 0:
                        start_idx = max(0, line_num - context_lines - 1)
                        end_idx = min(len(lines), line_num + context_lines)

                        context_before = [
                            lines[i].rstrip('\n\r')
                            for i in range(start_idx, line_num - 1)
                        ]
                        context_after = [
                            lines[i].rstrip('\n\r')
                            for i in range(line_num, end_idx)
                        ]

                    search_match = SearchMatch(
                        file_path=str(file_path),
                        line_number=line_num,
                        line_content=line_content,
                        match_start=match.start(),
                        match_end=match.end(),
                        context_before=context_before,
                        context_after=context_after
                    )
                    matches.append(search_match)

            if matches:
                return FileSearchResult(
                    file_path=str(file_path),
                    total_matches=len(matches),
                    matches=matches,
                    file_size=file_size,
                    encoding=encoding
                )

            return None

        except Exception as e:
            logger.warning(f"Error searching file {file_path}: {e}")
            return None

    def _find_files(self, search_path: Path, extensions: Optional[List[str]],
                   exclude_patterns: List[str], max_depth: Optional[int]) -> List[Path]:
        """Find all files to search based on criteria."""
        files = []

        def should_process_dir(dir_path: Path, current_depth: int) -> bool:
            if max_depth is not None and current_depth > max_depth:
                return False
            return not self._should_exclude_file(str(dir_path), exclude_patterns)

        def process_directory(dir_path: Path, current_depth: int = 0):
            if not should_process_dir(dir_path, current_depth):
                return

            try:
                for item in dir_path.iterdir():
                    if item.is_file():
                        if (not self._should_exclude_file(str(item), exclude_patterns) and
                            self._should_include_file(item, extensions)):
                            files.append(item)
                    elif item.is_dir() and not item.name.startswith('.'):
                        process_directory(item, current_depth + 1)
            except PermissionError:
                logger.warning(f"Permission denied accessing directory: {dir_path}")
            except Exception as e:
                logger.warning(f"Error processing directory {dir_path}: {e}")

        if search_path.is_file():
            if (not self._should_exclude_file(str(search_path), exclude_patterns) and
                self._should_include_file(search_path, extensions)):
                files.append(search_path)
        else:
            process_directory(search_path)

        return files

    def search_codebase(self,
                       pattern: str,
                       path: str = ".",
                       case_insensitive: bool = False,
                       whole_word: bool = False,
                       regex: bool = False,
                       extensions: Optional[str] = None,
                       exclude: Optional[str] = None,
                       max_depth: Optional[int] = None,
                       context: int = 0,
                       max_workers: int = 4) -> CodebaseSearchResult:
        """
        Search codebase for patterns with advanced filtering and analysis.

        Args:
            pattern: The pattern to search for
            path: The path to search in
            case_insensitive: Perform case-insensitive search
            whole_word: Match whole words only
            regex: Interpret pattern as regular expression
            extensions: Comma-separated list of file extensions to search
            exclude: Comma-separated list of glob patterns to exclude
            max_depth: Maximum directory depth to search
            context: Number of lines of context around matches
            max_workers: Number of parallel workers for file processing

        Returns:
            CodebaseSearchResult containing all search results and metadata
        """
        start_time = time.time()

        try:
            search_path = Path(path).resolve()
            if not search_path.exists():
                raise FileNotFoundError(f"Search path does not exist: {path}")

            # Parse extensions and exclude patterns
            extension_list = None
            if extensions:
                extension_list = [ext.strip() for ext in extensions.split(',')]

            exclude_patterns = self.default_exclude_patterns.copy()
            if exclude:
                exclude_patterns.extend([pattern.strip() for pattern in exclude.split(',')])

            # Compile search pattern
            compiled_pattern = self._compile_search_pattern(
                pattern, case_insensitive, whole_word, regex
            )

            # Find files to search
            files_to_search = self._find_files(
                search_path, extension_list, exclude_patterns, max_depth
            )

            if not files_to_search:
                search_time = time.time() - start_time
                return CodebaseSearchResult(
                    summary=SearchSummary(
                        total_files_searched=0,
                        total_files_with_matches=0,
                        total_matches=0,
                        search_time_seconds=search_time,
                        pattern=pattern,
                        search_path=str(search_path),
                        extensions_included=extension_list or [],
                        patterns_excluded=exclude_patterns
                    ),
                    file_results=[],
                    errors=["No files found matching search criteria"]
                )

            # Perform parallel search
            file_results = []
            errors = []

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {
                    executor.submit(self._search_file, file_path, compiled_pattern, context): file_path
                    for file_path in files_to_search
                }

                for future in as_completed(future_to_file):
                    file_path = future_to_file[future]
                    try:
                        result = future.result()
                        if result is not None:
                            file_results.append(result)
                    except Exception as e:
                        errors.append(f"Error searching {file_path}: {e}")

            search_time = time.time() - start_time
            total_matches = sum(fr.total_matches for fr in file_results)

            summary = SearchSummary(
                total_files_searched=len(files_to_search),
                total_files_with_matches=len(file_results),
                total_matches=total_matches,
                search_time_seconds=search_time,
                pattern=pattern,
                search_path=str(search_path),
                extensions_included=extension_list or [],
                patterns_excluded=exclude_patterns
            )

            return CodebaseSearchResult(
                summary=summary,
                file_results=file_results,
                errors=errors
            )

        except Exception as e:
            logger.error(f"codebase_search error: {e}", extra={"pattern": pattern, "path": path})
            raise

    def format_results(self, results: CodebaseSearchResult, format_type: str = "text",
                      compact: bool = False, group_by_file: bool = False) -> str:
        """
        Format search results in the specified format.

        Args:
            results: The search results to format
            format_type: Output format ('text', 'json', 'xml')
            compact: Use compact output format
            group_by_file: Group results by file

        Returns:
            Formatted string representation of results
        """
        if format_type.lower() == "json":
            return json.dumps(asdict(results), indent=2, default=str)

        elif format_type.lower() == "xml":
            return self._format_xml(results)

        else:  # text format
            return self._format_text(results, compact, group_by_file)

    def _format_text(self, results: CodebaseSearchResult, compact: bool,
                    group_by_file: bool) -> str:
        """Format results as human-readable text."""
        lines = []

        # Add summary
        summary = results.summary
        lines.append(f"Search Results for '{summary.pattern}'")
        lines.append("=" * 50)
        lines.append(f"Path: {summary.search_path}")
        lines.append(f"Files searched: {summary.total_files_searched}")
        lines.append(f"Files with matches: {summary.total_files_with_matches}")
        lines.append(f"Total matches: {summary.total_matches}")
        lines.append(f"Search time: {summary.search_time_seconds:.2f}s")

        if summary.extensions_included:
            lines.append(f"Extensions: {', '.join(summary.extensions_included)}")

        lines.append("")

        # Add results
        if not results.file_results:
            lines.append("No matches found.")
        else:
            if group_by_file:
                lines.extend(self._format_grouped_results(results.file_results, compact))
            else:
                lines.extend(self._format_sequential_results(results.file_results, compact))

        # Add errors if any
        if results.errors:
            lines.append("\nErrors:")
            for error in results.errors:
                lines.append(f"  - {error}")

        return "\n".join(lines)

    def _format_grouped_results(self, file_results: List[FileSearchResult],
                               compact: bool) -> List[str]:
        """Format results grouped by file."""
        lines = []

        for file_result in file_results:
            lines.append(f"\n{file_result.file_path} ({file_result.total_matches} matches)")
            lines.append("-" * 40)

            for match in file_result.matches:
                if compact:
                    lines.append(f"  {match.line_number}: {match.line_content}")
                else:
                    lines.append(f"  Line {match.line_number}:")
                    lines.append(f"    {match.line_content}")
                    if match.context_before or match.context_after:
                        lines.append("    Context:")
                        for ctx_line in match.context_before[-2:]:
                            lines.append(f"      - {ctx_line}")
                        lines.append(f"      > {match.line_content}")
                        for ctx_line in match.context_after[:2]:
                            lines.append(f"      + {ctx_line}")

        return lines

    def _format_sequential_results(self, file_results: List[FileSearchResult],
                                  compact: bool) -> List[str]:
        """Format results in sequential order."""
        lines = []

        for file_result in file_results:
            for match in file_result.matches:
                if compact:
                    lines.append(f"{file_result.file_path}:{match.line_number}: {match.line_content}")
                else:
                    lines.append(f"\n{file_result.file_path}:{match.line_number}")
                    lines.append(f"  {match.line_content}")

                    if match.context_before or match.context_after:
                        for ctx_line in match.context_before[-2:]:
                            lines.append(f"  - {ctx_line}")
                        for ctx_line in match.context_after[:2]:
                            lines.append(f"  + {ctx_line}")

        return lines

    def _format_xml(self, results: CodebaseSearchResult) -> str:
        """Format results as XML."""
        xml_lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        xml_lines.append('<search_results>')

        # Summary
        summary = results.summary
        xml_lines.append('  <summary>')
        xml_lines.append(f'    <pattern>{summary.pattern}</pattern>')
        xml_lines.append(f'    <search_path>{summary.search_path}</search_path>')
        xml_lines.append(f'    <total_files_searched>{summary.total_files_searched}</total_files_searched>')
        xml_lines.append(f'    <total_files_with_matches>{summary.total_files_with_matches}</total_files_with_matches>')
        xml_lines.append(f'    <total_matches>{summary.total_matches}</total_matches>')
        xml_lines.append(f'    <search_time_seconds>{summary.search_time_seconds}</search_time_seconds>')
        xml_lines.append('  </summary>')

        # Files
        xml_lines.append('  <files>')
        for file_result in results.file_results:
            xml_lines.append(f'    <file path="{file_result.file_path}" matches="{file_result.total_matches}">')

            for match in file_result.matches:
                xml_lines.append(f'      <match line="{match.line_number}">')
                xml_lines.append(f'        <content><![CDATA[{match.line_content}]]></content>')
                xml_lines.append(f'        <match_start>{match.match_start}</match_start>')
                xml_lines.append(f'        <match_end>{match.match_end}</match_end>')
                xml_lines.append('      </match>')

            xml_lines.append('    </file>')
        xml_lines.append('  </files>')

        xml_lines.append('</search_results>')
        return '\n'.join(xml_lines)

    def search_dataset_patterns(self, path: str = ".", pattern_type: str = "all") -> Dict[str, Any]:
        """
        Search for dataset-specific patterns (IPFS hashes, ML patterns, etc.).

        Args:
            path: Path to search
            pattern_type: Type of patterns to search for

        Returns:
            Dictionary containing found patterns organized by type
        """
        results = {}

        patterns_to_search = self.dataset_patterns
        if pattern_type != "all" and pattern_type in self.dataset_patterns:
            patterns_to_search = {pattern_type: self.dataset_patterns[pattern_type]}

        for pattern_name, pattern_regex in patterns_to_search.items():
            search_result = self.search_codebase(
                pattern=pattern_regex,
                path=path,
                regex=True,
                extensions="py,ipynb,md,txt,json,yaml,yml"
            )

            if search_result.file_results:
                results[pattern_name] = {
                    "total_matches": search_result.summary.total_matches,
                    "files": [fr.file_path for fr in search_result.file_results],
                    "sample_matches": [
                        {
                            "file": match.file_path,
                            "line": match.line_number,
                            "content": match.line_content
                        }
                        for file_result in search_result.file_results[:3]
                        for match in file_result.matches[:2]
                    ]
                }

        return results

    async def _execute_core(self, **kwargs) -> Dict[str, Any]:
        """
        Core execution method for the codebase search tool.

        Args:
            **kwargs: Search parameters

        Returns:
            Standardized result dictionary
        """
        try:
            # Extract parameters
            pattern = kwargs.get('pattern', '')
            path = kwargs.get('path', '.')
            case_insensitive = kwargs.get('case_insensitive', False)
            whole_word = kwargs.get('whole_word', False)
            regex = kwargs.get('regex', False)
            extensions = kwargs.get('extensions')
            exclude = kwargs.get('exclude')
            max_depth = kwargs.get('max_depth')
            context = kwargs.get('context', 0)
            format_type = kwargs.get('format', 'text')
            compact = kwargs.get('compact', False)
            group_by_file = kwargs.get('group_by_file', False)

            # Perform search
            results = self.search_codebase(
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

            # Format results
            formatted_output = self.format_results(
                results, format_type, compact, group_by_file
            )

            return self._create_success_result(
                result=formatted_output,
                metadata={
                    "search_summary": asdict(results.summary),
                    "files_with_matches": len(results.file_results),
                    "total_matches": results.summary.total_matches
                }
            )

        except Exception as e:
            self.logger.error(f"Codebase search failed: {e}")
            return self._create_error_result(
                "search_failed",
                f"Search operation failed: {str(e)}",
                {"exception_type": type(e).__name__}
            )


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
            except Exception as e:
                return {
                    "success": False,
                    "error": "file_write_error",
                    "message": f"Error writing to file {output}: {e}",
                    "metadata": {"tool": "codebase_search"}
                }

        return formatted_output

    except Exception as e:
        return {
            "success": False,
            "error": "search_error",
            "message": str(e),
            "metadata": {"tool": "codebase_search"}
        }


# Example usage and testing
if __name__ == "__main__":
    # Example search
    engine = CodebaseSearchEngine()

    # Search for function definitions
    results = engine.search_codebase(
        pattern=r"def\s+\w+\s*\(",
        path=".",
        regex=True,
        extensions="py",
        context=1
    )

    print(engine.format_results(results))

    # Search for dataset patterns
    dataset_results = engine.search_dataset_patterns(".", "ipfs_hash")
    print("\nDataset patterns found:")
    print(json.dumps(dataset_results, indent=2))

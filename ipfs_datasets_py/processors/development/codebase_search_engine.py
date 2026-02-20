"""
Codebase Search Engine — reusable core module.

Contains the ``CodebaseSearchEngine`` class and result dataclasses extracted
from ``codebase_search.py``.  Import from this module to use search logic
independently of MCP tooling.
"""

from __future__ import annotations

import fnmatch
import glob as glob_module
import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CodebaseSearchEngine:
    """
    Advanced codebase search engine with pattern matching, filtering, and analysis.

    Features:
    - Regular expression and literal pattern matching
    - File extension and path filtering
    - Context lines around matches
    - Multiple output formats (text, JSON, XML)
    - Performance optimisation with parallel processing
    - Dataset-aware search for IPFS hashes and data-science patterns
    """

    def __init__(self) -> None:
        """Initialise the search engine with default exclusion patterns."""
        self.logger = logging.getLogger(__name__)
        self.default_exclude_patterns = [
            "*.git*", "*__pycache__*", "*.pyc", "*.pyo", "*.pyd",
            "*node_modules*", "*.npm*", "*.yarn*",
            "*.egg-info*", "*.dist-info*", "*build*", "*dist*",
            "*.ipynb_checkpoints*", "*.pytest_cache*",
            "*.coverage*", "*.tox*", "*.mypy_cache*",
        ]

        # Dataset-aware patterns for specialised search
        self.dataset_patterns: Dict[str, str] = {
            "ipfs_hash": r"(?:Qm[1-9A-HJ-NP-Za-km-z]{44}|ba[a-z2-7]{56})",
            "cid_v0": r"Qm[1-9A-HJ-NP-Za-km-z]{44}",
            "cid_v1": r"ba[a-z2-7]{56}",
            "dataframe_ops": r"(?:\.read_csv|\.to_csv|\.read_parquet|\.to_parquet|pd\.DataFrame)",
            "ml_imports": r"(?:import (?:torch|tensorflow|sklearn|numpy|pandas|scipy))",
            "async_patterns": r"(?:async def|await |asyncio\.)",
            "test_patterns": r"(?:def test_|@pytest\.|unittest\.)",
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
        file_ext = file_path.suffix.lstrip(".")
        return file_ext.lower() in [ext.lower().lstrip(".") for ext in extensions]

    def _get_file_encoding(self, file_path: Path) -> str:
        """Detect file encoding."""
        try:
            for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        f.read(1024)
                    return encoding
                except UnicodeDecodeError:
                    continue
            return "utf-8"
        except OSError:
            return "utf-8"

    def _compile_search_pattern(
        self,
        pattern: str,
        case_insensitive: bool,
        whole_word: bool,
        regex: bool,
    ) -> re.Pattern:  # type: ignore[type-arg]
        """Compile search pattern with specified options."""
        if not regex:
            pattern = re.escape(pattern)
        if whole_word:
            pattern = r"\b" + pattern + r"\b"
        flags = re.MULTILINE
        if case_insensitive:
            flags |= re.IGNORECASE
        try:
            return re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regular expression pattern: {e}") from e

    def _search_file(
        self,
        file_path: Path,
        compiled_pattern: re.Pattern,  # type: ignore[type-arg]
        context_lines: int,
    ) -> Optional[FileSearchResult]:
        """Search a single file for the pattern."""
        try:
            encoding = self._get_file_encoding(file_path)
            with open(file_path, "r", encoding=encoding, errors="replace") as f:
                lines = f.readlines()

            matches: List[SearchMatch] = []
            file_size = file_path.stat().st_size

            for line_num, line in enumerate(lines, 1):
                line_content = line.rstrip("\n\r")
                for match in compiled_pattern.finditer(line_content):
                    context_before: List[str] = []
                    context_after: List[str] = []
                    if context_lines > 0:
                        start_idx = max(0, line_num - context_lines - 1)
                        end_idx = min(len(lines), line_num + context_lines)
                        context_before = [
                            lines[i].rstrip("\n\r")
                            for i in range(start_idx, line_num - 1)
                        ]
                        context_after = [
                            lines[i].rstrip("\n\r")
                            for i in range(line_num, end_idx)
                        ]
                    matches.append(
                        SearchMatch(
                            file_path=str(file_path),
                            line_number=line_num,
                            line_content=line_content,
                            match_start=match.start(),
                            match_end=match.end(),
                            context_before=context_before,
                            context_after=context_after,
                        )
                    )

            if matches:
                return FileSearchResult(
                    file_path=str(file_path),
                    total_matches=len(matches),
                    matches=matches,
                    file_size=file_size,
                    encoding=encoding,
                )
            return None
        except (OSError, UnicodeDecodeError) as e:
            logger.warning(f"Error searching file {file_path}: {e}")
            return None

    def _find_files(
        self,
        search_path: Path,
        extensions: Optional[List[str]],
        exclude_patterns: List[str],
        max_depth: Optional[int],
    ) -> List[Path]:
        """Find all files to search based on criteria."""
        files: List[Path] = []

        def should_process_dir(dir_path: Path, current_depth: int) -> bool:
            if max_depth is not None and current_depth > max_depth:
                return False
            return not self._should_exclude_file(str(dir_path), exclude_patterns)

        def process_directory(dir_path: Path, current_depth: int = 0) -> None:
            if not should_process_dir(dir_path, current_depth):
                return
            try:
                for item in dir_path.iterdir():
                    if item.is_file():
                        if not self._should_exclude_file(str(item), exclude_patterns) and \
                                self._should_include_file(item, extensions):
                            files.append(item)
                    elif item.is_dir() and not item.name.startswith("."):
                        process_directory(item, current_depth + 1)
            except PermissionError:
                logger.warning(f"Permission denied accessing directory: {dir_path}")
            except OSError as e:
                logger.warning(f"Error processing directory {dir_path}: {e}")

        if search_path.is_file():
            if not self._should_exclude_file(str(search_path), exclude_patterns) and \
                    self._should_include_file(search_path, extensions):
                files.append(search_path)
        else:
            process_directory(search_path)

        return files

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_codebase(
        self,
        pattern: str,
        path: str = ".",
        case_insensitive: bool = False,
        whole_word: bool = False,
        regex: bool = False,
        extensions: Optional[str] = None,
        exclude: Optional[str] = None,
        max_depth: Optional[int] = None,
        context: int = 0,
        max_workers: int = 4,
    ) -> CodebaseSearchResult:
        """Search codebase for patterns with advanced filtering and analysis."""
        start_time = time.time()

        search_path = Path(path).resolve()
        if not search_path.exists():
            raise FileNotFoundError(f"Search path does not exist: {path}")

        extension_list: Optional[List[str]] = None
        if extensions:
            extension_list = [ext.strip() for ext in extensions.split(",")]

        exclude_patterns = self.default_exclude_patterns.copy()
        if exclude:
            exclude_patterns.extend([p.strip() for p in exclude.split(",")])

        compiled_pattern = self._compile_search_pattern(
            pattern, case_insensitive, whole_word, regex
        )

        files_to_search = self._find_files(
            search_path, extension_list, exclude_patterns, max_depth
        )

        if not files_to_search:
            return CodebaseSearchResult(
                summary=SearchSummary(
                    total_files_searched=0,
                    total_files_with_matches=0,
                    total_matches=0,
                    search_time_seconds=time.time() - start_time,
                    pattern=pattern,
                    search_path=str(search_path),
                    extensions_included=extension_list or [],
                    patterns_excluded=exclude_patterns,
                ),
                file_results=[],
                errors=["No files found matching search criteria"],
            )

        file_results: List[FileSearchResult] = []
        errors: List[str] = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_file = {
                executor.submit(self._search_file, fp, compiled_pattern, context): fp
                for fp in files_to_search
            }
            for future in as_completed(future_to_file):
                fp = future_to_file[future]
                try:
                    result = future.result()
                    if result is not None:
                        file_results.append(result)
                except (OSError, ValueError) as e:
                    errors.append(f"Error searching {fp}: {e}")

        search_time = time.time() - start_time
        summary = SearchSummary(
            total_files_searched=len(files_to_search),
            total_files_with_matches=len(file_results),
            total_matches=sum(fr.total_matches for fr in file_results),
            search_time_seconds=search_time,
            pattern=pattern,
            search_path=str(search_path),
            extensions_included=extension_list or [],
            patterns_excluded=exclude_patterns,
        )
        return CodebaseSearchResult(
            summary=summary, file_results=file_results, errors=errors
        )

    def format_results(
        self,
        results: CodebaseSearchResult,
        format_type: str = "text",
        compact: bool = False,
        group_by_file: bool = False,
    ) -> str:
        """Format search results in the specified format."""
        if format_type.lower() == "json":
            return json.dumps(asdict(results), indent=2, default=str)
        if format_type.lower() == "xml":
            return self._format_xml(results)
        return self._format_text(results, compact, group_by_file)

    def _format_text(
        self,
        results: CodebaseSearchResult,
        compact: bool,
        group_by_file: bool,
    ) -> str:
        """Format results as human-readable text."""
        s = results.summary
        lines = [
            f"Search Results for '{s.pattern}'",
            "=" * 50,
            f"Path: {s.search_path}",
            f"Files searched: {s.total_files_searched}",
            f"Files with matches: {s.total_files_with_matches}",
            f"Total matches: {s.total_matches}",
            f"Search time: {s.search_time_seconds:.2f}s",
        ]
        if s.extensions_included:
            lines.append(f"Extensions: {', '.join(s.extensions_included)}")
        lines.append("")
        if not results.file_results:
            lines.append("No matches found.")
        elif group_by_file:
            lines.extend(self._format_grouped_results(results.file_results, compact))
        else:
            lines.extend(self._format_sequential_results(results.file_results, compact))
        if results.errors:
            lines.append("\nErrors:")
            for error in results.errors:
                lines.append(f"  - {error}")
        return "\n".join(lines)

    def _format_grouped_results(
        self, file_results: List[FileSearchResult], compact: bool
    ) -> List[str]:
        """Format results grouped by file."""
        lines: List[str] = []
        for fr in file_results:
            lines.append(f"\n{fr.file_path} ({fr.total_matches} matches)")
            lines.append("-" * 40)
            for m in fr.matches:
                if compact:
                    lines.append(f"  {m.line_number}: {m.line_content}")
                else:
                    lines.append(f"  Line {m.line_number}:")
                    lines.append(f"    {m.line_content}")
                    if m.context_before or m.context_after:
                        lines.append("    Context:")
                        for ctx in m.context_before[-2:]:
                            lines.append(f"      - {ctx}")
                        lines.append(f"      > {m.line_content}")
                        for ctx in m.context_after[:2]:
                            lines.append(f"      + {ctx}")
        return lines

    def _format_sequential_results(
        self, file_results: List[FileSearchResult], compact: bool
    ) -> List[str]:
        """Format results in sequential order."""
        lines: List[str] = []
        for fr in file_results:
            for m in fr.matches:
                if compact:
                    lines.append(f"{fr.file_path}:{m.line_number}: {m.line_content}")
                else:
                    lines.append(f"\n{fr.file_path}:{m.line_number}")
                    lines.append(f"  {m.line_content}")
                    if m.context_before or m.context_after:
                        for ctx in m.context_before[-2:]:
                            lines.append(f"  - {ctx}")
                        for ctx in m.context_after[:2]:
                            lines.append(f"  + {ctx}")
        return lines

    def _format_xml(self, results: CodebaseSearchResult) -> str:
        """Format results as XML."""
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<search_results>"]
        s = results.summary
        lines += [
            "  <summary>",
            f"    <pattern>{s.pattern}</pattern>",
            f"    <search_path>{s.search_path}</search_path>",
            f"    <total_files_searched>{s.total_files_searched}</total_files_searched>",
            f"    <total_files_with_matches>{s.total_files_with_matches}</total_files_with_matches>",
            f"    <total_matches>{s.total_matches}</total_matches>",
            f"    <search_time_seconds>{s.search_time_seconds}</search_time_seconds>",
            "  </summary>",
            "  <files>",
        ]
        for fr in results.file_results:
            lines.append(f'    <file path="{fr.file_path}" matches="{fr.total_matches}">')
            for m in fr.matches:
                lines += [
                    f'      <match line="{m.line_number}">',
                    f"        <content><![CDATA[{m.line_content}]]></content>",
                    f"        <match_start>{m.match_start}</match_start>",
                    f"        <match_end>{m.match_end}</match_end>",
                    "      </match>",
                ]
            lines.append("    </file>")
        lines += ["  </files>", "</search_results>"]
        return "\n".join(lines)

    def search_dataset_patterns(
        self, path: str = ".", pattern_type: str = "all"
    ) -> Dict[str, Any]:
        """Search for dataset-specific patterns (IPFS hashes, ML patterns, etc.)."""
        patterns_to_search = self.dataset_patterns
        if pattern_type != "all" and pattern_type in self.dataset_patterns:
            patterns_to_search = {pattern_type: self.dataset_patterns[pattern_type]}

        results: Dict[str, Any] = {}
        for pattern_name, pattern_regex in patterns_to_search.items():
            search_result = self.search_codebase(
                pattern=pattern_regex,
                path=path,
                regex=True,
                extensions="py,ipynb,md,txt,json,yaml,yml",
            )
            if search_result.file_results:
                results[pattern_name] = {
                    "total_matches": search_result.summary.total_matches,
                    "files": [fr.file_path for fr in search_result.file_results],
                    "sample_matches": [
                        {
                            "file": m.file_path,
                            "line": m.line_number,
                            "content": m.line_content,
                        }
                        for fr in search_result.file_results[:3]
                        for m in fr.matches[:2]
                    ],
                }
        return results


__all__ = [
    "CodebaseSearchEngine",
    "CodebaseSearchResult",
    "FileSearchResult",
    "SearchMatch",
    "SearchSummary",
]

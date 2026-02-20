"""
Linting Tools — MCP thin wrapper around the linting engine.

Business logic lives in :mod:`linting_engine`; this file provides the
MCP-facing ``LintingTools`` class and convenience entry-points.
"""

import logging
import anyio
from pathlib import Path
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .base_tool import BaseDevelopmentTool, development_tool_mcp_wrapper
from .config import get_config
# Core business logic (extracted to linting_engine.py for Phase 5 compliance)
from .linting_engine import LintIssue, LintResult, PythonLinter, DatasetLinter

logger = logging.getLogger(__name__)


class LintingTools(BaseDevelopmentTool):
    """
    Comprehensive linting tools for Python projects.

    Provides code quality checks, formatting fixes, and dataset-specific validations
    with support for flake8, mypy, and custom rules.
    """

    def __init__(self):
        super().__init__(
            name="linting_tools",
            description="Comprehensive Python linting and code quality tools",
            category="development"
        )
        self.config = get_config().linting_tools
        self.python_linter = PythonLinter(config=self.config)
        self.dataset_linter = DatasetLinter()

    async def _execute_core(self, **kwargs) -> Dict[str, Any]:
        """
        Core execution logic for the linting tools.

        Args:
            **kwargs: Tool-specific parameters forwarded to lint_codebase

        Returns:
            Tool execution result
        """
        return await self.lint_codebase(**kwargs)

    async def lint_codebase(self,
                           path: str = ".",
                           patterns: Optional[List[str]] = None,
                           exclude_patterns: Optional[List[str]] = None,
                           fix_issues: bool = True,
                           include_dataset_rules: bool = True,
                           dry_run: bool = False,
                           verbose: bool = False) -> Dict[str, Any]:
        """
        Lint Python codebase with comprehensive quality checks.

        Args:
            path: Target directory to process (default: ".")
            patterns: File patterns to include (default: ['**/*.py'])
            exclude_patterns: Patterns to exclude (default: configured defaults)
            fix_issues: Apply automatic fixes where possible (default: True)
            include_dataset_rules: Include dataset-specific linting rules (default: True)
            dry_run: Show what would be changed without making changes (default: False)
            verbose: Print detailed information (default: False)

        Returns:
            Dictionary containing linting results and statistics
        """
        try:
            # Validate inputs
            path = self._validate_path(path)

            if patterns is None:
                patterns = self.config.file_patterns
            if exclude_patterns is None:
                exclude_patterns = self.config.exclude_dirs

            # If dry run, don't fix issues
            if dry_run:
                fix_issues = False

            # Discover Python files
            python_files = self._discover_python_files(path, patterns, exclude_patterns)

            if not python_files:
                return self._create_error_result("no_files", "No Python files found to lint")

            # Lint files in parallel
            lint_results = await self._lint_files_parallel(
                python_files,
                fix_issues,
                include_dataset_rules,
                verbose
            )

            # Aggregate results
            aggregated_result = self._aggregate_results(lint_results)

            # Add run configuration to results
            aggregated_result.update({
                "path": str(path),
                "fix_issues": fix_issues,
                "dry_run": dry_run,
                "files_processed": len(python_files),
                "include_dataset_rules": include_dataset_rules
            })

            await self._audit_log("linting.completed", {
                "path": str(path),
                "files_processed": len(python_files),
                "issues_found": aggregated_result.get("total_issues", 0),
                "issues_fixed": aggregated_result.get("total_fixes", 0),
                "dry_run": dry_run
            })

            return self._create_success_result(aggregated_result)

        except Exception as e:
            logger.error(f"Linting failed: {e}")
            return self._create_error_result("linting_failed", f"Linting failed: {e}")

    def _discover_python_files(self, path: Path, patterns: List[str],
                              exclude_patterns: List[str]) -> List[Path]:
        """Discover Python files to lint."""
        python_files = []

        if path.is_file() and path.suffix == '.py':
            return [path]

        if path.is_dir():
            for pattern in patterns:
                for file_path in path.glob(pattern):
                    if file_path.is_file() and self._should_include_file(file_path, exclude_patterns):
                        python_files.append(file_path)

        return sorted(python_files)

    def _should_include_file(self, file_path: Path, exclude_patterns: List[str]) -> bool:
        """Check if file should be included based on exclude patterns."""
        file_str = str(file_path)

        for pattern in exclude_patterns:
            if pattern in file_str or file_path.match(pattern):
                return False

        return True

    async def _lint_files_parallel(self, python_files: List[Path], fix_issues: bool,
                                  include_dataset_rules: bool, verbose: bool) -> List[LintResult]:
        """Lint Python files in parallel."""
        def lint_file_sync(file_path):
            result = self.python_linter.lint_file(file_path, fix_issues)

            # Add dataset-specific rules if requested
            if include_dataset_rules:
                dataset_issues = self.dataset_linter.lint_dataset_code(file_path)
                result.issues.extend(dataset_issues)
                result.issues_found = len(result.issues)
                result.summary = self.python_linter.create_summary(result.issues)

            if verbose:
                logger.info(f"Linted {file_path}: {result.issues_found} issues found")

            return result

        # Process files in smaller batches to avoid overwhelming the system
        batch_size = 10
        all_results = []

        for i in range(0, len(python_files), batch_size):
            batch = python_files[i:i + batch_size]

            batch_results: List[Optional[LintResult]] = [None] * len(batch)
            async with anyio.create_task_group() as tg:
                for idx, file_path in enumerate(batch):
                    async def _runner(i: int = idx, fp: Path = file_path) -> None:
                        batch_results[i] = await anyio.to_thread.run_sync(lint_file_sync, fp)

                    tg.start_soon(_runner)

            all_results.extend([r for r in batch_results if r is not None])

        return all_results

    def _aggregate_results(self, lint_results: List[LintResult]) -> Dict[str, Any]:
        """Aggregate results from multiple files."""
        total_files = len(lint_results)
        total_issues = sum(r.issues_found for r in lint_results)
        total_fixes = sum(r.issues_fixed for r in lint_results)

        all_issues = []
        all_modified_files = []

        severity_counts = {"error": 0, "warning": 0, "info": 0}
        rule_counts = {}

        for result in lint_results:
            all_issues.extend(result.issues)
            all_modified_files.extend(result.files_modified)

            # Count by severity
            for issue in result.issues:
                severity_counts[issue.severity] = severity_counts.get(issue.severity, 0) + 1
                rule_counts[issue.rule_id] = rule_counts.get(issue.rule_id, 0) + 1

        return {
            "total_files": total_files,
            "total_issues": total_issues,
            "total_fixes": total_fixes,
            "files_modified": len(set(all_modified_files)),
            "severity_breakdown": severity_counts,
            "rule_breakdown": rule_counts,
            "issues": [
                {
                    "file": issue.file_path,
                    "line": issue.line_number,
                    "column": issue.column,
                    "rule": issue.rule_id,
                    "severity": issue.severity,
                    "message": issue.message,
                    "fix_suggestion": issue.fix_suggestion
                }
                for issue in all_issues
            ][:100]  # Limit to first 100 issues for display
        }


def lint_python_codebase(path: str = ".",
                        patterns: Optional[List[str]] = None,
                        exclude_patterns: Optional[List[str]] = None,
                        fix_issues: bool = True,
                        include_dataset_rules: bool = True,
                        dry_run: bool = False,
                        verbose: bool = False) -> Dict[str, Any]:
    """
    Lint Python codebase with comprehensive quality checks and automatic fixes.

    Args:
        path: Target directory to process (default: ".")
        patterns: File patterns to include like ['**/*.py'] (default: None uses config)
        exclude_patterns: Patterns to exclude like ['.venv', '__pycache__'] (default: None uses config)
        fix_issues: Apply automatic fixes where possible (default: True)
        include_dataset_rules: Include dataset-specific linting rules (default: True)
        dry_run: Show what would be changed without making changes (default: False)
        verbose: Print detailed information for each file (default: False)

    Returns:
        Dictionary containing linting results, statistics, and issue details
    """
    tool = LintingTools()
    
    # Execute the tool and return results
    try:
        # If called from within an async context, run in a worker thread.
        try:
            import sniffio

            sniffio.current_async_library()
            in_async = True
        except (ImportError, ModuleNotFoundError, AttributeError):
            in_async = False

        if in_async:
            def run_in_thread():
                return anyio.run(
                    tool.execute,
                    path=path,
                    patterns=patterns,
                    exclude_patterns=exclude_patterns,
                    fix_issues=fix_issues,
                    include_dataset_rules=include_dataset_rules,
                    dry_run=dry_run,
                    verbose=verbose,
                )

            with ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result()

        return anyio.run(
            tool.execute,
            path=path,
            patterns=patterns,
            exclude_patterns=exclude_patterns,
            fix_issues=fix_issues,
            include_dataset_rules=include_dataset_rules,
            dry_run=dry_run,
            verbose=verbose,
        )
    except Exception as e:
        # Fallback to error result if execution fails
        return {
            "success": False,
            "error": "execution_error",
            "message": f"Failed to execute linting tool: {e}",
            "metadata": {
                "tool": "lint_python_codebase",
                "timestamp": datetime.now().isoformat()
            }
        }


# Main MCP function
async def linting_tools(
    path: str = ".",
    file_patterns: Optional[List[str]] = None,
    auto_fix: bool = False,
    exclude_dirs: Optional[List[str]] = None
):
    """
    Comprehensive Python code linting and auto-fixing.
    """
    try:
        linter = LintingTools(
            name="LintingTools",
            description="Comprehensive Python code linting and auto-fixing"
        )
        
        result = await linter.execute(
            path=path,
            file_patterns=file_patterns or ["**/*.py"],
            auto_fix=auto_fix,
            exclude_dirs=exclude_dirs or [".venv", ".git", "__pycache__"]
        )
        
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Linting tools failed: {str(e)}",
            "tool_type": "development_tool"
        }

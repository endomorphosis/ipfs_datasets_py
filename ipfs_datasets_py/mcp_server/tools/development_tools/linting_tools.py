"""
Linting Tools

Provides comprehensive linting and code quality tools for Python projects.
Migrated from claudes_toolbox with enhanced IPFS and dataset validation capabilities.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .base_tool import BaseDevelopmentTool, development_tool_mcp_wrapper
from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class LintIssue:
    """Represents a linting issue."""
    file_path: str
    line_number: int
    column: Optional[int]
    rule_id: str
    severity: str  # 'error', 'warning', 'info'
    message: str
    fix_suggestion: Optional[str] = None


@dataclass
class LintResult:
    """Results of linting operation."""
    total_files: int
    issues_found: int
    issues_fixed: int
    files_modified: List[str]
    issues: List[LintIssue]
    summary: Dict[str, Any]


class PythonLinter:
    """Core Python linting functionality."""

    def __init__(self):
        self.config = get_config().linting_tools

    def lint_file(self, file_path: Path, fix_issues: bool = True,
                  patterns: Optional[List[str]] = None) -> LintResult:
        """Lint a single Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()

            issues = []
            modified_content = original_content
            files_modified = []

            # Apply fixes if requested
            if fix_issues:
                modified_content, fixed_issues = self._apply_basic_fixes(
                    original_content, file_path
                )
                issues.extend(fixed_issues)

                if modified_content != original_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(modified_content)
                    files_modified.append(str(file_path))

            # Run external linters
            external_issues = self._run_external_linters(file_path)
            issues.extend(external_issues)

            return LintResult(
                total_files=1,
                issues_found=len(issues),
                issues_fixed=len([i for i in issues if i.fix_suggestion]),
                files_modified=files_modified,
                issues=issues,
                summary=self._create_summary(issues)
            )

        except Exception as e:
            logger.error(f"Error linting file {file_path}: {e}")
            return LintResult(
                total_files=1,
                issues_found=0,
                issues_fixed=0,
                files_modified=[],
                issues=[],
                summary={"error": str(e)}
            )

    def _apply_basic_fixes(self, content: str, file_path: Path) -> Tuple[str, List[LintIssue]]:
        """Apply basic formatting fixes."""
        issues = []
        lines = content.split('\n')
        modified_lines = []

        for i, line in enumerate(lines):
            original_line = line
            line_number = i + 1

            # Fix trailing whitespace
            if line.rstrip() != line:
                issues.append(LintIssue(
                    file_path=str(file_path),
                    line_number=line_number,
                    column=len(line.rstrip()) + 1,
                    rule_id="W291",
                    severity="warning",
                    message="Trailing whitespace",
                    fix_suggestion="Remove trailing whitespace"
                ))
                line = line.rstrip()

            # Fix lines with only whitespace
            if line.strip() == "" and line != "":
                issues.append(LintIssue(
                    file_path=str(file_path),
                    line_number=line_number,
                    column=1,
                    rule_id="W293",
                    severity="warning",
                    message="Blank line contains whitespace",
                    fix_suggestion="Remove whitespace from blank line"
                ))
                line = ""

            modified_lines.append(line)

        # Ensure file ends with newline
        modified_content = '\n'.join(modified_lines)
        if content and not content.endswith('\n'):
            issues.append(LintIssue(
                file_path=str(file_path),
                line_number=len(lines),
                column=len(lines[-1]) + 1,
                rule_id="W292",
                severity="warning",
                message="No newline at end of file",
                fix_suggestion="Add newline at end of file"
            ))
            modified_content += '\n'

        return modified_content, issues

    def _run_external_linters(self, file_path: Path) -> List[LintIssue]:
        """Run external linting tools."""
        issues = []

        # Run flake8 if available
        if self.config.run_flake8:
            issues.extend(self._run_flake8(file_path))

        # Run mypy if available
        if self.config.run_mypy:
            issues.extend(self._run_mypy(file_path))

        return issues

    def _run_flake8(self, file_path: Path) -> List[LintIssue]:
        """Run flake8 linter."""
        try:
            # Check if flake8 is installed before attempting to run it
            import importlib.util
            flake8_spec = importlib.util.find_spec('flake8')

            if flake8_spec is None:
                logger.warning("flake8 is not installed. Install with 'pip install flake8'")
                return [LintIssue(
                    file_path=str(file_path),
                    line_number=1,
                    column=1,
                    rule_id="TOOL-MISSING",
                    severity="warning",
                    message="flake8 is not installed, install with 'pip install flake8'",
                    fix_suggestion="pip install flake8"
                )]

            result = subprocess.run(
                ['flake8', '--format=%(path)s:%(row)d:%(col)d: %(code)s %(text)s', str(file_path)],
                capture_output=True,
                text=True,
                timeout=30
            )

            issues = []
            for line in result.stdout.split('\n'):
                if line.strip():
                    match = re.match(r'([^:]+):(\d+):(\d+):\s+(\w+)\s+(.*)', line)
                    if match:
                        path, line_num, col, code, message = match.groups()
                        severity = "error" if code.startswith('E') else "warning"

                        issues.append(LintIssue(
                            file_path=path,
                            line_number=int(line_num),
                            column=int(col),
                            rule_id=code,
                            severity=severity,
                            message=message
                        ))

            return issues

        except subprocess.TimeoutExpired:
            logger.warning("flake8 timed out - consider increasing timeout for large files")
            return [LintIssue(
                file_path=str(file_path),
                line_number=1,
                column=1,
                rule_id="TIMEOUT",
                severity="warning",
                message="flake8 timed out while processing the file",
                fix_suggestion=None
            )]
        except FileNotFoundError:
            logger.warning("flake8 command not found in PATH. Install flake8 with 'pip install flake8'")
            return [LintIssue(
                file_path=str(file_path),
                line_number=1,
                column=1,
                rule_id="TOOL-MISSING",
                severity="warning",
                message="flake8 command not found, install with 'pip install flake8'",
                fix_suggestion="pip install flake8"
            )]
        except Exception as e:
            logger.error(f"Error running flake8: {e}")
            return [LintIssue(
                file_path=str(file_path),
                line_number=1,
                column=1,
                rule_id="ERROR",
                severity="error",
                message=f"Error running flake8: {e}",
                fix_suggestion=None
            )]

    def _run_mypy(self, file_path: Path) -> List[LintIssue]:
        """Run mypy type checker."""
        try:
            # Check if mypy is installed before attempting to run it
            import importlib.util
            mypy_spec = importlib.util.find_spec('mypy')

            if mypy_spec is None:
                logger.warning("mypy is not installed. Install with 'pip install mypy'")
                return [LintIssue(
                    file_path=str(file_path),
                    line_number=1,
                    column=1,
                    rule_id="TOOL-MISSING",
                    severity="warning",
                    message="mypy is not installed, install with 'pip install mypy'",
                    fix_suggestion="pip install mypy"
                )]

            result = subprocess.run(
                ['mypy', '--show-column-numbers', str(file_path)],
                capture_output=True,
                text=True,
                timeout=30
            )

            issues = []
            for line in result.stdout.split('\n'):
                if line.strip() and ':' in line:
                    match = re.match(r'([^:]+):(\d+):(\d+):\s+(error|warning|note):\s+(.*)', line)
                    if match:
                        path, line_num, col, severity, message = match.groups()

                        issues.append(LintIssue(
                            file_path=path,
                            line_number=int(line_num),
                            column=int(col),
                            rule_id="mypy",
                            severity=severity,
                            message=message
                        ))

            return issues

        except subprocess.TimeoutExpired:
            logger.warning("mypy timed out - consider increasing timeout for large files")
            return [LintIssue(
                file_path=str(file_path),
                line_number=1,
                column=1,
                rule_id="TIMEOUT",
                severity="warning",
                message="mypy timed out while processing the file",
                fix_suggestion=None
            )]
        except FileNotFoundError:
            logger.warning("mypy command not found in PATH. Install mypy with 'pip install mypy'")
            return [LintIssue(
                file_path=str(file_path),
                line_number=1,
                column=1,
                rule_id="TOOL-MISSING",
                severity="warning",
                message="mypy command not found, install with 'pip install mypy'",
                fix_suggestion="pip install mypy"
            )]
        except Exception as e:
            logger.error(f"Error running mypy: {e}")
            return [LintIssue(
                file_path=str(file_path),
                line_number=1,
                column=1,
                rule_id="ERROR",
                severity="error",
                message=f"Error running mypy: {e}",
                fix_suggestion=None
            )]

    def _create_summary(self, issues: List[LintIssue]) -> Dict[str, Any]:
        """Create summary of linting results."""
        summary = {
            "total_issues": len(issues),
            "errors": len([i for i in issues if i.severity == "error"]),
            "warnings": len([i for i in issues if i.severity == "warning"]),
            "info": len([i for i in issues if i.severity == "info"]),
            "rules_triggered": list(set(i.rule_id for i in issues))
        }

        return summary


class DatasetLinter:
    """Specialized linting for dataset-related code."""

    def __init__(self):
        self.dataset_patterns = [
            r'\.load_dataset\(',
            r'\.save_dataset\(',
            r'\.process_dataset\(',
            r'ipfs_hash\s*=',
            r'\.pin_to_ipfs\(',
            r'\.get_from_ipfs\('
        ]

    def lint_dataset_code(self, file_path: Path) -> List[LintIssue]:
        """Apply dataset-specific linting rules."""
        issues = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            lines = content.split('\n')

            for i, line in enumerate(lines):
                line_number = i + 1

                # Check for dataset operations without error handling
                if any(re.search(pattern, line) for pattern in self.dataset_patterns):
                    if not self._has_error_handling_nearby(lines, i):
                        issues.append(LintIssue(
                            file_path=str(file_path),
                            line_number=line_number,
                            column=1,
                            rule_id="DS001",
                            severity="warning",
                            message="Dataset operation should include error handling",
                            fix_suggestion="Add try/except block around dataset operations"
                        ))

                # Check for hardcoded IPFS hashes
                if re.search(r'Qm[A-Za-z0-9]{44}|baf[A-Za-z0-9]+', line):
                    issues.append(LintIssue(
                        file_path=str(file_path),
                        line_number=line_number,
                        column=1,
                        rule_id="DS002",
                        severity="info",
                        message="Consider using configuration for IPFS hashes",
                        fix_suggestion="Move IPFS hash to configuration file"
                    ))

        except Exception as e:
            logger.error(f"Error in dataset linting for {file_path}: {e}")

        return issues

    def _has_error_handling_nearby(self, lines: List[str], line_index: int) -> bool:
        """Check if error handling exists near the given line."""
        # Check 5 lines before and after for try/except
        start = max(0, line_index - 5)
        end = min(len(lines), line_index + 5)

        for i in range(start, end):
            if 'try:' in lines[i] or 'except' in lines[i]:
                return True

        return False


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
        self.python_linter = PythonLinter()
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
                result.summary = self.python_linter._create_summary(result.issues)

            if verbose:
                logger.info(f"Linted {file_path}: {result.issues_found} issues found")

            return result

        loop = asyncio.get_event_loop()

        # Process files in smaller batches to avoid overwhelming the system
        batch_size = 10
        all_results = []

        for i in range(0, len(python_files), batch_size):
            batch = python_files[i:i + batch_size]

            with ThreadPoolExecutor(max_workers=4) as executor:
                tasks = [
                    loop.run_in_executor(executor, lint_file_sync, file_path)
                    for file_path in batch
                ]

                batch_results = await asyncio.gather(*tasks)
                all_results.extend(batch_results)

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
        # Check if there's already an event loop running
        try:
            loop = asyncio.get_running_loop()
            # If we get here, there's a running loop, so we need to use a different approach
            import concurrent.futures
            import threading

            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(tool.execute(
                        path=path,
                        patterns=patterns,
                        exclude_patterns=exclude_patterns,
                        fix_issues=fix_issues,
                        include_dataset_rules=include_dataset_rules,
                        dry_run=dry_run,
                        verbose=verbose
                    ))
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result()

        except RuntimeError:
            # No running loop, we can use asyncio.run
            return asyncio.run(tool.execute(
                path=path,
                patterns=patterns,
                exclude_patterns=exclude_patterns,
                fix_issues=fix_issues,
                include_dataset_rules=include_dataset_rules,
                dry_run=dry_run,
                verbose=verbose
            ))
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

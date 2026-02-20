"""
Linting Engine — Core business logic for Python code linting.

This module contains the data structures and linting implementations that are
independent of the MCP layer.  It is imported by ``linting_tools.py``, which
provides the thin MCP wrapper on top.

Separation rationale
--------------------
Keeping core logic here allows:
* Unit-testing the linter without importing MCP or anyio.
* Reuse from other modules or scripts.
* The tool file to remain a thin orchestration wrapper (<150 lines target).
"""

import re
import subprocess
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration Protocol
# ---------------------------------------------------------------------------

class LintingConfigProtocol(Protocol):
    """Structural interface expected from a linting configuration object.

    Any object that provides ``run_flake8`` and ``run_mypy`` boolean attributes
    satisfies this protocol; no explicit subclassing required.
    """

    run_flake8: bool
    run_mypy: bool


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class LintIssue:
    """Represents a single linting issue found in a file."""

    file_path: str
    line_number: int
    column: Optional[int]
    rule_id: str
    severity: str          # 'error' | 'warning' | 'info'
    message: str
    fix_suggestion: Optional[str] = None


@dataclass
class LintResult:
    """Aggregated results of linting one or more files."""

    total_files: int
    issues_found: int
    issues_fixed: int
    files_modified: List[str]
    issues: List[LintIssue]
    summary: Dict[str, Any]


# ---------------------------------------------------------------------------
# PythonLinter
# ---------------------------------------------------------------------------

class PythonLinter:
    """Core Python linting functionality (flake8, mypy, basic fixes).

    This class is intentionally free of MCP / anyio dependencies so it can be
    used from synchronous contexts and tested independently.
    """

    def __init__(self, config: Optional[LintingConfigProtocol] = None) -> None:
        """Initialise the linter.

        Args:
            config: Optional linting configuration object satisfying
                :class:`LintingConfigProtocol`.  When *None* the linter uses
                conservative built-in defaults (no external tools invoked
                unless the corresponding flags are True).
        """
        self.config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lint_file(self, file_path: Path, fix_issues: bool = True,
                  patterns: Optional[List[str]] = None) -> LintResult:
        """Lint a single Python file, optionally applying auto-fixes.

        Args:
            file_path: Path to the ``.py`` file to lint.
            fix_issues: When *True* (default) apply basic formatting fixes
                (trailing whitespace, missing final newline) directly to the
                file on disk.
            patterns: Reserved for future pattern-based filtering; unused.

        Returns:
            A :class:`LintResult` describing every issue found and fixed.
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()

            issues: List[LintIssue] = []
            modified_content = original_content
            files_modified: List[str] = []

            if fix_issues:
                modified_content, fixed_issues = self._apply_basic_fixes(
                    original_content, file_path
                )
                issues.extend(fixed_issues)

                if modified_content != original_content:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(modified_content)
                    files_modified.append(str(file_path))

            issues.extend(self._run_external_linters(file_path))

            return LintResult(
                total_files=1,
                issues_found=len(issues),
                issues_fixed=len([i for i in issues if i.fix_suggestion]),
                files_modified=files_modified,
                issues=issues,
                summary=self._create_summary(issues),
            )

        except (OSError, ValueError) as e:
            logger.error(f"Error linting file {file_path}: {e}")
            return LintResult(
                total_files=1,
                issues_found=0,
                issues_fixed=0,
                files_modified=[],
                issues=[],
                summary={"error": str(e)},
            )

    def create_summary(self, issues: List[LintIssue]) -> Dict[str, Any]:
        """Public alias for :meth:`_create_summary` (for external callers)."""
        return self._create_summary(issues)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_basic_fixes(
        self, content: str, file_path: Path
    ) -> Tuple[str, List[LintIssue]]:
        """Apply whitespace and newline fixes, returning updated content + issues."""
        issues: List[LintIssue] = []
        lines = content.split('\n')
        modified_lines: List[str] = []

        for i, line in enumerate(lines):
            line_number = i + 1

            if line.rstrip() != line:
                issues.append(LintIssue(
                    file_path=str(file_path), line_number=line_number,
                    column=len(line.rstrip()) + 1, rule_id="W291",
                    severity="warning", message="Trailing whitespace",
                    fix_suggestion="Remove trailing whitespace",
                ))
                line = line.rstrip()

            if line.strip() == "" and line != "":
                issues.append(LintIssue(
                    file_path=str(file_path), line_number=line_number,
                    column=1, rule_id="W293", severity="warning",
                    message="Blank line contains whitespace",
                    fix_suggestion="Remove whitespace from blank line",
                ))
                line = ""

            modified_lines.append(line)

        modified_content = '\n'.join(modified_lines)
        if content and not content.endswith('\n'):
            issues.append(LintIssue(
                file_path=str(file_path), line_number=len(lines),
                column=len(lines[-1]) + 1, rule_id="W292",
                severity="warning", message="No newline at end of file",
                fix_suggestion="Add newline at end of file",
            ))
            modified_content += '\n'

        return modified_content, issues

    def _run_external_linters(self, file_path: Path) -> List[LintIssue]:
        """Delegate to flake8 and/or mypy based on configuration."""
        issues: List[LintIssue] = []
        cfg = self.config
        if cfg is not None and getattr(cfg, 'run_flake8', False):
            issues.extend(self._run_flake8(file_path))
        if cfg is not None and getattr(cfg, 'run_mypy', False):
            issues.extend(self._run_mypy(file_path))
        return issues

    def _run_flake8(self, file_path: Path) -> List[LintIssue]:
        """Run flake8 and parse its output into :class:`LintIssue` objects."""
        if importlib.util.find_spec('flake8') is None:
            return [self._missing_tool_issue(file_path, "flake8", "pip install flake8")]

        if not file_path.exists() or not file_path.is_file():
            return []

        try:
            result = subprocess.run(
                ['flake8', '--format=%(path)s:%(row)d:%(col)d: %(code)s %(text)s',
                 str(file_path)],
                capture_output=True, text=True, timeout=30, shell=False,
            )
        except subprocess.TimeoutExpired:
            return [self._timeout_issue(file_path, "flake8")]
        except FileNotFoundError:
            return [self._missing_tool_issue(file_path, "flake8", "pip install flake8")]

        issues: List[LintIssue] = []
        for line in result.stdout.split('\n'):
            if not line.strip():
                continue
            m = re.match(r'([^:]+):(\d+):(\d+):\s+(\w+)\s+(.*)', line)
            if m:
                path, row, col, code, msg = m.groups()
                issues.append(LintIssue(
                    file_path=path, line_number=int(row), column=int(col),
                    rule_id=code,
                    severity="error" if code.startswith('E') else "warning",
                    message=msg,
                ))
        return issues

    def _run_mypy(self, file_path: Path) -> List[LintIssue]:
        """Run mypy and parse its output into :class:`LintIssue` objects."""
        if importlib.util.find_spec('mypy') is None:
            return [self._missing_tool_issue(file_path, "mypy", "pip install mypy")]

        if not file_path.exists() or not file_path.is_file():
            return []

        try:
            result = subprocess.run(
                ['mypy', '--show-column-numbers', str(file_path)],
                capture_output=True, text=True, timeout=30, shell=False,
            )
        except subprocess.TimeoutExpired:
            return [self._timeout_issue(file_path, "mypy")]
        except FileNotFoundError:
            return [self._missing_tool_issue(file_path, "mypy", "pip install mypy")]

        issues: List[LintIssue] = []
        for line in result.stdout.split('\n'):
            if not line.strip() or ':' not in line:
                continue
            m = re.match(r'([^:]+):(\d+):(\d+):\s+(error|warning|note):\s+(.*)', line)
            if m:
                path, row, col, sev, msg = m.groups()
                issues.append(LintIssue(
                    file_path=path, line_number=int(row), column=int(col),
                    rule_id="mypy", severity=sev, message=msg,
                ))
        return issues

    def _create_summary(self, issues: List[LintIssue]) -> Dict[str, Any]:
        return {
            "total_issues": len(issues),
            "errors":   sum(1 for i in issues if i.severity == "error"),
            "warnings": sum(1 for i in issues if i.severity == "warning"),
            "info":     sum(1 for i in issues if i.severity == "info"),
            "rules_triggered": list({i.rule_id for i in issues}),
        }

    @staticmethod
    def _missing_tool_issue(file_path: Path, tool: str, fix: str) -> LintIssue:
        return LintIssue(
            file_path=str(file_path), line_number=1, column=1,
            rule_id="TOOL-MISSING", severity="warning",
            message=f"{tool} is not installed, install with '{fix}'",
            fix_suggestion=fix,
        )

    @staticmethod
    def _timeout_issue(file_path: Path, tool: str) -> LintIssue:
        return LintIssue(
            file_path=str(file_path), line_number=1, column=1,
            rule_id="TIMEOUT", severity="warning",
            message=f"{tool} timed out while processing the file",
        )


# ---------------------------------------------------------------------------
# DatasetLinter
# ---------------------------------------------------------------------------

class DatasetLinter:
    """Specialized linting for dataset-related code patterns.

    Checks for:
    * Dataset operations lacking error handling (DS001).
    * Hard-coded IPFS hashes (DS002).
    """

    # Regex patterns that identify IPFS dataset operations (load, save, process,
    # pin/get) and IPFS hash assignments.  Each match triggers a DS001 check to
    # ensure error handling is present nearby (see lint_dataset_code).
    DATASET_PATTERNS = [
        r'\.load_dataset\(',
        r'\.save_dataset\(',
        r'\.process_dataset\(',
        r'ipfs_hash\s*=',
        r'\.pin_to_ipfs\(',
        r'\.get_from_ipfs\(',
    ]

    def lint_dataset_code(self, file_path: Path) -> List[LintIssue]:
        """Return dataset-specific :class:`LintIssue` objects for *file_path*."""
        issues: List[LintIssue] = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            lines = content.split('\n')
            for i, line in enumerate(lines):
                line_number = i + 1

                if any(re.search(p, line) for p in self.DATASET_PATTERNS):
                    if not self._has_error_handling_nearby(lines, i):
                        issues.append(LintIssue(
                            file_path=str(file_path), line_number=line_number,
                            column=1, rule_id="DS001", severity="warning",
                            message="Dataset operation should include error handling",
                            fix_suggestion="Add try/except block around dataset operations",
                        ))

                if re.search(r'Qm[A-Za-z0-9]{44}|baf[A-Za-z0-9]+', line):
                    issues.append(LintIssue(
                        file_path=str(file_path), line_number=line_number,
                        column=1, rule_id="DS002", severity="info",
                        message="Consider using configuration for IPFS hashes",
                        fix_suggestion="Move IPFS hash to configuration file",
                    ))

        except (OSError, ValueError) as e:
            logger.error(f"Error in dataset linting for {file_path}: {e}")

        return issues

    @staticmethod
    def _has_error_handling_nearby(lines: List[str], line_index: int) -> bool:
        """Return True if try/except appears within ±5 lines of *line_index*."""
        start = max(0, line_index - 5)
        end = min(len(lines), line_index + 6)
        return any('try:' in lines[i] or 'except' in lines[i] for i in range(start, end))

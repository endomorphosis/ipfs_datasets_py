"""
Linting Tools — thin MCP wrapper.

Business logic lives in :mod:`linting_engine`.
This module provides standalone async MCP functions and a backward-compat
``LintingTools`` class shim for any callers using the old class API.
"""

from __future__ import annotations

import logging
import anyio
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from .config import get_config
from .linting_engine import LintIssue, LintResult, PythonLinter, DatasetLinter  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standalone async MCP function  (primary public API)
# ---------------------------------------------------------------------------


async def lint_codebase(
    path: str = ".",
    patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    fix_issues: bool = True,
    include_dataset_rules: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Lint Python codebase with comprehensive quality checks.

    Args:
        path: Target directory or file to lint (default: ``"."``).
        patterns: File glob patterns to include.
        exclude_patterns: Glob patterns to exclude.
        fix_issues: Apply automatic fixes where possible.
        include_dataset_rules: Include dataset-specific linting rules.
        dry_run: Report only; do not write changes.
        verbose: Log per-file details.

    Returns:
        Dictionary containing linting results and statistics.
    """
    try:
        cfg = get_config().linting_tools
        target = Path(path)

        if not target.exists():
            return {
                "success": False,
                "error":   "path_not_found",
                "message": f"Path not found: {path}",
            }

        patterns         = patterns         or cfg.file_patterns
        exclude_patterns = exclude_patterns or cfg.exclude_dirs
        if dry_run:
            fix_issues = False

        # Discover files
        python_linter  = PythonLinter(config=cfg)
        dataset_linter = DatasetLinter()

        if target.is_file() and target.suffix == ".py":
            python_files = [target]
        else:
            python_files = sorted(
                fp
                for pat in patterns
                for fp in target.glob(pat)
                if fp.is_file()
                and not any(ex in str(fp) or fp.match(ex) for ex in exclude_patterns)
            )

        if not python_files:
            return {
                "success": False,
                "error":   "no_files",
                "message": "No Python files found to lint",
            }

        # Lint files (offload sync linting to a thread)
        def _lint_file(fp: Path) -> LintResult:
            result = python_linter.lint_file(fp, fix_issues)
            if include_dataset_rules:
                extra = dataset_linter.lint_dataset_code(fp)
                result.issues.extend(extra)
                result.issues_found = len(result.issues)
                result.summary = python_linter.create_summary(result.issues)
            if verbose:
                logger.info("Linted %s: %d issues", fp, result.issues_found)
            return result

        lint_results: List[LintResult] = []
        batch_size = 10
        for i in range(0, len(python_files), batch_size):
            batch   = python_files[i:i + batch_size]
            results: List[Optional[LintResult]] = [None] * len(batch)
            async with anyio.create_task_group() as tg:
                for idx, fp in enumerate(batch):
                    async def _run(i: int = idx, fp: Path = fp) -> None:
                        results[i] = await anyio.to_thread.run_sync(_lint_file, fp)
                    tg.start_soon(_run)
            lint_results.extend(r for r in results if r is not None)

        # Aggregate
        total_issues = sum(r.issues_found  for r in lint_results)
        total_fixes  = sum(r.issues_fixed  for r in lint_results)
        all_issues   = [issue for r in lint_results for issue in r.issues]

        severity_counts: Dict[str, int] = {"error": 0, "warning": 0, "info": 0}
        rule_counts:     Dict[str, int] = {}
        modified_files:  List[str]      = []
        for r in lint_results:
            modified_files.extend(str(f) for f in r.files_modified)
            for issue in r.issues:
                sev = getattr(issue, "severity", "warning")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1
                rule = getattr(issue, "rule_id", "unknown")
                rule_counts[rule]    = rule_counts.get(rule, 0) + 1

        return {
            "success":         True,
            "status":          "success",
            "path":            str(target),
            "files_processed": len(lint_results),
            "total_issues":    total_issues,
            "total_fixes":     total_fixes,
            "severity_counts": severity_counts,
            "top_rules":       sorted(rule_counts.items(), key=lambda x: -x[1])[:10],
            "modified_files":  modified_files,
            "fix_issues":      fix_issues,
            "dry_run":         dry_run,
            "include_dataset_rules": include_dataset_rules,
            "timestamp":       datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.error("Linting failed: %s", exc)
        return {
            "success": False,
            "error":   "linting_failed",
            "message": f"Linting failed: {exc}",
        }


# Main MCP entry-point (legacy name kept for backward compat)
async def linting_tools(
    path: str = ".",
    file_patterns: Optional[List[str]] = None,
    auto_fix: bool = False,
    exclude_dirs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """MCP entry-point for comprehensive Python code linting."""
    return await lint_codebase(
        path=path,
        patterns=file_patterns or ["**/*.py"],
        fix_issues=auto_fix,
        exclude_patterns=exclude_dirs or [".venv", ".git", "__pycache__"],
    )


# Sync convenience wrapper (preserved for non-async callers)
def lint_python_codebase(
    path: str = ".",
    patterns: Optional[List[str]] = None,
    exclude_patterns: Optional[List[str]] = None,
    fix_issues: bool = True,
    include_dataset_rules: bool = True,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Synchronous convenience wrapper around :func:`lint_codebase`."""
    try:
        return anyio.run(
            lint_codebase,
            path, patterns, exclude_patterns, fix_issues,
            include_dataset_rules, dry_run, verbose,
        )
    except Exception as exc:
        return {
            "success": False,
            "error":   "execution_error",
            "message": f"Failed to execute linting tool: {exc}",
        }


# ---------------------------------------------------------------------------
# Backward-compat class shim (thin wrapper around lint_codebase)
# ---------------------------------------------------------------------------

class LintingTools:
    """Backward-compat shim for callers that instantiate LintingTools()."""

    def __init__(self, name: str = "LintingTools", description: str = "", **_kw):
        self.name        = name
        self.description = description

    async def execute(self, **kwargs) -> Dict[str, Any]:
        return await lint_codebase(
            path                 = kwargs.get("path", "."),
            patterns             = kwargs.get("file_patterns", kwargs.get("patterns")),
            fix_issues           = kwargs.get("auto_fix", kwargs.get("fix_issues", False)),
            exclude_patterns     = kwargs.get("exclude_dirs", kwargs.get("exclude_patterns")),
            include_dataset_rules= kwargs.get("include_dataset_rules", True),
            dry_run              = kwargs.get("dry_run", False),
            verbose              = kwargs.get("verbose", False),
        )

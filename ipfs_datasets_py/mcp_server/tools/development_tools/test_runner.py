"""
Test Runner Tool — thin MCP wrapper.

Business logic lives in :mod:`ipfs_datasets_py.testing`.
This module provides a standalone async MCP function and a backward-compat
``TestRunner`` class shim for any callers using the old class API.
"""

from __future__ import annotations

import logging
import anyio
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime

from .config import get_config
from ipfs_datasets_py.testing import (  # noqa: F401
    TestResult,
    TestSuiteResult,
    TestRunSummary,
    TestExecutor,
    DatasetTestRunner,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Standalone async MCP function  (primary public API)
# ---------------------------------------------------------------------------


async def run_tests(
    path: str = ".",
    run_unit_tests: bool = True,
    run_type_check: bool = True,
    run_linting: bool = True,
    run_dataset_tests: bool = True,
    test_framework: str = "pytest",
    coverage: bool = True,
    verbose: bool = False,
    save_results: bool = True,
    output_formats: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run comprehensive test suite.

    Args:
        path: Root path to test (default: ``"."``).
        run_unit_tests: Include unit tests.
        run_type_check: Include mypy type checking.
        run_linting: Include linting.
        run_dataset_tests: Include dataset-specific tests.
        test_framework: ``"pytest"`` or ``"unittest"``.
        coverage: Measure code coverage.
        verbose: Print detailed output.
        save_results: Write results to disk.
        output_formats: Report formats (e.g. ``["json", "html"]``).

    Returns:
        Dictionary containing test results and summary statistics.
    """
    try:
        cfg     = get_config().test_runner
        target  = Path(path)

        if not target.exists():
            return {
                "success": False,
                "error":   "path_not_found",
                "message": f"Path not found: {path}",
            }

        timeout = getattr(cfg, "timeout_seconds", 300)
        executor        = TestExecutor(timeout_seconds=timeout)
        dataset_runner  = DatasetTestRunner(timeout_seconds=timeout)

        suite_results: Dict[str, Any] = {}

        # Run each suite in a thread to avoid blocking the event loop
        async def _run_suite(suite_type: str, runner_fn) -> None:
            def _sync():
                return runner_fn(str(target))
            try:
                suite_results[suite_type] = await anyio.to_thread.run_sync(_sync)
            except Exception as exc:
                suite_results[suite_type] = {"success": False, "error": str(exc)}

        async with anyio.create_task_group() as tg:
            if run_unit_tests:
                tg.start_soon(_run_suite, "unit_tests",    executor.run_pytest)
            if run_dataset_tests:
                tg.start_soon(_run_suite, "dataset_tests", dataset_runner.run_dataset_integrity_tests)

        # Aggregate
        total_passed = total_failed = total_skipped = 0
        for suite_result in suite_results.values():
            if isinstance(suite_result, dict):
                total_passed  += suite_result.get("passed",  0)
                total_failed  += suite_result.get("failed",  0)
                total_skipped += suite_result.get("skipped", 0)

        return {
            "success":       total_failed == 0,
            "status":        "success" if total_failed == 0 else "failure",
            "path":          str(target),
            "suite_results": suite_results,
            "summary": {
                "total_passed":  total_passed,
                "total_failed":  total_failed,
                "total_skipped": total_skipped,
            },
            "run_config": {
                "run_unit_tests":    run_unit_tests,
                "run_type_check":    run_type_check,
                "run_linting":       run_linting,
                "run_dataset_tests": run_dataset_tests,
                "test_framework":    test_framework,
                "coverage":          coverage,
            },
            "timestamp": datetime.now().isoformat(),
        }

    except Exception as exc:
        logger.error("Test runner failed: %s", exc)
        return {
            "success": False,
            "error":   "runner_failed",
            "message": f"Test runner failed: {exc}",
        }


# Legacy MCP entry-point name
async def test_runner(**kwargs) -> Dict[str, Any]:
    """MCP entry-point alias for :func:`run_tests`."""
    return await run_tests(
        path              = kwargs.get("path", "."),
        run_unit_tests    = kwargs.get("run_unit_tests", True),
        run_type_check    = kwargs.get("run_type_check", True),
        run_linting       = kwargs.get("run_linting", True),
        run_dataset_tests = kwargs.get("run_dataset_tests", True),
        test_framework    = kwargs.get("test_framework", "pytest"),
        coverage          = kwargs.get("coverage", True),
        verbose           = kwargs.get("verbose", False),
        save_results      = kwargs.get("save_results", True),
        output_formats    = kwargs.get("output_formats"),
    )


# Sync convenience wrapper
def run_comprehensive_tests(
    path: str = ".",
    run_unit_tests: bool = True,
    run_type_check: bool = True,
    run_linting: bool = True,
    run_dataset_tests: bool = True,
    test_framework: str = "pytest",
    coverage: bool = True,
    verbose: bool = False,
    save_results: bool = True,
    output_formats: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Synchronous convenience wrapper around :func:`run_tests`."""
    try:
        return anyio.run(
            run_tests,
            path, run_unit_tests, run_type_check, run_linting,
            run_dataset_tests, test_framework, coverage,
            verbose, save_results, output_formats,
        )
    except Exception as exc:
        return {
            "success": False,
            "error":   "execution_error",
            "message": f"Failed to execute test runner: {exc}",
            "metadata": {"tool": "run_comprehensive_tests", "timestamp": datetime.now().isoformat()},
        }


def create_test_runner(**kwargs):
    """Backward-compat factory; returns a :class:`TestRunner` shim."""
    runner = TestRunner()
    runner._params = kwargs
    return runner


# ---------------------------------------------------------------------------
# Backward-compat class shim  (thin wrapper around run_tests)
# ---------------------------------------------------------------------------

class TestRunner:
    """Backward-compat shim for callers that instantiate TestRunner()."""

    def __init__(self):
        self._params: Dict[str, Any] = {}

    async def execute(self, **kwargs) -> Dict[str, Any]:
        merged = {**self._params, **kwargs}
        return await run_tests(
            path              = merged.get("path", "."),
            run_unit_tests    = merged.get("run_unit_tests", True),
            run_type_check    = merged.get("run_type_check", True),
            run_linting       = merged.get("run_linting", True),
            run_dataset_tests = merged.get("run_dataset_tests", True),
            test_framework    = merged.get("test_framework", "pytest"),
            coverage          = merged.get("coverage", True),
            verbose           = merged.get("verbose", False),
            save_results      = merged.get("save_results", True),
            output_formats    = merged.get("output_formats"),
        )

"""
Test Runner Tool - Thin MCP Wrapper

Comprehensive test execution and results management for Python projects.
This is a thin wrapper around core testing functionality.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import asdict
import logging
import anyio
from datetime import datetime

from .base_tool import BaseDevelopmentTool
from .config import get_config
from ipfs_datasets_py.testing import (
    TestResult,
    TestSuiteResult,
    TestRunSummary,
    TestExecutor,
    DatasetTestRunner
)

logger = logging.getLogger(__name__)


class TestRunner(BaseDevelopmentTool):
    """
    Thin MCP wrapper for comprehensive test runner.
    Delegates to core testing functionality.
    """

    def __init__(self):
        super().__init__(
            name="test_runner",
            description="Comprehensive test execution and results management",
            category="development"
        )
        self.config = get_config().test_runner
        self.executor = TestExecutor(timeout_seconds=self.config.timeout_seconds)
        self.dataset_runner = DatasetTestRunner(timeout_seconds=self.config.timeout_seconds)
        self.params = {}

    async def _execute_core(self, **kwargs) -> Dict[str, Any]:
        """Core execution logic - delegates to run_comprehensive_tests."""
        merged_kwargs = self.params.copy() if hasattr(self, 'params') else {}
        merged_kwargs.update(kwargs)
        return await self.run_comprehensive_tests(**merged_kwargs)

    async def run_comprehensive_tests(self,
                                    path: str = ".",
                                    run_unit_tests: bool = True,
                                    run_type_check: bool = True,
                                    run_linting: bool = True,
                                    run_dataset_tests: bool = True,
                                    test_framework: str = "pytest",
                                    coverage: bool = True,
                                    verbose: bool = False,
                                    save_results: bool = True,
                                    output_formats: Optional[List[str]] = None) -> Dict[str, Any]:
        """Run comprehensive test suite with multiple checkers."""
        try:
            path = self._validate_path(path)
            if output_formats is None:
                output_formats = ['json']

            start_time = time.time()
            timestamp = datetime.now().isoformat()

            suites = []
            tasks = []

            if run_unit_tests:
                if test_framework == "pytest":
                    tasks.append(self._run_test_suite_async("pytest", path, coverage, verbose))
                else:
                    tasks.append(self._run_test_suite_async("unittest", path, False, verbose))

            if run_type_check:
                tasks.append(self._run_test_suite_async("mypy", path))

            if run_linting:
                tasks.append(self._run_test_suite_async("flake8", path))

            if run_dataset_tests:
                tasks.append(self._run_test_suite_async("dataset_tests", path))

            if tasks:
                suites = [None] * len(tasks)

                async def _run_one(idx: int, awaitable) -> None:
                    suites[idx] = await awaitable

                async with anyio.create_task_group() as tg:
                    for idx, awaitable in enumerate(tasks):
                        tg.start_soon(_run_one, idx, awaitable)

                suites = [s for s in suites if s is not None]

            total_duration = time.time() - start_time

            total_suites = len(suites)
            suites_passed = len([s for s in suites if s.status == "passed"])
            suites_failed = total_suites - suites_passed
            overall_status = "passed" if suites_failed == 0 else "failed"

            summary = TestRunSummary(
                timestamp=timestamp,
                project_path=str(path),
                total_suites=total_suites,
                suites_passed=suites_passed,
                suites_failed=suites_failed,
                total_duration=total_duration,
                overall_status=overall_status,
                suites=suites
            )

            saved_files = []
            if save_results:
                saved_files = await self._save_test_results(summary, path, output_formats)

            await self._audit_log("tests.executed", {
                "path": str(path),
                "total_suites": total_suites,
                "suites_passed": suites_passed,
                "suites_failed": suites_failed,
                "overall_status": overall_status,
                "duration": total_duration
            })

            result = asdict(summary)
            result["saved_files"] = saved_files

            return self._create_success_result(result)

        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return self._create_error_result(f"Test execution failed: {e}")

    async def _run_test_suite_async(self, suite_type: str, path: Path,
                                   coverage: bool = False, verbose: bool = False) -> TestSuiteResult:
        """Run a test suite asynchronously - delegates to core executors."""
        def run_suite():
            if suite_type == "pytest":
                return self.executor.run_pytest(path, coverage, verbose)
            elif suite_type == "unittest":
                return self.executor.run_unittest(path, verbose)
            elif suite_type == "mypy":
                return self.executor.run_mypy(path)
            elif suite_type == "flake8":
                return self.executor.run_flake8(path)
            elif suite_type == "dataset_tests":
                return self.dataset_runner.run_dataset_integrity_tests(path)
            else:
                raise ValueError(f"Unknown test suite type: {suite_type}")

        return await anyio.to_thread.run_sync(run_suite)

    async def _save_test_results(self, summary: TestRunSummary,
                               path: Path, formats: List[str]) -> List[str]:
        """Save test results in specified formats."""
        saved_files = []
        results_dir = path / "test_results"
        results_dir.mkdir(exist_ok=True)

        timestamp = summary.timestamp.replace(":", "-").replace(".", "-")

        for format_type in formats:
            if format_type == "json":
                json_file = results_dir / f"test_results_{timestamp}.json"
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(asdict(summary), f, indent=2)
                saved_files.append(str(json_file))

            elif format_type == "markdown":
                md_file = results_dir / f"test_results_{timestamp}.md"
                md_content = self._generate_markdown_report(summary)
                with open(md_file, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                saved_files.append(str(md_file))

        return saved_files

    def _generate_markdown_report(self, summary: TestRunSummary) -> str:
        """Generate markdown test report."""
        lines = [
            f"# Test Results Report",
            f"",
            f"**Generated:** {summary.timestamp}",
            f"**Project:** {summary.project_path}",
            f"**Overall Status:** {'✅ PASSED' if summary.overall_status == 'passed' else '❌ FAILED'}",
            f"**Duration:** {summary.total_duration:.2f}s",
            f"",
            f"## Summary",
            f"",
            f"- **Total Suites:** {summary.total_suites}",
            f"- **Passed:** {summary.suites_passed}",
            f"- **Failed:** {summary.suites_failed}",
            f"",
            f"## Test Suites",
            f""
        ]

        for suite in summary.suites:
            status_icon = "✅" if suite.status == "passed" else "❌"
            lines.extend([
                f"### {status_icon} {suite.suite_name} ({suite.tool})",
                f"",
                f"- **Status:** {suite.status}",
                f"- **Duration:** {suite.duration:.2f}s",
                f"- **Total Tests:** {suite.total_tests}",
                f"- **Passed:** {suite.passed}",
                f"- **Failed:** {suite.failed}",
                f"- **Skipped:** {suite.skipped}",
                f"- **Errors:** {suite.errors}",
                f""
            ])

            if suite.output and len(suite.output.strip()) > 0:
                lines.extend([
                    f"#### Output",
                    f"```",
                    suite.output[:1000] + ("..." if len(suite.output) > 1000 else ""),
                    f"```",
                    f""
                ])

        return '\n'.join(lines)


# MCP Wrapper Functions

def create_test_runner(path: str = ".",
                     run_unit_tests: bool = True,
                     run_type_check: bool = True,
                     run_linting: bool = True,
                     run_dataset_tests: bool = True,
                     test_framework: str = "pytest",
                     coverage: bool = True,
                     verbose: bool = False,
                     save_results: bool = True,
                     output_formats: Optional[List[str]] = None) -> BaseDevelopmentTool:
    """Create a properly configured TestRunner instance."""
    runner = TestRunner()
    runner.params = {
        "path": path,
        "run_unit_tests": run_unit_tests,
        "run_type_check": run_type_check,
        "run_linting": run_linting,
        "run_dataset_tests": run_dataset_tests, 
        "test_framework": test_framework,
        "coverage": coverage,
        "verbose": verbose,
        "save_results": save_results,
        "output_formats": output_formats
    }
    return runner


def run_comprehensive_tests(path: str = ".",
                           run_unit_tests: bool = True,
                           run_type_check: bool = True,
                           run_linting: bool = True,
                           run_dataset_tests: bool = True,
                           test_framework: str = "pytest",
                           coverage: bool = True,
                           verbose: bool = False,
                           save_results: bool = True,
                           output_formats: Optional[List[str]] = None) -> Dict[str, Any]:
    """Run comprehensive test suite including unit tests, type checking, linting, and dataset tests."""
    test_runner = create_test_runner(
        path=path,
        run_unit_tests=run_unit_tests,
        run_type_check=run_type_check,
        run_linting=run_linting,
        run_dataset_tests=run_dataset_tests,
        test_framework=test_framework,
        coverage=coverage,
        verbose=verbose,
        save_results=save_results,
        output_formats=output_formats
    )
    
    try:
        try:
            import sniffio
            sniffio.current_async_library()
            in_async = True
        except (ImportError, ModuleNotFoundError, AttributeError):
            in_async = False

        if in_async:
            from concurrent.futures import ThreadPoolExecutor

            def run_in_thread():
                return anyio.run(test_runner.execute)

            with ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result()

        return anyio.run(test_runner.execute)
    except Exception as e:
        return {
            "success": False,
            "error": "execution_error",
            "message": f"Failed to execute test runner: {e}",
            "metadata": {
                "tool": "run_comprehensive_tests",
                "timestamp": datetime.now().isoformat()
            }
        }


async def test_runner(**kwargs):
    """MCP tool function for comprehensive test runner."""
    try:
        path = kwargs.get('path', '.')
        verbose = kwargs.get('verbose', False)
        coverage = kwargs.get('coverage', True)
        
        runner = TestRunner()
        
        result = await runner.execute(
            path=path,
            verbose=verbose,
            coverage=coverage,
            run_unit_tests=True,
            run_type_check=True,
            run_linting=True,
            run_dataset_tests=True
        )
        
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Test runner failed: {str(e)}",
            "tool_type": "development_tool"
        }


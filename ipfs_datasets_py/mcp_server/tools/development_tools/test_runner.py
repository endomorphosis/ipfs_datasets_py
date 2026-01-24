"""
Test Runner Tool

Comprehensive test execution and results management for Python projects.
Migrated from claudes_toolbox with enhanced dataset testing and IPFS integration.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from dataclasses import dataclass, asdict
import logging
import anyio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .base_tool import BaseDevelopmentTool, development_tool_mcp_wrapper
from .config import get_config

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Individual test result."""
    name: str
    status: str  # 'passed', 'failed', 'skipped', 'error'
    duration: float
    message: Optional[str] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None


@dataclass
class TestSuiteResult:
    """Results from a test suite run."""
    suite_name: str
    tool: str  # 'pytest', 'unittest', 'mypy', 'flake8', etc.
    status: str  # 'passed', 'failed', 'error'
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    duration: float
    coverage_percentage: Optional[float] = None
    tests: List[TestResult] = None
    output: str = ""

    def __post_init__(self):
        if self.tests is None:
            self.tests = []


@dataclass
class TestRunSummary:
    """Complete test run summary."""
    timestamp: str
    project_path: str
    total_suites: int
    suites_passed: int
    suites_failed: int
    total_duration: float
    overall_status: str
    suites: List[TestSuiteResult]
    coverage_report: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.suites is None:
            self.suites = []


class TestExecutor:
    """Core test execution functionality."""

    def __init__(self):
        self.config = get_config().test_runner

    def run_pytest(self, path: Path, coverage: bool = True,
                   verbose: bool = False) -> TestSuiteResult:
        """Run pytest test suite."""
        start_time = time.time()

        cmd = ['python', '-m', 'pytest', str(path)]

        if coverage:
            cmd.extend(['--cov', str(path), '--cov-report', 'json'])

        if verbose:
            cmd.append('-v')

        # Add JSON report for parsing
        json_report_path = tempfile.mktemp(suffix='.json')
        cmd.extend(['--json-report', f'--json-report-file={json_report_path}'])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=path,
                timeout=self.config.timeout_seconds
            )

            duration = time.time() - start_time

            # Parse JSON report if available
            tests = []
            total_tests = 0
            passed = failed = skipped = errors = 0

            if os.path.exists(json_report_path):
                try:
                    with open(json_report_path, 'r') as f:
                        report_data = json.load(f)

                    # Extract test results
                    for test in report_data.get('tests', []):
                        test_result = TestResult(
                            name=test.get('name', ''),
                            status=test.get('outcome', 'unknown'),
                            duration=test.get('duration', 0.0),
                            message=test.get('message'),
                            file_path=test.get('file'),
                            line_number=test.get('line')
                        )
                        tests.append(test_result)

                        if test_result.status == 'passed':
                            passed += 1
                        elif test_result.status == 'failed':
                            failed += 1
                        elif test_result.status == 'skipped':
                            skipped += 1
                        else:
                            errors += 1

                    total_tests = len(tests)

                except Exception as e:
                    logger.warning(f"Failed to parse pytest JSON report: {e}")

                finally:
                    # Clean up temp file
                    try:
                        os.unlink(json_report_path)
                    except:
                        pass

            # Fallback to parsing stdout if JSON report failed
            if total_tests == 0:
                total_tests, passed, failed, skipped, errors = self._parse_pytest_output(result.stdout)

            status = "passed" if result.returncode == 0 else "failed"

            return TestSuiteResult(
                suite_name="pytest",
                tool="pytest",
                status=status,
                total_tests=total_tests,
                passed=passed,
                failed=failed,
                skipped=skipped,
                errors=errors,
                duration=duration,
                tests=tests,
                output=result.stdout + result.stderr
            )

        except subprocess.TimeoutExpired:
            return TestSuiteResult(
                suite_name="pytest",
                tool="pytest",
                status="error",
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output="Test execution timed out"
            )
        except Exception as e:
            return TestSuiteResult(
                suite_name="pytest",
                tool="pytest",
                status="error",
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output=f"Error running pytest: {e}"
            )

    def run_unittest(self, path: Path, verbose: bool = False) -> TestSuiteResult:
        """Run unittest test suite."""
        start_time = time.time()

        cmd = ['python', '-m', 'unittest', 'discover']
        if verbose:
            cmd.append('-v')

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=path,
                timeout=self.config.timeout_seconds
            )

            duration = time.time() - start_time

            # Parse unittest output
            total_tests, passed, failed, skipped, errors = self._parse_unittest_output(result.stderr)

            status = "passed" if result.returncode == 0 else "failed"

            return TestSuiteResult(
                suite_name="unittest",
                tool="unittest",
                status=status,
                total_tests=total_tests,
                passed=passed,
                failed=failed,
                skipped=skipped,
                errors=errors,
                duration=duration,
                output=result.stdout + result.stderr
            )

        except subprocess.TimeoutExpired:
            return TestSuiteResult(
                suite_name="unittest",
                tool="unittest",
                status="error",
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output="Test execution timed out"
            )
        except Exception as e:
            return TestSuiteResult(
                suite_name="unittest",
                tool="unittest",
                status="error",
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output=f"Error running unittest: {e}"
            )

    def run_mypy(self, path: Path) -> TestSuiteResult:
        """Run mypy type checking."""
        start_time = time.time()

        cmd = ['python', '-m', 'mypy', str(path)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds
            )

            duration = time.time() - start_time

            # Count errors and warnings in mypy output
            errors = warnings = 0
            for line in result.stdout.split('\n'):
                if ': error:' in line:
                    errors += 1
                elif ': warning:' in line:
                    warnings += 1

            total_checks = errors + warnings
            passed = 0 if errors > 0 else 1

            status = "passed" if result.returncode == 0 else "failed"

            return TestSuiteResult(
                suite_name="mypy",
                tool="mypy",
                status=status,
                total_tests=max(1, total_checks),
                passed=passed,
                failed=errors,
                skipped=0,
                errors=warnings,
                duration=duration,
                output=result.stdout + result.stderr
            )

        except subprocess.TimeoutExpired:
            return TestSuiteResult(
                suite_name="mypy",
                tool="mypy",
                status="error",
                total_tests=1,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output="Type checking timed out"
            )
        except Exception as e:
            return TestSuiteResult(
                suite_name="mypy",
                tool="mypy",
                status="error",
                total_tests=1,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output=f"Error running mypy: {e}"
            )

    def run_flake8(self, path: Path) -> TestSuiteResult:
        """Run flake8 linting."""
        start_time = time.time()

        cmd = ['python', '-m', 'flake8', str(path)]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds
            )

            duration = time.time() - start_time

            # Count violations
            violations = len([line for line in result.stdout.split('\n') if line.strip()])

            status = "passed" if result.returncode == 0 else "failed"
            passed = 1 if violations == 0 else 0
            failed = 1 if violations > 0 else 0

            return TestSuiteResult(
                suite_name="flake8",
                tool="flake8",
                status=status,
                total_tests=max(1, violations),
                passed=passed,
                failed=failed,
                skipped=0,
                errors=0,
                duration=duration,
                output=result.stdout + result.stderr
            )

        except subprocess.TimeoutExpired:
            return TestSuiteResult(
                suite_name="flake8",
                tool="flake8",
                status="error",
                total_tests=1,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output="Linting timed out"
            )
        except Exception as e:
            return TestSuiteResult(
                suite_name="flake8",
                tool="flake8",
                status="error",
                total_tests=1,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output=f"Error running flake8: {e}"
            )

    def _parse_pytest_output(self, output: str) -> Tuple[int, int, int, int, int]:
        """Parse pytest output for test counts."""
        # Look for pattern like "5 passed, 2 failed, 1 skipped"
        import re

        total = passed = failed = skipped = errors = 0

        # Try to find the summary line
        for line in output.split('\n'):
            if 'passed' in line or 'failed' in line:
                # Extract numbers
                passed_match = re.search(r'(\d+) passed', line)
                failed_match = re.search(r'(\d+) failed', line)
                skipped_match = re.search(r'(\d+) skipped', line)
                error_match = re.search(r'(\d+) error', line)

                if passed_match:
                    passed = int(passed_match.group(1))
                if failed_match:
                    failed = int(failed_match.group(1))
                if skipped_match:
                    skipped = int(skipped_match.group(1))
                if error_match:
                    errors = int(error_match.group(1))

                total = passed + failed + skipped + errors
                break

        return total, passed, failed, skipped, errors

    def _parse_unittest_output(self, output: str) -> Tuple[int, int, int, int, int]:
        """Parse unittest output for test counts."""
        import re

        total = passed = failed = skipped = errors = 0

        # Look for pattern like "Ran 10 tests in 0.123s"
        ran_match = re.search(r'Ran (\d+) tests?', output)
        if ran_match:
            total = int(ran_match.group(1))

        # Count failures and errors
        if 'FAILED' in output:
            # Look for pattern like "FAILED (failures=2, errors=1)"
            failed_match = re.search(r'failures=(\d+)', output)
            error_match = re.search(r'errors=(\d+)', output)

            if failed_match:
                failed = int(failed_match.group(1))
            if error_match:
                errors = int(error_match.group(1))

        passed = total - failed - errors - skipped

        return total, passed, failed, skipped, errors


class DatasetTestRunner:
    """Specialized test runner for dataset-related functionality."""

    def __init__(self):
        self.config = get_config().test_runner

    def run_dataset_integrity_tests(self, path: Path) -> TestSuiteResult:
        """Run dataset integrity and validation tests."""
        start_time = time.time()

        try:
            # Look for dataset test files
            dataset_test_files = list(path.glob("**/test*dataset*.py")) + \
                               list(path.glob("**/test*ipfs*.py"))

            if not dataset_test_files:
                return TestSuiteResult(
                    suite_name="dataset_integrity",
                    tool="dataset_tests",
                    status="skipped",
                    total_tests=0,
                    passed=0,
                    failed=0,
                    skipped=1,
                    errors=0,
                    duration=time.time() - start_time,
                    output="No dataset test files found"
                )

            # Run dataset tests with pytest
            cmd = ['python', '-m', 'pytest', '-v'] + [str(f) for f in dataset_test_files]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=path,
                timeout=self.config.timeout_seconds
            )

            duration = time.time() - start_time

            # Parse results
            total_tests, passed, failed, skipped, errors = self._parse_dataset_test_output(result.stdout)

            status = "passed" if result.returncode == 0 else "failed"

            return TestSuiteResult(
                suite_name="dataset_integrity",
                tool="dataset_tests",
                status=status,
                total_tests=total_tests,
                passed=passed,
                failed=failed,
                skipped=skipped,
                errors=errors,
                duration=duration,
                output=result.stdout + result.stderr
            )

        except subprocess.TimeoutExpired:
            return TestSuiteResult(
                suite_name="dataset_integrity",
                tool="dataset_tests",
                status="error",
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output="Dataset tests timed out"
            )
        except Exception as e:
            return TestSuiteResult(
                suite_name="dataset_integrity",
                tool="dataset_tests",
                status="error",
                total_tests=0,
                passed=0,
                failed=0,
                skipped=0,
                errors=1,
                duration=time.time() - start_time,
                output=f"Error running dataset tests: {e}"
            )

    def _parse_dataset_test_output(self, output: str) -> Tuple[int, int, int, int, int]:
        """Parse dataset test output."""
        # Similar to pytest parsing
        import re

        total = passed = failed = skipped = errors = 0

        for line in output.split('\n'):
            if 'passed' in line or 'failed' in line:
                passed_match = re.search(r'(\d+) passed', line)
                failed_match = re.search(r'(\d+) failed', line)
                skipped_match = re.search(r'(\d+) skipped', line)
                error_match = re.search(r'(\d+) error', line)

                if passed_match:
                    passed = int(passed_match.group(1))
                if failed_match:
                    failed = int(failed_match.group(1))
                if skipped_match:
                    skipped = int(skipped_match.group(1))
                if error_match:
                    errors = int(error_match.group(1))

                total = passed + failed + skipped + errors
                break

        return total, passed, failed, skipped, errors


class TestRunner(BaseDevelopmentTool):
    """
    Comprehensive test runner for Python projects.

    Executes unit tests, type checking, linting, and dataset integrity tests
    with detailed reporting and results export.
    """

    def __init__(self):
        super().__init__(
            name="test_runner",
            description="Comprehensive test execution and results management",
            category="development"
        )
        self.config = get_config().test_runner
        self.executor = TestExecutor()
        self.dataset_runner = DatasetTestRunner()
        self.params = {}

    async def _execute_core(self, **kwargs) -> Dict[str, Any]:
        """
        Core execution logic for the test runner.

        Args:
            **kwargs: Tool-specific parameters forwarded to run_comprehensive_tests

        Returns:
            Tool execution result
        """
        # Merge kwargs with stored params if any
        merged_kwargs = self.params.copy() if hasattr(self, 'params') else {}
        merged_kwargs.update(kwargs)
            
        # Execute the test run and return the results directly
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
        """
        Run comprehensive test suite with multiple checkers.

        Args:
            path: Path to the project directory (default: ".")
            run_unit_tests: Run unit tests (default: True)
            run_type_check: Run mypy type checking (default: True)
            run_linting: Run flake8 linting (default: True)
            run_dataset_tests: Run dataset integrity tests (default: True)
            test_framework: Testing framework to use - 'pytest' or 'unittest' (default: "pytest")
            coverage: Generate coverage report (default: True)
            verbose: Enable verbose output (default: False)
            save_results: Save results to files (default: True)
            output_formats: Output formats for results - ['json', 'markdown'] (default: ['json'])

        Returns:
            Dictionary containing comprehensive test results and statistics
        """
        try:
            # Validate inputs
            path = self._validate_path(path)

            if output_formats is None:
                output_formats = ['json']

            start_time = time.time()
            timestamp = datetime.now().isoformat()

            # Initialize results
            suites = []

            # Run different test suites in parallel
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

            # Execute all test suites
            if tasks:
                suites = await asyncio.gather(*tasks)

            total_duration = time.time() - start_time

            # Calculate summary statistics
            total_suites = len(suites)
            suites_passed = len([s for s in suites if s.status == "passed"])
            suites_failed = total_suites - suites_passed
            overall_status = "passed" if suites_failed == 0 else "failed"

            # Create test run summary
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

            # Save results if requested
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

            # Convert to serializable format
            result = asdict(summary)
            result["saved_files"] = saved_files

            return self._create_success_result(result)

        except Exception as e:
            logger.error(f"Test execution failed: {e}")
            return self._create_error_result(f"Test execution failed: {e}")

    async def _run_test_suite_async(self, suite_type: str, path: Path,
                                   coverage: bool = False, verbose: bool = False) -> TestSuiteResult:
        """Run a test suite asynchronously."""
        loop = asyncio.get_event_loop()

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

        return await loop.run_in_executor(None, run_suite)

    async def _save_test_results(self, summary: TestRunSummary,
                               path: Path, formats: List[str]) -> List[str]:
        """Save test results in specified formats."""
        saved_files = []

        # Create results directory
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


# Create a function that returns the runner instance without decorator first
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
    """
    Create a properly configured TestRunner instance.
    """
    # Create a TestRunner instance
    runner = TestRunner()
    
    # Store parameters for later execution
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
    """
    Run comprehensive test suite including unit tests, type checking, linting, and dataset tests.

    Args:
        path: Path to the project directory (default: ".")
        run_unit_tests: Run unit tests (default: True)
        run_type_check: Run mypy type checking (default: True)
        run_linting: Run flake8 linting (default: True)
        run_dataset_tests: Run dataset integrity tests (default: True)
        test_framework: Testing framework - 'pytest' or 'unittest' (default: "pytest")
        coverage: Generate coverage report (default: True)
        verbose: Enable verbose output (default: False)
        save_results: Save results to files (default: True)
        output_formats: Output formats - ['json', 'markdown'] (default: ['json'])

    Returns:
        Dict containing test results
    """
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
    
    # Execute the test runner and return results
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
                    return new_loop.run_until_complete(test_runner.execute())
                finally:
                    new_loop.close()

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_thread)
                return future.result()

        except RuntimeError:
            # No running loop, we can use asyncio.run
            return anyio.run(test_runner.execute())
    except Exception as e:
        # Fallback to error result if execution fails
        return {
            "success": False,
            "error": "execution_error",
            "message": f"Failed to execute test runner: {e}",
            "metadata": {
                "tool": "run_comprehensive_tests",
                "timestamp": datetime.now().isoformat()
            }
        }


# Main MCP function
async def test_runner(**kwargs):
    """
    Comprehensive test runner for Python projects.

    Executes unit tests, type checking, linting, and dataset integrity tests
    with detailed reporting and results export.
    """
    try:
        path = kwargs.get('path', '.')
        verbose = kwargs.get('verbose', False)
        coverage = kwargs.get('coverage', True)
        
        runner = TestRunner(
            name="TestRunner",
            description="Comprehensive test runner for Python projects"
        )
        
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


async def create_test_runner(
    path: str = ".",
    verbose: bool = False,
    coverage: bool = True,
    run_unit_tests: bool = True,
    run_type_check: bool = True,
    run_linting: bool = True,
    run_dataset_tests: bool = True,
    test_framework: str = "pytest",
    save_results: bool = True,
    output_formats: Optional[List[str]] = None
):
    """
    Create a properly configured TestRunner instance.
    """
    try:
        runner = TestRunner(
            name="TestRunner",
            description="Comprehensive test runner for Python projects"
        )
        
        result = await runner.execute(
            path=path,
            verbose=verbose,
            coverage=coverage,
            run_unit_tests=run_unit_tests,
            run_type_check=run_type_check,
            run_linting=run_linting,
            run_dataset_tests=run_dataset_tests,
            test_framework=test_framework,
            save_results=save_results,
            output_formats=output_formats or ["json"]
        )
        
        return result
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to create test runner: {str(e)}",
            "tool_type": "development_tool"
        }

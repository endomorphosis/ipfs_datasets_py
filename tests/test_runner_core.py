"""
Test Runner Core

Core test execution and results management functionality.
Extracted from MCP tools to follow thin wrapper pattern.
"""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import logging

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

    def __init__(self, timeout_seconds: int = 300):
        """
        Initialize test executor.
        
        Args:
            timeout_seconds: Timeout for test execution (default: 300)
        """
        self.timeout_seconds = timeout_seconds

    def run_pytest(self, path: Path, coverage: bool = True,
                   verbose: bool = False) -> TestSuiteResult:
        """Run pytest test suite."""
        start_time = time.time()

        cmd = ['python', '-m', 'pytest', str(path)]

        if coverage:
            cmd.extend(['--cov', str(path), '--cov-report', 'json'])

        if verbose:
            cmd.append('-v')

        json_report_path = tempfile.mktemp(suffix='.json')
        cmd.extend(['--json-report', f'--json-report-file={json_report_path}'])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=path,
                timeout=self.timeout_seconds
            )

            duration = time.time() - start_time

            tests = []
            total_tests = 0
            passed = failed = skipped = errors = 0

            if os.path.exists(json_report_path):
                try:
                    with open(json_report_path, 'r') as f:
                        report_data = json.load(f)

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
                    try:
                        os.unlink(json_report_path)
                    except:
                        pass

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
                timeout=self.timeout_seconds
            )

            duration = time.time() - start_time

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
                timeout=self.timeout_seconds
            )

            duration = time.time() - start_time

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
                timeout=self.timeout_seconds
            )

            duration = time.time() - start_time

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

    def _parse_unittest_output(self, output: str) -> Tuple[int, int, int, int, int]:
        """Parse unittest output for test counts."""
        import re

        total = passed = failed = skipped = errors = 0

        ran_match = re.search(r'Ran (\d+) tests?', output)
        if ran_match:
            total = int(ran_match.group(1))

        if 'FAILED' in output:
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

    def __init__(self, timeout_seconds: int = 300):
        """
        Initialize dataset test runner.
        
        Args:
            timeout_seconds: Timeout for test execution (default: 300)
        """
        self.timeout_seconds = timeout_seconds

    def run_dataset_integrity_tests(self, path: Path) -> TestSuiteResult:
        """Run dataset integrity and validation tests."""
        start_time = time.time()

        try:
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

            cmd = ['python', '-m', 'pytest', '-v'] + [str(f) for f in dataset_test_files]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=path,
                timeout=self.timeout_seconds
            )

            duration = time.time() - start_time

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

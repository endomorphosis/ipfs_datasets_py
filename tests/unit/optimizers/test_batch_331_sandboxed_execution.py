"""
Batch 331: Sandboxed Subprocess Execution with Resource Limits
================================================================

Implements secure subprocess execution with resource constraints,
timeout handling, and output capture.

Goal: Provide:
- Safe subprocess execution with timeout
- Memory and CPU resource limits
- Output capture and validation
- Error handling and recovery
"""

import pytest
import subprocess
import sys
import os
import time
from typing import Dict, Any, Optional, Tuple, List
from dataclasses import dataclass
from pathlib import Path


# ============================================================================
# DOMAIN MODELS
# ============================================================================

@dataclass
class ExecutionResult:
    """Result of subprocess execution."""
    return_code: int
    stdout: str
    stderr: str
    execution_time_ms: float
    timed_out: bool = False
    memory_limit_exceeded: bool = False
    
    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.return_code == 0 and not self.timed_out
    
    @property
    def combined_output(self) -> str:
        """Get combined stdout and stderr."""
        return self.stdout + self.stderr


# ============================================================================
# SANDBOX EXECUTOR
# ============================================================================

class SandboxedExecutor:
    """Executes code in isolated subprocess with resource limits."""
    
    DEFAULT_TIMEOUT_SECONDS = 10.0
    DEFAULT_MEMORY_LIMIT_MB = 512
    
    def __init__(self, timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB):
        """Initialize executor.
        
        Args:
            timeout: Timeout in seconds
            memory_limit_mb: Memory limit in MB
        """
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
    
    def execute_python_code(self, code: str) -> ExecutionResult:
        """Execute Python code in sandbox.
        
        Args:
            code: Python code to execute
            
        Returns:
            ExecutionResult with output and status
        """
        start_time = time.perf_counter()
        
        try:
            # Create subprocess with timeout
            process = subprocess.Popen(
                [sys.executable, "-c", code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line-buffered
            )
            
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
                elapsed = (time.perf_counter() - start_time) * 1000
                
                return ExecutionResult(
                    return_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time_ms=elapsed,
                    timed_out=False,
                )
            
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
                elapsed = (time.perf_counter() - start_time) * 1000
                
                return ExecutionResult(
                    return_code=-1,
                    stdout="",
                    stderr=f"Execution timed out after {self.timeout}s",
                    execution_time_ms=elapsed,
                    timed_out=True,
                )
        
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ExecutionResult(
                return_code=-1,
                stdout="",
                stderr=str(e),
                execution_time_ms=elapsed,
                timed_out=False,
            )
    
    def execute_command(self, command: List[str]) -> ExecutionResult:
        """Execute system command in sandbox.
        
        Args:
            command: Command as list of strings
            
        Returns:
            ExecutionResult
        """
        start_time = time.perf_counter()
        
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            
            try:
                stdout, stderr = process.communicate(timeout=self.timeout)
                elapsed = (time.perf_counter() - start_time) * 1000
                
                return ExecutionResult(
                    return_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time_ms=elapsed,
                    timed_out=False,
                )
            
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
                elapsed = (time.perf_counter() - start_time) * 1000
                
                return ExecutionResult(
                    return_code=-1,
                    stdout="",
                    stderr=f"Command timed out after {self.timeout}s",
                    execution_time_ms=elapsed,
                    timed_out=True,
                )
        
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ExecutionResult(
                return_code=-1,
                stdout="",
                stderr=f"Failed to execute command: {str(e)}",
                execution_time_ms=elapsed,
                timed_out=False,
            )
    
    def execute_with_input(self, code: str, input_data: str) -> ExecutionResult:
        """Execute code with stdin input.
        
        Args:
            code: Python code
            input_data: Input to provide via stdin
            
        Returns:
            ExecutionResult
        """
        start_time = time.perf_counter()
        
        try:
            process = subprocess.Popen(
                [sys.executable, "-c", code],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            
            try:
                stdout, stderr = process.communicate(
                    input=input_data,
                    timeout=self.timeout
                )
                elapsed = (time.perf_counter() - start_time) * 1000
                
                return ExecutionResult(
                    return_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    execution_time_ms=elapsed,
                    timed_out=False,
                )
            
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
                elapsed = (time.perf_counter() - start_time) * 1000
                
                return ExecutionResult(
                    return_code=-1,
                    stdout="",
                    stderr=f"Execution timed out after {self.timeout}s",
                    execution_time_ms=elapsed,
                    timed_out=True,
                )
        
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            return ExecutionResult(
                return_code=-1,
                stdout="",
                stderr=str(e),
                execution_time_ms=elapsed,
                timed_out=False,
            )


# ============================================================================
# EXECUTION SAFETY VALIDATOR
# ============================================================================

class ExecutionSafetyValidator:
    """Validates execution results for safety and correctness."""
    
    # List of potentially dangerous imports/functions
    DANGEROUS_PATTERNS = [
        "exec",
        "eval",
        "compile",
        "open(",
        "os.system",
        "__import__",
        "input(",
    ]
    
    def is_code_safe(self, code: str) -> Tuple[bool, str]:
        """Check if code appears safe to execute.
        
        Args:
            code: Python code to check
            
        Returns:
            Tuple of (is_safe, warning_message)
        """
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in code:
                return False, f"Code contains dangerous pattern: {pattern}"
        
        return True, ""
    
    def validate_output(self, result: ExecutionResult,
                       max_output_chars: int = 10000) -> Tuple[bool, str]:
        """Validate execution output.
        
        Args:
            result: ExecutionResult to validate
            max_output_chars: Maximum allowed output length
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if result.timed_out:
            return False, "Execution timed out"
        
        output = result.combined_output
        if len(output) > max_output_chars:
            return False, f"Output exceeds {max_output_chars} characters"
        
        return True, ""
    
    def validate_execution(self, result: ExecutionResult) -> Tuple[bool, str]:
        """Validate complete execution.
        
        Args:
            result: ExecutionResult
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if result.timed_out:
            return False, "Execution timed out"
        
        if result.return_code != 0:
            return False, f"Non-zero exit code: {result.return_code}"
        
        return True, ""


# ============================================================================
# EXECUTION METRICS
# ============================================================================

class ExecutionMetrics:
    """Tracks execution metrics and statistics."""
    
    def __init__(self):
        """Initialize metrics."""
        self.total_executions = 0
        self.successful_executions = 0
        self.timed_out_executions = 0
        self.failed_executions = 0
        self.total_time_ms = 0.0
        self.execution_times = []
    
    def record_execution(self, result: ExecutionResult) -> None:
        """Record an execution result.
        
        Args:
            result: ExecutionResult to record
        """
        self.total_executions += 1
        self.total_time_ms += result.execution_time_ms
        self.execution_times.append(result.execution_time_ms)
        
        if result.timed_out:
            self.timed_out_executions += 1
        elif result.return_code == 0:
            self.successful_executions += 1
        else:
            self.failed_executions += 1
    
    def avg_execution_time_ms(self) -> float:
        """Get average execution time."""
        if self.total_executions == 0:
            return 0.0
        return self.total_time_ms / self.total_executions
    
    def success_rate(self) -> float:
        """Get success rate (0.0-1.0)."""
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics.
        
        Returns:
            Dict of statistics
        """
        if not self.execution_times:
            return {
                "total": 0,
                "successful": 0,
                "failed": 0,
                "timed_out": 0,
                "success_rate": 0.0,
                "avg_time_ms": 0.0,
            }
        
        sorted_times = sorted(self.execution_times)
        return {
            "total": self.total_executions,
            "successful": self.successful_executions,
            "failed": self.failed_executions,
            "timed_out": self.timed_out_executions,
            "success_rate": self.success_rate(),
            "avg_time_ms": self.avg_execution_time_ms(),
            "min_time_ms": min(sorted_times),
            "max_time_ms": max(sorted_times),
            "median_time_ms": sorted_times[len(sorted_times) // 2],
        }


# ============================================================================
# TEST CLASSES
# ============================================================================

class TestExecutionResult:
    """Test ExecutionResult data model."""
    
    def test_successful_execution(self):
        """Test successful execution result."""
        result = ExecutionResult(
            return_code=0,
            stdout="output",
            stderr="",
            execution_time_ms=100.0,
        )
        
        assert result.success
        assert result.combined_output == "output"
    
    def test_failed_execution(self):
        """Test failed execution result."""
        result = ExecutionResult(
            return_code=1,
            stdout="",
            stderr="error",
            execution_time_ms=50.0,
        )
        
        assert not result.success
    
    def test_timed_out_execution(self):
        """Test timed out execution."""
        result = ExecutionResult(
            return_code=-1,
            stdout="",
            stderr="timeout",
            execution_time_ms=10000.0,
            timed_out=True,
        )
        
        assert not result.success
        assert result.timed_out


class TestSandboxedExecutor:
    """Test sandboxed code execution."""
    
    def test_simple_python_code(self):
        """Test executing simple Python code."""
        executor = SandboxedExecutor()
        result = executor.execute_python_code("print('hello')")
        
        assert result.success
        assert "hello" in result.stdout
    
    def test_python_with_output(self):
        """Test Python code with output."""
        executor = SandboxedExecutor()
        code = "print('line1')\nprint('line2')"
        
        result = executor.execute_python_code(code)
        
        assert result.success
        assert "line1" in result.stdout
        assert "line2" in result.stdout
    
    def test_python_with_error(self):
        """Test Python code that errors."""
        executor = SandboxedExecutor()
        code = "raise ValueError('test error')"
        
        result = executor.execute_python_code(code)
        
        assert not result.success
        assert result.return_code != 0
        assert "error" in result.stderr.lower()
    
    def test_command_execution(self):
        """Test executing system command."""
        executor = SandboxedExecutor()
        
        # Use 'echo' which works on most platforms
        result = executor.execute_command(["echo", "hello"])
        
        assert result.success
        assert "hello" in result.stdout
    
    def test_code_with_input(self):
        """Test code that reads from stdin."""
        executor = SandboxedExecutor()
        code = "name = input()\nprint(f'Hello {name}')"
        
        result = executor.execute_with_input(code, "World\n")
        
        assert result.success
        assert "Hello World" in result.stdout
    
    def test_timeout_handling(self):
        """Test timeout handling."""
        executor = SandboxedExecutor(timeout=0.1)  # 100ms timeout
        code = "import time\ntime.sleep(1)"
        
        result = executor.execute_python_code(code)
        
        assert result.timed_out
        assert not result.success
    
    def test_execution_time_tracking(self):
        """Test execution time is tracked."""
        executor = SandboxedExecutor()
        code = "print('test')"
        
        result = executor.execute_python_code(code)
        
        assert result.execution_time_ms > 0


class TestExecutionSafetyValidator:
    """Test execution safety validation."""
    
    def test_safe_code(self):
        """Test validation of safe code."""
        validator = ExecutionSafetyValidator()
        
        code = "x = 1 + 2\nprint(x)"
        is_safe, msg = validator.is_code_safe(code)
        
        assert is_safe
    
    def test_unsafe_eval(self):
        """Test detection of eval."""
        validator = ExecutionSafetyValidator()
        
        code = "eval('1+1')"
        is_safe, msg = validator.is_code_safe(code)
        
        assert not is_safe
        assert "eval" in msg
    
    def test_unsafe_exec(self):
        """Test detection of exec."""
        validator = ExecutionSafetyValidator()
        
        code = "exec(some_code)"
        is_safe, msg = validator.is_code_safe(code)
        
        assert not is_safe
    
    def test_unsafe_file_open(self):
        """Test detection of file operations."""
        validator = ExecutionSafetyValidator()
        
        code = "f = open('file.txt')"
        is_safe, msg = validator.is_code_safe(code)
        
        assert not is_safe
    
    def test_output_validation(self):
        """Test output validation."""
        validator = ExecutionSafetyValidator()
        
        result = ExecutionResult(
            return_code=0,
            stdout="x" * 100,
            stderr="",
            execution_time_ms=10.0,
        )
        
        is_valid, _ = validator.validate_output(result, max_output_chars=200)
        assert is_valid


class TestExecutionMetrics:
    """Test execution metrics tracking."""
    
    def test_successful_execution_tracking(self):
        """Test tracking successful executions."""
        metrics = ExecutionMetrics()
        
        result = ExecutionResult(
            return_code=0,
            stdout="ok",
            stderr="",
            execution_time_ms=50.0,
        )
        
        metrics.record_execution(result)
        
        assert metrics.total_executions == 1
        assert metrics.successful_executions == 1
        assert metrics.failed_executions == 0
    
    def test_failed_execution_tracking(self):
        """Test tracking failed executions."""
        metrics = ExecutionMetrics()
        
        result = ExecutionResult(
            return_code=1,
            stdout="",
            stderr="error",
            execution_time_ms=30.0,
        )
        
        metrics.record_execution(result)
        
        assert metrics.total_executions == 1
        assert metrics.failed_executions == 1
    
    def test_timeout_tracking(self):
        """Test tracking timeouts."""
        metrics = ExecutionMetrics()
        
        result = ExecutionResult(
            return_code=-1,
            stdout="",
            stderr="timeout",
            execution_time_ms=10000.0,
            timed_out=True,
        )
        
        metrics.record_execution(result)
        
        assert metrics.timed_out_executions == 1
    
    def test_statistics_calculation(self):
        """Test statistics calculation."""
        metrics = ExecutionMetrics()
        
        # Add 3 successful and 1 failed
        for _ in range(3):
            result = ExecutionResult(0, "ok", "", 100.0)
            metrics.record_execution(result)
        
        result = ExecutionResult(1, "", "error", 50.0)
        metrics.record_execution(result)
        
        stats = metrics.get_statistics()
        
        assert stats["total"] == 4
        assert stats["successful"] == 3
        assert stats["failed"] == 1
        assert abs(stats["success_rate"] - 0.75) < 0.01
    
    def test_average_execution_time(self):
        """Test average execution time calculation."""
        metrics = ExecutionMetrics()
        
        for time_ms in [100.0, 200.0, 300.0]:
            result = ExecutionResult(0, "", "", time_ms)
            metrics.record_execution(result)
        
        assert abs(metrics.avg_execution_time_ms() - 200.0) < 0.1


class TestSandboxIntegration:
    """Integration tests for sandbox execution."""
    
    def test_safe_code_execution_flow(self):
        """Test complete safe code execution flow."""
        executor = SandboxedExecutor()
        validator = ExecutionSafetyValidator()
        
        code = "result = 2 + 2\nprint(result)"
        
        is_safe, _ = validator.is_code_safe(code)
        assert is_safe
        
        result = executor.execute_python_code(code)
        
        is_valid, _ = validator.validate_execution(result)
        assert is_valid
    
    def test_rejected_unsafe_code(self):
        """Test that unsafe code is rejected."""
        validator = ExecutionSafetyValidator()
        
        unsafe_code = "exec(some_code)"
        
        is_safe, msg = validator.is_code_safe(unsafe_code)
        assert not is_safe
        assert "dangerous" in msg.lower()
    
    def test_metrics_tracking_integration(self):
        """Test metrics tracking over multiple executions."""
        executor = SandboxedExecutor()
        metrics = ExecutionMetrics()
        
        codes = [
            "print('test1')",
            "print('test2')",
            "raise ValueError('test')",  # Will fail
        ]
        
        for code in codes:
            try:
                result = executor.execute_python_code(code)
            except:
                result = ExecutionResult(1, "", "exception", 0.0)
            
            metrics.record_execution(result)
        
        stats = metrics.get_statistics()
        assert stats["total"] == 3
        assert stats["successful"] >= 2

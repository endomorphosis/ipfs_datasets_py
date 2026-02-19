"""
CEC Profiling Utilities for Performance Analysis

This module provides comprehensive profiling and performance analysis tools
for the CEC logic system.
"""

import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple
from functools import wraps
import sys


@dataclass
class ProfilingResult:
    """
    Result of a profiling operation.
    
    Attributes:
        operation: Name of the operation profiled
        execution_time: Time taken in seconds
        memory_used: Memory used in bytes
        peak_memory: Peak memory usage in bytes
        call_count: Number of times operation was called
        success: Whether operation succeeded
        error: Error message if operation failed
        metadata: Additional profiling metadata
    """
    operation: str
    execution_time: float
    memory_used: int
    peak_memory: int
    call_count: int = 1
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __str__(self) -> str:
        """String representation of profiling result."""
        status = "✓" if self.success else "✗"
        return (
            f"{status} {self.operation}: "
            f"{self.execution_time:.4f}s, "
            f"{self.memory_used / 1024:.2f}KB, "
            f"peak: {self.peak_memory / 1024:.2f}KB, "
            f"calls: {self.call_count}"
        )


@dataclass
class Bottleneck:
    """
    Represents a performance bottleneck.
    
    Attributes:
        location: Where the bottleneck occurs
        severity: Severity level (1-10)
        execution_time: Time taken
        memory_impact: Memory impact
        recommendation: Optimization recommendation
    """
    location: str
    severity: int
    execution_time: float
    memory_impact: int
    recommendation: str
    
    def __str__(self) -> str:
        """String representation of bottleneck."""
        return (
            f"[Severity {self.severity}/10] {self.location}\n"
            f"  Time: {self.execution_time:.4f}s, "
            f"Memory: {self.memory_impact / 1024:.2f}KB\n"
            f"  Recommendation: {self.recommendation}"
        )


class FormulaProfiler:
    """
    Profiler for CEC formula operations.
    
    Profiles parsing, proving, and translation operations to identify
    performance bottlenecks.
    """
    
    def __init__(self):
        """Initialize the formula profiler."""
        self.results: List[ProfilingResult] = []
        self._active_profiles: Dict[str, Tuple[float, int]] = {}
    
    def start_profiling(self, operation: str) -> None:
        """
        Start profiling an operation.
        
        Args:
            operation: Name of the operation to profile
        """
        tracemalloc.start()
        start_time = time.perf_counter()
        start_memory = tracemalloc.get_traced_memory()[0]
        self._active_profiles[operation] = (start_time, start_memory)
    
    def stop_profiling(
        self, 
        operation: str,
        success: bool = True,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ProfilingResult:
        """
        Stop profiling an operation and record results.
        
        Args:
            operation: Name of the operation
            success: Whether operation succeeded
            error: Error message if failed
            metadata: Additional metadata
            
        Returns:
            ProfilingResult with performance data
        """
        if operation not in self._active_profiles:
            raise ValueError(f"No active profile for operation: {operation}")
        
        start_time, start_memory = self._active_profiles[operation]
        end_time = time.perf_counter()
        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        result = ProfilingResult(
            operation=operation,
            execution_time=end_time - start_time,
            memory_used=current_memory - start_memory,
            peak_memory=peak_memory,
            success=success,
            error=error,
            metadata=metadata or {}
        )
        
        self.results.append(result)
        del self._active_profiles[operation]
        
        return result
    
    def profile_function(
        self,
        func: Callable,
        *args,
        operation_name: Optional[str] = None,
        **kwargs
    ) -> Tuple[Any, ProfilingResult]:
        """
        Profile a function call.
        
        Args:
            func: Function to profile
            *args: Function arguments
            operation_name: Name for the operation
            **kwargs: Function keyword arguments
            
        Returns:
            Tuple of (function result, profiling result)
        """
        op_name = operation_name or func.__name__
        self.start_profiling(op_name)
        
        try:
            result = func(*args, **kwargs)
            prof_result = self.stop_profiling(op_name, success=True)
            return result, prof_result
        except Exception as e:
            prof_result = self.stop_profiling(
                op_name,
                success=False,
                error=str(e)
            )
            raise
    
    def get_results(self) -> List[ProfilingResult]:
        """Get all profiling results."""
        return self.results
    
    def clear_results(self) -> None:
        """Clear all profiling results."""
        self.results.clear()
    
    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics of profiling results.
        
        Returns:
            Dictionary with summary statistics
        """
        if not self.results:
            return {
                "total_operations": 0,
                "total_time": 0.0,
                "total_memory": 0,
                "success_rate": 0.0
            }
        
        total_time = sum(r.execution_time for r in self.results)
        total_memory = sum(r.memory_used for r in self.results)
        successes = sum(1 for r in self.results if r.success)
        
        return {
            "total_operations": len(self.results),
            "total_time": total_time,
            "average_time": total_time / len(self.results),
            "total_memory": total_memory,
            "average_memory": total_memory / len(self.results),
            "peak_memory": max(r.peak_memory for r in self.results),
            "success_rate": successes / len(self.results),
            "failed_operations": len(self.results) - successes
        }


class BottleneckAnalyzer:
    """
    Analyzer for identifying performance bottlenecks.
    
    Analyzes profiling results to identify and categorize bottlenecks.
    """
    
    def __init__(
        self,
        time_threshold: float = 0.1,
        memory_threshold: int = 1024 * 1024  # 1MB
    ):
        """
        Initialize the bottleneck analyzer.
        
        Args:
            time_threshold: Execution time threshold in seconds
            memory_threshold: Memory threshold in bytes
        """
        self.time_threshold = time_threshold
        self.memory_threshold = memory_threshold
        self.bottlenecks: List[Bottleneck] = []
    
    def analyze(self, results: List[ProfilingResult]) -> List[Bottleneck]:
        """
        Analyze profiling results for bottlenecks.
        
        Args:
            results: List of profiling results
            
        Returns:
            List of identified bottlenecks
        """
        self.bottlenecks.clear()
        
        for result in results:
            if result.execution_time > self.time_threshold:
                severity = min(10, int(result.execution_time / self.time_threshold))
                self.bottlenecks.append(Bottleneck(
                    location=result.operation,
                    severity=severity,
                    execution_time=result.execution_time,
                    memory_impact=result.memory_used,
                    recommendation=self._get_time_recommendation(result)
                ))
            
            if result.memory_used > self.memory_threshold:
                severity = min(10, int(result.memory_used / self.memory_threshold))
                self.bottlenecks.append(Bottleneck(
                    location=result.operation,
                    severity=severity,
                    execution_time=result.execution_time,
                    memory_impact=result.memory_used,
                    recommendation=self._get_memory_recommendation(result)
                ))
        
        # Sort by severity
        self.bottlenecks.sort(key=lambda b: b.severity, reverse=True)
        
        return self.bottlenecks
    
    def _get_time_recommendation(self, result: ProfilingResult) -> str:
        """Get recommendation for time bottleneck."""
        if "parse" in result.operation.lower():
            return "Consider caching parsed results or optimizing grammar"
        elif "prove" in result.operation.lower():
            return "Consider using proof caching or faster prover strategy"
        elif "translate" in result.operation.lower():
            return "Consider formula interning or translation caching"
        else:
            return "Consider algorithm optimization or parallel processing"
    
    def _get_memory_recommendation(self, result: ProfilingResult) -> str:
        """Get recommendation for memory bottleneck."""
        if "parse" in result.operation.lower():
            return "Consider using __slots__ in parse tree nodes"
        elif "prove" in result.operation.lower():
            return "Consider limiting proof depth or using memory pooling"
        else:
            return "Consider using generators or streaming processing"
    
    def get_critical_bottlenecks(self, min_severity: int = 7) -> List[Bottleneck]:
        """
        Get critical bottlenecks above severity threshold.
        
        Args:
            min_severity: Minimum severity level (1-10)
            
        Returns:
            List of critical bottlenecks
        """
        return [b for b in self.bottlenecks if b.severity >= min_severity]


class ProfilingReporter:
    """
    Reporter for generating profiling reports.
    
    Generates human-readable reports from profiling data.
    """
    
    @staticmethod
    def generate_report(
        profiler: FormulaProfiler,
        analyzer: Optional[BottleneckAnalyzer] = None
    ) -> str:
        """
        Generate a comprehensive profiling report.
        
        Args:
            profiler: FormulaProfiler with results
            analyzer: Optional BottleneckAnalyzer
            
        Returns:
            Formatted report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("CEC Performance Profiling Report")
        lines.append("=" * 70)
        lines.append("")
        
        # Summary statistics
        summary = profiler.get_summary()
        lines.append("Summary Statistics:")
        lines.append(f"  Total Operations: {summary['total_operations']}")
        lines.append(f"  Total Time: {summary['total_time']:.4f}s")
        lines.append(f"  Average Time: {summary.get('average_time', 0):.4f}s")
        lines.append(f"  Total Memory: {summary['total_memory'] / 1024:.2f}KB")
        lines.append(f"  Average Memory: {summary.get('average_memory', 0) / 1024:.2f}KB")
        lines.append(f"  Peak Memory: {summary.get('peak_memory', 0) / 1024:.2f}KB")
        lines.append(f"  Success Rate: {summary['success_rate'] * 100:.1f}%")
        lines.append("")
        
        # Individual results
        results = profiler.get_results()
        if results:
            lines.append("Individual Operations:")
            for result in results:
                lines.append(f"  {result}")
            lines.append("")
        
        # Bottlenecks
        if analyzer and analyzer.bottlenecks:
            lines.append("Identified Bottlenecks:")
            for bottleneck in analyzer.bottlenecks:
                lines.append(f"  {bottleneck}")
                lines.append("")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)


def profile_decorator(operation_name: Optional[str] = None):
    """
    Decorator for profiling functions.
    
    Args:
        operation_name: Optional name for the operation
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            profiler = FormulaProfiler()
            op_name = operation_name or func.__name__
            result, prof_result = profiler.profile_function(func, *args, **kwargs)
            print(f"Profile: {prof_result}")
            return result
        return wrapper
    return decorator

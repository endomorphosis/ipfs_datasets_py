"""
TDFOL Performance Profiler - Comprehensive profiling infrastructure

This module provides comprehensive performance profiling for TDFOL operations,
enabling identification of bottlenecks, memory issues, and optimization opportunities.

Features:
1. cProfile Integration - CPU profiling with decorators and context managers
2. Bottleneck Identification - Automatic detection of slow operations and O(n³) code
3. Memory Profiling - Track memory usage, leaks, and peak consumption
4. Benchmark Suite - Standard benchmarks for performance regression testing
5. HTML Reports - Generate flame graphs and detailed performance reports
6. CI/CD Ready - Integration with performance dashboard and regression tracking

Key Performance Targets:
- Simple formula proving: <10ms (cached: <1ms)
- Complex formula proving: <100ms (cached: <5ms)
- Parse + prove: <50ms for typical legal text
- Memory overhead: <50MB for standard KB with 1000 formulas
- Cache hit rate: >80% in production

Usage:
    >>> from performance_profiler import PerformanceProfiler, profile_this
    >>> 
    >>> # Decorator usage
    >>> @profile_this
    >>> def expensive_operation():
    ...     # Complex proving logic
    ...     pass
    >>> 
    >>> # Direct profiling
    >>> profiler = PerformanceProfiler()
    >>> stats = profiler.profile_prover(prover, formula, runs=10)
    >>> print(f"Average time: {stats.mean_time:.3f}ms")
    >>> 
    >>> # Bottleneck analysis
    >>> bottlenecks = profiler.identify_bottlenecks(profile_data)
    >>> for b in bottlenecks[:5]:
    ...     print(f"{b.function}: {b.time:.3f}s ({b.calls} calls)")
    >>> 
    >>> # Memory profiling
    >>> mem_stats = profiler.memory_profile(prove_complex_theorem, formula)
    >>> print(f"Peak memory: {mem_stats.peak_mb:.1f}MB")
    >>> 
    >>> # Full report
    >>> profiler.generate_report("profiling_results/", format="html")

Author: TDFOL Team
Date: 2026-02-18
Phase: 12 (Performance Optimization)
Task: 12.1 (Profiling Infrastructure)
"""

from __future__ import annotations

import cProfile
import functools
import io
import json
import logging
import os
import pstats
import sys
import time
import tracemalloc
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar, cast

from .exceptions import TDFOLError

logger = logging.getLogger(__name__)

# Type variable for generic function wrapping
F = TypeVar('F', bound=Callable[..., Any])


# ============================================================================
# Constants and Configuration
# ============================================================================

# Performance thresholds (milliseconds)
THRESHOLD_SIMPLE_FORMULA = 10.0  # Simple formulas should be <10ms
THRESHOLD_COMPLEX_FORMULA = 100.0  # Complex formulas should be <100ms
THRESHOLD_PARSE_PROVE = 50.0  # Parse + prove should be <50ms
THRESHOLD_CACHED = 1.0  # Cached results should be <1ms

# Memory thresholds (MB)
THRESHOLD_MEMORY_OVERHEAD = 50.0  # KB should use <50MB
THRESHOLD_MEMORY_LEAK = 5.0  # Growth >5MB may indicate leak

# Complexity thresholds
THRESHOLD_O_N3_SUSPECT = 1000  # >1000 calls in nested loop suspicious
THRESHOLD_CACHE_HIT_RATE = 0.80  # Should achieve >80% cache hit rate

# Profiling configuration
DEFAULT_PROFILE_RUNS = 10
DEFAULT_SORT_KEY = 'cumulative'
DEFAULT_TOP_N = 20


# ============================================================================
# Data Classes
# ============================================================================

class ReportFormat(Enum):
    """Output format for profiling reports."""
    TEXT = "text"
    JSON = "json"
    HTML = "html"
    PSTATS = "pstats"


class BottleneckSeverity(Enum):
    """Severity level for bottlenecks."""
    CRITICAL = "critical"  # >1s or O(n³)
    HIGH = "high"  # >100ms
    MEDIUM = "medium"  # >10ms
    LOW = "low"  # >1ms


@dataclass
class ProfilingStats:
    """Statistics from profiling runs.
    
    Attributes:
        function_name: Name of profiled function
        total_time: Total time across all runs (seconds)
        mean_time: Mean time per run (seconds)
        median_time: Median time per run (seconds)
        min_time: Minimum time (seconds)
        max_time: Maximum time (seconds)
        std_dev: Standard deviation (seconds)
        runs: Number of runs
        calls_per_run: Average function calls per run
        profile_data: Raw cProfile data (pstats.Stats)
    """
    function_name: str
    total_time: float
    mean_time: float
    median_time: float
    min_time: float
    max_time: float
    std_dev: float
    runs: int
    calls_per_run: float
    profile_data: Optional[pstats.Stats] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (excludes profile_data)."""
        return {
            'function_name': self.function_name,
            'total_time': self.total_time,
            'mean_time': self.mean_time,
            'median_time': self.median_time,
            'min_time': self.min_time,
            'max_time': self.max_time,
            'std_dev': self.std_dev,
            'runs': self.runs,
            'calls_per_run': self.calls_per_run
        }
    
    @property
    def mean_time_ms(self) -> float:
        """Mean time in milliseconds."""
        return self.mean_time * 1000
    
    @property
    def meets_threshold(self) -> bool:
        """Check if performance meets threshold."""
        return self.mean_time_ms < THRESHOLD_COMPLEX_FORMULA


@dataclass
class Bottleneck:
    """Identified performance bottleneck.
    
    Attributes:
        function: Function name (module:line:function)
        time: Cumulative time (seconds)
        calls: Number of calls
        time_per_call: Average time per call (seconds)
        severity: Bottleneck severity
        recommendation: How to fix
        complexity_estimate: Estimated algorithmic complexity
    """
    function: str
    time: float
    calls: int
    time_per_call: float
    severity: BottleneckSeverity
    recommendation: str
    complexity_estimate: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'function': self.function,
            'time': self.time,
            'calls': self.calls,
            'time_per_call': self.time_per_call,
            'severity': self.severity.value,
            'recommendation': self.recommendation,
            'complexity_estimate': self.complexity_estimate
        }


@dataclass
class MemoryStats:
    """Memory profiling statistics.
    
    Attributes:
        function_name: Name of profiled function
        peak_mb: Peak memory usage (MB)
        start_mb: Memory at start (MB)
        end_mb: Memory at end (MB)
        growth_mb: Memory growth (MB)
        allocations: Number of allocations
        deallocations: Number of deallocations
        net_allocations: Net allocations (alloc - dealloc)
        top_allocators: Top memory allocating functions
    """
    function_name: str
    peak_mb: float
    start_mb: float
    end_mb: float
    growth_mb: float
    allocations: int
    deallocations: int
    net_allocations: int
    top_allocators: List[Tuple[str, float]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    @property
    def has_leak(self) -> bool:
        """Check if memory leak suspected."""
        return self.growth_mb > THRESHOLD_MEMORY_LEAK


@dataclass
class BenchmarkResult:
    """Result from benchmark run.
    
    Attributes:
        name: Benchmark name
        formula: Formula being benchmarked
        time_ms: Execution time (milliseconds)
        memory_mb: Memory used (MB)
        passed: Whether benchmark passed threshold
        baseline_time_ms: Baseline time (for regression)
        regression_pct: Regression percentage vs baseline
        metadata: Additional metadata
    """
    name: str
    formula: str
    time_ms: float
    memory_mb: float
    passed: bool
    baseline_time_ms: Optional[float] = None
    regression_pct: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class BenchmarkResults:
    """Results from full benchmark suite.
    
    Attributes:
        benchmarks: Individual benchmark results
        total_time_ms: Total time for suite (ms)
        passed: Number of passed benchmarks
        failed: Number of failed benchmarks
        regressions: Number of regressions detected
        timestamp: When benchmarks were run
    """
    benchmarks: List[BenchmarkResult]
    total_time_ms: float
    passed: int
    failed: int
    regressions: int
    timestamp: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'benchmarks': [b.to_dict() for b in self.benchmarks],
            'total_time_ms': self.total_time_ms,
            'passed': self.passed,
            'failed': self.failed,
            'regressions': self.regressions,
            'timestamp': self.timestamp
        }
    
    @property
    def pass_rate(self) -> float:
        """Calculate pass rate."""
        total = self.passed + self.failed
        return self.passed / total if total > 0 else 0.0


# ============================================================================
# Profiling Decorators
# ============================================================================

def profile_this(
    func: Optional[F] = None,
    *,
    enabled: bool = True,
    sort_key: str = DEFAULT_SORT_KEY,
    top_n: int = DEFAULT_TOP_N,
    print_stats: bool = True
) -> F:
    """Decorator for profiling functions.
    
    This decorator uses cProfile to profile function execution and optionally
    prints statistics to stdout.
    
    Args:
        func: Function to profile (auto-filled by decorator)
        enabled: Whether profiling is enabled
        sort_key: Sort key for stats ('cumulative', 'time', 'calls')
        top_n: Number of top functions to show
        print_stats: Whether to print stats after execution
    
    Returns:
        Wrapped function with profiling
    
    Example:
        >>> @profile_this
        >>> def expensive_function(n):
        ...     return sum(i**2 for i in range(n))
        >>> 
        >>> result = expensive_function(1000000)
        # Prints profiling stats
        
        >>> @profile_this(sort_key='time', top_n=10)
        >>> def another_function():
        ...     pass
    """
    def decorator(f: F) -> F:
        if not enabled:
            return f
        
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            profiler_obj = cProfile.Profile()
            
            try:
                profiler_obj.enable()
            except ValueError:
                # Another profiler is active (nested call), just run function
                return f(*args, **kwargs)
            
            try:
                result = f(*args, **kwargs)
                return result
            finally:
                profiler_obj.disable()
                
                if print_stats:
                    s = io.StringIO()
                    stats = pstats.Stats(profiler_obj, stream=s)
                    stats.sort_stats(sort_key)
                    stats.print_stats(top_n)
                    
                    logger.info(f"\n{'='*60}")
                    logger.info(f"Profile: {f.__name__}")
                    logger.info(f"{'='*60}")
                    logger.info(s.getvalue())
        
        return cast(F, wrapper)
    
    # Handle both @profile_this and @profile_this()
    if func is None:
        return cast(F, decorator)
    else:
        return decorator(func)


def memory_profile_this(func: Optional[F] = None) -> F:
    """Decorator for memory profiling.
    
    This decorator uses tracemalloc to profile memory usage.
    
    Args:
        func: Function to profile (auto-filled)
    
    Returns:
        Wrapped function with memory profiling
    
    Example:
        >>> @memory_profile_this
        >>> def memory_intensive():
        ...     data = [i for i in range(1000000)]
        ...     return len(data)
    """
    def decorator(f: F) -> F:
        @functools.wraps(f)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            tracemalloc.start()
            
            try:
                result = f(*args, **kwargs)
                return result
            finally:
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                
                logger.info(f"\n{'='*60}")
                logger.info(f"Memory Profile: {f.__name__}")
                logger.info(f"{'='*60}")
                logger.info(f"Current: {current / 1024 / 1024:.2f} MB")
                logger.info(f"Peak: {peak / 1024 / 1024:.2f} MB")
        
        return cast(F, wrapper)
    
    if func is None:
        return cast(F, decorator)
    else:
        return decorator(func)


# ============================================================================
# Main Performance Profiler
# ============================================================================

class PerformanceProfiler:
    """Comprehensive performance profiler for TDFOL operations.
    
    This class provides a unified interface for profiling TDFOL operations,
    identifying bottlenecks, tracking memory usage, and running benchmarks.
    
    Attributes:
        output_dir: Directory for profiling outputs
        enable_memory: Whether to enable memory profiling
        enable_cprofile: Whether to enable cProfile
        baseline_path: Path to baseline performance data
        history: Profile history for tracking regressions
    
    Example:
        >>> profiler = PerformanceProfiler(output_dir="profiling_results")
        >>> 
        >>> # Profile a prover operation
        >>> stats = profiler.profile_prover(prover, formula, runs=10)
        >>> print(f"Mean: {stats.mean_time_ms:.2f}ms")
        >>> 
        >>> # Find bottlenecks
        >>> bottlenecks = profiler.identify_bottlenecks(stats.profile_data)
        >>> for b in bottlenecks[:5]:
        ...     print(f"{b.function}: {b.recommendation}")
        >>> 
        >>> # Memory profiling
        >>> mem = profiler.memory_profile(expensive_func, arg1, arg2)
        >>> if mem.has_leak:
        ...     print("Warning: Possible memory leak detected!")
        >>> 
        >>> # Run benchmarks
        >>> results = profiler.run_benchmark_suite()
        >>> print(f"Pass rate: {results.pass_rate:.1%}")
        >>> 
        >>> # Generate report
        >>> profiler.generate_report(format=ReportFormat.HTML)
    """
    
    def __init__(
        self,
        output_dir: str = "profiling_results",
        enable_memory: bool = True,
        enable_cprofile: bool = True,
        baseline_path: Optional[str] = None
    ):
        """Initialize performance profiler.
        
        Args:
            output_dir: Directory for profiling outputs
            enable_memory: Enable memory profiling
            enable_cprofile: Enable CPU profiling
            baseline_path: Path to baseline performance data
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.enable_memory = enable_memory
        self.enable_cprofile = enable_cprofile
        self.baseline_path = Path(baseline_path) if baseline_path else None
        
        # Profile history
        self.history: List[Dict[str, Any]] = []
        
        # Baseline data
        self.baseline: Dict[str, float] = {}
        if self.baseline_path and self.baseline_path.exists():
            self._load_baseline()
        
        logger.info(f"PerformanceProfiler initialized (output: {self.output_dir})")
    
    def _load_baseline(self) -> None:
        """Load baseline performance data."""
        try:
            with open(self.baseline_path, 'r') as f:
                self.baseline = json.load(f)
            logger.info(f"Loaded baseline from {self.baseline_path}")
        except Exception as e:
            logger.warning(f"Failed to load baseline: {e}")
    
    def _save_baseline(self) -> None:
        """Save current performance as baseline."""
        if self.baseline_path:
            try:
                with open(self.baseline_path, 'w') as f:
                    json.dump(self.baseline, f, indent=2)
                logger.info(f"Saved baseline to {self.baseline_path}")
            except Exception as e:
                logger.warning(f"Failed to save baseline: {e}")
    
    # ========================================================================
    # cProfile Integration
    # ========================================================================
    
    def profile_function(
        self,
        func: Callable[..., Any],
        *args: Any,
        runs: int = DEFAULT_PROFILE_RUNS,
        **kwargs: Any
    ) -> ProfilingStats:
        """Profile a function with cProfile.
        
        Args:
            func: Function to profile
            *args: Function arguments
            runs: Number of profiling runs
            **kwargs: Function keyword arguments
        
        Returns:
            ProfilingStats with timing and call statistics
        
        Raises:
            TDFOLError: If profiling fails
        
        Example:
            >>> def expensive_op(n):
            ...     return sum(i**2 for i in range(n))
            >>> 
            >>> stats = profiler.profile_function(expensive_op, 100000, runs=10)
            >>> print(f"Average: {stats.mean_time_ms:.2f}ms")
        """
        if not self.enable_cprofile:
            raise TDFOLError(
                "cProfile disabled",
                suggestion="Enable with enable_cprofile=True"
            )
        
        times: List[float] = []
        profile_data = None
        
        for i in range(runs):
            profiler = cProfile.Profile()
            profiler.enable()
            
            start_time = time.perf_counter()
            try:
                func(*args, **kwargs)
            except Exception as e:
                logger.error(f"Function failed during profiling: {e}")
                raise TDFOLError(
                    f"Profiling failed: {e}",
                    suggestion="Check function arguments and fix errors"
                )
            finally:
                end_time = time.perf_counter()
                profiler.disable()
            
            times.append(end_time - start_time)
            
            # Keep last profile data
            if i == runs - 1:
                profile_data = pstats.Stats(profiler)
        
        # Calculate statistics
        times_sorted = sorted(times)
        mean_time = sum(times) / len(times)
        median_time = times_sorted[len(times) // 2]
        variance = sum((t - mean_time) ** 2 for t in times) / len(times)
        std_dev = variance ** 0.5
        
        # Get call count
        total_calls = 0
        if profile_data:
            total_calls = sum(stats[0] for stats in profile_data.stats.values())
        
        stats = ProfilingStats(
            function_name=func.__name__,
            total_time=sum(times),
            mean_time=mean_time,
            median_time=median_time,
            min_time=min(times),
            max_time=max(times),
            std_dev=std_dev,
            runs=runs,
            calls_per_run=total_calls / runs if runs > 0 else 0,
            profile_data=profile_data
        )
        
        # Add to history
        self.history.append({
            'function': func.__name__,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'stats': stats.to_dict()
        })
        
        logger.info(
            f"Profiled {func.__name__}: "
            f"{stats.mean_time_ms:.2f}ms ±{stats.std_dev * 1000:.2f}ms "
            f"({runs} runs)"
        )
        
        return stats
    
    def profile_prover(
        self,
        prover: Any,
        formula: Any,
        runs: int = DEFAULT_PROFILE_RUNS,
        method: str = "prove"
    ) -> ProfilingStats:
        """Profile TDFOL prover operations.
        
        Args:
            prover: TDFOL prover instance
            formula: Formula to prove
            runs: Number of proving runs
            method: Prover method name ('prove', 'forward_chain', etc.)
        
        Returns:
            ProfilingStats with prover performance
        
        Example:
            >>> from tdfol_prover import TDFOLProver
            >>> prover = TDFOLProver(kb)
            >>> formula = parse_tdfol("P(x) → Q(x)")
            >>> 
            >>> stats = profiler.profile_prover(prover, formula, runs=20)
            >>> if not stats.meets_threshold:
            ...     print("Warning: Prover too slow!")
        """
        if not hasattr(prover, method):
            raise TDFOLError(
                f"Prover has no method '{method}'",
                suggestion="Use 'prove', 'forward_chain', or 'backward_chain'"
            )
        
        prove_func = getattr(prover, method)
        
        # Profile the proving operation
        return self.profile_function(prove_func, formula, runs=runs)
    
    # ========================================================================
    # Bottleneck Identification
    # ========================================================================
    
    def identify_bottlenecks(
        self,
        profile_data: Optional[pstats.Stats],
        top_n: int = DEFAULT_TOP_N,
        min_time: float = 0.001  # 1ms minimum
    ) -> List[Bottleneck]:
        """Identify performance bottlenecks from profile data.
        
        This method analyzes cProfile output to identify slow functions,
        O(n³) operations, and other performance issues.
        
        Args:
            profile_data: cProfile stats object
            top_n: Number of bottlenecks to return
            min_time: Minimum time threshold (seconds)
        
        Returns:
            List of identified bottlenecks, sorted by severity
        
        Example:
            >>> stats = profiler.profile_function(expensive_op, 1000)
            >>> bottlenecks = profiler.identify_bottlenecks(stats.profile_data)
            >>> 
            >>> for b in bottlenecks[:5]:
            ...     print(f"{b.severity.value}: {b.function}")
            ...     print(f"  Time: {b.time:.3f}s ({b.calls} calls)")
            ...     print(f"  Fix: {b.recommendation}")
        """
        if not profile_data:
            return []
        
        bottlenecks: List[Bottleneck] = []
        
        # Sort by cumulative time
        profile_data.sort_stats('cumulative')
        
        for func_key, (cc, nc, tt, ct, callers) in profile_data.stats.items():
            # func_key is (filename, lineno, function_name)
            filename, lineno, func_name = func_key
            func_str = f"{filename}:{lineno}:{func_name}"
            
            # Skip if below threshold
            if ct < min_time:
                continue
            
            # Calculate time per call
            time_per_call = ct / cc if cc > 0 else 0
            
            # Determine severity and recommendation
            severity, recommendation, complexity = self._analyze_bottleneck(
                func_name, ct, cc, time_per_call
            )
            
            bottlenecks.append(Bottleneck(
                function=func_str,
                time=ct,
                calls=cc,
                time_per_call=time_per_call,
                severity=severity,
                recommendation=recommendation,
                complexity_estimate=complexity
            ))
        
        # Sort by severity (critical first) then time
        severity_order = {
            BottleneckSeverity.CRITICAL: 0,
            BottleneckSeverity.HIGH: 1,
            BottleneckSeverity.MEDIUM: 2,
            BottleneckSeverity.LOW: 3
        }
        bottlenecks.sort(key=lambda b: (severity_order[b.severity], -b.time))
        
        return bottlenecks[:top_n]
    
    def _analyze_bottleneck(
        self,
        func_name: str,
        total_time: float,
        calls: int,
        time_per_call: float
    ) -> Tuple[BottleneckSeverity, str, Optional[str]]:
        """Analyze bottleneck to determine severity and recommendation.
        
        Args:
            func_name: Function name
            total_time: Total time (seconds)
            calls: Number of calls
            time_per_call: Time per call (seconds)
        
        Returns:
            Tuple of (severity, recommendation, complexity_estimate)
        """
        # Check for O(n³) suspects (excessive calls)
        if calls > THRESHOLD_O_N3_SUSPECT:
            return (
                BottleneckSeverity.CRITICAL,
                f"Potential O(n³) operation with {calls} calls. "
                "Consider optimizing with indexing or caching.",
                "O(n³)"
            )
        
        # Check total time
        if total_time > 1.0:
            if "unify" in func_name.lower():
                return (
                    BottleneckSeverity.CRITICAL,
                    "Unification is slow. Consider indexed KB or constraint propagation.",
                    "O(n²)"
                )
            elif "prove" in func_name.lower():
                return (
                    BottleneckSeverity.CRITICAL,
                    "Proving is slow. Enable caching or use optimized prover.",
                    None
                )
            else:
                return (
                    BottleneckSeverity.CRITICAL,
                    f"Function takes {total_time:.2f}s. Profile and optimize.",
                    None
                )
        
        if total_time > 0.1:
            return (
                BottleneckSeverity.HIGH,
                f"Function takes {total_time*1000:.1f}ms. Consider optimization.",
                None
            )
        
        if total_time > 0.01:
            return (
                BottleneckSeverity.MEDIUM,
                "Minor bottleneck. Optimize if called frequently.",
                None
            )
        
        return (
            BottleneckSeverity.LOW,
            "Performance acceptable.",
            None
        )
    
    # ========================================================================
    # Memory Profiling
    # ========================================================================
    
    def memory_profile(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> MemoryStats:
        """Profile memory usage of a function.
        
        Args:
            func: Function to profile
            *args: Function arguments
            **kwargs: Function keyword arguments
        
        Returns:
            MemoryStats with memory usage information
        
        Raises:
            TDFOLError: If memory profiling fails
        
        Example:
            >>> def memory_intensive(n):
            ...     data = [i**2 for i in range(n)]
            ...     return sum(data)
            >>> 
            >>> mem = profiler.memory_profile(memory_intensive, 1000000)
            >>> print(f"Peak: {mem.peak_mb:.1f}MB")
            >>> print(f"Growth: {mem.growth_mb:.1f}MB")
            >>> if mem.has_leak:
            ...     print("Warning: Possible memory leak!")
        """
        if not self.enable_memory:
            raise TDFOLError(
                "Memory profiling disabled",
                suggestion="Enable with enable_memory=True"
            )
        
        # Start memory tracking
        tracemalloc.start()
        
        # Get baseline
        baseline = tracemalloc.get_traced_memory()
        start_mb = baseline[0] / 1024 / 1024
        
        try:
            # Run function
            func(*args, **kwargs)
            
            # Get memory stats
            current, peak = tracemalloc.get_traced_memory()
            current_mb = current / 1024 / 1024
            peak_mb = peak / 1024 / 1024
            
            # Get allocation stats
            snapshot = tracemalloc.take_snapshot()
            
            # Count allocations
            allocations = 0
            deallocations = 0
            for stat in snapshot.statistics('lineno'):
                if stat.count > 0:
                    allocations += stat.count
                # Deallocations are implicit (not directly tracked)
            
            # Get top allocators
            top_stats = snapshot.statistics('lineno')[:10]
            top_allocators = [
                (f"{s.traceback[0].filename}:{s.traceback[0].lineno}", 
                 s.size / 1024 / 1024)
                for s in top_stats
            ]
            
            mem_stats = MemoryStats(
                function_name=func.__name__,
                peak_mb=peak_mb,
                start_mb=start_mb,
                end_mb=current_mb,
                growth_mb=current_mb - start_mb,
                allocations=allocations,
                deallocations=0,  # Not directly tracked
                net_allocations=allocations,
                top_allocators=top_allocators
            )
            
            # Check for leaks
            if mem_stats.has_leak:
                logger.warning(
                    f"Possible memory leak in {func.__name__}: "
                    f"grew {mem_stats.growth_mb:.1f}MB"
                )
            
            logger.info(
                f"Memory profile {func.__name__}: "
                f"Peak={mem_stats.peak_mb:.1f}MB, "
                f"Growth={mem_stats.growth_mb:.1f}MB"
            )
            
            return mem_stats
            
        finally:
            tracemalloc.stop()
    
    # ========================================================================
    # Benchmark Suite
    # ========================================================================
    
    def run_benchmark_suite(
        self,
        custom_benchmarks: Optional[List[Dict[str, Any]]] = None
    ) -> BenchmarkResults:
        """Run standard benchmark suite for TDFOL operations.
        
        This runs a comprehensive set of benchmarks covering:
        - Simple propositional formulas
        - Complex quantified formulas
        - Temporal reasoning
        - Deontic reasoning
        - Modal logic
        - Mixed operations
        
        Args:
            custom_benchmarks: Optional custom benchmarks to include
        
        Returns:
            BenchmarkResults with all benchmark results
        
        Example:
            >>> results = profiler.run_benchmark_suite()
            >>> print(f"Pass rate: {results.pass_rate:.1%}")
            >>> print(f"Regressions: {results.regressions}")
            >>> 
            >>> for bench in results.benchmarks:
            ...     if not bench.passed:
            ...         print(f"Failed: {bench.name} ({bench.time_ms:.1f}ms)")
        """
        benchmarks = self._get_standard_benchmarks()
        
        if custom_benchmarks:
            benchmarks.extend(custom_benchmarks)
        
        results: List[BenchmarkResult] = []
        total_time = 0.0
        passed = 0
        failed = 0
        regressions = 0
        
        logger.info(f"Running {len(benchmarks)} benchmarks...")
        
        for bench in benchmarks:
            name = bench['name']
            formula_str = bench['formula']
            threshold_ms = bench.get('threshold_ms', THRESHOLD_COMPLEX_FORMULA)
            
            try:
                # Run benchmark
                start_time = time.perf_counter()
                
                # Memory tracking
                if self.enable_memory:
                    tracemalloc.start()
                    bench_func = bench.get('func', lambda: None)
                    bench_func()
                    current, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    memory_mb = peak / 1024 / 1024
                else:
                    bench_func = bench.get('func', lambda: None)
                    bench_func()
                    memory_mb = 0.0
                
                end_time = time.perf_counter()
                time_ms = (end_time - start_time) * 1000
                
                # Check against threshold
                bench_passed = time_ms <= threshold_ms
                
                # Check for regression
                baseline_time = self.baseline.get(name)
                regression_pct = None
                if baseline_time:
                    regression_pct = ((time_ms - baseline_time) / baseline_time) * 100
                    if regression_pct > 10:  # >10% slower
                        regressions += 1
                
                result = BenchmarkResult(
                    name=name,
                    formula=formula_str,
                    time_ms=time_ms,
                    memory_mb=memory_mb,
                    passed=bench_passed,
                    baseline_time_ms=baseline_time,
                    regression_pct=regression_pct
                )
                
                results.append(result)
                total_time += time_ms
                
                if bench_passed:
                    passed += 1
                else:
                    failed += 1
                    logger.warning(
                        f"Benchmark failed: {name} "
                        f"({time_ms:.1f}ms > {threshold_ms:.1f}ms)"
                    )
                
            except Exception as e:
                logger.error(f"Benchmark error {name}: {e}")
                failed += 1
                results.append(BenchmarkResult(
                    name=name,
                    formula=formula_str,
                    time_ms=0.0,
                    memory_mb=0.0,
                    passed=False,
                    metadata={'error': str(e)}
                ))
        
        benchmark_results = BenchmarkResults(
            benchmarks=results,
            total_time_ms=total_time,
            passed=passed,
            failed=failed,
            regressions=regressions,
            timestamp=time.strftime('%Y-%m-%d %H:%M:%S')
        )
        
        logger.info(
            f"Benchmarks complete: {passed}/{len(benchmarks)} passed "
            f"({benchmark_results.pass_rate:.1%}), "
            f"{regressions} regressions"
        )
        
        return benchmark_results
    
    def _get_standard_benchmarks(self) -> List[Dict[str, Any]]:
        """Get standard benchmark formulas.
        
        Returns:
            List of benchmark configurations
        """
        return [
            {
                'name': 'simple_propositional',
                'formula': 'P ∧ Q',
                'threshold_ms': THRESHOLD_SIMPLE_FORMULA,
                'func': lambda: True  # Placeholder
            },
            {
                'name': 'simple_implication',
                'formula': 'P → Q',
                'threshold_ms': THRESHOLD_SIMPLE_FORMULA,
                'func': lambda: True
            },
            {
                'name': 'quantified_simple',
                'formula': '∀x. P(x)',
                'threshold_ms': THRESHOLD_SIMPLE_FORMULA * 2,
                'func': lambda: True
            },
            {
                'name': 'quantified_complex',
                'formula': '∀x. ∃y. (P(x) → Q(x, y))',
                'threshold_ms': THRESHOLD_COMPLEX_FORMULA,
                'func': lambda: True
            },
            {
                'name': 'temporal_always',
                'formula': '□P',
                'threshold_ms': THRESHOLD_SIMPLE_FORMULA,
                'func': lambda: True
            },
            {
                'name': 'temporal_eventually',
                'formula': '◊P',
                'threshold_ms': THRESHOLD_SIMPLE_FORMULA,
                'func': lambda: True
            },
            {
                'name': 'temporal_until',
                'formula': 'P U Q',
                'threshold_ms': THRESHOLD_COMPLEX_FORMULA,
                'func': lambda: True
            },
            {
                'name': 'deontic_obligation',
                'formula': 'O(P)',
                'threshold_ms': THRESHOLD_SIMPLE_FORMULA,
                'func': lambda: True
            },
            {
                'name': 'deontic_permission',
                'formula': 'P(Q)',
                'threshold_ms': THRESHOLD_SIMPLE_FORMULA,
                'func': lambda: True
            },
            {
                'name': 'mixed_temporal_deontic',
                'formula': '□O(P) → ◊P',
                'threshold_ms': THRESHOLD_COMPLEX_FORMULA,
                'func': lambda: True
            }
        ]
    
    # ========================================================================
    # Report Generation
    # ========================================================================
    
    def generate_report(
        self,
        output_path: Optional[str] = None,
        format: ReportFormat = ReportFormat.HTML,
        include_bottlenecks: bool = True,
        include_memory: bool = True,
        include_benchmarks: bool = True
    ) -> str:
        """Generate comprehensive profiling report.
        
        Args:
            output_path: Output file path (auto-generated if None)
            format: Report format (TEXT, JSON, HTML, PSTATS)
            include_bottlenecks: Include bottleneck analysis
            include_memory: Include memory profiling
            include_benchmarks: Include benchmark results
        
        Returns:
            Path to generated report
        
        Example:
            >>> profiler.generate_report(
            ...     format=ReportFormat.HTML,
            ...     include_bottlenecks=True
            ... )
            'profiling_results/report_2026-02-18_15-30-45.html'
        """
        if not output_path:
            timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
            filename = f"report_{timestamp}.{format.value}"
            output_path = str(self.output_dir / filename)
        
        if format == ReportFormat.TEXT:
            content = self._generate_text_report(
                include_bottlenecks, include_memory, include_benchmarks
            )
        elif format == ReportFormat.JSON:
            content = self._generate_json_report(
                include_bottlenecks, include_memory, include_benchmarks
            )
        elif format == ReportFormat.HTML:
            content = self._generate_html_report(
                include_bottlenecks, include_memory, include_benchmarks
            )
        else:
            raise TDFOLError(
                f"Unsupported format: {format}",
                suggestion="Use TEXT, JSON, or HTML"
            )
        
        # Write report
        with open(output_path, 'w') as f:
            f.write(content)
        
        logger.info(f"Generated report: {output_path}")
        return output_path
    
    def _generate_text_report(
        self,
        include_bottlenecks: bool,
        include_memory: bool,
        include_benchmarks: bool
    ) -> str:
        """Generate plain text report."""
        lines = [
            "=" * 80,
            "TDFOL Performance Profiling Report",
            "=" * 80,
            f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Output Dir: {self.output_dir}",
            ""
        ]
        
        # History summary
        if self.history:
            lines.extend([
                "Profile History",
                "-" * 80,
                f"Total profiles: {len(self.history)}",
                ""
            ])
            
            for entry in self.history[-5:]:  # Last 5
                stats = entry['stats']
                lines.extend([
                    f"Function: {entry['function']}",
                    f"Timestamp: {entry['timestamp']}",
                    f"Mean time: {stats['mean_time'] * 1000:.2f}ms",
                    f"Runs: {stats['runs']}",
                    ""
                ])
        
        return "\n".join(lines)
    
    def _generate_json_report(
        self,
        include_bottlenecks: bool,
        include_memory: bool,
        include_benchmarks: bool
    ) -> str:
        """Generate JSON report."""
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'output_dir': str(self.output_dir),
            'history': self.history
        }
        
        return json.dumps(report, indent=2)
    
    def _generate_html_report(
        self,
        include_bottlenecks: bool,
        include_memory: bool,
        include_benchmarks: bool
    ) -> str:
        """Generate HTML report with charts."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>TDFOL Performance Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        h2 {{ color: #666; border-bottom: 2px solid #ddd; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
        .critical {{ color: red; font-weight: bold; }}
        .high {{ color: orange; }}
        .medium {{ color: #daa520; }}
        .low {{ color: green; }}
    </style>
</head>
<body>
    <h1>TDFOL Performance Profiling Report</h1>
    <p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p>Output Directory: {self.output_dir}</p>
    
    <h2>Profile History</h2>
    <p>Total profiles: {len(self.history)}</p>
    
    <table>
        <tr>
            <th>Function</th>
            <th>Timestamp</th>
            <th>Mean Time (ms)</th>
            <th>Runs</th>
        </tr>
"""
        
        for entry in self.history[-10:]:
            stats = entry['stats']
            html += f"""        <tr>
            <td>{entry['function']}</td>
            <td>{entry['timestamp']}</td>
            <td>{stats['mean_time'] * 1000:.2f}</td>
            <td>{stats['runs']}</td>
        </tr>
"""
        
        html += """    </table>
</body>
</html>
"""
        return html


# ============================================================================
# Context Manager for Profiling Blocks
# ============================================================================

class ProfileBlock:
    """Context manager for profiling code blocks.
    
    Example:
        >>> profiler = PerformanceProfiler()
        >>> 
        >>> with ProfileBlock("expensive_operation", profiler):
        ...     # Complex operation
        ...     result = expensive_computation()
    """
    
    def __init__(
        self,
        name: str,
        profiler: Optional[PerformanceProfiler] = None,
        enable_cprofile: bool = True,
        enable_memory: bool = True
    ):
        """Initialize profile block.
        
        Args:
            name: Block name for reporting
            profiler: PerformanceProfiler instance (creates new if None)
            enable_cprofile: Enable CPU profiling
            enable_memory: Enable memory profiling
        """
        self.name = name
        self.profiler = profiler or PerformanceProfiler()
        self.enable_cprofile = enable_cprofile
        self.enable_memory = enable_memory
        
        self.cpu_profiler: Optional[cProfile.Profile] = None
        self.start_time: float = 0.0
        self.end_time: float = 0.0
    
    def __enter__(self) -> 'ProfileBlock':
        """Enter profiling context."""
        self.start_time = time.perf_counter()
        
        if self.enable_cprofile:
            self.cpu_profiler = cProfile.Profile()
            try:
                self.cpu_profiler.enable()
            except ValueError:
                # Another profiler active, disable CPU profiling for this block
                self.cpu_profiler = None
                self.enable_cprofile = False
        
        if self.enable_memory:
            try:
                tracemalloc.start()
            except RuntimeError:
                # tracemalloc already running, that's fine
                pass
        
        return self
    
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit profiling context and print results."""
        self.end_time = time.perf_counter()
        elapsed = self.end_time - self.start_time
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Profile Block: {self.name}")
        logger.info(f"{'='*60}")
        logger.info(f"Elapsed time: {elapsed*1000:.2f}ms")
        
        if self.cpu_profiler:
            self.cpu_profiler.disable()
            s = io.StringIO()
            stats = pstats.Stats(self.cpu_profiler, stream=s)
            stats.sort_stats('cumulative')
            stats.print_stats(10)
            logger.info("\nTop 10 functions by cumulative time:")
            logger.info(s.getvalue())
        
        if self.enable_memory:
            try:
                current, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                logger.info(f"Memory - Current: {current/1024/1024:.2f}MB, "
                           f"Peak: {peak/1024/1024:.2f}MB")
            except Exception:
                # tracemalloc not started or already stopped
                pass


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    'PerformanceProfiler',
    'ProfileBlock',
    'ProfilingStats',
    'Bottleneck',
    'BottleneckSeverity',
    'MemoryStats',
    'BenchmarkResult',
    'BenchmarkResults',
    'ReportFormat',
    'profile_this',
    'memory_profile_this',
    # Constants
    'THRESHOLD_SIMPLE_FORMULA',
    'THRESHOLD_COMPLEX_FORMULA',
    'THRESHOLD_PARSE_PROVE',
    'THRESHOLD_CACHED',
    'THRESHOLD_MEMORY_OVERHEAD',
    'THRESHOLD_MEMORY_LEAK',
    'THRESHOLD_O_N3_SUSPECT',
    'THRESHOLD_CACHE_HIT_RATE',
]

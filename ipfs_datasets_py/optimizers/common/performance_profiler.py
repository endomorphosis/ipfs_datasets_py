"""Performance profiling tools for optimizer module.

Provides utilities for profiling optimizer methods, identifying hotspots,
and measuring optimization improvements.

Usage:
    >>> from ipfs_datasets_py.optimizers.common.performance_profiler import PerformanceProfiler
    >>> profiler = PerformanceProfiler()
    >>> profiler.profile_function(my_function, *args, **kwargs)
    >>> report = profiler.generate_report()
    >>> print(report)
"""

import cProfile
import pstats
import time
import io
from typing import Callable, Any, Dict, Iterator, List, Literal, Tuple, Optional, cast
from dataclasses import dataclass, field
from contextlib import contextmanager
import functools


@dataclass
class ProfileResult:
    """Result of profiling a function."""
    function_name: str
    total_time: float  # seconds
    call_count: int
    hotspots: List[Tuple[str, float, int]] = field(default_factory=list)  # (name, time, calls)
    
    @property
    def avg_time(self) -> float:
        """Average time per call."""
        return self.total_time / max(1, self.call_count)


class PerformanceProfiler:
    """Simple performance profiler for optimizer methods.
    
    Profiles Python code using cProfile and identifies hotspots that
    consume the most time.
    
    Example:
        >>> profiler = PerformanceProfiler()
        >>> profiler.profile_function(slow_function, arg1, arg2)
        >>> stats = profiler.get_stats()
        >>> hotspots = profiler.get_hotspots(top_n=5)
    """
    
    def __init__(self) -> None:
        self.profiler = cProfile.Profile()
        self.results: Dict[str, ProfileResult] = {}
    
    def profile_function(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """Profile a function and return its result.
        
        Args:
            func: Function to profile
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
            
        Returns:
            Result of function call
        """
        self.profiler.enable()
        try:
            result = func(*args, **kwargs)
        finally:
            self.profiler.disable()
        
        return result
    
    def profile_code_block(self, code_func: Callable[..., Any]) -> Any:
        """Profile a code block (lambda or function).
        
        Args:
            code_func: Callable that executes the code to profile
            
        Returns:
            Result of code execution
        """
        return self.profile_function(code_func)
    
    def get_stats(self, top_n: int = 20) -> List[Tuple[str, float, int]]:
        """Get top N functions by total time.
        
        Args:
            top_n: Number of top functions to return
            
        Returns:
            List of (function_name, total_time, call_count)
        """
        stream = io.StringIO()
        stats = pstats.Stats(self.profiler, stream=stream)
        stats.sort_stats('cumulative')
        
        # Extract info
        results = []
        stats_data = cast(
            Dict[Any, Tuple[int, int, float, float, Dict[Any, Any]]],
            getattr(stats, "stats", {}),
        )
        for func_name, (primitive_calls, num_calls, total_time, cumulative_time, callers) in stats_data.items():
            results.append((
                self._format_func_name(func_name),
                cumulative_time,
                num_calls
            ))
        
        # Sort by cumulative time and return top N
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_n]
    
    def get_hotspots(self, threshold_percent: float = 10.0, top_n: int = 5) -> List[Tuple[str, float, float]]:
        """Identify hotspots consuming >threshold_percent of time.
        
        Args:
            threshold_percent: Minimum percentage of total time to be considered a hotspot
            top_n: Maximum number of hotspots to return
            
        Returns:
            List of (function_name, time_seconds, percent_of_total)
        """
        stream = io.StringIO()
        stats = pstats.Stats(self.profiler, stream=stream)
        stats.sort_stats('cumulative')
        
        # Calculate total time
        stats_data = cast(
            Dict[Any, Tuple[int, int, float, float, Dict[Any, Any]]],
            getattr(stats, "stats", {}),
        )
        total_time = sum(
            stat[3] for stat in stats_data.values()
        )
        
        if total_time == 0:
            return []
        
        # Find hotspots
        hotspots = []
        for func_name, (primitive_calls, num_calls, total, cumulative_time, callers) in stats_data.items():
            percent = (cumulative_time / total_time) * 100
            if percent >= threshold_percent:
                hotspots.append((
                    self._format_func_name(func_name),
                    cumulative_time,
                    percent
                ))
        
        # Sort by time and return top N
        hotspots.sort(key=lambda x: x[1], reverse=True)
        return hotspots[:top_n]
    
    def generate_report(self, top_n: int = 10) -> str:
        """Generate a formatted profiling report.
        
        Args:
            top_n: Number of top functions to include
            
        Returns:
            Formatted profiling report
        """
        lines = [
            "=" * 80,
            "PERFORMANCE PROFILING REPORT",
            "=" * 80,
            "",
        ]
        
        # Top functions by time
        lines.append("TOP FUNCTIONS BY CUMULATIVE TIME")
        lines.append("-" * 80)
        lines.append(f"{'Function':<50} {'Time (s)':<15} {'Calls':<10}")
        lines.append("-" * 80)
        
        for func_name, total_time, call_count in self.get_stats(top_n=top_n):
            lines.append(f"{func_name:<50} {total_time:>10.4f}      {call_count:>8}")
        
        lines.append("")
        lines.append("HOTSPOTS (functions consuming >10% of time)")
        lines.append("-" * 80)
        lines.append(f"{'Function':<50} {'Time (s)':<15} {'% Total':<10}")
        lines.append("-" * 80)
        
        hotspots = self.get_hotspots(threshold_percent=0.0, top_n=10)
        for func_name, total_time, percent in hotspots:
            if percent >= 10.0:
                lines.append(f"{func_name:<50} {total_time:>10.4f}      {percent:>8.1f}%")
        
        lines.append("")
        return "\n".join(lines)
    
    @staticmethod
    def _format_func_name(func_info: Tuple[Any, ...]) -> str:
        """Format function name from profiler tuple."""
        if len(func_info) == 3:
            filename, line_num, func_name = func_info
            return f"{func_name}:{line_num}"
        return str(func_info)


class BenchmarkTimer:
    """Simple timer for benchmarking code blocks.
    
    Example:
        >>> timer = BenchmarkTimer("my operation")
        >>> with timer:
        ...     slow_operation()
        >>> print(timer.elapsed)
        1.234 seconds
    """
    
    def __init__(self, name: str = "operation"):
        self.name = name
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
    
    def __enter__(self) -> "BenchmarkTimer":
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> Literal[False]:
        self.end_time = time.perf_counter()
        return False
    
    @property
    def elapsed(self) -> float:
        """Elapsed time in seconds."""
        if self.start_time is None or self.end_time is None:
            return 0.0
        return self.end_time - self.start_time
    
    def __str__(self) -> str:
        return f"{self.name}: {self.elapsed:.4f}s"


def profile_decorator(
    profile_func: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to optionally profile a function.
    
    Args:
        profile_func: If True, profile the function
        
    Example:
        >>> @profile_decorator(profile_func=True)
        ... def my_function(x):
        ...     return x * 2
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if profile_func:
                profiler = PerformanceProfiler()
                result = profiler.profile_function(func, *args, **kwargs)
                print(profiler.generate_report())
                return result
            else:
                return func(*args, **kwargs)
        return wrapper
    return decorator


@contextmanager
def benchmark(name: str = "operation") -> Iterator[BenchmarkTimer]:
    """Context manager for timing code blocks.
    
    Example:
        >>> with benchmark("my operation"):
        ...     slow_operation()
    """
    timer = BenchmarkTimer(name)
    with timer:
        yield timer
    print(timer)

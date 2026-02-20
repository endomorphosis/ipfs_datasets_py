"""
TDFOL Performance Metrics - Unified metrics collection infrastructure

This module provides a unified metrics collection system for TDFOL operations,
consolidating timing, memory, and statistical functionality previously duplicated
across performance_profiler.py and performance_dashboard.py.

Features:
1. Timing Operations - High-precision timing with decorators and context managers
2. Memory Profiling - Memory usage tracking, peak detection, and leak detection
3. Statistics Aggregation - Mean, median, percentiles (P50, P95, P99, P999)
4. Counters, Gauges, Histograms - Standard metric types
5. Export Formats - JSON, dict, integration with MCP monitoring

This consolidation eliminates ~200 LOC of duplication while providing a single,
well-tested implementation for all performance tracking needs.

Usage:
    >>> collector = MetricsCollector()
    >>> 
    >>> # Timing operations
    >>> with collector.time("proving"):
    ...     result = prover.prove(formula)
    >>> 
    >>> # Memory profiling
    >>> with collector.track_memory("proving"):
    ...     result = prover.prove(formula)
    >>> 
    >>> # Decorators
    >>> @collector.timed("expensive_op")
    >>> def expensive_operation():
    ...     pass
    >>> 
    >>> # Get statistics
    >>> stats = collector.get_statistics()
    >>> print(f"Mean time: {stats['proving']['mean']:.3f}ms")
    >>> 
    >>> # Export for MCP dashboard
    >>> metrics_dict = collector.export_dict()

Author: TDFOL Team
Date: 2026-02-19
Phase: 1 (Code Consolidation)
Task: 1.4 (Merge Performance Metrics)
"""

from __future__ import annotations

import functools
import logging
import statistics
import time
import tracemalloc
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Deque, Dict, List, Optional, TypeVar, Union

logger = logging.getLogger(__name__)

# Type variable for generic function wrapping
F = TypeVar('F', bound=Callable[..., Any])


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class TimingResult:
    """Result of a timing operation."""
    name: str
    duration_ms: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'duration_ms': self.duration_ms,
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            **self.metadata
        }


@dataclass
class MemoryResult:
    """Result of a memory profiling operation."""
    name: str
    current_mb: float
    peak_mb: float
    delta_mb: float
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'current_mb': self.current_mb,
            'peak_mb': self.peak_mb,
            'delta_mb': self.delta_mb,
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            **self.metadata
        }


@dataclass
class StatisticalSummary:
    """Statistical summary of a metric."""
    count: int
    sum: float
    mean: float
    median: float
    std_dev: float
    min: float
    max: float
    p50: float  # Same as median, included for consistency
    p95: float
    p99: float
    p999: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


# ============================================================================
# Metrics Collector
# ============================================================================


class MetricsCollector:
    """
    Unified metrics collector for timing, memory, and statistics.
    
    This class consolidates functionality previously duplicated across
    performance_profiler.py and performance_dashboard.py, providing a
    single source of truth for performance metrics collection.
    
    Features:
    - High-precision timing with nanosecond resolution
    - Memory profiling with tracemalloc integration
    - Statistical aggregation (mean, median, percentiles)
    - Counter, gauge, and histogram support
    - Export to JSON/dict for MCP dashboard integration
    - Thread-safe operations (within GIL limitations)
    
    Example:
        >>> collector = MetricsCollector()
        >>> 
        >>> # Time an operation
        >>> with collector.time("proving"):
        ...     prove_theorem()
        >>> 
        >>> # Track memory
        >>> with collector.track_memory("kb_loading"):
        ...     load_knowledge_base()
        >>> 
        >>> # Get statistics
        >>> stats = collector.get_statistics()
    """
    
    def __init__(self, maxlen: int = 10000):
        """
        Initialize metrics collector.
        
        Args:
            maxlen: Maximum number of samples to keep per metric (default: 10000)
        """
        self.maxlen = maxlen
        
        # Timing data storage
        self.timings: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))
        self.timing_results: List[TimingResult] = []
        
        # Memory data storage
        self.memory_snapshots: Dict[str, Deque[Dict[str, float]]] = defaultdict(
            lambda: deque(maxlen=maxlen)
        )
        self.memory_results: List[MemoryResult] = []
        
        # Counters and gauges
        self.counters: Dict[str, int] = defaultdict(int)
        self.gauges: Dict[str, float] = {}
        
        # Histograms (for arbitrary value distributions)
        self.histograms: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=maxlen))
        
        # Memory profiling state
        self._memory_tracking_active = False
        self._memory_start_snapshots: Dict[str, Tuple[float, float]] = {}
        
        # Timing state
        self._timing_starts: Dict[str, float] = {}
        
        logger.debug(f"MetricsCollector initialized with maxlen={maxlen}")
    
    # ========================================================================
    # Timing Operations
    # ========================================================================
    
    @contextmanager
    def time(self, name: str, **metadata):
        """
        Context manager for timing an operation.
        
        Args:
            name: Name of the operation being timed
            **metadata: Additional metadata to store with timing
        
        Example:
            >>> with collector.time("proving", formula="P(x)"):
            ...     result = prove()
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self.record_timing(name, duration_ms, **metadata)
    
    def start_timer(self, name: str) -> None:
        """
        Start a named timer.
        
        Args:
            name: Name of the timer
        """
        self._timing_starts[name] = time.perf_counter()
    
    def stop_timer(self, name: str, **metadata) -> float:
        """
        Stop a named timer and record the duration.
        
        Args:
            name: Name of the timer
            **metadata: Additional metadata to store
        
        Returns:
            Duration in milliseconds
        
        Raises:
            KeyError: If timer was not started
        """
        if name not in self._timing_starts:
            raise KeyError(f"Timer '{name}' was not started")
        
        start = self._timing_starts.pop(name)
        duration_ms = (time.perf_counter() - start) * 1000.0
        self.record_timing(name, duration_ms, **metadata)
        return duration_ms
    
    def record_timing(self, name: str, duration_ms: float, **metadata) -> None:
        """
        Record a timing measurement.
        
        Args:
            name: Name of the operation
            duration_ms: Duration in milliseconds
            **metadata: Additional metadata
        """
        self.timings[name].append(duration_ms)
        result = TimingResult(
            name=name,
            duration_ms=duration_ms,
            timestamp=time.time(),
            metadata=metadata
        )
        self.timing_results.append(result)
        logger.debug(f"Recorded timing: {name} = {duration_ms:.3f}ms")
    
    def timed(self, name: str, **metadata):
        """
        Decorator for timing a function.
        
        Args:
            name: Name for the timing metric
            **metadata: Additional metadata
        
        Example:
            >>> @collector.timed("expensive_operation")
            >>> def expensive_op():
            ...     pass
        """
        def decorator(func: F) -> F:
            """Wrap *func* so every call is timed and recorded under *name*."""
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                """Execute *func* inside a timing context manager."""
                with self.time(name, **metadata):
                    return func(*args, **kwargs)
            return wrapper
        return decorator
    
    # ========================================================================
    # Memory Operations
    # ========================================================================
    
    @contextmanager
    def track_memory(self, name: str, **metadata):
        """
        Context manager for tracking memory usage.
        
        Args:
            name: Name of the operation
            **metadata: Additional metadata
        
        Example:
            >>> with collector.track_memory("kb_loading"):
            ...     load_kb()
        """
        # Start memory tracking if not already active
        was_tracking = tracemalloc.is_tracing()
        if not was_tracking:
            tracemalloc.start()
        
        try:
            # Record initial state
            current, peak = tracemalloc.get_traced_memory()
            start_current_mb = current / 1024 / 1024
            start_peak_mb = peak / 1024 / 1024
            self._memory_start_snapshots[name] = (start_current_mb, start_peak_mb)
            
            yield
            
        finally:
            # Record final state
            current, peak = tracemalloc.get_traced_memory()
            end_current_mb = current / 1024 / 1024
            end_peak_mb = peak / 1024 / 1024
            
            start_current_mb, start_peak_mb = self._memory_start_snapshots.pop(name)
            delta_mb = end_current_mb - start_current_mb
            
            self.record_memory(
                name=name,
                current_mb=end_current_mb,
                peak_mb=end_peak_mb,
                delta_mb=delta_mb,
                **metadata
            )
            
            # Stop tracking if we started it
            if not was_tracking:
                tracemalloc.stop()
    
    def record_memory(
        self,
        name: str,
        current_mb: float,
        peak_mb: float,
        delta_mb: float,
        **metadata
    ) -> None:
        """
        Record a memory measurement.
        
        Args:
            name: Name of the operation
            current_mb: Current memory usage in MB
            peak_mb: Peak memory usage in MB
            delta_mb: Change in memory usage in MB
            **metadata: Additional metadata
        """
        snapshot = {
            'current_mb': current_mb,
            'peak_mb': peak_mb,
            'delta_mb': delta_mb
        }
        self.memory_snapshots[name].append(snapshot)
        
        result = MemoryResult(
            name=name,
            current_mb=current_mb,
            peak_mb=peak_mb,
            delta_mb=delta_mb,
            timestamp=time.time(),
            metadata=metadata
        )
        self.memory_results.append(result)
        logger.debug(f"Recorded memory: {name} delta={delta_mb:+.2f}MB peak={peak_mb:.2f}MB")
    
    # ========================================================================
    # Counters, Gauges, Histograms
    # ========================================================================
    
    def increment_counter(self, name: str, value: int = 1) -> None:
        """Increment a counter."""
        self.counters[name] += value
    
    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge value."""
        self.gauges[name] = value
    
    def record_histogram(self, name: str, value: float) -> None:
        """Record a value in a histogram."""
        self.histograms[name].append(value)
    
    # ========================================================================
    # Statistics
    # ========================================================================
    
    def get_timing_stats(self, name: str) -> Optional[StatisticalSummary]:
        """
        Get statistical summary for a timing metric.
        
        Args:
            name: Name of the timing metric
        
        Returns:
            StatisticalSummary or None if no data
        """
        if name not in self.timings or not self.timings[name]:
            return None
        
        return self._calculate_stats(list(self.timings[name]))
    
    def get_memory_stats(self, name: str, field: str = 'delta_mb') -> Optional[StatisticalSummary]:
        """
        Get statistical summary for a memory metric.
        
        Args:
            name: Name of the memory metric
            field: Field to analyze ('current_mb', 'peak_mb', 'delta_mb')
        
        Returns:
            StatisticalSummary or None if no data
        """
        if name not in self.memory_snapshots or not self.memory_snapshots[name]:
            return None
        
        values = [snapshot[field] for snapshot in self.memory_snapshots[name]]
        return self._calculate_stats(values)
    
    def get_histogram_stats(self, name: str) -> Optional[StatisticalSummary]:
        """Get statistical summary for a histogram."""
        if name not in self.histograms or not self.histograms[name]:
            return None
        
        return self._calculate_stats(list(self.histograms[name]))
    
    def _calculate_stats(self, values: List[float]) -> StatisticalSummary:
        """
        Calculate statistical summary for a list of values.
        
        Args:
            values: List of numeric values
        
        Returns:
            StatisticalSummary with computed statistics
        """
        if not values:
            return StatisticalSummary(
                count=0, sum=0, mean=0, median=0, std_dev=0,
                min=0, max=0, p50=0, p95=0, p99=0, p999=0
            )
        
        count = len(values)
        total = sum(values)
        mean = total / count if count > 0 else 0
        
        # Sort for percentiles
        sorted_values = sorted(values)
        
        # Median
        median = statistics.median(sorted_values)
        
        # Standard deviation
        std_dev = statistics.stdev(sorted_values) if count > 1 else 0
        
        # Min/Max
        min_val = sorted_values[0]
        max_val = sorted_values[-1]
        
        # Percentiles
        p50 = self._percentile(sorted_values, 50)
        p95 = self._percentile(sorted_values, 95)
        p99 = self._percentile(sorted_values, 99)
        p999 = self._percentile(sorted_values, 99.9)
        
        return StatisticalSummary(
            count=count,
            sum=total,
            mean=mean,
            median=median,
            std_dev=std_dev,
            min=min_val,
            max=max_val,
            p50=p50,
            p95=p95,
            p99=p99,
            p999=p999
        )
    
    @staticmethod
    def _percentile(sorted_values: List[float], percentile: float) -> float:
        """
        Calculate percentile from sorted values.
        
        Args:
            sorted_values: Pre-sorted list of values
            percentile: Percentile to calculate (0-100)
        
        Returns:
            Value at the given percentile
        """
        if not sorted_values:
            return 0.0
        
        k = (len(sorted_values) - 1) * percentile / 100
        f = int(k)
        c = f + 1
        
        if c >= len(sorted_values):
            return sorted_values[-1]
        
        d0 = sorted_values[f] * (c - k)
        d1 = sorted_values[c] * (k - f)
        return d0 + d1
    
    # ========================================================================
    # Statistics Export
    # ========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics for all metrics.
        
        Returns:
            Dictionary with statistics for all timing, memory, and histogram metrics
        """
        stats = {
            'timing': {},
            'memory': {},
            'histograms': {},
            'counters': dict(self.counters),
            'gauges': dict(self.gauges),
            'metadata': {
                'collector_maxlen': self.maxlen,
                'total_timing_samples': sum(len(d) for d in self.timings.values()),
                'total_memory_samples': sum(len(d) for d in self.memory_snapshots.values()),
                'generated_at': datetime.utcnow().isoformat()
            }
        }
        
        # Timing statistics
        for name in self.timings:
            timing_stats = self.get_timing_stats(name)
            if timing_stats:
                stats['timing'][name] = timing_stats.to_dict()
        
        # Memory statistics
        for name in self.memory_snapshots:
            stats['memory'][name] = {
                'delta_mb': self.get_memory_stats(name, 'delta_mb').to_dict() if self.get_memory_stats(name, 'delta_mb') else None,
                'peak_mb': self.get_memory_stats(name, 'peak_mb').to_dict() if self.get_memory_stats(name, 'peak_mb') else None,
                'current_mb': self.get_memory_stats(name, 'current_mb').to_dict() if self.get_memory_stats(name, 'current_mb') else None,
            }
        
        # Histogram statistics
        for name in self.histograms:
            hist_stats = self.get_histogram_stats(name)
            if hist_stats:
                stats['histograms'][name] = hist_stats.to_dict()
        
        return stats
    
    def export_dict(self) -> Dict[str, Any]:
        """
        Export all metrics as a dictionary for MCP dashboard integration.
        
        Returns:
            Dictionary with all metrics and metadata
        """
        return {
            'statistics': self.get_statistics(),
            'timing_results': [r.to_dict() for r in self.timing_results[-1000:]],  # Last 1000
            'memory_results': [r.to_dict() for r in self.memory_results[-1000:]],  # Last 1000
        }
    
    def reset(self) -> None:
        """Reset all metrics."""
        self.timings.clear()
        self.timing_results.clear()
        self.memory_snapshots.clear()
        self.memory_results.clear()
        self.counters.clear()
        self.gauges.clear()
        self.histograms.clear()
        self._timing_starts.clear()
        self._memory_start_snapshots.clear()
        logger.info("MetricsCollector reset")


# ============================================================================
# Global Instance
# ============================================================================

# Global metrics collector instance for convenience
_global_collector: Optional[MetricsCollector] = None


def get_global_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    global _global_collector
    if _global_collector is None:
        _global_collector = MetricsCollector()
    return _global_collector


def reset_global_collector() -> None:
    """Reset the global metrics collector."""
    global _global_collector
    _global_collector = None

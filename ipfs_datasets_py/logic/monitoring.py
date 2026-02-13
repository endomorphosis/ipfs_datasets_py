"""
Production monitoring and observability for logic modules.

This module provides comprehensive monitoring, metrics collection, and
observability features for production deployments.

Features:
- Real-time metrics collection
- Performance monitoring
- Error tracking and alerting
- Health checks
- Prometheus metrics export
- Custom dashboards

Example:
    >>> from ipfs_datasets_py.logic.monitoring import LogicMonitor
    >>> 
    >>> monitor = LogicMonitor()
    >>> 
    >>> # Track operations
    >>> with monitor.track_operation("fol_conversion"):
    ...     result = convert_text_to_fol(text)
    >>> 
    >>> # Get metrics
    >>> metrics = monitor.get_metrics()
    >>> print(f"Success rate: {metrics['success_rate']:.1%}")
"""

import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Callable
from collections import defaultdict, deque
from contextlib import contextmanager
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics collected."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class OperationMetrics:
    """
    Metrics for a specific operation type.
    
    Attributes:
        total_count: Total number of operations
        success_count: Number of successful operations
        failure_count: Number of failed operations
        total_time: Total execution time in seconds
        min_time: Minimum execution time
        max_time: Maximum execution time
        recent_times: Recent execution times (for moving average)
    """
    total_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    recent_times: deque = field(default_factory=lambda: deque(maxlen=100))
    
    def record(self, success: bool, duration: float) -> None:
        """Record an operation."""
        self.total_count += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        
        self.total_time += duration
        self.min_time = min(self.min_time, duration)
        self.max_time = max(self.max_time, duration)
        self.recent_times.append(duration)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.total_count == 0:
            return 0.0
        return self.success_count / self.total_count
    
    @property
    def avg_time(self) -> float:
        """Calculate average execution time."""
        if self.total_count == 0:
            return 0.0
        return self.total_time / self.total_count
    
    @property
    def recent_avg_time(self) -> float:
        """Calculate recent average time (last 100 operations)."""
        if not self.recent_times:
            return 0.0
        return sum(self.recent_times) / len(self.recent_times)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'total_count': self.total_count,
            'success_count': self.success_count,
            'failure_count': self.failure_count,
            'success_rate': self.success_rate,
            'avg_time': self.avg_time,
            'recent_avg_time': self.recent_avg_time,
            'min_time': self.min_time if self.min_time != float('inf') else 0.0,
            'max_time': self.max_time
        }


class LogicMonitor:
    """
    Production monitoring system for logic modules.
    
    Provides comprehensive metrics collection, health checks, and
    observability features for production deployments.
    
    Features:
        - Operation tracking with timing
        - Success/failure rate monitoring
        - Performance metrics (latency, throughput)
        - Error tracking and categorization
        - Health check integration
        - Prometheus metrics export
    
    Args:
        window_size: Size of sliding window for recent metrics (default: 100)
        enable_prometheus: Enable Prometheus metrics export (default: False)
    
    Example:
        >>> monitor = LogicMonitor()
        >>> 
        >>> # Track operation
        >>> with monitor.track_operation("fol_conversion") as ctx:
        ...     result = convert_text_to_fol(text)
        ...     ctx.success = result is not None
        >>> 
        >>> # Get metrics
        >>> metrics = monitor.get_metrics()
    """
    
    def __init__(
        self,
        window_size: int = 100,
        enable_prometheus: bool = False
    ):
        """Initialize monitoring system."""
        self.window_size = window_size
        self.enable_prometheus = enable_prometheus
        
        # Metrics storage
        self._operations: Dict[str, OperationMetrics] = defaultdict(OperationMetrics)
        self._errors: Dict[str, int] = defaultdict(int)
        self._warnings: Dict[str, int] = defaultdict(int)
        
        # Thread safety
        self._lock = threading.RLock()
        
        # System info
        self._start_time = time.time()
        self._last_health_check = time.time()
        
        logger.info("Logic monitoring initialized")
    
    @contextmanager
    def track_operation(self, operation: str):
        """
        Context manager for tracking operations.
        
        Args:
            operation: Name of the operation to track
        
        Yields:
            Context object with success attribute
        
        Example:
            >>> with monitor.track_operation("prove_formula") as ctx:
            ...     result = prove(formula)
            ...     ctx.success = result.status == "theorem"
        """
        start_time = time.time()
        
        class TrackingContext:
            def __init__(self):
                self.success = True
        
        ctx = TrackingContext()
        
        try:
            yield ctx
        except Exception as e:
            ctx.success = False
            self.record_error(operation, str(e))
            raise
        finally:
            duration = time.time() - start_time
            with self._lock:
                self._operations[operation].record(ctx.success, duration)
    
    def record_operation(
        self,
        operation: str,
        success: bool,
        duration: float
    ) -> None:
        """
        Manually record an operation.
        
        Args:
            operation: Operation name
            success: Whether operation succeeded
            duration: Execution time in seconds
        
        Example:
            >>> monitor.record_operation("cache_hit", True, 0.001)
        """
        with self._lock:
            self._operations[operation].record(success, duration)
    
    def record_error(self, category: str, message: str) -> None:
        """
        Record an error.
        
        Args:
            category: Error category
            message: Error message
        """
        with self._lock:
            self._errors[f"{category}: {message[:50]}"] += 1
        logger.error(f"[{category}] {message}")
    
    def record_warning(self, category: str, message: str) -> None:
        """
        Record a warning.
        
        Args:
            category: Warning category
            message: Warning message
        """
        with self._lock:
            self._warnings[f"{category}: {message[:50]}"] += 1
        logger.warning(f"[{category}] {message}")
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get all collected metrics.
        
        Returns:
            Dictionary containing all metrics
        
        Example:
            >>> metrics = monitor.get_metrics()
            >>> print(f"Operations: {metrics['operations']}")
        """
        with self._lock:
            return {
                'system': self._get_system_metrics(),
                'operations': {
                    name: metrics.to_dict()
                    for name, metrics in self._operations.items()
                },
                'errors': dict(self._errors),
                'warnings': dict(self._warnings),
                'health': self.health_check()
            }
    
    def _get_system_metrics(self) -> Dict[str, Any]:
        """Get system-level metrics."""
        uptime = time.time() - self._start_time
        
        # Calculate aggregate statistics
        total_ops = sum(m.total_count for m in self._operations.values())
        total_successes = sum(m.success_count for m in self._operations.values())
        total_failures = sum(m.failure_count for m in self._operations.values())
        
        return {
            'uptime_seconds': uptime,
            'total_operations': total_ops,
            'total_successes': total_successes,
            'total_failures': total_failures,
            'overall_success_rate': total_successes / total_ops if total_ops > 0 else 0.0,
            'total_errors': sum(self._errors.values()),
            'total_warnings': sum(self._warnings.values())
        }
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform health check.
        
        Returns:
            Health check results
        
        Example:
            >>> health = monitor.health_check()
            >>> if health['status'] == 'healthy':
            ...     print("System is healthy")
        """
        self._last_health_check = time.time()
        
        with self._lock:
            # Calculate health metrics
            total_ops = sum(m.total_count for m in self._operations.values())
            
            if total_ops == 0:
                return {
                    'status': 'unknown',
                    'message': 'No operations recorded yet',
                    'timestamp': self._last_health_check
                }
            
            success_rate = sum(m.success_count for m in self._operations.values()) / total_ops
            error_count = sum(self._errors.values())
            
            # Determine health status
            if success_rate >= 0.95 and error_count < 10:
                status = 'healthy'
                message = 'System operating normally'
            elif success_rate >= 0.80:
                status = 'degraded'
                message = f'Success rate: {success_rate:.1%}, may need attention'
            else:
                status = 'unhealthy'
                message = f'Success rate: {success_rate:.1%}, immediate attention required'
            
            return {
                'status': status,
                'message': message,
                'success_rate': success_rate,
                'error_count': error_count,
                'warning_count': sum(self._warnings.values()),
                'timestamp': self._last_health_check
            }
    
    def get_prometheus_metrics(self) -> str:
        """
        Export metrics in Prometheus format.
        
        Returns:
            Prometheus-formatted metrics string
        
        Example:
            >>> prometheus_data = monitor.get_prometheus_metrics()
        """
        if not self.enable_prometheus:
            return ""
        
        lines = []
        
        with self._lock:
            # System metrics
            system = self._get_system_metrics()
            lines.append(f"# HELP logic_uptime_seconds System uptime in seconds")
            lines.append(f"# TYPE logic_uptime_seconds gauge")
            lines.append(f"logic_uptime_seconds {system['uptime_seconds']}")
            
            lines.append(f"# HELP logic_operations_total Total operations")
            lines.append(f"# TYPE logic_operations_total counter")
            lines.append(f"logic_operations_total {system['total_operations']}")
            
            # Operation metrics
            for name, metrics in self._operations.items():
                safe_name = name.replace('-', '_').replace('.', '_')
                
                lines.append(f"# HELP logic_operation_{safe_name}_total Total count")
                lines.append(f"# TYPE logic_operation_{safe_name}_total counter")
                lines.append(f"logic_operation_{safe_name}_total {metrics.total_count}")
                
                lines.append(f"# HELP logic_operation_{safe_name}_success Success count")
                lines.append(f"# TYPE logic_operation_{safe_name}_success counter")
                lines.append(f"logic_operation_{safe_name}_success {metrics.success_count}")
                
                lines.append(f"# HELP logic_operation_{safe_name}_duration_seconds Operation duration")
                lines.append(f"# TYPE logic_operation_{safe_name}_duration_seconds summary")
                lines.append(f"logic_operation_{safe_name}_duration_seconds_sum {metrics.total_time}")
                lines.append(f"logic_operation_{safe_name}_duration_seconds_count {metrics.total_count}")
        
        return '\n'.join(lines)
    
    def reset_metrics(self) -> None:
        """Reset all collected metrics."""
        with self._lock:
            self._operations.clear()
            self._errors.clear()
            self._warnings.clear()
            self._start_time = time.time()
        logger.info("Metrics reset")
    
    def get_operation_summary(self, operation: str) -> Optional[Dict[str, Any]]:
        """
        Get summary for specific operation.
        
        Args:
            operation: Operation name
        
        Returns:
            Operation metrics dictionary or None if not found
        """
        with self._lock:
            if operation in self._operations:
                return self._operations[operation].to_dict()
        return None


# Global monitor instance
_global_monitor: Optional[LogicMonitor] = None


def get_global_monitor(
    window_size: int = 100,
    enable_prometheus: bool = False
) -> LogicMonitor:
    """
    Get or create the global monitor instance.
    
    Args:
        window_size: Sliding window size
        enable_prometheus: Enable Prometheus export
    
    Returns:
        Global LogicMonitor instance
    
    Example:
        >>> monitor = get_global_monitor()
        >>> with monitor.track_operation("test"):
        ...     pass
    """
    global _global_monitor
    
    if _global_monitor is None:
        _global_monitor = LogicMonitor(
            window_size=window_size,
            enable_prometheus=enable_prometheus
        )
    
    return _global_monitor

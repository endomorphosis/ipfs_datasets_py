"""
Health monitoring system for processors.

This module provides health checks, status tracking, and monitoring
for individual processors and the overall system.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional, Literal
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """
    Health status levels.
    
    - HEALTHY: Operating normally (success rate >= 95%)
    - DEGRADED: Experiencing issues (success rate 80-95%)
    - UNHEALTHY: Failing frequently (success rate < 80%)
    - UNKNOWN: No data available
    """
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ProcessorHealth:
    """
    Health status of a processor.
    
    Attributes:
        name: Processor name
        status: Health status (healthy, degraded, unhealthy)
        last_success: Timestamp of last successful operation
        last_failure: Timestamp of last failed operation
        success_rate: Success rate (0.0-1.0)
        avg_processing_time: Average processing time in seconds
        total_calls: Total number of calls
        successful_calls: Number of successful calls
        failed_calls: Number of failed calls
        error_count: Number of errors in recent window
        warning_count: Number of warnings
        last_error: Most recent error message
    """
    name: str
    status: HealthStatus = HealthStatus.UNKNOWN
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    success_rate: float = 0.0
    avg_processing_time: float = 0.0
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    error_count: int = 0
    warning_count: int = 0
    last_error: Optional[str] = None
    
    def is_healthy(self) -> bool:
        """Check if processor is healthy."""
        return self.status == HealthStatus.HEALTHY
    
    def is_degraded(self) -> bool:
        """Check if processor is degraded."""
        return self.status == HealthStatus.DEGRADED
    
    def is_unhealthy(self) -> bool:
        """Check if processor is unhealthy."""
        return self.status == HealthStatus.UNHEALTHY
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'status': self.status.value,
            'last_success': self.last_success.isoformat() if self.last_success else None,
            'last_failure': self.last_failure.isoformat() if self.last_failure else None,
            'success_rate': round(self.success_rate, 3),
            'avg_processing_time': round(self.avg_processing_time, 3),
            'total_calls': self.total_calls,
            'successful_calls': self.successful_calls,
            'failed_calls': self.failed_calls,
            'error_count': self.error_count,
            'warning_count': self.warning_count,
            'last_error': self.last_error
        }


@dataclass
class SystemHealth:
    """
    Overall system health.
    
    Attributes:
        status: Overall system status
        processor_count: Total number of processors
        healthy_count: Number of healthy processors
        degraded_count: Number of degraded processors
        unhealthy_count: Number of unhealthy processors
        overall_success_rate: Overall success rate across all processors
        processor_health: Health status of individual processors
    """
    status: HealthStatus
    processor_count: int
    healthy_count: int
    degraded_count: int
    unhealthy_count: int
    overall_success_rate: float
    processor_health: dict[str, ProcessorHealth] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'status': self.status.value,
            'processor_count': self.processor_count,
            'healthy_count': self.healthy_count,
            'degraded_count': self.degraded_count,
            'unhealthy_count': self.unhealthy_count,
            'overall_success_rate': round(self.overall_success_rate, 3),
            'processors': {
                name: health.to_dict()
                for name, health in self.processor_health.items()
            }
        }


class HealthMonitor:
    """
    Monitor processor health and system status.
    
    Tracks success rates, error counts, and performance metrics
    for individual processors and overall system health.
    
    Example:
        >>> monitor = HealthMonitor(registry)
        >>> health = monitor.check_processor_health("PDFProcessorAdapter")
        >>> if health.is_unhealthy():
        ...     logger.error(f"Processor unhealthy: {health.name}")
        >>> 
        >>> system_health = monitor.check_system_health()
        >>> print(f"System status: {system_health.status.value}")
    """
    
    def __init__(self, registry):
        """
        Initialize health monitor.
        
        Args:
            registry: ProcessorRegistry instance
        """
        self.registry = registry
        self._health_history: dict[str, list[ProcessorHealth]] = {}
    
    def check_processor_health(
        self,
        processor_name: str,
        window_seconds: int = 300
    ) -> ProcessorHealth:
        """
        Check health of specific processor.
        
        Args:
            processor_name: Name of processor to check
            window_seconds: Time window for error counting
            
        Returns:
            ProcessorHealth object
        """
        # Get statistics from registry
        stats = self.registry.get_statistics().get(processor_name, {})
        
        if not stats:
            return ProcessorHealth(
                name=processor_name,
                status=HealthStatus.UNKNOWN
            )
        
        # Calculate success rate
        total_calls = stats.get('calls', 0)
        successes = stats.get('successes', 0)
        failures = stats.get('failures', 0)
        
        if total_calls > 0:
            success_rate = successes / total_calls
        else:
            success_rate = 0.0
        
        # Determine status based on success rate
        if success_rate >= 0.95:
            status = HealthStatus.HEALTHY
        elif success_rate >= 0.80:
            status = HealthStatus.DEGRADED
        elif total_calls > 0:
            status = HealthStatus.UNHEALTHY
        else:
            status = HealthStatus.UNKNOWN
        
        # Calculate average processing time
        total_time = stats.get('total_time_seconds', 0.0)
        avg_time = total_time / total_calls if total_calls > 0 else 0.0
        
        health = ProcessorHealth(
            name=processor_name,
            status=status,
            success_rate=success_rate,
            avg_processing_time=avg_time,
            total_calls=total_calls,
            successful_calls=successes,
            failed_calls=failures,
            error_count=failures  # Simplified for now
        )
        
        # Store in history
        if processor_name not in self._health_history:
            self._health_history[processor_name] = []
        self._health_history[processor_name].append(health)
        
        # Keep only recent history (last 100 checks)
        if len(self._health_history[processor_name]) > 100:
            self._health_history[processor_name] = self._health_history[processor_name][-100:]
        
        return health
    
    def check_system_health(self) -> SystemHealth:
        """
        Check overall system health.
        
        Returns:
            SystemHealth object with aggregated health status
        """
        # Get all processor names
        processor_info = self.registry.list_processors()
        processor_names = list(processor_info.keys())
        
        # Check each processor
        processor_health = {}
        healthy_count = 0
        degraded_count = 0
        unhealthy_count = 0
        unknown_count = 0
        
        total_successes = 0
        total_calls = 0
        
        for name in processor_names:
            health = self.check_processor_health(name)
            processor_health[name] = health
            
            if health.status == HealthStatus.HEALTHY:
                healthy_count += 1
            elif health.status == HealthStatus.DEGRADED:
                degraded_count += 1
            elif health.status == HealthStatus.UNHEALTHY:
                unhealthy_count += 1
            else:
                unknown_count += 1
            
            total_successes += health.successful_calls
            total_calls += health.total_calls
        
        # Calculate overall success rate
        overall_success_rate = total_successes / total_calls if total_calls > 0 else 0.0
        
        # Determine overall system status
        if unhealthy_count > 0 or degraded_count > len(processor_names) / 2:
            system_status = HealthStatus.UNHEALTHY
        elif degraded_count > 0:
            system_status = HealthStatus.DEGRADED
        elif healthy_count > 0:
            system_status = HealthStatus.HEALTHY
        else:
            system_status = HealthStatus.UNKNOWN
        
        return SystemHealth(
            status=system_status,
            processor_count=len(processor_names),
            healthy_count=healthy_count,
            degraded_count=degraded_count,
            unhealthy_count=unhealthy_count,
            overall_success_rate=overall_success_rate,
            processor_health=processor_health
        )
    
    def get_health_report(self, format: Literal["text", "json"] = "text") -> str:
        """
        Generate health report.
        
        Args:
            format: Output format ("text" or "json")
            
        Returns:
            Formatted health report
        """
        system_health = self.check_system_health()
        
        if format == "json":
            import json
            return json.dumps(system_health.to_dict(), indent=2)
        
        # Text format
        lines = []
        lines.append("=" * 70)
        lines.append("PROCESSOR HEALTH REPORT")
        lines.append("=" * 70)
        lines.append(f"System Status: {system_health.status.value.upper()}")
        lines.append(f"Overall Success Rate: {system_health.overall_success_rate:.1%}")
        lines.append("")
        lines.append(f"Processors: {system_health.processor_count}")
        lines.append(f"  Healthy:   {system_health.healthy_count}")
        lines.append(f"  Degraded:  {system_health.degraded_count}")
        lines.append(f"  Unhealthy: {system_health.unhealthy_count}")
        lines.append("")
        lines.append("Individual Processor Status:")
        lines.append("-" * 70)
        
        for name, health in system_health.processor_health.items():
            status_symbol = {
                HealthStatus.HEALTHY: "✓",
                HealthStatus.DEGRADED: "⚠",
                HealthStatus.UNHEALTHY: "✗",
                HealthStatus.UNKNOWN: "?"
            }.get(health.status, "?")
            
            lines.append(
                f"{status_symbol} {name:30s} | "
                f"Success: {health.success_rate:5.1%} | "
                f"Calls: {health.total_calls:5d} | "
                f"Avg: {health.avg_processing_time:.2f}s"
            )
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def get_unhealthy_processors(self) -> list[ProcessorHealth]:
        """
        Get list of unhealthy processors.
        
        Returns:
            List of ProcessorHealth objects for unhealthy processors
        """
        system_health = self.check_system_health()
        return [
            health for health in system_health.processor_health.values()
            if health.is_unhealthy()
        ]
    
    def get_degraded_processors(self) -> list[ProcessorHealth]:
        """
        Get list of degraded processors.
        
        Returns:
            List of ProcessorHealth objects for degraded processors
        """
        system_health = self.check_system_health()
        return [
            health for health in system_health.processor_health.values()
            if health.is_degraded()
        ]


# Global metrics storage for @monitor decorator
_PROCESSOR_METRICS: dict[str, dict] = {}


def monitor(func):
    """
    Decorator to monitor processor method execution.
    
    Automatically tracks:
    - Execution time (latency)
    - Success/failure counts
    - Error messages
    - Call frequency
    
    Supports both sync and async functions.
    
    Usage:
        >>> @monitor
        ... async def process_document(self, doc):
        ...     return await self._process(doc)
        
        >>> @monitor
        ... def process_sync(self, doc):
        ...     return self._process(doc)
    
    The decorator extracts the processor name from the class and method,
    and records metrics that can be queried via get_processor_metrics().
    """
    import functools
    import time
    import inspect
    from datetime import datetime
    
    # Check if the function is async
    is_async = inspect.iscoroutinefunction(func)
    
    if is_async:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Extract processor name (class.method)
            if args and hasattr(args[0], '__class__'):
                processor_name = f"{args[0].__class__.__name__}.{func.__name__}"
            else:
                processor_name = func.__name__
            
            # Initialize metrics if needed
            if processor_name not in _PROCESSOR_METRICS:
                _PROCESSOR_METRICS[processor_name] = {
                    'total_calls': 0,
                    'successful_calls': 0,
                    'failed_calls': 0,
                    'total_time': 0.0,
                    'last_success': None,
                    'last_failure': None,
                    'last_error': None,
                    'errors': []
                }
            
            metrics = _PROCESSOR_METRICS[processor_name]
            metrics['total_calls'] += 1
            
            start_time = time.time()
            error_occurred = False
            error_msg = None
            
            try:
                result = await func(*args, **kwargs)
                metrics['successful_calls'] += 1
                metrics['last_success'] = datetime.now()
                return result
            except Exception as e:
                error_occurred = True
                error_msg = str(e)
                metrics['failed_calls'] += 1
                metrics['last_failure'] = datetime.now()
                metrics['last_error'] = error_msg
                metrics['errors'].append({
                    'timestamp': datetime.now().isoformat(),
                    'error': error_msg
                })
                # Keep only last 10 errors
                if len(metrics['errors']) > 10:
                    metrics['errors'] = metrics['errors'][-10:]
                raise
            finally:
                elapsed = time.time() - start_time
                metrics['total_time'] += elapsed
                
                # Log if slow (>5 seconds)
                if elapsed > 5.0:
                    logger.warning(
                        f"{processor_name} took {elapsed:.2f}s "
                        f"({'failed' if error_occurred else 'succeeded'})"
                    )
        
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Extract processor name (class.method)
            if args and hasattr(args[0], '__class__'):
                processor_name = f"{args[0].__class__.__name__}.{func.__name__}"
            else:
                processor_name = func.__name__
            
            # Initialize metrics if needed
            if processor_name not in _PROCESSOR_METRICS:
                _PROCESSOR_METRICS[processor_name] = {
                    'total_calls': 0,
                    'successful_calls': 0,
                    'failed_calls': 0,
                    'total_time': 0.0,
                    'last_success': None,
                    'last_failure': None,
                    'last_error': None,
                    'errors': []
                }
            
            metrics = _PROCESSOR_METRICS[processor_name]
            metrics['total_calls'] += 1
            
            start_time = time.time()
            error_occurred = False
            error_msg = None
            
            try:
                result = func(*args, **kwargs)
                metrics['successful_calls'] += 1
                metrics['last_success'] = datetime.now()
                return result
            except Exception as e:
                error_occurred = True
                error_msg = str(e)
                metrics['failed_calls'] += 1
                metrics['last_failure'] = datetime.now()
                metrics['last_error'] = error_msg
                metrics['errors'].append({
                    'timestamp': datetime.now().isoformat(),
                    'error': error_msg
                })
                # Keep only last 10 errors
                if len(metrics['errors']) > 10:
                    metrics['errors'] = metrics['errors'][-10:]
                raise
            finally:
                elapsed = time.time() - start_time
                metrics['total_time'] += elapsed
                
                # Log if slow (>5 seconds)
                if elapsed > 5.0:
                    logger.warning(
                        f"{processor_name} took {elapsed:.2f}s "
                        f"({'failed' if error_occurred else 'succeeded'})"
                    )
        
        return sync_wrapper


def get_processor_metrics(processor_name: Optional[str] = None) -> dict:
    """
    Get metrics for monitored processors.
    
    Args:
        processor_name: Specific processor name, or None for all
        
    Returns:
        Dictionary of metrics
    """
    if processor_name:
        return _PROCESSOR_METRICS.get(processor_name, {})
    return _PROCESSOR_METRICS.copy()


def reset_processor_metrics(processor_name: Optional[str] = None):
    """
    Reset metrics for monitored processors.
    
    Args:
        processor_name: Specific processor name, or None for all
    """
    if processor_name:
        if processor_name in _PROCESSOR_METRICS:
            del _PROCESSOR_METRICS[processor_name]
    else:
        _PROCESSOR_METRICS.clear()


def get_monitoring_summary() -> dict:
    """
    Get summary of all monitored processors.
    
    Returns:
        Dictionary with summary statistics
    """
    summary = {
        'total_processors': len(_PROCESSOR_METRICS),
        'total_calls': sum(m['total_calls'] for m in _PROCESSOR_METRICS.values()),
        'total_successes': sum(m['successful_calls'] for m in _PROCESSOR_METRICS.values()),
        'total_failures': sum(m['failed_calls'] for m in _PROCESSOR_METRICS.values()),
        'processors': {}
    }
    
    for name, metrics in _PROCESSOR_METRICS.items():
        total = metrics['total_calls']
        success_rate = metrics['successful_calls'] / total if total > 0 else 0.0
        avg_time = metrics['total_time'] / total if total > 0 else 0.0
        
        summary['processors'][name] = {
            'calls': total,
            'success_rate': round(success_rate, 3),
            'avg_time': round(avg_time, 3),
            'last_error': metrics['last_error']
        }
    
    return summary

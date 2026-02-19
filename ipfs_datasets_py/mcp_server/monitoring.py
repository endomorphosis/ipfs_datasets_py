# ipfs_datasets_py/mcp_server/monitoring.py

import anyio
import inspect
import time
import logging
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Union, AsyncGenerator
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from .exceptions import HealthCheckError, MonitoringError, MetricsCollectionError

logger = logging.getLogger(__name__)

@dataclass
class MetricData:
    """Container for metric data with timestamp and labels."""
    value: Union[float, int]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    labels: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class HealthCheckResult:
    """Result of a health check with detailed information."""
    component: str
    status: str  # 'healthy', 'warning', 'critical', 'unknown'
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = field(default_factory=dict)
    response_time_ms: Optional[float] = None

@dataclass
class PerformanceSnapshot:
    """Snapshot of performance metrics."""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    disk_percent: float
    active_connections: int
    request_rate: float
    error_rate: float
    avg_response_time_ms: float

class EnhancedMetricsCollector:
    """
    Enhanced metrics collector with advanced monitoring capabilities.
    Provides comprehensive performance tracking, health monitoring, and alerting.
    """
    
    def __init__(self, enabled: bool = True, retention_hours: int = 24) -> None:
        """Initialise the metrics collector with optional retention settings.

        Args:
            enabled: When False the collector records no data (useful in tests).
            retention_hours: How many hours of metric history to retain in memory.
        """
        self.enabled = enabled
        self.retention_hours = retention_hours
        self.start_time = datetime.utcnow()
        
        # Core metric storage
        self.counters: Dict[str, float] = defaultdict(float)
        self.gauges: Dict[str, float] = {}
        self.histograms: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.timeseries: Dict[str, deque] = defaultdict(lambda: deque(maxlen=2880))  # 24h @ 30s intervals
        
        # Health monitoring
        self.health_checks: Dict[str, HealthCheckResult] = {}
        self.health_check_registry: Dict[str, Callable] = {}
        
        # Request and response tracking
        self.request_count = 0
        self.error_count = 0
        self.total_request_time = 0.0
        self.request_times: deque = deque(maxlen=1000)
        self.active_requests: Dict[str, datetime] = {}
        
        # Tool performance metrics
        self.tool_metrics = {
            'call_counts': defaultdict(int),
            'error_counts': defaultdict(int),
            'execution_times': defaultdict(lambda: deque(maxlen=100)),
            'success_rates': defaultdict(float),
            'last_called': defaultdict(lambda: None)
        }
        
        # Session tracking
        self.session_metrics = {
            'total_sessions': 0,
            'active_sessions': 0,
            'session_duration': deque(maxlen=100),
            'creation_times': deque(maxlen=100)
        }
        
        # System resource monitoring
        self.system_metrics: Dict[str, float] = {}
        self.performance_snapshots: deque = deque(maxlen=2880)  # 24h @ 30s intervals
        
        # Alerting
        self.alert_thresholds = {
            'cpu_percent': 80.0,
            'memory_percent': 85.0,
            'disk_percent': 90.0,
            'error_rate': 0.05,  # 5%
            'response_time_ms': 5000.0  # 5 seconds
        }
        self.alerts: deque = deque(maxlen=100)
        
        # Background tasks
        self._monitoring_started = False
        self._lock = threading.Lock()
        
        # Don't start monitoring automatically during import
        # It will be started when needed via start_monitoring() method
    
    def _start_monitoring(self) -> None:
        """Start background monitoring tasks."""
        if self._monitoring_started:
            return

        # Only start when called from within an async context.
        from ipfs_datasets_py.utils.anyio_compat import in_async_context

        if not in_async_context():
            return

        from anyio.lowlevel import spawn_system_task

        spawn_system_task(self._monitoring_loop)
        spawn_system_task(self._cleanup_loop)
        self._monitoring_started = True
    
    def start_monitoring(self) -> None:
        """Public method to start monitoring when an event loop is available."""
        if self.enabled:
            self._start_monitoring()
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop that collects system metrics."""
        while True:
            try:
                await self._collect_system_metrics()
                await self._check_health()
                await self._check_alerts()
                await anyio.sleep(30)  # Collect every 30 seconds
                
            except anyio.get_cancelled_exc_class()():
                break
            except MetricsCollectionError as e:
                logger.error(f"Metrics collection error in monitoring loop: {e}")
                await anyio.sleep(60)
            except (OSError, IOError) as e:
                logger.error(f"System metrics unavailable: {e}", exc_info=True)
                await anyio.sleep(60)
            except Exception as e:
                logger.error(f"Unexpected error in monitoring loop: {e}", exc_info=True)
                await anyio.sleep(60)
    
    async def _cleanup_loop(self) -> None:
        """Clean up old metrics data."""
        while True:
            try:
                await self._cleanup_old_data()
                await anyio.sleep(3600)  # Cleanup every hour
                
            except anyio.get_cancelled_exc_class()():
                break
            except MonitoringError:
                raise
            except (IOError, OSError) as e:
                logger.error(f"System error in cleanup loop: {e}", exc_info=True)
                await anyio.sleep(3600)
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}", exc_info=True)
                await anyio.sleep(3600)
    
    async def _collect_system_metrics(self) -> None:
        """Collect system performance metrics."""
        try:
            # CPU and memory
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            
            # Disk usage
            disk = psutil.disk_usage('/')
            
            # Network statistics
            net_io = psutil.net_io_counters()
            
            # Process-specific metrics
            process = psutil.Process()
            process_memory = process.memory_info()
            
            # Update system metrics
            self.system_metrics.update({
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_used_mb': memory.used / 1024 / 1024,
                'memory_available_mb': memory.available / 1024 / 1024,
                'disk_percent': disk.percent,
                'disk_used_gb': disk.used / 1024 / 1024 / 1024,
                'disk_free_gb': disk.free / 1024 / 1024 / 1024,
                'network_bytes_sent': net_io.bytes_sent,
                'network_bytes_recv': net_io.bytes_recv,
                'process_memory_mb': process_memory.rss / 1024 / 1024,
                'process_cpu_percent': process.cpu_percent(),
                'open_files': len(process.open_files()),
                'num_threads': process.num_threads()
            })
            
            # Create performance snapshot
            snapshot = PerformanceSnapshot(
                timestamp=datetime.utcnow(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                memory_used_mb=memory.used / 1024 / 1024,
                disk_percent=disk.percent,
                active_connections=len(self.active_requests),
                request_rate=self._calculate_request_rate(),
                error_rate=self._calculate_error_rate(),
                avg_response_time_ms=self._calculate_avg_response_time()
            )
            
            with self._lock:
                self.performance_snapshots.append(snapshot)
                
                # Update timeseries data
                for metric_name, value in self.system_metrics.items():
                    self.timeseries[metric_name].append(MetricData(value))
                    
        except MetricsCollectionError as e:
            logger.error(f"Error collecting system metrics: {e}")
            raise
        except (OSError, IOError, AttributeError) as e:
            logger.error(f"System metrics unavailable: {e}", exc_info=True)
            raise MetricsCollectionError(f"Failed to access system metrics: {e}")
        except Exception as e:
            logger.error(f"Unexpected error collecting system metrics: {e}", exc_info=True)
            raise MetricsCollectionError(f"Failed to collect system metrics: {e}")
    
    def increment_counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter metric."""
        if not self.enabled:
            return
            
        with self._lock:
            self.counters[name] += value
            
            if labels:
                labeled_name = f"{name}_{self._serialize_labels(labels)}"
                self.counters[labeled_name] += value
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge metric value."""
        if not self.enabled:
            return
            
        with self._lock:
            self.gauges[name] = value
            
            if labels:
                labeled_name = f"{name}_{self._serialize_labels(labels)}"
                self.gauges[labeled_name] = value
    
    def observe_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Add an observation to a histogram."""
        if not self.enabled:
            return
            
        with self._lock:
            self.histograms[name].append(value)
            
            if labels:
                labeled_name = f"{name}_{self._serialize_labels(labels)}"
                self.histograms[labeled_name].append(value)
    
    @asynccontextmanager
    async def track_request(self, endpoint: str) -> AsyncGenerator[None, None]:
        """Context manager to track request duration and count."""
        try:
            task_id = str(id(anyio.get_current_task()))
        except AttributeError:
            task_id = "sync"
        except Exception as e:
            logger.debug(f"Error getting task ID: {e}")
            task_id = "sync"
        request_id = f"{endpoint}_{task_id}"
        start_time = time.time()
        
        try:
            with self._lock:
                self.active_requests[request_id] = datetime.utcnow()
                self.request_count += 1
            
            yield
            
        except MonitoringError:
            with self._lock:
                self.error_count += 1
            self.increment_counter('requests_failed', labels={'endpoint': endpoint})
            raise
        except Exception as e:
            with self._lock:
                self.error_count += 1
            self.increment_counter('requests_failed', labels={'endpoint': endpoint})
            raise
        finally:
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            
            with self._lock:
                self.active_requests.pop(request_id, None)
                self.total_request_time += duration_ms
                self.request_times.append(duration_ms)
            
            self.observe_histogram('request_duration_ms', duration_ms, {'endpoint': endpoint})
            self.increment_counter('requests_total', labels={'endpoint': endpoint})
    
    def track_tool_execution(self, tool_name: str, execution_time_ms: float, success: bool) -> None:
        """Track execution metrics for MCP tools with comprehensive performance monitoring.
        
        This method records detailed execution statistics for each tool invocation, including
        call counts, execution times, success rates, and error tracking. The metrics are used
        for performance analysis, debugging, and generating tool usage reports.
        
        Args:
            tool_name (str): The unique identifier of the tool being tracked. Should match
                    the tool's registered name in the MCP server tool registry.
            execution_time_ms (float): Tool execution duration in milliseconds. Must be
                    non-negative. Used for calculating average response times and identifying
                    performance bottlenecks.
            success (bool): Whether the tool execution completed successfully. True indicates
                    successful execution, False indicates an error or exception occurred.
                    Affects success_rate calculations and error_counts metrics.
        
        Side Effects:
            - Increments call_counts[tool_name] counter
            - Appends execution_time_ms to execution_times[tool_name] history
            - Updates last_called[tool_name] timestamp to current UTC time
            - Increments error_counts[tool_name] if success is False
            - Recalculates success_rates[tool_name] as (1 - errors/total_calls)
            - Updates Prometheus-style counters: tool_calls_total (labeled by tool, status)
            - Updates histogram: tool_execution_time_ms (labeled by tool)
        
        Example:
            >>> collector = EnhancedMetricsCollector()
            >>> collector.track_tool_execution("ipfs_add", 125.5, True)
            >>> collector.track_tool_execution("ipfs_add", 230.8, False)
            >>> # Check metrics
            >>> metrics = collector.get_metrics_summary()
            >>> print(metrics['tool_metrics']['call_counts']['ipfs_add'])
            2
            >>> print(metrics['tool_metrics']['success_rates']['ipfs_add'])
            0.5
        
        Note:
            - Thread-safe: Uses internal lock (_lock) to prevent race conditions
            - No-op if monitoring is disabled (self.enabled = False)
            - Execution times are stored in unbounded deque - consider memory in long-running apps
            - Success rate is calculated immediately on each call (not cached)
            - Metrics are aggregated across all tool invocations since collector initialization
            - Historical execution times can be used for percentile calculations (P50, P95, P99)
        
        Performance:
            - O(1) time complexity for counter updates
            - O(1) amortized for appending to execution_times deque
            - Lock contention possible under high concurrent load
            - Memory grows linearly with number of tool calls (execution_times history)
        
        Thread Safety:
            All metric updates are protected by self._lock to ensure atomic operations
            and consistent state in multi-threaded environments.
        """
        if not self.enabled:
            return
            
        with self._lock:
            self.tool_metrics['call_counts'][tool_name] += 1
            self.tool_metrics['execution_times'][tool_name].append(execution_time_ms)
            self.tool_metrics['last_called'][tool_name] = datetime.utcnow()
            
            if not success:
                self.tool_metrics['error_counts'][tool_name] += 1
            
            # Calculate success rate
            total_calls = self.tool_metrics['call_counts'][tool_name]
            errors = self.tool_metrics['error_counts'][tool_name]
            self.tool_metrics['success_rates'][tool_name] = 1.0 - (errors / total_calls)
        
        # Update metrics
        self.increment_counter('tool_calls_total', labels={'tool': tool_name, 'status': 'success' if success else 'error'})
        self.observe_histogram('tool_execution_time_ms', execution_time_ms, {'tool': tool_name})
    
    def register_health_check(self, name: str, check_func: Callable) -> None:
        """Register a health check function for automated system health monitoring.
        
        This method registers a custom health check callback that will be executed
        periodically or on-demand to verify the health status of system components.
        Health checks can be either synchronous or asynchronous functions and should
        return a HealthCheckResult object with status and diagnostic information.
        
        Args:
            name (str): Unique identifier for this health check. Used in health reports
                    and monitoring dashboards. Should be descriptive (e.g., "database_connection",
                    "ipfs_node_status", "redis_cache"). Duplicate names will overwrite
                    previous registrations.
            check_func (Callable): Health check callback function. Can be either:
                    - Synchronous: `def check() -> HealthCheckResult`
                    - Asynchronous: `async def check() -> HealthCheckResult`
                    
                    Expected return structure:
                    ```python
                    HealthCheckResult(
                        component=name,
                        status="healthy" | "warning" | "critical" | "unknown",
                        message="Description of health status",
                        timestamp=datetime.utcnow(),
                        details={...},  # Optional diagnostic data
                        response_time_ms=Optional[float]  # Check execution time
                    )
                    ```
        
        Returns:
            None
        
        Example:
            >>> collector = EnhancedMetricsCollector()
            >>> 
            >>> # Synchronous health check
            >>> def check_database():
            ...     try:
            ...         db.ping()
            ...         return HealthCheckResult(
            ...             component="database",
            ...             status="healthy",
            ...             message="Database connection OK"
            ...         )
            ...     except Exception as e:
            ...         return HealthCheckResult(
            ...             component="database",
            ...             status="critical",
            ...             message=f"Database unreachable: {e}"
            ...         )
            >>> collector.register_health_check("database_connection", check_database)
            >>> 
            >>> # Asynchronous health check
            >>> async def check_ipfs():
            ...     try:
            ...         result = await ipfs_client.id()
            ...         return HealthCheckResult(
            ...             component="ipfs",
            ...             status="healthy",
            ...             message=f"IPFS node responding: {result['ID']}"
            ...         )
            ...     except Exception as e:
            ...         return HealthCheckResult(
            ...             component="ipfs",
            ...             status="critical",
            ...             message=f"IPFS node error: {e}"
            ...         )
            >>> collector.register_health_check("ipfs_node", check_ipfs)
        
        Note:
            - Health checks are stored in health_check_registry dict (not threadsafe)
            - Registration overwrites existing checks with the same name
            - Check functions must return HealthCheckResult objects
            - Async/sync detection happens automatically during execution (_check_health)
            - No validation of check_func signature at registration time
            - Exceptions during check execution are caught and reported as 'critical' status
            - Health checks are executed via _check_health() method (manual or periodic)
        
        Best Practices:
            - Keep health checks lightweight (< 1 second execution time)
            - Return 'healthy' only if component is fully operational
            - Use 'warning' for degraded but functional state
            - Use 'critical' for non-operational components
            - Include diagnostic details in the details dict
            - Add response_time_ms for latency monitoring
            - Implement timeouts in check functions to prevent hangs
        
        Health Check Execution:
            Registered checks are executed by:
            - `_check_health()` method (called internally or via monitoring loops)
            - Results stored in self.health_check_results
            - Execution time tracked automatically
            - Exceptions converted to 'critical' status with error message
        """
        self.health_check_registry[name] = check_func
    
    async def _check_health(self) -> None:
        """Run all registered health checks."""
        for name, check_func in self.health_check_registry.items():
            try:
                start_time = time.time()
                
                if inspect.iscoroutinefunction(check_func):
                    result = await check_func()
                else:
                    result = check_func()
                    if inspect.isawaitable(result):
                        result = await result
                
                response_time_ms = (time.time() - start_time) * 1000
                
                if isinstance(result, HealthCheckResult):
                    result.response_time_ms = response_time_ms
                    self.health_checks[name] = result
                else:
                    # Assume success if function doesn't return HealthCheckResult
                    self.health_checks[name] = HealthCheckResult(
                        component=name,
                        status='healthy',
                        message='Health check passed',
                        response_time_ms=response_time_ms
                    )
                    
            except HealthCheckError as e:
                self.health_checks[name] = HealthCheckResult(
                    component=name,
                    status='critical',
                    message=f'Health check failed: {e.message}',
                    details={'error': str(e), 'check_name': e.check_name}
                )
            except (ImportError, ModuleNotFoundError) as e:
                self.health_checks[name] = HealthCheckResult(
                    component=name,
                    status='critical',
                    message=f'Health check module unavailable: {e}',
                    details={'error': str(e)}
                )
            except Exception as e:
                self.health_checks[name] = HealthCheckResult(
                    component=name,
                    status='critical',
                    message=f'Health check failed: {e}',
                    details={'error': str(e)}
                )
    
    async def _check_alerts(self) -> None:
        """Check for alert conditions and generate alerts."""
        alerts_triggered = []
        
        # CPU alert
        cpu_percent = self.system_metrics.get('cpu_percent', 0)
        if cpu_percent > self.alert_thresholds['cpu_percent']:
            alerts_triggered.append({
                'type': 'cpu_high',
                'severity': 'warning',
                'message': f'High CPU usage: {cpu_percent:.1f}%',
                'value': cpu_percent,
                'threshold': self.alert_thresholds['cpu_percent']
            })
        
        # Memory alert
        memory_percent = self.system_metrics.get('memory_percent', 0)
        if memory_percent > self.alert_thresholds['memory_percent']:
            alerts_triggered.append({
                'type': 'memory_high',
                'severity': 'warning',
                'message': f'High memory usage: {memory_percent:.1f}%',
                'value': memory_percent,
                'threshold': self.alert_thresholds['memory_percent']
            })
        
        # Error rate alert
        error_rate = self._calculate_error_rate()
        if error_rate > self.alert_thresholds['error_rate']:
            alerts_triggered.append({
                'type': 'error_rate_high',
                'severity': 'critical',
                'message': f'High error rate: {error_rate:.2%}',
                'value': error_rate,
                'threshold': self.alert_thresholds['error_rate']
            })
        
        # Response time alert
        avg_response_time = self._calculate_avg_response_time()
        if avg_response_time > self.alert_thresholds['response_time_ms']:
            alerts_triggered.append({
                'type': 'response_time_high',
                'severity': 'warning',
                'message': f'High response time: {avg_response_time:.1f}ms',
                'value': avg_response_time,
                'threshold': self.alert_thresholds['response_time_ms']
            })
        
        # Store alerts
        for alert in alerts_triggered:
            alert['timestamp'] = datetime.utcnow()
            with self._lock:
                self.alerts.append(alert)
    
    def _calculate_request_rate(self) -> float:
        """Calculate requests per second over the last minute."""
        if not self.request_times:
            return 0.0
        
        now = datetime.utcnow()
        minute_ago = now - timedelta(minutes=1)
        
        recent_requests = sum(1 for ts in self.performance_snapshots 
                             if ts.timestamp > minute_ago)
        
        return recent_requests / 60.0
    
    def _calculate_error_rate(self) -> float:
        """Calculate error rate as a percentage."""
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count
    
    def _calculate_avg_response_time(self) -> float:
        """Calculate average response time in milliseconds."""
        if not self.request_times:
            return 0.0
        return sum(self.request_times) / len(self.request_times)
    
    def _serialize_labels(self, labels: Dict[str, str]) -> str:
        """Serialize labels for metric naming."""
        return "_".join(f"{k}_{v}" for k, v in sorted(labels.items()))
    
    async def _cleanup_old_data(self) -> None:
        """Clean up old metric data based on retention policy."""
        cutoff_time = datetime.utcnow() - timedelta(hours=self.retention_hours)
        
        with self._lock:
            # Clean up performance snapshots
            while (self.performance_snapshots and 
                   self.performance_snapshots[0].timestamp < cutoff_time):
                self.performance_snapshots.popleft()
            
            # Clean up timeseries data
            for metric_name, data_deque in self.timeseries.items():
                while data_deque and data_deque[0].timestamp < cutoff_time:
                    data_deque.popleft()
            
            # Clean up alerts
            while self.alerts and self.alerts[0]['timestamp'] < cutoff_time:
                self.alerts.popleft()
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Retrieve a comprehensive snapshot of all monitoring metrics and system health.
        
        This method aggregates metrics from multiple subsystems into a single unified
        summary, providing a complete overview of system performance, tool usage,
        health checks, and recent alerts. The summary is thread-safe and represents
        a consistent point-in-time view of all metrics.
        
        Returns:
            Dict[str, Any]: Comprehensive metrics dictionary with the following structure:
                {
                    'uptime_seconds': float,  # Time since collector initialization
                    'system_metrics': {  # Current system resource utilization
                        'cpu_percent': float,
                        'memory_percent': float,
                        'memory_used_mb': float,
                        'disk_percent': float,
                        'active_connections': int
                    },
                    'request_metrics': {  # HTTP/API request statistics
                        'total_requests': int,
                        'total_errors': int,
                        'error_rate': float,  # Errors per second
                        'avg_response_time_ms': float,
                        'active_requests': int,  # Currently in-flight
                        'request_rate_per_second': float
                    },
                    'tool_metrics': {  # Per-tool execution statistics
                        '<tool_name>': {
                            'total_calls': int,
                            'error_count': int,
                            'success_rate': float,  # 0.0 to 1.0
                            'avg_execution_time_ms': float,
                            'last_called': datetime
                        },
                        # ... one entry per tool
                    },
                    'health_status': {  # Health check results
                        '<check_name>': {
                            'status': str,  # 'healthy', 'warning', 'critical', 'unknown'
                            'message': str,
                            'last_check': datetime,
                            'response_time_ms': Optional[float]
                        },
                        # ... one entry per registered health check
                    },
                    'recent_alerts': List[Dict]  # Last 10 alerts (FIFO order)
                }
        
        Example:
            >>> collector = EnhancedMetricsCollector()
            >>> summary = collector.get_metrics_summary()
            >>> print(f"Uptime: {summary['uptime_seconds']:.1f}s")
            >>> print(f"Request rate: {summary['request_metrics']['request_rate_per_second']:.2f} req/s")
            >>> print(f"Error rate: {summary['request_metrics']['error_rate']:.2f}%")
            >>> 
            >>> # Check specific tool metrics
            >>> if 'ipfs_add' in summary['tool_metrics']:
            ...     tool_stats = summary['tool_metrics']['ipfs_add']
            ...     print(f"IPFS Add - Calls: {tool_stats['total_calls']}, "
            ...           f"Success: {tool_stats['success_rate']*100:.1f}%")
            >>> 
            >>> # Check health status
            >>> for name, status in summary['health_status'].items():
            ...     if status['status'] != 'healthy':
            ...         print(f"⚠️ {name}: {status['message']}")
        
        Note:
            - **Thread-Safe**: All reads are protected by self._lock
            - **Point-in-Time**: Snapshot is consistent but may be stale immediately after return
            - **Memory**: Copies all metrics data - can be large with many tools/checks
            - **Performance**: O(n) where n = number of tools + health checks
            - **Calculation**: avg_execution_time_ms is calculated on-the-fly (not cached)
            - **Recent Alerts**: Limited to last 10 alerts to prevent unbounded growth
            - **Health Status**: Only includes checks that have been executed at least once
        
        Performance:
            - Typical execution: 1-5ms (depends on number of tools/checks)
            - Lock held for entire duration - can block tracking operations
            - Dictionary copies add memory allocation overhead
            - Calculation of averages done in-place (not pre-computed)
        
        Use Cases:
            - Monitoring dashboards and status pages
            - Health check endpoints (e.g., /metrics, /health)
            - Periodic metric exports to monitoring systems
            - Debugging performance issues
            - Capacity planning and trend analysis
            - Alert threshold evaluation
        
        Thread Safety:
            Entire method execution is wrapped in self._lock to ensure consistent
            snapshot across all metric categories. No partial updates possible.
        """
        with self._lock:
            return {
                'uptime_seconds': (datetime.utcnow() - self.start_time).total_seconds(),
                'system_metrics': self.system_metrics.copy(),
                'request_metrics': {
                    'total_requests': self.request_count,
                    'total_errors': self.error_count,
                    'error_rate': self._calculate_error_rate(),
                    'avg_response_time_ms': self._calculate_avg_response_time(),
                    'active_requests': len(self.active_requests),
                    'request_rate_per_second': self._calculate_request_rate()
                },
                'tool_metrics': {
                    tool: {
                        'total_calls': self.tool_metrics['call_counts'][tool],
                        'error_count': self.tool_metrics['error_counts'][tool],
                        'success_rate': self.tool_metrics['success_rates'][tool],
                        'avg_execution_time_ms': (
                            sum(self.tool_metrics['execution_times'][tool]) / 
                            len(self.tool_metrics['execution_times'][tool])
                            if self.tool_metrics['execution_times'][tool] else 0
                        ),
                        'last_called': self.tool_metrics['last_called'][tool]
                    }
                    for tool in self.tool_metrics['call_counts'].keys()
                },
                'health_status': {
                    name: {
                        'status': check.status,
                        'message': check.message,
                        'last_check': check.timestamp,
                        'response_time_ms': check.response_time_ms
                    }
                    for name, check in self.health_checks.items()
                },
                'recent_alerts': list(self.alerts)[-10:] if self.alerts else []
            }
    
    def get_performance_trends(self, hours: int = 1) -> Dict[str, List[Dict[str, Any]]]:
        """Retrieve time-series performance trends for specified historical period.
        
        This method extracts performance snapshots from the specified time window and
        formats them as time-series data for trending, visualization, and analysis.
        Useful for identifying performance patterns, degradation, and capacity issues.
        
        Args:
            hours (int, optional): Number of hours of historical data to retrieve.
                    Must be positive. Defaults to 1 hour. Maximum is limited by
                    snapshot retention (typically 24 hours). Larger values may
                    return fewer data points if snapshots have been garbage collected.
        
        Returns:
            Dict[str, List[Dict[str, Any]]]: Time-series data organized by metric type:
                {
                    'cpu_trend': [
                        {'timestamp': '2026-02-19T08:00:00', 'value': 45.2},
                        {'timestamp': '2026-02-19T08:05:00', 'value': 47.8},
                        # ... more data points
                    ],
                    'memory_trend': [
                        {'timestamp': '2026-02-19T08:00:00', 'value': 62.3},
                        # ... more data points
                    ],
                    'request_rate_trend': [
                        {'timestamp': '2026-02-19T08:00:00', 'value': 125.5},
                        # ... requests per second
                    ],
                    'response_time_trend': [
                        {'timestamp': '2026-02-19T08:00:00', 'value': 15.3},
                        # ... avg response time in ms
                    ]
                }
                
                Each trend is a list of data points in chronological order.
                Timestamps are ISO 8601 format strings.
                Values are floats with metric-specific units.
        
        Example:
            >>> collector = EnhancedMetricsCollector()
            >>> # Get last hour of trends (default)
            >>> trends = collector.get_performance_trends()
            >>> print(f"Data points: {len(trends['cpu_trend'])}")
            >>> 
            >>> # Get last 24 hours
            >>> daily_trends = collector.get_performance_trends(hours=24)
            >>> 
            >>> # Analyze CPU trend
            >>> cpu_values = [point['value'] for point in trends['cpu_trend']]
            >>> if cpu_values:
            ...     avg_cpu = sum(cpu_values) / len(cpu_values)
            ...     max_cpu = max(cpu_values)
            ...     print(f"Avg CPU: {avg_cpu:.1f}%, Peak: {max_cpu:.1f}%")
            >>> 
            >>> # Detect performance degradation
            >>> response_times = [p['value'] for p in trends['response_time_trend']]
            >>> if len(response_times) >= 2:
            ...     if response_times[-1] > response_times[0] * 2:
            ...         print("⚠️ Response time doubled in last hour!")
        
        Note:
            - **Data Resolution**: Snapshots are typically collected every 30-60 seconds
            - **Thread-Safe**: Snapshot filtering done under lock
            - **Time Zone**: All timestamps are UTC (datetime.utcnow())
            - **Sparse Data**: May return fewer points than expected if snapshots were skipped
            - **Memory**: Snapshot history is bounded (typically 1000-2000 points max)
            - **Garbage Collection**: Old snapshots are automatically purged
            - **No Interpolation**: Returns actual collected data points only
        
        Performance:
            - O(n) where n = number of snapshots in time window
            - Typical: <5ms for 1 hour (60-120 data points)
            - Lock held briefly during filtering (1-2ms)
            - Memory: ~1KB per hour of data returned
        
        Snapshot Retention:
            - Snapshots older than retention period are automatically deleted
            - Default retention: 24 hours (configurable)
            - Collection interval: 30-60 seconds (configurable)
            - Max snapshots: Typically 1000-2000 points (memory bounded)
        
        Use Cases:
            - Real-time performance monitoring dashboards
            - Trend visualization and charting
            - Performance degradation detection
            - Capacity planning and forecasting
            - Anomaly detection and alerting
            - Historical performance analysis
            - SLA compliance verification
        
        Trend Types:
            - **cpu_trend**: CPU utilization percentage (0-100)
            - **memory_trend**: Memory utilization percentage (0-100)
            - **request_rate_trend**: Requests per second (float)
            - **response_time_trend**: Average response time in milliseconds (float)
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        with self._lock:
            relevant_snapshots = [
                snapshot for snapshot in self.performance_snapshots
                if snapshot.timestamp > cutoff_time
            ]
        
        return {
            'cpu_trend': [
                {'timestamp': s.timestamp.isoformat(), 'value': s.cpu_percent}
                for s in relevant_snapshots
            ],
            'memory_trend': [
                {'timestamp': s.timestamp.isoformat(), 'value': s.memory_percent}
                for s in relevant_snapshots
            ],
            'request_rate_trend': [
                {'timestamp': s.timestamp.isoformat(), 'value': s.request_rate}
                for s in relevant_snapshots
            ],
            'response_time_trend': [
                {'timestamp': s.timestamp.isoformat(), 'value': s.avg_response_time_ms}
                for s in relevant_snapshots
            ]
        }
    
    async def shutdown(self) -> None:
        """Shutdown monitoring tasks."""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except anyio.get_cancelled_exc_class()():
                pass
        
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except anyio.get_cancelled_exc_class()():
                pass

class P2PMetricsCollector:
    """
    P2P-specific metrics collector for tracking peer discovery, workflows, and bootstrap operations.
    Integrates with EnhancedMetricsCollector for comprehensive P2P monitoring.
    """
    
    def __init__(self, base_collector: Optional[EnhancedMetricsCollector] = None) -> None:
        """Initialise the P2P metrics collector.

        Args:
            base_collector: Underlying :class:`EnhancedMetricsCollector` to use.
                If *None*, the global instance returned by :func:`get_metrics_collector`
                is used.
        """
        self.base_collector = base_collector or get_metrics_collector()
        
        # P2P-specific metrics
        self.peer_discovery_metrics = {
            'total_discoveries': 0,
            'successful_discoveries': 0,
            'failed_discoveries': 0,
            'peers_by_source': defaultdict(int),
            'discovery_times': deque(maxlen=100),
            'last_discovery': None
        }
        
        self.workflow_metrics = {
            'total_workflows': 0,
            'active_workflows': 0,
            'completed_workflows': 0,
            'failed_workflows': 0,
            'workflow_durations': deque(maxlen=100),
            'workflows_by_status': defaultdict(int),
            'last_workflow': None
        }
        
        self.bootstrap_metrics = {
            'total_bootstrap_attempts': 0,
            'successful_bootstraps': 0,
            'failed_bootstraps': 0,
            'bootstrap_methods_used': defaultdict(int),
            'bootstrap_times': deque(maxlen=100),
            'last_bootstrap': None
        }
        
        # Dashboard data cache
        self._dashboard_cache = None
        self._dashboard_cache_time = None
        self._cache_ttl = timedelta(seconds=30)
    
    def track_peer_discovery(
        self,
        source: str,
        peers_found: int,
        success: bool,
        duration_ms: Optional[float] = None
    ) -> None:
        """Track peer discovery operations for P2P network monitoring.
        
        This method records metrics for peer discovery attempts, tracking success rates,
        peer counts by source, and discovery latencies. Used for monitoring P2P network
        health and peer availability across different discovery mechanisms.
        
        Args:
            source (str): Discovery mechanism used. Common values include:
                    - "dht" - DHT (Distributed Hash Table) peer discovery
                    - "mdns" - Multicast DNS local peer discovery
                    - "bootstrap" - Bootstrap node peer discovery
                    - "relay" - Relay node peer discovery
                    - "pubsub" - PubSub-based peer discovery
                    - Custom discovery sources as implemented
            peers_found (int): Number of peers discovered in this operation.
                    Must be non-negative. Zero indicates discovery attempt with no results.
                    Only counted if success is True.
            success (bool): Whether the discovery operation completed successfully.
                    True indicates discovery ran without errors (even if peers_found=0).
                    False indicates discovery failed due to errors or timeouts.
            duration_ms (Optional[float], optional): Discovery operation duration in
                    milliseconds. If None, duration is not tracked. Defaults to None.
                    Used for latency analysis and performance monitoring.
        
        Side Effects:
            Updates the following metrics:
            - total_discoveries: Incremented always
            - successful_discoveries: Incremented if success=True
            - failed_discoveries: Incremented if success=False
            - peers_by_source[source]: Adds peers_found (only if success=True)
            - discovery_times: Appends duration_ms (if provided)
            - last_discovery: Updated to current UTC time
            - base_collector counters: p2p.peer_discovery.{source}, p2p.peer_discovery.errors
        
        Example:
            >>> collector = P2PMetricsCollector()
            >>> # Successful DHT discovery
            >>> collector.track_peer_discovery("dht", peers_found=5, success=True, duration_ms=125.3)
            >>> 
            >>> # Failed mDNS discovery
            >>> collector.track_peer_discovery("mdns", peers_found=0, success=False, duration_ms=30.0)
            >>> 
            >>> # Successful bootstrap with no duration tracking
            >>> collector.track_peer_discovery("bootstrap", peers_found=3, success=True)
            >>> 
            >>> # Check metrics
            >>> metrics = collector.get_dashboard_data()
            >>> print(f"Total discoveries: {metrics['peer_discovery']['total_discoveries']}")
            >>> print(f"Success rate: {metrics['peer_discovery']['success_rate']:.1%}")
            >>> print(f"Peers by source: {metrics['peer_discovery']['peers_by_source']}")
        
        Note:
            - Duration tracking is optional but recommended for performance analysis
            - Peers are only counted for successful discoveries
            - Failed discoveries still increment total_discoveries counter
            - discovery_times deque may grow unbounded in long-running applications
            - Source names are case-sensitive and not validated
            - Updates are not atomic across all metrics (no locking)
        
        Discovery Sources:
            **DHT (Distributed Hash Table):**
            - Distributed peer discovery via Kademlia DHT
            - Typically finds 10-50 peers per query
            - Latency: 100-1000ms
            
            **mDNS (Multicast DNS):**
            - Local network peer discovery
            - Finds 0-10 peers typically
            - Latency: 10-100ms
            - May fail if multicast disabled
            
            **Bootstrap:**
            - Discovery via configured bootstrap nodes
            - Typically finds 5-20 peers
            - Latency: 50-500ms
            
            **Relay:**
            - Discovery through relay nodes
            - Variable peer counts
            - Latency: 100-2000ms (network dependent)
        
        Use Cases:
            - P2P network health monitoring
            - Discovery mechanism effectiveness comparison
            - Latency analysis and optimization
            - Peer availability trending
            - Network connectivity diagnostics
        """
        self.peer_discovery_metrics['total_discoveries'] += 1
        
        if success:
            self.peer_discovery_metrics['successful_discoveries'] += 1
            self.peer_discovery_metrics['peers_by_source'][source] += peers_found
        else:
            self.peer_discovery_metrics['failed_discoveries'] += 1
        
        if duration_ms is not None:
            self.peer_discovery_metrics['discovery_times'].append(duration_ms)
        
        self.peer_discovery_metrics['last_discovery'] = datetime.utcnow()
        
        # Update base collector
        self.base_collector.increment_counter(f'p2p.peer_discovery.{source}', peers_found)
        if not success:
            self.base_collector.increment_counter('p2p.peer_discovery.errors')
    
    def track_workflow_execution(
        self,
        workflow_id: str,
        status: str,
        execution_time_ms: Optional[float] = None
    ) -> None:
        """Track P2P workflow execution lifecycle and performance metrics.
        
        This method monitors the execution state and performance of distributed P2P
        workflows, tracking state transitions, completion rates, and execution times.
        Used for workflow orchestration monitoring and failure detection.
        
        Args:
            workflow_id (str): Unique identifier for the workflow instance. Should be
                    consistent across all state transitions for the same workflow.
                    Typically a UUID or sequential ID.
            status (str): Current workflow execution status. Valid values:
                    - "running": Workflow is actively executing
                    - "completed": Workflow finished successfully
                    - "failed": Workflow encountered an error and terminated
                    - Custom status values are supported but may not affect active_workflows counter
            execution_time_ms (Optional[float], optional): Workflow execution duration
                    in milliseconds. Typically provided for "completed" or "failed" status.
                    If None, duration is not tracked. Defaults to None.
        
        Side Effects:
            Updates the following metrics based on status:
            
            **All statuses:**
            - total_workflows: Incremented always
            - workflows_by_status[status]: Incremented for this status
            - last_workflow: Updated to current UTC time
            - base_collector counter: p2p.workflow.{status}
            
            **status="running":**
            - active_workflows: Incremented by 1
            
            **status="completed":**
            - completed_workflows: Incremented by 1
            - active_workflows: Decremented by 1 (if > 0)
            - workflow_durations: Appends execution_time_ms (if provided)
            - base_collector histogram: p2p.workflow.execution_time_ms
            
            **status="failed":**
            - failed_workflows: Incremented by 1
            - active_workflows: Decremented by 1 (if > 0)
            - workflow_durations: Appends execution_time_ms (if provided)
        
        Example:
            >>> collector = P2PMetricsCollector()
            >>> # Start workflow
            >>> collector.track_workflow_execution("wf-123", status="running")
            >>> 
            >>> # Complete workflow
            >>> collector.track_workflow_execution("wf-123", status="completed", execution_time_ms=5432.1)
            >>> 
            >>> # Start another workflow that fails
            >>> collector.track_workflow_execution("wf-456", status="running")
            >>> collector.track_workflow_execution("wf-456", status="failed", execution_time_ms=1250.5)
            >>> 
            >>> # Check metrics
            >>> metrics = collector.get_dashboard_data()
            >>> print(f"Active workflows: {metrics['workflows']['active']}")
            >>> print(f"Completed: {metrics['workflows']['completed']}")
            >>> print(f"Failed: {metrics['workflows']['failed']}")
            >>> print(f"Success rate: {metrics['workflows']['success_rate']:.1%}")
        
        Note:
            - **State Tracking**: This method does NOT track which workflows are active
              (no workflow_id storage). It only maintains a count.
            - **Idempotency**: Calling with same workflow_id and status multiple times
              will increment counters each time (not idempotent)
            - **Active Count Protection**: active_workflows is guarded against going negative
            - **No Validation**: workflow_id and status are not validated
            - **Duration Optional**: execution_time_ms only meaningful for terminal statuses
            - **No Locking**: Updates are not atomic (thread safety not guaranteed)
        
        Workflow Status State Machine:
            ```
            [Created] ──→ "running" ──→ "completed" (success)
                                   └──→ "failed" (error)
            ```
            
            Expected sequence:
            1. track_workflow_execution(id, "running") when workflow starts
            2. track_workflow_execution(id, "completed"|"failed", duration) when done
        
        Metrics Calculation:
            - **Success Rate**: completed_workflows / (completed_workflows + failed_workflows)
            - **Average Duration**: mean(workflow_durations)
            - **Active Workflows**: Maintained via running/completed/failed transitions
        
        Use Cases:
            - Workflow orchestration monitoring
            - Distributed task completion tracking
            - Workflow performance analysis
            - Failure rate monitoring and alerting
            - SLA compliance verification
            - Capacity planning (active workflow counts)
        """
        self.workflow_metrics['total_workflows'] += 1
        self.workflow_metrics['workflows_by_status'][status] += 1
        
        if status == 'running':
            self.workflow_metrics['active_workflows'] += 1
        elif status == 'completed':
            self.workflow_metrics['completed_workflows'] += 1
            if self.workflow_metrics['active_workflows'] > 0:
                self.workflow_metrics['active_workflows'] -= 1
        elif status == 'failed':
            self.workflow_metrics['failed_workflows'] += 1
            if self.workflow_metrics['active_workflows'] > 0:
                self.workflow_metrics['active_workflows'] -= 1
        
        if execution_time_ms is not None:
            self.workflow_metrics['workflow_durations'].append(execution_time_ms)
        
        self.workflow_metrics['last_workflow'] = datetime.utcnow()
        
        # Update base collector
        self.base_collector.increment_counter(f'p2p.workflow.{status}')
        if execution_time_ms is not None:
            self.base_collector.observe_histogram('p2p.workflow.execution_time_ms', execution_time_ms)
    
    def track_bootstrap_operation(
        self,
        method: str,
        success: bool,
        duration_ms: Optional[float] = None
    ) -> None:
        """Track P2P network bootstrap operations and connection establishment.
        
        This method monitors bootstrap attempts to the P2P network, tracking success
        rates, methods used, and bootstrap latencies. Bootstrap operations are critical
        for initial P2P network connectivity and peer discovery.
        
        Args:
            method (str): Bootstrap method/mechanism used. Common values include:
                    - "config" - Bootstrap using configured bootstrap nodes
                    - "dht" - Bootstrap via DHT seed nodes
                    - "mdns" - Bootstrap via local mDNS discovery
                    - "relay" - Bootstrap through relay nodes
                    - "fallback" - Fallback bootstrap mechanism
                    - Custom methods as implemented in your P2P stack
            success (bool): Whether the bootstrap operation succeeded.
                    True: Successfully connected to at least one peer
                    False: Bootstrap failed, no peers connected
            duration_ms (Optional[float], optional): Bootstrap operation duration in
                    milliseconds. If None, duration is not tracked. Defaults to None.
                    Measures time from bootstrap initiation to first peer connection
                    or failure timeout.
        
        Side Effects:
            Updates the following metrics:
            
            **Always:**
            - total_bootstrap_attempts: Incremented by 1
            - bootstrap_methods_used[method]: Incremented by 1
            - last_bootstrap: Updated to current UTC time
            - base_collector counter: p2p.bootstrap.{method}
            
            **If success=True:**
            - successful_bootstraps: Incremented by 1
            
            **If success=False:**
            - failed_bootstraps: Incremented by 1
            - base_collector counter: p2p.bootstrap.errors
            
            **If duration_ms provided:**
            - bootstrap_times: Appends duration_ms to history
        
        Example:
            >>> collector = P2PMetricsCollector()
            >>> # Successful config bootstrap
            >>> collector.track_bootstrap_operation("config", success=True, duration_ms=342.5)
            >>> 
            >>> # Failed DHT bootstrap
            >>> collector.track_bootstrap_operation("dht", success=False, duration_ms=5000.0)
            >>> 
            >>> # Successful fallback bootstrap (no duration tracking)
            >>> collector.track_bootstrap_operation("fallback", success=True)
            >>> 
            >>> # Check metrics
            >>> metrics = collector.get_dashboard_data()
            >>> print(f"Total attempts: {metrics['bootstrap']['total_attempts']}")
            >>> print(f"Success rate: {metrics['bootstrap']['success_rate']:.1%}")
            >>> print(f"Methods used: {metrics['bootstrap']['methods_used']}")
            >>> avg_time = sum(metrics['bootstrap']['times']) / len(metrics['bootstrap']['times'])
            >>> print(f"Avg bootstrap time: {avg_time:.1f}ms")
        
        Note:
            - Bootstrap is typically one-time operation at P2P node startup
            - Multiple bootstrap methods may be tried in sequence (fallback cascade)
            - Duration includes network latency, peer connection time, handshakes
            - Failed bootstraps may retry with different methods
            - bootstrap_times deque may grow unbounded in applications with frequent restarts
            - Method names are case-sensitive and not validated
            - Updates are not atomic (no locking)
        
        Bootstrap Methods:
            **Config (Configured Bootstrap Nodes):**
            - Uses hardcoded bootstrap node addresses
            - Most reliable, requires known-good peers
            - Latency: 100-1000ms
            - Fails if bootstrap nodes offline
            
            **DHT (Distributed Hash Table):**
            - Uses DHT seed nodes for bootstrap
            - More resilient, distributed approach
            - Latency: 200-2000ms
            - Requires DHT network availability
            
            **mDNS (Multicast DNS):**
            - Local network peer discovery
            - Fast for local development/testing
            - Latency: 50-500ms
            - Only works on local network
            
            **Relay:**
            - Bootstrap through relay nodes
            - Fallback for NAT traversal
            - Latency: 500-3000ms
            - Higher latency due to hop
        
        Use Cases:
            - P2P node startup monitoring
            - Bootstrap reliability tracking
            - Network connectivity diagnostics
            - Bootstrap method effectiveness comparison
            - Failover strategy validation
            - SLA compliance for node availability
        
        Bootstrap Lifecycle:
            1. P2P node starts
            2. Attempts bootstrap with primary method ("config")
            3. If fails, tries secondary method ("dht")
            4. If fails, tries tertiary method ("fallback")
            5. Each attempt tracked with track_bootstrap_operation()
        """
        self.bootstrap_metrics['total_bootstrap_attempts'] += 1
        
        if success:
            self.bootstrap_metrics['successful_bootstraps'] += 1
        else:
            self.bootstrap_metrics['failed_bootstraps'] += 1
        
        self.bootstrap_metrics['bootstrap_methods_used'][method] += 1
        
        if duration_ms is not None:
            self.bootstrap_metrics['bootstrap_times'].append(duration_ms)
        
        self.bootstrap_metrics['last_bootstrap'] = datetime.utcnow()
        
        # Update base collector
        self.base_collector.increment_counter(f'p2p.bootstrap.{method}')
        if not success:
            self.base_collector.increment_counter('p2p.bootstrap.errors')
    
    def _calculate_average_times(self) -> Dict[str, float]:
        """Calculate average times for discovery, workflow, and bootstrap."""
        avg_discovery_time = (
            sum(self.peer_discovery_metrics['discovery_times']) / 
            len(self.peer_discovery_metrics['discovery_times'])
            if self.peer_discovery_metrics['discovery_times'] else 0.0
        )
        
        avg_workflow_duration = (
            sum(self.workflow_metrics['workflow_durations']) / 
            len(self.workflow_metrics['workflow_durations'])
            if self.workflow_metrics['workflow_durations'] else 0.0
        )
        
        avg_bootstrap_time = (
            sum(self.bootstrap_metrics['bootstrap_times']) / 
            len(self.bootstrap_metrics['bootstrap_times'])
            if self.bootstrap_metrics['bootstrap_times'] else 0.0
        )
        
        return {
            'discovery': avg_discovery_time,
            'workflow': avg_workflow_duration,
            'bootstrap': avg_bootstrap_time
        }
    
    def _calculate_success_rates(self) -> Dict[str, float]:
        """Calculate success rates for discovery, workflow, and bootstrap."""
        discovery_success_rate = (
            (self.peer_discovery_metrics['successful_discoveries'] / 
             self.peer_discovery_metrics['total_discoveries'] * 100)
            if self.peer_discovery_metrics['total_discoveries'] > 0 else 0.0
        )
        
        bootstrap_success_rate = (
            (self.bootstrap_metrics['successful_bootstraps'] / 
             self.bootstrap_metrics['total_bootstrap_attempts'] * 100)
            if self.bootstrap_metrics['total_bootstrap_attempts'] > 0 else 0.0
        )
        
        workflow_success_rate = (
            (self.workflow_metrics['completed_workflows'] / 
             (self.workflow_metrics['completed_workflows'] + self.workflow_metrics['failed_workflows']) * 100)
            if (self.workflow_metrics['completed_workflows'] + self.workflow_metrics['failed_workflows']) > 0 else 0.0
        )
        
        return {
            'discovery': discovery_success_rate,
            'workflow': workflow_success_rate,
            'bootstrap': bootstrap_success_rate
        }
    
    def _build_dashboard_data(self, avg_times: Dict[str, float], success_rates: Dict[str, float]) -> Dict[str, Any]:
        """Build the complete dashboard data structure."""
        return {
            'peer_discovery': {
                'total': self.peer_discovery_metrics['total_discoveries'],
                'successful': self.peer_discovery_metrics['successful_discoveries'],
                'failed': self.peer_discovery_metrics['failed_discoveries'],
                'success_rate': round(success_rates['discovery'], 2),
                'avg_duration_ms': round(avg_times['discovery'], 2),
                'by_source': dict(self.peer_discovery_metrics['peers_by_source']),
                'last_discovery': (
                    self.peer_discovery_metrics['last_discovery'].isoformat()
                    if self.peer_discovery_metrics['last_discovery'] else None
                )
            },
            'workflows': {
                'total': self.workflow_metrics['total_workflows'],
                'active': self.workflow_metrics['active_workflows'],
                'completed': self.workflow_metrics['completed_workflows'],
                'failed': self.workflow_metrics['failed_workflows'],
                'success_rate': round(success_rates['workflow'], 2),
                'avg_duration_ms': round(avg_times['workflow'], 2),
                'by_status': dict(self.workflow_metrics['workflows_by_status']),
                'last_workflow': (
                    self.workflow_metrics['last_workflow'].isoformat()
                    if self.workflow_metrics['last_workflow'] else None
                )
            },
            'bootstrap': {
                'total_attempts': self.bootstrap_metrics['total_bootstrap_attempts'],
                'successful': self.bootstrap_metrics['successful_bootstraps'],
                'failed': self.bootstrap_metrics['failed_bootstraps'],
                'success_rate': round(success_rates['bootstrap'], 2),
                'avg_duration_ms': round(avg_times['bootstrap'], 2),
                'by_method': dict(self.bootstrap_metrics['bootstrap_methods_used']),
                'last_bootstrap': (
                    self.bootstrap_metrics['last_bootstrap'].isoformat()
                    if self.bootstrap_metrics['last_bootstrap'] else None
                )
            }
        }
    
    def get_dashboard_data(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Retrieve P2P metrics formatted for dashboard display with intelligent caching.
        
        This method provides a comprehensive, dashboard-ready snapshot of all P2P network
        metrics including peer discovery, workflows, and bootstrap operations. Results are
        cached for 30 seconds by default to reduce computational overhead during frequent
        polling by monitoring dashboards.
        
        Args:
            force_refresh (bool, optional): Whether to bypass cache and recalculate metrics.
                    False (default): Use cached data if available and fresh (< 30s old)
                    True: Ignore cache, recalculate all metrics, update cache
                    Defaults to False.
        
        Returns:
            Dict[str, Any]: Comprehensive P2P metrics dictionary formatted for dashboard display:
                {
                    'peer_discovery': {
                        'total': int,  # Total discovery attempts
                        'successful': int,  # Successful discoveries
                        'failed': int,  # Failed discoveries
                        'success_rate': float,  # Percentage (0-100)
                        'avg_duration_ms': float,  # Average discovery time
                        'by_source': Dict[str, int],  # Peers discovered per source
                        'last_discovery': str | None  # ISO 8601 timestamp or None
                    },
                    'workflows': {
                        'total': int,  # Total workflows tracked
                        'active': int,  # Currently running workflows
                        'completed': int,  # Successfully completed workflows
                        'failed': int,  # Failed workflows
                        'success_rate': float,  # Percentage (0-100)
                        'avg_duration_ms': float,  # Average execution time
                        'by_status': Dict[str, int],  # Count per status
                        'last_workflow': str | None  # ISO 8601 timestamp or None
                    },
                    'bootstrap': {
                        'total_attempts': int,  # Total bootstrap attempts
                        'successful': int,  # Successful bootstraps
                        'failed': int,  # Failed bootstraps
                        'success_rate': float,  # Percentage (0-100)
                        'avg_duration_ms': float,  # Average bootstrap time
                        'by_method': Dict[str, int],  # Count per bootstrap method
                        'last_bootstrap': str | None  # ISO 8601 timestamp or None
                    }
                }
        
        Example:
            >>> collector = P2PMetricsCollector()
            >>> # Get cached data (fast, for dashboard polling)
            >>> data = collector.get_dashboard_data()
            >>> print(f"Peer discovery success: {data['peer_discovery']['success_rate']}%")
            >>> print(f"Active workflows: {data['workflows']['active']}")
            >>> 
            >>> # Force refresh (slower, for manual refresh)
            >>> fresh_data = collector.get_dashboard_data(force_refresh=True)
            >>> 
            >>> # Display in dashboard
            >>> print("=== P2P Network Status ===")
            >>> for category, metrics in data.items():
            ...     print(f"\n{category.upper()}:")
            ...     print(f"  Success Rate: {metrics['success_rate']:.1f}%")
            ...     print(f"  Avg Duration: {metrics.get('avg_duration_ms', 0):.1f}ms")
        
        Note:
            - **Cache TTL**: 30 seconds (hardcoded in self._cache_ttl)
            - **Cache Key**: force_refresh parameter
            - **Cache Storage**: self._dashboard_cache, self._dashboard_cache_time
            - **Calculations**: Average times and success rates computed on cache miss
            - **Rounding**: All float values rounded to 2 decimal places
            - **Timestamps**: ISO 8601 format (YYYY-MM-DDTHH:MM:SS)
            - **None Handling**: Timestamps are None if no operations tracked yet
            - **Thread Safety**: Not thread-safe (no locking during cache check/update)
        
        Performance:
            - **Cache Hit**: <0.1ms (dictionary lookup + time comparison)
            - **Cache Miss**: 1-5ms (calculate averages + build structure)
            - **force_refresh=True**: Always 1-5ms (recalculate + cache update)
            - Dashboard polling every 1-5 seconds benefits from 30s cache
        
        Cache Behavior:
            **Cache Hit (fast path):**
            1. Check force_refresh=False
            2. Verify cache exists (_dashboard_cache not None)
            3. Check cache age < 30 seconds
            4. Return cached dictionary (no recalculation)
            
            **Cache Miss (slow path):**
            1. Calculate average times (_calculate_average_times)
            2. Calculate success rates (_calculate_success_rates)
            3. Build dashboard data structure (_build_dashboard_data)
            4. Update cache with new data
            5. Update cache timestamp
            6. Return fresh data
        
        Dashboard Integration:
            Designed for:
            - Grafana dashboards (JSON datasource)
            - Custom web dashboards (REST API endpoint)
            - CLI monitoring tools (JSON output)
            - Prometheus exporters (convert to metrics)
            - Alerting systems (threshold checks)
        
        Use Cases:
            - Real-time P2P network monitoring
            - Network health dashboards
            - Performance trending and analysis
            - Capacity planning
            - SLA compliance verification
            - Debugging network connectivity issues
        """
        now = datetime.utcnow()
        
        # Return cached data if available and fresh
        if (not force_refresh and 
            self._dashboard_cache is not None and 
            self._dashboard_cache_time is not None and
            now - self._dashboard_cache_time < self._cache_ttl):
            return self._dashboard_cache
        
        # Calculate metrics
        avg_times = self._calculate_average_times()
        success_rates = self._calculate_success_rates()
        dashboard_data = self._build_dashboard_data(avg_times, success_rates)
        
        # Update cache
        self._dashboard_cache = dashboard_data
        self._dashboard_cache_time = now
        
        return dashboard_data
    
    def get_alert_conditions(self) -> List[Dict[str, Any]]:
        """Check for P2P-specific alert conditions and return actionable alert objects.
        
        This method evaluates current P2P metrics against predefined thresholds to detect
        potential issues requiring attention. It generates structured alert objects for
        integration with alerting systems, logging, and monitoring dashboards.
        
        Returns:
            List[Dict[str, Any]]: List of active alert conditions (empty list if all healthy).
                    Each alert is a dictionary with the following structure:
                    {
                        'type': str,  # Alert severity: 'warning' or 'critical'
                        'component': str,  # Affected component: 'peer_discovery', 'workflows', 'bootstrap'
                        'message': str,  # Human-readable alert description
                        'timestamp': str  # ISO 8601 timestamp when alert was generated
                    }
                    
                    Alerts are ordered by generation (not by severity).
        
        Alert Conditions:
            **Peer Discovery Failure (Warning):**
            - **Threshold**: >30% failure rate
            - **Minimum Sample**: 10 discoveries
            - **Type**: 'warning'
            - **Component**: 'peer_discovery'
            - **Message**: "High peer discovery failure rate: X.X%"
            
            **Workflow Failure (Warning):**
            - **Threshold**: >20% failure rate
            - **Minimum Sample**: 5 completed/failed workflows
            - **Type**: 'warning'
            - **Component**: 'workflows'
            - **Message**: "High workflow failure rate: X.X%"
            
            **Bootstrap Failure (Critical):**
            - **Threshold**: >50% failure rate
            - **Minimum Sample**: 3 bootstrap attempts
            - **Type**: 'critical'
            - **Component**: 'bootstrap'
            - **Message**: "High bootstrap failure rate: X.X%"
        
        Example:
            >>> collector = P2PMetricsCollector()
            >>> # Check for alerts
            >>> alerts = collector.get_alert_conditions()
            >>> if alerts:
            ...     print(f"⚠️ {len(alerts)} alert(s) detected:")
            ...     for alert in alerts:
            ...         icon = "🔴" if alert['type'] == 'critical' else "🟡"
            ...         print(f"{icon} [{alert['component']}] {alert['message']}")
            ... else:
            ...     print("✅ All P2P metrics healthy")
            >>> 
            >>> # Send to alerting system
            >>> for alert in alerts:
            ...     if alert['type'] == 'critical':
            ...         send_pagerduty_alert(alert['message'])
            ...     else:
            ...         send_slack_notification(alert['message'])
        
        Note:
            - **Stateless**: Alerts are calculated on-demand (not persisted)
            - **Idempotent**: Calling multiple times with same metrics returns same alerts
            - **No Deduplication**: Same alert returned on each call if condition persists
            - **No History**: Previous alerts are not tracked (stateless evaluation)
            - **Threshold-Based**: Simple percentage-based thresholds (no ML/anomaly detection)
            - **Minimum Samples**: Required to avoid false positives with low sample sizes
            - **Thread Safety**: Not thread-safe (reads metrics without locking)
        
        Alert Severity Levels:
            **Warning:**
            - Degraded performance, but system still operational
            - Requires attention but not immediate action
            - May self-recover or indicate temporary network issues
            - Examples: 30% peer discovery failures, 20% workflow failures
            
            **Critical:**
            - Severe degradation affecting system functionality
            - Requires immediate investigation and intervention
            - May indicate complete network partition or system failure
            - Examples: 50% bootstrap failures (node cannot join network)
        
        Threshold Rationale:
            - **Peer Discovery 30%**: Some failures expected due to network churn
            - **Workflow 20%**: Workflows should be reliable, higher threshold acceptable
            - **Bootstrap 50%**: Bootstrap is critical, but retries common, so 50% threshold
        
        Integration Patterns:
            **Polling:**
            ```python
            while True:
                alerts = collector.get_alert_conditions()
                for alert in alerts:
                    alert_manager.send(alert)
                time.sleep(30)
            ```
            
            **Event-Driven:**
            ```python
            def on_metric_update():
                alerts = collector.get_alert_conditions()
                if alerts:
                    for alert in alerts:
                        event_bus.publish('p2p.alert', alert)
            ```
            
            **Dashboard:**
            ```python
            @app.route('/alerts')
            def get_alerts():
                return jsonify(collector.get_alert_conditions())
            ```
        
        Use Cases:
            - Automated alerting and paging
            - Dashboard alert badges
            - Health check endpoint responses
            - Proactive issue detection
            - SLA monitoring and reporting
            - Network diagnostics and troubleshooting
        
        Performance:
            - O(1) evaluation (3 simple threshold checks)
            - <0.5ms typical execution time
            - No network I/O or expensive calculations
            - Safe to call frequently (every 1-5 seconds)
        """
        alerts = []
        
        # High discovery failure rate
        if self.peer_discovery_metrics['total_discoveries'] > 10:
            failure_rate = (
                self.peer_discovery_metrics['failed_discoveries'] / 
                self.peer_discovery_metrics['total_discoveries']
            )
            if failure_rate > 0.3:  # >30% failure rate
                alerts.append({
                    'type': 'warning',
                    'component': 'peer_discovery',
                    'message': f'High peer discovery failure rate: {failure_rate*100:.1f}%',
                    'timestamp': datetime.utcnow().isoformat()
                })
        
        # High workflow failure rate
        total_workflows = (
            self.workflow_metrics['completed_workflows'] + 
            self.workflow_metrics['failed_workflows']
        )
        if total_workflows > 5:
            failure_rate = self.workflow_metrics['failed_workflows'] / total_workflows
            if failure_rate > 0.2:  # >20% failure rate
                alerts.append({
                    'type': 'warning',
                    'component': 'workflows',
                    'message': f'High workflow failure rate: {failure_rate*100:.1f}%',
                    'timestamp': datetime.utcnow().isoformat()
                })
        
        # High bootstrap failure rate
        if self.bootstrap_metrics['total_bootstrap_attempts'] > 3:
            failure_rate = (
                self.bootstrap_metrics['failed_bootstraps'] / 
                self.bootstrap_metrics['total_bootstrap_attempts']
            )
            if failure_rate > 0.5:  # >50% failure rate
                alerts.append({
                    'type': 'critical',
                    'component': 'bootstrap',
                    'message': f'High bootstrap failure rate: {failure_rate*100:.1f}%',
                    'timestamp': datetime.utcnow().isoformat()
                })
        
        return alerts


# ✅ BETTER APPROACH
metrics_collector = None

def get_metrics_collector() -> EnhancedMetricsCollector:
    """Get or create the global :class:`EnhancedMetricsCollector` singleton.

    Returns:
        The global :class:`EnhancedMetricsCollector` instance, creating it on
        first call.
    """
    global metrics_collector
    if metrics_collector is None:
        metrics_collector = EnhancedMetricsCollector()
    return metrics_collector

# P2P metrics collector instance
p2p_metrics_collector = None

def get_p2p_metrics_collector() -> P2PMetricsCollector:
    """Get or create the global P2P metrics collector instance."""
    global p2p_metrics_collector
    if p2p_metrics_collector is None:
        p2p_metrics_collector = P2PMetricsCollector()
    return p2p_metrics_collector

# Global monitoring instances
metrics_collector = EnhancedMetricsCollector()
p2p_metrics_collector = P2PMetricsCollector()

# ipfs_datasets_py/mcp_server/monitoring.py

import anyio
import inspect
import time
import logging
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from collections import defaultdict, deque
from contextlib import asynccontextmanager

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
    
    def __init__(self, enabled: bool = True, retention_hours: int = 24):
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
    
    def _start_monitoring(self):
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
    
    def start_monitoring(self):
        """Public method to start monitoring when an event loop is available."""
        if self.enabled:
            self._start_monitoring()
    
    async def _monitoring_loop(self):
        """Main monitoring loop that collects system metrics."""
        while True:
            try:
                await self._collect_system_metrics()
                await self._check_health()
                await self._check_alerts()
                await anyio.sleep(30)  # Collect every 30 seconds
                
            except anyio.get_cancelled_exc_class()():
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await anyio.sleep(60)
    
    async def _cleanup_loop(self):
        """Clean up old metrics data."""
        while True:
            try:
                await self._cleanup_old_data()
                await anyio.sleep(3600)  # Cleanup every hour
                
            except anyio.get_cancelled_exc_class()():
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                await anyio.sleep(3600)
    
    async def _collect_system_metrics(self):
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
                    
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
    
    def increment_counter(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None):
        """Increment a counter metric."""
        if not self.enabled:
            return
            
        with self._lock:
            self.counters[name] += value
            
            if labels:
                labeled_name = f"{name}_{self._serialize_labels(labels)}"
                self.counters[labeled_name] += value
    
    def set_gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Set a gauge metric value."""
        if not self.enabled:
            return
            
        with self._lock:
            self.gauges[name] = value
            
            if labels:
                labeled_name = f"{name}_{self._serialize_labels(labels)}"
                self.gauges[labeled_name] = value
    
    def observe_histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None):
        """Add an observation to a histogram."""
        if not self.enabled:
            return
            
        with self._lock:
            self.histograms[name].append(value)
            
            if labels:
                labeled_name = f"{name}_{self._serialize_labels(labels)}"
                self.histograms[labeled_name].append(value)
    
    @asynccontextmanager
    async def track_request(self, endpoint: str):
        """Context manager to track request duration and count."""
        try:
            task_id = str(id(anyio.get_current_task()))
        except Exception:
            task_id = "sync"
        request_id = f"{endpoint}_{task_id}"
        start_time = time.time()
        
        try:
            with self._lock:
                self.active_requests[request_id] = datetime.utcnow()
                self.request_count += 1
            
            yield
            
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
    
    def track_tool_execution(self, tool_name: str, execution_time_ms: float, success: bool):
        """Track tool execution metrics."""
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
    
    def register_health_check(self, name: str, check_func: Callable):
        """Register a health check function."""
        self.health_check_registry[name] = check_func
    
    async def _check_health(self):
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
                    
            except Exception as e:
                self.health_checks[name] = HealthCheckResult(
                    component=name,
                    status='critical',
                    message=f'Health check failed: {e}',
                    details={'error': str(e)}
                )
    
    async def _check_alerts(self):
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
    
    async def _cleanup_old_data(self):
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
        """Get a comprehensive metrics summary."""
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
        """Get performance trends over the specified time period."""
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
    
    async def shutdown(self):
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
    
    def __init__(self, base_collector: Optional[EnhancedMetricsCollector] = None):
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
    ):
        """Track a peer discovery operation."""
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
    ):
        """Track a workflow execution."""
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
    ):
        """Track a bootstrap operation."""
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
        """
        Get P2P metrics formatted for dashboard display.
        Results are cached for 30 seconds to reduce overhead.
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
        """Check for P2P-specific alert conditions."""
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

def get_metrics_collector():
    global metrics_collector
    if metrics_collector is None:
        metrics_collector = EnhancedMetricsCollector()
    return metrics_collector

# P2P metrics collector instance
p2p_metrics_collector = None

def get_p2p_metrics_collector():
    """Get or create the global P2P metrics collector instance."""
    global p2p_metrics_collector
    if p2p_metrics_collector is None:
        p2p_metrics_collector = P2PMetricsCollector()
    return p2p_metrics_collector

# Global monitoring instances
metrics_collector = EnhancedMetricsCollector()
p2p_metrics_collector = P2PMetricsCollector()

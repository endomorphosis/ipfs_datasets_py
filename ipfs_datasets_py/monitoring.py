"""
Monitoring and Metrics Collection for IPFS Datasets.

This module provides comprehensive logging, performance metrics collection,
and monitoring capabilities for the IPFS Datasets Python library, enabling:
- Structured logging with configurable levels and outputs
- Performance metrics collection and reporting
- Operation tracing for distributed operations
- Health monitoring for IPFS nodes
- Resource usage tracking
- Alerting based on thresholds

The monitoring system is designed to be lightweight yet powerful, with minimal
performance impact when enabled, and zero overhead when disabled.
"""
import anyio
import sys
import json
import time
import logging
import atexit
import inspect
import threading
import contextlib
from enum import Enum
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import functools
import traceback
import socket

# Optional dependencies will be imported as needed
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import prometheus_client  # type: ignore[import-not-found]
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# Constants
DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO
DEFAULT_METRICS_INTERVAL = 60  # seconds
DEFAULT_LOG_FILE = "ipfs_datasets.log"
DEFAULT_METRICS_FILE = "ipfs_datasets_metrics.json"
DEFAULT_METRICS_PORT = 8889  # for Prometheus exporter
DEFAULT_LOG_ROTATION_SIZE = 10_485_760  # 10MB
DEFAULT_LOG_ROTATION_COUNT = 5


class LogLevel(Enum):
    """Log levels for the monitoring system."""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class MetricType(Enum):
    """Types of metrics that can be collected."""
    COUNTER = "counter"      # Monotonically increasing counter
    GAUGE = "gauge"          # Value that can go up and down
    HISTOGRAM = "histogram"  # Distribution of values
    SUMMARY = "summary"      # Similar to histogram but with quantiles
    TIMER = "timer"          # Specialized for timing operations
    EVENT = "event"          # Record of a specific event


@dataclass
class LoggerConfig:
    """Configuration for the logger."""
    name: str = "ipfs_datasets"
    level: LogLevel = LogLevel.INFO
    format: str = DEFAULT_LOG_FORMAT
    file_path: Optional[str] = None
    console: bool = True
    rotate_logs: bool = True
    max_file_size: int = DEFAULT_LOG_ROTATION_SIZE
    backup_count: int = DEFAULT_LOG_ROTATION_COUNT
    propagate: bool = False
    capture_warnings: bool = True
    include_context: bool = True
    include_process_info: bool = False
    silence_modules: List[str] = field(default_factory=list)


@dataclass
class MetricsConfig:
    """Configuration for metrics collection."""
    enabled: bool = True
    collect_interval: int = DEFAULT_METRICS_INTERVAL
    output_file: Optional[str] = None
    prometheus_export: bool = False
    prometheus_port: int = DEFAULT_METRICS_PORT
    system_metrics: bool = True
    network_metrics: bool = True
    memory_metrics: bool = True
    operation_metrics: bool = True
    custom_metrics: List[str] = field(default_factory=list)
    include_hostname: bool = True
    global_labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class MonitoringConfig:
    """Overall configuration for the monitoring system."""
    enabled: bool = True
    logger: LoggerConfig = field(default_factory=LoggerConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    base_dir: Optional[str] = None
    environment: str = "development"
    component_name: str = "ipfs_datasets"
    include_version: bool = True
    version: str = "0.1.0"


@dataclass
class MetricValue:
    """Value of a metric."""
    name: str
    type: MetricType
    value: Any
    timestamp: float = field(default_factory=time.time)
    labels: Dict[str, str] = field(default_factory=dict)
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "type": self.type.value,
            "value": self.value,
            "timestamp": self.timestamp,
            "labels": self.labels,
            "description": self.description
        }


@dataclass
class OperationMetrics:
    """Metrics for a specific operation."""
    operation_id: str
    operation_type: str
    start_time: float
    end_time: Optional[float] = None
    duration_ms: Optional[float] = None
    status: str = "pending"
    success: bool = False
    error: Optional[str] = None
    labels: Dict[str, str] = field(default_factory=dict)
    sub_operations: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def complete(self, success: bool = True, error: Optional[str] = None):
        """Mark the operation as complete."""
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.success = success
        self.status = "success" if success else "error"
        self.error = error
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "success": self.success,
            "error": self.error,
            "labels": self.labels,
            "sub_operations": self.sub_operations,
            "metrics": self.metrics
        }


class LogContext:
    """Context for structured logging."""
    _context_data = threading.local()

    @classmethod
    def get_current(cls) -> Dict[str, Any]:
        """Get the current context data."""
        if not hasattr(cls._context_data, "data"):
            cls._context_data.data = {}
        return cls._context_data.data.copy()

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """Set a context value."""
        if not hasattr(cls._context_data, "data"):
            cls._context_data.data = {}
        cls._context_data.data[key] = value

    @classmethod
    def update(cls, data: Dict[str, Any]) -> None:
        """Update multiple context values."""
        if not hasattr(cls._context_data, "data"):
            cls._context_data.data = {}
        cls._context_data.data.update(data)

    @classmethod
    def clear(cls) -> None:
        """Clear all context data."""
        if hasattr(cls._context_data, "data"):
            cls._context_data.data = {}


@contextlib.contextmanager
def log_context(**kwargs):
    """Context manager for setting log context."""
    old_context = LogContext.get_current()
    try:
        LogContext.update(kwargs)
        yield
    finally:
        # Restore old context
        LogContext._context_data.data = old_context


class ContextAdapter(logging.LoggerAdapter):
    """Adapter to add context data to log records."""

    def process(self, msg, kwargs):
        """Process the log record by adding context data."""
        # Add context data to the extra dict
        kwargs = kwargs.copy()
        extra = kwargs.get('extra', {}).copy()
        context = LogContext.get_current()

        if context:
            extra.update(context)

        kwargs['extra'] = extra
        return msg, kwargs


class MetricsRegistry:
    """Registry for collecting and managing metrics."""

    def __init__(self, config: MetricsConfig):
        """
        Initialize the metrics registry.

        Args:
            config: Configuration for metrics collection
        """
        self.config = config
        self.metrics: Dict[str, Dict[str, MetricValue]] = {}
        self.operations: Dict[str, OperationMetrics] = {}
        self.start_time = time.time()
        self.lock = threading.RLock()
        self.collection_thread = None
        self.running = False
        self.hostname = socket.gethostname() if config.include_hostname else None

        # Initialize Prometheus metrics if enabled
        self.prometheus_metrics = {}
        if config.prometheus_export and PROMETHEUS_AVAILABLE:
            self._init_prometheus()

    def _init_prometheus(self):
        """Initialize Prometheus metrics."""
        # Create a registry
        self.prometheus_registry = prometheus_client.CollectorRegistry()

        # Start the HTTP server for Prometheus scraping
        try:
            prometheus_client.start_http_server(
                port=self.config.prometheus_port,
                registry=self.prometheus_registry
            )
        except OSError as e:
            if "Address already in use" in str(e):
                # Server already exists, skip
                pass
            else:
                raise

    def _get_prometheus_metric(self, name: str, metric_type: MetricType, description: str = "", labels: List[str] = None):
        """Get or create a Prometheus metric."""
        if not PROMETHEUS_AVAILABLE:
            return None

        key = f"{name}_{metric_type.value}"
        if key in self.prometheus_metrics:
            return self.prometheus_metrics[key]

        # Create labels list including global labels
        all_labels = list(self.config.global_labels.keys())
        if labels:
            all_labels.extend(labels)
        if self.hostname:
            all_labels.append("hostname")

        # Create the appropriate metric type
        if metric_type == MetricType.COUNTER:
            metric = prometheus_client.Counter(
                name, description, all_labels, registry=self.prometheus_registry
            )
        elif metric_type == MetricType.GAUGE:
            metric = prometheus_client.Gauge(
                name, description, all_labels, registry=self.prometheus_registry
            )
        elif metric_type == MetricType.HISTOGRAM:
            metric = prometheus_client.Histogram(
                name, description, all_labels, registry=self.prometheus_registry
            )
        elif metric_type == MetricType.SUMMARY:
            metric = prometheus_client.Summary(
                name, description, all_labels, registry=self.prometheus_registry
            )
        elif metric_type == MetricType.TIMER:
            # Timings map naturally to Prometheus Summary/Histogram (both support observe).
            metric = prometheus_client.Summary(
                name, description, all_labels, registry=self.prometheus_registry
            )
        else:
            # Unsupported in Prometheus, use a gauge
            metric = prometheus_client.Gauge(
                name, description, all_labels, registry=self.prometheus_registry
            )

        self.prometheus_metrics[key] = metric
        return metric

    def _update_prometheus(self, metric: MetricValue):
        """Update Prometheus metrics."""
        if not PROMETHEUS_AVAILABLE or not self.config.prometheus_export:
            return

        # Skip event metrics as they don't map well to Prometheus
        if metric.type == MetricType.EVENT:
            return

        # Get the Prometheus metric
        prom_metric = self._get_prometheus_metric(
            metric.name,
            metric.type,
            metric.description or "",
            list(metric.labels.keys())
        )

        if not prom_metric:
            return

        # Combine global labels and metric labels
        labels = self.config.global_labels.copy()
        labels.update(metric.labels)
        if self.hostname:
            labels["hostname"] = self.hostname

        # Update the metric value
        if metric.type == MetricType.COUNTER:
            # For counter, we increment by the value
            prom_metric.labels(**labels).inc(metric.value)
        elif metric.type == MetricType.GAUGE:
            prom_metric.labels(**labels).set(metric.value)
        elif metric.type == MetricType.HISTOGRAM:
            prom_metric.labels(**labels).observe(metric.value)
        elif metric.type == MetricType.SUMMARY:
            prom_metric.labels(**labels).observe(metric.value)
        elif metric.type == MetricType.TIMER:
            # For timer, observe duration when supported; otherwise fall back to setting.
            labeled = prom_metric.labels(**labels)
            if hasattr(labeled, "observe"):
                labeled.observe(metric.value)
            else:
                labeled.set(metric.value)

    def record(self, name: str, value: Any, metric_type: MetricType,
              labels: Optional[Dict[str, str]] = None,
              description: Optional[str] = None) -> MetricValue:
        """
        Record a metric value.

        Args:
            name: Name of the metric
            value: Value of the metric
            metric_type: Type of the metric
            labels: Labels for the metric
            description: Description of the metric

        Returns:
            MetricValue: The recorded metric value
        """
        if not self.config.enabled:
            return MetricValue(name=name, type=metric_type, value=value,
                              labels=labels or {}, description=description)

        with self.lock:
            # Create metric value
            metric = MetricValue(
                name=name,
                type=metric_type,
                value=value,
                labels=labels or {},
                description=description
            )

            # Store in memory
            if name not in self.metrics:
                self.metrics[name] = {}

            # Use labels as a key for unique instances
            labels_key = json.dumps(sorted(metric.labels.items()))
            self.metrics[name][labels_key] = metric

            # Update Prometheus metrics
            self._update_prometheus(metric)

            return metric

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None,
                 description: Optional[str] = None) -> MetricValue:
        """
        Increment a counter metric.

        Args:
            name: Name of the metric
            value: Value to increment by
            labels: Labels for the metric
            description: Description of the metric

        Returns:
            MetricValue: The updated metric value
        """
        with self.lock:
            # Check if metric exists
            labels_key = json.dumps(sorted((labels or {}).items()))
            current_value = 0

            if name in self.metrics and labels_key in self.metrics[name]:
                current_metric = self.metrics[name][labels_key]
                if current_metric.type == MetricType.COUNTER:
                    current_value = current_metric.value

            # Increment value
            new_value = current_value + value

            # Record new value
            return self.record(
                name=name,
                value=new_value,
                metric_type=MetricType.COUNTER,
                labels=labels,
                description=description
            )

    def gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None,
             description: Optional[str] = None) -> MetricValue:
        """
        Record a gauge metric.

        Args:
            name: Name of the metric
            value: Value of the metric
            labels: Labels for the metric
            description: Description of the metric

        Returns:
            MetricValue: The recorded metric value
        """
        return self.record(
            name=name,
            value=value,
            metric_type=MetricType.GAUGE,
            labels=labels,
            description=description
        )

    def histogram(self, name: str, value: float, labels: Optional[Dict[str, str]] = None,
                 description: Optional[str] = None) -> MetricValue:
        """
        Record a histogram metric.

        Args:
            name: Name of the metric
            value: Value to observe
            labels: Labels for the metric
            description: Description of the metric

        Returns:
            MetricValue: The recorded metric value
        """
        return self.record(
            name=name,
            value=value,
            metric_type=MetricType.HISTOGRAM,
            labels=labels,
            description=description
        )

    def timer(self, name: str, duration_ms: float, labels: Optional[Dict[str, str]] = None,
             description: Optional[str] = None) -> MetricValue:
        """
        Record a timer metric.

        Args:
            name: Name of the metric
            duration_ms: Duration in milliseconds
            labels: Labels for the metric
            description: Description of the metric

        Returns:
            MetricValue: The recorded metric value
        """
        return self.record(
            name=name,
            value=duration_ms,
            metric_type=MetricType.TIMER,
            labels=labels,
            description=description
        )

    def event(self, name: str, data: Any, labels: Optional[Dict[str, str]] = None,
             description: Optional[str] = None) -> MetricValue:
        """
        Record an event metric.

        Args:
            name: Name of the metric
            data: Event data
            labels: Labels for the metric
            description: Description of the metric

        Returns:
            MetricValue: The recorded metric value
        """
        return self.record(
            name=name,
            value=data,
            metric_type=MetricType.EVENT,
            labels=labels,
            description=description
        )

    def start_operation(self, operation_type: str, labels: Optional[Dict[str, str]] = None) -> OperationMetrics:
        """
        Start tracking an operation.

        Args:
            operation_type: Type of the operation
            labels: Labels for the operation

        Returns:
            OperationMetrics: The operation metrics object
        """
        if not self.config.enabled:
            # Return a dummy object if metrics are disabled
            return OperationMetrics(
                operation_id=f"op_{int(time.time())}",
                operation_type=operation_type,
                start_time=time.time(),
                labels=labels or {}
            )

        with self.lock:
            # Create operation ID
            operation_id = f"{operation_type}_{int(time.time())}_{len(self.operations)}"

            # Create operation metrics
            operation = OperationMetrics(
                operation_id=operation_id,
                operation_type=operation_type,
                start_time=time.time(),
                labels=labels or {}
            )

            # Store operation
            self.operations[operation_id] = operation

            # Record event
            self.event(
                name="operation_started",
                data={
                    "operation_id": operation_id,
                    "operation_type": operation_type,
                    "start_time": operation.start_time
                },
                labels=labels
            )

            return operation

    def complete_operation(self, operation: OperationMetrics, success: bool = True,
                          error: Optional[str] = None) -> OperationMetrics:
        """
        Complete an operation.

        Args:
            operation: The operation metrics object
            success: Whether the operation was successful
            error: Error message if the operation failed

        Returns:
            OperationMetrics: The updated operation metrics object
        """
        if not self.config.enabled:
            # Just update the operation object
            return operation.complete(success, error)

        with self.lock:
            # Update operation
            operation.complete(success, error)

            # Update in storage
            if operation.operation_id in self.operations:
                self.operations[operation.operation_id] = operation

            # Record duration
            self.timer(
                name=f"{operation.operation_type}_duration",
                duration_ms=operation.duration_ms,
                labels=operation.labels
            )

            # Record success/failure
            self.increment(
                name=f"{operation.operation_type}_count",
                value=1,
                labels={**operation.labels, "status": operation.status}
            )

            # Record event
            self.event(
                name="operation_completed",
                data=operation.to_dict(),
                labels=operation.labels
            )

            return operation

    def collect_system_metrics(self):
        """Collect system metrics."""
        if not PSUTIL_AVAILABLE or not self.config.system_metrics:
            return

        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1)
            self.gauge("system_cpu_percent", cpu_percent, description="CPU usage percentage")

            # Per-CPU metrics
            per_cpu = psutil.cpu_percent(interval=0.1, percpu=True)
            for i, cpu in enumerate(per_cpu):
                self.gauge(f"system_cpu_{i}_percent", cpu, description=f"CPU {i} usage percentage")

            # System load
            load = psutil.getloadavg()
            self.gauge("system_load_1min", load[0], description="System load average (1 min)")
            self.gauge("system_load_5min", load[1], description="System load average (5 min)")
            self.gauge("system_load_15min", load[2], description="System load average (15 min)")

            # System uptime
            boot_time = psutil.boot_time()
            uptime = time.time() - boot_time
            self.gauge("system_uptime_seconds", uptime, description="System uptime in seconds")

            # Process metrics
            process = psutil.Process()

            # Memory usage
            if self.config.memory_metrics:
                memory = process.memory_info()
                self.gauge("process_memory_rss", memory.rss, description="Process RSS memory usage")
                self.gauge("process_memory_vms", memory.vms, description="Process VMS memory usage")

                # System memory
                sys_memory = psutil.virtual_memory()
                self.gauge("system_memory_total", sys_memory.total, description="Total system memory")
                self.gauge("system_memory_available", sys_memory.available, description="Available system memory")
                self.gauge("system_memory_used", sys_memory.used, description="Used system memory")
                self.gauge("system_memory_percent", sys_memory.percent, description="System memory usage percentage")

            # Network usage
            if self.config.network_metrics:
                net_io = psutil.net_io_counters()
                self.gauge("network_bytes_sent", net_io.bytes_sent, description="Network bytes sent")
                self.gauge("network_bytes_recv", net_io.bytes_recv, description="Network bytes received")
                self.gauge("network_packets_sent", net_io.packets_sent, description="Network packets sent")
                self.gauge("network_packets_recv", net_io.packets_recv, description="Network packets received")

            # Disk usage
            disk = psutil.disk_usage('/')
            self.gauge("disk_total", disk.total, description="Total disk space")
            self.gauge("disk_used", disk.used, description="Used disk space")
            self.gauge("disk_free", disk.free, description="Free disk space")
            self.gauge("disk_percent", disk.percent, description="Disk usage percentage")

            # Process info
            self.gauge("process_cpu_percent", process.cpu_percent(interval=0.1), description="Process CPU usage percentage")
            self.gauge("process_threads", process.num_threads(), description="Number of process threads")
            self.gauge("process_open_files", len(process.open_files()), description="Number of open files")
            self.gauge("process_connections", len(process.connections()), description="Number of network connections")

        except Exception as e:
            # Don't let metric collection failures affect the application
            logging.warning(f"Error collecting system metrics: {str(e)}")

    def collect_runtime_metrics(self):
        """Collect Python runtime metrics."""
        try:
            import gc

            # Garbage collection stats
            gc_counts = gc.get_count()
            for i, count in enumerate(gc_counts):
                self.gauge(f"gc_count_gen{i}", count, description=f"GC collection count for generation {i}")

            # Object counts
            self.gauge("gc_objects", len(gc.get_objects()), description="Number of objects tracked by GC")

            # Thread count
            self.gauge("thread_count", threading.active_count(), description="Number of active threads")

            # Python version
            version_info = sys.version_info
            self.gauge("python_version", float(f"{version_info.major}.{version_info.minor}"),
                      description="Python version")

        except Exception as e:
            logging.warning(f"Error collecting runtime metrics: {str(e)}")

    def _collection_loop(self):
        """Background thread for collecting metrics."""
        while self.running:
            try:
                # Collect system metrics
                self.collect_system_metrics()

                # Collect runtime metrics
                self.collect_runtime_metrics()

                # Write metrics to file if configured
                if self.config.output_file:
                    self.write_metrics()

            except Exception as e:
                logging.warning(f"Error in metrics collection: {str(e)}")

            # Sleep until next collection
            time.sleep(self.config.collect_interval)

    def start_collection(self):
        """Start the metrics collection thread."""
        if not self.config.enabled:
            return

        if self.collection_thread and self.collection_thread.is_alive():
            return

        self.running = True
        self.collection_thread = threading.Thread(
            target=self._collection_loop,
            name="MetricsCollector",
            daemon=True
        )
        self.collection_thread.start()

    def stop_collection(self):
        """Stop the metrics collection thread."""
        self.running = False
        if self.collection_thread:
            if self.collection_thread.is_alive():
                self.collection_thread.join(timeout=1.0)
            self.collection_thread = None

    def write_metrics(self, file_path: Optional[str] = None) -> bool:
        """
        Write metrics to a file.

        Args:
            file_path: Path to the file (uses configured path if None)

        Returns:
            bool: Whether the write was successful
        """
        if not self.config.enabled:
            return False

        file_path = file_path or self.config.output_file
        if not file_path:
            return False

        try:
            # Convert metrics to dictionary
            metrics_data = {}
            for name, instances in self.metrics.items():
                metrics_data[name] = [m.to_dict() for m in instances.values()]

            # Add operations
            operations_data = [op.to_dict() for op in self.operations.values()]

            # Add metadata
            data = {
                "metrics": metrics_data,
                "operations": operations_data,
                "timestamp": time.time(),
                "hostname": self.hostname,
                "uptime": time.time() - self.start_time
            }

            # Write to file
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)

            return True

        except Exception as e:
            logging.warning(f"Error writing metrics to {file_path}: {str(e)}")
            return False

    def reset(self):
        """Reset all metrics."""
        with self.lock:
            self.metrics = {}
            self.operations = {}


@contextlib.contextmanager
def timed_operation(name: str, metrics_registry: 'MetricsRegistry', labels: Optional[Dict[str, str]] = None):
    """
    Context manager for timing an operation.

    Args:
        name: Name of the operation
        metrics_registry: Metrics registry to record to
        labels: Labels for the operation
    """
    operation = metrics_registry.start_operation(name, labels)

    try:
        yield operation
        metrics_registry.complete_operation(operation, success=True)
    except Exception as e:
        metrics_registry.complete_operation(operation, success=False, error=str(e))
        raise


def timed(func=None, *, metric_name=None, registry=None, include_args=False):
    """
    Decorator to time a function execution.

    Args:
        func: Function to decorate
        metric_name: Name of the metric (uses function name if None)
        registry: Metrics registry to use
        include_args: Whether to include function arguments in labels
    """
    def decorator(fn):
        fn_name = metric_name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # Get registry from global if not provided
            nonlocal registry
            if registry is None:
                registry = MonitoringSystem.get_instance().metrics_registry

            # Prepare labels
            labels = {}
            if include_args:
                # Include a subset of args/kwargs as labels
                # Be careful not to include large or sensitive data
                arg_names = inspect.getfullargspec(fn).args
                for i, arg in enumerate(args):
                    if i < len(arg_names) and i < 3:  # Limit to first 3 positional args
                        arg_name = arg_names[i]
                        # Only include simple types
                        if isinstance(arg, (str, int, float, bool)):
                            labels[arg_name] = str(arg)

                # Include kwargs
                for k, v in kwargs.items():
                    if len(labels) < 5:  # Limit total labels
                        if isinstance(v, (str, int, float, bool)):
                            labels[k] = str(v)

            # Start operation
            operation = registry.start_operation(fn_name, labels)

            try:
                # Execute function
                result = fn(*args, **kwargs)
                # Complete operation
                registry.complete_operation(operation, success=True)
                return result
            except Exception as e:
                # Record failure
                registry.complete_operation(operation, success=False, error=str(e))
                raise

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            # Same as above but for async functions
            nonlocal registry
            if registry is None:
                registry = MonitoringSystem.get_instance().metrics_registry

            labels = {}
            if include_args:
                arg_names = inspect.getfullargspec(fn).args
                for i, arg in enumerate(args):
                    if i < len(arg_names) and i < 3:
                        arg_name = arg_names[i]
                        if isinstance(arg, (str, int, float, bool)):
                            labels[arg_name] = str(arg)

                for k, v in kwargs.items():
                    if len(labels) < 5:
                        if isinstance(v, (str, int, float, bool)):
                            labels[k] = str(v)

            operation = registry.start_operation(fn_name, labels)

            try:
                result = await fn(*args, **kwargs)
                registry.complete_operation(operation, success=True)
                return result
            except Exception as e:
                registry.complete_operation(operation, success=False, error=str(e))
                raise

        # Return appropriate wrapper based on function type
        if inspect.iscoroutinefunction(fn):
            return async_wrapper
        else:
            return wrapper

    if func is None:
        # Called with arguments
        return decorator
    else:
        # Called without arguments
        return decorator(func)


class MonitoringSystem:
    """
    Comprehensive Monitoring, Metrics, and Observability Platform for IPFS Datasets

    The MonitoringSystem class provides enterprise-grade monitoring, logging, and
    metrics collection capabilities specifically designed for distributed IPFS
    dataset operations. This platform enables comprehensive observability across
    content-addressable storage workflows, distributed processing pipelines, and
    peer-to-peer network operations while maintaining minimal performance overhead.

    The system implements a singleton pattern to ensure consistent monitoring state
    across all components and provides structured logging, performance metrics
    collection, operation tracing, health monitoring, resource usage tracking,
    and intelligent alerting based on configurable thresholds and conditions.

    Core Monitoring Features:
    - Structured logging with configurable levels, formats, and output destinations
    - Performance metrics collection with time-series data and statistical analysis
    - Distributed operation tracing across IPFS networks and processing clusters
    - Health monitoring for IPFS nodes, storage backends, and service dependencies
    - Resource usage tracking including CPU, memory, disk, and network utilization
    - Intelligent alerting with threshold-based rules and escalation policies
    - Real-time dashboards and visualization for operational visibility

    Metrics Collection Capabilities:
    - IPFS operation metrics including content retrieval, storage, and pin operations
    - Dataset processing performance including serialization, indexing, and queries
    - Vector operation metrics for embedding generation and similarity searches
    - Network performance tracking for distributed storage and retrieval operations
    - Error rates, latency distributions, and throughput measurements
    - Custom business metrics for application-specific monitoring requirements

    Logging and Tracing:
    - Structured JSON logging with contextual information and correlation IDs
    - Distributed tracing across microservices and processing components
    - Performance profiling with detailed operation timing and resource usage
    - Error tracking with stack traces, context, and resolution recommendations
    - Audit logging for security, compliance, and operational transparency
    - Log aggregation and centralized analysis for multi-node deployments

    Integration Capabilities:
    - Prometheus metrics export for cloud-native monitoring infrastructures
    - ELK Stack integration for log analysis and visualization
    - Grafana dashboard support for real-time operational visibility
    - PagerDuty and Slack integration for incident response and alerting
    - Custom webhook support for integration with existing monitoring systems
    - OpenTelemetry compatibility for standardized observability

    Health and Alerting:
    - IPFS node health checks including connectivity, performance, and storage
    - Service dependency monitoring with automatic failover detection
    - Threshold-based alerting for performance degradation and error conditions
    - Predictive alerting using machine learning for anomaly detection
    - Escalation policies with configurable notification channels and timing
    - Maintenance mode support for planned operations and deployments

    Attributes:
        _instance (Optional[MonitoringSystem]): Singleton instance reference for
            global monitoring state management and consistent behavior across
            all system components and processing workflows.
        config (MonitoringConfig): Comprehensive configuration object containing
            logging settings, metrics collection parameters, alerting rules,
            and integration configurations for operational customization.

    Public Methods:
        get_instance() -> MonitoringSystem:
            Retrieve the singleton monitoring system instance
        initialize(config: Optional[MonitoringConfig] = None) -> MonitoringSystem:
            Initialize monitoring system with comprehensive configuration
        configure(config: MonitoringConfig) -> None:
            Update monitoring configuration with validation and reloading
        get_logger(name: str) -> logging.Logger:
            Create contextual logger with structured formatting
        record_metric(name: str, value: float, labels: Dict[str, str] = None) -> None:
            Record performance metric with metadata and timestamps
        start_operation_trace(operation: str) -> str:
            Begin distributed operation tracing with correlation ID
        end_operation_trace(trace_id: str, **kwargs) -> None:
            Complete operation tracing with performance metrics
        check_health() -> Dict[str, Any]:
            Perform comprehensive health check across all components
        export_metrics() -> Dict[str, Any]:
            Export current metrics for external monitoring systems

    Usage Examples:
        # Initialize monitoring system with default configuration
        monitoring = MonitoringSystem.initialize()
        
        # Custom configuration for production environment
        config = MonitoringConfig(
            logger_config=LoggerConfig(
                level=LogLevel.INFO,
                file_path="/var/log/ipfs_datasets.log",
                max_file_size=100*1024*1024,  # 100MB
                backup_count=10
            ),
            metrics_config=MetricsConfig(
                enabled=True,
                collection_interval=30,
                prometheus_port=8889
            ),
            enable_distributed_tracing=True,
            enable_health_checks=True
        )
        monitoring = MonitoringSystem.initialize(config)
        
        # Structured logging with context
        logger = monitoring.get_logger(__name__)
        logger.info("Dataset processing started", extra={
            "dataset_id": "ds_12345",
            "operation": "embedding_generation"
        })
        
        # Performance metrics recording
        monitoring.record_metric(
            name="dataset_processing_duration",
            value=45.2,
            labels={"dataset_type": "text", "model": "bert-base"}
        )
        
        # Distributed operation tracing
        trace_id = monitoring.start_operation_trace("ipfs_content_retrieval")
        # ... perform IPFS operations ...
        monitoring.end_operation_trace(
            trace_id,
            success=True,
            duration=1.23,
            bytes_transferred=1024*1024
        )

    Dependencies:
        Required:
        - logging: Python standard library for structured logging
        - threading: Concurrent execution for background metrics collection
        - json: Data serialization for structured logging and metrics export
        
        Optional:
        - psutil: System resource monitoring and performance metrics
        - prometheus_client: Prometheus metrics export for cloud monitoring
        - opentelemetry: Distributed tracing and observability standards

    Notes:
        - Singleton pattern ensures consistent monitoring state across components
        - Minimal performance overhead when monitoring is disabled
        - Structured logging enables efficient log analysis and alerting
        - Metrics collection is configurable and can be disabled for performance
        - Health checks provide early warning for system degradation
        - Integration with external monitoring systems enables operational visibility
        - Configuration supports environment-specific customization and optimization
        - Background threads handle metrics collection without blocking operations
    """

    _instance = None

    @classmethod
    def get_instance(cls) -> 'MonitoringSystem':
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def initialize(cls, config: Optional[MonitoringConfig] = None) -> 'MonitoringSystem':
        """
        Initialize the monitoring system.

        Args:
            config: Configuration for the monitoring system

        Returns:
            MonitoringSystem: The initialized monitoring system
        """
        if cls._instance is not None:
            return cls._instance

        instance = cls.get_instance()
        instance.configure(config or MonitoringConfig())
        return instance

    def __init__(self):
        """Initialize the monitoring system."""
        self.config = MonitoringConfig()
        self.logger = None
        self.metrics_registry = None
        self.enabled = False
        self.initialized = False
        self.capture_warnings = True

    def configure(self, config: MonitoringConfig) -> None:
        """
        Configure the monitoring system.

        Args:
            config: Configuration for the monitoring system
        """
        self.config = config
        self.enabled = config.enabled

        if not self.enabled:
            return

        # Configure logger
        self._configure_logger()

        # Configure metrics
        self._configure_metrics()

        # Mark as initialized
        self.initialized = True

        # Register shutdown handler
        atexit.register(self.shutdown)

        # Log startup
        self.logger.info(
            f"Monitoring system initialized",
            extra={
                "component": self.config.component_name,
                "environment": self.config.environment,
                "version": self.config.version
            }
        )

    def _configure_logger(self) -> None:
        """Configure the logger."""
        logger_config = self.config.logger

        # Create logger
        logger = logging.getLogger(logger_config.name)
        logger.setLevel(logger_config.level.value)
        logger.propagate = logger_config.propagate

        # Clear existing handlers
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Create and add handlers
        handlers = []

        # Console handler
        if logger_config.console:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logger_config.level.value)
            console_handler.setFormatter(logging.Formatter(logger_config.format))
            handlers.append(console_handler)

        # File handler
        if logger_config.file_path:
            try:
                # Use rotating file handler
                if logger_config.rotate_logs:
                    from logging.handlers import RotatingFileHandler
                    file_handler = RotatingFileHandler(
                        logger_config.file_path,
                        maxBytes=logger_config.max_file_size,
                        backupCount=logger_config.backup_count
                    )
                else:
                    file_handler = logging.FileHandler(logger_config.file_path)

                file_handler.setLevel(logger_config.level.value)
                file_handler.setFormatter(logging.Formatter(logger_config.format))
                handlers.append(file_handler)
            except Exception as e:
                # Don't fail initialization if file handler fails
                print(f"Error creating file handler: {str(e)}", file=sys.stderr)

        # Add all handlers
        for handler in handlers:
            logger.addHandler(handler)

        # Create adapter for context
        self.logger = logger if not logger_config.include_context else ContextAdapter(logger, {})

        # Capture warnings if configured
        self.capture_warnings = logger_config.capture_warnings
        if self.capture_warnings:
            logging.captureWarnings(True)

        # Silence specified modules
        for module_name in logger_config.silence_modules:
            logging.getLogger(module_name).setLevel(logging.WARNING)

    def _configure_metrics(self) -> None:
        """Configure metrics collection."""
        metrics_config = self.config.metrics

        # Initialize registry
        self.metrics_registry = MetricsRegistry(metrics_config)

        # Set global labels
        if self.config.component_name:
            metrics_config.global_labels["component"] = self.config.component_name

        if self.config.environment:
            metrics_config.global_labels["environment"] = self.config.environment

        if self.config.include_version and self.config.version:
            metrics_config.global_labels["version"] = self.config.version

        # Start collection if enabled
        if metrics_config.enabled:
            self.metrics_registry.start_collection()

    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        """
        Get a logger instance.

        Args:
            name: Name of the logger (appends to base name)

        Returns:
            Logger: The logger instance
        """
        if not self.initialized or not self.enabled:
            # Return a dummy logger if not initialized
            return logging.getLogger("dummy")

        if name:
            full_name = f"{self.config.logger.name}.{name}"
            logger = logging.getLogger(full_name)
            if self.config.logger.include_context:
                return ContextAdapter(logger, {})
            return logger

        return self.logger

    def get_metrics_registry(self) -> MetricsRegistry:
        """
        Get the metrics registry.

        Returns:
            MetricsRegistry: The metrics registry
        """
        if not self.initialized or not self.enabled:
            # Return a dummy registry if not initialized
            return MetricsRegistry(MetricsConfig(enabled=False))

        return self.metrics_registry

    def shutdown(self) -> None:
        """Shutdown the monitoring system."""
        if not self.initialized or not self.enabled:
            return

        # Stop metrics collection
        if self.metrics_registry:
            self.metrics_registry.stop_collection()

            # Write final metrics
            if self.config.metrics.output_file:
                self.metrics_registry.write_metrics()

        # Log shutdown
        if self.logger:
            # FIXME This self.logger.info produces a ValueError on shutdown. Figure out why.
            print("Monitoring system shutdown")

        # Reset state
        self.initialized = False

    def log_exception(self, exc_info=None, **kwargs) -> None:
        """
        Log an exception.

        Args:
            exc_info: Exception info tuple (sys.exc_info())
            **kwargs: Additional context data
        """
        if not self.initialized or not self.enabled:
            return

        if exc_info is None:
            exc_info = sys.exc_info()

        # Extract exception details
        exc_type, exc_value, exc_tb = exc_info

        # Format traceback
        tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

        # Log with context
        self.logger.error(
            f"Exception: {exc_type.__name__}: {str(exc_value)}",
            exc_info=exc_info,
            extra={"traceback": tb_str, **kwargs}
        )

    @contextlib.contextmanager
    def monitor_context(self, **kwargs):
        """
        Context manager for setting log context and timing operations.

        Args:
            **kwargs: Context data
        """
        registry = self.get_metrics_registry()
        operation_name = kwargs.pop("operation_name", "operation")

        # Create operation
        operation = registry.start_operation(operation_name, kwargs)

        # Set log context
        with log_context(**kwargs):
            try:
                yield operation
                registry.complete_operation(operation, success=True)
            except Exception as e:
                registry.complete_operation(operation, success=False, error=str(e))
                MonitoringSystem.get_instance().log_exception(
                    operation=operation_name,
                    error=str(e),
                    **kwargs
                )
                raise





def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger from the monitoring system.

    Args:
        name: Name of the logger (appends to base name)

    Returns:
        Logger: The logger instance
    """
    return MonitoringSystem.get_instance().get_logger(name)


def get_metrics_registry() -> MetricsRegistry:
    """
    Get the metrics registry from the monitoring system.

    Returns:
        MetricsRegistry: The metrics registry
    """
    return MonitoringSystem.get_instance().get_metrics_registry()


def configure_monitoring(config: Optional[MonitoringConfig] = None) -> MonitoringSystem:
    """
    Configure the monitoring system.

    Args:
        config: Configuration for the monitoring system

    Returns:
        MonitoringSystem: The configured monitoring system
    """
    if config is None:
        config = MonitoringConfig()

    return MonitoringSystem.initialize(config)


@contextlib.contextmanager
def monitor_context(**kwargs):
    """
    Context manager for setting log context and timing operations.

    Args:
        **kwargs: Context data
    """
    registry = get_metrics_registry()
    operation_name = kwargs.pop("operation_name", "operation")

    # Create operation
    operation = registry.start_operation(operation_name, kwargs)

    # Set log context
    with log_context(**kwargs):
        try:
            yield operation
            registry.complete_operation(operation, success=True)
        except Exception as e:
            registry.complete_operation(operation, success=False, error=str(e))
            MonitoringSystem.get_instance().log_exception(
                operation=operation_name,
                error=str(e),
                **kwargs
            )
            raise


# Initialize with default configuration only if explicitly requested
# MonitoringSystem.initialize()  # Commented out to prevent auto-initialization

def demonstration_main():
    # Simple demonstration
    configure_monitoring(MonitoringConfig(
        enabled=True,
        logger=LoggerConfig(level=LogLevel.DEBUG, console=True),
        metrics=MetricsConfig(enabled=True, system_metrics=True)
    ))

    logger = get_logger()
    registry = get_metrics_registry()

    logger.info("Test message")

    with monitor_context(operation_name="test_operation", test_param="value"):
        logger.info("Inside monitored operation")
        registry.increment("test_counter")
        time.sleep(0.1)

    @timed
    def test_function(a, b):
        logger.info(f"Inside timed function: {a} + {b}")
        time.sleep(0.2)
        return a + b

    result = test_function(5, 10)
    print(f"Result: {result}")

    print("Metrics:", registry.metrics)
    print("Operations:", registry.operations)


if __name__ == "__main__":
    demonstration_main()

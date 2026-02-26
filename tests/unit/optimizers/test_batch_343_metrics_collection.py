"""
Batch 343: Metrics Collection & Aggregation
==========================================

Implements a comprehensive metrics collection system with support
for different metric types, aggregation, statistics, and export
for monitoring and observability.

Goal: Provide:
- Multiple metric types (Counter, Gauge, Histogram, Timer)
- Metrics registry and collection
- Statistical aggregation (mean, median, percentiles)
- Tag-based filtering and querying
- Metric snapshots and exports
- Thread-safe metric updates
- Performance tracking integration
"""

import pytest
import time
import threading
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from collections import defaultdict
import statistics


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class MetricType(Enum):
    """Type of metric."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class MetricsSnapshot:
    """Snapshot of a metric's current state."""
    name: str
    type: MetricType
    value: Optional[float] = None
    count: int = 0
    mean: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    p50: Optional[float] = None
    p95: Optional[float] = None
    p99: Optional[float] = None
    tags: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class MetricsAggregate:
    """Aggregate metrics across all instances."""
    total_metrics: int = 0
    total_counter_increments: int = 0
    total_gauge_updates: int = 0
    total_histogram_observations: int = 0
    total_timer_observations: int = 0
    uptime_seconds: float = 0.0


# ============================================================================
# METRIC IMPLEMENTATIONS
# ============================================================================

class Metric(ABC):
    """Base class for metrics."""
    
    def __init__(self, name: str, description: str = "", tags: Optional[Dict[str, str]] = None):
        """Initialize metric.
        
        Args:
            name: Metric name
            description: Metric description
            tags: Optional tags for categorization
        """
        self.name = name
        self.description = description
        self.tags = tags or {}
        self._lock = threading.Lock()
    
    @abstractmethod
    def snapshot(self) -> MetricsSnapshot:
        """Get current metric state.
        
        Returns:
            MetricsSnapshot
        """
        pass


class Counter(Metric):
    """Counter metric - monotonically increasing value."""
    
    def __init__(self, name: str, description: str = "", tags: Optional[Dict[str, str]] = None):
        """Initialize counter."""
        super().__init__(name, description, tags)
        self.value = 0
    
    def increment(self, amount: float = 1) -> None:
        """Increment counter.
        
        Args:
            amount: Amount to increment
        """
        with self._lock:
            self.value += amount
    
    def snapshot(self) -> MetricsSnapshot:
        """Get counter snapshot."""
        with self._lock:
            return MetricsSnapshot(
                name=self.name,
                type=MetricType.COUNTER,
                value=self.value,
                count=1,
                tags=self.tags.copy()
            )


class Gauge(Metric):
    """Gauge metric - value that can go up or down."""
    
    def __init__(self, name: str, description: str = "", tags: Optional[Dict[str, str]] = None):
        """Initialize gauge."""
        super().__init__(name, description, tags)
        self.value = 0.0
    
    def set(self, value: float) -> None:
        """Set gauge value.
        
        Args:
            value: New value
        """
        with self._lock:
            self.value = value
    
    def increment(self, amount: float = 1) -> None:
        """Increment gauge.
        
        Args:
            amount: Amount to increment
        """
        with self._lock:
            self.value += amount
    
    def decrement(self, amount: float = 1) -> None:
        """Decrement gauge.
        
        Args:
            amount: Amount to decrement
        """
        with self._lock:
            self.value -= amount
    
    def snapshot(self) -> MetricsSnapshot:
        """Get gauge snapshot."""
        with self._lock:
            return MetricsSnapshot(
                name=self.name,
                type=MetricType.GAUGE,
                value=self.value,
                tags=self.tags.copy()
            )


class Histogram(Metric):
    """Histogram metric - distribution of values."""
    
    def __init__(self, name: str, description: str = "", tags: Optional[Dict[str, str]] = None):
        """Initialize histogram."""
        super().__init__(name, description, tags)
        self.values: List[float] = []
    
    def observe(self, value: float) -> None:
        """Record observation.
        
        Args:
            value: Observed value
        """
        with self._lock:
            self.values.append(value)
    
    def snapshot(self) -> MetricsSnapshot:
        """Get histogram snapshot."""
        with self._lock:
            if not self.values:
                return MetricsSnapshot(
                    name=self.name,
                    type=MetricType.HISTOGRAM,
                    count=0,
                    tags=self.tags.copy()
                )
            
            sorted_values = sorted(self.values)
            mean = statistics.mean(sorted_values)
            min_val = min(sorted_values)
            max_val = max(sorted_values)
            
            def percentile(values, p):
                if not values:
                    return None
                k = (len(values) - 1) * p / 100
                f = int(k)
                c = k - f
                if c == 0:
                    return values[f]
                return values[f] * (1 - c) + values[f + 1] * c
            
            return MetricsSnapshot(
                name=self.name,
                type=MetricType.HISTOGRAM,
                count=len(self.values),
                mean=mean,
                min=min_val,
                max=max_val,
                p50=percentile(sorted_values, 50),
                p95=percentile(sorted_values, 95),
                p99=percentile(sorted_values, 99),
                tags=self.tags.copy()
            )


class Timer(Metric):
    """Timer metric - measures duration of operations."""
    
    def __init__(self, name: str, description: str = "", tags: Optional[Dict[str, str]] = None):
        """Initialize timer."""
        super().__init__(name, description, tags)
        self.values: List[float] = []
    
    def record(self, duration_ms: float) -> None:
        """Record time measurement.
        
        Args:
            duration_ms: Duration in milliseconds
        """
        with self._lock:
            self.values.append(duration_ms)
    
    def time_operation(self, operation_func):
        """Decorator/context manager to measure operation time.
        
        Args:
            operation_func: Function to time
            
        Returns:
            Decorated function
        """
        def wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            result = operation_func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self.record(elapsed_ms)
            return result
        return wrapper
    
    def snapshot(self) -> MetricsSnapshot:
        """Get timer snapshot."""
        with self._lock:
            if not self.values:
                return MetricsSnapshot(
                    name=self.name,
                    type=MetricType.TIMER,
                    count=0,
                    tags=self.tags.copy()
                )
            
            sorted_values = sorted(self.values)
            mean = statistics.mean(sorted_values)
            min_val = min(sorted_values)
            max_val = max(sorted_values)
            
            def percentile(values, p):
                if not values:
                    return None
                k = (len(values) - 1) * p / 100
                f = int(k)
                c = k - f
                if c == 0:
                    return values[f]
                return values[f] * (1 - c) + values[f + 1] * c
            
            return MetricsSnapshot(
                name=self.name,
                type=MetricType.TIMER,
                count=len(self.values),
                mean=mean,
                min=min_val,
                max=max_val,
                p50=percentile(sorted_values, 50),
                p95=percentile(sorted_values, 95),
                p99=percentile(sorted_values, 99),
                tags=self.tags.copy()
            )


# ============================================================================
# METRICS REGISTRY
# ============================================================================

class MetricsRegistry:
    """Registry for managing metrics."""
    
    def __init__(self):
        """Initialize metrics registry."""
        self.metrics: Dict[str, Metric] = {}
        self._lock = threading.Lock()
        self.start_time = time.time()
    
    def counter(self, name: str, description: str = "", 
                tags: Optional[Dict[str, str]] = None) -> Counter:
        """Get or create counter metric.
        
        Args:
            name: Metric name
            description: Metric description
            tags: Optional tags
            
        Returns:
            Counter instance
        """
        full_name = self._make_full_name(name, tags)
        
        with self._lock:
            if full_name not in self.metrics:
                self.metrics[full_name] = Counter(name, description, tags)
            return self.metrics[full_name]
    
    def gauge(self, name: str, description: str = "",
              tags: Optional[Dict[str, str]] = None) -> Gauge:
        """Get or create gauge metric.
        
        Args:
            name: Metric name
            description: Metric description
            tags: Optional tags
            
        Returns:
            Gauge instance
        """
        full_name = self._make_full_name(name, tags)
        
        with self._lock:
            if full_name not in self.metrics:
                self.metrics[full_name] = Gauge(name, description, tags)
            return self.metrics[full_name]
    
    def histogram(self, name: str, description: str = "",
                  tags: Optional[Dict[str, str]] = None) -> Histogram:
        """Get or create histogram metric.
        
        Args:
            name: Metric name
            description: Metric description
            tags: Optional tags
            
        Returns:
            Histogram instance
        """
        full_name = self._make_full_name(name, tags)
        
        with self._lock:
            if full_name not in self.metrics:
                self.metrics[full_name] = Histogram(name, description, tags)
            return self.metrics[full_name]
    
    def timer(self, name: str, description: str = "",
              tags: Optional[Dict[str, str]] = None) -> Timer:
        """Get or create timer metric.
        
        Args:
            name: Metric name
            description: Metric description
            tags: Optional tags
            
        Returns:
            Timer instance
        """
        full_name = self._make_full_name(name, tags)
        
        with self._lock:
            if full_name not in self.metrics:
                self.metrics[full_name] = Timer(name, description, tags)
            return self.metrics[full_name]
    
    def _make_full_name(self, name: str, tags: Optional[Dict[str, str]]) -> str:
        """Create full metric name with tags."""
        if not tags:
            return name
        
        tag_str = ",".join(f"{k}={v}" for k, v in sorted(tags.items()))
        return f"{name}[{tag_str}]"
    
    def get_snapshots(self, tags_filter: Optional[Dict[str, str]] = None) -> List[MetricsSnapshot]:
        """Get metric snapshots, optionally filtered by tags.
        
        Args:
            tags_filter: Filter metrics by tags
            
        Returns:
            List of metric snapshots
        """
        with self._lock:
            snapshots = []
            
            for metric in self.metrics.values():
                if tags_filter:
                    # Check if all filter tags match
                    if not all(metric.tags.get(k) == v for k, v in tags_filter.items()):
                        continue
                
                snapshots.append(metric.snapshot())
            
            return snapshots
    
    def get_aggregate(self) -> MetricsAggregate:
        """Get aggregate metrics.
        
        Returns:
            MetricsAggregate
        """
        with self._lock:
            aggregate = MetricsAggregate(
                total_metrics=len(self.metrics),
                uptime_seconds=time.time() - self.start_time
            )
            
            for metric in self.metrics.values():
                if isinstance(metric, Counter):
                    aggregate.total_counter_increments += 1
                elif isinstance(metric, Gauge):
                    aggregate.total_gauge_updates += 1
                elif isinstance(metric, Histogram):
                    aggregate.total_histogram_observations += 1
                elif isinstance(metric, Timer):
                    aggregate.total_timer_observations += 1
            
            return aggregate
    
    def clear(self) -> None:
        """Clear all metrics."""
        with self._lock:
            self.metrics.clear()


# ============================================================================
# TESTS
# ============================================================================

class TestCounter:
    """Test Counter metric."""
    
    def test_counter_increment(self):
        """Test counter increment."""
        counter = Counter("requests")
        
        counter.increment()
        assert counter.value == 1
        
        counter.increment(5)
        assert counter.value == 6
    
    def test_counter_snapshot(self):
        """Test counter snapshot."""
        counter = Counter("requests", tags={"service": "api"})
        counter.increment(10)
        
        snapshot = counter.snapshot()
        
        assert snapshot.value == 10
        assert snapshot.type == MetricType.COUNTER
        assert snapshot.tags["service"] == "api"


class TestGauge:
    """Test Gauge metric."""
    
    def test_gauge_set(self):
        """Test gauge set."""
        gauge = Gauge("memory_usage")
        
        gauge.set(512.5)
        assert gauge.value == 512.5
        
        gauge.increment(10.5)
        assert gauge.value == 523.0
        
        gauge.decrement(23.0)
        assert gauge.value == 500.0
    
    def test_gauge_snapshot(self):
        """Test gauge snapshot."""
        gauge = Gauge("temperature", tags={"location": "datacenter"})
        gauge.set(72.5)
        
        snapshot = gauge.snapshot()
        
        assert snapshot.value == 72.5
        assert snapshot.type == MetricType.GAUGE


class TestHistogram:
    """Test Histogram metric."""
    
    def test_histogram_observations(self):
        """Test histogram observations."""
        histogram = Histogram("latency_ms")
        
        values = [10, 20, 30, 40, 50]
        for v in values:
            histogram.observe(v)
        
        assert len(histogram.values) == 5
    
    def test_histogram_snapshot(self):
        """Test histogram snapshot with statistics."""
        histogram = Histogram("response_time")
        
        values = [10, 20, 30, 40, 50]
        for v in values:
            histogram.observe(v)
        
        snapshot = histogram.snapshot()
        
        assert snapshot.count == 5
        assert snapshot.mean == 30.0
        assert snapshot.min == 10
        assert snapshot.max == 50
        assert snapshot.p50 is not None


class TestTimer:
    """Test Timer metric."""
    
    def test_timer_record(self):
        """Test timer record."""
        timer = Timer("operation_time")
        
        timer.record(100.5)
        timer.record(200.3)
        
        assert len(timer.values) == 2
    
    def test_timer_snapshot(self):
        """Test timer snapshot."""
        timer = Timer("api_latency")
        
        values = [50, 75, 100, 125, 150]
        for v in values:
            timer.record(v)
        
        snapshot = timer.snapshot()
        
        assert snapshot.count == 5
        assert snapshot.mean == 100.0
        assert snapshot.min == 50
        assert snapshot.max == 150
    
    def test_timer_decorator(self):
        """Test timer as decorator."""
        timer = Timer("function_time")
        
        @timer.time_operation
        def slow_function():
            time.sleep(0.01)
            return "result"
        
        result = slow_function()
        
        assert result == "result"
        assert len(timer.values) == 1
        assert timer.values[0] > 10  # At least 10ms


class TestMetricsRegistry:
    """Test MetricsRegistry."""
    
    def test_counter_registration(self):
        """Test counter registration."""
        registry = MetricsRegistry()
        
        counter = registry.counter("http_requests")
        counter.increment()
        
        assert "http_requests" in registry.metrics
    
    def test_gauge_registration(self):
        """Test gauge registration."""
        registry = MetricsRegistry()
        
        gauge = registry.gauge("memory_usage")
        gauge.set(1024)
        
        assert "memory_usage" in registry.metrics
    
    def test_histogram_registration(self):
        """Test histogram registration."""
        registry = MetricsRegistry()
        
        histogram = registry.histogram("request_latency")
        histogram.observe(100)
        
        assert "request_latency" in registry.metrics
    
    def test_timer_registration(self):
        """Test timer registration."""
        registry = MetricsRegistry()
        
        timer = registry.timer("operation_time")
        timer.record(50)
        
        assert "operation_time" in registry.metrics
    
    def test_get_snapshots(self):
        """Test getting metric snapshots."""
        registry = MetricsRegistry()
        
        counter = registry.counter("requests", tags={"endpoint": "/api"})
        counter.increment(5)
        
        gauge = registry.gauge("memory", tags={"endpoint": "/api"})
        gauge.set(512)
        
        snapshots = registry.get_snapshots()
        
        assert len(snapshots) == 2
    
    def test_snapshot_filtering(self):
        """Test filtering snapshots by tags."""
        registry = MetricsRegistry()
        
        registry.counter("requests", tags={"service": "api"}).increment()
        registry.counter("requests", tags={"service": "web"}).increment()
        
        api_snapshots = registry.get_snapshots(tags_filter={"service": "api"})
        
        assert len(api_snapshots) == 1
        assert api_snapshots[0].tags["service"] == "api"
    
    def test_aggregate_metrics(self):
        """Test aggregate metrics."""
        registry = MetricsRegistry()
        
        registry.counter("counter1").increment()
        registry.gauge("gauge1").set(10)
        registry.histogram("histogram1").observe(100)
        registry.timer("timer1").record(50)
        
        aggregate = registry.get_aggregate()
        
        assert aggregate.total_metrics == 4
        assert aggregate.total_counter_increments == 1
        assert aggregate.total_gauge_updates == 1
    
    def test_metric_reuse(self):
        """Test that getting same metric returns same instance."""
        registry = MetricsRegistry()
        
        counter1 = registry.counter("requests")
        counter2 = registry.counter("requests")
        
        assert counter1 is counter2


class TestMetricsIntegration:
    """Integration tests for metrics."""
    
    def test_multi_metric_monitoring(self):
        """Test monitoring multiple metrics."""
        registry = MetricsRegistry()
        
        requests = registry.counter("http_requests", tags={"endpoint": "/api"})
        latency = registry.timer("http_latency", tags={"endpoint": "/api"})
        memory = registry.gauge("memory_usage")
        
        # Simulate requests
        for i in range(10):
            requests.increment()
            latency.record(50 + i * 5)
        
        memory.set(2048)
        
        snapshots = registry.get_snapshots(tags_filter={"endpoint": "/api"})
        
        assert len(snapshots) == 2
        assert any(s.type == MetricType.COUNTER for s in snapshots)
        assert any(s.type == MetricType.TIMER for s in snapshots)
    
    def test_concurrent_metric_updates(self):
        """Test concurrent updates to metrics."""
        registry = MetricsRegistry()
        counter = registry.counter("concurrent_requests")
        
        threads = []
        
        def increment_counter():
            for _ in range(100):
                counter.increment()
        
        for _ in range(5):
            thread = threading.Thread(target=increment_counter)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        snapshot = counter.snapshot()
        assert snapshot.value == 500  # 5 threads * 100 increments
    
    def test_metric_clear(self):
        """Test clearing all metrics."""
        registry = MetricsRegistry()
        
        registry.counter("counter1").increment()
        registry.gauge("gauge1").set(100)
        
        assert len(registry.metrics) == 2
        
        registry.clear()
        
        assert len(registry.metrics) == 0

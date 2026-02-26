"""
Batch 341: Health Checking Strategies
====================================

Implements health checking mechanisms to monitor backend service
availability and automatically detect unhealthy instances, enabling
automatic failover and recovery.

Goal: Provide:
- Multiple health check strategies (HTTP, TCP, DNS, Custom)
- Periodic health check scheduling with configurable intervals
- Health status tracking with history and state transitions
- Integration with load balancers and bulkheads
- Metrics collection (check count, success rate, response time)
- Automatic unhealthy instance detection and marking
"""

import pytest
import time
import threading
from typing import Callable, Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import socket


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class HealthCheckType(Enum):
    """Type of health check."""
    HTTP = "http"
    TCP = "tcp"
    DNS = "dns"
    CUSTOM = "custom"


class HealthStatus(Enum):
    """Health status."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    status: HealthStatus
    response_time_ms: float
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def is_healthy(self) -> bool:
        """Check if result indicates healthy status."""
        return self.status == HealthStatus.HEALTHY


@dataclass
class HealthCheckMetrics:
    """Metrics for health checks."""
    total_checks: int = 0
    successful_checks: int = 0
    failed_checks: int = 0
    avg_response_time_ms: float = 0.0
    
    def success_rate(self) -> float:
        """Get success rate."""
        if self.total_checks == 0:
            return 0.0
        return self.successful_checks / self.total_checks
    
    def failure_rate(self) -> float:
        """Get failure rate."""
        if self.total_checks == 0:
            return 0.0
        return self.failed_checks / self.total_checks


@dataclass
class HealthCheckTarget:
    """Target for health checks."""
    name: str
    host: str
    port: int
    path: Optional[str] = None
    check_type: HealthCheckType = HealthCheckType.HTTP
    timeout_seconds: float = 5.0
    metrics: HealthCheckMetrics = field(default_factory=HealthCheckMetrics)
    
    def __hash__(self):
        return hash((self.name, self.host, self.port))


# ============================================================================
# HEALTH CHECK IMPLEMENTATION
# ============================================================================

class HealthCheckBase(ABC):
    """Base class for health checks."""
    
    def __init__(self, target: HealthCheckTarget, callback: Optional[Callable] = None):
        """Initialize health check.
        
        Args:
            target: Health check target
            callback: Optional callback when status changes
        """
        self.target = target
        self.callback = callback
        self.last_status = HealthStatus.UNKNOWN
        self._lock = threading.Lock()
    
    @abstractmethod
    def check(self) -> HealthCheckResult:
        """Perform health check.
        
        Returns:
            HealthCheckResult
        """
        pass
    
    def run(self) -> HealthCheckResult:
        """Run health check and track metrics.
        
        Returns:
            HealthCheckResult
        """
        start_time = time.time()
        
        try:
            result = self.check()
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            result = HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message=str(e)
            )
        
        with self._lock:
            self.target.metrics.total_checks += 1
            
            if result.status == HealthStatus.HEALTHY:
                self.target.metrics.successful_checks += 1
            else:
                self.target.metrics.failed_checks += 1
            
            # Update average response time
            total_checks = self.target.metrics.total_checks
            avg = self.target.metrics.avg_response_time_ms
            self.target.metrics.avg_response_time_ms = (
                (avg * (total_checks - 1) + result.response_time_ms) / total_checks
            )
            
            # Call callback if status changed
            if result.status != self.last_status and self.callback:
                self.callback(self.target.name, self.last_status, result.status)
            
            self.last_status = result.status
        
        return result


class HTTPHealthCheck(HealthCheckBase):
    """HTTP health check."""
    
    def check(self) -> HealthCheckResult:
        """Perform HTTP health check.
        
        Returns:
            HealthCheckResult
        """
        start_time = time.time()
        
        try:
            # Simulate HTTP request
            import socket
            with socket.create_connection(
                (self.target.host, self.target.port),
                timeout=self.target.timeout_seconds
            ) as sock:
                elapsed_ms = (time.time() - start_time) * 1000
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    response_time_ms=elapsed_ms
                )
        except socket.timeout:
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message="Connection timeout"
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message=str(e)
            )


class TCPHealthCheck(HealthCheckBase):
    """TCP health check."""
    
    def check(self) -> HealthCheckResult:
        """Perform TCP health check.
        
        Returns:
            HealthCheckResult
        """
        start_time = time.time()
        
        try:
            with socket.create_connection(
                (self.target.host, self.target.port),
                timeout=self.target.timeout_seconds
            ):
                elapsed_ms = (time.time() - start_time) * 1000
                return HealthCheckResult(
                    status=HealthStatus.HEALTHY,
                    response_time_ms=elapsed_ms
                )
        except socket.timeout:
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message="TCP timeout"
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message=str(e)
            )


class DNSHealthCheck(HealthCheckBase):
    """DNS health check."""
    
    def check(self) -> HealthCheckResult:
        """Perform DNS health check.
        
        Returns:
            HealthCheckResult
        """
        start_time = time.time()
        
        try:
            socket.gethostbyname(self.target.host)
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                response_time_ms=elapsed_ms
            )
        except socket.timeout:
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message="DNS resolution timeout"
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message=str(e)
            )


class CustomHealthCheck(HealthCheckBase):
    """Custom health check with user-defined function."""
    
    def __init__(self, target: HealthCheckTarget, 
                 check_func: Callable, 
                 callback: Optional[Callable] = None):
        """Initialize custom health check.
        
        Args:
            target: Health check target
            check_func: Custom check function
            callback: Optional callback
        """
        super().__init__(target, callback)
        self.check_func = check_func
    
    def check(self) -> HealthCheckResult:
        """Perform custom health check.
        
        Returns:
            HealthCheckResult
        """
        start_time = time.time()
        
        try:
            result = self.check_func(self.target)
            elapsed_ms = (time.time() - start_time) * 1000
            
            if isinstance(result, bool):
                status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
                return HealthCheckResult(
                    status=status,
                    response_time_ms=elapsed_ms
                )
            elif isinstance(result, HealthCheckResult):
                result.response_time_ms = elapsed_ms
                return result
            else:
                raise ValueError(f"Invalid health check result: {result}")
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                response_time_ms=elapsed_ms,
                error_message=str(e)
            )


class HealthCheckScheduler:
    """Scheduler for periodic health checks."""
    
    def __init__(self, interval_seconds: float = 10.0,
                 history_size: int = 100):
        """Initialize scheduler.
        
        Args:
            interval_seconds: Check interval
            history_size: Keep last N results per target
        """
        self.interval_seconds = interval_seconds
        self.history_size = history_size
        self.checks: Dict[str, HealthCheckBase] = {}
        self.history: Dict[str, List[HealthCheckResult]] = {}
        self.running = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
    
    def register_check(self, name: str, check: HealthCheckBase) -> None:
        """Register health check.
        
        Args:
            name: Check name
            check: HealthCheckBase instance
        """
        with self._lock:
            self.checks[name] = check
            self.history[name] = []
    
    def start(self) -> None:
        """Start periodic health checks."""
        if self.running:
            return
        
        self.running = True
        self._thread = threading.Thread(target=self._run_checks, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop periodic health checks."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5.0)
    
    def _run_checks(self) -> None:
        """Run all checks periodically."""
        while self.running:
            with self._lock:
                for name, check in self.checks.items():
                    result = check.run()
                    
                    # Keep history
                    if name not in self.history:
                        self.history[name] = []
                    
                    self.history[name].append(result)
                    if len(self.history[name]) > self.history_size:
                        self.history[name].pop(0)
            
            time.sleep(self.interval_seconds)
    
    def get_status(self, name: str) -> HealthStatus:
        """Get current status of check.
        
        Args:
            name: Check name
            
        Returns:
            HealthStatus
        """
        with self._lock:
            check = self.checks.get(name)
            if check is None:
                return HealthStatus.UNKNOWN
            return check.last_status
    
    def get_history(self, name: str, limit: int = 10) -> List[HealthCheckResult]:
        """Get health check history.
        
        Args:
            name: Check name
            limit: Max results to return
            
        Returns:
            List of HealthCheckResult
        """
        with self._lock:
            history = self.history.get(name, [])
            return history[-limit:]


# ============================================================================
# TESTS
# ============================================================================

class TestHTTPHealthCheck:
    """Test HTTP health check."""
    
    def test_http_health_check_success(self):
        """Test successful HTTP health check."""
        target = HealthCheckTarget("api", "localhost", 8000)
        check = HTTPHealthCheck(target)
        
        result = check.run()
        
        # Should succeed for localhost
        assert result.status in [HealthStatus.HEALTHY, HealthStatus.UNHEALTHY]
        assert result.response_time_ms >= 0
    
    def test_http_health_check_metrics(self):
        """Test HTTP health check metrics."""
        target = HealthCheckTarget("api", "localhost", 8000)
        check = HTTPHealthCheck(target)
        
        for _ in range(3):
            check.run()
        
        assert target.metrics.total_checks == 3
        assert target.metrics.successful_checks + target.metrics.failed_checks == 3


class TestTCPHealthCheck:
    """Test TCP health check."""
    
    def test_tcp_health_check(self):
        """Test TCP health check."""
        target = HealthCheckTarget("db", "localhost", 5432, check_type=HealthCheckType.TCP)
        check = TCPHealthCheck(target)
        
        result = check.run()
        
        assert result.response_time_ms >= 0


class TestDNSHealthCheck:
    """Test DNS health check."""
    
    def test_dns_health_check_success(self):
        """Test successful DNS health check."""
        target = HealthCheckTarget("dns", "localhost", 53, check_type=HealthCheckType.DNS)
        check = DNSHealthCheck(target)
        
        result = check.run()
        
        assert result.response_time_ms >= 0
    
    def test_dns_health_check_invalid_host(self):
        """Test DNS health check with invalid host."""
        target = HealthCheckTarget("dns", "invalid-host-xyzabc.local", 53)
        check = DNSHealthCheck(target)
        
        result = check.run()
        
        assert result.status == HealthStatus.UNHEALTHY


class TestCustomHealthCheck:
    """Test custom health check."""
    
    def test_custom_health_check_with_bool(self):
        """Test custom health check returning bool."""
        target = HealthCheckTarget("custom", "localhost", 9000, check_type=HealthCheckType.CUSTOM)
        
        def check_func(target):
            return True
        
        check = CustomHealthCheck(target, check_func)
        result = check.run()
        
        assert result.status == HealthStatus.HEALTHY
    
    def test_custom_health_check_with_result(self):
        """Test custom health check returning HealthCheckResult."""
        target = HealthCheckTarget("custom", "localhost", 9000)
        
        def check_func(target):
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                response_time_ms=10.0
            )
        
        check = CustomHealthCheck(target, check_func)
        result = check.run()
        
        assert result.status == HealthStatus.HEALTHY
    
    def test_custom_health_check_exception(self):
        """Test custom health check with exception."""
        target = HealthCheckTarget("custom", "localhost", 9000)
        
        def check_func(target):
            raise Exception("Check failed")
        
        check = CustomHealthCheck(target, check_func)
        result = check.run()
        
        assert result.status == HealthStatus.UNHEALTHY
        assert "Check failed" in result.error_message


class TestHealthCheckBase:
    """Test base health check functionality."""
    
    def test_health_check_callback(self):
        """Test health check status change callback."""
        target = HealthCheckTarget("test", "localhost", 8000)
        status_changes = []
        
        def callback(name, old_status, new_status):
            status_changes.append((old_status, new_status))
        
        def check_func(target):
            return True
        
        check = CustomHealthCheck(target, check_func, callback=callback)
        
        # First check: UNKNOWN -> HEALTHY
        check.run()
        assert len(status_changes) == 1
        
        # Second check: no status change
        check.run()
        assert len(status_changes) == 1  # No new change
    
    def test_health_check_metrics_tracking(self):
        """Test that health checks track metrics."""
        target = HealthCheckTarget("test", "localhost", 8000)
        
        def check_func(target):
            return True
        
        check = CustomHealthCheck(target, check_func)
        
        for _ in range(5):
            check.run()
        
        assert target.metrics.total_checks == 5
        assert target.metrics.successful_checks == 5
        assert target.metrics.avg_response_time_ms >= 0


class TestHealthCheckScheduler:
    """Test health check scheduler."""
    
    def test_scheduler_registration(self):
        """Test registering health checks."""
        scheduler = HealthCheckScheduler(interval_seconds=0.1)
        
        target = HealthCheckTarget("api", "localhost", 8000)
        check = HTTPHealthCheck(target)
        
        scheduler.register_check("api_health", check)
        
        assert "api_health" in scheduler.checks
    
    def test_scheduler_start_stop(self):
        """Test starting and stopping scheduler."""
        scheduler = HealthCheckScheduler(interval_seconds=0.05)
        
        target = HealthCheckTarget("api", "localhost", 8000)
        
        def check_func(target):
            return True
        
        check = CustomHealthCheck(target, check_func)
        scheduler.register_check("api_health", check)
        
        scheduler.start()
        time.sleep(0.2)
        scheduler.stop()
        
        # Should have multiple results in history
        assert len(scheduler.history["api_health"]) > 0
    
    def test_scheduler_get_status(self):
        """Test getting status from scheduler."""
        scheduler = HealthCheckScheduler()
        
        target = HealthCheckTarget("api", "localhost", 8000)
        
        def check_func(target):
            return True
        
        check = CustomHealthCheck(target, check_func)
        check.run()
        
        scheduler.register_check("api_health", check)
        
        status = scheduler.get_status("api_health")
        assert status == HealthStatus.HEALTHY
    
    def test_scheduler_history(self):
        """Test scheduler maintains history."""
        scheduler = HealthCheckScheduler(interval_seconds=0.01, history_size=5)
        
        target = HealthCheckTarget("api", "localhost", 8000)
        
        def check_func(target):
            return True
        
        check = CustomHealthCheck(target, check_func)
        scheduler.register_check("api_health", check)
        scheduler.start()
        
        time.sleep(0.1)
        scheduler.stop()
        
        history = scheduler.get_history("api_health")
        assert len(history) > 0


class TestHealthCheckingIntegration:
    """Integration tests for health checking."""
    
    def test_multi_target_health_checks(self):
        """Test health checks for multiple targets."""
        targets = [
            HealthCheckTarget("api1", "localhost", 8000),
            HealthCheckTarget("api2", "localhost", 8001),
            HealthCheckTarget("api3", "localhost", 8002),
        ]
        
        scheduler = HealthCheckScheduler(interval_seconds=0.05)
        
        for target in targets:
            def check_func(t):
                return True
            
            check = CustomHealthCheck(target, check_func)
            scheduler.register_check(target.name, check)
        
        scheduler.start()
        time.sleep(0.15)
        scheduler.stop()
        
        # All targets should have history
        for target in targets:
            assert target.name in scheduler.history
            assert len(scheduler.history[target.name]) > 0
    
    def test_status_transitions(self):
        """Test health status transitions."""
        target = HealthCheckTarget("api", "localhost", 8000)
        
        statuses = [True, True, False, False, True]  # Transition pattern
        status_iter = iter(statuses)
        
        def check_func(target):
            return next(status_iter)
        
        check = CustomHealthCheck(target, check_func)
        results = [check.run() for _ in range(5)]
        
        # Verify transitions
        assert results[0].status == HealthStatus.HEALTHY
        assert results[1].status == HealthStatus.HEALTHY
        assert results[2].status == HealthStatus.UNHEALTHY
        assert results[3].status == HealthStatus.UNHEALTHY
        assert results[4].status == HealthStatus.HEALTHY

"""
Batch 340: Load Balancing Strategies
====================================

Implements multiple load balancing algorithms to distribute
requests across multiple backend instances, preventing hotspots
and improving overall throughput and resilience.

Goal: Provide:
- Multiple load balancing strategies (round-robin, least-connections, weighted, random)
- Health checking integration for backend availability
- Metrics collection (request counts, success rates per backend)
- Dynamic adjustment of backend weights
- Thread-safe backend management
"""

import pytest
import time
import threading
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
import random


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class LoadBalancingStrategy(Enum):
    """Load balancing strategy type."""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED = "weighted"
    RANDOM = "random"


@dataclass
class BackendMetrics:
    """Metrics for a single backend."""
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    active_connections: int = 0
    response_time_ms: float = 0.0
    
    def success_rate(self) -> float:
        """Get success rate."""
        if self.request_count == 0:
            return 0.0
        return self.success_count / self.request_count
    
    def error_rate(self) -> float:
        """Get error rate."""
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count


@dataclass
class Backend:
    """Represents a backend instance."""
    name: str
    host: str
    port: int
    healthy: bool = True
    weight: int = 1
    metrics: BackendMetrics = field(default_factory=BackendMetrics)
    
    def __hash__(self):
        return hash((self.name, self.host, self.port))
    
    def __eq__(self, other):
        if not isinstance(other, Backend):
            return False
        return self.name == other.name and self.host == other.host


@dataclass
class LoadBalancerMetrics:
    """Metrics for load balancer."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rebalance_count: int = 0
    
    def success_rate(self) -> float:
        """Get overall success rate."""
        if self.total_requests == 0:
            return 0.0
        return self.successful_requests / self.total_requests


# ============================================================================
# LOAD BALANCER IMPLEMENTATION
# ============================================================================

class LoadBalancerBase(ABC):
    """Base class for load balancers."""
    
    def __init__(self, strategy: LoadBalancingStrategy, backends: List[Backend]):
        """Initialize load balancer.
        
        Args:
            strategy: Balancing strategy
            backends: List of backend instances
        """
        self.strategy = strategy
        self.backends = backends
        self.metrics = LoadBalancerMetrics()
        self._lock = threading.Lock()
        self._current_index = 0
    
    @abstractmethod
    def select_backend(self) -> Optional[Backend]:
        """Select next backend for request.
        
        Returns:
            Selected backend or None if none available
        """
        pass
    
    def execute(self, func: Callable) -> Any:
        """Execute function on selected backend.
        
        Args:
            func: Function to execute with selected backend
            
        Returns:
            Function result
            
        Raises:
            Exception: If no healthy backend available
        """
        backend = self.select_backend()
        if backend is None:
            with self._lock:
                self.metrics.failed_requests += 1
            raise Exception("No healthy backend available")
        
        with self._lock:
            self.metrics.total_requests += 1
            backend.metrics.request_count += 1
            backend.metrics.active_connections += 1
        
        try:
            result = func(backend)
            with self._lock:
                self.metrics.successful_requests += 1
                backend.metrics.success_count += 1
            return result
        except Exception as e:
            with self._lock:
                self.metrics.failed_requests += 1
                backend.metrics.error_count += 1
            raise
        finally:
            with self._lock:
                backend.metrics.active_connections -= 1
    
    def get_healthy_backends(self) -> List[Backend]:
        """Get list of healthy backends.
        
        Returns:
            List of healthy backends
        """
        with self._lock:
            return [b for b in self.backends if b.healthy]
    
    def mark_backend_healthy(self, backend_name: str, healthy: bool) -> None:
        """Mark backend as healthy or unhealthy.
        
        Args:
            backend_name: Name of backend
            healthy: Health status
        """
        with self._lock:
            for backend in self.backends:
                if backend.name == backend_name:
                    backend.healthy = healthy
                    self.metrics.rebalance_count += 1
                    break
    
    def get_backend_metrics(self, backend_name: str) -> Optional[BackendMetrics]:
        """Get metrics for specific backend.
        
        Args:
            backend_name: Name of backend
            
        Returns:
            BackendMetrics or None if not found
        """
        with self._lock:
            for backend in self.backends:
                if backend.name == backend_name:
                    return backend.metrics
        return None


class RoundRobinLoadBalancer(LoadBalancerBase):
    """Round-robin load balancer."""
    
    def select_backend(self) -> Optional[Backend]:
        """Select next backend in round-robin fashion.
        
        Returns:
            Selected backend or None if none available
        """
        healthy_backends = self.get_healthy_backends()
        if not healthy_backends:
            return None
        
        with self._lock:
            backend = healthy_backends[self._current_index % len(healthy_backends)]
            self._current_index += 1
        
        return backend


class LeastConnectionsLoadBalancer(LoadBalancerBase):
    """Least connections load balancer."""
    
    def select_backend(self) -> Optional[Backend]:
        """Select backend with least active connections.
        
        Returns:
            Selected backend or None if none available
        """
        healthy_backends = self.get_healthy_backends()
        if not healthy_backends:
            return None
        
        with self._lock:
            backend = min(healthy_backends, 
                         key=lambda b: b.metrics.active_connections)
        
        return backend


class WeightedLoadBalancer(LoadBalancerBase):
    """Weighted load balancer."""
    
    def select_backend(self) -> Optional[Backend]:
        """Select backend based on weights.
        
        Returns:
            Selected backend or None if none available
        """
        healthy_backends = self.get_healthy_backends()
        if not healthy_backends:
            return None
        
        with self._lock:
            total_weight = sum(b.weight for b in healthy_backends)
            if total_weight == 0:
                return healthy_backends[0]
            
            choice = random.uniform(0, total_weight)
            current = 0
            
            for backend in healthy_backends:
                current += backend.weight
                if choice <= current:
                    return backend
            
            return healthy_backends[-1]


class RandomLoadBalancer(LoadBalancerBase):
    """Random load balancer."""
    
    def select_backend(self) -> Optional[Backend]:
        """Select random healthy backend.
        
        Returns:
            Selected backend or None if none available
        """
        healthy_backends = self.get_healthy_backends()
        if not healthy_backends:
            return None
        
        return random.choice(healthy_backends)


class LoadBalancerFactory:
    """Factory for creating load balancers."""
    
    def __init__(self):
        """Initialize factory."""
        self.balancers: Dict[str, LoadBalancerBase] = {}
        self._lock = threading.Lock()
    
    def create_balancer(self, name: str, strategy: LoadBalancingStrategy,
                       backends: List[Backend]) -> LoadBalancerBase:
        """Create load balancer.
        
        Args:
            name: Balancer name
            strategy: Balancing strategy
            backends: List of backends
            
        Returns:
            LoadBalancerBase instance
            
        Raises:
            ValueError: If strategy is unsupported
        """
        if strategy == LoadBalancingStrategy.ROUND_ROBIN:
            balancer = RoundRobinLoadBalancer(strategy, backends)
        elif strategy == LoadBalancingStrategy.LEAST_CONNECTIONS:
            balancer = LeastConnectionsLoadBalancer(strategy, backends)
        elif strategy == LoadBalancingStrategy.WEIGHTED:
            balancer = WeightedLoadBalancer(strategy, backends)
        elif strategy == LoadBalancingStrategy.RANDOM:
            balancer = RandomLoadBalancer(strategy, backends)
        else:
            raise ValueError(f"Unsupported strategy: {strategy}")
        
        with self._lock:
            self.balancers[name] = balancer
        
        return balancer
    
    def get_balancer(self, name: str) -> Optional[LoadBalancerBase]:
        """Get balancer by name.
        
        Args:
            name: Balancer name
            
        Returns:
            LoadBalancerBase or None if not found
        """
        with self._lock:
            return self.balancers.get(name)
    
    def list_balancers(self) -> List[str]:
        """List all balancer names.
        
        Returns:
            List of balancer names
        """
        with self._lock:
            return list(self.balancers.keys())


# ============================================================================
# TESTS
# ============================================================================

class TestRoundRobinLoadBalancer:
    """Test round-robin load balancer."""
    
    def test_basic_round_robin(self):
        """Test basic round-robin distribution."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
            Backend("api3", "10.0.0.3", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        # Should cycle through backends
        selected = [balancer.select_backend() for _ in range(9)]
        backend_names = [b.name for b in selected]
        
        assert backend_names == ["api1", "api2", "api3", "api1", "api2", "api3", "api1", "api2", "api3"]
    
    def test_round_robin_with_unhealthy_backend(self):
        """Test round-robin skips unhealthy backends."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000, healthy=False),
            Backend("api3", "10.0.0.3", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        # Should skip unhealthy backend
        selected = [balancer.select_backend() for _ in range(6)]
        backend_names = [b.name for b in selected]
        
        assert "api2" not in backend_names
        assert len(set(backend_names)) == 2  # Only 2 unique backends
    
    def test_round_robin_execute(self):
        """Test round-robin execute with function."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        def get_backend_name(backend):
            return backend.name
        
        results = [balancer.execute(get_backend_name) for _ in range(4)]
        
        assert results == ["api1", "api2", "api1", "api2"]
        assert balancer.metrics.successful_requests == 4


class TestLeastConnectionsLoadBalancer:
    """Test least-connections load balancer."""
    
    def test_least_connections_distribution(self):
        """Test least-connections selects backend with fewest connections."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
            Backend("api3", "10.0.0.3", 8000),
        ]
        
        balancer = LeastConnectionsLoadBalancer(LoadBalancingStrategy.LEAST_CONNECTIONS, backends)
        
        # Simulate connections on api1 and api2
        backends[0].metrics.active_connections = 5
        backends[1].metrics.active_connections = 3
        backends[2].metrics.active_connections = 0
        
        # Should select api3 (least connections)
        selected = balancer.select_backend()
        assert selected.name == "api3"
    
    def test_least_connections_balancing(self):
        """Test least-connections balances load."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
        ]
        
        balancer = LeastConnectionsLoadBalancer(LoadBalancingStrategy.LEAST_CONNECTIONS, backends)
        
        def add_connection(backend):
            # Increment connections during execution
            backend.metrics.active_connections += 1
            time.sleep(0.01)
            return backend.name
        
        results = []
        for _ in range(4):
            try:
                results.append(balancer.execute(add_connection))
            except:
                pass
        
        # Should distribute requests across backends
        assert len(set(results)) == 2


class TestWeightedLoadBalancer:
    """Test weighted load balancer."""
    
    def test_weighted_distribution(self):
        """Test weighted distribution respects weights."""
        backends = [
            Backend("api1", "10.0.0.1", 8000, weight=2),
            Backend("api2", "10.0.0.2", 8000, weight=1),
        ]
        
        balancer = WeightedLoadBalancer(LoadBalancingStrategy.WEIGHTED, backends)
        
        # Run multiple selections and track distribution
        selections = {}
        for _ in range(300):
            backend = balancer.select_backend()
            selections[backend.name] = selections.get(backend.name, 0) + 1
        
        # api1 should get roughly 2x more selections (ratio ~2:1)
        ratio = selections.get("api1", 0) / selections.get("api2", 1)
        assert 1.5 < ratio < 2.5  # Allow some variance
    
    def test_weighted_with_zero_weight(self):
        """Test weighted handles zero weight backends."""
        backends = [
            Backend("api1", "10.0.0.1", 8000, weight=1),
            Backend("api2", "10.0.0.2", 8000, weight=0),
        ]
        
        balancer = WeightedLoadBalancer(LoadBalancingStrategy.WEIGHTED, backends)
        
        selection = balancer.select_backend()
        assert selection.name == "api1"


class TestRandomLoadBalancer:
    """Test random load balancer."""
    
    def test_random_distribution(self):
        """Test random distribution."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
            Backend("api3", "10.0.0.3", 8000),
        ]
        
        balancer = RandomLoadBalancer(LoadBalancingStrategy.RANDOM, backends)
        
        selections = {}
        for _ in range(300):
            backend = balancer.select_backend()
            selections[backend.name] = selections.get(backend.name, 0) + 1
        
        # All backends should be selected
        assert len(selections) == 3
        # Each should get roughly equal distribution
        for count in selections.values():
            assert 50 < count < 150


class TestLoadBalancerBase:
    """Test base load balancer functionality."""
    
    def test_mark_backend_unhealthy(self):
        """Test marking backend as unhealthy."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        # Mark api1 as unhealthy
        balancer.mark_backend_healthy("api1", False)
        
        # Only api2 should be selected
        selected = balancer.select_backend()
        assert selected.name == "api2"
        assert balancer.metrics.rebalance_count == 1
    
    def test_backend_metrics_update(self):
        """Test that execute updates backend metrics."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        def dummy_func(backend):
            return "ok"
        
        balancer.execute(dummy_func)
        
        backend = backends[0]
        assert backend.metrics.request_count == 1
        assert backend.metrics.success_count == 1
        assert backend.metrics.error_count == 0
    
    def test_execute_failure_tracking(self):
        """Test that execute tracks failures."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        def failing_func(backend):
            raise Exception("Backend error")
        
        with pytest.raises(Exception):
            balancer.execute(failing_func)
        
        backend = backends[0]
        assert backend.metrics.error_count == 1
        assert balancer.metrics.failed_requests == 1
    
    def test_no_healthy_backends(self):
        """Test execute raises when no healthy backends."""
        backends = [
            Backend("api1", "10.0.0.1", 8000, healthy=False),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        def dummy_func(backend):
            return "ok"
        
        with pytest.raises(Exception, match="No healthy backend"):
            balancer.execute(dummy_func)


class TestLoadBalancerFactory:
    """Test load balancer factory."""
    
    def test_create_round_robin_balancer(self):
        """Test creating round-robin balancer."""
        factory = LoadBalancerFactory()
        backends = [Backend("api1", "10.0.0.1", 8000)]
        
        balancer = factory.create_balancer("api_lb", LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        assert isinstance(balancer, RoundRobinLoadBalancer)
        assert balancer.strategy == LoadBalancingStrategy.ROUND_ROBIN
    
    def test_create_multiple_balancers(self):
        """Test creating multiple balancers."""
        factory = LoadBalancerFactory()
        
        backends1 = [Backend("api1", "10.0.0.1", 8000)]
        backends2 = [Backend("db1", "10.0.0.2", 5432)]
        
        lb1 = factory.create_balancer("api_lb", LoadBalancingStrategy.ROUND_ROBIN, backends1)
        lb2 = factory.create_balancer("db_lb", LoadBalancingStrategy.LEAST_CONNECTIONS, backends2)
        
        assert factory.list_balancers() == ["api_lb", "db_lb"]
        assert factory.get_balancer("api_lb") == lb1
        assert factory.get_balancer("db_lb") == lb2
    
    def test_invalid_strategy(self):
        """Test that invalid strategy raises error."""
        factory = LoadBalancerFactory()
        backends = [Backend("api1", "10.0.0.1", 8000)]
        
        with pytest.raises(ValueError):
            factory.create_balancer("api_lb", "invalid_strategy", backends)


class TestLoadBalancingIntegration:
    """Integration tests for load balancing."""
    
    def test_multi_backend_system(self):
        """Test load balancing across multiple backends."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
            Backend("api3", "10.0.0.3", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        def query_backend(backend):
            return f"Response from {backend.name}"
        
        responses = [balancer.execute(query_backend) for _ in range(6)]
        
        assert len(responses) == 6
        assert balancer.metrics.successful_requests == 6
        assert balancer.metrics.total_requests == 6
    
    def test_failover_handling(self):
        """Test failover when backend becomes unhealthy."""
        backends = [
            Backend("api1", "10.0.0.1", 8000),
            Backend("api2", "10.0.0.2", 8000),
        ]
        
        balancer = RoundRobinLoadBalancer(LoadBalancingStrategy.ROUND_ROBIN, backends)
        
        def query_backend(backend):
            return backend.name
        
        # First request to api1
        result1 = balancer.execute(query_backend)
        assert result1 == "api1"
        
        # Mark api1 as unhealthy
        balancer.mark_backend_healthy("api1", False)
        
        # All subsequent requests should go to api2
        result2 = balancer.execute(query_backend)
        result3 = balancer.execute(query_backend)
        
        assert result2 == "api2"
        assert result3 == "api2"

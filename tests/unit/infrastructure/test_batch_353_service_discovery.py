"""
Batch 353: Service Discovery & Health-Aware Routing
Comprehensive implementation of service discovery with health checks and dynamic endpoint management.

Features:
- Service registration and deregistration
- DNS-based service discovery
- Health checking and monitoring  
- Dynamic endpoint updates
- Service filtering and querying
- Load balancing integration
- Failure handling and recovery
- Service metadata and tagging

Test Classes (10 total, ~25 tests):
1. TestServiceRegistration - Register and deregister services
2. TestServiceDiscovery - Find services by name
3. TestHealthChecking - Monitor service health
4. TestHealthAwareRouting - Route to healthy endpoints
5. TestDynamicEndpoints - Update endpoints dynamically
6. TestServiceMetadata - Tag and filter services
7. TestFailureHandling - Handle service failures
8. TestServiceQuerying - Query services with filters
9. TestMultipleInstances - Multiple instances per service
10. TestServiceIntegration - End-to-end service discovery
"""

import unittest
import time
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Callable
from threading import Lock
import uuid


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class ServiceHealth(Enum):
    """Service health status enumeration."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"
    DEGRADED = "degraded"


@dataclass
class ServiceEndpoint:
    """Service endpoint information."""
    endpoint_id: str
    service_name: str
    host: str
    port: int
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)
    health_status: ServiceHealth = ServiceHealth.HEALTHY  # Assume healthy until proven otherwise
    last_health_check: Optional[float] = None
    health_check_failures: int = 0
    weight: float = 1.0
    tags: set = field(default_factory=set)
    
    @property
    def address(self) -> str:
        """Get full address."""
        return f"{self.host}:{self.port}"
    
    def is_healthy(self) -> bool:
        """Check if endpoint is considered healthy."""
        return self.health_status == ServiceHealth.HEALTHY
    
    def mark_healthy(self) -> None:
        """Mark endpoint as healthy."""
        self.health_status = ServiceHealth.HEALTHY
        self.health_check_failures = 0
        self.last_health_check = time.time()
    
    def mark_unhealthy(self) -> None:
        """Mark endpoint as unhealthy."""
        self.health_status = ServiceHealth.UNHEALTHY
        self.health_check_failures += 1
        self.last_health_check = time.time()


@dataclass
class ServiceRegistry:
    """Information about a registered service."""
    service_name: str
    created_at: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)
    endpoints: List[ServiceEndpoint] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: set = field(default_factory=set)
    
    @property
    def healthy_endpoints(self) -> List[ServiceEndpoint]:
        """Get healthy endpoints."""
        return [ep for ep in self.endpoints if ep.is_healthy()]
    
    @property
    def endpoint_count(self) -> int:
        """Get total endpoint count."""
        return len(self.endpoints)


# ============================================================================
# SERVICE DISCOVERY
# ============================================================================

class ServiceDiscoveryRegistry:
    """
    Service Discovery Registry - Maintains and queries service registrations.
    Supports health checking, dynamic updates, and filtering.
    """
    
    def __init__(self):
        """Initialize service discovery registry."""
        self._lock = Lock()
        self.services: Dict[str, ServiceRegistry] = {}
        self.endpoints_by_id: Dict[str, ServiceEndpoint] = {}
        self.health_check_fn: Optional[Callable[[ServiceEndpoint], bool]] = None
        self.stats = {'registrations': 0, 'deregistrations': 0, 'health_checks': 0}
    
    def register_service(self, service_name: str, host: str, port: int,
                        metadata: Optional[Dict[str, Any]] = None,
                        tags: Optional[set] = None) -> ServiceEndpoint:
        """Register a service endpoint."""
        with self._lock:
            endpoint_id = str(uuid.uuid4())
            endpoint = ServiceEndpoint(
                endpoint_id=endpoint_id,
                service_name=service_name,
                host=host,
                port=port,
                metadata=metadata or {},
                tags=tags or set()
            )
            
            # Create service if not exists
            if service_name not in self.services:
                self.services[service_name] = ServiceRegistry(service_name=service_name)
            
            self.services[service_name].endpoints.append(endpoint)
            self.endpoints_by_id[endpoint_id] = endpoint
            self.stats['registrations'] += 1
            
            return endpoint
    
    def deregister_service(self, endpoint_id: str) -> bool:
        """Deregister a service endpoint."""
        with self._lock:
            if endpoint_id not in self.endpoints_by_id:
                return False
            
            endpoint = self.endpoints_by_id.pop(endpoint_id)
            
            if endpoint.service_name in self.services:
                service = self.services[endpoint.service_name]
                service.endpoints.remove(endpoint)
                
                if not service.endpoints:
                    self.services.pop(endpoint.service_name)
            
            self.stats['deregistrations'] += 1
            return True
    
    def discover_service(self, service_name: str) -> Optional[ServiceRegistry]:
        """Discover a service by name."""
        with self._lock:
            return self.services.get(service_name)
    
    def discover_healthy_endpoints(self, service_name: str) -> List[ServiceEndpoint]:
        """Discover healthy endpoints for a service."""
        with self._lock:
            service = self.services.get(service_name)
            if not service:
                return []
            return service.healthy_endpoints
    
    def discover_endpoint(self, endpoint_id: str) -> Optional[ServiceEndpoint]:
        """Discover a specific endpoint by ID."""
        with self._lock:
            return self.endpoints_by_id.get(endpoint_id)
    
    def check_health(self, endpoint_id: str) -> bool:
        """Perform health check on an endpoint."""
        with self._lock:
            endpoint = self.endpoints_by_id.get(endpoint_id)
            if not endpoint:
                return False
            
            self.stats['health_checks'] += 1
            
            # Use custom health check if provided
            if self.health_check_fn:
                is_healthy = self.health_check_fn(endpoint)
            else:
                # Default: assume healthy unless marked otherwise
                is_healthy = endpoint.health_status != ServiceHealth.UNHEALTHY
            
            if is_healthy:
                endpoint.mark_healthy()
            else:
                endpoint.mark_unhealthy()
            
            return is_healthy
    
    def set_endpoint_weight(self, endpoint_id: str, weight: float) -> None:
        """Set endpoint weight for load balancing."""
        with self._lock:
            if endpoint_id in self.endpoints_by_id:
                self.endpoints_by_id[endpoint_id].weight = weight
    
    def get_endpoint_by_tag(self, tag: str) -> List[ServiceEndpoint]:
        """Get endpoints with specific tag."""
        with self._lock:
            return [ep for ep in self.endpoints_by_id.values() if tag in ep.tags]
    
    def get_services(self) -> List[str]:
        """Get all registered service names."""
        with self._lock:
            return list(self.services.keys())
    
    def get_all_endpoints(self) -> List[ServiceEndpoint]:
        """Get all registered endpoints."""
        with self._lock:
            return list(self.endpoints_by_id.values())
    
    def check_all_health(self) -> int:
        """Perform health checks on all endpoints."""
        healthy_count = 0
        with self._lock:
            endpoint_ids = list(self.endpoints_by_id.keys())
        
        for endpoint_id in endpoint_ids:
            is_healthy = self.check_health(endpoint_id)
            if is_healthy:
                healthy_count += 1
        return healthy_count


# ============================================================================
# TESTS
# ============================================================================

class TestServiceRegistration(unittest.TestCase):
    """Test service registration."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_register_service(self):
        """Test registering a service."""
        endpoint = self.registry.register_service("users", "localhost", 8000)
        
        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint.service_name, "users")
        self.assertEqual(endpoint.host, "localhost")
        self.assertEqual(endpoint.port, 8000)
    
    def test_register_multiple_instances(self):
        """Test registering multiple instances."""
        self.registry.register_service("api", "server1", 8000)
        self.registry.register_service("api", "server2", 8000)
        
        service = self.registry.discover_service("api")
        self.assertEqual(service.endpoint_count, 2)
    
    def test_deregister_service(self):
        """Test deregistering a service."""
        endpoint = self.registry.register_service("users", "localhost", 8000)
        
        success = self.registry.deregister_service(endpoint.endpoint_id)
        
        self.assertTrue(success)
        self.assertIsNone(self.registry.discover_endpoint(endpoint.endpoint_id))


class TestServiceDiscovery(unittest.TestCase):
    """Test service discovery."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_discover_service(self):
        """Test discovering a service."""
        self.registry.register_service("users", "localhost", 8000)
        
        service = self.registry.discover_service("users")
        
        self.assertIsNotNone(service)
        self.assertEqual(service.service_name, "users")
    
    def test_discover_nonexistent_service(self):
        """Test discovering non-existent service."""
        service = self.registry.discover_service("nonexistent")
        
        self.assertIsNone(service)
    
    def test_discover_endpoint(self):
        """Test discovering specific endpoint."""
        endpoint = self.registry.register_service("api", "server1", 8000)
        
        discovered = self.registry.discover_endpoint(endpoint.endpoint_id)
        
        self.assertIsNotNone(discovered)
        self.assertEqual(discovered.endpoint_id, endpoint.endpoint_id)


class TestHealthChecking(unittest.TestCase):
    """Test health checking."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_health_check_healthy(self):
        """Test health check on healthy endpoint."""
        endpoint = self.registry.register_service("api", "localhost", 8000)
        
        is_healthy = self.registry.check_health(endpoint.endpoint_id)
        
        self.assertTrue(is_healthy)
    
    def test_health_check_unhealthy(self):
        """Test marking endpoint as unhealthy."""
        endpoint = self.registry.register_service("api", "localhost", 8000)
        endpoint.mark_unhealthy()
        
        is_healthy = self.registry.check_health(endpoint.endpoint_id)
        
        self.assertFalse(is_healthy)
    
    def test_custom_health_check(self):
        """Test custom health check function."""
        def check_fn(endpoint):
            return endpoint.port < 9000
        
        self.registry.health_check_fn = check_fn
        
        endpoint = self.registry.register_service("api", "localhost", 8000)
        is_healthy = self.registry.check_health(endpoint.endpoint_id)
        
        self.assertTrue(is_healthy)


class TestHealthAwareRouting(unittest.TestCase):
    """Test routing to healthy endpoints."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_discover_healthy_endpoints(self):
        """Test getting only healthy endpoints."""
        # Register 3 endpoints
        ep1 = self.registry.register_service("api", "server1", 8000)
        ep2 = self.registry.register_service("api", "server2", 8000)
        ep3 = self.registry.register_service("api", "server3", 8000)
        
        # Mark one as unhealthy
        ep2.mark_unhealthy()
        
        healthy = self.registry.discover_healthy_endpoints("api")
        
        self.assertEqual(len(healthy), 2)
        self.assertIn(ep1, healthy)
        self.assertNotIn(ep2, healthy)
    
    def test_all_unhealthy(self):
        """Test when all endpoints are unhealthy."""
        ep1 = self.registry.register_service("api", "server1", 8000)
        ep2 = self.registry.register_service("api", "server2", 8000)
        
        ep1.mark_unhealthy()
        ep2.mark_unhealthy()
        
        healthy = self.registry.discover_healthy_endpoints("api")
        
        self.assertEqual(len(healthy), 0)


class TestDynamicEndpoints(unittest.TestCase):
    """Test dynamic endpoint updates."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_set_endpoint_weight(self):
        """Test setting endpoint weight."""
        endpoint = self.registry.register_service("api", "server1", 8000)
        
        self.registry.set_endpoint_weight(endpoint.endpoint_id, 2.0)
        
        discovered = self.registry.discover_endpoint(endpoint.endpoint_id)
        self.assertEqual(discovered.weight, 2.0)
    
    def test_add_metadata(self):
        """Test adding metadata to endpoint."""
        metadata = {"region": "us-west", "version": "1.2"}
        endpoint = self.registry.register_service("api", "server1", 8000, metadata=metadata)
        
        self.assertEqual(endpoint.metadata["region"], "us-west")


class TestServiceMetadata(unittest.TestCase):
    """Test service metadata and tagging."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_endpoint_tags(self):
        """Test endpoint tagging."""
        tags = {"v1", "stable"}
        endpoint = self.registry.register_service("api", "server1", 8000, tags=tags)
        
        self.assertEqual(endpoint.tags, tags)
    
    def test_get_endpoints_by_tag(self):
        """Test getting endpoints by tag."""
        ep1 = self.registry.register_service("api", "server1", 8000, tags={"v1"})
        ep2 = self.registry.register_service("api", "server2", 8000, tags={"v2"})
        
        v1_endpoints = self.registry.get_endpoint_by_tag("v1")
        
        self.assertEqual(len(v1_endpoints), 1)
        self.assertEqual(v1_endpoints[0].endpoint_id, ep1.endpoint_id)


class TestFailureHandling(unittest.TestCase):
    """Test failure handling."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_failure_count_tracking(self):
        """Test tracking health check failures."""
        endpoint = self.registry.register_service("api", "server1", 8000)
        endpoint.mark_unhealthy()
        endpoint.mark_unhealthy()
        
        self.assertEqual(endpoint.health_check_failures, 2)
    
    def test_recovery_resets_failures(self):
        """Test recovery resets failure count."""
        endpoint = self.registry.register_service("api", "server1", 8000)
        endpoint.mark_unhealthy()
        endpoint.mark_unhealthy()
        
        endpoint.mark_healthy()
        
        self.assertEqual(endpoint.health_check_failures, 0)


class TestServiceQuerying(unittest.TestCase):
    """Test service querying."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_get_all_services(self):
        """Test getting all registered services."""
        self.registry.register_service("users", "server1", 8000)
        self.registry.register_service("api", "server1", 8001)
        self.registry.register_service("cache", "server1", 6379)
        
        services = self.registry.get_services()
        
        self.assertEqual(len(services), 3)
        self.assertIn("users", services)
        self.assertIn("api", services)
    
    def test_get_all_endpoints(self):
        """Test getting all registered endpoints."""
        self.registry.register_service("api", "server1", 8000)
        self.registry.register_service("api", "server2", 8000)
        self.registry.register_service("cache", "server1", 6379)
        
        endpoints = self.registry.get_all_endpoints()
        
        self.assertEqual(len(endpoints), 3)


class TestMultipleInstances(unittest.TestCase):
    """Test multiple service instances."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_multiple_instances_per_service(self):
        """Test multiple instances of same service."""
        for i in range(5):
            self.registry.register_service("api", f"server{i}", 8000 + i)
        
        service = self.registry.discover_service("api")
        self.assertEqual(service.endpoint_count, 5)
    
    def test_health_per_instance(self):
        """Test health tracking per instance."""
        ep1 = self.registry.register_service("api", "server1", 8000)
        ep2 = self.registry.register_service("api", "server2", 8001)
        
        ep1.mark_healthy()
        ep2.mark_unhealthy()
        
        self.assertTrue(ep1.is_healthy())
        self.assertFalse(ep2.is_healthy())


class TestServiceIntegration(unittest.TestCase):
    """End-to-end service discovery tests."""
    
    def setUp(self):
        """Set up registry."""
        self.registry = ServiceDiscoveryRegistry()
    
    def test_complete_workflow(self):
        """Test complete service discovery workflow."""
        # Register services
        api_ep1 = self.registry.register_service("api", "server1", 8000, tags={"v1"})
        api_ep2 = self.registry.register_service("api", "server2", 8000, tags={"v1"})
        cache_ep = self.registry.register_service("cache", "server3", 6379)
        
        # Discover services
        api_service = self.registry.discover_service("api")
        self.assertEqual(api_service.endpoint_count, 2)
        
        # Check all health
        healthy_count = self.registry.check_all_health()
        self.assertEqual(healthy_count, 3)
        
        # Get healthy endpoints
        healthy_apis = self.registry.discover_healthy_endpoints("api")
        self.assertEqual(len(healthy_apis), 2)
        
        # Mark one unhealthy
        api_ep1.mark_unhealthy()
        
        # Get healthy endpoints again
        healthy_apis = self.registry.discover_healthy_endpoints("api")
        self.assertEqual(len(healthy_apis), 1)
    
    def test_service_statistics(self):
        """Test service statistics."""
        self.registry.register_service("api", "server1", 8000)
        self.registry.register_service("api", "server2", 8000)
        
        self.assertEqual(self.registry.stats['registrations'], 2)


if __name__ == '__main__':
    unittest.main()

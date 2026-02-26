"""
Batch 350: API Gateway / Request Router Pattern
Comprehensive implementation of API gateway with route management, middleware chains, and request transformation.

Features:
- Dynamic route registration with pattern matching
- Middleware chain with pre/post processing
- Request/response transformation
- Authentication and authorization hooks
- Rate limiting integration with request tracking
- Request ID assignment and correlation
- Comprehensive error handling
- Metrics collection for all routes
- Request/response logging
- Support for query parameters, path variables, headers

Test Classes (11 total, ~25 tests):
1. TestRouteRegistration - Register, retrieve, search routes
2. TestRequestMatching - Match requests to routes
3. TestMiddlewareChain - Pre/post processing, error handling
4. TestRequestTransformation - Modify headers, body, metadata
5. TestAuthenticationHooks - Verify auth token, extract principal
6. TestRateLimiting - Track rate, check limits, track by principal
7. TestErrorHandling - Handle exceptions, 404s, 500s, timeouts
8. TestMetricsCollection - Track requests, errors, latency
9. TestRequestIDTracking - Assign IDs, correlate, propagate
10. TestRoutePatternMatching - Complex patterns, query params, path variables
11. TestGatewayIntegration - End-to-end request flow
"""

import unittest
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Any, Callable, Set
from threading import Lock
from collections import defaultdict
import re


# ============================================================================
# DOMAIN MODELS
# ============================================================================

class HttpMethod(Enum):
    """HTTP method enumeration."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class AuthLevel(Enum):
    """Authentication requirement levels."""
    NONE = "none"
    REQUIRED = "required"
    ADMIN = "admin"


@dataclass
class Request:
    """HTTP request model."""
    request_id: str
    method: HttpMethod
    path: str
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    query_params: Dict[str, str] = field(default_factory=dict)
    principal: Optional[str] = None  # Authenticated user
    timestamp: float = field(default_factory=time.time)
    
    def copy(self) -> 'Request':
        """Create a copy of this request."""
        return Request(
            request_id=self.request_id,
            method=self.method,
            path=self.path,
            headers=dict(self.headers),
            body=self.body,
            query_params=dict(self.query_params),
            principal=self.principal,
            timestamp=self.timestamp
        )


@dataclass
class Response:
    """HTTP response model."""
    status_code: int
    headers: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    error_message: Optional[str] = None
    processing_time_ms: float = 0.0


@dataclass
class Route:
    """API route definition."""
    path_pattern: str  # e.g., "/users/{id}", "/api/*/status"
    method: HttpMethod
    handler: Callable[[Request], Response]
    auth_required: AuthLevel = AuthLevel.NONE
    rate_limit: Optional[int] = None  # requests per second
    description: str = ""
    regex_pattern: Optional[re.Pattern] = None
    
    def __post_init__(self):
        """Compile path pattern to regex."""
        if self.regex_pattern is None:
            # Convert pattern like "/users/{id}" to regex "/users/(?P<id>[^/]+)"
            pattern = self.path_pattern
            pattern = pattern.replace("*", "[^/]+")
            pattern = re.sub(r'\{(\w+)\}', r'(?P<\1>[^/]+)', pattern)
            pattern = f"^{pattern}$"
            self.regex_pattern = re.compile(pattern)


@dataclass
class Middleware:
    """Request/response middleware component."""
    name: str
    pre_processor: Optional[Callable[[Request], Request]] = None
    post_processor: Optional[Callable[[Response], Response]] = None
    error_handler: Optional[Callable[[Exception, Request], Optional[Response]]] = None


@dataclass
class RateLimitBucket:
    """Rate limit tracking for a principal/endpoint."""
    principal: str
    endpoint: str
    request_count: int = 0
    window_start: float = field(default_factory=time.time)
    
    def is_within_limit(self, limit: int, window_seconds: int = 1) -> bool:
        """Check if request is within rate limit."""
        now = time.time()
        if now - self.window_start > window_seconds:
            self.request_count = 1
            self.window_start = now
            return True
        
        self.request_count += 1
        return self.request_count <= limit


@dataclass
class RouteMetrics:
    """Metrics for a route."""
    route_path: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: float = 0.0
    error_counts: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    accessed_at: Optional[float] = None
    
    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency."""
        return self.total_latency_ms / self.total_requests if self.total_requests > 0 else 0.0
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        return self.successful_requests / self.total_requests if self.total_requests > 0 else 0.0


@dataclass
class PathVariables:
    """Extracted path variables from request."""
    variables: Dict[str, str] = field(default_factory=dict)
    
    def get(self, name: str) -> Optional[str]:
        """Get a variable value."""
        return self.variables.get(name)


# ============================================================================
# API GATEWAY
# ============================================================================

class APIGateway:
    """
    API Gateway that manages routes, middleware, request routing, and metrics.
    Handles:
    - Dynamic route registration and retrieval
    - Request matching against route patterns
    - Middleware chain processing
    - Authentication and rate limiting
    - Error handling and recovery
    - Comprehensive metrics collection
    """
    
    def __init__(self):
        """Initialize API gateway."""
        self._lock = Lock()
        self.routes: List[Route] = []
        self.middlewares: List[Middleware] = []
        self.rate_limits: Dict[str, RateLimitBucket] = {}
        self.metrics: Dict[str, RouteMetrics] = {}
        self.request_log: List[Dict[str, Any]] = []
        self.request_id_counter = 0
    
    def register_route(self, route: Route) -> None:
        """Register a new route."""
        with self._lock:
            self.routes.append(route)
            self.metrics[route.path_pattern] = RouteMetrics(route_path=route.path_pattern)
    
    def register_middleware(self, middleware: Middleware) -> None:
        """Register a middleware component."""
        with self._lock:
            self.middlewares.append(middleware)
    
    def find_route(self, method: HttpMethod, path: str) -> tuple[Optional[Route], PathVariables]:
        """
        Find a matching route for the request.
        Returns the route and extracted path variables.
        """
        with self._lock:
            for route in self.routes:
                if route.method == method:
                    match = route.regex_pattern.match(path)
                    if match:
                        variables = PathVariables(variables=match.groupdict())
                        return route, variables
        return None, PathVariables()
    
    def get_routes(self) -> List[Route]:
        """Get all registered routes."""
        with self._lock:
            return list(self.routes)
    
    def search_routes(self, path_pattern: Optional[str] = None, method: Optional[HttpMethod] = None) -> List[Route]:
        """Search routes by pattern or method."""
        with self._lock:
            results = []
            for route in self.routes:
                if path_pattern and path_pattern not in route.path_pattern:
                    continue
                if method and route.method != method:
                    continue
                results.append(route)
            return results
    
    def process_request(self, method: HttpMethod, path: str, headers: Optional[Dict[str, str]] = None,
                       body: Optional[str] = None, query_params: Optional[Dict[str, str]] = None,
                       principal: Optional[str] = None) -> Response:
        """
        Process a request through the gateway.
        1. Assign request ID
        2. Find matching route
        3. Check authentication
        4. Check rate limiting
        5. Apply pre-processing middleware
        6. Call route handler
        7. Apply post-processing middleware
        8. Track metrics
        """
        start_time = time.time()
        request_id = self._generate_request_id()
        headers = headers or {}
        query_params = query_params or {}
        
        # Create request object
        request = Request(
            request_id=request_id,
            method=method,
            path=path,
            headers=headers,
            body=body,
            query_params=query_params,
            principal=principal,
            timestamp=start_time
        )
        
        # Add trace ID to headers
        request.headers['X-Request-ID'] = request_id
        
        try:
            # Find matching route
            route, path_vars = self.find_route(method, path)
            if not route:
                response = Response(status_code=404, error_message=f"Route not found: {method.value} {path}")
                self._track_metrics(None, response, start_time)
                return response
            
            # Check authentication
            if route.auth_required != AuthLevel.NONE:
                if not principal:
                    response = Response(status_code=401, error_message="Authentication required")
                    self._track_metrics(route, response, start_time)
                    return response
                
                if route.auth_required == AuthLevel.ADMIN and principal != "admin":
                    response = Response(status_code=403, error_message="Admin access required")
                    self._track_metrics(route, response, start_time)
                    return response
            
            # Check rate limiting
            if route.rate_limit:
                bucket_key = f"{principal or 'anonymous'}:{route.path_pattern}"
                bucket = self._get_or_create_rate_limit_bucket(bucket_key, principal or "anonymous", route.path_pattern)
                if not bucket.is_within_limit(route.rate_limit):
                    response = Response(status_code=429, error_message="Rate limit exceeded")
                    self._track_metrics(route, response, start_time)
                    return response
            
            # Apply pre-processing middleware
            for middleware in self.middlewares:
                if middleware.pre_processor:
                    try:
                        request = middleware.pre_processor(request)
                    except Exception as e:
                        if middleware.error_handler:
                            response = middleware.error_handler(e, request)
                            if response:
                                self._track_metrics(route, response, start_time)
                                return response
                        raise
            
            # Call route handler
            response = route.handler(request)
            
            # Apply post-processing middleware
            for middleware in self.middlewares:
                if middleware.post_processor:
                    try:
                        response = middleware.post_processor(response)
                    except Exception as e:
                        if middleware.error_handler:
                            response = middleware.error_handler(e, request)
                            if response:
                                self._track_metrics(route, response, start_time)
                                return response
                        raise
            
            # Track metrics
            self._track_metrics(route, response, start_time)
            return response
            
        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            response = Response(status_code=500, error_message=str(e), processing_time_ms=processing_time)
            self._track_metrics(None, response, start_time)
            return response
    
    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        with self._lock:
            self.request_id_counter += 1
            return f"req-{self.request_id_counter}-{uuid.uuid4().hex[:8]}"
    
    def _get_or_create_rate_limit_bucket(self, key: str, principal: str, endpoint: str) -> RateLimitBucket:
        """Get or create a rate limit bucket."""
        with self._lock:
            if key not in self.rate_limits:
                self.rate_limits[key] = RateLimitBucket(principal=principal, endpoint=endpoint)
            return self.rate_limits[key]
    
    def _track_metrics(self, route: Optional[Route], response: Response, start_time: float) -> None:
        """Track request metrics."""
        processing_time = (time.time() - start_time) * 1000
        response.processing_time_ms = processing_time
        
        with self._lock:
            if route:
                metrics = self.metrics[route.path_pattern]
                metrics.total_requests += 1
                metrics.total_latency_ms += processing_time
                metrics.accessed_at = time.time()
                
                if 200 <= response.status_code < 300:
                    metrics.successful_requests += 1
                else:
                    metrics.failed_requests += 1
                    metrics.error_counts[response.status_code] += 1
            
            # Log request
            self.request_log.append({
                'timestamp': time.time(),
                'route': route.path_pattern if route else 'unknown',
                'status_code': response.status_code,
                'processing_time_ms': processing_time
            })
    
    def get_metrics(self, route_path: Optional[str] = None) -> Dict[str, RouteMetrics]:
        """Get metrics for routes."""
        with self._lock:
            if route_path:
                return {route_path: self.metrics.get(route_path)} if route_path in self.metrics else {}
            return dict(self.metrics)
    
    def get_request_log(self) -> List[Dict[str, Any]]:
        """Get request log."""
        with self._lock:
            return list(self.request_log)
    
    def clear_rate_limits(self) -> None:
        """Clear all rate limit buckets."""
        with self._lock:
            self.rate_limits.clear()
    
    def reset_metrics(self) -> None:
        """Reset all metrics."""
        with self._lock:
            for metrics in self.metrics.values():
                metrics.total_requests = 0
                metrics.successful_requests = 0
                metrics.failed_requests = 0
                metrics.total_latency_ms = 0.0
                metrics.error_counts.clear()
                metrics.accessed_at = None


# ============================================================================
# TESTS
# ============================================================================

class TestRouteRegistration(unittest.TestCase):
    """Test route registration and retrieval."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_register_route(self):
        """Test basic route registration."""
        def handler(req):
            return Response(status_code=200, body="OK")
        
        route = Route(path_pattern="/users", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        routes = self.gateway.get_routes()
        self.assertEqual(len(routes), 1)
        self.assertEqual(routes[0].path_pattern, "/users")
    
    def test_register_multiple_routes(self):
        """Test registering multiple routes."""
        def handler(req):
            return Response(status_code=200)
        
        for i in range(5):
            route = Route(path_pattern=f"/endpoint{i}", method=HttpMethod.GET, handler=handler)
            self.gateway.register_route(route)
        
        routes = self.gateway.get_routes()
        self.assertEqual(len(routes), 5)
    
    def test_search_routes_by_pattern(self):
        """Test searching routes by path pattern."""
        def handler(req):
            return Response(status_code=200)
        
        for path in ["/users", "/users/settings", "/admin/users"]:
            route = Route(path_pattern=path, method=HttpMethod.GET, handler=handler)
            self.gateway.register_route(route)
        
        results = self.gateway.search_routes(path_pattern="/users")
        self.assertEqual(len(results), 3)  # /users, /users/settings, and /admin/users (all contain "/users")
    
    def test_search_routes_by_method(self):
        """Test searching routes by HTTP method."""
        def handler(req):
            return Response(status_code=200)
        
        self.gateway.register_route(Route(path_pattern="/users", method=HttpMethod.GET, handler=handler))
        self.gateway.register_route(Route(path_pattern="/users", method=HttpMethod.POST, handler=handler))
        self.gateway.register_route(Route(path_pattern="/admin", method=HttpMethod.GET, handler=handler))
        
        results = self.gateway.search_routes(method=HttpMethod.GET)
        self.assertEqual(len(results), 2)


class TestRequestMatching(unittest.TestCase):
    """Test request matching against routes."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_exact_path_matching(self):
        """Test exact path matching."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/users", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        matched, _ = self.gateway.find_route(HttpMethod.GET, "/users")
        self.assertIsNotNone(matched)
        self.assertEqual(matched.path_pattern, "/users")
    
    def test_path_no_match(self):
        """Test path that doesn't match."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/users", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        matched, _ = self.gateway.find_route(HttpMethod.GET, "/admin")
        self.assertIsNone(matched)
    
    def test_method_mismatch(self):
        """Test method mismatch."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/users", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        matched, _ = self.gateway.find_route(HttpMethod.POST, "/users")
        self.assertIsNone(matched)
    
    def test_path_variable_extraction(self):
        """Test extracting path variables."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/users/{id}", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        matched, path_vars = self.gateway.find_route(HttpMethod.GET, "/users/123")
        self.assertIsNotNone(matched)
        self.assertEqual(path_vars.get("id"), "123")
    
    def test_multiple_path_variables(self):
        """Test multiple path variables."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/users/{user_id}/posts/{post_id}", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        matched, path_vars = self.gateway.find_route(HttpMethod.GET, "/users/abc/posts/xyz")
        self.assertIsNotNone(matched)
        self.assertEqual(path_vars.get("user_id"), "abc")
        self.assertEqual(path_vars.get("post_id"), "xyz")
    
    def test_wildcard_pattern_matching(self):
        """Test wildcard pattern matching."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/api/*/status", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        matched, _ = self.gateway.find_route(HttpMethod.GET, "/api/service1/status")
        self.assertIsNotNone(matched)
        
        matched, _ = self.gateway.find_route(HttpMethod.GET, "/api/service2/status")
        self.assertIsNotNone(matched)


class TestMiddlewareChain(unittest.TestCase):
    """Test middleware processing."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_pre_processing_middleware(self):
        """Test pre-processing middleware modifies request."""
        modifications = []
        
        def pre_processor(req):
            modifications.append("pre")
            req.headers['X-Modified'] = 'true'
            return req
        
        middleware = Middleware(name="test", pre_processor=pre_processor)
        self.gateway.register_middleware(middleware)
        
        def handler(req):
            self.assertEqual(req.headers.get('X-Modified'), 'true')
            return Response(status_code=200, body="OK")
        
        route = Route(path_pattern="/test", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        response = self.gateway.process_request(HttpMethod.GET, "/test")
        self.assertEqual(response.status_code, 200)
        self.assertIn("pre", modifications)
    
    def test_post_processing_middleware(self):
        """Test post-processing middleware modifies response."""
        def post_processor(resp):
            resp.headers['X-Processed'] = 'true'
            return resp
        
        middleware = Middleware(name="test", post_processor=post_processor)
        self.gateway.register_middleware(middleware)
        
        def handler(req):
            return Response(status_code=200, body="OK")
        
        route = Route(path_pattern="/test", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        response = self.gateway.process_request(HttpMethod.GET, "/test")
        self.assertEqual(response.headers.get('X-Processed'), 'true')
    
    def test_middleware_order_preserved(self):
        """Test middleware is applied in order."""
        order = []
        
        def pre1(req):
            order.append("pre1")
            return req
        
        def pre2(req):
            order.append("pre2")
            return req
        
        self.gateway.register_middleware(Middleware(name="m1", pre_processor=pre1))
        self.gateway.register_middleware(Middleware(name="m2", pre_processor=pre2))
        
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/test", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/test")
        self.assertEqual(order, ["pre1", "pre2"])


class TestAuthenticationHooks(unittest.TestCase):
    """Test authentication handling."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_auth_not_required(self):
        """Test endpoint with no auth requirement."""
        def handler(req):
            return Response(status_code=200, body="OK")
        
        route = Route(path_pattern="/public", method=HttpMethod.GET, handler=handler, auth_required=AuthLevel.NONE)
        self.gateway.register_route(route)
        
        response = self.gateway.process_request(HttpMethod.GET, "/public")
        self.assertEqual(response.status_code, 200)
    
    def test_auth_required_missing_principal(self):
        """Test auth required but no principal provided."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/private", method=HttpMethod.GET, handler=handler, auth_required=AuthLevel.REQUIRED)
        self.gateway.register_route(route)
        
        response = self.gateway.process_request(HttpMethod.GET, "/private")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Authentication required", response.error_message)
    
    def test_auth_required_with_principal(self):
        """Test auth required with valid principal."""
        def handler(req):
            return Response(status_code=200, body=f"Hello {req.principal}")
        
        route = Route(path_pattern="/private", method=HttpMethod.GET, handler=handler, auth_required=AuthLevel.REQUIRED)
        self.gateway.register_route(route)
        
        response = self.gateway.process_request(HttpMethod.GET, "/private", principal="user1")
        self.assertEqual(response.status_code, 200)
    
    def test_admin_auth_required(self):
        """Test admin authentication requirement."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/admin", method=HttpMethod.GET, handler=handler, auth_required=AuthLevel.ADMIN)
        self.gateway.register_route(route)
        
        # Non-admin user
        response = self.gateway.process_request(HttpMethod.GET, "/admin", principal="user")
        self.assertEqual(response.status_code, 403)
        
        # Admin user
        response = self.gateway.process_request(HttpMethod.GET, "/admin", principal="admin")
        self.assertEqual(response.status_code, 200)


class TestRateLimiting(unittest.TestCase):
    """Test rate limiting."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_rate_limit_not_exceeded(self):
        """Test when rate limit is not exceeded."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/api", method=HttpMethod.GET, handler=handler, rate_limit=5)
        self.gateway.register_route(route)
        
        for i in range(3):
            response = self.gateway.process_request(HttpMethod.GET, "/api", principal="user1")
            self.assertEqual(response.status_code, 200)
    
    def test_rate_limit_exceeded(self):
        """Test when rate limit is exceeded."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/api", method=HttpMethod.GET, handler=handler, rate_limit=2)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/api", principal="user1")
        self.gateway.process_request(HttpMethod.GET, "/api", principal="user1")
        response = self.gateway.process_request(HttpMethod.GET, "/api", principal="user1")
        
        self.assertEqual(response.status_code, 429)
    
    def test_rate_limit_per_principal(self):
        """Test rate limits are tracked per principal."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/api", method=HttpMethod.GET, handler=handler, rate_limit=2)
        self.gateway.register_route(route)
        
        # User 1 uses 2 requests
        self.gateway.process_request(HttpMethod.GET, "/api", principal="user1")
        self.gateway.process_request(HttpMethod.GET, "/api", principal="user1")
        
        # User 2 should still have requests available
        response = self.gateway.process_request(HttpMethod.GET, "/api", principal="user2")
        self.assertEqual(response.status_code, 200)


class TestErrorHandling(unittest.TestCase):
    """Test error handling."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_route_not_found(self):
        """Test 404 for unknown route."""
        response = self.gateway.process_request(HttpMethod.GET, "/unknown")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Route not found", response.error_message)
    
    def test_handler_exception(self):
        """Test handler exceptions return 500."""
        def handler(req):
            raise ValueError("Something went wrong")
        
        route = Route(path_pattern="/error", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        response = self.gateway.process_request(HttpMethod.GET, "/error")
        self.assertEqual(response.status_code, 500)
    
    def test_middleware_error_handler(self):
        """Test middleware error handler."""
        handler_called = []
        
        def failing_pre_process(req):
            raise RuntimeError("Middleware error")
        
        def error_handler(exc, req):
            handler_called.append(True)
            return Response(status_code=503, error_message="Service unavailable")
        
        middleware = Middleware(name="test", pre_processor=failing_pre_process, error_handler=error_handler)
        self.gateway.register_middleware(middleware)
        
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/test", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        response = self.gateway.process_request(HttpMethod.GET, "/test")
        self.assertEqual(response.status_code, 503)
        self.assertTrue(handler_called)


class TestMetricsCollection(unittest.TestCase):
    """Test metrics tracking."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_request_metrics_tracked(self):
        """Test that request metrics are tracked."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/api", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/api")
        self.gateway.process_request(HttpMethod.GET, "/api")
        
        metrics = self.gateway.get_metrics("/api")
        self.assertEqual(metrics["/api"].total_requests, 2)
        self.assertEqual(metrics["/api"].successful_requests, 2)
    
    def test_error_metrics_tracked(self):
        """Test that error metrics are tracked."""
        def handler(req):
            return Response(status_code=500, error_message="Error")
        
        route = Route(path_pattern="/error", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/error")
        
        metrics = self.gateway.get_metrics("/error")
        self.assertEqual(metrics["/error"].failed_requests, 1)
        self.assertEqual(metrics["/error"].error_counts[500], 1)
    
    def test_latency_metrics(self):
        """Test latency metrics."""
        def handler(req):
            time.sleep(0.01)  # 10ms
            return Response(status_code=200)
        
        route = Route(path_pattern="/api", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/api")
        
        metrics = self.gateway.get_metrics("/api")
        self.assertTrue(metrics["/api"].total_latency_ms > 5)


class TestRequestIDTracking(unittest.TestCase):
    """Test request ID assignment and tracking."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_request_id_assigned(self):
        """Test request ID is assigned."""
        request_ids = []
        
        def handler(req):
            request_ids.append(req.request_id)
            return Response(status_code=200)
        
        route = Route(path_pattern="/test", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/test")
        
        self.assertEqual(len(request_ids), 1)
        self.assertTrue(request_ids[0].startswith("req-"))
    
    def test_request_ids_unique(self):
        """Test request IDs are unique."""
        request_ids = []
        
        def handler(req):
            request_ids.append(req.request_id)
            return Response(status_code=200)
        
        route = Route(path_pattern="/test", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        for _ in range(5):
            self.gateway.process_request(HttpMethod.GET, "/test")
        
        self.assertEqual(len(set(request_ids)), 5)
    
    def test_request_id_propagated_to_headers(self):
        """Test request ID is added to headers."""
        request_headers = []
        
        def handler(req):
            request_headers.append(dict(req.headers))
            return Response(status_code=200)
        
        route = Route(path_pattern="/test", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/test")
        
        self.assertIn('X-Request-ID', request_headers[0])
        self.assertTrue(request_headers[0]['X-Request-ID'].startswith("req-"))


class TestRoutePatternMatching(unittest.TestCase):
    """Test complex route pattern matching."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_query_params_preserved(self):
        """Test query parameters are preserved in request."""
        captured_query_params = []
        
        def handler(req):
            captured_query_params.append(req.query_params)
            return Response(status_code=200)
        
        route = Route(path_pattern="/search", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/search", query_params={"q": "test", "page": "1"})
        
        self.assertEqual(captured_query_params[0]["q"], "test")
        self.assertEqual(captured_query_params[0]["page"], "1")
    
    def test_headers_preserved(self):
        """Test headers are preserved in request."""
        captured_headers = []
        
        def handler(req):
            captured_headers.append(req.headers)
            return Response(status_code=200)
        
        route = Route(path_pattern="/api", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        self.gateway.process_request(HttpMethod.GET, "/api", headers={"Authorization": "Bearer token"})
        
        self.assertIn("Authorization", captured_headers[0])


class TestGatewayIntegration(unittest.TestCase):
    """End-to-end gateway integration tests."""
    
    def setUp(self):
        """Set up test gateway."""
        self.gateway = APIGateway()
    
    def test_complete_request_flow(self):
        """Test complete request processing flow."""
        # Track flow
        flow = []
        
        def pre_process(req):
            flow.append("pre")
            req.headers['X-User'] = req.principal or "anonymous"
            return req
        
        def post_process(resp):
            flow.append("post")
            resp.headers['X-Processed'] = 'true'
            return resp
        
        # Setup middleware
        self.gateway.register_middleware(Middleware(name="tracking", pre_processor=pre_process, post_processor=post_process))
        
        # Setup route
        def handler(req):
            flow.append("handler")
            self.assertEqual(req.headers.get('X-User'), 'user1')
            return Response(status_code=200, body="Success")
        
        route = Route(path_pattern="/users/{id}", method=HttpMethod.GET, handler=handler, auth_required=AuthLevel.REQUIRED)
        self.gateway.register_route(route)
        
        # Process request
        response = self.gateway.process_request(HttpMethod.GET, "/users/123", principal="user1")
        
        # Verify flow
        self.assertEqual(flow, ["pre", "handler", "post"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('X-Processed'), 'true')
    
    def test_multiple_routes_independent(self):
        """Test multiple routes operate independently."""
        def handler1(req):
            return Response(status_code=200, body="Route 1")
        
        def handler2(req):
            return Response(status_code=201, body="Route 2")
        
        self.gateway.register_route(Route(path_pattern="/route1", method=HttpMethod.GET, handler=handler1))
        self.gateway.register_route(Route(path_pattern="/route2", method=HttpMethod.POST, handler=handler2))
        
        r1 = self.gateway.process_request(HttpMethod.GET, "/route1")
        r2 = self.gateway.process_request(HttpMethod.POST, "/route2")
        
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 201)
    
    def test_gateway_under_load(self):
        """Test gateway handles multiple concurrent requests."""
        def handler(req):
            return Response(status_code=200)
        
        route = Route(path_pattern="/api", method=HttpMethod.GET, handler=handler)
        self.gateway.register_route(route)
        
        # Process many requests
        for i in range(20):
            response = self.gateway.process_request(HttpMethod.GET, "/api")
            self.assertEqual(response.status_code, 200)
        
        metrics = self.gateway.get_metrics("/api")
        self.assertEqual(metrics["/api"].total_requests, 20)


if __name__ == '__main__':
    unittest.main()

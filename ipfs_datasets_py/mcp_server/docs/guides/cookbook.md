# MCP Server Cookbook (v6)

A collection of ready-to-run recipes for common MCP server tasks introduced
or improved in v6.

---

## Recipe 1 — Parallel Tool Dispatch

Run multiple tool calls concurrently and collect results in order.

```python
import asyncio
import anyio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

async def main():
    manager = HierarchicalToolManager()

    # --- Basic parallel dispatch ---
    calls = [
        {"category": "dataset_tools", "tool": "load_dataset",     "params": {"source": "squad"}},
        {"category": "graph_tools",   "tool": "query_knowledge_graph"},
        {"category": "vector_tools",  "tool": "search_vector_index", "params": {"query": "AI"}},
    ]

    results = await manager.dispatch_parallel(calls)

    for i, result in enumerate(results):
        if result.get("status") == "error":
            print(f"Call {i} failed: {result['error']}")
        else:
            print(f"Call {i} succeeded")

    # --- Adaptive batching: at most 4 concurrent calls ---
    big_calls = [
        {"category": "dataset_tools", "tool": "load_dataset", "params": {"source": f"ds_{i}"}}
        for i in range(20)
    ]
    results = await manager.dispatch_parallel(big_calls, max_concurrent=4)
    print(f"Got {len(results)} results")

    # --- Fail-fast: raise on first error ---
    try:
        results = await manager.dispatch_parallel(calls, return_exceptions=False)
    except Exception as exc:
        print(f"One call failed: {exc}")

anyio.run(main)
```

**Key points:**
- Results are always returned in the **same order** as the input `calls` list.
- `return_exceptions=True` (default): individual errors become `{"status": "error", ...}` dicts.
- `return_exceptions=False`: the first exception cancels the task group.
- `max_concurrent=N`: caps concurrent calls to `N`; useful when downstream
  services have rate limits or when `calls` is very large.

---

## Recipe 2 — CircuitBreaker

Protect downstream calls with a circuit breaker that opens after repeated
failures and probes automatically after a recovery window.

```python
import asyncio
import anyio
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import CircuitBreaker

async def fragile_service(x: int) -> str:
    if x < 3:
        raise ConnectionError("service unavailable")
    return f"ok:{x}"

async def main():
    breaker = CircuitBreaker(
        name="fragile_svc",
        failure_threshold=3,   # trip after 3 consecutive failures
        recovery_timeout=5.0,  # probe again after 5 seconds
    )

    # First 3 calls fail → circuit opens
    for i in range(3):
        try:
            await breaker.call(fragile_service, i)
        except Exception as exc:
            print(f"Call {i}: {exc}")

    print(f"State: {breaker.state}")  # "open"

    # Calls while OPEN are rejected immediately (no I/O)
    try:
        await breaker.call(fragile_service, 99)
    except Exception as exc:
        print(f"Rejected: {exc}")    # CircuitBreakerOpenError

    # Simulate recovery window passing
    await asyncio.sleep(6)
    print(f"State: {breaker.state}")  # "half_open" — auto-transitioned

    # Probe succeeds → circuit closes
    result = await breaker.call(fragile_service, 10)
    print(f"Probe result: {result}")  # "ok:10"
    print(f"State: {breaker.state}")  # "closed"

    # Introspect
    print(breaker.info())
    # {"name": "fragile_svc", "state": "closed", "failure_count": 0, ...}

    # Manual reset (always returns to CLOSED)
    breaker.reset()

anyio.run(main)
```

**Key points:**
- The circuit breaker is **per-instance** — create one per downstream service.
- `KeyboardInterrupt` and `SystemExit` always propagate through uncaught.
- `breaker.info()` returns a snapshot dict for health-check endpoints.

---

## Recipe 3 — JWT Authentication & Token Revocation

Mint, verify, and revoke JWT tokens for the Enterprise API.

```python
import os
from ipfs_datasets_py.mcp_server.enterprise_api import AuthenticationManager

# Always use an environment variable for the signing key in production.
os.environ.setdefault("JWT_SECRET_KEY", "change-me-in-production")

auth = AuthenticationManager()

# --- Mint a token ---
token = auth.create_access_token("demo")
print(f"Token: {token[:20]}...")

# --- Verify ---
user_data = auth.verify_token(token)
print(f"Logged in as: {user_data['username']}")  # "demo"

# --- Revoke (e.g. on logout) ---
success = auth.revoke_token(token)
print(f"Revoked: {success}")   # True

# --- Subsequent verify returns None ---
user_data = auth.verify_token(token)
print(f"After revoke: {user_data}")   # None

# --- authenticate() raises 401 for revoked tokens ---
import asyncio
from fastapi import HTTPException
async def check():
    try:
        await auth.authenticate(token)
    except HTTPException as exc:
        print(f"401: {exc.detail}")   # "Token has been revoked"
asyncio.run(check())

# --- Invalid token returns False from revoke_token ---
bad = auth.revoke_token("not.a.valid.jwt")
print(f"Bad token revoke: {bad}")   # False
```

**Production notes:**
- The in-memory revocation store (`_revoked_tokens`) is cleared on process
  restart.  Replace it with Redis (`SETNX` / `EXPIRE`) or a database table
  for persistent revocation.
- Tokens that have already expired are still accepted by `revoke_token`
  (expiry verification is disabled for revocation) to allow explicit
  invalidation of known-bad tokens.

---

## Recipe 4 — Prometheus Metrics

Export MCP server metrics to Prometheus.

```python
from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
from ipfs_datasets_py.mcp_server.monitoring import get_metrics_collector

# Attach exporter to the running metrics collector.
exporter = PrometheusExporter(
    collector=get_metrics_collector(),
    port=9090,
    namespace="mcp",
)

# Start the HTTP /metrics endpoint (requires prometheus-client).
try:
    exporter.start_http_server()
    print("Prometheus metrics available at http://localhost:9090/metrics")
except ImportError:
    print("prometheus-client not installed; metrics endpoint disabled")

# Record individual tool calls.
exporter.record_tool_call(
    category="dataset_tools",
    tool="load_dataset",
    status="success",
    latency_seconds=0.042,
)

# Periodically push latest stats from the collector.
import asyncio
async def metrics_loop():
    while True:
        exporter.update()
        await asyncio.sleep(15)

print(exporter.get_info())
```

---

## Recipe 5 — OpenTelemetry Distributed Tracing

Instrument MCP dispatches with OpenTelemetry spans.

```python
from ipfs_datasets_py.mcp_server.otel_tracing import configure_tracing, MCPTracer

# One-time bootstrap (call at application start).
configured = configure_tracing(
    service_name="ipfs-mcp-server",
    otlp_endpoint="http://localhost:4317",
    export_protocol="grpc",
    insecure=True,
)
if not configured:
    print("OTel packages not installed; tracing disabled (no-op mode)")

tracer = MCPTracer()

# Manual span management.
import anyio
async def traced_dispatch(manager, category, tool, params):
    with tracer.start_dispatch_span(category, tool, params) as span:
        result = await manager.dispatch(category, tool, params)
        tracer.set_span_ok(span, result)
        return result

# Decorator style.
@tracer.trace_tool_call
async def load_my_dataset(category: str, tool: str, params: dict):
    from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager
    return await HierarchicalToolManager().dispatch(category, tool, params)

print(tracer.get_info())
```

---

## Recipe 6 — gRPC Transport

Serve MCP tool calls over gRPC (requires `grpcio`).

```python
import anyio
from ipfs_datasets_py.mcp_server.grpc_transport import GRPCTransportAdapter
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager

async def main():
    manager = HierarchicalToolManager()
    adapter = GRPCTransportAdapter(manager, host="[::]", port=50051)

    try:
        await adapter.start()
        print(f"gRPC server running: {adapter.is_running}")

        # Handle a request programmatically.
        from ipfs_datasets_py.mcp_server.grpc_transport import GRPCToolRequest
        req = GRPCToolRequest(
            category="dataset_tools",
            tool="load_dataset",
            params_json='{"source": "squad"}',
            request_id="req-001",
        )
        resp = await adapter.handle_request(req)
        print(f"success={resp.success}, id={resp.request_id}")

        await adapter.stop()
    except ImportError as exc:
        print(f"gRPC unavailable: {exc}")

    print(adapter.get_info())

anyio.run(main)
```

---

*See `docs/api/tool-reference.md` for full API reference and
`docs/adr/ADR-005-v6-coverage-hardening.md` for design rationale.*

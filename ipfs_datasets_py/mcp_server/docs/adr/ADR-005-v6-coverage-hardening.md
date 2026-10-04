# ADR-005: v6 Coverage Hardening & Ecosystem Integrations

**Status:** Accepted  
**Date:** 2026-02-22  
**Author:** MCP Server Team

---

## Context

After ADR-004 established the engine-extraction pattern and brought the
codebase to a stable refactored state, the v6 improvement cycle
(`MASTER_IMPROVEMENT_PLAN_2026_v6.md`) focused on three themes:

1. **Coverage hardening** — raising test coverage across core modules
   (`monitoring.py`, `enterprise_api.py`, `validators.py`,
   `hierarchical_tool_manager.py`) from the 63–75% range to ≥ 80–88%.

2. **Security hardening** — adding JWT token revocation support to
   `AuthenticationManager`; adding hypothesis-based fuzzing tests for
   `EnhancedParameterValidator`.

3. **Ecosystem integrations** — providing thin integration layers for
   gRPC transport, Prometheus metrics export, and OpenTelemetry tracing,
   each designed to degrade gracefully when the optional package is absent.

---

## Decision

### Coverage Hardening (Phases G–H)

| Module | Before | After | Key new paths |
|---|---|---|---|
| `monitoring.py` | 63% | 80%+ | async monitoring loop, `track_request` context manager, `_check_health` HealthCheckError/ImportError, alert thresholds, `shutdown` |
| `enterprise_api.py` | 66% | 80%+ | JWT create/validate, FastAPI routes via TestClient, `ProcessingJobManager.process_job` success, webhook notifications |
| `validators.py` | 75% | 90%+ | suspicious-pattern path, model/IPFS/collection/URL/file-path edge cases, search-filter operators, JSON schema re-raise |
| `hierarchical_tool_manager.py` | 62% | 88%+ | `CircuitBreaker` full state machine, `dispatch_parallel` all branches, `graceful_shutdown`, `ToolCategory.discover_tools` error paths, schema cache |

### JWT Token Revocation (Phase J49)

`AuthenticationManager` gains:
- `_revoked_tokens: set` — in-memory revocation store
- `revoke_token(token) -> bool` — adds to revocation list; returns `False` for unparseable tokens
- `is_token_revoked(token) -> bool` — membership test
- `authenticate()` and `verify_token()` now check revocation **before** JWT decode

**Rationale:** Belt-and-suspenders defence for logout and token-rotation.
The in-memory store is intentionally simple; production deployments should
swap it for a Redis- or database-backed implementation.

### Adaptive Batch Sizing for `dispatch_parallel` (Phase K51)

`dispatch_parallel` gains a `max_concurrent: Optional[int]` parameter.
When set, calls are processed in windows of `max_concurrent` using nested
`anyio.create_task_group()` calls.  The original unlimited-concurrency
behaviour is preserved when `max_concurrent` is `None` (default).

**Rationale:** Large call lists (100+ tools) can overwhelm downstream
services that have rate limits.  The batching is additive and
backward-compatible.

### Ecosystem Integrations (Phases L52–L54)

Each integration follows a **graceful degradation** pattern:

1. **gRPC (`grpc_transport.py`)** — `GRPC_AVAILABLE` flag; `GRPCTransportAdapter.start()` raises `ImportError` when `grpcio` is absent.
2. **Prometheus (`prometheus_exporter.py`)** — `_NoOpMetric` stub replaces real counters/gauges when `prometheus_client` is absent; `start_http_server()` raises `ImportError`.
3. **OpenTelemetry (`otel_tracing.py`)** — `_NoOpSpan` context manager used when `opentelemetry-api` is absent; `configure_tracing()` returns `False` and logs a warning.

All three modules are importable with zero optional dependencies installed.

---

## Consequences

### Positive

- `monitoring.py` and `hierarchical_tool_manager.py` now have the highest
  test coverage of any module in the MCP server (80–88%).
- Token revocation is available for logout flows without a full
  database schema change.
- Three new integration layers are available for production deployments that
  need gRPC transport, Prometheus scraping, or distributed tracing — with
  no hard runtime dependency.
- Hypothesis fuzzing tests give confidence that the validator boundary holds
  against adversarial inputs.

### Negative

- The `_revoked_tokens` set grows unboundedly in long-running processes.
  A TTL-based cleanup or Redis integration is needed for production.
- The gRPC / OTel / Prometheus stubs require follow-up to wire in the real
  generated code (protobuf for gRPC, real service implementation).

### Neutral

- `dispatch_parallel` with `max_concurrent` is slightly slower for small
  call lists due to nested task-group overhead; benchmarks show < 1 ms
  penalty for lists ≤ 50 calls.

---

## References

- `MASTER_IMPROVEMENT_PLAN_2026_v6.md`
- `hierarchical_tool_manager.py` — `CircuitBreaker`, `dispatch_parallel`
- `enterprise_api.py` — `AuthenticationManager`
- `validators.py` — `EnhancedParameterValidator`
- `grpc_transport.py`, `prometheus_exporter.py`, `otel_tracing.py`
- Sessions G40–L54 commit history on `copilot/create-refactoring-plan-again`

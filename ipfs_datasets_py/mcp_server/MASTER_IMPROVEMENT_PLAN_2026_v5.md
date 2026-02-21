# MCP Server — Master Improvement Plan v5.0

**Date:** 2026-02-21 (last updated)  
**Status:** 🟢 **ALL PHASES COMPLETE** — Sessions 22-26 on branch `copilot/refactor-markdown-files-again`  
**Preconditions:** All 7 v4 phases are ✅ complete (see [PHASES_STATUS.md](PHASES_STATUS.md))  
**Branch:** `copilot/refactor-markdown-files-again`

**Phase Completion Summary:**
- ✅ **Phase A** (Docs): `docs/tools/README.md` 49-cat table; `docs/api/tool-reference.md` 530L; `docs/adr/` 4 ADRs
- ✅ **Phase B** (Tests): 160+ tests passing; `test_graph/storage/provenance/file_converter/alert/media/p2p/web_archive/audit/security/monitoring/search/pdf/_tools.py` + `test_validators_property.py` + `test_tool_scenarios.py`
- ✅ **Phase C** (Observability): `request_id` UUID4 in every `dispatch()` response; `/health/ready` + `/metrics` endpoints; `get_tool_latency_percentiles()` in `EnhancedMetricsCollector`
- ✅ **Phase D** (Versioning): `ToolMetadata.schema_version`, `deprecated`, `deprecation_message` fields + `@tool_metadata()` params; `dispatch()` WARNING on deprecated tool
- ✅ **Phase E** (Benchmarks): `benchmarks/` suite (4 files, 15 tests); `.github/workflows/mcp-benchmarks.yml` CI workflow
- ✅ **Phase F** (Runtime): `dispatch_parallel()` (anyio task group); `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN); `graceful_shutdown()`; `cache_ttl` result caching hook; `_get_result_cache()` lazy initialiser

---

## TL;DR

The MCP server refactoring (v4) is fully complete. This v5 plan defines the **next generation of improvements** focused on documentation completeness, extended testing, observability, and advanced runtime features.

**Baseline (as of 2026-02-20):**
- 853 tests passing · 38 skipped · 0 failing
- 85-90% coverage across core modules
- 0 bare exceptions · 0 missing docstrings · 0 missing return types
- 382 tools · 60 categories · 4 meta-tools (hierarchical)
- Lazy loading · schema caching · P2P connection pooling

---

## Table of Contents

1. [Current State Assessment](#1-current-state-assessment)
2. [Improvement Areas](#2-improvement-areas)
3. [Phase A: Documentation Completion](#3-phase-a-documentation-completion)
4. [Phase B: Testing Depth](#4-phase-b-testing-depth)
5. [Phase C: Observability & Diagnostics](#5-phase-c-observability--diagnostics)
6. [Phase D: API Versioning & Stability](#6-phase-d-api-versioning--stability)
7. [Phase E: Performance Benchmarking](#7-phase-e-performance-benchmarking)
8. [Phase F: Advanced Runtime Features](#8-phase-f-advanced-runtime-features)
9. [Success Metrics](#9-success-metrics)
10. [Timeline & Prioritisation](#10-timeline--prioritisation)

---

## 1. Current State Assessment

### 1.1 Strengths (inherited from v4)

| Area | Status |
|------|--------|
| Architecture | ✅ Thin wrappers, hierarchical tools, dual-runtime |
| Security | ✅ 5 vulnerabilities fixed, no hardcoded secrets |
| Code quality | ✅ 0 bare exceptions, full type hints, docstrings |
| Test volume | ✅ 853 passing tests |
| Performance | ✅ Lazy loading, schema caching, P2P connection pool |

### 1.2 Remaining Gaps

| Area | Gap | Impact |
|------|-----|--------|
| Documentation | `docs/tools/README.md` and `docs/api/tool-reference.md` are stubs | Medium |
| Testing | Per-tool coverage highly uneven; many tool files untested | Medium |
| Observability | No structured tracing or distributed request IDs | Medium |
| API stability | No formal versioning contract for tool schemas | Low-Medium |
| Benchmarks | `benchmarks/` directory exists but contains only a README | Low-Medium |
| Typing | Inner closure functions in `server.py` lack return annotations | Low |

---

## 2. Improvement Areas

Six improvement phases are proposed. Each is **independent** — they can be started in any order or pursued in parallel.

| Phase | Area | Effort | Priority |
|-------|------|--------|----------|
| A | Documentation Completion | 4-6h | 🔴 High |
| B | Testing Depth | 8-12h | 🔴 High |
| C | Observability & Diagnostics | 6-8h | 🟡 Medium |
| D | API Versioning & Stability | 4-6h | 🟡 Medium |
| E | Performance Benchmarking | 4-6h | 🟡 Medium |
| F | Advanced Runtime Features | 10-14h | 🟢 Low |

**Total estimated effort:** 36-52 hours

---

## 3. Phase A: Documentation Completion

**Goal:** Eliminate all "Coming soon" / stub sections in the `docs/` tree and produce accurate, navigable reference material.

### A1: Tool Reference (docs/api/tool-reference.md)

**Current state:** Incomplete — lists only 4 tool categories.  
**Target:** Document all 60 categories with:
- Category purpose and use cases
- List of tools with one-line descriptions
- Common parameter types and return shapes
- At least one usage example per category

**Steps:**
1. Audit `tools/*/` directories — collect function signatures and docstrings
2. Generate a category summary table
3. Add per-category sections with tool lists
4. Add cross-references to THIN_TOOL_ARCHITECTURE.md

**Effort:** 3-4h

### A2: Tools README (docs/tools/README.md)

**Current state:** Stub — "Coming soon."  
**Target:** Navigation index for all 60 tool categories, with one-line descriptions and links to relevant source files.

**Effort:** 1-2h

### A3: Performance Tuning Guide (docs/guides/performance-tuning.md)

**Current state:** Exists but may not reflect Phase 7 optimizations.  
**Target:** Accurate guide covering:
- Lazy loading configuration
- Schema cache tuning
- P2P connection pool sizing
- Benchmarking procedure

**Effort:** 1h

### A4: Architecture Decision Records

**Current state:** No ADR directory.  
**Target:** `docs/adr/` with ADRs for key design decisions:
- ADR-001: Thin wrapper pattern
- ADR-002: Dual-runtime (FastAPI + Trio)
- ADR-003: Hierarchical tool system
- ADR-004: Engine extraction pattern (thick tools)

**Effort:** 1-2h

---

## 4. Phase B: Testing Depth

**Goal:** Increase per-tool coverage; add scenario-level integration tests; close remaining coverage gaps.

### B1: Tool Category Coverage Audit

**Current state:** Core server files at 85-90%; individual tool files largely untested.  
**Target:** Identify and address the lowest-coverage tool categories.

**Steps:**
1. Run `pytest tests/mcp/ --cov=ipfs_datasets_py.mcp_server.tools --cov-report=term-missing`
2. List categories with <50% coverage
3. Prioritise by usage frequency and complexity

**Effort:** 1h

### B2: Tool-Level Unit Tests for Top 10 Categories

**Target:** Add ≥3 unit tests per tool for the 10 most-used categories:

| Category | Key Scenarios |
|----------|---------------|
| `dataset_tools` | load, save, convert, invalid path |
| `search_tools` | semantic search, no results, pagination |
| `graph_tools` | query, insert, relationship lookup |
| `ipfs_tools` | pin, get, CAR conversion, timeout |
| `vector_tools` | index, search, delete, dimension mismatch |
| `pdf_tools` | extract text, OCR fallback, corrupt file |
| `embedding_tools` | embed text, batch, model unavailable |
| `monitoring_tools` | metrics collection, alert trigger |
| `security_tools` | scan, report, safe input |
| `audit_tools` | log event, retrieve, filter |

**Effort:** 4-6h

### B3: Scenario Integration Tests

**Current gap:** Integration tests focus on component interactions; missing end-to-end scenarios.  
**Target:** Add 5-10 scenario tests to `tests/mcp/integration/test_tool_scenarios.py`:

```python
async def test_dataset_search_pipeline():
    """Load dataset → embed → index → semantic search."""

async def test_p2p_workflow_submission():
    """Submit workflow → check status → retrieve result."""

async def test_graph_knowledge_extraction():
    """PDF → extract entities → build graph → query."""
```

**Effort:** 2-3h

### B4: Property-Based Testing for Validators

**Current state:** `validators.py` tested with fixed inputs.  
**Target:** Use `hypothesis` to property-test all 7 validator functions:
- Path traversal prevention
- URL sanitisation
- Integer bounds
- String length limits

**Effort:** 1-2h

---

## 5. Phase C: Observability & Diagnostics

**Goal:** Make the server's internal behaviour visible in production through structured logging, request tracing, and health endpoints.

### C1: Structured Request Logging

**Current state:** `logger.py` provides basic logging.  
**Target:** All tool executions log a structured record:

```json
{
  "request_id": "uuid4",
  "tool": "dataset_tools/load_dataset",
  "runtime": "fastapi",
  "duration_ms": 42,
  "status": "success",
  "error": null
}
```

**Implementation:**
- Add `request_id` to `ServerContext`
- Propagate through `HierarchicalToolManager.dispatch()`
- Emit structured log in `monitoring.py`

**Effort:** 2-3h

### C2: `/health` and `/metrics` Endpoints

**Current state:** `monitoring.py` collects metrics; no HTTP exposure for external scrapers.  
**Target:** Add to `fastapi_service.py`:
- `GET /health` — liveness probe (status, uptime, tool count)
- `GET /health/ready` — readiness probe (dependencies checked)
- `GET /metrics` — Prometheus-format metrics text output

**Effort:** 2-3h

### C3: Tool Execution Histogram

**Current state:** Metrics collected but not histogrammed per tool.  
**Target:** Per-tool `p99`, `p95`, `p50` latency tracked in `EnhancedMetricsCollector`.

**Effort:** 1-2h

---

## 6. Phase D: API Versioning & Stability

**Goal:** Establish a formal stability contract so consumers can depend on the tool schema.

### D1: Tool Schema Versioning

**Current state:** No version in tool schemas.  
**Target:** Add `schema_version` field to `ToolMetadata` and tool schema dicts:

```python
@dataclass
class ToolMetadata:
    name: str
    schema_version: str = "1.0"
    ...
```

Expose via `tools_get_schema()` and `HierarchicalToolManager.get_tool_schema()`.

**Effort:** 1-2h

### D2: Deprecation Markers

**Current state:** Old/renamed tools silently removed.  
**Target:** Add `deprecated: bool` and `deprecation_message: str` to `ToolMetadata`; log deprecation warnings on invocation.

**Effort:** 1h

### D3: Schema Change Detection Test

**Target:** Add a snapshot test that fails when any tool schema changes unexpectedly:

```python
def test_tool_schema_unchanged():
    """Guard against accidental schema regressions."""
    schema = tools_get_schema("dataset_tools", "load_dataset")
    assert schema == EXPECTED_SCHEMA  # golden file
```

**Effort:** 1-2h

---

## 7. Phase E: Performance Benchmarking

**Goal:** Formalise and automate the benchmarks so regressions are caught in CI.

### E1: Benchmark Suite (`benchmarks/`)

**Current state:** `benchmarks/README.md` placeholder only.  
**Target:** Runnable benchmark suite using `pytest-benchmark`:

```
benchmarks/
├── bench_hierarchical_dispatch.py   # dispatch latency
├── bench_schema_cache.py            # cache hit vs miss overhead
├── bench_p2p_connection_pool.py     # pool acquire/release
├── bench_tool_loading.py            # lazy vs eager startup
└── README.md                        # how to run, baseline results
```

**Key targets:**

| Operation | Baseline | Target |
|-----------|----------|--------|
| `dispatch()` (cache warm) | TBD | <5ms |
| `get_tool_schema()` (cached) | TBD | <0.1ms |
| Server startup (lazy) | TBD | <1s |
| P2P connection acquire (pool hit) | TBD | <1ms |

**Effort:** 3-4h

### E2: CI Integration

**Target:** Run benchmarks in CI on every PR; fail if any operation regresses >20%.

```yaml
# .github/workflows/mcp-benchmarks.yml
- name: Run MCP benchmarks
  run: pytest benchmarks/ --benchmark-compare --benchmark-compare-fail=mean:20%
```

**Effort:** 1-2h

---

## 8. Phase F: Advanced Runtime Features

**Goal:** Extend the runtime system with features that improve throughput and resilience.

### F1: Parallel Tool Execution

**Current state:** `HierarchicalToolManager.dispatch()` executes one tool at a time.  
**Target:** Add `dispatch_parallel(calls: list[ToolCall]) -> list[ToolResult]` method that fans out to both runtimes concurrently using `anyio.create_task_group()`.

**Effort:** 3-4h

### F2: Tool Result Caching (Optional)

**Current state:** No result-level caching.  
**Target:** Add opt-in per-tool TTL cache via `@tool_metadata(cache_ttl=60)`. Results stored in `mcplusplus/result_cache.py` (already exists).

**Effort:** 2-3h

### F3: Circuit Breaker for Flaky Tools

**Current state:** Flaky tools fail on every call.  
**Target:** Add circuit breaker state machine to `HierarchicalToolManager`:
- CLOSED → OPEN after N consecutive failures
- OPEN → HALF_OPEN after timeout
- HALF_OPEN → CLOSED on success

**Effort:** 3-4h

### F4: Graceful Shutdown

**Current state:** Server stops abruptly.  
**Target:** Implement graceful shutdown:
1. Stop accepting new requests
2. Wait for in-flight tool calls to complete (with timeout)
3. Flush metrics
4. Close P2P connections

**Effort:** 2-3h

---

## 9. Success Metrics

| Metric | Current | Phase A Target | Phase B Target | Phase C Target |
|--------|---------|----------------|----------------|----------------|
| Tests passing | 853 | 853+ | 950+ | 970+ |
| Test coverage (core) | 85-90% | 85-90% | 88-93% | 88-93% |
| Test coverage (tools) | ~30-40% | ~30-40% | ~55-65% | ~55-65% |
| Root-level `.md` files | 8 | 8 | 8 | 8 |
| Stub/incomplete docs | 3 | 0 | 0 | 0 |
| `/health` endpoint | ❌ | ❌ | ❌ | ✅ |
| Benchmark suite | ❌ | ❌ | ❌ | ❌ → Phase E |
| Tool schema version | ❌ | ❌ | ❌ | ❌ → Phase D |

---

## 10. Timeline & Prioritisation

### Recommended Order

**Sprint 1 (1-2 days):** Phase A — Documentation  
Documentation gaps are visible to all users and contributors. High value, low risk.

**Sprint 2 (2-3 days):** Phase B — Testing depth  
Closes coverage gaps in tool files. Reduces regression risk for future changes.

**Sprint 3 (1-2 days):** Phase C — Observability  
Structured logging and health endpoints are essential for production deployment.

**Sprint 4 (1 day):** Phase D — API versioning  
Low effort but high long-term value for consumers.

**Sprint 5 (1-2 days):** Phase E — Benchmarking  
Prevent performance regressions as the codebase grows.

**Sprint 6 (2-4 days):** Phase F — Advanced runtime  
Parallel dispatch, circuit breaker, graceful shutdown — highest-complexity items.

### Summary Table

| Phase | Area | Effort | Priority | Sprint |
|-------|------|--------|----------|--------|
| A | Documentation Completion | 4-6h | 🔴 High | 1 |
| B | Testing Depth | 8-12h | 🔴 High | 2 |
| C | Observability & Diagnostics | 6-8h | 🟡 Medium | 3 |
| D | API Versioning & Stability | 4-6h | 🟡 Medium | 4 |
| E | Performance Benchmarking | 4-6h | 🟡 Medium | 5 |
| F | Advanced Runtime Features | 10-14h | 🟢 Low | 6 |
| **Total** | | **36-52h** | | |

---

## Architecture Principles (Unchanged from v4)

1. ✅ **Business logic in core modules** — tools never contain domain logic
2. ✅ **Tools are thin wrappers** — <150 lines per tool
3. ✅ **Third-party reusable** — core modules importable without MCP
4. ✅ **Nested for context window** — HierarchicalToolManager reduces exposure to 4 tools
5. ✅ **Custom exceptions** — 18 exception classes, adopted everywhere
6. ✅ **Lazy loading** — categories loaded on first access
7. ✅ **Schema caching** — `ToolCategory._schema_cache`
8. ✅ **Connection pooling** — `P2PServiceManager` reuses live connections
9. 🔜 **Structured tracing** — Phase C
10. 🔜 **Circuit breaker** — Phase F
11. 🔜 **Parallel dispatch** — Phase F

---

**Last Updated:** 2026-02-20  
**Supersedes:** None (v4 plan is complete — this is a new forward-looking document)  
**Related:** [MASTER_REFACTORING_PLAN_2026_v4.md](MASTER_REFACTORING_PLAN_2026_v4.md) · [PHASES_STATUS.md](PHASES_STATUS.md)

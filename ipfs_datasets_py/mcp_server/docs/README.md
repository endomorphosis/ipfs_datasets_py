# MCP Server Documentation

This directory contains reference documentation for the IPFS Datasets MCP Server.
For installation, quick-start, and tool-category summaries see the [main README](../README.md).

---

## How It Works (Overview)

Understanding a few core mechanisms will help you navigate the docs below.

### Request flow

```
AI client sends tool call
        │
        ▼  (stdio or HTTP)
server.py  →  HierarchicalToolManager.dispatch(category, tool, params)
        │
        ├─ 1. Lazy-import tools/<category>/__init__.py  (cached after first call)
        ├─ 2. Validate params via EnhancedParameterValidator
        ├─ 3. Route to runtime via RuntimeRouter
        │      ├─ FastAPI backend  →  asyncio (~380 general tools)
        │      └─ Trio backend     →  structured concurrency (~26 P2P tools)
        ├─ 4. Run DispatchPipeline gates:
        │      compliance → risk → delegation → policy → nl_ucan_gate
        └─ 5. Execute tool function  →  emit EventNode to EventDAG
```

### Key data flows

| Concern | Module | What it does |
|---|---|---|
| Tool registration | `tool_registry.py` | `ClaudeMCPTool` wraps each function; `execute()` runs it, `get_schema()` returns its JSON schema |
| Tool metadata | `tool_metadata.py` | `@tool_metadata(runtime="trio")` annotates each function; `ToolMetadataRegistry` stores the annotations |
| Dispatch | `hierarchical_tool_manager.py` | Resolves category → function, applies circuit breaker, calls `RuntimeRouter` |
| Runtime routing | `runtime_router.py` | `RuntimeRouter.dispatch()` routes based on `ToolMetadata.runtime`; records per-tool latency metrics |
| Pipeline gates | `dispatch_pipeline.py` | `PipelineStage` constants: `COMPLIANCE`, `RISK`, `DELEGATION`, `POLICY`, `NL_UCAN_GATE`; each returns `StageOutcome` |
| Authorization | `ucan_delegation.py` | `DelegationManager` stores UCAN tokens; `DelegationEvaluator.can_invoke()` validates capability chains |
| NL policies | `nl_ucan_policy.py` | `NLUCANPolicyCompiler.compile_batch()` turns natural-language rules into `PolicyObject` values |
| Provenance | `event_dag.py` | `EventDAG.append(EventNode(parents=[…]))` builds content-addressed lineage graph |
| Audit trail | `policy_audit_log.py` | `PolicyAuditLog.record()` / `.recent()` / `.export_jsonl()` — zero overhead when disabled |
| Observability | `monitoring.py` | `EnhancedMetricsCollector` — counters, gauges, histograms; Prometheus export via `prometheus_exporter.py` |
| Validation | `validators.py` | `EnhancedParameterValidator` — text length, model name patterns, CIDv0/CIDv1, collection names, URLs |
| Errors | `exceptions.py` | `MCPServerError` hierarchy: `ToolError`, `ValidationError`, `RuntimeRoutingError`, `P2PServiceError`, … |
| Lifecycle | `server_context.py` | `ServerContext` — owns tool manager, P2P services, scheduler; cleanup handlers run on exit |

---

## Directory Layout

```
docs/
├── api/
│   └── tool-reference.md            Complete parameter/return reference for all 51 categories
├── architecture/
│   ├── dual-runtime.md              FastAPI + Trio design; how RuntimeRouter works
│   ├── mcp-plus-plus-alignment.md   UCAN, event-DAG, P2P transport, compliance checker
│   ├── DUAL_RUNTIME_ARCHITECTURE.md Detailed component diagram and latency analysis
│   └── adr/                         Architecture Decision Records
│       ├── ADR-001-thin-wrapper-pattern.md
│       ├── ADR-002-dual-runtime.md
│       ├── ADR-003-hierarchical-tool-system.md
│       ├── ADR-004-engine-extraction-pattern.md
│       ├── ADR-005-v6-coverage-hardening.md
│       └── ADR-006-mcp++-alignment.md
├── guides/
│   ├── cookbook.md                  Ready-to-run recipes (parallel dispatch, batching, error handling)
│   ├── p2p-migration.md             Migrating to P2P-backed tools
│   ├── performance-tuning.md        Tuning connection pools, concurrency limits, caches
│   └── performance-profiling.md     Using built-in profiling hooks
├── development/
│   ├── tool-patterns.md             How to write a new tool (thin wrapper, @tool_metadata, __init__.py)
│   └── tool-templates/              Copy-paste boilerplate for function/class/stateful tools
├── testing/
│   └── DUAL_RUNTIME_TESTING_STRATEGY.md  Writing tests for both asyncio and Trio backends
└── history/                         Archived phase-completion reports (reference only)
```

---

## API Reference

**[api/tool-reference.md](./api/tool-reference.md)** — the primary reference for tool consumers.

Covers every tool in all 51 categories with:
- Function signatures and parameter types
- Return value shapes
- Usage examples
- Error conditions

---

## Architecture

### [architecture/dual-runtime.md](./architecture/dual-runtime.md)

Explains the FastAPI + Trio dual-runtime design:
- Why two runtimes are needed (`asyncio` vs Trio event-loop models are incompatible)
- How `RuntimeRouter` reads `@tool_metadata(runtime=…)` to route calls
- How `trio_bridge.py` runs Trio tasks from the asyncio side
- Latency targets: 50–70% reduction for P2P operations in the Trio runtime

### [architecture/mcp-plus-plus-alignment.md](./architecture/mcp-plus-plus-alignment.md)

Documents the MCP++ extension layer:
- **UCAN delegation** (`ucan_delegation.py`) — `DelegationToken`, `Capability`, `DelegationManager`, `MergeResult`
- **NL UCAN policy** (`nl_ucan_policy.py`) — `NLUCANPolicyCompiler`, CIDv1-addressed `PolicyObject`
- **Event DAG** (`event_dag.py`) — `EventNode`, `EventDAG`, topological walk, frontier computation
- **P2P transport** (`mcp_p2p_transport.py`) — `LengthPrefixFramer`, `PubSubBus`, protocol constants
- **Compliance checker** (`compliance_checker.py`) — rule engine, `ComplianceStatus`, backup management
- **Policy audit log** (`policy_audit_log.py`) — ring-buffer, JSONL export/import

### [architecture/adr/](./architecture/adr/)

Six Architecture Decision Records (ADRs) document the major design choices:

| ADR | Title | Decision summary |
|---|---|---|
| [ADR-001](./architecture/adr/ADR-001-thin-wrapper-pattern.md) | Thin Wrapper Pattern | Business logic in `*_engine.py`; tool files ≤ 30 lines |
| [ADR-002](./architecture/adr/ADR-002-dual-runtime.md) | Dual-Runtime Architecture | `anyio` compatibility shim; FastAPI + Trio runtimes |
| [ADR-003](./architecture/adr/ADR-003-hierarchical-tool-system.md) | Hierarchical Tool System | Two-level category/tool hierarchy with 4 meta-tools |
| [ADR-004](./architecture/adr/ADR-004-engine-extraction-pattern.md) | Engine Extraction Pattern | All domain logic extracted to reusable engine modules |
| [ADR-005](./architecture/adr/ADR-005-v6-coverage-hardening.md) | v6 Coverage Hardening | 85%+ coverage requirement; anyio-parameterised tests |
| [ADR-006](./architecture/adr/ADR-006-mcp++-alignment.md) | MCP++ Alignment | UCAN, event-DAG, P2P transport alignment with MCP++ spec |

---

## Guides

| Guide | What you will learn |
|---|---|
| [guides/cookbook.md](./guides/cookbook.md) | `dispatch_parallel()` with `max_concurrent`; streaming results; fail-fast vs collect-all error modes |
| [guides/p2p-migration.md](./guides/p2p-migration.md) | Step-by-step migration from direct IPFS Kit to P2P-backed tools via `P2PServiceManager` |
| [guides/performance-tuning.md](./guides/performance-tuning.md) | Tuning `RuntimeRouter` concurrency limits, connection pools, schema cache TTL |
| [guides/performance-profiling.md](./guides/performance-profiling.md) | Enabling `StageMetric` timing; reading `EnhancedMetricsCollector` histograms; Prometheus scrape endpoint |

---

## Development

### [development/tool-patterns.md](./development/tool-patterns.md)

The authoritative guide for adding a new tool. Covers:
- Choosing the right category directory
- Writing a thin-wrapper function (≤ 150 lines) that delegates to a `*_engine.py` module
- Using `@tool_metadata(runtime="fastapi")` or `@tool_metadata(runtime="trio")`
- Registering the function in the category `__init__.py` `__all__` list
- Writing the accompanying GIVEN-WHEN-THEN unit test

### [development/tool-templates/](./development/tool-templates/)

Boilerplate templates:
- **function-based** — single `async def`, FastAPI runtime
- **class-based** — stateful tool backed by an engine class
- **trio tool** — P2P tool using Trio structured concurrency

---

## Testing

### [testing/DUAL_RUNTIME_TESTING_STRATEGY.md](./testing/DUAL_RUNTIME_TESTING_STRATEGY.md)

Explains how to write tests that cover both async runtimes:
- Using `anyio.pytest_plugin` to parameterise tests over `asyncio` and `trio` backends
- Mock strategies for P2P dependencies when Trio is unavailable
- Circuit-breaker test patterns
- `StageMetric` assertion patterns for pipeline tests

---

## Related top-level documents

| Document | Description |
|---|---|
| [../README.md](../README.md) | Full feature overview, tool categories, architecture, configuration |
| [../QUICKSTART.md](../QUICKSTART.md) | Get the server running in 5 minutes |
| [../THIN_TOOL_ARCHITECTURE.md](../THIN_TOOL_ARCHITECTURE.md) | Thin-wrapper principles (expanded ADR-001) |
| [../SECURITY.md](../SECURITY.md) | Security posture, JWT configuration, input sanitisation |
| [../CHANGELOG.md](../CHANGELOG.md) | Version history |

# MCP server context and dispatch

| Field | Value |
| --- | --- |
| Interface | `MCPServerArchitecture@1` |
| Task | `IPFSDOC-050` |
| Status | `canonical` |
| Owner | architecture; mcp-server |
| Source of truth | `ipfs_datasets_py/mcp_server/server.py`; `server_context.py`; `hierarchical_tool_manager.py`; `dispatch_pipeline.py`; `fastapi_service.py`; `configs.py`; `mcplusplus/result_cache.py`; package ADR-003; [ADR-007-MCP-RUNTIME-COMPATIBILITY.md](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md); [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8; [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.3 |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator |
| Related | [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md); transports/interfaces (IPFSDOC-051); policy/ops (IPFSDOC-052+) |
| Review cadence | after server startup, registration, or dispatch-path changes |

## 1. Purpose

This guide answers: **how the canonical MCP server starts, what context it
holds, how the four hierarchical meta-tools expose discovery and execution, and
how dispatch, caches, circuit breakers, and optional pre-dispatch pipelines
behave.** Tool package layout, metadata, and naming rules live in
[TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md).

**Do not treat log-line or historical tool counts as inventory authority.**
Category and tool cardinality change with the tree; discover live via
`tools_list_categories` / `tools_list_tools` or disk enumeration under
`mcp_server/tools/`.

## 2. Audience

- **Primary:** developers adding or invoking tools; agents wiring MCP clients
- **Secondary:** operators starting stdio/HTTP servers; architects reviewing
  canonical vs compatibility paths

## 3. Scope and non-goals

### In scope

- Canonical process entry and `IPFSDatasetsMCPServer` lifecycle
- `ServerContext` resource ownership (when used)
- Hierarchical meta-tool surface and lazy category/tool discovery
- `HierarchicalToolManager.dispatch` result contract
- Schema cache, opt-in result cache, and `CircuitBreaker` infrastructure
- Optional `DispatchPipeline` (integrated MCP++ stages vs legacy stage list)
- Flat naming compatibility on FastAPI/MCP list surfaces
- Compatibility and degraded servers (what they are *not*)

### Non-goals

- Full transport matrix (stdio/HTTP/gRPC/P2P parity) — IPFSDOC-051
- UCAN/risk/temporal policy bodies — IPFSDOC-052+
- Exhaustive per-tool catalogs or undated tool counts
- Domain algorithm ownership (tools are thin wrappers; see DOMAIN_MAP)

## 4. Canonical vs compatibility (summary)

| Class | Surfaces | Role |
| --- | --- | --- |
| **Canonical** | `python -m ipfs_datasets_py.mcp_server`; `IPFSDatasetsMCPServer`; `start_stdio_server` / `start_server`; hierarchical meta-tools | Preferred for new work and contract tests |
| **Compat / degraded** | `simple_server.SimpleIPFSDatasetsMCPServer`; `mcp_server/compat/*`; import stubs when `mcp` is missing | Migration and reduced environments — **not** a second architecture |
| **Optional** | MCP++ policy/compliance meta-tools; P2P service; attached `DispatchPipeline` | Opt-in; absence must not redefine the base tool contract |

Binding product rule: [ADR-007-MCP-RUNTIME-COMPATIBILITY.md](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md).

---

## 5. Canonical server startup

### 5.1 Process entry

| Mode | How | What runs |
| --- | --- | --- |
| **Stdio (default)** | `python -m ipfs_datasets_py.mcp_server` or `--stdio` | `start_stdio_server()` → `IPFSDatasetsMCPServer.start_stdio` → FastMCP `run_stdio_async` |
| **HTTP** | `--http [--host] [--port]` | `start_server()` → prefer Hypercorn+Trio on `fastapi_service.app`; uvicorn fallback; else stdio |
| **Python API** | `from ipfs_datasets_py.mcp_server import start_server, start_stdio_server` | Same launchers |

Module entry: `mcp_server/__main__.py`. Full packaging map:
[RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8.

### 5.2 Construction sequence (`IPFSDatasetsMCPServer`)

```text
IPFSDatasetsMCPServer.__init__(configs?)
  ├── configs = server_configs or global configs
  ├── _initialize_error_reporting()     # optional GitHub error reporter
  ├── _initialize_mcp_server()          # FastMCP("ipfs_datasets") or stub
  ├── tools = {}                        # server-side name → callable map
  ├── _enable_extended_meta_tools=True  # policy/compliance tools when importable
  ├── _dispatch_pipeline = None         # opt-in via set_pipeline()
  ├── _initialize_p2p_services()        # optional P2PServiceManager
  ├── _initialize_policy_store()        # IPFS_POLICY_STORE_PATH if set
  └── _initialize_delegation_manager()  # optional UCAN delegation state
```

Notes:

- If the real `mcp` package is missing (or shadowed by `ipfs_kit_py`), import
  recovery tries once; otherwise a **fail-closed stub** is used so non-MCP
  unit paths can construct the class. Operations that need FastMCP raise when
  registration/run is attempted without a real backend.
- P2P, policy store, and delegation are **optional**; failures log and leave
  the subsystem unset rather than aborting construction.

### 5.3 Start sequence (`start_stdio` / `start`)

```text
start_stdio() / start(host, port)
  ├── await register_tools()
  │     ├── add 4 hierarchical meta-tools to FastMCP + self.tools
  │     └── optionally register MCP++ policy + compliance meta-tools
  ├── optional register_ipfs_kit_tools(...)
  ├── optional p2p.start(P2PMCPRegistryAdapter(self))
  ├── run transport (stdio or HTTP)
  └── finally: p2p.stop(); DelegationManager.save() if present
```

**Flat bulk registration is intentionally off** on the canonical path:
`register_tools` no longer walks every category directory to call
`mcp.add_tool` per function. Individual tools are discovered and imported
**lazily** through the hierarchical manager (see §7). Legacy helper
`_register_tools_from_subdir` remains for specialized/compat paths only.

### 5.4 `ServerContext` (resource lifecycle)

`server_context.ServerContext` is the **recommended** resource owner for
tests and new hosts that need an isolated, thread-safe context instead of the
deprecated global tool-manager singleton.

| Resource | When initialized | Role |
| --- | --- | --- |
| `ToolMetadataRegistry` | enter | Runtime/category/priority metadata |
| `HierarchicalToolManager` | enter | Category discovery and dispatch |
| P2P services | if `ServerConfig.enable_p2p` | Deferred/placeholder until host wires real manager |
| Workflow scheduler | deferred | Optional |
| Vector stores | on `register_vector_store` | Named store map |
| Cleanup handlers | on exit / cleanup | FIFO; exceptions logged, others continue |

`ServerConfig` flags relevant to discovery:

| Flag | Default | Meaning |
| --- | --- | --- |
| `cache_tool_discovery` | `True` | Prefer cached discovery results |
| `lazy_load_tools` | `True` | Do not import full tool surface at enter |
| `tool_timeout_seconds` | `30.0` | Default tool budget (metadata may override) |
| `max_concurrent_tools` | `10` | Concurrent execution budget for hosts that honor it |

`get_tool_manager(context=...)` returns the context’s manager when a
`ServerContext` is passed; without context it falls back to a **deprecated**
process-global `HierarchicalToolManager` for backward compatibility with
meta-tool wrappers.

---

## 6. What is registered at the protocol surface

### 6.1 Four hierarchical meta-tools (always)

These are the only tools required for full hierarchical capability:

| Meta-tool | Parameters | Behavior |
| --- | --- | --- |
| `tools_list_categories` | `include_count: bool = False` | List category names/descriptions; optional per-category counts (forces category tool discovery) |
| `tools_list_tools` | `category: str` | List tools in one category (lazy import of that category) |
| `tools_get_schema` | `category`, `tool` | Full parameter/return schema (schema cache after first build) |
| `tools_dispatch` | `category`, `tool`, `params?` | Execute tool; primary execution entry |

Wrappers live at the bottom of `hierarchical_tool_manager.py` and call
`get_tool_manager()` then the matching manager method.

### 6.2 Extended MCP++ meta-tools (optional)

When `_enable_extended_meta_tools` is true (default on full `__init__`),
registration **attempts** additional tools if importable:

| Group | Names (examples) |
| --- | --- |
| Policy management | `policy_register`, `policy_list`, `policy_remove`, `policy_evaluate`, `interface_register`, `interface_list` |
| Compliance rules | `compliance_add_rule`, `compliance_list_rules`, `compliance_remove_rule`, `compliance_check_intent`, `compliance_register_interface` |

Import failures are debug-logged; the server still starts with the four core
meta-tools.

### 6.3 What clients see on HTTP / tools list

`fastapi_service` builds descriptors from:

1. **Registered server tools** (`server.tools` — meta-tools and any extended
   tools actually registered).
2. **Flat hierarchical descriptors** — cheap disk enumeration of
   `<category>.<stem>` names **without importing** tool modules; real schemas
   remain lazy via `tools_get_schema`.

Flat call path: `_dispatch_hierarchical_flat_tool("category.tool", args)` →
`tools_dispatch(category=..., tool=..., params=args)`.

This dual advertisement exists so stock MCP explorers that only call
`tools/list` do not under-report the hierarchical surface. Naming rules:
[TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md) § flat vs
hierarchical.

---

## 7. Lazy discovery model

```text
Client
  │ tools_list_categories
  v
HierarchicalToolManager.discover_categories()
  └── scan tools_root/* directories (skip _*)
      └── optional category.json description
      └── ToolCategory shells (tools not imported yet)
  │
  │ tools_list_tools(category) / tools_get_schema / tools_dispatch
  v
ToolCategory.discover_tools()   # once per category
  └── import non-_ *.py modules
  └── collect public functions (prefer name matching module stem)
  │
  │ first get_tool_schema
  v
schema built via inspect.signature → _schema_cache
```

**Lazy category loaders:** `lazy_register_category(name, loader)` registers a
callable that materializes a `ToolCategory` on first `get_category`. Listings
mark such categories with `"lazy": true` until loaded. Use this for heavy
optional dependency categories so startup stays cheap.

**Category ownership:** a category is a directory under
`ipfs_datasets_py/mcp_server/tools/<category_name>/`. The manager does not
own domain algorithms; category directories own thin tool modules that
delegate to domain packages ([DOMAIN_MAP.md](../DOMAIN_MAP.md)).

---

## 8. Dispatch path

### 8.1 Happy path

```text
tools_dispatch(category, tool, params)
  → HierarchicalToolManager.dispatch
       ├── reject if shutting down
       ├── request_id = uuid4(); timer start
       ├── resolve category (lazy if needed)
       ├── resolve tool callable
       ├── deprecation warning if @tool_metadata(deprecated=True)
       ├── filter params to signature parameters
       ├── optional ResultCache get (if metadata.cache_ttl > 0)
       ├── await or call tool
       ├── normalize non-dict → {"status":"success","result": str(...)}
       ├── optional ResultCache put
       └── setdefault request_id; structured success log
```

### 8.2 Result envelope (hierarchical dispatch)

Successful and failed hierarchical dispatches return **plain dicts** (not
necessarily MCP `CallToolResult` until a transport wraps them).

| Field | When | Meaning |
| --- | --- | --- |
| `status` | success/error paths | `"success"` or `"error"` (tools may also use domain-specific keys) |
| `request_id` | almost always on dispatch | Correlation ID for logs |
| `error` | error | Human-readable failure |
| `available_categories` / `available_tools` | not found | Discovery hints |
| `category` / `tool` | many errors | Echo of address |
| `_cached` | cache hit | Result served from result cache |
| `trace` / `_trace` | `dispatch_with_trace` | CID execution envelope (Profile B) |

Transport wrapping examples:

| Layer | Shape |
| --- | --- |
| FastAPI MCP call helper | `content` text + `structuredContent` + `isError` |
| `tools/mcp_helpers` | `{"content":[{"type":"text","text":"<json>"}]}` for legacy tests |
| `utils/_return_tool_call_results` | MCP `CallToolResult(isError=..., content=[TextContent...])` |
| FastMCP stdio | Protocol-native tool result around registered callables |

**Invariant:** discovery listing a name does not guarantee capability success
(missing extras, optional backends, circuit open, policy deny). See
[SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) and ADR-005.

### 8.3 Parallel dispatch and shutdown

- `dispatch_parallel(calls, return_exceptions=True, max_concurrent=None)` —
  concurrent `dispatch` via anyio task groups; optional batching.
- `graceful_shutdown(timeout)` — sets `_shutting_down`, rejects new calls,
  clears categories and schema caches.

### 8.4 Optional pre-dispatch pipeline

`IPFSDatasetsMCPServer.set_pipeline(pipeline)` attaches a
`DispatchPipeline`. When attached, hosts that honor it run
`pipeline.check(intent)` **before** tool execution; deny returns an error dict
without calling the tool. Default is **no pipeline** (pass-through).

#### Integrated vs legacy modes

| Mode | Construction | Behavior |
| --- | --- | --- |
| **Legacy** | `DispatchPipeline()` or `DispatchPipeline(stages=[...])` | Ordered `PipelineStage` handlers; each returns `{"allowed": bool, ...}`; optional short-circuit on deny; metrics via `PipelineMetricsRecorder` |
| **Integrated (MCP++)** | `DispatchPipeline(config=PipelineConfig(...))` | Named stages driven by flags: compliance, risk, delegation, temporal policy, NL-UCAN gate; missing subsystems **skip with allow** (soft degrade) unless a stage hard-fails |

Stage constants: `COMPLIANCE`, `RISK`, `DELEGATION`, `POLICY`, `NL_UCAN_GATE`,
`PASS`. Integrated checks build `PipelineIntent` (stable intent CID from
tool/actor/params) and optional `DecisionObject` / event-DAG hooks via
`record_execution` / `attach_event_dag`.

Detailed authorization semantics: later policy architecture pages; do not
bypass an attached pipeline from new hosts.

### 8.5 Dual-runtime routing (related)

`runtime_router.RuntimeRouter` can route callables to FastAPI/anyio vs Trio
based on `ToolMetadata.runtime` / `requires_p2p`. Hierarchical
`dispatch` itself invokes the callable in-process; hosts that need Trio
nurseries should compose the router around tool functions. See package
ADR-002 and IPFSDOC-051 for transport/runtime binding.

---

## 9. Schema cache, result cache, circuit breaker

### 9.1 Schema cache (per category)

`ToolCategory._schema_cache` memoizes the dict from `get_tool_schema`:

- First call: `inspect.signature`, type annotations, defaults, docstring metadata.
- Later calls: O(1) hit; counters via `cache_info()` (`hits`, `misses`, `size`).
- `clear_schema_cache()` after tool reload.

### 9.2 Result cache (opt-in per tool)

`HierarchicalToolManager` lazily creates
`mcplusplus.result_cache.ResultCache` over `MemoryCacheBackend` (default max
512 entries, LRU, default TTL 300s for the backend).

Caching is **off unless** the tool’s `ToolMetadata.cache_ttl` is a positive
float. Cache key is hierarchical tool path + filtered params. Failures on get/put
are non-fatal. Hits set `_cached: true`.

### 9.3 Circuit breaker

`CircuitBreaker` / `CircuitState` implement CLOSED → OPEN → HALF_OPEN with
configurable `failure_threshold` and `recovery_timeout`. While OPEN, `call`
returns an error dict with `circuit_state` without invoking the tool.

**Current wiring:** the class is exported infrastructure (and documented in
package ADR-003). Canonical `dispatch` does **not** automatically wrap every
tool in a breaker; hosts or category adapters may apply breakers where repeated
failure must fail fast. Do not document automatic per-call breaker behavior
that the tree does not implement.

---

## 10. Unavailable tools and failures

| Situation | Typical response |
| --- | --- |
| Unknown category | `status=error`, `available_categories` |
| Unknown tool in category | `status=error`, `available_tools` |
| Invalid parameters | `status=error`, `Invalid parameters: ...` |
| Tool raises | `status=error`, stringified exception + request_id |
| Server shutting down | `status=error`, no new calls |
| Optional import failure at discovery | Category/file skipped; warning log; not a process crash |
| Optional MCP package missing | Registration/run fail closed; stub may exist for tests |
| Pipeline deny | Error without tool execution (when pipeline attached) |
| Domain backend missing | Tool-level error envelope (e.g. “engine unavailable”) — discovery may still list the name |

**Unavailable ≠ unregistered.** A listed hierarchical name means a module stem
or discovered function exists; runtime extras may still be absent.

---

## 11. Duplicates, aliases, and flat names

| Concern | Rule |
| --- | --- |
| Hierarchical address | Canonical: `(category, tool)` via meta-tools |
| Flat alias (HTTP list) | `category.tool` → same dispatch; not a second registry |
| Class-style `ToolRegistry` / `MCPToolRegistry` | Compat / migration object model; do not invent parallel inventories for new tools |
| Global `get_tool_manager()` singleton | Deprecated vs `ServerContext` |
| `simple_server` / Flask HTTP | Deprecated; prefer stdio MCP or FastAPI |
| Re-exports under `tools/validators.py` | Alias to `mcp_server.validators` for import path compatibility |
| Same function name in two categories | Distinct hierarchical addresses; flat names differ by category prefix |

Eliminating **duplicate FastMCP registrations** was a deliberate goal of
hierarchical-only protocol registration: one meta-tool set, many lazy tools.

---

## 12. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| MCP protocol host, tool registration, hierarchical discovery/dispatch | Domain algorithms (`processors`, `logic`, `vector_stores`, …) |
| Server config, optional pipeline attach point, result/schema caches | Product-wide processor plugin registry |
| Fail-closed behavior when MCP dependency missing | Agent-supervisor leases / external orchestrators |

**Inbound:** MCP clients, CLI dynamic tool runner (same tools tree), FastAPI
MCP routes, optional P2P adapter.

**Outbound:** Tool modules → domain packages; optional IPFS kit MCP URL; policy
stores; P2P peers.

---

## 13. Extension checklist (server/dispatch)

1. Prefer hierarchical meta-tools; do not re-enable bulk `add_tool` for every
   function on the canonical server without an explicit product decision.
2. Put new tools under the correct category directory (lifecycle guide).
3. Use `ServerContext` in new hosts/tests instead of the global manager.
4. Attach `DispatchPipeline` only when policy stages are required; document
   fail-open vs fail-closed per stage configuration.
5. For HTTP discovery completeness, rely on flat descriptor enumeration rather
   than importing all modules at list time.
6. Never document static undated tool counts as authority.

---

## 14. Validation

```bash
# Guides present and non-empty
test -s docs/architecture/mcp/SERVER_AND_DISPATCH.md
test -s docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md

# Keyword coverage for this program leaf
rg -n 'meta-tool|lazy|hierarch|schema|cache|circuit|dispatch|compat' \
  docs/architecture/mcp/SERVER_AND_DISPATCH.md \
  docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md

# Live discovery (optional; requires package install)
python -c "from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager; m=HierarchicalToolManager(); m.discover_categories(); print(sorted(m.categories)[:5], '...', len(m.categories))"
```

---

## 15. Related documents

| Document | Relationship |
| --- | --- |
| [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md) | Tool tree, metadata, naming, validation |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | Packaging and CLI/MCP entry surfaces |
| [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | Canonical vs compatibility runtimes |
| [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | Registry/adapter product rule |
| Package ADR-003 | Hierarchical tool system decision body |
| IPFSDOC-051 (planned) | Interfaces, identity, transports |
| IPFSDOC-052+ (planned) | Policy, audit, observability, runbook |

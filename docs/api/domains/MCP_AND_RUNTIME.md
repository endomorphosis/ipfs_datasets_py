# MCP and runtime API domain reference

| Field | Value |
| --- | --- |
| Interface | `MCPRuntimeAPIReference@1` |
| Task | `IPFSDOC-081` |
| Status | `canonical` |
| Owner | api-reference / mcp-runtime |
| Source of truth | `ipfs_datasets_py/mcp_server/` (`__init__.py`, `server.py`, `client.py`, `simple_server.py`, `hierarchical_tool_manager.py`, `tool_registry.py`, `tool_metadata.py`, `tools/tool_wrapper.py`, `mcp_interfaces.py`, `interface_descriptor.py`, `dispatch_pipeline.py`, `server_context.py`, `runtime_router.py`, `configs.py`, transports); architecture leaves under `docs/architecture/mcp/`; [RUNTIME_ENTRYPOINTS.md](../../architecture/RUNTIME_ENTRYPOINTS.md); [ADR-007](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) |
| Last verified | 2026-08-03 |
| Audience | developer, agent, operator, security reviewer |
| Related | [KNOWLEDGE_LOGIC_AND_PROOF.md](KNOWLEDGE_LOGIC_AND_PROOF.md), [OPERATIONS_AND_INTEGRATIONS.md](OPERATIONS_AND_INTEGRATIONS.md), [CORE_AND_DATA.md](CORE_AND_DATA.md), [mcp/README.md](../../architecture/mcp/README.md), [DOMAIN_MAP.md](../../architecture/DOMAIN_MAP.md) |
| Review cadence | after server, transport, policy pipeline, tool-tree, or interface CID changes |

## 1. Purpose

This page maps **callable** MCP server, tool, interface, client, and runtime
router surfaces with provenance:

1. **Process entry** — stdio / HTTP start helpers and package exports.
2. **Server lifecycle** — `IPFSDatasetsMCPServer`, `ServerContext`, tool
   registration.
3. **Tool discovery and dispatch** — hierarchical manager, class-style
   `ToolRegistry`, wrappers, metadata.
4. **Interfaces and transports** — protocol types, interface CIDs, runtime
   router, optional carriers.
5. **Policy pipeline** — optional `DispatchPipeline` stages (not domain
   engines).
6. **Client** — `IPFSDatasetsMCPClient` convenience methods.

Importability is **not** public stability. Discovery of a tool name ≠ optional
backend present ≠ policy allow ≠ successful domain execution. Compatibility /
simple / legacy servers are labeled explicitly.

## 2. Authority legend

| Tag | Meaning |
| --- | --- |
| **Stability: public** | Preferred external product contract |
| **Stability: reviewed** | Exported / exercised; AST is authority |
| **Stability: compatibility** | Alias, simple/legacy server, flat name projection |
| **Stability: internal** | Implementation detail |
| **Optional** | MCP SDK, FastAPI, gRPC, P2P, ipfs_kit URL, policy stages |
| **Side effects** | Bind ports, load tools, network, audit/metrics attach |

**Core inequalities:**

- green `/health` **≠** policy allow **≠** tool executed successfully
- hierarchical category.tool **≠** a second domain engine
- flat `category.tool` alias **≠** a second registry
- interface **CID** / schema **≠** authorization
- `SimpleIPFSDatasetsMCPServer` **≠** canonical architecture

---

## 3. Package exports

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server import …` |
| **Source** | `ipfs_datasets_py/mcp_server/__init__.py` |
| **Stability** | reviewed symbols; import may **degrade** without MCP deps |

```python
__all__ = [
    "start_server",
    "start_stdio_server",
    "IPFSDatasetsMCPServer",
    "SimpleIPFSDatasetsMCPServer",
    "IPFSDatasetsMCPClient",
    "Configs",
    "configs",
    "load_config_from_yaml",
    "mcplusplus",
]
```

| Symbol | Notes |
| --- | --- |
| `start_server` / `start_stdio_server` / `IPFSDatasetsMCPServer` | Preferred path when `server.py` imports; else may fall back |
| `SimpleIPFSDatasetsMCPServer` / simple fallback | **Compatibility** — reduced surface |
| `IPFSDatasetsMCPClient` | **None** if MCP client deps missing |
| `Configs`, `configs`, `load_config_from_yaml` | Always importable config helpers |
| `mcplusplus` | **Optional** integration package; import failure soft-fails to `None` |

**Optional dependency:** `anyio`, `mcp` / modelcontextprotocol, optionally
`flask` for simple path. Missing deps raise `ImportError` from placeholder
`start_server` with install guidance.

---

## 4. Process entrypoints

### 4.1 Module and functions

| Entry | Signature (AST) | Stability | Side effects |
| --- | --- | --- | --- |
| Package module | `python -m ipfs_datasets_py.mcp_server` | public | starts configured server |
| `start_stdio_server` | `def start_stdio_server(ipfs_kit_mcp_url: Optional[str] = None) -> None` | public | stdio MCP loop; optional kit URL |
| `start_server` | `def start_server(host: str = "0.0.0.0", port: int = 8000, ipfs_kit_mcp_url: Optional[str] = None) -> None` | public | bind HTTP host/port |
| `start_simple_server` | `simple_server.start_simple_server` | **compatibility** | reduced server |
| `main` | `server.main()` argparse driver | reviewed CLI | same as start helpers |

```python
from ipfs_datasets_py.mcp_server import start_server, start_stdio_server

start_stdio_server()
# or
start_server(host="127.0.0.1", port=8000)
```

Architecture: [SERVER_AND_DISPATCH.md](../../architecture/mcp/SERVER_AND_DISPATCH.md),
[RUNTIME_ENTRYPOINTS.md](../../architecture/RUNTIME_ENTRYPOINTS.md).

---

## 5. IPFSDatasetsMCPServer

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPServer` |
| **Source** | `ipfs_datasets_py/mcp_server/server.py` |
| **Stability** | public / reviewed |
| **Optional** | ipfs_kit MCP URL; dispatch pipeline; P2P validation |
| **Side effects** | tool import from disk; network listen; optional kit registration |

#### Signatures (AST)

```python
class IPFSDatasetsMCPServer:
    def __init__(self, server_configs=None) -> None
    def set_pipeline(self, pipeline) -> None
    def get_pipeline(self) ...
    def get_server_delegation_manager(self) ...
    def revoke_delegation_chain(self, root_cid) ...
    async def validate_p2p_message(self, msg) ...
    async def register_tools(self) -> None
    async def register_ipfs_kit_tools(self, ipfs_kit_mcp_url: Optional[str] = None) -> None
    async def start_stdio(self) -> None
    async def start(self, host: str = ..., port: int = ...) -> None
```

Module helpers:

```python
def return_text_content(input: Any, result_str: str) -> TextContent
def return_tool_call_results(content: TextContent, error: bool = False) -> CallToolResult
def import_tools_from_directory(directory_path: Path) -> Dict[str, Any]
```

```python
server = IPFSDatasetsMCPServer()
await server.register_tools()
await server.register_ipfs_kit_tools()  # optional
await server.start(host="127.0.0.1", port=8000)
```

**Result authority:** MCP `CallToolResult` / text content wrap **tool**
outcomes. Domain success remains the domain envelope (`status`, proof kinds,
wallet grants). Pipeline deny is **not** a domain success.

---

## 6. ServerContext

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.server_context import ServerContext, create_server_context, get_current_context, set_current_context` |
| **Source** | `mcp_server/server_context.py` |
| **Stability** | reviewed |
| **Side effects** | initializes tool manager / metadata registry; optional P2P and workflow scheduler |

#### Signatures (AST summary)

```python
class ServerContext:
    def __init__(self, config: Optional[ServerConfig] = None) -> None
    def __enter__(self) -> ServerContext
    def __exit__(self, exc_type, exc_val, exc_tb) -> None
    def register_cleanup_handler(self, handler: Callable) -> None
    @property
    def tool_manager(self) -> Any
    @property
    def metadata_registry(self) -> Any
    @property
    def p2p_services(self) -> Optional[Any]
    @property
    def workflow_scheduler(self) -> Optional[Any]
    def get_vector_store(self, name: str) -> Optional[Any]
    def register_vector_store(self, name: str, store: Any) -> None
    def list_tools(self) -> List[str]
    def get_tool(self, tool_name: str) -> Optional[Callable]
    def execute_tool(self, tool_name: str, **kwargs) -> Any

def create_server_context(config: Optional[ServerConfig] = None) -> ServerContext
def set_current_context(context: Optional[ServerContext]) -> None
def get_current_context() -> Optional[ServerContext]
```

Context is the **process-local** handle for tools and optional services. It is
not a global capability grant.

---

## 7. Tools: hierarchical manager (canonical discovery)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import HierarchicalToolManager, get_tool_manager, tools_list_categories, tools_list_tools, tools_get_schema, tools_dispatch` |
| **Source** | `mcp_server/hierarchical_tool_manager.py` |
| **Stability** | public for meta-tools and manager |
| **Side effects** | disk discovery under `mcp_server/tools/`; tool execution side effects of domain |

### 7.1 Tool tree layout

Tools live under `ipfs_datasets_py/mcp_server/tools/` as **category
directories** (non-exhaustive): `dataset_tools`, `ipfs_tools`, `logic_tools`,
`embedding_tools`, `vector` / storage / search groups, `wallet_tools`,
`audit_tools`, `admin_tools`, `pdf_tools`, `legal_dataset_tools`,
`background_task_tools`, `mcplusplus_*`, `p2p_tools`, … plus helpers
`tool_wrapper.py`, `tool_registration.py`.

**Live inventory authority:** hierarchical discovery or disk enumeration —
**not** undated marketing catalogs. Architecture:
[TOOL_LIFECYCLE_AND_REGISTRIES.md](../../architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md).

### 7.2 HierarchicalToolManager signatures (AST)

```python
class HierarchicalToolManager:
    def __init__(self, tools_root=None)
    def discover_categories(self) ...
    def lazy_register_category(self, name, loader) ...
    def get_category(self, name) ...
    async def list_categories(self, include_count: bool = ...) -> ...
    async def list_tools(self, category: str) -> ...
    async def get_tool_schema(self, category: str, tool: str) -> ...
    async def get_tool_schema_cid(self, category: str, tool: str) -> ...
    async def dispatch(
        self, category: str, tool: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]
    async def dispatch_with_trace(
        self, category: str, tool: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]
    async def dispatch_parallel(self, calls) -> ...
    async def graceful_shutdown(self, timeout=...) -> None

def get_tool_manager(context=None) -> HierarchicalToolManager

async def tools_list_categories(include_count: bool = ...) -> ...
async def tools_list_tools(category: str) -> ...
async def tools_get_schema(category: str, tool: str) -> ...
async def tools_dispatch(
    category: str, tool: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]
```

Supporting types: `ToolCategory` (per-directory discovery), `CircuitBreaker` /
`CircuitState` (failure isolation around dispatch).

**Dispatch result authority:** dict envelope from the tool wrapper / domain
call. Trace variants add pipeline/timing metadata — they do not upgrade proof
or grant authority.

### 7.3 Tool wrappers

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.tools.tool_wrapper import EnhancedBaseMCPTool, FunctionToolWrapper, wrap_function_as_tool, wrap_function_with_metadata, wrap_tools_from_module` |
| **Source** | `mcp_server/tools/tool_wrapper.py` |
| **Stability** | reviewed |

```python
class EnhancedBaseMCPTool:
    async def execute(self, parameters) ...
    def get_schema(self) ...
    async def validate_parameters(self, ...) ...
    async def call(self, ...) ...
    def get_performance_stats(self) ...
    def enable_caching / disable_caching / clear_cache(...)

class FunctionToolWrapper(EnhancedBaseMCPTool):
    async def execute(self, parameters) ...

def wrap_function_as_tool(...)
def wrap_function_with_metadata(...)
def wrap_tools_from_module(...)
```

Also: `tool_registry.ClaudeMCPTool` ABC with `async execute`, `get_schema`,
`async run` — used by class-style registry paths.

### 7.4 Class-style ToolRegistry (compatibility path)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.tool_registry import ToolRegistry, initialize_laion_tools` |
| **Source** | `mcp_server/tool_registry.py` |
| **Stability** | **compatibility** / product-specific (LAION-style groups) relative to hierarchical tree |
| **Side effects** | registers and executes tools; may attach embedding service |

```python
class ToolRegistry:
    def register_tool(self, tool) ...
    def unregister_tool(self, tool_name) ...
    def get_tool / has_tool / get_all_tools / list_tools(...)
    def get_tools_by_category / get_tools_by_tag(...)
    def get_categories / get_tags(...)
    async def execute_tool(self, tool_name, parameters) ...
    def get_tool_statistics / search_tools / validate_tool_parameters(...)

def initialize_laion_tools(
    registry: Optional[ToolRegistry] = None,
    embedding_service: Optional[Any] = None,
) -> Optional[List[Any]]
```

Internal `_register_*_tools` helpers wire embedding, search, analysis, storage,
auth, admin, cache, monitoring, background tasks, rate limiting, IPFS cluster,
sessions, vector stores, workflows, etc. Prefer hierarchical meta-tools for
canonical discovery; treat this registry as a **parallel registration style**,
not a second source of domain truth.

### 7.5 Tool metadata

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.tool_metadata import ToolMetadata, ToolMetadataRegistry, tool_metadata, get_registry, get_tool_metadata, RUNTIME_FASTAPI, RUNTIME_TRIO, RUNTIME_AUTO` |
| **Source** | `mcp_server/tool_metadata.py` |
| **Stability** | reviewed |

```python
@tool_metadata(
    runtime=..., requires_p2p=..., category=..., priority=...,
    timeout_seconds=..., retry_policy=..., memory_intensive=...,
    cpu_intensive=..., io_intensive=..., mcp_schema=...,
    mcp_description=..., cache_ttl=..., schema_version=...,
    deprecated=..., deprecation_message=...,
)
def my_tool(...): ...

class ToolMetadataRegistry:
    def register / get / list_by_runtime / list_by_category / list_all(...)
    def get_statistics / clear(...)
```

Metadata drives runtime routing and deprecation labels. It does **not**
authorize execution.

---

## 8. Interfaces and transports

### 8.1 Protocol types

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.mcp_interfaces import MCPServerProtocol, ToolManagerProtocol, MCPClientProtocol, P2PServiceProtocol, check_protocol_implementation` |
| **Source** | `mcp_server/mcp_interfaces.py` |
| **Stability** | reviewed contracts |

```python
class MCPServerProtocol(Protocol):
    def validate_p2p_token(self, token) ...

class ToolManagerProtocol(Protocol):
    def list_categories(self) ...
    def list_tools(self, category) ...
    def get_schema(self, tool_name) ...
    def dispatch(self, tool_name) ...

class MCPClientProtocol(Protocol):
    def add_tool(self, func, name, description) ...
    def list_tools(self) ...

class P2PServiceProtocol(Protocol):
    def start / stop / is_running(self) ...
    def register_tool(self, name, func) ...

def check_protocol_implementation(obj, protocol, strict=...) -> ...
```

### 8.2 Interface descriptor / CID (Profile A)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceDescriptor, InterfaceRepository, compute_cid, check_compat, get_interface_repository, toolset_slice` |
| **Source** | `mcp_server/interface_descriptor.py` |
| **Stability** | reviewed |
| **Side effects** | pure CID/compat computation unless repository persists |

```python
class InterfaceDescriptor:
    def canonical_bytes(self) ...
    def interface_cid(self) ...
    def to_dict(self) ...
    @classmethod
    def from_dict(cls, data) ...

class InterfaceRepository:
    def register / list / get / compat / check_compat / select / toolset_slice(...)

def compute_cid(content) ...
def check_compat(candidate, required) ...
def get_interface_repository() ...
```

Interface CIDs identify **schemas/capability slices**, not execution rights.

Architecture: [INTERFACES_AND_TRANSPORTS.md](../../architecture/mcp/INTERFACES_AND_TRANSPORTS.md).

### 8.3 Runtime router

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.runtime_router import RuntimeRouter, create_router, RuntimeMetrics` |
| **Source** | `mcp_server/runtime_router.py` |
| **Stability** | reviewed |
| **Optional** | Trio/AnyIO/FastAPI runtime availability |

```python
class RuntimeRouter:
    def __init__(self, default_runtime=..., enable_metrics=..., ...)
    async def startup / shutdown(self) ...
    def detect_runtime(self, tool_name, tool_func) ...
    def register_tool_runtime(self, tool_name, runtime) ...
    async def route_tool_call(self, tool_name, tool_func) ...
    def get_metrics / get_runtime_stats / reset_metrics(...)
    def bulk_register_tools_from_metadata(self) ...
    async def runtime_context(self) ...

async def create_router(default_runtime=..., enable_metrics=...) -> RuntimeRouter
```

Runtime choice is **scheduling**, not authorization.

### 8.4 Transport carriers (availability)

| Carrier | Primary modules | Stability |
| --- | --- | --- |
| stdio MCP | `server.start_stdio` / `start_stdio_server` | public |
| HTTP / FastAPI | `server.start`, `fastapi_service`, `enterprise_api` | public / reviewed |
| gRPC | `grpc_transport` | **optional** |
| Trio / AnyIO adapters | `trio_adapter`, `trio_bridge` | reviewed helpers |
| P2P / libp2p / MCP++ | `p2p_*`, `mcplusplus`, `mcp_p2p_transport` | **optional** |
| Simple / standalone | `simple_server`, `standalone_server` | **compatibility** |

Degraded transport ≠ missing tool domain.

---

## 9. Dispatch pipeline (optional policy stages)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline, PipelineStage, make_default_pipeline, make_full_pipeline, make_delegation_stage, PipelineIntent, PipelineResult` |
| **Source** | `mcp_server/dispatch_pipeline.py` |
| **Stability** | reviewed when attached; **optional** by default on many paths |
| **Side effects** | metrics/audit recording; stage handlers may call external policy |

#### Stages (named constants)

```text
PipelineStage.COMPLIANCE
PipelineStage.RISK
PipelineStage.DELEGATION
PipelineStage.POLICY
PipelineStage.NL_UCAN_GATE
PipelineStage.PASS
```

```python
def make_default_pipeline(
    metrics_recorder: Optional[PipelineMetricsRecorder] = None,
) -> DispatchPipeline

def make_full_pipeline(
    metrics_recorder: Optional[PipelineMetricsRecorder] = None,
) -> DispatchPipeline

class DispatchPipeline:
    def add_stage(self, stage: PipelineStage) -> None
    def get_stage(self, name: str) -> Optional[PipelineStage]
    # check_and_record / run path yields PipelineResult with verdict,
    # stage_outcomes, blocking_stage
```

Attach via `IPFSDatasetsMCPServer.set_pipeline(pipeline)`.

**Result authority:**

| Pipeline outcome | Means | Does not mean |
| --- | --- | --- |
| allow / pass | stages did not block | domain succeeded |
| deny / soft-skip | policy refused or skipped | proof of harm or safety |
| stage error | handler failure | tool result |

Architecture: [POLICY_AND_AUTHORIZATION.md](../../architecture/mcp/POLICY_AND_AUTHORIZATION.md).
Logic-layer gates (`logic.admissibility`) are **separate** — compose explicitly;
do not assume MCP pipeline alone equals governed intent authorization.

---

## 10. Client

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server import IPFSDatasetsMCPClient` |
| **Source** | `mcp_server/client.py` |
| **Stability** | reviewed when MCP deps present; may be `None` at package import |
| **Side effects** | network calls to server |

#### Signatures (AST)

```python
class IPFSDatasetsMCPClient:
    def __init__(self, server_url: str) -> None
    async def get_available_tools(self) -> ...
    async def call_tool(
        self, tool_name: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]
    async def load_dataset(self, source, format=None, options=None) -> Dict[str, Any]
    async def save_dataset(self, dataset_id, destination, format=None, options=None) -> Dict[str, Any]
    async def process_dataset(self, dataset_id, operations, output_id=None) -> Dict[str, Any]
    async def convert_dataset_format(self, dataset_id, target_format, output_path=None) -> Dict[str, Any]
    async def pin_to_ipfs(self, content_path, recursive=True) -> Dict[str, Any]
    async def get_from_ipfs(self, cid, output_path=None) -> Dict[str, Any]
    async def create_vector_index(self, vectors, dimension=None, metric="cosine", metadata=None) -> Dict[str, Any]
    async def search_vector_index(self, index_id, query_vector, top_k=10) -> Dict[str, Any]
```

Convenience methods are **thin client projections** over named tools. Treat
returned dicts as remote tool envelopes; verify domain `status` and never
infer success from transport 200 alone.

```python
client = IPFSDatasetsMCPClient("http://localhost:8000")
tools = await client.get_available_tools()
result = await client.load_dataset("/path/to/data.json")
```

---

## 11. Config surface (MCP-local)

| Field | Value |
| --- | --- |
| **Canonical import** | `from ipfs_datasets_py.mcp_server import Configs, configs, load_config_from_yaml` |
| **Source** | `mcp_server/configs.py` |
| **Stability** | reviewed |

```python
def load_config_from_yaml(config_path: Optional[str] = None) -> ...

class Configs:
    @property
    def ROOT_DIR / PROJECT_NAME / CONFIG_DIR ...
```

Global product config lives under `ipfs_datasets_py.config` /
`ipfs_datasets_py.config.py` — see
[OPERATIONS_AND_INTEGRATIONS.md](OPERATIONS_AND_INTEGRATIONS.md). MCP `Configs`
is server-local pathing.

---

## 12. Compatibility and non-canonical surfaces

| Surface | Label | Notes |
| --- | --- | --- |
| `SimpleIPFSDatasetsMCPServer` / `start_simple_server` | compatibility | Reduced tool host; not architecture SoT |
| `standalone_server` / legacy Flask paths | compatibility / legacy | Operator-only if still present |
| Class `ToolRegistry` + LAION initializers | compatibility style | Parallel to hierarchical tree |
| Package import fallbacks when MCP missing | degrade | Placeholders raise clear ImportError |
| Static tool catalogs in old docs | non-authority | Discover live via manager |

ADR: [ADR-007-MCP-RUNTIME-COMPATIBILITY.md](../../architecture/decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md).

---

## 13. Observability hooks (API pointers)

MCP observability modules (not full ops domain):

| Module | Role |
| --- | --- |
| `event_dag` / `event_dag_zkp` | event / receipt DAG |
| `metrics`, `prometheus_exporter`, `otel_tracing` | metrics / traces |
| `audit_metrics_bridge`, `policy_audit_log` | audit correlation |
| FastAPI `/health` routes (service modules) | liveness / readiness |

**Non-substitution:** health and metrics presence ≠ compliance proof ≠ UCAN
capability. Full contracts:
[AUDIT_EVENTS_AND_OBSERVABILITY.md](../../architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md).
Product audit/wallet APIs:
[OPERATIONS_AND_INTEGRATIONS.md](OPERATIONS_AND_INTEGRATIONS.md).

---

## 14. Canonical import cheat sheet

| Intent | Canonical import | Stability |
| --- | --- | --- |
| Start HTTP server | `mcp_server.start_server` | public |
| Start stdio server | `mcp_server.start_stdio_server` | public |
| Programmatic server | `mcp_server.IPFSDatasetsMCPServer` | public |
| Process context | `mcp_server.server_context.ServerContext` | reviewed |
| List/dispatch tools | `hierarchical_tool_manager.tools_*` / `HierarchicalToolManager` | public |
| Wrap functions | `tools.tool_wrapper.wrap_function_as_tool` | reviewed |
| Tool metadata | `tool_metadata.tool_metadata` | reviewed |
| Class registry | `tool_registry.ToolRegistry` | compatibility style |
| Protocols | `mcp_interfaces.*Protocol` | reviewed |
| Interface CID | `interface_descriptor.InterfaceDescriptor` | reviewed |
| Runtime route | `runtime_router.RuntimeRouter` | reviewed |
| Policy pipeline | `dispatch_pipeline.make_default_pipeline` | reviewed / optional attach |
| Client | `mcp_server.IPFSDatasetsMCPClient` | reviewed / optional deps |
| Simple server | `SimpleIPFSDatasetsMCPServer` | compatibility |

---

## 15. Side-effect and optional summary

| Surface | Side effects | Optional |
| --- | --- | --- |
| `start_server` | bind port, load tools | FastAPI stack |
| `start_stdio_server` | stdio protocol loop | MCP SDK |
| `register_tools` | import tool modules | per-tool backends |
| `register_ipfs_kit_tools` | network to kit MCP | kit URL |
| `dispatch` | domain I/O of tool | backends, models |
| Pipeline | metrics/audit writes | stage providers |
| P2P / MCP++ | peer network | libp2p extras |
| Client | HTTP/MCP network | server up |

---

## 16. Discrepancies and deferred items

| Item | Disposition |
| --- | --- |
| Hierarchical vs class registry | Both present; hierarchical is discovery SoT |
| Exhaustive tool name list | Intentionally omitted — discover live |
| Simple/standalone servers | Compatibility only |
| Package `IPFSDatasetsMCPServer is None` when deps missing | Documented degrade path |
| Logic admissibility vs MCP pipeline | Separate layers; compose explicitly |
| Profile G MCP service modules | Runtime boundary; see architecture runtime leaves |

---

## 17. Validation evidence for this page

- Package `__all__` and guarded imports from `mcp_server/__init__.py`.
- Server, client, hierarchical manager, tool registry, metadata, interfaces,
  interface descriptor, dispatch pipeline, runtime router, and server context
  signatures from module AST (2026-08-03).
- Tool tree categories enumerated from `mcp_server/tools/` directory listing.
- Cross-linked to architecture MCP leaves (IPFSDOC-050–053) and ADR-007.

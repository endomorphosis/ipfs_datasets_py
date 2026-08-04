# MCP interfaces, content identity, transports, and runtime routing

| Field | Value |
| --- | --- |
| Interface | `MCPInterfaceTransportArchitecture@1` |
| Task | `IPFSDOC-051` |
| Status | `canonical` |
| Owner | architecture; mcp-server |
| Source of truth | `ipfs_datasets_py/mcp_server/interface_descriptor.py`; `mcp_interfaces.py`; `cid_artifacts.py`; `server.py`; `fastapi_service.py`; `grpc_transport.py`; `mcp_p2p_transport.py`; `p2p_libp2p_transport.py`; `p2p_service_manager.py`; `p2p_mcp_registry_adapter.py`; `service_registry.py`; `mcplusplus/`; `runtime_router.py`; `trio_bridge.py`; `trio_adapter.py`; `tool_metadata.py`; `profile_g_service.py`; package ADRs 002/006; [ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md); [ADR-004-FAIL-CLOSED-DEGRADATION.md](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md); [ADR-007-MCP-RUNTIME-COMPATIBILITY.md](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md); [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md); [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md); [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8 |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator |
| Related | [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md); [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md); policy/ops (IPFSDOC-052+) |
| Review cadence | after transport adapters, Profile G service, dual-runtime, or interface-CID changes |

## 1. Purpose

This guide answers: **how transport-neutral tool and interface contracts and
content identity relate to concrete hosts (stdio, HTTP/FastAPI, gRPC, Trio/AnyIO,
MCP++/libp2p), how runtime routing selects concurrency backends, where Profile G
service boundaries sit, and which capabilities, timeouts, cancel semantics, and
degradation rules are transport-specific.**

**Core product rule:** one logical tool/interface contract across multiple
runtimes and carriers **does not imply exact transport parity.** Carriers move
messages; contracts define meaning; CIDs name content.

Server startup, hierarchical meta-tools, caches, and dispatch pipelines:
[SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md). Tool tree, metadata, and
naming: [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md).

## 2. Audience

- **Primary:** architects and developers wiring multi-transport MCP clients or
  adding adapters
- **Secondary:** operators choosing stdio vs HTTP vs P2P; agents that must not
  invent a second identity or tool contract per transport

## 3. Scope and non-goals

### In scope

- Transport-neutral **interface** contracts (MCP-IDL / Profile A) and
  Protocol-based server/tool/P2P seams
- **Content identity** for interfaces, execution artifacts, and Profile G
  objects (CID rules and what is *not* identity)
- Host and adapter matrix: **stdio**, **HTTP/FastAPI**, **gRPC**, **Trio/AnyIO**,
  **MCP++** / **libp2p** / **P2P** registries and services
- **Runtime routing** (FastAPI vs Trio selection via metadata)
- **Profile G** service boundaries (risk/scheduling surface vs tool dispatch)
- Transport-specific **capabilities**, **timeout/cancel**, and **degradation**

### Non-goals

- Exhaustive per-tool catalogs or undated tool counts
- Full UCAN / temporal-policy body (IPFSDOC-052+)
- Operator runbooks and metrics dashboards (IPFSDOC-052+)
- Claiming that every transport exposes the same auth, streaming, or framing
  feature set

---

## 4. Separation of concerns (normative layering)

```text
  ┌─────────────────────────────────────────────────────────────┐
  │  Domain engines (processors, logic, embeddings, …)          │
  │  Authority: domain packages — not transports                │
  └────────────────────────────▲────────────────────────────────┘
                               │ thin tool wrappers
  ┌────────────────────────────┴────────────────────────────────┐
  │  Transport-neutral contracts                                │
  │  • Hierarchical meta-tools + HierarchicalToolManager        │
  │  • ToolMetadata / schemas / dispatch envelopes              │
  │  • InterfaceDescriptor (Profile A) + interface_cid          │
  │  • CID-native artifacts (Profile B) when opted in           │
  │  • mcp_interfaces Protocols (server / manager / P2P)        │
  └────────────────────────────▲────────────────────────────────┘
                               │ adapters only (no second logic)
  ┌────────────────────────────┴────────────────────────────────┐
  │  Carriers / hosts                                           │
  │  stdio (FastMCP) │ HTTP/FastAPI │ gRPC stub │ MCP+P2P/libp2p │
  │  Trio/AnyIO host path │ Profile G JSON-RPC/REST/P2P methods │
  └─────────────────────────────────────────────────────────────┘
```

| Layer | Owns | Must not own |
| --- | --- | --- |
| **Domain** | Algorithms, IR, storage semantics | Wire framing, peer multiaddrs |
| **Contract** | Tool names/schemas, interface CID, result envelope shapes, identity of *what* was said | HTTP status codes as business truth; peer-id as content identity |
| **Carrier** | Framing, sessions, auth handshake, host lifecycle, runtime event loop | Re-implement domain or invent a second tool inventory |
| **Runtime router** | Which concurrency backend runs a callable | Which *tool exists* or what its schema is |

Binding decisions: [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md)
(canonical vs compat), [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)
(registries/adapters), package ADR-002 (dual-runtime), package ADR-006 (MCP++
profiles).

---

## 5. Transport-neutral tool and interface contracts

### 5.1 Tool contract (canonical MCP product surface)

The product-facing tool contract is **independent of how the process is
started**:

1. Discover categories → `tools_list_categories`
2. Discover tools → `tools_list_tools(category)`
3. Fetch schema → `tools_get_schema(category, tool)`
4. Execute → `tools_dispatch(category, tool, params)` → structured result dict

Authority for discovery and dispatch:
`HierarchicalToolManager` under `mcp_server/tools/` (see
[TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md)). Flat bulk
registration of every tool onto the MCP host is **not** the canonical path.

**Implication for transports:** a carrier may expose only the four hierarchical
meta-tools, or may also project flat name aliases (e.g. FastAPI list surfaces).
Flat aliases are **views**, not a second registry.

### 5.2 Protocol seams (`mcp_interfaces.py`)

PEP 544 `Protocol` types break import cycles and define the minimal shapes
adapters may rely on:

| Protocol | Minimal surface | Used by |
| --- | --- | --- |
| `MCPServerProtocol` | `tools` map; `validate_p2p_token` | `P2PMCPRegistryAdapter` |
| `ToolManagerProtocol` | `list_categories` / `list_tools` / `get_schema` / `dispatch` | Hosts that call the manager without importing concrete class graphs |
| `MCPClientProtocol` | `add_tool` / `list_tools` | Client registration shims |
| `P2PServiceProtocol` | `start` / `stop` / `is_running` / `register_tool` | Optional peer service managers |

Adapters must depend on **Protocols**, not on transport-private types, when
crossing package or process boundaries.

### 5.3 Interface descriptors (MCP++ Profile A / MCP-IDL)

Module: `interface_descriptor.py`.

An `InterfaceDescriptor` is a **content-addressed interface contract**:

| Field group | Role |
| --- | --- |
| `name`, `namespace`, `version` | Logical interface identity (not a CID) |
| `methods[]` (`MethodSignature`: name, input/output schemas, errors, streaming) | Callable surface |
| `requires`, `compatibility` | Capability and version edges |
| `semantic_tags`, `observability`, `interaction_patterns` | Selection and ops hints |
| `interface_cid` | **CID of canonical bytes** of the descriptor |

Canonicalization: deterministic JSON (`sort_keys`, compact separators) →
`compute_cid` (CIDv1-style `bafy…` / multihash path; legacy `sha256:` prefix
supported for migration comparison only via `cids_equivalent` / digest helpers).

`InterfaceRepository` exposes:

- `list()` / `get(cid)` — discover and resolve by **interface CID**
- `compat(cid, required_cid=…)` — structural compatibility verdict
  (`CompatVerdict`: missing methods, requires, alternatives)
- optional `select(task_hint, budget)` — semantic-tag overlap selection

**Rule:** transport bindings advertise *which* `interface_cid` a peer or host
implements. They do not redefine method semantics. Pubsub topic for announce
(non-normative): `/mcp+p2p/topics/interface_cid/1.0.0` in
`MCP_P2P_PUBSUB_TOPICS`.

### 5.4 Tool metadata that is still transport-neutral

`ToolMetadata` (`tool_metadata.py`) attaches **execution hints** that routers
and hosts may honor without changing tool identity:

| Field | Meaning |
| --- | --- |
| `runtime` | `fastapi` \| `trio` \| `auto` (`RUNTIME_*` constants) |
| `timeout_seconds` | Default execution budget hint (default 30s) |
| `requires_p2p` | Tool expects P2P-capable host; incompatible with pure FastAPI-only claim |

These fields describe **how/where to run**, not **what the tool is**. Schema and
name remain the contract.

---

## 6. Content identity (what is a CID here)

Cross-product identity rules:
[ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md).
MCP-specific applications:

### 6.1 Identity vs location vs session

| Concept | Answers | Examples in MCP tree |
| --- | --- | --- |
| **Content identity (CID)** | *What* bytes / canonical object | `interface_cid`; Profile B artifact CIDs; Profile G goal/task/claim CIDs |
| **Location** | *Where* last seen | HTTP URL, multiaddr, pin set, SQLite path |
| **Session / peer identity** | *Who* is connected | libp2p PeerId, JWT subject, P2P shared token |
| **Tool name** | *Which* callable in a registry | `tools_dispatch` category+tool; flat alias string |

Never substitute multiaddr, filesystem path, or request-id for a CID when a
content-addressed field is required.

### 6.2 Profile B — CID-native execution artifacts

Module: `cid_artifacts.py` (optional; does not change base MCP JSON-RPC formats).

| Artifact | Role |
| --- | --- |
| `IntentObject` | CID'd planned action |
| `DecisionObject` | CID'd policy evaluation result |
| `ReceiptObject` | Immutable CID'd execution attestation |
| `ExecutionEnvelope` | Invocation wrapper with CID references |
| `EventNode` | DAG node linking intent/decision/receipt |

Optional hierarchical path `dispatch_with_trace` attaches CID-native `_trace`
envelopes for provenance of tool calls (see
[RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8.3).

### 6.3 Profile G artifact CIDs

`profile_g_service.py` / `logic.profile_g` use strict canonical validation and
`profile_g_cid` for every Profile G artifact. Mutations that fail CID validation
surface structured errors (e.g. `G_CID_MISMATCH`). See §10.

### 6.4 Identity implementation notes (discrepancies)

| Observation | Guidance |
| --- | --- |
| `interface_descriptor.compute_cid` produces CIDv1-style `b…` strings; older docs mentioned `sha256:` only | Prefer CIDv1; use equivalence helpers when comparing mixed historical formats |
| Domain ADR-001 prefers `utils.cid_utils` / DAG-JSON for new product artifacts | Profile A/B modules use their local canonicalize/CID path for MCP++ IDL/artifact parity; do not invent a third hash field name for the same object |
| Provenance rows ≠ CIDs | Lineage *references* content identities; it is not a substitute |

---

## 7. Transport matrix

**Parity rule:** every transport that can invoke tools should eventually land on
the same hierarchical dispatch semantics. **Feature parity is not guaranteed**
for auth modes, streaming, binary framing limits, or peer discovery.

### 7.1 Summary

| Transport | Module / entry | Primary role | Tool surface | Concurrency | Status class |
| --- | --- | --- | --- | --- | --- |
| **stdio** | `server.start_stdio` / FastMCP `run_stdio_async`; `python -m ipfs_datasets_py.mcp_server` | Default local host (IDE / agent pipes) | Hierarchical meta-tools on FastMCP | anyio over asyncio (typical) | **Canonical process** |
| **HTTP / FastAPI** | `fastapi_service.app`; `start_server` → Hypercorn+Trio preferred, uvicorn fallback | REST + MCP list/call helpers + ops endpoints | Meta-tools + hierarchical **flat** descriptors; Profile G REST bindings | FastAPI/anyio; Hypercorn may host with Trio | **Canonical HTTP host** |
| **gRPC** | `grpc_transport.GRPCTransportAdapter` | Optional mesh bridge | Category/tool/params → manager dispatch | asyncio-oriented stub | **Optional secondary** (stub; not MCP++ pipeline default) |
| **MCP+P2P (Profile E)** | `mcp_p2p_transport` constants/framer; `p2p_libp2p_transport`; `P2PServiceManager` | Peer sessions over `/mcp+p2p/1.0.0` | Same logical tools via registry adapter | **Trio** + libp2p | **Optional; carriage-only binding** |
| **Profile G methods** | `profile_g_service` | Risk/scheduling/goals — not hierarchical tools | JSON-RPC method names + REST map + native Profile E dispatch | Host-dependent | **Optional service boundary** |
| **simple / compat** | `simple_server`; `compat/*` | Degraded or migration | Reduced | Host-dependent | **Compatibility** — not second architecture |

### 7.2 stdio

```text
python -m ipfs_datasets_py.mcp_server [--stdio]
  → start_stdio_server()
  → IPFSDatasetsMCPServer.start_stdio
  → register_tools (meta-tools)
  → optional p2p.start(P2PMCPRegistryAdapter(self))
  → FastMCP run_stdio_async
  → finally: p2p.stop(); delegation save
```

- **Capabilities:** full MCP protocol over stdin/stdout; preferred for editor
  agents; no HTTP auth surface.
- **Limits:** single client pipe; no multiaddr advertisement; optional P2P may
  still start *alongside* stdio if configured.
- **Degradation:** missing FastMCP → fail-closed stub; registration/run that
  need real MCP raise rather than invent tools.

### 7.3 HTTP / FastAPI

```text
python -m ipfs_datasets_py.mcp_server --http [--host] [--port]
  → start_server(host, port)
  → prefer Hypercorn+Trio on fastapi_service.app
  → else uvicorn
  → else fall back to stdio with warning
```

`fastapi_service` owns:

- Lifespan construction of `IPFSDatasetsMCPServer` and `register_tools`
- Health/readiness and metrics endpoints
- Optional wallet router include
- Flat hierarchical tool projection for list/call HTTP paths
  (`_hierarchical_flat_descriptors`, `_dispatch_hierarchical_flat_tool`)
- Auth helpers (JWT-style login/refresh where enabled)

**Capabilities unique or stronger on HTTP:** REST ergonomics, readiness probes,
Prometheus-style metrics scrape, browser/ops clients, Profile G REST bindings
(`PROFILE_G_REST_BINDINGS`).

**Not implied:** every MCP JSON-RPC method or every P2P stream feature appears as
an HTTP route. Flat names are convenience projections of the hierarchical tree.

### 7.4 gRPC (optional secondary)

`grpc_transport.py` documents explicitly:

> **The canonical MCP transport is MCP+P2P (Profile E)** for peer carriage;
> process defaults for local work remain stdio/HTTP. gRPC is an *optional
> secondary* bridge for existing gRPC meshes and is **not** used by MCP++
> pipeline stages by default.

| Item | Behavior |
| --- | --- |
| Availability | `GRPC_AVAILABLE` gated on `grpc` import |
| Request shape | `GRPCToolRequest` (category, tool, params_json, request_id) |
| Response shape | `GRPCToolResponse` (success, result_json, error, request_id) |
| Dispatch | Adapter holds `HierarchicalToolManager` and executes the same logical tools |
| Status | Stub — server bootstrap wired; full protobuf codegen intentionally omitted until integration is completed |

Missing `grpcio` → import/start paths fail soft or raise with install hint; core
stdio/HTTP remain unaffected.

### 7.5 Trio / AnyIO dual-runtime

Package ADR-002 and [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md):

| Principle | Practice |
| --- | --- |
| Write portable tools | Prefer `anyio` primitives (`sleep`, `TaskGroup`, file I/O) over bare `asyncio.*` / `trio.*` in shared tools |
| Opt into Trio | `@tool_metadata(runtime=RUNTIME_TRIO)` or equivalent registry fields |
| Bridge | `trio_bridge.run_in_trio` / `trio_adapter` for Trio-marked tools on non-Trio hosts |
| Why Trio | Structured concurrency and cancel scopes for P2P-sensitive and workflow work |
| Why FastAPI/anyio | HTTP host path and general tool volume |

**Do not** treat dual-runtime as unfinished theory: process entry points and
accepted ADRs already bind it. **Do not** hard-code event-loop assumptions in
thin tool wrappers.

### 7.6 MCP++ and libp2p adapters (Profile E carriage)

Profile E is **carriage-only**: it moves MCP JSON-RPC (and related) messages
between peers **without changing method semantics or tool definitions**.

| Component | Responsibility |
| --- | --- |
| `mcp_p2p_transport` | Normative constants: `MCP_P2P_PROTOCOL_ID = "/mcp+p2p/1.0.0"`; frame size defaults (16 MiB); `LengthPrefixFramer`; session state machine; pubsub topic names |
| `p2p_libp2p_transport` | libp2p+Trio host: PeerId, stream multiplex, discovery, tool invocation over streams; optional install via `ipfs_accelerate_py` MCP++ provider |
| `p2p_service_manager` | Optional in-process TaskQueue/cache service lifecycle attached to `IPFSDatasetsMCPServer` |
| `p2p_mcp_registry_adapter` | Projects server tools (+ hierarchical fallback) into accelerate-style `{function, description, input_schema, runtime}` registry; forwards `validate_p2p_token` |
| `mcplusplus/*` | Peer registry, task queue, workflow DAG/engine, bootstrap — optional peer/workflow extensions |
| `service_registry` | Advertise/discover `ServiceRecord` (peer_id, multiaddrs, tools, TTL, optional signature) under `/mcppp/services/1.0.0` |

**P2P registries/services are discovery and carriage**, not domain engines
([ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)).

Session lifecycle (Profile E): `DISCONNECTED → CONNECTING → HANDSHAKING →
ACTIVE → CLOSING → CLOSED`.

---

## 8. Runtime routing

Module: `runtime_router.py` (`RuntimeRouter`).

```text
                    RuntimeRouter
                         |
          +--------------+--------------+
          |                             |
    FastAPI / anyio path          Trio path
    (general tools)               (P2P / marked tools)
          |                             |
    thread / host loop            Trio nursery / cancel scopes
```

### 8.1 Selection

1. Resolve `ToolMetadata` for the tool (registry / decorator).
2. Choose runtime:
   - `RUNTIME_TRIO` → Trio path (direct when already in Trio; bridge otherwise)
   - `RUNTIME_FASTAPI` → FastAPI/anyio path
   - `RUNTIME_AUTO` → default runtime configured on the router (typically FastAPI)
3. Record metrics (`RuntimeMetrics`: latency, error counts; bounded history).

Goals (design intent documented in module): reduce thread hops for Trio-native
P2P tools; keep the public tool API unchanged.

### 8.2 What routing is not

| Routing does | Routing does not |
| --- | --- |
| Select concurrency backend | Change tool name, schema, or domain result meaning |
| Honor `requires_p2p` / timeout metadata as host policy inputs | Guarantee P2P network success |
| Soft-fail metrics collection | Override fail-closed trust decisions |

`P2PMCPRegistryAdapter` may also tag tools with `runtime` metadata so remote
callers can filter or prefer peers that match.

---

## 9. Transport-specific capabilities

Use this matrix when designing clients. **Absent cell ⇒ do not assume.**

| Capability | stdio | HTTP/FastAPI | gRPC | MCP+P2P / libp2p | Profile G service |
| --- | --- | --- | --- | --- | --- |
| Hierarchical meta-tools | Yes (canonical) | Yes + flat projection | Via manager in adapter | Via registry adapter | N/A (different methods) |
| Flat name list | Optional / limited | Yes (HTTP helpers) | Request fields category+tool | Depends on peer registry shape | REST resource paths |
| Interface CID announce | Local repository | Optional expose | Optional | Pubsub topic `interface_announce` | Artifact CIDs in API |
| Peer discovery | No | No | No | mDNS / DHT / bootstrap | Neighborhood APIs (placement only) |
| Shared-token / P2P auth | Optional side service | JWT/session HTTP auth | Implementation-defined | Token + host `validate_p2p_token` | Authority validators injected |
| Streaming | Protocol-dependent | HTTP streaming limited | Stub | Stream multiplex over protocol ID | Request/response oriented |
| Metrics scrape | Process metrics if configured | `/metrics`, `/health` | Optional | Peer/local metrics | Risk/evidence history store |
| Max frame / payload | OS pipe | ASGI body limits | gRPC message limits | `DEFAULT_MAX_FRAME_BYTES` (16 MiB) | Method-level limits (`DEFAULT_LIMITS`) |

**Streaming flag on `MethodSignature.streaming`** describes the *interface*
capability; a carrier without stream support must fail clearly rather than
silently buffer unbounded payloads.

---

## 10. Profile G service boundaries

Profile G (`mcp++/risk-scheduling` v1.0 datasets provider) is a **separate
service surface** from hierarchical dataset/PDF/logic tools.

| Concern | Profile G | Hierarchical MCP tools |
| --- | --- | --- |
| Purpose | Goals, plans, risk evidence, schedule claims, neighborhood placement | Domain dataset/AI operations |
| Identity | Strict Profile G artifact CID validation | Tool names + optional Profile B traces |
| Authority | Profile C/D validators **fail closed** when absent (unless `trusted_local=True` in-process) | Dispatch pipeline / UCAN optional stages (soft skip vs hard deny per stage) |
| Placement vs execution | PlanBranch **advisory**; neighborhood is **placement confidence only** — never execution authority | Tool dispatch *is* the execution entry (subject to policy) |
| Persistence | `RiskEvidenceStore` (SQLite or memory); `IPFS_DATASETS_PROFILE_G_DB` | Tool-local / domain stores |
| Wire | JSON-RPC methods (`PROFILE_G_METHODS`), REST (`PROFILE_G_REST_BINDINGS`), Profile E/libp2p | stdio MCP / HTTP tool routes / P2P tool registry |

Representative method families:

- `mcp++/goals/*`, `mcp++/tasks/*` — plan structure (CIDs in path/body)
- `mcp++/risk/*` — profile, assess, evidence, history
- `mcp++/neighborhood/*` — query/attest (not leases of record for foreign executors)
- `mcp++/schedule/*` — frontier, claim, renew, release, resolve, reconcile

**Boundary rule:** do not re-home Profile G algorithms into FastAPI route
handlers or P2P adapters. Routes and adapters call `ProfileGService` /
`profile_g` facade. Network hosts **must** inject authority and policy
validators and an attestation signer; only authenticated in-process callers may
use `trusted_local=True`.

Facade docs: [docs/profile_g_datasets_provider.md](../../profile_g_datasets_provider.md).

---

## 11. Timeout, cancel, and concurrency semantics

Timeouts and cancellation are **host- and runtime-specific**. Contracts may
*hint* budgets; carriers *enforce* them.

| Layer | Mechanism | Notes |
| --- | --- | --- |
| Tool metadata | `timeout_seconds` (default 30) | Hint for routers and callers |
| Circuit breaker / server configs | Per-tool or default timeouts in server config objects | Complements metadata |
| AnyIO host | `anyio.move_on_after`, `anyio.get_cancelled_exc_class()` | Portable cancel detection (monitoring, pubsub handlers) |
| Trio / libp2p | `trio.CancelScope`, `trio.move_on_after` | Peer invoke timeout (e.g. default 30s) raises `TimeoutError` on cancel |
| Hypercorn+Trio HTTP | Process-level server lifecycle | Preferred HTTP host for Trio-aligned stack |
| P2P service startup | `p2p_startup_timeout_s` (config; often ~2s) | Bound optional service attach |
| Profile G | Method/store limits; lease expiry errors (`G_LEASE_EXPIRED`) | Scheduling claims are time-bounded |

**Rules for implementers:**

1. Prefer anyio cancel APIs in shared code so both backends behave.
2. On cancel, release peer streams and local resources; do not leave orphan
   TaskQueue work without a documented lease/reconcile path.
3. Timeout ⇒ structured error or raised timeout; **never** silent partial success
   presented as full success.
4. UNKNOWN / inconclusive solver outcomes (elsewhere in the product) remain
   **non-success** for trust — distinct from transport timeout
   ([ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md)).

---

## 12. Degradation matrix

Apply [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md): degrade
**features**; fail closed on **trust**.

| Condition | Allowed degradation | Forbidden |
| --- | --- | --- |
| FastMCP / `mcp` missing | Stub server for import; simple_server fallback for reduced envs | Pretending full MCP protocol works |
| Hypercorn missing | uvicorn, then stdio fallback with warning | Silent loss of configured HTTP without log |
| gRPC not installed | Adapter unavailable; other transports unaffected | Shipping fake protobuf success |
| libp2p / accelerate MCP++ extra missing | P2P optional path unset; log; local tools continue | Inventing peer results or forged multiaddrs |
| P2P start failure after register_tools | Log warning; stdio/HTTP continue | Aborting core tool contract construction without cause |
| Interface repository empty | No CID announce; tools still dispatch | Inventing interface_cid values |
| Profile G validators missing on network path | **Fail closed** mutations (`G_AUTHORITY_DENIED` / not ready / capability errors) | Allowing schedule side effects without authority |
| Trio unavailable | FastAPI path only; Trio-marked tools bridge or soft-unavailable | Deadlock by forcing Trio primitives on asyncio-only host without bridge |
| Optional MCP++ meta-tools import fail | Hierarchical four remain | Changing hierarchical semantics |

Canonical vs compatibility labeling:
[ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md).

---

## 13. Control and data flow (end-to-end)

### 13.1 Local tool call (stdio or HTTP)

```text
Client
  → carrier (stdio MCP or HTTP)
  → IPFSDatasetsMCPServer / FastAPI helper
  → tools_dispatch | flat hierarchical projection
  → optional DispatchPipeline (compliance/risk/UCAN — soft skip or hard fail per stage)
  → HierarchicalToolManager.dispatch
  → optional RuntimeRouter (FastAPI vs Trio)
  → thin tool → domain engine
  → result dict envelope
  → carrier response
```

### 13.2 Peer tool call (MCP+P2P)

```text
Remote peer
  → libp2p stream /mcp+p2p/1.0.0
  → LengthPrefixFramer / session ACTIVE
  → auth (shared token and/or host validate_p2p_token)
  → P2P service call_tool
  → P2PMCPRegistryAdapter.tools[name]
  → hierarchical meta-tools or flat callable
  → same manager/domain path as local
  → framed JSON-RPC response
```

### 13.3 Profile G mutation

```text
Client (JSON-RPC | REST | P2P)
  → ProfileGService method
  → canonical validate + CID check
  → authority_validator + policy_validator (fail closed if unset on network)
  → RiskEvidenceStore / schedule state
  → signed or stored evidence CID
```

---

## 14. Implementation map (source pointers)

| Concern | Primary paths |
| --- | --- |
| Interface CID / MCP-IDL | `mcp_server/interface_descriptor.py` |
| Protocols | `mcp_server/mcp_interfaces.py` |
| CID artifacts (Profile B) | `mcp_server/cid_artifacts.py` |
| Canonical server / stdio / HTTP launch | `mcp_server/server.py`, `__main__.py` |
| FastAPI app | `mcp_server/fastapi_service.py`, `fastapi_config.py` |
| gRPC adapter | `mcp_server/grpc_transport.py` |
| Profile E constants / framer | `mcp_server/mcp_p2p_transport.py` |
| libp2p+Trio transport | `mcp_server/p2p_libp2p_transport.py` |
| P2P service lifecycle | `mcp_server/p2p_service_manager.py` |
| P2P registry adapter | `mcp_server/p2p_mcp_registry_adapter.py` |
| Service advertisement | `mcp_server/service_registry.py`, `mcplusplus/peer_registry.py` |
| Runtime routing | `mcp_server/runtime_router.py`, `trio_bridge.py`, `tool_metadata.py` |
| Profile G | `mcp_server/profile_g_service.py`, `ipfs_datasets_py/profile_g` facade, `logic.profile_g` |
| Package decisions | `mcp_server/docs/adr/ADR-002-dual-runtime.md`, `ADR-006-mcp++-alignment.md` |

---

## 15. How to extend safely

1. **New tool** — add under `mcp_server/tools/<category>/`; keep transport-agnostic;
   mark `runtime=RUNTIME_TRIO` only if structured concurrency is required.
2. **New interface contract** — build `InterfaceDescriptor`, publish
   `interface_cid`; do not fork schemas per transport.
3. **New carrier** — adapter only: map framing ↔ hierarchical dispatch or
   Profile G service; depend on Protocols; document capability row in §9.
4. **New Profile G method** — implement on `ProfileGService` first; then add
   JSON-RPC name and REST binding; keep fail-closed validators.
5. **Never** put domain algorithms in `grpc_transport`, `p2p_*`, or FastAPI
   route bodies beyond validation and delegation.

---

## 16. Validation and verification

```bash
# Declared acceptance for IPFSDOC-051
test -s docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md && \
  rg -n 'interface|CID|stdio|HTTP|FastAPI|gRPC|Trio|P2P|MCP\+\+|Profile G' \
  docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md

# Spot-check modules still present (optional)
test -f ipfs_datasets_py/mcp_server/interface_descriptor.py
test -f ipfs_datasets_py/mcp_server/runtime_router.py
test -f ipfs_datasets_py/mcp_server/mcp_p2p_transport.py
test -f ipfs_datasets_py/mcp_server/profile_g_service.py
```

Focused import checks (optional; require package env):

```bash
python -c "from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCP_P2P_PROTOCOL_ID; print(MCP_P2P_PROTOCOL_ID)"
python -c "from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceDescriptor, compute_cid; print('ok')"
```

---

## 17. Related documents

| Document | Relationship |
| --- | --- |
| [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) | Startup, meta-tools, caches, pipelines |
| [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md) | Tool tree, naming, validation |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | Packaging and CLI/MCP entry |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Product content identity |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Feature degrade vs fail-closed trust |
| [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | Registries and adapters |
| [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | Canonical vs compatibility runtimes |
| [docs/profile_g_datasets_provider.md](../../profile_g_datasets_provider.md) | Profile G provider summary |
| Package ADR-002 / ADR-006 | Dual-runtime and MCP++ profile alignment bodies |
| IPFSDOC-052+ | Policy, audit, event DAG, observability |

---

## 18. Explicit non-parity and deferred items

Documented so agents do not invent equality:

1. **stdio ≠ HTTP ≠ gRPC ≠ P2P** for auth, discovery, and ops endpoints.
2. **gRPC** remains an optional stub bridge until protobuf codegen is productized.
3. **Profile G** method set is not a superset of hierarchical tools and is not
   interchangeable with `tools_dispatch`.
4. **Interface CID** announce over pubsub is optional; local servers work without
   it.
5. Full UCAN (Profile C) policy bodies and operator audit runbooks belong in
   later tasks (IPFSDOC-052+), not in this guide’s contract layer.

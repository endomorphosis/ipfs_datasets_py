# MCP++ (MCP+P2P) → Our MCP Server: Infinite Refactor + Integration Backlog

Source (innovations):
- `ipfs_datasets_py/ipfs_accelerate_py/ipfs_accelerate_py/mcplusplus_module`

Target (our implementation):
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server`

This is an **effectively infinite backlog**. The goal is to continuously:
1) refactor to reduce integration drag,
2) integrate MCP++ capabilities in small safe slices,
3) harden (tests, security, observability),
4) document the resulting system.

How to use this doc:
- Prefer **P0**/**P1** items.
- Prefer items with explicit “Done when …”.
- Keep changes import-quiet and micro-test-backed.

Upstream spec references (MCP++):
- https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/index.md
- https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/ARCHITECTURE.md

---

## 0) Where the code lives (map)

Core server + tool wiring
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/server.py`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/__main__.py`

Tool surfacing + dispatch
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/**`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/tool_registry.py` (overlaps conceptually; refactor target)

P2P runtime integration
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/p2p_service_manager.py`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/p2p_mcp_registry_adapter.py`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/trio_bridge.py`

MCP++ adapters/wrappers
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/mcplusplus/**`

Configuration + observability
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/configs.py`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/logger.py`
- `ipfs_datasets_py/ipfs_datasets_py/mcp_server/monitoring.py`

---

## 1) Current status (baseline)

Already working (keep green):
- Embedded libp2p TaskQueue service can run in-process (Trio in background thread).
- P2P `call_tool` routes into host MCP tool surface via `P2PMCPRegistryAdapter`.
- Auth mode `mcp_token` enforced for P2P messages.
- Remote wrappers exist (`p2p_remote_*`) and workflow scheduler tools exist.
- End-to-end tests exist for embedded startup + remote tool invocation.

---

## 2) Inventory of “MCP++ innovations” (glossary)

Keep this list updated as we discover new surfaces.
- P2P `call_tool` routing (auth + envelopes + retries)
- Durable TaskQueue (DuckDB)
- Result caching / receipts
- Workflow DAG scheduling + provenance
- Peer registry + discovery providers (bootstrap, file registry, rendezvous, etc.)
- Trio-native structured concurrency patterns
- Capability-based auth (UCAN-like)
- Content-addressed tool/interface contracts (schema hashing → CIDs)

### 2.1 Concrete code surfaces we can reuse (today)

From `mcplusplus_module` (reference implementation surfaces):
- Trio bridge utility pattern (`mcplusplus_module.trio.bridge.run_in_trio()`)
  - Our equivalent: `ipfs_datasets_py/ipfs_datasets_py/mcp_server/trio_bridge.py`
- Trio-native MCP server/client (ASGI + Hypercorn): `mcplusplus_module.trio.server` / `mcplusplus_module.trio.client`
  - Likely outcome: borrow patterns (structured concurrency + shutdown hygiene) rather than wholesale runtime swap.
- P2P client tool wrappers:
  - `mcplusplus_module.tools.taskqueue_tools` (wrappers around `ipfs_accelerate_py.p2p_tasks.client`)
  - `mcplusplus_module.tools.workflow_tools` (wrappers around workflow scheduler)
- Peer discovery helpers (optional):
  - `mcplusplus_module.p2p.bootstrap.SimplePeerBootstrap` (file-based registry + env)
  - `mcplusplus_module.p2p.peer_registry.P2PPeerRegistry` (GitHub Issue comment registry)
  - `mcplusplus_module.p2p.connectivity.UniversalConnectivity` (mDNS/DHT/rendezvous/relay scaffolding)

Docs/aspirational (may exist in docs but not code yet; track intentionally):
- Content-addressed contracts (CID-native MCP-IDL)
- Immutable execution envelopes/receipts
- UCAN capability delegation + policy evaluation
- Event DAG provenance and ordering

### 2.2 Spec-driven “profiles” to implement (incremental adoption)

MCP++ defines optional, negotiable profiles (draft).
Adoption order (suggested by the spec):
1) MCP-IDL (interface contracts)
2) CID-native envelopes + artifacts
3) Delegation (UCAN)
4) Policy evaluation (temporal/deontic)
5) P2P transport binding

Key spec chapters:
- `mcp+p2p` transport binding: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/transport-mcp-p2p.md
- Profile registry: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/mcp%2B%2B-profiles-draft.md
- MCP-IDL: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/mcp-idl.md
- CID-native artifacts: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/cid-native-artifacts.md
- UCAN delegation: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/ucan-delegation.md
- Temporal/deontic policy: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/temporal-deontic-policy.md
- Event DAG ordering: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/event-dag-ordering.md
- Risk + scheduling: https://raw.githubusercontent.com/endomorphosis/Mcp-Plus-Plus/main/docs/spec/risk-scheduling.md

---

## 3) Spec-driven P0/P1 milestones (interop first)

### 3.1 **P0** `mcp+p2p` baseline compliance checklist

Why:
- The transport binding defines a minimal interoperability set. Hitting it gives us a crisp “works with others” target.

TODOs (from `transport-mcp-p2p.md` baseline):
- [ ] **P0** Pick and publish supported libp2p stream protocol ID(s)
  - default proposed by draft: `/mcp+p2p/1.0.0`
- [ ] **P0** Define deterministic message framing for JSON-RPC on streams
  - strongly suggested: u32 big-endian length prefix + UTF-8 JSON
- [ ] **P0** Enforce max frame size with deterministic violation behavior
- [ ] **P0** Require MCP initialization handshake as first application data on a session stream
- [ ] **P0** Preserve JSON-RPC `id` correlation and allow multiple in-flight requests per session
- [ ] **P0** Abuse resistance
  - rate limit session creation
  - rate limit inbound message volume
  - per-peer quotas (streams / in-flight / bandwidth), at least configurable

Done when:
- Two independent implementations can interop on the same protocol ID + framing + handshake rules.
- Oversized frames and pre-init traffic are rejected deterministically.

Current code reality (important):
- Our embedded P2P runtime today is the TaskQueue RPC protocol (`/ipfs-datasets/task-queue/1.0.0`), implemented in `ipfs_accelerate_py.p2p_tasks`.
- It is *not yet* a carriage of MCP JSON-RPC over libp2p (`/mcp+p2p/1.0.0`).
- Migration path: either (a) add a true `/mcp+p2p/*` stream handler that runs MCP initialization + JSON-RPC framing, or (b) define a compatibility binding that maps our existing RPC protocol to the MCP++ transport requirements.

### 3.2 **P1** `mcp+p2p` conformance tests (OOM-safe)

TODOs (spec-suggested test ideas):
- [ ] **P1** Handshake tests: reject MCP traffic before init; accept after init
- [ ] **P1** Framing tests: concurrent requests with reordering; correlation preserved
- [ ] **P1** Abuse tests: flood small frames / open many streams triggers throttles, not OOM
- [ ] **P1** Authorization separation: valid libp2p channel but missing proofs/policy → transport OK, execution denied
- [ ] **P1** Pubsub independence (if implemented): disabling pubsub does not break point-to-point sessions

---

## 4) P0/P1 refactors (unlock velocity)

### 3.1 **P0** Single canonical tool/dispatch shape

Why:
- We currently have multiple tool “shapes” and multiple dispatch paths.

TODOs:
- [ ] **P0** Define a single canonical tool descriptor shape:
  - name, description, category/tags, JSON schema, runtime metadata
- [ ] **P0** Define one canonical dispatch API used by:
  - stdio MCP
  - P2P `call_tool`
  - (optional) HTTP transport
- [ ] **P1** Unify/retire overlapping abstractions (`tool_registry.py` vs hierarchical dispatch) or add adapters.

Done when:
- `P2PMCPRegistryAdapter` does not need to scrape `host_server.tools` ad-hoc.
- The same dispatcher is used by stdio and P2P.

### 3.2 **P0** Importability + packaging hygiene

Why:
- sys.path shims for nested submodules create brittleness.

TODOs:
- [ ] **P0** Decide and document the canonical strategy:
  - editable installs for dev + optional deps for runtime, OR
  - vendor minimal p2p_tasks subset into mcp_server
- [ ] **P1** Centralize all sys.path adjustments into one place (no per-module helpers).

Done when:
- No test requires per-script bootstrapping to import ipfs_accelerate_py.

### 3.3 **P1** Config and lifecycle consolidation

TODOs:
- [ ] **P1** Ensure `Configs` owns every P2P/MCP++ toggle and maps env vars explicitly.
- [ ] **P1** Add `Configs.validate()` for cross-field constraints.
- [ ] **P1** Make P2P lifecycle start/stop explicit in server lifecycle hooks.

Done when:
- Starting/stopping server never leaks env vars or background threads.

---

## 5) Integration epics (build capability)

### **P1** Profile A (MCP-IDL): interface contracts + repository APIs

Spec targets:
- Interface Descriptors are canonicalized and content-addressed into `interface_cid`.
- Servers expose repository APIs: `interfaces/list`, `interfaces/get(interface_cid)`, `interfaces/compat(interface_cid)`.

TODOs:
- [ ] **P1** Decide canonicalization format (canonical JSON vs DAG-JSON vs DAG-CBOR) and publish test vectors.
- [ ] **P1** Implement `interface_cid` computation for our tool surface.
- [ ] **P1** Add MCP tools implementing the repository APIs (`interfaces/*`).
- [ ] **P2** Toolset slicing: `interfaces/select(task_hint_cid, budget)`.

Done when:
- `interfaces/get()` returns byte-stable content; same descriptor ⇒ same `interface_cid`.
- `interfaces/compat()` returns deterministic verdicts + reasons.

### **P1** Execution envelopes + receipts

TODOs:
- [ ] **P1** Define a JSON-serializable receipt for every P2P operation:
  - request_id, tool_name, schema_hash, peer_id, timings, outcome, error_code
- [ ] **P2** Add tools to fetch/list receipts.

Done when:
- A receipt can be persisted and replayed for debugging.

### **P1/P2** Profile B (CID-native artifacts): intents/decisions/receipts/events

Spec targets:
- Canonicalize and CID-address: `input_cid`, `intent_cid`, `policy_cid`, `proof_cid`, `decision_cid`, `output_cid`, `receipt_cid`, `event_cid`.
- Receipts MAY be signed; decisions SHOULD be signable.

TODOs:
- [ ] **P1** Define artifact schemas (even if minimal) and canonicalization pipeline.
- [ ] **P1** Emit a minimal `intent_cid` for every remote tool invocation.
- [ ] **P2** Emit `decision_cid` + `receipt_cid` for invocations that go through auth/policy.
- [ ] **P2** Event DAG: link `parents[]` across multi-step workflows.

### **P1** Durable TaskQueue semantics

TODOs:
- [ ] **P1** Standardize task state machine (pending/running/completed/failed/cancelled).
- [ ] **P1** Add idempotency keys for task submission.
- [ ] **P2** Add retry policies per task type.

Done when:
- Duplicate submissions with same idempotency key do not double-execute.

### **P2** Profile C (UCAN delegation): proof bundles + execution-time validation

Spec targets:
- Invocation references delegation proofs (`proof_cid` or `ucan_proofs[]`).
- Validation MUST occur at execution time (capability match + caveats + expiry).

TODOs:
- [ ] **P2** Define the minimum proof bundle representation and `proof_cid` canonicalization.
- [ ] **P2** Extend auth context to accept proofs separate from PeerID.
- [ ] **P3** Bind receipts to proofs checked for auditability.

### **P3** Profile D (temporal/deontic policy): `policy_cid` → `decision_cid`

Spec targets:
- Policies are content-addressed and evaluated at execution time.
- Evaluation emits `decision_cid` (allow/deny/allow_with_obligations).

TODOs:
- [ ] **P3** Define a minimal policy representation + canonicalization rules.
- [ ] **P3** Implement policy evaluation hook (even if “allow all” w/ structured decision) as scaffolding.

### **P2** Peer discovery providers

TODOs:
- [ ] **P2** Define `PeerDiscoveryProvider` interface.
- [ ] **P2** Implement: announce-file, bootstrap list, local registry (and GitHub registry if desired).
- [ ] **P2** Add `p2p_peers_list()` tool with stable output.

### **P1/P2** Observability

TODOs:
- [ ] **P1** Correlation IDs: propagate request_id across stdio ↔ p2p ↔ workflows.
- [ ] **P1** Metrics: p2p latency/error/auth-failure counters/histograms.
- [ ] **P2** Diagnostics bundle tool (redacted config + receipts + recent logs).

---

## 6) Security hardening (stageable)

TODOs:
- [ ] **P1** Rate limiting / replay protection for P2P RPC messages.
- [ ] **P1** Audit logging for remote tool calls.
- [ ] **P2** Capability-based policy evaluation (UCAN-like) prototype.

Done when:
- Denied calls return deterministic `auth_error` receipts.

---

## 7) Testing strategy (OOM-safe)

Principles:
- Prefer micro-tests and AST/static checks.
- Keep P2P integration tests skippable when libp2p deps aren’t available.

TODOs:
- [ ] **P0** Import-quiet guards for P2P-touching modules.
- [ ] **P1** Contract tests for tool schema JSON-serializability and canonical envelopes.
- [ ] **P1** Routing-matrix tests for `call_tool`:
  - host MCP tools
  - hierarchical/meta tools
  - lightweight providers

---

## 8) Parking lot (append forever)

Use this template:
- [ ] **P?** <short title>
  - Why: <problem>
  - Where: <files/modules>
  - Done when: <acceptance>

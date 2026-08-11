# MCP architecture index

| Field | Value |
| --- | --- |
| Interface | `MCPArchitectureIndex@1` |
| Task | `IPFSDOC-053` |
| Status | `canonical` |
| Owner | architecture; mcp-server; operations |
| Source of truth | Canonical leaves under `docs/architecture/mcp/`; `ipfs_datasets_py/mcp_server/`; package ADRs under `ipfs_datasets_py/mcp_server/docs/adr/`; global [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md); [MCP_ADR_RECONCILIATION.md](../decisions/MCP_ADR_RECONCILIATION.md); [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8; [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.3 |
| Last verified | 2026-08-03 |
| Audience | architect, developer, agent, operator, security reviewer |
| Related | [decisions/README.md](../decisions/README.md); [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md); [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow E; [guides/operations/MCP_SERVER_RUNBOOK.md](../../guides/operations/MCP_SERVER_RUNBOOK.md) |
| Review cadence | after MCP server, transport, policy, or tool-tree structural changes |
| Goal | `IPFSDOC-G070` |

> **Lifecycle:** This page is the **canonical routing hub** for MCP architecture.
> It does **not** replace leaf guides or package-local ADR bodies. Prefer the
> leaves for contracts, matrices, and failure modes. Undated tool counts,
> marketing inventory claims, and static catalogs are **not** architecture
> authority — discover live via hierarchical meta-tools or disk enumeration
> under `mcp_server/tools/`.

## 1. Purpose

Route developers, agents, operators, and security reviewers to the right MCP
documentation **without** conflating:

| Concern | Must not be confused with |
| --- | --- |
| Canonical process entry | `simple_server` / import stubs / legacy Flask |
| Hierarchical meta-tools | Flat HTTP name projections or class-style registries |
| Tool listing / schema | Policy allow, proof, or successful domain execution |
| Transport carrier (stdio/HTTP/gRPC/P2P) | A second tool inventory or domain engine |
| Health / metrics / audit visibility | Authorization, capability consumption, or compliance |
| Package-local MCP ADR numbers | Global ADR-001…ADR-007 numbers (different namespaces) |

**Effects of this index:** one entry point for MCP architecture orientation;
leaves hold the binding contracts; the operator runbook holds safe local
lifecycle procedures.

**Core inequalities (all leaves agree):**

- green `/health` **≠** policy allow **≠** tool executed successfully
- discovery of a tool name **≠** optional backend present
- flat `category.tool` alias **≠** a second registry
- compatibility / simple / legacy surfaces **≠** canonical product architecture
- monitoring and event-DAG presence **≠** proof or one-time capability

## 2. Audience

| Audience | Use |
| --- | --- |
| **Architect / agent** | Place new MCP work in the correct leaf; avoid dual SoT |
| **Developer** | Start/dispatch path, tool layout, dual-runtime rules |
| **Operator / SRE** | Start → probe → stop → recover; see runbook |
| **Security reviewer** | Policy gates, audit/redaction, non-substitution rules |

## 3. Scope and non-goals

### In scope

- Index of **canonical** MCP architecture leaves under this directory
- Map of **package-local MCP ADRs** (bodies remain under the package tree)
- Related **global ADRs** that frame MCP product rules
- Canonical vs compatibility / simple / standalone / legacy labeling
- Routes to runtime entrypoints, domain map, operator runbook, and labeled
  non-authoritative material

### Non-goals

- Full server construction and dispatch algorithms → [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md)
- Full tool lifecycle / metadata / naming → [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md)
- Full transport parity matrices → [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md)
- Full policy stage semantics → [POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md)
- Full metrics / DAG / health contracts → [AUDIT_EVENTS_AND_OBSERVABILITY.md](AUDIT_EVENTS_AND_OBSERVABILITY.md)
- Operator command sequences → [MCP_SERVER_RUNBOOK.md](../../guides/operations/MCP_SERVER_RUNBOOK.md)
- Exhaustive per-tool catalogs or undated counts
- Copying package ADR bodies into this directory

---

## 4. Canonical MCP architecture guides

These five pages are the **architecture authority** for MCP under
`docs/architecture/mcp/`. All have status `canonical` as of last verification
(tasks `IPFSDOC-050`–`IPFSDOC-052`).

| Guide | Interface | Owns | Task | Status |
| --- | --- | --- | --- | --- |
| [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) | `MCPServerArchitecture@1` | Process entry, `IPFSDatasetsMCPServer` lifecycle, `ServerContext`, hierarchical meta-tools, dispatch envelopes, caches, optional pipeline attach, compat labels | IPFSDOC-050 | **canonical** |
| [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md) | `MCPToolLifecycle@1` | Tool tree layout, discovery, `ToolMetadata`, validation, naming, aliases, unavailable tools, how to add a tool | IPFSDOC-050 | **canonical** |
| [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md) | `MCPInterfaceTransportArchitecture@1` | Interface CID / Profile A, carriers (stdio, HTTP/FastAPI, gRPC, Trio/AnyIO, MCP++/libp2p), runtime router, Profile G boundary, transport timeouts/degradation | IPFSDOC-051 | **canonical** |
| [POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md) | `MCPPolicyArchitecture@1` | Optional `DispatchPipeline` stages (compliance, risk, UCAN, temporal, NL-UCAN), deny vs soft-skip, non-execution | IPFSDOC-052 | **canonical** |
| [AUDIT_EVENTS_AND_OBSERVABILITY.md](AUDIT_EVENTS_AND_OBSERVABILITY.md) | `MCPObservabilityArchitecture@1` | Event DAG / receipts, audit correlation & redaction, metrics, OTel, Prometheus, `/health` / `/health/ready`, P2P states; non-substitution | IPFSDOC-052 | **canonical** |

```text
                    ┌──────────────────────────────────────┐
                    │  docs/architecture/mcp/              │
                    │  README.md  (this index)             │
                    └──────────────────┬───────────────────┘
     ┌───────────────┬─────────────┬───┴────┬──────────────┬────────────────┐
     ▼               ▼             ▼        ▼              ▼                ▼
 SERVER_AND_     TOOL_LIFECYCLE  INTERFACES  POLICY_AND_  AUDIT_EVENTS_   Operator
 DISPATCH.md     _AND_           _AND_       AUTHORIZATION  AND_OBSERV…   runbook
                 REGISTRIES.md   TRANSPORTS  .md            .md           (ops)
```

**Reading order for a new MCP feature or host:**

1. This index (orientation + canonical vs compat)
2. [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) + [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md)
3. [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md) if multi-carrier
4. [POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md) +
   [AUDIT_EVENTS_AND_OBSERVABILITY.md](AUDIT_EVENTS_AND_OBSERVABILITY.md) if
   gated or audited hosts
5. [MCP_SERVER_RUNBOOK.md](../../guides/operations/MCP_SERVER_RUNBOOK.md) for
   local start/probe/stop/recover

---

## 5. Canonical vs simple / standalone / legacy / optional

Binding product rule:
[ADR-007-MCP-RUNTIME-COMPATIBILITY.md](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md).

| Class | Surfaces | Role for docs and new work |
| --- | --- | --- |
| **Canonical** | `python -m ipfs_datasets_py.mcp_server`; `IPFSDatasetsMCPServer`; `start_stdio_server` / `start_server`; hierarchical meta-tools (`tools_list_categories`, `tools_list_tools`, `tools_get_schema`, `tools_dispatch`); thin tools under `mcp_server/tools/` | **Preferred** for new work, contract tests, and production operator procedures |
| **Dual-runtime design (accepted)** | anyio-portable tools; `RUNTIME_TRIO` / `tool_metadata`; `trio_bridge`; FastAPI/HTTP + stdio hosts | Binding concurrency model for **full** server tools (package ADR-002) |
| **Compatibility / degraded** | `mcp_server/compat/*`; import stubs when `mcp` is missing | Migration and reduced environments — **not** a second architecture |
| **Simple / standalone** | `simple_server.SimpleIPFSDatasetsMCPServer`; `start_simple_server` | Fallback when full FastMCP stack unavailable; **deprecated** as a feature peer; do not extend as canonical |
| **Legacy** | `tools/legacy_mcp_tools/`; historical class-style `ToolRegistry` / `MCPToolRegistry` bulk registration; Flask-oriented simple HTTP | Compat inventory only; not preferred for new tools |
| **Optional extensions** | MCP++ profiles / `mcplusplus/*`; P2P registry adapters; gRPC stub; Prometheus/OTEL; `DispatchPipeline` stages; Profile G service | Opt-in; absence must **not** redefine the base hierarchical tool contract |

**Rules:**

1. Do not present `simple_server`, `compat`, or legacy trees as equal sources of
   truth for tool inventory, dispatch semantics, or engine placement.
2. Flat HTTP name lists are **views** over hierarchical discovery, not a second
   registry ([SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) §6–§11).
3. Domain algorithms live in domain packages; MCP modules are thin wrappers
   (package ADR-001/004; global [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)).

---

## 6. Package-local MCP ADRs

Six accepted Architecture Decision Records live under the **package** tree.
Their number space is **independent** of global ADR-001…ADR-007.

```text
ipfs_datasets_py/mcp_server/docs/adr/
  ADR-001-thin-wrapper-pattern.md
  ADR-002-dual-runtime.md
  ADR-003-hierarchical-tool-system.md
  ADR-004-engine-extraction-pattern.md
  ADR-005-v6-coverage-hardening.md
  ADR-006-mcp++-alignment.md
```

| Package ADR | Title | Primary disposition | Related global ADR(s) | May cite as decision authority? |
| --- | --- | --- | --- | --- |
| [MCP ADR-001](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md) | Thin Wrapper Pattern | **canonical-pointer** | [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md), [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | **Yes** (scoped) |
| [MCP ADR-002](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md) | Dual-Runtime Architecture | **canonical-pointer** | [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) (frames; does not supersede) | **Yes** (scoped) |
| [MCP ADR-003](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md) | Hierarchical Tool System | **canonical-pointer** | [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md), [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | **Yes** (scoped) |
| [MCP ADR-004](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-004-engine-extraction-pattern.md) | Engine Extraction Pattern | **canonical-pointer** | [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md), [ADR-006](../decisions/ADR-006-PROCESSOR-LAYERING.md) | **Yes** (scoped) |
| [MCP ADR-005](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-005-v6-coverage-hardening.md) | v6 Coverage Hardening | **refresh** | [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md), [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | After re-verify of dated metrics claims |
| [MCP ADR-006](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-006-mcp++-alignment.md) | MCP++ Specification Alignment | **refresh** | [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | After re-verify of profile readiness claims |

**Full disposition, non-actions, and collision rules:**
[MCP_ADR_RECONCILIATION.md](../decisions/MCP_ADR_RECONCILIATION.md).

**Must not:** copy package ADR bodies into `docs/architecture/decisions/` or
this directory; renumber package ADRs to “match” global numbers; treat static
coverage percentages inside ADRs as evergreen inventory.

**Always qualify:** “global ADR-00N” vs “package MCP ADR-00N” / full path.

---

## 7. Related global ADRs (product framing)

| Global ADR | Why it matters for MCP |
| --- | --- |
| [ADR-001](../decisions/ADR-001-CONTENT-IDENTITY-AND-PROVENANCE.md) | Content identity vs location; interface/artifact CIDs |
| [ADR-002](../decisions/ADR-002-LAZY-OPTIONAL-CAPABILITIES.md) | Optional extras stay lazy; hermetic import defaults |
| [ADR-003](../decisions/ADR-003-LAYERED-AUTHORITY.md) | Evidence ≠ proof ≠ policy ≠ authorization ≠ control plane |
| [ADR-004](../decisions/ADR-004-FAIL-CLOSED-DEGRADATION.md) | Degrade features; fail closed on trust |
| [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | One registry per concern; adapters are not engines |
| [ADR-006](../decisions/ADR-006-PROCESSOR-LAYERING.md) | Domain processor ownership vs thin MCP wrappers |
| [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | Canonical vs compatibility runtime product rule |

Decision hub: [decisions/README.md](../decisions/README.md).

---

## 8. Ownership and boundaries (summary)

| Owns (MCP layer) | Does not own |
| --- | --- |
| Protocol host, hierarchical discovery/dispatch, meta-tools | Domain algorithms (`processors`, `logic`, `embeddings`, …) |
| Transport adapters and interface descriptors | Content identity of domain artifacts (domain + storage) |
| Optional pre-dispatch policy attach point | Governed intent authorization algebra as a whole |
| Process metrics, health routes, event DAG hooks | Cluster-wide SLOs or SIEM product configuration |
| Fail-closed when MCP dependency missing for real run | Agent-supervisor leases / external orchestrators |

Domain ownership map: [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.3.
End-to-end Flow E (MCP → dispatch): [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md).
Process packaging map: [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8.

---

## 9. Component families and code anchors

| Family | Primary paths | Leaf authority |
| --- | --- | --- |
| Canonical server | `mcp_server/server.py`, `__main__.py`, `server_context.py` | SERVER_AND_DISPATCH |
| Hierarchical tools | `hierarchical_tool_manager.py`, `tools/` | TOOL_LIFECYCLE + SERVER_AND_DISPATCH |
| Metadata / validation | `tool_metadata.py`, `validators.py`, `tools/validators.py` | TOOL_LIFECYCLE |
| Transports | `fastapi_service.py`, `grpc_transport.py`, `mcp_p2p_transport.py`, `p2p_*` | INTERFACES_AND_TRANSPORTS |
| Dual-runtime | `trio_bridge.py`, `trio_adapter.py`, `runtime_router.py` | INTERFACES_AND_TRANSPORTS; package ADR-002 |
| Policy pipeline | `dispatch_pipeline.py`, `ucan_delegation.py`, `risk_scorer.py`, `temporal_policy.py`, `compliance_checker.py` | POLICY_AND_AUTHORIZATION |
| Observability | `event_dag.py`, `policy_audit_log.py`, `metrics.py`, `monitoring.py`, `otel_tracing.py`, `prometheus_exporter.py` | AUDIT_EVENTS_AND_OBSERVABILITY |
| Compat / simple | `simple_server.py`, `compat/`, import stubs in `__init__.py` | ADR-007; labeled degraded only |
| Optional MCP++ | `mcplusplus/`, Profile G (`profile_g_service.py`) | INTERFACES; package ADR-006 (refresh) |
| Config | `configs.py`, `fastapi_config.py`, YAML under package `config/` | RUNTIME_ENTRYPOINTS §8–§9 |

---

## 10. Documentation routes

### 10.1 Prefer these (authority chain)

| Need | Document |
| --- | --- |
| Architecture orientation | **This index** |
| Start / discover / probe / invoke / stop / recover | [MCP_SERVER_RUNBOOK.md](../../guides/operations/MCP_SERVER_RUNBOOK.md) |
| How the process starts and dispatches | [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) |
| How to add or name a tool | [TOOL_LIFECYCLE_AND_REGISTRIES.md](TOOL_LIFECYCLE_AND_REGISTRIES.md) |
| Stdio vs HTTP vs P2P / dual-runtime | [INTERFACES_AND_TRANSPORTS.md](INTERFACES_AND_TRANSPORTS.md) |
| Pre-dispatch allow/deny | [POLICY_AND_AUTHORIZATION.md](POLICY_AND_AUTHORIZATION.md) |
| Health, metrics, audit redaction | [AUDIT_EVENTS_AND_OBSERVABILITY.md](AUDIT_EVENTS_AND_OBSERVABILITY.md) |
| Which binary/module to run | [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8, §11 |
| Package ADR dispositions | [MCP_ADR_RECONCILIATION.md](../decisions/MCP_ADR_RECONCILIATION.md) |

### 10.2 Support / historical (not sole architecture)

| Material | Use as |
| --- | --- |
| [MCP_QUICKSTART.md](../../MCP_QUICKSTART.md), [guides/MCP_REFACTORING_QUICK_START.md](../../guides/MCP_REFACTORING_QUICK_START.md) | Developer onboarding examples |
| [MCP_TOOLS_GUIDE.md](../../MCP_TOOLS_GUIDE.md), catalogs under `docs/guides/` and `docs/architecture/mcp_tools_*` | Inventory / tutorial support — **date-check** before citing counts |
| [MCP_SYSTEMD_SETUP.md](../../guides/MCP_SYSTEMD_SETUP.md), dashboard guides | Ops examples for specific host layouts |
| [CLI_MCP_INTEGRATION_GUIDE.md](../../CLI_MCP_INTEGRATION_GUIDE.md) | CLI alignment support |
| Root status / phase / refactor reports | Historical campaign evidence only |

When support docs disagree with leaves or ADRs, prefer tests → implementation →
accepted ADRs → maintained leaves
([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

### 10.3 Operator surface

Safe local lifecycle (prerequisites, expected state, redaction, timeouts,
unavailable/degraded behavior, canonical vs simple/legacy):

**[MCP Server Operator Runbook](../../guides/operations/MCP_SERVER_RUNBOOK.md)**
(`MCPServerRunbook@1`).

---

## 11. Hierarchical product contract (one-page reminder)

Independent of how the process is started:

1. Discover categories → `tools_list_categories`
2. Discover tools → `tools_list_tools(category)`
3. Fetch schema → `tools_get_schema(category, tool)`
4. Execute → `tools_dispatch(category, tool, params)` → structured result dict

Optional hosts may attach `DispatchPipeline` **before** step 4; deny means the
tool body does not run. Optional observability records after or alongside —
never instead of — policy and dispatch success.

---

## 12. Extension and documentation obligations

1. New architecture claims about MCP go into the **owning leaf**, not a novel
   root README or competing hub.
2. Link new leaves from this index in §4; keep status and task IDs honest.
3. New package-local ADRs stay under `mcp_server/docs/adr/` and are indexed via
   [MCP_ADR_RECONCILIATION.md](../decisions/MCP_ADR_RECONCILIATION.md) + this
   §6 — do not fork bodies.
4. Operator procedure changes go in the runbook; architecture contracts stay
   in leaves.
5. Never publish undated tool/category counts as inventory authority.

---

## 13. Validation

```bash
# Index and leaves present
test -s docs/architecture/mcp/README.md
test -s docs/architecture/mcp/SERVER_AND_DISPATCH.md
test -s docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md
test -s docs/architecture/mcp/INTERFACES_AND_TRANSPORTS.md
test -s docs/architecture/mcp/POLICY_AND_AUTHORIZATION.md
test -s docs/architecture/mcp/AUDIT_EVENTS_AND_OBSERVABILITY.md
test -s docs/guides/operations/MCP_SERVER_RUNBOOK.md

# Package ADR bodies still at package path (not relocated by this index)
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md

# Index points at canonical leaves and ADR namespaces
rg -n 'SERVER_AND_DISPATCH|TOOL_LIFECYCLE|INTERFACES_AND_TRANSPORTS|POLICY_AND_AUTHORIZATION|AUDIT_EVENTS|package-local|simple_server|canonical' \
  docs/architecture/mcp/README.md
```

---

## 14. Related documents

| Document | Relationship |
| --- | --- |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.3 | Domain vs MCP ownership |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | Packaging and CLI/MCP start map |
| [SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md) | Product context |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) | Flow E MCP→dispatch |
| [INTEGRATION_BOUNDARIES.md](../INTEGRATION_BOUNDARIES.md) | Cross-package edges |
| [decisions/README.md](../decisions/README.md) | Global ADR index |
| [MCP_ADR_RECONCILIATION.md](../decisions/MCP_ADR_RECONCILIATION.md) | Package ADR dispositions |
| [MCP_SERVER_RUNBOOK.md](../../guides/operations/MCP_SERVER_RUNBOOK.md) | Operator lifecycle |
| [logic/GOVERNED_AUTHORIZATION.md](../logic/GOVERNED_AUTHORIZATION.md) | Separate governed auth stack |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Evidence ranking |

# ADR-007: MCP Runtime Compatibility (Canonical vs Compatibility)

| Field | Value |
| --- | --- |
| Interface | `MCPRuntimeCompatibilityDecision@1` |
| Task | `IPFSDOC-015` |
| Status | accepted |
| Date proposed | 2026-08-03 |
| Date accepted | 2026-08-03 |
| Decision owners | architecture; mcp-server maintainers |
| Consulted | documentation-governance; dual-runtime ADR authors |
| Source of truth | `ipfs_datasets_py/mcp_server/server.py`; `ipfs_datasets_py/mcp_server/__init__.py`; `ipfs_datasets_py/mcp_server/simple_server.py`; `ipfs_datasets_py/mcp_server/compat/`; `ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py`; `ipfs_datasets_py/mcp_server/tool_metadata.py`; `ipfs_datasets_py/mcp_server/trio_bridge.py`; package ADRs 001–006 under `ipfs_datasets_py/mcp_server/docs/adr/`; [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8 |
| Last verified | 2026-08-03 |
| Supersedes | none |
| Superseded by | none |
| Origin | Package ADR-002 dual-runtime; current server/compat/simple_server layout; DOMAIN_MAP mcp_server section |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

MCP is a primary product surface: AI clients and operators start a server,
discover tools, and dispatch into domain packages
([SYSTEM_CONTEXT.md](../SYSTEM_CONTEXT.md), [DOMAIN_MAP.md](../DOMAIN_MAP.md)
§4.3). Several **runtimes and fallbacks** coexist:

1. **Full MCP server** — `IPFSDatasetsMCPServer` / `start_stdio_server` /
   `start_server` in `mcp_server.server`, typically with FastMCP and FastAPI
   paths ([RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8).
2. **Dual async runtime (FastAPI/anyio + Trio)** — package
   [ADR-002](../../../ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md):
   tools written as portable `async def`; Trio opt-in via metadata and
   `trio_bridge` for structured concurrency / P2P-sensitive work.
3. **Compatibility layer** — `mcp_server/compat/` (shims, runtime detection,
   config migration, API versioning) for zero-break migration toward dual
   runtime.
4. **Simple / degraded server** — `simple_server.SimpleIPFSDatasetsMCPServer`
   and import-time fallbacks when the full MCP stack is unavailable
   (`mcp_server/__init__.py`).
5. **Optional MCP++ and legacy tool trees** — `mcplusplus/`,
   `tools/legacy_mcp_tools/`, optional transports (gRPC, P2P adapters).

Package-local ADRs already decide thin wrappers (001), dual-runtime (002),
hierarchy (003), engines (004), coverage/integrations (005), and MCP++ profiles
(006). Those **bodies remain canonical** in
`ipfs_datasets_py/mcp_server/docs/adr/` until IPFSDOC-016 indexes them. This
global ADR does **not** copy those bodies; it records the product-level rule for
**which surface is authoritative** when multiple runtimes exist, and the
strangler consequences of compatibility paths.

Without that rule, docs and agents treat `simple_server`, `compat`, and full
`server` as equal “the MCP architecture,” invent parallel tool inventories, or
present dual-runtime as unfinished theory despite production entry points.

## Decision

We will maintain a clear **canonical vs compatibility** split for MCP runtimes:

| Class | Surfaces | Authority |
| --- | --- | --- |
| **Canonical** | `python -m ipfs_datasets_py.mcp_server`; `IPFSDatasetsMCPServer`; `start_stdio_server` / `start_server` when full stack imports; hierarchical meta-tools (`tools_list_*`, `tools_dispatch`); thin tools under `mcp_server/tools/` delegating to domain engines | Preferred for new work, primary docs, and contract tests |
| **Dual-runtime design (accepted)** | anyio-portable tools; `RUNTIME_TRIO` / `tool_metadata`; `trio_bridge` / `trio_adapter`; FastAPI/HTTP and stdio hosts per package ADR-002 | Binding design for concurrency model of **full** server tools |
| **Compatibility / degraded** | `mcp_server/compat/*`; `SimpleIPFSDatasetsMCPServer` / `start_simple_server` fallbacks; `legacy_mcp_tools`; optional import stubs when `mcp` is missing | Supported for migration and reduced environments; **not** a second product architecture |
| **Optional extensions** | MCP++ profiles A–E modules; P2P registry adapters; gRPC/Prometheus/OTEL integrations (package ADR-005/006) | Opt-in; absence must not redefine the canonical tool contract |

We must not present compatibility or simple fallbacks as equal sources of truth
for tool inventory, dispatch semantics, or engine placement. We must not
duplicate package ADR decision bodies under `docs/architecture/decisions/`.

### Decision details

#### Canonical process and dispatch

1. **Process entry:** `__main__` / `start_stdio_server` (stdio default) and
   `start_server` (HTTP) on the full server class when dependencies allow.
2. **Dispatch contract:** hierarchical category → tool discovery and
   `HierarchicalToolManager.dispatch` (package ADR-003), shared with CLI
   dynamic tool runner ([RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md)
   §6–§8).
3. **Business logic:** thin wrappers only; engines in domain packages (package
   ADR-001/004; [ADR-005](ADR-005-REGISTRIES-AND-ADAPTERS.md),
   [ADR-006](ADR-006-PROCESSOR-LAYERING.md)).
4. **Dual-runtime:** new tools use anyio-compatible async primitives; mark Trio
   when required; do not hard-code `asyncio.sleep` / `trio.sleep` in shared
   tools (package ADR-002).

#### Compatibility surfaces (strangler)

| Surface | Purpose | Deprecation / limit |
| --- | --- | --- |
| `compat.CompatibilityShim` / `RuntimeDetector` | Keep existing tools working across FastAPI and Trio hosts | Opt-in enhancement; not a place for new domain features |
| `compat` config migration / API versioning | Config shape evolution | Must not invent a second tool registry |
| `simple_server` | Fallback when FastMCP / full stack missing | Document as degraded; do not extend as feature peer of full server |
| `__init__.py` import fallbacks | Package remains importable | Fail clearly when neither server works |
| `legacy_mcp_tools` | Historical tools | Compat inventory only; not preferred for new tools |
| Optional MCP++ / ecosystem adapters | Profiles and observability | Lazy/optional; graceful degradation (package ADR-005/006) |

#### Authority map (no duplicate SoT)

| Question | Authority |
| --- | --- |
| Why dual-runtime? | Package ADR-002 body |
| Why thin wrappers / engines? | Package ADR-001, ADR-004 |
| Why hierarchical meta-tools? | Package ADR-003 |
| Why MCP++ profiles? | Package ADR-006 |
| Which process to start in production docs? | This ADR + RUNTIME_ENTRYPOINTS: full server when available |
| Tool inventory | Live `mcp_server/tools/` + hierarchical manager — not static Markdown counts |
| Domain algorithms | Domain packages — not `compat/` or `simple_server` |

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| Single runtime only (asyncio or Trio) | Simpler mental model | Breaks MCP++/P2P Trio needs or FastAPI host reality | Rejected; package ADR-002 accepted dual-runtime |
| Promote `simple_server` to primary | Fewer deps | Incomplete protocol/tool surface | Rejected as canonical |
| Copy package ADRs into this file | One-stop reading | Duplicate SoT; drift; violates package-local map | Rejected; pointers only |
| Collapse compat into core with no labels | Cleaner tree diagram | Hides migration risk and degraded modes | Rejected |
| Document dual-runtime as “planned only” | Matches some old status banners | Contradicts current entry points and ADR-002 accepted | Rejected |

## Consequences

### Positive

- Operators and agents know which entry point is preferred and which is fallback.
- Package ADRs remain the detailed decision records; global ADR frames
  canonical vs compat without forking text.
- Strangler tools and shims can remain until call sites and hosts catch up.
- Aligns documentation program rules (no competing MCP architecture novels).

### Negative

- Multiple modules named “server” require careful doc labeling.
- Import-time fallbacks can surprise users who think they have full MCP when
  they have simple mode—docs must state degraded behavior.
- Dual-runtime discipline (anyio primitives) remains a training cost.

### Neutral / deferred

- **Strangler / deprecation consequences:**
  - Compatibility shims stay until dual-runtime coverage is universal for
    supported tools; new tools should not *require* compat wrappers if written
    to ADR-002 rules.
  - `legacy_mcp_tools` and ARCHIVE trees are historical; do not migrate archive
    prose into product authority.
  - `simple_server` remains for missing MCP deps; long-term removal only after
    packaging guarantees or an explicit superseding ADR.
  - MCP++ profiles remain optional; implementing a profile does not make
    `mcplusplus` the default process entry.
- IPFSDOC-016 will index package ADRs and this global series; numbering
  collision (global ADR-007 vs future package numbers) is namespace-scoped by
  path.
- Metric claims inside package ADR-005 are evidence-dated, not evergreen.

## Invariants

Rules that remain true while this ADR is `accepted`:

1. Preferred documented production entry is the **full** MCP server path when
   dependencies allow; simple/compat paths are labeled degraded or transitional.
2. Tool business logic remains outside MCP runtime modules (engines/domains).
3. Dual-runtime tools use portable async (anyio) unless explicitly Trio-marked
   per package ADR-002.
4. Compatibility modules do not define a second hierarchical tool inventory
   authority.
5. Package-local MCP ADR bodies under `mcp_server/docs/adr/` are not rewritten
   or fully copied into `docs/architecture/decisions/` by this decision.
6. Optional integrations degrade gracefully; missing optional packages must not
   redefine the core dispatch contract as failed-open authorization.

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

```bash
# Canonical exports and fallbacks are explicit
rg -n "IPFSDatasetsMCPServer|start_stdio_server|simple_server|start_simple" \
  ipfs_datasets_py/mcp_server/__init__.py

# Dual-runtime primitives still present
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-002-dual-runtime.md
rg -n "RUNTIME_TRIO|RUNTIME_FASTAPI" ipfs_datasets_py/mcp_server/tool_metadata.py
test -s ipfs_datasets_py/mcp_server/trio_bridge.py

# Compat package remains a labeled compatibility layer
test -s ipfs_datasets_py/mcp_server/compat/__init__.py
rg -n "CompatibilityShim|backward compatibility|dual-runtime" \
  ipfs_datasets_py/mcp_server/compat/__init__.py

# Hierarchical dispatch remains the meta-tool path
rg -n "class HierarchicalToolManager|async def dispatch" \
  ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py

# Package ADR bodies not duplicated as full copies here (pointer check)
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-006-mcp++-alignment.md
```

Narrative compliance criteria:

1. Runtime entrypoint docs list full server first; simple_server as fallback.
2. Architecture prose that describes only FastAPI or only Trio without anyio
   dual-runtime is incomplete relative to package ADR-002.
3. New tools are added under `mcp_server/tools/<category>/` as thin wrappers,
   not under `compat/` or `simple_server`.
4. Tool counts in guides are re-measured or marked evidence-dated.

## Scope

### Applies to

- MCP server process entry, dual-runtime tool execution model, and compatibility
  fallbacks inside `ipfs_datasets_py/mcp_server/`.
- Product architecture documentation that explains MCP hosts and runtimes.
- Relationship of optional MCP++ and ecosystem transports to the core server.

### Does not apply to

- Domain algorithm design inside processors/logic (ADR-005/006 and domain ADRs).
- Third-party MCP host products (VS Code, Claude Desktop) configuration details
  beyond entry commands.
- Agent-supervisor runtimes in other packages.
- Rewriting package-local ADR files or creating `docs/architecture/decisions/README.md`
  (IPFSDOC-016).

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| Package ADR-002 dual-runtime | Decision body for FastAPI + Trio via anyio |
| Package ADR-001 / 003 / 004 | Thin tools, hierarchy, engines |
| Package ADR-005 / 006 | Coverage/integrations; MCP++ profiles |
| [ADR-005-REGISTRIES-AND-ADAPTERS.md](ADR-005-REGISTRIES-AND-ADAPTERS.md) | Tool/processor discovery SoT |
| [ADR-006-PROCESSOR-LAYERING.md](ADR-006-PROCESSOR-LAYERING.md) | Where processor engines live |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) §8 | Operator entry map |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.3 | mcp_server domain ownership |
| [END_TO_END_DATA_FLOW.md](../END_TO_END_DATA_FLOW.md) Flow E | Request hop narrative |
| `mcp_server/compat/README.md` | Compat layer exposition |
| `mcp_server/docs/architecture/dual-runtime.md` | Package architecture narrative (refresh-and-surface; ADR outranks on conflict) |

## Notes / errata

- **2026-08-03:** Global ADR-007 does not supersede package ADR-002; it
  *frames* canonical vs compatibility around that accepted dual-runtime
  decision and the simple/compat fallbacks in the current tree.
- Historical package architecture pages may still say “Phase N complete” with
  checkmarks; treat phase banners as historical unless re-verified against
  code and tests ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Proposed and accepted as IPFSDOC-015 artifact (`MCPRuntimeCompatibilityDecision@1`) |

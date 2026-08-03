# ADR-005: Registries and Adapters

| Field | Value |
| --- | --- |
| Interface | `RegistryAdapterDecision@1` |
| Task | `IPFSDOC-015` |
| Status | accepted |
| Date proposed | 2026-08-03 |
| Date accepted | 2026-08-03 |
| Decision owners | architecture; documentation-governance |
| Consulted | mcp-server package ADR authors; processors maintainers |
| Source of truth | `ipfs_datasets_py/processors/core/registry.py`; `ipfs_datasets_py/processors/adapters/`; `ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py`; `ipfs_datasets_py/mcp_server/tool_registry.py`; `ipfs_datasets_py/logic/submodule_registry.py`; package-local MCP ADRs 001/003/004 under `ipfs_datasets_py/mcp_server/docs/adr/` |
| Last verified | 2026-08-03 |
| Supersedes | none |
| Superseded by | none |
| Origin | Current-tree registry/adapter practice; package MCP ADRs 001–004; [DOMAIN_MAP.md](../DOMAIN_MAP.md); [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) |

> **Status discipline:** Change `Status` deliberately. Once `accepted`, do not
> edit the Decision to mean something else—supersede with a new ADR instead.
> Editorial fixes (typos, dead links) are allowed; behavioral meaning is not.

## Context

The product exposes a large set of processors, MCP tools, logic submodules, and
optional backends. Callers need **discovery** (what exists and how it is
addressed) without embedding every implementation’s dependency graph into every
entry path. Two complementary patterns already appear throughout the tree:

1. **Registries** — machine-readable catalogs of named capabilities, categories,
   or submodules, with priority, metadata, and optional lazy import.
2. **Adapters** — thin conformance layers that wrap an existing domain engine so
   it satisfies a shared protocol (for example `ProcessorProtocol`) without
   re-implementing business logic.

Package-local MCP ADRs already encode related rules for the tool surface:

| Package ADR | Decision body | Relevance |
| --- | --- | --- |
| ADR-001 thin wrapper | `ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md` | Tools delegate to engines; no second business-logic home |
| ADR-003 hierarchical tools | `…/ADR-003-hierarchical-tool-system.md` | Category → tool registry and meta-tool discovery |
| ADR-004 engine extraction | `…/ADR-004-engine-extraction-pattern.md` | Canonical engine locations; MCP files are shims |

Without a product-level decision, agents and contributors invent parallel
registries, document static tool counts as authority, or put algorithms inside
adapters. That creates **duplicate sources of truth** and breaks
[SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) (discovery vs
capability; canonical vs compat).

This ADR records the pattern **as implemented**, including strangler-era dual
modules—not an idealized greenfield design.

## Decision

We will treat **one registry per concern** as the discovery authority for that
concern, and we will use **adapters only as protocol bridges** to domain engines.
We must not introduce a second registry, catalog document, or adapter layer as a
competing source of truth for the same names, schemas, or algorithms.

### Decision details

#### Registries (discovery authority)

| Concern | Canonical registry / manager | Role |
| --- | --- | --- |
| Processor plugins (unified system) | `ipfs_datasets_py.processors.core.registry` (`ProcessorRegistry`, `get_global_registry`) | Register `ProcessorProtocol` implementations; priority and capability routing |
| MCP hierarchical tools | `HierarchicalToolManager` + tool tree under `mcp_server/tools/` | Category/tool discovery, schema cache, `dispatch` |
| MCP tool object model | `mcp_server.tool_registry` (`ClaudeMCPTool`, wrappers) | Schema/usage patterns for class-style tools |
| Logic topology | `logic.submodule_registry` (`logic_submodule_specs`, `logic_integration_manifest`) | Machine-readable submodule map; import checks without heavy deps |
| MCP++ peers / services | `mcplusplus.peer_registry`, `service_registry`, `p2p_mcp_registry_adapter` | Optional peer/service discovery (not domain algorithms) |

Rules:

1. **Discovery ≠ capability.** A registered name means the implementation is
   addressable if dependencies allow; it does not assert that optional backends
   or extras are installed ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)
   §2).
2. **Registry modules own names and selection policy** for their concern.
   Domain packages own algorithms and schemas.
3. **Deprecation shims** (for example `processors.registry` re-exporting
   `processors.core.registry`) are **compat only**. New code must import the
   canonical module. Shims must warn and must not diverge behavior.
4. Static Markdown catalogs (tool counts, phase completion lists) are
   **not** registries. They may describe or point; they must not define
   inventory independently of code.

#### Adapters (protocol bridges)

| Adapter home | Pattern | Must not |
| --- | --- | --- |
| `processors/adapters/*` | Wrap specialized/domain processors into `ProcessorProtocol`; optional `auto_register.register_all_adapters` | Re-implement PDF/GraphRAG/media logic; invent a second processor API |
| MCP `tools/*` thin wrappers | Import engine; validate; delegate (package ADR-001) | Inline HTTP/DB/heavy transforms as the product logic home |
| Logic IR source adapters (`logic.intent_ir.source_adapters`, legal/security formalization adapters) | Map source shapes into IR/formal views without executing tools | Execute hostile content; own domain authority of another IR family |
| Integration adapters (embedding, GraphRAG, config, P2P registry) | Bridge packages or optional stacks | Become a silent second implementation of the domain |

Rules:

1. Adapters **delegate** to a single canonical engine or domain API
   (package ADR-004 locations where applicable).
2. Optional dependency failures degrade **registration or import**, not by
   copying a stub algorithm into the adapter as a second truth.
3. Adapter auto-registration feeds the **canonical** processor registry, not a
   parallel map.

#### Rejected: duplicate sources of truth

We explicitly reject:

- Maintaining both a “docs registry” and a code registry as equal inventory.
- A second global `ProcessorRegistry` implementation that new work targets while
  `core.registry` remains live (strangler shims may re-export only).
- Putting business logic in MCP tools **and** in adapters without a single
  engine owner.
- Treating `logic.tools` (deprecated compatibility) as equal to
  `logic.integration` for new work ([DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.2).

## Alternatives considered

| Alternative | Pros | Cons | Why not chosen |
| --- | --- | --- | --- |
| Flat hard-coded import tables only | Simple for tiny surfaces | Does not scale; no priority/capability; poor agent discovery | Rejected for processors and MCP tool volume |
| Docs/Markdown as tool or processor inventory | Easy to edit | Drifts from code; false discovery | Rejected as authority; OK as regenerated exposition |
| Fat adapters that own algorithms | Faster local hacks | Duplicates engines; breaks ADR-001/004 | Rejected |
| Multiple competing registries per concern | Incremental isolation | Name collisions; dual policy | Rejected; one registry + deprecation shims only |
| Do nothing (implicit practice) | No writing cost | Agents re-invent patterns; SoT drift | Rejected; must be explicit for documentation program |

## Consequences

### Positive

- Agents and humans know where discovery is authoritative per concern.
- Thin wrappers and adapters stay small; engines remain unit-testable without MCP.
- Strangler migrations can re-export through shims without forking policy.
- Aligns product documentation with package MCP ADRs without copying their bodies
  (IPFSDOC-016 indexes/reconciles).

### Negative

- Contributors must learn which registry owns which concern.
- Deprecation warnings and dual import paths add noise until shims are removed.
- Optional registration means “not in registry” can mean missing extra **or**
  not yet registered—docs must not collapse those cases.

### Neutral / deferred

- **Strangler / deprecation:** `processors.registry` warns and redirects to
  `processors.core.registry` (removal target documented in that shim as v2.0.0 /
  August 2026 era). Root-level processor modules and dual protocol files remain
  during the mixed layout; see [ADR-006](ADR-006-PROCESSOR-LAYERING.md).
- **Index reconciliation:** package-local MCP ADR numbers (001–006 under
  `mcp_server/docs/adr/`) are a **separate namespace** from this global
  `docs/architecture/decisions/` series. IPFSDOC-016 owns the index and
  pointer map; this ADR must not duplicate package ADR bodies.
- Full deletion of legacy registry modules is a code task, not this ADR.

## Invariants

Rules that remain true while this ADR is `accepted`:

1. For each concern in the registry table above, there is **one** canonical
   discovery module (or hierarchical manager) for new work.
2. Adapters and MCP tools do not become the canonical home of domain algorithms.
3. Compatibility shims re-export or wrap; they do not fork selection policy or
   schemas.
4. Registered discovery never implies optional capability or production
   authorization.
5. New documentation must not invent a parallel inventory that contradicts the
   live registry or tool tree without labeling it historical or generated.

Violating an invariant requires a new ADR (or explicit supersession), not a
quiet code change.

## Compliance and validation

How reviewers and agents check that the codebase still honors this decision:

```bash
# Canonical processor registry vs deprecation shim
rg -n "deprecated|core\.registry|ProcessorRegistry" \
  ipfs_datasets_py/processors/registry.py \
  ipfs_datasets_py/processors/core/registry.py

# Adapters register into core registry, not a parallel map
rg -n "get_global_registry|register_all_adapters|ProcessorProtocol" \
  ipfs_datasets_py/processors/adapters/

# Logic topology registry remains import-light and machine-readable
rg -n "LogicSubmoduleSpec|logic_integration_manifest|deprecated" \
  ipfs_datasets_py/logic/submodule_registry.py

# MCP hierarchical discovery remains the dispatch entry for category/tool
rg -n "class HierarchicalToolManager|async def dispatch" \
  ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py

# Package ADR bodies still exist (do not recreate under docs/architecture/decisions)
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-001-thin-wrapper-pattern.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-003-hierarchical-tool-system.md
test -s ipfs_datasets_py/mcp_server/docs/adr/ADR-004-engine-extraction-pattern.md
```

Narrative compliance criteria:

1. New processor plugins implement `ProcessorProtocol` (or wrap via adapters)
   and register with `processors.core.registry` / `get_global_registry`.
2. New MCP tools are thin wrappers over domain engines (package ADR-001/004).
3. Docs that list tools or processors cite code/registry evidence or mark counts
   as evidence-dated, not evergreen authority.
4. No new “global registry” package is introduced for a concern that already has
   one without superseding this ADR.

## Scope

### Applies to

- Processor discovery and adapter registration.
- MCP tool discovery, hierarchical dispatch, and thin wrappers.
- Logic submodule topology registry and deprecated `logic.tools` compatibility.
- Optional MCP++ peer/service registries as discovery only.
- Architecture and developer documentation that describe discovery.

### Does not apply to

- Choosing specific prover, vector, or embedding **backends** (routers and
  packaging extras; separate capability decisions).
- Authorization / admissibility policy truth (`logic.admissibility`, wallet).
- Agent-supervisor IR registries in `ipfs_accelerate_py` (external package;
  may mirror patterns but is out of this repo’s ownership).
- Creating or rewriting package-local MCP ADR bodies (IPFSDOC-016 index only).

## Related artifacts

| Artifact | Relationship |
| --- | --- |
| [ADR-006-PROCESSOR-LAYERING.md](ADR-006-PROCESSOR-LAYERING.md) | Root/core layout; where registry lives during strangler |
| [ADR-007-MCP-RUNTIME-COMPATIBILITY.md](ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | Canonical MCP server vs compat runtimes that consume registries |
| Package ADR-001 / 003 / 004 | Decision bodies for thin wrappers, hierarchy, engines |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Domain ownership for engines vs MCP |
| [RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md) | How CLI/MCP invoke registered tools |
| [SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md) | Discovery vs capability; ADR rank |
| `processors/adapters/auto_register.py` | Adapter → registry registration |
| `logic/submodule_registry.py` | Logic topology authority |

## Notes / errata

- **2026-08-03:** Global ADR numbers 005–007 are independent of package-local
  MCP ADR-005 (v6 coverage) and ADR-006 (MCP++ alignment). Do not merge bodies;
  reconcile via IPFSDOC-016.
- Tool and category **counts** in historical package docs and dual-runtime
  sketches are evidence-dated; re-measure from `mcp_server/tools/` and
  `HierarchicalToolManager` before citing.

## Document history

| Date | Change |
| --- | --- |
| 2026-08-03 | Proposed and accepted as IPFSDOC-015 artifact (`RegistryAdapterDecision@1`) |

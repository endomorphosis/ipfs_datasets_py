# MCP tool lifecycle and registries

| Field | Value |
| --- | --- |
| Interface | `MCPToolLifecycle@1` |
| Task | `IPFSDOC-050` |
| Status | `canonical` |
| Owner | architecture; mcp-server |
| Source of truth | `ipfs_datasets_py/mcp_server/tools/`; `hierarchical_tool_manager.py`; `tool_metadata.py`; `tool_registry.py`; `tools/tool_wrapper.py`; `tools/tool_registration.py`; `tools/validators.py`; `validators.py`; package ADRs 001/003/004; [ADR-005-REGISTRIES-AND-ADAPTERS.md](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md); [DOMAIN_MAP.md](../DOMAIN_MAP.md) §4.3 |
| Last verified | 2026-08-03 |
| Audience | developer, architect, agent |
| Related | [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md); transports (IPFSDOC-051) |
| Review cadence | after tool tree layout, metadata schema, or registry API changes |

## 1. Purpose

This guide answers: **how an MCP tool moves from implementation through
category ownership, registration/discovery, metadata, validation, naming,
dispatch envelopes, aliases, and unavailability** — without treating undated
tool counts or static catalogs as inventory authority.

Server process startup, the four meta-tools, caches, circuit breakers, and
pipelines: [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md).

## 2. Audience

- **Primary:** developers adding or refactoring tools under `mcp_server/tools/`
- **Secondary:** agents generating tools; reviewers checking thin-wrapper
  compliance

## 3. Scope and non-goals

### In scope

- Tool tree layout and root modules under `mcp_server/tools/`
- Category ownership and hierarchical vs flat naming
- Discovery rules (which files/functions become tools)
- `ToolMetadata` / registries and validation
- Integrated hierarchical dispatch contract vs legacy/class registries
- Result envelopes, duplicates, aliases, unavailable tools
- How to add a tool correctly

### Non-goals

- Transport-specific capability matrices (IPFSDOC-051)
- Exhaustive per-tool reference catalogs
- Domain algorithm design (belongs in domain packages)
- Embedding **undated** tool or category counts as authority

## 4. Lifecycle overview

```text
  [1] Domain capability exists
        (processors / logic / embeddings / …)
           │
           v
  [2] Thin tool module under tools/<category>/<tool>.py
        optional @tool_metadata(...); public async/sync function
           │
           v
  [3] Category directory owned by HierarchicalToolManager
        discover_categories → discover_tools (lazy import)
           │
           v
  [4] Client discovery
        tools_list_categories → tools_list_tools → tools_get_schema
           │
           v
  [5] Validation (signature filter + optional EnhancedParameterValidator
        + tool-local checks + optional DispatchPipeline)
           │
           v
  [6] tools_dispatch → domain call → result dict envelope
           │
           v
  [7] Transport wrap (stdio FastMCP / HTTP content / helpers)
```

**Architecture rule (ADR-001 / ADR-004):** business logic lives in domain
packages. MCP modules are thin wrappers and shims. Do not re-home algorithms
inside tool files or adapters ([ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)).

---

## 5. Category ownership and tree layout

### 5.1 Discovery root

Canonical tools root:

```text
ipfs_datasets_py/mcp_server/tools/
├── __init__.py              # lazy subpackage map; no eager category imports
├── <category>_tools/        # one directory per hierarchical category
│   ├── __init__.py
│   ├── category.json        # optional description metadata
│   └── *.py                 # tool modules (non-_ stem → discoverable)
├── root helper modules      # not categories (see §6)
└── legacy / special dirs    # compat ownership (§11)
```

`HierarchicalToolManager.discover_categories()`:

- Iterates **directories** under `tools_root`
- Skips names starting with `_`
- Reads optional `category.json` → `description`
- Does **not** import tool modules until that category is first used

Declared subpackage names in `tools/__init__.py` (`_TOOL_SUBMODULES`) keep
`from ipfs_datasets_py.mcp_server.tools import dataset_tools` cheap via
`__getattr__` lazy import — they are a **package surface map**, not a second
runtime registry. Hierarchical discovery is directory-based and may include
categories not listed in `_TOOL_SUBMODULES` if present on disk.

### 5.2 Who owns what

| Concern | Owner |
| --- | --- |
| Hierarchical name `(category, tool)` | `HierarchicalToolManager` + category directory |
| Tool function implementation | Category module under `tools/<category>/` |
| Domain algorithm / schema | Domain package (`processors`, `logic`, …) |
| Runtime/priority/P2P metadata | `ToolMetadataRegistry` / `@tool_metadata` |
| Protocol registration of meta-tools | `IPFSDatasetsMCPServer.register_tools` |
| Class-style object registry | `tool_registry.ToolRegistry` / `tools.tool_registration.MCPToolRegistry` (**compat / migration**) |

**One registry per concern** ([ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md)):
do not invent a parallel catalog document as competing authority for live
dispatch names.

### 5.3 Tool discovery within a category

`ToolCategory.discover_tools()` (once per category):

| Include | Exclude |
| --- | --- |
| `*.py` files not starting with `_` | `__init__.py`, private modules |
| Public functions (`inspect.isfunction`, name not starting with `_`) | Imported helpers that do not match discovery heuristics |
| Prefer function name equal to module stem or containing the stem | Silent skip of modules that fail import (warning log) |

Failed imports (missing optional deps) leave that module’s tools **unavailable**
for this process while other modules in the category may still load.

---

## 6. Root tool modules

Files directly under `mcp_server/tools/` (not category directories) are
**shared infrastructure**, not hierarchical categories:

| Module | Role |
| --- | --- |
| `__init__.py` | Lazy subpackage exports; avoids eager optional deps |
| `tool_wrapper.py` | `EnhancedBaseMCPTool` / `wrap_function_as_tool` for class-style tools |
| `tool_registration.py` | `MCPToolRegistry` + static `TOOL_MAPPINGS` for migration-era bulk wrap |
| `validators.py` | Re-export bridge to parent `mcp_server.validators` |
| `mcp_helpers.py` | Legacy test envelopes (`content`/`text` JSON) |
| `fastapi_integration.py` | FastAPI-oriented integration helpers |
| `ipfs_embeddings_integration.py` | Embeddings stack bridge |
| `logic_admissibility_tools.py` / `logic_admissibility_enforcement.py` / `logic_hammer.py` | Logic/admissibility surface helpers |
| `mcplusplus_peer_tools.py` / `mcplusplus_taskqueue_tools.py` / `mcplusplus_workflow_tools.py` | MCP++ peer/queue/workflow entry helpers |
| `TOOLS_IMPROVEMENT_PLAN_2026.md` | Historical plan (not runtime authority) |

Category packages such as `mcplusplus/` (directory) are hierarchical
categories; the root `mcplusplus_*.py` helpers are separate entry modules.

Do **not** place a new domain tool as a lone root-level `.py` if it should be
dispatchable via `(category, tool)` — put it in a category directory.

---

## 7. Flat vs hierarchical naming

### 7.1 Hierarchical (canonical)

| Form | Example | Used by |
| --- | --- | --- |
| Meta-tool parameters | `category="dataset_tools"`, `tool="load_dataset"` | `tools_list_tools`, `tools_get_schema`, `tools_dispatch` |
| Path string in logs/cache | `dataset_tools/load_dataset` | Dispatch logs, result cache keys, intent tool field in traces |

### 7.2 Flat (compatibility / discovery)

| Form | Example | Used by |
| --- | --- | --- |
| Dotted name | `dataset_tools.load_dataset` | FastAPI flat descriptor list; `_dispatch_hierarchical_flat_tool` |
| Bare function name | `load_dataset` | Local module; **not** globally unique across categories |

Flat names are **aliases** into hierarchical dispatch, not a separate tool
registry. Schema at list time for flat descriptors is intentionally minimal
(`{"type":"object"}`); full schemas come from `tools_get_schema`.

### 7.3 CLI alignment

Repository CLI dynamic runners import
`ipfs_datasets_py.mcp_server.tools.<category>.<tool>` — the **same tree** as
hierarchical MCP ([RUNTIME_ENTRYPOINTS.md](../RUNTIME_ENTRYPOINTS.md)). Prefer
identical category and module stem names across CLI and MCP.

---

## 8. Metadata system

### 8.1 `ToolMetadata` (`tool_metadata.py`)

Immutable dataclass fields (selected):

| Field | Role |
| --- | --- |
| `name` | Tool identity |
| `runtime` | `fastapi` \| `trio` \| `auto` |
| `requires_p2p` | Prefer Trio / P2P-capable host |
| `category` | Logical category label |
| `priority` | Scheduling/priority hint |
| `timeout_seconds` | Execution budget |
| `retry_policy` | `none` / fixed / exponential / … |
| `memory_intensive` / `cpu_intensive` / `io_intensive` | Placement hints |
| `mcp_schema` / `mcp_description` | Optional MCP-facing docs |
| `cache_ttl` | Opt-in result cache TTL (seconds); `None` disables |
| `schema_version` | Public schema contract version |
| `deprecated` / `deprecation_message` | Soft deprecation on invoke |

Decorator `@tool_metadata(...)` attaches metadata to the function
(`_mcp_metadata`) and registers with the process metadata registry.

`ToolMetadata.validate_complete()` returns **warnings** (missing description
or schema, P2P+FastAPI mismatch) — not hard registration failures.

### 8.2 `ToolMetadataRegistry`

Indexes tools by name, runtime, and category. Re-registration with a different
runtime logs a warning. Used by dual-runtime routing and hosts that query
metadata without importing every tool body.

`ServerContext` creates a registry on enter; global helpers (`get_registry`)
remain for decorator-time registration.

### 8.3 Class-style schemas (`ClaudeMCPTool` / wrappers)

`tool_registry.ClaudeMCPTool` and `tools.tool_wrapper.EnhancedBaseMCPTool`
provide:

- `input_schema` JSON schema
- `get_schema()` name/description/category/tags/version
- `execute` / `run` with usage counters (and optional local cache on enhanced base)

These integrate with **object registries** (below). Hierarchical discovery
primarily targets **module functions**; class tools are typically wrapped to
callables or registered via migration maps.

---

## 9. Validation

Validation is layered; not every layer runs for every tool.

| Layer | Where | What |
| --- | --- | --- |
| **Signature filter** | `HierarchicalToolManager.dispatch` | Keeps only kwargs present in the function signature |
| **Type/value errors** | Dispatch catch of `TypeError`/`ValueError` | Error envelope `Invalid parameters` |
| **EnhancedParameterValidator** | `mcp_server.validators` (re-exported as `tools.validators`) | Shared validators for text, CID/IPFS hashes, URLs, models, collections, paths; validation result cache |
| **Tool-local** | Individual tool modules | Domain-specific checks; often return `status=error` dicts |
| **Class tool schema** | `ToolRegistry.validate_tool_parameters` | Against `input_schema` when using object registry |
| **Pre-dispatch pipeline** | Optional `DispatchPipeline` on server | Policy/compliance/risk gates before execution |
| **Metadata completeness** | `ToolMetadata.validate_complete` | Soft warnings for authors |

Security note: server error reporting sanitizes kwargs (keys matching
token/password/secret patterns redacted) before external reporting.

---

## 10. Registries: integrated hierarchical vs legacy

### 10.1 Integrated hierarchical (canonical)

| Component | Path | Role |
| --- | --- | --- |
| `HierarchicalToolManager` | `hierarchical_tool_manager.py` | Category map, lazy load, schema cache, dispatch |
| `ToolCategory` | same | Per-directory tool dict + metadata + schema cache |
| Meta-tools | same | Protocol-facing four tools |
| `IPFSDatasetsMCPServer.tools` | `server.py` | Only meta-tools (+ optional extended), not every tool |

This is the **live lifecycle** for AI clients and CLI dynamic runners that
share the tools tree.

### 10.2 Legacy and compatibility registries

| Component | Role | Authority |
| --- | --- | --- |
| `import_tools_from_directory` + `_register_tools_from_subdir` | Flat FastMCP registration of every function | **Legacy helper**; not the default `register_tools` path |
| `tool_registry.ToolRegistry` | In-memory class-tool map with categories/tags/stats | Compat / Claudestyle object model |
| `tools.tool_registration.MCPToolRegistry` + `TOOL_MAPPINGS` | Migration registration from fixed maps | Compat; overwrites on name collision with warning |
| `tools/legacy_mcp_tools/` | Older tool implementations retained for reference/migration | **Compat category**; do not treat as preferred for new tools |
| `simple_server` | Deprecated Flask-oriented host | Compat; not canonical |
| `mcp_server/compat/` | Dual-runtime shims, detection, config migration | Compat for FastAPI↔Trio migration |

New tools must enter the **hierarchical category tree**. Do not add only a
`TOOL_MAPPINGS` entry without a discoverable category module.

### 10.3 Integrated vs legacy dispatch (summary)

| | Integrated hierarchical | Legacy / alternate |
| --- | --- | --- |
| Address | `(category, tool)` or flat `category.tool` | Bare name on FastMCP flat list; class registry name |
| Load | Lazy per category | Often eager import of directory or mapping |
| Schema | On demand + schema cache | Up-front tool schema objects |
| Execution | `manager.dispatch` | Direct callable / `registry.execute_tool` |
| Pipeline | Optional server pipeline around dispatch | Stage list if host wires it |
| Result | Dict envelope + `request_id` | Dict or MCP `CallToolResult` depending on host |

---

## 11. Result envelopes

### 11.1 Hierarchical dispatch dict (canonical tool return path)

After `tools_dispatch` / `manager.dispatch`:

| Pattern | Fields |
| --- | --- |
| Success (dict tool) | Tool’s own keys; `request_id` set if missing |
| Success (non-dict tool) | `status=success`, `result=<str>`, `request_id` |
| Not found | `status=error`, `error`, optional availability lists, `request_id` |
| Execution error | `status=error`, `error`, `category`, `tool`, `request_id` |
| Cache hit | Prior success payload + `_cached=true` + `request_id` |
| Traced | Same as success/error plus `trace` / `_trace` (CID envelope) |

Tools should prefer returning **dicts** with a clear `status` for agent
readability. Domain-specific success shapes are allowed; hosts must not
require a single universal schema for all categories.

### 11.2 Transport and helper envelopes

| Helper | Envelope |
| --- | --- |
| FastAPI `_mcp_tool_result` | `content` text JSON, `structuredContent`, `isError` |
| `mcp_helpers.mcp_text_response` | `content: [{type:text, text: json}]` |
| `mcp_helpers.mcp_error_response` | Same wrap around `status=error` payload |
| `utils.return_tool_call_results` | MCP SDK `CallToolResult` |

### 11.3 Deprecation envelope behavior

Deprecated tools (`ToolMetadata.deprecated=True`) still execute; dispatch logs
a warning with `deprecation_message`. Prefer documenting replacements in that
message rather than hard-removing names without a migration path.

---

## 12. Duplicates and aliases

| Situation | Behavior / rule |
| --- | --- |
| Same stem in two categories | Two hierarchical tools; flat names differ by category prefix |
| Re-register class tool same name | `MCPToolRegistry` warns and overwrites |
| Meta-tool name collision | Avoid; meta-tools own `tools_*` prefix |
| Flat vs hierarchical | Alias only — one implementation |
| `tools.validators` vs `mcp_server.validators` | Import alias (re-export) |
| `ParameterValidator` | Alias of `EnhancedParameterValidator` |
| Global tool manager singleton | Alias/compat for `ServerContext.tool_manager` |
| Function name ≠ module stem | May still be discovered if stem appears in function name; prefer matching stem for CLI/MCP alignment |
| Duplicate FastMCP registration of all tools | **Removed** on canonical path to cut startup cost and duplicate surfaces |

When docs or tests disagree on names, prefer live discovery + code over
historical catalogs ([SOURCE_AUTHORITY.md](../../maintenance/SOURCE_AUTHORITY.md)).

---

## 13. Unavailable tools

| Cause | Discovery | Dispatch |
| --- | --- | --- |
| Module import fails (optional dep) | Tool absent from category list for this process | N/A |
| Category directory missing | Category not listed | Category-not-found error |
| Function private (`_name`) | Not discovered | N/A |
| Backend/extra missing inside tool | Tool may still list | Tool returns error (“unavailable”, ImportError message, etc.) |
| Circuit breaker OPEN (if host wraps) | Listed | Immediate error dict with `circuit_state` |
| Pipeline deny | Listed | Error without execution |
| Server shutdown | — | Reject new dispatches |
| `mcp` package missing | Meta-tools may not register | Fail closed on real MCP run |

**Policy for authors:** degrade with structured `status=error` and a clear
message; do not raise uncaught exceptions for expected missing extras when a
dict error is sufficient. Do not claim capability success solely because a
name appeared in `tools_list_tools`.

---

## 14. How to add a tool (checklist)

1. **Confirm domain ownership** — implement capability in the domain package if
   missing; tool file only wraps it.
2. **Choose category directory** — existing `tools/<category>/` matching the
   concern; create directory + optional `category.json` if new category is
   justified.
3. **Add module** — `tools/<category>/<tool_name>.py` with a public function
   preferably named `<tool_name>`.
4. **Optional metadata** — `@tool_metadata(runtime=..., category=..., cache_ttl=..., schema_version=...)`.
5. **Return a dict** with success/error clarity; document parameters in the
   docstring (first line becomes list description).
6. **Do not** register the function on FastMCP individually on the canonical
   server; hierarchical discovery picks it up.
7. **Validate** with meta-tools or unit tests that import the module and call
   the function; exercise missing-extra paths.
8. **CLI** — if exposed via dynamic runner, ensure import path
   `...tools.<category>.<tool>` works.
9. **Never** update undated count tables as the source of truth; regenerate or
   date inventories in dedicated catalog tasks if required.

---

## 15. Schema and result caches (tool-facing)

| Cache | Scope | Invalidation |
| --- | --- | --- |
| Schema cache | Per `ToolCategory` | `clear_schema_cache()`; category clear on graceful shutdown |
| Result cache | Manager-wide `ResultCache` | TTL from metadata; LRU at backend max size |
| Validation cache | `EnhancedParameterValidator` | Process lifetime of validator instance |
| Flat descriptor cache | FastAPI module globals | Process lifetime until process restart |

Details and circuit breaker notes:
[SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) §9.

---

## 16. Ownership and boundaries

| Owns | Does not own |
| --- | --- |
| Tool module layout, hierarchical names, thin wrappers | Domain algorithms and IR schemas |
| Tool metadata decorator/registry | Product processor plugin registry |
| Category-level discovery rules | Agent orchestration / supervisor leases |

**Inbound:** meta-tools, flat HTTP dispatch, CLI dynamic runner, tests.

**Outbound:** domain packages, optional network/backends, shared validators.

---

## 17. Validation

```bash
test -s docs/architecture/mcp/SERVER_AND_DISPATCH.md
test -s docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md

rg -n 'meta-tool|lazy|hierarch|schema|cache|circuit|dispatch|compat' \
  docs/architecture/mcp/SERVER_AND_DISPATCH.md \
  docs/architecture/mcp/TOOL_LIFECYCLE_AND_REGISTRIES.md

# Structural smoke (optional)
python -c "
from pathlib import Path
root = Path('ipfs_datasets_py/mcp_server/tools')
cats = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith('_'))
print('categories_on_disk', len(cats))
print('sample', cats[:8])
"
```

---

## 18. Related documents

| Document | Relationship |
| --- | --- |
| [SERVER_AND_DISPATCH.md](SERVER_AND_DISPATCH.md) | Startup, meta-tools, dispatch pipeline, caches |
| [ADR-005](../decisions/ADR-005-REGISTRIES-AND-ADAPTERS.md) | One registry per concern |
| [ADR-007](../decisions/ADR-007-MCP-RUNTIME-COMPATIBILITY.md) | Canonical vs compatibility MCP runtimes |
| Package ADR-001 / 003 / 004 | Thin wrappers, hierarchy, engine extraction |
| [DOMAIN_MAP.md](../DOMAIN_MAP.md) | Domain ownership for tool delegation targets |
| [THIN_TOOL_ARCHITECTURE.md](../../../ipfs_datasets_py/mcp_server/THIN_TOOL_ARCHITECTURE.md) | Package-local thin-wrapper notes |

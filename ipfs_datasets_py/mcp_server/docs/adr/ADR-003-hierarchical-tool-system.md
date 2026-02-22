# ADR-003: Hierarchical Tool System

**Status:** Accepted  
**Date:** 2026-02-19  
**Author:** MCP Server Team

---

## Context

With 382 tools across 49 categories, a flat tool registry produces O(n) lookup
cost and an MCP schema payload too large for most AI clients to ingest efficiently.

## Decision

Introduce a **two-level hierarchy** managed by `HierarchicalToolManager`:

```
Category (e.g., "graph_tools")
  └── Tool (e.g., "graph_create")
```

**Tier 1 — Meta-tools:**  Four pseudo-tools registered at the top level:
- `tools_list_categories` — returns the 49 category names.
- `tools_list_tools(category)` — returns tool names within a category.
- `tools_get_schema(category, tool)` — returns the full JSON schema on demand.
- `tools_dispatch(category, tool, params)` — executes any tool by name.

An AI client discovers categories first, then lists tools in the relevant
category, then dispatches — without ever loading all 382 schemas at once.

**Lazy loading:**  Tool schemas are generated on first access and cached in
`_schema_cache` (an LRU dict) to amortise the cost of schema generation.

**`dispatch()` routing:**  `HierarchicalToolManager.dispatch(category, tool, **params)`
resolves the callable, validates inputs, and invokes it — returning a result dict.
Circuit breakers (via `CircuitBreaker`) protect against repeatedly failing tools.

## Consequences

### Positive
- AI clients can work with the full tool set using ≤ 4 initial schema objects.
- Schema cache means repeated `get_schema` calls are O(1).
- Adding a new tool requires only registering it in the correct category — no
  global registration table to update.

### Negative
- Callers must know the two-level address `(category, tool)`.
- Tools cannot easily reference each other by name without going through the
  manager.

### Neutral
- `dispatch_parallel()` added in Phase F1 enables fan-out to N tools with one call.

## References

- `ipfs_datasets_py/mcp_server/hierarchical_tool_manager.py`
- `ipfs_datasets_py/mcp_server/THIN_TOOL_ARCHITECTURE.md`

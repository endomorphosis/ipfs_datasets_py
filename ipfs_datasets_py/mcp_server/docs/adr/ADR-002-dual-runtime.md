# ADR-002: Dual-Runtime Architecture (FastAPI + Trio)

**Status:** Accepted  
**Date:** 2026-02-18  
**Author:** MCP Server Team

---

## Context

MCP tool functions are consumed in two contexts:

1. **HTTP/REST** — FastAPI endpoint handlers that run via anyio's asyncio backend.
2. **Trio structured-concurrency** — The MCP++ workflow engine that uses `trio`
   nurseries for reliable task cancellation and structured concurrency.

These runtimes have incompatible event-loop models.  Raw `asyncio` coroutines cannot
run directly inside a Trio nursery, and vice versa.

## Decision

Adopt a **dual-runtime** approach using `anyio` as the compatibility shim:

- All tool functions are written as `async def` functions compatible with both
  `asyncio` and `trio` (via `anyio`).
- `HierarchicalToolManager.dispatch()` detects the current runtime through
  `RUNTIME_TRIO` metadata and dispatches accordingly.
- A `trio_bridge.py` module provides `run_in_trio()` for tools explicitly marked
  with `runtime=RUNTIME_TRIO`.
- FastAPI routes run via anyio's asyncio backend; the Trio runtime is started in a
  dedicated thread via `trio.from_thread.run_sync`.

## Consequences

### Positive
- A single codebase serves both runtimes.
- `anyio` primitives (`TaskGroup`, `sleep`, `open_file`) work on both.
- Tools can opt into Trio structured concurrency via `@tool_metadata(runtime=RUNTIME_TRIO)`.

### Negative
- `anyio` adds one dependency.
- Developers must use anyio primitives (`anyio.sleep`, `anyio.open_file`, `TaskGroup`)
  and avoid runtime-specific primitives (e.g., `asyncio.sleep`, `trio.sleep`).

### Neutral
- `pytest-asyncio` is used for the test suite; both runtimes are tested.

## References

- [anyio documentation](https://anyio.readthedocs.io/)
- `ipfs_datasets_py/mcp_server/trio_bridge.py`
- `ipfs_datasets_py/mcp_server/tool_metadata.py` (`RUNTIME_TRIO` constant)

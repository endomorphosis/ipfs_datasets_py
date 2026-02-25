# MCP Server Documentation

This directory contains reference documentation for the IPFS Datasets MCP Server.
For a feature overview and quick-start instructions see the [main README](../README.md).

---

## Directory Layout

```
docs/
├── api/                  ← API reference
│   └── tool-reference.md      Full parameter/return reference for all 51 tool categories
├── architecture/         ← Internal design documentation
│   ├── dual-runtime.md        FastAPI + Trio dual-runtime design
│   ├── mcp-plus-plus-alignment.md  MCP++ architecture (UCAN, event DAG, P2P transport)
│   └── adr/                   Architecture Decision Records (ADR-001 – ADR-006)
├── guides/               ← How-to guides
│   ├── cookbook.md            Common usage recipes (parallel dispatch, streaming, batching)
│   ├── p2p-migration.md       Migrating to P2P infrastructure
│   ├── performance-tuning.md  Performance optimization
│   └── performance-profiling.md  Profiling guide
├── development/          ← Contributor guides
│   ├── tool-patterns.md       Standard patterns for writing new tools
│   └── tool-templates/        Copy-paste tool templates
└── testing/              ← Testing guides
    └── DUAL_RUNTIME_TESTING_STRATEGY.md  Testing strategy for dual-runtime code
```

---

## API Reference

**[api/tool-reference.md](./api/tool-reference.md)** — the primary reference for tool consumers.

Covers every tool in all 51 categories with:
- Function signatures and parameter types
- Return value shapes
- Usage examples
- Error conditions

---

## Architecture

**[architecture/dual-runtime.md](./architecture/dual-runtime.md)** — explains why there are two async runtimes (FastAPI for general tools, Trio for P2P tools) and how the `RuntimeRouter` dispatches between them.

**[architecture/mcp-plus-plus-alignment.md](./architecture/mcp-plus-plus-alignment.md)** — describes the UCAN delegation model, event-DAG provenance system, and P2P transport bindings (MCP++ layer).

**[architecture/adr/](./architecture/adr/)** — Architecture Decision Records documenting significant design choices with context and rationale.

---

## Guides

| Guide | Description |
|---|---|
| [guides/cookbook.md](./guides/cookbook.md) | Ready-to-run recipes: parallel dispatch, streaming results, adaptive batching, error handling |
| [guides/p2p-migration.md](./guides/p2p-migration.md) | Step-by-step migration to P2P-backed tools |
| [guides/performance-tuning.md](./guides/performance-tuning.md) | Tuning connection pools, concurrency limits, caches |
| [guides/performance-profiling.md](./guides/performance-profiling.md) | Using the built-in profiling hooks |

---

## Development

**[development/tool-patterns.md](./development/tool-patterns.md)** — the authoritative guide for adding a new tool.  Covers:
- Thin-wrapper pattern (keep tool files under 150 lines)
- `@tool_metadata` decorator (`runtime="fastapi"` vs `runtime="trio"`)
- Registering the tool in the category `__init__.py`
- Writing the accompanying unit test

**[development/tool-templates/](./development/tool-templates/)** — boilerplate templates for function-based, class-based, and stateful tools.

---

## Testing

**[testing/DUAL_RUNTIME_TESTING_STRATEGY.md](./testing/DUAL_RUNTIME_TESTING_STRATEGY.md)** — explains how to write tests that work correctly against both the FastAPI and Trio runtimes, including anyio backend selection and mock strategies for P2P dependencies.

---

## Related top-level documents

| Document | Description |
|---|---|
| [../README.md](../README.md) | Feature overview, quick start, configuration reference |
| [../QUICKSTART.md](../QUICKSTART.md) | Get the server running in 5 minutes |
| [../THIN_TOOL_ARCHITECTURE.md](../THIN_TOOL_ARCHITECTURE.md) | Thin-wrapper architecture principles |
| [../SECURITY.md](../SECURITY.md) | Security posture, practices, and known hardening |
| [../CHANGELOG.md](../CHANGELOG.md) | Version history |

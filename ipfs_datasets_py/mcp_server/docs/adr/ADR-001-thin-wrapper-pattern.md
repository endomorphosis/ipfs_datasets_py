# ADR-001: Thin Wrapper Pattern

**Status:** Accepted  
**Date:** 2026-02-20  
**Author:** MCP Server Team

---

## Context

The original MCP server contained monolithic tool files of 300–1,000 lines each.
Business logic (HTTP calls, data transforms, retry loops) was inlined alongside
parameter validation and MCP-specific boilerplate.  This made:

- Unit testing difficult (could not mock a single function without loading the
  entire dependency graph),
- Code reuse impossible (the same HTTP call was copied across three tools),
- Context-window cost high (LLMs reading the tool layer also ingested domain
  logic irrelevant to tool dispatch).

## Decision

All business logic is extracted to **canonical engine modules** under
`ipfs_datasets_py.<domain>.<name>_engine.py`.  Tool files become
**thin wrappers** of ≤ 30 lines that:

1. Import the canonical function(s).
2. Validate inputs (delegating to `EnhancedParameterValidator`).
3. Delegate to the engine.
4. Return the engine's result dict directly.

Engine modules are importable independently of the MCP layer so they can be
called from tests, CLIs, and other packages without starting an MCP server.

## Consequences

### Positive
- Tool files are ≤ 30 lines — fully readable in one screen.
- Engine functions are independently unit-testable with plain `pytest`.
- LLM context-window cost drops ~90% when reading the tool layer.
- Shared logic lives in one place (DRY principle).

### Negative
- One additional indirection layer (tool → engine).
- Engine module must be kept in sync with tool wrapper signature.

### Neutral
- 190+ files refactored across 24 sessions (sessions 1–21 on branch
  `copilot/refactor-markdown-files-again`).

## Compliance

A tool file is considered compliant when:
1. It contains no business logic (no HTTP, no DB, no complex transforms).
2. It imports from a canonical engine module.
3. Its total line count is ≤ 50 lines (excluding imports and docstring).

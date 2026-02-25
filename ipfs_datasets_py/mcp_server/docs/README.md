# MCP Server Documentation

Welcome to the MCP Server documentation. This directory contains comprehensive documentation organized by topic.

## Documentation Structure

### [architecture/](./architecture/)
Technical design documentation and architecture decisions:
- **dual-runtime.md** — FastAPI + Trio dual-runtime design
- **mcp-plus-plus-alignment.md** — MCP++ architecture alignment (UCAN, event DAG, P2P transport)
- **DUAL_RUNTIME_ARCHITECTURE.md** — Detailed dual-runtime architecture
- **adr/** — Architecture Decision Records (ADR-001 through ADR-006)

### [api/](./api/)
API reference documentation:
- **tool-reference.md** — Complete tool API reference covering all 51 categories

### [guides/](./guides/)
User guides and how-to documentation:
- **p2p-migration.md** — Migrating to P2P infrastructure
- **performance-tuning.md** — Performance optimization guide
- **performance-profiling.md** — Performance profiling guide
- **cookbook.md** — Common usage patterns and recipes

### [development/](./development/)
Developer documentation:
- **tool-patterns.md** — Standard tool patterns (function-based, class-based, stateful)
- **tool-templates/** — Ready-to-use tool templates

### [testing/](./testing/)
Testing documentation:
- **DUAL_RUNTIME_TESTING_STRATEGY.md** — Testing strategy for dual-runtime architecture

### [history/](./history/)
Historical documentation and archived reports:
- Phase completion summaries (PHASE_1 through PHASE_4)
- Refactoring plans and checklists
- Implementation summaries

### [tools/](./tools/)
Tool-specific documentation:
- Tool category reference guides

## Quick Links

- [Main README](../README.md) — Project overview and current status
- [Quick Start Guide](../QUICKSTART.md) — Get started quickly
- [Thin Tool Architecture](../THIN_TOOL_ARCHITECTURE.md) — Architecture principles
- [Changelog](../CHANGELOG.md) — Version history
- [Security](../SECURITY.md) — Security posture and fixes

## Contributing

See [Development Guide](./development/README.md) for guidelines on creating tools and running tests.


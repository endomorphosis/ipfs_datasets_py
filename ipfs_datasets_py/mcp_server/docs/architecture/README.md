# Architecture Documentation

This directory contains technical architecture documentation for the MCP server.

## Documents

### [dual-runtime.md](./dual-runtime.md)
Technical documentation for the dual-runtime architecture combining FastAPI (for general tools) and Trio (for P2P tools). Explains:
- Why dual-runtime architecture
- Runtime routing mechanism
- Performance characteristics
- Integration patterns

### [mcp-plus-plus-alignment.md](./mcp-plus-plus-alignment.md)
Documentation on MCP++ alignment (v1–v39 complete). Covers:
- UCAN delegation implementation
- Event DAG provenance
- P2P PubSub transport bindings
- Compliance checker
- Policy audit log
- NL UCAN policy compiler
- I18N policy detection (20 languages)

### [DUAL_RUNTIME_ARCHITECTURE.md](./DUAL_RUNTIME_ARCHITECTURE.md)
Detailed dual-runtime architecture document.

### [adr/](./adr/)
Architecture Decision Records:
- **ADR-001** — Thin wrapper pattern
- **ADR-002** — Dual-runtime design
- **ADR-003** — Hierarchical tool system
- **ADR-004** — Engine extraction pattern
- **ADR-005** — v6 coverage hardening
- **ADR-006** — MCP++ alignment

## Related Documentation

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) - Core architectural principles
- [API Reference](../api/tool-reference.md) - Tool API documentation
- [P2P Migration Guide](../guides/p2p-migration.md) - Practical migration guide

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
Documentation on how this implementation aligns with MCP++ architecture principles. Covers:
- Profile negotiation
- CID-addressed tool contracts
- Event DAG provenance
- UCAN delegation
- Transport bindings

## Related Documentation

- [Thin Tool Architecture](../../THIN_TOOL_ARCHITECTURE.md) - Core architectural principles
- [API Reference](../api/tool-reference.md) - Tool API documentation
- [P2P Migration Guide](../guides/p2p-migration.md) - Practical migration guide

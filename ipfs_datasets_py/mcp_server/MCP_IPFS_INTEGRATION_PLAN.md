# MCP-IPFS Integration Plan

## Project Overview
**Date**: June 25, 2025  
**Purpose**: Replace the MCP (Model Context Protocol) library with a custom implementation that properly interfaces with IPFS daemons without conflicts.  
**Client Requirement**: Complete replacement of MCP library due to potential conflicts with IPFS daemons.

## Current State Analysis

### Codebase Structure
- **Root**: `/home/kylerose1946/ipfs_datasets_py/`
- **Size**: 996 files, 313,089 lines of code, 38.57 MB
- **MCP Server Location**: `/ipfs_datasets_py/mcp_server/`
- **MCP Package Copy**: `/ipfs_datasets_py/mcp_server/mcp_package_copy/`

### Existing Implementation Status
- Migration reported as **95% complete** (per `/migration_docs/MCP_SERVER.md`)
- Custom MCP server implementation exists using FastMCP
- Fallback mechanisms when `modelcontextprotocol` isn't available
- 9 tool categories implemented with 20+ tools total

### Tool Categories
1. **dataset_tools**: Load, save, process, convert datasets
2. **ipfs_tools**: IPFS interactions
3. **vector_tools**: Vector operations and similarity search
4. **graph_tools**: Knowledge graph operations
5. **audit_tools**: Audit logging
6. **security_tools**: Security operations
7. **provenance_tools**: Provenance tracking
8. **development_tools**: Test generation, documentation, linting
9. **cli/functions**: Command execution and Python snippets

### Known Issues
1. **Hallucinated Import**: `from mcp.client import MCPClient` - doesn't exist
2. **FastMCP Dependency**: Current implementation relies on FastMCP from original library
3. **STDIO vs HTTP**: Server defaults to STDIO mode, HTTP mode not fully supported
4. **Unknown Conflicts**: Specific IPFS conflicts not yet identified

## Technical Requirements

### Must Have
1. Complete MCP server implementation without original library dependency
2. Full protocol compatibility with MCP clients
3. No conflicts with IPFS daemon operations
4. Support for all existing tools
5. VS Code MCP integration support

### Architecture Decisions
1. **Create custom FastMCP replacement** (per client preference)
2. **Build custom MCP client implementation**
3. **Identify and isolate IPFS-conflicting components**
4. **Maintain API compatibility**

## Implementation Strategy

### Phase 1: Analysis and Discovery
1. **Analyze MCP Protocol**
   - Study `/mcp_package_copy/` to understand protocol
   - Document all MCP message types and flows
   - Identify core components needed

2. **Identify Potential Conflicts**
   - Port binding mechanisms
   - Event loop (asyncio) usage
   - Resource locking patterns
   - IPC/stdio communication methods

### Phase 2: Custom Implementation
1. **Core Components to Build**
   - Custom FastMCP replacement
   - Session management (ServerSession, ClientSession)
   - Protocol handlers (JSONRPCRequest, JSONRPCResponse)
   - Tool registration system
   - Message routing

2. **IPFS-Safe Design Principles**
   - Isolated event loops
   - Non-conflicting port management
   - Resource-safe communication
   - Clean process separation

### Phase 3: Integration
1. Replace FastMCP imports with custom implementation
2. Update all tool registrations
3. Fix the MCPClient issue
4. Test with active IPFS daemons

## Key Files to Analyze

### MCP Package Structure
```
/mcp_package_copy/mcp/
├── __init__.py          # Main exports and types
├── types.py             # Protocol type definitions
├── cli/                 # CLI utilities
├── shared/              # Shared components
│   └── exceptions.py    # Error handling
├── server/              # Server implementation
│   ├── session.py       # ServerSession class
│   ├── stdio.py         # STDIO server
│   └── fastmcp/         # FastMCP implementation
└── client/              # Client implementation
    ├── session.py       # ClientSession class
    └── stdio.py         # STDIO client
```

### Our Implementation
```
/ipfs_datasets_py/mcp_server/
├── server.py            # Main server implementation
├── simple_server.py     # Fallback implementation
├── client.py            # Client implementation (if exists)
├── configs.py           # Configuration system
├── logger.py            # Logging utilities
└── tools/               # All tool implementations
```

## Critical Code Sections

### Current Server Implementation Issues
1. **Line 234 in server.py**: `from mcp.client import MCPClient` - needs replacement
2. **FastMCP usage**: All instances need custom implementation
3. **Import fallbacks**: Already has structure for library-independent operation

## Unknown Factors
- Specific IPFS daemon operations being affected
- Nature of conflicts (ports, events, resources, protocols)
- FastMCP internal implementation details
- Full MCP protocol specification

## Next Steps

### Immediate Actions
1. Study MCP protocol in detail using `/mcp_package_copy/`
2. Create minimal test case to reproduce IPFS conflicts
3. Design custom FastMCP replacement architecture
4. Implement core protocol handlers

### Development Approach
1. Start with protocol analysis and documentation
2. Build minimal working server without MCP dependency
3. Add tool support incrementally
4. Test each component with IPFS daemons
5. Ensure VS Code integration works

## Success Metrics
1. Zero imports from original `mcp` package
2. All 20+ tools functioning correctly
3. Concurrent IPFS daemon operations work
4. VS Code MCP integration functional
5. All existing tests pass
6. No resource conflicts or port collisions

## Risk Mitigation
1. **Protocol Compatibility**: Extensive testing with existing clients
2. **Performance**: Benchmark against original implementation
3. **Stability**: Comprehensive error handling and recovery
4. **IPFS Conflicts**: Isolated testing environment with active daemons

## Additional Notes
- The codebase appears to be largely LLM-generated, expect inconsistencies
- Multiple migration attempts visible in `/migration_docs/`
- Extensive test infrastructure already in place
- Configuration system using TOML files
- Logging infrastructure ready

## Future Considerations
1. Performance optimization after functional implementation
2. Enhanced error handling and debugging capabilities
3. Documentation for custom protocol implementation
4. Migration guide for users of original MCP library

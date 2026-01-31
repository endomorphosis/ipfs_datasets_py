# Architecture Documentation

System architecture and design documentation for IPFS Datasets Python.

## Contents

### System Design
- [GitHub Actions Architecture](github_actions_architecture.md) - CI/CD architecture
- [GitHub Actions Implementation](github_actions_implementation_summary.md) - Implementation details
- [GitHub Actions Infrastructure](github_actions_infrastructure.md) - Infrastructure setup
- [Project Structure](project_structure.md) - Overall project organization

### Submodule Architecture
- [Submodule Architecture](submodule_architecture.md) - Submodule design
- [Submodule Deprecation](submodule_deprecation.md) - Deprecation strategy
- [Submodule Fix](submodule_fix.md) - Submodule fixes
- [Submodule Migration Verification](submodule_migration_verification.md) - Migration validation

### MCP Tools Architecture
- [MCP Tools Comprehensive Documentation](mcp_tools_comprehensive_documentation.md) - Complete MCP docs
- [MCP Tools Technical Reference](mcp_tools_technical_reference.md) - Technical details
- [MCP Tools Catalog](mcp_tools_catalog.md) - Tool catalog (200+ tools)

## Architecture Overview

IPFS Datasets Python follows a modular architecture:

```
┌─────────────────────────────────────────┐
│         User Interfaces                 │
│  (CLI, MCP Server, Python API)         │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────┴───────────────────────┐
│      Core Components                    │
│  - Dataset Management                   │
│  - Embeddings & Vector Stores          │
│  - GraphRAG & Knowledge Graphs         │
│  - PDF Processing                       │
│  - Multimedia Processing                │
└─────────────────┬───────────────────────┘
                  │
┌─────────────────┴───────────────────────┐
│      Storage Layer                      │
│  - IPFS/IPLD                           │
│  - Vector Databases                     │
│  - File Systems                         │
└─────────────────────────────────────────┘
```

## Key Design Principles

1. **Modular**: Components are loosely coupled
2. **Extensible**: Easy to add new backends and features
3. **Testable**: Comprehensive test coverage (182+ tests)
4. **Production-Ready**: Battle-tested in real deployments
5. **Decentralized**: IPFS-native from the ground up

## Related Documentation

- [Developer Guide](../developer_guide.md) - Development information
- [Implementation Notes](../implementation_notes/) - Technical details
- [Implementation Plans](../implementation_plans/) - Future work

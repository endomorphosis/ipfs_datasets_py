# IPFS Datasets Python Documentation

This directory contains all the documentation for the IPFS Datasets Python project. The documentation is organized into a structured hierarchy for easy navigation.

## Documentation Structure

### Core Documentation (Root Level)

- **[index.md](index.md)**: Main documentation portal with links to all resources
- **Getting Started**
  - [getting_started.md](getting_started.md): Introduction to basic concepts
  - [installation.md](installation.md): Installation instructions
  - [user_guide.md](user_guide.md): Comprehensive user guide
  - [developer_guide.md](developer_guide.md): Guide for developers
  - [unified_dashboard.md](unified_dashboard.md): Unified dashboard documentation

### Organized Documentation Directories

- **[guides/](guides/)**: Feature guides and how-to documentation
  - [guides/deployment/](guides/deployment/): Deployment and runner setup guides
  - [guides/tools/](guides/tools/): Tool-specific documentation (MCP, scrapers, web search, etc.)
  - [guides/infrastructure/](guides/infrastructure/): Infrastructure and CI/CD guides
  - [guides/security/](guides/security/): Security, audit logging, and governance
  - [guides/reference/](guides/reference/): API reference and technical documentation
  - Feature guides: data_provenance, distributed_features, ipld_optimization, pdf_processing, performance_optimization, query_optimization, etc.

- **[tutorials/](tutorials/)**: Step-by-step tutorials for specific features

- **[examples/](examples/)**: Usage examples and code samples

- **[architecture/](architecture/)**: System architecture and technical design documents

- **[implementation_plans/](implementation_plans/)**: Implementation plans and migration strategies

- **[implementation_notes/](implementation_notes/)**: Technical implementation details

- **[analysis/](analysis/)**: Technical analysis and audit reports

- **[reports/](reports/)**: Historical project reports and completion summaries

- **[archive/](archive/)**: Archived and deprecated documentation
  - [archive/reorganization/](archive/reorganization/): Documentation reorganization history
  - [archive/deprecated/](archive/deprecated/): Deprecated and obsolete documents

### Component Documentation

- [Vector Stores](../ipfs_datasets_py/vector_stores/) - Vector database implementations
- [Embeddings](../ipfs_datasets_py/embeddings/) - Embedding generation and management
- [Search](../ipfs_datasets_py/search/) - Advanced search capabilities
- [RAG](../ipfs_datasets_py/rag/) - Retrieval-augmented generation
- [PDF Processing](../ipfs_datasets_py/pdf_processing/) - PDF analysis and processing
- [Multimedia](../ipfs_datasets_py/multimedia/) - Media processing capabilities
- [LLM](../ipfs_datasets_py/llm/) - Language model integration
- [MCP Tools](../ipfs_datasets_py/mcp_tools/) - MCP tool integration
- [IPLD](../ipfs_datasets_py/ipld/) - InterPlanetary Linked Data
- [Audit](../ipfs_datasets_py/audit/) - Security and audit logging

## Documentation Maintenance Guidelines

1. **Centralization**: All documentation should be kept in the `docs/` directory
2. **Organization**: Follow the established structure for different types of documentation
3. **Cross-Referencing**: Use relative links between documentation files
4. **Implementation Notes**: Technical implementation details should go in the `implementation_notes/` directory
5. **Component Documentation**: Each major component should have its own subdirectory
6. **Examples**: Example documentation belongs in the `examples/` directory
7. **Index Files**: Each subdirectory should include an index.md file

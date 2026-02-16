# IPFS Datasets Python Documentation

Welcome to the comprehensive documentation for **IPFS Datasets Python** - a production-ready decentralized AI data platform.

## 🚀 Quick Navigation

### For New Users
- **[Getting Started](getting_started.md)** - Introduction and basic concepts
- **[Installation Guide](installation.md)** - Install and setup instructions
- **[User Guide](user_guide.md)** - Comprehensive usage guide
- **[Quick Start Examples](../README.md#-quick-start)** - Code examples to get started

### For Developers
- **[Developer Guide](developer_guide.md)** - Development guidelines and patterns
- **[API Reference](guides/reference/)** - Complete API documentation
- **[Contributing](../CONTRIBUTING.md)** - How to contribute to the project

### Latest Features (February 2026)

**🗄️ IPLD Vector Database** - Production-ready distributed vector search
- [Vector Store Guides](guides/knowledge_graphs/) - Implementation guides
- 18 MCP tools for vector operations
- 95% test coverage, 150+ tests

**📚 Knowledge Graphs Enhanced** - Modular extraction and query system  
- [Knowledge Graph Guides](guides/knowledge_graphs/) - Complete documentation
- 110+ new tests with comprehensive coverage
- Unified query engine with hybrid search

**📖 Documentation Reorganized** - Clean, structured hierarchy
- [Archive](archive/) - Historical reports and planning docs
- [Guides](guides/) - 45 organized feature guides
- Reduced clutter: 85% fewer files in docs root

## Documentation Structure

### Core Documentation (Root Level)

Essential guides for all users:

- **[index.md](index.md)** - Main documentation portal
- **[getting_started.md](getting_started.md)** - Introduction to basic concepts
- **[installation.md](installation.md)** - Installation instructions
- **[user_guide.md](user_guide.md)** - Comprehensive user guide
- **[developer_guide.md](developer_guide.md)** - Guide for developers
- **[unified_dashboard.md](unified_dashboard.md)** - Dashboard documentation
- **[FEATURES.md](FEATURES.md)** - Complete feature list
- **[CHANGELOG.md](CHANGELOG.md)** - Version history

### Organized Documentation Directories

#### [guides/](guides/) - Feature Guides and How-To Documentation

Organized by feature and component:

- **[guides/knowledge_graphs/](guides/knowledge_graphs/)** - Knowledge graph documentation (16 guides)
  - Implementation guides, migration paths, quick references
  - Entity extraction, relationship mapping, query engine
  
- **[guides/processors/](guides/processors/)** - Processor subsystem documentation (29 guides)
  - Architecture, migration guides, quick references
  - File conversion, multimedia processing, data transformation

- **[guides/deployment/](guides/deployment/)** - Deployment and runner setup guides
- **[guides/tools/](guides/tools/)** - Tool-specific documentation (MCP, scrapers, web search)
- **[guides/infrastructure/](guides/infrastructure/)** - Infrastructure and CI/CD guides
- **[guides/security/](guides/security/)** - Security, audit logging, and governance
- **[guides/reference/](guides/reference/)** - API reference and technical documentation

#### [tutorials/](tutorials/) - Step-by-Step Tutorials

Hands-on tutorials for specific features and use cases.

#### [examples/](examples/) - Usage Examples

Code samples and practical examples for common scenarios.

#### [architecture/](architecture/) - System Architecture

Technical design documents and architecture diagrams.

#### [reports/](reports/) - Project Reports

Historical completion reports and project summaries (44+ files).

#### [archive/](archive/) - Archived Documentation

Historical documentation and deprecated content organized into:

- **[archive/completion_reports/](archive/completion_reports/)** - Phase, session, and task completion reports (44 files)
- **[archive/knowledge_graphs/](archive/knowledge_graphs/)** - Historical KG planning and reports (29 files)
- **[archive/processors/](archive/processors/)** - Historical processor planning and reports (27 files)
- **[archive/root_status_reports/](archive/root_status_reports/)** - Root directory status reports (25 files)
- **[archive/reorganization/](archive/reorganization/)** - Documentation reorganization history
- **[archive/deprecated/](archive/deprecated/)** - Deprecated and obsolete documents

### Component Documentation

Direct links to module documentation:

- **[Vector Stores](../ipfs_datasets_py/vector_stores/)** - IPLD vector database, FAISS, Qdrant, Elasticsearch
- **[Embeddings](../ipfs_datasets_py/embeddings/)** - Embedding generation and management
- **[Search](../ipfs_datasets_py/search/)** - Advanced search including RAG and GraphRAG
- **[Knowledge Graphs](../ipfs_datasets_py/knowledge_graphs/)** - Extraction, query, and storage
- **[PDF Processing](../ipfs_datasets_py/pdf_processing/)** - PDF analysis and processing
- **[Multimedia](../ipfs_datasets_py/multimedia/)** - Media processing capabilities
- **[LLM](../ipfs_datasets_py/llm/)** - Language model integration
- **[MCP Tools](../ipfs_datasets_py/mcp_tools/)** - 200+ tools for AI assistants
- **[IPLD](../ipfs_datasets_py/ipld/)** - InterPlanetary Linked Data
- **[Audit](../ipfs_datasets_py/audit/)** - Security and audit logging

## 🔍 Finding Documentation

### By Topic

- **Vector Search & Embeddings:** See `guides/knowledge_graphs/` and `../ipfs_datasets_py/vector_stores/`
- **Knowledge Graphs:** See `guides/knowledge_graphs/` for all KG documentation
- **File Processing:** See `guides/processors/` for file conversion and multimedia
- **MCP Integration:** See `guides/tools/` for MCP server and tool documentation
- **Deployment:** See `guides/deployment/` for production deployment guides
- **Security:** See `guides/security/` for audit logging and governance

### By Use Case

- **Getting Started:** Start with `getting_started.md` and `installation.md`
- **Building AI Applications:** See `user_guide.md` and MCP documentation
- **Contributing Code:** See `developer_guide.md` and architecture docs
- **Production Deployment:** See `guides/deployment/` and `guides/infrastructure/`

## Documentation Maintenance

### Guidelines

1. **Centralization**: All documentation lives in the `docs/` directory
2. **Organization**: Follow the established structure for different doc types
3. **Cross-Referencing**: Use relative links between documentation files
4. **Archive Old Docs**: Move completed session/phase reports to `archive/`
5. **Update Guides**: Keep permanent guides in `guides/` up to date
6. **Index Files**: Each subdirectory should include a README.md or index file

### Recent Reorganization (February 2026)

The documentation was comprehensively reorganized to improve navigation:

- **Archived 100+ files:** Session reports, phase completions, and planning docs moved to `archive/`
- **Created guides structure:** 45 permanent guides organized by feature in `guides/`
- **Reduced clutter:** 85% reduction in docs root files (177 → 27 core files)

For details, see [DOCS_REORGANIZATION_2026_02_16.md](reports/DOCS_REORGANIZATION_2026_02_16.md).

## Need Help?

- **General Questions:** See [FAQ](faq.md) or [User Guide](user_guide.md)
- **Bug Reports:** Open an issue on [GitHub](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Feature Requests:** Check existing issues or open a new one
- **Contributing:** See [CONTRIBUTING.md](../CONTRIBUTING.md) for guidelines

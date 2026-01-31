# IPFS Datasets Python Documentation

Welcome to the IPFS Datasets Python documentation. This comprehensive guide covers all aspects of using the library for data processing and distribution across decentralized networks.

## 🚀 Quick Start

- **New Users**: Start with the [Getting Started Guide](getting_started.md)
- **Installation**: See [Installation Guide](installation.md)
- **Examples**: Check out [Examples Overview](examples/)
- **API Reference**: Browse the [Complete API Reference](guides/reference/api_reference.md)
- **Complete Navigation**: Use the [Master Documentation Index](archive/deprecated/master_documentation_index.md) for comprehensive access to all documentation

## 📚 Documentation Organization

This documentation is organized into several sections:
- **Getting Started**: Basic installation and usage instructions
- **Core Features**: Overview of main capabilities
- **Advanced Features**: Documentation of more complex functionality
- **Tutorials & Examples**: Hands-on guides and example use cases
- **Component Documentation**: Details about specific components
- **Implementation Notes**: Technical details for developers

## 🔍 Quick Reference

### Common Tasks
- [Load a dataset](getting_started.md#loading-datasets)
- [Generate embeddings](getting_started.md#basic-embedding-generation)
- [Search documents](getting_started.md#vector-search)
- [Process PDFs](getting_started.md#pdf-processing-and-llm-optimization)
- [Set up RAG](getting_started.md#graphrag-integration)

### Component Quick Links
- [Vector Stores](../ipfs_datasets_py/vector_stores/README.md) - Multi-backend vector databases
- [Embeddings](../ipfs_datasets_py/embeddings/README.md) - Embedding generation and management
- [Search](../ipfs_datasets_py/search/README.md) - Semantic search capabilities
- [RAG](../ipfs_datasets_py/rag/README.md) - Retrieval-augmented generation
- [PDF Processing](../ipfs_datasets_py/pdf_processing/README.md) - Advanced PDF analysis
- [MCP Tools](../ipfs_datasets_py/mcp_tools/README.md) - AI assistant integration
- [Utils](../ipfs_datasets_py/utils/README.md) - Text processing utilities

## Getting Started

- [Getting Started Guide](getting_started.md) - Introduction to basic concepts and quick start
- [Installation Guide](installation.md) - Detailed installation instructions
- [User Guide](user_guide.md) - Comprehensive guide for using the library
- [API Reference](guides/reference/api_reference.md) - Complete API documentation
- [Developer Guide](developer_guide.md) - Guide for developers contributing to the project

## Core Features

- **Data Processing** - Working with datasets from various sources
- **File Conversion** - Convert arbitrary file types to text for GraphRAG ([Quick Guide](implementation_plans/file_conversion_pros_cons.md) | [Full Analysis](implementation_plans/file_conversion_systems_analysis.md) | [Merge Feasibility](implementation_plans/file_conversion_merge_feasibility.md) | [Integration Plan](implementation_plans/file_conversion_integration_plan.md))
- **PDF Processing** - Advanced PDF decomposition and LLM-optimized content extraction
- **IPLD Integration** - Content-addressed data structures with IPLD
- **Vector Storage** - Efficient storage and retrieval of vector embeddings
- **GraphRAG** - Graph-enhanced retrieval augmented generation
- **Web Archive Integration** - Working with web archives via IPWB, Internet Archive, Archive.is
- **Multimedia Scraping** - YT-DLP integration for 1000+ platforms with FFmpeg processing
- **Common Crawl Integration** - Large-scale web crawl data access and processing

## Advanced Features

- [Security & Governance](guides/security/security_governance.md) - Encryption, access control, provenance, and audit logging
- [Performance Optimization](guides/performance_optimization.md) - Optimizing for large datasets
- [Distributed Features](guides/distributed_features.md) - Multi-node capabilities
- [IPLD Optimization](guides/ipld_optimization.md) - IPLD encoding/decoding optimizations
- [Query Optimization](guides/query_optimization.md) - Optimizing graph and vector queries
- [Data Provenance](guides/data_provenance.md) - Detailed lineage tracking
- [Audit Logging](guides/security/audit_logging.md) - Comprehensive audit logging capabilities
- [PDF Processing](guides/pdf_processing.md) - Advanced PDF decomposition and LLM optimization

## Tutorials & Examples

- [Advanced Examples](examples/advanced_examples.md) - Comprehensive examples for complex scenarios
- [Docker Deployment](guides/deployment/docker_deployment.md) - Guide for containerizing with Docker
- [MCP Server Integration](guides/tools/mcp_server_integration.md) - AI assistant access via Model Context Protocol
- [Examples Overview](examples/) - Detailed overview of available examples

## Tutorials

- [GraphRAG Tutorial](tutorials/graphrag_tutorial.md) - Building knowledge-enhanced retrieval systems
- [Web Archive Processing](tutorials/web_archive_tutorial.md) - Complete web archiving and processing workflow
- [Media Scraping Tutorial](tutorials/media_scraping_tutorial.md) - Comprehensive multimedia content scraping and processing
- [Comprehensive Web Scraping Guide](guides/comprehensive_web_scraping_guide.md) - Complete guide to all web scraping capabilities
- [Distributed Dataset Management](tutorials/distributed_dataset_tutorial.md) - Managing datasets across nodes  
- [Security Implementation](tutorials/security_tutorial.md) - Implementing security features

## Component Documentation

- **Core Components** - See individual module README files:
  - [Utils](../ipfs_datasets_py/utils/README.md) - Text processing utilities
  - [Vector Stores](../ipfs_datasets_py/vector_stores/README.md) - Vector database support
  - [Embeddings](../ipfs_datasets_py/embeddings/README.md) - Embedding generation
  - [Search](../ipfs_datasets_py/search/README.md) - Search capabilities
  - [RAG](../ipfs_datasets_py/rag/README.md) - Retrieval-augmented generation
  - [PDF Processing](../ipfs_datasets_py/pdf_processing/README.md) - PDF analysis
  - [Multimedia](../ipfs_datasets_py/multimedia/README.md) - Media processing
  - [LLM](../ipfs_datasets_py/llm/README.md) - Language model integration
  - [MCP Tools](../ipfs_datasets_py/mcp_tools/README.md) - AI assistant tools
  - [IPLD](../ipfs_datasets_py/ipld/README.md) - Content-addressed data structures

## Implementation Notes

- [RAG Optimizer Learning Metrics](rag_optimizer/learning_metrics_implementation.md) - RAG Query Optimizer learning metrics implementation details
- [RAG Optimizer Integration Plan](rag_optimizer/integration_plan.md) - Integration plan for RAG Query Optimizer metrics
- [Audit System Implementation](implementation_notes/audit_system.md) - Audit logging and reporting system implementation details

## Examples

The library includes numerous example files demonstrating key features:

- `example.py` - Basic usage examples
- `security_example.py` - Security and governance features
- `monitoring_example.py` - Monitoring and metrics
- `resilient_operations_example.py` - Resilient distributed operations
- `admin_dashboard_example.py` - Administration dashboard
- `llm_reasoning_example.py` - LLM reasoning with tracing
- `graphrag_optimizer_example.py` - GraphRAG query optimization
- `comprehensive_audit.py` - Comprehensive audit logging
- `rag_query_optimizer_example.py` - RAG query optimization
- `wiki_rag_optimization.py` - Wikipedia-specific RAG optimization

## Architecture

The IPFS Datasets Python library architecture is organized around several key components:

1. **Core Data Layer**
   - Dataset loading and processing
   - Format conversion (Parquet, CAR, Arrow)
   - Serialization utilities

2. **IPLD Storage Layer**
   - DAG-PB implementation
   - CAR file handling
   - UnixFS integration

3. **Vector Processing**
   - Vector indexing and search
   - Embedding generation
   - Memory-mapped vector storage

4. **Knowledge Graph**
   - Entity extraction
   - Relationship modeling
   - GraphRAG query engine

5. **Web Archive Integration**
   - WARC file handling
   - IPWB integration
   - Archive processing

6. **Operations & Management**
   - Security and governance
   - Monitoring and metrics
   - Resilient operations
   - Administration tools

7. **Distributed Features**
   - Sharded datasets
   - Peer-to-peer communication
   - Federated search
   - Node health monitoring

## Integration Diagram

```
                                  ┌─────────────────┐
                                  │ Data Sources    │
                                  │ (HF, DuckDB,    │
                                  │  Web Archives)  │
                                  └────────┬────────┘
                                           │
                                           ▼
┌──────────────────┐           ┌────────────────────┐           ┌──────────────────┐
│                  │           │                    │           │                  │
│   Processing     │◀─────────▶│     UnifiedData    │◀─────────▶│  Storage Layer   │
│    Pipeline      │           │      Layer         │           │    (IPFS/IPLD)   │
│                  │           │                    │           │                  │
└─────────┬────────┘           └─────────┬──────────┘           └────────┬─────────┘
          │                              │                               │
          ▼                              ▼                               ▼
┌───────────────────┐           ┌────────────────────┐           ┌──────────────────┐
│  Transformations  │           │     Conversion     │           │  IPLD Components │
│ - Vector Encoding │           │     Components     │           │ - CAR            │
│ - KG Extraction   │           │ - Parquet ↔ CAR    │           │ - DAG-PB         │
│ - Entity Linking  │           │ - Arrow ↔ IPLD     │           │ - UnixFS         │
└─────────┬─────────┘           └─────────┬──────────┘           └────────┬─────────┘
          │                               │                               │
          └───────────────────────────────┼───────────────────────────────┘
                                          │
                                          ▼
                               ┌────────────────────┐
                               │   Query Systems    │
                               │ - Vector Search    │
                               │ - Knowledge Graph  │
                               │ - GraphRAG         │
                               └────────────────────┘
```

## Implementation Plan

The library is being implemented according to the phased plan outlined in CLAUDE.md:

- **Phase 0: Foundation** ✅
- **Phase 1: Core Infrastructure Integration** ✅
- **Phase 2: Processing & Analysis** ✅
- **Phase 3: Advanced Features** ✅
- **Phase 4: Optimization and Scaling** ✅
- **Phase 5: Production Readiness** ✅
  - **Monitoring and Management** ✅
  - **Security & Governance** ✅
  - **Documentation and Packaging** ✅

## Contributing

If you want to contribute to the IPFS Datasets Python project, please check out:

- [GitHub Repository](https://github.com/your-organization/ipfs_datasets_py)
- [Issue Tracker](https://github.com/your-organization/ipfs_datasets_py/issues)
- [Code of Conduct](https://github.com/your-organization/ipfs_datasets_py/blob/main/CODE_OF_CONDUCT.md)

## License

This project is licensed under the MIT License - see the LICENSE file for details.

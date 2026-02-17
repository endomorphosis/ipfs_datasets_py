# IPFS Datasets Python - Development Guide

## Project Overview
This repository serves as a comprehensive data processing and storage library with full IPFS embeddings integration:
- DuckDB, Arrow, and HuggingFace Datasets for data manipulation
- IPLD for data structuring
- IPFS (via ipfs_datasets_py.ipfs_kit) for decentralized storage
- libp2p (via ipfs_datasets_py.libp2p_kit) for peer-to-peer data transfer
- InterPlanetary Wayback (IPWB) for web archive integration
- **Advanced Vector Embeddings** (migrated from ipfs_embeddings_py)
- **Vector Stores** (Qdrant, Elasticsearch, FAISS integration)
- **Semantic Search & Similarity** capabilities
- **MCP (Model Context Protocol) Tools** for AI integration
- **FastAPI Service** for REST API endpoints

The primary goal is to provide a unified interface for data processing, semantic search, and distribution across decentralized networks, with seamless conversion between formats and storage systems.


### Build & Test Commands
- **Install**: `pip install -e .`
- **Install Dependencies**: `pip install -r requirements.txt`
- **Build**: `python setup.py build`
- **Run all tests**: `python -m pytest tests/`
- **Run MCP tools test**: `python comprehensive_mcp_test.py`
- **Run integration tests**: `python systematic_validation.py`
- **Start FastAPI server**: `python start_fastapi.py`
- **Start MCP server**: `python -m ipfs_datasets_py.mcp_server --stdio`
- **Run single test**: `python -m pytest tests/test_embedding_tools.py`
- **Generate AST**: `python -m astroid ipfs_datasets_py > ast_analysis.json`
- **Check for duplications**: `pylint --disable=all --enable=duplicate-code ipfs_datasets_py`

## New Features (Post-Integration)

### Embedding & Vector Capabilities
- **Advanced Embedding Generation**: Text, document, and multimodal embeddings
- **Vector Stores**: Qdrant, Elasticsearch, FAISS backends
- **Semantic Search**: Similarity search across embeddings
- **Sharding**: Large-scale embedding distribution
- **Quality Assessment**: Embedding quality metrics and validation

### MCP Tool Categories
- **Dataset Tools**: Load, process, save, convert datasets
- **IPFS Tools**: Pin, retrieve, manage IPFS content
- **Vector Tools**: Create indexes, search, manage vector stores
- **Embedding Tools**: Generate, search, shard embeddings
- **Admin Tools**: System management and monitoring
- **Cache Tools**: Distributed caching and optimization
- **Workflow Tools**: Automation and pipeline management
- **Analysis Tools**: Clustering, drift detection, quality assessment
- **Auth Tools**: Authentication and authorization
- **Monitoring Tools**: Health checks and metrics

### FastAPI Service Endpoints
- **Dataset Management**: `/datasets/` endpoints for CRUD operations
- **Vector Operations**: `/vectors/` for embedding and search
- **IPFS Integration**: `/ipfs/` for decentralized storage
- **Health & Metrics**: `/health`, `/metrics` monitoring
- **Authentication**: Token-based auth with `/auth/` endpoints

<!-- Rest of CLAUDE.md content -->


---

## Best Practices

### Performance Optimization
- **Use hardware acceleration**: Enable `ipfs_accelerate_py` for 2-20x performance improvements
- **Batch processing**: Process data in batches for better throughput
- **Caching**: Leverage caching mechanisms to avoid redundant operations
- **Async operations**: Use async/await for I/O-bound operations

### IPFS Integration
- **Pin important content**: Use `ipfs_kit_py` to pin content for persistence
- **Content addressing**: Leverage CID-based deduplication
- **CAR files**: Use CAR archives for bulk storage and transfer
- **Pinning services**: Configure remote pinning for reliability

### Code Organization
- **Follow reorganized structure**: Use correct import paths after refactoring
  ```python
  # Correct imports
  from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboard
  from ipfs_datasets_py.caching.cache import GitHubAPICache
  from ipfs_datasets_py.processors.web_archiving.web_archive import create_web_archive
  ```

### Error Handling
- **Graceful degradation**: Handle missing dependencies gracefully
- **Retry logic**: Implement retry for network operations
- **Logging**: Use structured logging for debugging
- **Validation**: Validate inputs before processing

### Security
- **Secrets management**: Use environment variables for sensitive data
- **Input validation**: Sanitize and validate all user inputs
- **Access control**: Implement proper authentication/authorization
- **Audit logging**: Track important operations

### Common Pitfalls to Avoid
- ❌ Don't use old import paths (pre-refactoring)
- ❌ Don't hardcode file paths
- ❌ Don't ignore error handling
- ❌ Don't skip dependency version pinning
- ❌ Don't commit sensitive data

### Integration Tips
- **MCP Tools**: Use the unified CLI for tool execution
- **Docker**: Use provided Dockerfiles in `docker/` directory
- **Testing**: Run `pytest` with parallel execution for faster tests
- **Documentation**: Refer to guides in `docs/guides/` for detailed info


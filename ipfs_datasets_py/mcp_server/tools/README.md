# MCP Server Tools

This directory contains **344 Python tool files** across **51 categories** that expose the full
functionality of IPFS Datasets Python through the Model Context Protocol.

Tools follow the [Thin Tool Architecture](../THIN_TOOL_ARCHITECTURE.md):
- Business logic lives in `ipfs_datasets_py/` core modules
- Each tool file is a thin wrapper (<150 lines) that validates inputs, calls core logic, and formats responses
- Tools are lazily loaded by `HierarchicalToolManager` to minimise startup cost

---

## Category Index

### 🗄️ Data & Storage

| Category | Files | Description |
|----------|-------|-------------|
| [`dataset_tools/`](./dataset_tools/) | 7 | Load, save, convert, and process datasets |
| [`ipfs_tools/`](./ipfs_tools/) | 3 | IPFS pin, get, CAR conversion, UnixFS ops |
| [`ipfs_cluster_tools/`](./ipfs_cluster_tools/) | 1 | IPFS cluster coordination |
| [`storage_tools/`](./storage_tools/) | 2 | Multi-backend storage management |
| [`provenance_tools/`](./provenance_tools/) | 2 | Data provenance and lineage tracking |
| [`index_management_tools/`](./index_management_tools/) | 1 | Search index lifecycle |

### 🔍 Search & Retrieval

| Category | Files | Description |
|----------|-------|-------------|
| [`search_tools/`](./search_tools/) | 1 | Semantic and keyword search |
| [`web_archive_tools/`](./web_archive_tools/) | 18 | Common Crawl, Wayback Machine, web search APIs |
| [`web_scraping_tools/`](./web_scraping_tools/) | 1 | General web scraping utilities |

### 🧠 AI & Embeddings

| Category | Files | Description |
|----------|-------|-------------|
| [`embedding_tools/`](./embedding_tools/) | 9 | Embedding generation, similarity, batching |
| [`sparse_embedding_tools/`](./sparse_embedding_tools/) | 1 | Sparse/BM25 embeddings |
| [`vector_tools/`](./vector_tools/) | 6 | Vector store operations (FAISS, Qdrant, ES) |
| [`vector_store_tools/`](./vector_store_tools/) | 3 | Enhanced vector store management |

### 📊 Knowledge Graphs & Logic

| Category | Files | Description |
|----------|-------|-------------|
| [`graph_tools/`](./graph_tools/) | 11 | Knowledge graph construction and Cypher queries |
| [`logic_tools/`](./logic_tools/) | 12 | FOL, deontic logic, temporal reasoning, theorem proving |
| [`analysis_tools/`](./analysis_tools/) | 1 | Data analysis and pattern detection |

### 📄 Document Processing

| Category | Files | Description |
|----------|-------|-------------|
| [`pdf_tools/`](./pdf_tools/) | 8 | PDF extraction, OCR, GraphRAG processing |
| [`file_converter_tools/`](./file_converter_tools/) | 8 | Format conversion (text, images, audio, video) |
| [`file_detection_tools/`](./file_detection_tools/) | 3 | MIME type detection and file classification |
| [`media_tools/`](./media_tools/) | 9 | FFmpeg video/audio processing, yt-dlp download |

### ⚖️ Legal & Finance

| Category | Files | Description |
|----------|-------|-------------|
| [`legal_dataset_tools/`](./legal_dataset_tools/) | 38 | Legal scrapers (RECAP, CourtListener, state laws, municipal codes) |
| [`finance_data_tools/`](./finance_data_tools/) | 6 | Stock data, financial news, theorem-based reasoning |

### 🔬 Specialist Research

| Category | Files | Description |
|----------|-------|-------------|
| [`investigation_tools/`](./investigation_tools/) | 7 | Data ingestion and multi-source investigation |
| [`medical_research_scrapers/`](./medical_research_scrapers/) | 6 | Biomedical datasets and literature |
| [`geospatial_tools/`](./geospatial_tools/) | 1 | Geographic data and spatial analysis |
| [`software_engineering_tools/`](./software_engineering_tools/) | 11 | GitHub/GitLab analysis, CI/CD, log parsing |

### 🛠️ Development & CLI

| Category | Files | Description |
|----------|-------|-------------|
| [`development_tools/`](./development_tools/) | 19 | GitHub CLI, Claude CLI, Gemini CLI, codebase search |
| [`cli/`](./cli/) | 2 | Command-line interface utilities |
| [`functions/`](./functions/) | 1 | Generic function utilities |
| [`bespoke_tools/`](./bespoke_tools/) | 7 | Custom one-off tools (cache stats, etc.) |

### ⚙️ Infrastructure & Operations

| Category | Files | Description |
|----------|-------|-------------|
| [`admin_tools/`](./admin_tools/) | 2 | Server administration, user management |
| [`auth_tools/`](./auth_tools/) | 2 | Authentication and authorisation |
| [`monitoring_tools/`](./monitoring_tools/) | 2 | Metrics collection, health checks, alerting |
| [`alert_tools/`](./alert_tools/) | 1 | Discord and notification alerts |
| [`audit_tools/`](./audit_tools/) | 3 | Audit logging and compliance |
| [`background_task_tools/`](./background_task_tools/) | 3 | Async job queue management |
| [`cache_tools/`](./cache_tools/) | 2 | Caching layer operations |
| [`rate_limiting_tools/`](./rate_limiting_tools/) | 1 | API rate limiting helpers |
| [`session_tools/`](./session_tools/) | 3 | Session state management |
| [`security_tools/`](./security_tools/) | 1 | Security scanning and hardening |
| [`data_processing_tools/`](./data_processing_tools/) | 1 | Data transformation and validation |
| [`dashboard_tools/`](./dashboard_tools/) | 3 | Dashboard UI and visualisation |
| [`workflow_tools/`](./workflow_tools/) | 2 | Workflow orchestration (DAG-based) |

### 🌐 P2P & Network

| Category | Files | Description |
|----------|-------|-------------|
| [`p2p_tools/`](./p2p_tools/) | 2 | Peer-to-peer network operations |
| [`p2p_workflow_tools/`](./p2p_workflow_tools/) | 1 | P2P workflow submission |
| [`mcplusplus/`](./mcplusplus/) | 3 | MCP++ task queue, peer, and workflow engines |

### 📡 External Integrations

| Category | Files | Description |
|----------|-------|-------------|
| [`discord_tools/`](./discord_tools/) | 4 | Discord bot and notification tools |
| [`email_tools/`](./email_tools/) | 3 | Email sending and SMTP integration |

### 🗃️ Legacy

| Category | Files | Description |
|----------|-------|-------------|
| [`legacy_mcp_tools/`](./legacy_mcp_tools/) | 32 | Pre-refactoring tools (being migrated to category dirs) |
| [`lizardperson_argparse_programs/`](./lizardperson_argparse_programs/) | 0 py, 11 md | Legacy CLI program (Bluebook Citation Validator) — MCP wrapper: `legal_dataset_tools/bluebook_citation_validator_tool.py` |
| [`lizardpersons_function_tools/`](./lizardpersons_function_tools/) | 0 | Empty placeholder |

---

## Key Files at Root Level

| File | Purpose |
|------|---------|
| `__init__.py` | Lazy-load module registry for all 51 categories |
| `tool_registration.py` | Tool registration and discovery logic |
| `tool_wrapper.py` | Thin wrapper base utilities |
| `validators.py` | Input validation shared by tools |
| `fastapi_integration.py` | FastAPI route integration helpers |

---

## Adding a New Tool

1. Choose the appropriate category directory (or create a new one)
2. Create a thin wrapper file following the [template](../docs/development/tool-templates/)
3. Add business logic to the relevant `ipfs_datasets_py/` core module
4. Export the tool function from the category's `__init__.py`
5. Register in `tool_registration.py`
6. Write tests in `tests/mcp/`

See [THIN_TOOL_ARCHITECTURE.md](../THIN_TOOL_ARCHITECTURE.md) for the full pattern.

---

## Improvement Plan

See [TOOLS_IMPROVEMENT_PLAN_2026.md](./TOOLS_IMPROVEMENT_PLAN_2026.md) for the full plan covering:
- Documentation coverage (44 categories currently undocumented)
- Code quality (thick tools, legacy migration, disabled tests)
- Priority ordering and effort estimates

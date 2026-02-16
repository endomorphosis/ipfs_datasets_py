# 🌐 IPFS Datasets Python

> **Decentralized AI Data Platform - Production Ready**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![Production Ready](https://img.shields.io/badge/status-production%20ready-green)](#)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-4500%2B-brightgreen)](./tests/)
[![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen)](#)


**IPFS Datasets Python** is a comprehensive platform for decentralized AI data processing, combining mathematical theorem proving, AI-powered document intelligence, multimedia processing, and knowledge graph operations—all on decentralized IPFS infrastructure.

## 📑 Table of Contents

- [Key Features](#-key-features)
- [Quick Start](#-quick-start)
- [CLI Tools](#-cli-tools)
- [MCP Server](#-mcp-server)
- [MCP Dashboard](#-mcp-dashboard)
- [Core Modules](#-core-modules)
- [Functional Modules](#-functional-modules)
- [Documentation](#-documentation)
- [Contributing](#-contributing)
- [License](#-license)

## ✨ Key Features

- 🗄️ **IPLD Vector Database** - Production-ready distributed vector search with sharding and replication
- 🔬 **Mathematical Theorem Proving** - Convert legal text to verified formal logic (Z3, CVC5, Lean 4, Coq)
- 🧬 **GraphRAG Ontology Optimizer** - AI-powered multi-agent system for knowledge graph optimization
- 📄 **GraphRAG Document Processing** - AI-powered PDF analysis with knowledge graphs
- 🕸️ **Knowledge Graph Intelligence** - Modular extraction package with cross-document reasoning
- 📝 **Universal File Conversion** - Convert any file type to text for AI processing
- 🎬 **Universal Media Processing** - Download and process from 1000+ platforms (yt-dlp + FFmpeg)
- 🌐 **Decentralized Storage** - IPFS-native with content addressing (ipfs_kit_py)
- ⚡ **Hardware Acceleration** - 2-20x speedup with multi-backend support (ipfs_accelerate_py)
- 🤖 **MCP Server** - 200+ tools for AI assistants (Claude, ChatGPT, etc.)
- 🔧 **Auto-Fix with GitHub Copilot** - Production-ready AI code fixes (100% verified)
- 🐛 **Automatic Error Reporting** - Runtime errors → GitHub issues automatically
- 📊 **Production Monitoring** - Dashboards, analytics, and observability
- 🔄 **Distributed Compute** - P2P networking and distributed workflows
- 🛡️ **Enterprise Ready** - Security, audit logging, and provenance tracking

## 🚀 Quick Start

### Installation

```bash
# Clone repository
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py

# Quick setup (core dependencies)
python scripts/setup/install.py --quick

# Or install with specific features
pip install -e ".[all]"  # All features
pip install -e ".[ml]"   # ML/AI features only
```

### Basic Usage

```python
from ipfs_datasets_py.dataset_manager import DatasetManager

# Load and process datasets
manager = DatasetManager()
dataset = manager.load_dataset("squad", split="train[:1000]")
manager.save_dataset(dataset, "output/processed_data.parquet")
```

## 🔧 CLI Tools

The `ipfs-datasets` CLI provides comprehensive command-line access to all features.

### Info Commands

```bash
# System status and information
ipfs-datasets info status
ipfs-datasets info version
ipfs-datasets info defaults

# Save configuration
ipfs-datasets save-defaults
```

### MCP Server Management

```bash
# Start MCP server
ipfs-datasets mcp start

# Stop server
ipfs-datasets mcp stop

# Check status
ipfs-datasets mcp status

# View logs
ipfs-datasets mcp logs
```

### Tool Management

```bash
# List all tool categories (200+ tools)
ipfs-datasets tools categories

# List tools in a category
ipfs-datasets tools list dataset_tools

# Execute a tool directly
ipfs-datasets tools run dataset_tools load_dataset --source squad

# Alternative execution
ipfs-datasets tools execute dataset_tools load_dataset --source squad --split train
```

### VSCode CLI Integration

```bash
# Check VSCode CLI status
ipfs-datasets vscode status

# Install VSCode CLI
ipfs-datasets vscode install

# Configure authentication
ipfs-datasets vscode auth

# Install with auth in one step
ipfs-datasets vscode install-with-auth

# Manage extensions
ipfs-datasets vscode extensions list
ipfs-datasets vscode extensions install ms-python.python

# Tunnel management
ipfs-datasets vscode tunnel --name my-tunnel
```

### GitHub CLI Integration

```bash
# Check GitHub CLI status
ipfs-datasets github status

# Install GitHub CLI
ipfs-datasets github install

# Authenticate
ipfs-datasets github auth login

# Execute GitHub commands
ipfs-datasets github execute issue list
ipfs-datasets github execute pr create
```

### Discord Integration

```bash
# Send Discord message
ipfs-datasets discord send "Hello from IPFS Datasets!" --channel general

# Send to webhook
ipfs-datasets discord webhook "Status update" --url https://discord.com/api/webhooks/...

# Send file
ipfs-datasets discord file report.pdf --channel reports
```

### Email Integration

```bash
# Send email
ipfs-datasets email send --to user@example.com --subject "Report" --body "See attached"

# Check email status
ipfs-datasets email status
```

### Vector Database Quick Start

```python
from ipfs_datasets_py.vector_stores.ipld_vector_store import IPLDVectorStore
from ipfs_datasets_py.vector_stores.config import create_ipld_config

# Create IPLD vector store with distributed sharding
config = create_ipld_config(
    use_ipfs_router=True,
    enable_sharding=True,
    replication_factor=3
)
store = IPLDVectorStore(config)

# Add vectors
store.add_texts(["Hello world", "IPFS vector search"])

# Search
results = store.similarity_search("vector search", k=5)
```

### Knowledge Graph Extraction

```python
from ipfs_datasets_py.knowledge_graphs.extraction import KnowledgeGraphExtractor

# Extract entities and relationships from text
extractor = KnowledgeGraphExtractor()
text = "Alice works at OpenAI. She lives in San Francisco."

# Extract knowledge graph
kg = extractor.extract_knowledge_graph(text)
print(f"Entities: {kg.entities}")
print(f"Relationships: {kg.relationships}")
```

#### Optional: Z3 / CVC5 / Lean / Coq theorem provers

Z3, CVC5, Lean, and Coq are external system tools (not Python packages). `ipfs_datasets_py` can use them for symbolic proof execution when installed.

- Manual best-effort installer:
	- `ipfs-datasets-install-provers --yes --z3 --cvc5 --lean --coq`

- Auto-run after `setup.py` install/develop (enabled by default; set to `0` to disable):
	- `IPFS_DATASETS_PY_AUTO_INSTALL_PROVERS=1` (set `0` to disable)
	- Fine-grained toggles:
		- `IPFS_DATASETS_PY_AUTO_INSTALL_Z3=1`
		- `IPFS_DATASETS_PY_AUTO_INSTALL_CVC5=1`
		- `IPFS_DATASETS_PY_AUTO_INSTALL_LEAN=1`
		- `IPFS_DATASETS_PY_AUTO_INSTALL_COQ=1`

Notes:
- Lean installs via `elan` into your user home.
- Z3/CVC5/Coq installation depends on your OS/package manager; auto-install may require root (apt) or manual steps.

## 🤖 MCP Server

The Model Context Protocol (MCP) server provides **200+ tools** across **50+ categories** for AI assistant integration.

### What is MCP?

MCP (Model Context Protocol) enables AI assistants like Claude, ChatGPT, and GitHub Copilot to access external tools and services. Our MCP server exposes comprehensive dataset operations, web scraping, knowledge graphs, and more.

### Starting the Server

```bash
# Start MCP server
ipfs-datasets mcp start

# Server runs on http://localhost:8765
# Dashboard available at http://localhost:8765/dashboard
```

### Tool Categories

The MCP server provides tools in these categories:

- **dataset_tools** - Load, process, and manage datasets
- **vector_tools** - IPLD vector store operations (add, search, migrate)
- **web_archive_tools** - Web scraping, yt-dlp, Common Crawl
- **pdf_tools** - PDF processing and GraphRAG
- **knowledge_graph_tools** - Entity extraction and graph operations  
- **ipfs_tools** - IPFS operations (add, get, pin, cat)
- **p2p_tools** - Distributed computing and workflows
- **cache_tools** - Caching strategies
- **monitoring_tools** - System monitoring and metrics
- ...and 40+ more categories

### Using Tools

```bash
# Discover available tools
ipfs-datasets tools categories

# List tools in a category
ipfs-datasets tools list dataset_tools

# Run a tool
ipfs-datasets tools run dataset_tools load_dataset --source squad --split train

# Run web archive tool
ipfs-datasets tools run web_archive_tools search_common_crawl --query "AI research"
```

### AI Assistant Integration

Once the MCP server is running, AI assistants can discover and execute tools:

```
# From Claude Desktop, ChatGPT, or GitHub Copilot
"Load the squad dataset using MCP tools"
"Search Common Crawl for AI research papers"
"Extract entities from this document using knowledge graph tools"
```

## 📊 MCP Dashboard

The MCP Dashboard provides real-time monitoring and analytics for all MCP operations.

### Features

- **Investigation Tracking** - Track GitHub issues → MCP tools → AI suggestions workflow
- **Tool Usage Analytics** - See which tools are used most, execution times, success rates
- **System Monitoring** - Real-time system health, resource usage, error tracking
- **Real-time Updates** - WebSocket-based live updates of all operations

### Access

```bash
# Start MCP server (includes dashboard)
ipfs-datasets mcp start

# Access dashboard in browser
# URL: http://localhost:8765/dashboard
```

### Dashboard Sections

1. **Investigation Panel** - Active investigations, GitHub issue tracking, tool execution history
2. **Analytics Panel** - Tool usage statistics, performance metrics, success/failure rates
3. **System Panel** - CPU/memory usage, active connections, error logs
4. **Tool Explorer** - Browse all 200+ tools, test executions, view documentation

## 📦 Core Modules

The package includes 13 core modules providing foundational functionality.

### 1. dataset_manager

Dataset loading and management with hardware acceleration support.

```python
from ipfs_datasets_py.dataset_manager import DatasetManager

# Initialize with acceleration
manager = DatasetManager(use_accelerate=True)

# Load dataset
dataset = manager.load_dataset("squad", split="train[:1000]")

# Save processed dataset
manager.save_dataset(dataset, "output/processed.parquet")
```

**Features:**
- HuggingFace datasets integration
- Hardware acceleration support (ipfs_accelerate_py)
- Multiple format support (Parquet, JSONL, CSV)
- Caching and optimization

### 2. config

Configuration management with TOML support and override capabilities.

```python
from ipfs_datasets_py.config import config

# Load configuration
cfg = config()

# Access configuration
database_url = cfg.baseConfig['database']['url']

# Override configuration
cfg.overrideToml(cfg.baseConfig, {'database': {'url': 'new_url'}})
```

**Features:**
- TOML-based configuration
- Hierarchical overrides
- Environment variable support
- Default value handling

### 3. security

Security, authentication, and authorization (planned expansion).

**Planned Features:**
- API key management
- OAuth integration
- Rate limiting
- Access control lists

### 4. monitoring

System monitoring, metrics collection, and health checks.

```python
from ipfs_datasets_py.monitoring import monitor

# Track metrics
monitor.track_metric("api_calls", 1)
monitor.track_metric("processing_time", 0.5)

# Health check
status = monitor.health_check()
```

**Features:**
- Prometheus metrics
- Health check endpoints
- Resource usage tracking
- Performance monitoring

### 5. ipfs_datasets

Core IPFS operations and dataset handling.

```python
from ipfs_datasets_py.ipfs_datasets import ipfs_datasets

# Initialize IPFS operations
ipfs = ipfs_datasets()

# IPFS operations
cid = ipfs.add_file("data.json")
content = ipfs.get_file(cid)
```

**Features:**
- IPFS add/get operations
- Content addressing
- Dataset storage on IPFS
- Pinning management

### 6. content_discovery

IPFS content discovery and indexing.

**Features:**
- Content indexing
- Discovery protocols
- Metadata management
- Search capabilities

### 7. auto_installer

Automatic dependency management and installation.

**Features:**
- Dependency resolution
- Automatic installation
- Version management
- Platform detection

### 8. audit

Comprehensive audit logging for compliance and security.

```python
from ipfs_datasets_py.audit import audit

# Log audit event
audit.log_event("data_access", {"user": "admin", "resource": "dataset_123"})
```

**Features:**
- Event logging
- Compliance tracking
- Security auditing
- Log rotation

### 9. file_detector

File type detection and validation.

**Features:**
- MIME type detection
- File format validation
- Content analysis
- Extension mapping

### 10. admin_dashboard

Administrative web interface for system management.

**Features:**
- User management
- System configuration
- Monitoring dashboard
- Log viewer

### 11. _dependencies

Internal dependency tracking and management.

**Features:**
- Dependency graph
- Version tracking
- Import analysis
- Health checks

### 12. ipfs_multiformats

IPFS multiformat support (CID, multibase, multihash).

**Features:**
- CID encoding/decoding
- Multibase conversion
- Multihash operations
- Format validation

### 13. ipfs_knn_index

K-Nearest Neighbors indexing for IPFS content.

**Features:**
- Vector indexing
- Similarity search
- Distributed KNN
- IPFS integration

## 🎯 Functional Modules

The package includes 12 functional modules providing specialized capabilities.

### 1. dashboards/

Dashboard implementations for monitoring and analytics.

**Components:**
- **mcp_dashboard.py** - Main MCP server dashboard (real-time monitoring)
- **mcp_investigation_dashboard.py** - Investigation workflow tracking
- **unified_monitoring_dashboard.py** - System-wide monitoring
- **news_analysis_dashboard.py** - News aggregation and analysis

```python
from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboard

dashboard = MCPDashboard(port=8765)
dashboard.start()
```

**Features:**
- Real-time updates via WebSocket
- Tool usage analytics
- System health monitoring
- Investigation tracking

### 2. cli/

CLI tool implementations for various integrations.

**Components:**
- **discord_cli.py** - Discord messaging integration
- **github_cli.py** - GitHub operations
- **vscode_cli.py** - VSCode editor integration
- **email_cli.py** - Email notification system

```python
from ipfs_datasets_py.cli.discord_cli import send_discord_message

send_discord_message("Status update", channel="general")
```

**Features:**
- Discord webhooks and messaging
- GitHub CLI integration
- VSCode remote development
- Email notifications

### 3. processors/

Data processors for various formats and operations.

**Components:**
- **graphrag_processor.py** - GraphRAG document processing
- **document_processor.py** - General document processing
- **image_processor.py** - Image analysis
- **video_processor.py** - Video processing

```python
from ipfs_datasets_py.processors.graphrag_processor import GraphRAGProcessor

processor = GraphRAGProcessor()
result = processor.process_pdf("document.pdf")
```

**Features:**
- PDF to knowledge graph
- Document intelligence
- Image OCR and analysis
- Video transcription

### 4. caching/

Caching systems for performance optimization.

**Components:**
- **cache.py** - GitHub API cache
- **query_cache.py** - Query result caching
- **distributed_cache.py** - P2P distributed cache

```python
from ipfs_datasets_py.caching.cache import GitHubAPICache

cache = GitHubAPICache()
result = cache.get_or_fetch("repos/user/project")
```

**Features:**
- LRU caching
- Distributed caching
- Cache invalidation
- Performance optimization

### 5. web_archiving/

Web scraping and archiving capabilities.

**Components:**
- **web_archive.py** - Main web archiving
- **yt_dlp_integration.py** - yt-dlp wrapper (1000+ platforms)
- **ffmpeg_integration.py** - FFmpeg video processing
- **common_crawl.py** - Common Crawl search

```python
from ipfs_datasets_py.web_archiving import create_web_archive

archive = create_web_archive("https://example.com")
```

**Features:**
- yt-dlp integration (1000+ platforms)
- FFmpeg video processing
- Common Crawl search
- WARC file creation

### 6. p2p_networking/

P2P networking and distributed compute.

**Components:**
- **libp2p_kit.py** - libp2p integration
- **p2p_workflow_scheduler.py** - Distributed workflows
- **p2p_peer_registry.py** - Peer management

```python
from ipfs_datasets_py.p2p_networking.libp2p_kit import LibP2PKit

p2p = LibP2PKit()
p2p.start_node()
```

**Features:**
- libp2p networking
- Distributed workflows
- Peer discovery
- Task distribution

### 7. knowledge_graphs/

Knowledge graph extraction and operations.

**Components:**
- **knowledge_graph_extraction.py** - Entity extraction
- **graph_operations.py** - Graph queries
- **reasoning.py** - Graph reasoning

```python
from ipfs_datasets_py.knowledge_graphs import KnowledgeGraphExtractor

extractor = KnowledgeGraphExtractor()
graph = extractor.extract_from_text(document)
```

**Features:**
- Entity extraction
- Relationship detection
- Graph construction
- Cross-document reasoning

### 8. data_transformation/

Data format conversion and transformation.

**Components:**
- **car_conversion.py** - CAR file operations
- **parquet_conversion.py** - Parquet format
- **jsonl_conversion.py** - JSONL format
- **format_detector.py** - Format detection

```python
from ipfs_datasets_py.data_transformation import convert_to_parquet

convert_to_parquet("data.jsonl", "output.parquet")
```

**Features:**
- CAR file creation
- Format conversion
- Data validation
- Schema detection

### 9. integrations/

Third-party service integrations.

**Components:**
- **accelerate_integration.py** - ipfs_accelerate_py integration
- **graphrag_integration.py** - GraphRAG integration
- **vscode_integration.py** - VSCode integration
- **github_integration.py** - GitHub API integration

```python
from ipfs_datasets_py.integrations.accelerate_integration import AccelerateManager

accelerator = AccelerateManager()
accelerator.setup_distributed()
```

**Features:**
- Hardware acceleration (ipfs_accelerate_py)
- GraphRAG integration
- GitHub API
- VSCode remote development

### 10. reasoning/

Logic and reasoning systems.

**Components:**
- **deontological_reasoning.py** - Deontic logic
- **theorem_proving.py** - Formal verification

```python
from ipfs_datasets_py.reasoning import TheoremProver

prover = TheoremProver(backend="z3")
result = prover.prove(formal_logic)
```

**Features:**
- Deontic logic
- Theorem proving (Z3, CVC5, Lean 4, Coq)
- Legal text → formal logic
- Formal verification

### 11. optimizers/

AI-powered optimization systems for knowledge graphs and logic.

**Components:**
- **graphrag/** - Knowledge graph ontology optimizer ([docs](ipfs_datasets_py/optimizers/graphrag/README.md))
  - Multi-agent optimization (Generator, Critic, Mediator, Validator, Optimizer)
  - SGD optimization cycles with convergence detection
  - TDFOL theorem prover integration for logical validation
  - Domain templates (legal, medical, scientific, general)
  - Parallel batch processing with configurable workers

```python
from ipfs_datasets_py.optimizers.graphrag import (
    OntologyHarness, MetricsCollector, OntologyVisualizer
)

# Run ontology optimization with parallel execution
harness = OntologyHarness(parallelism=4)
metrics = MetricsCollector()

cycle_results = harness.run_sgd_cycle(
    data_sources=documents,
    contexts=contexts,
    num_cycles=10,
    convergence_threshold=0.85
)

# Track and visualize results
for cycle in cycle_results:
    for session in cycle.sessions:
        metrics.record_session(session)

visualizer = OntologyVisualizer()
dashboard = visualizer.create_dashboard(metrics)
```

**Features:**
- Multi-agent adversarial optimization (complaint-generator pattern)
- Quality-driven iterative refinement with 5-dimensional scoring
- Logical consistency validation with theorem provers
- Dynamic prompt generation with feedback adaptation
- Comprehensive metrics and visualization
- Production-ready with 305+ tests

### 12. ipfs_formats/

IPFS format handling and operations.

**Components:**
- **car_files.py** - CAR archive operations
- **ipld_operations.py** - IPLD operations
- **content_addressing.py** - CID operations

```python
from ipfs_datasets_py.ipfs_formats import create_car_file

car_cid = create_car_file("data/", "output.car")
```

**Features:**
- CAR archive creation
- IPLD path resolution
- Content addressing
- Format conversion

## 📚 Documentation

### Getting Started
- **[Quick Start Guide](docs/guides/QUICK_START.md)** - Complete getting started tutorial
- **[Installation Guide](docs/installation.md)** - Detailed installation instructions
- **[Architecture Overview](docs/architecture/)** - Package structure and design

### Architecture & Migration (NEW) 🆕
- **[Three-Tier Architecture](docs/PROCESSORS_DATA_TRANSFORMATION_ARCHITECTURE.md)** - Complete architecture documentation
- **[Migration Guide v2.0](docs/MIGRATION_GUIDE_V2.md)** - Comprehensive v1.x → v2.0 migration guide
- **[Deprecation Timeline](docs/DEPRECATION_TIMELINE.md)** - 6-month deprecation schedule (Feb-Aug 2026)
- **[GraphRAG Consolidation](docs/GRAPHRAG_CONSOLIDATION_GUIDE.md)** - Unified GraphRAG processor guide
- **[Multimedia Migration](docs/MULTIMEDIA_MIGRATION_GUIDE.md)** - Multimedia processor migration

### Features & Integration
- **[Complete Features List](docs/FEATURES.md)** - All capabilities explained
- **[Hardware Acceleration](docs/guides/IPFS_ACCELERATE_INTEGRATION.md)** - ipfs_accelerate_py (2-20x speedup)
- **[IPFS Operations](docs/guides/IPFS_KIT_INTEGRATION.md)** - ipfs_kit_py integration
- **[Best Practices](docs/guides/BEST_PRACTICES.md)** - Performance, security, patterns

### Migration & CLI
- **[CLI Tools](docs/guides/CLI_TOOL_MERGE.md)** - Command-line interface guide

## 📄 License

This project is licensed under the AGPL-3.0 License - see the [LICENSE](LICENSE) file for details.

## 🔗 Links

- **Documentation:** [docs/](docs/)
- **Issues:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **Discussions:** [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)

## Credits

**Endomorphosis** [Github](https://github.com/endomorphosis/) Senior ML-OPS Architect

**The-Ride-Never-Ends** [Github](https://github.com/the-ride-never-ends) Junior Developer / Political Scientist

**Coregod360** [Github](https://github.com/Coregod360) Formerly Junior Developer 

---

**Built with** ❤️ **for decentralized AI**

# 🌐 IPFS Datasets Python

> **Decentralized AI Data Platform - Production Ready**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![Production Ready](https://img.shields.io/badge/status-production%20ready-green)](#)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-4500%2B-brightgreen)](./tests/)
[![Coverage](https://img.shields.io/badge/coverage-95%25-brightgreen)](#)
[![Legal V2 Reasoner CI](https://github.com/endomorphosis/ipfs_datasets_py/actions/workflows/legal-v2-reasoner-ci.yml/badge.svg)](https://github.com/endomorphosis/ipfs_datasets_py/actions/workflows/legal-v2-reasoner-ci.yml)


**IPFS Datasets Python** is a comprehensive platform for decentralized AI data processing, combining mathematical theorem proving, AI-powered document intelligence, multimedia processing, and knowledge graph operations—all on decentralized IPFS infrastructure.

## 📑 Table of Contents

- [Key Features](#-key-features)
- [Quick Start](#-quick-start)
- [CLI Tools](#-cli-tools)
- [Hybrid Legal V2 Ops](#-hybrid-legal-v2-ops)
- [MCP Server](#-mcp-server)
- [MCP Dashboard](#-mcp-dashboard)
- [Core Modules](#-core-modules)
- [Functional Modules](#-functional-modules)
  - [Logic & Reasoning](#10-logic)
  - [Zero-Knowledge Proofs](#12-zero-knowledge-proofs-logiczkp)
- [Documentation](#-documentation)
- [Contributing](#-contributing)
- [License](#-license)

## ✨ Key Features

- 🗄️ **IPLD Vector Database** - Production-ready distributed vector search with sharding and replication
- 🔬 **Mathematical Theorem Proving** - Convert legal text to verified formal logic (Z3, CVC5, Lean 4, Coq)
- 🔐 **Zero-Knowledge Proofs** - Privacy-preserving theorem verification with simulated backend and Groth16 Rust FFI (BN254 curve), plus Ethereum on-chain verification
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

# Canonical setup: creates/updates .venv and installs repo dependencies automatically
python scripts/setup/install.py --quick

# The installer re-runs itself inside ./.venv. After that, activate it for normal use.
source .venv/bin/activate

# If you want a different target environment path
python scripts/setup/install.py --quick --venv-dir .venv-pacer-test
```

The setup installer syncs the repository dependency set from [requirements.txt](requirements.txt) into the target virtual environment and then installs the project in editable mode. That keeps a fresh `.venv` consistent without having to remember separate `pip install` commands.

The base install intentionally excludes the third-party `brave-search` package.
Its currently installable release depends on an older `httpx` range that
conflicts with the MCP/FastMCP stack used by this workspace. If you need Brave
Search specifically, install it in a separate optional environment.

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

### Docket Dataset Audit

```bash
# Auto-detect a local docket directory, JSON file, packaged bundle, or CourtListener URL/id
ipfs-datasets docket --input-type auto --input-path /path/to/docket_dir --output /tmp/docket_dataset.json

# Hint auto-detection when an unlabeled export JSON should be labeled as PACER or Tyler Host
ipfs-datasets docket --input-type auto --input-path /path/to/normalized_export.json --source-type-hint pacer --json

# Import a docket JSON and emit citation audit (including EU/member-state citations)
ipfs-datasets docket --input-type json --input-path /path/to/docket.json --citation-source-audit --json

# Import a normalized PACER export directory or JSON payload
ipfs-datasets docket --input-type pacer --input-path /path/to/pacer_export --case-name "Doe v. Example" --json

# Import a raw PACER docket HTML file
ipfs-datasets docket --input-type pacer --input-path /path/to/pacer_docket.html --json

# Import a normalized Tyler Host export JSON or directory
ipfs-datasets docket --input-type tyler_host --input-path /path/to/tyler_export.json --court "State Court" --json

# Import a wrapped PACER or Tyler export JSON without an explicit hint when nested source_type is present
ipfs-datasets docket --input-type auto --input-path /path/to/wrapped_export.json --json

# Tune EU/member-state citation audit extraction
ipfs-datasets docket --input-type json --input-path /path/to/docket.json \
  --citation-source-audit --eu-citation-language en --eu-citation-max-documents 200 --json
```

Normalized PACER/Tyler Host input shape:

```json
{
  "docket_id": "1:24-cv-1001",
  "case_name": "Doe v. Example",
  "court": "D. Example",
  "source_type": "pacer",
  "case_number": "1:24-cv-1001",
  "documents": [
    {
      "id": "doc_1",
      "title": "Complaint",
      "text": "Complaint text or extracted PDF text.",
      "date_filed": "2024-01-10",
      "document_number": "1",
      "source_url": "file:///exports/complaint.pdf",
      "metadata": {
        "source_path": "/exports/complaint.pdf",
        "text_extraction": {"source": "directory_pdf"}
      }
    }
  ],
  "plaintiff_docket": [],
  "defendant_docket": [],
  "authorities": []
}
```

Also accepted:

- Wrapped JSON envelopes such as `{"result": {"source_type": "pacer", "case": {...}}}` or `{"result": {"source_type": "tyler_host", "case": {...}}}`.
- Tyler-style camelCase keys such as `caseNumber`, `caseTitle`, `courtName`, `docketEntries`, `documentTitle`, `filedDate`, `docNumber`, and `documentUrl`.
- PACER HTML files, including docket tables with extra columns, links, and multiline entry text.

For local export folders, the docket CLI can ingest `.txt`, `.md`, `.json`, and `.pdf` documents. PDF folders are post-processed to extract text and detect case numbers from caption text when available.
The `pacer` input type also accepts raw PACER docket HTML files and normalizes docket rows into document records.
Wrapped PACER/Tyler JSON can also be auto-detected without `--source-type-hint` when nested `source_type` metadata is present under `result`, `case`, `data`, or `payload`.
Use `--source-type-hint pacer` or `--source-type-hint tyler_host` with `--input-type auto` when an upstream JSON export does not carry any source label.

See `docs/guides/DOCKET_CITATION_AUDIT.md` for audit payload schemas.
See `docs/guides/legal_data/DOCKET_SOURCE_TEMPLATE_GUIDE.md` for public PACER and portal-parser template references that can be used when building raw-source adapters.

### Workspace Dataset Bundles

```bash
# Export a workspace dataset bundle (single parquet) from a JSON workspace payload
ipfs-datasets workspace --action export --input-path /path/to/workspace.json \
  --output-parquet /tmp/workspace_bundle.parquet --json

# Package a workspace dataset bundle into chain-loadable parquet + optional CAR artifacts
ipfs-datasets workspace --action package --input-path /path/to/discord_export.json \
  --output-dir /tmp/workspace_bundle --package-name workspace_bundle --json

# Inspect a packaged workspace bundle summary
ipfs-datasets workspace --action package-summary --input-path /tmp/workspace_bundle/bundle_manifest.json --json
```

See `docs/guides/legal_data/WORKSPACE_DATASET_BUNDLES.md` for the full bundle lifecycle guide.

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

## ⚖️ Hybrid Legal V2 Ops

Run the package-native V2 legal pipeline using the committed batch fixture:

```bash
bash scripts/ops/legal_data/run_hybrid_v2_pipeline.sh \
    --input-jsonl ipfs_datasets_py/tests/reasoner/fixtures/hybrid_v2_cli_batch_sentences.jsonl \
    --sentence-field sentence \
    --output-json /tmp/hybrid_v2_pipeline_fixture_batch.json \
    --pretty
```

Reference runbook:
- `docs/guides/legal_data/HYBRID_LEGAL_REASONING_OPERATIONS_RUNBOOK.md`

Dedicated CI workflow (local/CI parity for V2 suite):
- `.github/workflows/legal-v2-reasoner-ci.yml`
- `https://github.com/endomorphosis/ipfs_datasets_py/actions/workflows/legal-v2-reasoner-ci.yml`

Comprehensive architecture plan:
- `docs/guides/legal_data/HYBRID_LEGAL_COMPREHENSIVE_IMPROVEMENT_PLAN.md`

Master integration plan (IR/CNL/compilers/reasoner with examples):
- `docs/guides/legal_data/HYBRID_LEGAL_MASTER_INTEGRATION_PLAN.md`

Execution workstreams:
- `docs/guides/legal_data/HYBRID_LEGAL_EXECUTION_WORKSTREAMS.md`

Implementation ticket backlog (issue-ready WS8 plan):
- `docs/guides/legal_data/HYBRID_LEGAL_WS8_IMPLEMENTATION_TICKETS.md`

Copy/paste GitHub issue bodies (WS8 tickets 01-05):
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS8_ISSUE_BODIES_01_05.md`

Copy/paste GitHub issue bodies (WS8 tickets 06-15):
- `docs/guides/legal_data/templates/HYBRID_LEGAL_WS8_ISSUE_BODIES_06_15.md`

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

The package includes 13 functional modules providing specialized capabilities.

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
from ipfs_datasets_py.processors.web_archiving import create_web_archive

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

### 10. logic/

Complete neurosymbolic reasoning system (790+ tests, 94% coverage).

**Sub-modules:**

- **logic/fol/** - First-Order Logic (FOL) converter with 174 tests, 14× cache speedup
- **logic/deontic/** - Deontic logic (obligations, permissions, prohibitions) for legal text analysis
- **logic/TDFOL/** - Temporal Deontic First-Order Logic (TDFOL) core — unified logic representation
- **logic/CEC/** - Cognitive Event Calculus (CEC) framework, native Python 3 (81% submodule coverage, 418+ tests)
- **logic/zkp/** - Zero-Knowledge Proof system (simulated + Groth16 Rust FFI backend)
- **logic/ErgoAI/** - ErgoAI integration *(planned — placeholder)*
- **logic/flogic/** - Functional logic utilities
- **logic/integration/** - Bridge adapters (TDFOL↔CEC, UCAN policy, neurosymbolic GraphRAG)
- **logic/external_provers/** - Z3, CVC5, Lean 4, Coq router

**Canonical API:**

```python
from ipfs_datasets_py.logic.api import FOLConverter, DeonticConverter

# Convert natural language to First-Order Logic
fol = FOLConverter()
result = fol.convert("All humans are mortal. Socrates is human.")

# Convert legal text to deontic formulas
deontic = DeonticConverter()
formula = deontic.convert("The agent must report within 30 days.")
```

**CEC Framework (Cognitive Event Calculus):**

```python
from ipfs_datasets_py.logic.CEC import CECFramework

framework = CECFramework()
framework.initialize()

# Full pipeline: NL → Logic → Prove
task = framework.reason_about(
    "The agent is obligated to perform action X",
    prove=True,
    axioms=["rule1", "rule2"]
)
print(f"Formula: {task.dcec_formula}")
print(f"Proof: {task.proof_result}")
```

**Features:**
- 128 inference rules (41 TDFOL + 87 CEC)
- 5 modal logic provers (K, S4, S5, D, Cognitive)
- Grammar-based NL processing (100+ lexicon entries)
- Legal text → formal deontic logic
- Theorem proving (Z3, CVC5, Lean 4, Coq, SPASS)
- ZKP privacy-preserving proof verification
- IPFS-backed proof caching

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

### 12. Zero-Knowledge Proofs (logic/zkp/)

Privacy-preserving theorem verification — prove that a theorem follows from private axioms without revealing those axioms.

**Backends:**

| Backend | Status | Notes |
|---------|--------|-------|
| `simulated` | ✅ Default | Hash-based mock proofs — educational/demo only, **not cryptographically secure** |
| `groth16` | ⚙️ Opt-in | Real Groth16 zkSNARKs (BN254 curve) via Rust FFI — requires building the bundled Rust binary |

**Quick start (simulation):**

```python
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

# ⚠️ WARNING: simulation backend — NOT cryptographically secure
prover = ZKPProver()                          # defaults to "simulated"
proof = prover.generate_proof(
    theorem="Company is compliant with regulation X",
    private_axioms=[
        "Internal policy A",
        "Internal policy B",
        "Policies A and B satisfy regulation X",
    ],
)

verifier = ZKPVerifier()
assert verifier.verify_proof(proof)
print(f"Proof size: {proof.size_bytes} bytes (~160 bytes)")
```

**Groth16 Rust FFI backend (opt-in):**

```bash
# Build the Rust binary first
cd ipfs_datasets_py/processors/groth16_backend
bash build.sh
# or: pip install -e ".[groth16]"

# Then enable via environment variable (default: 1)
export IPFS_DATASETS_ENABLE_GROTH16=1
```

```python
from ipfs_datasets_py.logic.zkp.backends import get_backend

backend = get_backend("groth16")
backend.ensure_setup(version=1)          # run trusted setup once
proof = backend.generate_proof(
    theorem="Q",
    private_axioms=["P", "P -> Q"],
    metadata={"circuit_version": 1, "ruleset_id": "TDFOL_v1"},
)
assert backend.verify_proof(proof)
```

**On-chain Ethereum verification:**

```python
from ipfs_datasets_py.logic.zkp.eth_integration import EthereumProofClient, EthereumConfig

config = EthereumConfig(
    rpc_url="https://sepolia.infura.io/v3/YOUR_KEY",
    network_id=11155111,
    network_name="sepolia",
    verifier_contract_address="0x...",    # deployed GrothVerifier.sol
    registry_contract_address="0x...",   # deployed ComplaintRegistry.sol
)
client = EthereumProofClient(config)
result = client.submit_and_verify(proof)
```

**UCAN delegation bridge:**

```python
from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import ZKPToUCANBridge

bridge = ZKPToUCANBridge()
result = bridge.prove_and_delegate(
    theorem="P → Q",
    actor="did:key:alice",
    resource="logic/proof",
    ability="proof/invoke",
)
```

**Smart contracts (Solidity):**
- `processors/groth16_backend/contracts/GrothVerifier.sol` — on-chain Groth16 proof verifier
- `processors/groth16_backend/contracts/VKHashRegistry.sol` — verifying-key hash registry

**Features:**
- Pluggable backend protocol (swap simulation for real Groth16 without API change)
- Circuit builder (`ZKPCircuit`) with AND/OR/NOT/IMPLIES gates
- Proof caching with SHA-256 keyed by canonical theorem + axioms
- Deterministic proving (`metadata={"seed": N}`)
- IPFS proof storage (`proof.to_dict()` / `ZKPProof.from_dict(...)`)
- On-chain verification pipeline (EVM, off-chain precheck, gas estimation)
- UCAN delegation caveat embedding

> **Security note:** The `simulated` backend is for prototyping and education only.
> For real zero-knowledge security, build and enable the `groth16` Rust FFI backend.
> See `ipfs_datasets_py/logic/zkp/PRODUCTION_UPGRADE_PATH.md` for the upgrade path.

### 13. ipfs_formats/

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

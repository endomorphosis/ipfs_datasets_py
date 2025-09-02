# 🌐 IPFS Datasets Python

> **The Complete Decentralized AI Data Platform**  
> From raw data to formal proofs, multimedia processing to knowledge graphs—all on decentralized infrastructure.

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Production Ready](https://img.shields.io/badge/status-production%20ready-green)](#production-features)
[![MCP Compatible](https://img.shields.io/badge/MCP-compatible-purple)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-182%2B-brightgreen)](./tests/)

## 🚀 What Makes This Special?

**IPFS Datasets Python** isn't just another data processing library—it's the **first production-ready platform** that combines:

🔬 **[Mathematical Theorem Proving](#-theorem-proving-breakthrough)** - Convert legal text to verified formal logic  
📄 **[AI-Powered Document Processing](#-graphrag-document-intelligence)** - GraphRAG with 182+ production tests  
🎬 **[Universal Media Processing](#-multimedia-everywhere)** - Download from 1000+ platforms with FFmpeg  
🕸️ **[Knowledge Graph Intelligence](#-knowledge-graph-rag)** - Cross-document reasoning with semantic search  
🌐 **[Decentralized Everything](#-decentralized-by-design)** - IPFS-native storage with content addressing  
🤖 **[AI Development Tools](#-ai-development-acceleration)** - Full MCP server with 200+ integrated tools  

### 🎯 I Want To...

| **Goal** | **One Command** | **What You Get** |
|----------|------------------|------------------|
| **🔬 Prove Legal Statements** | `python scripts/demo/demonstrate_complete_pipeline.py` | Website text → Verified formal logic |
| **📄 Process Documents with AI** | `python scripts/demo/demonstrate_graphrag_pdf.py --create-sample` | GraphRAG + Knowledge graphs |
| **🎬 Download Any Media** | `pip install ipfs-datasets-py[multimedia]` | YouTube, Vimeo, 1000+ platforms |
| **🔍 Build Semantic Search** | `pip install ipfs-datasets-py[embeddings]` | Vector search + IPFS storage |
| **🤖 Get AI Dev Tools** | `python -m ipfs_datasets_py.mcp_server` | 200+ tools for AI assistants |

### 📦 Installation

```bash
# Core installation
pip install ipfs-datasets-py

# For specific capabilities
pip install ipfs-datasets-py[theorem_proving]  # Mathematical proofs
pip install ipfs-datasets-py[graphrag]         # Document AI  
pip install ipfs-datasets-py[multimedia]       # Media processing
pip install ipfs-datasets-py[all]             # Everything
```

### 🌟 30-Second Demo

```python
# Load and process any dataset with IPFS backing
from ipfs_datasets_py import load_dataset, IPFSVectorStore

# Load data (works with HuggingFace, local files, IPFS)
dataset = load_dataset("wikipedia", split="train[:100]")

# Create semantic search
vector_store = IPFSVectorStore(dimension=768)
vector_store.add_documents(dataset["text"])

# Search with natural language  
results = vector_store.search("What is artificial intelligence?")
print(f"Found {len(results)} relevant passages")
```

## 🏆 Production Features

### 🔬 **Theorem Proving Breakthrough** ⭐ *World's First*

Convert natural language to mathematically verified formal logic:

```python
from ipfs_datasets_py.logic_integration import create_proof_engine

# Create proof engine (auto-installs Z3, CVC5, Lean, Coq)
engine = create_proof_engine()

# Convert legal text to formal logic and PROVE it
result = engine.process_legal_text(
    "Citizens must pay taxes by April 15th", 
    prover="z3"
)

print(f"Formula: {result.deontic_formula}")
print(f"Proof: {result.proof_status} ({result.execution_time}s)")
# ✅ Proof: Success (0.008s)
```

**Proven Results**: 12/12 complex legal proofs verified • 100% success rate • 0.008s average execution

### 📄 **GraphRAG Document Intelligence**

Production-ready AI document processing with 182+ comprehensive tests:

```python
from ipfs_datasets_py.pdf_processing import PDFProcessor

processor = PDFProcessor()
results = await processor.process_pdf("research_paper.pdf")

print(f"🏷️ Entities: {results['entities_count']}")
print(f"🔗 Relationships: {results['relationships_count']}")
print(f"🧠 Knowledge graph ready for querying")
```

**Battle-Tested**: 136 unit tests • 23 ML integration tests • 12 E2E tests • 11 performance benchmarks

### 🎬 **Multimedia Everywhere**

Download and process media from 1000+ platforms:

```python
from ipfs_datasets_py.multimedia import YtDlpWrapper

downloader = YtDlpWrapper()
result = await downloader.download_video(
    "https://youtube.com/watch?v=example",
    quality="720p",
    extract_audio=True
)
print(f"Downloaded: {result['title']}")
```

**Universal Support**: YouTube, Vimeo, SoundCloud, TikTok, and 1000+ more platforms

### 🕸️ **Knowledge Graph RAG**

Combine vector similarity with graph reasoning:

```python
from ipfs_datasets_py.rag import GraphRAGQueryEngine

query_engine = GraphRAGQueryEngine()
results = query_engine.query(
    "How does IPFS enable decentralized AI?",
    max_hops=3,  # Multi-hop reasoning
    top_k=10
)
```

## 🌐 **Decentralized by Design**

Everything runs on IPFS with content addressing:

- **📊 Data Storage**: Content-addressed datasets with IPLD
- **🔍 Vector Indices**: Distributed semantic search  
- **🎬 Media Files**: Decentralized multimedia storage
- **📄 Documents**: Immutable document processing
- **🔗 Knowledge Graphs**: Cryptographically verified lineage

## 🤖 **AI Development Acceleration**  

Full Model Context Protocol (MCP) server with integrated development tools:

```bash
# Start MCP server for AI assistants
python -m ipfs_datasets_py.mcp_server --port 8080
```

**200+ Tools Available**:
- 🧪 Test generation and execution
- 📚 Documentation generation  
- 🔍 Codebase search and analysis
- 🎯 Linting and code quality
- 📊 Performance profiling
- 🔒 Security scanning

## 🔬 **Complete SAT/SMT Solver and Theorem Prover Integration**

### 🚀 **NEW: End-to-End Website to Formal Proof Pipeline**

Transform legal text from websites into machine-verifiable formal logic with **actual theorem proving execution**:

```bash
# Install all theorem provers automatically (Z3, CVC5, Lean 4, Coq)
python -m ipfs_datasets_py.auto_installer theorem_provers --verbose

# Complete pipeline: Website → GraphRAG → Deontic Logic → Theorem Proof
python demonstrate_complete_pipeline.py --install-all --prove-long-statements

# Process specific website content
python demonstrate_complete_pipeline.py --url "https://legal-site.com" --prover z3
```

### ✅ **Proven Capabilities**

**Real Test Results from Production System:**
- ✅ **8,758 characters** of complex legal text processed from websites
- ✅ **13 entities** and **5 relationships** extracted via GraphRAG
- ✅ **12 formal deontic logic formulas** generated automatically
- ✅ **12/12 proofs successful** with Z3 theorem prover (100% success rate)
- ✅ **Average 0.008s** execution time per proof

### 🛠️ **Automated Theorem Prover Installation**

**Cross-Platform Support:**
- **Linux**: apt, yum, dnf, pacman package managers
- **macOS**: Homebrew package manager  
- **Windows**: Chocolatey, Scoop, Winget package managers

**Supported Theorem Provers:**
- **Z3**: Microsoft's SMT solver - excellent for legal logic and constraints
- **CVC5**: Advanced SMT solver with strong quantifier handling
- **Lean 4**: Modern proof assistant with dependent types
- **Coq**: Mature proof assistant with rich mathematical libraries

```bash
# Install individual provers
python -m ipfs_datasets_py.auto_installer z3 --verbose
python -m ipfs_datasets_py.auto_installer cvc5 --verbose
python -m ipfs_datasets_py.auto_installer lean --verbose
python -m ipfs_datasets_py.auto_installer coq --verbose
```

### 🌐 **Website Text Extraction**

**Multi-Method Extraction with Automatic Fallbacks:**
- **newspaper3k**: Optimized for news and article content
- **readability**: Cleans and extracts main content from web pages
- **BeautifulSoup**: Direct HTML parsing with custom selectors
- **requests**: Basic HTML fetching with user-agent rotation

```python
from ipfs_datasets_py.logic_integration import WebTextExtractor

extractor = WebTextExtractor()
text = extractor.extract_from_url("https://legal-site.com")
# Automatically tries best available method with graceful fallbacks
```

### ⚖️ **Legal Document Formalization**

**Convert Complex Legal Statements to Formal Logic:**

```python
# Input: Complex legal obligation
legal_text = """
The board of directors shall exercise diligent oversight of the 
company's operations while ensuring compliance with all applicable 
securities laws and regulations.
"""

# Processing Pipeline
from ipfs_datasets_py.logic_integration import create_proof_engine
engine = create_proof_engine()

# Output: Verified formal logic
result = engine.process_legal_text(legal_text)
print(f"Deontic Formula: {result.deontic_formula}")
# O[board_of_directors](exercise_diligent_oversight_ensuring_compliance)

# Execute actual proof
proof_result = engine.prove_deontic_formula(result.deontic_formula, "z3")
print(f"Z3 Proof: {proof_result.status} ({proof_result.execution_time}s)")
# ✅ Z3 Proof: Success (0.008s)
```

**Supported Legal Domains:**
- Corporate governance and fiduciary duties
- Employment and labor law obligations
- Intellectual property and technology transfer  
- Contract law and performance requirements
- Data privacy and security compliance
- International trade and export controls

### 📊 **Complete Usage Examples**

```bash
# 1. Install all dependencies and test complete system
python demonstrate_complete_pipeline.py --install-all --test-provers --prove-long-statements

# 2. Process website content with specific prover
python demonstrate_complete_pipeline.py --url "https://example.com/legal-doc" --prover cvc5

# 3. Test local content with all available provers
python demonstrate_complete_pipeline.py --prover all --prove-long-statements

# 4. Quick verification of theorem prover installation
python -m ipfs_datasets_py.auto_installer --test-provers
```

## Key Features

### 🔬 **Formal Logic and Theorem Proving** ⭐ **FLAGSHIP FEATURE**

**Complete end-to-end pipeline from natural language to mathematically verified formal logic:**

#### 🌐 Website Text to Formal Proof Pipeline
- **Multi-method text extraction** from websites with automatic fallbacks
- **GraphRAG processing** for entity extraction and relationship mapping
- **Deontic logic conversion** for legal obligations, permissions, prohibitions
- **Real theorem proving execution** using Z3, CVC5, Lean 4, Coq
- **IPLD storage integration** with complete provenance tracking

#### ⚖️ Legal Document Formalization
- **Complex statement processing**: Multi-clause legal obligations with temporal conditions
- **Cross-domain support**: Corporate governance, employment law, IP, contracts, privacy
- **Production validation**: 12/12 complex proofs verified with 100% success rate
- **Performance optimized**: Average 0.008s execution time per proof

#### 🛠️ Automated Infrastructure 
- **Cross-platform installation**: Linux, macOS, Windows theorem prover setup
- **Dependency management**: Automatic installation of Z3, CVC5, Lean 4, Coq
- **Python integration**: z3-solver, cvc5, pysmt bindings automatically configured
- **Installation verification**: Tests each prover after installation

### Advanced Embedding Capabilities

Comprehensive embedding generation and vector search capabilities:

#### Embedding Generation & Management
- **Multi-Modal Embeddings**: Support for text, image, and hybrid embeddings
- **Sharding & Distribution**: Handle large-scale embedding datasets across IPFS clusters  
- **Sparse Embeddings**: BM25 and other sparse representation support
- **Embedding Analysis**: Visualization and quality assessment tools

#### Vector Search & Storage
- **Multiple Backends**: Qdrant, Elasticsearch, and FAISS integration
- **Semantic Search**: Advanced similarity search with ranking
- **Hybrid Search**: Combine dense and sparse embeddings
- **Index Management**: Automated index optimization and lifecycle management

#### IPFS Cluster Integration
- **Distributed Storage**: Cluster-aware embedding distribution
- **High Availability**: Redundant embedding storage across nodes
- **Performance Optimization**: Embedding-optimized IPFS operations
- **Cluster Monitoring**: Real-time cluster health and performance metrics

#### Web API & Authentication
- **FastAPI Integration**: RESTful API endpoints for all operations
- **JWT Authentication**: Secure access control with role-based permissions
- **Rate Limiting**: Intelligent request throttling and quota management
- **Real-time Monitoring**: Performance dashboards and analytics

### MCP Server with Development Tools

Complete Model Context Protocol (MCP) server implementation with integrated development tools:

- **Test Generator** (`TestGeneratorTool`): Generate unittest test files from JSON specifications
- **Documentation Generator** (`DocumentationGeneratorTool`): Generate markdown documentation from Python code
- **Codebase Search** (`CodebaseSearchEngine`): Advanced pattern matching and code search capabilities
- **Linting Tools** (`LintingTools`): Comprehensive Python code linting and auto-fixing
- **Test Runner** (`TestRunner`): Execute and analyze test suites with detailed reporting

*Note: For optimal performance, use direct imports when accessing development tools due to complex package-level dependency chains.*

## Installation

### Basic Installation
```bash
pip install ipfs-datasets-py
```

### Development Installation
```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
pip install -e .
```

### Optional Dependencies
```bash
# For theorem proving and formal logic (NEW!)
pip install ipfs-datasets-py[theorem_proving]

# For vector search capabilities
pip install ipfs-datasets-py[vector]

# For knowledge graph and RAG capabilities
pip install ipfs-datasets-py[graphrag]

# For web archive and multimedia scraping
pip install ipfs-datasets-py[web_archive,media]

# For security features
pip install ipfs-datasets-py[security]

# For audit logging capabilities
pip install ipfs-datasets-py[audit]

# For all features (includes theorem proving)
pip install ipfs-datasets-py[all]

# Additional media processing dependencies
pip install yt-dlp ffmpeg-python
```

## Key Capabilities

### 🌐 Comprehensive Web Scraping and Archiving

IPFS Datasets Python provides industry-leading web scraping capabilities:

#### Web Archive Integration
- **InterPlanetary Wayback Machine (IPWB)**: Decentralized web archiving on IPFS
- **Internet Archive**: Query and download historical web content
- **Archive.is (archive.today)**: Permanent webpage snapshots  
- **Common Crawl**: Access to massive web crawl datasets
- **Perma.cc**: Academic and legal webpage preservation

#### Multimedia Content Scraping  
- **YT-DLP Integration**: Download from 1000+ platforms (YouTube, Vimeo, TikTok, SoundCloud, etc.)
- **FFmpeg Processing**: Professional media conversion and analysis
- **Batch Operations**: Parallel processing for large-scale content acquisition

#### Advanced Features
- **Multi-Service Archiving**: Archive to multiple services simultaneously
- **Content Deduplication**: Intelligent duplicate detection and removal
- **Quality Control**: Content validation and quality assessment
- **Temporal Analysis**: Historical content tracking and comparison
- **Resource Management**: Optimized resource usage with monitoring

```python
# Quick web scraping example
from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor
from ipfs_datasets_py.mcp_server.tools.media_tools import ytdlp_download_video
from archivenow import archivenow

# Archive website to multiple services
ia_url = archivenow.push("https://example.com", "ia")        # Internet Archive
is_url = archivenow.push("https://example.com", "is")        # Archive.is
warc_file = processor.create_warc("https://example.com")     # Local WARC

# Download multimedia content
video_result = await ytdlp_download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    quality="720p",
    download_info_json=True
)

print(f"Content archived to: {ia_url}, {is_url}, {warc_file}")
print(f"Video downloaded: {video_result['output_file']}")
```

## Basic Usage

```python
# Using MCP tools for dataset operations
from ipfs_datasets_py.mcp_server.tools.dataset_tools.load_dataset import load_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.process_dataset import process_dataset
from ipfs_datasets_py.mcp_server.tools.dataset_tools.save_dataset import save_dataset

# Load a dataset (supports local and remote datasets)
result = await load_dataset("wikipedia", options={"split": "train"})
dataset_id = result["dataset_id"]
print(f"Loaded dataset: {result['summary']}")

# Process the dataset
processed_result = await process_dataset(
    dataset_source=dataset_id,
    operations=[
        {"type": "filter", "column": "length", "condition": ">", "value": 1000},
        {"type": "select", "columns": ["id", "title", "text"]}
    ]
)

# Save to different formats
await save_dataset(processed_result["dataset_id"], "output/dataset.parquet", format="parquet")
```

## MCP Server Usage

### Starting the MCP Server

```python
# Start the MCP server with development tools
from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

server = IPFSDatasetsMCPServer()
await server.start(host="localhost", port=8080)
```

### Using Development Tools Directly

```python
# Direct import method (recommended for performance)
from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import TestGeneratorTool
from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import DocumentationGeneratorTool

# Generate tests from specification
test_gen = TestGeneratorTool()
test_spec = {
    "test_file": "test_example.py",
    "class_name": "TestExample", 
    "functions": ["test_basic_functionality"]
}
result = await test_gen.execute("generate_test", test_spec)

# Generate documentation
doc_gen = DocumentationGeneratorTool()
doc_result = await doc_gen.execute("generate_docs", {
    "source_file": "my_module.py",
    "output_format": "markdown"
})
```

See the [MCP Server Documentation](docs/MCP_TOOLS_COMPREHENSIVE_DOCUMENTATION.md) for complete MCP server documentation.

## Vector Search

```python
import numpy as np
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Create sample vectors
vectors = [np.random.rand(768) for _ in range(100)]
metadata = [{"id": i, "source": "wikipedia", "title": f"Article {i}"} for i in range(100)]

# Create vector index
index = IPFSKnnIndex(dimension=768, metric="cosine")
vector_ids = index.add_vectors(np.array(vectors), metadata=metadata)

# Search for similar vectors
query_vector = np.random.rand(768)
results = index.search(query_vector, k=5)
for i, (vector_id, score, meta) in enumerate(results):
    print(f"Result {i+1}: ID={vector_id}, Score={score:.4f}, Title={meta['title']}")
```

## MCP Server and Development Tools

IPFS Datasets Python includes a comprehensive Model Context Protocol (MCP) server with integrated development tools for AI-assisted workflows.

### Starting the MCP Server

```python
from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

# Start the MCP server
server = IPFSDatasetsMCPServer()
await server.start(host="localhost", port=8080)
```

### Development Tools

The MCP server includes five powerful development tools:

#### 1. Test Generator
Generate unittest test files from JSON specifications:

```python
from ipfs_datasets_py.mcp_server.tools.development_tools.test_generator import TestGeneratorTool

test_generator = TestGeneratorTool()
test_spec = {
    "test_file": "test_my_module.py",
    "class_name": "TestMyModule", 
    "functions": [
        {
            "name": "test_basic_functionality",
            "description": "Test basic functionality"
        }
    ]
}

result = await test_generator.execute("generate_test_file", test_spec)
```

#### 2. Documentation Generator
Generate markdown documentation from Python code:

```python
from ipfs_datasets_py.mcp_server.tools.development_tools.documentation_generator import DocumentationGeneratorTool

doc_generator = DocumentationGeneratorTool()
result = await doc_generator.execute("generate_documentation", {
    "source_file": "path/to/python_file.py",
    "output_format": "markdown"
})
print(result["documentation"])
```

#### 3. Codebase Search
Advanced pattern matching and code search:

```python
from ipfs_datasets_py.mcp_server.tools.development_tools.codebase_search import CodebaseSearchEngine

search_engine = CodebaseSearchEngine()
result = await search_engine.execute("search_codebase", {
    "pattern": "def test_",
    "directory": ".",
    "file_patterns": ["*.py"]
})
for match in result["matches"]:
    print(f"Found in {match['file']}: {match['line']}")
```

#### 4. Linting Tools
Comprehensive Python code linting and auto-fixing:

```python
from ipfs_datasets_py.mcp_server.tools.development_tools.linting_tools import LintingTools

linter = LintingTools()
result = await linter.execute("lint_and_fix_file", {
    "file_path": "path/to/python_file.py"
})
print(f"Fixed {len(result['fixes'])} issues")
```

#### 5. Test Runner
Execute and analyze test suites:

```python
from ipfs_datasets_py.mcp_server.tools.development_tools.test_runner import TestRunner

test_runner = TestRunner()
result = await test_runner.execute("run_tests_in_file", {
    "test_file": "tests/test_my_module.py"
})
print(f"Tests passed: {result['passed']}, Failed: {result['failed']}")
```

### VS Code Integration

The MCP server is designed for seamless integration with VS Code Copilot Chat. Once running, the development tools can be accessed through natural language commands in Copilot Chat.

## GraphRAG Integration

The GraphRAG system combines vector similarity search with knowledge graph traversal for enhanced retrieval and reasoning capabilities. It includes advanced query optimization for efficient cross-document reasoning.

```python
from ipfs_datasets_py.ipld import IPLDStorage, IPLDVectorStore, IPLDKnowledgeGraph
from ipfs_datasets_py.graphrag_integration import GraphRAGQueryEngine
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.cross_document_reasoning import CrossDocumentReasoner
import numpy as np

# Initialize IPLD storage components
storage = IPLDStorage()
vector_store = IPLDVectorStore(dimension=768, metric="cosine", storage=storage)
knowledge_graph = IPLDKnowledgeGraph(name="my_graph", storage=storage, vector_store=vector_store)

# Extract knowledge graph from text
extractor = KnowledgeGraphExtractor()
text = "IPFS is a peer-to-peer hypermedia protocol designed to make the web faster, safer, and more open."
entities, relationships = extractor.extract_graph(text)

# Add entities and relationships to the knowledge graph
for entity in entities:
    knowledge_graph.add_entity(
        entity_type=entity.type,
        name=entity.name,
        properties=entity.properties,
        vector=np.random.rand(768)  # In practice, use actual embeddings
    )

for relationship in relationships:
    knowledge_graph.add_relationship(
        relationship_type=relationship.type,
        source=relationship.source_id,
        target=relationship.target_id,
        properties=relationship.properties
    )

# Initialize query optimizer with metrics collection and visualization
from ipfs_datasets_py.rag.rag_query_optimizer import QueryMetricsCollector, QueryVisualizer

# Create metrics collector and visualizer
metrics_collector = QueryMetricsCollector(
    metrics_dir="metrics",
    track_resources=True
)
visualizer = QueryVisualizer(metrics_collector)

# Initialize query optimizer with metrics and visualization capabilities
query_optimizer = UnifiedGraphRAGQueryOptimizer(
    enable_query_rewriting=True,
    enable_budget_management=True,
    auto_detect_graph_type=True,
    metrics_collector=metrics_collector,
    visualizer=visualizer
)

# Initialize GraphRAG query engine with optimizer
query_engine = GraphRAGQueryEngine(
    vector_stores={"default": vector_store},
    knowledge_graph=knowledge_graph,
    query_optimizer=query_optimizer
)

# Perform a query
results = query_engine.query(
    query_text="How does IPFS work?",
    top_k=5,
    max_graph_hops=2
)

# Initialize cross-document reasoner
cross_doc_reasoner = CrossDocumentReasoner(
    query_optimizer=query_optimizer,
    reasoning_tracer=None,  # Optional LLMReasoningTracer can be provided
    min_connection_strength=0.6,
    max_reasoning_depth=3
)

# Advanced cross-document reasoning
reasoning_results = cross_doc_reasoner.reason_across_documents(
    query="What are the security benefits of content addressing in IPFS?",
    query_embedding=None,  # Will be computed if not provided
    vector_store=vector_store,
    knowledge_graph=knowledge_graph,
    reasoning_depth="deep",  # "basic", "moderate", or "deep"
    max_documents=10,
    min_relevance=0.6,
    max_hops=2,
    return_trace=True  # Include detailed reasoning trace
)

print(f"Answer: {reasoning_results['answer']}")
print(f"Confidence: {reasoning_results['confidence']}")

# View entity-mediated connections
for connection in reasoning_results["entity_connections"]:
    print(f"Connection through {connection['entity']} ({connection['type']}): {connection['relation']} relationship")

# Analyze reasoning trace
if "reasoning_trace" in reasoning_results:
    for step in reasoning_results["reasoning_trace"]["steps"]:
        print(f"Reasoning step: {step['content']}")
```

## Web Archive Integration

```python
from ipfs_datasets_py.web_archive_utils import archive_website, index_warc, extract_dataset_from_cdxj

# Archive a website
warc_file = archive_website("https://example.com/", output_dir="archives")

# Index WARC file to IPFS
cdxj_path = index_warc(warc_file, output_path="indexes/example.cdxj")

# Extract dataset from CDXJ index
dataset = extract_dataset_from_cdxj(cdxj_path)
```

## Security and Governance

IPFS Datasets provides comprehensive security and governance features including data classification, access control, security policy enforcement, and secure operations through an integrated design.

```python
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, SecurityPolicy, AccessControlEntry, DataClassification, 
    DataEncryptionConfig, AccessDecision, SecuritySession, security_operation
)

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()

# Set data classifications
security_manager.set_data_classification(
    resource_id="customer_data",
    classification=DataClassification.CONFIDENTIAL,
    user_id="admin_user"
)

# Add access control entries
ace = AccessControlEntry(
    resource_id="customer_data",
    resource_type="dataset",
    principal_id="data_analyst",
    principal_type="user",
    permissions=["read"],
    conditions={"time_range": {"start": "08:00:00", "end": "18:00:00"}}
)
security_manager.add_access_control_entry(ace)

# Create security policies
policy = SecurityPolicy(
    policy_id="data_access_policy",
    name="Sensitive Data Access Policy",
    description="Controls access to sensitive data",
    enforcement_level="enforcing",
    rules=[
        {
            "type": "access_time",
            "allowed_hours": {"start": 8, "end": 18},
            "severity": "medium"
        },
        {
            "type": "data_volume",
            "threshold_bytes": 50 * 1024 * 1024,  # 50MB
            "severity": "high"
        }
    ]
)
security_manager.add_security_policy(policy)

# Secure operations with security decorator
@security_operation(user_id_arg="user_id", resource_id_arg="resource_id", action="process_data")
def process_data(user_id, resource_id, operation_type):
    # Function is automatically protected with access checks and auditing
    return f"Processed {resource_id} with {operation_type} operation"

# Security session context manager
with SecuritySession(
    user_id="data_analyst",
    resource_id="customer_data",
    action="analyze_data"
) as session:
    # Set context for the session
    session.set_context("purpose", "quarterly_analysis")
    
    session.set_context("client_ip", "192.168.1.100")
    
    # Check access within the session
    decision = session.check_access("read")
    
    # Perform operation if allowed
    if decision == AccessDecision.ALLOW:
        # Perform analysis operation
        pass
        
# Security-Provenance Integration for lineage-aware access control
from ipfs_datasets_py.audit.security_provenance_integration import (
    SecurityProvenanceIntegrator, secure_provenance_operation
)

# Initialize the integrator
integrator = SecurityProvenanceIntegrator()

# Function with lineage-aware access control
@secure_provenance_operation(user_id_arg="user", data_id_arg="data_id")
def access_data_with_lineage(user, data_id):
    """
    This function checks access based on both direct permissions
    and data lineage before execution.
    """
    # Only executes if access is allowed based on lineage checks
    return {"status": "success", "data_id": data_id}

# Legacy security API is still supported
from ipfs_datasets_py.security import SecurityManager, require_authentication, require_access

# Initialize security manager
security = SecurityManager()

# Create users with different roles
admin_id = security.create_user("admin", "admin_password", role="admin")
user_id = security.create_user("standard_user", "user_password", role="user")

# Use authentication and access control
@require_authentication
@require_access("dataset_id", "write")
def update_dataset(user_token, dataset_id, new_data):
    # Update logic here
    return True
```

## Audit Logging and Adaptive Security

```python
from ipfs_datasets_py.audit import AuditLogger, AuditCategory, AuditLevel
from ipfs_datasets_py.audit import FileAuditHandler, JSONAuditHandler

# Get the global audit logger
audit_logger = AuditLogger.get_instance()

# Configure handlers
audit_logger.add_handler(FileAuditHandler("file", "logs/audit.log"))
audit_logger.add_handler(JSONAuditHandler("json", "logs/audit.json"))

# Set thread-local context
audit_logger.set_context(user="current_user", session_id="session123")

# Log various types of events
audit_logger.auth("login", status="success", details={"ip": "192.168.1.100"})
audit_logger.data_access("read", resource_id="dataset123", resource_type="dataset")
audit_logger.security("permission_change", level=AuditLevel.WARNING,
                   details={"target_role": "admin", "changes": ["added_user"]})

# Generate compliance report
from ipfs_datasets_py.audit import GDPRComplianceReporter
reporter = GDPRComplianceReporter()
report = reporter.generate_report(events)
report.save_html("reports/gdpr_compliance.html")

# Setup adaptive security response system
from ipfs_datasets_py.audit import (
    AdaptiveSecurityManager, ResponseRule, ResponseAction, RuleCondition,
    IntrusionDetection, SecurityAlertManager
)

# Create security components
alert_manager = SecurityAlertManager(alert_storage_path="security_alerts.json")
intrusion_detection = IntrusionDetection(alert_manager=alert_manager)

# Create adaptive security manager
adaptive_security = AdaptiveSecurityManager(
    alert_manager=alert_manager,
    audit_logger=audit_logger,
    response_storage_path="security_responses.json"
)

# Define a security response rule for brute force login attempts
brute_force_rule = ResponseRule(
    rule_id="brute-force-response",
    name="Brute Force Login Response",
    alert_type="brute_force_login",
    severity_levels=["medium", "high"],
    actions=[
        {
            "type": "LOCKOUT",
            "duration_minutes": 30,
            "account": "{{alert.source_entity}}"
        },
        {
            "type": "NOTIFY",
            "message": "Brute force login detected from {{alert.source_entity}}",
            "recipients": ["security@example.com"]
        }
    ],
    conditions=[
        RuleCondition("alert.attempt_count", ">=", 5)
    ],
    description="Respond to brute force login attempts"
)

# Add rule to the security manager
adaptive_security.add_rule(brute_force_rule)

# Process any pending security alerts
processed_count = adaptive_security.process_pending_alerts()
print(f"Processed {processed_count} security alerts")
```

## Data Provenance and Lineage

IPFS Datasets provides comprehensive data provenance and lineage tracking features to understand the origin, transformations, and usage of data.

### Basic Provenance Tracking

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize provenance manager with IPLD optimization
provenance = EnhancedProvenanceManager(
    storage_path="provenance_data",
    enable_ipld_storage=True,             # Enable IPLD-based storage
    enable_crypto_verification=True,      # Enable cryptographic verification
    default_agent_id="data_scientist",
    tracking_level="detailed",
    visualization_engine="plotly"         # Use interactive visualizations
)

# Record a data source
source_id = provenance.record_source(
    data_id="customer_data",
    source_type="csv", 
    location="/data/customers.csv",
    format="csv",
    description="Raw customer data",
    size=1024 * 1024 * 5,  # 5MB
    hash="sha256:abc123def456...",
    metadata={"document_id": "customer_dataset"}  # Associate with document
)

# Record data cleaning with context manager
with provenance.begin_transformation(
    description="Clean customer data",
    transformation_type="data_cleaning",
    tool="pandas",
    version="1.5.3",
    input_ids=["customer_data"],
    parameters={"dropna": True, "normalize": True},
    metadata={"document_id": "customer_dataset"}  # Same document ID
) as context:
    # Actual data cleaning code would go here
    # ...
    
    # Set output ID
    context.set_output_ids(["cleaned_data"])

# Record data validation with proper semantic indexing
verification_id = provenance.record_verification(
    data_id="cleaned_data",
    verification_type="schema",
    schema={"required": ["customer_id", "name", "email"]},
    validation_rules=[{"field": "email", "rule": "email_format"}],
    pass_count=950,
    fail_count=50,
    description="Customer data schema validation",  # Improved for semantic search
    metadata={"document_id": "data_validation"}  # Different document ID
)
```

### Enhanced Cross-Document Lineage Tracking

The enhanced lineage tracking system provides sophisticated capabilities for tracking data flows across document and domain boundaries with comprehensive metadata and relationship tracking:

```python
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker, LineageDomain, LineageNode
import time
import datetime

# Initialize the enhanced lineage tracker with comprehensive features
tracker = EnhancedLineageTracker(
    config={
        "enable_audit_integration": True,         # Link with audit logging system
        "enable_temporal_consistency": True,      # Ensure logical timing in data flows
        "enable_semantic_detection": True,        # Detect relationships automatically
        "enable_ipld_storage": True,              # Store lineage data using IPLD
        "domain_validation_level": "strict"       # Enforce domain boundary validation
    }
)

# Create hierarchical domains to organize lineage data
org_domain = tracker.create_domain(
    name="OrganizationData",
    description="Root domain for all organizational data",
    domain_type="organization",
    attributes={"compliance_level": "high"}
)

# Create sub-domains with hierarchical organization
finance_domain = tracker.create_domain(
    name="FinanceSystem",
    description="Financial data processing system",
    domain_type="business",
    parent_domain_id=org_domain,  # Define hierarchical relationship
    attributes={
        "organization": "Finance Department",
        "compliance_frameworks": ["SOX", "GDPR"],
        "data_owner": "finance_team",
        "classification": "restricted"
    },
    metadata_schema={  # Define validation schema for metadata
        "required": ["retention_period", "classification"],
        "properties": {
            "retention_period": {"type": "string"},
            "classification": {"enum": ["public", "internal", "confidential", "restricted"]}
        }
    }
)

analytics_domain = tracker.create_domain(
    name="AnalyticsSystem",
    description="Data analytics platform",
    domain_type="business",
    parent_domain_id=org_domain,  # Define hierarchical relationship
    attributes={
        "organization": "Data Science Team",
        "compliance_frameworks": ["GDPR"],
        "data_owner": "analytics_team",
        "classification": "internal"
    }
)

# Create a boundary between domains with security constraints
finance_to_analytics = tracker.create_domain_boundary(
    source_domain_id=finance_domain,
    target_domain_id=analytics_domain,
    boundary_type="data_transfer",
    attributes={
        "protocol": "SFTP", 
        "encryption": "AES-256",
        "access_control": "role_based",
        "data_masking": "enabled",
        "requires_approval": True
    },
    constraints=[
        {"type": "field_level", "fields": ["account_number", "ssn"], "action": "mask"},
        {"type": "time_constraint", "hours": "8-17", "days": "mon-fri"},
        {"type": "approval", "approvers": ["data_governance_team"]}
    ]
)

# Create nodes in specific domains with rich metadata
finance_data = tracker.create_node(
    node_type="dataset",
    metadata={
        "name": "Financial Transactions",
        "format": "parquet",
        "retention_period": "7 years",
        "classification": "restricted",
        "record_count": 1500000,
        "created_at": datetime.datetime.now().isoformat(),
        "source_system": "SAP Financial",
        "schema_version": "2.3",
        "contains_pii": True,
        "data_quality": {
            "completeness": 0.98,
            "accuracy": 0.95,
            "consistency": 0.97
        },
        "security_controls": {
            "encryption": "column-level",
            "access_restriction": "need-to-know",
            "masking_rules": ["account_number", "ssn"]
        }
    },
    domain_id=finance_domain,
    entity_id="financial_data_001"
)

# Create transformation node with detailed tracking and versioning
transform_node = tracker.create_node(
    node_type="transformation",
    metadata={
        "name": "Transaction Analysis",
        "tool": "pandas",
        "version": "1.5.2",
        "execution_time": "45m",
        "executor": "data_scientist_1",
        "execution_id": "job-12345",
        "git_commit": "a7c3b2e1",
        "environment": "production",
        "configuration": {
            "threads": 8,
            "timeout": 3600,
            "incremental": True
        },
        "security_context": {
            "authentication": "mfa",
            "authorization": "role_based",
            "security_clearance": "confidential"
        }
    },
    domain_id=analytics_domain,
    entity_id="analysis_001"
)

# Create relationships with rich context and boundary crossing information
tracker.create_link(
    source_id=finance_data,
    target_id=transform_node,
    relationship_type="input_to",
    metadata={
        "timestamp": datetime.datetime.now().isoformat(),
        "dataflow_id": "flow-23456",
        "filter_conditions": "transaction_date >= '2023-01-01'",
        "quality_checks_passed": True,
        "record_count": 1500000,
        "boundary_crossing": {
            "approved_by": "data_governance_team",
            "approval_date": datetime.datetime.now().isoformat(),
            "security_validation": "passed",
            "transfer_purpose": "quarterly financial analysis"
        }
    },
    confidence=0.95,
    cross_domain=True  # Explicitly mark as cross-domain
)

# Record detailed transformation information with field-level impacts
tracker.record_transformation_details(
    transformation_id=transform_node,
    operation_type="data_aggregation",
    inputs=[
        {"field": "transaction_date", "type": "date", "nullable": False, "format": "yyyy-MM-dd"},
        {"field": "amount", "type": "decimal(10,2)", "nullable": False, "business_entity": "transaction"},
        {"field": "account_number", "type": "string", "nullable": False, "sensitivity": "high", "pii": True},
        {"field": "transaction_type", "type": "string", "nullable": False, "enum": ["debit", "credit"]}
    ],
    outputs=[
        {"field": "daily_total", "type": "decimal(12,2)", "nullable": False, "aggregation": "sum", "business_entity": "daily_summary"},
        {"field": "transaction_count", "type": "integer", "nullable": False, "aggregation": "count"},
        {"field": "avg_transaction_amount", "type": "decimal(10,2)", "nullable": False, "aggregation": "avg"},
        {"field": "transaction_date", "type": "date", "nullable": False, "granularity": "day"},
        {"field": "account_category", "type": "string", "nullable": False, "derived": True}
    ],
    parameters={
        "group_by": ["transaction_date", "account_category"],
        "aggregations": {
            "amount": ["sum", "avg", "min", "max"],
            "transaction_id": ["count"]
        },
        "filters": {
            "amount": "> 0",
            "transaction_status": "= 'completed'"
        },
        "derivations": {
            "account_category": "CASE WHEN account_number LIKE '1%' THEN 'savings' ELSE 'checking' END"
        }
    },
    impact_level="field"
)

# Create version information for lineage nodes
analysis_version = tracker.create_version(
    node_id=transform_node,
    version_number="1.2.0",
    change_description="Added account categorization and improved aggregation logic",
    parent_version_id="v1.1.0",  # Previous version
    creator_id="data_scientist_1",
    attributes={
        "release_notes": "Enhanced transaction analysis with account categorization",
        "quality_score": 0.98,
        "verification_status": "verified",
        "verification_date": datetime.datetime.now().isoformat(),
        "verified_by": "data_quality_team"
    }
)

# Automatically detect semantic relationships between lineage nodes
relationships = tracker.detect_semantic_relationships(
    confidence_threshold=0.7,
    max_candidates=100,
    methods=["content_similarity", "metadata_overlap", "name_matching", "pattern_recognition"]
)
print(f"Detected {len(relationships)} semantic relationships")
for rel in relationships[:3]:  # Show first three for example
    print(f"- {rel['source_id']} → {rel['target_id']} ({rel['relationship_type']}, confidence: {rel['confidence']:.2f})")

# Generate comprehensive provenance report with impact analysis
report = tracker.generate_provenance_report(
    entity_id="financial_data_001",
    include_visualization=True,
    include_impact_analysis=True,
    include_security_context=True,
    include_transformation_details=True,
    include_audit_trail=True,
    format="html"
)
print(f"Generated {report['format']} report: {report['title']}")
print(f"Report includes {report['statistics']['node_count']} nodes and {report['statistics']['relationship_count']} relationships")

# Export lineage to IPLD for decentralized storage with enhanced metadata
root_cid = tracker.export_to_ipld(
    include_domains=True,
    include_boundaries=True,
    include_versions=True,
    include_transformation_details=True,
    include_semantic_relationships=True,
    encrypt_sensitive_data=True  # Enable encryption for sensitive data
)
print(f"Exported lineage graph to IPLD with root CID: {root_cid}")
```

### Advanced Query and Analysis Capabilities

The enhanced lineage tracking system provides powerful query capabilities with fine-grained filters and comprehensive analysis:

```python
# Query for all transformations in the analytics domain that process PII data
query_results = tracker.query_lineage({
    "node_type": "transformation",
    "domain_id": analytics_domain,
    "start_time": datetime.datetime(2023, 1, 1).timestamp(),
    "end_time": datetime.datetime(2023, 12, 31).timestamp(),
    "metadata_filters": {
        "security_context.security_clearance": "confidential"
    },
    "include_domains": True,
    "include_versions": True,
    "include_transformation_details": True,
    "relationship_filter": {
        "types": ["input_to", "derived_from"],
        "cross_domain": True,
        "min_confidence": 0.8
    }
})
print(f"Query found {len(query_results.nodes)} nodes and {len(query_results.links)} relationships")

# Find all paths between two nodes with detailed analysis
paths = tracker.find_paths(
    start_node_id=finance_data,
    end_node_id=transform_node,
    max_depth=5,
    relationship_filter=["input_to", "derived_from", "version_of"],
    include_metrics=True  # Include path metrics like reliability, latency, etc.
)
print(f"Found {len(paths)} paths with the following metrics:")
for i, path in enumerate(paths):
    print(f"Path {i+1}: Length={len(path)}, Confidence={path['metrics']['confidence']:.2f}, Cross-domain boundaries={path['metrics']['boundary_count']}")

# Temporal consistency validation
inconsistencies = tracker.validate_temporal_consistency()
if inconsistencies:
    print(f"Found {len(inconsistencies)} temporal inconsistencies")
    for issue in inconsistencies[:3]:  # Show first three for example
        print(f"- Inconsistency between {issue['source_id']} and {issue['target_id']}: {issue['description']}")

# Analyze impact of a specific node
impact_analysis = tracker.analyze_impact(
    node_id=finance_data,
    max_depth=3, 
    include_domain_analysis=True,
    include_security_implications=True
)
print(f"Impact analysis shows this node affects {impact_analysis['affected_node_count']} downstream nodes")
print(f"Critical downstream nodes: {', '.join(impact_analysis['critical_nodes'])}")

# Create an interactive visualization of the lineage subgraph
visualization = tracker.visualize_lineage(
    subgraph=query_results,
    output_path="lineage_visualization.html",
    visualization_type="interactive",
    include_domains=True,
    highlight_critical_path=True,
    highlight_boundaries=True,
    include_transformation_details=True,
    include_security_context=True,
    layout="hierarchical"
)
```

## Monitoring and Administration

IPFS Datasets provides comprehensive monitoring and administration capabilities:

```python
from ipfs_datasets_py.monitoring import MonitoringSystem, MetricsCollector
from ipfs_datasets_py.admin_dashboard import AdminDashboard

# Initialize monitoring system
monitoring = MonitoringSystem(
    metrics_path="metrics",
    log_path="logs",
    monitoring_interval=60,  # seconds
    enable_prometheus=True,
    enable_alerts=True
)

# Start collecting system metrics
metrics = monitoring.start_metrics_collection(
    collect_system_metrics=True,
    collect_ipfs_metrics=True,
    collect_application_metrics=True
)

# Track a specific operation
with monitoring.track_operation("data_processing", tags=["high_priority"]):
    # perform operation
    process_data()

# Initialize admin dashboard
dashboard = AdminDashboard(
    monitoring_system=monitoring,
    port=8080,
    enable_user_management=True,
    enable_ipfs_management=True
)

# Launch dashboard
dashboard.start()
```

## 🎉 **NEW: Automated Dependency Installation System**

**🔧 Cross-platform | 🚀 Full functionality | 📦 No more mocks**

IPFS Datasets Python now features an **intelligent automated dependency installation system** that replaces graceful degradations with real functionality. Dependencies are automatically installed across Linux, macOS, and Windows, ensuring complete GraphRAG PDF processing capabilities instead of None fallbacks.

### 🔄 **Transformation: From Mocks to Real Functionality**

```python
# ❌ BEFORE: Graceful degradations with None fallbacks  
import ipfs_datasets_py
print(ipfs_datasets_py.PDFProcessor)       # None - no functionality
print(ipfs_datasets_py.GraphRAGIntegrator) # None - no processing

# ✅ AFTER: Full functionality with automated installation
import ipfs_datasets_py as ids  
processor = ids.PDFProcessor()             # ✅ Complete pipeline operational
integrator = ids.GraphRAGIntegrator()      # ✅ Entity extraction working
query_engine = ids.QueryEngine()          # ✅ Semantic search available
```

### 🌟 **Smart Installation Capabilities**

| **Feature** | **Description** | **Platform** |
|-------------|-----------------|--------------|
| **🖥️ OS Detection** | Automatic Linux/macOS/Windows detection | ✅ Universal |
| **📦 Package Managers** | apt, yum, dnf, brew, choco, winget support | ✅ Auto-detected |
| **🧠 Intelligent Fallbacks** | Multiple package variants tried automatically | ✅ Robust |
| **⚡ On-demand Installation** | Dependencies installed when needed | ✅ Efficient |
| **🔧 Environment Aware** | CI/sandbox detection and safe defaults | ✅ Smart |

### 🛠️ **Installation Methods**

#### **Method 1: Enhanced Cross-Platform Installer (Recommended)**
```bash
git clone https://github.com/endomorphosis/ipfs_datasets_py.git
cd ipfs_datasets_py
chmod +x install.sh && ./install.sh    # Linux/macOS
# install.bat                           # Windows
```

#### **Method 2: Import-Time Auto-Installation**
```python
# Just import - dependencies installed automatically!
import ipfs_datasets_py  # Triggers intelligent dependency management
```

#### **Method 3: Component-Specific Installation**
```python
from ipfs_datasets_py.auto_installer import install_for_component

install_for_component('graphrag')  # Complete PDF processing + GraphRAG  
install_for_component('ocr')       # Multi-engine OCR (Surya, Tesseract, EasyOCR)
install_for_component('vectors')   # Vector stores (FAISS, Qdrant, Elasticsearch)
install_for_component('ml')        # ML stack (transformers, torch, sentence-transformers)
```

#### **Method 4: Configuration Control**
```bash
# Control behavior with environment variables
export IPFS_AUTO_INSTALL=true       # Enable auto-installation (default)
export IPFS_INSTALL_VERBOSE=true    # Show installation progress

python -c "import ipfs_datasets_py; print('✅ Ready!')"
```

## 🚀 **Complete GraphRAG PDF Processing System**

**🎯 182+ tests | 📊 5-phase implementation | 🔧 Real dependencies auto-installed**

### 🎯 **What's New: 5-Phase Implementation Complete**

✅ **Phase 1**: Foundation setup with 10-stage PDF processing pipeline  
✅ **Phase 2**: 136 unit tests across all core components  
✅ **Phase 3**: Real ML integration tests with transformers and neural networks  
✅ **Phase 4**: End-to-end tests with diverse PDF document types  
✅ **Phase 5**: Performance benchmarking and robustness validation  

### 🚀 **Try the Interactive Demo**

Experience the complete GraphRAG PDF system with one command:

```bash
# Run the comprehensive GraphRAG PDF demonstration
python demonstrate_graphrag_pdf.py --create-sample --show-architecture

# Or test with your own PDF
python demonstrate_graphrag_pdf.py your_research_paper.pdf --test-queries
```

### 💻 **Quick Start: Process Your First PDF**

```python
from ipfs_datasets_py.pdf_processing import PDFProcessor

# Initialize the processor
processor = PDFProcessor(enable_monitoring=True)

# Process a PDF through the complete GraphRAG pipeline
results = await processor.process_pdf("research_paper.pdf")

# Results include entity extraction, relationship discovery, and IPLD storage
print(f"✅ Status: {results['status']}")
print(f"🏷️ Entities found: {results.get('entities_count', 0)}")
print(f"🔗 Relationships: {results.get('relationships_count', 0)}")
print(f"🌐 Knowledge graph ready for querying")
```

### 🏗️ **Complete Pipeline Architecture**

```
📄 PDF Input → 📋 Validation → 🔧 Decomposition → 💾 IPLD Storage → 
👁️ OCR Processing → 🤖 LLM Optimization → 🏷️ Entity Extraction → 
🔗 Vector Embedding → 🕸️ GraphRAG Integration → 🌐 Cross-Document Analysis → 
📊 Quality Assessment → 🔍 Query Interface
```

### 🧪 **Comprehensive Testing Infrastructure**

The GraphRAG PDF system includes **182+ production-ready tests**:

| **Test Type** | **Count** | **Coverage** | **Status** |
|---------------|-----------|--------------|------------|
| **Unit Tests** | 136 tests | Core components (PDFProcessor, GraphRAG, QueryEngine, OCR) | ✅ Complete |
| **Integration Tests** | 23 tests | Real ML models (transformers, torch, scikit-learn) | ✅ Complete |
| **End-to-End Tests** | 12 tests | Various PDF types, edge cases, multilingual | ✅ Complete |
| **Performance Tests** | 11 tests | Scaling, memory profiling, concurrent processing | ✅ Complete |

**Run the test suite:**

```bash
# Run all GraphRAG PDF tests
pytest tests/integration/test_graphrag_pdf_integration.py -v

# Run with ML dependencies (requires transformers, torch, etc.)
pytest tests/integration/test_graphrag_ml_integration.py -v

# Run performance benchmarks
pytest tests/performance/test_graphrag_performance.py -v
```

### 📈 **Production Deployment Ready**

✅ **Scalability Validated** - Linear performance scaling tested  
✅ **Memory Optimized** - Leak detection and efficient resource usage  
✅ **Error Resilience** - Graceful fallbacks and comprehensive error handling  
✅ **Security Integrated** - Audit logging and compliance features built-in  
✅ **Monitoring Ready** - Real-time metrics and performance tracking  
✅ **Documentation Complete** - Interactive demos and comprehensive examples  

### ✨ **Key Capabilities**

- **🧠 Intelligent Entity Extraction**: Automatic identification of people, organizations, concepts, and relationships
- **📊 Knowledge Graph Construction**: Build interconnected knowledge graphs from document content
- **🔍 Hybrid Search**: Combine vector similarity with graph traversal for advanced reasoning
- **🌐 Cross-Document Analysis**: Discover connections and patterns across multiple documents
- **💾 IPLD Native Storage**: Content-addressed storage with cryptographic integrity
- **📈 Production Ready**: Comprehensive testing with 182+ tests covering all scenarios
- **🚀 Performance Optimized**: Benchmarked scaling and memory-efficient processing

### 🔧 **Installation for GraphRAG PDF**

```bash
# Basic installation
pip install ipfs-datasets-py

# For full GraphRAG PDF capabilities (recommended)
pip install ipfs-datasets-py[graphrag]

# Or install individual dependencies as needed
pip install transformers sentence-transformers torch scikit-learn

# For the interactive demo with sample PDF generation
pip install reportlab numpy
```

### 📊 **Current Status**

| Component | Status | Description |
|-----------|---------|-------------|
| 📄 PDFProcessor | ✅ Production Ready | Core pipeline with 58 unit tests |
| 🕸️ GraphRAGIntegrator | ✅ Production Ready | Entity extraction with 28 unit tests |
| 🔍 QueryEngine | ✅ Production Ready | Natural language queries with 26 unit tests |
| 👁️ OCREngine | ✅ Production Ready | Multi-engine OCR with 24 unit tests |
| 📈 Monitoring | ✅ Operational | Real-time performance tracking |
| 🧪 Testing | ✅ Complete | 182+ tests across all components |

### 🔍 **Multi-Engine OCR Configuration**

The GraphRAG system includes intelligent OCR with automatic fallback between multiple engines:

```python
from ipfs_datasets_py.pdf_processing import MultiEngineOCR

# Configure OCR with automatic engine selection
ocr_engine = MultiEngineOCR(
    primary_engine='surya',    # Best for academic papers and complex layouts
    fallback_engines=['tesseract', 'easyocr'],  # Backup engines for reliability
    confidence_threshold=0.8,  # Switch to fallback if confidence is low
    auto_rotate=True,          # Automatically detect and fix rotation
    language_detection=True    # Auto-detect document language
)

# Process images with intelligent engine selection
result = await ocr_engine.process_image("scanned_document.png")
print(f"✅ Extracted text: {result['text']}")
print(f"🎯 Confidence: {result['confidence']:.2f}")
print(f"🔧 Engine used: {result['engine']}")
```

**Supported engines and their strengths:**
- **Surya**: Best for academic papers, complex layouts, and scientific documents
- **Tesseract**: Excellent for clean text and standard document formats  
- **EasyOCR**: Superior for handwritten text and multilingual documents

### 🔍 **Intelligent Querying System**

Query your processed documents using natural language with advanced AI reasoning:

```python
from ipfs_datasets_py.pdf_processing import QueryEngine

# Initialize the query engine with your processed documents
query_engine = QueryEngine()

# 1. Entity-focused queries - Find specific people, organizations, concepts
entities = await query_engine.query(
    "Who are the authors mentioned in the documents?",
    query_type="entity_search",
    filters={"entity_type": "person", "confidence_threshold": 0.8}
)
print(f"📍 Found {len(entities['results'])} authors")

# 2. Relationship analysis - Discover connections between entities
relationships = await query_engine.query(
    "How are Google and Microsoft connected in these papers?",
    query_type="relationship_search",
    include_indirect_relationships=True,
    max_hops=3  # Look up to 3 degrees of connection
)
print(f"🔗 Found {len(relationships['connections'])} relationship paths")

# 3. Semantic search with embeddings - Find conceptually similar content
semantic_results = await query_engine.query(
    "Find information about machine learning applications in healthcare",
    query_type="semantic_search",
    filters={
        "min_similarity": 0.7,
        "domains": ["healthcare", "medical", "clinical"]
    },
    top_k=10
)
print(f"🧠 Found {len(semantic_results['results'])} relevant passages")

# 4. Graph traversal - Multi-hop reasoning across documents
reasoning_paths = await query_engine.query(
    "Show the path from AI research to commercial applications",
    query_type="graph_traversal",
    start_concepts=["artificial intelligence", "machine learning"],
    end_concepts=["commercial application", "business use"],
    max_path_length=5
)
print(f"🕸️ Discovered {len(reasoning_paths['paths'])} reasoning paths")

# 5. Cross-document analysis - Find patterns across your document collection
cross_doc_insights = await query_engine.query(
    "What are the common themes across all research papers?",
    query_type="cross_document_analysis",
    analysis_type="theme_extraction",
    minimum_document_frequency=0.3  # Theme must appear in 30%+ of documents
)
print(f"🌐 Identified {len(cross_doc_insights['themes'])} common themes")
```

**Query Types Explained:**
- **🎯 Entity Search**: Find specific people, places, organizations, or concepts
- **🔗 Relationship Search**: Discover how entities are connected
- **🧠 Semantic Search**: Use AI embeddings to find conceptually similar content  
- **🕸️ Graph Traversal**: Multi-hop reasoning following relationship chains
- **🌐 Cross-Document Analysis**: Pattern discovery across your entire document collection

### 🧪 **Testing and Validation**

**Quick Validation:**
```bash
# Test the core GraphRAG functionality (basic components)
python demonstrate_graphrag_pdf.py --create-sample

# Run the basic integration test suite (no external dependencies needed)
python -m pytest tests/integration/test_graphrag_pdf_integration.py::test_basic_components -v
```

**Full Testing with ML Dependencies:**
```bash
# Install full ML dependencies for comprehensive testing
pip install transformers sentence-transformers torch scikit-learn nltk

# Run the complete test suite (all 182+ tests)
python -m pytest tests/integration/test_graphrag_pdf_integration.py -v
python -m pytest tests/integration/test_graphrag_ml_integration.py -v

# Run performance benchmarks
python -m pytest tests/performance/test_graphrag_performance.py -v

# Test with various PDF types
python -m pytest tests/e2e/test_pdf_types_e2e.py -v
```

**Development Testing:**
```bash
# Check current pipeline status and component health
python demonstrate_graphrag_pdf.py --show-architecture

# Test individual components
python -m pytest tests/unit/test_pdf_processor_unit.py -v        # PDFProcessor (58 tests)
python -m pytest tests/unit/test_graphrag_integrator_unit.py -v  # GraphRAG (28 tests)  
python -m pytest tests/unit/test_query_engine_unit.py -v         # QueryEngine (26 tests)
python -m pytest tests/unit/test_ocr_engine_unit.py -v           # OCR (24 tests)
```

**📊 Current Status Overview:**

| **Component** | **Status** | **Tests** | **Features** |
|---------------|------------|-----------|--------------|
| 📄 Core Pipeline | ✅ Production Ready | 58 unit + 10 integration | PDF validation, decomposition, IPLD storage |
| 🕸️ GraphRAG | ✅ Production Ready | 28 unit + 13 ML integration | Entity extraction, knowledge graphs |
| 🔍 Query Engine | ✅ Production Ready | 26 unit + 12 e2e | Natural language queries, graph traversal |
| 👁️ OCR Processing | ✅ Production Ready | 24 unit + 11 performance | Multi-engine text extraction |
| 📊 Monitoring | ✅ Operational | Integrated testing | Real-time metrics, audit logging |

**Need Help?** 
- 🐛 Issues? Run `python demonstrate_graphrag_pdf.py --create-sample` for diagnostics
- 📖 Documentation: Each component has detailed README files with examples
- 🧪 All tests follow GIVEN-WHEN-THEN format for clarity

## 🎬 Multimedia Processing with YT-DLP Integration

IPFS Datasets Python now includes comprehensive multimedia processing capabilities with integrated YT-DLP support for downloading and processing video/audio content from 1000+ platforms.

### Key Features

- **Universal Downloads**: Support for YouTube, Vimeo, SoundCloud, and 1000+ other platforms
- **Audio/Video Processing**: Download videos, extract audio, handle playlists
- **Batch Operations**: Concurrent downloads with progress tracking
- **MCP Server Integration**: Complete set of multimedia tools for the MCP server
- **Format Flexibility**: Multiple output formats and quality settings
- **Advanced Features**: Search, metadata extraction, subtitle downloads

### Quick Start

```python
from ipfs_datasets_py.multimedia import YtDlpWrapper, MediaUtils

# Initialize the YT-DLP wrapper
downloader = YtDlpWrapper(
    default_output_dir="./downloads",
    default_quality="best"
)

# Download a single video
result = await downloader.download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    quality="720p",
    extract_audio=False
)
print(f"Downloaded: {result['video_info']['title']}")

# Download audio only
audio_result = await downloader.download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    audio_only=True,
    audio_format="mp3"
)

# Download entire playlist
playlist_result = await downloader.download_playlist(
    playlist_url="https://www.youtube.com/playlist?list=...",
    max_downloads=10,
    quality="best"
)

# Search for videos
search_results = await downloader.search_videos(
    query="machine learning tutorial",
    max_results=5
)

# Extract video information without downloading
info = await downloader.extract_info(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    download=False
)
print(f"Video duration: {info['info']['duration']} seconds")
```

### Batch Processing

```python
# Download multiple videos concurrently
urls = [
    "https://www.youtube.com/watch?v=video1",
    "https://www.youtube.com/watch?v=video2",
    "https://www.youtube.com/watch?v=video3"
]

batch_result = await downloader.batch_download(
    urls=urls,
    max_concurrent=3,
    quality="720p",
    ignore_errors=True
)

print(f"Downloaded {batch_result['successful']} of {batch_result['total']} videos")
```

### MCP Server Integration

The multimedia functionality is fully integrated with the MCP server, providing five powerful tools:

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ytdlp_download_video,
    ytdlp_download_playlist, 
    ytdlp_extract_info,
    ytdlp_search_videos,
    ytdlp_batch_download
)

# Download video through MCP interface
result = await ytdlp_download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir="./downloads",
    quality="best",
    audio_only=False,
    download_thumbnails=True,
    subtitle_langs=["en", "es"]
)

# Search and download workflow
search_result = await ytdlp_search_videos(
    query="Python tutorial",
    max_results=5
)

# Download the first search result
if search_result["status"] == "success":
    first_video_url = search_result["results"][0]["url"]
    download_result = await ytdlp_download_video(
        url=first_video_url,
        quality="720p"
    )
```

### Advanced Configuration

```python
# Advanced download with custom options
advanced_result = await downloader.download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    format_selector="best[height<=720]",
    subtitle_langs=["en", "es", "fr"],
    download_thumbnails=True,
    download_info_json=True,
    custom_opts={
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en"],
        "ignoreerrors": False
    }
)

# Monitor download progress
downloads = downloader.list_active_downloads()
print(f"Active downloads: {downloads['total_active']}")
print(f"Completed: {downloads['total_completed']}")

# Get specific download status
download_status = downloader.get_download_status(download_id)
if download_status["status"] == "downloading":
    print(f"Progress: {download_status['progress']}%")
```

### Utility Functions

```python
from ipfs_datasets_py.multimedia import MediaUtils

# Validate URLs
is_valid = MediaUtils.validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

# Get supported formats
formats = MediaUtils.get_supported_formats()
print(f"Supported video formats: {formats['video']}")
print(f"Supported audio formats: {formats['audio']}")

# Sanitize filenames for safe storage
clean_filename = MediaUtils.sanitize_filename("My Video <Title>.mp4")

# Format file sizes and durations
size_str = MediaUtils.format_file_size(1024 * 1024 * 500)  # "500.0 MB"
duration_str = MediaUtils.format_duration(3661)  # "01:01:01"
```

### Error Handling and Resilience

```python
# Robust download with error handling
try:
    result = await downloader.download_video(
        url="https://example.com/invalid-video",
        quality="best"
    )
    
    if result["status"] == "success":
        print(f"Downloaded: {result['output_path']}")
    else:
        print(f"Download failed: {result['error']}")
        
except Exception as e:
    print(f"Unexpected error: {e}")

# Batch download with error resilience
batch_result = await downloader.batch_download(
    urls=["https://valid-url.com", "https://invalid-url.com"],
    ignore_errors=True  # Continue processing even if some downloads fail
)

print(f"Successful: {len(batch_result['successful_results'])}")
print(f"Failed: {len(batch_result['failed_results'])}")
```

### Installation and Dependencies

```bash
# Install with multimedia support
pip install ipfs-datasets-py[multimedia]

# Or install dependencies manually
pip install yt-dlp ffmpeg-python

# For development
pip install -e .[multimedia]
```

### Testing

```bash
# Run multimedia validation
python validate_multimedia_simple.py

# Run comprehensive multimedia tests  
python test_multimedia_comprehensive.py

# Run specific test suites
python -m pytest tests/unit/test_ytdlp_wrapper.py -v
python -m pytest tests/unit/test_ytdlp_mcp_tools.py -v
```

### Supported Platforms

YT-DLP supports content download from 1000+ platforms including:
- **Video**: YouTube, Vimeo, Dailymotion, Twitch, TikTok, Instagram
- **Audio**: SoundCloud, Bandcamp, Spotify (metadata), Apple Music (metadata)
- **Live Streams**: YouTube Live, Twitch streams, Facebook Live
- **Educational**: Khan Academy, Coursera, edX
- **And many more...**

For a complete list, see the [YT-DLP supported sites documentation](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

## 🧠 Complete First-Order Logic and Theorem Proving System ⭐ **NEW**

IPFS Datasets Python includes sophisticated logic conversion tools for formal reasoning and legal text analysis.

### First-Order Logic (FOL) Conversion

Convert natural language statements into formal First-Order Logic for automated reasoning and theorem proving:

```python
from ipfs_datasets_py.mcp_server.tools.dataset_tools import text_to_fol

# Convert natural language to FOL
result = await text_to_fol(
    text_input="All cats are animals and some dogs are friendly",
    output_format="json",
    confidence_threshold=0.7
)

print(f"FOL Formula: {result['fol_formulas'][0]['fol_formula']}")
# Output: ∀x (Cat(x) → Animal(x)) ∧ ∃y (Dog(y) ∧ Friendly(y))

# Multiple output formats supported
prolog_result = await text_to_fol(
    text_input="Every student studies hard",
    output_format="prolog"
)

tptp_result = await text_to_fol(
    text_input="If all birds fly then some animals fly", 
    output_format="tptp"
)
```

### Deontic Logic for Legal Text with **ACTUAL THEOREM PROVING** ⭐ **NEW**

Convert legal text into deontic logic and **execute mathematical proofs** using real theorem provers:

```python
from ipfs_datasets_py.logic_integration import create_proof_engine

# Create proof engine with automatic theorem prover setup
engine = create_proof_engine()

# Convert and PROVE legal obligations
result = engine.process_legal_text(
    "Citizens must pay taxes by April 15th",
    prover="z3"  # Also supports: cvc5, lean, coq
)

print(f"Deontic Formula: {result.deontic_formula}")
# Output: O[citizens](pay_taxes_by_april_15)

# EXECUTE ACTUAL PROOF
proof_result = engine.prove_deontic_formula(result.deontic_formula, "z3")
print(f"Z3 Proof: {proof_result.status} ({proof_result.execution_time}s)")
# ✅ Z3 Proof: Success (0.008s)

# Process complex legal statements
complex_text = """
The board of directors shall exercise diligent oversight of the 
company's operations while ensuring compliance with all applicable 
securities laws and regulations.
"""

complex_result = engine.process_legal_text(complex_text, prover="all")
# Executes proofs with Z3, CVC5, Lean 4, and Coq simultaneously!
```

### **Website Text to Formal Proof Pipeline** ⭐ **NEW**

Complete end-to-end processing from website content to verified mathematical proofs:

```python
from ipfs_datasets_py.logic_integration import WebTextExtractor, create_proof_engine

# Extract legal text from websites
extractor = WebTextExtractor()
text = extractor.extract_from_url("https://legal-site.com")

# Convert to formal logic and prove
engine = create_proof_engine()
proof_results = engine.prove_website_content(text, prover="z3")

print(f"Processed {len(proof_results)} legal statements")
print(f"Successful proofs: {sum(1 for r in proof_results if r.status == 'success')}")
# Example output: Processed 12 legal statements, Successful proofs: 12
```

### Advanced Logic Processing

```python
# Batch processing of legal documents
legal_texts = [
    "Drivers must have a valid license",
    "Speed limit is 65 mph on highways", 
    "Parking is prohibited during street cleaning"
]

results = []
for text in legal_texts:
    result = await legal_text_to_deontic(
        text_input=text,
        jurisdiction="us",
        include_exceptions=True
    )
    results.append(result)

# FOL with domain-specific predicates
domain_predicates = ["Student", "Course", "Enrolled", "Completed"]
academic_result = await text_to_fol(
    text_input="All students enrolled in a course must complete assignments",
    domain_predicates=domain_predicates,
    output_format="symbolic"
)
```

### Logic Utilities

The logic tools include comprehensive utility functions for predicate extraction, parsing, and formatting:

```python
from ipfs_datasets_py.mcp_server.tools.dataset_tools.logic_utils import (
    extract_predicates, parse_quantifiers, build_fol_formula,
    extract_normative_elements, identify_obligations
)

# Extract predicates from text
predicates = extract_predicates("All cats are animals and some dogs bark")
print(f"Nouns: {predicates['nouns']}")
print(f"Verbs: {predicates['verbs']}")

# Parse quantifiers
quantifiers = parse_quantifiers("Every student studies and some teachers help")
print(f"Universal: {[q for q in quantifiers if q['type'] == 'universal']}")
print(f"Existential: {[q for q in quantifiers if q['type'] == 'existential']}")

# Identify legal obligations
obligations = identify_obligations("Citizens must vote and may petition the government")
print(f"Obligations: {[o for o in obligations if o['type'] == 'obligation']}")
print(f"Permissions: {[o for o in obligations if o['type'] == 'permission']}")
```

### MCP Server Integration

Both logic tools are fully integrated with the MCP server and can be accessed by AI assistants:

```python
# The tools are automatically available when the MCP server starts
from ipfs_datasets_py.mcp_server import start_server

# Start server with logic tools enabled
start_server(host="localhost", port=8080)

# Tools are discoverable as:
# - mcp_ipfs-datasets_text_to_fol
# - mcp_ipfs-datasets_legal_text_to_deontic
```

### Testing

Comprehensive test suite verifies all functionality:

```bash
# Run all logic-related tests
pytest ipfs_datasets_py/mcp_server/tools/dataset_tools/tests/test_*logic* \
       tests/unit/test_logic_* \
       tests/integration/test_logic_* -v

# Quick verification
python tests/unit/test_logic_tools_discoverability.py
```

**Status**: ✅ **Production Ready** - 26 tests passing, comprehensive coverage of FOL conversion, deontic logic analysis, and MCP tool interfaces.

## 📚 Documentation

The IPFS Datasets Python project provides comprehensive documentation to help you get started quickly and make the most of all available features.

### 📖 Quick Access
- **[Master Documentation Index](docs/MASTER_DOCUMENTATION_INDEX.md)** - Complete navigation to all documentation
- **[Getting Started Guide](docs/getting_started.md)** - Introduction and basic usage
- **[API Reference](docs/api_reference.md)** - Enhanced API documentation with navigation aids
- **[Examples](examples/)** - Working code examples for all major features

### 🔧 Component Documentation
Each major module now includes comprehensive README files with usage examples and integration guides:

- **[Utils](ipfs_datasets_py/utils/README.md)** - Text processing and optimization utilities
- **[Vector Stores](ipfs_datasets_py/vector_stores/README.md)** - Multi-backend vector database support
- **[Embeddings](ipfs_datasets_py/embeddings/README.md)** - Embedding generation and management
- **[Search](ipfs_datasets_py/search/README.md)** - Advanced semantic search capabilities
- **[RAG](ipfs_datasets_py/rag/README.md)** - Retrieval-augmented generation workflows
- **[PDF Processing](ipfs_datasets_py/pdf_processing/README.md)** - Advanced PDF analysis and LLM optimization
- **[Multimedia](ipfs_datasets_py/multimedia/README.md)** - Video and audio processing capabilities
- **[LLM Integration](ipfs_datasets_py/llm/README.md)** - Large language model integration and reasoning
- **[MCP Tools](ipfs_datasets_py/mcp_tools/README.md)** - Model Context Protocol tool integration
- **[IPLD](ipfs_datasets_py/ipld/README.md)** - InterPlanetary Linked Data integration
- **[Audit](ipfs_datasets_py/audit/README.md)** - Security and audit logging

### 🎓 Learning Resources
- **[Tutorials](docs/tutorials/)** - Step-by-step guides for specific features
- **[Advanced Examples](docs/advanced_examples.md)** - Complex usage scenarios
- **[Workflow Examples](docs/workflow_examples.md)** - End-to-end workflow demonstrations
- **[Performance Guide](docs/performance_optimization.md)** - Optimization strategies
- **[Security Guide](docs/security_governance.md)** - Security and governance features
- **[Theorem Prover Integration Guide](THEOREM_PROVER_INTEGRATION_GUIDE.md)** ⭐ **NEW** - Complete SAT/SMT solver setup and usage

### 🛠️ **Interactive Demonstration Scripts** ⭐ **NEW**

Experience all capabilities with comprehensive demonstration scripts:

```bash
# Complete theorem proving pipeline with website extraction
python demonstrate_complete_pipeline.py --install-all --prove-long-statements

# End-to-end website to formal proof (requires network)
python demonstrate_end_to_end_theorem_proving.py --install-provers --show-status

# Local theorem proving without network dependencies
python demonstrate_local_theorem_proving.py --prover all --show-formulas

# Legal deontic logic demonstration
python demonstrate_legal_deontic_logic.py --show-architecture

# GraphRAG PDF processing demonstration
python demonstrate_graphrag_pdf.py --create-sample --test-queries
```

### 🛠️ Developer Resources
- **[Developer Guide](docs/developer_guide.md)** - Development and contribution guidelines
- **[Project Structure](PROJECT_STRUCTURE.md)** - Directory organization and implementation status
- **[MCP Tools Catalog](MCP_TOOLS_COMPLETE_CATALOG.md)** - Complete listing of available tools
- **[Documentation Improvement Report](docs/DOCUMENTATION_IMPROVEMENT_REPORT.md)** - Recent documentation enhancements

### 📊 Documentation Improvements (August 2025)
- ✅ **🔬 NEW: Complete SAT/SMT Theorem Proving Integration** - Full pipeline from website text to formal proofs
- ✅ **🌐 NEW: Website Text Extraction** - Multi-method extraction with automatic fallbacks  
- ✅ **⚖️ NEW: Legal Document Formalization** - Complex legal statements to verified formal logic
- ✅ **🛠️ NEW: Automated Theorem Prover Installation** - Cross-platform Z3, CVC5, Lean 4, Coq setup
- ✅ **📊 NEW: Production Validation** - 12/12 complex proofs verified with 100% success rate
- ✅ **🚀 NEW: GraphRAG PDF Processing** - Complete 5-phase implementation with 182+ tests
- ✅ **Production-Ready Pipeline** - 10-stage processing with comprehensive testing infrastructure
- ✅ **Interactive Demo** - Working demonstration script with sample PDF generation
- ✅ **100% Component Coverage** - Added comprehensive README files for all 12 major subdirectories
- ✅ **Enhanced Navigation** - Improved main documentation with quick access guides and master index
- ✅ **API Reference Enhancement** - Restructured API documentation with use case organization
- ✅ **Comprehensive Examples** - Over 658 total documentation files with practical examples
- ✅ **Standardized Format** - Consistent documentation structure across all components
- ✅ **Cross-References** - Integrated linking between related modules and guides
- ✅ **Organized Stub Files** - Created structure for 362 auto-generated stub files

The documentation now provides multiple pathways to find information:
- **By task/use case** - Quick access to relevant functionality
- **By component** - Deep dive into specific modules  
- **By skill level** - From beginner tutorials to advanced references
- **By integration needs** - Cross-component workflow guidance



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

## ⚡ Quick Start

Choose your path based on what you want to accomplish:

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

## 📖 Documentation & Learning

### 🎓 **Quick Learning Paths**

| **I Am A...** | **Start Here** | **Time to Value** |
|---------------|----------------|-------------------|
| **🔬 Researcher** | [Theorem Proving Guide](docs/guides/THEOREM_PROVER_INTEGRATION_GUIDE.md) | 5 minutes |
| **📄 Document Analyst** | [GraphRAG Tutorial](docs/guides/GRAPHRAG_PRODUCTION_GUIDE.md) | 10 minutes |
| **🎬 Content Creator** | [Multimedia Guide](docs/guides/MULTIMEDIA_PROCESSING_GUIDE.md) | 3 minutes |
| **👩‍💻 Developer** | [MCP Tools Reference](docs/guides/MCP_TOOLS_COMPREHENSIVE_REFERENCE.md) | 1 minute |
| **🏢 Enterprise** | [Production Deployment](docs/guides/DEPLOYMENT_GUIDE.md) | 30 minutes |

### 📚 **Complete Documentation**

- **[🚀 Getting Started](docs/getting_started.md)** - Zero to productive in minutes
- **[🔧 Installation Guide](docs/installation.md)** - Detailed setup for all platforms  
- **[📖 API Reference](docs/api_reference.md)** - Complete API documentation
- **[💡 Examples](examples/)** - Working code for every feature
- **[🎬 Video Tutorials](docs/tutorials/)** - Step-by-step visual guides

### 🛠️ **Interactive Demonstrations**

```bash
# Complete theorem proving pipeline  
python scripts/demo/demonstrate_complete_pipeline.py --install-all

# GraphRAG PDF processing
python scripts/demo/demonstrate_graphrag_pdf.py --create-sample  

# Legal document formalization
python scripts/demo/demonstrate_legal_deontic_logic.py

# Multimedia processing showcase
python scripts/demo/demo_multimedia_final.py
```

## 🌟 **Why Choose IPFS Datasets Python?**

### ✅ **Production Ready**
- **182+ comprehensive tests** across all components
- **Battle-tested** with real workloads and edge cases  
- **Zero-downtime deployments** with Docker and Kubernetes support
- **Enterprise security** with audit logging and access control

### ⚡ **Unique Capabilities** 
- **World's first** natural language to formal proof system
- **Production GraphRAG** with comprehensive knowledge graph construction
- **True decentralization** with IPFS-native everything
- **Universal multimedia** support for 1000+ platforms

### 🚀 **Developer Experience**
- **One-command installation** with automated dependency management
- **200+ AI development tools** integrated via MCP protocol
- **Interactive demonstrations** for every major feature  
- **Comprehensive documentation** with multiple learning paths

### 🔬 **Cutting Edge**
- **Mathematical theorem proving** (Z3, CVC5, Lean 4, Coq)
- **Advanced GraphRAG** with multi-document reasoning
- **Cross-platform multimedia** processing with FFmpeg
- **Distributed vector search** with multiple backends

## 🤝 **Community & Support**

- **📖 Documentation**: [Full Documentation](docs/)  
- **💬 Discussions**: [GitHub Discussions](https://github.com/endomorphosis/ipfs_datasets_py/discussions)
- **🐛 Issues**: [Bug Reports](https://github.com/endomorphosis/ipfs_datasets_py/issues)
- **📧 Contact**: [starworks5@gmail.com](mailto:starworks5@gmail.com)

## 🏗️ **Built With**

**Core Technologies**: Python 3.10+, IPFS, IPLD, PyTorch, Transformers  
**AI/ML Stack**: HuggingFace, Sentence Transformers, FAISS, Qdrant  
**Theorem Provers**: Z3, CVC5, Lean 4, Coq  
**Multimedia**: FFmpeg, YT-DLP, PIL, OpenCV  
**Web**: FastAPI, BeautifulSoup, Playwright  

---

<p align="center">
  <strong>Ready to revolutionize how you work with data?</strong><br>
  <a href="docs/getting_started.md">📖 Get Started</a> •
  <a href="docs/api_reference.md">🔧 API Docs</a> •  
  <a href="examples/">💡 Examples</a> •
  <a href="docs/guides/">🎓 Guides</a>
</p>

<p align="center">
  <sub>Made with ❤️ by the IPFS Datasets team</sub>
</p>
# IPFS Datasets Python - Examples

This directory contains examples demonstrating how to integrate ipfs_datasets_py into your applications. These examples focus on **package modules** (not MCP server tools) to help you understand how to use the library programmatically.

## 🚀 Quick Start

Choose an example based on your needs:

### 🌟 **Essential Examples (Start Here)**

1. **[01_getting_started.py](01_getting_started.py)** - Verify installation and check available modules
2. **[02_embeddings_basic.py](02_embeddings_basic.py)** - Generate text embeddings and measure semantic similarity
3. **[03_vector_search.py](03_vector_search.py)** - Store embeddings and perform similarity search with FAISS/Qdrant
4. **[04_file_conversion.py](04_file_conversion.py)** - Convert various file formats (PDF, DOCX, etc.) to text
5. **[05_knowledge_graphs_basic.py](05_knowledge_graphs_basic.py)** - Extract entities and relationships from text
6. **[06_ipfs_storage.py](06_ipfs_storage.py)** - Store and retrieve data on IPFS

### 📚 **Intermediate Examples**

7. **07_pdf_processing.py** (Coming Soon) - Advanced PDF processing with OCR
8. **08_multimedia_download.py** (Coming Soon) - Download and process media with yt-dlp and FFmpeg
9. **09_batch_processing.py** (Coming Soon) - Process multiple files in parallel
10. **10_legal_data_scraping.py** (Coming Soon) - Scrape federal/state/municipal legal datasets
11. **11_web_archiving.py** (Coming Soon) - Archive and search web content

### 🔬 **Advanced Examples**

12. **12_graphrag_basic.py** (Coming Soon) - Knowledge graph-enhanced RAG
13. **13_logic_reasoning.py** (Coming Soon) - Formal logic and theorem proving
14. **14_cross_document_reasoning.py** (Coming Soon) - Multi-document entity linking
15. **15_graphrag_optimization.py** (Coming Soon) - Ontology generation and optimization

## 📋 Prerequisites

### Core Requirements
```bash
# Install the package
pip install -e .

# Or with all features
pip install -e ".[all]"
```

### Optional Dependencies by Feature

- **Embeddings & ML**: `pip install transformers torch sentence-transformers`
- **Vector Search**: `pip install faiss-cpu` (or `faiss-gpu`) `qdrant-client`
- **PDF Processing**: `pip install pypdf pymupdf pytesseract`
- **Multimedia**: `pip install yt-dlp ffmpeg-python`
- **Legal Data**: `pip install beautifulsoup4 lxml`
- **IPFS**: Install IPFS daemon or use `ipfs_kit_py`

## 🎯 New Package Features

### Core Modules

- **Embeddings** (`ml.embeddings`): Generate semantic embeddings from text
- **Vector Stores** (`vector_stores`): FAISS, Qdrant, IPLD-based vector storage
- **Knowledge Graphs** (`knowledge_graphs`): Extract and query structured knowledge
- **File Conversion** (`processors.file_converter`): Convert 20+ file formats
- **PDF Processing** (`processors.specialized.pdf`): Multi-engine OCR and extraction
- **Multimedia** (`processors.multimedia`): yt-dlp, FFmpeg, Discord, email processing
- **Logic Module** (`logic`): Formal logic, theorem proving, neural-symbolic integration
- **Legal Scrapers** (`processors.legal_scrapers`): 21K+ entity knowledge base
- **Web Archiving** (`web_archiving`): Common Crawl, Brave Search, web scraping
- **IPFS/IPLD**: Content-addressed decentralized storage

### Processor Architecture

The package uses a **unified processor** system:
- `UnifiedProcessor`: Auto-detects input type and routes to appropriate handler
- `ProcessorRegistry`: Plugin-based extensibility
- Protocol-based design for consistency
- Lazy loading and graceful degradation

## 💡 Example Patterns

### Basic Usage Pattern
```python
# 1. Import the module
from ipfs_datasets_py.ml.embeddings import IPFSEmbeddings

# 2. Initialize
embedder = IPFSEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")

# 3. Use the functionality
texts = ["Sample text 1", "Sample text 2"]
embeddings = await embedder.generate_embeddings(texts)
```

### Async/Await Pattern
Most examples use `asyncio` for async operations:
```python
import asyncio

async def main():
    # Your async code here
    pass

if __name__ == "__main__":
    asyncio.run(main())
```

### Error Handling Pattern
```python
try:
    result = await some_operation()
    if result.success:
        print(f"✅ Success: {result.data}")
    else:
        print(f"❌ Failed: {result.error}")
except Exception as e:
    print(f"❌ Error: {e}")
```

## 📖 Running the Examples

### Run Individual Examples
```bash
# From the repository root
python examples/01_getting_started.py
python examples/02_embeddings_basic.py
python examples/03_vector_search.py
```

### With Environment Variables
```bash
# Enable debug logging
LOGLEVEL=DEBUG python examples/02_embeddings_basic.py

# Specify HuggingFace token
HF_TOKEN=your_token python examples/02_embeddings_basic.py
```

## 🔧 Troubleshooting

### Import Errors
If you get import errors:
```bash
# Make sure you're in the repository root
cd /path/to/ipfs_datasets_py

# Install in development mode
pip install -e .

# Or install with all dependencies
pip install -e ".[all]"
```

### Missing Dependencies
```bash
# Check what's installed
python examples/01_getting_started.py

# Install specific features
pip install transformers torch              # For embeddings
pip install faiss-cpu                       # For vector search
pip install yt-dlp ffmpeg-python           # For multimedia
```

### IPFS Daemon
For IPFS examples (06_ipfs_storage.py):
```bash
# Install IPFS
# See: https://docs.ipfs.tech/install/

# Initialize and start
ipfs init
ipfs daemon

# Then run the example
python examples/06_ipfs_storage.py
```


## 📂 Directory Organization

The examples directory is being reorganized for better clarity:

```
examples/
├── README.md                          # This file
├── 01_getting_started.py              # ✅ Installation verification
├── 02_embeddings_basic.py             # ✅ Text embeddings
├── 03_vector_search.py                # ✅ FAISS/Qdrant search
├── 04_file_conversion.py              # ✅ File format conversion
├── 05_knowledge_graphs_basic.py       # ✅ Entity extraction
├── 06_ipfs_storage.py                 # ✅ IPFS operations
├── 07_pdf_processing.py               # 🚧 Coming soon
├── 08_multimedia_download.py          # 🚧 Coming soon
├── 09_batch_processing.py             # 🚧 Coming soon
├── 10_legal_data_scraping.py          # 🚧 Coming soon
├── 11_web_archiving.py                # 🚧 Coming soon
├── 12_graphrag_basic.py               # 🚧 Coming soon
├── 13_logic_reasoning.py              # 🚧 Coming soon
├── 14_cross_document_reasoning.py     # 🚧 Coming soon
├── 15_graphrag_optimization.py        # 🚧 Coming soon
│
├── archived/                          # Old/deprecated examples
│   ├── mcp_dashboard_examples.py
│   ├── demo_mcp_server.py
│   └── ...
│
├── knowledge_graphs/                  # Specialized KG examples
│   └── simple_example.py
│
├── neurosymbolic/                     # Logic & reasoning examples
│   ├── example1_basic_reasoning.py
│   └── ...
│
└── processors/                        # Processor-specific examples
    ├── 04_ipfs_processing.py
    └── ...
```

## 🗂️ Existing Examples Reference

Many existing examples are still valuable but are being reorganized:

### Legacy Examples Still Available
- `knowledge_graph_validation_example.py` - SPARQL validation with Wikidata
- `pipeline_example.py` - Monadic error handling and pipelines
- `advanced_features_example.py` - Metadata extraction and batch processing
- `neurosymbolic/` - Logic reasoning examples (FOL, deontic, temporal)
- `external_provers/` - Z3 theorem prover integration

### MCP Server Examples (Moving to Archived)
These focus on the MCP server rather than package integration:
- `demo_mcp_server.py`, `mcp_server_example.py`
- `demo_mcp_dashboard.py`, `mcp_dashboard_examples.py`
- Various dashboard demos

## 🎓 Learning Path

### **Beginner** (Essential Skills)
1. Start with `01_getting_started.py` to verify setup
2. Learn embeddings with `02_embeddings_basic.py`
3. Understand vector search in `03_vector_search.py`
4. Process files with `04_file_conversion.py`

### **Intermediate** (Build Applications)
5. Extract knowledge with `05_knowledge_graphs_basic.py`
6. Store data decentralized with `06_ipfs_storage.py`
7. Process PDFs with OCR (coming soon)
8. Handle multimedia files (coming soon)
9. Batch processing at scale (coming soon)

### **Advanced** (Production Systems)
10. Build GraphRAG systems (coming soon)
11. Integrate formal logic (coming soon)
12. Cross-document reasoning (coming soon)
13. Ontology optimization (coming soon)

## 🔗 Related Documentation

- **[Main README](../README.md)** - Project overview and installation
- **[CLAUDE.md](../CLAUDE.md)** - Development coordination (for contributors)
- **[API Documentation](../docs/)** - Detailed API references
- **[Tests](../tests/)** - Test suite for reference implementations

## 🤝 Contributing Examples

Want to contribute an example? Please:

1. Follow the existing pattern (docstring, demos, tips)
2. Use async/await where appropriate
3. Handle errors gracefully
4. Include clear comments
5. Add to this README with proper numbering
6. Test thoroughly before submitting

## 📝 Example Template

```python
\"\"\"
Example Title - Brief Description

Detailed description of what this example demonstrates.
Include requirements and use cases.

Requirements:
    - List dependencies here
    - pip install commands

Usage:
    python examples/XX_example_name.py
\"\"\"

import asyncio

async def demo_feature_1():
    \"\"\"Demonstrate feature 1.\"\"\"
    print("\\n" + "="*70)
    print("DEMO 1: Feature Name")
    print("="*70)
    
    try:
        # Implementation
        pass
    except Exception as e:
        print(f"❌ Error: {e}")

def show_tips():
    \"\"\"Show tips for using this feature.\"\"\"
    print("\\n" + "="*70)
    print("TIPS")
    print("="*70)
    # Add useful tips

async def main():
    \"\"\"Run all demonstrations.\"\"\"
    await demo_feature_1()
    show_tips()

if __name__ == "__main__":
    asyncio.run(main())
```

---

**Last Updated**: 2024-02-17  
**Status**: 🚧 Active Refactoring - 6 new examples added, more coming soon
# Basic Examples

Welcome to the basic examples! Start here if you're new to IPFS Datasets Python.

## Examples in This Directory

### 01_getting_started.py
**Your First Steps with IPFS Datasets**
- Installation verification
- Package structure overview
- Basic configuration
- Common patterns

**Run**: `python examples/basic/01_getting_started.py`

### 02_embeddings_basic.py
**Text Embeddings and Semantic Search**
- Generate embeddings from text
- Calculate similarity scores
- Batch processing
- Model selection

**Requirements**: `transformers`, `torch`, `sentence-transformers`

### 03_vector_search.py
**Vector Stores for Semantic Search**
- FAISS vector store setup
- Qdrant integration
- IPLD-based storage
- Similarity search

**Requirements**: `faiss-cpu`, `qdrant-client`

### 04_file_conversion.py
**Universal File Conversion**
- Convert 20+ file formats
- PDF, DOCX, XLSX support
- Text extraction
- Batch conversion

**Requirements**: `pypdf`, `python-docx`, `openpyxl`

### 05_knowledge_graphs_basic.py
**Extract Entities and Relationships**
- Entity extraction from text
- Relationship discovery
- Knowledge graph construction
- Query knowledge graphs

**Requirements**: `transformers`, `spacy`

### 06_ipfs_storage.py
**Content-Addressed Storage with IPFS**
- Store data on IPFS
- Retrieve by CID
- Pin management
- Decentralized storage

**Requirements**: IPFS daemon or `ipfs_kit_py`

## Installation

### Quick Setup
```bash
# Install core dependencies for all basic examples
pip install transformers torch sentence-transformers faiss-cpu
pip install pypdf python-docx openpyxl
pip install ipfshttpclient
```

### Full Installation
```bash
# Install all optional dependencies
pip install -e ".[all]"
```

## Learning Path

1. **Start with 01**: Verify installation and learn basics
2. **Then 02-03**: Understanding embeddings and search
3. **Next 04-05**: Data processing and knowledge extraction
4. **Finally 06**: Decentralized storage with IPFS

## Next Steps

After completing the basic examples, move on to:
- **intermediate/** - More advanced features (PDF/OCR, multimedia, GraphRAG)
- **advanced/** - Production-ready systems (optimization, legal research, distributed)

## Getting Help

- Check the main `examples/README.md` for comprehensive guide
- See `examples/MIGRATION_GUIDE.md` if looking for old examples
- Review package documentation in `docs/`

## Tips

- All examples follow the same pattern (async demos + tips)
- Examples handle missing dependencies gracefully
- Run examples from repository root: `python examples/basic/01_getting_started.py`
- Set `LOGLEVEL=DEBUG` for verbose output

# Example Catalog - IPFS Datasets Python

Complete index of all examples organized by feature, use case, and complexity.

## By Complexity Level

### Basic (Beginner-Friendly)
| # | Example | Description | Requirements |
|---|---------|-------------|--------------|
| 01 | getting_started | Installation, setup, first steps | Core only |
| 02 | embeddings_basic | Text embeddings, similarity | transformers, torch |
| 03 | vector_search | FAISS, Qdrant vector stores | faiss-cpu, qdrant-client |
| 04 | file_conversion | Convert 20+ file formats | pypdf, python-docx |
| 05 | knowledge_graphs_basic | Entity extraction, relationships | transformers, spacy |
| 06 | ipfs_storage | Content-addressed storage | ipfshttpclient |

### Intermediate (Feature-Rich)
| # | Example | Description | Requirements |
|---|---------|-------------|--------------|
| 07 | pdf_processing | Multi-engine OCR, extraction | pypdf, pytesseract |
| 08 | multimedia_download | yt-dlp, FFmpeg processing | yt-dlp, ffmpeg-python |
| 09 | batch_processing | Parallel file processing | Core only |
| 10 | legal_data_scraping | 21K+ legal entity KB | beautifulsoup4, lxml |
| 11 | web_archiving | Common Crawl, Wayback | beautifulsoup4, requests |
| 12 | graphrag_basic | Hybrid vector-graph RAG | transformers, faiss-cpu |
| 13 | logic_reasoning | FOL, temporal, deontic logic | z3-solver |
| 14 | cross_document_reasoning | Multi-doc entity linking | transformers, torch |

### Advanced (Production-Ready)
| # | Example | Description | Requirements |
|---|---------|-------------|--------------|
| 15 | graphrag_optimization | Production GraphRAG systems | transformers, faiss-cpu |
| 16 | logic_enhanced_rag | RAG with formal logic | z3-solver, transformers |
| 17 | legal_knowledge_base | Complete legal research | beautifulsoup4, lxml |
| 18 | neural_symbolic_integration | LLM + theorem proving | z3-solver, transformers |
| 19 | distributed_processing | P2P, IPFS, decentralized | ipfs_kit_py, ipfshttpclient |

## By Feature

### Embeddings & Vector Search
- 02_embeddings_basic.py - Generate embeddings
- 03_vector_search.py - FAISS, Qdrant, IPLD stores
- 12_graphrag_basic.py - Hybrid vector-graph search
- 19_distributed_processing.py - Distributed vector search

### Knowledge Graphs
- 05_knowledge_graphs_basic.py - Entity extraction, relationships
- 12_graphrag_basic.py - Knowledge graph-enhanced RAG
- 14_cross_document_reasoning.py - Entity linking
- 15_graphrag_optimization.py - Production optimization
- 17_legal_knowledge_base.py - Legal entity graphs
- 19_distributed_processing.py - Distributed graphs

### File Processing
- 04_file_conversion.py - Universal file conversion
- 07_pdf_processing.py - PDF with multi-engine OCR
- 08_multimedia_download.py - yt-dlp, FFmpeg
- 09_batch_processing.py - Parallel batch processing

### Logic & Reasoning
- 13_logic_reasoning.py - FOL, temporal, deontic
- 16_logic_enhanced_rag.py - Logic + RAG integration
- 18_neural_symbolic_integration.py - Neural + symbolic

### Legal Research
- 10_legal_data_scraping.py - Access legal datasets
- 17_legal_knowledge_base.py - Complete research system

### Web & Archives
- 11_web_archiving.py - Common Crawl, Wayback Machine
- 17_legal_knowledge_base.py - Multi-engine search

### IPFS & Distributed
- 06_ipfs_storage.py - Basic IPFS operations
- 19_distributed_processing.py - Complete distributed system

## By Use Case

### Academic Research
- 02_embeddings_basic.py - Semantic similarity
- 12_graphrag_basic.py - Research paper analysis
- 14_cross_document_reasoning.py - Literature review
- 18_neural_symbolic_integration.py - AI research

### Legal & Compliance
- 10_legal_data_scraping.py - Legal data access
- 16_logic_enhanced_rag.py - Policy compliance
- 17_legal_knowledge_base.py - Professional legal research

### Data Processing
- 04_file_conversion.py - Format conversion
- 07_pdf_processing.py - Document processing
- 08_multimedia_download.py - Media processing
- 09_batch_processing.py - Scalable pipelines

### AI/ML Applications
- 02_embeddings_basic.py - Embeddings
- 03_vector_search.py - Semantic search
- 12_graphrag_basic.py - Hybrid RAG
- 13_logic_reasoning.py - Explainable AI
- 16_logic_enhanced_rag.py - Verified AI
- 18_neural_symbolic_integration.py - Advanced AI

### Production Systems
- 15_graphrag_optimization.py - Scale to billions of entities
- 17_legal_knowledge_base.py - Complete production system
- 19_distributed_processing.py - Distributed deployment

## By Required API Keys

### No API Keys Required
- 01, 02, 03, 04, 05, 06, 07, 08, 09, 13, 14, 15, 16, 18, 19
- Most examples work without API keys

### Optional API Keys
- 10_legal_data_scraping.py - BRAVE_API_KEY (optional)
- 11_web_archiving.py - BRAVE_API_KEY (optional)
- 12_graphrag_basic.py - HF_TOKEN (optional)
- 17_legal_knowledge_base.py - BRAVE_API_KEY, GOOGLE_CSE_API_KEY (optional)

### Note
DuckDuckGo search engine works without any API key!

## Installation Profiles

### Minimal (Examples 01, 09)
```bash
pip install -e .
```

### Basic Features (01-06)
```bash
pip install transformers torch faiss-cpu sentence-transformers
pip install pypdf python-docx openpyxl ipfshttpclient
```

### Intermediate Features (07-14)
```bash
pip install -r examples/requirements.txt
```

### All Features (01-19)
```bash
pip install -e ".[all]"
```

## Quick Start Guide

### Day 1: Foundations
1. Run `01_getting_started.py` - Verify setup
2. Run `02_embeddings_basic.py` - Learn embeddings
3. Run `03_vector_search.py` - Semantic search

### Day 2: Data Processing
4. Run `04_file_conversion.py` - File formats
5. Run `07_pdf_processing.py` - PDF processing
6. Run `09_batch_processing.py` - Parallel processing

### Day 3: Knowledge & Intelligence
7. Run `05_knowledge_graphs_basic.py` - Entity extraction
8. Run `12_graphrag_basic.py` - GraphRAG fundamentals
9. Run `13_logic_reasoning.py` - Logic systems

### Week 2: Advanced Features
10. Explore intermediate examples (10-14)
11. Study advanced examples (15-19)
12. Choose examples matching your use case

## Total Code Statistics

- **19 examples total**
- **~6,860 lines of code**
- **3 difficulty levels**
- **8 major feature areas**
- **100% async/await**
- **Comprehensive error handling**

## Contributing

Want to add an example?
1. Follow the established pattern (see existing examples)
2. Include comprehensive docstring
3. Add 5-7 demo functions
4. Include tips section
5. Handle missing dependencies gracefully
6. Update this catalog

## Support

- Main README: `examples/README.md`
- Migration guide: `examples/MIGRATION_GUIDE.md`
- Package docs: `docs/`
- Source code: `ipfs_datasets_py/`

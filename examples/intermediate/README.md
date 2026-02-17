# Intermediate Examples

These examples demonstrate more advanced features and integration patterns.

## Examples in This Directory

### 07_pdf_processing.py
**PDF Processing with Multi-Engine OCR**
- Text extraction from PDFs
- Multi-engine OCR (Tesseract, EasyOCR, PaddleOCR)
- Table extraction
- Form processing

**Requirements**: `pypdf`, `pymupdf`, `pytesseract`

### 08_multimedia_download.py
**Download and Process Media Files**
- Download from 1000+ platforms (yt-dlp)
- FFmpeg processing
- Audio/video conversion
- Metadata extraction

**Requirements**: `yt-dlp`, `ffmpeg-python`

### 09_batch_processing.py
**Scalable Batch File Processing**
- Parallel processing
- Progress tracking
- Error handling
- Resource management

**Requirements**: Core dependencies only

### 10_legal_data_scraping.py
**Access Legal Datasets**
- 21,334 entity knowledge base
- Federal, state, municipal data
- Natural language queries
- Search term generation

**Requirements**: `beautifulsoup4`, `lxml`

### 11_web_archiving.py
**Web Scraping and Archiving**
- Common Crawl integration
- Wayback Machine access
- Parallel web archiving
- WARC file handling

**Requirements**: `beautifulsoup4`, `requests`

### 12_graphrag_basic.py
**Knowledge Graph-Enhanced RAG**
- Hybrid vector-graph search
- Entity-centric retrieval
- Multi-hop reasoning
- Subgraph extraction

**Requirements**: `transformers`, `torch`, `faiss-cpu`

### 13_logic_reasoning.py
**Formal Logic and Theorem Proving**
- First-Order Logic (FOL)
- Temporal logic
- Deontic logic (obligations/permissions)
- Z3 theorem prover integration

**Requirements**: `z3-solver`

### 14_cross_document_reasoning.py
**Multi-Document Analysis**
- Entity linking across documents
- Relationship discovery
- Contradiction detection
- Information fusion

**Requirements**: `transformers`, `torch`

## Installation

```bash
# Install all intermediate dependencies
pip install -r examples/requirements.txt

# Or install selectively by feature
pip install pypdf pymupdf pytesseract  # PDF processing
pip install yt-dlp ffmpeg-python       # Multimedia
pip install beautifulsoup4 lxml        # Web scraping
pip install z3-solver                  # Logic reasoning
```

## Learning Path

1. **Processing (07-09)**: PDF, multimedia, batch operations
2. **Legal & Web (10-11)**: Legal data access, web archiving
3. **Advanced AI (12-14)**: GraphRAG, logic, multi-document

## Prerequisites

Before starting intermediate examples, you should:
- Complete basic examples (01-06)
- Understand embeddings and vector search
- Be familiar with async/await patterns

## Next Steps

Ready for production systems? Check out:
- **advanced/** - GraphRAG optimization, legal research, distributed systems

## Common Patterns

All intermediate examples demonstrate:
- Robust error handling
- Graceful degradation
- Progress tracking
- Resource cleanup
- Production-ready code

## Tips

- PDF processing can be memory-intensive
- yt-dlp supports 1000+ platforms
- Legal search has 14 complaint types
- GraphRAG combines vector + graph search
- Logic reasoning enables explainable AI

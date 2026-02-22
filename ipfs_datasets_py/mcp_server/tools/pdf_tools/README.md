# PDF Tools

MCP tools for AI-powered PDF processing with GraphRAG integration. These tools provide a complete
pipeline from raw PDFs to searchable knowledge graphs, enabling entity extraction, relationship
analysis, and semantic querying across large document corpora.

## Tools

| File | Function(s) | Description |
|------|-------------|-------------|
| `pdf_ingest_to_graphrag.py` | `pdf_ingest_to_graphrag()` | Full pipeline: OCR → LLM optimization → entity extraction → graph storage |
| `pdf_extract_entities.py` | `pdf_extract_entities()` | Extract named entities (people, orgs, dates, concepts) from a PDF |
| `pdf_analyze_relationships.py` | `pdf_analyze_relationships()` | Discover relationships between entities across pages/sections |
| `pdf_query_knowledge_graph.py` | `pdf_query_knowledge_graph()` | Query the knowledge graph built from PDF corpus |
| `pdf_query_corpus.py` | `pdf_query_corpus()` | Semantic search over the full indexed PDF corpus |
| `pdf_cross_document_analysis.py` | `pdf_cross_document_analysis()` | Compare and cross-reference entities across multiple PDFs |
| `pdf_optimize_for_llm.py` | `pdf_optimize_for_llm()` | Clean and chunk PDF text optimized for LLM context windows |
| `pdf_batch_process.py` | `pdf_batch_process()` | Batch ingest and process multiple PDFs in parallel |

## Usage

### Full ingest pipeline

```python
from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_ingest_to_graphrag

result = await pdf_ingest_to_graphrag(
    pdf_path="/data/legal_document.pdf",
    graph_name="legal_corpus",         # Target knowledge graph
    enable_ocr=True,                   # Auto-OCR scanned pages
    extract_tables=True,
    chunk_size=512,                    # Tokens per chunk for LLM
    model="gpt-4"                      # LLM for entity extraction
)
# Returns: {"status": "success", "entities_extracted": 142, "relationships": 89, "graph": "legal_corpus"}
```

### Extract entities only

```python
from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_extract_entities

result = await pdf_extract_entities(
    pdf_path="/data/contract.pdf",
    entity_types=["Person", "Organization", "Date", "MonetaryValue"],
    include_context=True               # Include surrounding text for each entity
)
```

### Analyze relationships

```python
from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_analyze_relationships

result = await pdf_analyze_relationships(
    pdf_path="/data/contract.pdf",
    relationship_types=["PARTY_TO", "DATED", "SIGNED_BY"],
    graph_name="contracts"             # Optional: store to graph
)
```

### Query the knowledge graph

```python
from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_query_knowledge_graph

result = await pdf_query_knowledge_graph(
    graph_name="legal_corpus",
    query="MATCH (p:Person)-[:SIGNED]->(d:Document) WHERE d.date > '2023-01-01' RETURN p, d",
    query_type="cypher"               # "cypher" | "natural_language"
)
```

### Semantic corpus search

```python
from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_query_corpus

result = await pdf_query_corpus(
    corpus_name="legal_corpus",
    query="indemnification clauses in software contracts",
    top_k=10,
    include_source_pages=True
)
```

### Batch process

```python
from ipfs_datasets_py.mcp_server.tools.pdf_tools import pdf_batch_process

result = await pdf_batch_process(
    pdf_directory="/data/documents/",
    graph_name="document_corpus",
    parallel_workers=4,
    skip_processed=True               # Resume interrupted batch
)
```

## Pipeline Architecture

```
PDF File
    │
    ▼
PDF Text Extraction (pdfminer / PyMuPDF)
    │
    ├─── OCR (Tesseract) ←─ if scanned pages
    │
    ▼
LLM Optimization (chunking, cleaning)
    │
    ▼
Entity Extraction (NER + LLM)
    │
    ▼
Relationship Discovery
    │
    ▼
Knowledge Graph Storage (graph_tools)
    │
    ▼
Vector Indexing (embedding_tools)
```

## Core Module

All business logic delegates to:
- `ipfs_datasets_py.pdf_processing` — PDF text extraction and chunking
- `ipfs_datasets_py.processors.relationship_analysis_api` — relationship extraction
- `ipfs_datasets_py.core_operations.knowledge_graph_manager` — graph storage

## Dependencies

**Required:**
- Standard library: `logging`, `typing`, `pathlib`

**Optional (specific tools degrade gracefully):**
- `pdfminer.six` or `PyMuPDF (fitz)` — PDF text extraction
- `pytesseract` + `Pillow` — OCR for scanned pages
- `openai` / `anthropic` — LLM-based entity extraction
- `spacy` — NER model for entity extraction without LLM
- `transformers` — local NER/NLP models

## Status

| Tool | Status |
|------|--------|
| `pdf_ingest_to_graphrag` | ✅ Production ready |
| `pdf_extract_entities` | ✅ Production ready |
| `pdf_analyze_relationships` | ✅ Production ready |
| `pdf_query_knowledge_graph` | ✅ Production ready |
| `pdf_query_corpus` | ✅ Production ready |
| `pdf_cross_document_analysis` | ✅ Production ready |
| `pdf_optimize_for_llm` | ✅ Production ready |
| `pdf_batch_process` | ✅ Production ready |

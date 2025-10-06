# PDF Processing - Advanced PDF Analysis and LLM Optimization

This module provides comprehensive PDF processing capabilities with specialized optimization for Large Language Model (LLM) workflows and knowledge extraction.

## Overview

The PDF processing module offers advanced PDF decomposition, content extraction, OCR capabilities, and LLM-optimized text processing. It's designed to handle complex documents and prepare content for embedding generation, vector search, and knowledge graph construction.

## Components

### PDFProcessor (`pdf_processor.py`)
Core PDF processing engine with multi-modal content extraction.

**Key Features:**
- Advanced PDF parsing and content extraction
- Layout analysis and structure preservation
- Table and figure extraction
- Font and formatting analysis
- Multi-language support with OCR fallback

### BatchProcessor (`batch_processor.py`)
High-performance batch processing for large PDF collections.

**Features:**
- Parallel PDF processing with worker pools
- Memory-efficient streaming for large files
- Progress tracking and error recovery
- Distributed processing across multiple nodes
- Automatic load balancing and optimization

### OCREngine (`ocr_engine.py`)
Optical Character Recognition for scanned documents and images.

**Capabilities:**
- Multiple OCR backends (Tesseract, cloud services)
- Language detection and optimization
- Image preprocessing and enhancement
- Confidence scoring and quality assessment
- Layout preservation and formatting recovery

### LLMOptimizer (`llm_optimizer.py`)
Specialized optimization for LLM-ready content preparation.

**Optimization Features:**
- Content chunking optimized for LLM context windows
- Semantic structure preservation
- Metadata enrichment for better retrieval
- Quality scoring for content selection
- Format standardization for consistent processing

### GraphRAG Integrator (`graphrag_integrator.py`)
Integration with Graph-enhanced Retrieval-Augmented Generation workflows.

**Integration Features:**
- Knowledge graph extraction from PDF content
- Entity and relationship identification
- Graph-based context enhancement
- Cross-document relationship discovery
- Semantic linking and clustering

### Query Engine (`query_engine.py`)
Advanced query engine for PDF content search and retrieval.

**Query Capabilities:**
- Natural language querying of PDF collections
- Multi-modal search (text, structure, metadata)
- Citation and reference extraction
- Cross-document analysis
- Contextual result ranking

## Usage Examples

### Basic PDF Processing
```python
from ipfs_datasets_py.pdf_processing import PDFProcessor

processor = PDFProcessor()

# Process a single PDF
result = await processor.process_pdf(
    pdf_path="document.pdf",
    extract_images=True,
    perform_ocr=True
)

print(f"Extracted {len(result.pages)} pages")
print(f"Found {len(result.tables)} tables")
print(f"Extracted {len(result.images)} images")
```

### Batch Processing
```python
from ipfs_datasets_py.pdf_processing import BatchProcessor

batch_processor = BatchProcessor(
    max_workers=4,
    chunk_size=10
)

# Process multiple PDFs
results = await batch_processor.process_batch(
    pdf_paths=pdf_file_list,
    output_format="llm_optimized",
    include_metadata=True
)
```

### LLM Optimization
```python
from ipfs_datasets_py.pdf_processing import LLMOptimizer

optimizer = LLMOptimizer(
    target_model="gpt-4",
    max_context_length=8192
)

# Optimize content for LLM processing
optimized_content = optimizer.optimize_for_llm(
    pdf_content=extracted_text,
    preserve_structure=True,
    include_citations=True
)
```

### GraphRAG Integration
```python
from ipfs_datasets_py.pdf_processing import GraphRAGIntegrator

integrator = GraphRAGIntegrator()

# Extract knowledge graph from PDFs
knowledge_graph = await integrator.extract_graph(
    pdf_collection=processed_pdfs,
    entity_types=["person", "organization", "concept"],
    relationship_types=["authored", "references", "related_to"]
)
```

## Configuration

### Processing Configuration
```python
pdf_config = {
    "ocr": {
        "enabled": True,
        "language": "eng",
        "confidence_threshold": 0.8
    },
    "extraction": {
        "extract_images": True,
        "extract_tables": True,
        "preserve_formatting": True
    },
    "optimization": {
        "target_chunk_size": 512,
        "overlap_ratio": 0.1,
        "quality_threshold": 0.7
    }
}
```

### Batch Processing Configuration
```python
batch_config = {
    "max_workers": 8,
    "chunk_size": 20,
    "memory_limit": "4GB",
    "timeout_per_file": 300,
    "retry_attempts": 3
}
```

## Output Formats

### Standard Formats
- **Raw text** - Plain text extraction
- **Structured JSON** - Hierarchical document structure
- **Markdown** - Formatted text with structure preservation
- **HTML** - Rich formatting with links and styles

### LLM-Optimized Formats
- **Chunked text** - Optimized for embedding generation
- **Contextual segments** - Semantic boundary preservation
- **Metadata-enriched** - Enhanced with extraction metadata
- **Citation-linked** - Cross-referenced with source information

## Advanced Features

### Multi-Modal Processing
- Combined text, image, and table extraction
- OCR integration for scanned documents
- Layout analysis and structure preservation
- Cross-modal relationship discovery

### Quality Assessment
- Content quality scoring and filtering
- OCR confidence evaluation
- Completeness and accuracy metrics
- Automated quality improvement suggestions

### Performance Optimization
- Memory-efficient streaming processing
- GPU acceleration for OCR operations
- Parallel processing with worker pools
- Intelligent caching and memoization

## Integration

The PDF processing module integrates with:

- **Embeddings** - Generate embeddings from extracted content
- **Vector Stores** - Store processed content for search
- **RAG Module** - Prepare content for retrieval workflows
- **Knowledge Graphs** - Extract structured information
- **IPFS** - Distributed storage of processed content

## Dependencies

- `PyMuPDF` - Core PDF processing
- `pytesseract` - OCR capabilities
- `opencv-python` - Image processing
- `pandas` - Table data processing
- `nltk` - Natural language processing
- `asyncio` - Asynchronous operations

## See Also

- [RAG Module](../rag/README.md) - Retrieval-augmented generation workflows
- [Embeddings](../embeddings/README.md) - Embedding generation from PDF content
- [Utils](../utils/README.md) - Text processing utilities
- [PDF Processing Guide](../../docs/pdf_processing.md) - Detailed processing guide
- [Performance Optimization](../../docs/performance_optimization.md) - Optimization strategies
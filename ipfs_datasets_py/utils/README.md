# Utils - Text Processing and Optimization Utilities

This module provides core text processing, chunking, and optimization utilities for the IPFS Datasets Python library.

## Overview

The utils module contains essential utilities for processing and optimizing text data in preparation for embedding generation, vector storage, and search operations.

## Components

### TextProcessor (`text_processing.py`)
Advanced text processing and normalization utility for document pipeline operations.

**Key Features:**
- Comprehensive text cleaning and normalization
- Intelligent sentence segmentation
- Language detection capabilities
- Quality assessment metrics
- Content optimization for ML applications

**Main Methods:**
- `clean_text()` - Clean and normalize text content
- `segment_sentences()` - Intelligent sentence boundary detection
- `assess_quality()` - Evaluate text quality metrics
- `normalize_whitespace()` - Standardize whitespace and formatting

### ChunkOptimizer (`chunk_optimizer.py`)
Intelligent text chunking and optimization for embedding generation.

**Key Features:**
- Multiple chunking strategies (fixed, semantic, sentence-based)
- Chunk size optimization for different embedding models
- Overlap management for context preservation
- Performance optimization for large documents

**Main Methods:**
- `optimize_chunks()` - Create optimized text chunks
- `calculate_optimal_size()` - Determine ideal chunk size
- `merge_small_chunks()` - Consolidate undersized chunks
- `validate_chunks()` - Ensure chunk quality and consistency

## Usage Examples

### Basic Text Processing
```python
from ipfs_datasets_py.utils import TextProcessor

processor = TextProcessor()
cleaned_text = processor.clean_text(raw_text)
sentences = processor.segment_sentences(cleaned_text)
quality_score = processor.assess_quality(cleaned_text)
```

### Text Chunking
```python
from ipfs_datasets_py.utils import ChunkOptimizer

optimizer = ChunkOptimizer()
chunks = optimizer.optimize_chunks(
    text=document_text,
    target_size=512,
    overlap_ratio=0.1
)
```

## Configuration

Both components support extensive configuration through initialization parameters:

- **Language settings** - Specify target language for processing
- **Quality thresholds** - Set minimum quality requirements
- **Chunk parameters** - Configure size, overlap, and splitting strategies
- **Performance settings** - Memory and processing optimizations

## Integration

The utils module integrates seamlessly with other IPFS Datasets components:

- **Embeddings module** - Provides optimized text for embedding generation
- **PDF processing** - Processes extracted text from PDF documents
- **Search module** - Prepares text for indexing and search operations
- **GraphRAG module** - Optimizes text chunks for retrieval operations

## Dependencies

- `nltk` - Natural language processing
- `re` - Regular expression support
- Standard library modules for text processing

## See Also

- [Embeddings Module](../embeddings/README.md) - Embedding generation using processed text
- [PDF Processing](../processors/pdf_processing.py) - PDF text extraction and processing
- [Search Module](../search/README.md) - Text indexing and search capabilities
- [GraphRAG Optimizers](../optimizers/graphrag/README.md) - Graph-enhanced retrieval workflows
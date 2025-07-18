# Getting Started with IPFS Datasets Python

This guide will help you get started with the IPFS Datasets Python package, covering installation, basic usage, and common workflows.

## Table of Contents

1. [Installation](#installation)
2. [Basic Concepts](#basic-concepts)
3. [Loading Datasets](#loading-datasets)
4. [Working with Datasets](#working-with-datasets)
5. [Converting Between Formats](#converting-between-formats)
6. [Vector Search](#vector-search)
7. [PDF Processing and LLM Optimization](#pdf-processing-and-llm-optimization)
8. [Knowledge Graph Extraction](#knowledge-graph-extraction)
9. [GraphRAG Integration](#graphrag-integration)
10. [Web Archive Integration](#web-archive-integration)
11. [Next Steps](#next-steps)

## Installation

### Prerequisites

- Python 3.7 or higher
- pip (Python package manager)
- IPFS daemon (optional, but recommended for full functionality)

### Basic Installation

```bash
pip install ipfs-datasets-py
```

### Development Installation

For development or to use the latest features:

```bash
git clone https://github.com/your-organization/ipfs_datasets_py.git
cd ipfs_datasets_py
pip install -e .
```

### Installing Optional Dependencies

For certain features, you may need additional dependencies:

```bash
# For vector search capabilities
pip install ipfs-datasets-py[vector]

# For knowledge graph and RAG capabilities
pip install ipfs-datasets-py[graphrag]

# For web archive integration
pip install ipfs-datasets-py[webarchive]

# For all features
pip install ipfs-datasets-py[all]
```

## Basic Concepts

IPFS Datasets Python is built around several key concepts:

1. **Content-Addressed Storage**: Data is addressed by its content (hash) rather than location
2. **IPLD (InterPlanetary Linked Data)**: Data structures for content-addressed data
3. **CAR (Content Addressable aRchives)**: Format for exchanging IPLD data
4. **Vector Storage**: Efficient storage and search for embeddings
5. **Knowledge Graphs**: Entity and relationship modeling with IPLD
6. **GraphRAG**: Graph-based retrieval augmented generation

## Loading Datasets

IPFS Datasets Python provides a unified interface for loading datasets from various sources.

### Loading from Hugging Face Datasets

```python
from ipfs_datasets_py import ipfs_datasets

# Load a dataset from Hugging Face
dataset = ipfs_datasets.load_dataset("wikipedia", subset="20220301.en")
print(f"Loaded dataset with {len(dataset)} records")
```

### Loading from Local Files

```python
# Load from a local Parquet file
dataset = ipfs_datasets.load_dataset("path/to/dataset.parquet")

# Load from a CAR file
dataset = ipfs_datasets.load_dataset("path/to/dataset.car")
```

### Loading from IPFS

```python
# Load by CID
dataset = ipfs_datasets.load_dataset("bafybeihsl7tqdebswdmafvytgkofgxnpq5rwzzqpsbd7gtaiujwsn4qeyy")
```

## Working with Datasets

Once loaded, you can work with datasets using familiar operations.

### Basic Data Exploration

```python
# Display basic information
print(f"Dataset has {len(dataset)} rows and {len(dataset.features)} columns")
print(f"Columns: {list(dataset.features.keys())}")

# Show a sample
print(dataset[:5])
```

### Processing Datasets

```python
from ipfs_datasets_py import ipfs_datasets

# Apply processing operations
processed_dataset = ipfs_datasets.process_dataset(
    dataset,
    operations=[
        {"type": "filter", "column": "length", "condition": ">", "value": 1000},
        {"type": "select", "columns": ["id", "title", "text"]},
        {"type": "sort", "by": "title"}
    ]
)

print(f"Processed dataset has {len(processed_dataset)} rows")
```

### Saving Datasets

```python
# Save to Parquet
ipfs_datasets.save_dataset(dataset, "output/dataset.parquet", format="parquet")

# Save to CAR
cid = ipfs_datasets.save_dataset(dataset, "output/dataset.car", format="car")
print(f"Dataset saved with root CID: {cid}")
```

## Converting Between Formats

IPFS Datasets Python makes it easy to convert between different data formats.

### Parquet to CAR Conversion

```python
from ipfs_datasets_py.car_conversion import parquet_to_car

# Convert Parquet to CAR
root_cid = parquet_to_car(
    parquet_path="input/dataset.parquet",
    car_path="output/dataset.car",
    hash_columns=["id"]  # Use these columns for content-addressing
)

print(f"Conversion complete. Root CID: {root_cid}")
```

### CAR to Parquet Conversion

```python
from ipfs_datasets_py.car_conversion import car_to_parquet

# Convert CAR to Parquet
parquet_path = car_to_parquet(
    car_path="input/dataset.car",
    parquet_path="output/dataset.parquet"
)

print(f"Conversion complete. Parquet file: {parquet_path}")
```

## Vector Search

IPFS Datasets Python provides powerful vector search capabilities with IPFS integration.

### Creating a Vector Index

```python
import numpy as np
from typing import List
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Create sample vectors for demonstration
vectors: List[np.ndarray] = [np.random.rand(768) for _ in range(100)]
metadata = [{"id": i, "source": "example", "title": f"Item {i}"} for i in range(100)]

# Create vector index
index = IPFSKnnIndex(dimension=768, metric="cosine")
vector_ids = index.add_vectors(vectors, metadata=metadata)
print(f"Added {len(vector_ids)} vectors to index")
```

### Searching for Similar Vectors

```python
# Create a query vector
query_vector = np.random.rand(768)

# Search for similar vectors
results = index.search(query_vector, top_k=5)
for i, result in enumerate(results):
    print(f"Result {i+1}: ID={result.id}, Score={result.score:.4f}, Title={result.metadata['title']}")
```

### Saving and Loading Vector Index

```python
# Save index to file
index.save("vector_index.pkl")

# Save index to IPFS
cid = index.export_to_ipfs()
print(f"Index saved to IPFS with CID: {cid}")

# Load index from file
loaded_index = IPFSKnnIndex.load("vector_index.pkl")

# Load index from IPFS
loaded_index = IPFSKnnIndex.from_ipfs(cid)
```

## PDF Processing and LLM Optimization

IPFS Datasets Python provides comprehensive PDF processing capabilities designed for optimal LLM consumption and GraphRAG integration.

### Basic PDF Processing

```python
from ipfs_datasets_py.pdf_processing import PDFGraphRAGIntegrator

# Initialize PDF processor
pdf_integrator = PDFGraphRAGIntegrator()

# Process a PDF with the complete pipeline:
# PDF Input → Decomposition → IPLD Structuring → OCR Processing → 
# LLM Optimization → Entity Extraction → Vector Embedding → 
# IPLD GraphRAG Integration → Cross-Document Analysis → Query Interface
result = pdf_integrator.ingest_pdf_into_graphrag(
    pdf_path="research_paper.pdf",
    metadata={
        "title": "AI Research Paper",
        "author": "Dr. Smith",
        "domain": "artificial_intelligence"
    }
)

print(f"Document ID: {result['document_id']}")
print(f"Entities added: {result['entities_added']}")
print(f"Relationships added: {result['relationships_added']}")
print(f"IPLD CID: {result['ipld_cid']}")
```

### LLM-Optimized Content Processing

```python
from ipfs_datasets_py.pdf_processing import LLMOptimizedProcessor

# Initialize processor for specific LLM
processor = LLMOptimizedProcessor()

# Optimize content for target LLM
optimized_content = processor.optimize_for_target_llm(
    pdf_path="document.pdf",
    target_llm="gpt-4"  # Supports: gpt-4, claude-3, gemini-pro, llama-2
)

# Access optimized chunks
for chunk in optimized_content['chunks']:
    print(f"Chunk: {chunk['text'][:100]}...")
    print(f"Entities: {chunk['entities']}")
    print(f"Context: {chunk['context']}")
```

### Multi-Engine OCR Processing

```python
from ipfs_datasets_py.pdf_processing import MultiEngineOCR

# Initialize OCR with intelligent fallback
ocr = MultiEngineOCR()

# Extract text with quality-first strategy
result = ocr.extract_with_ocr(
    image_data=image_bytes,
    strategy='quality_first'  # Uses Surya → PaddleOCR → Tesseract → EasyOCR
)

print(f"Extracted text: {result['text']}")
print(f"Confidence: {result['confidence']:.2f}")
print(f"Engine used: {result['engine']}")
```

### Querying PDF Corpus

```python
from ipfs_datasets_py.pdf_processing import PDFGraphRAGQueryEngine

# Initialize query engine
query_engine = PDFGraphRAGQueryEngine(pdf_integrator)

# Query across PDF documents with cross-document reasoning
results = query_engine.query_pdf_corpus(
    query="What are the security benefits of content addressing in IPFS?",
    query_type="cross_document",
    max_documents=10
)

print(f"Answer: {results['answer']}")
print(f"Confidence: {results['confidence']:.2f}")
print(f"Source documents: {[doc['title'] for doc in results['source_documents']]}")

# View cross-document relationships
for connection in results.get('entity_connections', []):
    print(f"Connection: {connection['entity']} → {connection['relation']}")
```

## Knowledge Graph Extraction

Extract knowledge graphs from text data for enhanced retrieval.

### Extracting a Knowledge Graph

```python
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor

# Initialize extractor
extractor = KnowledgeGraphExtractor()

# Extract knowledge graph from text
text = """
IPFS is a peer-to-peer hypermedia protocol designed to make the web faster, safer, and more open.
It was created by Juan Benet and is now maintained by Protocol Labs.
IPFS uses content-addressing to uniquely identify each file.
"""

entities, relationships = extractor.extract_graph(text)

# Display results
print(f"Extracted {len(entities)} entities and {len(relationships)} relationships")

for entity in entities[:5]:
    print(f"Entity: {entity.name} ({entity.type})")

for rel in relationships[:5]:
    print(f"Relationship: {rel.source} --[{rel.type}]--> {rel.target}")
```

### Storing Knowledge Graph in IPLD

```python
# Store graph on IPFS
graph_cid = extractor.store_on_ipfs(entities, relationships)
print(f"Knowledge graph stored on IPFS with CID: {graph_cid}")
```

## GraphRAG Integration

Combine vector search with knowledge graph traversal for enhanced retrieval.

### Setting Up GraphRAG

```python
from ipfs_datasets_py.llm.llm_graphrag import GraphRAGQueryEngine
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor

# Initialize components
vector_store = IPFSKnnIndex(dimension=768, metric="cosine")
knowledge_graph = KnowledgeGraphExtractor().extract_graph(large_text)

# Initialize GraphRAG query engine
query_engine = GraphRAGQueryEngine(
    vector_stores={"default": vector_store},
    graph_store=knowledge_graph
)
```

### Querying with GraphRAG

```python
# Perform a query
results = query_engine.query(
    query_text="How does IPFS handle content addressing?",
    top_k=5,
    max_graph_hops=2
)

# Display results
for i, result in enumerate(results):
    print(f"Result {i+1}: {result.text[:100]}...")
    print(f"  Source: {result.source}")
    print(f"  Relevance: {result.relevance:.2f}")
    print(f"  Supporting Entities: {[e.name for e in result.entities]}")
```

## Web Archive Integration

Work with web archives using IPFS for storage.

### Archiving a Website

```python
from ipfs_datasets_py.web_archive_utils import archive_website

# Archive a website
warc_file = archive_website("https://example.com/", output_dir="archives")
print(f"Website archived to: {warc_file}")
```

### Indexing a WARC File

```python
from ipfs_datasets_py.web_archive_utils import index_warc

# Index WARC file to IPFS
cdxj_path = index_warc(warc_file, output_path="indexes/example.cdxj")
print(f"WARC indexed to: {cdxj_path}")
```

### Extracting Data from Web Archives

```python
from ipfs_datasets_py.web_archive_utils import extract_dataset_from_cdxj

# Extract dataset from CDXJ index
dataset = extract_dataset_from_cdxj(cdxj_path)
print(f"Extracted dataset with {len(dataset)} entries")
```

## Next Steps

Now that you're familiar with the basics of IPFS Datasets Python, here are some next steps:

1. Explore the [API Reference](api_reference.md) for detailed documentation of all modules
2. Try the [Advanced Tutorials](tutorials/index.md) for in-depth examples
3. Learn about [Security and Governance](security_governance.md) features
4. Check out [Performance Optimization](performance_optimization.md) for large datasets
5. Explore [Distributed Features](distributed_features.md) for multi-node scenarios

For more information and support:

- GitHub Repository: [https://github.com/your-organization/ipfs_datasets_py](https://github.com/your-organization/ipfs_datasets_py)
- Documentation: [https://ipfs-datasets-py.readthedocs.io/](https://ipfs-datasets-py.readthedocs.io/)
- Issue Tracker: [https://github.com/your-organization/ipfs_datasets_py/issues](https://github.com/your-organization/ipfs_datasets_py/issues)
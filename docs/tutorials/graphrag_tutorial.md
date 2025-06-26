# GraphRAG Tutorial: Building Knowledge-Enhanced Retrieval Systems

This tutorial walks through building a Graph-enhanced Retrieval Augmented Generation (GraphRAG) system using IPFS Datasets Python. GraphRAG combines vector similarity search with knowledge graph traversal for more comprehensive and accurate retrieval.

## Table of Contents

1. [Introduction to GraphRAG](#introduction-to-graphrag)
2. [Prerequisites](#prerequisites)
3. [Setup](#setup)
4. [Processing Documents](#processing-documents)
5. [Building the Vector Index](#building-the-vector-index)
6. [Extracting the Knowledge Graph](#extracting-the-knowledge-graph)
7. [Creating the GraphRAG Engine](#creating-the-graphrag-engine)
8. [Querying with GraphRAG](#querying-with-graphrag)
9. [Advanced GraphRAG Techniques](#advanced-graphrag-techniques)
10. [Exporting and Sharing](#exporting-and-sharing)
11. [Complete Example](#complete-example)

## Introduction to GraphRAG

GraphRAG enhances traditional RAG systems by incorporating the structural information in knowledge graphs alongside vector embeddings. This combination allows for more nuanced retrieval that can follow explicit relationships between concepts, not just semantic similarity.

Key benefits include:
- More precise retrieval through relationship awareness
- Better handling of complex, multi-hop questions
- Improved explainability through explicit relationship paths
- Enhanced context gathering by traversing connected information

## Prerequisites

Before starting, ensure you have:

- IPFS Datasets Python installed with GraphRAG dependencies:
  ```bash
  pip install ipfs-datasets-py[graphrag]
  ```
- Sample documents for processing (this tutorial uses research papers on AI)
- Basic understanding of embeddings and knowledge graphs

## Setup

First, let's import the necessary modules and initialize our environment:

```python
import os
import numpy as np
from typing import List, Dict, Any
from pathlib import Path

from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.llm_graphrag import GraphRAGQueryEngine
from ipfs_datasets_py import ipfs_datasets

# Set up working directory
os.makedirs("graphrag_demo", exist_ok=True)
os.chdir("graphrag_demo")

# Load embedding model
embedding_model = ipfs_datasets.load_embedding_model("sentence-transformers/all-MiniLM-L6-v2")
```

## Processing Documents

Let's process a collection of documents to demonstrate the GraphRAG workflow:

```python
def load_documents(directory: str) -> List[Dict[str, Any]]:
    """Load documents from a directory."""
    documents = []
    for file_path in Path(directory).glob("*.txt"):
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
            doc = {
                "id": file_path.stem,
                "title": file_path.stem.replace("_", " ").title(),
                "text": text,
                "path": str(file_path)
            }
            documents.append(doc)
    return documents

# Load sample documents
documents = load_documents("../sample_docs")
print(f"Loaded {len(documents)} documents")

# Chunk documents for processing
def chunk_document(doc, chunk_size=512, overlap=50):
    """Split document into overlapping chunks."""
    text = doc["text"]
    chunks = []
    
    for i in range(0, len(text), chunk_size - overlap):
        chunk_text = text[i:i + chunk_size]
        if len(chunk_text) < 100:  # Skip very small chunks
            continue
            
        chunks.append({
            "doc_id": doc["id"],
            "title": doc["title"],
            "text": chunk_text,
            "chunk_index": len(chunks),
            "start_char": i,
            "end_char": i + len(chunk_text)
        })
    
    return chunks

# Process all documents into chunks
all_chunks = []
for doc in documents:
    chunks = chunk_document(doc)
    all_chunks.extend(chunks)
    print(f"Document '{doc['title']}' → {len(chunks)} chunks")

print(f"Created {len(all_chunks)} total chunks")
```

## Processing PDF Documents for GraphRAG

For PDF documents, IPFS Datasets Python provides specialized processing that optimizes content for both LLM consumption and GraphRAG integration:

```python
from ipfs_datasets_py.pdf_processing import PDFGraphRAGIntegrator

# Initialize PDF GraphRAG integrator
pdf_integrator = PDFGraphRAGIntegrator()

# Process PDFs with complete pipeline
pdf_files = ["research_paper1.pdf", "research_paper2.pdf", "technical_spec.pdf"]
processed_pdfs = []

for pdf_path in pdf_files:
    print(f"Processing PDF: {pdf_path}")
    
    # Complete PDF processing pipeline:
    # PDF Input → Decomposition → IPLD Structuring → OCR Processing → 
    # LLM Optimization → Entity Extraction → Vector Embedding → 
    # IPLD GraphRAG Integration → Cross-Document Analysis → Query Interface
    result = pdf_integrator.ingest_pdf_into_graphrag(
        pdf_path=pdf_path,
        metadata={
            "source": pdf_path,
            "document_type": "research_paper",
            "processing_date": "2025-06-26"
        }
    )
    
    processed_pdfs.append(result)
    print(f"✓ Processed {pdf_path}: {result['entities_added']} entities, {result['relationships_added']} relationships")

# The PDF processing automatically:
# 1. Extracts text using multi-engine OCR (Surya, Tesseract, EasyOCR fallback)
# 2. Creates LLM-optimized chunks with proper context windows
# 3. Extracts entities and relationships
# 4. Generates embeddings for multimodal content
# 5. Integrates with IPLD GraphRAG system
# 6. Enables cross-document relationship discovery

print(f"Successfully processed {len(processed_pdfs)} PDF documents")
```

### PDF-Specific Benefits

PDF processing provides several advantages for GraphRAG:

1. **Multimodal Content**: Processes text, images, and tables together
2. **Document Structure**: Preserves hierarchical relationships (sections, subsections)
3. **Cross-References**: Maintains citation and reference relationships
4. **Quality Optimization**: Multiple OCR engines ensure high text quality
5. **LLM-Ready**: Content optimized for different LLM architectures
6. **IPLD Integration**: Native content-addressed storage

## Building the Vector Index

Now, let's create embeddings for our document chunks and build a vector index:

```python
# Generate embeddings for all chunks
def generate_embeddings(chunks, model):
    """Generate embeddings for text chunks."""
    texts = [chunk["text"] for chunk in chunks]
    embeddings = model.encode(texts)
    return embeddings

# Create embeddings
print("Generating embeddings...")
chunk_embeddings = generate_embeddings(all_chunks, embedding_model)

# Create metadata for each chunk
chunk_metadata = []
for i, chunk in enumerate(all_chunks):
    metadata = {
        "doc_id": chunk["doc_id"],
        "title": chunk["title"],
        "chunk_index": chunk["chunk_index"],
        "text": chunk["text"][:200] + "...",  # First 200 chars for preview
        "start_char": chunk["start_char"],
        "end_char": chunk["end_char"]
    }
    chunk_metadata.append(metadata)

# Create and populate vector index
vector_index = IPFSKnnIndex(dimension=embedding_model.get_dimension(), metric="cosine")
vector_ids = vector_index.add_vectors(chunk_embeddings, metadata=chunk_metadata)

print(f"Added {len(vector_ids)} vectors to index")

# Save the index for later use
vector_index.save("ai_papers_index.pkl")
```

## Extracting the Knowledge Graph

Next, let's extract a knowledge graph from our documents:

```python
# Initialize the knowledge graph extractor
extractor = KnowledgeGraphExtractor()

# Extract entities and relationships from each document
all_entities = []
all_relationships = []

for doc in documents:
    print(f"Extracting knowledge graph from '{doc['title']}'...")
    entities, relationships = extractor.extract_graph(doc["text"], document_id=doc["id"])
    
    print(f"  Found {len(entities)} entities and {len(relationships)} relationships")
    all_entities.extend(entities)
    all_relationships.extend(relationships)

print(f"Total: {len(all_entities)} entities and {len(all_relationships)} relationships")

# Deduplicate entities by name
unique_entities = {}
for entity in all_entities:
    if entity.name not in unique_entities:
        unique_entities[entity.name] = entity
    else:
        # Merge mentions
        unique_entities[entity.name].mentions.extend(entity.mentions)

all_entities = list(unique_entities.values())
print(f"After deduplication: {len(all_entities)} unique entities")

# Store the knowledge graph
knowledge_graph_cid = extractor.store_on_ipfs(all_entities, all_relationships)
print(f"Knowledge graph stored with CID: {knowledge_graph_cid}")

# Save locally as well for convenience
extractor.save_graph_locally(all_entities, all_relationships, "ai_papers_graph.json")
```

## Creating the GraphRAG Engine

Now, let's combine our vector index and knowledge graph into a GraphRAG engine:

```python
# Initialize the GraphRAG query engine
query_engine = GraphRAGQueryEngine(
    vector_stores={"default": vector_index},
    graph_store={"entities": all_entities, "relationships": all_relationships},
    model_weights={"default": 1.0}
)

print("GraphRAG engine initialized and ready for queries")
```

## Querying with GraphRAG

Let's perform some queries using our GraphRAG system:

```python
def run_query(query_text, top_k=5, max_graph_hops=2):
    """Run a query through the GraphRAG engine and display results."""
    print(f"\nQUERY: {query_text}")
    print("-" * 80)
    
    results = query_engine.query(
        query_text=query_text,
        top_k=top_k,
        max_graph_hops=max_graph_hops
    )
    
    print(f"Found {len(results)} results\n")
    
    for i, result in enumerate(results):
        print(f"Result {i+1} (Score: {result['score']:.4f}):")
        print(f"  Document: {result['metadata']['title']}")
        print(f"  Text: {result['text'][:150]}...")
        
        if 'evidence_path' in result:
            print(f"  Evidence Path: {' -> '.join([e['name'] for e in result['evidence_path']])}")
        
        print()

# Run some example queries
run_query("What are transformer models used for in natural language processing?")
run_query("How does reinforcement learning relate to neural networks?", max_graph_hops=3)
run_query("Explain the relationship between deep learning and computer vision")
```

## Advanced GraphRAG Techniques

Let's explore some advanced techniques for improving GraphRAG performance:

```python
# 1. Hybrid retrieval with weighted combination
def hybrid_query(query_text, vector_weight=0.7, graph_weight=0.3, top_k=5):
    """Perform hybrid retrieval with custom weights."""
    # Get query embedding
    query_embedding = embedding_model.encode(query_text)
    
    # Perform vector search
    vector_results = vector_index.search(query_embedding, top_k=top_k*2)
    
    # Get mentioned entities in query
    query_entities = extractor.extract_entities_from_text(query_text)
    
    # Perform graph search
    graph_results = []
    if query_entities:
        # Find corresponding entities in our knowledge graph
        seed_entities = []
        for query_entity in query_entities:
            for entity in all_entities:
                if entity.name.lower() == query_entity.lower():
                    seed_entities.append(entity)
                    break
        
        # Traverse graph from seed entities
        if seed_entities:
            graph_results = query_engine.graph_search(seed_entities, max_hops=2)
    
    # Combine results with weights
    combined_results = query_engine.combine_results(
        vector_results, 
        graph_results,
        weights={"vector": vector_weight, "graph": graph_weight}
    )
    
    return combined_results[:top_k]

# 2. Query expansion using the knowledge graph
def expanded_query(query_text, top_k=5):
    """Expand query using related terms from knowledge graph."""
    # Get entities in query
    query_entities = extractor.extract_entities_from_text(query_text)
    
    # Find related terms to expand query
    expanded_terms = set()
    for query_entity in query_entities:
        for entity in all_entities:
            if entity.name.lower() == query_entity.lower():
                # Find directly related entities
                for rel in all_relationships:
                    if rel.source == entity.id:
                        for target_entity in all_entities:
                            if target_entity.id == rel.target:
                                expanded_terms.add(target_entity.name)
                    elif rel.target == entity.id:
                        for source_entity in all_entities:
                            if source_entity.id == rel.source:
                                expanded_terms.add(source_entity.name)
    
    # Combine original query with expansion terms
    expanded_query_text = query_text
    if expanded_terms:
        expanded_query_text += " " + " ".join(expanded_terms)
        print(f"Expanded query: {expanded_query_text}")
    
    # Run the expanded query
    query_embedding = embedding_model.encode(expanded_query_text)
    results = vector_index.search(query_embedding, top_k=top_k)
    
    return results

# 3. IPLD-specific optimizations for content-addressed data
def ipld_optimized_query(query_text, top_k=5, max_hops=2):
    """Execute a query with IPLD-specific optimizations for content-addressed data."""
    from ipfs_datasets_py.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer, QueryRewriter
    
    # Create specialized components for optimizing IPLD queries
    query_rewriter = QueryRewriter()
    optimizer = UnifiedGraphRAGQueryOptimizer(
        rewriter=query_rewriter,
        graph_info={"graph_type": "ipld"}
    )
    
    # Get query embedding
    query_embedding = embedding_model.encode(query_text)
    
    # Prepare query with IPLD signals
    query = {
        "query_vector": query_embedding,
        "max_vector_results": top_k,
        "max_traversal_depth": max_hops,
        "graph_type": "ipld",
        "query_text": query_text
    }
    
    # Get optimized query plan
    plan = optimizer.optimize_query(query)
    
    # Extract traversal parameters with IPLD-specific optimizations
    traversal_params = plan["query"].get("traversal", {})
    print(f"Using DAG traversal strategy: {traversal_params.get('strategy') == 'dag_traversal'}")
    print(f"Using CID path optimization: {traversal_params.get('use_cid_path_optimization', False)}")
    print(f"Using batch loading: {traversal_params.get('batch_loading', False)}")
    
    # Execute optimized query
    results = query_engine.query(
        query_text=query_text,
        query_vector=query_embedding,
        top_k=top_k,
        max_graph_hops=max_hops,
        traversal_options=traversal_params
    )
    
    return results

# Try these advanced queries
print("\n=== HYBRID RETRIEVAL ===")
hybrid_results = hybrid_query("How is reinforcement learning used in robotics?")
for i, result in enumerate(hybrid_results):
    print(f"Result {i+1} (Score: {result['score']:.4f}): {result['metadata']['title']}")

print("\n=== QUERY EXPANSION ===")
expanded_results = expanded_query("What is attention mechanism?")
for i, result in enumerate(expanded_results):
    print(f"Result {i+1} (Score: {result.score:.4f}): {result.metadata['title']}")

print("\n=== IPLD OPTIMIZED QUERY ===")
ipld_results = ipld_optimized_query("How does content addressing relate to CIDs?")
for i, result in enumerate(ipld_results):
    print(f"Result {i+1} (Score: {result['score']:.4f}): {result['metadata']['title']}")
    if 'evidence_path' in result:
        print(f"  Evidence Path: {' -> '.join([e.get('name', 'Unknown') for e in result['evidence_path']])}")
```

## Exporting and Sharing

Let's export our GraphRAG system to CAR files for sharing and archiving:

```python
# Export vector index to CAR
index_cid = vector_index.export_to_car("ai_papers_index.car")
print(f"Vector index exported to CAR with root CID: {index_cid}")

# Export knowledge graph to CAR (already done above)
print(f"Knowledge graph exported to CAR with root CID: {knowledge_graph_cid}")

# Create a manifest linking everything together
import json
import datetime

manifest = {
    "name": "AI Research Papers GraphRAG System",
    "description": "GraphRAG system built from AI research papers",
    "created_at": datetime.datetime.now().isoformat(),
    "components": {
        "vector_index": {
            "cid": index_cid,
            "dimension": embedding_model.get_dimension(),
            "metric": "cosine",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "item_count": len(vector_ids)
        },
        "knowledge_graph": {
            "cid": knowledge_graph_cid,
            "entity_count": len(all_entities),
            "relationship_count": len(all_relationships)
        }
    },
    "documents": [doc["title"] for doc in documents]
}

# Save manifest locally
with open("graphrag_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

print("Created GraphRAG manifest: graphrag_manifest.json")
```

## Complete Example

Here's a complete script that ties all the components together:

```python
import os
import numpy as np
import json
import datetime
from pathlib import Path
from typing import List, Dict, Any

from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.llm_graphrag import GraphRAGQueryEngine
from ipfs_datasets_py import ipfs_datasets

# Setup
os.makedirs("graphrag_demo", exist_ok=True)
os.chdir("graphrag_demo")
embedding_model = ipfs_datasets.load_embedding_model("sentence-transformers/all-MiniLM-L6-v2")

# Load documents
def load_documents(directory: str) -> List[Dict[str, Any]]:
    documents = []
    for file_path in Path(directory).glob("*.txt"):
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
            doc = {
                "id": file_path.stem,
                "title": file_path.stem.replace("_", " ").title(),
                "text": text,
                "path": str(file_path)
            }
            documents.append(doc)
    return documents

documents = load_documents("../sample_docs")
print(f"Loaded {len(documents)} documents")

# Chunk documents
def chunk_document(doc, chunk_size=512, overlap=50):
    text = doc["text"]
    chunks = []
    
    for i in range(0, len(text), chunk_size - overlap):
        chunk_text = text[i:i + chunk_size]
        if len(chunk_text) < 100:  # Skip very small chunks
            continue
            
        chunks.append({
            "doc_id": doc["id"],
            "title": doc["title"],
            "text": chunk_text,
            "chunk_index": len(chunks),
            "start_char": i,
            "end_char": i + len(chunk_text)
        })
    
    return chunks

all_chunks = []
for doc in documents:
    chunks = chunk_document(doc)
    all_chunks.extend(chunks)
    print(f"Document '{doc['title']}' → {len(chunks)} chunks")

print(f"Created {len(all_chunks)} total chunks")

# Generate embeddings
def generate_embeddings(chunks, model):
    texts = [chunk["text"] for chunk in chunks]
    embeddings = model.encode(texts)
    return embeddings

print("Generating embeddings...")
chunk_embeddings = generate_embeddings(all_chunks, embedding_model)

# Create vector index
chunk_metadata = []
for i, chunk in enumerate(all_chunks):
    metadata = {
        "doc_id": chunk["doc_id"],
        "title": chunk["title"],
        "chunk_index": chunk["chunk_index"],
        "text": chunk["text"][:200] + "...",
        "start_char": chunk["start_char"],
        "end_char": chunk["end_char"]
    }
    chunk_metadata.append(metadata)

vector_index = IPFSKnnIndex(dimension=embedding_model.get_dimension(), metric="cosine")
vector_ids = vector_index.add_vectors(chunk_embeddings, metadata=chunk_metadata)
print(f"Added {len(vector_ids)} vectors to index")
vector_index.save("ai_papers_index.pkl")

# Extract knowledge graph
extractor = KnowledgeGraphExtractor()
all_entities = []
all_relationships = []

for doc in documents:
    print(f"Extracting knowledge graph from '{doc['title']}'...")
    entities, relationships = extractor.extract_graph(doc["text"], document_id=doc["id"])
    
    print(f"  Found {len(entities)} entities and {len(relationships)} relationships")
    all_entities.extend(entities)
    all_relationships.extend(relationships)

print(f"Total: {len(all_entities)} entities and {len(all_relationships)} relationships")

# Deduplicate entities
unique_entities = {}
for entity in all_entities:
    if entity.name not in unique_entities:
        unique_entities[entity.name] = entity
    else:
        unique_entities[entity.name].mentions.extend(entity.mentions)

all_entities = list(unique_entities.values())
print(f"After deduplication: {len(all_entities)} unique entities")

# Store knowledge graph
knowledge_graph_cid = extractor.store_on_ipfs(all_entities, all_relationships)
print(f"Knowledge graph stored with CID: {knowledge_graph_cid}")
extractor.save_graph_locally(all_entities, all_relationships, "ai_papers_graph.json")

# Create GraphRAG engine
query_engine = GraphRAGQueryEngine(
    vector_stores={"default": vector_index},
    graph_store={"entities": all_entities, "relationships": all_relationships},
    model_weights={"default": 1.0}
)

# Run queries
def run_query(query_text, top_k=5, max_graph_hops=2):
    print(f"\nQUERY: {query_text}")
    print("-" * 80)
    
    results = query_engine.query(
        query_text=query_text,
        top_k=top_k,
        max_graph_hops=max_graph_hops
    )
    
    print(f"Found {len(results)} results\n")
    
    for i, result in enumerate(results):
        print(f"Result {i+1} (Score: {result['score']:.4f}):")
        print(f"  Document: {result['metadata']['title']}")
        print(f"  Text: {result['text'][:150]}...")
        
        if 'evidence_path' in result:
            print(f"  Evidence Path: {' -> '.join([e['name'] for e in result['evidence_path']])}")
        
        print()

# Example queries
run_query("What are transformer models used for in natural language processing?")
run_query("How does reinforcement learning relate to neural networks?", max_graph_hops=3)
run_query("Explain the relationship between deep learning and computer vision")

# Export for sharing
index_cid = vector_index.export_to_car("ai_papers_index.car")
print(f"Vector index exported to CAR with root CID: {index_cid}")

manifest = {
    "name": "AI Research Papers GraphRAG System",
    "description": "GraphRAG system built from AI research papers",
    "created_at": datetime.datetime.now().isoformat(),
    "components": {
        "vector_index": {
            "cid": index_cid,
            "dimension": embedding_model.get_dimension(),
            "metric": "cosine",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
            "item_count": len(vector_ids)
        },
        "knowledge_graph": {
            "cid": knowledge_graph_cid,
            "entity_count": len(all_entities),
            "relationship_count": len(all_relationships)
        }
    },
    "documents": [doc["title"] for doc in documents]
}

with open("graphrag_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

print("Created GraphRAG manifest: graphrag_manifest.json")
print("\nGraphRAG tutorial completed successfully!")
```

This tutorial demonstrated how to build a complete GraphRAG system with IPFS Datasets Python, from document processing to knowledge graph extraction, vector indexing, and hybrid querying. The system can be exported to CAR files for sharing and deployed on any system with IPFS Datasets Python installed.
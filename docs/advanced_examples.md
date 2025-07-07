# Advanced Examples

This document provides advanced examples and usage patterns for IPFS Datasets Python, including the newly integrated IPFS embeddings functionality. These examples demonstrate how to combine multiple features to solve complex data processing, storage, and retrieval challenges.

## 🚀 New Integration Features

The integration with ipfs_embeddings_py brings powerful new capabilities:
- **Advanced Vector Embeddings**: Text, document, and multimodal embeddings
- **Semantic Search**: Similarity search across large document collections  
- **Vector Stores**: Qdrant, Elasticsearch, and FAISS integration
- **MCP Tools**: 100+ tools for AI model integration
- **FastAPI Service**: REST API for all functionality
- **Quality Assessment**: Embedding validation and metrics

## Table of Contents

1. [Complete Data Processing Pipeline](#complete-data-processing-pipeline)
2. [Advanced PDF Processing and GraphRAG Integration](#advanced-pdf-processing-and-graphrag-integration)
3. [Building a Knowledge Dataset from Web Archives](#building-a-knowledge-dataset-from-web-archives)
4. [GraphRAG with Multi-Model Embeddings](#graphrag-with-multi-model-embeddings)
5. [Distributed Vector Search with Sharding](#distributed-vector-search-with-sharding)
6. [Cross-Document Reasoning with LLM Integration](#cross-document-reasoning-with-llm-integration)
7. [DuckDB, Arrow, and IPLD Integration](#duckdb-arrow-and-ipld-integration)
8. [Resilient Distributed Operations](#resilient-distributed-operations)
9. [Comprehensive Audit and Provenance Tracking](#comprehensive-audit-and-provenance-tracking)


## Complete Data Processing Pipeline

This example demonstrates a complete data processing pipeline that loads data from multiple sources, processes it, and stores it in various formats.

```python
from ipfs_datasets_py.data_integration import UnifiedDataLayer
from ipfs_datasets_py.duckdb_connector import DuckDBConnector
import pandas as pd

# Initialize components
data_layer = UnifiedDataLayer()
duckdb = DuckDBConnector("analytics.duckdb")

# 1. Load dataset from Huggingface
print("Loading dataset from Huggingface...")
dataset = data_layer.load_hf_dataset("wikipedia", "20220301.en", split="train")

# 2. Process using DuckDB for analytics
print("Processing with DuckDB...")
# First convert to Arrow
arrow_table = data_layer.hf_dataset_to_arrow(dataset)

# Create DuckDB table from Arrow
duckdb.create_table_from_arrow("wikipedia_raw", arrow_table)

# Run analytics query
processed_data = duckdb.query_to_arrow("""
    SELECT 
        id,
        title,
        url,
        text,
        LENGTH(text) as text_length,
        REGEXP_COUNT(LOWER(text), 'python') as python_mentions
    FROM wikipedia_raw
    WHERE text_length > 1000
    AND python_mentions > 0
    ORDER BY python_mentions DESC
    LIMIT 10000
""")

# 3. Export in multiple formats
print("Exporting data...")
# Export to Parquet
data_layer.arrow_to_parquet(processed_data, "wikipedia_python.parquet")

# Export to CAR file with content-addressing
data_layer.arrow_to_car(processed_data, "wikipedia_python.car", hash_columns=["id"])

# Export back to Huggingface Dataset
hf_processed = data_layer.arrow_to_hf_dataset(processed_data)
hf_processed.push_to_hub("myusername/wikipedia-python-articles")

print("Data processing and export complete!")
print(f"Processed {len(processed_data)} records")
print(f"Outputs: wikipedia_python.parquet, wikipedia_python.car, and dataset on HF Hub")
```

## Advanced PDF Processing and GraphRAG Integration

This example demonstrates comprehensive PDF processing that integrates the complete pipeline for optimal LLM consumption and GraphRAG integration.

```python
from ipfs_datasets_py.pdf_processing import (
    PDFGraphRAGIntegrator, 
    LLMOptimizedProcessor, 
    MultiEngineOCR,
    PDFGraphRAGQueryEngine,
    PDFBatchProcessor
)
from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.monitoring import MonitoringSystem
import asyncio
from pathlib import Path

# Initialize monitoring for comprehensive processing
monitoring = MonitoringSystem(
    metrics_path="pdf_processing_metrics",
    enable_prometheus=True,
    enable_alerts=True
)

# 1. Initialize PDF processing components
pdf_integrator = PDFGraphRAGIntegrator()
llm_processor = LLMOptimizedProcessor()
batch_processor = PDFBatchProcessor(
    batch_size=5,
    parallel_workers=4,
    enable_caching=True
)

# 2. Process a collection of research papers
pdf_directory = Path("research_papers/")
pdf_files = list(pdf_directory.glob("*.pdf"))

print(f"Processing {len(pdf_files)} PDF documents...")

# Batch process PDFs with complete pipeline
with monitoring.track_operation("pdf_batch_processing"):
    results = batch_processor.process_pdf_batch(
        pdf_paths=[str(f) for f in pdf_files],
        target_llm="gpt-4",  # Optimize for GPT-4
        enable_cross_document_analysis=True
    )

# 3. Advanced multi-engine OCR demonstration
print("\nDemonstrating multi-engine OCR...")
ocr = MultiEngineOCR()

# Configure OCR engines with different strategies
ocr_strategies = ['quality_first', 'speed_first', 'accuracy_first']
for strategy in ocr_strategies:
    with open("sample_scanned_page.png", "rb") as f:
        image_data = f.read()
    
    result = ocr.extract_with_fallback(image_data, strategy=strategy)
    print(f"Strategy '{strategy}': {result['confidence']:.2f} confidence, "
          f"engine: {result['engine']}")

# 4. LLM-specific optimization for different architectures
llm_targets = ['gpt-4', 'claude-3', 'gemini-pro', 'llama-2']
optimized_contents = {}

for target_llm in llm_targets:
    print(f"\nOptimizing content for {target_llm}...")
    
    optimized_content = llm_processor.optimize_for_target_llm(
        pdf_path=str(pdf_files[0]),  # Use first PDF as example
        target_llm=target_llm
    )
    
    optimized_contents[target_llm] = optimized_content
    
    # Print optimization statistics
    chunks = optimized_content['chunks']
    avg_chunk_size = sum(len(chunk['text']) for chunk in chunks) / len(chunks)
    print(f"  - {len(chunks)} chunks created")
    print(f"  - Average chunk size: {avg_chunk_size:.0f} characters")
    print(f"  - Total entities extracted: {sum(len(chunk.get('entities', [])) for chunk in chunks)}")

# 5. Advanced querying with cross-document reasoning
query_engine = PDFGraphRAGQueryEngine(pdf_integrator)

# Complex queries that benefit from GraphRAG
complex_queries = [
    "What are the common methodologies used across these research papers for evaluating AI safety?",
    "How do the findings in paper A relate to the conclusions in paper B regarding model interpretability?",
    "What trends can be identified in the evolution of transformer architectures across these documents?",
    "Which papers discuss similar ethical considerations, and what are their different perspectives?"
]

print("\nExecuting complex cross-document queries...")
query_results = {}

for query in complex_queries:
    print(f"\nQuery: {query[:80]}...")
    
    results = query_engine.query_pdf_corpus(
        query=query,
        query_type="cross_document",
        max_documents=len(pdf_files),
        include_reasoning_trace=True
    )
    
    query_results[query] = results
    
    print(f"Answer: {results['answer'][:200]}...")
    print(f"Confidence: {results['confidence']:.2f}")
    print(f"Sources: {len(results['source_documents'])} documents")
    
    # Show entity connections
    if 'entity_connections' in results:
        print("Key entity connections:")
        for conn in results['entity_connections'][:3]:
            print(f"  - {conn['entity']} ({conn['type']}): {conn['relation']}")

# 6. Document relationship analysis
print("\nAnalyzing document relationships...")
for result in results:
    doc_analysis = query_engine.analyze_document_relationships(
        result['document_id']
    )
    
    print(f"Document {result['document_id']}:")
    print(f"  - Internal relationships: {doc_analysis['internal_relationships']}")
    print(f"  - External relationships: {doc_analysis['external_relationships']}")
    print(f"  - Cross-document links: {len(doc_analysis['cross_document_links'])}")

# 7. Export processed knowledge graph to IPLD
print("\nExporting knowledge graph to IPLD...")
ipld_storage = IPLDStorage()

export_result = pdf_integrator.export_knowledge_graph_to_ipld(
    include_embeddings=True,
    include_relationships=True,
    include_document_content=True,
    compression_level=6
)

print(f"Knowledge graph exported with root CID: {export_result['root_cid']}")
print(f"Total nodes: {export_result['node_count']}")
print(f"Total relationships: {export_result['relationship_count']}")
print(f"Compressed size: {export_result['compressed_size_mb']:.2f} MB")

# 8. Performance metrics and quality assessment
processing_metrics = monitoring.get_operation_metrics("pdf_batch_processing")
print(f"\nProcessing Performance:")
print(f"  - Total processing time: {processing_metrics['duration']:.2f} seconds")
print(f"  - Average time per document: {processing_metrics['duration']/len(pdf_files):.2f} seconds")
print(f"  - Memory usage peak: {processing_metrics['peak_memory_mb']:.1f} MB")

# Quality assessment
quality_metrics = batch_processor.get_quality_metrics()
print(f"\nQuality Metrics:")
print(f"  - Average OCR confidence: {quality_metrics['avg_ocr_confidence']:.2f}")
print(f"  - Content coherence score: {quality_metrics['avg_coherence_score']:.2f}")
print(f"  - Entity extraction confidence: {quality_metrics['avg_entity_confidence']:.2f}")
print(f"  - Cross-document relationship accuracy: {quality_metrics['relationship_accuracy']:.2f}")

print("\nAdvanced PDF processing complete!")
print(f"Processed {len(pdf_files)} documents with full GraphRAG integration")
```

This example demonstrates:

1. **Complete Pipeline Integration**: PDF Input → Decomposition → IPLD Structuring → OCR Processing → LLM Optimization → Entity Extraction → Vector Embedding → IPLD GraphRAG Integration → Cross-Document Analysis → Query Interface

2. **Multi-Engine OCR**: Intelligent fallback between Surya, Tesseract, EasyOCR, and other engines

3. **LLM-Specific Optimization**: Content optimized for different LLM architectures (GPT-4, Claude-3, Gemini Pro, Llama-2)

4. **Cross-Document Reasoning**: Complex queries that span multiple documents and discover relationships

5. **Performance Monitoring**: Comprehensive metrics collection and quality assessment

6. **IPLD Integration**: Native content-addressed storage with compression and efficient retrieval

## Building a Knowledge Dataset from Web Archives

This example shows how to archive a website, index it to IPFS, extract structured data, and build a knowledge graph from the content.

```python
from ipfs_datasets_py import ipfs_datasets, web_archive_utils
from ipfs_datasets_py.ipld_storage import IPLDStorage
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph
from archivenow import archivenow
import json
import datetime

# Step 1: Archive a website using ArchiveNow
print("Creating web archive...")
warc_file = archivenow.push("https://en.wikipedia.org/wiki/IPFS", "warc", 
                           {"warc": "ipfs_wiki", "agent": "wget"})

# Step 2: Index the WARC file to IPFS using IPWB
print("Indexing to IPFS...")
from ipwb import indexer
cdxj_path = indexer.index_file_at(warc_file, outfile="ipfs_wiki.cdxj")

# Step 3: Extract structured data from the archive
print("Extracting structured data...")
# Create a processing pipeline for the web archive
pipeline = web_archive_utils.WARCProcessingPipeline(
    extraction_steps=[
        web_archive_utils.extractors.HTMLExtractor(),
        web_archive_utils.extractors.TextExtractor(),
        web_archive_utils.extractors.EntityExtractor(),
        web_archive_utils.extractors.LinkExtractor()
    ],
    transformation_steps=[
        web_archive_utils.transformers.HTMLCleaner(),
        web_archive_utils.transformers.TextNormalizer(),
        web_archive_utils.transformers.EntityLinker()
    ],
    output_format="dataset"
)

# Process the archive into a dataset
dataset = pipeline.process(cdxj_path)

# Step 4: Create vector embeddings and store in IPLD
print("Creating embeddings...")
# Initialize IPLD storage
ipld_storage = IPLDStorage()

# Create vector embeddings for the text content
embedding_model = ipfs_datasets.load_embedding_model("sentence-transformers/all-MiniLM-L6-v2")
text_chunks = dataset.get_chunked_texts(chunk_size=512, overlap=50)
embeddings = [embedding_model.encode(chunk) for chunk in text_chunks]

# Create vector index
vector_index = IPFSKnnIndex(dimension=embedding_model.dimension)
vector_ids = vector_index.add_vectors(embeddings, metadata={
    "source": "wikipedia",
    "topic": "ipfs",
    "chunks": text_chunks
})

# Step 5: Build knowledge graph from extracted entities
print("Building knowledge graph...")
kg = IPLDKnowledgeGraph()

# Add entities from the dataset
for entity in dataset.get_entities():
    entity_cid = kg.add_entity({
        "name": entity.name,
        "type": entity.type,
        "mentions": entity.mentions,
        "vector_ids": [vector_ids[i] for i in entity.chunk_indices]
    })

# Add relationships between entities
for relation in dataset.get_relations():
    kg.add_relationship(
        source_cid=relation.source_entity_cid,
        target_cid=relation.target_entity_cid,
        relationship_type=relation.type,
        properties=relation.properties
    )

# Step 6: Export everything to CAR files for distribution
print("Exporting to CAR files...")
# Export vector index to CAR
index_car = vector_index.export_to_car("ipfs_wiki_vectors.car")

# Export knowledge graph to CAR
kg_car = kg.export_to_car("ipfs_wiki_knowledge_graph.car")

# Create a root object linking everything together
dataset_root = {
    "name": "IPFS Wikipedia Dataset",
    "description": "Knowledge dataset created from Wikipedia IPFS article",
    "source_warc": warc_file,
    "cdxj_index": cdxj_path,
    "vector_index_cid": vector_index.root_cid,
    "knowledge_graph_cid": kg.root_cid,
    "created_at": datetime.datetime.now().isoformat()
}

# Store the root object
root_cid = ipld_storage.store(json.dumps(dataset_root).encode())
ipld_storage.export_to_car([root_cid], "ipfs_wiki_dataset_root.car")

print(f"Dataset creation complete. Root CID: {root_cid}")

# Step 7: Query the dataset
print("Performing hybrid vector + graph query...")
query = "How does IPFS handle content addressing?"
query_embedding = embedding_model.encode(query)

# Vector search to find relevant chunks
vector_results = vector_index.search(query_embedding, top_k=5)

# Get entities mentioned in the most relevant chunks
mentioned_entities = kg.get_entities_by_vector_ids(
    [result.id for result in vector_results]
)

# Perform graph traversal to find related concepts
related_concepts = kg.traverse_from_entities(
    mentioned_entities,
    relationship_types=["RELATED_TO", "IS_PART_OF"],
    max_depth=2
)

# Combine results for a comprehensive answer
print("Results:")
for result in vector_results:
    print(f"- {result.metadata['chunks'][result.metadata_index][:100]}...")

print("\nRelated concepts:")
for concept in related_concepts:
    print(f"- {concept.properties['name']} ({concept.properties['type']})")
```

## GraphRAG with Multi-Model Embeddings

This example demonstrates how to set up a GraphRAG system with multiple embedding models for improved retrieval performance.

```python
import torch
from transformers import AutoTokenizer, AutoModel
from ipfs_datasets_py.llm.llm_graphrag import GraphRAGLLMProcessor
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph
from ipfs_datasets_py.ipfs_knn_index import MultiModelSearch
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

# Initialize embedding models
models = {
    "miniLM": {
        "tokenizer": AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2"),
        "model": AutoModel.from_pretrained("sentence-transformers/all-MiniLM-L6-v2"),
        "dimension": 384,
        "weight": 0.3
    },
    "mpnet": {
        "tokenizer": AutoTokenizer.from_pretrained("sentence-transformers/multi-qa-mpnet-base-dot-v1"),
        "model": AutoModel.from_pretrained("sentence-transformers/multi-qa-mpnet-base-dot-v1"),
        "dimension": 768,
        "weight": 0.7
    }
}

# Helper function for embedding generation
def mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0]
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

# Function to generate embeddings with multiple models
def generate_multi_model_embeddings(text):
    embeddings = {}
    for model_name, model_info in models.items():
        tokenizer = model_info["tokenizer"]
        model = model_info["model"]
        
        # Tokenize and get model output
        inputs = tokenizer(text, padding=True, truncation=True, return_tensors="pt")
        with torch.no_grad():
            outputs = model(**inputs)
        
        # Mean pooling
        embedding = mean_pooling(outputs, inputs['attention_mask'])
        embeddings[model_name] = embedding[0].numpy()
    
    return embeddings

# Load knowledge graph
kg = IPLDKnowledgeGraph.from_cid("bafybeihsl7tqdebswdmafvytgkofgxnpq5rwzzqpsbd7gtaiujwsn4qeyy")

# Create multi-model vector search
multi_model_search = MultiModelSearch(
    models={
        "miniLM": {"dimension": 384, "weight": 0.3},
        "mpnet": {"dimension": 768, "weight": 0.7}
    }
)

# Add vectors to search index
# (Assuming vectors were previously generated and stored)
vectors_miniLM = [...]  # List of numpy arrays for miniLM
vectors_mpnet = [...]   # List of numpy arrays for mpnet
metadata = [...]        # List of metadata dictionaries

multi_model_search.add_vectors("miniLM", vectors_miniLM, metadata)
multi_model_search.add_vectors("mpnet", vectors_mpnet, metadata)

# Create GraphRAG processor with multi-model search
processor = GraphRAGLLMProcessor(
    knowledge_graph=kg,
    vector_search=multi_model_search
)

# Create query optimizer
optimizer = UnifiedGraphRAGQueryOptimizer(auto_detect_graph_type=True)

# Process a query
query_text = "How does IPFS implement content addressing?"
query_embeddings = generate_multi_model_embeddings(query_text)

# Optimize query
optimized_plan = optimizer.optimize_query(
    query_text=query_text,
    query_vectors=query_embeddings,
    root_cids=[kg.root_cid],
    content_types=["application/json"]
)

# Execute with optimized plan
results = processor.query(
    query_text=query_text,
    query_embeddings=query_embeddings,
    optimized_plan=optimized_plan
)

# Process results
for i, result in enumerate(results):
    print(f"Result {i+1}: {result.text[:100]}...")
    print(f"  Similarity: {result.similarity:.4f}")
    print(f"  Graph Distance: {result.graph_distance}")
    print(f"  Source: {result.source}")
```

## Distributed Vector Search with Sharding

This example demonstrates how to create a distributed vector search system with sharding across multiple nodes.

```python
from ipfs_datasets_py.federated_search import FederatedSearch, NodeSelector
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex, ShardedVectorIndex
from ipfs_datasets_py.resilient_operations import CircuitBreaker, RetryStrategy
import numpy as np

# Create sharded vector index
sharded_index = ShardedVectorIndex(
    dimension=768,
    metric="cosine",
    num_shards=5,
    shard_strategy="hash",
    redundancy=2  # Each vector is stored on 2 shards for redundancy
)

# Create vector data
vectors = [np.random.rand(768) for _ in range(10000)]
metadata = [{"id": i, "content": f"Document {i}"} for i in range(10000)]

# Add vectors to sharded index
vector_ids = sharded_index.add_vectors(vectors, metadata)

# Set up node configuration
nodes = [
    {"id": "node1", "address": "192.168.1.101", "shards": [0, 1]},
    {"id": "node2", "address": "192.168.1.102", "shards": [1, 2]},
    {"id": "node3", "address": "192.168.1.103", "shards": [2, 3]},
    {"id": "node4", "address": "192.168.1.104", "shards": [3, 4]},
    {"id": "node5", "address": "192.168.1.105", "shards": [0, 4]}
]

# Create node selector
node_selector = NodeSelector(
    nodes=nodes,
    selection_strategy="health_aware",
    redundancy_level=2
)

# Create retry strategy
retry_strategy = RetryStrategy(
    max_retries=3,
    base_delay=0.5,
    max_delay=5.0,
    backoff_factor=2.0
)

# Create circuit breaker
circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=30,
    half_open_requests=2
)

# Create federated search
federated_search = FederatedSearch(
    node_selector=node_selector,
    retry_strategy=retry_strategy,
    circuit_breaker=circuit_breaker,
    timeout_seconds=10
)

# Perform distributed search
query_vector = np.random.rand(768)
results = federated_search.search(
    query_vector=query_vector,
    top_k=10,
    min_similarity=0.7,
    combine_method="score_based"
)

# Process results
print(f"Found {len(results)} results")
for i, result in enumerate(results):
    print(f"Result {i+1}: ID={result.id}, Score={result.score:.4f}")
    print(f"  Content: {result.metadata['content']}")
    print(f"  Source Node: {result.source_node}")
```

## Cross-Document Reasoning with LLM Integration

This example demonstrates cross-document reasoning with the GraphRAG system and LLM integration.

```python
from ipfs_datasets_py.llm.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer
from ipfs_datasets_py.llm_reasoning_tracer import ReasoningTracer
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
import numpy as np

# Load knowledge graph
kg = IPLDKnowledgeGraph.from_cid("bafybeihsl7tqdebswdmafvytgkofgxnpq5rwzzqpsbd7gtaiujwsn4qeyy")

# Load vector index
index = IPFSKnnIndex.load("path/to/index")

# Create reasoning tracer
tracer = ReasoningTracer(
    trace_storage_path="reasoning_traces",
    visualization_enabled=True,
    detailed_tracing=True
)

# Create reasoning enhancer
enhancer = ReasoningEnhancer(
    reasoning_tracer=tracer,
    reasoning_depth="deep",
    explanation_type="detailed"
)

# Create GraphRAG processor
processor = GraphRAGLLMProcessor(
    knowledge_graph=kg,
    vector_index=index,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2",
    reasoning_enhancer=enhancer
)

# Perform cross-document reasoning
result = processor.cross_document_reasoning(
    query="Compare how IPFS and BitTorrent handle content distribution",
    document_node_types=["paper", "article", "specification"],
    max_hops=2,
    min_relevance=0.7,
    max_documents=5,
    reasoning_depth="deep"
)

# Extract reasoning trace
reasoning_trace = result["reasoning_trace"]
print(f"Reasoning Steps: {len(reasoning_trace)}")
for i, step in enumerate(reasoning_trace):
    print(f"Step {i+1}: {step}")

# Output answer with evidence
print("\nAnswer:")
print(result["answer"])

print("\nEvidence:")
for doc in result["documents"]:
    print(f"- {doc['title']} (Relevance: {doc['relevance']:.2f})")

print("\nEvidence Paths:")
for path in result["evidence_paths"]:
    print(f"- Type: {path['type']}, Strength: {path['strength']:.2f}")
    print(f"  Inference: {path['potential_inference']}")

# Visualize reasoning process
tracer.visualize_trace(
    trace_id=result["trace_id"],
    output_path="reasoning_visualization.html"
)
```

## DuckDB, Arrow, and IPLD Integration

This example demonstrates how to integrate DuckDB, Arrow, and IPLD for efficient data processing and storage.

```python
from ipfs_datasets_py.data_integration import UnifiedDataLayer
from ipfs_datasets_py.duckdb_connector import DuckDBConnector
from ipfs_datasets_py.arrow_ipld import ArrowIPLDConverter, DataInterchangeUtils
from ipfs_datasets_py.streaming import StreamingProcessor
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
import json

# Initialize components
data_layer = UnifiedDataLayer()
duckdb_connector = DuckDBConnector("analytics.duckdb")
arrow_ipld = ArrowIPLDConverter()
data_interchange = DataInterchangeUtils()
streaming = StreamingProcessor(chunk_size=10000)

# 1. Create DuckDB table with test data
duckdb_connector.execute("""
    CREATE TABLE IF NOT EXISTS test_data AS
    SELECT 
        i as id,
        'Product ' || i as product_name,
        RANDOM() * 1000 as price,
        RANDOM() * 100 as quantity,
        CASE WHEN RANDOM() < 0.5 THEN 'electronics' ELSE 'clothing' END as category
    FROM RANGE(0, 100000) t(i);
""")

# 2. Run DuckDB query and convert to Arrow
arrow_table = duckdb_connector.query_to_arrow("""
    SELECT 
        id,
        product_name,
        price,
        quantity,
        category,
        price * quantity as total_value
    FROM test_data
    WHERE category = 'electronics'
    ORDER BY total_value DESC;
""")

print(f"Arrow table has {len(arrow_table)} rows")

# 3. Convert Arrow table to IPLD
root_cid, blocks = arrow_ipld.table_to_ipld(
    arrow_table,
    hash_columns=["id", "product_name"]
)

print(f"Converted to IPLD with root CID: {root_cid}")
print(f"Number of IPLD blocks: {len(blocks)}")

# 4. Export IPLD blocks to CAR file
car_path = "arrow_data.car"
data_interchange.export_blocks_to_car(blocks, root_cid, car_path)

print(f"Exported to CAR file: {car_path}")

# 5. Import back from CAR to Arrow
imported_root_cid, imported_blocks = data_interchange.import_from_car(car_path)
imported_table = arrow_ipld.ipld_to_table(imported_root_cid, imported_blocks)

print(f"Imported table has {len(imported_table)} rows")

# 6. Process large dataset in streaming fashion
large_parquet_path = "large_dataset.parquet"

# First create a large dataset
duckdb.execute(f"""
    COPY (
        SELECT 
            i as id,
            'Product ' || i as product_name,
            RANDOM() * 1000 as price,
            RANDOM() * 100 as quantity,
            CASE WHEN RANDOM() < 0.5 THEN 'electronics' ELSE 'clothing' END as category
        FROM RANGE(0, 1000000) t(i)
    )
    TO '{large_parquet_path}'
    (FORMAT PARQUET, ROW_GROUP_SIZE 100000)
""")

# Process in streaming fashion to CAR
streaming_car_path = "large_dataset.car"
streaming.stream_parquet_to_car(
    parquet_path=large_parquet_path,
    car_path=streaming_car_path,
    hash_columns=["id", "product_name"]
)

print(f"Streamed large dataset to CAR file: {streaming_car_path}")

# 7. Use C Data Interface for interprocess communication
c_data = data_interchange.get_c_data_interface(arrow_table)

# Serialize interface data (except for the actual memory buffers)
interface_json = json.dumps({
    "schema": c_data["schema"],
    "buffer_addresses": [int(addr) for addr in c_data["buffers"]]
})

print(f"Prepared C Data Interface: {len(interface_json)} bytes")
```

## Resilient Distributed Operations

This example demonstrates how to implement resilient operations in a distributed environment with fault tolerance.

```python
from ipfs_datasets_py.resilient_operations import (
    CircuitBreaker, RetryStrategy, HealthMonitor, 
    NodeSelector, CheckpointManager
)
from ipfs_datasets_py.distributed import DistributedProcessor
import time
import random

# Define retry strategy
retry_strategy = RetryStrategy(
    max_retries=3,
    base_delay=1.0,
    max_delay=10.0,
    backoff_factor=2.0,
    jitter=0.1
)

# Create circuit breaker
circuit_breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=30,
    half_open_requests=2
)

# Create health monitor
health_monitor = HealthMonitor(
    ping_interval=5,
    timeout=2,
    failure_threshold=3,
    success_threshold=5
)

# Create node selector
node_selector = NodeSelector(
    selection_strategy="health_aware",
    min_healthy_ratio=0.5,
    prefer_local=True
)

# Create checkpoint manager
checkpoint_manager = CheckpointManager(
    checkpoint_interval=60,
    storage_path="checkpoints",
    max_checkpoints=5
)

# Initialize sample nodes
nodes = [
    {"id": "node1", "address": "192.168.1.101", "status": "healthy"},
    {"id": "node2", "address": "192.168.1.102", "status": "healthy"},
    {"id": "node3", "address": "192.168.1.103", "status": "degraded"},
    {"id": "node4", "address": "192.168.1.104", "status": "healthy"},
    {"id": "node5", "address": "192.168.1.105", "status": "unhealthy"}
]

# Register nodes with health monitor
for node in nodes:
    health_monitor.register_node(node["id"], node["address"])

# Start health monitoring
health_monitor.start()

# Simulate node health changes
def simulate_health_changes():
    while True:
        for node in nodes:
            if random.random() < 0.1:  # 10% chance to change status
                node["status"] = random.choice(["healthy", "degraded", "unhealthy"])
                health_monitor.update_node_status(
                    node["id"], 
                    {"status": node["status"]}
                )
        time.sleep(10)

# Create distributed processor
processor = DistributedProcessor(
    nodes=nodes,
    retry_strategy=retry_strategy,
    circuit_breaker=circuit_breaker,
    health_monitor=health_monitor,
    node_selector=node_selector,
    checkpoint_manager=checkpoint_manager
)

# Example distributed operation with checkpointing
@processor.distributed
def process_dataset_chunk(chunk_id, data):
    print(f"Processing chunk {chunk_id} on node {processor.current_node}")
    # Simulate processing
    time.sleep(random.random() * 2)
    # Simulate failures
    if random.random() < 0.2:  # 20% chance of failure
        raise Exception(f"Processing failed for chunk {chunk_id}")
    return {"chunk_id": chunk_id, "result": "processed", "records": len(data)}

# Process dataset with resilience
with processor.resilient_operation(
    operation_name="process_large_dataset",
    checkpoint_enabled=True
) as op:
    # Split dataset into chunks
    dataset_chunks = [{"id": i, "data": list(range(100))} for i in range(20)]
    
    # Process chunks with resilience
    results = []
    for chunk in dataset_chunks:
        try:
            # Will automatically retry on failure, trigger circuit breaker, etc.
            result = process_dataset_chunk(chunk["id"], chunk["data"])
            results.append(result)
            # Save checkpoint after each chunk
            op.checkpoint({"processed_chunks": len(results), "last_chunk_id": chunk["id"]})
        except Exception as e:
            print(f"Failed to process chunk {chunk['id']}: {e}")
    
    # Final results
    print(f"Successfully processed {len(results)} chunks")
    print(f"Total records processed: {sum(r['records'] for r in results)}")
```

## Comprehensive Audit and Provenance Tracking

This example demonstrates comprehensive audit logging and data provenance tracking for a complex data processing workflow.

```python
from ipfs_datasets_py.audit import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.data_provenance import EnhancedProvenanceManager
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
import uuid
import datetime
import os

# Create directories
os.makedirs("logs", exist_ok=True)
os.makedirs("provenance", exist_ok=True)

# 1. Set up audit logging
audit_logger = AuditLogger.get_instance()
audit_logger.min_level = AuditLevel.INFO
audit_logger.default_application = "data_processor"

# Add file handler for audit logs
audit_logger.add_file_handler(
    name="file",
    file_path="logs/audit.log",
    min_level=AuditLevel.INFO,
    rotate_size_mb=10,
    rotate_count=5
)

# Add JSON handler for machine-readable logs
audit_logger.add_json_handler(
    name="json",
    file_path="logs/audit.json",
    min_level=AuditLevel.INFO
)

# 2. Set up provenance tracking
provenance_manager = EnhancedProvenanceManager(
    storage_path="provenance/records.db"
)

# 3. Set up audit-provenance integration
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# 4. Record workflow overview
workflow_id = str(uuid.uuid4())
project_id = "project-123"
user_id = "user-456"

audit_logger.log(
    level=AuditLevel.INFO,
    category=AuditCategory.WORKFLOW,
    message="Starting data processing workflow",
    context={
        "workflow_id": workflow_id,
        "project_id": project_id,
        "user_id": user_id,
        "start_time": datetime.datetime.now().isoformat()
    }
)

provenance_manager.record_workflow(
    workflow_id=workflow_id,
    name="Data Processing Workflow",
    description="Extract, transform, and analyze data from multiple sources",
    initiated_by=user_id,
    project_id=project_id
)

# 5. Data source acquisition with audit and provenance
source_id = str(uuid.uuid4())
with audit_logger.create_context(
    category=AuditCategory.DATA_SOURCE,
    context={"workflow_id": workflow_id, "source_id": source_id}
) as audit_ctx:
    # Record audit event
    audit_ctx.log(
        level=AuditLevel.INFO,
        message="Acquiring data from external source",
        context={"source_type": "api", "source_url": "https://example.com/api/data"}
    )
    
    # Record provenance
    provenance_manager.record_data_source(
        source_id=source_id,
        source_type="api",
        source_uri="https://example.com/api/data",
        access_time=datetime.datetime.now(),
        access_method="https",
        user_id=user_id,
        workflow_id=workflow_id
    )
    
    # Simulate data acquisition
    source_data = {"records": [{"id": i, "value": i * 2} for i in range(100)]}
    
    # Record completion
    audit_ctx.log(
        level=AuditLevel.INFO,
        message="Data acquisition completed",
        context={"record_count": len(source_data["records"])}
    )

# 6. Data transformation with audit and provenance
transform_id = str(uuid.uuid4())
output_id = str(uuid.uuid4())

with audit_logger.create_context(
    category=AuditCategory.DATA_TRANSFORMATION,
    context={"workflow_id": workflow_id, "transform_id": transform_id}
) as audit_ctx:
    # Record start of transformation
    audit_ctx.log(
        level=AuditLevel.INFO,
        message="Starting data transformation",
        context={"operation": "filter_and_enrich"}
    )
    
    # Record provenance transformation
    provenance_manager.record_transformation(
        transformation_id=transform_id,
        source_id=source_id,
        transformation_type="filter_and_enrich",
        parameters={"min_value": 50, "add_metadata": True},
        output_id=output_id,
        workflow_id=workflow_id,
        user_id=user_id
    )
    
    # Simulate transformation
    transformed_data = [
        {"id": r["id"], "value": r["value"], "metadata": {"processed": True}}
        for r in source_data["records"] if r["value"] >= 50
    ]
    
    # Record transformation steps in detail
    audit_ctx.log(
        level=AuditLevel.DEBUG,
        message="Applied filtering",
        context={"filter_criteria": "value >= 50", "input_count": len(source_data["records"]), "output_count": len(transformed_data)}
    )
    
    audit_ctx.log(
        level=AuditLevel.DEBUG,
        message="Added metadata",
        context={"metadata_fields": ["processed"]}
    )
    
    # Record transformation completion
    audit_ctx.log(
        level=AuditLevel.INFO,
        message="Data transformation completed",
        context={"input_count": len(source_data["records"]), "output_count": len(transformed_data)}
    )
    
    # Add transformation step details
    provenance_manager.add_transformation_step(
        transformation_id=transform_id,
        step_number=1,
        step_type="filter",
        parameters={"min_value": 50},
        input_count=len(source_data["records"]),
        output_count=len(transformed_data)
    )
    
    provenance_manager.add_transformation_step(
        transformation_id=transform_id,
        step_number=2,
        step_type="enrich",
        parameters={"fields": ["metadata"]},
        input_count=len(transformed_data),
        output_count=len(transformed_data)
    )

# 7. Data export with audit and provenance
export_id = str(uuid.uuid4())

with audit_logger.create_context(
    category=AuditCategory.DATA_EXPORT,
    context={"workflow_id": workflow_id, "export_id": export_id}
) as audit_ctx:
    # Record export start
    audit_ctx.log(
        level=AuditLevel.INFO,
        message="Starting data export",
        context={"format": "parquet", "destination": "file"}
    )
    
    # Record provenance
    provenance_manager.record_data_export(
        export_id=export_id,
        source_id=output_id,
        export_format="parquet",
        destination_type="file",
        destination_uri="file:///data/output.parquet",
        export_time=datetime.datetime.now(),
        record_count=len(transformed_data),
        workflow_id=workflow_id,
        user_id=user_id
    )
    
    # Simulate export
    output_hash = hashlib.sha256(str(transformed_data).encode()).hexdigest()
    
    # Record export completion
    audit_ctx.log(
        level=AuditLevel.INFO,
        message="Data export completed",
        context={"record_count": len(transformed_data), "file_hash": output_hash}
    )
    
    # Update provenance with hash
    provenance_manager.update_data_export(
        export_id=export_id,
        metadata={"file_hash": output_hash}
    )

# 8. Workflow completion with audit
audit_logger.log(
    level=AuditLevel.INFO,
    category=AuditCategory.WORKFLOW,
    message="Data processing workflow completed",
    context={
        "workflow_id": workflow_id,
        "end_time": datetime.datetime.now().isoformat(),
        "status": "success",
        "records_processed": len(transformed_data)
    }
)

# 9. Generate provenance report
lineage = provenance_manager.get_lineage(output_id)
report = provenance_manager.generate_report(
    entity_id=output_id,
    report_type="full",
    include_visualizations=True
)

# Save report
with open("provenance/workflow_report.json", "w") as f:
    json.dump(report, f, indent=2)

# Generate visualization
provenance_manager.visualize_lineage(
    entity_id=output_id,
    output_path="provenance/lineage_visualization.html",
    include_attributes=True,
    include_operations=True
)

print(f"Workflow completed: {workflow_id}")
print(f"See audit logs in: logs/audit.log")
print(f"See provenance report in: provenance/workflow_report.json")
print(f"See lineage visualization in: provenance/lineage_visualization.html")
```

These advanced examples demonstrate the flexibility and power of IPFS Datasets Python for complex data processing, storage, and retrieval tasks. By combining multiple features, you can build sophisticated data pipelines and applications that leverage the power of decentralized storage and distributed computing.
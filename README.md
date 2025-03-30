# IPFS Huggingface Datasets

This is a model manager and wrapper for huggingface, looks up a index of models from an collection of models, and will download a model from either https/s3/ipfs, depending on which source is the fastest.

## How to use
~~~shell
pip install .
~~~

look run ``python3 example.py`` for examples of usage.

this is designed to be a drop in replacement, which requires only 2 lines to be changed

In your python script
~~~shell
from datasets import load_dataset
from ipfs_datasets import load_dataset
dataset = load_dataset.from_auto_download("bge-small-en-v1.5")  
~~~

or 

~~~shell
from datasets import load_dataset
from ipfs_datasets import load_dataset
dataset = load_dataset.from_ipfs("QmccfbkWLYs9K3yucc6b3eSt8s8fKcyRRt24e3CDaeRhM1")
~~~

or to use with with s3 caching 
~~~shell
from datasets import load_dataset
from ipfs_datasets import load_dataset
dataset = load_dataset.from_auto_download(
    dataset_name="common-crawl",
    s3cfg={
        "bucket": "cloud",
        "endpoint": "https://storage.googleapis.com",
        "secret_key": "",
        "access_key": ""
    }
)
~~~

## Advanced GraphRAG Capabilities

This library includes advanced Graph Retrieval-Augmented Generation (GraphRAG) capabilities that combine vector embeddings with graph structures for enhanced information retrieval.

```python
from ipfs_datasets_py.dataset_serialization import VectorAugmentedGraphDataset
import numpy as np

# Create a GraphRAG dataset
dataset = VectorAugmentedGraphDataset(vector_dimension=768)

# Add nodes with vector embeddings
paper1 = dataset.add_node("paper", {"title": "Neural Networks"}, vector=vector1)
paper2 = dataset.add_node("paper", {"title": "Graph Neural Networks"}, vector=vector2)

# Add edges with properties
dataset.add_edge(paper1, "cites", paper2, {"importance": "high"})

# Perform basic GraphRAG searches

# 1. Find semantically similar nodes connected by specific relationships
results = dataset.find_similar_connected_nodes(
    query_vector=query_vector,
    max_hops=2,
    edge_filters=[("importance", "=", "high")]
)

# 2. Extract a subgraph of semantically similar nodes
subgraph = dataset.semantic_subgraph(
    query_vector=query_vector,
    similarity_threshold=0.7
)

# 3. Perform logical operations on multiple query vectors
results = dataset.logical_query(
    query_vectors=[vector1, vector2],
    operators=["AND"],
    similarity_threshold=0.7
)

# 4. Hybrid search combining semantic similarity with structured filters
results = dataset.hybrid_structured_semantic_search(
    query_vector=query_vector,
    node_filters=[("citation_count", ">=", 50)],
    relationship_patterns=[{
        "direction": "outgoing",
        "edge_type": "cites",
        "edge_filters": [("importance", "=", "high")]
    }]
)

# 5. Generate explanations for paths between nodes
explanations = dataset.explain_path(
    start_node_id=paper1,
    end_node_id=paper2
)

# 6. Incrementally update the graph
dataset.incremental_graph_update(
    nodes_to_add=[new_node],
    edges_to_add=[(paper1, "references", "new_node", {"count": 3})],
    maintain_index=True
)

# Advanced knowledge graph features

# 7. Rank nodes by centrality with PageRank algorithm
central_nodes = dataset.rank_nodes_by_centrality(
    query_vector=query_vector,  # Optional semantic influence
    damping_by_similarity=True,
    weight_by_edge_properties={"cites": "importance"}
)

# 8. Infer indirect relationships through multi-hop patterns
collaborators = dataset.multi_hop_inference(
    start_node_id="author1",
    relationship_pattern=["authored", "cites", "authored_by"],
    confidence_threshold=0.5
)

# 9. Discover entity clusters and thematic communities
clusters = dataset.find_entity_clusters(
    similarity_threshold=0.6,
    min_community_size=3,
    relationship_weight=0.4
)

# Advanced retrieval enhancement

# 10. Expand queries with knowledge graph context
expanded_query = dataset.expand_query(
    query_vector=query_vector,
    expansion_strategy="concept_enrichment",
    expansion_factor=0.3,
    max_terms=3
)

# 11. Identify and group duplicate entities
entity_groups = dataset.resolve_entities(
    candidate_nodes=papers,
    resolution_strategy="hybrid",
    similarity_threshold=0.8
)

# 12. Generate context-aware embeddings
contextual_embedding = dataset.generate_contextual_embeddings(
    node_id=paper1,
    context_strategy="type_specific",
    context_depth=1
)
```

These GraphRAG capabilities allow for enhanced knowledge retrieval that combines the benefits of semantic similarity search with graph-based relationships. The library supports:

### Basic Features
- **Semantic Search**: Find entities based on vector similarity
- **Structured Queries**: Filter entities by metadata and relationship patterns
- **Hybrid Retrieval**: Combine semantic and structured search criteria
- **Graph Analysis**: Rank entities by centrality and discover clusters
- **Relationship Inference**: Discover implicit connections through patterns
- **Path Explanation**: Generate natural language explanations of entity connections
- **Incremental Updates**: Efficiently maintain and update knowledge graphs
- **Community Detection**: Identify thematic clusters in the knowledge graph

### Advanced Features
- **Query Expansion**: Enhance queries with related concepts from the knowledge graph
- **Entity Resolution**: Identify and link duplicate or equivalent entities
- **Contextual Embeddings**: Generate vectors that incorporate graph structure
- **Semantic Ranking**: PageRank variant with semantic similarity influence
- **Multi-hop Inference**: Discover indirect relationships through pattern matching
- **Relationship Weighting**: Weight edges by semantic and structural properties
- **Thematic Clustering**: Identify communities with common themes
- **Semantic Deduplication**: Merge equivalent entities based on properties and vectors
- **Subgraph Comparison**: Measure similarity between different subgraphs
- **Temporal Analysis**: Track graph evolution over time periods
- **Knowledge Graph Completion**: Predict missing relationships
- **Cross-Document Reasoning**: Reason across multiple documents using entity connections
- **LLM-Enhanced GraphRAG**: Integrate LLMs for improved reasoning capabilities

```python
# Comparing subgraphs
comparison = dataset.compare_subgraphs(
    subgraph1=ml_subgraph, 
    subgraph2=cv_subgraph,
    comparison_method="hybrid",
    semantic_weight=0.6,
    structural_weight=0.4
)

# Analyzing temporal evolution of the graph
results = dataset.temporal_graph_analysis(
    time_property="year",
    time_intervals=[(2018, 2019), (2020, 2021)],
    metrics=["node_count", "edge_count", "density"],
    reference_node_id="paper1"  # Track a specific entity
)

# Predicting missing relationships in the graph
predicted_edges = dataset.knowledge_graph_completion(
    completion_method="combined",  # semantic, structural, or combined
    target_relation_types=["cites"],
    min_confidence=0.7,
    use_existing_edges_as_training=True
)

# Performing cross-document reasoning
reasoning_result = dataset.cross_document_reasoning(
    query="How has deep learning influenced computer vision?",
    document_node_types=["document", "paper"],
    max_hops=2,
    reasoning_depth="moderate"  # basic, moderate, or deep
)
```

### Cross-Document Reasoning

The library provides advanced cross-document reasoning capabilities that go beyond simple document retrieval. This feature enables answering complex queries by connecting information across multiple documents using their semantic relationships and shared entities.

```python
# Sample cross-document reasoning for a complex query
result = dataset.cross_document_reasoning(
    query="What is the relationship between neural networks and reinforcement learning?",
    document_node_types=["document", "paper"],
    max_hops=2,
    min_relevance=0.6,
    max_documents=5,
    reasoning_depth="deep"  # basic, moderate, or deep
)

# Access the synthesized answer
print(result["answer"])

# Access the evidence paths
for path in result["evidence_paths"]:
    print(f"Connection: {path['potential_inference']}")

# Get explanation of the reasoning process
for step in result["reasoning_trace"]:
    print(step)

# Get confidence score
print(f"Answer confidence: {result['confidence']}")
```

#### Reasoning Depths:
- **Basic**: Simple connections between documents through shared entities
- **Moderate**: Entity-mediated relationships with information relation analysis (complementary/contradictory)
- **Deep**: Complex multi-hop reasoning with knowledge gaps, transitive relationships, and detailed inferences

The cross-document reasoning feature enables:
- Identifying connections between documents through shared entities
- Detecting complementary or contradictory information
- Analyzing knowledge gaps between documents
- Discovering transitive relationships through multi-hop paths
- Generating comprehensive answers with confidence scores
- Producing detailed reasoning traces that explain the answer derivation

### Knowledge Graph Extraction with Temperature Control

The library provides advanced knowledge graph extraction capabilities with tunable parameters to control the level of detail and structural complexity:

```python
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor

# Initialize the extractor
extractor = KnowledgeGraphExtractor()

# Extract knowledge graph with temperature parameters
text = "IPFS (InterPlanetary File System) is a protocol and peer-to-peer network for storing and sharing data in a distributed file system. IPFS was created by Juan Benet and is maintained by Protocol Labs."

kg = extractor.extract_knowledge_graph(
    text=text,
    extraction_temperature=0.7,  # Controls level of detail extracted
    structure_temperature=0.5    # Controls structural complexity of the graph
)

# View extracted entities
for entity in kg.entities.values():
    print(f"Entity: {entity.name}, Type: {entity.entity_type}, Confidence: {entity.confidence}")

# View extracted relationships
for rel in kg.relationships.values():
    print(f"Relationship: {rel.source_entity.name} --[{rel.relationship_type}]--> {rel.target_entity.name}")
```

#### Temperature Parameters:
- **Extraction Temperature (0.0-1.0)**:
  - Lower values (0.1-0.3): Extract only major concepts and strongest relationships
  - Medium values (0.4-0.7): Extract balanced set of entities and relationships
  - Higher values (0.8-1.0): Extract detailed concepts, properties, and nuanced relationships

- **Structure Temperature (0.0-1.0)**:
  - Lower values (0.1-0.3): Flatter structure with fewer relationship types
  - Medium values (0.4-0.7): Balanced hierarchical structure
  - Higher values (0.8-1.0): Rich, multi-level concept hierarchies with diverse relationship types

### Knowledge Graph Extraction with Integrated SPARQL Validation

The library includes comprehensive capabilities for extracting knowledge graphs from text, Wikipedia pages, and multiple documents, with integrated validation against Wikidata using SPARQL queries:

```python
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractorWithValidation

# Initialize the extractor with integrated validation
extractor = KnowledgeGraphExtractorWithValidation(
    validate_during_extraction=True,
    auto_correct_suggestions=True,
    cache_validation_results=True
)

# Extract knowledge graph from a Wikipedia page with validation
result = extractor.extract_from_wikipedia(
    page_title="IPFS",
    extraction_temperature=0.7,
    structure_temperature=0.5,
    validation_depth=2  # Include relationship validation
)

# Access the extracted knowledge graph
kg = result["knowledge_graph"]
print(f"Extracted {len(kg.entities)} entities and {len(kg.relationships)} relationships")

# Check validation metrics
metrics = result["validation_metrics"]
print(f"Property coverage: {metrics['property_coverage']:.2f}")
print(f"Relationship coverage: {metrics['relationship_coverage']:.2f}")
print(f"Overall coverage: {metrics['overall_coverage']:.2f}")

# Get correction suggestions
if "corrections" in result:
    print("Correction suggestions available")
    
    # Apply the suggested corrections
    corrected_kg = extractor.apply_validation_corrections(
        kg=kg,
        corrections=result["corrections"]
    )
    print(f"Corrected knowledge graph created")

# Extract from custom text
text_result = extractor.extract_knowledge_graph(
    text="IPFS is a peer-to-peer hypermedia protocol designed to make the web faster, safer, and more open.",
    validation_depth=1  # Validate only entities
)

# Extract from multiple documents
documents = [
    {"title": "Doc 1", "text": "IPFS was created by Juan Benet in 2014."},
    {"title": "Doc 2", "text": "Protocol Labs develops IPFS and Filecoin."}
]
multi_doc_result = extractor.extract_from_documents(
    documents=documents,
    text_key="text",
    validation_depth=2
)
```

This enhanced functionality provides:
- **Integrated extraction and validation**: Seamlessly extract and validate knowledge graphs in one step
- **Validation against Wikidata**: Verify entity properties and relationships using SPARQL queries
- **Automatic correction suggestions**: Receive suggestions for fixing inaccurate or incomplete information
- **Path finding between entities**: Discover how entities are connected in Wikidata
- **Validation metrics**: Measure coverage of properties and relationships compared to Wikidata
- **Caching of validation results**: Improve performance with cached validation results
- **Multiple sources**: Extract from text, Wikipedia articles, or multiple documents
- **Flexible validation depth**: Control whether to validate only entities or both entities and relationships

### Comprehensive RAG Query Optimization Framework

The library includes a comprehensive query optimization framework for GraphRAG operations, supporting both Wikipedia-derived knowledge graphs and IPLD-based knowledge graphs. The framework consists of specialized optimizers that can be used independently or through a unified interface that handles mixed environments.

```python
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
from ipfs_datasets_py.rag_query_optimizer import (
    WikipediaKnowledgeGraphOptimizer,  # For Wikipedia-derived knowledge graphs
    IPLDGraphRAGQueryOptimizer,        # For IPLD-based knowledge graphs
    UnifiedGraphRAGQueryOptimizer      # For mixed environments
)
import numpy as np

# Create a query vector (using an embedding model in real applications)
query = "How does content addressing work in distributed systems?"
query_vector = np.random.rand(768)  # Placeholder for a real embedding

# Option 1: Wikipedia-specific optimization
tracer = WikipediaKnowledgeGraphTracer()
wiki_optimizer = WikipediaKnowledgeGraphOptimizer(tracer=tracer)

# Optimize the query for a Wikipedia-derived knowledge graph
wiki_plan = wiki_optimizer.optimize_query(
    query_text=query,
    query_vector=query_vector,
    trace_id="wikipedia-trace-123"  # Trace ID from extraction
)

# Option 2: IPLD-specific optimization
ipld_optimizer = IPLDGraphRAGQueryOptimizer()

# Optimize the query for an IPLD-based knowledge graph
ipld_plan = ipld_optimizer.optimize_query(
    query_vector=query_vector,
    query_text=query,
    root_cids=["QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco"],  # Root CID
    content_types=["application/json"]  # Content types to optimize for
)

# Option 3: Unified optimizer for mixed environments
unified_optimizer = UnifiedGraphRAGQueryOptimizer(
    wikipedia_optimizer=wiki_optimizer,
    ipld_optimizer=ipld_optimizer,
    auto_detect_graph_type=True
)

# Automatically detect graph type based on parameters
auto_plan = unified_optimizer.optimize_query(
    query_vector=query_vector,
    query_text=query,
    trace_id="wikipedia-trace-123"  # Will use Wikipedia optimizer
)

# Multi-graph query that spans different graph types
multi_graph_plan = unified_optimizer.optimize_multi_graph_query(
    query_vector=query_vector,
    query_text="Compare content addressing in IPFS and BitTorrent",
    graph_specs=[
        {"graph_type": "wikipedia", "trace_id": "wiki-ipfs", "weight": 0.4},
        {"graph_type": "wikipedia", "trace_id": "wiki-bittorrent", "weight": 0.3},
        {"graph_type": "ipld", "root_cid": "QmZ4tDuvesekSs4qM5ZBKpXiZGun7S2CYtEZRB3DYXkjGx", "weight": 0.3}
    ]
)

# Get optimization statistics and performance analysis
stats = unified_optimizer.get_optimization_stats()
analysis = unified_optimizer.analyze_query_performance()
```

The query optimization framework provides:

#### Wikipedia Knowledge Graph Optimization
- **Type-Specific Optimization**: Adapts query parameters based on entity types in the query
- **Edge Type Detection**: Identifies important relationship types for the query
- **Temperature-Aware Planning**: Uses extraction and validation information to adjust parameters
- **Category Expansion**: Automatically expands queries with category-related terms
- **Entity-Mediated Traversal**: Plans efficient paths through connecting entities
- **Cross-Document Reasoning**: Optimizes queries that require information from multiple documents

#### IPLD Knowledge Graph Optimization
- **CID-Aware Caching**: Optimizes query execution with CID-level caching
- **Content-Addressed Path Planning**: Efficient traversal planning for IPLD DAGs
- **Content Type-Specific Tuning**: Adjusts vector/graph weights based on content types
- **Block Prefetching**: Intelligent prefetching of relevant IPLD blocks
- **DAG Traversal Strategies**: Breadth-first or depth-first strategies based on query patterns
- **Multi-CID Query Planning**: Optimized planning for queries spanning multiple CIDs

#### Unified Optimization for Mixed Environments
- **Graph Type Auto-Detection**: Automatically determines the appropriate optimizer
- **Multi-Graph Support**: Handles queries spanning different graph types
- **Weighted Result Combination**: Adjustable weights for different knowledge sources
- **Performance Analysis**: Comprehensive statistics and optimization recommendations
- **Cache Management**: Intelligent caching across different graph types
- **Centralized Statistics**: Unified view of query patterns and performance

See the `examples/rag_query_optimizer_example.py` file for comprehensive usage examples.

### LLM-Enhanced GraphRAG with Query Optimization

The library integrates the RAG Query Optimizer with the GraphRAG LLM processor for enhanced cross-document reasoning. This integration enables optimized knowledge graph traversal, content-aware query planning, and improved performance.

```python
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer
from ipfs_datasets_py.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.llm_graphrag import GraphRAGLLMProcessor, ReasoningEnhancer
from ipfs_datasets_py.llm_interface import LLMInterfaceFactory
import numpy as np

# Create the query optimizer
tracer = WikipediaKnowledgeGraphTracer()
unified_optimizer = UnifiedGraphRAGQueryOptimizer(
    wikipedia_optimizer=WikipediaKnowledgeGraphOptimizer(tracer=tracer),
    ipld_optimizer=IPLDGraphRAGQueryOptimizer(),
    auto_detect_graph_type=True
)

# Initialize LLM processor with the optimizer
llm = LLMInterfaceFactory.create()
processor = GraphRAGLLMProcessor(
    llm_interface=llm,
    query_optimizer=unified_optimizer
)

# Create reasoning enhancer
enhancer = ReasoningEnhancer(
    llm_processor=processor,
    query_optimizer=unified_optimizer
)

# Perform optimized cross-document reasoning
documents = [...]  # Your document list
connections = [...]  # Document connections
query = "How do neural networks relate to transformers?"
query_vector = np.array([...])  # Your query embedding

# The optimize_and_reason method automatically applies the appropriate optimizations
result = enhancer.optimize_and_reason(
    query=query,
    query_vector=query_vector,
    documents=documents,
    connections=connections,
    reasoning_depth="moderate",
    doc_trace_ids=["trace1", "trace2"],  # For Wikipedia graphs
    root_cids=["bafy123", "bafy456"]     # For IPLD graphs
)

# Access the optimized results
answer = result["answer"]
confidence = result["confidence"]
optimizer_info = result.get("optimizer_info", {})
```

Key features of the integrated system:

- **Optimizer-Enhanced LLM Processing**: Combines the power of query optimization with LLM capabilities
- **Knowledge Graph-Aware Reasoning**: Uses graph structure to improve reasoning quality
- **Multi-Graph Support**: Handles reasoning across Wikipedia and IPLD-based knowledge graphs
- **Domain-Specific Processing**: Tailors reasoning for different knowledge domains (academic, medical, etc.)
- **Performance Monitoring**: Tracks and analyzes LLM interactions for optimization
- **Cross-Document Analysis**: Identifies connections and performs reasoning across multiple documents

The system provides a seamless way to enhance the quality of answers by optimizing how the knowledge graph is traversed and which parts are prioritized based on the query.

# Example of direct processor usage
result = processor.analyze_evidence_chain(
    doc1={"id": "doc1", "title": "Document 1"},
    doc2={"id": "doc2", "title": "Document 2"},
    entity={"id": "entity1", "name": "Entity", "type": "concept"},
    doc1_context="Context from document 1",
    doc2_context="Context from document 2"
)

print(f"Relationship type: {result['relationship_type']}")
print(f"Inference: {result['inference']}")
print(f"Confidence: {result['confidence']}")
```

The GraphRAG LLM integration with Query Optimization provides:
- **Enhanced Cross-Document Reasoning**: More sophisticated analysis of document connections
- **Evidence Chain Analysis**: LLM-powered analysis of document relationships
- **Query-Optimized Knowledge Graph Traversal**: Efficient exploration of graph structures
- **Content-Type Aware Processing**: Tailored processing for different content types
- **Domain-Specific Analysis**: Specialized analysis for different knowledge domains
- **Performance Monitoring and Optimization**: Continuous improvement of reasoning quality
- **Knowledge Gap Identification**: Detection of missing information between documents
- **Deep Inference Generation**: Generation of insights based on document connections
- **Transitive Relationship Analysis**: Analysis of multi-hop paths between entities
- **LLM-Powered Synthesis**: Generation of comprehensive answers to complex queries
- **Mock LLM Interface**: Development-ready interfaces that will eventually connect to real models

### Tracing and Explanation for GraphRAG

The library includes comprehensive tracing and explanation capabilities for GraphRAG operations, particularly for Wikipedia knowledge graph extraction and cross-document analysis:

```python
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor, KnowledgeGraphExtractorWithValidation
from ipfs_datasets_py.llm_reasoning_tracer import WikipediaKnowledgeGraphTracer

# Initialize components
tracer = WikipediaKnowledgeGraphTracer()
extractor = KnowledgeGraphExtractorWithValidation(use_tracer=True)

# Extract knowledge graph with tracing
result = extractor.extract_from_wikipedia(
    page_title="IPFS",
    extraction_temperature=0.7,
    structure_temperature=0.5,
    validation_depth=2
)
kg = result["knowledge_graph"]
trace_id = result.get("trace_id")

# Get detailed explanation of the extraction process
explanation = tracer.explain_extraction_trace(trace_id)
print(explanation)

# Generate visualization of the knowledge graph
visualization = tracer._generate_detailed_mermaid_graph({"entities": kg.entities, "relationships": kg.relationships})
print(visualization)

# Extract knowledge graphs from multiple related pages
ai_result = extractor.extract_from_wikipedia("Artificial Intelligence", validation_depth=2)
ml_result = extractor.extract_from_wikipedia("Machine Learning", validation_depth=2)
dl_result = extractor.extract_from_wikipedia("Deep Learning", validation_depth=2)

# Perform cross-document analysis
analysis = tracer.cross_document_analysis(
    trace_ids=[ai_result.get("trace_id"), ml_result.get("trace_id"), dl_result.get("trace_id")],
    entity_threshold=0.7,
    relationship_threshold=0.6
)

# Print cross-document insights
print(f"Found {len(analysis['connecting_entities'])} connecting entities across documents")
print(f"Found {len(analysis['shared_relationships'])} shared relationships")
print(f"Identified {len(analysis['knowledge_gaps']['property_gaps'])} knowledge gaps")
print(f"Generated {len(analysis['potential_inferences'])} potential inferences")

# Visualize cross-document connections
print(analysis["visualization"])

# Compare different temperature settings
comparison = tracer.compare_temperature_settings(
    trace_ids=["low_temp_extraction", "medium_temp_extraction", "high_temp_extraction"],
    comparison_aspects=["entity_count", "relationship_count", "structure_complexity"]
)

# Get temperature recommendations
recommendation = tracer.generate_temperature_recommendation(
    trace_id=trace_id,
    target="balanced"  # Can be "detailed", "balanced", or "concise"
)
print(f"Recommended settings: extraction={recommendation['recommended_settings']['extraction_temperature']}, structure={recommendation['recommended_settings']['structure_temperature']}")
```

The enhanced tracing and explanation capabilities now provide:

#### Basic Features
- **Detailed Process Tracing**: Capture every step of the knowledge graph extraction and validation
- **Temperature Impact Analysis**: Compare the effects of different temperature settings with detailed metrics
- **Wikidata Coverage Gap Analysis**: Identify what knowledge is missing compared to Wikidata
- **Enhanced Visualizations**: Generate detailed graph visualizations, timelines, and cross-document connections
- **Confidence Explanation**: Explain how confidence scores were determined
- **Human-Readable Summaries**: Generate concise explanations of complex processes
- **Knowledge Graph Statistics**: Provide detailed metrics about extracted knowledge graphs

#### New Cross-Document Analysis Features
- **Entity Connections**: Discover entities that appear across multiple Wikipedia pages
- **Shared Relationship Detection**: Identify similar relationships across documents
- **Knowledge Gap Analysis**: Find missing properties and relationships in documents
- **Cross-Document Inferences**: Generate potential inferences by combining information across documents
- **Cross-Document Visualization**: Visualize the connections between documents through shared entities

#### Advanced Temperature Control
- **Temperature Recommendation System**: Get recommendations for temperature settings based on desired output profiles
- **Profile-Based Extraction**: Choose from "detailed", "balanced", or "concise" extraction profiles
- **Temperature Impact Tracking**: Analyze how temperature changes affect entity counts, relationship diversity, and complexity
- **Entity Type and Relationship Diversity Analysis**: Measure how temperature affects knowledge graph diversity

See the `examples/graph_reasoning_tracer_example.py` file for comprehensive examples of these new capabilities.

### Distributed Dataset Management with LibP2P

The library includes distributed dataset management capabilities using LibP2P, enabling peer-to-peer sharing and collaborative dataset building:

```python
from ipfs_datasets_py.libp2p_kit import DistributedDatasetManager, NodeRole
import numpy as np

# Initialize a distributed dataset manager
manager = DistributedDatasetManager(
    storage_dir="./data",
    listen_addresses=["/ip4/0.0.0.0/tcp/0"],
    bootstrap_peers=["/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ"],
    role=NodeRole.HYBRID
)

# Create a new dataset
dataset = manager.create_dataset(
    name="Vector Dataset",
    description="A distributed vector dataset",
    schema={"id": "string", "text": "string", "vector": "float32[]"},
    vector_dimensions=128,
    tags=["example", "vectors"]
)

# Shard the dataset and distribute it across the network
await manager.shard_dataset(
    dataset_id=dataset.dataset_id,
    data=dataset_data,
    format="parquet",
    replication_factor=3
)

# Perform a federated vector search across the network
query_vector = np.random.rand(128)
results = await manager.vector_search(
    dataset_id=dataset.dataset_id,
    query_vector=query_vector,
    top_k=10
)

# Perform a federated keyword search
keyword_results = await manager.keyword_search(
    dataset_id=dataset.dataset_id,
    query="machine learning",
    top_k=10
)

# Get network status information
status = await manager.get_network_status()
print(f"Connected to {status['peer_count']} peers")
print(f"Managing {status['dataset_count']} datasets with {status['shard_count']} shards")
```

The distributed dataset management features provide:

#### Core Features
- **Peer-to-Peer Communication**: Direct communication between dataset nodes using LibP2P
- **Dataset Sharding**: Division of large datasets into manageable shards for distribution
- **Distributed Storage**: Storage of shards across multiple nodes in the network
- **Federated Search**: Search capabilities that span all nodes storing relevant data
- **Metadata Synchronization**: Automatic synchronization of dataset metadata across nodes
- **Node Discovery**: Automatic discovery of peers in the network
- **Resilient Operations**: Handling of node failures and network partitions

#### Advanced Features
- **Dataset Replication**: Configurable replication of shards for redundancy and availability
- **Collaborative Dataset Building**: Ability for multiple nodes to contribute to the same dataset
- **Shard Transfer Protocol**: Efficient protocol for transferring shards between nodes
- **Node Roles**: Different node types (coordinator, worker, hybrid, client) for specialized tasks
- **Protocol Handlers**: Extensible protocol handlers for custom dataset operations
- **Federated Vector Search**: Distributed similarity search across vector embeddings
- **Federated Keyword Search**: Distributed text search capabilities

See the `examples/distributed_dataset_example.py` file for comprehensive examples of these distributed capabilities.

### Performance Optimized Streaming Data Loading

The library includes high-performance streaming data loaders for efficient processing of large datasets:

```python
from ipfs_datasets_py.streaming_data_loader import (
    load_parquet,
    load_csv,
    load_json,
    load_huggingface,
    create_memory_mapped_vectors,
    load_memory_mapped_vectors
)
import numpy as np

# Load a large Parquet file with streaming
dataset = load_parquet(
    parquet_path="large_dataset.parquet",
    batch_size=10000,
    prefetch_batches=2,
    cache_enabled=True
)

# Process data in batches without loading the entire dataset into memory
for batch in dataset.iter_batches():
    # Process batch
    print(f"Processing batch with {len(batch)} records")

# Transform data on-the-fly
transformed_dataset = dataset.map(lambda batch: process_batch(batch))

# Memory-mapped access to large vector datasets
vectors = load_memory_mapped_vectors(
    file_path="embeddings.bin",
    dimension=768,
    mode='r'
)

# Efficient random access without loading entire dataset
vector = vectors[1000]  # Get a specific vector
batch = vectors[5000:5100]  # Get a batch of vectors

# Create and populate memory-mapped vectors
with create_memory_mapped_vectors(
    file_path="new_embeddings.bin",
    dimension=768,
    mode='w+'
) as mmap_vectors:
    # Add vectors in batches
    batch = np.random.rand(1000, 768).astype(np.float32)
    mmap_vectors.append(batch)
```

The streaming data loading capabilities provide:

#### Core Features
- **Memory-Efficient Streaming**: Process datasets larger than available RAM
- **Support for Multiple Formats**: Parquet, CSV, JSON, and HuggingFace datasets
- **Memory-Mapped Vector Access**: Efficient random access to large vector datasets
- **Batch Processing**: Process data in manageable chunks
- **Prefetching**: Load next batch while processing current batch
- **Caching**: Avoid redundant reads with intelligent caching

#### Performance Features
- **Performance Monitoring**: Detailed statistics on throughput and processing time
- **Transformation Pipeline**: Apply transformations while streaming
- **Filtering Capabilities**: Filter data without loading the entire dataset
- **Custom Batch Processing**: Define custom functions to process batches
- **Parallel Processing Support**: Designed to work with parallel processing libraries
- **Minimal Memory Footprint**: Optimized for working with very large datasets

See the `examples/streaming_data_example.py` file for comprehensive examples of these streaming capabilities.

# IPFS Huggingface Bridge:

for transformers python library visit:
https://github.com/endomorphosis/ipfs_transformers/

for transformers js client visit:                          
https://github.com/endomorphosis/ipfs_transformers_js/

for orbitdb_kit nodejs library visit:
https://github.com/endomorphosis/orbitdb_kit/

for fireproof_kit nodejs library visit:
https://github.com/endomorphosis/fireproof_kit

for Faiss KNN index python library visit:
https://github.com/endomorphosis/ipfs_faiss/

for python model manager library visit: 
https://github.com/endomorphosis/ipfs_model_manager/

for nodejs model manager library visit: 
https://github.com/endomorphosis/ipfs_model_manager_js/

for nodejs ipfs huggingface scraper with pinning services visit:
https://github.com/endomorphosis/ipfs_huggingface_scraper/


Author - Benjamin Barber
QA - Kevin De Haan
# IPFS Datasets Python - Example Documentation

This directory contains examples demonstrating the various capabilities of the IPFS Datasets Python library, including the newly integrated IPFS embeddings functionality.

## 🎯 New Integration Features

### Vector Embeddings and Semantic Search
- **Advanced embedding generation** for text, documents, and multimodal content
- **Vector store integration** with Qdrant, Elasticsearch, and FAISS
- **Semantic search** capabilities across large document collections
- **Embedding quality assessment** and validation tools

### MCP (Model Context Protocol) Tools
- **100+ integrated MCP tools** for AI model integration
- **Dataset management** tools for loading, processing, and saving
- **IPFS integration** tools for decentralized storage
- **Vector operations** for embedding and similarity search
- **Workflow automation** and pipeline management tools

### FastAPI Service
- **REST API endpoints** for all major functionality
- **Authentication and authorization** system
- **Health monitoring** and metrics collection
- **Comprehensive documentation** via OpenAPI/Swagger

## Knowledge Graph Extraction and Validation

### knowledge_graph_validation_example.py

This example demonstrates the integrated knowledge graph extraction and validation capabilities, which combine extraction of structured knowledge from text with validation against Wikidata using SPARQL queries.

Key features showcased:

- **Extraction from different sources**:
  - Extracting from plain text
  - Extracting from Wikipedia pages
  - Extracting from multiple documents

- **Integrated validation**:
  - Validation against Wikidata during extraction
  - Validation metrics and coverage analysis
  - Confidence scoring based on validation results

- **Correction suggestions**:
  - Automatic suggestions for fixing inaccurate entities
  - Automatic suggestions for fixing inaccurate relationships
  - Applying corrections to create improved knowledge graphs

- **Entity path analysis**:
  - Finding direct paths between entities
  - Finding multi-hop paths via intermediate entities
  - Analysis of relationship patterns

### Usage

```bash
python knowledge_graph_validation_example.py
```

### Example Output

The example will produce output showing:
- Extracted entities and relationships
- Entity and relationship types
- Validation metrics (coverage scores)
- Path analysis between entities
- Correction suggestions

## Vector Embeddings Examples

### Basic Embedding Generation
```python
from ipfs_datasets_py.embeddings import EmbeddingGenerator

# Initialize embedding generator
embedder = EmbeddingGenerator(model="sentence-transformers/all-MiniLM-L6-v2")

# Generate embeddings for text
texts = ["Hello world", "Machine learning is fascinating"]
embeddings = await embedder.generate_embeddings(texts)
```

### Vector Store Operations
```python
from ipfs_datasets_py.vector_stores import QdrantStore

# Initialize vector store
store = QdrantStore(collection_name="documents")

# Add documents with embeddings
await store.add_documents(
    documents=["Document content..."],
    embeddings=embeddings,
    metadata=[{"source": "example.txt"}]
)

# Perform similarity search
results = await store.search(query_embedding, top_k=5)
```

### MCP Tool Usage
```python
from ipfs_datasets_py.mcp_server.tools.embedding_tools import embedding_generation
from ipfs_datasets_py.mcp_server.tools.vector_tools import create_vector_index

# Generate embeddings via MCP tool
result = await embedding_generation({
    "texts": ["Sample text for embedding"],
    "model": "sentence-transformers/all-MiniLM-L6-v2"
})

# Create vector index
index_result = await create_vector_index({
    "vectors": result["embeddings"],
    "metadata": [{"text": "Sample text for embedding"}]
})
```

### FastAPI Service Integration
```bash
# Start the FastAPI service
python start_fastapi.py

# Access the API documentation
curl http://localhost:8000/docs

# Generate embeddings via API
curl -X POST "http://localhost:8000/embeddings/generate" \
     -H "Content-Type: application/json" \
     -d '{"texts": ["Hello world"], "model": "sentence-transformers/all-MiniLM-L6-v2"}'
```

## Advanced GraphRAG Capabilities

Other examples in this directory demonstrate advanced GraphRAG (Graph Retrieval-Augmented Generation) capabilities that combine vector embeddings with graph structures for enhanced information retrieval.

## Getting Started

To run any of these examples:

1. Ensure the IPFS Datasets Python library is installed with all dependencies:
   ```bash
   pip install -e ..
   pip install -r ../requirements.txt
   ```

2. For vector embedding examples, ensure vector stores are available:
   ```bash
   # Start Qdrant (if using Qdrant examples)
   docker run -p 6333:6333 qdrant/qdrant
   
   # Or start Elasticsearch (if using Elasticsearch examples)
   docker run -p 9200:9200 -e "discovery.type=single-node" elasticsearch:8.11.0
   ```

3. Run the desired example:
   ```bash
   python example_name.py
   ```

4. For MCP tool examples, you can also test via the comprehensive test suite:
   ```bash
   python ../comprehensive_mcp_test.py
   ```

5. For FastAPI examples, start the service first:
   ```bash
   python ../start_fastapi.py
   ```

Each example is thoroughly documented with explanatory comments to help understand the code and concepts. The integration with ipfs_embeddings_py provides powerful semantic search and AI integration capabilities.
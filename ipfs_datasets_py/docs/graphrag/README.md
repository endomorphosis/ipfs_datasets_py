# GraphRAG - Graph-Enhanced Retrieval and Query Optimization

This module provides comprehensive GraphRAG capabilities with advanced query optimization, visualization, and dashboard features.

## Overview

The GraphRAG module implements retrieval-augmented generation workflows, combining vector search with graph-based knowledge retrieval to enhance AI responses with relevant context from your datasets.

## Components

### GraphRAG Query Optimizer (`optimizers/graphrag/query_optimizer.py`)
Intelligent query optimization engine for enhanced retrieval performance.

**Key Features:**
- Query expansion and refinement strategies
- Multi-modal query processing (text, vector, graph)
- Performance optimization for large knowledge bases
- Adaptive filtering and ranking algorithms
- Context-aware result selection

**Main Methods:**
- `optimize_query()` - Enhance queries for better retrieval
- `expand_context()` - Add relevant context to queries
- `rank_results()` - Advanced result ranking and filtering
- `analyze_performance()` - Query performance analysis

### GraphRAG Query Dashboard (`dashboards/rag/query_dashboard.py`)
Interactive web dashboard for GraphRAG query monitoring and optimization.

**Features:**
- Real-time query performance monitoring
- Visual query analysis and debugging
- Interactive result exploration
- Performance metrics and analytics
- Query history and comparison tools

### GraphRAG Query Visualization (`dashboards/rag/query_visualization.py`)
Advanced visualization tools for understanding GraphRAG operations.

**Visualization Types:**
- Query-document relevance heatmaps
- Knowledge graph traversal paths
- Embedding space visualizations
- Performance metrics dashboards
- Result clustering and analysis

### Dashboard Enhancement (`rag_dashboard_enhancement.py`)
Enhanced dashboard features for enterprise GraphRAG deployments.

**Enterprise Features:**
- Multi-user access control
- Advanced analytics and reporting
- Custom visualization templates
- API integration capabilities
- Automated optimization suggestions

## Usage Examples

### Basic GraphRAG Query Optimization
```python
from ipfs_datasets_py.optimizers.graphrag import query_optimizer

optimizer = query_optimizer.RAGQueryOptimizer(
    vector_store=your_vector_store,
    knowledge_graph=your_graph
)

# Optimize a user query
optimized_query = await optimizer.optimize_query(
    query="How does machine learning work?",
    context_limit=5,
    expand_synonyms=True
)

# Retrieve and rank results
results = await optimizer.retrieve_and_rank(
    optimized_query,
    num_results=10
)
```

### Dashboard Integration
```python
from ipfs_datasets_py.dashboards.rag import query_dashboard as graphrag_query_dashboard

# Launch GraphRAG dashboard
dashboard = graphrag_query_dashboard.RAGDashboard(
    port=8080,
    vector_store=your_store,
    enable_real_time=True
)

await dashboard.start()
# Access dashboard at http://localhost:8080
```

### Query Visualization
```python
from ipfs_datasets_py.dashboards.rag import query_visualization as graphrag_query_visualization

visualizer = graphrag_query_visualization.QueryVisualizer()

# Create query analysis visualization
viz = visualizer.create_query_analysis(
    query="Your query here",
    results=retrieval_results,
    show_embeddings=True
)

viz.save("query_analysis.html")
```

## Configuration

### Optimizer Configuration
```python
optimizer_config = {
    "expansion_strategies": ["synonyms", "related_terms"],
    "ranking_algorithm": "hybrid",
    "context_window": 512,
    "performance_threshold": 0.1
}
```

### Dashboard Configuration
```python
dashboard_config = {
    "host": "0.0.0.0",
    "port": 8080,
    "enable_auth": True,
    "real_time_updates": True,
    "cache_results": True
}
```

## Advanced Features

### Multi-Modal GraphRAG
- Text-based retrieval with semantic search
- Graph-based knowledge traversal
- Image and multimedia content integration
- Cross-modal relevance scoring

### Performance Optimization
- Query caching and result memoization
- Parallel retrieval across multiple stores
- Adaptive context selection
- Real-time performance monitoring

### Integration Capabilities
- REST API for external system integration
- WebSocket support for real-time updates
- Plugin architecture for custom processors
- Export capabilities for analysis tools

## Integration

The GraphRAG module works seamlessly with:

- **Vector Stores** - Retrieval backend for similarity search
- **Embeddings** - Query and document embedding generation
- **Search Module** - Enhanced search capabilities
- **Knowledge Graphs** - Graph-based context retrieval
- **LLM Module** - Integration with language models

## Dependencies

- `asyncio` - Asynchronous operations
- `plotly` / `matplotlib` - Visualization capabilities
- `flask` / `fastapi` - Dashboard web framework
- `networkx` - Graph processing
- `numpy` - Numerical operations

## See Also

- [Vector Stores](../vector_stores/README.md) - Storage backends for GraphRAG
- [Embeddings](../embeddings/README.md) - Embedding generation
- [Search Module](../search/README.md) - Search and retrieval
- [LLM Module](../llm/README.md) - Language model integration
- [Query Optimization Guide](../../docs/query_optimization.md) - Detailed optimization strategies
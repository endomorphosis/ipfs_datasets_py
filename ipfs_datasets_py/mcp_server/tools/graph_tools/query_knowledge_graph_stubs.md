# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/graph_tools/query_knowledge_graph.py'

Files last updated: 1748635923.4513795

Stub file last updated: 2025-07-07 01:10:14

## query_knowledge_graph

```python
async def query_knowledge_graph(graph_id: str, query: str, query_type: str = "sparql", max_results: int = 100, include_metadata: bool = True) -> Dict[str, Any]:
    """
    Query a knowledge graph for information.

Args:
    graph_id: ID of the knowledge graph to query
    query: The query string (SPARQL, Cypher, etc.)
    query_type: The type of query ('sparql', 'cypher', 'gremlin', etc.)
    max_results: Maximum number of results to return
    include_metadata: Whether to include metadata in the results

Returns:
    Dict containing query results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

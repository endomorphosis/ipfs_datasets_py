# ipfs_datasets_py/mcp_server/tools/graph_tools/query_knowledge_graph.py
"""
MCP tool for querying knowledge graphs.

This tool handles querying knowledge graphs for information
using the GraphRAGProcessor from graphrag_processor.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger
from ipfs_datasets_py.graphrag_processor import GraphRAGProcessor, MockGraphRAGProcessor


async def query_knowledge_graph(
    graph_id: str,
    query: str,
    query_type: str = "sparql",
    max_results: int = 100,
    include_metadata: bool = True
) -> Dict[str, Any]:
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
    try:
        logger.info(f"Querying knowledge graph {graph_id} with {query_type} query")
        
        # Import the graph processor
        from ipfs_datasets_py.rag_query_optimizer import GraphRAGProcessor
        
        # Create a graph processor instance
        processor = GraphRAGProcessor(graph_id=graph_id)
        
        # Execute the query using the simplified interface
        result = processor.query(query, query_type=query_type, max_results=max_results)
        
        if result["status"] == "success":
            return {
                "status": "success",
                "results": result["results"],
                "graph_id": graph_id,
                "query_type": query_type,
                "num_results": len(result["results"])
            }
        else:
            return result
            
    except Exception as e:
        logger.error(f"Error querying knowledge graph: {e}")
        return {
            "status": "error",
            "message": str(e),
            "graph_id": graph_id,
            "query_type": query_type
        }

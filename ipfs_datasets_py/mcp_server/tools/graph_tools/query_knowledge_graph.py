# ipfs_datasets_py/mcp_server/tools/graph_tools/query_knowledge_graph.py
"""
MCP tool for querying knowledge graphs.

This tool handles querying knowledge graphs for information.
"""
import asyncio
from typing import Dict, Any, Optional, Union, List

from ipfs_datasets_py.mcp_server.logger import logger


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
        processor = GraphRAGProcessor()
        
        # Load the graph
        graph = processor.load_graph(graph_id)
        
        # Execute the query
        if query_type.lower() == "sparql":
            results = processor.execute_sparql(graph, query, limit=max_results)
        elif query_type.lower() == "cypher":
            results = processor.execute_cypher(graph, query, limit=max_results)
        elif query_type.lower() == "gremlin":
            results = processor.execute_gremlin(graph, query, limit=max_results)
        elif query_type.lower() == "semantic":
            results = processor.execute_semantic_query(graph, query, limit=max_results)
        else:
            return {
                "status": "error",
                "message": f"Unsupported query type: {query_type}",
                "graph_id": graph_id
            }
            
        # Format the results
        formatted_results = []
        for result in results:
            if include_metadata:
                formatted_results.append(result)
            else:
                # Filter out metadata fields
                if isinstance(result, dict):
                    formatted_results.append({
                        k: v for k, v in result.items() 
                        if not k.startswith("_") and k != "metadata"
                    })
                else:
                    formatted_results.append(result)
            
        # Return the query results
        return {
            "status": "success",
            "graph_id": graph_id,
            "query_type": query_type,
            "num_results": len(formatted_results),
            "results": formatted_results[:max_results]
        }
    except Exception as e:
        logger.error(f"Error querying knowledge graph: {e}")
        return {
            "status": "error",
            "message": str(e),
            "graph_id": graph_id,
            "query_type": query_type
        }

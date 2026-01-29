"""
PDF Knowledge Graph Query Tool

MCP tool for querying knowledge graphs constructed from PDF documents.
Provides direct access to the knowledge graph structure, entities, relationships,
and graph traversal capabilities built by the GraphRAG processing pipeline.
"""

import anyio
import logging
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)

async def pdf_query_knowledge_graph(
    graph_id: str,
    query: str,
    query_type: str = "sparql",
    max_results: int = 100,
    include_metadata: bool = True,
    return_subgraph: bool = False
) -> Dict[str, Any]:
    """
    Query a knowledge graph constructed from PDF documents.
    
    This tool provides direct access to the knowledge graph structure created by
    the PDF processing pipeline, allowing for complex graph queries, entity lookups,
    relationship traversal, and subgraph extraction.
    
    Args:
        graph_id: ID of the knowledge graph to query (typically the document ID or collection ID)
        query: The query string (SPARQL, Cypher, natural language, or entity name)
        query_type: Type of query to perform:
            - "sparql": SPARQL query against the RDF graph
            - "cypher": Cypher query for graph traversal
            - "entity": Query for specific entity by name or type
            - "relationship": Query for specific relationship types
            - "natural_language": Natural language query translated to graph query
        max_results: Maximum number of results to return
        include_metadata: Whether to include entity/relationship metadata in results
        return_subgraph: Whether to return a subgraph structure instead of flat results
        
    Returns:
        Dict containing:
        - status: "success" or "error"
        - results: List of query results (entities, relationships, or query matches)
        - entities: List of entity objects with properties
        - relationships: List of relationship objects connecting entities
        - subgraph: Optional subgraph structure if return_subgraph is True
        - graph_statistics: Statistics about the queried graph
        - query_metadata: Information about query processing
        - message: Success/error message
    """
    try:
        # Import graph processing components
        from ipfs_datasets_py.pdf_processing import GraphRAGIntegrator, QueryEngine
        from ipfs_datasets_py.monitoring import track_operation
        
        # Validate query type
        valid_query_types = ["sparql", "cypher", "entity", "relationship", "natural_language"]
        if query_type not in valid_query_types:
            return {
                "status": "error",
                "message": f"Invalid query type. Must be one of: {valid_query_types}"
            }
            
        # Validate parameters
        if not query.strip():
            return {
                "status": "error",
                "message": "Query cannot be empty"
            }
            
        if not graph_id.strip():
            return {
                "status": "error",
                "message": "Graph ID cannot be empty"
            }
            
        if max_results <= 0:
            return {
                "status": "error",
                "message": "max_results must be greater than 0"
            }
        
        # Track the query operation
        with track_operation("pdf_query_knowledge_graph"):
            # Initialize the GraphRAG integrator
            integrator = GraphRAGIntegrator(graph_id=graph_id)
            
            # Execute query based on type
            if query_type == "sparql":
                # Execute SPARQL query
                result = await integrator.query_sparql(
                    query=query,
                    max_results=max_results
                )
            elif query_type == "cypher":
                # Execute Cypher query (for property graph)
                result = await integrator.query_cypher(
                    query=query,
                    max_results=max_results
                )
            elif query_type == "entity":
                # Query for specific entities
                result = await integrator.find_entities(
                    entity_query=query,
                    max_results=max_results,
                    include_metadata=include_metadata
                )
            elif query_type == "relationship":
                # Query for specific relationships
                result = await integrator.find_relationships(
                    relationship_query=query,
                    max_results=max_results,
                    include_metadata=include_metadata
                )
            else:  # natural_language
                # Translate natural language to graph query
                query_engine = QueryEngine()
                result = await query_engine.natural_language_to_graph_query(
                    query=query,
                    graph_id=graph_id,
                    max_results=max_results
                )
            
            # Format the results
            entities = []
            relationships = []
            
            if "entities" in result:
                for entity in result["entities"]:
                    entity_data = {
                        "id": entity.get("id"),
                        "type": entity.get("type"),
                        "name": entity.get("name"),
                        "properties": entity.get("properties", {}) if include_metadata else {}
                    }
                    entities.append(entity_data)
            
            if "relationships" in result:
                for rel in result["relationships"]:
                    rel_data = {
                        "id": rel.get("id"),
                        "type": rel.get("type"),
                        "source": rel.get("source"),
                        "target": rel.get("target"),
                        "properties": rel.get("properties", {}) if include_metadata else {}
                    }
                    relationships.append(rel_data)
            
            # Build subgraph if requested
            subgraph = None
            if return_subgraph:
                subgraph = {
                    "nodes": entities,
                    "edges": relationships,
                    "metadata": {
                        "graph_id": graph_id,
                        "node_count": len(entities),
                        "edge_count": len(relationships)
                    }
                }
            
            # Get graph statistics
            graph_statistics = {
                "total_entities": result.get("total_entities", len(entities)),
                "total_relationships": result.get("total_relationships", len(relationships)),
                "entity_types": result.get("entity_types", []),
                "relationship_types": result.get("relationship_types", [])
            }
            
            return {
                "status": "success",
                "results": result.get("results", []),
                "entities": entities,
                "relationships": relationships,
                "subgraph": subgraph,
                "graph_statistics": graph_statistics,
                "query_metadata": {
                    "query_type": query_type,
                    "graph_id": graph_id,
                    "results_count": len(result.get("results", [])),
                    "entities_found": len(entities),
                    "relationships_found": len(relationships),
                    "processing_time": result.get("processing_time", 0)
                },
                "message": f"Successfully executed {query_type} query on graph {graph_id}"
            }
            
    except ImportError as e:
        logger.error(f"Graph processing dependencies not available: {e}")
        return {
            "status": "error",
            "message": f"Graph processing dependencies not available: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error querying knowledge graph: {e}")
        return {
            "status": "error",
            "message": f"Failed to query knowledge graph: {str(e)}"
        }

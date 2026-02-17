"""
Legal GraphRAG Integration MCP Tool.

This tool exposes the LegalGraphRAG system which bridges GraphRAG infrastructure
for legal document analysis with entity/relationship extraction, semantic search,
and graph visualization.

Core implementation: ipfs_datasets_py.processors.legal_scrapers.legal_graphrag
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def create_legal_knowledge_graph(
    documents: List[Dict[str, Any]],
    extract_entities: bool = True,
    extract_relationships: bool = True,
    entity_types: Optional[List[str]] = None,
    relationship_types: Optional[List[str]] = None,
    min_confidence: float = 0.6
) -> Dict[str, Any]:
    """
    Create a legal knowledge graph from documents using GraphRAG.
    
    This is a thin wrapper around LegalGraphRAG from the processors module.
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.legal_graphrag
    
    Features:
    - Entity extraction (cases, statutes, regulations, parties, concepts)
    - Relationship extraction (cites, references, overrules, extends)
    - Semantic search over graph structure
    - Subgraph extraction for specific queries
    - Graph visualization export
    
    Args:
        documents: List of documents (each with 'id', 'title', 'content')
        extract_entities: Extract legal entities from documents (default: True)
        extract_relationships: Extract relationships between entities (default: True)
        entity_types: Filter entity types ["case", "statute", "regulation", "party", "concept"]
        relationship_types: Filter relationship types ["cites", "references", "overrules", "extends"]
        min_confidence: Minimum confidence score for extraction (0.0-1.0, default: 0.6)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - graph_id: Unique identifier for the knowledge graph
        - entities: List of extracted entities
        - relationships: List of extracted relationships
        - graph_statistics: Statistics about the graph (nodes, edges, density)
        - total_documents: Number of documents processed
        - total_entities: Number of entities extracted
        - total_relationships: Number of relationships extracted
        - extraction_metadata: Details about extraction process
    
    Example:
        >>> documents = [
        ...     {"id": "1", "title": "Case A", "content": "..."},
        ...     {"id": "2", "title": "Case B", "content": "..."}
        ... ]
        >>> graph = await create_legal_knowledge_graph(
        ...     documents=documents,
        ...     entity_types=["case", "statute"],
        ...     min_confidence=0.7
        ... )
        >>> print(f"Created graph with {graph['total_entities']} entities")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalGraphRAG
        
        # Validate input
        if not documents or not isinstance(documents, list):
            return {
                "status": "error",
                "message": "Documents must be a non-empty list"
            }
        
        # Validate each document has required fields
        for idx, doc in enumerate(documents):
            if not isinstance(doc, dict):
                return {
                    "status": "error",
                    "message": f"Document at index {idx} must be a dictionary"
                }
            if "content" not in doc:
                return {
                    "status": "error",
                    "message": f"Document at index {idx} missing required field 'content'"
                }
        
        if not 0 <= min_confidence <= 1:
            return {
                "status": "error",
                "message": "min_confidence must be between 0.0 and 1.0"
            }
        
        if entity_types:
            valid_types = ["case", "statute", "regulation", "party", "concept", "jurisdiction", "date"]
            for etype in entity_types:
                if etype not in valid_types:
                    return {
                        "status": "error",
                        "message": f"Invalid entity type '{etype}'. Must be one of: {valid_types}"
                    }
        
        if relationship_types:
            valid_types = ["cites", "references", "overrules", "extends", "modifies", "relates_to"]
            for rtype in relationship_types:
                if rtype not in valid_types:
                    return {
                        "status": "error",
                        "message": f"Invalid relationship type '{rtype}'. Must be one of: {valid_types}"
                    }
        
        # Initialize Legal GraphRAG
        graphrag_config = {
            "extract_entities": extract_entities,
            "extract_relationships": extract_relationships,
            "min_confidence": min_confidence
        }
        
        if entity_types:
            graphrag_config["entity_types"] = entity_types
        if relationship_types:
            graphrag_config["relationship_types"] = relationship_types
        
        legal_graphrag = LegalGraphRAG(**graphrag_config)
        
        # Create knowledge graph
        graph_result = legal_graphrag.create_graph_from_documents(documents)
        
        # Extract entities and relationships
        entities = graph_result.get("entities", [])
        relationships = graph_result.get("relationships", [])
        
        # Calculate graph statistics
        graph_stats = legal_graphrag.get_graph_statistics(
            entities=entities,
            relationships=relationships
        )
        
        return {
            "status": "success",
            "graph_id": graph_result.get("graph_id"),
            "entities": entities,
            "relationships": relationships,
            "graph_statistics": graph_stats,
            "total_documents": len(documents),
            "total_entities": len(entities),
            "total_relationships": len(relationships),
            "extraction_metadata": graphrag_config,
            "mcp_tool": "create_legal_knowledge_graph"
        }
        
    except ImportError as e:
        logger.error(f"Import error in create_legal_knowledge_graph: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in create_legal_knowledge_graph MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "total_documents": len(documents) if documents else 0
        }


async def search_legal_graph(
    graph_id: str,
    query: str,
    search_type: str = "semantic",
    max_results: int = 10,
    include_subgraph: bool = False,
    hops: int = 2
) -> Dict[str, Any]:
    """
    Search a legal knowledge graph using various methods.
    
    Search types:
    - semantic: Semantic similarity search over entities
    - keyword: Keyword-based search
    - structural: Graph structure-based search (e.g., find all cases citing X)
    - hybrid: Combined semantic and structural search
    
    Args:
        graph_id: ID of the knowledge graph to search
        query: Search query (text or entity ID)
        search_type: Type of search - "semantic", "keyword", "structural", or "hybrid"
        max_results: Maximum number of results to return (default: 10)
        include_subgraph: Include subgraph around results (default: False)
        hops: Number of hops for subgraph extraction (default: 2)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - results: List of matching entities/nodes
        - subgraph: Subgraph around results (if include_subgraph=True)
        - total_results: Number of results found
        - search_metadata: Details about search process
    
    Example:
        >>> results = await search_legal_graph(
        ...     graph_id="legal_kg_123",
        ...     query="EPA regulations on clean water",
        ...     search_type="semantic",
        ...     include_subgraph=True
        ... )
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalGraphRAG
        
        if not graph_id:
            return {
                "status": "error",
                "message": "graph_id is required"
            }
        
        if not query:
            return {
                "status": "error",
                "message": "query is required"
            }
        
        if search_type not in ["semantic", "keyword", "structural", "hybrid"]:
            return {
                "status": "error",
                "message": "search_type must be 'semantic', 'keyword', 'structural', or 'hybrid'"
            }
        
        if max_results < 1 or max_results > 100:
            return {
                "status": "error",
                "message": "max_results must be between 1 and 100"
            }
        
        if hops < 1 or hops > 5:
            return {
                "status": "error",
                "message": "hops must be between 1 and 5"
            }
        
        # Initialize Legal GraphRAG
        legal_graphrag = LegalGraphRAG()
        
        # Load graph
        graph = legal_graphrag.load_graph(graph_id)
        
        # Search graph
        search_results = legal_graphrag.search_graph(
            graph=graph,
            query=query,
            search_type=search_type,
            max_results=max_results
        )
        
        # Extract subgraph if requested
        subgraph = None
        if include_subgraph and search_results:
            result_nodes = [r.get("id") for r in search_results]
            subgraph = legal_graphrag.extract_subgraph(
                graph=graph,
                seed_nodes=result_nodes,
                hops=hops
            )
        
        return {
            "status": "success",
            "results": search_results,
            "subgraph": subgraph,
            "total_results": len(search_results),
            "search_metadata": {
                "graph_id": graph_id,
                "query": query,
                "search_type": search_type,
                "include_subgraph": include_subgraph,
                "hops": hops
            },
            "mcp_tool": "search_legal_graph"
        }
        
    except Exception as e:
        logger.error(f"Error in search_legal_graph MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "graph_id": graph_id,
            "query": query
        }


async def visualize_legal_graph(
    graph_id: str,
    layout: str = "force",
    format: str = "html",
    highlight_entities: Optional[List[str]] = None,
    output_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Visualize a legal knowledge graph.
    
    Layout options:
    - force: Force-directed layout
    - hierarchical: Hierarchical tree layout
    - circular: Circular layout
    - community: Community detection layout
    
    Export formats:
    - html: Interactive HTML visualization
    - png: Static PNG image
    - svg: Scalable SVG image
    - json: Graph data in JSON format
    
    Args:
        graph_id: ID of the knowledge graph to visualize
        layout: Layout algorithm (default: "force")
        format: Export format (default: "html")
        highlight_entities: List of entity IDs to highlight
        output_path: Optional file path to save visualization
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - visualization_data: Visualization data (if output_path not provided)
        - output_path: Path where file was saved (if output_path provided)
        - format: Export format used
    
    Example:
        >>> viz = await visualize_legal_graph(
        ...     graph_id="legal_kg_123",
        ...     layout="force",
        ...     format="html",
        ...     output_path="/tmp/graph.html"
        ... )
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import LegalGraphRAG
        
        if not graph_id:
            return {
                "status": "error",
                "message": "graph_id is required"
            }
        
        if layout not in ["force", "hierarchical", "circular", "community"]:
            return {
                "status": "error",
                "message": "layout must be 'force', 'hierarchical', 'circular', or 'community'"
            }
        
        if format not in ["html", "png", "svg", "json"]:
            return {
                "status": "error",
                "message": "format must be 'html', 'png', 'svg', or 'json'"
            }
        
        # Initialize Legal GraphRAG
        legal_graphrag = LegalGraphRAG()
        
        # Load graph
        graph = legal_graphrag.load_graph(graph_id)
        
        # Create visualization
        viz_data = legal_graphrag.visualize_graph(
            graph=graph,
            layout=layout,
            format=format,
            highlight_entities=highlight_entities,
            output_path=output_path
        )
        
        result = {
            "status": "success",
            "format": format,
            "layout": layout
        }
        
        if output_path:
            result["output_path"] = output_path
            result["message"] = f"Graph visualization saved to {output_path}"
        else:
            result["visualization_data"] = viz_data
            result["message"] = "Graph visualization created successfully"
        
        return result
        
    except Exception as e:
        logger.error(f"Error in visualize_legal_graph MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "graph_id": graph_id
        }

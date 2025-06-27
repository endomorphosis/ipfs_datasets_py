"""
PDF Corpus Query Tool

MCP tool for querying PDF documents ingested into the GraphRAG system
using advanced query capabilities including semantic search, entity queries,
relationship traversal, and cross-document analysis.
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)

async def pdf_query_corpus(
    query: str,
    query_type: str = "hybrid",
    max_documents: int = 10,
    document_filters: Optional[Dict[str, Any]] = None,
    enable_reasoning: bool = True,
    include_sources: bool = True,
    confidence_threshold: float = 0.7
) -> Dict[str, Any]:
    """
    Query the PDF corpus using GraphRAG capabilities for comprehensive document analysis.
    
    This tool provides multiple query strategies:
    - Semantic search across document content
    - Entity-based queries for specific entities and relationships
    - Cross-document relationship traversal
    - Hybrid queries combining multiple approaches
    - Advanced reasoning with LLM integration
    
    Args:
        query: Natural language query or structured query
        query_type: Type of query ("semantic", "entity", "relationship", "hybrid", "cross_document")
        max_documents: Maximum number of documents to include in results
        document_filters: Optional filters (author, date_range, document_type, etc.)
        enable_reasoning: Enable LLM-based reasoning over results
        include_sources: Include source document information in results
        confidence_threshold: Minimum confidence score for results
        
    Returns:
        Dict containing:
        - status: "success" or "error"
        - answer: Generated answer or analysis
        - confidence_score: Overall confidence in the answer
        - source_documents: List of source documents with relevance scores
        - entities_found: Relevant entities discovered
        - relationships_found: Relevant relationships discovered
        - cross_document_connections: Cross-document relationships
        - query_analysis: Analysis of the query and processing approach
        - processing_time: Query processing time
        - message: Success/error message
    """
    try:
        # Import query processing components
        from ipfs_datasets_py.pdf_processing import QueryEngine
        from ipfs_datasets_py.graphrag import GraphRAGQueryOptimizer
        from ipfs_datasets_py.monitoring import track_operation
        
        # Initialize query engine
        query_engine = QueryEngine()
        
        # Validate query type
        valid_query_types = ["semantic", "entity", "relationship", "hybrid", "cross_document"]
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
            
        if max_documents <= 0:
            return {
                "status": "error",
                "message": "max_documents must be greater than 0"
            }
            
        if not 0.0 <= confidence_threshold <= 1.0:
            return {
                "status": "error",
                "message": "confidence_threshold must be between 0.0 and 1.0"
            }
        
        # Track the query operation
        with track_operation("pdf_query_corpus"):
            # Execute the query based on type
            if query_type == "semantic":
                result = await query_engine.semantic_search(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold
                )
            elif query_type == "entity":
                result = await query_engine.entity_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold
                )
            elif query_type == "relationship":
                result = await query_engine.relationship_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold
                )
            elif query_type == "cross_document":
                result = await query_engine.cross_document_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    confidence_threshold=confidence_threshold
                )
            else:  # hybrid
                result = await query_engine.hybrid_query(
                    query=query,
                    max_results=max_documents,
                    filters=document_filters,
                    enable_reasoning=enable_reasoning,
                    confidence_threshold=confidence_threshold
                )
            
            # Process and format results
            source_documents = []
            if include_sources and "documents" in result:
                for doc in result["documents"]:
                    source_documents.append({
                        "document_id": doc.get("document_id"),
                        "title": doc.get("title", "Unknown"),
                        "relevance_score": doc.get("score", 0.0),
                        "page_numbers": doc.get("pages", []),
                        "excerpt": doc.get("excerpt", ""),
                        "metadata": doc.get("metadata", {})
                    })
            
            # Extract entities and relationships
            entities_found = result.get("entities", [])
            relationships_found = result.get("relationships", [])
            cross_document_connections = result.get("cross_document_relationships", [])
            
            return {
                "status": "success",
                "answer": result.get("answer", ""),
                "confidence_score": result.get("confidence", 0.0),
                "source_documents": source_documents,
                "entities_found": entities_found,
                "relationships_found": relationships_found,
                "cross_document_connections": cross_document_connections,
                "query_analysis": {
                    "query_type": query_type,
                    "query_complexity": result.get("query_complexity", "medium"),
                    "processing_strategy": result.get("strategy", "standard"),
                    "documents_searched": result.get("documents_searched", 0),
                    "total_matches": len(source_documents)
                },
                "processing_time": result.get("processing_time", 0),
                "message": f"Successfully processed {query_type} query with {len(source_documents)} relevant documents found"
            }
            
    except ImportError as e:
        logger.error(f"Query processing dependencies not available: {e}")
        return {
            "status": "error",
            "message": f"Query processing dependencies not available: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error querying PDF corpus: {e}")
        return {
            "status": "error",
            "message": f"Failed to query PDF corpus: {str(e)}"
        }

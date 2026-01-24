"""
PDF Relationship Analysis Tool

MCP tool for analyzing and discovering relationships within and between
PDF documents in the GraphRAG system.
"""

import anyio
import logging
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)

async def pdf_analyze_relationships(
    document_id: str,
    analysis_type: str = "comprehensive",
    include_cross_document: bool = True,
    relationship_types: Optional[List[str]] = None,
    min_confidence: float = 0.6,
    max_relationships: int = 100
) -> Dict[str, Any]:
    """
    Analyze relationships for a specific PDF document or across the corpus.
    
    This tool provides comprehensive relationship analysis including:
    - Entity co-occurrence analysis
    - Semantic relationship discovery
    - Citation and reference networks
    - Cross-document entity connections
    - Thematic relationship clustering
    
    Args:
        document_id: ID of the document to analyze (or "all" for corpus-wide)
        analysis_type: Type of analysis ("entities", "citations", "themes", "comprehensive")
        include_cross_document: Include relationships with other documents
        relationship_types: Specific relationship types to focus on
        min_confidence: Minimum confidence threshold for relationships
        max_relationships: Maximum number of relationships to return
        
    Returns:
        Dict containing:
        - status: "success" or "error"
        - document_info: Information about the analyzed document(s)
        - entity_relationships: Entity-based relationships found
        - citation_network: Citation and reference relationships
        - thematic_relationships: Thematic connections
        - cross_document_relationships: Relationships with other documents
        - relationship_graph: Graph representation of relationships
        - analysis_summary: Summary statistics and insights
        - processing_time: Analysis processing time
        - message: Success/error message
    """
    try:
        # Import relationship analysis components
        from ipfs_datasets_py.pdf_processing import GraphRAGIntegrator
        from ipfs_datasets_py.graphrag import RelationshipAnalyzer
        from ipfs_datasets_py.monitoring import track_operation
        
        # Initialize components
        integrator = GraphRAGIntegrator()
        analyzer = RelationshipAnalyzer()
        
        # Validate parameters
        valid_analysis_types = ["entities", "citations", "themes", "comprehensive"]
        if analysis_type not in valid_analysis_types:
            return {
                "status": "error",
                "message": f"Invalid analysis type. Must be one of: {valid_analysis_types}"
            }
            
        if not 0.0 <= min_confidence <= 1.0:
            return {
                "status": "error",
                "message": "min_confidence must be between 0.0 and 1.0"
            }
            
        if max_relationships <= 0:
            return {
                "status": "error",
                "message": "max_relationships must be greater than 0"
            }
        
        # Track the analysis operation
        with track_operation("pdf_analyze_relationships"):
            # Get document information
            if document_id == "all":
                document_info = {"type": "corpus_wide", "document_count": "all"}
                documents = await integrator.get_all_documents()
            else:
                document_info = await integrator.get_document_info(document_id)
                if not document_info:
                    return {
                        "status": "error",
                        "message": f"Document not found: {document_id}"
                    }
                documents = [document_info]
            
            # Perform relationship analysis based on type
            results = {}
            
            if analysis_type in ["entities", "comprehensive"]:
                # Entity relationship analysis
                entity_results = await analyzer.analyze_entity_relationships(
                    documents=documents,
                    min_confidence=min_confidence,
                    max_relationships=max_relationships,
                    relationship_types=relationship_types
                )
                results["entity_relationships"] = entity_results
            
            if analysis_type in ["citations", "comprehensive"]:
                # Citation network analysis
                citation_results = await analyzer.analyze_citation_network(
                    documents=documents,
                    include_cross_document=include_cross_document,
                    min_confidence=min_confidence
                )
                results["citation_network"] = citation_results
            
            if analysis_type in ["themes", "comprehensive"]:
                # Thematic relationship analysis
                theme_results = await analyzer.analyze_thematic_relationships(
                    documents=documents,
                    include_cross_document=include_cross_document,
                    min_confidence=min_confidence
                )
                results["thematic_relationships"] = theme_results
            
            # Cross-document analysis if requested
            cross_doc_relationships = []
            if include_cross_document and document_id != "all":
                cross_doc_results = await analyzer.find_cross_document_relationships(
                    source_document_id=document_id,
                    min_confidence=min_confidence,
                    max_relationships=max_relationships
                )
                cross_doc_relationships = cross_doc_results.get("relationships", [])
            
            # Generate relationship graph
            relationship_graph = await analyzer.build_relationship_graph(
                results,
                include_cross_document=include_cross_document
            )
            
            # Generate analysis summary
            analysis_summary = {
                "total_relationships": sum(len(r) for r in results.values() if isinstance(r, list)),
                "entity_count": len(results.get("entity_relationships", {}).get("entities", [])),
                "citation_count": len(results.get("citation_network", {}).get("citations", [])),
                "theme_count": len(results.get("thematic_relationships", {}).get("themes", [])),
                "cross_document_count": len(cross_doc_relationships),
                "analysis_type": analysis_type,
                "confidence_range": {
                    "min": min_confidence,
                    "max": max(r.get("confidence", 0) for r in 
                              sum([results.get(k, {}).get("relationships", []) 
                                   for k in results.keys()], []) or [{"confidence": 0}])
                }
            }
            
            return {
                "status": "success",
                "document_info": document_info,
                "entity_relationships": results.get("entity_relationships", {}),
                "citation_network": results.get("citation_network", {}),
                "thematic_relationships": results.get("thematic_relationships", {}),
                "cross_document_relationships": cross_doc_relationships,
                "relationship_graph": relationship_graph,
                "analysis_summary": analysis_summary,
                "processing_time": sum(r.get("processing_time", 0) for r in results.values() if isinstance(r, dict)),
                "message": f"Successfully analyzed {analysis_type} relationships for document(s). Found {analysis_summary['total_relationships']} relationships."
            }
            
    except ImportError as e:
        logger.error(f"Relationship analysis dependencies not available: {e}")
        return {
            "status": "error",
            "message": f"Relationship analysis dependencies not available: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error analyzing relationships: {e}")
        return {
            "status": "error",
            "message": f"Failed to analyze relationships: {str(e)}"
        }

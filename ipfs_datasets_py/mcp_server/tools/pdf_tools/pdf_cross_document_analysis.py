"""
PDF Cross-Document Analysis Tool

MCP tool for performing comprehensive cross-document analysis across
a corpus of PDF documents with entity linking, thematic analysis,
and knowledge graph discovery.
"""

import anyio
import logging
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)

async def pdf_cross_document_analysis(
    document_ids: Optional[List[str]] = None,
    analysis_types: List[str] = ["entities", "themes", "citations"],
    similarity_threshold: float = 0.75,
    max_connections: int = 100,
    temporal_analysis: bool = True,
    include_visualizations: bool = False,
    output_format: str = "detailed"
) -> Dict[str, Any]:
    """
    Perform comprehensive cross-document analysis across PDF corpus with
    entity linking, thematic analysis, citation networks, and knowledge discovery.
    
    This tool provides advanced cross-document analysis including:
    - Entity co-reference resolution across documents
    - Thematic similarity and clustering analysis
    - Citation and reference network construction
    - Temporal evolution tracking of concepts
    - Knowledge graph relationship discovery
    - Document influence and authority analysis
    
    Args:
        document_ids: Specific document IDs to analyze (None for entire corpus)
        analysis_types: Types of analysis to perform
        similarity_threshold: Minimum similarity for cross-document connections
        max_connections: Maximum number of connections to return
        temporal_analysis: Include temporal evolution analysis
        include_visualizations: Generate visualization data
        output_format: Output detail level ("summary", "detailed", "full")
        
    Returns:
        Dict containing:
        - status: "success" or "error"
        - corpus_info: Information about the analyzed corpus
        - entity_connections: Cross-document entity connections
        - thematic_clusters: Thematic clusters and relationships
        - citation_networks: Citation and reference networks
        - temporal_evolution: Temporal analysis of concepts and themes
        - influence_analysis: Document influence and authority scores
        - knowledge_discoveries: Novel relationships discovered
        - visualization_data: Data for visualization (if requested)
        - analysis_summary: Summary statistics and insights
        - processing_time: Analysis processing time
        - message: Success/error message
    """
    try:
        # Import cross-document analysis components
        from ipfs_datasets_py.pdf_processing import GraphRAGIntegrator
        from ipfs_datasets_py.analysis import CrossDocumentAnalyzer, TemporalAnalyzer
        from ipfs_datasets_py.visualization import NetworkVisualizer
        from ipfs_datasets_py.monitoring import track_operation
        
        # Validate inputs
        valid_analysis_types = ["entities", "themes", "citations", "temporal", "influence", "clustering"]
        invalid_types = [t for t in analysis_types if t not in valid_analysis_types]
        if invalid_types:
            return {
                "status": "error",
                "message": f"Invalid analysis types: {invalid_types}. Valid types: {valid_analysis_types}"
            }
            
        if not 0.0 <= similarity_threshold <= 1.0:
            return {
                "status": "error",
                "message": "similarity_threshold must be between 0.0 and 1.0"
            }
            
        if max_connections <= 0:
            return {
                "status": "error",
                "message": "max_connections must be greater than 0"
            }
            
        valid_output_formats = ["summary", "detailed", "full"]
        if output_format not in valid_output_formats:
            return {
                "status": "error",
                "message": f"Invalid output_format. Must be one of: {valid_output_formats}"
            }
        
        # Initialize components
        integrator = GraphRAGIntegrator()
        analyzer = CrossDocumentAnalyzer()
        
        # Track the analysis operation
        with track_operation("pdf_cross_document_analysis"):
            # Get document corpus
            if document_ids:
                documents = []
                for doc_id in document_ids:
                    doc_info = await integrator.get_document_info(doc_id)
                    if doc_info:
                        documents.append(doc_info)
                    else:
                        logger.warning(f"Document not found: {doc_id}")
                
                if not documents:
                    return {
                        "status": "error",
                        "message": "No valid documents found"
                    }
            else:
                # Analyze entire corpus
                documents = await integrator.get_all_documents()
                if not documents:
                    return {
                        "status": "error",
                        "message": "No documents found in corpus"
                    }
            
            corpus_info = {
                "total_documents": len(documents),
                "date_range": {
                    "earliest": min(d.get("date", "") for d in documents if d.get("date")),
                    "latest": max(d.get("date", "") for d in documents if d.get("date"))
                },
                "document_types": list(set(d.get("type", "unknown") for d in documents)),
                "total_pages": sum(d.get("pages", 0) for d in documents)
            }
            
            # Initialize results dictionary
            analysis_results = {
                "entity_connections": [],
                "thematic_clusters": [],
                "citation_networks": [],
                "temporal_evolution": {},
                "influence_analysis": {},
                "knowledge_discoveries": []
            }
            
            # Perform entity connection analysis
            if "entities" in analysis_types:
                entity_result = await analyzer.analyze_entity_connections(
                    documents=documents,
                    similarity_threshold=similarity_threshold,
                    max_connections=max_connections
                )
                analysis_results["entity_connections"] = entity_result.get("connections", [])
            
            # Perform thematic analysis
            if "themes" in analysis_types:
                thematic_result = await analyzer.analyze_thematic_relationships(
                    documents=documents,
                    similarity_threshold=similarity_threshold,
                    clustering_method="hierarchical"
                )
                analysis_results["thematic_clusters"] = thematic_result.get("clusters", [])
            
            # Perform citation network analysis
            if "citations" in analysis_types:
                citation_result = await analyzer.build_citation_networks(
                    documents=documents,
                    include_external_citations=True
                )
                analysis_results["citation_networks"] = citation_result.get("networks", [])
            
            # Perform temporal analysis if requested
            if temporal_analysis and ("temporal" in analysis_types or "full" in analysis_types):
                temporal_analyzer = TemporalAnalyzer()
                temporal_result = await temporal_analyzer.analyze_temporal_evolution(
                    documents=documents,
                    time_window="yearly",
                    track_entities=True,
                    track_themes=True
                )
                analysis_results["temporal_evolution"] = temporal_result
            
            # Perform influence analysis
            if "influence" in analysis_types:
                influence_result = await analyzer.calculate_document_influence(
                    documents=documents,
                    citation_networks=analysis_results.get("citation_networks", []),
                    entity_connections=analysis_results.get("entity_connections", [])
                )
                analysis_results["influence_analysis"] = influence_result
            
            # Discover novel knowledge connections
            if "clustering" in analysis_types or output_format == "full":
                discovery_result = await analyzer.discover_knowledge_connections(
                    documents=documents,
                    existing_connections=analysis_results["entity_connections"],
                    novelty_threshold=0.8
                )
                analysis_results["knowledge_discoveries"] = discovery_result.get("discoveries", [])
            
            # Generate visualizations if requested
            visualization_data = {}
            if include_visualizations:
                visualizer = NetworkVisualizer()
                
                # Entity network visualization
                if analysis_results["entity_connections"]:
                    entity_viz = await visualizer.create_entity_network(
                        connections=analysis_results["entity_connections"],
                        documents=documents
                    )
                    visualization_data["entity_network"] = entity_viz
                
                # Thematic cluster visualization
                if analysis_results["thematic_clusters"]:
                    theme_viz = await visualizer.create_thematic_map(
                        clusters=analysis_results["thematic_clusters"],
                        documents=documents
                    )
                    visualization_data["thematic_map"] = theme_viz
                
                # Citation network visualization
                if analysis_results["citation_networks"]:
                    citation_viz = await visualizer.create_citation_graph(
                        networks=analysis_results["citation_networks"]
                    )
                    visualization_data["citation_graph"] = citation_viz
            
            # Generate analysis summary
            analysis_summary = {
                "documents_analyzed": len(documents),
                "total_entity_connections": len(analysis_results["entity_connections"]),
                "thematic_clusters_found": len(analysis_results["thematic_clusters"]),
                "citation_relationships": len(analysis_results["citation_networks"]),
                "novel_discoveries": len(analysis_results["knowledge_discoveries"]),
                "analysis_types_performed": analysis_types,
                "similarity_threshold_used": similarity_threshold,
                "temporal_span": corpus_info["date_range"] if temporal_analysis else None,
                "most_influential_documents": [],
                "key_themes": [],
                "strongest_connections": []
            }
            
            # Extract key insights for summary
            if analysis_results["influence_analysis"]:
                top_docs = sorted(
                    analysis_results["influence_analysis"].get("document_scores", []),
                    key=lambda x: x.get("influence_score", 0),
                    reverse=True
                )[:5]
                analysis_summary["most_influential_documents"] = [
                    {"document_id": d["document_id"], "title": d.get("title", ""), "score": d["influence_score"]}
                    for d in top_docs
                ]
            
            if analysis_results["thematic_clusters"]:
                analysis_summary["key_themes"] = [
                    {"theme": c.get("theme", ""), "document_count": len(c.get("documents", []))}
                    for c in analysis_results["thematic_clusters"][:10]
                ]
            
            if analysis_results["entity_connections"]:
                top_connections = sorted(
                    analysis_results["entity_connections"],
                    key=lambda x: x.get("strength", 0),
                    reverse=True
                )[:10]
                analysis_summary["strongest_connections"] = [
                    {"entities": c.get("entities", []), "strength": c.get("strength", 0)}
                    for c in top_connections
                ]
            
            # Format output based on requested detail level
            if output_format == "summary":
                return {
                    "status": "success",
                    "corpus_info": corpus_info,
                    "analysis_summary": analysis_summary,
                    "processing_time": sum(
                        r.get("processing_time", 0) for r in analysis_results.values() 
                        if isinstance(r, dict)
                    ),
                    "message": f"Successfully analyzed {len(documents)} documents with {len(analysis_types)} analysis types"
                }
            elif output_format == "detailed":
                return {
                    "status": "success",
                    "corpus_info": corpus_info,
                    "entity_connections": analysis_results["entity_connections"][:50],  # Limit for readability
                    "thematic_clusters": analysis_results["thematic_clusters"],
                    "citation_networks": analysis_results["citation_networks"],
                    "influence_analysis": analysis_results["influence_analysis"],
                    "analysis_summary": analysis_summary,
                    "visualization_data": visualization_data if include_visualizations else {},
                    "processing_time": sum(
                        r.get("processing_time", 0) for r in analysis_results.values() 
                        if isinstance(r, dict)
                    ),
                    "message": f"Successfully performed cross-document analysis on {len(documents)} documents"
                }
            else:  # full
                return {
                    "status": "success",
                    "corpus_info": corpus_info,
                    "entity_connections": analysis_results["entity_connections"],
                    "thematic_clusters": analysis_results["thematic_clusters"],
                    "citation_networks": analysis_results["citation_networks"],
                    "temporal_evolution": analysis_results["temporal_evolution"],
                    "influence_analysis": analysis_results["influence_analysis"],
                    "knowledge_discoveries": analysis_results["knowledge_discoveries"],
                    "visualization_data": visualization_data,
                    "analysis_summary": analysis_summary,
                    "processing_time": sum(
                        r.get("processing_time", 0) for r in analysis_results.values() 
                        if isinstance(r, dict)
                    ),
                    "message": f"Successfully completed comprehensive cross-document analysis on {len(documents)} documents"
                }
            
    except ImportError as e:
        logger.error(f"Cross-document analysis dependencies not available: {e}")
        return {
            "status": "error",
            "message": f"Cross-document analysis dependencies not available: {str(e)}"
        }
    except Exception as e:
        logger.error(f"Error in cross-document analysis: {e}")
        return {
            "status": "error",
            "message": f"Failed to perform cross-document analysis: {str(e)}"
        }

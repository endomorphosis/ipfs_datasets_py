"""
Citation Extraction MCP Tool.

This tool exposes the SearchResultCitationExtractor which extracts, ranks,
and exports legal citations from search results with network building and
multiple export formats.

Core implementation: ipfs_datasets_py.processors.legal_scrapers.citation_extraction
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def extract_legal_citations(
    results: List[Dict[str, Any]],
    extract_metadata: bool = True,
    build_network: bool = True,
    rank_by: str = "importance",
    min_confidence: float = 0.5,
    citation_types: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Extract and rank legal citations from search results.
    
    This is a thin wrapper around SearchResultCitationExtractor from the processors module.
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.citation_extraction
    
    Features:
    - Extracts citations from URLs, titles, and snippets
    - Identifies citation types (case law, statutes, regulations, rules)
    - Builds citation networks showing relationships
    - Ranks citations by importance, frequency, or recency
    - Exports to multiple formats (JSON, CSV, GraphML, DOT)
    
    Args:
        results: List of search results (each with 'url', 'title', 'snippet')
        extract_metadata: Extract additional metadata for each citation (default: True)
        build_network: Build citation network graph (default: True)
        rank_by: Ranking method - "importance", "frequency", or "recency" (default: "importance")
        min_confidence: Minimum confidence score for extracted citations (0.0-1.0, default: 0.5)
        citation_types: Filter by citation types ["case", "statute", "regulation", "rule"]
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - citations: List of extracted citations with metadata
        - citation_network: Citation network graph (if build_network=True)
        - ranking_scores: Importance/frequency/recency scores per citation
        - total_citations: Total number of citations extracted
        - unique_citations: Number of unique citations
        - citation_types_found: Distribution of citation types
        - extraction_metadata: Details about extraction process
    
    Example:
        >>> results = [{"url": "...", "title": "...", "snippet": "..."}]
        >>> extracted = await extract_legal_citations(
        ...     results=results,
        ...     build_network=True,
        ...     rank_by="importance"
        ... )
        >>> print(f"Extracted {extracted['total_citations']} citations")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import SearchResultCitationExtractor
        
        # Validate input
        if not results or not isinstance(results, list):
            return {
                "status": "error",
                "message": "Results must be a non-empty list"
            }
        
        # Validate each result has required fields
        for idx, result in enumerate(results):
            if not isinstance(result, dict):
                return {
                    "status": "error",
                    "message": f"Result at index {idx} must be a dictionary"
                }
        
        if rank_by not in ["importance", "frequency", "recency"]:
            return {
                "status": "error",
                "message": "rank_by must be 'importance', 'frequency', or 'recency'"
            }
        
        if not 0 <= min_confidence <= 1:
            return {
                "status": "error",
                "message": "min_confidence must be between 0.0 and 1.0"
            }
        
        if citation_types:
            valid_types = ["case", "statute", "regulation", "rule"]
            for ctype in citation_types:
                if ctype not in valid_types:
                    return {
                        "status": "error",
                        "message": f"Invalid citation type '{ctype}'. Must be one of: {valid_types}"
                    }
        
        # Initialize citation extractor
        extractor_config = {
            "extract_metadata": extract_metadata,
            "min_confidence": min_confidence
        }
        
        extractor = SearchResultCitationExtractor(**extractor_config)
        
        # Extract citations from results
        citations = extractor.extract_citations(results)
        
        # Filter by citation type if specified
        if citation_types:
            citations = [
                c for c in citations 
                if c.get("citation_type") in citation_types
            ]
        
        # Build citation network if requested
        citation_network = None
        if build_network and citations:
            citation_network = extractor.build_citation_network(citations)
        
        # Rank citations
        ranking_scores = extractor.rank_citations(citations, rank_by=rank_by)
        
        # Calculate statistics
        unique_citations = len(set(c.get("citation_id") for c in citations))
        citation_types_found = {}
        for citation in citations:
            ctype = citation.get("citation_type", "unknown")
            citation_types_found[ctype] = citation_types_found.get(ctype, 0) + 1
        
        return {
            "status": "success",
            "citations": citations,
            "citation_network": citation_network,
            "ranking_scores": ranking_scores,
            "total_citations": len(citations),
            "unique_citations": unique_citations,
            "citation_types_found": citation_types_found,
            "extraction_metadata": {
                "extract_metadata": extract_metadata,
                "build_network": build_network,
                "rank_by": rank_by,
                "min_confidence": min_confidence,
                "citation_types_filter": citation_types
            },
            "mcp_tool": "extract_legal_citations"
        }
        
    except ImportError as e:
        logger.error(f"Import error in extract_legal_citations: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in extract_legal_citations MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "total_results": len(results) if results else 0
        }


async def export_citations(
    citations: List[Dict[str, Any]],
    format: str = "json",
    include_network: bool = False,
    output_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    Export extracted citations to various formats.
    
    Supported formats:
    - json: JSON format with full metadata
    - csv: CSV format for spreadsheet analysis
    - graphml: GraphML format for network analysis (Gephi, Cytoscape)
    - dot: DOT format for Graphviz visualization
    
    Args:
        citations: List of citation dictionaries
        format: Export format - "json", "csv", "graphml", or "dot" (default: "json")
        include_network: Include citation network data (default: False)
        output_path: Optional file path to save export (if not provided, returns data)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - exported_data: Exported citation data (if output_path not provided)
        - output_path: Path where file was saved (if output_path provided)
        - format: Export format used
        - total_citations: Number of citations exported
    
    Example:
        >>> exported = await export_citations(
        ...     citations=citations,
        ...     format="csv",
        ...     output_path="/tmp/citations.csv"
        ... )
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import SearchResultCitationExtractor
        
        if not citations or not isinstance(citations, list):
            return {
                "status": "error",
                "message": "Citations must be a non-empty list"
            }
        
        if format not in ["json", "csv", "graphml", "dot"]:
            return {
                "status": "error",
                "message": "Format must be 'json', 'csv', 'graphml', or 'dot'"
            }
        
        extractor = SearchResultCitationExtractor()
        
        # Export citations
        exported_data = extractor.export_citations(
            citations,
            format=format,
            include_network=include_network,
            output_path=output_path
        )
        
        result = {
            "status": "success",
            "format": format,
            "total_citations": len(citations),
            "include_network": include_network
        }
        
        if output_path:
            result["output_path"] = output_path
            result["message"] = f"Citations exported to {output_path}"
        else:
            result["exported_data"] = exported_data
            result["message"] = "Citations exported successfully"
        
        return result
        
    except Exception as e:
        logger.error(f"Error exporting citations: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


async def analyze_citation_network(
    citations: List[Dict[str, Any]],
    analysis_type: str = "centrality"
) -> Dict[str, Any]:
    """
    Analyze citation network for insights.
    
    Analysis types:
    - centrality: Identify most central/influential citations
    - clusters: Find citation clusters and communities
    - paths: Analyze citation paths and chains
    - statistics: Network statistics (density, diameter, etc.)
    
    Args:
        citations: List of citation dictionaries
        analysis_type: Type of analysis - "centrality", "clusters", "paths", or "statistics"
    
    Returns:
        Dictionary with network analysis results
    
    Example:
        >>> analysis = await analyze_citation_network(
        ...     citations=citations,
        ...     analysis_type="centrality"
        ... )
        >>> print(f"Most central: {analysis['top_citations']}")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import SearchResultCitationExtractor
        
        if not citations or not isinstance(citations, list):
            return {
                "status": "error",
                "message": "Citations must be a non-empty list"
            }
        
        if analysis_type not in ["centrality", "clusters", "paths", "statistics"]:
            return {
                "status": "error",
                "message": "analysis_type must be 'centrality', 'clusters', 'paths', or 'statistics'"
            }
        
        extractor = SearchResultCitationExtractor()
        
        # Build network
        network = extractor.build_citation_network(citations)
        
        # Perform analysis
        analysis_results = extractor.analyze_network(network, analysis_type=analysis_type)
        
        return {
            "status": "success",
            "analysis_type": analysis_type,
            "results": analysis_results,
            "total_citations": len(citations),
            "message": f"Network analysis completed: {analysis_type}"
        }
        
    except Exception as e:
        logger.error(f"Error analyzing citation network: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

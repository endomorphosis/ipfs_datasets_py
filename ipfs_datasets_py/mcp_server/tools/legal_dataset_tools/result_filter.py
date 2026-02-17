"""
Advanced Result Filtering MCP Tool.

This tool exposes the ResultFilter system which provides sophisticated
filtering of legal search results by domain, date, jurisdiction, quality
scoring, and fuzzy deduplication.

Core implementation: ipfs_datasets_py.processors.legal_scrapers.result_filter
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def filter_legal_results(
    results: List[Dict[str, Any]],
    domain_whitelist: Optional[List[str]] = None,
    domain_blacklist: Optional[List[str]] = None,
    date_range: Optional[Dict[str, str]] = None,
    jurisdictions: Optional[List[str]] = None,
    min_quality_score: float = 0.0,
    enable_fuzzy_dedup: bool = True,
    similarity_threshold: float = 0.85,
    sort_by: str = "quality",
    max_results: Optional[int] = None
) -> Dict[str, Any]:
    """
    Filter and rank legal search results with advanced criteria.
    
    This is a thin wrapper around ResultFilter from the processors module.
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.result_filter
    
    Features:
    - Domain filtering (whitelist/blacklist for government sites)
    - Date range filtering (results within specified date range)
    - Jurisdiction filtering (federal, state, local, international)
    - Quality scoring (relevance, authority, freshness)
    - Fuzzy deduplication (removes near-duplicate results)
    
    Args:
        results: List of search results to filter (each must have 'url', 'title', 'snippet')
        domain_whitelist: List of allowed domains (e.g., ["gov", "courts.gov"])
        domain_blacklist: List of blocked domains (e.g., ["example.com"])
        date_range: Date range filter {"start": "2020-01-01", "end": "2024-12-31"}
        jurisdictions: Filter by jurisdictions ["federal", "state", "local", "international"]
        min_quality_score: Minimum quality score (0.0-1.0, default: 0.0)
        enable_fuzzy_dedup: Remove near-duplicate results (default: True)
        similarity_threshold: Similarity threshold for deduplication (0.0-1.0, default: 0.85)
        sort_by: Sort results by "quality", "date", or "relevance" (default: "quality")
        max_results: Maximum number of results to return (optional)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - filtered_results: List of filtered and ranked results
        - filter_stats: Statistics about filtering process
        - total_input: Number of input results
        - total_output: Number of output results
        - removed_by_domain: Count removed by domain filters
        - removed_by_date: Count removed by date filters
        - removed_by_jurisdiction: Count removed by jurisdiction filters
        - removed_by_quality: Count removed by quality threshold
        - removed_by_deduplication: Count removed by deduplication
    
    Example:
        >>> results = [{"url": "...", "title": "...", "snippet": "..."}]
        >>> filtered = await filter_legal_results(
        ...     results=results,
        ...     domain_whitelist=["gov"],
        ...     min_quality_score=0.5,
        ...     jurisdictions=["federal"]
        ... )
        >>> print(f"Filtered from {filtered['total_input']} to {filtered['total_output']}")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import ResultFilter
        
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
            if "url" not in result:
                return {
                    "status": "error",
                    "message": f"Result at index {idx} missing required field 'url'"
                }
        
        if sort_by not in ["quality", "date", "relevance"]:
            return {
                "status": "error",
                "message": "sort_by must be 'quality', 'date', or 'relevance'"
            }
        
        if not 0 <= min_quality_score <= 1:
            return {
                "status": "error",
                "message": "min_quality_score must be between 0.0 and 1.0"
            }
        
        if not 0 <= similarity_threshold <= 1:
            return {
                "status": "error",
                "message": "similarity_threshold must be between 0.0 and 1.0"
            }
        
        if jurisdictions:
            valid_jurisdictions = ["federal", "state", "local", "international"]
            for jurisdiction in jurisdictions:
                if jurisdiction not in valid_jurisdictions:
                    return {
                        "status": "error",
                        "message": f"Invalid jurisdiction '{jurisdiction}'. Must be one of: {valid_jurisdictions}"
                    }
        
        # Initialize result filter
        filter_config = {
            "domain_whitelist": domain_whitelist or [],
            "domain_blacklist": domain_blacklist or [],
            "enable_fuzzy_dedup": enable_fuzzy_dedup,
            "similarity_threshold": similarity_threshold
        }
        
        result_filter = ResultFilter(**filter_config)
        
        # Apply filters
        filtered_results = results
        filter_stats = {
            "removed_by_domain": 0,
            "removed_by_date": 0,
            "removed_by_jurisdiction": 0,
            "removed_by_quality": 0,
            "removed_by_deduplication": 0
        }
        
        # Domain filtering
        if domain_whitelist or domain_blacklist:
            before_count = len(filtered_results)
            filtered_results = result_filter.filter_by_domain(filtered_results)
            filter_stats["removed_by_domain"] = before_count - len(filtered_results)
        
        # Date range filtering
        if date_range:
            before_count = len(filtered_results)
            filtered_results = result_filter.filter_by_date_range(
                filtered_results,
                start_date=date_range.get("start"),
                end_date=date_range.get("end")
            )
            filter_stats["removed_by_date"] = before_count - len(filtered_results)
        
        # Jurisdiction filtering
        if jurisdictions:
            before_count = len(filtered_results)
            filtered_results = result_filter.filter_by_jurisdiction(
                filtered_results,
                jurisdictions
            )
            filter_stats["removed_by_jurisdiction"] = before_count - len(filtered_results)
        
        # Quality scoring and filtering
        before_count = len(filtered_results)
        filtered_results = result_filter.score_and_filter(
            filtered_results,
            min_score=min_quality_score
        )
        filter_stats["removed_by_quality"] = before_count - len(filtered_results)
        
        # Fuzzy deduplication
        if enable_fuzzy_dedup:
            before_count = len(filtered_results)
            filtered_results = result_filter.deduplicate(filtered_results)
            filter_stats["removed_by_deduplication"] = before_count - len(filtered_results)
        
        # Sort results
        filtered_results = result_filter.sort_results(filtered_results, sort_by=sort_by)
        
        # Limit results
        if max_results and len(filtered_results) > max_results:
            filtered_results = filtered_results[:max_results]
        
        return {
            "status": "success",
            "filtered_results": filtered_results,
            "filter_stats": filter_stats,
            "total_input": len(results),
            "total_output": len(filtered_results),
            "removed_total": len(results) - len(filtered_results),
            "filter_config": filter_config,
            "sort_by": sort_by,
            "mcp_tool": "filter_legal_results"
        }
        
    except ImportError as e:
        logger.error(f"Import error in filter_legal_results: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in filter_legal_results MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "total_input": len(results) if results else 0
        }


async def get_filter_statistics(
    results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Get statistics about search results for filter planning.
    
    Analyzes results to provide insights on:
    - Domain distribution
    - Date distribution
    - Jurisdiction distribution
    - Quality score distribution
    
    Args:
        results: List of search results to analyze
    
    Returns:
        Dictionary with distribution statistics
    
    Example:
        >>> stats = await get_filter_statistics(results)
        >>> print(f"Domains: {stats['domain_distribution']}")
    """
    try:
        from ipfs_datasets_py.processors.legal_scrapers import ResultFilter
        
        if not results or not isinstance(results, list):
            return {
                "status": "error",
                "message": "Results must be a non-empty list"
            }
        
        result_filter = ResultFilter()
        stats = result_filter.get_result_statistics(results)
        
        return {
            "status": "success",
            "statistics": stats,
            "total_results": len(results)
        }
        
    except Exception as e:
        logger.error(f"Error getting filter statistics: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

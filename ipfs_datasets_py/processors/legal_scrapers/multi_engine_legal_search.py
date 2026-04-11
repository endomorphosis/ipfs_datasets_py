"""
Multi-Engine Legal Search — canonical business logic module.

Provides the MultiEngineLegalSearch system that supports searching
across multiple search engines (Brave, DuckDuckGo, Google CSE) with intelligent
fallback and result aggregation.

Reusable by:
- MCP server tools (mcp_server/tools/legal_dataset_tools/)
- CLI commands
- Direct Python imports: from ipfs_datasets_py.processors.legal_scrapers.multi_engine_legal_search import ...

The MCP tool wrapper lives at mcp_server/tools/legal_dataset_tools/multi_engine_legal_search.py
and re-exports all symbols from here.
"""

import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


async def multi_engine_legal_search(
    query: str,
    engines: Optional[List[str]] = None,
    max_results: int = 20,
    parallel_enabled: bool = True,
    fallback_enabled: bool = True,
    deduplication_enabled: bool = True,
    result_aggregation: str = "merge",
    country: str = "US",
    lang: str = "en",
    brave_api_key: Optional[str] = None,
    google_api_key: Optional[str] = None,
    google_cse_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Search for legal rules using multiple search engines with intelligent fallback.
    
    This is a thin wrapper around MultiEngineLegalSearch from the processors module.
    All business logic is in ipfs_datasets_py.processors.legal_scrapers.multi_engine_legal_search
    
    Engines supported:
    - brave: Brave Search API (requires BRAVE_API_KEY)
    - duckduckgo: DuckDuckGo (no API key required)
    - google_cse: Google Custom Search Engine (requires GOOGLE_API_KEY and GOOGLE_CSE_ID)
    
    Args:
        query: Natural language query about legal rules (e.g., "EPA water regulations in California")
        engines: List of search engines to use (default: ["brave", "duckduckgo"])
        max_results: Maximum number of results to return per engine (default: 20)
        parallel_enabled: Execute searches across engines in parallel (default: True)
        fallback_enabled: Automatically fallback to other engines on failure (default: True)
        deduplication_enabled: Remove duplicate results by URL (default: True)
        result_aggregation: How to combine results - "merge", "best", or "round_robin" (default: "merge")
        country: Country code for search (default: "US")
        lang: Language code for search (default: "en")
        brave_api_key: Brave Search API key (or set BRAVE_API_KEY env var)
        google_api_key: Google API key (or set GOOGLE_API_KEY env var)
        google_cse_id: Google Custom Search Engine ID (or set GOOGLE_CSE_ID env var)
    
    Returns:
        Dictionary containing:
        - status: "success" or "error"
        - query: The search query
        - results: List of search results from all engines
        - metadata: Search metadata including engines used, timing, and performance metrics
        - search_terms: Generated search terms
        - entities_matched: Legal entities matched
        - engines_used: List of engines that returned results
        - total_results: Total number of results returned
    
    Example:
        >>> result = await multi_engine_legal_search(
        ...     query="OSHA workplace safety regulations",
        ...     engines=["brave", "duckduckgo"],
        ...     max_results=10
        ... )
        >>> print(f"Found {result['total_results']} results from {result['engines_used']}")
    """
    try:
        from ipfs_datasets_py.processors.web_archiving.search_engines import (
            MultiEngineOrchestrator,
            OrchestratorConfig,
            SearchEngineConfig,
            SearchEngineError,
        )
        
        # Validate input
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "message": "Query must be a non-empty string"
            }
        
        if engines is None:
            engines = ["brave", "duckduckgo"]
        
        if not isinstance(engines, list) or not engines:
            return {
                "status": "error",
                "message": "Engines must be a non-empty list"
            }
        
        valid_engines = ["brave", "duckduckgo", "google_cse"]
        for engine in engines:
            if engine not in valid_engines:
                return {
                    "status": "error",
                    "message": f"Invalid engine '{engine}'. Must be one of: {valid_engines}"
                }
        
        if max_results < 1 or max_results > 100:
            return {
                "status": "error",
                "message": "max_results must be between 1 and 100"
            }
        
        if result_aggregation not in ["merge", "best", "round_robin"]:
            return {
                "status": "error",
                "message": "result_aggregation must be 'merge', 'best', or 'round_robin'"
            }
        
        engine_configs: Dict[str, SearchEngineConfig] = {}
        if "brave" in engines:
            engine_configs["brave"] = SearchEngineConfig(
                engine_type="brave",
                api_key=brave_api_key,
            )
        if "google_cse" in engines:
            engine_configs["google_cse"] = SearchEngineConfig(
                engine_type="google_cse",
                api_key=google_api_key,
                extra_params={"cse_id": google_cse_id},
            )

        orchestrator = MultiEngineOrchestrator(
            OrchestratorConfig(
                engines=engines,
                engine_configs=engine_configs,
                parallel_enabled=parallel_enabled,
                fallback_enabled=fallback_enabled,
                result_aggregation=result_aggregation,
                deduplication_enabled=deduplication_enabled,
            )
        )

        response = orchestrator.search(
            query=query,
            max_results=max_results,
            country=country,
            lang=lang
        )

        results = [
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "engine": str(item.engine),
                "score": item.score,
                "published_date": item.published_date,
                "domain": item.domain,
                "metadata": item.metadata,
            }
            for item in list(response.results or [])
        ]
        engines_used = list(response.metadata.get("engines_used") or [])

        return {
            "status": "success",
            "query": query,
            "results": results,
            "metadata": dict(response.metadata or {}),
            "search_terms": [query],
            "entities_matched": [],
            "engines_used": engines_used,
            "total_results": len(results),
            "mcp_tool": "multi_engine_legal_search",
            "engines_requested": engines,
            "parallel_enabled": parallel_enabled,
            "fallback_enabled": fallback_enabled,
        }

    except (ImportError, SearchEngineError) as e:
        logger.error(f"Import error in multi_engine_legal_search: {e}")
        return {
            "status": "error",
            "message": f"Required module not found: {str(e)}. Install with: pip install ipfs-datasets-py[legal]"
        }
    except Exception as e:
        logger.error(f"Error in multi_engine_legal_search MCP tool: {e}")
        return {
            "status": "error",
            "message": str(e),
            "query": query
        }


async def get_multi_engine_stats() -> Dict[str, Any]:
    """
    Get performance statistics for multi-engine legal search.
    
    Returns aggregated statistics including:
    - Total requests per engine
    - Success/failure rates
    - Average response times
    - Cache hit rates
    
    Returns:
        Dictionary containing statistics for each configured engine
    """
    try:
        from ipfs_datasets_py.processors.web_archiving.search_engines import (
            MultiEngineOrchestrator,
            OrchestratorConfig,
        )

        orchestrator = MultiEngineOrchestrator(
            OrchestratorConfig(engines=["duckduckgo"])
        )
        stats = {
            engine_name: engine.get_stats()
            for engine_name, engine in orchestrator.engines.items()
        }
        
        return {
            "status": "success",
            "stats": stats,
            "message": "Multi-engine statistics retrieved successfully"
        }
        
    except Exception as e:
        logger.error(f"Error getting multi-engine stats: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

"""Brave Search API integration for web search and data discovery.

This tool provides integration with Brave Search API for web search,
enabling dataset creation from search results. It now uses the improved
brave_search_client module from web_archiving with caching support.

The BraveSearchAPI class has been extracted to brave_search_engine.py;
it is re-exported here so existing import paths continue to work unchanged.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Re-export BraveSearchAPI so existing imports keep working.
from .brave_search_engine import BraveSearchAPI, HAVE_BRAVE_CLIENT  # noqa: F401

# Import cache helpers for the standalone async tool functions below.
try:
    from ipfs_datasets_py.processors.web_archiving.brave_search_client import (
        brave_search_cache_stats,
        clear_brave_search_cache,
    )
except ImportError:
    brave_search_cache_stats = None  # type: ignore[assignment]
    clear_brave_search_cache = None  # type: ignore[assignment]
async def search_brave(
    query: str,
    api_key: Optional[str] = None,
    count: int = 10,
    offset: int = 0,
    search_lang: str = "en",
    country: str = "US",
    safesearch: Literal["off", "moderate", "strict"] = "moderate",
    freshness: Optional[Literal["pd", "pw", "pm", "py"]] = None,
    text_decorations: bool = True,
    spellcheck: bool = True,
    result_filter: Optional[str] = None
) -> Dict[str, Any]:
    """Search the web using Brave Search API.

    Args:
        query: Search query string
        api_key: Brave Search API key (can also be set via BRAVE_API_KEY env var)
        count: Number of results to return (1-20, default 10)
        offset: Pagination offset (default 0)
        search_lang: Search language code (default "en")
        country: Country code for search results (default "US")
        safesearch: Safe search filter level
        freshness: Time-based freshness filter (pd=past day, pw=past week, pm=past month, py=past year)
        text_decorations: Enable text decorations in results
        spellcheck: Enable spell checking
        result_filter: Filter results (e.g., "web", "news", "videos")

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of search results
            - query: Original search query
            - total_results: Total number of results available
            - error: Error message (if failed)
    """
    try:
        # Input validation
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "error": "Query must be a non-empty string",
                "validation": {
                    "query": "Required string parameter"
                },
                "help": "Provide a valid search query string"
            }
        
        if not isinstance(count, int) or count < 1 or count > 20:
            return {
                "status": "error",
                "error": "Count must be between 1 and 20",
                "validation": {
                    "count": "Must be integer between 1 and 20"
                },
                "help": "Set count parameter between 1 and 20"
            }
        
        if not isinstance(offset, int) or offset < 0:
            return {
                "status": "error",
                "error": "Offset must be a non-negative integer",
                "validation": {
                    "offset": "Must be integer >= 0"
                },
                "help": "Set offset to 0 or higher for pagination"
            }
        
        valid_safesearch = ["off", "moderate", "strict"]
        if safesearch not in valid_safesearch:
            return {
                "status": "error",
                "error": f"Invalid safesearch value: {safesearch}",
                "validation": {
                    "safesearch": f"Must be one of: {', '.join(valid_safesearch)}"
                },
                "help": f"Use one of: {', '.join(valid_safesearch)}"
            }
        
        if freshness and freshness not in ["pd", "pw", "pm", "py"]:
            return {
                "status": "error",
                "error": f"Invalid freshness value: {freshness}",
                "validation": {
                    "freshness": "Must be one of: pd (past day), pw (past week), pm (past month), py (past year)"
                },
                "help": "Use pd, pw, pm, or py for freshness filter"
            }
        
        # Get API key from parameter or environment
        if api_key is None:
            api_key = os.environ.get("BRAVE_API_KEY")
        
        if not api_key:
            return {
                "status": "error",
                "error": "Brave Search API key required. Set BRAVE_API_KEY environment variable or pass api_key parameter.",
                "help": "Get API key from https://brave.com/search/api/"
            }

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required for Brave Search. Install with: pip install aiohttp",
                "help": "Run: pip install aiohttp"
            }

        # Brave Search API endpoint
        url = "https://api.search.brave.com/res/v1/web/search"
        
        # Prepare query parameters
        params = {
            "q": query,
            "count": min(count, 20),  # API limit
            "offset": offset,
            "search_lang": search_lang,
            "country": country,
            "safesearch": safesearch,
            "text_decorations": str(text_decorations).lower(),
            "spellcheck": str(spellcheck).lower()
        }
        
        if freshness:
            params["freshness"] = freshness
        
        if result_filter:
            params["result_filter"] = result_filter

        # Set headers with API key
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key
        }

        # Make the API request
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract search results
                    results = []
                    web_results = data.get("web", {}).get("results", [])
                    
                    for result in web_results:
                        results.append({
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "description": result.get("description", ""),
                            "published_date": result.get("age", ""),
                            "language": result.get("language", ""),
                            "family_friendly": result.get("family_friendly", True),
                            "extra_snippets": result.get("extra_snippets", [])
                        })
                    
                    # Get query info
                    query_info = data.get("query", {})
                    
                    return {
                        "status": "success",
                        "results": results,
                        "query": query,
                        "original_query": query_info.get("original", query),
                        "altered_query": query_info.get("altered"),
                        "spellcheck_off": query_info.get("spellcheck_off", False),
                        "total_results": len(results),
                        "search_timestamp": datetime.now().isoformat()
                    }
                elif response.status == 401:
                    return {
                        "status": "error",
                        "error": "Invalid Brave Search API key"
                    }
                elif response.status == 429:
                    return {
                        "status": "error",
                        "error": "Brave Search API rate limit exceeded"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"Brave Search API error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search Brave: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def search_brave_news(
    query: str,
    api_key: Optional[str] = None,
    count: int = 10,
    offset: int = 0,
    search_lang: str = "en",
    country: str = "US",
    safesearch: Literal["off", "moderate", "strict"] = "moderate",
    freshness: Optional[Literal["pd", "pw", "pm", "py"]] = None
) -> Dict[str, Any]:
    """Search news using Brave Search API.

    Args:
        query: Search query string
        api_key: Brave Search API key (can also be set via BRAVE_API_KEY env var)
        count: Number of results to return (1-20, default 10)
        offset: Pagination offset (default 0)
        search_lang: Search language code (default "en")
        country: Country code for search results (default "US")
        safesearch: Safe search filter level
        freshness: Time-based freshness filter

    Returns:
        Dict containing news search results
    """
    # Use the main search function with news filter
    return await search_brave(
        query=query,
        api_key=api_key,
        count=count,
        offset=offset,
        search_lang=search_lang,
        country=country,
        safesearch=safesearch,
        freshness=freshness,
        result_filter="news"
    )


async def search_brave_images(
    query: str,
    api_key: Optional[str] = None,
    count: int = 10,
    offset: int = 0,
    search_lang: str = "en",
    country: str = "US",
    safesearch: Literal["off", "moderate", "strict"] = "moderate"
) -> Dict[str, Any]:
    """Search images using Brave Search API.

    Args:
        query: Search query string
        api_key: Brave Search API key
        count: Number of results to return
        offset: Pagination offset
        search_lang: Search language code
        country: Country code for search results
        safesearch: Safe search filter level

    Returns:
        Dict containing image search results
    """
    try:
        # Get API key from parameter or environment
        if api_key is None:
            api_key = os.environ.get("BRAVE_API_KEY")
        
        if not api_key:
            return {
                "status": "error",
                "error": "Brave Search API key required"
            }

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        # Brave Search API endpoint for images
        url = "https://api.search.brave.com/res/v1/images/search"
        
        params = {
            "q": query,
            "count": min(count, 20),
            "offset": offset,
            "search_lang": search_lang,
            "country": country,
            "safesearch": safesearch
        }

        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    image_results = data.get("results", [])
                    
                    for result in image_results:
                        results.append({
                            "title": result.get("title", ""),
                            "url": result.get("url", ""),
                            "thumbnail": result.get("thumbnail", {}).get("src", ""),
                            "source": result.get("source", ""),
                            "width": result.get("properties", {}).get("width"),
                            "height": result.get("properties", {}).get("height"),
                            "format": result.get("properties", {}).get("format")
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "query": query,
                        "total_results": len(results),
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"Brave Image Search error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search Brave images: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def batch_search_brave(
    queries: List[str],
    api_key: Optional[str] = None,
    count: int = 10,
    delay_seconds: float = 1.0
) -> Dict[str, Any]:
    """Batch search multiple queries using Brave Search API.

    Args:
        queries: List of search query strings
        api_key: Brave Search API key
        count: Number of results per query
        delay_seconds: Delay between requests to avoid rate limiting

    Returns:
        Dict containing batch search results
    """
    try:
        import anyio
        
        results = {}
        success_count = 0
        error_count = 0
        
        for query in queries:
            result = await search_brave(query=query, api_key=api_key, count=count)
            results[query] = result
            
            if result['status'] == 'success':
                success_count += 1
            else:
                error_count += 1
            
            # Add delay between requests
            if query != queries[-1]:  # Don't delay after last query
                await anyio.sleep(delay_seconds)
        
        return {
            "status": "success",
            "results": results,
            "total_queries": len(queries),
            "success_count": success_count,
            "error_count": error_count,
            "batch_completed_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed batch Brave search: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def get_brave_cache_stats() -> Dict[str, Any]:
    """Get Brave Search cache statistics.
    
    Returns:
        Dict containing cache statistics if caching is available
    """
    try:
        if HAVE_BRAVE_CLIENT:
            stats = brave_search_cache_stats()
            return {
                "status": "success",
                **stats
            }
        else:
            return {
                "status": "unavailable",
                "message": "Caching requires brave_search_client module. Install with: pip install requests"
            }
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def clear_brave_cache() -> Dict[str, Any]:
    """Clear the Brave Search cache.
    
    Returns:
        Dict containing cache clearing result
    """
    try:
        if HAVE_BRAVE_CLIENT:
            result = clear_brave_search_cache()
            return {
                "status": "success",
                **result
            }
        else:
            return {
                "status": "unavailable",
                "message": "Caching requires brave_search_client module"
            }
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

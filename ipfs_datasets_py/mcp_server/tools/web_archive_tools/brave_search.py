"""Brave Search API integration for web search and data discovery.

This tool provides integration with Brave Search API for web search,
enabling dataset creation from search results. It now uses the improved
brave_search_client module from web_archiving with caching support.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import os

logger = logging.getLogger(__name__)

# Import the improved Brave Search client
try:
    from ipfs_datasets_py.processors.web_archiving.brave_search_client import (
        BraveSearchClient,
        brave_search_cache_stats,
        clear_brave_search_cache
    )
    HAVE_BRAVE_CLIENT = True
except ImportError:
    HAVE_BRAVE_CLIENT = False
    BraveSearchClient = None


class BraveSearchAPI:
    """Brave Search API class with install, config, and queue methods.
    
    This class provides a backward-compatible interface while using the
    improved BraveSearchClient under the hood when available.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize Brave Search API.
        
        Args:
            api_key: Brave Search API key (can use BRAVE_API_KEY env var)
        """
        self.api_key = api_key or os.environ.get("BRAVE_API_KEY") or os.environ.get("BRAVE_SEARCH_API_KEY")
        self.queue = []
        self.config = {
            "timeout": 30,
            "max_count": 20,
            "default_lang": "en",
            "default_country": "US"
        }
        
        # Use improved client if available
        if HAVE_BRAVE_CLIENT and self.api_key:
            self.client = BraveSearchClient(api_key=self.api_key)
        else:
            self.client = None
    
    def _install(self) -> Dict[str, Any]:
        """Install and verify Brave Search API dependencies.
        
        Returns:
            Dict containing installation status and instructions
        """
        try:
            import aiohttp
            aiohttp_installed = True
        except ImportError:
            aiohttp_installed = False
        
        try:
            import requests
            requests_installed = True
        except ImportError:
            requests_installed = False
        
        return {
            "status": "success" if ((aiohttp_installed or requests_installed) and self.api_key) else "incomplete",
            "dependencies": {
                "aiohttp": {
                    "installed": aiohttp_installed,
                    "required": False,
                    "install_command": "pip install aiohttp",
                    "note": "Required for async functions"
                },
                "requests": {
                    "installed": requests_installed,
                    "required": True,
                    "install_command": "pip install requests",
                    "note": "Required for sync functions and caching"
                }
            },
            "environment_variables": {
                "BRAVE_API_KEY": {
                    "set": bool(self.api_key),
                    "required": True,
                    "description": "Brave Search API key (required)"
                }
            },
            "instructions": {
                "1": "Install requests: pip install requests" if not requests_installed else "✓ Dependencies installed",
                "2": "Set BRAVE_API_KEY or BRAVE_SEARCH_API_KEY environment variable" if not self.api_key else "✓ API key configured",
                "3": "Get API key from: https://brave.com/search/api/"
            },
            "ready": (aiohttp_installed or requests_installed) and bool(self.api_key),
            "caching_available": HAVE_BRAVE_CLIENT
        }
    
    def _config(self, **kwargs) -> Dict[str, Any]:
        """Configure Brave Search API settings.
        
        Args:
            **kwargs: Configuration options (timeout, max_count, default_lang, default_country, etc.)
        
        Returns:
            Dict containing current configuration
        """
        valid_config_keys = ["timeout", "max_count", "default_lang", "default_country"]
        
        for key, value in kwargs.items():
            if key in valid_config_keys:
                self.config[key] = value
            elif key == "api_key":
                self.api_key = value
                # Update client if using improved version
                if HAVE_BRAVE_CLIENT:
                    self.client = BraveSearchClient(api_key=self.api_key)
        
        return {
            "status": "success",
            "configuration": self.config,
            "api_key_set": bool(self.api_key),
            "valid_config_keys": valid_config_keys,
            "example": {
                "timeout": 30,
                "max_count": 20,
                "default_lang": "en",
                "default_country": "US"
            },
            "caching_available": HAVE_BRAVE_CLIENT
        }
    
    def _queue(self, operation: str, **params) -> Dict[str, Any]:
        """Queue a search operation for batch processing.
        
        Args:
            operation: Operation type ('search', 'search_news', 'search_images')
            **params: Operation parameters
        
        Returns:
            Dict containing queue status
        """
        queue_item = {
            "id": len(self.queue) + 1,
            "operation": operation,
            "params": params,
            "queued_at": datetime.now().isoformat(),
            "status": "queued"
        }
        
        self.queue.append(queue_item)
        
        return {
            "status": "success",
            "queue_item": queue_item,
            "queue_length": len(self.queue),
            "message": f"Operation '{operation}' queued successfully"
        }
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get current queue status."""
        return {
            "queue_length": len(self.queue),
            "queued_operations": self.queue,
            "operations_pending": len([item for item in self.queue if item["status"] == "queued"])
        }
    
    def clear_queue(self) -> Dict[str, Any]:
        """Clear all queued operations."""
        cleared_count = len(self.queue)
        self.queue = []
        return {
            "status": "success",
            "cleared_count": cleared_count,
            "message": f"Cleared {cleared_count} queued operations"
        }
    
    def cache_stats(self) -> Dict[str, Any]:
        """Get Brave Search cache statistics.
        
        Returns:
            Dict containing cache stats if caching is available
        """
        if HAVE_BRAVE_CLIENT:
            return brave_search_cache_stats()
        else:
            return {
                "status": "unavailable",
                "message": "Caching requires brave_search_client module"
            }
    
    def clear_cache(self) -> Dict[str, Any]:
        """Clear the Brave Search cache.
        
        Returns:
            Dict containing cache clearing result
        """
        if HAVE_BRAVE_CLIENT:
            return clear_brave_search_cache()
        else:
            return {
                "status": "unavailable",
                "message": "Caching requires brave_search_client module"
            }



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

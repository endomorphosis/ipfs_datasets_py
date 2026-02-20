"""SerpStack API integration for search engine results (thin MCP wrapper).

Business logic (``SerpStackSearchAPI``) lives in:
    ipfs_datasets_py.web_archiving.serpstack_engine
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from ipfs_datasets_py.web_archiving.serpstack_engine import SerpStackSearchAPI  # noqa: F401

logger = logging.getLogger(__name__)

async def search_serpstack(
    query: str,
    api_key: Optional[str] = None,
    engine: str = "google",
    num: int = 10,
    page: int = 1,
    location: Optional[str] = None,
    device: Optional[Literal["desktop", "mobile", "tablet"]] = None,
    lang: Optional[str] = None
) -> Dict[str, Any]:
    """Search using SerpStack API.
    
    Args:
        query: Search query string
        api_key: SerpStack API key (can also be set via SERPSTACK_API_KEY env var)
        engine: Search engine to use (google, bing, yandex, yahoo, baidu)
        num: Number of results to return (default 10)
        page: Page number for pagination (default 1)
        location: Location for localized results (e.g., "United States")
        device: Device type for search simulation
        lang: Language code (e.g., "en", "es")
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of search results
            - query: Original search query
            - total_results: Estimated total results
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
        
        valid_engines = ["google", "bing", "yandex", "yahoo", "baidu"]
        if engine not in valid_engines:
            return {
                "status": "error",
                "error": f"Invalid search engine: {engine}",
                "validation": {
                    "engine": f"Must be one of: {', '.join(valid_engines)}"
                },
                "help": f"Supported engines: {', '.join(valid_engines)}"
            }
        
        if num < 1 or num > 100:
            return {
                "status": "error",
                "error": "Number of results must be between 1 and 100",
                "validation": {
                    "num": "Must be integer between 1 and 100"
                },
                "help": "Set num parameter between 1 and 100"
            }
        
        if page < 1:
            return {
                "status": "error",
                "error": "Page number must be >= 1",
                "validation": {
                    "page": "Must be integer >= 1"
                },
                "help": "Set page parameter to 1 or higher"
            }
        
        # Get API key
        if api_key is None:
            api_key = os.environ.get("SERPSTACK_API_KEY")
        
        if not api_key:
            return {
                "status": "error",
                "error": "SerpStack API key required. Set SERPSTACK_API_KEY environment variable or pass api_key parameter.",
                "help": "Get a free API key at https://serpstack.com/signup/free"
            }
        
        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required for SerpStack. Install with: pip install aiohttp",
                "help": "Run: pip install aiohttp"
            }
        
        # SerpStack API endpoint
        url = "http://api.serpstack.com/search"
        
        # Prepare query parameters
        params = {
            "access_key": api_key,
            "query": query,
            "engine": engine,
            "num": min(num, 100),
            "page": page
        }
        
        if location:
            params["location"] = location
        
        if device:
            params["device"] = device
        
        if lang:
            params["lang"] = lang
        
        # Make the API request
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Check for API errors
                    if "error" in data:
                        return {
                            "status": "error",
                            "error": data["error"].get("info", "Unknown API error"),
                            "error_code": data["error"].get("code"),
                            "help": "Check API documentation at https://serpstack.com/documentation"
                        }
                    
                    # Extract search results
                    results = []
                    organic_results = data.get("organic_results", [])
                    
                    for item in organic_results:
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "description": item.get("description", ""),
                            "displayed_url": item.get("displayed_url", ""),
                            "position": item.get("position", 0)
                        })
                    
                    search_info = data.get("search_information", {})
                    
                    return {
                        "status": "success",
                        "results": results,
                        "query": query,
                        "engine": engine,
                        "total_results": search_info.get("total_results", "N/A"),
                        "time_taken": search_info.get("time_taken", 0),
                        "page": page,
                        "search_timestamp": datetime.now().isoformat()
                    }
                elif response.status == 401:
                    return {
                        "status": "error",
                        "error": "Invalid SerpStack API key",
                        "help": "Check your API key at https://serpstack.com/dashboard"
                    }
                elif response.status == 429:
                    return {
                        "status": "error",
                        "error": "SerpStack API rate limit exceeded",
                        "help": "Upgrade your plan or wait before retrying"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"SerpStack API error (status {response.status}): {error_text}",
                        "help": "Check API documentation for error details"
                    }
    
    except Exception as e:
        logger.error(f"Failed to search SerpStack: {e}")
        return {
            "status": "error",
            "error": str(e),
            "help": "Check parameters and network connection"
        }


async def search_serpstack_images(
    query: str,
    api_key: Optional[str] = None,
    engine: str = "google",
    num: int = 10,
    location: Optional[str] = None
) -> Dict[str, Any]:
    """Search for images using SerpStack API.
    
    Args:
        query: Search query string
        api_key: SerpStack API key
        engine: Search engine to use
        num: Number of results
        location: Location for localized results
    
    Returns:
        Dict containing image search results
    """
    try:
        # Input validation
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "error": "Query must be a non-empty string",
                "validation": {"query": "Required string parameter"},
                "help": "Provide a valid search query"
            }
        
        if api_key is None:
            api_key = os.environ.get("SERPSTACK_API_KEY")
        
        if not api_key:
            return {
                "status": "error",
                "error": "SerpStack API key required",
                "help": "Set SERPSTACK_API_KEY or pass api_key parameter"
            }
        
        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required",
                "help": "Install with: pip install aiohttp"
            }
        
        url = "http://api.serpstack.com/search"
        
        params = {
            "access_key": api_key,
            "query": query,
            "engine": engine,
            "type": "images",
            "num": min(num, 100)
        }
        
        if location:
            params["location"] = location
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if "error" in data:
                        return {
                            "status": "error",
                            "error": data["error"].get("info", "Unknown error"),
                            "help": "Check API documentation"
                        }
                    
                    results = []
                    image_results = data.get("image_results", [])
                    
                    for item in image_results:
                        results.append({
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "image_url": item.get("image_url", ""),
                            "thumbnail": item.get("thumbnail", ""),
                            "source": item.get("source", ""),
                            "width": item.get("width"),
                            "height": item.get("height")
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "query": query,
                        "engine": engine,
                        "total_results": len(results),
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"SerpStack API error (status {response.status}): {error_text}",
                        "help": "Check API parameters"
                    }
    
    except Exception as e:
        logger.error(f"Failed to search SerpStack images: {e}")
        return {
            "status": "error",
            "error": str(e),
            "help": "Check parameters and try again"
        }


async def batch_search_serpstack(
    queries: List[str],
    api_key: Optional[str] = None,
    engine: str = "google",
    num: int = 10,
    delay_seconds: float = 1.0
) -> Dict[str, Any]:
    """Batch search multiple queries using SerpStack API.
    
    Args:
        queries: List of search queries
        api_key: SerpStack API key
        engine: Search engine to use
        num: Results per query
        delay_seconds: Delay between requests
    
    Returns:
        Dict containing batch search results
    """
    try:
        import anyio
        
        # Input validation
        if not queries or not isinstance(queries, list):
            return {
                "status": "error",
                "error": "Queries must be a non-empty list",
                "validation": {"queries": "Required list of strings"},
                "help": "Provide a list of search queries"
            }
        
        if not all(isinstance(q, str) for q in queries):
            return {
                "status": "error",
                "error": "All queries must be strings",
                "validation": {"queries": "All items must be strings"},
                "help": "Ensure all queries are valid strings"
            }
        
        results = {}
        success_count = 0
        error_count = 0
        
        for query in queries:
            result = await search_serpstack(query=query, api_key=api_key, engine=engine, num=num)
            results[query] = result
            
            if result['status'] == 'success':
                success_count += 1
            else:
                error_count += 1
            
            # Add delay between requests
            if query != queries[-1]:
                await anyio.sleep(delay_seconds)
        
        return {
            "status": "success",
            "results": results,
            "engine": engine,
            "total_queries": len(queries),
            "success_count": success_count,
            "error_count": error_count,
            "batch_completed_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Failed batch SerpStack search: {e}")
        return {
            "status": "error",
            "error": str(e),
            "help": "Check parameters and try again"
        }

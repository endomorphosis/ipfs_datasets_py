"""Brave Search API integration for web search and data discovery.

This tool provides integration with Brave Search API for web search,
enabling dataset creation from search results.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import os

logger = logging.getLogger(__name__)


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
        # Get API key from parameter or environment
        if api_key is None:
            api_key = os.environ.get("BRAVE_API_KEY")
        
        if not api_key:
            return {
                "status": "error",
                "error": "Brave Search API key required. Set BRAVE_API_KEY environment variable or pass api_key parameter."
            }

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required for Brave Search. Install with: pip install aiohttp"
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
        import asyncio
        
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
                await asyncio.sleep(delay_seconds)
        
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

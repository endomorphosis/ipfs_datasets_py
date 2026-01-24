"""Google Custom Search API integration for web search and data discovery.

This tool provides integration with Google Custom Search API for web search,
enabling dataset creation from search results.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import os

logger = logging.getLogger(__name__)


async def search_google(
    query: str,
    api_key: Optional[str] = None,
    search_engine_id: Optional[str] = None,
    num: int = 10,
    start: int = 1,
    search_type: Optional[Literal["image"]] = None,
    file_type: Optional[str] = None,
    site_search: Optional[str] = None,
    date_restrict: Optional[str] = None,
    safe: Literal["off", "medium", "high"] = "medium",
    lr: Optional[str] = None,
    gl: Optional[str] = None
) -> Dict[str, Any]:
    """Search using Google Custom Search API.

    Args:
        query: Search query string
        api_key: Google API key (can also be set via GOOGLE_API_KEY env var)
        search_engine_id: Custom Search Engine ID (can also be set via GOOGLE_CSE_ID env var)
        num: Number of results to return (1-10, default 10)
        start: Starting index for results (default 1)
        search_type: Search type ("image" for image search, None for web search)
        file_type: File type to filter (e.g., "pdf", "doc")
        site_search: Restrict search to a specific site
        date_restrict: Date restriction (e.g., "d[number]" for days, "w[number]" for weeks)
        safe: Safe search level
        lr: Language restriction (e.g., "lang_en")
        gl: Geolocation of end user (country code)

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of search results
            - query: Original search query
            - total_results: Total number of results available
            - error: Error message (if failed)
    """
    try:
        # Get credentials from parameters or environment
        if api_key is None:
            api_key = os.environ.get("GOOGLE_API_KEY")
        
        if search_engine_id is None:
            search_engine_id = os.environ.get("GOOGLE_CSE_ID")
        
        if not api_key or not search_engine_id:
            return {
                "status": "error",
                "error": "Google API key and Search Engine ID required. Set GOOGLE_API_KEY and GOOGLE_CSE_ID environment variables."
            }

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required for Google Search. Install with: pip install aiohttp"
            }

        # Google Custom Search API endpoint
        url = "https://www.googleapis.com/customsearch/v1"
        
        # Prepare query parameters
        params = {
            "key": api_key,
            "cx": search_engine_id,
            "q": query,
            "num": min(num, 10),  # API limit per request
            "start": start,
            "safe": safe
        }
        
        if search_type:
            params["searchType"] = search_type
        
        if file_type:
            params["fileType"] = file_type
        
        if site_search:
            params["siteSearch"] = site_search
        
        if date_restrict:
            params["dateRestrict"] = date_restrict
        
        if lr:
            params["lr"] = lr
        
        if gl:
            params["gl"] = gl

        # Make the API request
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract search results
                    results = []
                    items = data.get("items", [])
                    
                    for item in items:
                        result = {
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "snippet": item.get("snippet", ""),
                            "display_link": item.get("displayLink", ""),
                            "formatted_url": item.get("formattedUrl", "")
                        }
                        
                        # Add image-specific fields if present
                        if "image" in item:
                            result["image"] = {
                                "context_link": item["image"].get("contextLink", ""),
                                "height": item["image"].get("height"),
                                "width": item["image"].get("width"),
                                "byte_size": item["image"].get("byteSize"),
                                "thumbnail_link": item["image"].get("thumbnailLink", "")
                            }
                        
                        # Add page metadata if present
                        if "pagemap" in item:
                            result["metadata"] = item["pagemap"]
                        
                        results.append(result)
                    
                    # Get search information
                    search_info = data.get("searchInformation", {})
                    total_results = int(search_info.get("totalResults", 0))
                    
                    return {
                        "status": "success",
                        "results": results,
                        "query": query,
                        "total_results": total_results,
                        "search_time": search_info.get("searchTime", 0),
                        "formatted_total_results": search_info.get("formattedTotalResults", "0"),
                        "search_timestamp": datetime.now().isoformat()
                    }
                elif response.status == 400:
                    error_data = await response.json()
                    return {
                        "status": "error",
                        "error": f"Bad request: {error_data.get('error', {}).get('message', 'Unknown error')}"
                    }
                elif response.status == 403:
                    return {
                        "status": "error",
                        "error": "Invalid Google API key or quota exceeded"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"Google Search API error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search Google: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def search_google_images(
    query: str,
    api_key: Optional[str] = None,
    search_engine_id: Optional[str] = None,
    num: int = 10,
    start: int = 1,
    img_size: Optional[Literal["huge", "icon", "large", "medium", "small", "xlarge", "xxlarge"]] = None,
    img_type: Optional[Literal["clipart", "face", "lineart", "stock", "photo", "animated"]] = None,
    img_color_type: Optional[Literal["color", "gray", "mono", "trans"]] = None,
    img_dominant_color: Optional[str] = None,
    safe: Literal["off", "medium", "high"] = "medium"
) -> Dict[str, Any]:
    """Search for images using Google Custom Search API.

    Args:
        query: Search query string
        api_key: Google API key
        search_engine_id: Custom Search Engine ID
        num: Number of results to return (1-10)
        start: Starting index for results
        img_size: Image size filter
        img_type: Image type filter
        img_color_type: Color type filter
        img_dominant_color: Dominant color filter
        safe: Safe search level

    Returns:
        Dict containing image search results
    """
    try:
        # Get credentials from parameters or environment
        if api_key is None:
            api_key = os.environ.get("GOOGLE_API_KEY")
        
        if search_engine_id is None:
            search_engine_id = os.environ.get("GOOGLE_CSE_ID")
        
        if not api_key or not search_engine_id:
            return {
                "status": "error",
                "error": "Google API key and Search Engine ID required"
            }

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        url = "https://www.googleapis.com/customsearch/v1"
        
        params = {
            "key": api_key,
            "cx": search_engine_id,
            "q": query,
            "num": min(num, 10),
            "start": start,
            "searchType": "image",
            "safe": safe
        }
        
        if img_size:
            params["imgSize"] = img_size
        
        if img_type:
            params["imgType"] = img_type
        
        if img_color_type:
            params["imgColorType"] = img_color_type
        
        if img_dominant_color:
            params["imgDominantColor"] = img_dominant_color

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    items = data.get("items", [])
                    
                    for item in items:
                        result = {
                            "title": item.get("title", ""),
                            "url": item.get("link", ""),
                            "snippet": item.get("snippet", ""),
                            "display_link": item.get("displayLink", "")
                        }
                        
                        if "image" in item:
                            result["image"] = {
                                "context_link": item["image"].get("contextLink", ""),
                                "height": item["image"].get("height"),
                                "width": item["image"].get("width"),
                                "byte_size": item["image"].get("byteSize"),
                                "thumbnail_link": item["image"].get("thumbnailLink", ""),
                                "thumbnail_height": item["image"].get("thumbnailHeight"),
                                "thumbnail_width": item["image"].get("thumbnailWidth")
                            }
                        
                        results.append(result)
                    
                    search_info = data.get("searchInformation", {})
                    
                    return {
                        "status": "success",
                        "results": results,
                        "query": query,
                        "total_results": int(search_info.get("totalResults", 0)),
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"Google Image Search error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search Google images: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def batch_search_google(
    queries: List[str],
    api_key: Optional[str] = None,
    search_engine_id: Optional[str] = None,
    num: int = 10,
    delay_seconds: float = 0.5
) -> Dict[str, Any]:
    """Batch search multiple queries using Google Custom Search API.

    Args:
        queries: List of search query strings
        api_key: Google API key
        search_engine_id: Custom Search Engine ID
        num: Number of results per query
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
            result = await search_google(
                query=query,
                api_key=api_key,
                search_engine_id=search_engine_id,
                num=num
            )
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
            "total_queries": len(queries),
            "success_count": success_count,
            "error_count": error_count,
            "batch_completed_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed batch Google search: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

"""OpenVerse API integration for Creative Commons media search.

This tool provides integration with OpenVerse API for searching
Creative Commons licensed images, audio, and other media.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class OpenVerseSearchAPI:
    """OpenVerse Search API class with install, config, and queue methods."""
    
    def __init__(self, api_key: Optional[str] = None, api_url: str = "https://api.openverse.org/v1"):
        """Initialize OpenVerse API.
        
        Args:
            api_key: OpenVerse API key (optional, can use OPENVERSE_API_KEY env var)
            api_url: Base API URL (default: https://api.openverse.org/v1)
        """
        self.api_key = api_key or os.environ.get("OPENVERSE_API_KEY")
        self.api_url = api_url
        self.queue = []
        self.config = {
            "api_url": api_url,
            "timeout": 30,
            "max_results": 100,
            "default_license_type": "all"
        }
    
    def _install(self) -> Dict[str, Any]:
        """Install and verify OpenVerse API dependencies.
        
        Returns:
            Dict containing installation status and instructions
        """
        try:
            import aiohttp
            aiohttp_installed = True
        except ImportError:
            aiohttp_installed = False
        
        return {
            "status": "success" if aiohttp_installed else "incomplete",
            "dependencies": {
                "aiohttp": {
                    "installed": aiohttp_installed,
                    "required": True,
                    "install_command": "pip install aiohttp"
                }
            },
            "environment_variables": {
                "OPENVERSE_API_KEY": {
                    "set": bool(self.api_key),
                    "required": False,
                    "description": "OpenVerse API key (optional, increases rate limits)"
                }
            },
            "instructions": {
                "1": "Install aiohttp: pip install aiohttp" if not aiohttp_installed else "✓ Dependencies installed",
                "2": "Set OPENVERSE_API_KEY environment variable (optional)" if not self.api_key else "✓ API key configured",
                "3": "Get API key from: https://wordpress.org/openverse/register/"
            }
        }
    
    def _config(self, **kwargs) -> Dict[str, Any]:
        """Configure OpenVerse API settings.
        
        Args:
            **kwargs: Configuration options (api_url, timeout, max_results, etc.)
        
        Returns:
            Dict containing current configuration
        """
        # Update configuration with provided kwargs
        valid_config_keys = ["api_url", "timeout", "max_results", "default_license_type"]
        
        for key, value in kwargs.items():
            if key in valid_config_keys:
                self.config[key] = value
            elif key == "api_key":
                self.api_key = value
        
        return {
            "status": "success",
            "configuration": self.config,
            "api_key_set": bool(self.api_key),
            "valid_config_keys": valid_config_keys,
            "example": {
                "api_url": "https://api.openverse.org/v1",
                "timeout": 30,
                "max_results": 100,
                "default_license_type": "all"
            }
        }
    
    def _queue(self, operation: str, **params) -> Dict[str, Any]:
        """Queue a search operation for batch processing.
        
        Args:
            operation: Operation type ('search_images', 'search_audio', etc.)
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
        """Get current queue status.
        
        Returns:
            Dict containing queue information
        """
        return {
            "queue_length": len(self.queue),
            "queued_operations": self.queue,
            "operations_pending": len([item for item in self.queue if item["status"] == "queued"])
        }
    
    def clear_queue(self) -> Dict[str, Any]:
        """Clear all queued operations.
        
        Returns:
            Dict containing clear status
        """
        cleared_count = len(self.queue)
        self.queue = []
        
        return {
            "status": "success",
            "cleared_count": cleared_count,
            "message": f"Cleared {cleared_count} queued operations"
        }


async def search_openverse_images(
    query: str,
    api_key: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    license_type: Optional[str] = None,
    source: Optional[str] = None,
    creator: Optional[str] = None
) -> Dict[str, Any]:
    """Search OpenVerse for Creative Commons images.
    
    Args:
        query: Search query string
        api_key: OpenVerse API key (can also be set via OPENVERSE_API_KEY env var)
        page: Page number (default 1)
        page_size: Results per page (max 100, default 20)
        license_type: License type filter (e.g., 'cc0', 'pdm', 'by', 'by-sa')
        source: Source filter (e.g., 'flickr', 'wikimedia')
        creator: Creator/author filter
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of image results
            - result_count: Number of results
            - page_count: Total pages available
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
                }
            }
        
        if page < 1:
            return {
                "status": "error",
                "error": "Page number must be >= 1",
                "validation": {
                    "page": "Must be integer >= 1"
                }
            }
        
        if page_size < 1 or page_size > 100:
            return {
                "status": "error",
                "error": "Page size must be between 1 and 100",
                "validation": {
                    "page_size": "Must be integer between 1 and 100"
                }
            }
        
        # Get API key
        if api_key is None:
            api_key = os.environ.get("OPENVERSE_API_KEY")
        
        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required for OpenVerse. Install with: pip install aiohttp",
                "help": "Run: pip install aiohttp"
            }
        
        # OpenVerse API endpoint
        url = "https://api.openverse.org/v1/images/"
        
        # Prepare query parameters
        params = {
            "q": query,
            "page": page,
            "page_size": min(page_size, 100)
        }
        
        if license_type:
            params["license_type"] = license_type
        
        if source:
            params["source"] = source
        
        if creator:
            params["creator"] = creator
        
        # Set headers
        headers = {
            "Accept": "application/json"
        }
        
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        # Make the API request
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    for item in data.get("results", []):
                        results.append({
                            "id": item.get("id"),
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "thumbnail": item.get("thumbnail", ""),
                            "width": item.get("width"),
                            "height": item.get("height"),
                            "creator": item.get("creator", ""),
                            "creator_url": item.get("creator_url", ""),
                            "license": item.get("license", ""),
                            "license_version": item.get("license_version", ""),
                            "license_url": item.get("license_url", ""),
                            "source": item.get("source", ""),
                            "tags": item.get("tags", [])
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "result_count": data.get("result_count", 0),
                        "page_count": data.get("page_count", 0),
                        "page": page,
                        "query": query,
                        "search_timestamp": datetime.now().isoformat()
                    }
                elif response.status == 401:
                    return {
                        "status": "error",
                        "error": "Invalid OpenVerse API key",
                        "help": "Set OPENVERSE_API_KEY environment variable or pass api_key parameter"
                    }
                elif response.status == 429:
                    return {
                        "status": "error",
                        "error": "OpenVerse API rate limit exceeded",
                        "help": "Wait before retrying or get an API key to increase limits"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"OpenVerse API error (status {response.status}): {error_text}",
                        "help": "Check API documentation at https://api.openverse.org/v1/"
                    }
    
    except Exception as e:
        logger.error(f"Failed to search OpenVerse images: {e}")
        return {
            "status": "error",
            "error": str(e),
            "help": "Check parameters and network connection"
        }


async def search_openverse_audio(
    query: str,
    api_key: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    license_type: Optional[str] = None,
    source: Optional[str] = None
) -> Dict[str, Any]:
    """Search OpenVerse for Creative Commons audio.
    
    Args:
        query: Search query string
        api_key: OpenVerse API key
        page: Page number
        page_size: Results per page (max 100)
        license_type: License type filter
        source: Source filter
    
    Returns:
        Dict containing audio search results
    """
    try:
        # Input validation
        if not query or not isinstance(query, str):
            return {
                "status": "error",
                "error": "Query must be a non-empty string",
                "validation": {"query": "Required string parameter"}
            }
        
        if page < 1 or page_size < 1 or page_size > 100:
            return {
                "status": "error",
                "error": "Invalid page or page_size parameters",
                "validation": {
                    "page": "Must be integer >= 1",
                    "page_size": "Must be integer between 1 and 100"
                }
            }
        
        if api_key is None:
            api_key = os.environ.get("OPENVERSE_API_KEY")
        
        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required",
                "help": "Install with: pip install aiohttp"
            }
        
        url = "https://api.openverse.org/v1/audio/"
        
        params = {
            "q": query,
            "page": page,
            "page_size": min(page_size, 100)
        }
        
        if license_type:
            params["license_type"] = license_type
        if source:
            params["source"] = source
        
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    for item in data.get("results", []):
                        results.append({
                            "id": item.get("id"),
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                            "creator": item.get("creator", ""),
                            "duration": item.get("duration"),
                            "license": item.get("license", ""),
                            "license_url": item.get("license_url", ""),
                            "source": item.get("source", ""),
                            "tags": item.get("tags", [])
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "result_count": data.get("result_count", 0),
                        "page_count": data.get("page_count", 0),
                        "page": page,
                        "query": query,
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"OpenVerse API error (status {response.status}): {error_text}",
                        "help": "Check API documentation"
                    }
    
    except Exception as e:
        logger.error(f"Failed to search OpenVerse audio: {e}")
        return {
            "status": "error",
            "error": str(e),
            "help": "Check parameters and network connection"
        }


async def batch_search_openverse(
    queries: List[str],
    search_type: Literal["images", "audio"] = "images",
    api_key: Optional[str] = None,
    page_size: int = 20,
    delay_seconds: float = 0.5
) -> Dict[str, Any]:
    """Batch search OpenVerse with multiple queries.
    
    Args:
        queries: List of search queries
        search_type: Type of media to search
        api_key: OpenVerse API key
        page_size: Results per query
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
                "validation": {"queries": "Required list of strings"}
            }
        
        if not all(isinstance(q, str) for q in queries):
            return {
                "status": "error",
                "error": "All queries must be strings",
                "validation": {"queries": "All items must be strings"}
            }
        
        # Select search function
        search_func = search_openverse_images if search_type == "images" else search_openverse_audio
        
        results = {}
        success_count = 0
        error_count = 0
        
        for query in queries:
            result = await search_func(query=query, api_key=api_key, page_size=page_size)
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
            "search_type": search_type,
            "total_queries": len(queries),
            "success_count": success_count,
            "error_count": error_count,
            "batch_completed_at": datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"Failed batch OpenVerse search: {e}")
        return {
            "status": "error",
            "error": str(e),
            "help": "Check parameters and try again"
        }

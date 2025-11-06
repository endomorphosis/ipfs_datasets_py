"""HuggingFace Hub API search integration for model, dataset, and space discovery.

This tool provides integration with HuggingFace Hub API for searching models,
datasets, and spaces to enable AI/ML resource discovery and dataset creation.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import os

logger = logging.getLogger(__name__)


async def search_huggingface_models(
    query: Optional[str] = None,
    api_token: Optional[str] = None,
    filter_task: Optional[str] = None,
    filter_library: Optional[str] = None,
    filter_language: Optional[str] = None,
    sort: Literal["downloads", "created", "updated", "likes"] = "downloads",
    direction: int = -1,
    limit: int = 20
) -> Dict[str, Any]:
    """Search HuggingFace models.

    Args:
        query: Search query string (searches in model name, tags, description)
        api_token: HuggingFace API token (can also be set via HF_TOKEN env var)
        filter_task: Filter by task (e.g., "text-classification", "image-classification")
        filter_library: Filter by library (e.g., "transformers", "pytorch", "tensorflow")
        filter_language: Filter by language (e.g., "en", "fr", "multilingual")
        sort: Sort field
        direction: Sort direction (-1 for descending, 1 for ascending)
        limit: Maximum number of results to return

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of model results
            - total_count: Number of results returned
            - error: Error message (if failed)
    """
    try:
        # Get API token from parameter or environment
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required for HuggingFace Search. Install with: pip install aiohttp"
            }

        # HuggingFace API endpoint
        url = "https://huggingface.co/api/models"
        
        # Prepare query parameters
        params = {
            "limit": limit,
            "sort": sort,
            "direction": direction
        }
        
        if query:
            params["search"] = query
        
        if filter_task:
            params["filter"] = f"task:{filter_task}"
        
        if filter_library:
            if "filter" in params:
                params["filter"] += f",library:{filter_library}"
            else:
                params["filter"] = f"library:{filter_library}"
        
        if filter_language:
            if "filter" in params:
                params["filter"] += f",language:{filter_language}"
            else:
                params["filter"] = f"language:{filter_language}"

        # Set headers
        headers = {
            "Accept": "application/json"
        }
        
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        # Make the API request
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract model results
                    results = []
                    
                    for item in data:
                        results.append({
                            "id": item.get("id", item.get("modelId", "")),
                            "model_id": item.get("modelId", item.get("id", "")),
                            "author": item.get("author", ""),
                            "sha": item.get("sha", ""),
                            "created_at": item.get("createdAt", ""),
                            "last_modified": item.get("lastModified", ""),
                            "private": item.get("private", False),
                            "disabled": item.get("disabled", False),
                            "downloads": item.get("downloads", 0),
                            "likes": item.get("likes", 0),
                            "tags": item.get("tags", []),
                            "pipeline_tag": item.get("pipeline_tag", ""),
                            "library_name": item.get("library_name", ""),
                            "model_url": f"https://huggingface.co/{item.get('modelId', item.get('id', ''))}",
                            "card_data": item.get("cardData", {})
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": len(results),
                        "query": query,
                        "filters": {
                            "task": filter_task,
                            "library": filter_library,
                            "language": filter_language
                        },
                        "search_timestamp": datetime.now().isoformat()
                    }
                elif response.status == 401:
                    return {
                        "status": "error",
                        "error": "Invalid HuggingFace API token"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"HuggingFace API error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search HuggingFace models: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def search_huggingface_datasets(
    query: Optional[str] = None,
    api_token: Optional[str] = None,
    filter_task: Optional[str] = None,
    filter_language: Optional[str] = None,
    filter_size: Optional[str] = None,
    sort: Literal["downloads", "created", "updated", "likes"] = "downloads",
    direction: int = -1,
    limit: int = 20
) -> Dict[str, Any]:
    """Search HuggingFace datasets.

    Args:
        query: Search query string
        api_token: HuggingFace API token
        filter_task: Filter by task category
        filter_language: Filter by language
        filter_size: Filter by dataset size (e.g., "n<1K", "1K<n<10K", "10K<n<100K")
        sort: Sort field
        direction: Sort direction
        limit: Maximum number of results

    Returns:
        Dict containing dataset search results
    """
    try:
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        url = "https://huggingface.co/api/datasets"
        
        params = {
            "limit": limit,
            "sort": sort,
            "direction": direction
        }
        
        if query:
            params["search"] = query
        
        if filter_task:
            params["filter"] = f"task_categories:{filter_task}"
        
        if filter_language:
            if "filter" in params:
                params["filter"] += f",language:{filter_language}"
            else:
                params["filter"] = f"language:{filter_language}"
        
        if filter_size:
            if "filter" in params:
                params["filter"] += f",size_categories:{filter_size}"
            else:
                params["filter"] = f"size_categories:{filter_size}"

        headers = {
            "Accept": "application/json"
        }
        
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    
                    for item in data:
                        results.append({
                            "id": item.get("id", ""),
                            "dataset_id": item.get("id", ""),
                            "author": item.get("author", ""),
                            "sha": item.get("sha", ""),
                            "created_at": item.get("createdAt", ""),
                            "last_modified": item.get("lastModified", ""),
                            "private": item.get("private", False),
                            "disabled": item.get("disabled", False),
                            "downloads": item.get("downloads", 0),
                            "likes": item.get("likes", 0),
                            "tags": item.get("tags", []),
                            "description": item.get("description", ""),
                            "dataset_url": f"https://huggingface.co/datasets/{item.get('id', '')}",
                            "card_data": item.get("cardData", {})
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": len(results),
                        "query": query,
                        "filters": {
                            "task": filter_task,
                            "language": filter_language,
                            "size": filter_size
                        },
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"HuggingFace Datasets API error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search HuggingFace datasets: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def search_huggingface_spaces(
    query: Optional[str] = None,
    api_token: Optional[str] = None,
    filter_sdk: Optional[str] = None,
    sort: Literal["created", "updated", "likes"] = "likes",
    direction: int = -1,
    limit: int = 20
) -> Dict[str, Any]:
    """Search HuggingFace Spaces (demo applications).

    Args:
        query: Search query string
        api_token: HuggingFace API token
        filter_sdk: Filter by SDK (e.g., "gradio", "streamlit", "static")
        sort: Sort field
        direction: Sort direction
        limit: Maximum number of results

    Returns:
        Dict containing spaces search results
    """
    try:
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        url = "https://huggingface.co/api/spaces"
        
        params = {
            "limit": limit,
            "sort": sort,
            "direction": direction
        }
        
        if query:
            params["search"] = query
        
        if filter_sdk:
            params["filter"] = f"sdk:{filter_sdk}"

        headers = {
            "Accept": "application/json"
        }
        
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    
                    for item in data:
                        results.append({
                            "id": item.get("id", ""),
                            "space_id": item.get("id", ""),
                            "author": item.get("author", ""),
                            "sha": item.get("sha", ""),
                            "created_at": item.get("createdAt", ""),
                            "last_modified": item.get("lastModified", ""),
                            "private": item.get("private", False),
                            "sdk": item.get("sdk", ""),
                            "likes": item.get("likes", 0),
                            "tags": item.get("tags", []),
                            "space_url": f"https://huggingface.co/spaces/{item.get('id', '')}",
                            "card_data": item.get("cardData", {})
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": len(results),
                        "query": query,
                        "filters": {
                            "sdk": filter_sdk
                        },
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"HuggingFace Spaces API error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search HuggingFace spaces: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def get_huggingface_model_info(
    model_id: str,
    api_token: Optional[str] = None
) -> Dict[str, Any]:
    """Get detailed information about a specific HuggingFace model.

    Args:
        model_id: Model ID (e.g., "bert-base-uncased")
        api_token: HuggingFace API token

    Returns:
        Dict containing detailed model information
    """
    try:
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        url = f"https://huggingface.co/api/models/{model_id}"

        headers = {
            "Accept": "application/json"
        }
        
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    return {
                        "status": "success",
                        "model_info": {
                            "id": data.get("id", data.get("modelId", "")),
                            "author": data.get("author", ""),
                            "sha": data.get("sha", ""),
                            "created_at": data.get("createdAt", ""),
                            "last_modified": data.get("lastModified", ""),
                            "private": data.get("private", False),
                            "downloads": data.get("downloads", 0),
                            "likes": data.get("likes", 0),
                            "tags": data.get("tags", []),
                            "pipeline_tag": data.get("pipeline_tag", ""),
                            "library_name": data.get("library_name", ""),
                            "model_index": data.get("model-index", []),
                            "config": data.get("config", {}),
                            "siblings": data.get("siblings", []),
                            "card_data": data.get("cardData", {})
                        },
                        "retrieved_at": datetime.now().isoformat()
                    }
                elif response.status == 404:
                    return {
                        "status": "error",
                        "error": f"Model not found: {model_id}"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"HuggingFace API error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to get HuggingFace model info: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def batch_search_huggingface(
    queries: List[str],
    search_type: Literal["models", "datasets", "spaces"] = "models",
    api_token: Optional[str] = None,
    limit: int = 20,
    delay_seconds: float = 0.5
) -> Dict[str, Any]:
    """Batch search HuggingFace with multiple queries.

    Args:
        queries: List of search queries
        search_type: Type of resource to search
        api_token: HuggingFace API token
        limit: Number of results per query
        delay_seconds: Delay between requests

    Returns:
        Dict containing batch search results
    """
    try:
        import asyncio
        
        # Select the appropriate search function
        search_func = {
            "models": search_huggingface_models,
            "datasets": search_huggingface_datasets,
            "spaces": search_huggingface_spaces
        }.get(search_type, search_huggingface_models)
        
        results = {}
        success_count = 0
        error_count = 0
        
        for query in queries:
            result = await search_func(query=query, api_token=api_token, limit=limit)
            results[query] = result
            
            if result['status'] == 'success':
                success_count += 1
            else:
                error_count += 1
            
            # Add delay between requests
            if query != queries[-1]:
                await asyncio.sleep(delay_seconds)
        
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
        logger.error(f"Failed batch HuggingFace search: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

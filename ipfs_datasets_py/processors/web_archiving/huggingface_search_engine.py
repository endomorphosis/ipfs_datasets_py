"""HuggingFace Hub API search engine — canonical domain module.

This module contains the core domain logic for searching the HuggingFace Hub API.
It is imported by the MCP tool at:
  ipfs_datasets_py.mcp_server.tools.web_archive_tools.huggingface_search

Usage (package import)::

    from ipfs_datasets_py.web_archiving.huggingface_search_engine import (
        search_huggingface_models,
        search_huggingface_datasets,
        search_huggingface_spaces,
        get_huggingface_model_info,
        batch_search_huggingface,
    )
"""
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


async def search_huggingface_models(
    query: Optional[str] = None,
    api_token: Optional[str] = None,
    filter_task: Optional[str] = None,
    filter_library: Optional[str] = None,
    filter_language: Optional[str] = None,
    sort: Literal["downloads", "created", "updated", "likes"] = "downloads",
    direction: int = -1,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search HuggingFace models via Hub API."""
    try:
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required. Install with: pip install aiohttp",
            }

        url = "https://huggingface.co/api/models"
        params: Dict[str, Any] = {"limit": limit, "sort": sort, "direction": direction}
        if query:
            params["search"] = query
        if filter_task:
            params["filter"] = f"task:{filter_task}"
        if filter_library:
            params["filter"] = params.get("filter", "") + f",library:{filter_library}" if "filter" in params else f"library:{filter_library}"
        if filter_language:
            params["filter"] = params.get("filter", "") + f",language:{filter_language}" if "filter" in params else f"language:{filter_language}"

        headers = {"Accept": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    results = [
                        {
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
                            "card_data": item.get("cardData", {}),
                        }
                        for item in data
                    ]
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": len(results),
                        "query": query,
                        "filters": {"task": filter_task, "library": filter_library, "language": filter_language},
                        "search_timestamp": datetime.now().isoformat(),
                    }
                elif response.status == 401:
                    return {"status": "error", "error": "Invalid HuggingFace API token"}
                else:
                    error_text = await response.text()
                    return {"status": "error", "error": f"HuggingFace API error ({response.status}): {error_text}"}
    except Exception as e:
        logger.error(f"Failed to search HuggingFace models: {e}")
        return {"status": "error", "error": str(e)}


async def search_huggingface_datasets(
    query: Optional[str] = None,
    api_token: Optional[str] = None,
    filter_task: Optional[str] = None,
    filter_language: Optional[str] = None,
    filter_size: Optional[str] = None,
    sort: Literal["downloads", "created", "updated", "likes"] = "downloads",
    direction: int = -1,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search HuggingFace datasets via Hub API."""
    try:
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")
        try:
            import aiohttp
        except ImportError:
            return {"status": "error", "error": "aiohttp library required"}

        url = "https://huggingface.co/api/datasets"
        params: Dict[str, Any] = {"limit": limit, "sort": sort, "direction": direction}
        if query:
            params["search"] = query
        if filter_task:
            params["filter"] = f"task_categories:{filter_task}"
        if filter_language:
            params["filter"] = params.get("filter", "") + f",language:{filter_language}" if "filter" in params else f"language:{filter_language}"
        if filter_size:
            params["filter"] = params.get("filter", "") + f",size_categories:{filter_size}" if "filter" in params else f"size_categories:{filter_size}"

        headers = {"Accept": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    results = [
                        {
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
                            "card_data": item.get("cardData", {}),
                        }
                        for item in data
                    ]
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": len(results),
                        "query": query,
                        "filters": {"task": filter_task, "language": filter_language, "size": filter_size},
                        "search_timestamp": datetime.now().isoformat(),
                    }
                else:
                    error_text = await response.text()
                    return {"status": "error", "error": f"HuggingFace Datasets API error ({response.status}): {error_text}"}
    except Exception as e:
        logger.error(f"Failed to search HuggingFace datasets: {e}")
        return {"status": "error", "error": str(e)}


async def search_huggingface_spaces(
    query: Optional[str] = None,
    api_token: Optional[str] = None,
    filter_sdk: Optional[str] = None,
    sort: Literal["created", "updated", "likes"] = "likes",
    direction: int = -1,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search HuggingFace Spaces (demo applications)."""
    try:
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")
        try:
            import aiohttp
        except ImportError:
            return {"status": "error", "error": "aiohttp library required"}

        url = "https://huggingface.co/api/spaces"
        params: Dict[str, Any] = {"limit": limit, "sort": sort, "direction": direction}
        if query:
            params["search"] = query
        if filter_sdk:
            params["filter"] = f"sdk:{filter_sdk}"

        headers = {"Accept": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    results = [
                        {
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
                            "card_data": item.get("cardData", {}),
                        }
                        for item in data
                    ]
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": len(results),
                        "query": query,
                        "filters": {"sdk": filter_sdk},
                        "search_timestamp": datetime.now().isoformat(),
                    }
                else:
                    error_text = await response.text()
                    return {"status": "error", "error": f"HuggingFace Spaces API error ({response.status}): {error_text}"}
    except Exception as e:
        logger.error(f"Failed to search HuggingFace spaces: {e}")
        return {"status": "error", "error": str(e)}


async def get_huggingface_model_info(
    model_id: str,
    api_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Get detailed information about a specific HuggingFace model."""
    try:
        if api_token is None:
            api_token = os.environ.get("HF_TOKEN")
        try:
            import aiohttp
        except ImportError:
            return {"status": "error", "error": "aiohttp library required"}

        url = f"https://huggingface.co/api/models/{model_id}"
        headers = {"Accept": "application/json"}
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
                            "card_data": data.get("cardData", {}),
                        },
                        "retrieved_at": datetime.now().isoformat(),
                    }
                elif response.status == 404:
                    return {"status": "error", "error": f"Model not found: {model_id}"}
                else:
                    error_text = await response.text()
                    return {"status": "error", "error": f"HuggingFace API error ({response.status}): {error_text}"}
    except Exception as e:
        logger.error(f"Failed to get HuggingFace model info: {e}")
        return {"status": "error", "error": str(e)}


async def batch_search_huggingface(
    queries: List[str],
    search_type: Literal["models", "datasets", "spaces"] = "models",
    api_token: Optional[str] = None,
    limit: int = 20,
    delay_seconds: float = 0.5,
) -> Dict[str, Any]:
    """Batch search HuggingFace with multiple queries."""
    try:
        import anyio

        search_func = {
            "models": search_huggingface_models,
            "datasets": search_huggingface_datasets,
            "spaces": search_huggingface_spaces,
        }.get(search_type, search_huggingface_models)

        results: Dict[str, Any] = {}
        success_count = 0
        error_count = 0

        for query in queries:
            result = await search_func(query=query, api_token=api_token, limit=limit)
            results[query] = result
            if result["status"] == "success":
                success_count += 1
            else:
                error_count += 1
            if query != queries[-1]:
                await anyio.sleep(delay_seconds)

        return {
            "status": "success",
            "results": results,
            "search_type": search_type,
            "total_queries": len(queries),
            "success_count": success_count,
            "error_count": error_count,
            "batch_completed_at": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Failed batch HuggingFace search: {e}")
        return {"status": "error", "error": str(e)}

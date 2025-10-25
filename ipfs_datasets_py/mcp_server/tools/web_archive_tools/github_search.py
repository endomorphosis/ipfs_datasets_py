"""GitHub API search integration for repository and code discovery.

This tool provides integration with GitHub API for searching repositories,
code, users, and issues to enable dataset creation.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime
import os

logger = logging.getLogger(__name__)


async def search_github_repositories(
    query: str,
    api_token: Optional[str] = None,
    sort: Optional[Literal["stars", "forks", "help-wanted-issues", "updated"]] = None,
    order: Literal["asc", "desc"] = "desc",
    per_page: int = 30,
    page: int = 1
) -> Dict[str, Any]:
    """Search GitHub repositories.

    Args:
        query: Search query (supports GitHub search syntax)
        api_token: GitHub API token (can also be set via GITHUB_TOKEN env var)
        sort: Sort field for results
        order: Sort order (ascending or descending)
        per_page: Number of results per page (max 100)
        page: Page number for pagination

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of repository results
            - total_count: Total number of matching repositories
            - error: Error message (if failed)
    """
    try:
        # Get API token from parameter or environment
        if api_token is None:
            api_token = os.environ.get("GITHUB_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required for GitHub Search. Install with: pip install aiohttp"
            }

        # GitHub API endpoint
        url = "https://api.github.com/search/repositories"
        
        # Prepare query parameters
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "page": page,
            "order": order
        }
        
        if sort:
            params["sort"] = sort

        # Set headers
        headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        
        if api_token:
            headers["Authorization"] = f"token {api_token}"

        # Make the API request
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Extract repository results
                    results = []
                    items = data.get("items", [])
                    
                    for item in items:
                        results.append({
                            "id": item.get("id"),
                            "name": item.get("name", ""),
                            "full_name": item.get("full_name", ""),
                            "owner": item.get("owner", {}).get("login", ""),
                            "description": item.get("description", ""),
                            "url": item.get("html_url", ""),
                            "clone_url": item.get("clone_url", ""),
                            "stars": item.get("stargazers_count", 0),
                            "forks": item.get("forks_count", 0),
                            "watchers": item.get("watchers_count", 0),
                            "open_issues": item.get("open_issues_count", 0),
                            "language": item.get("language", ""),
                            "topics": item.get("topics", []),
                            "created_at": item.get("created_at", ""),
                            "updated_at": item.get("updated_at", ""),
                            "pushed_at": item.get("pushed_at", ""),
                            "size": item.get("size", 0),
                            "default_branch": item.get("default_branch", ""),
                            "license": item.get("license", {}).get("name", "") if item.get("license") else ""
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": data.get("total_count", 0),
                        "incomplete_results": data.get("incomplete_results", False),
                        "query": query,
                        "search_timestamp": datetime.now().isoformat()
                    }
                elif response.status == 403:
                    return {
                        "status": "error",
                        "error": "GitHub API rate limit exceeded. Provide a token or wait for rate limit reset."
                    }
                elif response.status == 422:
                    error_data = await response.json()
                    return {
                        "status": "error",
                        "error": f"Invalid search query: {error_data.get('message', 'Unknown error')}"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"GitHub API error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search GitHub repositories: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def search_github_code(
    query: str,
    api_token: Optional[str] = None,
    sort: Optional[Literal["indexed"]] = None,
    order: Literal["asc", "desc"] = "desc",
    per_page: int = 30,
    page: int = 1
) -> Dict[str, Any]:
    """Search code on GitHub.

    Args:
        query: Search query (supports GitHub code search syntax)
        api_token: GitHub API token
        sort: Sort field (only "indexed" is supported)
        order: Sort order
        per_page: Number of results per page (max 100)
        page: Page number for pagination

    Returns:
        Dict containing code search results
    """
    try:
        # Get API token from parameter or environment
        if api_token is None:
            api_token = os.environ.get("GITHUB_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        url = "https://api.github.com/search/code"
        
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "page": page,
            "order": order
        }
        
        if sort:
            params["sort"] = sort

        headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        
        if api_token:
            headers["Authorization"] = f"token {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    items = data.get("items", [])
                    
                    for item in items:
                        results.append({
                            "name": item.get("name", ""),
                            "path": item.get("path", ""),
                            "sha": item.get("sha", ""),
                            "url": item.get("html_url", ""),
                            "git_url": item.get("git_url", ""),
                            "repository": {
                                "id": item.get("repository", {}).get("id"),
                                "name": item.get("repository", {}).get("name", ""),
                                "full_name": item.get("repository", {}).get("full_name", ""),
                                "owner": item.get("repository", {}).get("owner", {}).get("login", ""),
                                "url": item.get("repository", {}).get("html_url", "")
                            }
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": data.get("total_count", 0),
                        "incomplete_results": data.get("incomplete_results", False),
                        "query": query,
                        "search_timestamp": datetime.now().isoformat()
                    }
                elif response.status == 403:
                    return {
                        "status": "error",
                        "error": "GitHub API rate limit exceeded or authentication required for code search"
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"GitHub Code Search error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search GitHub code: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def search_github_users(
    query: str,
    api_token: Optional[str] = None,
    sort: Optional[Literal["followers", "repositories", "joined"]] = None,
    order: Literal["asc", "desc"] = "desc",
    per_page: int = 30,
    page: int = 1
) -> Dict[str, Any]:
    """Search GitHub users.

    Args:
        query: Search query
        api_token: GitHub API token
        sort: Sort field
        order: Sort order
        per_page: Number of results per page
        page: Page number for pagination

    Returns:
        Dict containing user search results
    """
    try:
        if api_token is None:
            api_token = os.environ.get("GITHUB_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        url = "https://api.github.com/search/users"
        
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "page": page,
            "order": order
        }
        
        if sort:
            params["sort"] = sort

        headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        
        if api_token:
            headers["Authorization"] = f"token {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    items = data.get("items", [])
                    
                    for item in items:
                        results.append({
                            "id": item.get("id"),
                            "login": item.get("login", ""),
                            "url": item.get("html_url", ""),
                            "avatar_url": item.get("avatar_url", ""),
                            "type": item.get("type", ""),
                            "site_admin": item.get("site_admin", False),
                            "score": item.get("score", 0)
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": data.get("total_count", 0),
                        "incomplete_results": data.get("incomplete_results", False),
                        "query": query,
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"GitHub User Search error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search GitHub users: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def search_github_issues(
    query: str,
    api_token: Optional[str] = None,
    sort: Optional[Literal["comments", "reactions", "created", "updated"]] = None,
    order: Literal["asc", "desc"] = "desc",
    per_page: int = 30,
    page: int = 1
) -> Dict[str, Any]:
    """Search GitHub issues and pull requests.

    Args:
        query: Search query (use "is:issue" or "is:pr" to filter)
        api_token: GitHub API token
        sort: Sort field
        order: Sort order
        per_page: Number of results per page
        page: Page number for pagination

    Returns:
        Dict containing issue/PR search results
    """
    try:
        if api_token is None:
            api_token = os.environ.get("GITHUB_TOKEN")

        try:
            import aiohttp
        except ImportError:
            return {
                "status": "error",
                "error": "aiohttp library required"
            }

        url = "https://api.github.com/search/issues"
        
        params = {
            "q": query,
            "per_page": min(per_page, 100),
            "page": page,
            "order": order
        }
        
        if sort:
            params["sort"] = sort

        headers = {
            "Accept": "application/vnd.github.v3+json"
        }
        
        if api_token:
            headers["Authorization"] = f"token {api_token}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    results = []
                    items = data.get("items", [])
                    
                    for item in items:
                        results.append({
                            "id": item.get("id"),
                            "number": item.get("number"),
                            "title": item.get("title", ""),
                            "state": item.get("state", ""),
                            "url": item.get("html_url", ""),
                            "user": item.get("user", {}).get("login", ""),
                            "labels": [label.get("name") for label in item.get("labels", [])],
                            "created_at": item.get("created_at", ""),
                            "updated_at": item.get("updated_at", ""),
                            "closed_at": item.get("closed_at", ""),
                            "comments": item.get("comments", 0),
                            "pull_request": "pull_request" in item,
                            "repository_url": item.get("repository_url", ""),
                            "score": item.get("score", 0)
                        })
                    
                    return {
                        "status": "success",
                        "results": results,
                        "total_count": data.get("total_count", 0),
                        "incomplete_results": data.get("incomplete_results", False),
                        "query": query,
                        "search_timestamp": datetime.now().isoformat()
                    }
                else:
                    error_text = await response.text()
                    return {
                        "status": "error",
                        "error": f"GitHub Issue Search error (status {response.status}): {error_text}"
                    }

    except Exception as e:
        logger.error(f"Failed to search GitHub issues: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def batch_search_github(
    queries: List[str],
    search_type: Literal["repositories", "code", "users", "issues"] = "repositories",
    api_token: Optional[str] = None,
    per_page: int = 30,
    delay_seconds: float = 2.0
) -> Dict[str, Any]:
    """Batch search GitHub with multiple queries.

    Args:
        queries: List of search queries
        search_type: Type of search to perform
        api_token: GitHub API token
        per_page: Number of results per query
        delay_seconds: Delay between requests to respect rate limits

    Returns:
        Dict containing batch search results
    """
    try:
        import asyncio
        
        # Select the appropriate search function
        search_func = {
            "repositories": search_github_repositories,
            "code": search_github_code,
            "users": search_github_users,
            "issues": search_github_issues
        }.get(search_type, search_github_repositories)
        
        results = {}
        success_count = 0
        error_count = 0
        
        for query in queries:
            result = await search_func(query=query, api_token=api_token, per_page=per_page)
            results[query] = result
            
            if result['status'] == 'success':
                success_count += 1
            else:
                error_count += 1
            
            # Add delay between requests to respect rate limits
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
        logger.error(f"Failed batch GitHub search: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

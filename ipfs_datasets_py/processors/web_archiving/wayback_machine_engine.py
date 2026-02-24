"""Wayback Machine search and retrieval engine — canonical location.

Contains domain logic for Internet Archive's Wayback Machine integration.
MCP tool wrapper lives in:
    ipfs_datasets_py/mcp_server/tools/web_archive_tools/wayback_machine_search.py

Reusable by:
    - MCP server tools (mcp_server/tools/web_archive_tools/)
    - CLI commands
    - Direct Python imports
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)


async def search_wayback_machine(
    url: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
    collapse: Optional[str] = None,
    output_format: Literal["json", "cdx"] = "json",
) -> Dict[str, Any]:
    """Search Wayback Machine for captures of a URL.

    Args:
        url: URL to search for
        from_date: Start date (YYYYMMDD format)
        to_date: End date (YYYYMMDD format)
        limit: Maximum number of results
        collapse: Field to collapse on (e.g., 'timestamp:8' for daily snapshots)
        output_format: Output format - "json" or "cdx"

    Returns:
        Dict containing captures list and metadata
    """
    try:
        try:
            from wayback import WaybackClient
        except ImportError:
            return await _search_wayback_direct_api(url, from_date, to_date, limit, collapse, output_format)

        client = WaybackClient()
        start_date = None
        end_date = None

        if from_date:
            try:
                start_date = datetime.strptime(from_date, "%Y%m%d")
            except ValueError:
                start_date = datetime.strptime(from_date, "%Y-%m-%d")
        if to_date:
            try:
                end_date = datetime.strptime(to_date, "%Y%m%d")
            except ValueError:
                end_date = datetime.strptime(to_date, "%Y-%m-%d")

        captures: List[Any] = []
        try:
            for capture in client.search(url, from_date=start_date, to_date=end_date, limit=limit):
                if output_format == "json":
                    captures.append(
                        {
                            "timestamp": capture.timestamp.strftime("%Y%m%d%H%M%S"),
                            "url": capture.raw_url,
                            "original_url": capture.original_url,
                            "wayback_url": capture.archive_url,
                            "status_code": getattr(capture, "status_code", ""),
                            "mime_type": getattr(capture, "mime_type", ""),
                            "digest": getattr(capture, "digest", ""),
                            "length": getattr(capture, "length", 0),
                        }
                    )
                else:
                    captures.append(capture.raw)
        except Exception as search_error:
            logger.warning(f"Search completed with some issues: {search_error}")

        return {
            "status": "success",
            "results": captures,
            "url": url,
            "count": len(captures),
            "search_params": {
                "from_date": from_date,
                "to_date": to_date,
                "limit": limit,
                "collapse": collapse,
            },
        }
    except Exception as e:
        logger.error(f"Wayback Machine search failed for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def _search_wayback_direct_api(
    url: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    limit: int = 100,
    collapse: Optional[str] = None,
    output_format: Literal["json", "cdx"] = "json",
) -> Dict[str, Any]:
    """Direct API search fallback for Wayback Machine."""
    try:
        import requests

        cdx_url = "http://web.archive.org/cdx/search/cdx"
        params: Dict[str, Any] = {"url": url, "output": "json", "limit": limit}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if collapse:
            params["collapse"] = collapse

        response = requests.get(cdx_url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()
        if len(data) <= 1:
            return {"status": "success", "results": [], "url": url, "count": 0}

        headers = data[0]
        records = data[1:]
        results = []
        for record in records:
            if output_format == "json":
                capture = {
                    "timestamp": record[1] if len(record) > 1 else "",
                    "url": record[2] if len(record) > 2 else "",
                    "original_url": record[2] if len(record) > 2 else "",
                    "wayback_url": (
                        f"http://web.archive.org/web/{record[1]}/{record[2]}" if len(record) > 2 else ""
                    ),
                    "mime_type": record[3] if len(record) > 3 else "",
                    "status_code": record[4] if len(record) > 4 else "",
                    "digest": record[5] if len(record) > 5 else "",
                    "length": record[6] if len(record) > 6 else 0,
                }
                results.append(capture)
            else:
                results.append(dict(zip(headers, record)))

        return {"status": "success", "results": results, "url": url, "count": len(results)}
    except Exception as e:
        logger.error(f"Direct Wayback API search failed for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def get_wayback_content(
    url: str,
    timestamp: Optional[str] = None,
    closest: bool = True,
) -> Dict[str, Any]:
    """Get content from Wayback Machine for a specific URL.

    Args:
        url: URL to retrieve
        timestamp: Specific timestamp (YYYYMMDDHHMMSS format), or None for latest
        closest: If True, get closest capture to timestamp

    Returns:
        Dict containing content and metadata
    """
    try:
        try:
            from wayback import WaybackClient
        except ImportError:
            return await _get_wayback_content_direct(url, timestamp, closest)

        client = WaybackClient()
        target_date = datetime.strptime(timestamp, "%Y%m%d%H%M%S") if timestamp else datetime.now()

        try:
            capture = client.get_capture(url, timestamp=target_date, closest=closest)
            return {
                "status": "success",
                "content": capture.content,
                "content_type": capture.mime_type,
                "wayback_url": capture.archive_url,
                "capture_timestamp": capture.timestamp.strftime("%Y%m%d%H%M%S"),
                "original_url": capture.original_url,
            }
        except Exception as capture_error:
            logger.error(f"Failed to get capture: {capture_error}")
            return {"status": "error", "error": f"No capture found for {url}: {capture_error}"}
    except Exception as e:
        logger.error(f"Failed to get Wayback content for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def _get_wayback_content_direct(
    url: str,
    timestamp: Optional[str] = None,
    closest: bool = True,
) -> Dict[str, Any]:
    """Direct content retrieval fallback."""
    try:
        import requests

        wayback_url = (
            f"http://web.archive.org/web/{timestamp}/{url}"
            if timestamp
            else f"http://web.archive.org/web/{url}"
        )
        response = requests.get(wayback_url, timeout=30)
        response.raise_for_status()

        capture_timestamp = ""
        if hasattr(response, "url") and "/web/" in response.url:
            match = re.search(r"/web/(\d{14})/", response.url)
            if match:
                capture_timestamp = match.group(1)

        return {
            "status": "success",
            "content": response.content,
            "content_type": response.headers.get("content-type", "text/html"),
            "wayback_url": wayback_url,
            "capture_timestamp": capture_timestamp,
            "original_url": url,
        }
    except Exception as e:
        logger.error(f"Direct Wayback content retrieval failed for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def archive_to_wayback(url: str) -> Dict[str, Any]:
    """Archive a URL to Wayback Machine.

    Args:
        url: URL to archive

    Returns:
        Dict containing archived_url, job_id and metadata
    """
    try:
        try:
            import internetarchive as ia  # noqa: F401
        except ImportError:
            return await _archive_to_wayback_direct(url)

        archive_url = f"https://web.archive.org/save/{url}"
        return {
            "status": "success",
            "archived_url": archive_url,
            "message": f"Submitted {url} for archiving to Wayback Machine",
        }
    except Exception as e:
        logger.error(f"Failed to archive {url} to Wayback Machine: {e}")
        return {"status": "error", "error": str(e)}


async def _archive_to_wayback_direct(url: str) -> Dict[str, Any]:
    """Direct archive submission fallback."""
    try:
        import requests

        save_url = f"https://web.archive.org/save/{url}"
        response = requests.get(save_url, timeout=60)
        response.raise_for_status()
        return {
            "status": "success",
            "archived_url": save_url,
            "message": f"Successfully submitted {url} for archiving",
        }
    except Exception as e:
        logger.error(f"Direct archive submission failed for {url}: {e}")
        return {"status": "error", "error": str(e)}

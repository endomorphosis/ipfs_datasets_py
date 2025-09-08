"""Common Crawl search and data extraction using CDX Toolkit.

This tool provides access to Common Crawl datasets for large-scale web content analysis
using the CDX (Canonical Document Index) format.
"""
import logging
from typing import Dict, List, Optional, Any, Literal
from datetime import datetime

logger = logging.getLogger(__name__)

async def search_common_crawl(
    domain: str,
    crawl_id: Optional[str] = None,
    limit: int = 100,
    from_timestamp: Optional[str] = None,
    to_timestamp: Optional[str] = None,
    output_format: Literal['json', 'cdx'] = 'json'
) -> Dict[str, Any]:
    """Search Common Crawl data for a specific domain.

    Args:
        domain: Domain to search for (e.g., "example.com")
        crawl_id: Specific crawl ID (e.g., "CC-MAIN-2024-10"), defaults to latest
        limit: Maximum number of results to return
        from_timestamp: Start timestamp filter (YYYYMMDD format)
        to_timestamp: End timestamp filter (YYYYMMDD format)
        output_format: Output format - "json" or "cdx"

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of matching records
            - crawl_info: Information about the crawl used
            - count: Number of results returned
            - error: Error message (if failed)
    """
    try:
        # Try to import cdx_toolkit
        try:
            from cdx_toolkit import CDXFetcher
        except ImportError:
            return {
                "status": "error",
                "error": "cdx-toolkit not installed. Install with: pip install cdx-toolkit"
            }

        # Initialize CDX fetcher
        if crawl_id:
            cdx = CDXFetcher(source=crawl_id)
        else:
            # Use latest Common Crawl by default
            cdx = CDXFetcher(source='cc')

        # Build search query
        url_pattern = f"*.{domain}/*"
        
        # Search parameters
        kwargs = {
            'url': url_pattern,
            'limit': limit
        }
        
        if from_timestamp:
            kwargs['from_ts'] = from_timestamp
        if to_timestamp:
            kwargs['to_ts'] = to_timestamp

        # Perform search
        records = []
        try:
            for record in cdx.iter(**kwargs):
                if output_format == 'json':
                    records.append({
                        'url': record.data.get('url', ''),
                        'timestamp': record.data.get('timestamp', ''),
                        'status_code': record.data.get('status', ''),
                        'mime_type': record.data.get('mime', ''),
                        'digest': record.data.get('digest', ''),
                        'length': record.data.get('length', ''),
                        'warc_filename': record.data.get('filename', ''),
                        'warc_offset': record.data.get('offset', ''),
                    })
                else:  # cdx format
                    records.append(record.data)
        except Exception as search_error:
            logger.warning(f"Search completed with some errors: {search_error}")

        return {
            "status": "success",
            "results": records,
            "count": len(records),
            "crawl_info": {
                "source": crawl_id or "cc (latest)",
                "domain": domain,
                "search_timestamp": datetime.now().isoformat()
            }
        }

    except Exception as e:
        logger.error(f"Common Crawl search failed for domain {domain}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def get_common_crawl_content(
    url: str,
    timestamp: str,
    crawl_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get content from Common Crawl for a specific URL and timestamp.

    Args:
        url: URL to retrieve content for
        timestamp: Timestamp of the capture (YYYYMMDDHHMMSS format)
        crawl_id: Specific crawl ID to search in

    Returns:
        Dict containing:
            - status: "success" or "error"
            - content: Raw content (if successful)
            - content_type: MIME type of the content
            - headers: HTTP headers
            - error: Error message (if failed)
    """
    try:
        try:
            from cdx_toolkit import CDXFetcher
            import requests
        except ImportError as e:
            return {
                "status": "error",
                "error": f"Required libraries not installed: {e}"
            }

        # Initialize CDX fetcher
        if crawl_id:
            cdx = CDXFetcher(source=crawl_id)
        else:
            cdx = CDXFetcher(source='cc')

        # Find the specific record
        records = list(cdx.iter(url=url, from_ts=timestamp, to_ts=timestamp, limit=1))
        
        if not records:
            return {
                "status": "error",
                "error": "No records found for the specified URL and timestamp"
            }

        record = records[0]
        
        # Get WARC file URL and offset
        warc_url = f"https://commoncrawl.s3.amazonaws.com/{record.data.get('filename', '')}"
        offset = int(record.data.get('offset', 0))
        length = int(record.data.get('length', 0))

        # Download content from WARC
        headers = {'Range': f'bytes={offset}-{offset + length - 1}'}
        response = requests.get(warc_url, headers=headers, timeout=30)
        response.raise_for_status()

        return {
            "status": "success",
            "content": response.content,
            "content_type": record.data.get('mime', 'application/octet-stream'),
            "headers": dict(response.headers),
            "warc_info": {
                "filename": record.data.get('filename', ''),
                "offset": offset,
                "length": length,
                "digest": record.data.get('digest', '')
            }
        }

    except Exception as e:
        logger.error(f"Failed to get Common Crawl content for {url}: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

async def list_common_crawl_indexes() -> Dict[str, Any]:
    """List available Common Crawl indexes.

    Returns:
        Dict containing:
            - status: "success" or "error"
            - indexes: List of available crawl indexes
            - count: Number of available indexes
            - error: Error message (if failed)
    """
    try:
        try:
            from cdx_toolkit import CDXFetcher
        except ImportError:
            return {
                "status": "error",
                "error": "cdx-toolkit not installed. Install with: pip install cdx-toolkit"
            }

        # Get list of available indexes
        cdx = CDXFetcher()
        indexes = cdx.list_cc_datasets()

        return {
            "status": "success",
            "indexes": indexes,
            "count": len(indexes)
        }

    except Exception as e:
        logger.error(f"Failed to list Common Crawl indexes: {e}")
        return {
            "status": "error",
            "error": str(e)
        }
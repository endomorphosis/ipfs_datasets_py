"""
Common Crawl Multi-Index Search Integration

This module provides comprehensive Common Crawl searching across multiple indexes.
Each Common Crawl index is a delta/snapshot from a specific time period, so searching
across multiple indexes is essential for comprehensive coverage.

Example indexes:
- CC-MAIN-2025-47 (November 2025)
- CC-MAIN-2025-46 (October 2025)
- CC-MAIN-2025-45 (September 2025)
etc.

Usage:
    from ipfs_datasets_py.integrations import CommonCrawlClient
    
    client = CommonCrawlClient()
    # Search across all recent indexes
    results = client.search_multi_index("https://library.municode.com/*")
    
    # Search specific indexes
    results = client.search_multi_index(
        "https://library.municode.com/*",
        indexes=["CC-MAIN-2025-47", "CC-MAIN-2025-46"]
    )
"""

import asyncio
import logging
import httpx
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class CommonCrawlRecord:
    """A single record from Common Crawl."""
    url: str
    timestamp: str
    digest: str
    mime_type: str
    status: int
    filename: str
    offset: int
    length: int
    index: str  # Which CC index this came from
    warc_record_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "timestamp": self.timestamp,
            "digest": self.digest,
            "mime_type": self.mime_type,
            "status": self.status,
            "filename": self.filename,
            "offset": self.offset,
            "length": self.length,
            "index": self.index,
            "warc_record_id": self.warc_record_id
        }


class CommonCrawlClient:
    """
    Client for searching Common Crawl indexes.
    
    This client searches across multiple Common Crawl indexes since each index
    is a snapshot/delta from a specific time period. Comprehensive searches
    require checking multiple indexes.
    """
    
    # Default indexes to search (most recent first)
    DEFAULT_INDEXES = [
        "CC-MAIN-2025-47",
        "CC-MAIN-2025-46",
        "CC-MAIN-2025-45",
        "CC-MAIN-2025-44",
        "CC-MAIN-2025-43",
        "CC-MAIN-2024-51",  # Going back further
        "CC-MAIN-2024-50",
        "CC-MAIN-2024-49",
        "CC-MAIN-2024-48",
        "CC-MAIN-2024-47",
    ]
    
    INDEX_URL_TEMPLATE = "https://index.commoncrawl.org/{index}-index"
    
    def __init__(self, timeout: int = 30, max_results_per_index: int = 100):
        """
        Initialize Common Crawl client.
        
        Args:
            timeout: HTTP request timeout in seconds
            max_results_per_index: Maximum results to fetch per index
        """
        self.timeout = timeout
        self.max_results_per_index = max_results_per_index
        self.client = httpx.AsyncClient(timeout=timeout)
    
    async def search_single_index(
        self, 
        url_pattern: str, 
        index: str
    ) -> List[CommonCrawlRecord]:
        """
        Search a single Common Crawl index.
        
        Args:
            url_pattern: URL or URL pattern to search (supports * wildcard)
            index: Common Crawl index name (e.g., "CC-MAIN-2025-47")
        
        Returns:
            List of CommonCrawlRecord objects found in this index
        """
        index_url = self.INDEX_URL_TEMPLATE.format(index=index)
        
        try:
            response = await self.client.get(
                index_url,
                params={
                    "url": url_pattern,
                    "output": "json",
                    "limit": self.max_results_per_index
                }
            )
            response.raise_for_status()
            
            records = []
            for line in response.text.strip().split('\n'):
                if not line:
                    continue
                try:
                    data = eval(line)  # CC returns Python dict format
                    record = CommonCrawlRecord(
                        url=data.get('url', ''),
                        timestamp=data.get('timestamp', ''),
                        digest=data.get('digest', ''),
                        mime_type=data.get('mime', ''),
                        status=int(data.get('status', 0)),
                        filename=data.get('filename', ''),
                        offset=int(data.get('offset', 0)),
                        length=int(data.get('length', 0)),
                        index=index
                    )
                    records.append(record)
                except Exception as e:
                    logger.warning(f"Failed to parse CC record: {e}")
                    continue
            
            logger.info(f"Found {len(records)} records in {index} for {url_pattern}")
            return records
        
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.warning(f"No results in {index} for {url_pattern}")
                return []
            else:
                logger.error(f"HTTP error searching {index}: {e}")
                return []
        except Exception as e:
            logger.error(f"Error searching {index}: {e}")
            return []
    
    async def search_multi_index(
        self,
        url_pattern: str,
        indexes: Optional[List[str]] = None,
        deduplicate: bool = True
    ) -> List[CommonCrawlRecord]:
        """
        Search across multiple Common Crawl indexes.
        
        Since each CC index is a snapshot/delta, searching multiple indexes
        provides more comprehensive coverage. This method searches in parallel.
        
        Args:
            url_pattern: URL or URL pattern (supports * wildcard)
            indexes: List of index names to search (default: most recent 10)
            deduplicate: Remove duplicate URLs (default: True)
        
        Returns:
            List of CommonCrawlRecord objects from all indexes
        """
        indexes = indexes or self.DEFAULT_INDEXES
        
        logger.info(f"Searching {len(indexes)} Common Crawl indexes for: {url_pattern}")
        
        # Search all indexes in parallel
        tasks = [
            self.search_single_index(url_pattern, index)
            for index in indexes
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Flatten results
        all_records = []
        for result in results_list:
            if isinstance(result, list):
                all_records.extend(result)
            elif isinstance(result, Exception):
                logger.warning(f"Search task failed: {result}")
        
        # Deduplicate by URL if requested
        if deduplicate:
            seen_urls = set()
            unique_records = []
            for record in all_records:
                if record.url not in seen_urls:
                    seen_urls.add(record.url)
                    unique_records.append(record)
            
            logger.info(f"Found {len(all_records)} total records, "
                       f"{len(unique_records)} unique URLs")
            return unique_records
        
        return all_records
    
    def search_multi_index_sync(
        self,
        url_pattern: str,
        indexes: Optional[List[str]] = None,
        deduplicate: bool = True
    ) -> List[CommonCrawlRecord]:
        """Synchronous version of search_multi_index."""
        return asyncio.run(self.search_multi_index(url_pattern, indexes, deduplicate))
    
    async def fetch_warc_record(
        self,
        record: CommonCrawlRecord
    ) -> Optional[bytes]:
        """
        Fetch the actual WARC record content for a Common Crawl record.
        
        Args:
            record: CommonCrawlRecord with filename, offset, length
        
        Returns:
            WARC record bytes or None if failed
        """
        warc_url = f"https://data.commoncrawl.org/{record.filename}"
        
        try:
            # Use range request to fetch specific byte range
            headers = {
                'Range': f'bytes={record.offset}-{record.offset + record.length - 1}'
            }
            
            response = await self.client.get(warc_url, headers=headers)
            response.raise_for_status()
            
            logger.info(f"Fetched WARC record for {record.url} ({len(response.content)} bytes)")
            return response.content
        
        except Exception as e:
            logger.error(f"Failed to fetch WARC record for {record.url}: {e}")
            return None
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()
    
    def __del__(self):
        """Cleanup."""
        try:
            asyncio.run(self.close())
        except:
            pass


# Convenience function for quick searches
def search_common_crawl(
    url_pattern: str,
    indexes: Optional[List[str]] = None,
    max_results_per_index: int = 100
) -> List[CommonCrawlRecord]:
    """
    Quick search across Common Crawl indexes.
    
    Args:
        url_pattern: URL or pattern to search
        indexes: Optional list of indexes (default: most recent 10)
        max_results_per_index: Max results per index
    
    Returns:
        List of CommonCrawlRecord objects
    
    Example:
        records = search_common_crawl("https://library.municode.com/*")
        for record in records:
            print(f"{record.url} from {record.index}")
    """
    client = CommonCrawlClient(max_results_per_index=max_results_per_index)
    return client.search_multi_index_sync(url_pattern, indexes)

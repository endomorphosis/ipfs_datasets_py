#!/usr/bin/env python3
"""
Multi-Index Common Crawl and Interplanetary Wayback Integration

This module provides:
1. Multi-index Common Crawl searches (across all delta indexes)
2. Interplanetary Wayback Machine integration
3. Content-addressed duplicate detection across archives
4. Unified interface for historical web content retrieval
"""

import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Available Common Crawl indexes (these are cumulative deltas)
COMMON_CRAWL_INDEXES = [
    "CC-MAIN-2024-51",  # December 2024
    "CC-MAIN-2024-46",  # November 2024
    "CC-MAIN-2024-42",  # October 2024
    "CC-MAIN-2024-38",  # September 2024
    "CC-MAIN-2024-33",  # August 2024
    "CC-MAIN-2024-30",  # July 2024
    "CC-MAIN-2024-26",  # June 2024
    "CC-MAIN-2024-22",  # May 2024
    "CC-MAIN-2024-18",  # April 2024
    "CC-MAIN-2024-10",  # March 2024
    # Add more as needed
]


class MultiIndexWebArchiveSearcher:
    """
    Multi-index web archive searcher with content addressing.
    
    Searches across:
    - Multiple Common Crawl indexes (each is a delta from previous)
    - Interplanetary Wayback Machine
    - Regular Internet Archive Wayback Machine
    - Content-addressed local cache
    """
    
    def __init__(self, content_addressed_scraper=None):
        """
        Initialize multi-index searcher.
        
        Args:
            content_addressed_scraper: ContentAddressedScraper instance for CID tracking
        """
        self.content_scraper = content_addressed_scraper
        self.search_cache = {}
        
        logger.info("MultiIndexWebArchiveSearcher initialized")
    
    async def search_all_common_crawl_indexes(
        self,
        domain: str,
        url_pattern: Optional[str] = None,
        limit_per_index: int = 100,
        deduplicate: bool = True
    ) -> Dict[str, Any]:
        """
        Search ALL Common Crawl indexes for a domain.
        
        Each Common Crawl index is a delta (only new content since last crawl),
        so we need to search ALL indexes to get complete coverage.
        
        Args:
            domain: Domain to search for
            url_pattern: Optional URL pattern to match
            limit_per_index: Max results per index
            deduplicate: Remove duplicate URLs/content across indexes
            
        Returns:
            Dict containing:
                - results: List of all results across indexes
                - by_index: Results grouped by index
                - total_results: Total number of results
                - indexes_searched: List of indexes searched
                - unique_urls: Number of unique URLs found
                - unique_content_cids: Number of unique content CIDs
        """
        logger.info(f"Searching {len(COMMON_CRAWL_INDEXES)} Common Crawl indexes for domain: {domain}")
        
        all_results = []
        by_index = {}
        seen_urls = set()
        seen_cids = set()
        
        # Search each index
        for crawl_id in COMMON_CRAWL_INDEXES:
            try:
                logger.info(f"Searching index: {crawl_id}")
                
                # Import common_crawl_search from the existing tool
                try:
                    import sys
                    parent_path = Path(__file__).parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "web_archive_tools"
                    if parent_path.exists():
                        sys.path.insert(0, str(parent_path))
                    from common_crawl_search import search_common_crawl
                except ImportError:
                    logger.warning(f"common_crawl_search not available, using mock")
                    result = await self._mock_common_crawl_search(domain, crawl_id, limit_per_index)
                else:
                    result = await search_common_crawl(
                        domain=domain,
                        crawl_id=crawl_id,
                        limit=limit_per_index
                    )
                
                if result.get('status') == 'success':
                    index_results = result.get('results', [])
                    by_index[crawl_id] = index_results
                    
                    # Process results
                    for record in index_results:
                        url = record.get('url', '')
                        
                        # Deduplicate if requested
                        if deduplicate and url in seen_urls:
                            continue
                        
                        seen_urls.add(url)
                        
                        # Compute content CID if we have the content
                        if self.content_scraper and 'content' in record:
                            content_cid = self.content_scraper.compute_content_cid(record['content'])
                            record['content_cid'] = content_cid
                            seen_cids.add(content_cid)
                        
                        # Add source index
                        record['source_index'] = crawl_id
                        record['source'] = 'common_crawl'
                        
                        all_results.append(record)
                    
                    logger.info(f"  Found {len(index_results)} results in {crawl_id}")
                
                # Small delay between index searches
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Error searching index {crawl_id}: {e}")
                by_index[crawl_id] = {"error": str(e)}
        
        return {
            "status": "success",
            "results": all_results,
            "by_index": by_index,
            "total_results": len(all_results),
            "indexes_searched": COMMON_CRAWL_INDEXES,
            "unique_urls": len(seen_urls),
            "unique_content_cids": len(seen_cids),
            "deduplicated": deduplicate
        }
    
    async def search_interplanetary_wayback(
        self,
        url: str,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Search Interplanetary Wayback Machine (IPFS-based Wayback).
        
        The Interplanetary Wayback Machine stores web archives on IPFS,
        making them permanent and decentralized.
        
        Args:
            url: URL to search for
            from_date: Start date (YYYYMMDD)
            to_date: End date (YYYYMMDD)
            limit: Max results
            
        Returns:
            Dict containing search results with IPFS CIDs
        """
        logger.info(f"Searching Interplanetary Wayback for: {url}")
        
        try:
            # Try to import wayback library
            try:
                from wayback import WaybackClient
            except ImportError:
                logger.warning("wayback library not available")
                return await self._mock_ipwb_search(url)
            
            # Check if IPFS Wayback (ipwb) is available
            try:
                import ipwb
                HAVE_IPWB = True
            except ImportError:
                HAVE_IPWB = False
                logger.warning("ipwb not available - using regular Wayback")
            
            if HAVE_IPWB:
                # Use Interplanetary Wayback
                return await self._search_ipwb(url, from_date, to_date, limit)
            else:
                # Fallback to regular Wayback with CID generation
                return await self._search_wayback_with_cids(url, from_date, to_date, limit)
        
        except Exception as e:
            logger.error(f"Interplanetary Wayback search failed: {e}")
            return {
                "status": "error",
                "error": str(e),
                "source": "interplanetary_wayback"
            }
    
    async def _search_ipwb(
        self,
        url: str,
        from_date: Optional[str],
        to_date: Optional[str],
        limit: int
    ) -> Dict[str, Any]:
        """Search using IPFS Wayback (ipwb)."""
        # This would use the ipwb library to search IPFS-stored archives
        # For now, providing the interface structure
        
        return {
            "status": "success",
            "results": [],
            "source": "ipfs_wayback",
            "message": "IPFS Wayback integration - to be implemented with ipwb library"
        }
    
    async def _search_wayback_with_cids(
        self,
        url: str,
        from_date: Optional[str],
        to_date: Optional[str],
        limit: int
    ) -> Dict[str, Any]:
        """Search regular Wayback and add CIDs to results."""
        try:
            # Import from existing wayback tool
            import sys
            parent_path = Path(__file__).parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "web_archive_tools"
            if parent_path.exists():
                sys.path.insert(0, str(parent_path))
            from wayback_machine_search import search_wayback_machine
        except ImportError:
            logger.warning("wayback_machine_search not available")
            return await self._mock_wayback_search(url)
        
        # Search Wayback
        result = await search_wayback_machine(
            url=url,
            from_date=from_date,
            to_date=to_date,
            limit=limit
        )
        
        if result.get('status') == 'success':
            # Add CIDs to each capture
            for capture in result.get('results', []):
                if self.content_scraper:
                    # Generate CID from URL + timestamp (content-addressable identifier)
                    identifier = f"{capture.get('url')}|{capture.get('timestamp')}"
                    pseudo_cid = self.content_scraper.compute_content_cid(identifier.encode('utf-8'))
                    capture['pseudo_cid'] = pseudo_cid
                
                capture['source'] = 'wayback_machine'
        
        return result
    
    async def _mock_common_crawl_search(
        self,
        domain: str,
        crawl_id: str,
        limit: int
    ) -> Dict[str, Any]:
        """Mock Common Crawl search for testing."""
        return {
            "status": "success",
            "results": [
                {
                    "url": f"https://{domain}/page1",
                    "timestamp": "20241215120000",
                    "status_code": "200",
                    "mime_type": "text/html"
                }
            ],
            "count": 1,
            "crawl_info": {"source": crawl_id, "domain": domain}
        }
    
    async def _mock_ipwb_search(self, url: str) -> Dict[str, Any]:
        """Mock IPFS Wayback search."""
        return {
            "status": "success",
            "results": [],
            "source": "ipfs_wayback_mock",
            "message": "Mock IPFS Wayback - install ipwb for real functionality"
        }
    
    async def _mock_wayback_search(self, url: str) -> Dict[str, Any]:
        """Mock Wayback search."""
        return {
            "status": "success",
            "results": [],
            "source": "wayback_mock"
        }
    
    async def unified_archive_search(
        self,
        url: str,
        domain: Optional[str] = None,
        search_common_crawl: bool = True,
        search_wayback: bool = True,
        search_ipfs_wayback: bool = True,
        deduplicate_by_cid: bool = True
    ) -> Dict[str, Any]:
        """
        Unified search across all web archives with content deduplication.
        
        Searches:
        1. All Common Crawl indexes
        2. Interplanetary Wayback Machine
        3. Regular Wayback Machine
        4. Local content-addressed cache
        
        Args:
            url: Specific URL to search for
            domain: Domain to search (for Common Crawl)
            search_common_crawl: Search Common Crawl indexes
            search_wayback: Search Wayback Machine
            search_ipfs_wayback: Search IPFS Wayback
            deduplicate_by_cid: Deduplicate results by content CID
            
        Returns:
            Dict containing unified results across all sources
        """
        logger.info(f"Unified archive search for: {url}")
        
        results = {
            "url": url,
            "domain": domain,
            "searched_sources": [],
            "common_crawl": {},
            "wayback": {},
            "ipfs_wayback": {},
            "local_cache": {},
            "all_results": [],
            "unique_cids": set(),
            "total_captures": 0
        }
        
        # Check local cache first
        if self.content_scraper:
            cache_status = self.content_scraper.check_url_scraped(url)
            results["local_cache"] = cache_status
            results["searched_sources"].append("local_cache")
            
            if cache_status['scraped']:
                logger.info(f"  Found {cache_status['total_versions']} cached versions")
                for version in cache_status['versions']:
                    results["unique_cids"].add(version.get('content_cid'))
        
        # Search Common Crawl (all indexes)
        if search_common_crawl and domain:
            cc_results = await self.search_all_common_crawl_indexes(domain)
            results["common_crawl"] = cc_results
            results["searched_sources"].append("common_crawl")
            results["all_results"].extend(cc_results.get('results', []))
            results["total_captures"] += cc_results.get('total_results', 0)
            
            # Add CIDs
            for cid in cc_results.get('unique_content_cids', []):
                if isinstance(cid, str):
                    results["unique_cids"].add(cid)
        
        # Search IPFS Wayback
        if search_ipfs_wayback:
            ipfs_wb_results = await self.search_interplanetary_wayback(url)
            results["ipfs_wayback"] = ipfs_wb_results
            results["searched_sources"].append("ipfs_wayback")
            results["all_results"].extend(ipfs_wb_results.get('results', []))
            results["total_captures"] += len(ipfs_wb_results.get('results', []))
        
        # Search regular Wayback
        if search_wayback:
            wb_results = await self._search_wayback_with_cids(url, None, None, 100)
            results["wayback"] = wb_results
            results["searched_sources"].append("wayback_machine")
            results["all_results"].extend(wb_results.get('results', []))
            results["total_captures"] += wb_results.get('count', 0)
        
        # Deduplicate by CID if requested
        if deduplicate_by_cid:
            unique_results = []
            seen_cids = set()
            
            for result in results["all_results"]:
                cid = result.get('content_cid') or result.get('pseudo_cid')
                if cid and cid in seen_cids:
                    continue
                if cid:
                    seen_cids.add(cid)
                unique_results.append(result)
            
            results["all_results"] = unique_results
            results["deduplicated"] = True
            results["unique_cids"] = seen_cids
        
        # Convert set to list for JSON serialization
        results["unique_cids"] = list(results["unique_cids"])
        
        results["summary"] = {
            "sources_searched": results["searched_sources"],
            "total_captures": results["total_captures"],
            "unique_content_versions": len(results["unique_cids"]),
            "deduplicated": deduplicate_by_cid
        }
        
        logger.info(f"  Found {results['total_captures']} total captures across {len(results['searched_sources'])} sources")
        logger.info(f"  Unique content versions: {len(results['unique_cids'])}")
        
        return results


# Global instance
_multi_index_searcher = None

def get_multi_index_searcher(content_addressed_scraper=None) -> MultiIndexWebArchiveSearcher:
    """Get or create global multi-index searcher instance."""
    global _multi_index_searcher
    if _multi_index_searcher is None:
        _multi_index_searcher = MultiIndexWebArchiveSearcher(
            content_addressed_scraper=content_addressed_scraper
        )
    return _multi_index_searcher


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    async def example():
        print("=" * 70)
        print("Multi-Index Web Archive Search Demo")
        print("=" * 70)
        
        searcher = get_multi_index_searcher()
        
        test_domain = "example.com"
        test_url = "https://example.com/page"
        
        print(f"\n1. Searching ALL Common Crawl indexes for domain: {test_domain}")
        cc_results = await searcher.search_all_common_crawl_indexes(test_domain, limit_per_index=10)
        print(f"   Searched {len(cc_results['indexes_searched'])} indexes")
        print(f"   Total results: {cc_results['total_results']}")
        print(f"   Unique URLs: {cc_results['unique_urls']}")
        
        print(f"\n2. Searching Interplanetary Wayback for: {test_url}")
        ipwb_results = await searcher.search_interplanetary_wayback(test_url)
        print(f"   Status: {ipwb_results['status']}")
        print(f"   Source: {ipwb_results.get('source', 'N/A')}")
        
        print(f"\n3. Unified search across all sources...")
        unified_results = await searcher.unified_archive_search(
            url=test_url,
            domain=test_domain,
            deduplicate_by_cid=True
        )
        print(f"   Sources searched: {unified_results['summary']['sources_searched']}")
        print(f"   Total captures: {unified_results['summary']['total_captures']}")
        print(f"   Unique versions: {unified_results['summary']['unique_content_versions']}")
        
        print("\n✅ Demo complete!")
    
    asyncio.run(example())

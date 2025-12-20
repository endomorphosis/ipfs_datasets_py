#!/usr/bin/env python3
"""
Legal Data Scraper Unified Adapter

This adapter integrates all legal data scrapers with:
1. Unified scraping architecture with fallbacks
2. Content-addressed storage and deduplication
3. Multi-index Common Crawl and archive search
4. IPFS integration for permanent storage
5. Version tracking and change detection

Use this as a drop-in replacement for direct requests/aiohttp calls in legal scrapers.
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

# Import content-addressed scraping system
try:
    sys.path.insert(0, str(Path(__file__).parent))
    from content_addressed_scraper import get_content_addressed_scraper
    from multi_index_archive_search import get_multi_index_searcher
    from unified_scraping_adapter import get_unified_scraper
    HAVE_UNIFIED_SYSTEM = True
except ImportError as e:
    logger.warning(f"Unified scraping system not available: {e}")
    HAVE_UNIFIED_SYSTEM = False


class LegalScraperUnifiedAdapter:
    """
    Unified adapter for all legal data scrapers.
    
    Provides a consistent interface that:
    - Checks if content already scraped (deduplication)
    - Uses unified scraping with fallbacks
    - Tracks versions with content addressing
    - Searches archives (Common Crawl, Wayback)
    - Integrates with IPFS storage
    """
    
    def __init__(self, 
                 scraper_name: str,
                 cache_dir: Optional[str] = None,
                 enable_ipfs: bool = False):
        """
        Initialize unified adapter for a legal scraper.
        
        Args:
            scraper_name: Name of the scraper (e.g., "municode", "state_laws")
            cache_dir: Custom cache directory
            enable_ipfs: Enable IPFS storage integration
        """
        self.scraper_name = scraper_name
        self.cache_dir = cache_dir or f"./legal_scraper_cache/{scraper_name}"
        
        # Initialize content-addressed scraper
        if HAVE_UNIFIED_SYSTEM:
            # IPFS integration if requested
            ipfs_storage = None
            if enable_ipfs:
                try:
                    parent_path = Path(__file__).parent.parent / "ipfs_datasets_py" / "mcp_server" / "tools" / "legal_dataset_tools"
                    if parent_path.exists():
                        sys.path.insert(0, str(parent_path))
                    from ipfs_storage_integration import IPFSStorageManager
                    ipfs_storage = IPFSStorageManager()
                    logger.info(f"IPFS storage enabled for {scraper_name}")
                except ImportError:
                    logger.warning("IPFS storage not available")
            
            self.content_scraper = get_content_addressed_scraper(
                cache_dir=self.cache_dir,
                ipfs_storage_manager=ipfs_storage
            )
            self.archive_searcher = get_multi_index_searcher(self.content_scraper)
            self.unified_scraper = get_unified_scraper()
        else:
            self.content_scraper = None
            self.archive_searcher = None
            self.unified_scraper = None
        
        logger.info(f"LegalScraperUnifiedAdapter initialized for {scraper_name}")
    
    async def scrape_with_deduplication(
        self,
        url: str,
        metadata: Optional[Dict[str, Any]] = None,
        check_archives: bool = True,
        force_rescrape: bool = False
    ) -> Dict[str, Any]:
        """
        Scrape URL with full deduplication and archive checking.
        
        This is the main method legal scrapers should use instead of direct requests.
        
        Args:
            url: URL to scrape
            metadata: Additional metadata about the content
            check_archives: Check Common Crawl and Wayback archives
            force_rescrape: Force rescrape even if already cached
            
        Returns:
            Dict containing:
                - status: "success", "cached", or "error"
                - content: Scraped content (bytes or str)
                - content_cid: Content identifier
                - metadata_cid: Metadata identifier
                - already_scraped: Whether this URL was already scraped
                - content_changed: Whether content changed from last version
                - version: Version number
                - archive_results: Results from archive searches
                - error: Error message (if failed)
        """
        if not HAVE_UNIFIED_SYSTEM:
            return await self._fallback_scrape(url)
        
        logger.info(f"[{self.scraper_name}] Scraping with deduplication: {url}")
        
        result = {
            "scraper": self.scraper_name,
            "url": url,
            "archive_results": {}
        }
        
        # 1. Check if already scraped
        scrape_status = self.content_scraper.check_url_scraped(url)
        result["already_scraped"] = scrape_status['scraped']
        
        if scrape_status['scraped']:
            logger.info(f"  URL already scraped: {scrape_status['total_versions']} versions")
            result["previous_versions"] = scrape_status['total_versions']
            result["latest_cid"] = scrape_status['latest_cid']
            
            if not force_rescrape:
                logger.info("  Using cached version")
                result["status"] = "cached"
                result["cached"] = True
                return result
        
        # 2. Check archives (optional but recommended)
        if check_archives and self.archive_searcher:
            try:
                # Extract domain from URL
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                
                logger.info(f"  Checking archives for domain: {domain}")
                archive_results = await self.archive_searcher.unified_archive_search(
                    url=url,
                    domain=domain,
                    search_common_crawl=True,
                    search_wayback=True,
                    deduplicate_by_cid=True
                )
                
                result["archive_results"] = {
                    "total_captures": archive_results['summary']['total_captures'],
                    "unique_versions": archive_results['summary']['unique_content_versions'],
                    "sources": archive_results['summary']['sources_searched']
                }
                
                logger.info(f"  Found {archive_results['summary']['total_captures']} archive captures")
            except Exception as e:
                logger.warning(f"  Archive search failed: {e}")
                result["archive_results"]["error"] = str(e)
        
        # 3. Scrape with content addressing
        scrape_result = await self.content_scraper.scrape_with_content_addressing(
            url=url,
            metadata={
                "scraper": self.scraper_name,
                **(metadata or {})
            },
            force_rescrape=force_rescrape,
            check_version_changes=True
        )
        
        # Merge results
        result.update(scrape_result)
        
        if scrape_result['status'] == 'success':
            logger.info(f"  ✓ Scraped successfully")
            logger.info(f"    Content CID: {scrape_result['content_cid']}")
            logger.info(f"    Changed: {scrape_result['changed']}")
            logger.info(f"    Version: {scrape_result['version']}")
        
        return result
    
    async def batch_scrape_with_deduplication(
        self,
        urls: List[str],
        metadata_list: Optional[List[Dict[str, Any]]] = None,
        rate_limit_delay: float = 1.0,
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Batch scrape multiple URLs with deduplication.
        
        Args:
            urls: List of URLs to scrape
            metadata_list: Optional list of metadata dicts (one per URL)
            rate_limit_delay: Delay between requests
            max_concurrent: Maximum concurrent requests
            
        Returns:
            List of scrape results
        """
        if not metadata_list:
            metadata_list = [None] * len(urls)
        
        results = []
        
        # Process in batches
        for i in range(0, len(urls), max_concurrent):
            batch_urls = urls[i:i + max_concurrent]
            batch_metadata = metadata_list[i:i + max_concurrent]
            
            # Scrape batch concurrently
            tasks = [
                self.scrape_with_deduplication(url, meta)
                for url, meta in zip(batch_urls, batch_metadata)
            ]
            
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for url, result in zip(batch_urls, batch_results):
                if isinstance(result, Exception):
                    results.append({
                        "status": "error",
                        "url": url,
                        "error": str(result)
                    })
                else:
                    results.append(result)
            
            # Rate limiting
            if i + max_concurrent < len(urls):
                await asyncio.sleep(rate_limit_delay)
        
        logger.info(f"[{self.scraper_name}] Batch scrape complete: {len(results)} URLs processed")
        return results
    
    async def _fallback_scrape(self, url: str) -> Dict[str, Any]:
        """Fallback scraping when unified system not available."""
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status == 200:
                        content = await response.read()
                        return {
                            "status": "success",
                            "url": url,
                            "content": content,
                            "fallback": True,
                            "message": "Using fallback scraping (unified system not available)"
                        }
                    else:
                        return {
                            "status": "error",
                            "url": url,
                            "error": f"HTTP {response.status}"
                        }
        except Exception as e:
            return {
                "status": "error",
                "url": url,
                "error": str(e)
            }
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics for this scraper."""
        if not self.content_scraper:
            return {"error": "Unified system not available"}
        
        stats = self.content_scraper.get_statistics()
        stats["scraper_name"] = self.scraper_name
        return stats


# Convenience functions for each legal scraper type

def get_municode_adapter(**kwargs) -> LegalScraperUnifiedAdapter:
    """Get adapter for Municode scraper."""
    return LegalScraperUnifiedAdapter("municode", **kwargs)

def get_state_laws_adapter(**kwargs) -> LegalScraperUnifiedAdapter:
    """Get adapter for State Laws scraper."""
    return LegalScraperUnifiedAdapter("state_laws", **kwargs)

def get_federal_register_adapter(**kwargs) -> LegalScraperUnifiedAdapter:
    """Get adapter for Federal Register scraper."""
    return LegalScraperUnifiedAdapter("federal_register", **kwargs)

def get_recap_adapter(**kwargs) -> LegalScraperUnifiedAdapter:
    """Get adapter for RECAP scraper."""
    return LegalScraperUnifiedAdapter("recap", **kwargs)

def get_us_code_adapter(**kwargs) -> LegalScraperUnifiedAdapter:
    """Get adapter for US Code scraper."""
    return LegalScraperUnifiedAdapter("us_code", **kwargs)

def get_ecode360_adapter(**kwargs) -> LegalScraperUnifiedAdapter:
    """Get adapter for eCode360 scraper."""
    return LegalScraperUnifiedAdapter("ecode360", **kwargs)

def get_american_legal_adapter(**kwargs) -> LegalScraperUnifiedAdapter:
    """Get adapter for American Legal scraper."""
    return LegalScraperUnifiedAdapter("american_legal", **kwargs)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    async def example():
        print("=" * 70)
        print("Legal Scraper Unified Adapter Demo")
        print("=" * 70)
        
        # Initialize adapter for Municode scraper
        adapter = get_municode_adapter()
        
        test_url = "https://library.municode.com/wa/seattle"
        
        print(f"\n1. Scraping with deduplication: {test_url}")
        result = await adapter.scrape_with_deduplication(
            url=test_url,
            metadata={"jurisdiction": "Seattle, WA"},
            check_archives=True
        )
        
        print(f"   Status: {result['status']}")
        print(f"   Already scraped: {result.get('already_scraped', False)}")
        if 'content_cid' in result:
            print(f"   Content CID: {result['content_cid']}")
            print(f"   Version: {result.get('version', 'N/A')}")
        
        if 'archive_results' in result:
            print(f"   Archive captures: {result['archive_results'].get('total_captures', 0)}")
        
        print(f"\n2. Getting statistics...")
        stats = adapter.get_statistics()
        print(f"   Scraper: {stats.get('scraper_name', 'N/A')}")
        print(f"   URLs tracked: {stats.get('total_urls_tracked', 0)}")
        print(f"   Unique CIDs: {stats.get('total_unique_content_cids', 0)}")
        
        print("\n✅ Demo complete!")
    
    asyncio.run(example())

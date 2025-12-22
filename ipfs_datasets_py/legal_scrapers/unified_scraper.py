"""
Unified Legal Scraper - Main entry point for all legal scraping.

This module provides a unified interface that:
1. Automatically selects the right scraper based on URL
2. Uses content addressing to avoid duplicate scrapes
3. Implements fallback chain: Common Crawl → Wayback → IPWB → Archive.is → Playwright → Live
4. Supports WARC export and IPFS storage
5. Handles multiprocessing for parallel scraping
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from multiprocessing import Pool, cpu_count
from datetime import datetime

logger = logging.getLogger(__name__)

# Import content addressed scraper
try:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from content_addressed_scraper import ContentAddressedScraper
    HAVE_CA_SCRAPER = True
except ImportError as e:
    logger.warning(f"ContentAddressedScraper not available: {e}")
    HAVE_CA_SCRAPER = False

# Import unified web scraper (multi-method fallbacks)
try:
    from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig, ScraperMethod
    HAVE_UNIFIED_WEB_SCRAPER = True
except ImportError as e:
    logger.warning(f"UnifiedWebScraper not available: {e}")
    HAVE_UNIFIED_WEB_SCRAPER = False


class UnifiedLegalScraper:
    """
    Main unified legal scraper with automatic fallbacks.
    
    This scraper automatically:
    - Detects the type of legal URL (municode, state law, federal, etc.)
    - Checks if already scraped (content addressed)
    - Falls back through multiple sources
    - Generates IPFS CIDs
    - Exports to WARC
    """
    
    def __init__(self,
                 cache_dir: str = "./legal_scraper_cache",
                 enable_ipfs: bool = False,
                 enable_warc: bool = True,
                 check_archives: bool = True,
                 request_timeout: int = 60,
                 max_workers: Optional[int] = None):
        """
        Initialize unified legal scraper.
        
        Args:
            cache_dir: Directory for caching
            enable_ipfs: Enable IPFS storage
            enable_warc: Enable WARC export
            check_archives: Check archives before live scraping
            max_workers: Max workers for parallel scraping (default: CPU count)
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.enable_ipfs = enable_ipfs
        self.enable_warc = enable_warc
        self.check_archives = check_archives
        self.request_timeout = int(request_timeout)
        self.max_workers = max_workers or cpu_count()
        
        # Initialize content addressed scraper
        if HAVE_CA_SCRAPER:
            self.ca_scraper = ContentAddressedScraper(
                cache_dir=str(self.cache_dir / "content_addressed")
            )
        else:
            self.ca_scraper = None
        
        # Initialize unified adapter
        if HAVE_UNIFIED_WEB_SCRAPER:
            self.web_scraper = UnifiedWebScraper()
        else:
            self.web_scraper = None
        
        logger.info(f"UnifiedLegalScraper initialized (IPFS={enable_ipfs}, WARC={enable_warc})")
    
    def detect_scraper_type(self, url: str) -> str:
        """
        Detect the appropriate scraper type for a URL.
        
        Args:
            url: URL to analyze
        
        Returns:
            Scraper type: "municode", "ecode360", "american_legal", "state", "federal", "recap", "generic"
        """
        url_lower = url.lower()
        
        # Municipal code providers
        if "municode.com" in url_lower:
            return "municode"
        elif "ecode360.com" in url_lower:
            return "ecode360"
        elif "amlegal.com" in url_lower or "codelibrary.amlegal.com" in url_lower:
            return "american_legal"
        
        # Federal sources
        elif "uscode.house.gov" in url_lower:
            return "us_code"
        elif "federalregister.gov" in url_lower:
            return "federal_register"
        elif "courtlistener.com" in url_lower or "recap" in url_lower:
            return "recap"
        
        # State sources (this is simplified - real implementation would check against state domains)
        elif any(state in url_lower for state in ["state.", ".gov/statutes", ".gov/codes", "legislature"]):
            return "state"
        
        else:
            return "generic"
    
    async def scrape_url(self,
                        url: str,
                        force_rescrape: bool = False,
                        prefer_archived: bool = True) -> Dict[str, Any]:
        """
        Scrape a single legal URL with fallbacks.
        
        Args:
            url: URL to scrape
            force_rescrape: Force rescrape even if cached
            prefer_archived: Prefer archived sources
        
        Returns:
            Dict with scraping results including CID, content, source, etc.
        """
        logger.info(f"Scraping {url}")
        
        # Check content addressing first
        if self.ca_scraper and not force_rescrape:
            ca_result = await self.ca_scraper.scrape_with_version_tracking(url)
            if ca_result.get("already_scraped") and not force_rescrape:
                logger.info(f"URL already scraped: {url} (CID: {ca_result.get('content_cid')})")
                return ca_result
        
        # Detect scraper type
        scraper_type = self.detect_scraper_type(url)
        logger.info(f"Detected scraper type: {scraper_type}")
        
        # Use appropriate scraper
        try:
            if scraper_type == "municode":
                from .scrapers.municipal_scrapers import municode_scraper
                result = await municode_scraper.scrape_code(url)
            elif scraper_type == "ecode360":
                from .scrapers.municipal_scrapers import ecode360_scraper
                result = await ecode360_scraper.scrape_code(url)
            elif scraper_type == "american_legal":
                from .scrapers.municipal_scrapers import american_legal_scraper
                result = await american_legal_scraper.scrape_code(url)
            elif scraper_type == "us_code":
                from .scrapers import us_code_scraper
                result = await us_code_scraper.scrape_us_code(url)
            elif scraper_type == "federal_register":
                from .scrapers import federal_register_scraper
                result = await federal_register_scraper.scrape_federal_register(url)
            elif scraper_type == "recap":
                from .core import recap
                result = await recap.search_recap_documents(query=url)
            elif scraper_type == "state":
                # For state URLs, we need to detect which state
                # This is simplified - real implementation would parse URL
                from .scrapers import get_state_scraper
                result = await self._scrape_with_unified_fallback(url)
            else:
                # Generic URL - use unified fallback
                result = await self._scrape_with_unified_fallback(url)
            
            return result
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return {
                "success": False,
                "url": url,
                "error": str(e),
                "scraper_type": scraper_type
            }
    
    async def _scrape_with_unified_fallback(self, url: str) -> Dict[str, Any]:
        """
        Scrape using unified adapter with full fallback chain.
        
        Fallback order:
        1. Common Crawl (all indexes)
        2. Wayback Machine
        3. IPWB (Interplanetary Wayback)
        4. Archive.is
        5. Playwright (for JS-heavy sites)
        6. Live scraping
        
        Args:
            url: URL to scrape
        
        Returns:
            Dict with scraping results
        """
        if not self.web_scraper:
            return {
                "success": False,
                "url": url,
                "error": "UnifiedWebScraper not available"
            }
        
        try:
            # If prefer archived sources, front-load archives; otherwise prefer live fetch.
            if self.check_archives:
                preferred_methods = [
                    ScraperMethod.COMMON_CRAWL,
                    ScraperMethod.WAYBACK_MACHINE,
                    ScraperMethod.IPWB,
                    ScraperMethod.ARCHIVE_IS,
                    ScraperMethod.PLAYWRIGHT,
                    ScraperMethod.BEAUTIFULSOUP,
                    ScraperMethod.REQUESTS_ONLY,
                    ScraperMethod.NEWSPAPER,
                    ScraperMethod.READABILITY,
                ]
            else:
                preferred_methods = [
                    ScraperMethod.PLAYWRIGHT,
                    ScraperMethod.BEAUTIFULSOUP,
                    ScraperMethod.REQUESTS_ONLY,
                    ScraperMethod.WAYBACK_MACHINE,
                    ScraperMethod.ARCHIVE_IS,
                    ScraperMethod.COMMON_CRAWL,
                    ScraperMethod.IPWB,
                    ScraperMethod.NEWSPAPER,
                    ScraperMethod.READABILITY,
                ]

            self.web_scraper.config = ScraperConfig(
                timeout=self.request_timeout,
                extract_links=True,
                extract_text=True,
                fallback_enabled=True,
                preferred_methods=preferred_methods,
            )

            web_result = await self.web_scraper.scrape(url)

            if not web_result.success:
                return {
                    "success": False,
                    "url": url,
                    "error": "; ".join(web_result.errors) if web_result.errors else "Scraping failed",
                    "errors": web_result.errors,
                    "metadata": web_result.metadata,
                }

            method_used = web_result.method_used.value if web_result.method_used else None
            source = method_used
            if method_used in {"beautifulsoup", "requests_only", "newspaper", "readability"}:
                source = "live"

            return {
                "success": True,
                "url": url,
                "content": web_result.content,
                "html": web_result.html,
                "title": web_result.title,
                "text": web_result.text,
                "links": web_result.links,
                "source": source,
                "method_used": method_used,
                "metadata": web_result.metadata,
            }
        except Exception as e:
            logger.error(f"Unified fallback scraping failed for {url}: {e}")
            return {
                "success": False,
                "url": url,
                "error": str(e)
            }
    
    async def scrape_urls_parallel(self,
                                   urls: List[str],
                                   max_concurrent: int = 10,
                                   force_rescrape: bool = False,
                                   prefer_archived: bool = True) -> List[Dict[str, Any]]:
        """
        Scrape multiple URLs in parallel.
        
        Args:
            urls: List of URLs to scrape
            max_concurrent: Maximum concurrent requests
            force_rescrape: Force rescrape even if cached
            prefer_archived: Prefer archived sources
        
        Returns:
            List of scraping results
        """
        logger.info(f"Scraping {len(urls)} URLs in parallel (max_concurrent={max_concurrent})")
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(url):
            async with semaphore:
                return await self.scrape_url(url, force_rescrape, prefer_archived)
        
        tasks = [scrape_with_semaphore(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Convert exceptions to error dicts
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append({
                    "success": False,
                    "url": urls[i],
                    "error": str(result)
                })
            else:
                processed_results.append(result)
        
        return processed_results
    
    def scrape_urls_multiprocessing(self,
                                    urls: List[str],
                                    force_rescrape: bool = False,
                                    prefer_archived: bool = True) -> List[Dict[str, Any]]:
        """
        Scrape multiple URLs using multiprocessing for maximum speed.
        
        This uses process-level parallelism in addition to async parallelism.
        Best for scraping large datasets (thousands of URLs).
        
        Args:
            urls: List of URLs to scrape
            force_rescrape: Force rescrape even if cached
            prefer_archived: Prefer archived sources
        
        Returns:
            List of scraping results
        """
        logger.info(f"Scraping {len(urls)} URLs with multiprocessing ({self.max_workers} workers)")
        
        def scrape_batch(batch):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            scraper = UnifiedLegalScraper(
                cache_dir=str(self.cache_dir),
                enable_ipfs=self.enable_ipfs,
                enable_warc=self.enable_warc,
                check_archives=self.check_archives
            )
            results = loop.run_until_complete(
                scraper.scrape_urls_parallel(batch, force_rescrape=force_rescrape, prefer_archived=prefer_archived)
            )
            loop.close()
            return results
        
        # Split URLs into batches
        batch_size = max(1, len(urls) // self.max_workers)
        batches = [urls[i:i+batch_size] for i in range(0, len(urls), batch_size)]
        
        # Process batches in parallel
        with Pool(self.max_workers) as pool:
            batch_results = pool.map(scrape_batch, batches)
        
        # Flatten results
        all_results = []
        for batch_result in batch_results:
            all_results.extend(batch_result)
        
        return all_results


# Convenience function
def get_unified_legal_scraper(**kwargs) -> UnifiedLegalScraper:
    """Get a configured unified legal scraper instance."""
    return UnifiedLegalScraper(**kwargs)


# Backward-compatible alias for older imports/tests
UnifiedScraper = UnifiedLegalScraper

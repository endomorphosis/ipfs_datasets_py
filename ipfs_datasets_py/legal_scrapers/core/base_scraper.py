#!/usr/bin/env python3
"""
Base Legal Scraper with Unified Scraping Support

This is the base class that all legal scrapers inherit from.
Provides:
- Unified scraping with content addressing
- WARC import/export
- Multi-interface support (package, CLI, MCP)
- Common utilities and error handling
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional
from abc import ABC, abstractmethod
from pathlib import Path
import sys

logger = logging.getLogger(__name__)

# Import unified scraping components
try:
    # Try relative imports first
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from legal_scraper_unified_adapter import LegalScraperUnifiedAdapter
    from content_addressed_scraper import get_content_addressed_scraper
    from warc_integration import CommonCrawlWARCImporter, WARCExporter
    HAVE_UNIFIED_SCRAPING = True
    logger.info("Unified scraping system available")
except ImportError as e:
    logger.warning(f"Unified scraping not available: {e}")
    HAVE_UNIFIED_SCRAPING = False


class BaseLegalScraper(ABC):
    """
    Base class for all legal data scrapers.
    
    Features:
    - Unified scraping with content addressing
    - Automatic deduplication
    - Version tracking
    - WARC import/export
    - Multiple output formats
    - Progress tracking
    
    Subclasses must implement:
    - scrape() method for core scraping logic
    - get_scraper_name() to identify the scraper
    
    Example:
        class MunicodeScraper(BaseLegalScraper):
            def get_scraper_name(self) -> str:
                return "municode"
            
            async def scrape(self, jurisdiction_url: str, **kwargs):
                result = await self.scrape_url_unified(
                    url=jurisdiction_url,
                    metadata={"source": "municode"}
                )
                return result
    """
    
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        enable_ipfs: bool = False,
        enable_warc: bool = False,
        check_archives: bool = True,
        output_format: str = "json"
    ):
        """
        Initialize base legal scraper.
        
        Args:
            cache_dir: Directory for caching scraped content
            enable_ipfs: Enable IPFS storage for permanent archiving
            enable_warc: Enable WARC import/export
            check_archives: Check Common Crawl/Wayback before scraping
            output_format: Output format (json, parquet, csv, warc)
        """
        self.cache_dir = cache_dir or f"./legal_scraper_cache/{self.get_scraper_name()}"
        self.enable_ipfs = enable_ipfs
        self.enable_warc = enable_warc
        self.check_archives = check_archives
        self.output_format = output_format
        
        # Initialize unified scraping if available
        if HAVE_UNIFIED_SCRAPING:
            self.adapter = LegalScraperUnifiedAdapter(
                scraper_name=self.get_scraper_name(),
                cache_dir=self.cache_dir,
                enable_ipfs=enable_ipfs
            )
            
            if enable_warc:
                self.content_scraper = get_content_addressed_scraper(cache_dir=self.cache_dir)
                self.warc_importer = CommonCrawlWARCImporter(self.content_scraper)
                self.warc_exporter = WARCExporter(output_dir=f"{self.cache_dir}/warc_exports")
            else:
                self.content_scraper = None
                self.warc_importer = None
                self.warc_exporter = None
        else:
            self.adapter = None
            self.content_scraper = None
            self.warc_importer = None
            self.warc_exporter = None
        
        logger.info(f"{self.get_scraper_name()} scraper initialized")
        logger.info(f"  Cache dir: {self.cache_dir}")
        logger.info(f"  IPFS: {enable_ipfs}")
        logger.info(f"  WARC: {enable_warc}")
        logger.info(f"  Check archives: {check_archives}")
    
    @abstractmethod
    def get_scraper_name(self) -> str:
        """Return the name of this scraper (e.g., 'municode', 'state_laws')."""
        pass
    
    @abstractmethod
    async def scrape(self, target: Any, **kwargs) -> Dict[str, Any]:
        """
        Core scraping method - must be implemented by subclasses.
        
        Args:
            target: What to scrape (URL, state code, date range, etc.)
            **kwargs: Additional scraping parameters
            
        Returns:
            Dict with scraped data and metadata
        """
        pass
    
    async def scrape_url_unified(
        self,
        url: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Scrape a URL using unified scraping system.
        
        This is the recommended method for scraping URLs.
        Uses content addressing, deduplication, and archive checking.
        
        Args:
            url: URL to scrape
            metadata: Additional metadata to store
            
        Returns:
            Dict with content, CID, version info, etc.
        """
        if not HAVE_UNIFIED_SCRAPING or not self.adapter:
            logger.warning("Unified scraping not available, using fallback")
            return await self._fallback_scrape(url)
        
        return await self.adapter.scrape_with_deduplication(
            url=url,
            metadata=metadata,
            check_archives=self.check_archives
        )
    
    async def batch_scrape(
        self,
        urls: List[str],
        metadata_list: Optional[List[Dict[str, Any]]] = None,
        max_concurrent: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Batch scrape multiple URLs with unified scraping.
        
        Args:
            urls: List of URLs to scrape
            metadata_list: Optional metadata for each URL
            max_concurrent: Maximum concurrent requests
            
        Returns:
            List of scraping results
        """
        if not HAVE_UNIFIED_SCRAPING or not self.adapter:
            logger.warning("Unified scraping not available")
            return []
        
        return await self.adapter.batch_scrape_with_deduplication(
            urls=urls,
            metadata_list=metadata_list,
            max_concurrent=max_concurrent
        )
    
    async def import_from_common_crawl(
        self,
        url_pattern: str,
        index_id: str = "CC-MAIN-2025-47",
        max_records: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Import historical content from Common Crawl.
        
        Args:
            url_pattern: URL pattern to search (e.g., "domain.com/*")
            index_id: Common Crawl index ID
            max_records: Maximum records to import
            
        Returns:
            List of imported records with content and CIDs
        """
        if not self.enable_warc or not self.warc_importer:
            logger.error("WARC support not enabled - set enable_warc=True")
            return []
        
        return await self.warc_importer.import_from_common_crawl(
            url_pattern=url_pattern,
            index_id=index_id,
            max_records=max_records,
            store_with_cid=True
        )
    
    def export_to_warc(
        self,
        records: List[Dict[str, Any]],
        output_filename: Optional[str] = None
    ) -> str:
        """
        Export scraped records to WARC format.
        
        Args:
            records: List of scraped records
            output_filename: Optional custom filename
            
        Returns:
            Path to created WARC file
        """
        if not self.enable_warc or not self.warc_exporter:
            logger.error("WARC support not enabled - set enable_warc=True")
            raise ValueError("WARC support not enabled")
        
        return self.warc_exporter.export_to_warc(records, output_filename)
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get scraping statistics.
        
        Returns:
            Dict with statistics about scraped content
        """
        if self.adapter:
            return self.adapter.get_statistics()
        return {"error": "Unified scraping not available"}
    
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
    
    def format_output(self, data: Any, format_type: Optional[str] = None) -> Any:
        """
        Format output data according to specified format.
        
        Args:
            data: Data to format
            format_type: Output format (json, parquet, csv, etc.)
            
        Returns:
            Formatted data
        """
        format_type = format_type or self.output_format
        
        if format_type == "json":
            return data
        elif format_type == "parquet":
            # Convert to parquet format
            try:
                import pandas as pd
                df = pd.DataFrame(data if isinstance(data, list) else [data])
                return df
            except ImportError:
                logger.warning("pandas not available, returning JSON")
                return data
        elif format_type == "csv":
            # Convert to CSV format
            try:
                import pandas as pd
                df = pd.DataFrame(data if isinstance(data, list) else [data])
                return df.to_csv(index=False)
            except ImportError:
                logger.warning("pandas not available, returning JSON")
                return data
        else:
            return data


# Sync wrapper for async scrapers
def run_async_scraper(coro):
    """
    Run an async scraper method synchronously.
    
    Usage:
        result = run_async_scraper(scraper.scrape(target))
    
    Args:
        coro: Coroutine to run
        
    Returns:
        Result of the coroutine
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(coro)

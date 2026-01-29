"""
Unified Web Scraper MCP Tool

This tool provides access to the unified web scraping system through the MCP server,
allowing AI assistants to scrape web content with automatic fallback mechanisms.
"""

import logging
from typing import Dict, List, Optional, Any, Literal

from ipfs_datasets_py.web_archiving.unified_web_scraper import (
    UnifiedWebScraper,
    ScraperConfig,
    ScraperMethod,
    scrape_url,
    scrape_urls
)

logger = logging.getLogger(__name__)


async def scrape_url_tool(
    url: str,
    method: Optional[str] = None,
    timeout: int = 30,
    extract_links: bool = True,
    extract_text: bool = True,
    fallback_enabled: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Scrape a URL using the unified web scraper with intelligent fallbacks.
    
    This tool automatically tries multiple scraping methods in sequence:
    1. Playwright (JavaScript rendering)
    2. BeautifulSoup (HTML parsing)
    3. Wayback Machine (Internet Archive)
    4. Archive.is (permanent snapshots)
    5. Common Crawl (web archive)
    6. IPWB (IPFS-based archive)
    7. Newspaper3k (article extraction)
    8. Readability (content extraction)
    9. Requests-only (basic scraping)
    
    Args:
        url: URL to scrape
        method: Specific method to use (optional). Options: "playwright", "beautifulsoup",
                "wayback_machine", "common_crawl", "archive_is", "ipwb", "newspaper",
                "readability", "requests_only". If not specified, tries all methods.
        timeout: Request timeout in seconds (default: 30)
        extract_links: Whether to extract links from the page (default: True)
        extract_text: Whether to extract text content (default: True)
        fallback_enabled: Whether to try alternative methods if primary fails (default: True)
    
    Returns:
        Dict containing:
            - status: "success" or "error"
            - url: Original URL
            - content: Extracted text content
            - html: HTML content (if available)
            - title: Page title
            - links: List of extracted links
            - method_used: Scraping method that succeeded
            - metadata: Additional metadata
            - extraction_time: Time taken to scrape
            - error: Error message (if failed)
    """
    try:
        # Create config
        config = ScraperConfig(
            timeout=timeout,
            extract_links=extract_links,
            extract_text=extract_text,
            fallback_enabled=fallback_enabled
        )
        
        # Create scraper
        scraper = UnifiedWebScraper(config)
        
        # Parse method if specified
        method_enum = None
        if method:
            try:
                method_enum = ScraperMethod(method.lower())
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid method: {method}. Valid methods: " + 
                            ", ".join([m.value for m in ScraperMethod])
                }
        
        # Scrape
        result = scraper.scrape_sync(url, method=method_enum, **kwargs)
        
        if result.success:
            return {
                "status": "success",
                "url": result.url,
                "content": result.content,
                "html": result.html,
                "title": result.title,
                "text": result.text,
                "links": result.links,
                "method_used": result.method_used.value if result.method_used else None,
                "metadata": result.metadata,
                "extraction_time": result.extraction_time,
                "timestamp": result.timestamp
            }
        else:
            return {
                "status": "error",
                "url": url,
                "error": "; ".join(result.errors),
                "errors": result.errors
            }
    
    except Exception as e:
        logger.error(f"Scraping failed for {url}: {e}")
        return {
            "status": "error",
            "url": url,
            "error": str(e)
        }


async def scrape_multiple_urls_tool(
    urls: List[str],
    method: Optional[str] = None,
    timeout: int = 30,
    max_concurrent: int = 5,
    extract_links: bool = True,
    extract_text: bool = True,
    fallback_enabled: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Scrape multiple URLs concurrently using the unified web scraper.
    
    This tool scrapes multiple URLs in parallel with automatic fallback mechanisms.
    Each URL is scraped independently with its own fallback sequence.
    
    Args:
        urls: List of URLs to scrape
        method: Specific method to use for all URLs (optional)
        timeout: Request timeout in seconds (default: 30)
        max_concurrent: Maximum number of concurrent scraping operations (default: 5)
        extract_links: Whether to extract links from pages (default: True)
        extract_text: Whether to extract text content (default: True)
        fallback_enabled: Whether to try alternative methods if primary fails (default: True)
    
    Returns:
        Dict containing:
            - status: "success" or "partial" or "error"
            - results: List of scraping results for each URL
            - successful_count: Number of successfully scraped URLs
            - failed_count: Number of failed URLs
            - total_time: Total processing time
    """
    try:
        # Create config
        config = ScraperConfig(
            timeout=timeout,
            extract_links=extract_links,
            extract_text=extract_text,
            fallback_enabled=fallback_enabled
        )
        
        # Create scraper
        scraper = UnifiedWebScraper(config)
        
        # Parse method if specified
        method_enum = None
        if method:
            try:
                method_enum = ScraperMethod(method.lower())
            except ValueError:
                return {
                    "status": "error",
                    "error": f"Invalid method: {method}"
                }
        
        # Scrape multiple URLs
        results = scraper.scrape_multiple_sync(urls, max_concurrent=max_concurrent, method=method_enum, **kwargs)
        
        # Process results
        successful = 0
        failed = 0
        processed_results = []
        
        for result in results:
            if result.success:
                successful += 1
                processed_results.append({
                    "status": "success",
                    "url": result.url,
                    "content": result.content,
                    "title": result.title,
                    "links": result.links,
                    "method_used": result.method_used.value if result.method_used else None,
                    "extraction_time": result.extraction_time
                })
            else:
                failed += 1
                processed_results.append({
                    "status": "error",
                    "url": result.url,
                    "error": "; ".join(result.errors)
                })
        
        overall_status = "success" if failed == 0 else ("partial" if successful > 0 else "error")
        
        return {
            "status": overall_status,
            "results": processed_results,
            "successful_count": successful,
            "failed_count": failed,
            "total_urls": len(urls)
        }
    
    except Exception as e:
        logger.error(f"Multiple URL scraping failed: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def check_scraper_methods_tool() -> Dict[str, Any]:
    """
    Check which scraping methods are currently available.
    
    Returns information about installed scraping libraries and available methods.
    
    Returns:
        Dict containing:
            - available_methods: Dict of method names and their availability
            - recommended_installs: List of recommended packages to install
            - all_methods: List of all possible methods
    """
    try:
        scraper = UnifiedWebScraper()
        
        available = {}
        unavailable = []
        
        for method in ScraperMethod:
            is_available = scraper.available_methods.get(method, False)
            available[method.value] = is_available
            if not is_available:
                unavailable.append(method.value)
        
        # Recommend packages for unavailable methods
        recommendations = {
            "playwright": "playwright (install: pip install playwright && playwright install)",
            "beautifulsoup": "beautifulsoup4 and requests (install: pip install beautifulsoup4 requests)",
            "wayback_machine": "wayback (install: pip install wayback)",
            "common_crawl": "cdx-toolkit (install: pip install cdx-toolkit)",
            "archive_is": "requests (install: pip install requests)",
            "ipwb": "ipwb (install: pip install ipwb)",
            "newspaper": "newspaper3k (install: pip install newspaper3k)",
            "readability": "readability-lxml (install: pip install readability-lxml)",
            "requests_only": "requests (install: pip install requests)"
        }
        
        recommended_installs = [
            recommendations[method] for method in unavailable 
            if method in recommendations
        ]
        
        return {
            "status": "success",
            "available_methods": available,
            "unavailable_methods": unavailable,
            "recommended_installs": recommended_installs,
            "all_methods": [m.value for m in ScraperMethod],
            "fallback_sequence": [
                "playwright", "beautifulsoup", "wayback_machine", "archive_is",
                "common_crawl", "ipwb", "newspaper", "readability", "requests_only"
            ]
        }
    
    except Exception as e:
        logger.error(f"Failed to check scraper methods: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

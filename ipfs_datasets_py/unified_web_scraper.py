"""
Unified Web Scraping System with Intelligent Fallback Mechanisms

This module provides a comprehensive, centralized web scraping system that automatically
tries multiple scraping methods in a smart fallback sequence. It eliminates duplicate
scraping logic across the codebase by providing a single interface for all web scraping needs.

Supported Scraping Methods (in fallback order):
1. Playwright - JavaScript rendering, dynamic content
2. BeautifulSoup + Requests - Standard HTML parsing
3. Wayback Machine - Historical snapshots via Internet Archive
4. Common Crawl - Large-scale web archive
5. Archive.is - Permanent webpage snapshots
6. IPWB (InterPlanetary Wayback) - IPFS-based web archives
7. Newspaper3k - Article extraction
8. Readability - Content extraction

The scraper automatically tries each method in sequence until successful,
making it resilient to various failure scenarios.
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Any, Literal, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from urllib.parse import urlparse, urljoin
import hashlib

logger = logging.getLogger(__name__)


class ScraperMethod(Enum):
    """Available scraping methods."""
    PLAYWRIGHT = "playwright"
    BEAUTIFULSOUP = "beautifulsoup"
    WAYBACK_MACHINE = "wayback_machine"
    COMMON_CRAWL = "common_crawl"
    ARCHIVE_IS = "archive_is"
    IPWB = "ipwb"
    NEWSPAPER = "newspaper"
    READABILITY = "readability"
    REQUESTS_ONLY = "requests_only"


@dataclass
class ScraperResult:
    """Result from a web scraping operation."""
    url: str
    content: str = ""
    html: str = ""
    title: str = ""
    text: str = ""
    links: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    method_used: Optional[ScraperMethod] = None
    success: bool = False
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    extraction_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "content": self.content,
            "html": self.html,
            "title": self.title,
            "text": self.text,
            "links": self.links,
            "metadata": self.metadata,
            "method_used": self.method_used.value if self.method_used else None,
            "success": self.success,
            "errors": self.errors,
            "timestamp": self.timestamp,
            "extraction_time": self.extraction_time
        }


@dataclass
class ScraperConfig:
    """Configuration for the unified scraper."""
    timeout: int = 30
    user_agent: str = "IPFS-Datasets-UnifiedScraper/1.0"
    max_retries: int = 3
    retry_delay: float = 1.0
    playwright_headless: bool = True
    playwright_wait_for: str = "networkidle"
    extract_links: bool = True
    extract_text: bool = True
    follow_redirects: bool = True
    verify_ssl: bool = True
    rate_limit_delay: float = 1.0
    preferred_methods: Optional[List[ScraperMethod]] = None
    fallback_enabled: bool = True
    
    def __post_init__(self):
        """Set default preferred methods if not specified."""
        if self.preferred_methods is None:
            self.preferred_methods = [
                ScraperMethod.PLAYWRIGHT,
                ScraperMethod.BEAUTIFULSOUP,
                ScraperMethod.WAYBACK_MACHINE,
                ScraperMethod.ARCHIVE_IS,
                ScraperMethod.COMMON_CRAWL,
                ScraperMethod.IPWB,
                ScraperMethod.NEWSPAPER,
                ScraperMethod.READABILITY,
                ScraperMethod.REQUESTS_ONLY
            ]


class UnifiedWebScraper:
    """
    Unified web scraping system with intelligent fallback mechanisms.
    
    This class provides a single interface for all web scraping needs, automatically
    trying multiple methods in sequence until successful. It consolidates all scraping
    logic from across the codebase into one reusable component.
    """
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """
        Initialize the unified scraper.
        
        Args:
            config: Scraper configuration. If None, uses defaults.
        """
        self.config = config or ScraperConfig()
        self._check_dependencies()
        self._init_session()
    
    def _check_dependencies(self):
        """Check which scraping libraries are available."""
        self.available_methods = {}
        
        # Check Playwright
        try:
            from playwright.async_api import async_playwright
            self.available_methods[ScraperMethod.PLAYWRIGHT] = True
        except ImportError:
            self.available_methods[ScraperMethod.PLAYWRIGHT] = False
            logger.debug("Playwright not available")
        
        # Check BeautifulSoup + requests
        try:
            from bs4 import BeautifulSoup
            import requests
            self.available_methods[ScraperMethod.BEAUTIFULSOUP] = True
        except ImportError:
            self.available_methods[ScraperMethod.BEAUTIFULSOUP] = False
            logger.debug("BeautifulSoup or requests not available")
        
        # Check Wayback Machine
        try:
            from wayback import WaybackClient
            self.available_methods[ScraperMethod.WAYBACK_MACHINE] = True
        except ImportError:
            self.available_methods[ScraperMethod.WAYBACK_MACHINE] = False
            logger.debug("Wayback library not available")
        
        # Check Common Crawl
        try:
            from cdx_toolkit import CDXFetcher
            self.available_methods[ScraperMethod.COMMON_CRAWL] = True
        except ImportError:
            self.available_methods[ScraperMethod.COMMON_CRAWL] = False
            logger.debug("CDX Toolkit not available")
        
        # Check Archive.is (requires requests)
        try:
            import requests
            self.available_methods[ScraperMethod.ARCHIVE_IS] = True
        except ImportError:
            self.available_methods[ScraperMethod.ARCHIVE_IS] = False
        
        # Check IPWB
        try:
            import ipwb
            self.available_methods[ScraperMethod.IPWB] = True
        except ImportError:
            self.available_methods[ScraperMethod.IPWB] = False
            logger.debug("IPWB not available")
        
        # Check Newspaper
        try:
            import newspaper
            self.available_methods[ScraperMethod.NEWSPAPER] = True
        except ImportError:
            self.available_methods[ScraperMethod.NEWSPAPER] = False
            logger.debug("Newspaper3k not available")
        
        # Check Readability
        try:
            from readability import Document
            self.available_methods[ScraperMethod.READABILITY] = True
        except ImportError:
            self.available_methods[ScraperMethod.READABILITY] = False
            logger.debug("Readability not available")
        
        # Requests-only is always available if requests is available
        try:
            import requests
            self.available_methods[ScraperMethod.REQUESTS_ONLY] = True
        except ImportError:
            self.available_methods[ScraperMethod.REQUESTS_ONLY] = False
    
    def _init_session(self):
        """Initialize HTTP session."""
        try:
            import requests
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': self.config.user_agent})
        except ImportError:
            self.session = None
    
    async def scrape(
        self,
        url: str,
        method: Optional[ScraperMethod] = None,
        **kwargs
    ) -> ScraperResult:
        """
        Scrape a URL using the specified method or automatic fallback.
        
        Args:
            url: URL to scrape
            method: Specific method to use. If None, tries all available methods.
            **kwargs: Additional method-specific arguments
        
        Returns:
            ScraperResult with scraped content and metadata
        """
        start_time = time.time()
        
        if method:
            # Use specific method
            result = await self._scrape_with_method(url, method, **kwargs)
        elif self.config.fallback_enabled:
            # Try methods in order of preference
            result = await self._scrape_with_fallback(url, **kwargs)
        else:
            # Try preferred method only
            preferred = self.config.preferred_methods[0] if self.config.preferred_methods else ScraperMethod.BEAUTIFULSOUP
            result = await self._scrape_with_method(url, preferred, **kwargs)
        
        result.extraction_time = time.time() - start_time
        return result
    
    async def _scrape_with_fallback(self, url: str, **kwargs) -> ScraperResult:
        """Try multiple scraping methods in sequence until one succeeds."""
        errors = []
        
        for method in self.config.preferred_methods:
            if not self.available_methods.get(method, False):
                continue
            
            try:
                logger.info(f"Trying {method.value} for {url}")
                result = await self._scrape_with_method(url, method, **kwargs)
                
                if result.success:
                    logger.info(f"Successfully scraped {url} using {method.value}")
                    return result
                else:
                    errors.extend(result.errors)
            
            except Exception as e:
                error_msg = f"{method.value} failed: {str(e)}"
                errors.append(error_msg)
                logger.warning(error_msg)
            
            # Rate limiting between attempts
            await asyncio.sleep(self.config.rate_limit_delay)
        
        # All methods failed
        return ScraperResult(
            url=url,
            success=False,
            errors=errors or ["No scraping methods available"]
        )
    
    async def _scrape_with_method(
        self,
        url: str,
        method: ScraperMethod,
        **kwargs
    ) -> ScraperResult:
        """Scrape using a specific method."""
        if not self.available_methods.get(method, False):
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"Method {method.value} not available"]
            )
        
        try:
            if method == ScraperMethod.PLAYWRIGHT:
                return await self._scrape_playwright(url, **kwargs)
            elif method == ScraperMethod.BEAUTIFULSOUP:
                return await self._scrape_beautifulsoup(url, **kwargs)
            elif method == ScraperMethod.WAYBACK_MACHINE:
                return await self._scrape_wayback(url, **kwargs)
            elif method == ScraperMethod.COMMON_CRAWL:
                return await self._scrape_common_crawl(url, **kwargs)
            elif method == ScraperMethod.ARCHIVE_IS:
                return await self._scrape_archive_is(url, **kwargs)
            elif method == ScraperMethod.IPWB:
                return await self._scrape_ipwb(url, **kwargs)
            elif method == ScraperMethod.NEWSPAPER:
                return await self._scrape_newspaper(url, **kwargs)
            elif method == ScraperMethod.READABILITY:
                return await self._scrape_readability(url, **kwargs)
            elif method == ScraperMethod.REQUESTS_ONLY:
                return await self._scrape_requests_only(url, **kwargs)
            else:
                return ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"Unknown method: {method.value}"]
                )
        except Exception as e:
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"{method.value} error: {str(e)}"],
                method_used=method
            )
    
    async def _scrape_playwright(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Playwright for JavaScript-rendered content."""
        from playwright.async_api import async_playwright
        from bs4 import BeautifulSoup
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.config.playwright_headless)
            page = await browser.new_page()
            
            try:
                await page.goto(url, wait_until=self.config.playwright_wait_for, timeout=self.config.timeout * 1000)
                
                # Get content
                html = await page.content()
                title = await page.title()
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract text
                text = ""
                if self.config.extract_text:
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text(separator='\n', strip=True)
                
                # Extract links
                links = []
                if self.config.extract_links:
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if href.startswith('/'):
                            href = urljoin(url, href)
                        links.append({
                            'url': href,
                            'text': link.get_text(strip=True)
                        })
                
                return ScraperResult(
                    url=url,
                    html=html,
                    title=title,
                    text=text,
                    content=text,
                    links=links,
                    method_used=ScraperMethod.PLAYWRIGHT,
                    success=True,
                    metadata={
                        'method': 'playwright',
                        'content_length': len(html)
                    }
                )
            
            finally:
                await browser.close()
    
    async def _scrape_beautifulsoup(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using BeautifulSoup + requests."""
        import requests
        from bs4 import BeautifulSoup
        
        response = self.session.get(
            url,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            allow_redirects=self.config.follow_redirects
        )
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract title
        title_tag = soup.find('title')
        title = title_tag.get_text() if title_tag else ""
        
        # Extract text
        text = ""
        if self.config.extract_text:
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator='\n', strip=True)
        
        # Extract links
        links = []
        if self.config.extract_links:
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.startswith('/'):
                    href = urljoin(url, href)
                links.append({
                    'url': href,
                    'text': link.get_text(strip=True)
                })
        
        return ScraperResult(
            url=url,
            html=response.text,
            title=title,
            text=text,
            content=text,
            links=links,
            method_used=ScraperMethod.BEAUTIFULSOUP,
            success=True,
            metadata={
                'method': 'beautifulsoup',
                'status_code': response.status_code,
                'content_type': response.headers.get('Content-Type', ''),
                'content_length': len(response.content)
            }
        )
    
    async def _scrape_wayback(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Wayback Machine."""
        from wayback import WaybackClient
        from bs4 import BeautifulSoup
        import requests
        
        client = WaybackClient()
        
        # Get most recent capture
        try:
            capture = next(client.search(url, limit=1))
            archive_url = capture.archive_url
            
            # Fetch archived content
            response = requests.get(archive_url, timeout=self.config.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract data
            title = soup.find('title')
            title_text = title.get_text() if title else ""
            
            text = ""
            if self.config.extract_text:
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text(separator='\n', strip=True)
            
            return ScraperResult(
                url=url,
                html=response.text,
                title=title_text,
                text=text,
                content=text,
                method_used=ScraperMethod.WAYBACK_MACHINE,
                success=True,
                metadata={
                    'method': 'wayback_machine',
                    'archive_url': archive_url,
                    'timestamp': capture.timestamp.isoformat(),
                    'original_url': capture.original_url
                }
            )
        except StopIteration:
            return ScraperResult(
                url=url,
                success=False,
                errors=["No Wayback Machine captures found for this URL"]
            )
    
    async def _scrape_common_crawl(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Common Crawl."""
        from cdx_toolkit import CDXFetcher
        import requests
        from bs4 import BeautifulSoup
        
        domain = urlparse(url).netloc
        cdx = CDXFetcher(source='cc')
        
        try:
            # Search for the URL
            record = next(cdx.iter(url=url, limit=1))
            
            # Common Crawl stores content in WARC files on S3
            # For now, return metadata only
            return ScraperResult(
                url=url,
                success=True,
                method_used=ScraperMethod.COMMON_CRAWL,
                metadata={
                    'method': 'common_crawl',
                    'timestamp': record.data.get('timestamp', ''),
                    'mime_type': record.data.get('mime', ''),
                    'status_code': record.data.get('status', ''),
                    'warc_filename': record.data.get('filename', ''),
                    'warc_offset': record.data.get('offset', ''),
                    'note': 'Common Crawl metadata only. Full content requires WARC file access.'
                }
            )
        except StopIteration:
            return ScraperResult(
                url=url,
                success=False,
                errors=["URL not found in Common Crawl"]
            )
    
    async def _scrape_archive_is(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Archive.is."""
        import requests
        from bs4 import BeautifulSoup
        
        # Try to find existing archive first
        search_url = f"https://archive.is/newest/{url}"
        
        try:
            response = requests.get(search_url, timeout=self.config.timeout, allow_redirects=True)
            
            if response.status_code == 200 and 'archive.is' in response.url:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                title = soup.find('title')
                title_text = title.get_text() if title else ""
                
                text = ""
                if self.config.extract_text:
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text(separator='\n', strip=True)
                
                return ScraperResult(
                    url=url,
                    html=response.text,
                    title=title_text,
                    text=text,
                    content=text,
                    method_used=ScraperMethod.ARCHIVE_IS,
                    success=True,
                    metadata={
                        'method': 'archive_is',
                        'archive_url': response.url
                    }
                )
        except Exception as e:
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"Archive.is scraping failed: {str(e)}"]
            )
    
    async def _scrape_ipwb(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using IPWB (InterPlanetary Wayback)."""
        import ipwb
        
        # IPWB requires a local index
        # This is a placeholder for IPWB integration
        return ScraperResult(
            url=url,
            success=False,
            errors=["IPWB scraping requires a local CDXJ index"]
        )
    
    async def _scrape_newspaper(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Newspaper3k."""
        import newspaper
        
        article = newspaper.Article(url)
        article.download()
        article.parse()
        
        return ScraperResult(
            url=url,
            title=article.title or "",
            text=article.text or "",
            content=article.text or "",
            html=article.html or "",
            method_used=ScraperMethod.NEWSPAPER,
            success=True,
            metadata={
                'method': 'newspaper',
                'authors': article.authors,
                'publish_date': str(article.publish_date) if article.publish_date else None,
                'top_image': article.top_image
            }
        )
    
    async def _scrape_readability(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Readability."""
        import requests
        from readability import Document
        from bs4 import BeautifulSoup
        
        response = self.session.get(url, timeout=self.config.timeout)
        response.raise_for_status()
        
        doc = Document(response.content)
        title = doc.title()
        html_summary = doc.summary()
        
        soup = BeautifulSoup(html_summary, 'html.parser')
        text = soup.get_text(separator='\n', strip=True)
        
        return ScraperResult(
            url=url,
            title=title,
            html=html_summary,
            text=text,
            content=text,
            method_used=ScraperMethod.READABILITY,
            success=True,
            metadata={
                'method': 'readability',
                'content_length': len(response.content)
            }
        )
    
    async def _scrape_requests_only(self, url: str, **kwargs) -> ScraperResult:
        """Basic scraping with requests only."""
        import requests
        import re
        
        response = self.session.get(url, timeout=self.config.timeout)
        response.raise_for_status()
        
        # Basic HTML tag removal
        text = re.sub(r'<[^>]+>', '', response.text)
        text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
        
        # Extract title
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', response.text, re.IGNORECASE)
        title = title_match.group(1) if title_match else ""
        
        return ScraperResult(
            url=url,
            title=title,
            html=response.text,
            text=text,
            content=text,
            method_used=ScraperMethod.REQUESTS_ONLY,
            success=True,
            metadata={
                'method': 'requests_only',
                'status_code': response.status_code
            }
        )
    
    def scrape_sync(self, url: str, **kwargs) -> ScraperResult:
        """Synchronous version of scrape."""
        return asyncio.run(self.scrape(url, **kwargs))
    
    async def scrape_multiple(
        self,
        urls: List[str],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[ScraperResult]:
        """Scrape multiple URLs concurrently."""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(url):
            async with semaphore:
                result = await self.scrape(url, **kwargs)
                await asyncio.sleep(self.config.rate_limit_delay)
                return result
        
        tasks = [scrape_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    def scrape_multiple_sync(self, urls: List[str], **kwargs) -> List[ScraperResult]:
        """Synchronous version of scrape_multiple."""
        return asyncio.run(self.scrape_multiple(urls, **kwargs))


# Convenience functions for backward compatibility
def scrape_url(url: str, method: Optional[str] = None, **kwargs) -> ScraperResult:
    """Scrape a single URL (synchronous)."""
    scraper = UnifiedWebScraper()
    method_enum = ScraperMethod(method) if method else None
    return scraper.scrape_sync(url, method=method_enum, **kwargs)


def scrape_urls(urls: List[str], **kwargs) -> List[ScraperResult]:
    """Scrape multiple URLs (synchronous)."""
    scraper = UnifiedWebScraper()
    return scraper.scrape_multiple_sync(urls, **kwargs)


async def scrape_url_async(url: str, method: Optional[str] = None, **kwargs) -> ScraperResult:
    """Scrape a single URL (asynchronous)."""
    scraper = UnifiedWebScraper()
    method_enum = ScraperMethod(method) if method else None
    return await scraper.scrape(url, method=method_enum, **kwargs)


async def scrape_urls_async(urls: List[str], **kwargs) -> List[ScraperResult]:
    """Scrape multiple URLs (asynchronous)."""
    scraper = UnifiedWebScraper()
    return await scraper.scrape_multiple(urls, **kwargs)

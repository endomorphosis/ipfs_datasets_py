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
import anyio
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

    # Common Crawl (via local common_crawl_search_engine) configuration.
    # Defaults match common_crawl_search_engine.ccindex.api.search_domain_via_meta_indexes().
    common_crawl_parquet_root: Optional[str] = None
    common_crawl_master_db: Optional[str] = None
    common_crawl_year_db: Optional[str] = None
    common_crawl_collection_db: Optional[str] = None
    common_crawl_year: Optional[str] = None
    common_crawl_max_matches: int = 25
    common_crawl_max_parquet_files: int = 200
    common_crawl_per_parquet_limit: int = 2000
    common_crawl_prefix: str = "https://data.commoncrawl.org/"
    common_crawl_fetch_max_bytes: int = 2_000_000
    common_crawl_cache_mode: str = "range"
    common_crawl_prefer_exact_url: bool = True
    # Optimization: coalesce many per-record Range GETs into fewer larger slice GETs.
    # These are byte sizes on the remote WARC file.
    common_crawl_slice_max_bytes: int = 64_000_000
    common_crawl_slice_gap_bytes: int = 1_000_000
    common_crawl_slice_min_bytes: int = 1_000_000
    common_crawl_slice_workers: int = 8
    common_crawl_warc_workers: int = 8
    
    def __post_init__(self):
        """Set default preferred methods if not specified."""
        if self.preferred_methods is None:
            self.preferred_methods = [
                # Prefer archive-based sources first to reduce origin fetches (e.g. Cloudflare).
                ScraperMethod.COMMON_CRAWL,
                ScraperMethod.PLAYWRIGHT,
                ScraperMethod.BEAUTIFULSOUP,
                ScraperMethod.WAYBACK_MACHINE,
                ScraperMethod.ARCHIVE_IS,
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
            # Prefer local common_crawl_search_engine integration when available.
            from common_crawl_search_engine.ccindex import api as _ccapi  # noqa: F401
            self.available_methods[ScraperMethod.COMMON_CRAWL] = True
        except ImportError:
            try:
                from cdx_toolkit import CDXFetcher  # noqa: F401
                self.available_methods[ScraperMethod.COMMON_CRAWL] = True
            except ImportError:
                self.available_methods[ScraperMethod.COMMON_CRAWL] = False
                logger.debug("Common Crawl integration not available")
        
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
            await anyio.sleep(self.config.rate_limit_delay)
        
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
        # Preferred path: use local common_crawl_search_engine for both pointer discovery
        # and record fetching + HTTP extraction.
        try:
            from common_crawl_search_engine.ccindex import api as ccapi
            have_cc_engine = True
        except Exception:
            have_cc_engine = False

        if have_cc_engine:
            try:
                from pathlib import Path

                parquet_root = self.config.common_crawl_parquet_root
                master_db = self.config.common_crawl_master_db
                year_db = self.config.common_crawl_year_db
                collection_db = self.config.common_crawl_collection_db
                year = self.config.common_crawl_year

                res = ccapi.search_domain_via_meta_indexes(
                    url,
                    parquet_root=(Path(parquet_root).expanduser().resolve() if parquet_root else Path("/storage/ccindex_parquet")),
                    master_db=(Path(master_db).expanduser().resolve() if master_db else Path("/storage/ccindex_duckdb/cc_pointers_master/cc_master_index.duckdb")),
                    year_db=(Path(year_db).expanduser().resolve() if year_db else None),
                    collection_db=(Path(collection_db).expanduser().resolve() if collection_db else None),
                    year=year,
                    max_parquet_files=int(self.config.common_crawl_max_parquet_files),
                    max_matches=int(self.config.common_crawl_max_matches),
                    per_parquet_limit=int(self.config.common_crawl_per_parquet_limit),
                )

                records = list(getattr(res, "records", []) or [])
                if not records:
                    return ScraperResult(url=url, success=False, errors=["No Common Crawl records for domain"])

                chosen = None
                if self.config.common_crawl_prefer_exact_url:
                    for r in records:
                        if str(r.get("url") or "") == str(url):
                            chosen = r
                            break
                if chosen is None:
                    chosen = records[0]

                wf = chosen.get("warc_filename")
                off = chosen.get("warc_offset")
                ln = chosen.get("warc_length")
                if not wf or off is None or ln is None:
                    return ScraperResult(
                        url=url,
                        success=False,
                        errors=["Common Crawl pointer missing warc_filename/offset/length"],
                        method_used=ScraperMethod.COMMON_CRAWL,
                        metadata={"record": chosen},
                    )

                fetch, source, local_path = ccapi.fetch_warc_record(
                    warc_filename=str(wf),
                    warc_offset=int(off),
                    warc_length=int(ln),
                    prefix=str(self.config.common_crawl_prefix),
                    timeout_s=float(self.config.timeout),
                    max_bytes=int(self.config.common_crawl_fetch_max_bytes),
                    decode_gzip_text=False,
                    cache_mode=str(self.config.common_crawl_cache_mode),
                )

                if not getattr(fetch, "ok", False) or not getattr(fetch, "raw_base64", None):
                    return ScraperResult(
                        url=url,
                        success=False,
                        errors=[str(getattr(fetch, "error", None) or "fetch_warc_record failed")],
                        method_used=ScraperMethod.COMMON_CRAWL,
                        metadata={"record": chosen, "source": source, "local_path": local_path},
                    )

                import base64

                gz_bytes = base64.b64decode(fetch.raw_base64)
                http = ccapi.extract_http_from_warc_gzip_member(
                    gz_bytes,
                    max_body_bytes=int(self.config.common_crawl_fetch_max_bytes),
                    max_preview_chars=200_000,
                )

                html = http.body_text_preview or ""
                title = ""
                text = ""
                links = []
                if html and (http.body_is_html or (http.body_mime or "").startswith("text/html")):
                    try:
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(html, "html.parser")
                        title_tag = soup.find("title")
                        title = title_tag.get_text() if title_tag else ""
                        if self.config.extract_text:
                            for script in soup(["script", "style"]):
                                script.decompose()
                            text = soup.get_text(separator="\n", strip=True)
                        if self.config.extract_links:
                            for link in soup.find_all("a", href=True):
                                href = link.get("href")
                                if not href:
                                    continue
                                if href.startswith("/"):
                                    href = urljoin(url, href)
                                links.append({"url": href, "text": link.get_text(strip=True)})
                    except Exception:
                        pass

                return ScraperResult(
                    url=url,
                    html=html,
                    title=title,
                    text=text,
                    content=text or html,
                    links=links,
                    method_used=ScraperMethod.COMMON_CRAWL,
                    success=True,
                    metadata={
                        "method": "common_crawl_search_engine",
                        "cc_record": chosen,
                        "cc_source": source,
                        "cc_local_warc_path": local_path,
                        "http_status": http.http_status,
                        "http_mime": http.body_mime,
                        "http_charset": http.body_charset,
                        "ok": http.ok,
                        "error": http.error,
                    },
                )
            except Exception as e:
                return ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"common_crawl_search_engine error: {type(e).__name__}: {e}"],
                    method_used=ScraperMethod.COMMON_CRAWL,
                )

        # Fallback: if cdx_toolkit is available, keep prior behavior (metadata-only).
        try:
            from cdx_toolkit import CDXFetcher

            cdx = CDXFetcher(source='cc')
            record = next(cdx.iter(url=url, limit=1))
            return ScraperResult(
                url=url,
                success=True,
                method_used=ScraperMethod.COMMON_CRAWL,
                metadata={
                    'method': 'cdx_toolkit',
                    'timestamp': record.data.get('timestamp', ''),
                    'mime_type': record.data.get('mime', ''),
                    'status_code': record.data.get('status', ''),
                    'warc_filename': record.data.get('filename', ''),
                    'warc_offset': record.data.get('offset', ''),
                    'note': 'Metadata-only fallback; install common_crawl_search_engine for full content.'
                }
            )
        except Exception:
            return ScraperResult(
                url=url,
                success=False,
                errors=["Common Crawl integration unavailable"]
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
        async def _runner() -> ScraperResult:
            return await self.scrape(url, **kwargs)

        return anyio.run(_runner)

    async def scrape_domain(self, url: str, *, max_pages: Optional[int] = None, **kwargs) -> List[ScraperResult]:
        """Scrape a whole domain using Common Crawl first.

        This is intended for "domain-first" archival scraping to avoid origin blocking.
        Currently it only uses the local `common_crawl_search_engine` integration.

        Returns a list of ScraperResult objects (successful and/or failed).
        """

        # Only Common Crawl domain mode for now.
        max_pages_i = int(max_pages if max_pages is not None else self.config.common_crawl_max_matches)
        if max_pages_i <= 0:
            return []

        try:
            from common_crawl_search_engine.ccindex import api as ccapi
        except Exception as e:
            return [
                ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"common_crawl_search_engine unavailable: {type(e).__name__}: {e}"],
                    method_used=ScraperMethod.COMMON_CRAWL,
                )
            ]

        try:
            from pathlib import Path
            import base64
            from bs4 import BeautifulSoup

            parquet_root = self.config.common_crawl_parquet_root
            master_db = self.config.common_crawl_master_db
            year_db = self.config.common_crawl_year_db
            collection_db = self.config.common_crawl_collection_db
            year = self.config.common_crawl_year

            res = ccapi.search_domain_via_meta_indexes(
                url,
                parquet_root=(Path(parquet_root).expanduser().resolve() if parquet_root else Path("/storage/ccindex_parquet")),
                master_db=(Path(master_db).expanduser().resolve() if master_db else Path("/storage/ccindex_duckdb/cc_pointers_master/cc_master_index.duckdb")),
                year_db=(Path(year_db).expanduser().resolve() if year_db else None),
                collection_db=(Path(collection_db).expanduser().resolve() if collection_db else None),
                year=year,
                max_parquet_files=int(self.config.common_crawl_max_parquet_files),
                max_matches=int(max_pages_i),
                per_parquet_limit=int(self.config.common_crawl_per_parquet_limit),
            )

            records = list(getattr(res, "records", []) or [])
            if not records:
                return [
                    ScraperResult(
                        url=url,
                        success=False,
                        errors=["No Common Crawl records for domain"],
                        method_used=ScraperMethod.COMMON_CRAWL,
                        metadata={"method": "common_crawl_search_engine"},
                    )
                ]

            results: List[ScraperResult] = []
            seen_urls = set()

            # Prefer an exact match for the requested URL (if configured), then continue.
            ordered_records = records
            if self.config.common_crawl_prefer_exact_url:
                exact = [r for r in records if str(r.get("url") or "") == str(url)]
                rest = [r for r in records if r not in exact]
                ordered_records = exact + rest

            # Build the list of unique pages to fetch first (preserving order).
            to_fetch: List[Dict[str, Any]] = []
            for r in ordered_records:
                if len(to_fetch) >= max_pages_i:
                    break
                page_url = str(r.get("url") or url)
                if page_url in seen_urls:
                    continue
                seen_urls.add(page_url)
                wf = r.get("warc_filename")
                off = r.get("warc_offset")
                ln = r.get("warc_length")
                if not wf or off is None or ln is None:
                    results.append(
                        ScraperResult(
                            url=page_url,
                            success=False,
                            errors=["Common Crawl pointer missing warc_filename/offset/length"],
                            method_used=ScraperMethod.COMMON_CRAWL,
                            metadata={"method": "common_crawl_search_engine", "cc_record": r},
                        )
                    )
                    continue
                to_fetch.append({"page_url": page_url, "cc_record": r, "wf": str(wf), "off": int(off), "ln": int(ln)})

            # Fetch in batches per WARC file using slice-range coalescing when available.
            bytes_by_key: Dict[tuple, bytes] = {}
            err_by_key: Dict[tuple, str] = {}
            try:
                batch_fn = getattr(ccapi, "fetch_warc_record_ranges_sliced", None)
            except Exception:
                batch_fn = None

            if callable(batch_fn):
                by_wf: Dict[str, List[tuple]] = {}
                for item in to_fetch:
                    by_wf.setdefault(item["wf"], []).append((item["off"], item["ln"]))

                # Fetch different WARC files in parallel (common case: 1 record per WARC).
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _fetch_wf(wf: str, ranges: List[tuple]):
                    return wf, batch_fn(
                        warc_filename=str(wf),
                        ranges=list(ranges),
                        prefix=str(self.config.common_crawl_prefix),
                        timeout_s=float(self.config.timeout),
                        max_slice_bytes=int(self.config.common_crawl_slice_max_bytes),
                        max_gap_bytes=int(self.config.common_crawl_slice_gap_bytes),
                        min_slice_bytes=int(self.config.common_crawl_slice_min_bytes),
                        max_workers=int(self.config.common_crawl_slice_workers),
                    )

                warc_workers = int(self.config.common_crawl_warc_workers)
                if warc_workers <= 1 or len(by_wf) <= 1:
                    items = [(_fetch_wf(wf, ranges)) for wf, ranges in by_wf.items()]
                else:
                    items = []
                    with ThreadPoolExecutor(max_workers=warc_workers) as ex:
                        futs = [ex.submit(_fetch_wf, wf, ranges) for wf, ranges in by_wf.items()]
                        for fut in as_completed(futs):
                            items.append(fut.result())

                for wf, (data_by, e_by) in items:
                    for (off, ln), blob in (data_by or {}).items():
                        bytes_by_key[(str(wf), int(off), int(ln))] = blob
                    for (off, ln), msg in (e_by or {}).items():
                        err_by_key[(str(wf), int(off), int(ln))] = str(msg)

            for item in to_fetch:
                page_url = item["page_url"]
                r = item["cc_record"]
                wf = item["wf"]
                off = item["off"]
                ln = item["ln"]

                gz_bytes: Optional[bytes] = None
                cc_source: Optional[str] = None
                cc_local_warc_path: Optional[str] = None
                k = (str(wf), int(off), int(ln))
                if k in bytes_by_key:
                    gz_bytes = bytes_by_key[k]
                    cc_source = "range_slice"
                elif k in err_by_key and not callable(batch_fn):
                    # shouldn't happen, but keep behavior sane.
                    cc_source = "range"

                if gz_bytes is None and callable(batch_fn):
                    # Slice mode ran but this specific range failed.
                    results.append(
                        ScraperResult(
                            url=page_url,
                            success=False,
                            errors=[err_by_key.get(k, "slice fetch failed")],
                            method_used=ScraperMethod.COMMON_CRAWL,
                            metadata={
                                "method": "common_crawl_search_engine",
                                "cc_record": r,
                                "cc_source": cc_source,
                                "cc_local_warc_path": cc_local_warc_path,
                            },
                        )
                    )
                    continue

                if gz_bytes is None:
                    fetch, source, local_path = ccapi.fetch_warc_record(
                        warc_filename=str(wf),
                        warc_offset=int(off),
                        warc_length=int(ln),
                        prefix=str(self.config.common_crawl_prefix),
                        timeout_s=float(self.config.timeout),
                        max_bytes=int(self.config.common_crawl_fetch_max_bytes),
                        decode_gzip_text=False,
                        cache_mode=str(self.config.common_crawl_cache_mode),
                    )

                    if not getattr(fetch, "ok", False) or not getattr(fetch, "raw_base64", None):
                        results.append(
                            ScraperResult(
                                url=page_url,
                                success=False,
                                errors=[str(getattr(fetch, "error", None) or "fetch_warc_record failed")],
                                method_used=ScraperMethod.COMMON_CRAWL,
                                metadata={
                                    "method": "common_crawl_search_engine",
                                    "cc_record": r,
                                    "cc_source": source,
                                    "cc_local_warc_path": local_path,
                                },
                            )
                        )
                        continue

                    gz_bytes = base64.b64decode(fetch.raw_base64)
                    cc_source = source
                    cc_local_warc_path = local_path

                http = ccapi.extract_http_from_warc_gzip_member(
                    gz_bytes,
                    max_body_bytes=int(self.config.common_crawl_fetch_max_bytes),
                    max_preview_chars=200_000,
                )

                html = http.body_text_preview or ""
                title = ""
                text = ""
                links: List[Dict[str, str]] = []
                if html and (http.body_is_html or (http.body_mime or "").startswith("text/html")):
                    try:
                        soup = BeautifulSoup(html, "html.parser")
                        title_tag = soup.find("title")
                        title = title_tag.get_text() if title_tag else ""
                        if self.config.extract_text:
                            for script in soup(["script", "style"]):
                                script.decompose()
                            text = soup.get_text(separator="\n", strip=True)
                        if self.config.extract_links:
                            for link in soup.find_all("a", href=True):
                                href = link.get("href")
                                if not href:
                                    continue
                                if href.startswith("/"):
                                    href = urljoin(page_url, href)
                                links.append({"url": href, "text": link.get_text(strip=True)})
                    except Exception:
                        pass

                results.append(
                    ScraperResult(
                        url=page_url,
                        html=html,
                        title=title,
                        text=text,
                        content=text or html,
                        links=links,
                        method_used=ScraperMethod.COMMON_CRAWL,
                        success=bool(html or text),
                        metadata={
                            "method": "common_crawl_search_engine",
                            "cc_record": r,
                            "cc_source": cc_source,
                            "cc_local_warc_path": cc_local_warc_path,
                            "http_status": http.http_status,
                            "http_mime": http.body_mime,
                            "http_charset": http.body_charset,
                            "ok": http.ok,
                            "error": http.error,
                        },
                    )
                )

            return results
        except Exception as e:
            return [
                ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"common_crawl_search_engine domain error: {type(e).__name__}: {e}"],
                    method_used=ScraperMethod.COMMON_CRAWL,
                )
            ]

    def scrape_domain_sync(self, url: str, *, max_pages: Optional[int] = None, **kwargs) -> List[ScraperResult]:
        """Synchronous version of scrape_domain."""

        async def _runner() -> List[ScraperResult]:
            return await self.scrape_domain(url, max_pages=max_pages, **kwargs)

        return anyio.run(_runner)
    
    async def scrape_multiple(
        self,
        urls: List[str],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[ScraperResult]:
        """Scrape multiple URLs concurrently."""
        semaphore = anyio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(url):
            async with semaphore:
                result = await self.scrape(url, **kwargs)
                await anyio.sleep(self.config.rate_limit_delay)
                return result
        
        # Execute all scrapes concurrently using anyio task group
        results = []
        async with anyio.create_task_group() as tg:
            async def collect_result(url):
                result = await scrape_with_semaphore(url)
                results.append(result)
            
            for url in urls:
                tg.start_soon(collect_result, url)
        
        return results
    
    def scrape_multiple_sync(self, urls: List[str], **kwargs) -> List[ScraperResult]:
        """Synchronous version of scrape_multiple."""
        async def _runner() -> List[ScraperResult]:
            return await self.scrape_multiple(urls, **kwargs)

        return anyio.run(_runner)


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

"""
URL/Network Resource Handler for File Converter.

Provides async downloading and processing of files from HTTP/HTTPS URLs.
Integrates with the file conversion pipeline and comprehensive web scraping system
to enable processing of remote files with automatic fallback for Cloudflare and
other challenges.
"""

import os
import tempfile
import logging
from dataclasses import dataclass
from typing import Optional, Dict
from urllib.parse import urlparse, unquote

import anyio

logger = logging.getLogger(__name__)

# Try to import comprehensive web scraping system
try:
    from ipfs_datasets_py.processors.web_archiving.unified_web_scraper import (
        UnifiedWebScraper, ScraperConfig, ScraperMethod
    )
    WEB_SCRAPER_AVAILABLE = True
except ImportError:
    WEB_SCRAPER_AVAILABLE = False

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False


@dataclass
class URLDownloadResult:
    """Result of downloading a file from a URL."""
    
    url: str
    local_path: str
    content_type: Optional[str] = None
    content_length: Optional[int] = None
    filename: Optional[str] = None
    headers: Dict[str, str] = None
    success: bool = True
    error: Optional[str] = None
    
    def __post_init__(self):
        if self.headers is None:
            self.headers = {}


class URLHandler:
    """
    Handler for downloading files from HTTP/HTTPS URLs.
    
    Features:
    - Async downloading with aiohttp
    - Integration with comprehensive web scraping system for Cloudflare handling
    - Automatic fallback through multiple methods (Playwright, BeautifulSoup, archives)
    - Content-type detection from headers
    - Automatic filename extraction
    - Progress tracking (future)
    - Integration with FileConverter
    - Temporary file management
    
    Example:
        >>> handler = URLHandler()
        >>> result = await handler.download('https://example.com/document.pdf')
        >>> print(f"Downloaded to: {result.local_path}")
        >>> print(f"Content-type: {result.content_type}")
    """
    
    def __init__(
        self,
        temp_dir: Optional[str] = None,
        timeout: int = 30,
        max_size_mb: Optional[int] = None,
        chunk_size: int = 8192,
        use_web_scraper: bool = True
    ):
        """
        Initialize URL handler.
        
        Args:
            temp_dir: Directory for temporary downloads (default: system temp)
            timeout: Download timeout in seconds (default: 30)
            max_size_mb: Maximum file size in MB (default: no limit)
            chunk_size: Download chunk size in bytes (default: 8192)
            use_web_scraper: Use comprehensive web scraping system for challenging URLs
                           (Cloudflare, etc.) (default: True)
        """
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.timeout = timeout
        self.max_size_mb = max_size_mb
        self.chunk_size = chunk_size
        self.use_web_scraper = use_web_scraper and WEB_SCRAPER_AVAILABLE
        
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for URL downloading. "
                "Install with: pip install aiohttp"
            )
        
        # Initialize web scraper if available and enabled
        self.web_scraper = None
        if self.use_web_scraper:
            try:
                config = ScraperConfig(
                    timeout=timeout,
                    fallback_enabled=True,
                    verify_ssl=True
                )
                self.web_scraper = UnifiedWebScraper(config)
                logger.info("Unified web scraper enabled for URL handling (Cloudflare protection)")
            except Exception as e:
                logger.warning(f"Could not initialize web scraper: {e}")
                self.web_scraper = None
    
    async def download(
        self,
        url: str,
        dest_path: Optional[str] = None,
        filename: Optional[str] = None,
        use_web_scraper_fallback: bool = True
    ) -> URLDownloadResult:
        """
        Download a file from a URL.
        
        First attempts direct download via aiohttp. If that fails (e.g., due to
        Cloudflare protection), automatically falls back to the comprehensive
        web scraping system with Playwright, archive.is, Wayback Machine, etc.
        
        Args:
            url: HTTP/HTTPS URL to download from
            dest_path: Destination path (default: temp directory)
            filename: Specific filename to use (default: from URL or Content-Disposition)
            use_web_scraper_fallback: Use web scraper if direct download fails (default: True)
        
        Returns:
            URLDownloadResult with download information
        """
        try:
            # Parse URL
            parsed = urlparse(url)
            if parsed.scheme not in ('http', 'https'):
                return URLDownloadResult(
                    url=url,
                    local_path="",
                    success=False,
                    error=f"Unsupported URL scheme: {parsed.scheme}"
                )
            
            # Determine filename
            if not filename:
                filename = self._extract_filename(url)
            
            # Determine destination path
            if not dest_path:
                dest_path = os.path.join(self.temp_dir, filename)
            
            # Download file
            async with aiohttp.ClientSession() as session:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with session.get(url, timeout=timeout) as response:
                    response.raise_for_status()
                    
                    # Extract metadata
                    content_type = response.headers.get('Content-Type')
                    content_length = response.headers.get('Content-Length')
                    content_length = int(content_length) if content_length else None
                    
                    # Check size limit
                    if self.max_size_mb and content_length:
                        max_bytes = self.max_size_mb * 1024 * 1024
                        if content_length > max_bytes:
                            return URLDownloadResult(
                                url=url,
                                local_path="",
                                success=False,
                                error=f"File too large: {content_length} bytes (max: {max_bytes})"
                            )
                    
                    # Try to get filename from Content-Disposition
                    content_disp = response.headers.get('Content-Disposition')
                    if content_disp and not filename:
                        filename = self._extract_filename_from_header(content_disp) or filename
                    
                    # Download to file
                    os.makedirs(os.path.dirname(dest_path) or '.', exist_ok=True)
                    
                    with open(dest_path, 'wb') as f:
                        downloaded = 0
                        async for chunk in response.content.iter_chunked(self.chunk_size):
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Check size limit during download
                            if self.max_size_mb:
                                max_bytes = self.max_size_mb * 1024 * 1024
                                if downloaded > max_bytes:
                                    os.remove(dest_path)
                                    return URLDownloadResult(
                                        url=url,
                                        local_path="",
                                        success=False,
                                        error=f"Download exceeded size limit: {self.max_size_mb}MB"
                                    )
                    
                    return URLDownloadResult(
                        url=url,
                        local_path=dest_path,
                        content_type=content_type,
                        content_length=content_length or downloaded,
                        filename=filename,
                        headers=dict(response.headers),
                        success=True
                    )
        
        except (aiohttp.ClientError, TimeoutError) as e:
            error_msg = f"Direct download failed: {str(e)}"
            logger.warning(error_msg)
            
            # Try web scraper fallback if enabled
            if use_web_scraper_fallback and self.web_scraper:
                logger.info(f"Attempting web scraper fallback for: {url}")
                try:
                    return await self._download_via_web_scraper(
                        url, dest_path, filename
                    )
                except Exception as scraper_error:
                    logger.error(f"Web scraper fallback failed: {scraper_error}")
                    return URLDownloadResult(
                        url=url,
                        local_path="",
                        success=False,
                        error=f"{error_msg}. Scraper fallback also failed: {str(scraper_error)}"
                    )
            
            return URLDownloadResult(
                url=url,
                local_path="",
                success=False,
                error=error_msg
            )
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            logger.warning(error_msg)
            
            # Try web scraper fallback if enabled
            if use_web_scraper_fallback and self.web_scraper:
                logger.info(f"Attempting web scraper fallback for: {url}")
                try:
                    return await self._download_via_web_scraper(
                        url, dest_path, filename
                    )
                except Exception as scraper_error:
                    logger.error(f"Web scraper fallback failed: {scraper_error}")
                    return URLDownloadResult(
                        url=url,
                        local_path="",
                        success=False,
                        error=f"{error_msg}. Scraper fallback also failed: {str(scraper_error)}"
                    )
            
            return URLDownloadResult(
                url=url,
                local_path="",
                success=False,
                error=error_msg
            )
    
    async def _download_via_web_scraper(
        self,
        url: str,
        dest_path: str,
        filename: str
    ) -> URLDownloadResult:
        """
        Download content using the comprehensive web scraping system.
        
        This method handles Cloudflare protection and other challenges by
        automatically trying multiple scraping methods (Playwright, BeautifulSoup,
        Wayback Machine, archive.is, Common Crawl, etc.).
        
        Args:
            url: URL to scrape
            dest_path: Destination path for downloaded content
            filename: Filename to use
        
        Returns:
            URLDownloadResult with scraping result
        """
        logger.info(f"Using comprehensive web scraper for: {url}")
        
        # Scrape using unified web scraper
        result = await self.web_scraper.scrape(url)
        
        if not result.success:
            raise Exception(f"All scraping methods failed: {', '.join(result.errors)}")
        
        # Save scraped content to file
        os.makedirs(os.path.dirname(dest_path) or '.', exist_ok=True)
        
        # Save HTML or text content
        content_to_save = result.html or result.content or result.text
        if not content_to_save:
            raise Exception("No content extracted from URL")
        
        with open(dest_path, 'w', encoding='utf-8') as f:
            f.write(content_to_save)
        
        file_size = os.path.getsize(dest_path)
        
        logger.info(
            f"Successfully downloaded via {result.method_used.value if result.method_used else 'unknown'}: "
            f"{url} ({file_size} bytes)"
        )
        
        return URLDownloadResult(
            url=url,
            local_path=dest_path,
            content_type='text/html',  # Web scraper returns HTML/text
            content_length=file_size,
            filename=filename,
            headers={'X-Scraper-Method': result.method_used.value if result.method_used else 'unknown'},
            success=True
        )
    
    def _extract_filename(self, url: str) -> str:
        """Extract filename from URL."""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path)
        
        if not filename or '.' not in filename:
            # Generate filename from URL
            filename = f"download_{abs(hash(url)) % 1000000}.tmp"
        
        return filename
    
    def _extract_filename_from_header(self, content_disposition: str) -> Optional[str]:
        """Extract filename from Content-Disposition header."""
        try:
            if 'filename=' in content_disposition:
                parts = content_disposition.split('filename=')
                if len(parts) > 1:
                    filename = parts[1].strip(' "\'')
                    return filename
        except Exception:
            pass
        return None
    
    def cleanup(self, result: URLDownloadResult):
        """Clean up downloaded file."""
        if result.local_path and os.path.exists(result.local_path):
            try:
                os.remove(result.local_path)
            except Exception:
                pass


def is_url(input_str: str) -> bool:
    """
    Check if a string is a valid HTTP/HTTPS URL.
    
    Args:
        input_str: String to check
    
    Returns:
        True if valid URL, False otherwise
    """
    try:
        parsed = urlparse(input_str)
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except Exception:
        return False


async def download_from_url(
    url: str,
    dest_path: Optional[str] = None,
    timeout: int = 30,
    max_size_mb: Optional[int] = None
) -> URLDownloadResult:
    """
    Convenience function to download a file from a URL.
    
    Args:
        url: HTTP/HTTPS URL to download from
        dest_path: Destination path (default: temp directory)
        timeout: Download timeout in seconds
        max_size_mb: Maximum file size in MB
    
    Returns:
        URLDownloadResult with download information
    
    Example:
        >>> result = await download_from_url('https://example.com/file.pdf')
        >>> if result.success:
        ...     print(f"Downloaded to: {result.local_path}")
    """
    handler = URLHandler(timeout=timeout, max_size_mb=max_size_mb)
    return await handler.download(url, dest_path=dest_path)


# Sync wrapper for backwards compatibility
def download_from_url_sync(
    url: str,
    dest_path: Optional[str] = None,
    timeout: int = 30,
    max_size_mb: Optional[int] = None
) -> URLDownloadResult:
    """
    Synchronous wrapper for download_from_url.
    
    Args:
        url: HTTP/HTTPS URL to download from
        dest_path: Destination path (default: temp directory)
        timeout: Download timeout in seconds
        max_size_mb: Maximum file size in MB
    
    Returns:
        URLDownloadResult with download information
    """
    async def _runner() -> URLDownloadResult:
        return await download_from_url(
            url=url,
            dest_path=dest_path,
            timeout=timeout,
            max_size_mb=max_size_mb,
        )

    return anyio.run(_runner)

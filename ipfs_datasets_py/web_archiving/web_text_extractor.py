"""
Website Text Extractor for Legal Document Processing

This module provides capability to extract and process text from websites,
extending the existing PDF processing to work with web-based legal documents.
"""

import os
import sys
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Tuple
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
import tempfile

# Import with fallbacks
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

try:
    import newspaper
    NEWSPAPER_AVAILABLE = True
except ImportError:
    NEWSPAPER_AVAILABLE = False

try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class WebTextExtractionResult:
    """Result of web text extraction."""
    url: str
    title: str = ""
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    errors: List[str] = field(default_factory=list)
    extraction_time: float = 0.0
    text_length: int = 0
    
    def __post_init__(self):
        self.text_length = len(self.text)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "metadata": self.metadata,
            "success": self.success,
            "errors": self.errors,
            "extraction_time": self.extraction_time,
            "text_length": self.text_length
        }


class WebTextExtractor:
    """
    Extracts text from websites for legal document processing.
    """
    
    def __init__(self, timeout: int = 30, user_agent: str = None):
        self.timeout = timeout
        self.user_agent = user_agent or "IPFS Legal Document Processor/1.0"
        
        # Check available extraction libraries
        self.available_extractors = {
            'requests': REQUESTS_AVAILABLE,
            'beautifulsoup': BS4_AVAILABLE,
            'newspaper': NEWSPAPER_AVAILABLE,
            'readability': READABILITY_AVAILABLE
        }
        
        if not any(self.available_extractors.values()):
            logger.warning("No web extraction libraries available. Install with: pip install requests beautifulsoup4 newspaper3k readability")
        
        # Session for connection reuse
        if REQUESTS_AVAILABLE:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': self.user_agent})
        else:
            self.session = None
    
    def extract_text(self, url: str, method: str = "auto") -> WebTextExtractionResult:
        """
        Extract text from a URL using the specified method.
        
        Args:
            url: URL to extract text from
            method: Extraction method ('auto', 'requests', 'newspaper', 'readability')
        """
        start_time = time.time()
        
        try:
            if method == "auto":
                # Try methods in order of preference
                if NEWSPAPER_AVAILABLE:
                    result = self._extract_with_newspaper(url)
                elif READABILITY_AVAILABLE and REQUESTS_AVAILABLE:
                    result = self._extract_with_readability(url)
                elif BS4_AVAILABLE and REQUESTS_AVAILABLE:
                    result = self._extract_with_beautifulsoup(url)
                elif REQUESTS_AVAILABLE:
                    result = self._extract_with_requests(url)
                else:
                    return WebTextExtractionResult(
                        url=url,
                        success=False,
                        errors=["No extraction libraries available"]
                    )
            elif method == "newspaper" and NEWSPAPER_AVAILABLE:
                result = self._extract_with_newspaper(url)
            elif method == "readability" and READABILITY_AVAILABLE:
                result = self._extract_with_readability(url)
            elif method == "beautifulsoup" and BS4_AVAILABLE:
                result = self._extract_with_beautifulsoup(url)
            elif method == "requests" and REQUESTS_AVAILABLE:
                result = self._extract_with_requests(url)
            else:
                return WebTextExtractionResult(
                    url=url,
                    success=False,
                    errors=[f"Method {method} not available"]
                )
            
            result.extraction_time = time.time() - start_time
            return result
            
        except Exception as e:
            return WebTextExtractionResult(
                url=url,
                success=False,
                errors=[str(e)],
                extraction_time=time.time() - start_time
            )
    
    def _extract_with_newspaper(self, url: str) -> WebTextExtractionResult:
        """Extract text using newspaper3k library."""
        try:
            article = newspaper.Article(url)
            article.download()
            article.parse()
            
            return WebTextExtractionResult(
                url=url,
                title=article.title or "",
                text=article.text or "",
                metadata={
                    "method": "newspaper",
                    "authors": article.authors,
                    "publish_date": str(article.publish_date) if article.publish_date else None,
                    "top_image": article.top_image,
                    "keywords": article.keywords
                }
            )
        except Exception as e:
            return WebTextExtractionResult(
                url=url,
                success=False,
                errors=[f"Newspaper extraction failed: {str(e)}"]
            )
    
    def _extract_with_readability(self, url: str) -> WebTextExtractionResult:
        """Extract text using readability library."""
        if not REQUESTS_AVAILABLE:
            return WebTextExtractionResult(
                url=url,
                success=False,
                errors=["Requests library not available"]
            )
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            doc = Document(response.content)
            title = doc.title()
            text = doc.summary()
            
            # Parse with BeautifulSoup to get clean text
            if BS4_AVAILABLE:
                soup = BeautifulSoup(text, 'html.parser')
                clean_text = soup.get_text()
            else:
                # Basic HTML tag removal
                import re
                clean_text = re.sub(r'<[^>]+>', '', text)
            
            return WebTextExtractionResult(
                url=url,
                title=title,
                text=clean_text,
                metadata={
                    "method": "readability",
                    "content_length": len(response.content),
                    "encoding": response.encoding
                }
            )
        except Exception as e:
            return WebTextExtractionResult(
                url=url,
                success=False,
                errors=[f"Readability extraction failed: {str(e)}"]
            )
    
    def _extract_with_beautifulsoup(self, url: str) -> WebTextExtractionResult:
        """Extract text using BeautifulSoup."""
        if not REQUESTS_AVAILABLE or not BS4_AVAILABLE:
            return WebTextExtractionResult(
                url=url,
                success=False,
                errors=["Required libraries not available"]
            )
        
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get title
            title_tag = soup.find('title')
            title = title_tag.get_text() if title_tag else ""
            
            # Get main content (try common content selectors)
            content_selectors = [
                'article', 'main', '.content', '#content', 
                '.post-content', '.entry-content', '.article-content'
            ]
            
            text = ""
            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    text = content.get_text()
                    break
            
            # Fallback to body if no content found
            if not text:
                text = soup.get_text()
            
            # Clean up text
            text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
            
            return WebTextExtractionResult(
                url=url,
                title=title.strip(),
                text=text,
                metadata={
                    "method": "beautifulsoup",
                    "content_length": len(response.content),
                    "encoding": response.encoding,
                    "status_code": response.status_code
                }
            )
        except Exception as e:
            return WebTextExtractionResult(
                url=url,
                success=False,
                errors=[f"BeautifulSoup extraction failed: {str(e)}"]
            )
    
    def _extract_with_requests(self, url: str) -> WebTextExtractionResult:
        """Basic text extraction using requests only."""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            # Basic HTML tag removal
            import re
            text = re.sub(r'<[^>]+>', '', response.text)
            text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
            
            # Try to extract title from HTML
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', response.text, re.IGNORECASE)
            title = title_match.group(1) if title_match else ""
            
            return WebTextExtractionResult(
                url=url,
                title=title.strip(),
                text=text,
                metadata={
                    "method": "requests_only",
                    "content_length": len(response.content),
                    "encoding": response.encoding,
                    "status_code": response.status_code
                }
            )
        except Exception as e:
            return WebTextExtractionResult(
                url=url,
                success=False,
                errors=[f"Requests extraction failed: {str(e)}"]
            )
    
    def extract_from_multiple_urls(self, urls: List[str], 
                                  method: str = "auto") -> List[WebTextExtractionResult]:
        """Extract text from multiple URLs."""
        results = []
        
        for url in urls:
            result = self.extract_text(url, method)
            results.append(result)
            
            # Small delay to be respectful to servers
            time.sleep(0.5)
        
        return results
    
    def save_extracted_text(self, result: WebTextExtractionResult, 
                          output_dir: Union[str, Path]) -> Path:
        """Save extracted text to a file."""
        output_dir = Path(output_dir)
        output_dir.mkdir(exist_ok=True)
        
        # Create safe filename from URL
        parsed_url = urlparse(result.url)
        domain = parsed_url.netloc.replace('.', '_')
        path_safe = parsed_url.path.replace('/', '_').replace('.', '_')
        filename = f"{domain}_{path_safe}.txt"
        
        output_file = output_dir / filename
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"URL: {result.url}\n")
            f.write(f"Title: {result.title}\n")
            f.write(f"Extracted: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Method: {result.metadata.get('method', 'unknown')}\n")
            f.write(f"Text Length: {result.text_length} characters\n")
            f.write("=" * 80 + "\n\n")
            f.write(result.text)
        
        return output_file


# Auto-install dependencies when imported
def _ensure_web_dependencies():
    """Ensure web extraction dependencies are available."""
    installer = None
    try:
        from ipfs_datasets_py.auto_installer import get_installer
        installer = get_installer()
        
        # Install web scraping dependencies
        dependencies = [
            ('requests', 'requests'),
            ('bs4', 'beautifulsoup4'),
            ('newspaper', 'newspaper3k'),
            ('readability', 'readability-lxml')
        ]
        
        for module_name, package_name in dependencies:
            installer.ensure_dependency(module_name, package_name)
            
    except Exception as e:
        if installer is not None and getattr(installer, "verbose", False):
            logger.warning(f"Could not auto-install web dependencies: {e}")


# Initialize web dependencies if auto-install is enabled
if os.getenv('IPFS_AUTO_INSTALL', 'true').lower() == 'true':
    _ensure_web_dependencies()


# Convenience functions
def extract_website_text(url: str, method: str = "auto") -> WebTextExtractionResult:
    """Extract text from a website URL."""
    extractor = WebTextExtractor()
    return extractor.extract_text(url, method)


def extract_multiple_websites(urls: List[str], method: str = "auto") -> List[WebTextExtractionResult]:
    """Extract text from multiple website URLs."""
    extractor = WebTextExtractor()
    return extractor.extract_from_multiple_urls(urls, method)


def save_website_text(url: str, output_dir: Union[str, Path], 
                     method: str = "auto") -> Tuple[WebTextExtractionResult, Path]:
    """Extract and save website text to file."""
    extractor = WebTextExtractor()
    result = extractor.extract_text(url, method)
    
    if result.success:
        output_file = extractor.save_extracted_text(result, output_dir)
        return result, output_file
    else:
        return result, None
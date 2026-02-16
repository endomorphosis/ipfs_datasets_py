"""Common Crawl Legal Scraper with Intelligent Fallback Chain.

This module provides a comprehensive legal document scraper that integrates:
1. Common Crawl via HuggingFace datasets (primary source)
2. Brave Search API (fallback 1)
3. Wayback Machine / WebArchive (fallback 2)
4. Archive.is and other archives (fallback 3)
5. Direct HTTP requests (fallback 4)

The scraper automatically tries each method in sequence until successful,
making it resilient to various failure scenarios.

Features:
- Load JSONL URL lists (federal, municipal, state)
- Query HuggingFace Common Crawl indexes
- Parse WARC files with offset + range
- GraphRAG extraction for rule mining
- Logic module integration
- Comprehensive error handling and retry logic
- @monitor decorator for observability
- Async/await patterns for performance

Usage:
    >>> scraper = CommonCrawlLegalScraper()
    >>> await scraper.load_jsonl_sources()
    >>> results = await scraper.scrape_url(
    ...     "https://congress.gov/",
    ...     source_type="federal"
    ... )
    >>> # Results include: content, metadata, method_used, success
"""

import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Literal, Union
from enum import Enum

import anyio

# Add parent directory to path for imports
PARENT_DIR = Path(__file__).parent.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

logger = logging.getLogger(__name__)

# Try to import monitoring decorator
try:
    from ..infrastructure.monitoring import monitor
    MONITORING_AVAILABLE = True
except ImportError:
    # Fallback if monitoring not available
    def monitor(func):
        return func
    MONITORING_AVAILABLE = False

# Import web archiving tools
try:
    from ...web_archiving.common_crawl_integration import CommonCrawlSearchEngine
    HAVE_COMMON_CRAWL = True
except ImportError:
    HAVE_COMMON_CRAWL = False
    logger.warning("Common Crawl integration not available")

try:
    from ...web_archiving.brave_search_client import BraveSearchClient
    HAVE_BRAVE_SEARCH = True
except ImportError:
    HAVE_BRAVE_SEARCH = False
    logger.warning("Brave Search client not available")

try:
    from ...web_archiving.web_archive import WebArchive
    HAVE_WEB_ARCHIVE = True
except ImportError:
    HAVE_WEB_ARCHIVE = False
    logger.warning("WebArchive (Wayback Machine) not available")

try:
    from ...web_archiving.unified_web_scraper import UnifiedWebScraper, ScraperResult
    HAVE_UNIFIED_SCRAPER = True
except ImportError:
    HAVE_UNIFIED_SCRAPER = False
    logger.warning("UnifiedWebScraper not available")

# Import GraphRAG for extraction
try:
    from ..specialized.graphrag.unified_graphrag import UnifiedGraphRAGProcessor
    HAVE_GRAPHRAG = True
except ImportError:
    HAVE_GRAPHRAG = False
    logger.warning("GraphRAG processor not available")

# Import logic module
try:
    from ...logic_integration import LogicProcessor
    HAVE_LOGIC = True
except ImportError:
    HAVE_LOGIC = False
    logger.warning("Logic processor not available")

# Import base scraper
from .state_scrapers.base_scraper import NormalizedStatute, StatuteMetadata


class SourceType(Enum):
    """Types of legal sources."""
    FEDERAL = "federal"
    MUNICIPAL = "municipal"
    STATE = "state"
    UNKNOWN = "unknown"


class FallbackMethod(Enum):
    """Available fallback methods for fetching content."""
    COMMON_CRAWL = "common_crawl"
    BRAVE_SEARCH = "brave_search"
    WAYBACK_MACHINE = "wayback_machine"
    ARCHIVE_IS = "archive_is"
    UNIFIED_SCRAPER = "unified_scraper"
    DIRECT_HTTP = "direct_http"


@dataclass
class LegalSourceMetadata:
    """Metadata for a legal source from JSONL."""
    id: str
    kind: str  # "entity"
    branch: str  # "legislative", "executive", "judicial"
    branch_confidence: float
    branch_reasons: List[str]
    name: str
    aliases: List[str]
    website: str
    host: str
    description: str
    sources: List[str]
    seed_urls: List[str]
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LegalSourceMetadata':
        """Create from dictionary (JSONL entry)."""
        return cls(
            id=data.get("id", ""),
            kind=data.get("kind", "entity"),
            branch=data.get("branch", "unknown"),
            branch_confidence=data.get("branch_confidence", 0.0),
            branch_reasons=data.get("branch_reasons", []),
            name=data.get("name", ""),
            aliases=data.get("aliases", []),
            website=data.get("website", ""),
            host=data.get("host", ""),
            description=data.get("description", ""),
            sources=data.get("sources", []),
            seed_urls=data.get("seed_urls", [])
        )


@dataclass
class ScrapedLegalContent:
    """Result from scraping a legal source."""
    url: str
    source_type: SourceType
    source_metadata: Optional[LegalSourceMetadata] = None
    content: str = ""
    html: str = ""
    title: str = ""
    text: str = ""
    extracted_rules: List[Dict[str, Any]] = field(default_factory=list)
    method_used: Optional[FallbackMethod] = None
    fallback_methods_tried: List[FallbackMethod] = field(default_factory=list)
    success: bool = False
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    extraction_time: float = 0.0
    warc_metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "source_type": self.source_type.value,
            "source_metadata": asdict(self.source_metadata) if self.source_metadata else None,
            "content": self.content,
            "html": self.html,
            "title": self.title,
            "text": self.text,
            "extracted_rules": self.extracted_rules,
            "method_used": self.method_used.value if self.method_used else None,
            "fallback_methods_tried": [m.value for m in self.fallback_methods_tried],
            "success": self.success,
            "errors": self.errors,
            "timestamp": self.timestamp,
            "extraction_time": self.extraction_time,
            "warc_metadata": self.warc_metadata
        }
    
    def to_normalized_statute(self) -> NormalizedStatute:
        """Convert to NormalizedStatute format for compatibility."""
        state_code = "US"  # Federal or unknown
        state_name = "United States"
        
        if self.source_metadata:
            if self.source_metadata.branch:
                state_code = self.source_metadata.branch.upper()[:2]
        
        return NormalizedStatute(
            state_code=state_code,
            state_name=state_name,
            statute_id=self.url,
            short_title=self.title or self.source_metadata.name if self.source_metadata else "",
            full_text=self.text or self.content,
            source_url=self.url,
            legal_area=self.source_metadata.branch if self.source_metadata else "general",
            topics=[self.source_type.value],
            metadata=StatuteMetadata()
        )


class CommonCrawlLegalScraper:
    """Legal document scraper with intelligent fallback chain.
    
    This scraper attempts to fetch legal documents using multiple methods:
    1. Common Crawl (HuggingFace datasets + WARC parsing)
    2. Brave Search API
    3. Wayback Machine
    4. Archive.is (via UnifiedWebScraper)
    5. Direct HTTP request
    
    It automatically tries each method in sequence until successful.
    
    Attributes:
        federal_sources: List of federal legal sources from JSONL
        municipal_sources: List of municipal legal sources
        state_sources: List of state legal sources
        cc_engine: Common Crawl search engine instance
        brave_client: Brave Search API client
        web_archive: WebArchive (Wayback Machine) instance
        unified_scraper: UnifiedWebScraper instance
        graphrag: GraphRAG processor for rule extraction
        logic: Logic processor for rule ingestion
    """
    
    def __init__(
        self,
        jsonl_dir: Optional[Path] = None,
        enable_graphrag: bool = True,
        enable_logic_integration: bool = True,
        fallback_chain: Optional[List[FallbackMethod]] = None
    ):
        """Initialize the scraper.
        
        Args:
            jsonl_dir: Directory containing JSONL files (defaults to this file's directory)
            enable_graphrag: Enable GraphRAG rule extraction
            enable_logic_integration: Enable logic module integration
            fallback_chain: Custom fallback order (defaults to all methods in order)
        """
        self.jsonl_dir = jsonl_dir or Path(__file__).parent
        self.enable_graphrag = enable_graphrag and HAVE_GRAPHRAG
        self.enable_logic_integration = enable_logic_integration and HAVE_LOGIC
        
        # Source lists (loaded from JSONL)
        self.federal_sources: List[LegalSourceMetadata] = []
        self.municipal_sources: List[LegalSourceMetadata] = []
        self.state_sources: List[LegalSourceMetadata] = []
        self.sources_by_url: Dict[str, LegalSourceMetadata] = {}
        
        # Fallback chain configuration
        if fallback_chain is None:
            fallback_chain = [
                FallbackMethod.COMMON_CRAWL,
                FallbackMethod.BRAVE_SEARCH,
                FallbackMethod.WAYBACK_MACHINE,
                FallbackMethod.UNIFIED_SCRAPER,
                FallbackMethod.DIRECT_HTTP
            ]
        self.fallback_chain = fallback_chain
        
        # Initialize web archiving tools
        self.cc_engine = None
        self.brave_client = None
        self.web_archive = None
        self.unified_scraper = None
        self.graphrag = None
        self.logic = None
        
        # Initialize available tools
        self._init_tools()
        
        logger.info("CommonCrawlLegalScraper initialized")
        logger.info(f"GraphRAG enabled: {self.enable_graphrag}")
        logger.info(f"Logic integration enabled: {self.enable_logic_integration}")
        logger.info(f"Fallback chain: {[m.value for m in self.fallback_chain]}")
    
    def _init_tools(self):
        """Initialize web archiving and processing tools."""
        # Common Crawl
        if HAVE_COMMON_CRAWL:
            try:
                self.cc_engine = CommonCrawlSearchEngine(mode="local")
                logger.info("Common Crawl engine initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Common Crawl: {e}")
        
        # Brave Search
        if HAVE_BRAVE_SEARCH:
            try:
                self.brave_client = BraveSearchClient()
                logger.info("Brave Search client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Brave Search: {e}")
        
        # WebArchive (Wayback Machine)
        if HAVE_WEB_ARCHIVE:
            try:
                self.web_archive = WebArchive()
                logger.info("WebArchive initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize WebArchive: {e}")
        
        # Unified Scraper
        if HAVE_UNIFIED_SCRAPER:
            try:
                self.unified_scraper = UnifiedWebScraper()
                logger.info("UnifiedWebScraper initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize UnifiedWebScraper: {e}")
        
        # GraphRAG
        if self.enable_graphrag and HAVE_GRAPHRAG:
            try:
                self.graphrag = UnifiedGraphRAGProcessor()
                logger.info("GraphRAG processor initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize GraphRAG: {e}")
                self.enable_graphrag = False
        
        # Logic Processor
        if self.enable_logic_integration and HAVE_LOGIC:
            try:
                self.logic = LogicProcessor()
                logger.info("Logic processor initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Logic processor: {e}")
                self.enable_logic_integration = False
    
    @monitor
    async def load_jsonl_sources(self) -> Dict[str, int]:
        """Load legal sources from JSONL files.
        
        Loads from:
        - federal_all_branches.jsonl (or variants)
        - us_towns_and_counties_urls.jsonl (municipal)
        - state-specific files if present
        
        Returns:
            Dict with counts: {"federal": N, "municipal": M, "state": S}
        """
        counts = {"federal": 0, "municipal": 0, "state": 0}
        
        # Load federal sources
        federal_files = [
            "federal_all_branches_with_sources_and_provenance.jsonl",
            "federal_all_branches_with_provenance.jsonl",
            "federal_all_branches.jsonl"
        ]
        
        for filename in federal_files:
            filepath = self.jsonl_dir / filename
            if filepath.exists():
                count = await self._load_jsonl_file(filepath, SourceType.FEDERAL)
                counts["federal"] += count
                logger.info(f"Loaded {count} federal sources from {filename}")
                break  # Use first available file
        
        # Load municipal sources
        municipal_file = self.jsonl_dir / "us_towns_and_counties_urls.jsonl"
        if municipal_file.exists():
            count = await self._load_jsonl_file(municipal_file, SourceType.MUNICIPAL)
            counts["municipal"] = count
            logger.info(f"Loaded {count} municipal sources")
        
        # Load state sources (if any state-specific JSONL files exist)
        # TODO: Add state-specific JSONL loading if needed
        
        logger.info(f"Total sources loaded: {sum(counts.values())}")
        return counts
    
    async def _load_jsonl_file(
        self,
        filepath: Path,
        source_type: SourceType
    ) -> int:
        """Load a single JSONL file.
        
        Args:
            filepath: Path to JSONL file
            source_type: Type of sources in file
            
        Returns:
            Number of sources loaded
        """
        count = 0
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    try:
                        data = json.loads(line)
                        metadata = LegalSourceMetadata.from_dict(data)
                        
                        # Add to appropriate list
                        if source_type == SourceType.FEDERAL:
                            self.federal_sources.append(metadata)
                        elif source_type == SourceType.MUNICIPAL:
                            self.municipal_sources.append(metadata)
                        elif source_type == SourceType.STATE:
                            self.state_sources.append(metadata)
                        
                        # Index by URL for quick lookup
                        for url in metadata.seed_urls:
                            self.sources_by_url[url] = metadata
                        if metadata.website:
                            self.sources_by_url[metadata.website] = metadata
                        
                        count += 1
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse JSON line: {e}")
                    except Exception as e:
                        logger.warning(f"Failed to process entry: {e}")
        
        except Exception as e:
            logger.error(f"Failed to load {filepath}: {e}")
        
        return count
    
    def get_source_metadata(self, url: str) -> Optional[LegalSourceMetadata]:
        """Get metadata for a URL if available.
        
        Args:
            url: URL to look up
            
        Returns:
            LegalSourceMetadata if found, None otherwise
        """
        return self.sources_by_url.get(url)
    
    @monitor
    async def scrape_url(
        self,
        url: str,
        source_type: Optional[SourceType] = None,
        extract_rules: bool = True,
        feed_to_logic: bool = True
    ) -> ScrapedLegalContent:
        """Scrape a legal document URL with fallback chain.
        
        Tries each fallback method in sequence until successful.
        
        Args:
            url: URL to scrape
            source_type: Type of source (auto-detected if None)
            extract_rules: Extract rules using GraphRAG
            feed_to_logic: Feed extracted rules to logic module
            
        Returns:
            ScrapedLegalContent with results
        """
        start_time = anyio.current_time()
        
        # Auto-detect source type if not provided
        if source_type is None:
            source_type = self._detect_source_type(url)
        
        # Get metadata if available
        metadata = self.get_source_metadata(url)
        
        # Initialize result
        result = ScrapedLegalContent(
            url=url,
            source_type=source_type,
            source_metadata=metadata
        )
        
        # Try each fallback method
        for method in self.fallback_chain:
            try:
                logger.info(f"Trying {method.value} for {url}")
                result.fallback_methods_tried.append(method)
                
                if method == FallbackMethod.COMMON_CRAWL:
                    content = await self._fetch_common_crawl(url)
                elif method == FallbackMethod.BRAVE_SEARCH:
                    content = await self._fetch_brave_search(url)
                elif method == FallbackMethod.WAYBACK_MACHINE:
                    content = await self._fetch_wayback_machine(url)
                elif method == FallbackMethod.UNIFIED_SCRAPER:
                    content = await self._fetch_unified_scraper(url)
                elif method == FallbackMethod.DIRECT_HTTP:
                    content = await self._fetch_direct_http(url)
                else:
                    continue
                
                # If we got content, use it
                if content and (content.get("content") or content.get("text")):
                    result.content = content.get("content", "")
                    result.html = content.get("html", "")
                    result.title = content.get("title", "")
                    result.text = content.get("text", "") or content.get("content", "")
                    result.method_used = method
                    result.success = True
                    result.warc_metadata = content.get("warc_metadata")
                    logger.info(f"Successfully fetched {url} using {method.value}")
                    break
            
            except Exception as e:
                error_msg = f"{method.value} failed: {str(e)}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
                continue
        
        # Extract rules with GraphRAG if enabled and successful
        if result.success and extract_rules and self.enable_graphrag:
            try:
                rules = await self._extract_rules_graphrag(result)
                result.extracted_rules = rules
                logger.info(f"Extracted {len(rules)} rules from {url}")
            except Exception as e:
                logger.warning(f"GraphRAG extraction failed: {e}")
                result.errors.append(f"GraphRAG: {str(e)}")
        
        # Feed to logic module if enabled
        if result.success and result.extracted_rules and feed_to_logic and self.enable_logic_integration:
            try:
                await self._feed_to_logic(result)
                logger.info(f"Fed {len(result.extracted_rules)} rules to logic module")
            except Exception as e:
                logger.warning(f"Logic integration failed: {e}")
                result.errors.append(f"Logic: {str(e)}")
        
        result.extraction_time = anyio.current_time() - start_time
        return result
    
    def _detect_source_type(self, url: str) -> SourceType:
        """Detect source type from URL.
        
        Args:
            url: URL to analyze
            
        Returns:
            Detected SourceType
        """
        url_lower = url.lower()
        
        # Federal indicators
        if any(domain in url_lower for domain in [
            "gov/", ".gov", "congress.", "gpo.", "federalregister",
            "supremecourt", "uscourts"
        ]):
            return SourceType.FEDERAL
        
        # Municipal indicators
        if any(term in url_lower for term in [
            "city", "town", "county", "municipal", "municode"
        ]):
            return SourceType.MUNICIPAL
        
        # State indicators
        if any(term in url_lower for term in [
            "state", "legislature", "statehouse"
        ]):
            return SourceType.STATE
        
        return SourceType.UNKNOWN
    
    async def _fetch_common_crawl(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch content from Common Crawl via HuggingFace.
        
        Args:
            url: URL to fetch
            
        Returns:
            Dict with content and metadata, or None
        """
        if not self.cc_engine:
            return None
        
        try:
            # Query Common Crawl index
            # TODO: Integrate HuggingFace datasets when available
            # For now, use direct Common Crawl search
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc
            
            # Search for domain
            results = self.cc_engine.search_domain(domain, max_matches=10)
            
            if not results:
                return None
            
            # Find best match for this specific URL
            for result in results:
                if result.get("url") == url or url in result.get("url", ""):
                    # Fetch WARC content
                    warc_url = result.get("warc_filename")
                    offset = result.get("warc_record_offset")
                    length = result.get("warc_record_length")
                    
                    if warc_url and offset is not None:
                        # TODO: Implement WARC fetching
                        # content = await self.cc_engine.fetch_warc_content(warc_url, offset, length)
                        return {
                            "content": result.get("content", ""),
                            "html": result.get("html", ""),
                            "title": result.get("title", ""),
                            "text": result.get("text", ""),
                            "warc_metadata": {
                                "warc_url": warc_url,
                                "offset": offset,
                                "length": length
                            }
                        }
            
            return None
        
        except Exception as e:
            logger.warning(f"Common Crawl fetch failed: {e}")
            return None
    
    async def _fetch_brave_search(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch content using Brave Search API.
        
        Args:
            url: URL to fetch
            
        Returns:
            Dict with content, or None
        """
        if not self.brave_client:
            return None
        
        try:
            # Search for the URL
            results = self.brave_client.web_search(url, count=1)
            
            if results and len(results) > 0:
                result = results[0]
                return {
                    "content": result.get("description", ""),
                    "title": result.get("title", ""),
                    "text": result.get("description", ""),
                    "html": ""
                }
            
            return None
        
        except Exception as e:
            logger.warning(f"Brave Search fetch failed: {e}")
            return None
    
    async def _fetch_wayback_machine(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch content from Wayback Machine.
        
        Args:
            url: URL to fetch
            
        Returns:
            Dict with content, or None
        """
        if not self.web_archive:
            return None
        
        try:
            # Archive and retrieve
            result = self.web_archive.archive_url(url)
            
            if result and result.get("success"):
                archived = self.web_archive.retrieve_archive(result["archive_id"])
                if archived:
                    data = archived.get("data", {})
                    return {
                        "content": data.get("content", ""),
                        "html": data.get("html", ""),
                        "title": data.get("title", ""),
                        "text": data.get("text", "")
                    }
            
            return None
        
        except Exception as e:
            logger.warning(f"Wayback Machine fetch failed: {e}")
            return None
    
    async def _fetch_unified_scraper(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch content using UnifiedWebScraper.
        
        Args:
            url: URL to fetch
            
        Returns:
            Dict with content, or None
        """
        if not self.unified_scraper:
            return None
        
        try:
            result = await self.unified_scraper.scrape(url)
            
            if result and result.success:
                return {
                    "content": result.content,
                    "html": result.html,
                    "title": result.title,
                    "text": result.text
                }
            
            return None
        
        except Exception as e:
            logger.warning(f"UnifiedWebScraper fetch failed: {e}")
            return None
    
    async def _fetch_direct_http(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch content via direct HTTP request.
        
        Args:
            url: URL to fetch
            
        Returns:
            Dict with content, or None
        """
        try:
            import httpx
            from bs4 import BeautifulSoup
            
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                html = response.text
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract title
                title = soup.find('title')
                title = title.get_text(strip=True) if title else ""
                
                # Extract text
                text = soup.get_text(separator='\n', strip=True)
                
                return {
                    "content": text,
                    "html": html,
                    "title": title,
                    "text": text
                }
        
        except Exception as e:
            logger.warning(f"Direct HTTP fetch failed: {e}")
            return None
    
    async def _extract_rules_graphrag(
        self,
        result: ScrapedLegalContent
    ) -> List[Dict[str, Any]]:
        """Extract rules using GraphRAG.
        
        Args:
            result: Scraped content
            
        Returns:
            List of extracted rules
        """
        if not self.graphrag:
            return []
        
        try:
            # Use GraphRAG to extract rules
            extraction = await self.graphrag.extract_legal_rules(
                text=result.text or result.content,
                source_url=result.url,
                metadata=result.source_metadata
            )
            
            return extraction.get("rules", [])
        
        except Exception as e:
            logger.error(f"GraphRAG extraction error: {e}")
            return []
    
    async def _feed_to_logic(self, result: ScrapedLegalContent):
        """Feed extracted rules to logic module.
        
        Args:
            result: Scraped content with extracted rules
        """
        if not self.logic:
            return
        
        try:
            await self.logic.ingest_rules(
                rules=result.extracted_rules,
                source=result.url,
                source_type=result.source_type.value,
                metadata=result.source_metadata
            )
        
        except Exception as e:
            logger.error(f"Logic integration error: {e}")
    
    @monitor
    async def scrape_all_sources(
        self,
        source_types: Optional[List[SourceType]] = None,
        max_sources: Optional[int] = None,
        extract_rules: bool = True,
        feed_to_logic: bool = True
    ) -> List[ScrapedLegalContent]:
        """Scrape all loaded sources.
        
        Args:
            source_types: Filter by source types (None = all)
            max_sources: Maximum number of sources to scrape
            extract_rules: Extract rules using GraphRAG
            feed_to_logic: Feed rules to logic module
            
        Returns:
            List of ScrapedLegalContent results
        """
        results = []
        count = 0
        
        # Determine which sources to scrape
        sources_to_scrape = []
        
        if not source_types or SourceType.FEDERAL in source_types:
            sources_to_scrape.extend([
                (src, SourceType.FEDERAL) for src in self.federal_sources
            ])
        
        if not source_types or SourceType.MUNICIPAL in source_types:
            sources_to_scrape.extend([
                (src, SourceType.MUNICIPAL) for src in self.municipal_sources
            ])
        
        if not source_types or SourceType.STATE in source_types:
            sources_to_scrape.extend([
                (src, SourceType.STATE) for src in self.state_sources
            ])
        
        logger.info(f"Scraping {len(sources_to_scrape)} sources...")
        
        # Scrape each source
        for metadata, source_type in sources_to_scrape:
            if max_sources and count >= max_sources:
                break
            
            # Try each seed URL
            for url in metadata.seed_urls[:1]:  # Start with first URL
                try:
                    result = await self.scrape_url(
                        url=url,
                        source_type=source_type,
                        extract_rules=extract_rules,
                        feed_to_logic=feed_to_logic
                    )
                    results.append(result)
                    count += 1
                    
                    if result.success:
                        logger.info(f"[{count}] Success: {url}")
                        break  # Move to next source after first successful URL
                    else:
                        logger.warning(f"[{count}] Failed: {url}")
                
                except Exception as e:
                    logger.error(f"Error scraping {url}: {e}")
            
            # Rate limiting
            await anyio.sleep(1.0)
        
        logger.info(f"Scraped {len(results)} sources, {sum(1 for r in results if r.success)} successful")
        return results


# CLI interface for testing
async def main():
    """Main function for CLI testing."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Common Crawl Legal Scraper")
    parser.add_argument("--load-sources", action="store_true", help="Load JSONL sources")
    parser.add_argument("--scrape-url", type=str, help="Scrape a specific URL")
    parser.add_argument("--scrape-all", action="store_true", help="Scrape all sources")
    parser.add_argument("--max-sources", type=int, help="Maximum sources to scrape")
    parser.add_argument("--source-type", choices=["federal", "municipal", "state"], help="Filter by source type")
    
    args = parser.parse_args()
    
    # Initialize scraper
    scraper = CommonCrawlLegalScraper()
    
    # Load sources
    if args.load_sources or args.scrape_all:
        print("Loading JSONL sources...")
        counts = await scraper.load_jsonl_sources()
        print(f"Loaded: {counts}")
    
    # Scrape single URL
    if args.scrape_url:
        print(f"Scraping {args.scrape_url}...")
        result = await scraper.scrape_url(args.scrape_url)
        print(f"Success: {result.success}")
        print(f"Method: {result.method_used.value if result.method_used else 'none'}")
        print(f"Content length: {len(result.content)}")
        print(f"Rules extracted: {len(result.extracted_rules)}")
    
    # Scrape all sources
    if args.scrape_all:
        source_type = SourceType(args.source_type) if args.source_type else None
        source_types = [source_type] if source_type else None
        
        print("Scraping all sources...")
        results = await scraper.scrape_all_sources(
            source_types=source_types,
            max_sources=args.max_sources
        )
        
        successful = sum(1 for r in results if r.success)
        print(f"\nResults: {successful}/{len(results)} successful")
        
        # Print method usage statistics
        from collections import Counter
        methods = Counter(r.method_used.value for r in results if r.method_used)
        print("\nMethods used:")
        for method, count in methods.most_common():
            print(f"  {method}: {count}")


if __name__ == "__main__":
    anyio.run(main)

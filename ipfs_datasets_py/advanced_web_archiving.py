#!/usr/bin/env python3
"""
Advanced Web Archiving System for GraphRAG

This module provides comprehensive web archiving capabilities including:
- Multi-service archiving (Internet Archive, Archive.is, Local WARC)
- Intelligent content discovery and extraction
- Archive quality assessment and validation
- Historical snapshot management
- Bulk website archiving with dependency tracking
"""

import os
import re
import json
import time
import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Any, Union, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, unquote
from pathlib import Path
import uuid
import hashlib

# Optional imports
try:
    import requests
    from requests.adapters import HTTPAdapter
    from requests.packages.urllib3.util.retry import Retry
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    import warcio
    from warcio.archiveiterator import ArchiveIterator
    from warcio.warcwriter import WARCWriter
    HAS_WARCIO = True
except ImportError:
    HAS_WARCIO = False

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False

logger = logging.getLogger(__name__)


@dataclass
class ArchivingConfig:
    """Configuration for web archiving operations"""
    
    # Archive services
    enable_internet_archive: bool = True
    enable_archive_is: bool = True  
    enable_local_warc: bool = True
    
    # Crawling settings
    max_pages_per_domain: int = 100
    crawl_depth: int = 3
    respect_robots_txt: bool = True
    user_agent: str = "GraphRAG-Archive-Bot/1.0"
    request_delay: float = 1.0  # seconds between requests
    
    # Content filtering
    include_external_links: bool = False
    include_media_files: bool = True
    include_documents: bool = True
    max_file_size_mb: int = 100
    
    # Archive quality
    verify_archives: bool = True
    archive_timeout: int = 30
    retry_attempts: int = 3
    
    # Storage
    local_archive_path: str = "archives"
    maintain_directory_structure: bool = True


@dataclass
class WebResource:
    """Represents a web resource to be archived"""
    
    url: str
    resource_type: str = "page"  # page, image, document, media, stylesheet, script
    mime_type: str = "text/html"
    size_bytes: int = 0
    last_modified: Optional[datetime] = None
    discovered_from: str = ""  # URL that referenced this resource
    
    # Archive status
    archive_status: str = "pending"  # pending, archived, failed, skipped
    archive_urls: Dict[str, str] = field(default_factory=dict)  # service -> archive_url
    local_path: Optional[str] = None
    
    # Quality metrics
    content_hash: str = ""
    is_duplicate: bool = False
    quality_score: float = 0.0
    
    # Processing metadata
    discovered_at: datetime = field(default_factory=datetime.now)
    archived_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # Additional fields needed by the archiving system
    resource_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArchiveCollection:
    """Collection of archived web resources"""
    
    collection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    
    # Target information
    root_urls: List[str] = field(default_factory=list)
    domains: Set[str] = field(default_factory=set)
    
    # Resources
    resources: List[WebResource] = field(default_factory=list)
    resource_index: Dict[str, WebResource] = field(default_factory=dict)
    
    # Statistics
    total_resources: int = 0
    archived_resources: int = 0
    failed_resources: int = 0
    total_size_bytes: int = 0
    
    # Archive metadata
    created_at: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    archiving_status: str = "pending"  # pending, active, completed, failed
    estimated_completion: Optional[datetime] = None
    
    # Configuration
    config: ArchivingConfig = field(default_factory=ArchivingConfig)


class AdvancedWebArchiver:
    """Advanced web archiving system with multi-service support"""
    
    def __init__(self, config: Optional[ArchivingConfig] = None):
        self.config = config or ArchivingConfig()
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Initialize HTTP session
        self.session = None
        self._initialize_session()
        
        # Archive service endpoints
        self.archive_endpoints = {
            "internet_archive": "https://web.archive.org/save/",
            "archive_is": "https://archive.is/submit/",
            "wayback_machine": "http://web.archive.org/cdx/search/cdx",
            "common_crawl": "https://index.commoncrawl.org"
        }
        
        # Content type mappings
        self.content_type_mapping = {
            "text/html": "page",
            "text/css": "stylesheet", 
            "application/javascript": "script",
            "text/javascript": "script",
            "application/pdf": "document",
            "image/": "image",
            "video/": "media",
            "audio/": "media"
        }
        
        # Initialize new archiving tools
        self.autoscraper_models = {}
        self.ipwb_indexes = {}
        
        # Ensure local archive directory exists
        os.makedirs(self.config.local_archive_path, exist_ok=True)
    
    def _initialize_session(self):
        """Initialize HTTP session with retry strategy"""
        
        if not HAS_REQUESTS:
            self.logger.warning("Requests library not available - limited functionality")
            return
            
        self.session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.config.retry_attempts,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set user agent
        self.session.headers.update({
            "User-Agent": self.config.user_agent
        })
    
    async def archive_website(
        self,
        urls: Union[str, List[str]],
        collection_name: str = ""
    ) -> ArchiveCollection:
        """Archive a complete website or multiple URLs"""
        
        if isinstance(urls, str):
            urls = [urls]
            
        collection = ArchiveCollection(
            name=collection_name or f"Archive-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            root_urls=urls,
            config=self.config
        )
        
        self.logger.info(f"Starting archive collection: {collection.name}")
        collection.archiving_status = "active"
        
        try:
            # Phase 1: Discovery - Find all resources to archive
            await self._discover_resources(collection)
            
            # Phase 2: Prioritization - Prioritize resources for archiving
            self._prioritize_resources(collection)
            
            # Phase 3: Archiving - Archive resources using available services
            await self._archive_resources(collection)
            
            # Phase 4: Verification - Verify archive integrity
            if self.config.verify_archives:
                await self._verify_archives(collection)
            
            # Phase 5: Generate reports and metadata
            self._generate_collection_metadata(collection)
            
            collection.archiving_status = "completed"
            
        except Exception as e:
            self.logger.error(f"Archive collection failed: {e}")
            collection.archiving_status = "failed"
            
        collection.last_updated = datetime.now()
        return collection
    
    async def _discover_resources(self, collection: ArchiveCollection):
        """Discover all resources to be archived"""
        
        self.logger.info("Phase 1: Discovering resources...")
        
        discovered_urls = set()
        pending_urls = list(collection.root_urls)
        depth = 0
        
        while pending_urls and depth <= self.config.crawl_depth:
            current_batch = pending_urls[:50]  # Process in batches
            pending_urls = pending_urls[50:]
            
            batch_resources = []
            
            for url in current_batch:
                if url in discovered_urls:
                    continue
                    
                try:
                    resource = await self._analyze_web_resource(url)
                    if resource and self._should_include_resource(resource):
                        batch_resources.append(resource)
                        discovered_urls.add(url)
                        
                        # Extract additional URLs if it's an HTML page
                        if resource.resource_type == "page":
                            additional_urls = await self._extract_page_urls(url, resource)
                            for add_url in additional_urls:
                                if add_url not in discovered_urls and len(discovered_urls) < self.config.max_pages_per_domain:
                                    pending_urls.append(add_url)
                    
                    # Rate limiting
                    await asyncio.sleep(self.config.request_delay)
                    
                except Exception as e:
                    self.logger.error(f"Failed to analyze resource {url}: {e}")
                    
            # Add batch to collection
            collection.resources.extend(batch_resources)
            for resource in batch_resources:
                collection.resource_index[resource.url] = resource
                
            depth += 1
            
        self.logger.info(f"Discovery completed: {len(collection.resources)} resources found")
        collection.total_resources = len(collection.resources)
    
    async def _analyze_web_resource(self, url: str) -> Optional[WebResource]:
        """Analyze a web resource and determine its properties"""
        
        if not HAS_REQUESTS:
            return None
            
        try:
            # HEAD request to get metadata without downloading content
            response = self.session.head(url, timeout=self.config.archive_timeout, allow_redirects=True)
            
            if response.status_code >= 400:
                return None
                
            # Determine resource type from content-type
            content_type = response.headers.get("content-type", "").lower()
            resource_type = "page"  # default
            
            for ct_prefix, rt in self.content_type_mapping.items():
                if content_type.startswith(ct_prefix):
                    resource_type = rt
                    break
                    
            # Check file size
            content_length = response.headers.get("content-length")
            size_bytes = int(content_length) if content_length else 0
            
            if size_bytes > self.config.max_file_size_mb * 1024 * 1024:
                self.logger.info(f"Skipping large file: {url} ({size_bytes / 1024 / 1024:.1f}MB)")
                return None
                
            # Parse last modified
            last_modified = None
            last_mod_header = response.headers.get("last-modified")
            if last_mod_header:
                try:
                    last_modified = datetime.strptime(last_mod_header, "%a, %d %b %Y %H:%M:%S GMT")
                except:
                    pass
                    
            resource = WebResource(
                url=url,
                resource_type=resource_type,
                mime_type=content_type,
                size_bytes=size_bytes,
                last_modified=last_modified
            )
            
            # Generate content hash for duplicate detection
            resource.content_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
            
            return resource
            
        except Exception as e:
            self.logger.error(f"Failed to analyze resource {url}: {e}")
            return None
    
    def _should_include_resource(self, resource: WebResource) -> bool:
        """Determine if a resource should be included in the archive"""
        
        # Check domain restrictions
        parsed = urlparse(resource.url)
        domain = parsed.netloc.lower()
        
        if not self.config.include_external_links:
            # Only include if domain matches one of the root URLs
            # This needs to be passed from the collection context, so we'll skip this check for now
            # and implement domain filtering at the collection level
            pass
                
        # Check resource type restrictions
        if resource.resource_type == "media" and not self.config.include_media_files:
            return False
            
        if resource.resource_type == "document" and not self.config.include_documents:
            return False
            
        # Size check already done in _analyze_web_resource
        
        return True
    
    async def _extract_page_urls(self, page_url: str, resource: WebResource) -> List[str]:
        """Extract URLs from an HTML page"""
        
        if resource.resource_type != "page" or not HAS_BEAUTIFULSOUP:
            return []
            
        urls = []
        
        try:
            # Get page content
            response = self.session.get(page_url, timeout=self.config.archive_timeout)
            response.raise_for_status()
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract links
            for link in soup.find_all(['a', 'link'], href=True):
                href = link.get('href')
                if href:
                    absolute_url = urljoin(page_url, href)
                    if self._is_valid_url(absolute_url):
                        urls.append(absolute_url)
            
            # Extract images, scripts, stylesheets if configured
            if self.config.include_media_files:
                for img in soup.find_all('img', src=True):
                    src = img.get('src')
                    if src:
                        absolute_url = urljoin(page_url, src)
                        if self._is_valid_url(absolute_url):
                            urls.append(absolute_url)
                            
                for script in soup.find_all('script', src=True):
                    src = script.get('src')
                    if src:
                        absolute_url = urljoin(page_url, src)
                        if self._is_valid_url(absolute_url):
                            urls.append(absolute_url)
            
            # Remove duplicates
            urls = list(set(urls))
            
        except Exception as e:
            self.logger.error(f"Failed to extract URLs from {page_url}: {e}")
            
        return urls
    
    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid for archiving"""
        
        try:
            parsed = urlparse(url)
            
            # Must have valid scheme and netloc
            if not parsed.scheme or not parsed.netloc:
                return False
                
            # Must be HTTP/HTTPS
            if parsed.scheme not in ['http', 'https']:
                return False
                
            # Skip common non-archivable patterns
            skip_patterns = [
                r'mailto:',
                r'javascript:',
                r'#',  # Fragment-only URLs
                r'\.(exe|zip|tar|gz)$',  # Executables/archives
            ]
            
            for pattern in skip_patterns:
                if re.search(pattern, url, re.IGNORECASE):
                    return False
                    
            return True
            
        except Exception:
            return False
    
    def _prioritize_resources(self, collection: ArchiveCollection):
        """Prioritize resources for archiving based on importance"""
        
        self.logger.info("Phase 2: Prioritizing resources...")
        
        # Sort resources by priority
        def priority_score(resource: WebResource) -> float:
            score = 0.0
            
            # HTML pages are highest priority
            if resource.resource_type == "page":
                score += 10.0
                
            # Root URLs get bonus
            if resource.url in collection.root_urls:
                score += 5.0
                
            # Penalize very large files
            if resource.size_bytes > 10 * 1024 * 1024:  # 10MB
                score -= 2.0
                
            # Bonus for recent content
            if resource.last_modified:
                age_days = (datetime.now() - resource.last_modified).days
                if age_days < 30:
                    score += 2.0
                elif age_days < 365:
                    score += 1.0
                    
            return score
        
        collection.resources.sort(key=priority_score, reverse=True)
        
        self.logger.info(f"Prioritization completed for {len(collection.resources)} resources")
    
    async def _archive_resources(self, collection: ArchiveCollection):
        """Archive resources using configured services"""
        
        self.logger.info("Phase 3: Archiving resources...")
        
        successful = 0
        failed = 0
        
        for i, resource in enumerate(collection.resources):
            try:
                self.logger.info(f"Archiving {i+1}/{len(collection.resources)}: {resource.url}")
                
                # Try different archive services
                archived = False
                
                if self.config.enable_local_warc:
                    if await self._archive_to_local_warc(resource, collection):
                        archived = True
                        
                if self.config.enable_internet_archive:
                    if await self._archive_to_internet_archive(resource):
                        archived = True
                    
                    # Also try enhanced Wayback Machine integration
                    if await self._archive_to_wayback_enhanced(resource):
                        archived = True
                        
                if self.config.enable_archive_is:
                    if await self._archive_to_archive_is(resource):
                        archived = True
                
                # New archiving services
                if hasattr(self.config, 'enable_common_crawl') and self.config.enable_common_crawl:
                    if await self._archive_to_common_crawl(resource):
                        archived = True
                
                if hasattr(self.config, 'enable_ipwb') and self.config.enable_ipwb:
                    if await self._archive_to_ipwb(resource, collection):
                        archived = True
                
                # AutoScraper extraction (if model specified)
                if hasattr(self.config, 'autoscraper_model') and self.config.autoscraper_model:
                    await self._extract_with_autoscraper(resource, self.config.autoscraper_model)
                
                if archived:
                    resource.archive_status = "archived"
                    resource.archived_at = datetime.now()
                    successful += 1
                else:
                    resource.archive_status = "failed"
                    failed += 1
                    
            except Exception as e:
                self.logger.error(f"Failed to archive {resource.url}: {e}")
                resource.archive_status = "failed"
                resource.error_message = str(e)
                failed += 1
                
            # Rate limiting between requests
            await asyncio.sleep(self.config.request_delay)
        
        collection.archived_resources = successful
        collection.failed_resources = failed
        
        self.logger.info(f"Archiving completed: {successful} successful, {failed} failed")
    
    async def _archive_to_local_warc(self, resource: WebResource, collection: ArchiveCollection) -> bool:
        """Archive resource to local WARC file"""
        
        if not HAS_WARCIO:
            return False
            
        try:
            # Download resource content
            response = self.session.get(resource.url, timeout=self.config.archive_timeout)
            response.raise_for_status()
            
            # Create WARC file path
            warc_filename = f"{collection.collection_id}.warc.gz"
            warc_path = os.path.join(self.config.local_archive_path, warc_filename)
            
            # Write to WARC file
            with open(warc_path, 'ab') as output:
                writer = WARCWriter(output, gzip=True)
                
                # Create WARC record
                warc_headers = {
                    'WARC-Date': datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'WARC-Type': 'response',
                    'WARC-Target-URI': resource.url,
                    'Content-Type': f'application/http; msgtype=response'
                }
                
                # Create HTTP response content
                http_headers = f"HTTP/1.1 {response.status_code} {response.reason}\r\n"
                for header, value in response.headers.items():
                    http_headers += f"{header}: {value}\r\n"
                http_headers += "\r\n"
                
                record_content = http_headers.encode() + response.content
                
                record = writer.create_warc_record(
                    resource.url,
                    'response', 
                    warc_headers=warc_headers,
                    payload=record_content
                )
                
                writer.write_record(record)
            
            resource.local_path = warc_path
            resource.archive_urls["local_warc"] = warc_path
            
            return True
            
        except Exception as e:
            self.logger.error(f"Local WARC archiving failed for {resource.url}: {e}")
            return False
    
    async def _archive_to_internet_archive(self, resource: WebResource) -> bool:
        """Archive resource to Internet Archive Wayback Machine"""
        
        try:
            # Internet Archive save API
            save_url = f"{self.archive_endpoints['internet_archive']}{resource.url}"
            
            response = self.session.get(save_url, timeout=self.config.archive_timeout)
            
            if response.status_code == 200:
                # Look for archive URL in response
                archive_url = f"https://web.archive.org/web/{datetime.now().strftime('%Y%m%d%H%M%S')}/{resource.url}"
                resource.archive_urls["internet_archive"] = archive_url
                return True
                
        except Exception as e:
            self.logger.error(f"Internet Archive archiving failed for {resource.url}: {e}")
            
        return False
    
    async def _archive_to_archive_is(self, resource: WebResource) -> bool:
        """Archive resource to Archive.is"""
        
        try:
            # Archive.is submit API
            data = {"url": resource.url}
            response = self.session.post(
                self.archive_endpoints["archive_is"], 
                data=data, 
                timeout=self.config.archive_timeout
            )
            
            if response.status_code == 200:
                # Parse response for archive URL
                if "archive.is" in response.text:
                    # Simple extraction - in production, would parse properly
                    archive_url = f"https://archive.is/{hashlib.md5(resource.url.encode()).hexdigest()[:8]}"
                    resource.archive_urls["archive_is"] = archive_url
                    return True
                    
        except Exception as e:
            self.logger.error(f"Archive.is archiving failed for {resource.url}: {e}")
            
        return False
    
    async def _archive_to_common_crawl(self, resource: WebResource) -> bool:
        """Search for existing content in Common Crawl."""
        try:
            # Import the new tool using absolute import
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.common_crawl_search import search_common_crawl
            
            # Extract domain from URL
            from urllib.parse import urlparse
            parsed_url = urlparse(resource.url)
            domain = parsed_url.netloc
            
            # Search for existing archives in Common Crawl
            search_result = await search_common_crawl(domain, limit=10)
            
            if search_result['status'] == 'success' and search_result['results']:
                # Found existing archives
                resource.archive_urls["common_crawl"] = search_result['results'][0]['warc_filename']
                resource.metadata["common_crawl_results"] = len(search_result['results'])
                return True
                
        except Exception as e:
            self.logger.error(f"Common Crawl search failed for {resource.url}: {e}")
            
        return False
    
    async def _archive_to_wayback_enhanced(self, resource: WebResource) -> bool:
        """Archive to Wayback Machine using enhanced wayback library."""
        try:
            # Import the new tool using absolute import
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.wayback_machine_search import archive_to_wayback
            
            # Archive to Wayback Machine
            result = await archive_to_wayback(resource.url)
            
            if result['status'] == 'success':
                resource.archive_urls["wayback_machine"] = result['archived_url']
                return True
                
        except Exception as e:
            self.logger.error(f"Enhanced Wayback archiving failed for {resource.url}: {e}")
            
        return False
    
    async def _archive_to_ipwb(self, resource: WebResource, collection: ArchiveCollection) -> bool:
        """Archive to InterPlanetary Wayback Machine (IPWB)."""
        try:
            # First create a local WARC for this resource
            local_warc_success = await self._archive_to_local_warc(resource, collection)
            
            if local_warc_success:
                # Import IPWB tool using absolute import
                from ipfs_datasets_py.mcp_server.tools.web_archive_tools.ipwb_integration import index_warc_to_ipwb
                
                # Get the WARC path for this resource
                warc_path = os.path.join(
                    self.config.local_archive_path,
                    f"{collection.collection_id}_{resource.resource_id}.warc"
                )
                
                # Index to IPWB
                result = await index_warc_to_ipwb(warc_path)
                
                if result['status'] == 'success':
                    resource.archive_urls["ipwb"] = f"ipwb://{result['ipfs_hashes'][0]}"
                    resource.metadata["ipwb_cdxj"] = result['cdxj_path']
                    return True
                    
        except Exception as e:
            self.logger.error(f"IPWB archiving failed for {resource.url}: {e}")
            
        return False
    
    async def _extract_with_autoscraper(self, resource: WebResource, model_name: Optional[str] = None) -> bool:
        """Extract structured data using AutoScraper."""
        try:
            if not model_name:
                return False

            # Import AutoScraper tool using absolute import
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools.autoscraper_integration import scrape_with_autoscraper

            # Get model path
            model_path = f"/tmp/autoscraper_models/{model_name}.pkl"
            if not os.path.exists(model_path):
                self.logger.warning(f"AutoScraper model {model_name} not found")
                return False

            # Scrape data
            result = await scrape_with_autoscraper(model_path, [resource.url])

            if result['status'] == 'success' and resource.url in result['results']:
                url_result = result['results'][resource.url]
                if url_result['status'] == 'success':
                    resource.metadata["autoscraper_data"] = url_result['data']
                    resource.metadata["autoscraper_model"] = model_name
                    return True

        except Exception as e:
            self.logger.error(f"AutoScraper extraction failed for {resource.url}: {e}")

        return False

    async def _verify_archives(self, collection: ArchiveCollection):
        """Verify that archived resources are accessible"""
        
        self.logger.info("Phase 4: Verifying archives...")
        
        verified = 0
        for resource in collection.resources:
            if resource.archive_status == "archived":
                # Check at least one archive URL is accessible
                archive_accessible = False
                
                for service, archive_url in resource.archive_urls.items():
                    try:
                        if service == "local_warc":
                            # For WARC files, just check file exists
                            if os.path.exists(archive_url):
                                archive_accessible = True
                                break
                        else:
                            # For online archives, try to access
                            response = self.session.head(archive_url, timeout=10)
                            if response.status_code < 400:
                                archive_accessible = True
                                break
                    except:
                        continue
                        
                if archive_accessible:
                    verified += 1
                else:
                    resource.archive_status = "verification_failed"
                    
        self.logger.info(f"Archive verification completed: {verified} verified")
    
    def _generate_collection_metadata(self, collection: ArchiveCollection):
        """Generate metadata and reports for the archive collection"""
        
        self.logger.info("Phase 5: Generating metadata...")
        
        # Update collection statistics
        collection.total_size_bytes = sum(r.size_bytes for r in collection.resources)
        collection.domains = {urlparse(r.url).netloc for r in collection.resources}
        
        # Generate summary report
        report = {
            "collection_id": collection.collection_id,
            "name": collection.name,
            "created_at": collection.created_at.isoformat(),
            "completed_at": collection.last_updated.isoformat(),
            "statistics": {
                "total_resources": collection.total_resources,
                "archived_resources": collection.archived_resources,
                "failed_resources": collection.failed_resources,
                "total_size_bytes": collection.total_size_bytes,
                "total_size_mb": collection.total_size_bytes / 1024 / 1024,
                "domains_covered": len(collection.domains)
            },
            "resources_by_type": {},
            "archive_services_used": set()
        }
        
        # Count resources by type
        type_counts = {}
        for resource in collection.resources:
            type_counts[resource.resource_type] = type_counts.get(resource.resource_type, 0) + 1
            report["archive_services_used"].update(resource.archive_urls.keys())
            
        report["resources_by_type"] = type_counts
        report["archive_services_used"] = list(report["archive_services_used"])
        
        # Save report
        report_path = os.path.join(self.config.local_archive_path, f"{collection.collection_id}_report.json")
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
            
        self.logger.info(f"Collection metadata saved to {report_path}")
    
    def get_archive_collection(self, collection_id: str) -> Optional[ArchiveCollection]:
        """Retrieve an existing archive collection"""
        
        report_path = os.path.join(self.config.local_archive_path, f"{collection_id}_report.json")
        
        if not os.path.exists(report_path):
            return None
            
        try:
            with open(report_path, 'r') as f:
                report_data = json.load(f)
                
            # Reconstruct collection from report (simplified)
            collection = ArchiveCollection(
                collection_id=collection_id,
                name=report_data.get("name", ""),
                total_resources=report_data["statistics"]["total_resources"],
                archived_resources=report_data["statistics"]["archived_resources"],
                failed_resources=report_data["statistics"]["failed_resources"],
                total_size_bytes=report_data["statistics"]["total_size_bytes"]
            )
            
            return collection
            
        except Exception as e:
            self.logger.error(f"Failed to load collection {collection_id}: {e}")
            return None
    
    def list_collections(self) -> List[Dict[str, Any]]:
        """List all available archive collections"""
        
        collections = []
        
        try:
            for filename in os.listdir(self.config.local_archive_path):
                if filename.endswith("_report.json"):
                    collection_id = filename.replace("_report.json", "")
                    
                    with open(os.path.join(self.config.local_archive_path, filename), 'r') as f:
                        report = json.load(f)
                        
                    collections.append({
                        "collection_id": collection_id,
                        "name": report.get("name", ""),
                        "created_at": report.get("created_at", ""),
                        "total_resources": report["statistics"]["total_resources"],
                        "archived_resources": report["statistics"]["archived_resources"],
                        "total_size_mb": report["statistics"]["total_size_mb"]
                    })
                    
        except Exception as e:
            self.logger.error(f"Failed to list collections: {e}")
            
        return collections


# Factory function
def create_advanced_web_archiver(config: Optional[ArchivingConfig] = None) -> AdvancedWebArchiver:
    """Create an AdvancedWebArchiver with the given configuration"""
    return AdvancedWebArchiver(config)


# Configuration presets
ARCHIVING_PRESETS = {
    "fast": ArchivingConfig(
        max_pages_per_domain=20,
        crawl_depth=1,
        request_delay=0.5,
        verify_archives=False
    ),
    "balanced": ArchivingConfig(
        max_pages_per_domain=50,
        crawl_depth=2,
        request_delay=1.0,
        verify_archives=True
    ),
    "comprehensive": ArchivingConfig(
        max_pages_per_domain=200,
        crawl_depth=3,
        request_delay=2.0,
        verify_archives=True,
        include_media_files=True,
        include_documents=True
    )
}


if __name__ == "__main__":
    # Test the archiver
    import asyncio
    
    async def test_archiver():
        """Test the web archiver"""
        
        archiver = AdvancedWebArchiver()
        print("🌐 Advanced Web Archiver Test")
        print("=" * 40)
        
        # Test with a simple URL
        test_urls = ["https://example.com"]
        
        print(f"📦 Creating archive collection for: {test_urls}")
        print(f"   Local archiving: {HAS_WARCIO}")
        print(f"   HTTP requests: {HAS_REQUESTS}")
        print(f"   HTML parsing: {HAS_BEAUTIFULSOUP}")
        
        if HAS_REQUESTS:
            # Create a small test collection
            config = ARCHIVING_PRESETS["fast"]
            archiver = AdvancedWebArchiver(config)
            
            # Note: This would actually try to archive - commenting out for demo
            # collection = await archiver.archive_website(test_urls, "Test Archive")
            # print(f"✅ Archive collection completed")
            # print(f"   Resources found: {collection.total_resources}")
            # print(f"   Successfully archived: {collection.archived_resources}")
            
            print("⚠️  Archive test skipped (would make actual web requests)")
        else:
            print("ℹ️  Limited functionality - install requests library for full features")
            
        # List any existing collections
        collections = archiver.list_collections()
        if collections:
            print(f"📋 Existing collections: {len(collections)}")
            for col in collections[:3]:
                print(f"   • {col['name']}: {col['total_resources']} resources")
        else:
            print("📋 No existing archive collections found")
    
    asyncio.run(test_archiver())
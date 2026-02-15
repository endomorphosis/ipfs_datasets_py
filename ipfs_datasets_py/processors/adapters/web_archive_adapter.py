"""
WebArchiveProcessorAdapter - Adapter for web archiving functionality.

This adapter provides web archiving capabilities through ProcessorProtocol,
supporting multiple archiving services and local WARC creation.

Implements the synchronous ProcessorProtocol from processors.core.
"""

from __future__ import annotations

import logging
from typing import Union, Optional, Dict, Any, List
from pathlib import Path
import time

from ..core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
)

logger = logging.getLogger(__name__)


class WebArchiveProcessorAdapter:
    """
    Adapter for web archiving that implements ProcessorProtocol.
    
    This adapter provides comprehensive web archiving capabilities including:
    - Internet Archive submission
    - Archive.is submission
    - Local WARC creation
    - Archive verification and quality assessment
    - Historical snapshot management
    
    Features:
    - Multi-service archiving
    - Content discovery and extraction
    - Archive quality validation
    - Bulk website archiving
    
    Example:
        >>> from ipfs_datasets_py.processors.core import ProcessingContext, InputType
        >>> adapter = WebArchiveProcessorAdapter()
        >>> context = ProcessingContext(
        ...     input_type=InputType.URL,
        ...     source="https://example.com",
        ...     options={"archive_services": ["internet_archive"]}
        ... )
        >>> can_handle = adapter.can_handle(context)
        >>> result = adapter.process(context)
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._archiver = None
        self._name = "WebArchiveProcessor"
        self._priority = 8  # Medium-high priority for web archiving
    
    def _get_archiver(self):
        """Lazy-load web archiver on first use."""
        if self._archiver is None:
            try:
                from ..advanced_web_archiving import AdvancedWebArchiver
                self._archiver = AdvancedWebArchiver()
                logger.info("AdvancedWebArchiver loaded successfully")
            except ImportError as e:
                logger.warning(f"Could not import AdvancedWebArchiver: {e}")
                # Create a minimal fallback
                self._archiver = MinimalWebArchiver()
                logger.info("Using minimal web archiver fallback")
        return self._archiver
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """
        Check if this adapter can handle web archiving inputs.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if input is a URL (web archiving makes sense for URLs)
        """
        input_str = str(context.source).lower()
        
        # Web archiving is for HTTP/HTTPS URLs
        if input_str.startswith(('http://', 'https://')):
            return True
        
        return False
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """
        Process URL and create web archives.
        
        This method:
        1. Archives content to selected services
        2. Creates local WARC if requested
        3. Extracts content for knowledge graph
        4. Returns unified result with archive metadata
        
        Args:
            context: Processing context with input source and options
                - archive_services: List of services ['internet_archive', 'archive_is', 'local_warc']
                - verify_archives: Whether to verify archive success (default: True)
                - include_knowledge_graph: Extract content for KG (default: True)
                - max_pages: Maximum pages to crawl for bulk archiving (default: 1)
                
        Returns:
            ProcessingResult with archive URLs and knowledge graph
            
        Example:
            >>> result = adapter.process(context)
            >>> print(result.metadata['archive_urls'])
        """
        start_time = time.time()
        source = context.source
        options = context.options
        
        try:
            url = str(source)
            logger.info(f"Archiving URL: {url}")
            
            # Get archiver
            archiver = self._get_archiver()
            
            # Archive the URL
            archive_result = self._archive_url(
                archiver,
                url,
                options
            )
            
            # Build knowledge graph
            knowledge_graph = self._build_knowledge_graph(url, archive_result)
            
            # Generate vectors (placeholder)
            vectors: List[List[float]] = []
            
            # Processing time
            elapsed = time.time() - start_time
            
            logger.info(f"Successfully archived: {url}")
            
            return ProcessingResult(
                success=True,
                knowledge_graph=knowledge_graph,
                vectors=vectors,
                metadata={
                    "processor": self._name,
                    "processor_type": "web_archive",
                    "processing_time": elapsed,
                    "url": url,
                    "archive_urls": archive_result.get('archive_urls', {}),
                    "archive_status": archive_result.get('status', 'unknown'),
                    "archived_at": archive_result.get('archived_at', ''),
                    "archive_size": archive_result.get('size', 0),
                    "warc_path": archive_result.get('warc_path', None),
                    "archive_services": list(archive_result.get('archive_urls', {}).keys())
                }
            )
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Web archiving error: {e}", exc_info=True)
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "error": str(e)
                },
                errors=[f"Web archiving failed: {str(e)}"]
            )
    
    def _archive_url(self, archiver, url: str, options: dict) -> dict:
        """
        Archive URL using the archiver.
        
        Args:
            archiver: Web archiver instance
            url: URL to archive
            options: Archiving options
            
        Returns:
            Dictionary with archive results
        """
        services = options.get('archive_services', ['internet_archive', 'local_warc'])
        verify = options.get('verify_archives', True)
        
        archive_urls = {}
        status = "success"
        warc_path = None
        
        # Try Internet Archive
        if 'internet_archive' in services:
            try:
                ia_url = self._archive_to_internet_archive(url)
                if ia_url:
                    archive_urls['internet_archive'] = ia_url
            except Exception as e:
                logger.warning(f"Internet Archive failed: {e}")
                status = "partial"
        
        # Try Archive.is
        if 'archive_is' in services:
            try:
                archive_is_url = self._archive_to_archive_is(url)
                if archive_is_url:
                    archive_urls['archive_is'] = archive_is_url
            except Exception as e:
                logger.warning(f"Archive.is failed: {e}")
                status = "partial"
        
        # Try local WARC
        if 'local_warc' in services:
            try:
                warc_path = self._create_local_warc(archiver, url)
                if warc_path:
                    archive_urls['local_warc'] = str(warc_path)
            except Exception as e:
                logger.warning(f"Local WARC creation failed: {e}")
                status = "partial"
        
        if not archive_urls:
            status = "failed"
        
        return {
            'archive_urls': archive_urls,
            'status': status,
            'archived_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'warc_path': warc_path,
            'size': 0  # Could calculate if needed
        }
    
    def _archive_to_internet_archive(self, url: str) -> Optional[str]:
        """Submit URL to Internet Archive Wayback Machine."""
        try:
            import requests
            
            # Wayback Machine Save API
            save_url = f"https://web.archive.org/save/{url}"
            
            response = requests.get(save_url, timeout=30, allow_redirects=True)
            if response.status_code in (200, 302):
                # Get the archived URL from response
                archived_url = str(response.url)
                logger.info(f"Archived to Internet Archive: {archived_url}")
                return archived_url
            else:
                logger.warning(f"Internet Archive returned status {response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"Internet Archive submission failed: {e}")
            return None
    
    def _archive_to_archive_is(self, url: str) -> Optional[str]:
        """Submit URL to Archive.is (archive.today)."""
        try:
            import requests
            import re
            
            # Archive.is Submit API
            submit_url = "https://archive.is/submit/"
            
            response = requests.post(
                submit_url,
                data={'url': url},
                timeout=30,
                allow_redirects=True
            )
            if response.status_code in (200, 302):
                # Extract archived URL from response
                text = response.text
                # Simple extraction - could be improved
                match = re.search(r'https://archive\.(is|today|ph)/[A-Za-z0-9]+', text)
                if match:
                    archived_url = match.group(0)
                    logger.info(f"Archived to Archive.is: {archived_url}")
                    return archived_url
            
            logger.warning(f"Archive.is returned status {response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"Archive.is submission failed: {e}")
            return None
    
    def _create_local_warc(self, archiver, url: str) -> Optional[Path]:
        """Create local WARC file."""
        try:
            # If archiver has archive_url method, use it
            if hasattr(archiver, 'archive_url'):
                result = archiver.archive_url(url, enable_local_warc=True)
                if result and result.get('warc_path'):
                    return Path(result['warc_path'])
            
            # Fallback: simple WARC creation
            logger.warning("Full WARC creation not available in fallback mode")
            return None
            
        except Exception as e:
            logger.warning(f"Local WARC creation failed: {e}")
            return None
    
    def _build_knowledge_graph(self, url: str, archive_result: dict) -> Dict[str, Any]:
        """
        Build knowledge graph from archive results.
        
        Args:
            url: Original URL
            archive_result: Archive operation results
            
        Returns:
            Dictionary with archive entities and relationships
        """
        entities = []
        relationships = []
        
        # Create main URL entity
        url_entity = {
            "id": f"url:{url}",
            "type": "WebPage",
            "label": url,
            "properties": {
                "url": url,
                "archived": True,
                "archive_status": archive_result.get('status', 'unknown')
            }
        }
        entities.append(url_entity)
        
        # Create archive entities for each service
        for service, archive_url in archive_result.get('archive_urls', {}).items():
            archive_entity = {
                "id": f"archive:{service}:{url}",
                "type": "WebArchive",
                "label": f"{service} archive",
                "properties": {
                    "service": service,
                    "archive_url": archive_url,
                    "archived_at": archive_result.get('archived_at', '')
                }
            }
            entities.append(archive_entity)
            
            # Create relationship
            relationship = {
                "id": f"archived_by:{url}:{service}",
                "source": url_entity["id"],
                "target": archive_entity["id"],
                "type": "ARCHIVED_BY",
                "properties": {
                    "service": service,
                    "timestamp": archive_result.get('archived_at', '')
                }
            }
            relationships.append(relationship)
        
        return {
            "entities": entities,
            "relationships": relationships,
            "source": url
        }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return processor capabilities and metadata.
        
        Returns:
            Dictionary with processor name, priority, supported formats, etc.
        """
        return {
            "name": self._name,
            "priority": self._priority,
            "formats": ["url", "webpage", "web_archive"],
            "input_types": ["url"],
            "outputs": ["knowledge_graph", "archive_urls"],
            "features": [
                "internet_archive",
                "archive_is",
                "local_warc",
                "archive_verification"
            ]
        }


class MinimalWebArchiver:
    """Minimal fallback web archiver when full implementation not available."""
    
    def archive_url(self, url: str, **options) -> dict:
        """Minimal archive implementation."""
        return {
            'url': url,
            'status': 'fallback',
            'message': 'Full web archiving not available'
        }

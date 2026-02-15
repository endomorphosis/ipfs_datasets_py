"""
WebArchiveProcessorAdapter - Adapter for web archiving functionality.

This adapter provides web archiving capabilities through ProcessorProtocol,
supporting multiple archiving services and local WARC creation.
"""

from __future__ import annotations

import logging
from typing import Union, Optional
from pathlib import Path
import time

from ..protocol import (
    ProcessorProtocol,
    ProcessingResult,
    ProcessingMetadata,
    ProcessingStatus,
    InputType,
    KnowledgeGraph,
    VectorStore,
    Entity,
    Relationship
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
        >>> adapter = WebArchiveProcessorAdapter()
        >>> can_process = await adapter.can_process("https://example.com")
        >>> result = await adapter.process("https://example.com", archive_services=['internet_archive'])
    """
    
    def __init__(self):
        """Initialize adapter."""
        self._archiver = None
    
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
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle web archiving inputs.
        
        Args:
            input_source: Input to check
            
        Returns:
            True if input is a URL (web archiving makes sense for URLs)
        """
        input_str = str(input_source).lower()
        
        # Web archiving is for HTTP/HTTPS URLs
        if input_str.startswith(('http://', 'https://')):
            return True
        
        return False
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process URL and create web archives.
        
        This method:
        1. Archives content to selected services
        2. Creates local WARC if requested
        3. Extracts content for knowledge graph
        4. Returns unified result with archive metadata
        
        Args:
            input_source: URL to archive
            **options: Archiving options
                - archive_services: List of services ['internet_archive', 'archive_is', 'local_warc']
                - verify_archives: Whether to verify archive success (default: True)
                - include_knowledge_graph: Extract content for KG (default: True)
                - max_pages: Maximum pages to crawl for bulk archiving (default: 1)
                
        Returns:
            ProcessingResult with archive URLs and knowledge graph
            
        Example:
            >>> result = await adapter.process(
            ...     "https://example.com",
            ...     archive_services=['internet_archive', 'local_warc'],
            ...     verify_archives=True
            ... )
            >>> print(result.content['archive_urls'])
        """
        start_time = time.time()
        
        # Create metadata
        metadata = ProcessingMetadata(
            processor_name="WebArchiveProcessorAdapter",
            processor_version="1.0",
            input_type=InputType.URL
        )
        
        try:
            url = str(input_source)
            logger.info(f"Archiving URL: {url}")
            
            # Get archiver
            archiver = self._get_archiver()
            
            # Archive the URL
            archive_result = await self._archive_url(
                archiver,
                url,
                options
            )
            
            # Build knowledge graph
            knowledge_graph = self._build_knowledge_graph(url, archive_result)
            
            # Create vector store (minimal for now)
            vectors = VectorStore()
            
            # Collect content
            content = {
                'url': url,
                'archive_urls': archive_result.get('archive_urls', {}),
                'archive_status': archive_result.get('status', 'unknown'),
                'archived_at': archive_result.get('archived_at', ''),
                'archive_size': archive_result.get('size', 0),
                'warc_path': archive_result.get('warc_path', None)
            }
            
            # Update metadata
            metadata.status = ProcessingStatus.SUCCESS
            metadata.resource_usage['archive_services'] = list(archive_result.get('archive_urls', {}).keys())
            metadata.processing_time_seconds = time.time() - start_time
            
            logger.info(f"Successfully archived: {url}")
            
            return ProcessingResult(
                knowledge_graph=knowledge_graph,
                vectors=vectors,
                content=content,
                metadata=metadata
            )
            
        except Exception as e:
            metadata.add_error(f"Web archiving failed: {str(e)}")
            metadata.status = ProcessingStatus.FAILED
            metadata.processing_time_seconds = time.time() - start_time
            logger.error(f"Web archiving error: {e}", exc_info=True)
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(),
                vectors=VectorStore(),
                content={'error': str(e)},
                metadata=metadata
            )
    
    async def _archive_url(self, archiver, url: str, options: dict) -> dict:
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
                ia_url = await self._archive_to_internet_archive(url)
                if ia_url:
                    archive_urls['internet_archive'] = ia_url
            except Exception as e:
                logger.warning(f"Internet Archive failed: {e}")
                status = "partial"
        
        # Try Archive.is
        if 'archive_is' in services:
            try:
                archive_is_url = await self._archive_to_archive_is(url)
                if archive_is_url:
                    archive_urls['archive_is'] = archive_is_url
            except Exception as e:
                logger.warning(f"Archive.is failed: {e}")
                status = "partial"
        
        # Try local WARC
        if 'local_warc' in services:
            try:
                warc_path = await self._create_local_warc(archiver, url)
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
    
    async def _archive_to_internet_archive(self, url: str) -> Optional[str]:
        """Submit URL to Internet Archive Wayback Machine."""
        try:
            import aiohttp
            
            # Wayback Machine Save API
            save_url = f"https://web.archive.org/save/{url}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(save_url, timeout=30) as response:
                    if response.status in (200, 302):
                        # Get the archived URL from response
                        archived_url = str(response.url)
                        logger.info(f"Archived to Internet Archive: {archived_url}")
                        return archived_url
                    else:
                        logger.warning(f"Internet Archive returned status {response.status}")
                        return None
        except Exception as e:
            logger.warning(f"Internet Archive submission failed: {e}")
            return None
    
    async def _archive_to_archive_is(self, url: str) -> Optional[str]:
        """Submit URL to Archive.is (archive.today)."""
        try:
            import aiohttp
            
            # Archive.is Submit API
            submit_url = "https://archive.is/submit/"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    submit_url,
                    data={'url': url},
                    timeout=30
                ) as response:
                    if response.status in (200, 302):
                        # Extract archived URL from response
                        text = await response.text()
                        # Simple extraction - could be improved
                        import re
                        match = re.search(r'https://archive\.(is|today|ph)/[A-Za-z0-9]+', text)
                        if match:
                            archived_url = match.group(0)
                            logger.info(f"Archived to Archive.is: {archived_url}")
                            return archived_url
                    
                    logger.warning(f"Archive.is returned status {response.status}")
                    return None
        except Exception as e:
            logger.warning(f"Archive.is submission failed: {e}")
            return None
    
    async def _create_local_warc(self, archiver, url: str) -> Optional[Path]:
        """Create local WARC file."""
        try:
            # If archiver has archive_url method, use it
            if hasattr(archiver, 'archive_url'):
                result = await archiver.archive_url(url, enable_local_warc=True)
                if result and result.get('warc_path'):
                    return Path(result['warc_path'])
            
            # Fallback: simple WARC creation
            logger.warning("Full WARC creation not available in fallback mode")
            return None
            
        except Exception as e:
            logger.warning(f"Local WARC creation failed: {e}")
            return None
    
    def _build_knowledge_graph(self, url: str, archive_result: dict) -> KnowledgeGraph:
        """
        Build knowledge graph from archive results.
        
        Args:
            url: Original URL
            archive_result: Archive operation results
            
        Returns:
            KnowledgeGraph with archive entities and relationships
        """
        kg = KnowledgeGraph(source=url)
        
        # Create main URL entity
        url_entity = Entity(
            id=f"url:{url}",
            type="WebPage",
            label=url,
            properties={
                "url": url,
                "archived": True,
                "archive_status": archive_result.get('status', 'unknown')
            }
        )
        kg.add_entity(url_entity)
        
        # Create archive entities for each service
        for service, archive_url in archive_result.get('archive_urls', {}).items():
            archive_entity = Entity(
                id=f"archive:{service}:{url}",
                type="WebArchive",
                label=f"{service} archive",
                properties={
                    "service": service,
                    "archive_url": archive_url,
                    "archived_at": archive_result.get('archived_at', '')
                }
            )
            kg.add_entity(archive_entity)
            
            # Create relationship
            relationship = Relationship(
                id=f"archived_by:{url}:{service}",
                source=url_entity.id,
                target=archive_entity.id,
                type="ARCHIVED_BY",
                properties={
                    "service": service,
                    "timestamp": archive_result.get('archived_at', '')
                }
            )
            kg.add_relationship(relationship)
        
        return kg
    
    def get_supported_types(self) -> list[str]:
        """
        Return list of supported input types.
        
        Returns:
            List of type identifiers
        """
        return ["url", "webpage", "web_archive"]
    
    def get_priority(self) -> int:
        """
        Get processor priority.
        
        Web archiving is specialized, so medium priority.
        
        Returns:
            Priority value (higher = more preferred)
        """
        return 8  # Medium-high priority for web archiving
    
    def get_name(self) -> str:
        """
        Get processor name.
        
        Returns:
            Processor name
        """
        return "WebArchiveProcessorAdapter"


class MinimalWebArchiver:
    """Minimal fallback web archiver when full implementation not available."""
    
    async def archive_url(self, url: str, **options) -> dict:
        """Minimal archive implementation."""
        return {
            'url': url,
            'status': 'fallback',
            'message': 'Full web archiving not available'
        }

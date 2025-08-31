"""
Website GraphRAG Processor

Central orchestration class for processing entire websites into GraphRAG systems.
Coordinates web archiving, content discovery, multi-modal processing, knowledge
graph extraction, and GraphRAG system creation.

Usage:
    processor = WebsiteGraphRAGProcessor()
    graphrag_system = await processor.process_website("https://example.com")
    results = graphrag_system.query("What is this website about?")
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass

# Import existing components
from ipfs_datasets_py.web_archive_utils import WebArchiveProcessor
from ipfs_datasets_py.graphrag_integration import GraphRAGFactory
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.content_discovery import ContentDiscoveryEngine, ContentManifest
from ipfs_datasets_py.multimodal_processor import MultiModalContentProcessor, ProcessedContentBatch
from ipfs_datasets_py.website_graphrag_system import WebsiteGraphRAGSystem

# Set up logging
logger = logging.getLogger(__name__)


@dataclass
class WebsiteProcessingConfig:
    """Configuration for website processing pipeline"""
    
    # Archive settings
    archive_services: List[str] = None  # ['ia', 'is', 'cc']
    crawl_depth: int = 2
    include_robots_txt: bool = True
    
    # Content processing
    include_media: bool = True
    max_file_size_mb: int = 100
    supported_media_types: List[str] = None
    
    # GraphRAG settings
    enable_graphrag: bool = True
    vector_store_type: str = "faiss"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size: int = 1000
    chunk_overlap: int = 200
    
    # Performance settings
    max_parallel_processing: int = 4
    processing_timeout_minutes: int = 30
    
    def __post_init__(self):
        if self.archive_services is None:
            self.archive_services = ['ia', 'is']
        if self.supported_media_types is None:
            self.supported_media_types = ['audio/mpeg', 'audio/wav', 'video/mp4', 'video/webm']


class WebsiteGraphRAGProcessor:
    """
    Comprehensive website processing for GraphRAG implementation.
    
    Handles end-to-end processing from URL to searchable GraphRAG system:
    1. Website archiving and content discovery
    2. Multi-format content extraction (HTML, PDF, audio, video)
    3. Vector embedding generation
    4. Knowledge graph construction
    5. GraphRAG system creation
    
    Example:
        processor = WebsiteGraphRAGProcessor()
        graphrag_system = await processor.process_website(
            url="https://example.com",
            crawl_depth=2,
            include_media=True
        )
        
        # Search across all website content
        results = graphrag_system.query(
            "What are the main topics discussed on this website?"
        )
    """
    
    def __init__(self, config: Optional[WebsiteProcessingConfig] = None):
        """
        Initialize processor with configuration.
        
        Args:
            config: Processing configuration. If None, uses defaults.
        """
        self.config = config or WebsiteProcessingConfig()
        self._initialize_components()
    
    def _initialize_components(self):
        """Initialize all processing components"""
        try:
            # Core processors
            self.web_archive_processor = WebArchiveProcessor()
            self.content_discovery = ContentDiscoveryEngine()
            self.multimodal_processor = MultiModalContentProcessor()
            self.knowledge_extractor = KnowledgeGraphExtractor()
            self.graphrag_factory = GraphRAGFactory()
            
            logger.info("WebsiteGraphRAGProcessor components initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            raise
    
    async def process_website(
        self,
        url: str,
        crawl_depth: Optional[int] = None,
        include_media: Optional[bool] = None,
        archive_services: Optional[List[str]] = None,
        enable_graphrag: Optional[bool] = None
    ) -> WebsiteGraphRAGSystem:
        """
        Process entire website into GraphRAG system.
        
        Args:
            url: Website URL to process
            crawl_depth: Maximum crawl depth (overrides config)
            include_media: Whether to process media files (overrides config)
            archive_services: Archive services to use (overrides config)
            enable_graphrag: Whether to enable GraphRAG (overrides config)
            
        Returns:
            WebsiteGraphRAGSystem ready for querying
            
        Raises:
            ValueError: If URL is invalid
            RuntimeError: If processing fails
        """
        # Validate URL
        self._validate_url(url)
        
        # Use provided parameters or fall back to config
        crawl_depth = crawl_depth or self.config.crawl_depth
        include_media = include_media if include_media is not None else self.config.include_media
        archive_services = archive_services or self.config.archive_services
        enable_graphrag = enable_graphrag if enable_graphrag is not None else self.config.enable_graphrag
        
        logger.info(f"Starting website processing for: {url}")
        start_time = datetime.now()
        
        try:
            # Step 1: Archive website
            logger.info("Step 1: Archiving website...")
            archive_results = await self._archive_website(url, crawl_depth, archive_services)
            
            # Step 2: Discover content
            logger.info("Step 2: Discovering content...")
            content_manifest = await self._discover_content(archive_results)
            
            # Step 3: Process content
            logger.info("Step 3: Processing content...")
            processed_content = await self._process_content(content_manifest, include_media)
            
            # Step 4: Extract knowledge graph
            logger.info("Step 4: Extracting knowledge graph...")
            knowledge_graph = await self._extract_knowledge_graph(processed_content)
            
            # Step 5: Build GraphRAG system
            logger.info("Step 5: Building GraphRAG system...")
            graphrag_system = await self._build_graphrag_system(
                processed_content, knowledge_graph, enable_graphrag
            )
            
            # Create final system
            processing_time = (datetime.now() - start_time).total_seconds()
            metadata = self._generate_metadata(url, archive_results, processing_time)
            
            website_system = WebsiteGraphRAGSystem(
                url=url,
                content_manifest=content_manifest,
                processed_content=processed_content,
                knowledge_graph=knowledge_graph,
                graphrag=graphrag_system,
                metadata=metadata
            )
            
            logger.info(f"Website processing completed in {processing_time:.2f} seconds")
            return website_system
            
        except Exception as e:
            logger.error(f"Website processing failed for {url}: {e}")
            raise RuntimeError(f"Processing failed: {e}") from e
    
    async def _archive_website(
        self, 
        url: str, 
        crawl_depth: int, 
        archive_services: List[str]
    ) -> Dict[str, Any]:
        """Archive website using configured services"""
        archive_results = {
            'url': url,
            'timestamp': datetime.now().isoformat(),
            'services': {},
            'warc_files': []
        }
        
        try:
            # Create local WARC file
            warc_path = await self._create_local_warc(url, crawl_depth)
            archive_results['warc_files'].append(warc_path)
            
            # Archive to external services
            for service in archive_services:
                try:
                    service_result = await self._archive_to_service(url, service)
                    archive_results['services'][service] = service_result
                    logger.info(f"Successfully archived to {service}: {service_result}")
                except Exception as e:
                    logger.warning(f"Failed to archive to {service}: {e}")
                    archive_results['services'][service] = {'error': str(e)}
            
            return archive_results
            
        except Exception as e:
            logger.error(f"Website archiving failed: {e}")
            raise
    
    async def _create_local_warc(self, url: str, crawl_depth: int) -> str:
        """Create local WARC file using WebArchiveProcessor"""
        warc_options = {
            'depth': crawl_depth,
            'agent': 'wget',
            'robots': self.config.include_robots_txt
        }
        
        warc_path = self.web_archive_processor.create_warc(
            url=url,
            options=warc_options
        )
        
        if not os.path.exists(warc_path):
            raise RuntimeError(f"WARC file was not created: {warc_path}")
        
        return warc_path
    
    async def _archive_to_service(self, url: str, service: str) -> Dict[str, Any]:
        """Archive URL to external service"""
        if service == 'ia':
            # Internet Archive
            from archivenow import archivenow
            result_url = archivenow.push(url, "ia")
            return {'archived_url': result_url, 'service': 'Internet Archive'}
        
        elif service == 'is':
            # Archive.is
            from archivenow import archivenow  
            result_url = archivenow.push(url, "is")
            return {'archived_url': result_url, 'service': 'Archive.is'}
        
        elif service == 'cc':
            # Perma.cc
            from archivenow import archivenow
            result_url = archivenow.push(url, "cc")
            return {'archived_url': result_url, 'service': 'Perma.cc'}
        
        else:
            raise ValueError(f"Unsupported archive service: {service}")
    
    async def _discover_content(self, archive_results: Dict[str, Any]) -> ContentManifest:
        """Discover all content types in archived website"""
        if not archive_results['warc_files']:
            raise ValueError("No WARC files available for content discovery")
        
        # Use the first WARC file for content discovery
        primary_warc = archive_results['warc_files'][0]
        
        content_manifest = await self.content_discovery.discover_content(primary_warc)
        
        logger.info(
            f"Content discovery completed: "
            f"{len(content_manifest.html_pages)} HTML pages, "
            f"{len(content_manifest.pdf_documents)} PDFs, "
            f"{len(content_manifest.media_files)} media files"
        )
        
        return content_manifest
    
    async def _process_content(
        self, 
        content_manifest: ContentManifest, 
        include_media: bool
    ) -> ProcessedContentBatch:
        """Process all discovered content"""
        processed_content = await self.multimodal_processor.process_content_batch(
            content_manifest=content_manifest,
            include_embeddings=True,
            include_media=include_media
        )
        
        logger.info(
            f"Content processing completed: "
            f"Processed {len(processed_content.processed_items)} items, "
            f"Errors: {len(processed_content.errors)}"
        )
        
        if processed_content.errors:
            logger.warning(f"Processing errors occurred: {processed_content.errors}")
        
        return processed_content
    
    async def _extract_knowledge_graph(self, processed_content: ProcessedContentBatch):
        """Extract knowledge graph from processed content"""
        # Combine all text content for knowledge extraction
        combined_text = "\n\n".join([
            item.text_content for item in processed_content.processed_items
            if item.text_content
        ])
        
        if not combined_text.strip():
            logger.warning("No text content available for knowledge graph extraction")
            return None
        
        # Extract knowledge graph
        knowledge_graph = self.knowledge_extractor.extract_graph_from_text(
            text=combined_text,
            confidence_threshold=0.7
        )
        
        logger.info(
            f"Knowledge graph extraction completed: "
            f"{len(knowledge_graph.entities)} entities, "
            f"{len(knowledge_graph.relationships)} relationships"
        )
        
        return knowledge_graph
    
    async def _build_graphrag_system(
        self, 
        processed_content: ProcessedContentBatch,
        knowledge_graph,
        enable_graphrag: bool
    ):
        """Build GraphRAG system from processed content and knowledge graph"""
        if not enable_graphrag:
            logger.info("GraphRAG disabled, using vector search only")
            return None
        
        try:
            # Create GraphRAG configuration
            graphrag_config = {
                "vector_weight": 0.6,
                "graph_weight": 0.4,
                "max_graph_hops": 2,
                "enable_cross_document_reasoning": True,
                "vector_store_type": self.config.vector_store_type,
                "embedding_model": self.config.embedding_model,
                "chunk_size": self.config.chunk_size,
                "chunk_overlap": self.config.chunk_overlap
            }
            
            # Build GraphRAG system using factory
            graphrag_system = self.graphrag_factory.create_graphrag_system(
                content_items=[item.text_content for item in processed_content.processed_items],
                knowledge_graph=knowledge_graph,
                config=graphrag_config
            )
            
            logger.info("GraphRAG system created successfully")
            return graphrag_system
            
        except Exception as e:
            logger.error(f"Failed to build GraphRAG system: {e}")
            # Fall back to vector search only
            return None
    
    def _generate_metadata(
        self, 
        url: str, 
        archive_results: Dict[str, Any], 
        processing_time: float
    ) -> Dict[str, Any]:
        """Generate metadata for processed website"""
        return {
            'source_url': url,
            'processing_timestamp': datetime.now().isoformat(),
            'processing_time_seconds': processing_time,
            'archive_results': archive_results,
            'config': {
                'crawl_depth': self.config.crawl_depth,
                'include_media': self.config.include_media,
                'archive_services': self.config.archive_services,
                'vector_store_type': self.config.vector_store_type,
                'embedding_model': self.config.embedding_model
            },
            'processor_version': '1.0.0'
        }
    
    def _validate_url(self, url: str) -> None:
        """Validate URL format"""
        import re
        
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        
        if not url_pattern.match(url):
            raise ValueError(f"Invalid URL format: {url}")

    def get_supported_archive_services(self) -> List[str]:
        """Get list of supported archive services"""
        return ['ia', 'is', 'cc']
    
    def get_default_config(self) -> WebsiteProcessingConfig:
        """Get default configuration"""
        return WebsiteProcessingConfig()
    
    async def process_multiple_websites(
        self, 
        urls: List[str],
        **kwargs
    ) -> List[WebsiteGraphRAGSystem]:
        """Process multiple websites concurrently"""
        semaphore = asyncio.Semaphore(self.config.max_parallel_processing)
        
        async def process_single(url: str) -> WebsiteGraphRAGSystem:
            async with semaphore:
                return await self.process_website(url, **kwargs)
        
        tasks = [process_single(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and log errors
        successful_results = []
        for url, result in zip(urls, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to process {url}: {result}")
            else:
                successful_results.append(result)
        
        return successful_results


def _default_config() -> WebsiteProcessingConfig:
    """Get default processing configuration"""
    return WebsiteProcessingConfig()


# Example usage and testing
if __name__ == "__main__":
    async def main():
        """Example usage of WebsiteGraphRAGProcessor"""
        # Initialize processor
        processor = WebsiteGraphRAGProcessor()
        
        # Process a simple website
        try:
            graphrag_system = await processor.process_website(
                url="https://httpbin.org/html",
                crawl_depth=1,
                include_media=False  # Disable media for this simple example
            )
            
            print(f"Successfully processed website: {graphrag_system.url}")
            print(f"Content overview: {graphrag_system.get_content_overview()}")
            
            # Test search
            results = graphrag_system.query("What is the content of this page?")
            print(f"Search results: {len(results.results)} items found")
            
        except Exception as e:
            print(f"Processing failed: {e}")
    
    # Run example
    asyncio.run(main())
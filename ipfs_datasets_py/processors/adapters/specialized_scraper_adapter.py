"""
SpecializedScraperAdapter - Adapter for domain-specific web scrapers.

This adapter provides intelligent routing to specialized scrapers based on
URL domain patterns, supporting legal databases, patent systems, Wikipedia, and more.
"""

from __future__ import annotations

import logging
from typing import Union, Optional
from pathlib import Path
import time
from urllib.parse import urlparse

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


class SpecializedScraperAdapter:
    """
    Adapter for specialized web scrapers that implements ProcessorProtocol.
    
    This adapter intelligently routes URLs to domain-specific scrapers:
    - Legal databases (municipal codes, federal register, court records)
    - Patent databases (USPTO, EPO, Google Patents)
    - Wikipedia (all language editions)
    - Academic papers (arXiv, PubMed)
    - News sources
    
    The adapter detects the domain and selects the appropriate scraper
    for optimal data extraction and knowledge graph generation.
    
    Example:
        >>> adapter = SpecializedScraperAdapter()
        >>> # Automatically routes to Wikipedia scraper
        >>> result = await adapter.process("https://en.wikipedia.org/wiki/Python")
        >>> # Automatically routes to patent scraper
        >>> result = await adapter.process("https://patents.google.com/patent/US...")
    """
    
    # Domain patterns for specialized scrapers
    DOMAIN_PATTERNS = {
        'legal': [
            'municode.com',
            'law.cornell.edu',
            'federalregister.gov',
            'courtlistener.com',
            'supremecourt.gov'
        ],
        'patent': [
            'patents.google.com',
            'uspto.gov',
            'epo.org',
            'wipo.int'
        ],
        'wikipedia': [
            'wikipedia.org',
            'wikimedia.org'
        ],
        'academic': [
            'arxiv.org',
            'pubmed.ncbi.nlm.nih.gov',
            'scholar.google.com',
            'doi.org',
            'researchgate.net'
        ]
    }
    
    def __init__(self):
        """Initialize adapter."""
        self._scrapers = {}
    
    def _get_scraper_type(self, url: str) -> Optional[str]:
        """
        Determine scraper type based on URL domain.
        
        Args:
            url: URL to analyze
            
        Returns:
            Scraper type ('legal', 'patent', 'wikipedia', 'academic') or None
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Check each pattern category
            for scraper_type, patterns in self.DOMAIN_PATTERNS.items():
                for pattern in patterns:
                    if pattern in domain:
                        return scraper_type
            
            return None
            
        except Exception as e:
            logger.warning(f"Error parsing URL {url}: {e}")
            return None
    
    def _get_legal_scraper(self):
        """Lazy-load legal scraper."""
        if 'legal' not in self._scrapers:
            try:
                # Try to import legal scrapers
                from ..legal_scrapers import LegalDatasetAPI
                self._scrapers['legal'] = LegalDatasetAPI()
                logger.info("Legal scraper loaded")
            except ImportError as e:
                logger.warning(f"Legal scraper not available: {e}")
                self._scrapers['legal'] = None
        return self._scrapers['legal']
    
    def _get_patent_scraper(self):
        """Lazy-load patent scraper."""
        if 'patent' not in self._scrapers:
            try:
                from ..patent_scraper import PatentScraper
                self._scrapers['patent'] = PatentScraper()
                logger.info("Patent scraper loaded")
            except ImportError as e:
                logger.warning(f"Patent scraper not available: {e}")
                self._scrapers['patent'] = None
        return self._scrapers['patent']
    
    def _get_wikipedia_scraper(self):
        """Lazy-load Wikipedia scraper."""
        if 'wikipedia' not in self._scrapers:
            try:
                # Wikipedia scraper might be in wikipedia_x
                from ..wikipedia_x import WikipediaProcessor
                self._scrapers['wikipedia'] = WikipediaProcessor()
                logger.info("Wikipedia scraper loaded")
            except ImportError as e:
                logger.warning(f"Wikipedia scraper not available: {e}")
                self._scrapers['wikipedia'] = None
        return self._scrapers['wikipedia']
    
    async def can_process(self, input_source: Union[str, Path]) -> bool:
        """
        Check if this adapter can handle specialized scraping inputs.
        
        Args:
            input_source: Input to check
            
        Returns:
            True if URL matches a known specialized scraper domain
        """
        input_str = str(input_source).lower()
        
        # Only process URLs
        if not input_str.startswith(('http://', 'https://')):
            return False
        
        # Check if we have a specialized scraper for this domain
        scraper_type = self._get_scraper_type(input_str)
        return scraper_type is not None
    
    async def process(
        self,
        input_source: Union[str, Path],
        **options
    ) -> ProcessingResult:
        """
        Process URL using appropriate specialized scraper.
        
        This method:
        1. Detects the domain type
        2. Routes to appropriate specialized scraper
        3. Extracts domain-specific structured data
        4. Builds specialized knowledge graph
        5. Returns unified result
        
        Args:
            input_source: URL to scrape
            **options: Scraper-specific options
                
        Returns:
            ProcessingResult with specialized knowledge graph
            
        Example:
            >>> result = await adapter.process("https://en.wikipedia.org/wiki/Python")
            >>> # Returns knowledge graph with Wikipedia-specific entities
        """
        start_time = time.time()
        
        # Create metadata
        metadata = ProcessingMetadata(
            processor_name="SpecializedScraperAdapter",
            processor_version="1.0",
            input_type=InputType.URL
        )
        
        try:
            url = str(input_source)
            scraper_type = self._get_scraper_type(url)
            
            if not scraper_type:
                metadata.add_error(f"No specialized scraper for URL: {url}")
                metadata.status = ProcessingStatus.FAILED
                return ProcessingResult(
                    knowledge_graph=KnowledgeGraph(),
                    vectors=VectorStore(),
                    content={'error': 'No specialized scraper available'},
                    metadata=metadata
                )
            
            logger.info(f"Processing {url} with {scraper_type} scraper")
            
            # Route to appropriate scraper
            if scraper_type == 'legal':
                result = await self._process_legal(url, options)
            elif scraper_type == 'patent':
                result = await self._process_patent(url, options)
            elif scraper_type == 'wikipedia':
                result = await self._process_wikipedia(url, options)
            elif scraper_type == 'academic':
                result = await self._process_academic(url, options)
            else:
                raise ValueError(f"Unknown scraper type: {scraper_type}")
            
            # Update metadata
            result.metadata.processor_name = "SpecializedScraperAdapter"
            result.metadata.resource_usage['scraper_type'] = scraper_type
            result.metadata.processing_time_seconds = time.time() - start_time
            
            logger.info(f"Successfully scraped {url} using {scraper_type} scraper")
            return result
            
        except Exception as e:
            metadata.add_error(f"Specialized scraping failed: {str(e)}")
            metadata.status = ProcessingStatus.FAILED
            metadata.processing_time_seconds = time.time() - start_time
            logger.error(f"Scraping error: {e}", exc_info=True)
            
            return ProcessingResult(
                knowledge_graph=KnowledgeGraph(),
                vectors=VectorStore(),
                content={'error': str(e)},
                metadata=metadata
            )
    
    async def _process_legal(self, url: str, options: dict) -> ProcessingResult:
        """Process legal database URL."""
        scraper = self._get_legal_scraper()
        
        if not scraper:
            # Fallback: basic processing
            return self._create_basic_result(url, "legal")
        
        # Use legal scraper
        try:
            if hasattr(scraper, 'scrape_url'):
                result = await scraper.scrape_url(url, **options)
                return self._convert_to_processing_result(result, url, "legal")
            else:
                return self._create_basic_result(url, "legal")
        except Exception as e:
            logger.warning(f"Legal scraper error: {e}")
            return self._create_basic_result(url, "legal")
    
    async def _process_patent(self, url: str, options: dict) -> ProcessingResult:
        """Process patent database URL."""
        scraper = self._get_patent_scraper()
        
        if not scraper:
            return self._create_basic_result(url, "patent")
        
        # Use patent scraper
        try:
            if hasattr(scraper, 'scrape_patent'):
                result = await scraper.scrape_patent(url, **options)
                return self._convert_to_processing_result(result, url, "patent")
            else:
                return self._create_basic_result(url, "patent")
        except Exception as e:
            logger.warning(f"Patent scraper error: {e}")
            return self._create_basic_result(url, "patent")
    
    async def _process_wikipedia(self, url: str, options: dict) -> ProcessingResult:
        """Process Wikipedia URL."""
        scraper = self._get_wikipedia_scraper()
        
        if not scraper:
            return self._create_basic_result(url, "wikipedia")
        
        # Use Wikipedia scraper
        try:
            if hasattr(scraper, 'process_article'):
                result = await scraper.process_article(url, **options)
                return self._convert_to_processing_result(result, url, "wikipedia")
            else:
                return self._create_basic_result(url, "wikipedia")
        except Exception as e:
            logger.warning(f"Wikipedia scraper error: {e}")
            return self._create_basic_result(url, "wikipedia")
    
    async def _process_academic(self, url: str, options: dict) -> ProcessingResult:
        """Process academic paper URL."""
        # Basic processing for now - could be enhanced with specific scrapers
        return self._create_basic_result(url, "academic")
    
    def _create_basic_result(self, url: str, scraper_type: str) -> ProcessingResult:
        """
        Create basic processing result when specialized scraper not available.
        
        Args:
            url: URL being processed
            scraper_type: Type of scraper (for metadata)
            
        Returns:
            Basic ProcessingResult
        """
        kg = KnowledgeGraph(source=url)
        
        # Create basic entity
        entity = Entity(
            id=f"url:{url}",
            type=scraper_type.title() + "Resource",
            label=url,
            properties={
                "url": url,
                "scraper_type": scraper_type,
                "processed": True
            }
        )
        kg.add_entity(entity)
        
        metadata = ProcessingMetadata(
            processor_name="SpecializedScraperAdapter",
            processor_version="1.0",
            input_type=InputType.URL,
            status=ProcessingStatus.PARTIAL
        )
        metadata.add_warning(f"Using basic processing for {scraper_type} content")
        metadata.resource_usage['scraper_type'] = scraper_type
        
        return ProcessingResult(
            knowledge_graph=kg,
            vectors=VectorStore(),
            content={
                'url': url,
                'scraper_type': scraper_type,
                'mode': 'basic'
            },
            metadata=metadata
        )
    
    def _convert_to_processing_result(
        self,
        scraper_result: Any,
        url: str,
        scraper_type: str
    ) -> ProcessingResult:
        """
        Convert scraper-specific result to ProcessingResult.
        
        Args:
            scraper_result: Result from specialized scraper
            url: Original URL
            scraper_type: Type of scraper used
            
        Returns:
            Unified ProcessingResult
        """
        # If scraper already returns ProcessingResult, use it
        if isinstance(scraper_result, ProcessingResult):
            return scraper_result
        
        # Otherwise, create from scraper result
        # (This would need to be customized based on actual scraper APIs)
        kg = KnowledgeGraph(source=url)
        vectors = VectorStore()
        
        metadata = ProcessingMetadata(
            processor_name="SpecializedScraperAdapter",
            processor_version="1.0",
            input_type=InputType.URL,
            status=ProcessingStatus.SUCCESS
        )
        metadata.resource_usage['scraper_type'] = scraper_type
        
        content = {
            'url': url,
            'scraper_type': scraper_type,
            'data': scraper_result
        }
        
        return ProcessingResult(
            knowledge_graph=kg,
            vectors=vectors,
            content=content,
            metadata=metadata
        )
    
    def get_supported_types(self) -> list[str]:
        """
        Return list of supported input types.
        
        Returns:
            List of type identifiers
        """
        return ["url", "legal", "patent", "wikipedia", "academic"]
    
    def get_priority(self) -> int:
        """
        Get processor priority.
        
        Specialized scrapers should have medium-high priority
        to be preferred over generic web scraping.
        
        Returns:
            Priority value (higher = more preferred)
        """
        return 12  # Higher than generic GraphRAG (10) but lower than Batch (15)
    
    def get_name(self) -> str:
        """
        Get processor name.
        
        Returns:
            Processor name
        """
        return "SpecializedScraperAdapter"

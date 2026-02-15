"""
SpecializedScraperAdapter - Adapter for domain-specific web scrapers.

This adapter provides intelligent routing to specialized scrapers based on
URL domain patterns, supporting legal databases, patent systems, Wikipedia, and more.

Implements the synchronous ProcessorProtocol from processors.core.
"""

from __future__ import annotations

import logging
from typing import Union, Optional, Dict, Any, List
from pathlib import Path
import time
from urllib.parse import urlparse

from ..core.protocol import (
    ProcessorProtocol,
    ProcessingContext,
    ProcessingResult,
    InputType,
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
        >>> from ipfs_datasets_py.processors.core import ProcessingContext, InputType
        >>> adapter = SpecializedScraperAdapter()
        >>> # Automatically routes to Wikipedia scraper
        >>> context = ProcessingContext(
        ...     input_type=InputType.URL,
        ...     source="https://en.wikipedia.org/wiki/Python",
        ...     metadata={}
        ... )
        >>> result = adapter.process(context)
        >>> # Automatically routes to patent scraper
        >>> context2 = ProcessingContext(
        ...     input_type=InputType.URL,
        ...     source="https://patents.google.com/patent/US...",
        ...     metadata={}
        ... )
        >>> result2 = adapter.process(context2)
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
        self._name = "SpecializedScraperProcessor"
        self._priority = 12  # Higher than generic GraphRAG (10) but lower than Batch (15)
    
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
    
    def can_handle(self, context: ProcessingContext) -> bool:
        """
        Check if this adapter can handle specialized scraping inputs.
        
        Args:
            context: Processing context with input information
            
        Returns:
            True if URL matches a known specialized scraper domain
        """
        input_str = str(context.source).lower()
        
        # Only process URLs
        if not input_str.startswith(('http://', 'https://')):
            return False
        
        # Check if we have a specialized scraper for this domain
        scraper_type = self._get_scraper_type(input_str)
        return scraper_type is not None
    
    def process(self, context: ProcessingContext) -> ProcessingResult:
        """
        Process URL using appropriate specialized scraper.
        
        This method:
        1. Detects the domain type
        2. Routes to appropriate specialized scraper
        3. Extracts domain-specific structured data
        4. Builds specialized knowledge graph
        5. Returns unified result
        
        Args:
            context: Processing context with input source and options
                
        Returns:
            ProcessingResult with specialized knowledge graph
            
        Example:
            >>> result = adapter.process(context)
            >>> # Returns knowledge graph with domain-specific entities
        """
        start_time = time.time()
        source = context.source
        options = context.options
        
        try:
            url = str(source)
            scraper_type = self._get_scraper_type(url)
            
            if not scraper_type:
                return ProcessingResult(
                    success=False,
                    knowledge_graph={},
                    vectors=[],
                    metadata={
                        "processor": self._name,
                        "processing_time": time.time() - start_time,
                        "error": f"No specialized scraper for URL: {url}"
                    },
                    errors=[f"No specialized scraper for URL: {url}"]
                )
            
            logger.info(f"Processing {url} with {scraper_type} scraper")
            
            # Route to appropriate scraper
            if scraper_type == 'legal':
                result = self._process_legal(url, options)
            elif scraper_type == 'patent':
                result = self._process_patent(url, options)
            elif scraper_type == 'wikipedia':
                result = self._process_wikipedia(url, options)
            elif scraper_type == 'academic':
                result = self._process_academic(url, options)
            else:
                raise ValueError(f"Unknown scraper type: {scraper_type}")
            
            # Update metadata
            if result.metadata is None:
                result.metadata = {}
            result.metadata["processor"] = self._name
            result.metadata["scraper_type"] = scraper_type
            result.metadata["processing_time"] = time.time() - start_time
            
            logger.info(f"Successfully scraped {url} using {scraper_type} scraper")
            return result
            
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"Scraping error: {e}", exc_info=True)
            
            return ProcessingResult(
                success=False,
                knowledge_graph={},
                vectors=[],
                metadata={
                    "processor": self._name,
                    "processing_time": elapsed,
                    "error": str(e)
                },
                errors=[f"Specialized scraping failed: {str(e)}"]
            )
    
    def _process_legal(self, url: str, options: dict) -> ProcessingResult:
        """Process legal database URL."""
        scraper = self._get_legal_scraper()
        
        if not scraper:
            # Fallback: basic processing
            return self._create_basic_result(url, "legal")
        
        # Use legal scraper
        try:
            if hasattr(scraper, 'scrape_url'):
                result = scraper.scrape_url(url, **options)
                return self._convert_to_processing_result(result, url, "legal")
            else:
                return self._create_basic_result(url, "legal")
        except Exception as e:
            logger.warning(f"Legal scraper error: {e}")
            return self._create_basic_result(url, "legal")
    
    def _process_patent(self, url: str, options: dict) -> ProcessingResult:
        """Process patent database URL."""
        scraper = self._get_patent_scraper()
        
        if not scraper:
            return self._create_basic_result(url, "patent")
        
        # Use patent scraper
        try:
            if hasattr(scraper, 'scrape_patent'):
                result = scraper.scrape_patent(url, **options)
                return self._convert_to_processing_result(result, url, "patent")
            else:
                return self._create_basic_result(url, "patent")
        except Exception as e:
            logger.warning(f"Patent scraper error: {e}")
            return self._create_basic_result(url, "patent")
    
    def _process_wikipedia(self, url: str, options: dict) -> ProcessingResult:
        """Process Wikipedia URL."""
        scraper = self._get_wikipedia_scraper()
        
        if not scraper:
            return self._create_basic_result(url, "wikipedia")
        
        # Use Wikipedia scraper
        try:
            if hasattr(scraper, 'process_article'):
                result = scraper.process_article(url, **options)
                return self._convert_to_processing_result(result, url, "wikipedia")
            else:
                return self._create_basic_result(url, "wikipedia")
        except Exception as e:
            logger.warning(f"Wikipedia scraper error: {e}")
            return self._create_basic_result(url, "wikipedia")
    
    def _process_academic(self, url: str, options: dict) -> ProcessingResult:
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
        # Create basic entity
        entity = {
            "id": f"url:{url}",
            "type": scraper_type.title() + "Resource",
            "label": url,
            "properties": {
                "url": url,
                "scraper_type": scraper_type,
                "processed": True
            }
        }
        
        warnings = [f"Using basic processing for {scraper_type} content"]
        
        return ProcessingResult(
            success=True,
            knowledge_graph={
                "entities": [entity],
                "relationships": [],
                "source": url
            },
            vectors=[],
            metadata={
                "processor": self._name,
                "url": url,
                "scraper_type": scraper_type,
                "mode": "basic"
            },
            warnings=warnings
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
        return ProcessingResult(
            success=True,
            knowledge_graph={
                "entities": [],
                "relationships": [],
                "source": url
            },
            vectors=[],
            metadata={
                "processor": self._name,
                "url": url,
                "scraper_type": scraper_type,
                "data": scraper_result
            }
        )
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Return processor capabilities and metadata.
        
        Returns:
            Dictionary with processor name, priority, supported formats, etc.
        """
        return {
            "name": self._name,
            "priority": self._priority,
            "formats": ["url", "legal", "patent", "wikipedia", "academic"],
            "input_types": ["url"],
            "outputs": ["knowledge_graph", "structured_data"],
            "features": [
                "legal_scraping",
                "patent_scraping",
                "wikipedia_scraping",
                "academic_scraping",
                "domain_routing"
            ]
        }

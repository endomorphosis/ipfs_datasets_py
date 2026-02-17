"""
Multi-Engine Legal Search - Enhanced Natural Language Search.

This module extends BraveLegalSearch to support multiple search engines
(Brave, DuckDuckGo, Google CSE) with intelligent fallback and result aggregation.

Features:
- Multi-engine support with parallel execution
- Automatic fallback on engine failure
- Result deduplication and ranking
- Smart engine selection based on query type
- Performance metrics and monitoring

Example:
    >>> from ipfs_datasets_py.processors.legal_scrapers import MultiEngineLegalSearch
    >>> 
    >>> # Initialize with multiple engines
    >>> searcher = MultiEngineLegalSearch(
    ...     engines=["brave", "duckduckgo"],
    ...     parallel_enabled=True
    ... )
    >>> 
    >>> # Search across all engines
    >>> results = searcher.search("EPA regulations on water pollution in California")
    >>> 
    >>> # See which engines were used
    >>> print(f"Engines used: {results['metadata']['engines_used']}")
"""

import logging
import os
from typing import Dict, List, Optional, Any
from pathlib import Path

from .brave_legal_search import BraveLegalSearch
from ipfs_datasets_py.processors.web_archiving.search_engines import (
    MultiEngineOrchestrator,
    OrchestratorConfig,
    SearchEngineConfig,
    SearchEngineType,
    SearchEngineError,
)

logger = logging.getLogger(__name__)


class MultiEngineLegalSearch(BraveLegalSearch):
    """Multi-engine legal search with intelligent fallback.
    
    Extends BraveLegalSearch to support multiple search engines with:
    - Parallel search execution across engines
    - Automatic fallback on engine failure
    - Result aggregation and deduplication
    - Engine-specific optimization
    
    This class maintains backward compatibility with BraveLegalSearch while
    adding multi-engine capabilities.
    
    Example:
        >>> # Use multiple engines with fallback
        >>> searcher = MultiEngineLegalSearch(
        ...     engines=["brave", "duckduckgo", "google_cse"],
        ...     brave_api_key="your_brave_key",
        ...     google_cse_id="your_cse_id",
        ...     fallback_enabled=True
        ... )
        >>> 
        >>> # Search will try all engines in parallel
        >>> results = searcher.search("OSHA workplace safety")
        >>> 
        >>> # Check performance metrics
        >>> stats = searcher.get_engine_stats()
        >>> print(f"Total requests: {stats['total_requests']}")
    """
    
    def __init__(
        self,
        # BraveLegalSearch parameters
        api_key: Optional[str] = None,
        knowledge_base_dir: Optional[str] = None,
        cache_enabled: bool = True,
        cache_ttl: int = 3600,
        # Multi-engine parameters
        engines: Optional[List[str]] = None,
        parallel_enabled: bool = True,
        fallback_enabled: bool = True,
        result_aggregation: str = "merge",
        deduplication_enabled: bool = True,
        # Engine-specific API keys
        brave_api_key: Optional[str] = None,
        google_api_key: Optional[str] = None,
        google_cse_id: Optional[str] = None,
    ):
        """Initialize multi-engine legal search.
        
        Args:
            api_key: Brave API key (deprecated, use brave_api_key)
            knowledge_base_dir: Directory with JSONL files
            cache_enabled: Enable query result caching
            cache_ttl: Cache TTL in seconds
            engines: List of engines to use (default: ["brave", "duckduckgo"])
            parallel_enabled: Execute searches in parallel
            fallback_enabled: Fall back to other engines on failure
            result_aggregation: "merge", "best", or "round_robin"
            deduplication_enabled: Remove duplicate results by URL
            brave_api_key: Brave Search API key
            google_api_key: Google API key
            google_cse_id: Google Custom Search Engine ID
        """
        # Initialize parent BraveLegalSearch
        super().__init__(
            api_key=api_key or brave_api_key,
            knowledge_base_dir=knowledge_base_dir,
            cache_enabled=cache_enabled,
            cache_ttl=cache_ttl
        )
        
        # Default engines if not specified
        if engines is None:
            engines = ["brave", "duckduckgo"]
        
        # Configure engine-specific settings
        engine_configs = {}
        
        # Brave configuration
        if "brave" in engines:
            brave_key = brave_api_key or api_key or os.environ.get("BRAVE_API_KEY")
            engine_configs["brave"] = SearchEngineConfig(
                engine_type="brave",
                api_key=brave_key,
                rate_limit_per_minute=60,
                cache_enabled=cache_enabled,
                cache_ttl_seconds=cache_ttl,
            )
        
        # DuckDuckGo configuration (no API key required)
        if "duckduckgo" in engines:
            engine_configs["duckduckgo"] = SearchEngineConfig(
                engine_type="duckduckgo",
                rate_limit_per_minute=30,  # Conservative limit
                cache_enabled=cache_enabled,
                cache_ttl_seconds=cache_ttl,
            )
        
        # Google CSE configuration
        if "google_cse" in engines:
            google_key = google_api_key or os.environ.get("GOOGLE_API_KEY")
            cse_id = google_cse_id or os.environ.get("GOOGLE_CSE_ID")
            
            if not google_key or not cse_id:
                logger.warning(
                    "Google CSE requires both GOOGLE_API_KEY and GOOGLE_CSE_ID. "
                    "Removing google_cse from engines."
                )
                engines = [e for e in engines if e != "google_cse"]
            else:
                engine_configs["google_cse"] = SearchEngineConfig(
                    engine_type="google_cse",
                    api_key=google_key,
                    rate_limit_per_minute=60,
                    cache_enabled=cache_enabled,
                    cache_ttl_seconds=cache_ttl,
                    extra_params={"cse_id": cse_id}
                )
        
        # Create orchestrator config
        orchestrator_config = OrchestratorConfig(
            engines=engines,
            engine_configs=engine_configs,
            parallel_enabled=parallel_enabled,
            fallback_enabled=fallback_enabled,
            result_aggregation=result_aggregation,
            deduplication_enabled=deduplication_enabled,
            max_workers=min(len(engines), 3),
            timeout_seconds=30
        )
        
        # Initialize multi-engine orchestrator
        try:
            self.orchestrator = MultiEngineOrchestrator(orchestrator_config)
            logger.info(
                f"Multi-engine orchestrator initialized with {len(engines)} engines: {engines}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize orchestrator: {e}")
            raise SearchEngineError(f"Orchestrator initialization failed: {e}") from e
    
    def search(
        self,
        query: str,
        max_results: int = 20,
        country: str = "US",
        lang: str = "en",
        execute_search: bool = True,
        engines: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Search for legal rules using multiple engines.
        
        Args:
            query: Natural language query
            max_results: Maximum results to return
            country: Country code for localization
            lang: Language code
            execute_search: Whether to execute the search
            engines: Specific engines to use (None = use all configured)
            
        Returns:
            Dict containing:
                - query: Original query
                - intent: Parsed query intent
                - search_terms: Generated search terms
                - results: Aggregated search results from all engines
                - metadata: Additional metadata including engines_used
                - cache_hit: Whether from cache
        """
        logger.info(f"Multi-engine search for: {query}")
        
        # Check cache first
        cache_key = self._get_cache_key(query, max_results, country, lang)
        if self.cache_enabled and cache_key in self._query_cache:
            cached = self._query_cache[cache_key]
            if cached['timestamp'] + self.cache_ttl > self._get_timestamp():
                logger.info("Returning cached results")
                cached['cache_hit'] = True
                return cached['data']
        
        # Process query with NLP
        intent = self.query_processor.process_query(query)
        
        # Generate search terms
        search_terms = self.term_generator.generate_search_terms(intent)
        
        if not execute_search:
            return {
                'query': query,
                'intent': intent.__dict__,
                'search_terms': search_terms,
                'results': [],
                'metadata': {
                    'execute_search': False
                },
                'cache_hit': False
            }
        
        # Execute multi-engine search for each term
        all_results = []
        engines_used = set()
        
        for term in search_terms[:3]:  # Limit to top 3 terms
            try:
                logger.debug(f"Searching with term: {term}")
                
                # Execute search via orchestrator
                response = self.orchestrator.search(
                    query=term,
                    max_results=max_results,
                    offset=0,
                    engines=engines
                )
                
                # Track which engines were used
                engines_used.update(response.metadata.get('engines_used', []))
                
                # Convert to legacy format for compatibility
                for result in response.results:
                    all_results.append({
                        'title': result.title,
                        'url': result.url,
                        'description': result.snippet,
                        'snippet': result.snippet,
                        'domain': result.domain,
                        'engine': result.engine,
                        'score': result.score,
                        'published_date': result.published_date,
                        'metadata': result.metadata
                    })
                
            except Exception as e:
                logger.warning(f"Search failed for term '{term}': {e}")
        
        # Deduplicate results by URL
        seen_urls = set()
        unique_results = []
        for result in all_results:
            url = result['url'].lower().strip()
            if url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(result)
        
        # Prepare response
        response_data = {
            'query': query,
            'intent': intent.__dict__,
            'search_terms': search_terms,
            'results': unique_results[:max_results],
            'metadata': {
                'total_results': len(unique_results),
                'engines_used': list(engines_used),
                'engine_count': len(engines_used),
                'search_terms_used': len(search_terms[:3]),
                'country': country,
                'lang': lang
            },
            'cache_hit': False
        }
        
        # Cache the results
        if self.cache_enabled:
            self._query_cache[cache_key] = {
                'data': response_data,
                'timestamp': self._get_timestamp()
            }
        
        logger.info(
            f"Multi-engine search complete: {len(unique_results)} results "
            f"from {len(engines_used)} engines"
        )
        
        return response_data
    
    def get_engine_stats(self) -> Dict[str, Any]:
        """Get statistics for all search engines.
        
        Returns:
            Dictionary with per-engine stats
        """
        return self.orchestrator.get_stats()
    
    def test_engines(self) -> Dict[str, bool]:
        """Test connectivity to all configured engines.
        
        Returns:
            Dictionary mapping engine names to connection status
        """
        return self.orchestrator.test_all_connections()
    
    def _get_cache_key(
        self,
        query: str,
        max_results: int,
        country: str,
        lang: str
    ) -> str:
        """Generate cache key for a query."""
        import hashlib
        cache_str = f"{query}:{max_results}:{country}:{lang}"
        return hashlib.md5(cache_str.encode()).hexdigest()
    
    def _get_timestamp(self) -> float:
        """Get current timestamp."""
        import time
        return time.time()

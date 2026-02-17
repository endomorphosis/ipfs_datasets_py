"""
Multi-Engine Search Orchestrator.

This module coordinates searches across multiple search engines,
providing parallel execution, fallback handling, and result aggregation.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from .base import (
    SearchEngineAdapter,
    SearchEngineConfig,
    SearchEngineResponse,
    SearchEngineResult,
    SearchEngineError,
    SearchEngineType,
)
from .brave_adapter import BraveSearchEngine
from .duckduckgo_adapter import DuckDuckGoSearchEngine
from .google_cse_adapter import GoogleCSESearchEngine

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for multi-engine orchestrator."""
    engines: List[str] = field(default_factory=lambda: ["brave"])
    engine_configs: Dict[str, SearchEngineConfig] = field(default_factory=dict)
    parallel_enabled: bool = True
    fallback_enabled: bool = True
    result_aggregation: str = "merge"  # "merge", "best", "round_robin"
    deduplication_enabled: bool = True
    max_workers: int = 3
    timeout_seconds: int = 30


class MultiEngineOrchestrator:
    """Orchestrate searches across multiple search engines.
    
    This class manages multiple search engine adapters and coordinates
    their execution with support for:
    - Parallel execution across engines
    - Fallback to alternate engines on failure
    - Result aggregation and deduplication
    - Performance metrics and monitoring
    
    Example:
        >>> from ipfs_datasets_py.web_archiving.search_engines import (
        ...     MultiEngineOrchestrator,
        ...     OrchestratorConfig
        ... )
        >>> config = OrchestratorConfig(
        ...     engines=["brave", "duckduckgo", "google_cse"],
        ...     parallel_enabled=True,
        ...     fallback_enabled=True
        ... )
        >>> orchestrator = MultiEngineOrchestrator(config)
        >>> response = orchestrator.search("EPA regulations California")
        >>> print(f"Found {len(response.results)} results from {len(response.metadata['engines_used'])} engines")
    """
    
    # Engine class mapping
    ENGINE_CLASSES = {
        SearchEngineType.BRAVE: BraveSearchEngine,
        SearchEngineType.DUCKDUCKGO: DuckDuckGoSearchEngine,
        SearchEngineType.GOOGLE_CSE: GoogleCSESearchEngine,
    }
    
    def __init__(self, config: OrchestratorConfig):
        """Initialize multi-engine orchestrator.
        
        Args:
            config: Orchestrator configuration
        """
        self.config = config
        self.engines: Dict[str, SearchEngineAdapter] = {}
        
        # Initialize engines
        self._initialize_engines()
        
        logger.info(
            f"Multi-engine orchestrator initialized with "
            f"{len(self.engines)} engines: {list(self.engines.keys())}"
        )
    
    def _initialize_engines(self) -> None:
        """Initialize configured search engines."""
        for engine_name in self.config.engines:
            try:
                # Get engine config or use default
                engine_config = self.config.engine_configs.get(
                    engine_name,
                    SearchEngineConfig(engine_type=engine_name)
                )
                
                # Get engine class
                engine_class = self.ENGINE_CLASSES.get(engine_name)
                if not engine_class:
                    logger.warning(f"Unknown engine type: {engine_name}")
                    continue
                
                # Create engine instance
                engine = engine_class(engine_config)
                self.engines[engine_name] = engine
                
                logger.info(f"Initialized {engine_name} search engine")
                
            except Exception as e:
                logger.error(f"Failed to initialize {engine_name}: {e}")
    
    def search(
        self,
        query: str,
        max_results: int = 20,
        offset: int = 0,
        engines: Optional[List[str]] = None,
        **kwargs
    ) -> SearchEngineResponse:
        """Execute a search across multiple engines.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            offset: Result offset for pagination
            engines: Specific engines to use (None = use all)
            **kwargs: Additional search parameters
            
        Returns:
            Aggregated SearchEngineResponse from multiple engines
            
        Raises:
            SearchEngineError: If all engines fail
        """
        start_time = time.time()
        
        # Determine which engines to use
        target_engines = engines or list(self.engines.keys())
        target_engines = [e for e in target_engines if e in self.engines]
        
        if not target_engines:
            raise SearchEngineError("No valid engines available")
        
        logger.info(
            f"Executing multi-engine search with {len(target_engines)} engines: "
            f"{target_engines}"
        )
        
        # Execute searches
        if self.config.parallel_enabled and len(target_engines) > 1:
            responses = self._parallel_search(
                query, max_results, offset, target_engines, **kwargs
            )
        else:
            responses = self._sequential_search(
                query, max_results, offset, target_engines, **kwargs
            )
        
        # Check if any engines succeeded
        if not responses:
            raise SearchEngineError("All search engines failed")
        
        # Aggregate results
        aggregated = self._aggregate_responses(
            responses,
            query,
            max_results
        )
        
        # Update timing
        aggregated.took_ms = (time.time() - start_time) * 1000
        
        logger.info(
            f"Multi-engine search completed: {len(aggregated.results)} results "
            f"from {len(responses)} engines in {aggregated.took_ms:.0f}ms"
        )
        
        return aggregated
    
    def _parallel_search(
        self,
        query: str,
        max_results: int,
        offset: int,
        engines: List[str],
        **kwargs
    ) -> List[SearchEngineResponse]:
        """Execute searches in parallel across engines.
        
        Args:
            query: Search query
            max_results: Maximum results
            offset: Result offset
            engines: List of engine names
            **kwargs: Additional parameters
            
        Returns:
            List of successful responses
        """
        responses = []
        
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            # Submit search tasks
            future_to_engine = {}
            for engine_name in engines:
                engine = self.engines[engine_name]
                future = executor.submit(
                    self._safe_search,
                    engine,
                    query,
                    max_results,
                    offset,
                    **kwargs
                )
                future_to_engine[future] = engine_name
            
            # Collect results
            for future in as_completed(
                future_to_engine.keys(),
                timeout=self.config.timeout_seconds
            ):
                engine_name = future_to_engine[future]
                try:
                    response = future.result()
                    if response:
                        responses.append(response)
                        logger.debug(
                            f"{engine_name} search succeeded: "
                            f"{len(response.results)} results"
                        )
                except Exception as e:
                    logger.warning(f"{engine_name} search failed: {e}")
        
        return responses
    
    def _sequential_search(
        self,
        query: str,
        max_results: int,
        offset: int,
        engines: List[str],
        **kwargs
    ) -> List[SearchEngineResponse]:
        """Execute searches sequentially across engines.
        
        Args:
            query: Search query
            max_results: Maximum results
            offset: Result offset
            engines: List of engine names
            **kwargs: Additional parameters
            
        Returns:
            List of successful responses
        """
        responses = []
        
        for engine_name in engines:
            engine = self.engines[engine_name]
            
            try:
                response = engine.search(
                    query,
                    max_results=max_results,
                    offset=offset,
                    **kwargs
                )
                responses.append(response)
                logger.debug(
                    f"{engine_name} search succeeded: "
                    f"{len(response.results)} results"
                )
                
                # If fallback disabled, stop after first success
                if not self.config.fallback_enabled:
                    break
                    
            except Exception as e:
                logger.warning(f"{engine_name} search failed: {e}")
                
                # If fallback disabled, re-raise error
                if not self.config.fallback_enabled:
                    raise
        
        return responses
    
    def _safe_search(
        self,
        engine: SearchEngineAdapter,
        query: str,
        max_results: int,
        offset: int,
        **kwargs
    ) -> Optional[SearchEngineResponse]:
        """Safely execute a search with error handling.
        
        Args:
            engine: Search engine adapter
            query: Search query
            max_results: Maximum results
            offset: Result offset
            **kwargs: Additional parameters
            
        Returns:
            Response or None on failure
        """
        try:
            return engine.search(
                query,
                max_results=max_results,
                offset=offset,
                **kwargs
            )
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            return None
    
    def _aggregate_responses(
        self,
        responses: List[SearchEngineResponse],
        query: str,
        max_results: int
    ) -> SearchEngineResponse:
        """Aggregate multiple search responses.
        
        Args:
            responses: List of engine responses
            query: Original query
            max_results: Maximum results to return
            
        Returns:
            Aggregated response
        """
        if self.config.result_aggregation == "best":
            # Return response with most results
            return max(responses, key=lambda r: len(r.results))
        
        elif self.config.result_aggregation == "round_robin":
            # Interleave results from engines
            all_results = []
            max_len = max(len(r.results) for r in responses)
            
            for i in range(max_len):
                for response in responses:
                    if i < len(response.results):
                        all_results.append(response.results[i])
        
        else:  # "merge" (default)
            # Merge all results
            all_results = []
            for response in responses:
                all_results.extend(response.results)
        
        # Deduplicate if enabled
        if self.config.deduplication_enabled:
            all_results = self._deduplicate_results(all_results)
        
        # Limit to max_results
        all_results = all_results[:max_results]
        
        # Create aggregated response
        engines_used = [r.engine for r in responses]
        
        return SearchEngineResponse(
            results=all_results,
            engine="multi_engine",
            query=query,
            total_results=len(all_results),
            page=1,
            took_ms=0.0,  # Will be updated by caller
            from_cache=False,
            metadata={
                "engines_used": engines_used,
                "engine_count": len(responses),
                "aggregation_method": self.config.result_aggregation,
                "deduplication": self.config.deduplication_enabled,
            }
        )
    
    def _deduplicate_results(
        self,
        results: List[SearchEngineResult]
    ) -> List[SearchEngineResult]:
        """Remove duplicate results based on URL.
        
        Args:
            results: List of results
            
        Returns:
            Deduplicated list
        """
        seen_urls = set()
        deduplicated = []
        
        for result in results:
            url = result.url.lower().strip()
            if url not in seen_urls:
                seen_urls.add(url)
                deduplicated.append(result)
        
        logger.debug(
            f"Deduplication: {len(results)} -> {len(deduplicated)} results"
        )
        
        return deduplicated
    
    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics.
        
        Returns:
            Dictionary with stats for all engines
        """
        stats = {
            "engines": {},
            "total_requests": 0,
            "total_cache_entries": 0,
        }
        
        for engine_name, engine in self.engines.items():
            engine_stats = engine.get_stats()
            stats["engines"][engine_name] = engine_stats
            stats["total_requests"] += engine_stats["requests"]
            stats["total_cache_entries"] += engine_stats["cache_entries"]
        
        return stats
    
    def test_all_connections(self) -> Dict[str, bool]:
        """Test connections to all configured engines.
        
        Returns:
            Dictionary mapping engine names to connection status
        """
        results = {}
        
        for engine_name, engine in self.engines.items():
            try:
                results[engine_name] = engine.test_connection()
            except Exception as e:
                logger.error(f"Connection test failed for {engine_name}: {e}")
                results[engine_name] = False
        
        return results

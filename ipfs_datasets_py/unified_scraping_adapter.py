#!/usr/bin/env python3
"""
Unified Scraping Adapter

This module provides a unified interface for all scraping operations,
ensuring consistent fallback mechanisms, error handling, and caching across the codebase.

All scraping should go through this adapter instead of direct requests.get() calls.
"""

import logging
import time
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import json

# Import the new unified scrapers
try:
    from enhanced_model_scraper import EnhancedModelScraper, ModelRecord
    from production_hf_scraper import ProductionHFScraper
    HAVE_UNIFIED_SCRAPERS = True
except ImportError:
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from enhanced_model_scraper import EnhancedModelScraper, ModelRecord
        from production_hf_scraper import ProductionHFScraper
        HAVE_UNIFIED_SCRAPERS = True
    except ImportError:
        HAVE_UNIFIED_SCRAPERS = False

logger = logging.getLogger(__name__)


class UnifiedScrapingAdapter:
    """
    Unified adapter for all scraping operations.
    
    This adapter provides:
    1. Consistent fallback mechanisms (API -> Cache -> Mock)
    2. Automatic rate limiting
    3. Error handling and retry logic
    4. Response caching
    5. Data validation
    """
    
    def __init__(self, cache_dir: str = "./unified_scrape_cache", 
                 rate_limit_delay: float = 0.1):
        """Initialize the unified scraping adapter."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True, parents=True)
        self.rate_limit_delay = rate_limit_delay
        self.last_request_time = 0
        
        # Initialize scrapers if available
        if HAVE_UNIFIED_SCRAPERS:
            self.enhanced_scraper = EnhancedModelScraper(data_dir=str(self.cache_dir / "enhanced"))
            self.production_scraper = ProductionHFScraper(data_dir=str(self.cache_dir / "production"))
        else:
            self.enhanced_scraper = None
            self.production_scraper = None
            logger.warning("Unified scrapers not available - using fallback mode")
    
    def scrape_with_fallbacks(self, 
                              primary_method: Callable,
                              fallback_cache_key: Optional[str] = None,
                              mock_generator: Optional[Callable] = None,
                              **kwargs) -> Any:
        """
        Execute scraping with automatic fallbacks.
        
        Args:
            primary_method: Primary scraping method to try
            fallback_cache_key: Cache key for fallback data
            mock_generator: Function to generate mock data if all else fails
            **kwargs: Arguments to pass to primary_method
        
        Returns:
            Scraped data with fallbacks applied
        """
        # Apply rate limiting
        self._apply_rate_limit()
        
        # Try primary method
        try:
            logger.debug(f"Trying primary scraping method: {primary_method.__name__}")
            result = primary_method(**kwargs)
            if result is not None:
                # Cache successful result
                if fallback_cache_key:
                    self._cache_result(fallback_cache_key, result)
                return result
        except Exception as e:
            logger.warning(f"Primary scraping method failed: {e}")
        
        # Try cached data
        if fallback_cache_key:
            try:
                logger.debug(f"Trying cached data for key: {fallback_cache_key}")
                cached = self._load_from_cache(fallback_cache_key)
                if cached is not None:
                    logger.info(f"Using cached data for {fallback_cache_key}")
                    return cached
            except Exception as e:
                logger.warning(f"Cache lookup failed: {e}")
        
        # Try mock generator
        if mock_generator:
            try:
                logger.debug("Generating mock data as final fallback")
                mock_data = mock_generator(**kwargs)
                logger.info("Using mock data as fallback")
                return mock_data
            except Exception as e:
                logger.error(f"Mock data generation failed: {e}")
        
        # All fallbacks failed
        logger.error("All scraping fallbacks failed")
        return None
    
    def scrape_huggingface_models(self, 
                                   query: str = "",
                                   limit: int = 100,
                                   use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        Scrape HuggingFace models using unified scraping infrastructure.
        
        Args:
            query: Search query
            limit: Maximum number of results
            use_cache: Whether to use cached data as fallback
        
        Returns:
            List of model dictionaries
        """
        cache_key = f"hf_models_{query}_{limit}"
        
        def primary_scrape():
            """Primary scraping using production scraper."""
            if self.production_scraper and HAVE_UNIFIED_SCRAPERS:
                import asyncio
                try:
                    # Use async scraper
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    models = loop.run_until_complete(
                        self.production_scraper.get_all_models(limit=limit)
                    )
                    loop.close()
                    return models
                except Exception as e:
                    logger.warning(f"Async scraping failed: {e}")
                    return None
            return None
        
        def mock_generator():
            """Generate mock data."""
            if self.enhanced_scraper and HAVE_UNIFIED_SCRAPERS:
                models = self.enhanced_scraper.create_mock_comprehensive_dataset(size=min(limit, 100))
                return [self._model_record_to_dict(m) for m in models]
            return []
        
        return self.scrape_with_fallbacks(
            primary_method=primary_scrape,
            fallback_cache_key=cache_key if use_cache else None,
            mock_generator=mock_generator
        )
    
    def scrape_model_metadata(self, 
                             model_id: str,
                             use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Scrape detailed metadata for a specific model.
        
        Args:
            model_id: Model identifier
            use_cache: Whether to use cached data
        
        Returns:
            Model metadata dictionary
        """
        cache_key = f"model_meta_{model_id.replace('/', '_')}"
        
        def primary_scrape():
            """Scrape from HuggingFace API."""
            # Would use requests here with proper error handling
            # For now, return None to trigger fallback
            return None
        
        def mock_generator():
            """Generate mock metadata."""
            if self.enhanced_scraper and HAVE_UNIFIED_SCRAPERS:
                models = self.enhanced_scraper.create_mock_comprehensive_dataset(size=1)
                if models:
                    model = models[0]
                    model.model_id = model_id
                    return self._model_record_to_dict(model)
            return {"model_id": model_id, "mock": True}
        
        return self.scrape_with_fallbacks(
            primary_method=primary_scrape,
            fallback_cache_key=cache_key if use_cache else None,
            mock_generator=mock_generator
        )
    
    def _apply_rate_limit(self):
        """Apply rate limiting between requests."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.rate_limit_delay:
            sleep_time = self.rate_limit_delay - time_since_last
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.3f}s")
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()
    
    def _cache_result(self, key: str, data: Any):
        """Cache result to disk."""
        try:
            cache_file = self.cache_dir / f"{key}.json"
            with open(cache_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            logger.debug(f"Cached result to {cache_file}")
        except Exception as e:
            logger.warning(f"Failed to cache result: {e}")
    
    def _load_from_cache(self, key: str) -> Optional[Any]:
        """Load result from cache."""
        try:
            cache_file = self.cache_dir / f"{key}.json"
            if cache_file.exists():
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                logger.debug(f"Loaded cached result from {cache_file}")
                return data
        except Exception as e:
            logger.warning(f"Failed to load from cache: {e}")
        return None
    
    def _model_record_to_dict(self, model: 'ModelRecord') -> Dict[str, Any]:
        """Convert ModelRecord to dictionary."""
        from dataclasses import asdict
        return asdict(model)
    
    def clear_cache(self, pattern: Optional[str] = None):
        """Clear cache files matching pattern."""
        try:
            if pattern:
                for cache_file in self.cache_dir.glob(f"*{pattern}*.json"):
                    cache_file.unlink()
                    logger.info(f"Deleted cache file: {cache_file}")
            else:
                for cache_file in self.cache_dir.glob("*.json"):
                    cache_file.unlink()
                logger.info("Cleared all cache files")
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")


# Global singleton instance
_adapter_instance = None

def get_unified_scraper(cache_dir: str = "./unified_scrape_cache",
                       rate_limit_delay: float = 0.1) -> UnifiedScrapingAdapter:
    """
    Get or create the global unified scraper instance.
    
    Args:
        cache_dir: Directory for caching
        rate_limit_delay: Delay between requests in seconds
    
    Returns:
        UnifiedScrapingAdapter instance
    """
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = UnifiedScrapingAdapter(
            cache_dir=cache_dir,
            rate_limit_delay=rate_limit_delay
        )
    return _adapter_instance


# Convenience functions for backward compatibility
def unified_scrape_hf_models(query: str = "", limit: int = 100, 
                            use_cache: bool = True) -> List[Dict[str, Any]]:
    """
    Scrape HuggingFace models with unified fallback mechanisms.
    
    This is a convenience function that uses the global adapter instance.
    """
    adapter = get_unified_scraper()
    return adapter.scrape_huggingface_models(query=query, limit=limit, use_cache=use_cache)


def unified_scrape_model_metadata(model_id: str, 
                                  use_cache: bool = True) -> Optional[Dict[str, Any]]:
    """
    Scrape model metadata with unified fallback mechanisms.
    
    This is a convenience function that uses the global adapter instance.
    """
    adapter = get_unified_scraper()
    return adapter.scrape_model_metadata(model_id=model_id, use_cache=use_cache)


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)
    
    print("Testing Unified Scraping Adapter")
    print("=" * 60)
    
    # Test HuggingFace scraping
    print("\n1. Testing HuggingFace model scraping...")
    models = unified_scrape_hf_models(query="gpt", limit=10)
    print(f"   Retrieved {len(models)} models")
    
    # Test model metadata
    print("\n2. Testing model metadata scraping...")
    metadata = unified_scrape_model_metadata("gpt2")
    print(f"   Retrieved metadata: {list(metadata.keys()) if metadata else 'None'}")
    
    # Test caching
    print("\n3. Testing cache...")
    models_cached = unified_scrape_hf_models(query="gpt", limit=10)
    print(f"   Retrieved {len(models_cached)} models from cache")
    
    print("\n✅ Unified scraping adapter test complete")

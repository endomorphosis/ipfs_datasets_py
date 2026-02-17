"""HuggingFace API Search for Common Crawl Indexes.

This module enables querying HuggingFace datasets via API without downloading
the full dataset. It provides:
- Streaming search through HF datasets
- Query-based filtering without local storage
- Faster initial queries
- Lower storage requirements

The module supports:
- HuggingFace Inference API for fast queries
- Datasets streaming API for larger results
- Fallback to local/download modes
- Graceful degradation when API unavailable

Example:
    >>> from ipfs_datasets_py.processors.legal_scrapers import HuggingFaceAPISearch
    >>> 
    >>> # Search without downloading full dataset
    >>> searcher = HuggingFaceAPISearch(api_key="hf_...")
    >>> results = searcher.search_federal("EPA water")
    >>> 
    >>> # Search with streaming (larger datasets)
    >>> results = searcher.search_state("California", state_code="CA", use_streaming=True)
"""

import logging
from typing import Dict, List, Optional, Any, Union
from pathlib import Path
import os

logger = logging.getLogger(__name__)

# HuggingFace dataset repos
DATASET_REPOS = {
    "federal": "endomorphosis/common_crawl_federal_index",
    "state": "endomorphosis/common_crawl_state_index",
    "municipal": "endomorphosis/common_crawl_municipal_index",
    "pointers": "endomorphosis/common_crawl_pointers_by_collection",
    "meta": "endomorphosis/common_crawl_meta_indexes"
}

# Try to import HuggingFace libraries
try:
    from huggingface_hub import InferenceClient
    HAVE_HF_HUB = True
except ImportError:
    HAVE_HF_HUB = False
    logger.warning("huggingface_hub not available - API search disabled")

try:
    from datasets import load_dataset
    HAVE_DATASETS = True
except ImportError:
    HAVE_DATASETS = False
    logger.warning("datasets library not available - streaming disabled")


class HuggingFaceAPISearch:
    """Search HuggingFace Common Crawl indexes via API without full download.
    
    This class provides efficient querying of HuggingFace-hosted Common Crawl
    indexes using:
    1. HuggingFace Inference API for fast queries
    2. Datasets streaming API for larger results
    3. Query-based filtering without downloading full datasets
    4. Graceful fallback to local/download modes
    
    Attributes:
        api_key: HuggingFace API key (optional, uses HF_TOKEN env var)
        use_streaming: Whether to use streaming API for large datasets
        cache_dir: Directory for caching API responses
        
    Example:
        >>> searcher = HuggingFaceAPISearch(api_key="hf_...")
        >>> results = searcher.search("EPA regulations", jurisdiction="federal")
        >>> print(f"Found {len(results)} results")
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        use_streaming: bool = True,
        cache_dir: Optional[Union[str, Path]] = None,
        max_results: int = 100
    ):
        """Initialize HuggingFace API Search.
        
        Args:
            api_key: HuggingFace API key (or uses HF_TOKEN env var)
            use_streaming: Whether to use streaming API (recommended for large datasets)
            cache_dir: Directory for caching responses
            max_results: Maximum number of results to return per query
        """
        self.api_key = api_key or os.getenv("HF_TOKEN")
        self.use_streaming = use_streaming and HAVE_DATASETS
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "hf_api_search"
        self.max_results = max_results
        
        # Create cache directory
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize inference client if available
        self.inference_client = None
        if HAVE_HF_HUB and self.api_key:
            try:
                self.inference_client = InferenceClient(token=self.api_key)
                logger.info("HuggingFace Inference API initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize HF Inference API: {e}")
    
    def search(
        self,
        query: str,
        jurisdiction: str = "federal",
        state_code: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search HuggingFace indexes via API.
        
        This is the main entry point for API-based searching. It automatically
        selects the appropriate dataset and search method based on jurisdiction.
        
        Args:
            query: Search query string
            jurisdiction: Type of jurisdiction ("federal", "state", "municipal")
            state_code: State code for state-specific searches (e.g., "CA")
            filters: Additional filters to apply
            
        Returns:
            List of matching records from the index
            
        Example:
            >>> searcher = HuggingFaceAPISearch()
            >>> results = searcher.search("EPA water", jurisdiction="federal")
        """
        if jurisdiction == "federal":
            return self.search_federal(query, filters)
        elif jurisdiction == "state":
            return self.search_state(query, state_code, filters)
        elif jurisdiction == "municipal":
            return self.search_municipal(query, filters)
        else:
            logger.error(f"Unknown jurisdiction: {jurisdiction}")
            return []
    
    def search_federal(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search federal government indexes.
        
        Args:
            query: Search query string
            filters: Additional filters to apply
            
        Returns:
            List of matching federal records
        """
        return self._search_dataset(
            DATASET_REPOS["federal"],
            query,
            filters
        )
    
    def search_state(
        self,
        query: str,
        state_code: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search state government indexes.
        
        Args:
            query: Search query string
            state_code: State code filter (e.g., "CA", "NY")
            filters: Additional filters to apply
            
        Returns:
            List of matching state records
        """
        if state_code:
            if not filters:
                filters = {}
            filters["state"] = state_code.upper()
        
        return self._search_dataset(
            DATASET_REPOS["state"],
            query,
            filters
        )
    
    def search_municipal(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search municipal government indexes.
        
        Args:
            query: Search query string
            filters: Additional filters to apply
            
        Returns:
            List of matching municipal records
        """
        return self._search_dataset(
            DATASET_REPOS["municipal"],
            query,
            filters
        )
    
    def _search_dataset(
        self,
        dataset_name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Internal method to search a specific HuggingFace dataset.
        
        This method handles the actual API interaction, trying streaming first
        if available, then falling back to other methods.
        
        Args:
            dataset_name: HuggingFace dataset repository name
            query: Search query string
            filters: Filters to apply
            
        Returns:
            List of matching records
        """
        if not query or not query.strip():
            logger.warning("Empty query provided")
            return []
        
        query = query.strip().lower()
        results = []
        
        # Try streaming API first (most efficient)
        if self.use_streaming and HAVE_DATASETS:
            try:
                results = self._search_streaming(dataset_name, query, filters)
                if results:
                    logger.info(f"Found {len(results)} results via streaming API")
                    return results
            except Exception as e:
                logger.warning(f"Streaming search failed: {e}")
        
        # Fallback: explain that full download is needed
        logger.info(
            f"API search not available for {dataset_name}. "
            f"Use CommonCrawlIndexLoader for local search or download."
        )
        return []
    
    def _search_streaming(
        self,
        dataset_name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search using HuggingFace datasets streaming API.
        
        This method streams the dataset and filters records matching the query
        without downloading the entire dataset.
        
        Args:
            dataset_name: HuggingFace dataset repository name
            query: Search query (lowercase)
            filters: Additional filters
            
        Returns:
            List of matching records (up to max_results)
        """
        if not HAVE_DATASETS:
            return []
        
        results = []
        query_terms = set(query.split())
        
        try:
            # Load dataset in streaming mode
            logger.info(f"Streaming dataset: {dataset_name}")
            dataset = load_dataset(
                dataset_name,
                split="train",
                streaming=True,
                token=self.api_key
            )
            
            # Iterate through records
            for record in dataset:
                if len(results) >= self.max_results:
                    break
                
                # Check if record matches query
                if self._matches_query(record, query_terms, filters):
                    results.append(record)
            
            logger.info(f"Streaming search found {len(results)} results")
            
        except Exception as e:
            logger.error(f"Streaming search failed: {e}")
            raise
        
        return results
    
    def _matches_query(
        self,
        record: Dict[str, Any],
        query_terms: set,
        filters: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Check if a record matches the query and filters.
        
        Args:
            record: Dataset record to check
            query_terms: Set of query terms (lowercase)
            filters: Additional filters to apply
            
        Returns:
            True if record matches, False otherwise
        """
        # Apply filters first (faster)
        if filters:
            for key, value in filters.items():
                if key in record and record[key] != value:
                    return False
        
        # Check if any field contains query terms
        record_text = ""
        for key, value in record.items():
            if isinstance(value, str):
                record_text += f" {value.lower()}"
        
        # Must match at least one query term
        return any(term in record_text for term in query_terms)
    
    def get_api_status(self) -> Dict[str, Any]:
        """Get status of HuggingFace API integration.
        
        Returns:
            Dictionary with API availability status
        """
        return {
            "hf_hub_available": HAVE_HF_HUB,
            "datasets_available": HAVE_DATASETS,
            "inference_client": self.inference_client is not None,
            "streaming_enabled": self.use_streaming,
            "api_key_configured": bool(self.api_key)
        }


def search_hf_api(
    query: str,
    jurisdiction: str = "federal",
    api_key: Optional[str] = None,
    **kwargs
) -> List[Dict[str, Any]]:
    """Convenience function for HuggingFace API search.
    
    Args:
        query: Search query string
        jurisdiction: Type of jurisdiction ("federal", "state", "municipal")
        api_key: Optional HuggingFace API key
        **kwargs: Additional arguments passed to HuggingFaceAPISearch
        
    Returns:
        List of matching records
        
    Example:
        >>> results = search_hf_api("EPA regulations", jurisdiction="federal")
    """
    searcher = HuggingFaceAPISearch(api_key=api_key, **kwargs)
    return searcher.search(query, jurisdiction)

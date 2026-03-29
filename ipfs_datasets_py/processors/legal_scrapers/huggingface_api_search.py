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
import importlib
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
except (ImportError, AttributeError):
    HAVE_DATASETS = False
    logger.debug("datasets library APIs unavailable - streaming disabled")


def _coalesce_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "")
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _resolve_hf_api_token() -> str:
    token = _coalesce_env(
        "IPFS_DATASETS_PY_HF_API_TOKEN",
        "HUGGINGFACEHUB_API_TOKEN",
        "HUGGINGFACE_API_TOKEN",
        "HUGGINGFACE_HUB_TOKEN",
        "HUGGINGFACE_API_KEY",
        "HF_TOKEN",
        "HF_API_TOKEN",
    )
    if token:
        return token

    try:
        hub = importlib.import_module("huggingface_hub")
        getter = getattr(hub, "get_token", None)
        resolved = getter() if callable(getter) else ""
        if resolved is not None and str(resolved).strip():
            return str(resolved).strip()
    except Exception:
        return ""
    return ""


def _resolve_hf_bill_to(value: Optional[str] = None) -> str:
    if value is not None and str(value).strip():
        return str(value).strip()
    return _coalesce_env(
        "IPFS_DATASETS_PY_HF_BILL_TO",
        "HUGGINGFACE_BILL_TO",
        "HF_BILL_TO",
        "HF_ORGANIZATION",
        "HUGGINGFACE_ORG",
    )


def _admin_rules_force_state_hf_index() -> bool:
    return str(os.getenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        max_results: int = 100,
        bill_to: Optional[str] = None,
    ):
        """Initialize HuggingFace API Search.
        
        Args:
            api_key: HuggingFace API key (or uses HF_TOKEN env var)
            use_streaming: Whether to use streaming API (recommended for large datasets)
            cache_dir: Directory for caching responses
            max_results: Maximum number of results to return per query
        """
        self.api_key = api_key or _resolve_hf_api_token()
        self.bill_to = _resolve_hf_bill_to(bill_to)
        self.use_streaming = use_streaming and HAVE_DATASETS
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "hf_api_search"
        self.max_results = max_results
        
        # Create cache directory
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize inference client if available
        self.inference_client = None
        if HAVE_HF_HUB and self.api_key:
            try:
                client_kwargs = {"token": self.api_key}
                if self.bill_to:
                    client_kwargs["bill_to"] = self.bill_to
                self.inference_client = InferenceClient(**client_kwargs)
                logger.info("HuggingFace Inference API initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize HF Inference API: {e}")
    
    def search(
        self,
        query: str,
        jurisdiction: str = "state",
        state_code: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Search HuggingFace indexes via API.
        
        This is the main entry point for API-based searching. It automatically
        selects the appropriate dataset and search method based on jurisdiction.
        
        Args:
            query: Search query string
            jurisdiction: Type of jurisdiction ("federal", "state", "municipal").
                Defaults to "state" so state/admin discovery does not silently
                fall into the federal index when callers omit jurisdiction.
            state_code: State code for state-specific searches (e.g., "CA")
            filters: Additional filters to apply
            
        Returns:
            List of matching records from the index
            
        Example:
            >>> searcher = HuggingFaceAPISearch()
            >>> results = searcher.search("EPA water", jurisdiction="federal")
        """
        if jurisdiction == "federal" and _admin_rules_force_state_hf_index():
            logger.info(
                "Redirecting HuggingFace Common Crawl search from federal to state for admin-rules agentic mode"
            )
            jurisdiction = "state"

        if jurisdiction == "federal":
            return self.search_federal(query, filters, max_results=max_results)
        elif jurisdiction == "state":
            return self.search_state(query, state_code, filters, max_results=max_results)
        elif jurisdiction == "municipal":
            return self.search_municipal(query, filters, max_results=max_results)
        else:
            logger.error(f"Unknown jurisdiction: {jurisdiction}")
            return []
    
    def search_federal(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Search federal government indexes.
        
        Args:
            query: Search query string
            filters: Additional filters to apply
            
        Returns:
            List of matching federal records
        """
        if _admin_rules_force_state_hf_index():
            logger.info(
                "Redirecting direct HuggingFace federal index search to state for admin-rules agentic mode"
            )
            return self.search_state(query, filters=filters, max_results=max_results)

        return self._search_dataset(
            DATASET_REPOS["federal"],
            query,
            filters,
            max_results=max_results,
        )
    
    def search_state(
        self,
        query: str,
        state_code: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None,
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
            filters,
            max_results=max_results,
        )
    
    def search_municipal(
        self,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None,
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
            filters,
            max_results=max_results,
        )
    
    def _search_dataset(
        self,
        dataset_name: str,
        query: str,
        filters: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None,
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
                results = self._search_streaming(dataset_name, query, filters, max_results=max_results)
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
        filters: Optional[Dict[str, Any]] = None,
        max_results: Optional[int] = None,
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
        result_limit = max_results if max_results is not None else self.max_results
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
                if len(results) >= result_limit:
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
            "api_key_configured": bool(self.api_key),
            "hf_bill_to": self.bill_to,
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

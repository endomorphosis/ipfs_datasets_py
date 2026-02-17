"""Common Crawl Index Loader with HuggingFace Integration.

This module provides a smart loader for Common Crawl indexes that:
1. Checks local filesystem first (fast path)
2. Falls back to HuggingFace datasets library if not found
3. Caches downloaded indexes for future use
4. Handles partial uploads gracefully

The loader supports jurisdiction-specific indexes:
- Federal: endomorphosis/common_crawl_federal_index
- State: endomorphosis/common_crawl_state_index
- Municipal: endomorphosis/common_crawl_municipal_index
- Pointers: endomorphosis/common_crawl_pointers_by_collection
- Meta Indexes: endomorphosis/common_crawl_meta_indexes

Example:
    >>> from ipfs_datasets_py.processors.legal_scrapers import CommonCrawlIndexLoader
    >>> 
    >>> # Load federal index (checks local first, then HuggingFace)
    >>> loader = CommonCrawlIndexLoader()
    >>> federal_index = loader.load_federal_index()
    >>> 
    >>> # Load state index for a specific state
    >>> ca_index = loader.load_state_index("CA")
    >>> 
    >>> # Load municipal index
    >>> municipal_index = loader.load_municipal_index()
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import json

logger = logging.getLogger(__name__)

# HuggingFace dataset names
DATASET_REPOS = {
    "federal": "endomorphosis/common_crawl_federal_index",
    "state": "endomorphosis/common_crawl_state_index",
    "municipal": "endomorphosis/common_crawl_municipal_index",
    "pointers": "endomorphosis/common_crawl_pointers_by_collection",
    "meta": "endomorphosis/common_crawl_meta_indexes"
}

# Default local paths
DEFAULT_LOCAL_PATHS = {
    "federal": "data/common_crawl_indexes/federal",
    "state": "data/common_crawl_indexes/state",
    "municipal": "data/common_crawl_indexes/municipal",
    "pointers": "data/common_crawl_indexes/pointers",
    "meta": "data/common_crawl_indexes/meta"
}


class CommonCrawlIndexLoader:
    """Loader for Common Crawl indexes with local filesystem + HuggingFace fallback.
    
    This class provides intelligent loading of Common Crawl indexes:
    1. Fast path: Check local filesystem first
    2. Fallback: Download from HuggingFace using datasets library
    3. Cache: Store downloaded indexes locally for future use
    4. Graceful degradation: Handle partial uploads
    
    Attributes:
        local_base_dir: Base directory for local index storage
        cache_dir: Directory for caching downloaded HuggingFace datasets
        use_hf_fallback: Whether to fall back to HuggingFace if local not found
        verify_integrity: Whether to verify index file integrity
        
    Example:
        >>> loader = CommonCrawlIndexLoader(
        ...     local_base_dir="/path/to/indexes",
        ...     use_hf_fallback=True
        ... )
        >>> federal_index = loader.load_federal_index()
        >>> if federal_index:
        ...     print(f"Loaded {len(federal_index)} federal records")
    """
    
    def __init__(
        self,
        local_base_dir: Optional[Union[str, Path]] = None,
        cache_dir: Optional[Union[str, Path]] = None,
        use_hf_fallback: bool = True,
        verify_integrity: bool = False
    ):
        """Initialize the Common Crawl Index Loader.
        
        Args:
            local_base_dir: Base directory for local indexes (checks this first)
            cache_dir: Directory for caching HuggingFace downloads
            use_hf_fallback: Whether to fall back to HuggingFace if local not found
            verify_integrity: Whether to verify downloaded index integrity
        """
        self.local_base_dir = Path(local_base_dir) if local_base_dir else Path.cwd() / "data" / "common_crawl_indexes"
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "huggingface" / "datasets"
        self.use_hf_fallback = use_hf_fallback
        self.verify_integrity = verify_integrity
        
        # Track what's been loaded to avoid redundant operations
        self._loaded_indexes: Dict[str, Any] = {}
        
        # Check if datasets library is available
        self._have_datasets = self._check_datasets_available()
        
        logger.info(f"CommonCrawlIndexLoader initialized:")
        logger.info(f"  Local base dir: {self.local_base_dir}")
        logger.info(f"  Cache dir: {self.cache_dir}")
        logger.info(f"  HF fallback: {self.use_hf_fallback}")
        logger.info(f"  datasets library: {self._have_datasets}")
    
    def _check_datasets_available(self) -> bool:
        """Check if HuggingFace datasets library is available."""
        try:
            import datasets
            return True
        except ImportError:
            logger.warning("HuggingFace datasets library not available. Install with: pip install datasets")
            return False
    
    def _get_local_path(self, index_type: str) -> Path:
        """Get the local filesystem path for an index type.
        
        Args:
            index_type: Type of index ("federal", "state", "municipal", "pointers", "meta")
            
        Returns:
            Path to local index directory
        """
        return self.local_base_dir / index_type
    
    def _check_local_index(self, index_type: str) -> Optional[Path]:
        """Check if index exists locally and return path if found.
        
        Args:
            index_type: Type of index to check
            
        Returns:
            Path to local index if found, None otherwise
        """
        local_path = self._get_local_path(index_type)
        
        if not local_path.exists():
            logger.debug(f"Local index not found: {local_path}")
            return None
        
        # Check if directory has any parquet or index files
        parquet_files = list(local_path.glob("*.parquet"))
        index_files = list(local_path.glob("*.index")) + list(local_path.glob("*.jsonl"))
        
        if parquet_files or index_files:
            logger.info(f"Found local index at {local_path}: {len(parquet_files)} parquet, {len(index_files)} index files")
            return local_path
        
        logger.debug(f"Local index directory empty: {local_path}")
        return None
    
    def _load_from_huggingface(self, index_type: str, **kwargs) -> Optional[Any]:
        """Load index from HuggingFace datasets.
        
        Args:
            index_type: Type of index to load
            **kwargs: Additional arguments passed to load_dataset
            
        Returns:
            Loaded dataset or None if failed
        """
        if not self._have_datasets:
            logger.error("Cannot load from HuggingFace: datasets library not available")
            return None
        
        if not self.use_hf_fallback:
            logger.debug("HuggingFace fallback disabled")
            return None
        
        repo_name = DATASET_REPOS.get(index_type)
        if not repo_name:
            logger.error(f"Unknown index type: {index_type}")
            return None
        
        try:
            from datasets import load_dataset
            
            logger.info(f"Loading {index_type} index from HuggingFace: {repo_name}")
            logger.info("This may take a while for large indexes...")
            
            # Load dataset with caching
            dataset = load_dataset(
                repo_name,
                cache_dir=str(self.cache_dir),
                **kwargs
            )
            
            logger.info(f"Successfully loaded {index_type} index from HuggingFace")
            
            # Cache locally for future use
            self._cache_dataset_locally(dataset, index_type)
            
            return dataset
            
        except Exception as e:
            logger.warning(f"Failed to load from HuggingFace: {e}")
            logger.warning(f"Note: Dataset may still be uploading to HuggingFace")
            return None
    
    def _cache_dataset_locally(self, dataset: Any, index_type: str):
        """Cache a HuggingFace dataset to local filesystem.
        
        Args:
            dataset: HuggingFace dataset to cache
            index_type: Type of index being cached
        """
        try:
            local_path = self._get_local_path(index_type)
            local_path.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Caching {index_type} index to {local_path}")
            
            # Export to parquet for fast future loading
            if hasattr(dataset, 'to_parquet'):
                output_file = local_path / f"{index_type}_index.parquet"
                dataset.to_parquet(str(output_file))
                logger.info(f"Cached to: {output_file}")
            else:
                logger.warning(f"Dataset does not support parquet export")
                
        except Exception as e:
            logger.warning(f"Failed to cache dataset locally: {e}")
    
    def load_federal_index(self, force_refresh: bool = False) -> Optional[Any]:
        """Load federal government Common Crawl index.
        
        This loads index records for federal .gov domains (e.g., epa.gov, fda.gov).
        Checks local filesystem first, then falls back to HuggingFace.
        
        Args:
            force_refresh: Force reload from HuggingFace even if local copy exists
            
        Returns:
            Federal index dataset or None if not available
            
        Example:
            >>> loader = CommonCrawlIndexLoader()
            >>> federal_index = loader.load_federal_index()
            >>> if federal_index:
            ...     print(f"Loaded {len(federal_index)} federal records")
        """
        if "federal" in self._loaded_indexes and not force_refresh:
            return self._loaded_indexes["federal"]
        
        # Check local first
        if not force_refresh:
            local_path = self._check_local_index("federal")
            if local_path:
                # Load from local parquet files
                try:
                    import pandas as pd
                    parquet_files = list(local_path.glob("*.parquet"))
                    if parquet_files:
                        logger.info(f"Loading federal index from local parquet files")
                        dfs = [pd.read_parquet(f) for f in parquet_files]
                        federal_index = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
                        self._loaded_indexes["federal"] = federal_index
                        return federal_index
                except Exception as e:
                    logger.warning(f"Failed to load local parquet: {e}")
        
        # Fallback to HuggingFace
        dataset = self._load_from_huggingface("federal")
        if dataset:
            self._loaded_indexes["federal"] = dataset
        return dataset
    
    def load_state_index(self, state_code: Optional[str] = None, force_refresh: bool = False) -> Optional[Any]:
        """Load state government Common Crawl index.
        
        This loads index records for state .gov domains (e.g., ca.gov, ny.gov).
        Can optionally filter to a specific state.
        
        Args:
            state_code: Optional 2-letter state code to filter (e.g., "CA", "NY")
            force_refresh: Force reload from HuggingFace even if local copy exists
            
        Returns:
            State index dataset or None if not available
            
        Example:
            >>> loader = CommonCrawlIndexLoader()
            >>> ca_index = loader.load_state_index("CA")
            >>> if ca_index:
            ...     print(f"Loaded {len(ca_index)} California records")
        """
        cache_key = f"state_{state_code}" if state_code else "state"
        
        if cache_key in self._loaded_indexes and not force_refresh:
            return self._loaded_indexes[cache_key]
        
        # Check local first
        if not force_refresh:
            local_path = self._check_local_index("state")
            if local_path:
                try:
                    import pandas as pd
                    parquet_files = list(local_path.glob("*.parquet"))
                    
                    # If state_code specified, look for state-specific file first
                    if state_code:
                        state_files = list(local_path.glob(f"*{state_code.lower()}*.parquet"))
                        if state_files:
                            parquet_files = state_files
                    
                    if parquet_files:
                        logger.info(f"Loading state index from local parquet files")
                        dfs = [pd.read_parquet(f) for f in parquet_files]
                        state_index = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
                        
                        # Filter by state code if specified
                        if state_code and 'state' in state_index.columns:
                            state_index = state_index[state_index['state'].str.upper() == state_code.upper()]
                        
                        self._loaded_indexes[cache_key] = state_index
                        return state_index
                except Exception as e:
                    logger.warning(f"Failed to load local parquet: {e}")
        
        # Fallback to HuggingFace
        dataset = self._load_from_huggingface("state")
        if dataset and state_code:
            # Filter by state code
            try:
                dataset = dataset.filter(lambda x: x.get('state', '').upper() == state_code.upper())
            except Exception as e:
                logger.warning(f"Failed to filter by state: {e}")
        
        if dataset:
            self._loaded_indexes[cache_key] = dataset
        return dataset
    
    def load_municipal_index(self, force_refresh: bool = False) -> Optional[Any]:
        """Load municipal/county Common Crawl index.
        
        This loads index records for city and county websites.
        
        Args:
            force_refresh: Force reload from HuggingFace even if local copy exists
            
        Returns:
            Municipal index dataset or None if not available
            
        Example:
            >>> loader = CommonCrawlIndexLoader()
            >>> municipal_index = loader.load_municipal_index()
            >>> if municipal_index:
            ...     print(f"Loaded {len(municipal_index)} municipal records")
        """
        if "municipal" in self._loaded_indexes and not force_refresh:
            return self._loaded_indexes["municipal"]
        
        # Check local first
        if not force_refresh:
            local_path = self._check_local_index("municipal")
            if local_path:
                try:
                    import pandas as pd
                    parquet_files = list(local_path.glob("*.parquet"))
                    if parquet_files:
                        logger.info(f"Loading municipal index from local parquet files")
                        dfs = [pd.read_parquet(f) for f in parquet_files]
                        municipal_index = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
                        self._loaded_indexes["municipal"] = municipal_index
                        return municipal_index
                except Exception as e:
                    logger.warning(f"Failed to load local parquet: {e}")
        
        # Fallback to HuggingFace
        dataset = self._load_from_huggingface("municipal")
        if dataset:
            self._loaded_indexes["municipal"] = dataset
        return dataset
    
    def load_pointers_index(self, force_refresh: bool = False) -> Optional[Any]:
        """Load Common Crawl pointers by collection index.
        
        This loads the mapping of URLs to their locations in Common Crawl WARC files.
        
        Args:
            force_refresh: Force reload from HuggingFace even if local copy exists
            
        Returns:
            Pointers index dataset or None if not available
        """
        if "pointers" in self._loaded_indexes and not force_refresh:
            return self._loaded_indexes["pointers"]
        
        # Check local first
        if not force_refresh:
            local_path = self._check_local_index("pointers")
            if local_path:
                try:
                    import pandas as pd
                    parquet_files = list(local_path.glob("*.parquet"))
                    if parquet_files:
                        logger.info(f"Loading pointers index from local parquet files")
                        dfs = [pd.read_parquet(f) for f in parquet_files]
                        pointers_index = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
                        self._loaded_indexes["pointers"] = pointers_index
                        return pointers_index
                except Exception as e:
                    logger.warning(f"Failed to load local parquet: {e}")
        
        # Fallback to HuggingFace
        dataset = self._load_from_huggingface("pointers")
        if dataset:
            self._loaded_indexes["pointers"] = dataset
        return dataset
    
    def load_meta_indexes(self, force_refresh: bool = False) -> Optional[Any]:
        """Load Common Crawl meta indexes.
        
        This loads metadata about available Common Crawl collections and indexes.
        
        Args:
            force_refresh: Force reload from HuggingFace even if local copy exists
            
        Returns:
            Meta indexes dataset or None if not available
        """
        if "meta" in self._loaded_indexes and not force_refresh:
            return self._loaded_indexes["meta"]
        
        # Check local first
        if not force_refresh:
            local_path = self._check_local_index("meta")
            if local_path:
                try:
                    import pandas as pd
                    parquet_files = list(local_path.glob("*.parquet"))
                    if parquet_files:
                        logger.info(f"Loading meta indexes from local parquet files")
                        dfs = [pd.read_parquet(f) for f in parquet_files]
                        meta_indexes = pd.concat(dfs, ignore_index=True) if len(dfs) > 1 else dfs[0]
                        self._loaded_indexes["meta"] = meta_indexes
                        return meta_indexes
                except Exception as e:
                    logger.warning(f"Failed to load local parquet: {e}")
        
        # Fallback to HuggingFace
        dataset = self._load_from_huggingface("meta")
        if dataset:
            self._loaded_indexes["meta"] = dataset
        return dataset
    
    def get_index_info(self) -> Dict[str, Any]:
        """Get information about available indexes.
        
        Returns:
            Dictionary with index availability and statistics
        """
        info = {
            "local_base_dir": str(self.local_base_dir),
            "cache_dir": str(self.cache_dir),
            "use_hf_fallback": self.use_hf_fallback,
            "have_datasets": self._have_datasets,
            "indexes": {}
        }
        
        for index_type in ["federal", "state", "municipal", "pointers", "meta"]:
            local_path = self._check_local_index(index_type)
            info["indexes"][index_type] = {
                "local_available": local_path is not None,
                "local_path": str(local_path) if local_path else None,
                "hf_repo": DATASET_REPOS[index_type],
                "loaded": index_type in self._loaded_indexes
            }
        
        return info
    
    def clear_cache(self):
        """Clear loaded index cache to free memory."""
        self._loaded_indexes.clear()
        logger.info("Cleared index cache")

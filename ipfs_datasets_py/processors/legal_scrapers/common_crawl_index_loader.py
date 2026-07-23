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
import time
import shutil
import hashlib
from urllib.parse import urlencode
from urllib.request import urlopen

logger = logging.getLogger(__name__)


def _admin_rules_force_state_hf_index() -> bool:
    return str(os.getenv("LEGAL_ADMIN_RULES_DIRECT_AGENTIC_ALL_STATES", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

# HuggingFace dataset names
DATASET_REPOS = {
    "federal": "endomorphosis/common_crawl_federal_index",
    "state": "endomorphosis/common_crawl_state_index",
    "municipal": "endomorphosis/common_crawl_municipal_index",
    "pointers": "endomorphosis/common_crawl_pointers_by_collection",
    "meta": "endomorphosis/common_crawl_meta_indexes"
}

DATASET_REPO_CANDIDATES = {
    "federal": ["endomorphosis/common_crawl_federal_index"],
    "state": ["endomorphosis/common_crawl_state_index"],
    "municipal": [
        "endomorphosis/common_crawl_municipal_index",
        "Publicus/common_crawl_municipal_index",
    ],
    "pointers": [
        "endomorphosis/common_crawl_pointers_by_collection",
        "Publicus/common_crawl_pointers_by_collection",
    ],
    "meta": [
        "endomorphosis/common_crawl_meta_indexes",
        "Publicus/common_crawl_meta_indexes",
    ],
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
        env_local_base_dir = str(os.getenv("IPFS_DATASETS_PY_COMMON_CRAWL_INDEX_ROOT", "") or "").strip()
        chosen_local_base_dir = local_base_dir or env_local_base_dir or (Path.cwd() / "data" / "common_crawl_indexes")
        self.local_base_dir = Path(chosen_local_base_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "huggingface" / "datasets"
        self.use_hf_fallback = use_hf_fallback
        self.verify_integrity = verify_integrity
        
        # Track what's been loaded to avoid redundant operations
        self._loaded_indexes: Dict[str, Any] = {}
        self.last_query_error: Optional[str] = None
        
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
        parquet_files = list(local_path.rglob("*.parquet"))
        index_files = (
            list(local_path.rglob("*.index"))
            + list(local_path.rglob("*.jsonl"))
        )
        
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

    def _get_hf_parquet_urls(self, index_type: str) -> List[str]:
        """Return converted parquet URLs for a hosted Common Crawl index."""
        if not self.use_hf_fallback:
            return []
        candidates = DATASET_REPO_CANDIDATES.get(index_type) or [DATASET_REPOS[index_type]]
        last_error: Optional[Exception] = None
        for repo_name in candidates:
            try:
                query = urlencode({"dataset": repo_name})
                with urlopen(f"https://datasets-server.huggingface.co/parquet?{query}", timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                urls = [
                    str(item.get("url") or "")
                    for item in payload.get("parquet_files", [])
                    if item.get("url")
                ]
                if urls:
                    return urls
            except Exception as exc:
                last_error = exc
                logger.debug("Failed to resolve parquet URLs for %s: %s", repo_name, exc)
        if last_error is not None:
            logger.warning("Failed to resolve HF parquet URLs for %s: %s", index_type, last_error)
        return []

    def materialize_index_locally(self, index_type: str, force_refresh: bool = False) -> List[Path]:
        """Download hosted parquet shards into the local index directory.

        This makes subsequent DuckDB queries hit the local fast-path instead of
        remote HF parquet URLs.
        """
        local_path = self._get_local_path(index_type)
        if local_path.exists() and not force_refresh:
            existing = sorted(local_path.rglob("*.parquet"))
            if existing:
                logger.info("Using existing local %s parquet shards at %s", index_type, local_path)
                return existing

        urls = self._get_hf_parquet_urls(index_type)
        if not urls:
            logger.warning("No Hugging Face parquet URLs were available for %s", index_type)
            return []

        local_path.mkdir(parents=True, exist_ok=True)
        downloaded: List[Path] = []
        for index, url in enumerate(urls, start=1):
            filename = Path(str(url).split("?", 1)[0]).name or f"{index_type}_{index:04d}.parquet"
            target = local_path / filename
            if target.exists() and not force_refresh and target.stat().st_size > 0:
                downloaded.append(target)
                continue
            try:
                with urlopen(url, timeout=120) as response, target.open("wb") as fh:
                    shutil.copyfileobj(response, fh)
                downloaded.append(target)
            except Exception as exc:
                logger.warning("Failed to download %s parquet shard %s: %s", index_type, url, exc)
        return downloaded

    def materialize_state_index_locally(self, force_refresh: bool = False) -> List[Path]:
        """Download the state Common Crawl index parquet shards locally."""
        return self.materialize_index_locally("state", force_refresh=force_refresh)

    @staticmethod
    def _sql_literal(value: Any) -> str:
        return "'" + str(value or "").replace("'", "''") + "'"

    def _state_query_sidecar_dir(self) -> Path:
        configured = str(
            os.getenv("IPFS_DATASETS_PY_COMMON_CRAWL_STATE_QUERY_SIDECAR_DIR", "") or ""
        ).strip()
        if configured:
            return Path(configured)
        return self.local_base_dir / "state_query_sidecars"

    def _state_query_sidecar_enabled(self) -> bool:
        raw = str(os.getenv("IPFS_DATASETS_PY_COMMON_CRAWL_USE_STATE_QUERY_SIDECAR", "") or "").strip().lower()
        if raw in {"0", "false", "no", "off"}:
            return False
        return True

    def _state_query_sidecar_path(
        self,
        *,
        state_code: Optional[str] = None,
        domain_terms: Optional[List[str]] = None,
        url_terms: Optional[List[str]] = None,
        mime_terms: Optional[List[str]] = None,
        status_code: Optional[int] = 200,
    ) -> Path:
        payload = {
            "state_code": str(state_code or "").strip().upper(),
            "domain_terms": sorted(str(term or "").strip().lower() for term in list(domain_terms or []) if str(term or "").strip()),
            "url_terms": sorted(str(term or "").strip().lower() for term in list(url_terms or []) if str(term or "").strip()),
            "mime_terms": sorted(str(term or "").strip().lower() for term in list(mime_terms or []) if str(term or "").strip()),
            "status_code": status_code,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        state_label = payload["state_code"] or "ALL"
        return self._state_query_sidecar_dir() / f"state_query_{state_label}_{digest}.parquet"

    def materialize_state_query_sidecar(
        self,
        *,
        state_code: Optional[str] = None,
        domain_terms: Optional[List[str]] = None,
        url_terms: Optional[List[str]] = None,
        mime_terms: Optional[List[str]] = None,
        status_code: Optional[int] = 200,
        force_refresh: bool = False,
    ) -> Optional[Path]:
        """Build a small local parquet sidecar for a state query signature.

        The source state parquet is very large, and some hosted/local shards have
        sparse ``state_code`` values. This sidecar intentionally filters by the
        caller's domain/url/mime hints and can be reused across repeated daemon
        passes.
        """
        if not self._state_query_sidecar_enabled():
            return None

        try:
            import duckdb
        except Exception as exc:
            self.last_query_error = f"DuckDB is required for state query sidecars: {exc}"
            logger.warning("%s", self.last_query_error)
            return None

        local_path = self._check_local_index("state")
        if local_path is None:
            return None
        relation = self._duckdb_relation_for_index("state")
        if not relation:
            return None

        target = self._state_query_sidecar_path(
            state_code=state_code,
            domain_terms=domain_terms,
            url_terms=url_terms,
            mime_terms=mime_terms,
            status_code=status_code,
        )
        if target.exists() and not force_refresh and target.stat().st_size > 0:
            return target

        filters: List[str] = []
        if status_code is not None:
            filters.append(f"status = {int(status_code)}")

        domain_filters: List[str] = []
        for term in list(domain_terms or []):
            normalized = str(term or "").strip().lower()
            if normalized:
                domain_filters.append(f"lower(domain) LIKE {self._sql_literal('%' + normalized + '%')}")
        if domain_filters:
            filters.append("(" + " OR ".join(domain_filters) + ")")

        url_filters: List[str] = []
        for term in list(url_terms or []):
            normalized = str(term or "").strip().lower()
            if normalized:
                url_filters.append(f"lower(url) LIKE {self._sql_literal('%' + normalized + '%')}")
        if url_filters:
            filters.append("(" + " OR ".join(url_filters) + ")")

        mime_filters: List[str] = []
        for term in list(mime_terms or []):
            normalized = str(term or "").strip().lower()
            if normalized:
                mime_filters.append(f"lower(mime) LIKE {self._sql_literal('%' + normalized + '%')}")
        if mime_filters:
            filters.append("(" + " OR ".join(mime_filters) + ")")

        where_clause = " AND ".join(filters) if filters else "TRUE"
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_target = target.with_suffix(".tmp.parquet")
        if tmp_target.exists():
            tmp_target.unlink()
        sql = f"""
            COPY (
                SELECT domain, url, collection, timestamp, mime, status,
                       warc_filename, warc_offset, warc_length, gnis, place_name, state_code
                FROM {relation}
                WHERE {where_clause}
            ) TO {self._sql_literal(str(tmp_target))} (FORMAT PARQUET)
        """
        try:
            duckdb.connect().execute(sql)
            if tmp_target.exists() and tmp_target.stat().st_size > 0:
                tmp_target.replace(target)
                logger.info("Materialized state query sidecar at %s", target)
                return target
        except Exception as exc:
            self.last_query_error = str(exc)
            logger.warning("Failed to materialize state query sidecar: %s", exc)
        finally:
            if tmp_target.exists():
                try:
                    tmp_target.unlink()
                except Exception:
                    pass
        return None

    def _duckdb_relation_for_index(self, index_type: str) -> Optional[str]:
        """Build a DuckDB read_parquet relation for local or HF parquet files."""
        local_path = self._check_local_index(index_type)
        if local_path is not None:
            parquet_files = sorted(local_path.rglob("*.parquet"))
            if parquet_files:
                if len(parquet_files) == 1:
                    return f"read_parquet({self._sql_literal(str(parquet_files[0]))})"
                values = ", ".join(self._sql_literal(str(path)) for path in parquet_files)
                return f"read_parquet([{values}])"

        urls = self._get_hf_parquet_urls(index_type)
        if not urls:
            return None
        if len(urls) == 1:
            return f"read_parquet({self._sql_literal(urls[0])})"
        values = ", ".join(self._sql_literal(url) for url in urls)
        return f"read_parquet([{values}])"

    def query_municipal_index(
        self,
        *,
        place_name: Optional[str] = None,
        state_code: Optional[str] = None,
        gnis: Optional[str] = None,
        url_terms: Optional[List[str]] = None,
        mime_terms: Optional[List[str]] = None,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query municipal Common Crawl pointers without loading the full index.

        The hosted municipal index is multi-GB, so this method uses DuckDB over
        local/HF parquet files and pushes place/state/url filters down to parquet.
        """
        try:
            import duckdb
        except Exception as exc:
            self.last_query_error = f"DuckDB is required for remote municipal index queries: {exc}"
            logger.warning("%s", self.last_query_error)
            return []

        self.last_query_error = None
        relation = self._duckdb_relation_for_index("municipal")
        if not relation:
            self.last_query_error = "No municipal Common Crawl parquet relation was available"
            return []

        filters: List[str] = []
        if state_code:
            filters.append(f"upper(state_code) = upper({self._sql_literal(state_code)})")
        if gnis:
            filters.append(f"gnis = {self._sql_literal(gnis)}")
        if place_name:
            place = str(place_name).strip().lower()
            place = place.removeprefix("city of ").removeprefix("town of ").removeprefix("county of ").strip()
            filters.append(f"lower(place_name) LIKE {self._sql_literal('%' + place + '%')}")
        term_filters: List[str] = []
        for term in list(url_terms or []):
            normalized = str(term or "").strip().lower()
            if normalized:
                term_filters.append(f"lower(url) LIKE {self._sql_literal('%' + normalized + '%')}")
        if term_filters:
            filters.append("(" + " OR ".join(term_filters) + ")")
        mime_filters: List[str] = []
        for term in list(mime_terms or []):
            normalized = str(term or "").strip().lower()
            if normalized:
                mime_filters.append(f"lower(mime) LIKE {self._sql_literal('%' + normalized + '%')}")
        if mime_filters:
            filters.append("(" + " OR ".join(mime_filters) + ")")

        where_clause = " AND ".join(filters) if filters else "TRUE"
        limit = max(1, int(max_results or 100))
        sql = f"""
            SELECT domain, url, collection, timestamp, mime, status,
                   warc_filename, warc_offset, warc_length, gnis, place_name, state_code
            FROM {relation}
            WHERE {where_clause}
            ORDER BY
                CASE WHEN status = 200 THEN 0 ELSE 1 END,
                CASE WHEN lower(mime) LIKE '%html%' THEN 0 ELSE 1 END,
                timestamp DESC
            LIMIT {limit}
        """
        attempts = 3
        backoff_seconds = 5.0
        for attempt in range(attempts):
            try:
                return [dict(row) for row in duckdb.connect().execute(sql).fetchdf().to_dict("records")]
            except Exception as exc:
                self.last_query_error = str(exc)
                is_rate_limited = "429" in str(exc) or "Too Many Requests" in str(exc)
                if attempt + 1 >= attempts or not is_rate_limited:
                    logger.warning("Municipal Common Crawl index query failed: %s", exc)
                    return []
                time.sleep(backoff_seconds * (attempt + 1))
        return []

    def query_state_index(
        self,
        *,
        state_code: Optional[str] = None,
        domain_terms: Optional[List[str]] = None,
        url_terms: Optional[List[str]] = None,
        mime_terms: Optional[List[str]] = None,
        status_code: Optional[int] = 200,
        max_results: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query state Common Crawl records without loading the full index."""
        try:
            import duckdb
        except Exception as exc:
            self.last_query_error = f"DuckDB is required for remote state index queries: {exc}"
            logger.warning("%s", self.last_query_error)
            return []

        self.last_query_error = None
        sidecar_path = self.materialize_state_query_sidecar(
            state_code=state_code,
            domain_terms=domain_terms,
            url_terms=url_terms,
            mime_terms=mime_terms,
            status_code=status_code,
        )
        relation = None
        if sidecar_path is not None and sidecar_path.exists():
            relation = f"read_parquet({self._sql_literal(str(sidecar_path))})"
        if relation is None:
            relation = self._duckdb_relation_for_index("state")
        if not relation:
            self.last_query_error = "No state Common Crawl parquet relation was available"
            return []

        limit = max(1, int(max_results or 100))

        def _build_query(include_state_code: bool) -> str:
            filters: List[str] = []
            if include_state_code and state_code:
                filters.append(
                    f"upper(CAST(state_code AS VARCHAR)) = upper({self._sql_literal(state_code)})"
                )
            if status_code is not None:
                filters.append(f"status = {int(status_code)}")

            domain_filters: List[str] = []
            for term in list(domain_terms or []):
                normalized = str(term or "").strip().lower()
                if normalized:
                    domain_filters.append(f"lower(domain) LIKE {self._sql_literal('%' + normalized + '%')}")
            if domain_filters:
                filters.append("(" + " OR ".join(domain_filters) + ")")

            url_filters: List[str] = []
            for term in list(url_terms or []):
                normalized = str(term or "").strip().lower()
                if normalized:
                    url_filters.append(f"lower(url) LIKE {self._sql_literal('%' + normalized + '%')}")
            if url_filters:
                filters.append("(" + " OR ".join(url_filters) + ")")

            mime_filters: List[str] = []
            for term in list(mime_terms or []):
                normalized = str(term or "").strip().lower()
                if normalized:
                    mime_filters.append(f"lower(mime) LIKE {self._sql_literal('%' + normalized + '%')}")
            if mime_filters:
                filters.append("(" + " OR ".join(mime_filters) + ")")

            where_clause = " AND ".join(filters) if filters else "TRUE"
            return f"""
                SELECT domain, url, collection, timestamp, mime, status,
                       warc_filename, warc_offset, warc_length, gnis, place_name, state_code
                FROM {relation}
                WHERE {where_clause}
                ORDER BY
                    CASE WHEN status = 200 THEN 0 ELSE 1 END,
                    CASE WHEN lower(mime) LIKE '%html%' THEN 0 ELSE 1 END,
                    timestamp DESC
                LIMIT {limit}
            """

        def _execute(sql: str) -> List[Dict[str, Any]]:
            return [dict(row) for row in duckdb.connect().execute(sql).fetchdf().to_dict("records")]

        attempts = 3
        backoff_seconds = 5.0
        for attempt in range(attempts):
            try:
                rows = _execute(_build_query(include_state_code=bool(state_code)))
                if rows or not state_code:
                    return rows
                logger.info(
                    "State Common Crawl query returned no rows for state_code=%s; retrying without state filter",
                    state_code,
                )
                fallback_rows = _execute(_build_query(include_state_code=False))
                if fallback_rows:
                    for row in fallback_rows:
                        if not row.get("state_code"):
                            row["state_code"] = state_code
                return fallback_rows
            except Exception as exc:
                self.last_query_error = str(exc)
                is_rate_limited = "429" in str(exc) or "Too Many Requests" in str(exc)
                if attempt + 1 >= attempts or not is_rate_limited:
                    logger.warning("State Common Crawl index query failed: %s", exc)
                    return []
                time.sleep(backoff_seconds * (attempt + 1))
        return []
    
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
        if _admin_rules_force_state_hf_index():
            logger.info(
                "Redirecting Common Crawl federal index load to state index for admin-rules agentic mode"
            )
            return self.load_state_index(force_refresh=force_refresh)

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

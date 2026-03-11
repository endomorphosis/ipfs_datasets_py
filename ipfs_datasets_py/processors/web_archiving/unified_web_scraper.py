"""
Unified Web Scraping System with Intelligent Fallback Mechanisms

This module provides a comprehensive, centralized web scraping system that automatically
tries multiple scraping methods in a smart fallback sequence. It eliminates duplicate
scraping logic across the codebase by providing a single interface for all web scraping needs.

Supported Scraping Methods (in fallback order):
1. Playwright - JavaScript rendering, dynamic content
2. BeautifulSoup + Requests - Standard HTML parsing
3. Wayback Machine - Historical snapshots via Internet Archive
4. Common Crawl - Large-scale web archive
5. Archive.is - Permanent webpage snapshots
6. Cloudflare Browser Rendering crawl - remote crawl fallback
7. IPWB (InterPlanetary Wayback) - IPFS-based web archives
8. Newspaper3k - Article extraction
9. Readability - Content extraction

The scraper automatically tries each method in sequence until successful,
making it resilient to various failure scenarios.
"""

import logging
import anyio
import glob
import os
import re
import time
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Dict, List, Optional, Any, Literal, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from urllib.parse import urlparse, urljoin
import hashlib

logger = logging.getLogger(__name__)


class ScraperMethod(Enum):
    """Available scraping methods."""
    PLAYWRIGHT = "playwright"
    BEAUTIFULSOUP = "beautifulsoup"
    WAYBACK_MACHINE = "wayback_machine"
    COMMON_CRAWL = "common_crawl"
    ARCHIVE_IS = "archive_is"
    CLOUDFLARE_BROWSER_RENDERING = "cloudflare_browser_rendering"
    IPWB = "ipwb"
    NEWSPAPER = "newspaper"
    READABILITY = "readability"
    REQUESTS_ONLY = "requests_only"


@dataclass
class ScraperResult:
    """Result from a web scraping operation."""
    url: str
    content: str = ""
    html: str = ""
    title: str = ""
    text: str = ""
    links: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    method_used: Optional[ScraperMethod] = None
    success: bool = False
    errors: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    extraction_time: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "content": self.content,
            "html": self.html,
            "title": self.title,
            "text": self.text,
            "links": self.links,
            "metadata": self.metadata,
            "method_used": self.method_used.value if self.method_used else None,
            "success": self.success,
            "errors": self.errors,
            "timestamp": self.timestamp,
            "extraction_time": self.extraction_time
        }


@dataclass
class ScraperConfig:
    """Configuration for the unified scraper."""
    timeout: int = 30
    user_agent: str = "IPFS-Datasets-UnifiedScraper/1.0"
    max_retries: int = 3
    retry_delay: float = 1.0
    playwright_headless: bool = True
    playwright_wait_for: str = "networkidle"
    playwright_hydration_wait_ms: int = 3000
    playwright_shell_retry_wait_ms: int = 9000
    extract_links: bool = True
    extract_text: bool = True
    follow_redirects: bool = True
    verify_ssl: bool = True
    retry_insecure_ssl: bool = True
    rate_limit_delay: float = 1.0
    preferred_methods: Optional[List[ScraperMethod]] = None
    fallback_enabled: bool = True
    archive_is_submit_on_miss: bool = True
    archive_is_submit_wait: bool = False
    archive_is_submit_retries: int = 2
    archive_is_submit_backoff_seconds: float = 2.0
    cloudflare_account_id: Optional[str] = None
    cloudflare_api_token: Optional[str] = None
    cloudflare_timeout_seconds: int = 120
    cloudflare_poll_interval_seconds: float = 2.0
    cloudflare_limit: int = 1
    cloudflare_depth: int = 0
    cloudflare_render: bool = False
    cloudflare_source: str = "all"
    cloudflare_formats: Optional[List[str]] = None
    cloudflare_include_external_links: bool = False
    cloudflare_include_subdomains: bool = False

    # Common Crawl (via local common_crawl_search_engine) configuration.
    # Defaults match common_crawl_search_engine.ccindex.api.search_domain_via_meta_indexes().
    common_crawl_parquet_root: Optional[str] = None
    common_crawl_master_db: Optional[str] = None
    common_crawl_year_db: Optional[str] = None
    common_crawl_collection_db: Optional[str] = None
    common_crawl_year: Optional[str] = None
    # Prefer HF remote SQL/row-group search by default, then fallback to local disk indexes.
    common_crawl_hf_remote_meta: Optional[bool] = True
    common_crawl_hf_meta_index_dataset: Optional[str] = None
    common_crawl_hf_pointer_dataset: Optional[str] = None
    common_crawl_hf_revision: Optional[str] = None
    common_crawl_hf_retry_attempts: int = 3
    common_crawl_hf_retry_backoff_seconds: float = 2.0
    common_crawl_max_matches: int = 25
    common_crawl_max_parquet_files: int = 200
    common_crawl_per_parquet_limit: int = 2000
    common_crawl_prefix: str = "https://data.commoncrawl.org/"
    common_crawl_fetch_max_bytes: int = 2_000_000
    common_crawl_cache_mode: str = "range"
    common_crawl_prefer_exact_url: bool = True
    # Optimization: coalesce many per-record Range GETs into fewer larger slice GETs.
    # These are byte sizes on the remote WARC file.
    common_crawl_slice_max_bytes: int = 64_000_000
    common_crawl_slice_gap_bytes: int = 1_000_000
    common_crawl_slice_min_bytes: int = 1_000_000
    common_crawl_slice_workers: int = 8
    common_crawl_warc_workers: int = 8
    
    def __post_init__(self):
        """Set default preferred methods if not specified."""
        if self.preferred_methods is None:
            self.preferred_methods = [
                # Prefer archive-based sources first to reduce origin fetches (e.g. Cloudflare).
                ScraperMethod.COMMON_CRAWL,
                ScraperMethod.PLAYWRIGHT,
                ScraperMethod.BEAUTIFULSOUP,
                ScraperMethod.WAYBACK_MACHINE,
                ScraperMethod.ARCHIVE_IS,
                ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
                ScraperMethod.IPWB,
                ScraperMethod.NEWSPAPER,
                ScraperMethod.READABILITY,
                ScraperMethod.REQUESTS_ONLY
            ]


class UnifiedWebScraper:
    """
    Unified web scraping system with intelligent fallback mechanisms.
    
    This class provides a single interface for all web scraping needs, automatically
    trying multiple methods in sequence until successful. It consolidates all scraping
    logic from across the codebase into one reusable component.
    """
    
    def __init__(self, config: Optional[ScraperConfig] = None):
        """
        Initialize the unified scraper.
        """
        self.config = config or ScraperConfig()
        self._apply_env_overrides()
        self._check_dependencies()
        self._init_session()
    
    def _check_dependencies(self):
        """Check which scraping libraries are available."""
        self.available_methods = {}
        
        # Check Playwright
        try:
            from playwright.async_api import async_playwright
            self.available_methods[ScraperMethod.PLAYWRIGHT] = True
        except ImportError:
            self.available_methods[ScraperMethod.PLAYWRIGHT] = False
            logger.debug("Playwright not available")
        
        # Check BeautifulSoup + requests
        try:
            from bs4 import BeautifulSoup
            import requests
            self.available_methods[ScraperMethod.BEAUTIFULSOUP] = True
        except ImportError:
            self.available_methods[ScraperMethod.BEAUTIFULSOUP] = False
            logger.debug("BeautifulSoup or requests not available")
        
        # Check Wayback Machine
        try:
            from wayback import WaybackClient
            self.available_methods[ScraperMethod.WAYBACK_MACHINE] = True
        except ImportError:
            self.available_methods[ScraperMethod.WAYBACK_MACHINE] = False
            logger.debug("Wayback library not available")
        
        # Check Common Crawl
        try:
            # Prefer local common_crawl_search_engine integration when available.
            from common_crawl_search_engine.ccindex import api as _ccapi  # noqa: F401
            self.available_methods[ScraperMethod.COMMON_CRAWL] = True
        except ImportError:
            try:
                from cdx_toolkit import CDXFetcher  # noqa: F401
                self.available_methods[ScraperMethod.COMMON_CRAWL] = True
            except ImportError:
                self.available_methods[ScraperMethod.COMMON_CRAWL] = False
                logger.debug("Common Crawl integration not available")
        
        # Check Archive.is (requires requests)
        try:
            import requests
            self.available_methods[ScraperMethod.ARCHIVE_IS] = True
        except ImportError:
            self.available_methods[ScraperMethod.ARCHIVE_IS] = False

        # Check Cloudflare Browser Rendering crawl endpoint.
        try:
            import requests  # noqa: F401
            account_id, api_token = self._resolve_cloudflare_credentials()
            self.available_methods[ScraperMethod.CLOUDFLARE_BROWSER_RENDERING] = bool(account_id and api_token)
            if not self.available_methods[ScraperMethod.CLOUDFLARE_BROWSER_RENDERING]:
                logger.debug("Cloudflare Browser Rendering credentials not configured")
        except ImportError:
            self.available_methods[ScraperMethod.CLOUDFLARE_BROWSER_RENDERING] = False
        
        # Check IPWB
        try:
            import ipwb
            self.available_methods[ScraperMethod.IPWB] = True
        except ImportError:
            self.available_methods[ScraperMethod.IPWB] = False
            logger.debug("IPWB not available")
        
        # Check Newspaper
        try:
            import newspaper
            self.available_methods[ScraperMethod.NEWSPAPER] = True
        except ImportError:
            self.available_methods[ScraperMethod.NEWSPAPER] = False
            logger.debug("Newspaper3k not available")
        
        # Check Readability
        try:
            from readability import Document
            self.available_methods[ScraperMethod.READABILITY] = True
        except ImportError:
            self.available_methods[ScraperMethod.READABILITY] = False
            logger.debug("Readability not available")
        
        # Requests-only is always available if requests is available
        try:
            import requests
            self.available_methods[ScraperMethod.REQUESTS_ONLY] = True
        except ImportError:
            self.available_methods[ScraperMethod.REQUESTS_ONLY] = False
    
    def _init_session(self):
        """Initialize HTTP session."""
        try:
            import requests
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': self.config.user_agent})
        except ImportError:
            self.session = None

    @staticmethod
    def _env_bool(*names: str) -> Optional[bool]:
        """Parse the first present boolean-like environment variable."""
        for name in names:
            raw = (os.environ.get(name) or "").strip().lower()
            if not raw:
                continue
            if raw in {"1", "true", "yes", "on"}:
                return True
            if raw in {"0", "false", "no", "off"}:
                return False
        return None

    @staticmethod
    def _env_list(*names: str) -> List[str]:
        """Parse the first present comma-separated environment variable."""
        for name in names:
            raw = str(os.environ.get(name) or "").strip()
            if not raw:
                continue
            values = [item.strip() for item in raw.split(",") if item.strip()]
            if values:
                return values
        return []

    @staticmethod
    def _env_int(*names: str) -> Optional[int]:
        for name in names:
            raw = str(os.environ.get(name) or "").strip()
            if not raw:
                continue
            try:
                return int(raw)
            except ValueError:
                continue
        return None

    @staticmethod
    def _env_float(*names: str) -> Optional[float]:
        for name in names:
            raw = str(os.environ.get(name) or "").strip()
            if not raw:
                continue
            try:
                return float(raw)
            except ValueError:
                continue
        return None

    @staticmethod
    def _env_str(*names: str) -> Optional[str]:
        for name in names:
            raw = str(os.environ.get(name) or "").strip()
            if raw:
                return raw
        return None

    @classmethod
    def _parse_method_names(cls, names: List[str]) -> List[ScraperMethod]:
        aliases = {
            "bs4": ScraperMethod.BEAUTIFULSOUP,
            "beautifulsoup4": ScraperMethod.BEAUTIFULSOUP,
            "beautifulsoup": ScraperMethod.BEAUTIFULSOUP,
            "wayback": ScraperMethod.WAYBACK_MACHINE,
            "commoncrawl": ScraperMethod.COMMON_CRAWL,
            "archiveis": ScraperMethod.ARCHIVE_IS,
            "cloudflare": ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
            "browser_rendering": ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
            "requests": ScraperMethod.REQUESTS_ONLY,
        }
        parsed: List[ScraperMethod] = []
        seen: set[ScraperMethod] = set()
        for raw_name in names:
            key = str(raw_name or "").strip().lower()
            if not key:
                continue
            method = aliases.get(key)
            if method is None:
                try:
                    method = ScraperMethod(key)
                except ValueError:
                    continue
            if method not in seen:
                parsed.append(method)
                seen.add(method)
        return parsed

    def _apply_env_overrides(self) -> None:
        preferred_method_names = self._env_list(
            "IPFS_DATASETS_SCRAPER_METHOD_ORDER",
            "IPFS_DATASETS_WEB_SCRAPER_METHOD_ORDER",
            "LEGAL_SCRAPER_METHOD_ORDER",
        )
        preferred_methods = self._parse_method_names(preferred_method_names)
        if preferred_methods:
            self.config.preferred_methods = preferred_methods

        fallback_enabled = self._env_bool(
            "IPFS_DATASETS_SCRAPER_FALLBACK_ENABLED",
            "LEGAL_SCRAPER_FALLBACK_ENABLED",
        )
        if fallback_enabled is not None:
            self.config.fallback_enabled = fallback_enabled

        archive_submit_on_miss = self._env_bool(
            "IPFS_DATASETS_ARCHIVE_IS_SUBMIT_ON_MISS",
            "LEGAL_SCRAPER_ARCHIVE_IS_SUBMIT_ON_MISS",
        )
        if archive_submit_on_miss is not None:
            self.config.archive_is_submit_on_miss = archive_submit_on_miss

        archive_submit_wait = self._env_bool(
            "IPFS_DATASETS_ARCHIVE_IS_SUBMIT_WAIT",
            "LEGAL_SCRAPER_ARCHIVE_IS_SUBMIT_WAIT",
        )
        if archive_submit_wait is not None:
            self.config.archive_is_submit_wait = archive_submit_wait

        cloudflare_timeout = self._env_int(
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_TIMEOUT_SECONDS",
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_TIMEOUT_SECONDS",
        )
        if cloudflare_timeout is not None and cloudflare_timeout > 0:
            self.config.cloudflare_timeout_seconds = cloudflare_timeout

        cloudflare_poll_interval = self._env_float(
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_POLL_INTERVAL_SECONDS",
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_POLL_INTERVAL_SECONDS",
        )
        if cloudflare_poll_interval is not None and cloudflare_poll_interval > 0:
            self.config.cloudflare_poll_interval_seconds = cloudflare_poll_interval

        cloudflare_limit = self._env_int(
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_LIMIT",
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_LIMIT",
        )
        if cloudflare_limit is not None and cloudflare_limit > 0:
            self.config.cloudflare_limit = cloudflare_limit

        cloudflare_depth = self._env_int(
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_DEPTH",
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_DEPTH",
        )
        if cloudflare_depth is not None and cloudflare_depth >= 0:
            self.config.cloudflare_depth = cloudflare_depth

        cloudflare_render = self._env_bool(
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_RENDER",
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_RENDER",
        )
        if cloudflare_render is not None:
            self.config.cloudflare_render = cloudflare_render

        cloudflare_source = self._env_str(
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_SOURCE",
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_SOURCE",
        )
        if cloudflare_source:
            self.config.cloudflare_source = cloudflare_source

        cloudflare_formats = self._env_list(
            "IPFS_DATASETS_CLOUDFLARE_CRAWL_FORMATS",
            "LEGAL_SCRAPER_CLOUDFLARE_CRAWL_FORMATS",
        )
        if cloudflare_formats:
            self.config.cloudflare_formats = cloudflare_formats

    def _resolve_cloudflare_credentials(self) -> tuple[Optional[str], Optional[str]]:
        account_id = (
            self.config.cloudflare_account_id
            or self._env_str(
                "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
                "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
                "CLOUDFLARE_ACCOUNT_ID",
            )
            or ""
        ).strip() or None
        api_token = (
            self.config.cloudflare_api_token
            or self._env_str(
                "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
                "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
                "CLOUDFLARE_API_TOKEN",
            )
            or ""
        ).strip() or None
        return account_id, api_token

    @staticmethod
    def _existing_path(*candidates: Optional[Union[str, Path]], want_dir: bool = False, want_file: bool = False) -> Optional[Path]:
        """Return the first existing path from a candidate list."""
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if not path.exists():
                continue
            if want_dir and not path.is_dir():
                continue
            if want_file and not path.is_file():
                continue
            return path.resolve()
        return None

    @staticmethod
    def _latest_matching_path(patterns: List[str]) -> Optional[Path]:
        """Pick the lexicographically latest existing path from glob patterns."""
        matches: List[Path] = []
        for pattern in patterns:
            if not pattern:
                continue
            matches.extend(Path(p) for p in glob.glob(pattern))
        if not matches:
            return None
        return sorted((p.expanduser().resolve() for p in matches if p.exists()), reverse=True)[0]

    def _resolve_common_crawl_search_options(self, *, max_matches: int) -> tuple[Dict[str, Any], str, bool]:
        """Resolve Common Crawl options with HF-remote-first policy and local fallback."""
        year = self.config.common_crawl_year or (os.environ.get("COMMON_CRAWL_YEAR") or "").strip() or None

        parquet_root = self._existing_path(
            self.config.common_crawl_parquet_root,
            os.environ.get("IPFS_DATASETS_PY_COMMON_CRAWL_PARQUET_ROOT"),
            os.environ.get("COMMON_CRAWL_PARQUET_ROOT"),
            os.environ.get("CCINDEX_PARQUET_ROOT"),
            "~/ccindex_storage/parquet",
            "/storage/ccindex_parquet",
            want_dir=True,
        )

        master_db = self._existing_path(
            self.config.common_crawl_master_db,
            os.environ.get("IPFS_DATASETS_PY_COMMON_CRAWL_MASTER_DB"),
            os.environ.get("COMMON_CRAWL_MASTER_DB"),
            os.environ.get("CCINDEX_MASTER_DB"),
            "~/ccindex_storage/duckdb/cc_pointers_master/cc_master_index.duckdb",
            "/storage/ccindex_duckdb/cc_pointers_master/cc_master_index.duckdb",
            want_file=True,
        )

        year_db = self._existing_path(
            self.config.common_crawl_year_db,
            os.environ.get("IPFS_DATASETS_PY_COMMON_CRAWL_YEAR_DB"),
            os.environ.get("COMMON_CRAWL_YEAR_DB"),
            os.environ.get("CCINDEX_YEAR_DB"),
            (f"~/ccindex_storage/duckdb/cc_pointers_by_year/{year}.duckdb" if year else None),
            want_file=True,
        )

        collection_db = self._existing_path(
            self.config.common_crawl_collection_db,
            os.environ.get("IPFS_DATASETS_PY_COMMON_CRAWL_COLLECTION_DB"),
            os.environ.get("COMMON_CRAWL_COLLECTION_DB"),
            os.environ.get("CCINDEX_COLLECTION_DB"),
            want_file=True,
        )
        if collection_db is None:
            collection_db = self._latest_matching_path([
                f"{Path('~/ccindex_storage/duckdb/cc_pointers_by_collection').expanduser()}/CC-MAIN-{year}-*.duckdb" if year else "",
                f"{Path('~/ccindex_storage/duckdb/cc_pointers_by_collection').expanduser()}/*.duckdb",
            ])

        meta_mode = "none"
        if master_db is not None:
            meta_mode = "master"
        elif year_db is not None:
            meta_mode = "year"
        elif collection_db is not None:
            meta_mode = "collection"

        hf_remote_meta = self.config.common_crawl_hf_remote_meta
        if hf_remote_meta is None:
            hf_remote_meta = self._env_bool(
                "IPFS_DATASETS_PY_COMMON_CRAWL_HF_REMOTE_META",
                "COMMON_CRAWL_HF_REMOTE_META",
                "HF_REMOTE_META",
            )
        if hf_remote_meta is None:
            hf_remote_meta = True
        hf_remote_requested = bool(hf_remote_meta)
        hf_remote_auto = False
        hf_remote_fallback_allowed = True

        search_options: Dict[str, Any] = {
            "parquet_root": parquet_root if parquet_root is not None else Path("/storage/ccindex_parquet"),
            "master_db": master_db,
            "year_db": year_db,
            "collection_db": collection_db,
            "year": year,
            "max_parquet_files": int(self.config.common_crawl_max_parquet_files),
            "max_matches": int(max_matches),
            "per_parquet_limit": int(self.config.common_crawl_per_parquet_limit),
        }

        if hf_remote_requested or hf_remote_auto:
            search_options.update(
                {
                    "hf_remote_meta": True,
                    "hf_meta_index_dataset": self.config.common_crawl_hf_meta_index_dataset
                    or os.environ.get("COMMON_CRAWL_HF_META_INDEX_DATASET")
                    or "Publicus/common_crawl_pointer_indices",
                    "hf_pointer_dataset": self.config.common_crawl_hf_pointer_dataset
                    or os.environ.get("COMMON_CRAWL_HF_POINTER_DATASET")
                    or "Publicus/common_crawl_pointers_by_collection",
                    "hf_revision": self.config.common_crawl_hf_revision
                    or os.environ.get("COMMON_CRAWL_HF_REVISION")
                    or "main",
                }
            )

        return search_options, meta_mode, hf_remote_fallback_allowed

    def _search_common_crawl_records(self, ccapi: Any, url: str, *, max_matches: int):
        """Search Common Crawl via HF remote first, then fallback to local disk indexes."""
        search_options, meta_mode, hf_remote_enabled = self._resolve_common_crawl_search_options(
            max_matches=max_matches
        )

        def _run(options: Dict[str, Any]):
            return ccapi.search_domain_via_meta_indexes(url, **options)

        def _is_hf_rate_limit_error(exc: Exception) -> bool:
            msg = str(exc).lower()
            return (
                " 429" in msg
                or "http 429" in msg
                or "too many requests" in msg
                or "rate limit" in msg
            )

        def _run_remote_with_backoff(options: Dict[str, Any]):
            attempts = max(1, int(self.config.common_crawl_hf_retry_attempts))
            backoff = max(0.0, float(self.config.common_crawl_hf_retry_backoff_seconds))
            last_exc: Optional[Exception] = None
            for attempt in range(1, attempts + 1):
                try:
                    return _run(options)
                except Exception as exc:
                    last_exc = exc
                    if attempt >= attempts or not _is_hf_rate_limit_error(exc):
                        raise
                    delay = backoff * attempt
                    logger.warning(
                        "Common Crawl HF remote rate-limited (attempt %s/%s); retrying in %.1fs",
                        attempt,
                        attempts,
                        delay,
                    )
                    time.sleep(delay)
            if last_exc is not None:
                raise last_exc
            raise RuntimeError("HF remote search retry loop exited unexpectedly")

        if bool(search_options.get("hf_remote_meta")):
            remote_options = dict(search_options)
            remote_options.update(
                {
                    "master_db": None,
                    "year_db": None,
                    "collection_db": None,
                    "hf_remote_meta": True,
                }
            )
            try:
                remote_result = _run_remote_with_backoff(remote_options)
                remote_records = list(getattr(remote_result, "records", []) or [])
                if remote_records or meta_mode == "none":
                    return remote_result, True
            except Exception as remote_error:
                if meta_mode == "none":
                    raise
                logger.warning("Common Crawl HF remote search failed; falling back to local indexes: %s", remote_error)

        local_options = dict(search_options)
        local_options.update({"hf_remote_meta": False})

        try:
            result = _run(local_options)
        except (FileNotFoundError, ValueError):
            if not hf_remote_enabled:
                raise
            remote_options = dict(local_options)
            remote_options.update(
                {
                    "master_db": None,
                    "year_db": None,
                    "collection_db": None,
                    "hf_remote_meta": True,
                }
            )
            return _run_remote_with_backoff(remote_options), True

        if meta_mode == "collection" and hf_remote_enabled and not list(getattr(result, "records", []) or []):
            remote_options = dict(local_options)
            remote_options.update(
                {
                    "master_db": None,
                    "year_db": None,
                    "collection_db": None,
                    "hf_remote_meta": True,
                }
            )
            return _run_remote_with_backoff(remote_options), True

        return result, bool(search_options.get("hf_remote_meta"))

    @staticmethod
    def _ssl_retry_allowed(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            token in message
            for token in [
                "ssl",
                "certificate verify failed",
                "certificate_verify_failed",
                "cert verify failed",
            ]
        )

    @staticmethod
    def _content_type_matches(content_type: str, *tokens: str) -> bool:
        lowered = (content_type or "").lower()
        return any(token in lowered for token in tokens)

    @staticmethod
    def _response_filename(url: str, content_disposition: str) -> str:
        match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', content_disposition or "", re.IGNORECASE)
        if match:
            return os.path.basename(match.group(1).strip())
        parsed = urlparse(url)
        return os.path.basename(parsed.path.rstrip("/")) or parsed.netloc or url

    def _is_binary_document_response(self, *, url: str, content_type: str, content_disposition: str) -> bool:
        haystack = f"{url} {content_type} {content_disposition}".lower()
        binary_tokens = [
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument",
            "application/vnd.ms-excel",
            "application/vnd.ms-powerpoint",
            "application/octet-stream",
        ]
        if any(token in haystack for token in binary_tokens):
            return True
        return "attachment" in (content_disposition or "").lower()

    @staticmethod
    async def _extract_pdf_text(pdf_bytes: bytes) -> str:
        if not pdf_bytes:
            return ""
        temp_path: Optional[Path] = None
        try:
            from ipfs_datasets_py.processors.specialized.pdf import PDFProcessor

            with NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(pdf_bytes)
                temp_path = Path(handle.name)

            processor = PDFProcessor()
            decomposed_content = await processor._decompose_pdf(temp_path)

            text_parts: List[str] = []
            for page_data in decomposed_content.get("pages") or []:
                text_blocks = page_data.get("text_blocks") or []
                try:
                    page_text = processor._extract_native_text(text_blocks)
                except Exception:
                    page_text = ""
                page_text = str(page_text or "").strip()
                if page_text:
                    text_parts.append(page_text)

            if text_parts:
                return "\n\n".join(text_parts).strip()

            try:
                ocr_results = await processor._process_ocr(decomposed_content)
            except Exception:
                ocr_results = {}

            for page_ocr in (ocr_results or {}).values():
                for image_result in page_ocr or []:
                    ocr_text = str((image_result or {}).get("text") or "").strip()
                    if ocr_text:
                        text_parts.append(ocr_text)

            return "\n\n".join(text_parts).strip()
        except Exception:
            return ""
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    async def _build_binary_document_result(
        self,
        *,
        url: str,
        response: Any,
        method: ScraperMethod,
        ssl_verification_relaxed: bool,
    ) -> ScraperResult:
        content_type = response.headers.get("Content-Type", "")
        content_disposition = response.headers.get("Content-Disposition", "")
        raw_bytes = bytes(response.content or b"")
        filename = self._response_filename(url, content_disposition)
        text = ""
        if self._content_type_matches(content_type, "application/pdf") or url.lower().endswith(".pdf"):
            text = await self._extract_pdf_text(raw_bytes)

        return ScraperResult(
            url=url,
            title=filename,
            text=text,
            content=text,
            method_used=method,
            success=bool(raw_bytes),
            metadata={
                "method": method.value,
                "status_code": getattr(response, "status_code", None),
                "content_type": content_type,
                "content_disposition": content_disposition,
                "content_length": len(raw_bytes),
                "raw_bytes": raw_bytes,
                "binary_document": True,
                "ssl_verification_relaxed": ssl_verification_relaxed,
            },
            errors=[] if raw_bytes else ["Binary document response was empty"],
        )

    def _request_with_ssl_fallback(self, url: str, **kwargs) -> tuple[Any, bool]:
        verify = kwargs.pop("verify", self.config.verify_ssl)
        try:
            return self.session.get(url, verify=verify, **kwargs), False
        except Exception as exc:
            if not verify or not self.config.retry_insecure_ssl or not self._ssl_retry_allowed(exc):
                raise
            logger.info("Retrying %s without SSL verification after %s", url, type(exc).__name__)
            return self.session.get(url, verify=False, **kwargs), True
    
    async def scrape(
        self,
        url: str,
        method: Optional[ScraperMethod] = None,
        **kwargs
    ) -> ScraperResult:
        """
        Scrape a URL using the specified method or automatic fallback.
        
        Args:
            url: URL to scrape
            method: Specific method to use. If None, tries all available methods.
            **kwargs: Additional method-specific arguments
        
        Returns:
            ScraperResult with scraped content and metadata
        """
        start_time = time.time()
        
        if method:
            # Use specific method
            result = await self._scrape_with_method(url, method, **kwargs)
        elif self.config.fallback_enabled:
            # Try methods in order of preference
            result = await self._scrape_with_fallback(url, **kwargs)
        else:
            # Try preferred method only
            preferred = self.config.preferred_methods[0] if self.config.preferred_methods else ScraperMethod.BEAUTIFULSOUP
            result = await self._scrape_with_method(url, preferred, **kwargs)
        
        result.extraction_time = time.time() - start_time
        return result
    
    async def _scrape_with_fallback(self, url: str, **kwargs) -> ScraperResult:
        """Try multiple scraping methods in sequence until one succeeds."""
        errors = []
        archive_snapshot_miss = False
        
        for method in self.config.preferred_methods:
            if not self.available_methods.get(method, False):
                continue
            
            try:
                logger.info(f"Trying {method.value} for {url}")
                result = await self._scrape_with_method(url, method, **kwargs)

                if result is None:
                    error_msg = f"{method.value} returned no result"
                    errors.append(error_msg)
                    logger.warning(error_msg)
                    continue
                
                if result.success:
                    logger.info(f"Successfully scraped {url} using {method.value}")
                    return result
                else:
                    if (
                        method == ScraperMethod.ARCHIVE_IS
                        and "Archive.is returned no archived snapshot" in (getattr(result, "errors", []) or [])
                    ):
                        archive_snapshot_miss = True
                    errors.extend(result.errors)
            
            except Exception as e:
                error_msg = f"{method.value} failed: {str(e)}"
                errors.append(error_msg)
                logger.warning(error_msg)
            
            # Rate limiting between attempts
            await anyio.sleep(self.config.rate_limit_delay)

        if archive_snapshot_miss and self.config.archive_is_submit_on_miss:
            try:
                logger.info("Submitting %s to Archive.is as final fallback", url)
                result = await self._scrape_archive_is(url, submit_on_miss=True, **kwargs)
                if result.success:
                    return result
                errors.extend(getattr(result, "errors", []) or [])
            except Exception as exc:
                errors.append(f"archive_is submission failed: {type(exc).__name__}: {exc}")
        
        # All methods failed
        return ScraperResult(
            url=url,
            success=False,
            errors=errors or ["No scraping methods available"]
        )
    
    async def _scrape_with_method(
        self,
        url: str,
        method: ScraperMethod,
        **kwargs
    ) -> ScraperResult:
        """Scrape using a specific method."""
        if not self.available_methods.get(method, False):
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"Method {method.value} not available"]
            )
        
        try:
            if method == ScraperMethod.PLAYWRIGHT:
                return await self._scrape_playwright(url, **kwargs)
            elif method == ScraperMethod.BEAUTIFULSOUP:
                return await self._scrape_beautifulsoup(url, **kwargs)
            elif method == ScraperMethod.WAYBACK_MACHINE:
                return await self._scrape_wayback(url, **kwargs)
            elif method == ScraperMethod.COMMON_CRAWL:
                return await self._scrape_common_crawl(url, **kwargs)
            elif method == ScraperMethod.ARCHIVE_IS:
                return await self._scrape_archive_is(url, **kwargs)
            elif method == ScraperMethod.CLOUDFLARE_BROWSER_RENDERING:
                return await self._scrape_cloudflare_browser_rendering(url, **kwargs)
            elif method == ScraperMethod.IPWB:
                return await self._scrape_ipwb(url, **kwargs)
            elif method == ScraperMethod.NEWSPAPER:
                return await self._scrape_newspaper(url, **kwargs)
            elif method == ScraperMethod.READABILITY:
                return await self._scrape_readability(url, **kwargs)
            elif method == ScraperMethod.REQUESTS_ONLY:
                return await self._scrape_requests_only(url, **kwargs)
            else:
                return ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"Unknown method: {method.value}"]
                )
        except Exception as e:
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"{method.value} error: {str(e)}"],
                method_used=method
            )
    
    async def _scrape_playwright(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Playwright for JavaScript-rendered content."""
        from playwright.async_api import async_playwright
        from bs4 import BeautifulSoup

        browser_user_agent = self.config.user_agent
        if browser_user_agent == "IPFS-Datasets-UnifiedScraper/1.0":
            browser_user_agent = (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )

        async def _read_live_dom(page: Any) -> tuple[str, List[Dict[str, str]]]:
            body_text = ""
            if self.config.extract_text:
                try:
                    body_text = await page.locator("body").inner_text()
                except Exception:
                    body_text = ""

            dom_links: List[Dict[str, str]] = []
            if self.config.extract_links:
                try:
                    raw_links = await page.locator("a").evaluate_all(
                        """
                        (els) => els.map((a) => ({
                            href: a.href || '',
                            text: (a.innerText || a.textContent || '').trim(),
                        }))
                        """
                    )
                except Exception:
                    raw_links = []
                for link in raw_links or []:
                    if not isinstance(link, dict):
                        continue
                    href = str(link.get("href") or "").strip()
                    if not href:
                        continue
                    dom_links.append({
                        "url": href,
                        "text": str(link.get("text") or "").strip(),
                    })
            return body_text, dom_links
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.config.playwright_headless)
            context = await browser.new_context(
                user_agent=browser_user_agent,
                locale="en-US",
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()
            
            try:
                # SPAs on state code hosts often return an initial shell before client-side
                # hydration fills in the real body text and links.
                await page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout * 1000)
                try:
                    await page.wait_for_load_state(self.config.playwright_wait_for, timeout=min(5000, self.config.timeout * 1000))
                except Exception:
                    pass
                if self.config.playwright_hydration_wait_ms > 0:
                    await page.wait_for_timeout(self.config.playwright_hydration_wait_ms)

                text, links = await _read_live_dom(page)
                shell_like = (
                    (not text.strip())
                    or "you need to enable javascript to run this app" in text.lower()
                    or (self.config.extract_links and not links)
                )
                if shell_like and self.config.playwright_shell_retry_wait_ms > 0:
                    await page.wait_for_timeout(self.config.playwright_shell_retry_wait_ms)
                    text, links = await _read_live_dom(page)
                
                # Get content
                html = await page.content()
                title = await page.title()
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract text
                parsed_text = ""
                if self.config.extract_text:
                    for script in soup(["script", "style"]):
                        script.decompose()
                    parsed_text = soup.get_text(separator='\n', strip=True)
                if not text:
                    text = parsed_text
                
                # Extract links
                if self.config.extract_links and not links:
                    links = []
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if href.startswith('/'):
                            href = urljoin(url, href)
                        links.append({
                            'url': href,
                            'text': link.get_text(strip=True)
                        })
                
                return ScraperResult(
                    url=url,
                    html=html,
                    title=title,
                    text=text,
                    content=text,
                    links=links,
                    method_used=ScraperMethod.PLAYWRIGHT,
                    success=True,
                    metadata={
                        'method': 'playwright',
                        'content_length': len(html)
                    }
                )
            
            finally:
                await context.close()
                await browser.close()
    
    async def _scrape_beautifulsoup(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using BeautifulSoup + requests."""
        from bs4 import BeautifulSoup
        
        response, ssl_relaxed = self._request_with_ssl_fallback(
            url,
            timeout=self.config.timeout,
            allow_redirects=self.config.follow_redirects
        )
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '')
        content_disposition = response.headers.get('Content-Disposition', '')
        if self._is_binary_document_response(
            url=url,
            content_type=content_type,
            content_disposition=content_disposition,
        ):
            return await self._build_binary_document_result(
                url=url,
                response=response,
                method=ScraperMethod.BEAUTIFULSOUP,
                ssl_verification_relaxed=ssl_relaxed,
            )
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Extract title
        title_tag = soup.find('title')
        title = title_tag.get_text() if title_tag else ""
        
        # Extract text
        text = ""
        if self.config.extract_text:
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator='\n', strip=True)
        
        # Extract links
        links = []
        if self.config.extract_links:
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.startswith('/'):
                    href = urljoin(url, href)
                links.append({
                    'url': href,
                    'text': link.get_text(strip=True)
                })
        
        return ScraperResult(
            url=url,
            html=response.text,
            title=title,
            text=text,
            content=text,
            links=links,
            method_used=ScraperMethod.BEAUTIFULSOUP,
            success=True,
            metadata={
                'method': 'beautifulsoup',
                'status_code': response.status_code,
                'content_type': response.headers.get('Content-Type', ''),
                'content_length': len(response.content),
                'ssl_verification_relaxed': ssl_relaxed,
            }
        )
    
    async def _scrape_wayback(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Wayback Machine."""
        from wayback import WaybackClient
        from bs4 import BeautifulSoup
        import requests
        
        client = WaybackClient()
        
        # Get most recent capture
        try:
            capture = next(client.search(url, limit=1))
            archive_url = capture.archive_url
            
            # Fetch archived content
            response = requests.get(archive_url, timeout=self.config.timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract data
            title = soup.find('title')
            title_text = title.get_text() if title else ""
            
            text = ""
            if self.config.extract_text:
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text(separator='\n', strip=True)
            
            return ScraperResult(
                url=url,
                html=response.text,
                title=title_text,
                text=text,
                content=text,
                method_used=ScraperMethod.WAYBACK_MACHINE,
                success=True,
                metadata={
                    'method': 'wayback_machine',
                    'archive_url': archive_url,
                    'timestamp': capture.timestamp.isoformat(),
                    'original_url': capture.original_url
                }
            )
        except StopIteration:
            return ScraperResult(
                url=url,
                success=False,
                errors=["No Wayback Machine captures found for this URL"]
            )
    
    async def _scrape_common_crawl(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Common Crawl."""
        # Preferred path: use local common_crawl_search_engine for both pointer discovery
        # and record fetching + HTTP extraction.
        try:
            from common_crawl_search_engine.ccindex import api as ccapi
            have_cc_engine = True
        except Exception:
            have_cc_engine = False

        if have_cc_engine:
            try:
                res, _used_hf_remote = self._search_common_crawl_records(
                    ccapi,
                    url,
                    max_matches=int(self.config.common_crawl_max_matches),
                )

                records = list(getattr(res, "records", []) or [])
                if not records:
                    return ScraperResult(url=url, success=False, errors=["No Common Crawl records for domain"])

                chosen = None
                if self.config.common_crawl_prefer_exact_url:
                    for r in records:
                        if str(r.get("url") or "") == str(url):
                            chosen = r
                            break
                if chosen is None:
                    chosen = records[0]

                wf = chosen.get("warc_filename")
                off = chosen.get("warc_offset")
                ln = chosen.get("warc_length")
                if not wf or off is None or ln is None:
                    return ScraperResult(
                        url=url,
                        success=False,
                        errors=["Common Crawl pointer missing warc_filename/offset/length"],
                        method_used=ScraperMethod.COMMON_CRAWL,
                        metadata={"record": chosen},
                    )

                fetch, source, local_path = ccapi.fetch_warc_record(
                    warc_filename=str(wf),
                    warc_offset=int(off),
                    warc_length=int(ln),
                    prefix=str(self.config.common_crawl_prefix),
                    timeout_s=float(self.config.timeout),
                    max_bytes=int(self.config.common_crawl_fetch_max_bytes),
                    decode_gzip_text=False,
                    cache_mode=str(self.config.common_crawl_cache_mode),
                )

                if not getattr(fetch, "ok", False) or not getattr(fetch, "raw_base64", None):
                    return ScraperResult(
                        url=url,
                        success=False,
                        errors=[str(getattr(fetch, "error", None) or "fetch_warc_record failed")],
                        method_used=ScraperMethod.COMMON_CRAWL,
                        metadata={"record": chosen, "source": source, "local_path": local_path},
                    )

                import base64

                gz_bytes = base64.b64decode(fetch.raw_base64)
                http = ccapi.extract_http_from_warc_gzip_member(
                    gz_bytes,
                    max_body_bytes=int(self.config.common_crawl_fetch_max_bytes),
                    max_preview_chars=200_000,
                )

                html = http.body_text_preview or ""
                title = ""
                text = ""
                links = []
                if html and (http.body_is_html or (http.body_mime or "").startswith("text/html")):
                    try:
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(html, "html.parser")
                        title_tag = soup.find("title")
                        title = title_tag.get_text() if title_tag else ""
                        if self.config.extract_text:
                            for script in soup(["script", "style"]):
                                script.decompose()
                            text = soup.get_text(separator="\n", strip=True)
                        if self.config.extract_links:
                            for link in soup.find_all("a", href=True):
                                href = link.get("href")
                                if not href:
                                    continue
                                if href.startswith("/"):
                                    href = urljoin(url, href)
                                links.append({"url": href, "text": link.get_text(strip=True)})
                    except Exception:
                        pass

                return ScraperResult(
                    url=url,
                    html=html,
                    title=title,
                    text=text,
                    content=text or html,
                    links=links,
                    method_used=ScraperMethod.COMMON_CRAWL,
                    success=True,
                    metadata={
                        "method": "common_crawl_search_engine",
                        "cc_record": chosen,
                        "cc_source": source,
                        "cc_local_warc_path": local_path,
                        "http_status": http.http_status,
                        "http_mime": http.body_mime,
                        "content_type": http.body_mime,
                        "http_charset": http.body_charset,
                        "ok": http.ok,
                        "error": http.error,
                    },
                )
            except Exception as e:
                return ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"common_crawl_search_engine error: {type(e).__name__}: {e}"],
                    method_used=ScraperMethod.COMMON_CRAWL,
                )

        # Fallback: if cdx_toolkit is available, keep prior behavior (metadata-only).
        try:
            from cdx_toolkit import CDXFetcher

            cdx = CDXFetcher(source='cc')
            record = next(cdx.iter(url=url, limit=1))
            return ScraperResult(
                url=url,
                success=True,
                method_used=ScraperMethod.COMMON_CRAWL,
                metadata={
                    'method': 'cdx_toolkit',
                    'timestamp': record.data.get('timestamp', ''),
                    'mime_type': record.data.get('mime', ''),
                    'status_code': record.data.get('status', ''),
                    'warc_filename': record.data.get('filename', ''),
                    'warc_offset': record.data.get('offset', ''),
                    'note': 'Metadata-only fallback; install common_crawl_search_engine for full content.'
                }
            )
        except Exception:
            return ScraperResult(
                url=url,
                success=False,
                errors=["Common Crawl integration unavailable"]
            )
    
    async def _scrape_archive_is(self, url: str, submit_on_miss: Optional[bool] = None, **kwargs) -> ScraperResult:
        """Scrape using Archive.is."""
        import requests
        from bs4 import BeautifulSoup

        if submit_on_miss is None:
            submit_on_miss = False
        
        # Try to find existing archive first
        search_url = f"https://archive.is/newest/{url}"
        
        try:
            response = requests.get(search_url, timeout=self.config.timeout, allow_redirects=True)
            
            if response.status_code == 200 and 'archive.is' in response.url:
                soup = BeautifulSoup(response.content, 'html.parser')
                
                title = soup.find('title')
                title_text = title.get_text() if title else ""
                
                text = ""
                if self.config.extract_text:
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text(separator='\n', strip=True)
                
                return ScraperResult(
                    url=url,
                    html=response.text,
                    title=title_text,
                    text=text,
                    content=text,
                    method_used=ScraperMethod.ARCHIVE_IS,
                    success=True,
                    metadata={
                        'method': 'archive_is',
                        'archive_url': response.url,
                        'archive_lookup_only': not submit_on_miss,
                    }
                )
        except Exception as e:
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"Archive.is scraping failed: {str(e)}"]
            )

        if submit_on_miss:
            try:
                from .archive_is_engine import archive_to_archive_is

                attempts = max(1, int(self.config.archive_is_submit_retries))
                backoff = max(0.0, float(self.config.archive_is_submit_backoff_seconds))
                last_result: Dict[str, Any] = {}
                for attempt in range(attempts):
                    last_result = await archive_to_archive_is(
                        url,
                        wait_for_completion=bool(self.config.archive_is_submit_wait),
                        timeout=max(60, int(self.config.timeout)),
                    )
                    status = str(last_result.get("status") or "").lower()
                    if status == "success":
                        archive_url = str(last_result.get("archive_url") or "")
                        return ScraperResult(
                            url=url,
                            success=True,
                            method_used=ScraperMethod.ARCHIVE_IS,
                            metadata={
                                "method": "archive_is",
                                "archive_url": archive_url,
                                "archive_submitted": True,
                                "archive_submit_status": status,
                            },
                            content=archive_url,
                            text=archive_url,
                            title="Archive.is submission created",
                        )
                    if status == "pending":
                        return ScraperResult(
                            url=url,
                            success=False,
                            method_used=ScraperMethod.ARCHIVE_IS,
                            metadata={
                                "method": "archive_is",
                                "archive_submitted": True,
                                "archive_submit_status": status,
                                **last_result,
                            },
                            errors=["Archive.is capture submitted and is still pending"],
                        )
                    if attempt + 1 < attempts:
                        await anyio.sleep(backoff * (attempt + 1))
                return ScraperResult(
                    url=url,
                    success=False,
                    method_used=ScraperMethod.ARCHIVE_IS,
                    metadata={
                        "method": "archive_is",
                        "archive_submitted": bool(last_result),
                        **last_result,
                    },
                    errors=[str(last_result.get("error") or "Archive.is submission failed")],
                )
            except Exception as e:
                return ScraperResult(
                    url=url,
                    success=False,
                    method_used=ScraperMethod.ARCHIVE_IS,
                    errors=[f"Archive.is submission failed: {str(e)}"],
                )

        return ScraperResult(
            url=url,
            success=False,
            errors=["Archive.is returned no archived snapshot"]
        )

    async def _scrape_cloudflare_browser_rendering(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Cloudflare Browser Rendering crawl as a remote fallback."""
        from .cloudflare_browser_rendering_engine import crawl_with_cloudflare_browser_rendering

        account_id, api_token = self._resolve_cloudflare_credentials()
        if not account_id or not api_token:
            return ScraperResult(
                url=url,
                success=False,
                method_used=ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
                errors=["Cloudflare Browser Rendering credentials are not configured"],
            )

        formats = kwargs.get("cloudflare_formats") or self.config.cloudflare_formats or ["markdown", "html"]
        crawl_result = await crawl_with_cloudflare_browser_rendering(
            url,
            account_id=account_id,
            api_token=api_token,
            timeout_seconds=int(kwargs.get("cloudflare_timeout_seconds", self.config.cloudflare_timeout_seconds)),
            poll_interval_seconds=float(kwargs.get("cloudflare_poll_interval_seconds", self.config.cloudflare_poll_interval_seconds)),
            request_timeout_seconds=int(kwargs.get("cloudflare_request_timeout_seconds", self.config.timeout)),
            limit=int(kwargs.get("cloudflare_limit", self.config.cloudflare_limit)),
            depth=int(kwargs.get("cloudflare_depth", self.config.cloudflare_depth)),
            formats=formats,
            render=bool(kwargs.get("cloudflare_render", self.config.cloudflare_render)),
            source=str(kwargs.get("cloudflare_source", self.config.cloudflare_source)),
            include_external_links=bool(kwargs.get("cloudflare_include_external_links", self.config.cloudflare_include_external_links)),
            include_subdomains=bool(kwargs.get("cloudflare_include_subdomains", self.config.cloudflare_include_subdomains)),
            include_patterns=kwargs.get("cloudflare_include_patterns"),
            exclude_patterns=kwargs.get("cloudflare_exclude_patterns"),
            extra_body=kwargs.get("cloudflare_extra_body"),
        )

        if crawl_result.get("status") != "success":
            error = str(crawl_result.get("error") or f"Cloudflare crawl failed with status {crawl_result.get('status')}")
            return ScraperResult(
                url=url,
                success=False,
                method_used=ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
                errors=[error],
                metadata={
                    "method": "cloudflare_browser_rendering",
                    "cloudflare_status": crawl_result.get("status"),
                    "cloudflare_job_id": crawl_result.get("job_id"),
                },
            )

        records = list(crawl_result.get("records") or [])
        selected_record: Optional[Dict[str, Any]] = None
        normalized_url = url.rstrip("/")

        for record in records:
            if str(record.get("status") or "").lower() != "completed":
                continue
            record_url = str(record.get("url") or "").rstrip("/")
            if record_url == normalized_url:
                selected_record = record
                break
        if selected_record is None:
            for record in records:
                if str(record.get("status") or "").lower() == "completed":
                    selected_record = record
                    break
        if selected_record is None and records:
            selected_record = records[0]

        if not selected_record:
            return ScraperResult(
                url=url,
                success=False,
                method_used=ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
                errors=["Cloudflare crawl completed without returning any records"],
                metadata={
                    "method": "cloudflare_browser_rendering",
                    "cloudflare_job_id": crawl_result.get("job_id"),
                },
            )

        metadata = dict(selected_record.get("metadata") or {})
        html = str(selected_record.get("html") or "")
        text = str(selected_record.get("markdown") or "").strip()
        if not text and html and self.config.extract_text:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            text = soup.get_text(separator="\n", strip=True)

        title = str(metadata.get("title") or "").strip()
        record_status = str(selected_record.get("status") or "").strip().lower()
        success = record_status == "completed" and bool(text or html)
        errors = [] if success else [f"Cloudflare crawl record status: {record_status or 'unknown'}"]

        return ScraperResult(
            url=url,
            html=html,
            title=title,
            text=text,
            content=text or html,
            method_used=ScraperMethod.CLOUDFLARE_BROWSER_RENDERING,
            success=success,
            errors=errors,
            metadata={
                "method": "cloudflare_browser_rendering",
                "cloudflare_job_id": crawl_result.get("job_id"),
                "cloudflare_job_status": str((crawl_result.get("job") or {}).get("status") or ""),
                "cloudflare_record_status": record_status,
                "cloudflare_record_count": len(records),
                **metadata,
            },
        )
    
    async def _scrape_ipwb(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using IPWB (InterPlanetary Wayback)."""
        import ipwb
        
        # IPWB requires a local index
        # This is a placeholder for IPWB integration
        return ScraperResult(
            url=url,
            success=False,
            errors=["IPWB scraping requires a local CDXJ index"]
        )
    
    async def _scrape_newspaper(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Newspaper3k."""
        import newspaper
        
        article = newspaper.Article(url)
        article.download()
        article.parse()
        
        return ScraperResult(
            url=url,
            title=article.title or "",
            text=article.text or "",
            content=article.text or "",
            html=article.html or "",
            method_used=ScraperMethod.NEWSPAPER,
            success=True,
            metadata={
                'method': 'newspaper',
                'authors': article.authors,
                'publish_date': str(article.publish_date) if article.publish_date else None,
                'top_image': article.top_image
            }
        )
    
    async def _scrape_readability(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Readability."""
        from readability import Document
        from bs4 import BeautifulSoup
        
        response, ssl_relaxed = self._request_with_ssl_fallback(url, timeout=self.config.timeout)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '')
        content_disposition = response.headers.get('Content-Disposition', '')
        if self._is_binary_document_response(
            url=url,
            content_type=content_type,
            content_disposition=content_disposition,
        ):
            return await self._build_binary_document_result(
                url=url,
                response=response,
                method=ScraperMethod.READABILITY,
                ssl_verification_relaxed=ssl_relaxed,
            )
        
        doc = Document(response.content)
        title = doc.title()
        html_summary = doc.summary()
        
        soup = BeautifulSoup(html_summary, 'html.parser')
        text = soup.get_text(separator='\n', strip=True)
        
        return ScraperResult(
            url=url,
            title=title,
            html=html_summary,
            text=text,
            content=text,
            method_used=ScraperMethod.READABILITY,
            success=True,
            metadata={
                'method': 'readability',
                'content_length': len(response.content),
                'content_type': content_type,
                'ssl_verification_relaxed': ssl_relaxed,
            }
        )
    
    async def _scrape_requests_only(self, url: str, **kwargs) -> ScraperResult:
        """Basic scraping with requests only."""
        import re
        
        response, ssl_relaxed = self._request_with_ssl_fallback(url, timeout=self.config.timeout)
        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '')
        content_disposition = response.headers.get('Content-Disposition', '')
        if self._is_binary_document_response(
            url=url,
            content_type=content_type,
            content_disposition=content_disposition,
        ):
            return await self._build_binary_document_result(
                url=url,
                response=response,
                method=ScraperMethod.REQUESTS_ONLY,
                ssl_verification_relaxed=ssl_relaxed,
            )
        
        # Basic HTML tag removal
        text = re.sub(r'<[^>]+>', '', response.text)
        text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
        
        # Extract title
        title_match = re.search(r'<title[^>]*>([^<]+)</title>', response.text, re.IGNORECASE)
        title = title_match.group(1) if title_match else ""
        
        return ScraperResult(
            url=url,
            title=title,
            html=response.text,
            text=text,
            content=text,
            method_used=ScraperMethod.REQUESTS_ONLY,
            success=True,
            metadata={
                'method': 'requests_only',
                'status_code': response.status_code,
                'content_type': content_type,
                'ssl_verification_relaxed': ssl_relaxed,
            }
        )
    
    def scrape_sync(self, url: str, **kwargs) -> ScraperResult:
        """Synchronous version of scrape."""
        async def _runner() -> ScraperResult:
            return await self.scrape(url, **kwargs)

        try:
            result = anyio.run(_runner)
        except BaseException as exc:
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"scrape_sync interrupted: {type(exc).__name__}: {str(exc)}"],
            )

        if result is None:
            return ScraperResult(
                url=url,
                success=False,
                errors=["scrape_sync returned no result"],
            )
        return result

    async def scrape_domain(self, url: str, *, max_pages: Optional[int] = None, **kwargs) -> List[ScraperResult]:
        """Scrape a whole domain using Common Crawl first.

        This is intended for "domain-first" archival scraping to avoid origin blocking.
        Currently it only uses the local `common_crawl_search_engine` integration.

        Returns a list of ScraperResult objects (successful and/or failed).
        """

        # Only Common Crawl domain mode for now.
        max_pages_i = int(max_pages if max_pages is not None else self.config.common_crawl_max_matches)
        if max_pages_i <= 0:
            return []

        try:
            from common_crawl_search_engine.ccindex import api as ccapi
        except Exception as e:
            return [
                ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"common_crawl_search_engine unavailable: {type(e).__name__}: {e}"],
                    method_used=ScraperMethod.COMMON_CRAWL,
                )
            ]

        try:
            import base64
            from bs4 import BeautifulSoup

            res, _used_hf_remote = self._search_common_crawl_records(
                ccapi,
                url,
                max_matches=max_pages_i,
            )

            records = list(getattr(res, "records", []) or [])
            if not records:
                return [
                    ScraperResult(
                        url=url,
                        success=False,
                        errors=["No Common Crawl records for domain"],
                        method_used=ScraperMethod.COMMON_CRAWL,
                        metadata={"method": "common_crawl_search_engine"},
                    )
                ]

            results: List[ScraperResult] = []
            seen_urls = set()

            # Prefer an exact match for the requested URL (if configured), then continue.
            ordered_records = records
            if self.config.common_crawl_prefer_exact_url:
                exact = [r for r in records if str(r.get("url") or "") == str(url)]
                rest = [r for r in records if r not in exact]
                ordered_records = exact + rest

            # Build the list of unique pages to fetch first (preserving order).
            to_fetch: List[Dict[str, Any]] = []
            for r in ordered_records:
                if len(to_fetch) >= max_pages_i:
                    break
                page_url = str(r.get("url") or url)
                if page_url in seen_urls:
                    continue
                seen_urls.add(page_url)
                wf = r.get("warc_filename")
                off = r.get("warc_offset")
                ln = r.get("warc_length")
                if not wf or off is None or ln is None:
                    results.append(
                        ScraperResult(
                            url=page_url,
                            success=False,
                            errors=["Common Crawl pointer missing warc_filename/offset/length"],
                            method_used=ScraperMethod.COMMON_CRAWL,
                            metadata={"method": "common_crawl_search_engine", "cc_record": r},
                        )
                    )
                    continue
                to_fetch.append({"page_url": page_url, "cc_record": r, "wf": str(wf), "off": int(off), "ln": int(ln)})

            # Fetch in batches per WARC file using slice-range coalescing when available.
            bytes_by_key: Dict[tuple, bytes] = {}
            err_by_key: Dict[tuple, str] = {}
            try:
                batch_fn = getattr(ccapi, "fetch_warc_record_ranges_sliced", None)
            except Exception:
                batch_fn = None

            if callable(batch_fn):
                by_wf: Dict[str, List[tuple]] = {}
                for item in to_fetch:
                    by_wf.setdefault(item["wf"], []).append((item["off"], item["ln"]))

                # Fetch different WARC files in parallel (common case: 1 record per WARC).
                from concurrent.futures import ThreadPoolExecutor, as_completed

                def _fetch_wf(wf: str, ranges: List[tuple]):
                    return wf, batch_fn(
                        warc_filename=str(wf),
                        ranges=list(ranges),
                        prefix=str(self.config.common_crawl_prefix),
                        timeout_s=float(self.config.timeout),
                        max_slice_bytes=int(self.config.common_crawl_slice_max_bytes),
                        max_gap_bytes=int(self.config.common_crawl_slice_gap_bytes),
                        min_slice_bytes=int(self.config.common_crawl_slice_min_bytes),
                        max_workers=int(self.config.common_crawl_slice_workers),
                    )

                warc_workers = int(self.config.common_crawl_warc_workers)
                if warc_workers <= 1 or len(by_wf) <= 1:
                    items = [(_fetch_wf(wf, ranges)) for wf, ranges in by_wf.items()]
                else:
                    items = []
                    with ThreadPoolExecutor(max_workers=warc_workers) as ex:
                        futs = [ex.submit(_fetch_wf, wf, ranges) for wf, ranges in by_wf.items()]
                        for fut in as_completed(futs):
                            items.append(fut.result())

                for wf, (data_by, e_by) in items:
                    for (off, ln), blob in (data_by or {}).items():
                        bytes_by_key[(str(wf), int(off), int(ln))] = blob
                    for (off, ln), msg in (e_by or {}).items():
                        err_by_key[(str(wf), int(off), int(ln))] = str(msg)

            for item in to_fetch:
                page_url = item["page_url"]
                r = item["cc_record"]
                wf = item["wf"]
                off = item["off"]
                ln = item["ln"]

                gz_bytes: Optional[bytes] = None
                cc_source: Optional[str] = None
                cc_local_warc_path: Optional[str] = None
                k = (str(wf), int(off), int(ln))
                if k in bytes_by_key:
                    gz_bytes = bytes_by_key[k]
                    cc_source = "range_slice"
                elif k in err_by_key and not callable(batch_fn):
                    # shouldn't happen, but keep behavior sane.
                    cc_source = "range"

                if gz_bytes is None and callable(batch_fn):
                    # Slice mode ran but this specific range failed.
                    results.append(
                        ScraperResult(
                            url=page_url,
                            success=False,
                            errors=[err_by_key.get(k, "slice fetch failed")],
                            method_used=ScraperMethod.COMMON_CRAWL,
                            metadata={
                                "method": "common_crawl_search_engine",
                                "cc_record": r,
                                "cc_source": cc_source,
                                "cc_local_warc_path": cc_local_warc_path,
                            },
                        )
                    )
                    continue

                if gz_bytes is None:
                    fetch, source, local_path = ccapi.fetch_warc_record(
                        warc_filename=str(wf),
                        warc_offset=int(off),
                        warc_length=int(ln),
                        prefix=str(self.config.common_crawl_prefix),
                        timeout_s=float(self.config.timeout),
                        max_bytes=int(self.config.common_crawl_fetch_max_bytes),
                        decode_gzip_text=False,
                        cache_mode=str(self.config.common_crawl_cache_mode),
                    )

                    if not getattr(fetch, "ok", False) or not getattr(fetch, "raw_base64", None):
                        results.append(
                            ScraperResult(
                                url=page_url,
                                success=False,
                                errors=[str(getattr(fetch, "error", None) or "fetch_warc_record failed")],
                                method_used=ScraperMethod.COMMON_CRAWL,
                                metadata={
                                    "method": "common_crawl_search_engine",
                                    "cc_record": r,
                                    "cc_source": source,
                                    "cc_local_warc_path": local_path,
                                },
                            )
                        )
                        continue

                    gz_bytes = base64.b64decode(fetch.raw_base64)
                    cc_source = source
                    cc_local_warc_path = local_path

                http = ccapi.extract_http_from_warc_gzip_member(
                    gz_bytes,
                    max_body_bytes=int(self.config.common_crawl_fetch_max_bytes),
                    max_preview_chars=200_000,
                )

                html = http.body_text_preview or ""
                title = ""
                text = ""
                links: List[Dict[str, str]] = []
                if html and (http.body_is_html or (http.body_mime or "").startswith("text/html")):
                    try:
                        soup = BeautifulSoup(html, "html.parser")
                        title_tag = soup.find("title")
                        title = title_tag.get_text() if title_tag else ""
                        if self.config.extract_text:
                            for script in soup(["script", "style"]):
                                script.decompose()
                            text = soup.get_text(separator="\n", strip=True)
                        if self.config.extract_links:
                            for link in soup.find_all("a", href=True):
                                href = link.get("href")
                                if not href:
                                    continue
                                if href.startswith("/"):
                                    href = urljoin(page_url, href)
                                links.append({"url": href, "text": link.get_text(strip=True)})
                    except Exception:
                        pass

                results.append(
                    ScraperResult(
                        url=page_url,
                        html=html,
                        title=title,
                        text=text,
                        content=text or html,
                        links=links,
                        method_used=ScraperMethod.COMMON_CRAWL,
                        success=bool(html or text),
                        metadata={
                            "method": "common_crawl_search_engine",
                            "cc_record": r,
                            "cc_source": cc_source,
                            "cc_local_warc_path": cc_local_warc_path,
                            "http_status": http.http_status,
                            "http_mime": http.body_mime,
                            "http_charset": http.body_charset,
                            "ok": http.ok,
                            "error": http.error,
                        },
                    )
                )

            return results
        except Exception as e:
            return [
                ScraperResult(
                    url=url,
                    success=False,
                    errors=[f"common_crawl_search_engine domain error: {type(e).__name__}: {e}"],
                    method_used=ScraperMethod.COMMON_CRAWL,
                )
            ]

    def scrape_domain_sync(self, url: str, *, max_pages: Optional[int] = None, **kwargs) -> List[ScraperResult]:
        """Synchronous version of scrape_domain."""

        async def _runner() -> List[ScraperResult]:
            return await self.scrape_domain(url, max_pages=max_pages, **kwargs)

        return anyio.run(_runner)
    
    async def scrape_multiple(
        self,
        urls: List[str],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[ScraperResult]:
        """Scrape multiple URLs concurrently."""
        semaphore = anyio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(url):
            async with semaphore:
                result = await self.scrape(url, **kwargs)
                await anyio.sleep(self.config.rate_limit_delay)
                return result
        
        # Execute all scrapes concurrently using anyio task group
        results = []
        async with anyio.create_task_group() as tg:
            async def collect_result(url):
                result = await scrape_with_semaphore(url)
                results.append(result)
            
            for url in urls:
                tg.start_soon(collect_result, url)
        
        return results
    
    def scrape_multiple_sync(self, urls: List[str], **kwargs) -> List[ScraperResult]:
        """Synchronous version of scrape_multiple."""
        async def _runner() -> List[ScraperResult]:
            return await self.scrape_multiple(urls, **kwargs)

        return anyio.run(_runner)


# Convenience functions for backward compatibility
def scrape_url(url: str, method: Optional[str] = None, **kwargs) -> ScraperResult:
    """Scrape a single URL (synchronous)."""
    scraper = UnifiedWebScraper()
    method_enum = ScraperMethod(method) if method else None
    return scraper.scrape_sync(url, method=method_enum, **kwargs)


def scrape_urls(urls: List[str], **kwargs) -> List[ScraperResult]:
    """Scrape multiple URLs (synchronous)."""
    scraper = UnifiedWebScraper()
    return scraper.scrape_multiple_sync(urls, **kwargs)


async def scrape_url_async(url: str, method: Optional[str] = None, **kwargs) -> ScraperResult:
    """Scrape a single URL (asynchronous)."""
    scraper = UnifiedWebScraper()
    method_enum = ScraperMethod(method) if method else None
    return await scraper.scrape(url, method=method_enum, **kwargs)


async def scrape_urls_async(urls: List[str], **kwargs) -> List[ScraperResult]:
    """Scrape multiple URLs (asynchronous)."""
    scraper = UnifiedWebScraper()
    return await scraper.scrape_multiple(urls, **kwargs)

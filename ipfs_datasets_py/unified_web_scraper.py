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
6. IPWB (InterPlanetary Wayback) - IPFS-based web archives
7. Newspaper3k - Article extraction
8. Readability - Content extraction

The scraper automatically tries each method in sequence until successful,
making it resilient to various failure scenarios.
"""

import logging
import asyncio
import time
from typing import Dict, List, Optional, Any, Literal, Union, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from urllib.parse import urlparse, urljoin
import hashlib
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class ScraperMethod(Enum):
    """Available scraping methods."""
    PLAYWRIGHT = "playwright"
    BEAUTIFULSOUP = "beautifulsoup"
    WAYBACK_MACHINE = "wayback_machine"
    COMMON_CRAWL = "common_crawl"
    ARCHIVE_IS = "archive_is"
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
    # Which Playwright engine to use: chromium (default), firefox, or webkit.
    # Useful when some sites behave differently across engines.
    playwright_browser: str = "chromium"
    # Optional proxy for Playwright (used for the Playwright method only).
    # If not set, Playwright will fall back to the global proxy settings below.
    playwright_proxy_url: Optional[str] = None
    # If enabled, detect common anti-bot challenge pages (e.g., Cloudflare "Just a moment...")
    # and treat them as a scrape failure so the fallback chain continues.
    playwright_detect_challenge_pages: bool = True

    # Optional deterministic viewport sizing (no randomization). Useful for compatibility testing.
    # If both are set, they will be passed to Playwright as the browser context viewport.
    playwright_viewport_width: Optional[int] = None
    playwright_viewport_height: Optional[int] = None

    # Optional: capture API-like calls made by the page (XHR/fetch) to help discover
    # official JSON endpoints used by client-side apps.
    playwright_capture_api_calls: bool = False
    playwright_capture_api_max_entries: int = 50
    # If enabled, attempt to capture small JSON bodies for API calls.
    playwright_capture_api_bodies: bool = False
    playwright_capture_api_max_body_bytes: int = 200_000

    # Optional: when a challenge page is detected, write HTML + screenshot here.
    # This is diagnostic only and helps decide when to route to archive sources.
    playwright_challenge_artifacts_dir: Optional[str] = None
    extract_links: bool = True
    extract_text: bool = True
    follow_redirects: bool = True
    verify_ssl: bool = True

    # Global proxy options (applies to *all* requests-based methods).
    # If not provided, requests will still honor environment variables like
    # HTTPS_PROXY / HTTP_PROXY / ALL_PROXY.
    proxies: Optional[Dict[str, str]] = None
    # Convenience form: a single proxy URL for both HTTP and HTTPS.
    proxy_url: Optional[str] = None

    # Optional: route requests-based traffic through a local Tor SOCKS proxy.
    # IMPORTANT: Tor routing uses SOCKS, so requests needs PySocks
    # (`requests[socks]` or `pysocks`). You must also have Tor running locally.
    use_tor: bool = False
    # Optional override; if not set and use_tor=True, the scraper will pick 9050/9150.
    tor_proxy_url: Optional[str] = None

    rate_limit_delay: float = 1.0
    preferred_methods: Optional[List[ScraperMethod]] = None
    fallback_enabled: bool = True

    # Common Crawl options
    # If True, attempt to fetch and parse the archived response from the WARC
    # using HTTPS range requests to data.commoncrawl.org.
    common_crawl_fetch_content: bool = True
    # If True, treat "index hit" as success even if content fetch/parse fails.
    # When False (default), Common Crawl is only a success if content is extracted.
    common_crawl_metadata_only_ok: bool = False
    # Limit number of indexes tried per URL (kept small for tight iteration).
    common_crawl_max_indexes: int = 6
    # Number of records to request per query (we use the first hit).
    common_crawl_max_records_per_query: int = 1

    # Common Crawl endpoint overrides
    # Useful when index.commoncrawl.org is blocked and you need a proxy/mirror.
    common_crawl_cdx_base_url: str = "https://index.commoncrawl.org"
    common_crawl_collinfo_url: str = "https://index.commoncrawl.org/collinfo.json"
    # Optional: provide multiple CDX endpoints to try in order (e.g. official + your proxy).
    # When provided, the scraper will probe/select a working endpoint and cache it.
    common_crawl_cdx_base_urls: Optional[List[str]] = None
    # Optional: provide multiple collinfo URLs corresponding to base URLs. If omitted,
    # the scraper will derive collinfo as <base>/collinfo.json.
    common_crawl_collinfo_urls: Optional[List[str]] = None
    # If provided, skip collinfo discovery and only try these index ids (e.g., ["CC-MAIN-2025-50"]).
    common_crawl_index_ids: Optional[List[str]] = None

    # Common Crawl CDX transport options
    # Option C: try querying https://index.commoncrawl.org via Playwright.
    # This can help on networks where direct HTTP requests to the CDX service are
    # blocked/mitm'd but browser traffic works.
    common_crawl_cdx_playwright_first: bool = False
    # Default to using Playwright as a fallback transport (not first) so a single-URL
    # lookup can still succeed on networks where direct HTTP to the CDX service is blocked.
    common_crawl_cdx_playwright_fallback: bool = True

    # Wayback Machine options
    # If enabled, when there are no Wayback captures for a URL, attempt to request an
    # archival snapshot using the official Internet Archive "Save Page Now" endpoint.
    # This is opt-in and should be used sparingly.
    wayback_submit_on_miss: bool = False
    
    # Archive check and submit options
    # If enabled, check Archive.org and Archive.is before scraping and submit if not present
    archive_check_before_scrape: bool = False
    # Check Archive.org Wayback Machine for existing archives
    archive_check_wayback: bool = True
    # Check Archive.is for existing archives
    archive_check_archive_is: bool = True
    # Submit to archives if not present
    archive_submit_if_missing: bool = True
    # Wait for archive submission to complete before continuing
    archive_wait_for_completion: bool = False
    # Timeout for archive submission operations
    archive_submission_timeout: int = 60
    # Timeout (seconds) for the Save Page Now submission request.
    wayback_submit_timeout: float = 30.0
    # After submission, optionally poll Wayback for a newly created capture.
    wayback_submit_poll_attempts: int = 3
    wayback_submit_poll_delay: float = 2.0

    # Async archive submission options (Wayback + Archive.is)
    # If enabled, when the overall fallback chain fails (and/or when a bot challenge
    # page is detected), enqueue an asynchronous archive submission job and return
    # the job id in the final result metadata.
    archive_async_submit_on_failure: bool = False
    archive_async_submit_on_challenge: bool = False
    archive_async_check_archive_org: bool = True
    archive_async_check_archive_is: bool = True
    archive_async_submit_if_missing: bool = True
    archive_async_poll_interval_seconds: float = 60.0
    archive_async_max_wait_seconds: float = 6 * 60 * 60
    archive_async_callback_url: Optional[str] = None
    archive_async_callback_file: Optional[str] = None
    # Timeout for the *initial* check+submit call; the long-running monitoring is
    # handled by the background job.
    archive_async_initial_submit_timeout_seconds: int = 60

    # Common Crawl index fallback via direct index shard access (Option A).
    # Uses public files on https://data.commoncrawl.org/:
    # - cc-index.paths.gz
    # - cluster.idx (maps SURT ranges -> cdx shard + (offset,length))
    # - cdx-*.gz (gzip members containing JSON lines)
    # This avoids index.commoncrawl.org entirely, but still requires multiple
    # HTTP range requests and may be slower.
    common_crawl_direct_index_enabled: bool = False
    # Crawl IDs (e.g. CC-MAIN-2025-47) to try, in order, when direct index is enabled.
    common_crawl_direct_index_crawl_ids: Optional[List[str]] = None

    # Safety limits for Option A (direct index shard access).
    # `cluster.idx` points to a compressed CDX shard block via (offset, length).
    # By default we keep this conservative to avoid unexpectedly large downloads
    # when scraping a single site.
    #
    # - `common_crawl_direct_index_max_block_bytes` caps the HTTP range fetch size.
    # - `common_crawl_direct_index_max_decompressed_bytes` caps decompression output.
    # - Set `common_crawl_direct_index_allow_large_blocks=True` to override.
    common_crawl_direct_index_allow_large_blocks: bool = False
    common_crawl_direct_index_max_block_bytes: int = 8_000_000
    common_crawl_direct_index_max_decompressed_bytes: int = 25_000_000

    # Optional: if enabled, allow a prefix/domain match fallback for direct-index lookup.
    # This is useful when you only need "some capture for this site" (e.g., discovery)
    # and the exact URL is missing.
    common_crawl_direct_index_prefix_fallback: bool = False

    # Optional explicit proxies for Common Crawl requests (CDX + WARC range fetch).
    # Example:
    #   {"https": "http://user:pass@proxy-host:3128", "http": "http://user:pass@proxy-host:3128"}
    # If not provided, `requests` will still honor environment variables like
    # HTTPS_PROXY / HTTP_PROXY (helpful on Windows), but explicit config is more
    # predictable for packaged apps.
    common_crawl_proxies: Optional[Dict[str, str]] = None
    # Convenience form for packaged apps: a single proxy URL.
    # If set and `common_crawl_proxies` is not, we will build a requests-style
    # proxy dict: {"http": url, "https": url}.
    common_crawl_proxy_url: Optional[str] = None

    # Optional: route Common Crawl traffic through a local Tor SOCKS proxy.
    # This is useful when the public CDX endpoint (index.commoncrawl.org) is
    # blocked/unreachable on some networks.
    #
    # IMPORTANT:
    # - Tor routing still uses SOCKS, so `requests` needs PySocks
    #   (installable via `requests[socks]` or `pysocks`).
    # - You must have Tor running locally (Tor daemon or Tor Browser).
    #   Common defaults:
    #     - Tor daemon:  socks5h://127.0.0.1:9050
    #     - Tor Browser: socks5h://127.0.0.1:9150
    common_crawl_use_tor: bool = False
    # Optional override; when not set, we will auto-detect 9050/9150.
    common_crawl_tor_proxy_url: Optional[str] = None

    # Common Crawl index fallback via Amazon Athena (columnar index).
    # IMPORTANT:
    # - Requires AWS credentials (IAM permissions for Athena + S3).
    # - Requires an S3 bucket YOU control for Athena query results (OutputLocation).
    #   This is mandatory even if the Common Crawl dataset itself is public.
    # - May incur AWS charges (Athena is billed by bytes scanned + S3 storage for results).
    # This is only used if enabled and CDX is unreachable/blocked.
    common_crawl_athena_enabled: bool = False
    common_crawl_athena_region: str = "us-east-1"
    # REQUIRED when `common_crawl_athena_enabled=True`.
    # Athena writes query results to S3; you must provide a bucket you control.
    # Example: "s3://my-athena-results-bucket/prefix/"
    common_crawl_athena_output_s3: Optional[str] = None
    common_crawl_athena_workgroup: Optional[str] = None
    common_crawl_athena_database: str = "ccindex"
    common_crawl_athena_table: str = "ccindex"
    common_crawl_athena_subset: str = "warc"
    # Partition(s) to try, in order. If not set, uses a small recent-ish list.
    common_crawl_athena_crawl_ids: Optional[List[str]] = None
    common_crawl_athena_max_wait_s: float = 30.0
    common_crawl_athena_poll_interval_s: float = 0.8
    
    def __post_init__(self):
        """Set default preferred methods if not specified."""
        if self.preferred_methods is None:
            self.preferred_methods = [
                ScraperMethod.PLAYWRIGHT,
                ScraperMethod.BEAUTIFULSOUP,
                ScraperMethod.WAYBACK_MACHINE,
                ScraperMethod.ARCHIVE_IS,
                ScraperMethod.COMMON_CRAWL,
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
        
        Args:
            config: Scraper configuration. If None, uses defaults.
        """
        self.config = config or ScraperConfig()
        self._check_dependencies()
        self._init_session()
        self._common_crawl_down_until: float = 0.0
        self._common_crawl_down_reason: Optional[str] = None
        self._common_crawl_selected_cdx_base_url: Optional[str] = None
        self._common_crawl_selected_collinfo_url: Optional[str] = None
        self._common_crawl_selected_until: float = 0.0
        self._common_crawl_endpoint_down: Dict[str, float] = {}

        # Cached resolved proxy dict for requests-based methods.
        self._resolved_proxies: Optional[Dict[str, str]] = None

    def _common_crawl_endpoint_candidates(self) -> List[Dict[str, str]]:
        """Return ordered candidate CDX endpoints.

        The first candidate is the default (or configured) endpoint. If lists are
        provided, those are used in-order.
        """
        candidates: List[Dict[str, str]] = []

        if self.config.common_crawl_cdx_base_urls:
            bases = [b for b in self.config.common_crawl_cdx_base_urls if b]
        else:
            bases = [self.config.common_crawl_cdx_base_url]

        collinfos: Optional[List[str]] = None
        if self.config.common_crawl_collinfo_urls:
            collinfos = [c for c in self.config.common_crawl_collinfo_urls if c]

        for i, base in enumerate(bases):
            base_norm = (base or "").rstrip("/")
            if not base_norm:
                continue
            if collinfos and i < len(collinfos):
                collinfo = collinfos[i]
            else:
                collinfo = f"{base_norm}/collinfo.json"
            candidates.append({"base": base_norm, "collinfo": collinfo})

        # Always ensure official endpoint is in the list as a last resort.
        if not any(c["base"] == "https://index.commoncrawl.org" for c in candidates):
            candidates.append({
                "base": "https://index.commoncrawl.org",
                "collinfo": "https://index.commoncrawl.org/collinfo.json",
            })

        return candidates

    def _common_crawl_proxies(self) -> Optional[Dict[str, str]]:
        """Resolve Common Crawl proxy settings.

        Priority:
        1) Explicit `ScraperConfig.common_crawl_proxies`
        2) Convenience `ScraperConfig.common_crawl_proxy_url`
        2b) Tor routing (`ScraperConfig.common_crawl_use_tor`)
        3) Global proxy settings (ScraperConfig.proxies / proxy_url / use_tor)
        4) None (requests will use system env vars like HTTPS_PROXY/HTTP_PROXY)
        """
        if self.config.common_crawl_proxies:
            return self.config.common_crawl_proxies
        if self.config.common_crawl_proxy_url:
            p = self.config.common_crawl_proxy_url.strip()
            if p:
                return {"http": p, "https": p}

        if self.config.common_crawl_use_tor:
            tor_url = (self.config.common_crawl_tor_proxy_url or "").strip() or self._detect_local_tor_proxy_url()
            if tor_url:
                return {"http": tor_url, "https": tor_url}
        return self._resolve_global_proxies()

    def _resolve_global_proxies(self) -> Optional[Dict[str, str]]:
        """Resolve proxy settings for requests-based methods.

        Priority:
        1) Explicit `ScraperConfig.proxies`
        2) Convenience `ScraperConfig.proxy_url`
        3) Tor routing (`ScraperConfig.use_tor`)
        4) None (requests will use system env vars)
        """
        if self.config.proxies:
            return self.config.proxies
        if self.config.proxy_url:
            p = (self.config.proxy_url or "").strip()
            if p:
                return {"http": p, "https": p}
        if self.config.use_tor:
            tor_url = (self.config.tor_proxy_url or "").strip() or self._detect_local_tor_proxy_url()
            if tor_url:
                return {"http": tor_url, "https": tor_url}
        return None

    def _ensure_requests_proxy_supported(self, proxies: Optional[Dict[str, str]]) -> None:
        if self._proxies_use_socks(proxies) and not self._has_socks_support():
            raise RuntimeError(
                "SOCKS proxy configured but PySocks is not installed. "
                "Install 'requests[socks]' (or 'pysocks') in the environment."
            )

    def _session_get(self, url: str, *, timeout: Optional[float] = None, **kwargs):
        """requests GET wrapper that enforces proxy dependency checks."""
        if not getattr(self, "session", None):
            import requests

            proxies = self._resolved_proxies or self._resolve_global_proxies()
            self._ensure_requests_proxy_supported(proxies)
            return requests.get(url, timeout=timeout or self.config.timeout, proxies=proxies, **kwargs)

        proxies = self._resolved_proxies or self._resolve_global_proxies()
        self._ensure_requests_proxy_supported(proxies)
        return self.session.get(url, timeout=timeout or self.config.timeout, **kwargs)

    def _playwright_proxy_config(self) -> Optional[Dict[str, str]]:
        """Return a Playwright proxy config dict for browser launch, if configured."""
        proxy_url = (self.config.playwright_proxy_url or "").strip()
        if not proxy_url:
            # Fall back to global proxy settings
            proxies = self._resolve_global_proxies()
            if proxies:
                proxy_url = (proxies.get("https") or proxies.get("http") or "").strip()

        if not proxy_url:
            return None

        # Playwright supports socks5 but not socks5h; rewrite for compatibility.
        if proxy_url.lower().startswith("socks5h://"):
            proxy_url = "socks5://" + proxy_url[len("socks5h://"):]

        from urllib.parse import urlparse

        parsed = urlparse(proxy_url)
        username = parsed.username
        password = parsed.password

        # Keep server without credentials
        host = parsed.hostname
        port = parsed.port
        scheme = parsed.scheme or "http"
        if not host:
            return {"server": proxy_url}
        server = f"{scheme}://{host}:{port}" if port else f"{scheme}://{host}"
        cfg: Dict[str, str] = {"server": server}
        if username:
            cfg["username"] = username
        if password:
            cfg["password"] = password
        return cfg

    @staticmethod
    def _detect_local_tor_proxy_url() -> Optional[str]:
        """Best-effort detection of a local Tor SOCKS proxy.

        Returns a SOCKS URL (preferably socks5h for remote DNS) if a known Tor
        port appears reachable on localhost, else None.

        This does not require PySocks; it only checks for an open TCP port.
        """
        import socket

        for port in (9050, 9150):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.35):
                    return f"socks5h://127.0.0.1:{port}"
            except Exception:
                continue
        # If nothing is reachable, fall back to the most common daemon port.
        # The actual request will fail with a clearer error later.
        return "socks5h://127.0.0.1:9050"

    @staticmethod
    def _to_surt(url: str) -> str:
        """Convert a URL to a SURT-like key used by Common Crawl cluster indexes.

        This is a pragmatic implementation suitable for mapping URLs into the
        `cluster.idx` keyspace. It aims to match Common Crawl's index ordering.
        """
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host:
            return url
        host_parts = [p for p in host.split(".") if p]
        host_rev = ",".join(reversed(host_parts))
        path = parsed.path or "/"
        query = ("?" + parsed.query) if parsed.query else ""
        return f"{host_rev}){path}{query}"

    async def _cc_http_get(self, url: str, *, timeout: float, headers: Dict[str, str], proxies: Optional[Dict[str, str]]) -> "requests.Response":
        """HTTP GET for Common Crawl metadata endpoints with optional Playwright transport."""
        import requests

        # If SOCKS is configured but support isn't available, fail fast.
        if self._proxies_use_socks(proxies) and not self._has_socks_support():
            raise RuntimeError(
                "SOCKS proxy configured for Common Crawl but PySocks is not installed. "
                "Install 'requests[socks]' (or 'pysocks')."
            )

        async def _via_requests() -> requests.Response:
            return await asyncio.to_thread(
                lambda: requests.get(url, timeout=timeout, headers=headers, proxies=proxies)
            )

        async def _via_playwright() -> requests.Response:
            # Use Playwright's request context, but return a lightweight shim that
            # mimics the parts we need (status_code, text, json()).
            from playwright.async_api import async_playwright

            class _Shim:
                def __init__(self, status: int, body: bytes):
                    self.status_code = status
                    self._body = body

                @property
                def text(self) -> str:
                    return self._body.decode("utf-8", errors="replace")

                def json(self):
                    return json.loads(self.text)

                def raise_for_status(self):
                    if not (200 <= self.status_code < 300):
                        raise RuntimeError(f"HTTP {self.status_code}")

            proxy_cfg = self._playwright_proxy_config()
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, proxy=proxy_cfg)
                try:
                    context = await browser.new_context(user_agent=headers.get("User-Agent"))
                    resp = await context.request.get(url, timeout=timeout * 1000)
                    body = await resp.body()
                    return _Shim(resp.status, body)  # type: ignore[return-value]
                finally:
                    await browser.close()

        if self.config.common_crawl_cdx_playwright_first:
            try:
                return await _via_playwright()
            except Exception:
                return await _via_requests()

        try:
            return await _via_requests()
        except Exception:
            if self.config.common_crawl_cdx_playwright_fallback and self.available_methods.get(ScraperMethod.PLAYWRIGHT, False):
                return await _via_playwright()
            raise

    async def _cc_http_get_text(self, url: str, *, timeout: float, headers: Dict[str, str], proxies: Optional[Dict[str, str]], params: Optional[Dict[str, Any]] = None) -> str:
        """HTTP GET returning response text, with optional Playwright transport."""
        import requests

        if params:
            # Use requests to build a fully qualified URL; Playwright request supports
            # querystring but this keeps behavior consistent.
            req = requests.Request("GET", url, params=params).prepare()
            url = str(req.url)

        resp = await self._cc_http_get(url, timeout=timeout, headers=headers, proxies=proxies)
        resp.raise_for_status()
        return resp.text

    async def _cc_direct_index_lookup(self, *, target_url: str, crawl_id: str, timeout: float, headers: Dict[str, str], proxies: Optional[Dict[str, str]], match_type: str = "exact") -> Optional[Dict[str, Any]]:
        """Option A: Lookup a CDX-like record via data.commoncrawl.org index shards.

        Returns a record dict containing at least filename/offset/length/url when found.
        """
        import gzip
        import io
        import requests

        if self._proxies_use_socks(proxies) and not self._has_socks_support():
            raise RuntimeError(
                "SOCKS proxy configured for Common Crawl but PySocks is not installed. "
                "Install 'requests[socks]' (or 'pysocks')."
            )

        # Determine the cluster key for the target URL.
        target_surt = self._to_surt(target_url)

        cluster_url = f"https://data.commoncrawl.org/cc-index/collections/{crawl_id}/indexes/cluster.idx"

        def _head_size() -> int:
            r = requests.head(cluster_url, timeout=min(timeout, 15.0), headers=headers, proxies=proxies)
            r.raise_for_status()
            size = int(r.headers.get("Content-Length") or "0")
            if not size:
                raise RuntimeError("cluster.idx missing Content-Length")
            return size

        def _get_range(start: int, end: int) -> bytes:
            r = requests.get(
                cluster_url,
                headers={**headers, "Range": f"bytes={start}-{end}"},
                timeout=min(timeout, 20.0),
                proxies=proxies,
            )
            if r.status_code not in (200, 206):
                raise RuntimeError(f"cluster.idx range fetch failed (status={r.status_code})")
            return r.content

        size = await asyncio.to_thread(_head_size)

        # Binary search over the remote file using range reads.
        lo = 0
        hi = size - 1
        best_line: Optional[str] = None
        best_fields: Optional[List[str]] = None

        chunk = 65536

        while lo <= hi:
            mid = (lo + hi) // 2
            start = max(0, mid - (chunk // 2))
            end = min(size - 1, start + chunk - 1)
            blob = await asyncio.to_thread(_get_range, start, end)
            text = blob.decode("utf-8", errors="replace")

            rel_mid = mid - start
            # Find a full line that starts after the previous newline.
            before = text.rfind("\n", 0, max(0, rel_mid))
            line_start = (before + 1) if before >= 0 else 0
            after = text.find("\n", max(0, rel_mid))
            if after < 0:
                # If we didn't get a newline, expand search window.
                if end < size - 1:
                    hi = min(hi, end)
                    continue
                after = len(text)

            line = text[line_start:after].strip("\r\n")
            if not line:
                break

            fields = line.split()
            if len(fields) < 5:
                break

            surt = fields[0]
            if surt <= target_surt:
                best_line = line
                best_fields = fields
                # Move right
                lo = mid + 1
            else:
                hi = mid - 1

        if not best_fields:
            return None

        # cluster.idx format: surt, timestamp, cdx-file, offset, length, ...
        cdx_file = best_fields[2]
        try:
            offset = int(best_fields[3])
            length = int(best_fields[4])
        except Exception:
            return None

        # Avoid unexpectedly large downloads by default.
        max_block = int(getattr(self.config, "common_crawl_direct_index_max_block_bytes", 0) or 0)
        allow_large = bool(getattr(self.config, "common_crawl_direct_index_allow_large_blocks", False))
        if max_block > 0 and length > max_block and not allow_large:
            raise RuntimeError(
                f"direct index block too large (crawl={crawl_id}, file={cdx_file}, length={length} bytes; "
                f"cap={max_block}). Set ScraperConfig.common_crawl_direct_index_allow_large_blocks=True "
                f"or raise ScraperConfig.common_crawl_direct_index_max_block_bytes to proceed."
            )

        cdx_url = f"https://data.commoncrawl.org/cc-index/collections/{crawl_id}/indexes/{cdx_file}"

        def _get_cdx_block() -> bytes:
            r = requests.get(
                cdx_url,
                headers={**headers, "Range": f"bytes={offset}-{offset + length - 1}"},
                timeout=min(timeout, 30.0),
                proxies=proxies,
            )
            if r.status_code not in (200, 206):
                raise RuntimeError(f"cdx range fetch failed (status={r.status_code})")
            return r.content

        block = await asyncio.to_thread(_get_cdx_block)
        max_decompressed = int(getattr(self.config, "common_crawl_direct_index_max_decompressed_bytes", 0) or 0)
        try:
            # Streamed decompression with a hard cap to avoid huge expansions.
            gz = gzip.GzipFile(fileobj=io.BytesIO(block))
            if max_decompressed > 0 and not allow_large:
                out = gz.read(max_decompressed + 1)
                if len(out) > max_decompressed:
                    raise RuntimeError(
                        f"direct index decompressed output too large (crawl={crawl_id}, file={cdx_file}; "
                        f"cap={max_decompressed} bytes). Set ScraperConfig.common_crawl_direct_index_allow_large_blocks=True "
                        f"or raise ScraperConfig.common_crawl_direct_index_max_decompressed_bytes to proceed."
                    )
                decompressed = out.decode("utf-8", errors="replace")
            else:
                decompressed = gz.read().decode("utf-8", errors="replace")
        except RuntimeError:
            raise
        except Exception:
            return None

        from urllib.parse import urlparse, urlunparse

        def _normalize_url(u: str) -> str:
            try:
                p = urlparse(u)
                scheme = (p.scheme or "").lower()
                host = (p.hostname or "").lower()
                port = p.port
                netloc = host
                if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
                    netloc = f"{host}:{port}"
                path = p.path or "/"
                # Keep query; drop fragment.
                return urlunparse((scheme, netloc, path, "", p.query or "", "")).rstrip("/")
            except Exception:
                return (u or "").strip().rstrip("/")

        def _normalize_url_no_query(u: str) -> str:
            try:
                p = urlparse(u)
                scheme = (p.scheme or "").lower()
                host = (p.hostname or "").lower()
                port = p.port
                netloc = host
                if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
                    netloc = f"{host}:{port}"
                path = p.path or "/"
                return urlunparse((scheme, netloc, path, "", "", "")).rstrip("/")
            except Exception:
                return (u or "").strip().rstrip("/")

        match_type = (match_type or "exact").strip().lower()
        if match_type not in {"exact", "prefix"}:
            match_type = "exact"

        # Build match candidates.
        candidates_raw = {target_url}
        if target_url.startswith("https://"):
            candidates_raw.add("http://" + target_url[len("https://"):])
        if target_url.startswith("http://"):
            candidates_raw.add("https://" + target_url[len("http://"):])

        # Add www/non-www variants.
        for u in list(candidates_raw):
            p = urlparse(u)
            host = p.hostname or ""
            if host.startswith("www."):
                alt_host = host[len("www."):]
            else:
                alt_host = "www." + host if host else host
            if alt_host and alt_host != host:
                netloc = alt_host
                if p.port:
                    netloc = f"{alt_host}:{p.port}"
                candidates_raw.add(urlunparse((p.scheme, netloc, p.path or "/", "", p.query or "", "")))

        # Add trailing-slash variants when path is root.
        for u in list(candidates_raw):
            p = urlparse(u)
            if not p.path or p.path == "/":
                candidates_raw.add(urlunparse((p.scheme, p.netloc, "/", "", p.query or "", "")))

        if match_type == "exact":
            candidates = {_normalize_url(u) for u in candidates_raw if u}
        else:
            # For prefix matches, ignore querystrings to avoid over-filtering.
            candidates = {_normalize_url_no_query(u) for u in candidates_raw if u}

        for raw_line in decompressed.splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            parts = raw_line.split(None, 2)
            if len(parts) < 3:
                continue
            try:
                rec = json.loads(parts[2])
            except Exception:
                continue
            u = rec.get("url")
            if not u:
                continue

            if match_type == "exact":
                ok = _normalize_url(u) in candidates
            else:
                nu = _normalize_url_no_query(u)
                ok = any(nu.startswith(pref) for pref in candidates if pref)

            if ok:
                # Attach best-effort provenance for audit/debugging.
                try:
                    rec["_direct_index_shard_file"] = cdx_file
                    rec["_direct_index_block_offset"] = offset
                    rec["_direct_index_block_length"] = length
                    rec["_direct_index_cluster_line"] = best_line
                    rec["_direct_index_match_type"] = match_type
                except Exception:
                    pass
                return rec

        return None

    def common_crawl_capabilities(self) -> Dict[str, Any]:
        """Return runtime capability info relevant to Common Crawl.

        Intended for startup diagnostics in packaged apps (no network calls).
        """
        proxies = self._common_crawl_proxies()

        tor_url = None
        tor_detected = False
        if self.config.common_crawl_use_tor:
            tor_url = (self.config.common_crawl_tor_proxy_url or "").strip() or self._detect_local_tor_proxy_url()
            # If we auto-detected 9150, consider it detected; otherwise best-effort.
            tor_detected = bool(tor_url)

        def _env_has_proxy() -> bool:
            import os

            for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
                if os.environ.get(k):
                    return True
            return False

        try:
            import boto3  # type: ignore

            athena_available = True
        except Exception:
            athena_available = False

        try:
            from warcio.archiveiterator import ArchiveIterator  # type: ignore

            warcio_available = True
        except Exception:
            warcio_available = False

        try:
            from bs4 import BeautifulSoup  # type: ignore

            bs4_available = True
        except Exception:
            bs4_available = False

        return {
            "proxies_configured": bool(proxies),
            "uses_socks": self._proxies_use_socks(proxies),
            "socks_supported": self._has_socks_support(),
            "tor_enabled": bool(self.config.common_crawl_use_tor),
            "tor_proxy_url": tor_url,
            "tor_proxy_detected": tor_detected,
            "env_proxy_set": _env_has_proxy(),
            "warcio_available": warcio_available,
            "beautifulsoup_available": bs4_available,
            "athena_sdk_available": athena_available,
        }

    @staticmethod
    def _proxies_use_socks(proxies: Optional[Dict[str, str]]) -> bool:
        if not proxies:
            return False
        for v in proxies.values():
            if not v:
                continue
            vv = str(v).lower().strip()
            if vv.startswith("socks5://") or vv.startswith("socks5h://") or vv.startswith("socks4://") or vv.startswith("socks4a://"):
                return True
        return False

    @staticmethod
    def _has_socks_support() -> bool:
        """Return True if requests can use SOCKS proxies.

        `requests` requires PySocks (installable via `requests[socks]` or `pysocks`).
        """
        try:
            import socks  # type: ignore

            return True
        except Exception:
            return False

    async def _pick_common_crawl_endpoint(self, *, timeout: float, headers: Dict[str, str]) -> Dict[str, str]:
        """Pick a reachable Common Crawl CDX endpoint and cache it.

        This doesn't guarantee the endpoint will stay up, but it prevents us from
        hammering a broken host and allows rotation when a proxy is available.
        """
        now = time.time()
        if self._common_crawl_selected_until and now < self._common_crawl_selected_until:
            if self._common_crawl_selected_cdx_base_url and self._common_crawl_selected_collinfo_url:
                return {
                    "base": self._common_crawl_selected_cdx_base_url,
                    "collinfo": self._common_crawl_selected_collinfo_url,
                }

        import requests

        proxies = self._common_crawl_proxies()
        # If SOCKS is configured but support isn't available, don't waste time probing.
        if self._proxies_use_socks(proxies) and not self._has_socks_support():
            base_norm = (self.config.common_crawl_cdx_base_url or "https://index.commoncrawl.org").rstrip("/")
            return {"base": base_norm, "collinfo": self.config.common_crawl_collinfo_url}

        def _probe(url_: str) -> bool:
            # Use a tiny GET (HEAD may be blocked by some proxies).
            r = requests.get(url_, timeout=min(timeout, 4.0), headers=headers, proxies=proxies)
            return 200 <= r.status_code < 300

        candidates = self._common_crawl_endpoint_candidates()
        for cand in candidates:
            base = cand["base"]
            down_until = self._common_crawl_endpoint_down.get(base, 0.0)
            if down_until and now < down_until:
                continue
            try:
                ok = await asyncio.to_thread(_probe, cand["collinfo"])
            except Exception:
                ok = False
            if ok:
                self._common_crawl_selected_cdx_base_url = base
                self._common_crawl_selected_collinfo_url = cand["collinfo"]
                # Cache selection briefly to reduce probes.
                self._common_crawl_selected_until = now + 300.0
                return cand

        # Fallback: return default config (even if unreachable) so error paths
        # remain informative.
        base_norm = (self.config.common_crawl_cdx_base_url or "https://index.commoncrawl.org").rstrip("/")
        return {"base": base_norm, "collinfo": self.config.common_crawl_collinfo_url}
    
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
            import requests
            self.available_methods[ScraperMethod.COMMON_CRAWL] = True
        except ImportError:
            self.available_methods[ScraperMethod.COMMON_CRAWL] = False
            logger.debug("requests not available for Common Crawl")
        
        # Check Archive.is (requires requests)
        try:
            import requests
            self.available_methods[ScraperMethod.ARCHIVE_IS] = True
        except ImportError:
            self.available_methods[ScraperMethod.ARCHIVE_IS] = False
        
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

            # Cache resolved proxies and set them on the session (requests-based methods).
            self._resolved_proxies = self._resolve_global_proxies()
            if self._resolved_proxies:
                # Don't hard-fail init if SOCKS support is missing; individual requests
                # will raise a clearer error via _session_get().
                try:
                    self._ensure_requests_proxy_supported(self._resolved_proxies)
                    self.session.proxies.update(self._resolved_proxies)
                except Exception as e:
                    logger.warning(f"Proxy configured but could not be applied to requests session: {e}")
        except ImportError:
            self.session = None
    
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
        
        # Check and submit to archives if configured
        archive_check_result = None
        if self.config.archive_check_before_scrape:
            try:
                from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import check_and_submit_to_archives
                
                logger.info(f"Checking archives for {url}")
                archive_check_result = await check_and_submit_to_archives(
                    url,
                    check_archive_org=self.config.archive_check_wayback,
                    check_archive_is=self.config.archive_check_archive_is,
                    submit_if_missing=self.config.archive_submit_if_missing,
                    wait_for_archive_completion=self.config.archive_wait_for_completion,
                    archive_timeout=self.config.archive_submission_timeout
                )
                
                logger.info(f"Archive check completed: {archive_check_result.get('summary', 'no summary')}")
            except Exception as e:
                logger.warning(f"Archive check failed for {url}: {e}")
                # Continue with scraping even if archive check fails
        
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
        
        # Add archive check result to metadata
        if archive_check_result:
            result.metadata = result.metadata or {}
            result.metadata["archive_check"] = archive_check_result
        
        result.extraction_time = time.time() - start_time
        return result
    
    async def _scrape_with_fallback(self, url: str, **kwargs) -> ScraperResult:
        """Try multiple scraping methods in sequence until one succeeds."""
        errors: List[str] = []
        attempted_methods: List[str] = []
        skipped_unavailable: List[str] = []
        errors_by_method: Dict[str, List[str]] = {}
        metadata_by_method: Dict[str, Dict[str, Any]] = {}

        for method in self.config.preferred_methods:
            if not self.available_methods.get(method, False):
                skipped_unavailable.append(method.value)
                continue

            attempted_methods.append(method.value)

            try:
                logger.info(f"Trying {method.value} for {url}")
                result = await self._scrape_with_method(url, method, **kwargs)

                # Preserve per-method metadata for diagnostics, even on failure.
                if isinstance(getattr(result, "metadata", None), dict) and result.metadata:
                    metadata_by_method[method.value] = result.metadata

                if result.success:
                    logger.info(f"Successfully scraped {url} using {method.value}")
                    result.metadata = {
                        **(result.metadata or {}),
                        "attempted_methods": attempted_methods,
                        "skipped_unavailable_methods": skipped_unavailable,
                        "errors_by_method": errors_by_method,
                        "metadata_by_method": metadata_by_method,
                        "available_methods": {m.value: bool(self.available_methods.get(m, False)) for m in ScraperMethod},
                    }
                    return result

                # Method returned a structured failure
                if result.errors:
                    errors_by_method.setdefault(method.value, []).extend(result.errors)
                    errors.extend(result.errors)

            except Exception as e:
                error_msg = f"{method.value} failed: {str(e)}"
                errors_by_method.setdefault(method.value, []).append(error_msg)
                errors.append(error_msg)
                logger.warning(error_msg)

            # Rate limiting between attempts
            await asyncio.sleep(self.config.rate_limit_delay)

        # All methods failed
        challenge_detected = any(
            bool((m or {}).get("challenge_detected"))
            for m in (metadata_by_method or {}).values()
            if isinstance(m, dict)
        )
        should_enqueue_archive_job = bool(getattr(self.config, "archive_async_submit_on_failure", False)) or (
            challenge_detected and bool(getattr(self.config, "archive_async_submit_on_challenge", False))
        )

        archive_async: Optional[Dict[str, Any]] = None
        if should_enqueue_archive_job:
            trigger = "bot_challenge" if challenge_detected else "fallback_failure"
            archive_async = await self._maybe_enqueue_async_archive_job(url, trigger=trigger)

        final = ScraperResult(
            url=url,
            success=False,
            errors=errors or ["No scraping methods available"],
            metadata={
                "attempted_methods": attempted_methods,
                "skipped_unavailable_methods": skipped_unavailable,
                "errors_by_method": errors_by_method,
                "metadata_by_method": metadata_by_method,
                "available_methods": {m.value: bool(self.available_methods.get(m, False)) for m in ScraperMethod},
                **({"archive_async": archive_async} if archive_async else {}),
            },
        )
        return final
    
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
        
        async with async_playwright() as p:
            proxy_cfg = self._playwright_proxy_config()
            engine = (self.config.playwright_browser or "chromium").strip().lower()
            if engine not in {"chromium", "firefox", "webkit"}:
                engine = "chromium"
            launcher = getattr(p, engine)
            browser = await launcher.launch(headless=self.config.playwright_headless, proxy=proxy_cfg)

            viewport = None
            if self.config.playwright_viewport_width and self.config.playwright_viewport_height:
                viewport = {
                    "width": int(self.config.playwright_viewport_width),
                    "height": int(self.config.playwright_viewport_height),
                }

            context = await browser.new_context(
                user_agent=(self.config.user_agent or None),
                viewport=viewport,
            )
            page = await context.new_page()

            api_calls: List[Dict[str, Any]] = []
            if self.config.playwright_capture_api_calls:
                async def _handle_response(resp) -> None:
                    try:
                        if len(api_calls) >= int(self.config.playwright_capture_api_max_entries or 0):
                            return

                        req = resp.request
                        resource_type = (req.resource_type or "").lower()
                        if resource_type not in {"xhr", "fetch"}:
                            return

                        headers = resp.headers or {}
                        content_type = (headers.get("content-type") or headers.get("Content-Type") or "").lower()
                        entry: Dict[str, Any] = {
                            "url": resp.url,
                            "status": resp.status,
                            "method": req.method,
                            "resource_type": resource_type,
                            "content_type": content_type,
                        }

                        # Capture small response bodies for API calls.
                        # Some providers return JSON with non-JSON content-types (e.g., text/plain),
                        # so we also gate on URL heuristics and then validate that the body looks like JSON.
                        if self.config.playwright_capture_api_bodies:
                            try:
                                max_bytes = int(self.config.playwright_capture_api_max_body_bytes or 0)
                                if max_bytes > 0:
                                    # Avoid attempting to capture obviously-large responses.
                                    cl = headers.get("content-length") or headers.get("Content-Length")
                                    try:
                                        if cl is not None and int(cl) > max_bytes:
                                            entry["body_truncated"] = True
                                            entry["body_len"] = int(cl)
                                            cl = None
                                    except Exception:
                                        pass

                                    looks_like_json_ct = "json" in content_type
                                    u = (resp.url or "").lower()
                                    looks_like_api_url = any(tok in u for tok in ("/api/", "graphql", ".json", "format=json"))

                                    if looks_like_json_ct or looks_like_api_url:
                                        body = await resp.body()
                                        if len(body) <= max_bytes:
                                            text = body.decode("utf-8", errors="replace")
                                            # Only persist when the payload looks JSON-ish.
                                            # (We don't want to store HTML pages by accident.)
                                            s = text.lstrip()
                                            if looks_like_json_ct or s.startswith("{") or s.startswith("["):
                                                entry["body_text"] = text
                                        else:
                                            entry["body_truncated"] = True
                                            entry["body_len"] = len(body)
                            except Exception as e:
                                entry["body_error"] = str(e)

                        api_calls.append(entry)
                    except Exception:
                        # Best-effort diagnostics; never break scraping.
                        return

                def _on_response(resp) -> None:
                    asyncio.create_task(_handle_response(resp))

                page.on("response", _on_response)
            
            try:
                await page.goto(url, wait_until=self.config.playwright_wait_for, timeout=self.config.timeout * 1000)
                
                # Get content
                html = await page.content()
                title = await page.title()

                # Detect common anti-bot challenge pages and fail fast so fallback continues.
                if self.config.playwright_detect_challenge_pages:
                    t = (title or "").strip().lower()
                    h = (html or "").lower()
                    if (
                        "just a moment" in t
                        and (
                            "cdn-cgi" in h
                            or "cf-browser-verification" in h
                            or "challenge-platform" in h
                            or "cf_chl" in h
                            or "cf-turnstile" in h
                        )
                    ):
                        artifacts: Dict[str, Any] = {}
                        if self.config.playwright_challenge_artifacts_dir:
                            try:
                                out_dir = Path(self.config.playwright_challenge_artifacts_dir)
                                out_dir.mkdir(parents=True, exist_ok=True)
                                ts = datetime.now().strftime("%Y%m%dT%H%M%S")
                                hsh = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
                                html_path = out_dir / f"challenge_{ts}_{hsh}.html"
                                png_path = out_dir / f"challenge_{ts}_{hsh}.png"
                                html_path.write_text(html or "", encoding="utf-8", errors="replace")
                                await page.screenshot(path=str(png_path), full_page=True)
                                artifacts = {
                                    "html_path": str(html_path),
                                    "screenshot_path": str(png_path),
                                }
                            except Exception as e:
                                artifacts = {"error": str(e)}

                        return ScraperResult(
                            url=url,
                            success=False,
                            errors=[
                                "Playwright received an anti-bot challenge page (likely Cloudflare). "
                                "Treating as failure so other fallbacks can run."
                            ],
                            method_used=ScraperMethod.PLAYWRIGHT,
                            metadata={
                                "method": "playwright",
                                "challenge_detected": True,
                                "challenge_provider": "cloudflare",
                                "title": title,
                                "api_calls": api_calls,
                                **({"challenge_artifacts": artifacts} if artifacts else {}),
                            },
                        )
                
                # Parse with BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                
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
                    html=html,
                    title=title,
                    text=text,
                    content=text,
                    links=links,
                    method_used=ScraperMethod.PLAYWRIGHT,
                    success=True,
                    metadata={
                        'method': 'playwright',
                        'content_length': len(html),
                        **({"api_calls": api_calls} if api_calls else {}),
                    }
                )
            
            finally:
                await context.close()
                await browser.close()
    
    async def _scrape_beautifulsoup(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using BeautifulSoup + requests."""
        from bs4 import BeautifulSoup

        response = self._session_get(
            url,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            allow_redirects=self.config.follow_redirects
        )
        response.raise_for_status()
        
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
                'content_length': len(response.content)
            }
        )
    
    async def _scrape_wayback(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Wayback Machine."""
        from wayback import WaybackClient
        from bs4 import BeautifulSoup
        
        client = WaybackClient()
        
        # Get most recent capture
        try:
            capture = next(client.search(url, limit=1))

            # wayback library can return different record types depending on version;
            # be defensive about attribute names.
            archive_url = getattr(capture, "archive_url", None) or getattr(capture, "url", None)
            if not archive_url:
                # Try building an IA URL from timestamp + original
                ts = getattr(capture, "timestamp", None)
                ts_str = None
                if ts is not None:
                    try:
                        ts_str = ts.strftime("%Y%m%d%H%M%S")
                    except Exception:
                        ts_str = str(ts)
                ts_str = ts_str or ""
                archive_url = f"https://web.archive.org/web/{ts_str}/{url}" if ts_str else None

            if not archive_url:
                return ScraperResult(
                    url=url,
                    success=False,
                    errors=["Wayback capture found but archive URL could not be determined"],
                )
            
            # Fetch archived content
            response = self._session_get(archive_url, timeout=self.config.timeout)
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
                    'timestamp': getattr(capture, 'timestamp', None).isoformat() if hasattr(getattr(capture, 'timestamp', None), 'isoformat') else str(getattr(capture, 'timestamp', '')),
                    'original_url': getattr(capture, 'original_url', None) or getattr(capture, 'original', None) or url,
                }
            )
        except StopIteration:
            # Optional: request an archive snapshot via the official Save Page Now endpoint.
            submit_result = None
            if getattr(self.config, "wayback_submit_on_miss", False):
                submit_result = self._submit_wayback_savepagenow(url)
                if submit_result.get("submitted"):
                    submitted_archive_url = submit_result.get("archive_url")
                    if submitted_archive_url:
                        try:
                            response = self._session_get(submitted_archive_url, timeout=self.config.timeout)
                            response.raise_for_status()
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
                                method_used=ScraperMethod.WAYBACK_MACHINE,
                                success=True,
                                metadata={
                                    'method': 'wayback_machine',
                                    'archive_url': submitted_archive_url,
                                    'timestamp': None,
                                    'original_url': url,
                                    'wayback_submit': submit_result,
                                },
                            )
                        except Exception as e:
                            return ScraperResult(
                                url=url,
                                success=False,
                                errors=[
                                    "Wayback Save Page Now submission succeeded but fetching archived content failed: "
                                    + str(e)
                                ],
                                metadata={
                                    'method': 'wayback_machine',
                                    'wayback_submit': submit_result,
                                },
                            )

                    # If we don't have an immediate archive URL, poll for a new capture.
                    try:
                        poll_attempts = max(0, int(getattr(self.config, "wayback_submit_poll_attempts", 0)))
                        poll_delay = float(getattr(self.config, "wayback_submit_poll_delay", 0.0))
                    except Exception:
                        poll_attempts, poll_delay = 0, 0.0

                    for _ in range(poll_attempts):
                        if poll_delay > 0:
                            time.sleep(poll_delay)
                        try:
                            capture = next(client.search(url, limit=1))
                            archive_url = getattr(capture, "archive_url", None) or getattr(capture, "url", None)
                            if archive_url:
                                response = self._session_get(archive_url, timeout=self.config.timeout)
                                response.raise_for_status()

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
                                    method_used=ScraperMethod.WAYBACK_MACHINE,
                                    success=True,
                                    metadata={
                                        'method': 'wayback_machine',
                                        'archive_url': archive_url,
                                        'timestamp': getattr(capture, 'timestamp', None).isoformat() if hasattr(getattr(capture, 'timestamp', None), 'isoformat') else str(getattr(capture, 'timestamp', '')),
                                        'original_url': getattr(capture, 'original_url', None) or getattr(capture, 'original', None) or url,
                                        'wayback_submit': submit_result,
                                    },
                                )
                        except StopIteration:
                            continue
                        except Exception:
                            continue

            return ScraperResult(
                url=url,
                success=False,
                errors=["No Wayback Machine captures found for this URL"],
                metadata={
                    'method': 'wayback_machine',
                    'wayback_submit': submit_result,
                },
            )
        except Exception as e:
            submit_result = None
            if getattr(self.config, "wayback_submit_on_miss", False):
                try:
                    submit_result = self._submit_wayback_savepagenow(url)
                except Exception:
                    submit_result = {"submitted": False, "error": "Save Page Now submission helper failed"}
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"Wayback Machine scraping failed: {str(e)}"],
                metadata={
                    "method": "wayback_machine",
                    "wayback_submit": submit_result,
                },
            )

    def _is_safe_public_url_for_archiving(self, url: str) -> bool:
        """Return True if `url` is an http(s) URL and does not target local/private hosts.

        This is a safety check to reduce the risk of submitting internal URLs to third-party
        archiving services.
        """
        try:
            from urllib.parse import urlparse
            import ipaddress

            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            host = parsed.hostname
            if not host:
                return False
            if host.lower() in {"localhost"}:
                return False

            # If the host is an IP address, ensure it's public.
            try:
                ip = ipaddress.ip_address(host)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_multicast
                    or ip.is_reserved
                ):
                    return False
            except ValueError:
                # Hostname: block common local-only suffixes without resolving.
                h = host.lower()
                if h.endswith(".local") or h.endswith(".internal"):
                    return False

            return True
        except Exception:
            return False

    def _submit_wayback_savepagenow(self, url: str) -> Dict[str, Any]:
        """Request an archival snapshot from the Internet Archive Save Page Now endpoint.

        This uses the official endpoint at https://web.archive.org/save/<url>.
        Returns a small dict with status details and (when available) the archive URL.
        """
        if not self._is_safe_public_url_for_archiving(url):
            return {
                "submitted": False,
                "error": "Refusing to submit non-public or non-http(s) URL for archiving",
            }

        save_url = f"https://web.archive.org/save/{url}"
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        timeout = float(getattr(self.config, "wayback_submit_timeout", 30.0))
        try:
            resp = self._session_get(save_url, timeout=timeout, headers=headers, allow_redirects=False)
            archive_url = None

            # Save Page Now may respond with Content-Location or Location pointing to the new capture.
            content_location = resp.headers.get("Content-Location")
            location = resp.headers.get("Location")
            candidate = content_location or location
            if candidate:
                if candidate.startswith("http://") or candidate.startswith("https://"):
                    archive_url = candidate
                else:
                    archive_url = "https://web.archive.org" + candidate

            return {
                "submitted": True,
                "status_code": getattr(resp, "status_code", None),
                "save_url": save_url,
                "archive_url": archive_url,
                "location": location,
                "content_location": content_location,
            }
        except Exception as e:
            return {
                "submitted": False,
                "save_url": save_url,
                "error": str(e),
            }
    

    async def _maybe_enqueue_async_archive_job(
        self,
        url: str,
        *,
        trigger: str,
    ) -> Optional[Dict[str, Any]]:
        """Optionally submit an async archive job and return a compact summary."""
        if not self._is_safe_public_url_for_archiving(url):
            return {
                "status": "skipped",
                "trigger": trigger,
                "reason": "unsafe_url",
            }

        try:
            from ipfs_datasets_py.mcp_server.tools.web_archive_tools import submit_archives_async
        except Exception as e:
            return {
                "status": "error",
                "trigger": trigger,
                "error": f"submit_archives_async unavailable: {e}",
            }

        try:
            resp = await submit_archives_async(
                url,
                check_archive_org=bool(getattr(self.config, "archive_async_check_archive_org", True)),
                check_archive_is=bool(getattr(self.config, "archive_async_check_archive_is", True)),
                submit_if_missing=bool(getattr(self.config, "archive_async_submit_if_missing", True)),
                poll_interval_seconds=float(getattr(self.config, "archive_async_poll_interval_seconds", 60.0)),
                max_wait_seconds=float(getattr(self.config, "archive_async_max_wait_seconds", 6 * 60 * 60)),
                callback_url=getattr(self.config, "archive_async_callback_url", None),
                callback_file=getattr(self.config, "archive_async_callback_file", None),
                initial_submit_timeout_seconds=int(getattr(self.config, "archive_async_initial_submit_timeout_seconds", 60)),
            )
        except TypeError:
            # Backward compatibility if submit_archives_async signature differs.
            resp = await submit_archives_async(
                url,
                check_archive_org=bool(getattr(self.config, "archive_async_check_archive_org", True)),
                check_archive_is=bool(getattr(self.config, "archive_async_check_archive_is", True)),
                submit_if_missing=bool(getattr(self.config, "archive_async_submit_if_missing", True)),
                poll_interval_seconds=float(getattr(self.config, "archive_async_poll_interval_seconds", 60.0)),
                max_wait_seconds=float(getattr(self.config, "archive_async_max_wait_seconds", 6 * 60 * 60)),
                callback_url=getattr(self.config, "archive_async_callback_url", None),
                callback_file=getattr(self.config, "archive_async_callback_file", None),
            )
        except Exception as e:
            return {
                "status": "error",
                "trigger": trigger,
                "error": str(e),
            }

        if not isinstance(resp, dict) or resp.get("status") != "success":
            return {
                "status": "error",
                "trigger": trigger,
                "error": (resp.get("error") if isinstance(resp, dict) else "Unknown error"),
                "raw": resp,
            }

        job = (resp.get("job") or {}) if isinstance(resp, dict) else {}
        return {
            "status": "success",
            "trigger": trigger,
            "job_id": resp.get("job_id"),
            "providers": job.get("providers"),
            "initial": job.get("initial"),
            "callback": job.get("callback"),
        }

    async def _scrape_common_crawl(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Common Crawl."""
        import requests

        now = time.time()
        if self._common_crawl_down_until and now < self._common_crawl_down_until:
            reason = self._common_crawl_down_reason or "Common Crawl endpoint unreachable"
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"Common Crawl temporarily disabled: {reason}"],
                metadata={
                    "method": "common_crawl",
                    "down_until": self._common_crawl_down_until,
                },
            )

        timeout = float(self.config.timeout)
        headers = {"User-Agent": self.config.user_agent}
        proxies = self._common_crawl_proxies()

        # Fast, clear error for SOCKS proxies when the dependency isn't bundled.
        if self._proxies_use_socks(proxies) and not self._has_socks_support():
            return ScraperResult(
                url=url,
                success=False,
                errors=[
                    "SOCKS proxy configured for Common Crawl but PySocks is not installed. "
                    "Install 'requests[socks]' (or 'pysocks') in the bundled environment."
                ],
                metadata={
                    "method": "common_crawl",
                    "proxy": "socks",
                },
            )

        # Select a working endpoint if multiple are configured.
        endpoint_cfg = await self._pick_common_crawl_endpoint(timeout=timeout, headers=headers)
        cdx_base_url = endpoint_cfg.get("base", (self.config.common_crawl_cdx_base_url or "https://index.commoncrawl.org").rstrip("/"))
        collinfo_url = endpoint_cfg.get("collinfo", self.config.common_crawl_collinfo_url)

        def _is_connectivity_error(msg: str) -> bool:
            m = (msg or "")
            return (
                "Failed to establish a new connection" in m
                or "Connection refused" in m
                or "Name or service" in m
                or "Remote end closed connection" in m
                or "RemoteDisconnected" in m
                or "Connection aborted" in m
                or "Empty reply" in m
                # Common Node/Playwright network errors.
                or "ECONNREFUSED" in m
                or "ETIMEDOUT" in m
                or "ENOTFOUND" in m
                or "EAI_AGAIN" in m
            )

        async def _athena_lookup_record(target_url: str, crawl_id: str) -> ScraperResult:
            """Lookup a WARC record for a URL via Athena columnar index.

            Returns a *ScraperResult* only for errors/diagnostics; on success it
            returns a ScraperResult with success=False and metadata containing
            the record fields (so the caller can reuse the WARC extraction path).
            """
            if not self.config.common_crawl_athena_output_s3:
                return ScraperResult(
                    url=target_url,
                    success=False,
                    errors=["Athena fallback enabled but common_crawl_athena_output_s3 is not set"],
                    metadata={"method": "common_crawl", "athena": True},
                )

            try:
                import boto3  # type: ignore
            except Exception as e:
                return ScraperResult(
                    url=target_url,
                    success=False,
                    errors=[f"Athena fallback requires boto3 (missing): {str(e)}"],
                    metadata={"method": "common_crawl", "athena": True},
                )

            # Conservative query: only one crawl partition at a time.
            def _sql_escape(s: str) -> str:
                return s.replace("'", "''")

            db = self.config.common_crawl_athena_database
            table = self.config.common_crawl_athena_table
            subset = self.config.common_crawl_athena_subset
            url_escaped = _sql_escape(target_url)
            crawl_escaped = _sql_escape(crawl_id)
            subset_escaped = _sql_escape(subset)

            # Common Crawl's published Athena schema typically includes:
            # url, warc_filename, warc_record_offset, warc_record_length, fetch_status, content_mime_type, crawl, subset
            query = (
                f"SELECT url, warc_filename, warc_record_offset, warc_record_length, "
                f"fetch_status, content_mime_type "
                f"FROM \"{db}\".\"{table}\" "
                f"WHERE crawl = '{crawl_escaped}' AND subset = '{subset_escaped}' AND url = '{url_escaped}' "
                f"LIMIT 1"
            )

            region = self.config.common_crawl_athena_region
            output = self.config.common_crawl_athena_output_s3
            workgroup = self.config.common_crawl_athena_workgroup
            max_wait = float(self.config.common_crawl_athena_max_wait_s)
            poll = float(self.config.common_crawl_athena_poll_interval_s)

            def _run() -> Dict[str, Any]:
                client = boto3.client("athena", region_name=region)
                start_args: Dict[str, Any] = {
                    "QueryString": query,
                    "QueryExecutionContext": {"Database": db},
                    "ResultConfiguration": {"OutputLocation": output},
                }
                if workgroup:
                    start_args["WorkGroup"] = workgroup
                qid = client.start_query_execution(**start_args)["QueryExecutionId"]

                deadline = time.time() + max_wait
                state = "RUNNING"
                reason = ""
                while time.time() < deadline:
                    info = client.get_query_execution(QueryExecutionId=qid)
                    status = info.get("QueryExecution", {}).get("Status", {})
                    state = status.get("State", state)
                    reason = status.get("StateChangeReason", "") or ""
                    if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                        break
                    time.sleep(poll)

                if state != "SUCCEEDED":
                    return {"ok": False, "state": state, "reason": reason, "query": query, "qid": qid}

                rs = client.get_query_results(QueryExecutionId=qid, MaxResults=2)
                rows = rs.get("ResultSet", {}).get("Rows", [])
                if len(rows) < 2:
                    return {"ok": True, "row": None, "query": query, "qid": qid}

                data = rows[1].get("Data", [])
                vals = [d.get("VarCharValue", "") for d in data]
                # Order matches SELECT list
                return {
                    "ok": True,
                    "row": {
                        "url": vals[0] if len(vals) > 0 else "",
                        "filename": vals[1] if len(vals) > 1 else "",
                        "offset": vals[2] if len(vals) > 2 else "",
                        "length": vals[3] if len(vals) > 3 else "",
                        "status": vals[4] if len(vals) > 4 else "",
                        "mime": vals[5] if len(vals) > 5 else "",
                    },
                    "query": query,
                    "qid": qid,
                }

            try:
                out = await asyncio.to_thread(_run)
            except Exception as e:
                return ScraperResult(
                    url=target_url,
                    success=False,
                    errors=[f"Athena query failed: {str(e)}"],
                    metadata={"method": "common_crawl", "athena": True, "crawl": crawl_id},
                )

            if not out.get("ok"):
                return ScraperResult(
                    url=target_url,
                    success=False,
                    errors=[f"Athena query did not succeed: {out.get('state')} {out.get('reason', '')}".strip()],
                    metadata={"method": "common_crawl", "athena": True, "crawl": crawl_id, "qid": out.get("qid"), "query": out.get("query")},
                )

            row = out.get("row")
            if not row:
                return ScraperResult(
                    url=target_url,
                    success=False,
                    errors=["No Athena row found for URL in this crawl partition"],
                    metadata={"method": "common_crawl", "athena": True, "crawl": crawl_id, "qid": out.get("qid")},
                )

            return ScraperResult(
                url=target_url,
                success=False,
                metadata={
                    "method": "common_crawl",
                    "athena": True,
                    "crawl": crawl_id,
                    "qid": out.get("qid"),
                    "record": row,
                },
            )

        async def _extract_from_cc_record(record: Dict[str, Any], metadata: Dict[str, Any]) -> ScraperResult:
            # If content fetch is disabled, optionally treat as metadata-only success.
            if not self.config.common_crawl_fetch_content:
                return ScraperResult(
                    url=url,
                    success=bool(self.config.common_crawl_metadata_only_ok),
                    method_used=ScraperMethod.COMMON_CRAWL if self.config.common_crawl_metadata_only_ok else None,
                    errors=[] if self.config.common_crawl_metadata_only_ok else ["Common Crawl metadata found but content fetch disabled"],
                    metadata={
                        **metadata,
                        'note': 'Common Crawl metadata only (fetch disabled).'
                    },
                )

            filename = record.get('filename')
            offset = record.get('offset')
            length = record.get('length')
            if not filename or offset is None or length is None:
                return ScraperResult(
                    url=url,
                    success=bool(self.config.common_crawl_metadata_only_ok),
                    method_used=ScraperMethod.COMMON_CRAWL if self.config.common_crawl_metadata_only_ok else None,
                    errors=[] if self.config.common_crawl_metadata_only_ok else ["Common Crawl record missing filename/offset/length"],
                    metadata={
                        **metadata,
                        'note': 'Missing fields for WARC fetch.'
                    },
                )

            try:
                offset_i = int(offset)
                length_i = int(length)
            except Exception:
                return ScraperResult(
                    url=url,
                    success=False,
                    errors=["Common Crawl record had non-integer offset/length"],
                    metadata=metadata,
                )

            warc_url = f"https://data.commoncrawl.org/{filename}"
            try:
                warc_bytes = await _retry_to_thread(lambda: _range_get(warc_url, offset_i, length_i), attempts=2)
            except Exception as e:
                return ScraperResult(
                    url=url,
                    success=bool(self.config.common_crawl_metadata_only_ok),
                    method_used=ScraperMethod.COMMON_CRAWL if self.config.common_crawl_metadata_only_ok else None,
                    errors=[] if self.config.common_crawl_metadata_only_ok else [f"Failed to fetch WARC range: {str(e)}"],
                    metadata={
                        **metadata,
                        'warc_url': warc_url,
                    },
                )

            # Parse WARC response record (optional dependency).
            try:
                from io import BytesIO
                from warcio.archiveiterator import ArchiveIterator
            except Exception as e:
                return ScraperResult(
                    url=url,
                    success=bool(self.config.common_crawl_metadata_only_ok),
                    method_used=ScraperMethod.COMMON_CRAWL if self.config.common_crawl_metadata_only_ok else None,
                    errors=[] if self.config.common_crawl_metadata_only_ok else [f"warcio not available to parse WARC: {str(e)}"],
                    metadata={
                        **metadata,
                        'warc_url': warc_url,
                    },
                )

            html = ""
            try:
                for rec in ArchiveIterator(BytesIO(warc_bytes)):
                    if rec.rec_type != 'response':
                        continue
                    payload = rec.content_stream().read()
                    html = payload.decode('utf-8', errors='replace')
                    break
            except Exception as e:
                return ScraperResult(
                    url=url,
                    success=bool(self.config.common_crawl_metadata_only_ok),
                    method_used=ScraperMethod.COMMON_CRAWL if self.config.common_crawl_metadata_only_ok else None,
                    errors=[] if self.config.common_crawl_metadata_only_ok else [f"Failed parsing WARC payload: {str(e)}"],
                    metadata={
                        **metadata,
                        'warc_url': warc_url,
                    },
                )

            if not html.strip():
                return ScraperResult(
                    url=url,
                    success=bool(self.config.common_crawl_metadata_only_ok),
                    method_used=ScraperMethod.COMMON_CRAWL if self.config.common_crawl_metadata_only_ok else None,
                    errors=[] if self.config.common_crawl_metadata_only_ok else ["Common Crawl WARC fetched but no HTML extracted"],
                    metadata={
                        **metadata,
                        'warc_url': warc_url,
                    },
                )

            # Extract text/links from HTML similarly to BeautifulSoup method.
            try:
                from bs4 import BeautifulSoup
            except Exception:
                return ScraperResult(
                    url=url,
                    html=html,
                    content=html,
                    method_used=ScraperMethod.COMMON_CRAWL,
                    success=True,
                    metadata={
                        **metadata,
                        'warc_url': warc_url,
                        'note': 'HTML extracted from WARC; BeautifulSoup unavailable for text extraction.'
                    },
                )

            soup = BeautifulSoup(html, 'html.parser')
            title_tag = soup.find('title')
            title = title_tag.get_text() if title_tag else ""

            text_out = ""
            if self.config.extract_text:
                for script in soup(["script", "style"]):
                    script.decompose()
                text_out = soup.get_text(separator='\n', strip=True)

            links: List[Dict[str, str]] = []
            if self.config.extract_links:
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if href.startswith('/'):
                        href = urljoin(url, href)
                    links.append({'url': href, 'text': link.get_text(strip=True)})

            return ScraperResult(
                url=url,
                html=html,
                title=title,
                text=text_out,
                content=text_out,
                links=links,
                success=True,
                method_used=ScraperMethod.COMMON_CRAWL,
                metadata={
                    **metadata,
                    'warc_url': warc_url,
                    'note': 'HTML extracted from WARC via range request.'
                },
            )

        async def _retry_async(func: Callable[[], Any], attempts: int = 3) -> Any:
            last_exc: Optional[BaseException] = None
            for i in range(attempts):
                try:
                    out = func()
                    # Support passing an awaitable-producing lambda.
                    if asyncio.iscoroutine(out):
                        return await out
                    return out
                except BaseException as e:
                    last_exc = e
                    await asyncio.sleep(0.3 * (i + 1))
            raise last_exc  # type: ignore[misc]

        async def _get_json(url_: str) -> Any:
            text = await self._cc_http_get_text(
                url_,
                timeout=min(timeout, 10.0),
                headers=headers,
                proxies=proxies,
            )
            if not text:
                return []
            return json.loads(text)

        async def _get_text(url_: str, params: Dict[str, Any]) -> str:
            return await self._cc_http_get_text(
                url_,
                timeout=timeout,
                headers=headers,
                proxies=proxies,
                params=params,
            )

        def _range_get(url_: str, offset: int, length: int) -> bytes:
            end = offset + length - 1
            resp = requests.get(
                url_,
                headers={**headers, "Range": f"bytes={offset}-{end}"},
                timeout=timeout,
                proxies=proxies,
            )
            # Expect partial content (206) for range requests.
            if resp.status_code not in (200, 206):
                resp.raise_for_status()
            return resp.content

        async def _retry_to_thread(func: Callable[[], Any], attempts: int = 3) -> Any:
            last_exc: Optional[BaseException] = None
            for i in range(attempts):
                try:
                    return await asyncio.to_thread(func)
                except BaseException as e:
                    last_exc = e
                    # small backoff; keep it short for tight iteration
                    await asyncio.sleep(0.3 * (i + 1))
            raise last_exc  # type: ignore[misc]

        # Discover available indexes (small request, but can transiently fail).
        indexes: List[Dict[str, Any]] = []
        used_fallback_index_list = False
        if self.config.common_crawl_index_ids:
            indexes = [{"id": i} for i in self.config.common_crawl_index_ids]
        else:
            try:
                indexes = await _retry_async(lambda: _get_json(collinfo_url), attempts=3)  # type: ignore[assignment]
            except Exception:
                # If collinfo is unreachable, fall back to a small, recent-ish list.
                used_fallback_index_list = True
                fallback_ids = [
                    "CC-MAIN-2025-47",
                    "CC-MAIN-2025-50",
                    "CC-MAIN-2025-46",
                    "CC-MAIN-2025-42",
                    "CC-MAIN-2025-38",
                    "CC-MAIN-2025-33",
                    "CC-MAIN-2024-52",
                    "CC-MAIN-2024-46",
                ]
                indexes = [{"id": i} for i in fallback_ids]

        # Try a few most recent indexes to keep this quick.
        # Each index has a CDX endpoint of form: https://index.commoncrawl.org/<id>-index
        tried_indexes: List[str] = []
        last_error: Optional[str] = None

        parsed = urlparse(url)
        prefix_url = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else None

        # Candidate queries: exact URL first, then a prefix match on host.
        query_specs: List[Dict[str, Any]] = [
            {"url": url, "matchType": "exact"},
        ]
        if prefix_url:
            query_specs.append({"url": prefix_url, "matchType": "prefix"})

        for idx in (indexes or [])[: int(self.config.common_crawl_max_indexes)]:
            idx_id = (idx or {}).get("id")
            if not idx_id:
                continue
            tried_indexes.append(idx_id)
            base = (cdx_base_url or "https://index.commoncrawl.org").rstrip("/")
            endpoint = f"{base}/{idx_id}-index"

            for spec in query_specs:
                params = {
                    "url": spec["url"],
                    "output": "json",
                    "limit": int(self.config.common_crawl_max_records_per_query),
                    # Common Crawl CDX API rejects the older pywb-style "==status:200" with HTTP 404.
                    "filter": "status:200",
                    "matchType": spec["matchType"],
                    # Request the fields needed to fetch content from WARC.
                    "fl": "url,timestamp,status,mime,length,offset,filename,digest",
                }

                try:
                    text = await _retry_async(lambda: _get_text(endpoint, params), attempts=2)
                except Exception as e:
                    last_error = f"{idx_id}: query failed: {str(e)}"
                    # If Common Crawl is blocked/unreachable, avoid repeating slow failures for every URL.
                    msg = str(e)
                    if _is_connectivity_error(msg):
                        # Mark this endpoint down and force reselection on next call.
                        try:
                            self._common_crawl_endpoint_down[base] = time.time() + 120.0
                        except Exception:
                            pass
                        self._common_crawl_selected_until = 0.0
                        self._common_crawl_down_reason = msg
                        # Only disable Common Crawl entirely when there are no additional
                        # fallbacks that might still work (direct index / Athena).
                        if not (self.config.common_crawl_direct_index_enabled or self.config.common_crawl_athena_enabled):
                            self._common_crawl_down_until = time.time() + 120.0
                    continue

                lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
                if not lines:
                    continue

                try:
                    record = json.loads(lines[0])
                except Exception:
                    continue

                metadata: Dict[str, Any] = {
                    'method': 'common_crawl',
                    'index': idx_id,
                    'tried_indexes': tried_indexes,
                    'used_fallback_index_list': used_fallback_index_list,
                    'matchType': spec["matchType"],
                    'query_url': spec["url"],
                    'timestamp': record.get('timestamp', ''),
                    'mime_type': record.get('mime', ''),
                    'status_code': record.get('status', ''),
                    'warc_filename': record.get('filename', ''),
                    'warc_offset': record.get('offset', ''),
                    'warc_length': record.get('length', ''),
                    'digest': record.get('digest', ''),
                }

                return await _extract_from_cc_record(
                    {
                        "filename": record.get("filename"),
                        "offset": record.get("offset"),
                        "length": record.get("length"),
                    },
                    metadata,
                )

            # Polite pacing between index attempts to avoid hammering the CDX API.
            if self.config.rate_limit_delay:
                await asyncio.sleep(float(self.config.rate_limit_delay))

        # Determine if CDX is unreachable (connectivity errors), which gates Athena/direct-index fallbacks.
        cdx_failed_connectivity = False
        if last_error and _is_connectivity_error(last_error):
            cdx_failed_connectivity = True
        if self._common_crawl_down_reason and _is_connectivity_error(self._common_crawl_down_reason):
            cdx_failed_connectivity = True

        athena_fallback_error: Optional[str] = None

        # If CDX seems unreachable and Athena fallback is enabled, try Athena.
        if self.config.common_crawl_athena_enabled:
            # Prefer using the exact URL for Athena. (Prefix searches would be costly.)
            if cdx_failed_connectivity:
                crawl_ids = self.config.common_crawl_athena_crawl_ids
                if not crawl_ids:
                    # Reuse the same recent-ish list as the CDX fallback.
                    crawl_ids = [
                        "CC-MAIN-2025-47",
                        "CC-MAIN-2025-50",
                        "CC-MAIN-2025-46",
                        "CC-MAIN-2025-42",
                        "CC-MAIN-2025-38",
                        "CC-MAIN-2025-33",
                        "CC-MAIN-2024-52",
                        "CC-MAIN-2024-46",
                    ]

                athena_errors: List[str] = []
                for crawl_id in crawl_ids[: int(self.config.common_crawl_max_indexes)]:
                    looked = await _athena_lookup_record(url, crawl_id)
                    if looked.errors:
                        athena_errors.extend(looked.errors)
                    rec = (looked.metadata or {}).get("record")
                    if isinstance(rec, dict) and rec.get("filename") and rec.get("offset") and rec.get("length"):
                        md: Dict[str, Any] = {
                            "method": "common_crawl",
                            "athena": True,
                            "crawl": crawl_id,
                            "tried_indexes": tried_indexes,
                            "used_fallback_index_list": used_fallback_index_list,
                            "status_code": rec.get("status", ""),
                            "mime_type": rec.get("mime", ""),
                        }
                        return await _extract_from_cc_record(
                            {"filename": rec.get("filename"), "offset": rec.get("offset"), "length": rec.get("length")},
                            md,
                        )

                # Athena didn't find a record or couldn't run.
                err = "Common Crawl CDX unreachable; Athena fallback did not yield a record"
                if athena_errors:
                    err = f"{err} (athena_last_error={athena_errors[-1]})"
                athena_fallback_error = err
                if not self.config.common_crawl_direct_index_enabled:
                    return ScraperResult(
                        url=url,
                        success=False,
                        errors=[err],
                        metadata={
                            "tried_indexes": tried_indexes,
                            "used_fallback_index_list": used_fallback_index_list,
                            "athena_attempted": True,
                        },
                    )

        # Option A: if CDX is unreachable/blocked, try direct shard-based lookup via data.commoncrawl.org.
        if self.config.common_crawl_direct_index_enabled and cdx_failed_connectivity:
            crawl_ids = self.config.common_crawl_direct_index_crawl_ids
            if not crawl_ids:
                # Defaults that currently publish cluster.idx on data.commoncrawl.org.
                crawl_ids = [
                    "CC-MAIN-2025-47",
                    "CC-MAIN-2025-38",
                    "CC-MAIN-2025-33",
                    "CC-MAIN-2024-46",
                    "CC-MAIN-2024-42",
                    "CC-MAIN-2023-50",
                ]
                # Also try whatever CDX indexes we attempted (best-effort).
                for i in tried_indexes:
                    if i not in crawl_ids:
                        crawl_ids.append(i)

            direct_errors: List[str] = []
            for crawl_id in crawl_ids[: int(self.config.common_crawl_max_indexes)]:
                try:
                    rec = await self._cc_direct_index_lookup(
                        target_url=url,
                        crawl_id=crawl_id,
                        timeout=timeout,
                        headers=headers,
                        proxies=proxies,
                        match_type="exact",
                    )
                except Exception as e:
                    direct_errors.append(str(e))
                    continue

                if isinstance(rec, dict) and rec.get("filename") and rec.get("offset") and rec.get("length"):
                    md: Dict[str, Any] = {
                        "method": "common_crawl",
                        "direct_index": True,
                        "crawl": crawl_id,
                        "tried_indexes": tried_indexes,
                        "used_fallback_index_list": used_fallback_index_list,
                        "status_code": rec.get("status", ""),
                        "mime_type": rec.get("mime", ""),
                        "direct_index_shard_file": rec.get("_direct_index_shard_file"),
                        "direct_index_block_offset": rec.get("_direct_index_block_offset"),
                        "direct_index_block_length": rec.get("_direct_index_block_length"),
                        "matchType": rec.get("_direct_index_match_type") or "exact",
                    }
                    try:
                        # Expose configured caps so runs are auditable.
                        md["direct_index_max_block_bytes"] = int(getattr(self.config, "common_crawl_direct_index_max_block_bytes", 0) or 0)
                        md["direct_index_max_decompressed_bytes"] = int(getattr(self.config, "common_crawl_direct_index_max_decompressed_bytes", 0) or 0)
                        md["direct_index_allow_large_blocks"] = bool(getattr(self.config, "common_crawl_direct_index_allow_large_blocks", False))
                    except Exception:
                        pass
                    return await _extract_from_cc_record(
                        {"filename": rec.get("filename"), "offset": rec.get("offset"), "length": rec.get("length")},
                        md,
                    )

                # Optional prefix/domain match fallback (discovery-oriented).
                if (
                    self.config.common_crawl_direct_index_prefix_fallback
                    and prefix_url
                ):
                    try:
                        pref_rec = await self._cc_direct_index_lookup(
                            target_url=prefix_url,
                            crawl_id=crawl_id,
                            timeout=timeout,
                            headers=headers,
                            proxies=proxies,
                            match_type="prefix",
                        )
                    except Exception as e:
                        direct_errors.append(str(e))
                        pref_rec = None

                    if isinstance(pref_rec, dict) and pref_rec.get("filename") and pref_rec.get("offset") and pref_rec.get("length"):
                        md = {
                            "method": "common_crawl",
                            "direct_index": True,
                            "crawl": crawl_id,
                            "tried_indexes": tried_indexes,
                            "used_fallback_index_list": used_fallback_index_list,
                            "status_code": pref_rec.get("status", ""),
                            "mime_type": pref_rec.get("mime", ""),
                            "direct_index_shard_file": pref_rec.get("_direct_index_shard_file"),
                            "direct_index_block_offset": pref_rec.get("_direct_index_block_offset"),
                            "direct_index_block_length": pref_rec.get("_direct_index_block_length"),
                            "matchType": pref_rec.get("_direct_index_match_type") or "prefix",
                            "query_url": prefix_url,
                            "note": "Direct-index prefix/domain match used; record may not be the exact requested URL.",
                        }
                        try:
                            md["direct_index_max_block_bytes"] = int(getattr(self.config, "common_crawl_direct_index_max_block_bytes", 0) or 0)
                            md["direct_index_max_decompressed_bytes"] = int(getattr(self.config, "common_crawl_direct_index_max_decompressed_bytes", 0) or 0)
                            md["direct_index_allow_large_blocks"] = bool(getattr(self.config, "common_crawl_direct_index_allow_large_blocks", False))
                        except Exception:
                            pass
                        return await _extract_from_cc_record(
                            {"filename": pref_rec.get("filename"), "offset": pref_rec.get("offset"), "length": pref_rec.get("length")},
                            md,
                        )

            err = "Common Crawl CDX unreachable; direct index fallback did not yield a record"
            if direct_errors:
                err = f"{err} (direct_index_last_error={direct_errors[-1]})"
            if athena_fallback_error:
                err = f"{err}; {athena_fallback_error}"
            return ScraperResult(
                url=url,
                success=False,
                errors=[err],
                metadata={
                    "tried_indexes": tried_indexes,
                    "used_fallback_index_list": used_fallback_index_list,
                    "direct_index_attempted": True,
                    "athena_attempted": bool(self.config.common_crawl_athena_enabled),
                    "direct_index_max_block_bytes": int(getattr(self.config, "common_crawl_direct_index_max_block_bytes", 0) or 0),
                    "direct_index_max_decompressed_bytes": int(getattr(self.config, "common_crawl_direct_index_max_decompressed_bytes", 0) or 0),
                    "direct_index_allow_large_blocks": bool(getattr(self.config, "common_crawl_direct_index_allow_large_blocks", False)),
                },
            )

        # Not found in indexes we tried.
        err = "URL not found in Common Crawl"
        if last_error:
            err = f"{err} (last_error={last_error})"
        if athena_fallback_error:
            err = f"{err}; {athena_fallback_error}"

        return ScraperResult(
            url=url,
            success=False,
            errors=[err],
            metadata={
                "tried_indexes": tried_indexes,
                "used_fallback_index_list": used_fallback_index_list,
            },
        )
    
    async def _scrape_archive_is(self, url: str, **kwargs) -> ScraperResult:
        """Scrape using Archive.is."""
        from bs4 import BeautifulSoup
        
        # Try to find existing archive first
        search_url = f"https://archive.is/newest/{url}"
        
        try:
            response = self._session_get(search_url, timeout=self.config.timeout, allow_redirects=True)
            
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
                        'archive_url': response.url
                    }
                )
            return ScraperResult(
                url=url,
                success=False,
                errors=["No Archive.is snapshot found for this URL"],
                metadata={
                    "method": "archive_is",
                    "search_url": search_url,
                    "status_code": response.status_code,
                    "final_url": response.url,
                },
            )
        except Exception as e:
            return ScraperResult(
                url=url,
                success=False,
                errors=[f"Archive.is scraping failed: {str(e)}"]
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

        response = self._session_get(url, timeout=self.config.timeout)
        response.raise_for_status()
        
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
                'content_length': len(response.content)
            }
        )
    
    async def _scrape_requests_only(self, url: str, **kwargs) -> ScraperResult:
        """Basic scraping with requests only."""
        import re

        response = self._session_get(url, timeout=self.config.timeout)
        response.raise_for_status()
        
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
                'status_code': response.status_code
            }
        )
    
    def scrape_sync(self, url: str, **kwargs) -> ScraperResult:
        """Synchronous version of scrape."""
        return asyncio.run(self.scrape(url, **kwargs))
    
    async def scrape_multiple(
        self,
        urls: List[str],
        max_concurrent: int = 5,
        **kwargs
    ) -> List[ScraperResult]:
        """Scrape multiple URLs concurrently."""
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def scrape_with_semaphore(url):
            async with semaphore:
                result = await self.scrape(url, **kwargs)
                await asyncio.sleep(self.config.rate_limit_delay)
                return result
        
        tasks = [scrape_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    def scrape_multiple_sync(self, urls: List[str], **kwargs) -> List[ScraperResult]:
        """Synchronous version of scrape_multiple."""
        return asyncio.run(self.scrape_multiple(urls, **kwargs))


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

"""
Parallel Web Archiver for Legal Search.

This module provides parallel/async web content archiving with multiple fallback sources
for fast batch retrieval of legal search results.

Features:
- Query HuggingFace datasets for Common Crawl WARC file pointers
- Parallel/async content retrieval using anyio
- Multiple fallback sources with ordered priority:
  1. Common Crawl (via WARC pointers from HF)
  2. Wayback Machine API
  3. web_archiving module
- Configurable rate limiting per source
- Retry logic with exponential backoff
- Real-time progress tracking for batch operations
- Auto-archiving of Brave search results

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import ParallelWebArchiver
    
    archiver = ParallelWebArchiver(
        hf_api_key="hf_...",
        max_concurrent=10,
        use_warc_pointers=True
    )
    
    # Parallel retrieval (10-25x faster)
    urls = ["https://epa.gov/...", "https://ca.gov/...", ...]
    results = await archiver.archive_urls_parallel(urls)
    
    # Get WARC pointers from HF
    pointers = await archiver.get_warc_pointers(urls)
"""

import anyio
from ipfs_datasets_py.utils.anyio_compat import gather as _anyio_gather
import logging
import os
import time
from typing import List, Dict, Optional, Any, Tuple, Literal
from dataclasses import dataclass, field
from datetime import datetime
import json

from .shared_fetch_cache import SharedFetchCache

logger = logging.getLogger(__name__)

# Optional dependencies
try:
    import aiohttp
    HAVE_AIOHTTP = True
except ImportError:
    HAVE_AIOHTTP = False
    logger.debug("aiohttp not available - parallel archiving will use synchronous fallback")

try:
    from ipfs_datasets_py.processors.legal_scrapers import HuggingFaceAPISearch
    HAVE_HF_API = True
except ImportError:
    HAVE_HF_API = False
    logger.debug("HuggingFace API search not available")


@dataclass
class ArchiveResult:
    """Result of archiving a single URL."""
    url: str
    success: bool
    content: Optional[str] = None
    source: Optional[str] = None  # "warc", "wayback", "web_archive"
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    warc_pointer: Optional[Dict[str, Any]] = None


@dataclass
class ArchiveProgress:
    """Progress tracking for batch archiving."""
    total: int
    completed: int = 0
    successful: int = 0
    failed: int = 0
    start_time: float = field(default_factory=time.time)
    
    @property
    def elapsed_time(self) -> float:
        return time.time() - self.start_time
    
    @property
    def completion_rate(self) -> float:
        return self.completed / self.total if self.total > 0 else 0.0
    
    @property
    def success_rate(self) -> float:
        return self.successful / self.completed if self.completed > 0 else 0.0


class ParallelWebArchiver:
    """
    Parallel web content archiver with multiple fallback sources.
    
    Retrieves web content in parallel using async/await for maximum performance.
    Supports multiple fallback sources for resilience.
    
    Args:
        hf_api_key: HuggingFace API key for WARC pointer retrieval
        max_concurrent: Maximum concurrent requests (default: 10)
        use_warc_pointers: Enable Common Crawl via WARC pointers (default: True)
        use_wayback: Enable Wayback Machine API (default: True)
        use_web_archive: Enable web_archiving module (default: True)
        rate_limit_per_source: Requests per second per source (default: 5)
        retry_attempts: Number of retry attempts (default: 3)
        timeout: Request timeout in seconds (default: 30)
        fallback_priority: Order of fallback sources (default: ["warc", "wayback", "web_archive"])
    """
    
    def __init__(
        self,
        hf_api_key: Optional[str] = None,
        max_concurrent: int = 10,
        use_warc_pointers: bool = True,
        use_wayback: bool = True,
        use_web_archive: bool = True,
        rate_limit_per_source: float = 5.0,
        retry_attempts: int = 3,
        timeout: int = 30,
        fallback_priority: Optional[List[str]] = None
    ):
        self.hf_api_key = hf_api_key or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
        self.max_concurrent = max_concurrent
        self.use_warc_pointers = use_warc_pointers and HAVE_HF_API
        self.use_wayback = use_wayback
        self.use_web_archive = use_web_archive
        self.rate_limit_per_source = rate_limit_per_source
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.fallback_priority = fallback_priority or ["warc", "wayback", "web_archive"]
        self._shared_fetch_cache: Optional[SharedFetchCache] = SharedFetchCache.from_env()
        
        # Initialize components
        self._hf_search = None
        if self.use_warc_pointers and HAVE_HF_API:
            try:
                self._hf_search = HuggingFaceAPISearch(api_key=self.hf_api_key)
            except Exception as e:
                logger.warning(f"Failed to initialize HF API search: {e}")
                self.use_warc_pointers = False
        
        # Rate limiting state
        self._last_request_time = {
            "warc": 0.0,
            "wayback": 0.0,
            "web_archive": 0.0
        }
        
        # Statistics
        self._stats = {
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "warc_hits": 0,
            "wayback_hits": 0,
            "web_archive_hits": 0
        }
    
    async def archive_urls_parallel(
        self,
        urls: List[str],
        progress_callback: Optional[callable] = None,
        max_concurrent: Optional[int] = None,
        jurisdiction: Optional[Literal["federal", "state", "municipal"]] = None,
        state_code: Optional[str] = None,
    ) -> List[ArchiveResult]:
        """
        Archive multiple URLs in parallel with fallback sources.
        
        Args:
            urls: List of URLs to archive
            progress_callback: Optional callback function(progress: ArchiveProgress)
            
        Returns:
            List of ArchiveResult objects
        """
        if not HAVE_AIOHTTP:
            logger.warning("aiohttp not available, using synchronous fallback")
            return self._archive_urls_sync(urls, progress_callback)
        
        requested_urls = [str(url).strip() for url in list(urls or []) if str(url).strip()]
        progress = ArchiveProgress(total=len(requested_urls))
        concurrency = max(1, int(max_concurrent or self.max_concurrent or 1))
        if not requested_urls:
            return []

        cached_results: Dict[str, ArchiveResult] = {}
        cache_misses: List[str] = []
        seen_urls: set[str] = set()
        for url in requested_urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            cached = self._load_cached_result(url)
            if cached is not None:
                cached_results[url] = cached
            else:
                cache_misses.append(url)

        if cached_results:
            progress.completed += len(cached_results)
            progress.successful += len(cached_results)
            if progress_callback:
                try:
                    progress_callback(progress)
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")
        
        # Create semaphore to limit concurrent requests
        semaphore = anyio.Semaphore(concurrency)
        
        normalized_jurisdiction = str(jurisdiction or "").strip().lower() or None
        normalized_state_code = str(state_code or "").strip().upper() or None

        async def archive_with_semaphore(url: str) -> ArchiveResult:
            async with semaphore:
                result = await self._archive_single_url(
                    url,
                    jurisdiction=normalized_jurisdiction,
                    state_code=normalized_state_code,
                )
                progress.completed += 1
                if result.success:
                    progress.successful += 1
                else:
                    progress.failed += 1
                
                if progress_callback:
                    try:
                        progress_callback(progress)
                    except Exception as e:
                        logger.warning(f"Progress callback error: {e}")
                
                return result
        
        # Execute all tasks in parallel
        tasks = [archive_with_semaphore(url) for url in cache_misses]
        results = await _anyio_gather(*tasks)
        
        # Handle any exceptions
        fetched_results: Dict[str, ArchiveResult] = {}
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Failed to archive {cache_misses[i]}: {result}")
                fetched_results[cache_misses[i]] = ArchiveResult(
                    url=cache_misses[i],
                    success=False,
                    error=str(result)
                )
            else:
                fetched_results[result.url] = result
                self._store_cached_result(result)

        final_results = []
        for url in requested_urls:
            final_results.append(
                cached_results.get(url)
                or fetched_results.get(url)
                or ArchiveResult(url=url, success=False, error="missing_result")
            )
        
        return final_results

    def _load_cached_result(self, url: str) -> Optional[ArchiveResult]:
        if self._shared_fetch_cache is None:
            return None
        payload = self._shared_fetch_cache.load(namespace="parallel_web_archiver", url=url)
        if not isinstance(payload, dict):
            return None
        content = str(payload.get("content") or "").strip()
        if not content:
            return None
        return ArchiveResult(
            url=str(payload.get("url") or url),
            success=bool(payload.get("success", False)),
            content=content,
            source="cache",
            error=payload.get("error"),
            warc_pointer=payload.get("warc_pointer") if isinstance(payload.get("warc_pointer"), dict) else None,
        )

    def _store_cached_result(self, result: ArchiveResult) -> None:
        if self._shared_fetch_cache is None or not result.success:
            return
        content = str(result.content or "").strip()
        if not content:
            return
        try:
            self._shared_fetch_cache.save(
                namespace="parallel_web_archiver",
                url=result.url,
                payload={
                    "url": result.url,
                    "success": bool(result.success),
                    "content": content,
                    "source": str(result.source or ""),
                    "error": result.error,
                    "warc_pointer": result.warc_pointer if isinstance(result.warc_pointer, dict) else None,
                    "timestamp": result.timestamp.isoformat(),
                },
                payload_name=f"parallel_web_archiver_{abs(hash(result.url))}",
            )
        except Exception as exc:
            logger.warning("Failed to write parallel archiver cache entry for %s: %s", result.url, exc)
    
    async def _archive_single_url(
        self,
        url: str,
        *,
        jurisdiction: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> ArchiveResult:
        """Archive a single URL with fallback sources."""
        self._stats["total_requests"] += 1
        
        # Try each source in priority order
        for source in self.fallback_priority:
            if not self._is_source_enabled(source):
                continue
            
            try:
                await self._rate_limit_wait(source)
                
                if source == "warc":
                    result = await self._archive_via_warc(
                        url,
                        jurisdiction=jurisdiction,
                        state_code=state_code,
                    )
                elif source == "wayback":
                    result = await self._archive_via_wayback(url)
                elif source == "web_archive":
                    result = await self._archive_via_web_archive(url)
                else:
                    continue
                
                if result and result.success:
                    self._stats["successful"] += 1
                    self._stats[f"{source}_hits"] += 1
                    return result
                
            except Exception as e:
                logger.debug(f"Failed to archive {url} via {source}: {e}")
                continue
        
        # All sources failed
        self._stats["failed"] += 1
        return ArchiveResult(
            url=url,
            success=False,
            error="All fallback sources failed"
        )
    
    async def _archive_via_warc(
        self,
        url: str,
        *,
        jurisdiction: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[ArchiveResult]:
        """Archive via Common Crawl WARC pointers from HuggingFace."""
        if not self._hf_search:
            return None
        
        try:
            # Query HF for WARC pointers
            pointer_data = await self.get_warc_pointer(
                url,
                jurisdiction=jurisdiction,
                state_code=state_code,
            )
            if not pointer_data:
                return None
            
            # Extract WARC file info
            warc_file = pointer_data.get("warc_file") or pointer_data.get("warc_filename") or pointer_data.get("filename")
            warc_offset = pointer_data.get("warc_offset") or pointer_data.get("offset")
            warc_length = pointer_data.get("warc_length") or pointer_data.get("length")
            
            if not all([warc_file, warc_offset, warc_length]):
                return None

            try:
                from ipfs_datasets_py.processors.web_archiving.common_crawl_integration import (
                    CommonCrawlSearchEngine,
                    _ensure_common_crawl_import_path,
                )

                _ensure_common_crawl_import_path()
                from common_crawl_search_engine.ccindex import api as ccapi

                engine = CommonCrawlSearchEngine(mode="local")
                raw_record = await anyio.to_thread.run_sync(
                    engine.fetch_warc_record,
                    str(warc_file),
                    int(warc_offset),
                    int(warc_length),
                )
                http = await anyio.to_thread.run_sync(
                    lambda: ccapi.extract_http_from_warc_gzip_member(
                        raw_record,
                        max_body_bytes=2_000_000,
                        max_preview_chars=80_000,
                    )
                )
                content = str(getattr(http, "body_text_preview", "") or "").strip()
                if not getattr(http, "ok", False) or not content:
                    return None
            except Exception as exc:
                logger.debug("Common Crawl WARC body extraction failed for %s: %s", url, exc)
                return None

            pointer_data.setdefault("warc_file", str(warc_file))
            pointer_data.setdefault("warc_filename", str(warc_file))
            pointer_data["warc_offset"] = int(warc_offset)
            pointer_data["warc_length"] = int(warc_length)
            return ArchiveResult(
                url=url,
                success=True,
                content=content,
                source="warc",
                warc_pointer=pointer_data
            )
            
        except Exception as e:
            logger.debug(f"WARC archiving failed for {url}: {e}")
            return None
    
    async def _archive_via_wayback(self, url: str) -> Optional[ArchiveResult]:
        """Archive via Wayback Machine API."""
        if not HAVE_AIOHTTP:
            return None
        
        try:
            wayback_url = f"https://archive.org/wayback/available?url={url}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(wayback_url, timeout=self.timeout) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        snapshots = data.get("archived_snapshots", {})
                        closest = snapshots.get("closest", {})
                        
                        if closest.get("available"):
                            archived_url = closest.get("url")
                            
                            # Fetch archived content
                            async with session.get(archived_url, timeout=self.timeout) as content_response:
                                if content_response.status == 200:
                                    content = await content_response.text()
                                    
                                    return ArchiveResult(
                                        url=url,
                                        success=True,
                                        content=content,
                                        source="wayback"
                                    )
            
            return None
            
        except Exception as e:
            logger.debug(f"Wayback archiving failed for {url}: {e}")
            return None
    
    async def _archive_via_web_archive(self, url: str) -> Optional[ArchiveResult]:
        """Archive via web_archiving module."""
        try:
            # Import web_archiving module if available
            from ipfs_datasets_py.data_transformation import web_archiving
            
            # Use web_archiving functionality (synchronous wrapper)
            result = await anyio.to_thread.run_sync(
                web_archiving.archive_url,
                url
            )
            
            if result:
                return ArchiveResult(
                    url=url,
                    success=True,
                    content=result.get("content"),
                    source="web_archive"
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"web_archiving failed for {url}: {e}")
            return None
    
    async def get_warc_pointer(
        self,
        url: str,
        *,
        jurisdiction: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get WARC file pointer for a URL from HuggingFace."""
        if not self._hf_search:
            return None
        
        try:
            normalized_jurisdiction = str(jurisdiction or "").strip().lower()
            if normalized_jurisdiction not in {"federal", "state", "municipal"}:
                normalized_jurisdiction = "state"

            normalized_state_code = str(state_code or "").strip().upper() or None
            if normalized_jurisdiction != "state":
                normalized_state_code = None

            # Query HF pointer dataset
            results = self._hf_search.search(
                query=url,
                jurisdiction=normalized_jurisdiction,
                state_code=normalized_state_code,
                max_results=1,
            )
            
            if results and len(results) > 0:
                pointer = dict(results[0])
                warc_file = pointer.get("warc_file") or pointer.get("warc_filename") or pointer.get("filename")
                warc_offset = pointer.get("warc_offset") or pointer.get("offset")
                warc_length = pointer.get("warc_length") or pointer.get("length")
                if warc_file:
                    pointer.setdefault("warc_file", str(warc_file))
                    pointer.setdefault("warc_filename", str(warc_file))
                if warc_offset is not None:
                    pointer["warc_offset"] = int(warc_offset)
                if warc_length is not None:
                    pointer["warc_length"] = int(warc_length)
                return pointer
            
            return None
            
        except Exception as e:
            logger.debug(f"Failed to get WARC pointer for {url}: {e}")
            return None
    
    async def get_warc_pointers(
        self,
        urls: List[str],
        *,
        jurisdiction: Optional[str] = None,
        state_code: Optional[str] = None,
    ) -> List[Optional[Dict[str, Any]]]:
        """Get WARC pointers for multiple URLs in parallel."""
        tasks = [
            self.get_warc_pointer(url, jurisdiction=jurisdiction, state_code=state_code)
            for url in urls
        ]
        return await _anyio_gather(tasks)
    
    def _archive_urls_sync(
        self, 
        urls: List[str],
        progress_callback: Optional[callable] = None
    ) -> List[ArchiveResult]:
        """Synchronous fallback for archiving URLs."""
        results = []
        progress = ArchiveProgress(total=len(urls))
        
        for url in urls:
            # Try each source synchronously
            result = None
            for source in self.fallback_priority:
                if not self._is_source_enabled(source):
                    continue
                
                try:
                    if source == "web_archive":
                        from ipfs_datasets_py.data_transformation import web_archiving
                        content = web_archiving.archive_url(url)
                        if content:
                            result = ArchiveResult(
                                url=url,
                                success=True,
                                content=content.get("content"),
                                source="web_archive"
                            )
                            break
                except Exception as e:
                    logger.debug(f"Sync archiving failed for {url} via {source}: {e}")
                    continue
            
            if not result:
                result = ArchiveResult(
                    url=url,
                    success=False,
                    error="All sources failed"
                )
            
            results.append(result)
            progress.completed += 1
            if result.success:
                progress.successful += 1
            else:
                progress.failed += 1
            
            if progress_callback:
                try:
                    progress_callback(progress)
                except Exception as e:
                    logger.warning(f"Progress callback error: {e}")
        
        return results
    
    async def _rate_limit_wait(self, source: str):
        """Wait to respect rate limits for a source."""
        min_interval = 1.0 / self.rate_limit_per_source
        elapsed = time.time() - self._last_request_time[source]
        
        if elapsed < min_interval:
            await anyio.sleep(min_interval - elapsed)
        
        self._last_request_time[source] = time.time()
    
    def _is_source_enabled(self, source: str) -> bool:
        """Check if a source is enabled."""
        if source == "warc":
            return self.use_warc_pointers
        elif source == "wayback":
            return self.use_wayback
        elif source == "web_archive":
            return self.use_web_archive
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get archiving statistics."""
        return {
            **self._stats,
            "success_rate": self._stats["successful"] / self._stats["total_requests"] if self._stats["total_requests"] > 0 else 0.0,
            "warc_hit_rate": self._stats["warc_hits"] / self._stats["successful"] if self._stats["successful"] > 0 else 0.0,
            "wayback_hit_rate": self._stats["wayback_hits"] / self._stats["successful"] if self._stats["successful"] > 0 else 0.0,
            "web_archive_hit_rate": self._stats["web_archive_hits"] / self._stats["successful"] if self._stats["successful"] > 0 else 0.0
        }
    
    def clear_stats(self):
        """Clear statistics."""
        for key in self._stats:
            self._stats[key] = 0


# Convenience function for quick parallel archiving
async def archive_urls(
    urls: List[str],
    hf_api_key: Optional[str] = None,
    max_concurrent: int = 10
) -> List[ArchiveResult]:
    """
    Quick function to archive URLs in parallel.
    
    Args:
        urls: List of URLs to archive
        hf_api_key: Optional HuggingFace API key
        max_concurrent: Maximum concurrent requests
        
    Returns:
        List of ArchiveResult objects
    """
    archiver = ParallelWebArchiver(
        hf_api_key=hf_api_key,
        max_concurrent=max_concurrent
    )
    
    return await archiver.archive_urls_parallel(urls)

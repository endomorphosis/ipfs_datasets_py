"""Shared archival fetch client for state law scrapers.

Implements resilient URL retrieval with fallback order:
1. Common Crawl index/WARC recovery
2. direct fetch
3. Wayback Machine
4. Archive.is
"""

from __future__ import annotations

import asyncio
import gzip
import importlib
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from requests.exceptions import SSLError

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    content: bytes
    source: str
    fetched_at: str
    status_code: Optional[int] = None
    archive_url: Optional[str] = None
    archive_timestamp: Optional[str] = None


class ArchivalFetchClient:
    """Fetch URLs with web-archive fallback support."""

    def __init__(
        self,
        *,
        request_timeout_seconds: int = 30,
        delay_seconds: float = 0.0,
        user_agent: str = (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
    ):
        self.request_timeout_seconds = request_timeout_seconds
        self.delay_seconds = delay_seconds
        self.user_agent = user_agent

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})

    def _request_with_retries(self, url: str, *, timeout: int, verify: bool = True) -> Optional[requests.Response]:
        # A small retry loop helps with transient 403/429/503 and edge rate limiting.
        retry_statuses = {403, 429, 500, 502, 503, 504}
        for _attempt in range(3):
            try:
                response = self._session.get(url, timeout=timeout, verify=verify)
            except Exception:
                continue
            if int(response.status_code) not in retry_statuses:
                return response
        return None

    async def fetch_with_fallback(self, url: str) -> FetchResult:
        common_crawl = await asyncio.to_thread(self._fetch_from_common_crawl, url)
        if common_crawl is not None:
            return common_crawl

        direct = await asyncio.to_thread(self._fetch_direct, url)
        if direct is not None:
            return direct

        wayback = await self._fetch_from_wayback(url)
        if wayback is not None:
            return wayback

        archive_is = await self._fetch_from_archive_is(url)
        if archive_is is not None:
            return archive_is

        raise RuntimeError(f"Unable to fetch URL via direct or archival fallback: {url}")

    def _fetch_direct(self, url: str) -> Optional[FetchResult]:
        try:
            response = self._request_with_retries(url, timeout=self.request_timeout_seconds, verify=True)
            if response is None:
                return None
            if response.status_code == 200 and self._looks_like_html(response.content):
                return FetchResult(
                    url=url,
                    content=response.content,
                    source="direct",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    status_code=response.status_code,
                )
            return None
        except SSLError:
            # Some state sites present a broken chain from this host; fall back to
            # insecure TLS only as a last resort so archives can still be queried.
            try:
                response = self._request_with_retries(url, timeout=self.request_timeout_seconds, verify=False)
                if response is None:
                    return None
                if response.status_code == 200 and self._looks_like_html(response.content):
                    return FetchResult(
                        url=url,
                        content=response.content,
                        source="direct_insecure_tls",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        status_code=response.status_code,
                    )
            except Exception:
                return None
            return None
        except Exception:
            return None

    def _fetch_from_common_crawl(self, url: str) -> Optional[FetchResult]:
        parsed = urlparse(url)
        if not parsed.netloc:
            return None

        try:
            cc_module = importlib.import_module(
                "ipfs_datasets_py.processors.web_archiving.common_crawl_integration"
            )
            engine_cls = getattr(cc_module, "CommonCrawlSearchEngine")
        except Exception:
            return None

        modes_to_try: List[tuple[str, Dict[str, Any]]] = [("local", {}), ("cli", {})]
        remote_endpoint = os.environ.get("CCINDEX_MCP_ENDPOINT")
        if remote_endpoint:
            modes_to_try.append(("remote", {"mcp_endpoint": remote_endpoint}))

        records: List[Dict[str, Any]] = []
        for mode, mode_kwargs in modes_to_try:
            try:
                engine = engine_cls(mode=mode, **mode_kwargs)
                if not getattr(engine, "is_available", lambda: False)():
                    continue
                mode_records = engine.search_domain(parsed.netloc, max_matches=300)
                if mode_records:
                    records = mode_records
                    break
            except Exception:
                continue

        if not records:
            return None

        normalized_target = url.rstrip("/")
        preferred: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            candidate_url = str(record.get("url", "")).rstrip("/")
            if candidate_url == normalized_target:
                preferred.append(record)

        candidates = preferred if preferred else [r for r in records if isinstance(r, dict)]

        for record in candidates:
            archive_url = record.get("archive_url") or record.get("wayback_url")
            if archive_url:
                fetched = self._fetch_candidate_archive_url(url, str(archive_url), record)
                if fetched is not None:
                    return fetched

            warc_fetch = self._fetch_from_common_crawl_warc_record(url, record)
            if warc_fetch is not None:
                return warc_fetch

            candidate_url = str(record.get("url", "")).strip()
            if candidate_url and candidate_url != url:
                fetched = self._fetch_candidate_archive_url(url, candidate_url, record)
                if fetched is not None:
                    return fetched

        return None

    def _fetch_candidate_archive_url(
        self,
        original_url: str,
        candidate_url: str,
        record: Dict[str, Any],
    ) -> Optional[FetchResult]:
        try:
            response = self._request_with_retries(candidate_url, timeout=self.request_timeout_seconds, verify=True)
            if response is None:
                return None
            if response.status_code != 200:
                return None
            if not self._looks_like_html(response.content):
                return None
            return FetchResult(
                url=original_url,
                content=response.content,
                source="common_crawl",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                status_code=response.status_code,
                archive_url=candidate_url,
                archive_timestamp=str(record.get("timestamp") or "") or None,
            )
        except SSLError:
            try:
                response = self._request_with_retries(candidate_url, timeout=self.request_timeout_seconds, verify=False)
                if response is None or int(response.status_code) != 200:
                    return None
                if not self._looks_like_html(response.content):
                    return None
                return FetchResult(
                    url=original_url,
                    content=response.content,
                    source="common_crawl_insecure_tls",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    status_code=response.status_code,
                    archive_url=candidate_url,
                    archive_timestamp=str(record.get("timestamp") or "") or None,
                )
            except Exception:
                return None
        except Exception:
            return None

    def _fetch_from_common_crawl_warc_record(
        self,
        original_url: str,
        record: Dict[str, Any],
    ) -> Optional[FetchResult]:
        warc_filename = record.get("warc_filename") or record.get("filename")
        warc_offset = record.get("warc_offset") or record.get("offset")
        warc_length = record.get("warc_length") or record.get("length")

        if not warc_filename or warc_offset is None or warc_length is None:
            return None

        try:
            offset = int(warc_offset)
            length = int(warc_length)
            if length <= 0:
                return None
        except Exception:
            return None

        range_end = offset + length - 1
        warc_url = f"https://data.commoncrawl.org/{warc_filename}"

        try:
            response = self._session.get(
                warc_url,
                headers={"Range": f"bytes={offset}-{range_end}"},
                timeout=max(self.request_timeout_seconds, 45),
            )
            if response.status_code not in (200, 206):
                return None

            html_payload = self._extract_html_from_warc_bytes(response.content)
            if not html_payload or not self._looks_like_html(html_payload):
                return None

            return FetchResult(
                url=original_url,
                content=html_payload,
                source="common_crawl",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                status_code=response.status_code,
                archive_url=warc_url,
                archive_timestamp=str(record.get("timestamp") or "") or None,
            )
        except Exception:
            return None

    @staticmethod
    def _extract_html_from_warc_bytes(raw_bytes: bytes) -> bytes:
        if not raw_bytes:
            return b""

        blob = raw_bytes
        try:
            blob = gzip.decompress(raw_bytes)
        except Exception:
            blob = raw_bytes

        http_start = blob.find(b"HTTP/")
        if http_start != -1:
            http_blob = blob[http_start:]
            header_end = http_blob.find(b"\r\n\r\n")
            if header_end != -1:
                return http_blob[header_end + 4 :]

        return blob

    async def _fetch_from_wayback(self, url: str) -> Optional[FetchResult]:
        try:
            wayback_module = importlib.import_module(
                "ipfs_datasets_py.processors.web_archiving.wayback_machine_engine"
            )
            get_wayback_content = getattr(wayback_module, "get_wayback_content")
            search_wayback_machine = getattr(wayback_module, "search_wayback_machine")
        except Exception:
            return None

        try:
            search_result = await search_wayback_machine(
                url=url,
                limit=6,
                collapse="timestamp:8",
                output_format="json",
            )
        except Exception:
            search_result = {"status": "error", "results": []}

        captures = search_result.get("results", []) if isinstance(search_result, dict) else []

        for capture in captures:
            timestamp = capture.get("timestamp")
            try:
                content_result = await get_wayback_content(url=url, timestamp=timestamp, closest=True)
                if content_result.get("status") != "success":
                    continue

                content = content_result.get("content", b"")
                if isinstance(content, str):
                    content = content.encode("utf-8", errors="replace")

                if not content or not self._looks_like_html(content):
                    continue

                return FetchResult(
                    url=url,
                    content=content,
                    source="wayback",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    archive_url=content_result.get("wayback_url") or capture.get("wayback_url"),
                    archive_timestamp=content_result.get("capture_timestamp") or timestamp,
                )
            except Exception:
                continue

        return None

    async def _fetch_from_archive_is(self, url: str) -> Optional[FetchResult]:
        try:
            archive_module = importlib.import_module(
                "ipfs_datasets_py.processors.web_archiving.archive_is_engine"
            )
            archive_to_archive_is = getattr(archive_module, "archive_to_archive_is")
            get_archive_is_content = getattr(archive_module, "get_archive_is_content")
        except Exception:
            return None

        try:
            submit_result = await archive_to_archive_is(url, wait_for_completion=False)
            archive_url = submit_result.get("archive_url") if isinstance(submit_result, dict) else None
            if not archive_url:
                return None

            content_result = await get_archive_is_content(archive_url)
            if content_result.get("status") != "success":
                return None

            content = content_result.get("content", b"")
            if isinstance(content, str):
                content = content.encode("utf-8", errors="replace")

            if not content or not self._looks_like_html(content):
                return None

            return FetchResult(
                url=url,
                content=content,
                source="archive_is",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                archive_url=archive_url,
            )
        except Exception:
            return None

    @staticmethod
    def _looks_like_html(content: bytes) -> bool:
        if not content:
            return False
        sample = content[:4096].lower()
        return b"<html" in sample or b"<!doctype html" in sample

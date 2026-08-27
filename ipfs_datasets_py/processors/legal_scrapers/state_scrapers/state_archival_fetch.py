"""Shared archival fetch client for state law scrapers.

Implements resilient URL retrieval with the historical archive-first order and
an explicit live-source-first mode for current official frontiers.  Both modes
batch exact Common Crawl pointers by WARC object before falling through to the
remaining transports.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import inspect
import logging
import os
import re
import ssl
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ipfs_datasets_py.processors.web_archiving.common_crawl_integration import (
    CommonCrawlSearchEngine,
)
from ipfs_datasets_py.processors.web_archiving.common_crawl_search_engine.ccindex.api import (
    extract_http_from_warc_gzip_member,
    warc_download_url,
)
from ipfs_datasets_py.processors.web_archiving.wayback_machine_engine import (
    exact_http_locator_identity,
    parse_exact_http_locator,
    parse_wayback_archive_url,
    same_exact_http_locator,
)
from ipfs_datasets_py.utils import anyio_compat as asyncio

logger = logging.getLogger(__name__)

_MODULE_SOURCE_PATH = Path(__file__).resolve()
MODULE_IMPORT_SOURCE_SHA256 = hashlib.sha256(_MODULE_SOURCE_PATH.read_bytes()).hexdigest()


def assert_module_source_unchanged() -> str:
    """Fail if this producer's source bytes changed after module import."""

    current = hashlib.sha256(_MODULE_SOURCE_PATH.read_bytes()).hexdigest()
    if current != MODULE_IMPORT_SOURCE_SHA256:
        raise RuntimeError(f"loaded module source drifted on disk: {_MODULE_SOURCE_PATH}")
    return current


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int = 0) -> int:
    value = str(os.getenv(name) or "").strip()
    if not value:
        return int(default)
    try:
        return int(value)
    except Exception:
        return int(default)


def _env_float(name: str, default: float = 0.0) -> float:
    value = str(os.getenv(name) or "").strip()
    if not value:
        return float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_wayback_snapshot_url(url: str) -> str:
    """Return a canonical retained/replay locator without repairing aliases."""

    text = str(url or "").strip()
    if not text:
        return text
    if "web.archive.org" not in text.lower():
        return text
    try:
        return parse_wayback_archive_url(
            text,
            allowed_modifiers=("", "id_", "if_"),
        ).raw
    except ValueError:
        return ""


def _extract_original_url_from_wayback(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parsed = parse_wayback_archive_url(
            text,
            allowed_modifiers=("", "id_", "if_"),
        )
    except ValueError:
        return ""
    return parsed.original_url


def _archived_resource_identity(
    value: str,
) -> Optional[Tuple[str, str, str, bool, str]]:
    """Return the exact resource key shared by CDX matching and WARC checks."""

    try:
        return exact_http_locator_identity(
            value,
            allow_http_https_equivalence=True,
        )
    except ValueError:
        return None


def _same_archived_resource(left: str, right: str) -> bool:
    """Compare an archived HTTP(S) target without conflating distinct pages.

    Common Crawl commonly retains an ``http`` capture for a locator now
    published as ``https``.  Treat that scheme upgrade and a trailing slash as
    equivalent, but keep host, path and raw query exact.  Fragments,
    authentication, and non-default ports are rejected rather than ignored.
    """

    left_identity = _archived_resource_identity(left)
    return (
        left_identity is not None
        and left_identity == _archived_resource_identity(right)
    )


def _canonical_nonnegative_integer(
    value: object,
    *,
    positive: bool,
) -> Optional[int]:
    """Accept only an integer or its canonical unsigned decimal spelling."""

    if isinstance(value, bool):
        return None
    if type(value) is int:
        parsed = value
    elif type(value) is str and re.fullmatch(r"0|[1-9][0-9]*", value):
        parsed = int(value)
    else:
        return None
    if parsed < 0 or (positive and parsed == 0):
        return None
    return parsed


def _safe_common_crawl_warc_filename(value: object) -> str:
    """Return one canonical Common Crawl object path, or an empty string."""

    if type(value) is not str:
        return ""
    filename = value
    parts = filename.split("/")
    if (
        not filename
        or filename != filename.strip()
        or filename.startswith("/")
        or "\\" in filename
        or "%" in filename
        or "?" in filename
        or "#" in filename
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in filename)
        or any(part in {"", ".", ".."} for part in parts)
        or len(parts) < 3
        or parts[0] != "crawl-data"
        or re.fullmatch(r".+\.warc(?:\.gz)?", parts[-1], re.IGNORECASE) is None
    ):
        return ""
    return filename


def _common_crawl_warc_timestamp(value: object) -> str:
    """Translate one exact UTC WARC-Date to its fourteen-digit CDX form."""

    if type(value) is not str or not value or value != value.strip():
        return ""
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return ""
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return ""
    if parsed.utcoffset().total_seconds() != 0:
        return ""
    return parsed.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def _common_crawl_payload_digest(value: object) -> str:
    """Normalize the SHA-1/base32 spelling used by Common Crawl CDX/WARC."""

    if type(value) is not str or not value or value != value.strip():
        return ""
    digest = value
    if ":" in digest:
        algorithm, encoded = digest.split(":", 1)
        if algorithm.lower() != "sha1":
            return ""
    else:
        encoded = digest
    encoded = encoded.upper()
    if re.fullmatch(r"[A-Z2-7]{32}", encoded) is None:
        return ""
    return f"sha1:{encoded}"


@dataclass
class FetchResult:
    url: str
    content: bytes
    source: str
    fetched_at: str
    status_code: Optional[int] = None
    archive_url: Optional[str] = None
    archive_timestamp: Optional[str] = None
    # Exact Common Crawl transport evidence.  These fields are optional so
    # existing callers and non-Common-Crawl transports retain their prior API.
    common_crawl_indexed_url: Optional[str] = None
    common_crawl_warc_filename: Optional[str] = None
    common_crawl_warc_offset: Optional[int] = None
    common_crawl_warc_length: Optional[int] = None
    common_crawl_collection: Optional[str] = None
    content_sha256: Optional[str] = None
    # Discovery evidence for a replay selected from one bounded Wayback CDX
    # prefix inventory.  Parser-input receipts continue to bind the official
    # URL, capture timestamp/status, archive URL, and body digest directly.
    wayback_cdx_query_url: Optional[str] = None
    wayback_cdx_response_sha256: Optional[str] = None
    wayback_cdx_fetched_at: Optional[str] = None


@dataclass
class CommonCrawlBatchFetchResult:
    """Aligned per-page results plus range-request reduction counters."""

    results: List[Optional[FetchResult]]
    stats: Dict[str, Any]


@dataclass
class WaybackBatchFetchResult:
    """Aligned exact-capture replays selected by one prefix inventory."""

    results: List[Optional[FetchResult]]
    errors: List[Optional[str]]
    stats: Dict[str, Any]


@dataclass
class ArchivalMultiFetchResult:
    """Aligned multi-page results, failures, and archive request savings."""

    results: List[Optional[FetchResult]]
    errors: List[Optional[str]]
    stats: Dict[str, Any]


@dataclass
class _HttpResponse:
    status_code: int
    content: bytes


class _TransientWaybackReplayError(RuntimeError):
    """An exact capture replay failed for a retryable transport reason."""


def _wayback_replay_failure_is_transient(
    *,
    response_status: int = 0,
    error: str = "",
) -> bool:
    """Classify only bounded transport/status failures as retryable."""

    if int(response_status or 0) in {408, 425, 429, 500, 502, 503, 504}:
        return True
    error_text = str(error or "").strip().lower()
    if not error_text:
        return False
    if re.search(r"\b(?:408|425|429|500|502|503|504)\b", error_text):
        return True
    return any(
        token in error_text
        for token in (
            "connection aborted",
            "connection refused",
            "connection reset",
            "max retries exceeded",
            "read timed out",
            "remote end closed",
            "temporarily unavailable",
            "temporary failure",
            "timed out",
            "timeout",
        )
    )


class ArchivalFetchClient:
    """Fetch URLs with web-archive fallback support."""

    _stage_backoff_until: Dict[str, float] = {}

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
        content_validator: Optional[Callable[[bytes], bool]] = None,
        enable_common_crawl: Optional[bool] = None,
        enable_direct: bool = True,
        enable_insecure_direct: bool = True,
        enable_wayback: bool = True,
        enable_archive_is: bool = True,
    ):
        if not isinstance(enable_direct, bool):
            raise TypeError("enable_direct must be a boolean")
        if not isinstance(enable_insecure_direct, bool):
            raise TypeError("enable_insecure_direct must be a boolean")
        if not isinstance(enable_wayback, bool):
            raise TypeError("enable_wayback must be a boolean")
        if not isinstance(enable_archive_is, bool):
            raise TypeError("enable_archive_is must be a boolean")
        self.request_timeout_seconds = request_timeout_seconds
        self.delay_seconds = delay_seconds
        self.user_agent = user_agent
        self._content_validator = content_validator or self._looks_like_html
        self._enable_common_crawl = enable_common_crawl
        self._enable_direct = enable_direct
        self._enable_insecure_direct = enable_insecure_direct
        self._enable_wayback = enable_wayback
        self._enable_archive_is = enable_archive_is

    def _stage_backoff_seconds(self, stage: str, *, reason: str = "") -> int:
        reason_l = str(reason or "").strip().lower()
        if stage == "wayback":
            seconds = max(0, _env_int("LEGAL_SCRAPER_WAYBACK_BACKOFF_SECONDS", default=120))
            if any(
                token in reason_l
                for token in ("connection refused", "timed out", "timeout", "max retries exceeded")
            ):
                seconds = min(seconds, 60)
            return seconds
        if stage == "archive_is":
            return max(0, _env_int("LEGAL_SCRAPER_ARCHIVE_IS_BACKOFF_SECONDS", default=900))
        return max(0, _env_int("LEGAL_SCRAPER_ARCHIVAL_STAGE_BACKOFF_SECONDS", default=600))

    def _stage_backoff_key(self, stage: str, *, url: str = "") -> str:
        host = str(urlparse(str(url or "")).netloc or "").strip().lower()
        if host:
            return f"{stage}:{host}"
        return stage

    def _is_stage_backed_off(self, stage: str, *, url: str = "") -> bool:
        now = time.time()
        stage_key = self._stage_backoff_key(stage, url=url)
        host_until = float(self._stage_backoff_until.get(stage_key, 0.0) or 0.0)
        global_until = float(self._stage_backoff_until.get(stage, 0.0) or 0.0)
        return max(host_until, global_until) > now

    def _mark_stage_backoff(self, stage: str, *, reason: str, url: str = "") -> None:
        seconds = self._stage_backoff_seconds(stage, reason=reason)
        if seconds <= 0:
            return
        until = time.time() + float(seconds)
        stage_key = self._stage_backoff_key(stage, url=url)
        self._stage_backoff_until[stage_key] = until
        logger.warning(
            "archival_fetch stage=%s scope=%s backed_off_for_seconds=%s reason=%s",
            stage,
            stage_key,
            seconds,
            reason[:200],
        )

    def _blocking_archival_stage_timeout_seconds(self) -> float:
        """Return the hard deadline for one blocking archive integration.

        The legacy Wayback and Archive.is integrations expose coroutine
        functions but perform synchronous HTTP/DNS work inside those
        coroutines.  A cancel scope cannot interrupt such work while it owns
        the crawler event-loop thread, so each integration is run in an
        abandonable worker thread and bounded here.
        """

        default = max(1.0, float(self.request_timeout_seconds or 30)) + 10.0
        return max(
            0.05,
            _env_float(
                "LEGAL_SCRAPER_ARCHIVAL_STAGE_TIMEOUT_SECONDS",
                default=default,
            ),
        )

    async def _run_blocking_archival_stage(
        self,
        stage: str,
        *,
        url: str,
        operation: Callable[[], Any],
    ) -> Any:
        """Run one potentially blocking archive stage without owning the loop."""

        timeout_seconds = self._blocking_archival_stage_timeout_seconds()

        def _run() -> Any:
            result = operation()
            if inspect.isawaitable(result):
                return asyncio.run(result)
            return result

        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_run),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            detail = (
                f"{stage} blocking integration exceeded hard stage deadline "
                f"of {timeout_seconds:g}s"
            )
            self._mark_stage_backoff(stage, reason=detail, url=url)
            logger.warning(
                "archival_fetch stage=%s timeout_seconds=%s url=%s",
                stage,
                timeout_seconds,
                url,
            )
            return None

    def _request_with_retries(
        self,
        url: str,
        *,
        timeout: int,
        verify: bool = True,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[_HttpResponse]:
        # A small retry loop helps with transient 403/429/503 and edge rate limiting.
        retry_statuses = {403, 429, 500, 502, 503, 504}
        last_ssl_error: Optional[ssl.SSLError] = None
        for _attempt in range(3):
            try:
                response = self._http_get(url, timeout=timeout, verify=verify, headers=headers)
                last_ssl_error = None
            except ssl.SSLError as exc:
                last_ssl_error = exc
                continue
            except Exception:
                continue
            if int(response.status_code) not in retry_statuses:
                return response
        if last_ssl_error is not None:
            raise last_ssl_error
        return None

    @staticmethod
    def _direct_candidate_urls(url: str) -> List[str]:
        # Prefer live official URL when a seed is a Wayback replay URL so the
        # scraper can progress even when web.archive.org is unavailable.
        text = str(url or "").strip()
        try:
            parsed = parse_exact_http_locator(text)
        except ValueError:
            return []
        if parsed.hostname in {"web.archive.org", "www.web.archive.org"}:
            original = _extract_original_url_from_wayback(text)
            return [original] if original else []
        return [parsed.raw]

    def _http_get(
        self,
        url: str,
        *,
        timeout: int,
        verify: bool,
        headers: Optional[Dict[str, str]] = None,
    ) -> _HttpResponse:
        request_headers = {"User-Agent": self.user_agent}
        if headers:
            request_headers.update(headers)
        req = Request(url, headers=request_headers)
        context = None if verify else ssl._create_unverified_context()
        try:
            with urlopen(
                req, timeout=max(1, int(timeout or self.request_timeout_seconds)), context=context
            ) as response:
                status_code = int(getattr(response, "status", 200) or 200)
                content = response.read()
                return _HttpResponse(status_code=status_code, content=bytes(content or b""))
        except HTTPError as exc:
            payload = b""
            try:
                payload = bytes(exc.read() or b"")
            except Exception:
                payload = b""
            return _HttpResponse(status_code=int(getattr(exc, "code", 0) or 0), content=payload)

    async def fetch_with_fallback(
        self,
        url: str,
        *,
        enable_common_crawl: Optional[bool] = None,
        enable_direct: Optional[bool] = None,
        enable_wayback: Optional[bool] = None,
        enable_archive_is: Optional[bool] = None,
        request_headers: Optional[Mapping[str, str]] = None,
    ) -> FetchResult:
        """Fetch ``url`` through enabled transports in the documented order.

        Per-call switches let provenance-sensitive callers exclude transports
        without changing process-wide environment variables.  ``None`` keeps
        the constructor/environment behavior, preserving the original API.
        """

        if enable_common_crawl is not None and not isinstance(enable_common_crawl, bool):
            raise TypeError("enable_common_crawl must be a boolean or None")
        if enable_direct is not None and not isinstance(enable_direct, bool):
            raise TypeError("enable_direct must be a boolean or None")
        if enable_wayback is not None and not isinstance(enable_wayback, bool):
            raise TypeError("enable_wayback must be a boolean or None")
        if enable_archive_is is not None and not isinstance(enable_archive_is, bool):
            raise TypeError("enable_archive_is must be a boolean or None")

        direct_request_headers = {
            str(key): str(value)
            for key, value in dict(request_headers or {}).items()
            if str(key).strip()
        }
        common_crawl_enabled = (
            self._enable_common_crawl
            if enable_common_crawl is None
            else enable_common_crawl
        )
        if common_crawl_enabled is None:
            common_crawl_enabled = _env_flag(
                "LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL", default=False
            )
        if common_crawl_enabled:
            logger.info("archival_fetch stage=common_crawl start url=%s", url)
            common_crawl = await asyncio.to_thread(self._fetch_from_common_crawl, url)
            if common_crawl is not None:
                logger.info(
                    "archival_fetch stage=common_crawl done source=%s url=%s",
                    common_crawl.source,
                    url,
                )
                return common_crawl
            logger.info("archival_fetch stage=common_crawl miss url=%s", url)
        else:
            logger.info(
                "archival_fetch stage=common_crawl skipped env=LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL url=%s",
                url,
            )

        direct_enabled = self._enable_direct if enable_direct is None else enable_direct
        if direct_enabled:
            direct_candidates = self._direct_candidate_urls(url)
            direct: Optional[FetchResult] = None
            for candidate in direct_candidates:
                logger.info("archival_fetch stage=direct start url=%s", candidate)
                if direct_request_headers:
                    direct = await asyncio.to_thread(
                        self._fetch_direct,
                        candidate,
                        headers=direct_request_headers,
                    )
                else:
                    direct = await asyncio.to_thread(self._fetch_direct, candidate)
                if direct is not None:
                    # Preserve the original requested URL for callers while still
                    # recording where the bytes were sourced.
                    direct.url = url
                    logger.info(
                        "archival_fetch stage=direct done source=%s requested_url=%s fetched_url=%s",
                        direct.source,
                        url,
                        candidate,
                    )
                    return direct
                logger.info("archival_fetch stage=direct miss url=%s", candidate)
        else:
            logger.info(
                "archival_fetch stage=direct skipped caller_already_attempted url=%s",
                url,
            )

        wayback_enabled = (
            self._enable_wayback if enable_wayback is None else enable_wayback
        )
        disable_wayback = _env_flag("LEGAL_SCRAPER_DISABLE_WAYBACK", default=False)
        if not wayback_enabled:
            logger.info(
                "archival_fetch stage=wayback skipped caller_disabled url=%s",
                url,
            )
        elif disable_wayback:
            logger.info(
                "archival_fetch stage=wayback skipped env=LEGAL_SCRAPER_DISABLE_WAYBACK url=%s", url
            )
        elif self._is_stage_backed_off("wayback", url=url):
            logger.info("archival_fetch stage=wayback skipped backoff_active url=%s", url)
        else:
            logger.info("archival_fetch stage=wayback start url=%s", url)
            wayback = await self._run_blocking_archival_stage(
                "wayback",
                url=url,
                operation=lambda: self._fetch_from_wayback(url),
            )
            if wayback is not None:
                logger.info(
                    "archival_fetch stage=wayback done source=%s url=%s", wayback.source, url
                )
                return wayback
            logger.info("archival_fetch stage=wayback miss url=%s", url)

        # archive.is does not expose a response contract that binds both the
        # returned bytes and replay locator to this exact official target.
        # Retained legacy receipts remain migration-readable in the provenance
        # adapter, but this production acquisition path must not create them.
        logger.info(
            "archival_fetch stage=archive_is skipped non_authorizing_transport url=%s",
            url,
        )

        raise RuntimeError(f"Unable to fetch URL via direct or archival fallback: {url}")

    async def fetch_many_with_fallback(
        self,
        urls: Sequence[str],
        *,
        common_crawl_records: Sequence[Tuple[str, Dict[str, Any]]] = (),
        common_crawl_record_loader: Optional[Callable[[Sequence[str]], Any]] = None,
        common_crawl_engine: Any | None = None,
        wayback_inventory_loader: Optional[Callable[[Sequence[str]], Any]] = None,
        result_callback: Optional[Callable[[str, FetchResult], None]] = None,
        enable_common_crawl: Optional[bool] = None,
        enable_archive_is: Optional[bool] = None,
        enable_per_page_fallback: bool = True,
        wayback_capture_replay_attempts: int = 1,
        wayback_capture_retry_concurrency: int = 4,
        max_concurrency: int = 8,
        prefer_direct: bool = False,
        request_headers: Optional[Mapping[str, str]] = None,
    ) -> ArchivalMultiFetchResult:
        """Fetch an aligned URL frontier while batching exact WARC ranges.

        ``common_crawl_records`` is a pointer inventory produced by any shared
        CDX/index discovery path.  All exact pointers are resolved first in a
        single call to :meth:`fetch_common_crawl_records`, which groups pages
        by immutable WARC object and coalesces nearby ranges.  Only misses then
        enter the ordinary direct/Wayback/archive.is fallback path, with Common
        Crawl disabled there so a page is never looked up or range-fetched a
        second time.

        Duplicate input URLs share one acquisition result but remain aligned
        in the returned list.  This method deliberately separates discovery
        from retrieval: callers can enumerate a whole domain once instead of
        repeating a domain query for every page.  ``prefer_direct`` is for a
        current official frontier: live pages are fetched concurrently once,
        then all direct misses are resolved through one grouped WARC batch and
        finally Wayback/archive.is without repeating the live request.  When a
        ``wayback_inventory_loader`` is supplied, it receives the exact misses
        once and returns the shared prefix-inventory outcome from
        ``fetch_wayback_capture_inventory``.  Exact captures are replayed
        directly, and that grouped inventory is authoritative for the wave:
        unresolved pages do not enter legacy per-page Wayback or archive.is
        fallback.

        A synchronous ``result_callback`` is invoked as soon as each unique
        successful result is transport-validated.  Production callers use this
        seam to durably admit parser inputs before the rest of a frontier can be
        interrupted; the callback does not alter final alignment or ordering.
        """

        requested = [str(url or "").strip() for url in urls]
        if any(not url for url in requested):
            raise ValueError("urls must contain only non-empty values")
        if isinstance(max_concurrency, bool) or int(max_concurrency) <= 0:
            raise ValueError("max_concurrency must be positive")
        if not isinstance(prefer_direct, bool):
            raise TypeError("prefer_direct must be a boolean")
        if not isinstance(enable_per_page_fallback, bool):
            raise TypeError("enable_per_page_fallback must be a boolean")
        if isinstance(wayback_capture_replay_attempts, bool) or not 1 <= int(
            wayback_capture_replay_attempts
        ) <= 2:
            raise ValueError(
                "wayback_capture_replay_attempts must be one or two"
            )
        if isinstance(wayback_capture_retry_concurrency, bool) or int(
            wayback_capture_retry_concurrency
        ) <= 0:
            raise ValueError(
                "wayback_capture_retry_concurrency must be positive"
            )
        if common_crawl_record_loader is not None and not callable(
            common_crawl_record_loader
        ):
            raise TypeError("common_crawl_record_loader must be callable or None")
        if wayback_inventory_loader is not None and not callable(
            wayback_inventory_loader
        ):
            raise TypeError("wayback_inventory_loader must be callable or None")
        if result_callback is not None and not callable(result_callback):
            raise TypeError("result_callback must be callable or None")
        if result_callback is not None and inspect.iscoroutinefunction(result_callback):
            raise TypeError("result_callback must be synchronous")

        direct_request_headers = {
            str(key): str(value)
            for key, value in dict(request_headers or {}).items()
            if str(key).strip()
        }
        result_callbacks_emitted = 0

        def _emit_result(url: str, result: FetchResult) -> None:
            nonlocal result_callbacks_emitted
            if result_callback is None:
                return
            callback_result = result_callback(url, result)
            if inspect.isawaitable(callback_result):
                close = getattr(callback_result, "close", None)
                if callable(close):
                    close()
                raise TypeError("result_callback must return synchronously")
            result_callbacks_emitted += 1

        unique_urls = list(dict.fromkeys(requested))
        result_by_url: Dict[str, FetchResult] = {}
        error_by_url: Dict[str, str] = {}
        records_by_url: Dict[str, List[Dict[str, Any]]] = {}
        unique_set = set(unique_urls)
        def _ingest_common_crawl_records(
            values: Sequence[Tuple[str, Dict[str, Any]]],
        ) -> None:
            for item in values or ():
                if not isinstance(item, (tuple, list)) or len(item) != 2:
                    raise TypeError(
                        "each Common Crawl pointer must be (official_url, record)"
                    )
                official_url, raw_record = item
                normalized_url = str(official_url or "").strip()
                if normalized_url not in unique_set:
                    raise ValueError(
                        "Common Crawl pointer URL is outside the requested frontier"
                    )
                if not isinstance(raw_record, dict):
                    raise TypeError(
                        "each Common Crawl pointer record must be a dictionary"
                    )
                record = dict(raw_record)
                if self._common_crawl_pointer(record) is None:
                    continue
                indexed_url = str(record.get("url") or "").strip()
                if indexed_url and not _same_archived_resource(
                    normalized_url,
                    indexed_url,
                ):
                    # A domain-wide CDX inventory may contain unrelated pages.
                    # A mismatched record is a miss for this locator, not
                    # permission to demultiplex another page's response.
                    continue
                records_by_url.setdefault(normalized_url, []).append(record)

        _ingest_common_crawl_records(common_crawl_records)

        direct_initial_requests = 0
        direct_initial_successes = 0
        if prefer_direct and self._enable_direct:
            direct_initial_requests = len(unique_urls)
            direct_semaphore = asyncio.Semaphore(int(max_concurrency))

            async def _direct_one(url: str) -> None:
                nonlocal direct_initial_successes
                async with direct_semaphore:
                    for candidate in self._direct_candidate_urls(url):
                        logger.info(
                            "archival_fetch stage=direct_batch start url=%s",
                            candidate,
                        )
                        if direct_request_headers:
                            result = await asyncio.to_thread(
                                self._fetch_direct,
                                candidate,
                                headers=direct_request_headers,
                            )
                        else:
                            result = await asyncio.to_thread(
                                self._fetch_direct,
                                candidate,
                            )
                        if result is None:
                            logger.info(
                                "archival_fetch stage=direct_batch miss url=%s",
                                candidate,
                            )
                            continue
                        result.url = url
                        _emit_result(url, result)
                        result_by_url[url] = result
                        direct_initial_successes += 1
                        logger.info(
                            "archival_fetch stage=direct_batch done source=%s requested_url=%s fetched_url=%s",
                            result.source,
                            url,
                            candidate,
                        )
                        return

            await asyncio.gather(
                *(_direct_one(url) for url in unique_urls),
                return_exceptions=False,
            )

        common_crawl_enabled = (
            self._enable_common_crawl
            if enable_common_crawl is None
            else enable_common_crawl
        )
        if common_crawl_enabled is None:
            common_crawl_enabled = _env_flag(
                "LEGAL_SOURCE_RECOVERY_ENABLE_COMMON_CRAWL", default=False
            )
        missing_after_direct = [
            url for url in unique_urls if url not in result_by_url
        ]
        if (
            common_crawl_enabled
            and missing_after_direct
            and common_crawl_record_loader is not None
        ):
            loaded_records = common_crawl_record_loader(
                tuple(missing_after_direct)
            )
            if inspect.isawaitable(loaded_records):
                loaded_records = await loaded_records
            _ingest_common_crawl_records(loaded_records or ())
        selected_pointer_requests: List[Tuple[str, Dict[str, Any]]] = []
        if common_crawl_enabled and records_by_url:
            for official_url in unique_urls:
                if official_url in result_by_url:
                    continue
                candidates = records_by_url.get(official_url, [])
                if not candidates:
                    continue
                candidates.sort(
                    key=lambda record: str(record.get("timestamp") or ""),
                    reverse=True,
                )
                selected_pointer_requests.append((official_url, candidates[0]))

        common_crawl_stats: Dict[str, Any] = {
            "requested_pages": 0,
            "successful_pages": 0,
            "failed_pages": 0,
            "warc_objects": 0,
            "range_fetch_calls": 0,
            "naive_range_fetches": 0,
            "range_fetches_avoided": 0,
        }
        if selected_pointer_requests:
            engine = common_crawl_engine
            if engine is None:
                engine = CommonCrawlSearchEngine(mode="local")
            batch = await asyncio.to_thread(
                self.fetch_common_crawl_records,
                selected_pointer_requests,
                engine=engine,
                result_callback=_emit_result,
            )
            common_crawl_stats.update(dict(batch.stats or {}))
            if len(batch.results) != len(selected_pointer_requests):
                raise RuntimeError(
                    "Common Crawl batch result count did not match its request count"
                )
            for (official_url, _record), result in zip(
                selected_pointer_requests,
                batch.results,
                strict=True,
            ):
                if result is not None:
                    result_by_url[official_url] = result

        wayback_inventory_stats: Dict[str, Any] = {
            "requested_pages": 0,
            "unique_pages": 0,
            "prefix_queries_planned": 0,
            "prefix_queries_attempted": 0,
            "prefix_queries_succeeded": 0,
            "prefix_queries_failed": 0,
            "matched_pages": 0,
            "unmatched_pages": 0,
            "selected_capture_replays": 0,
            "successful_capture_replays": 0,
            "failed_capture_replays": 0,
        }
        wayback_error_by_url: Dict[str, str] = {}
        missing_after_common_crawl = [
            url for url in unique_urls if url not in result_by_url
        ]
        if wayback_inventory_loader is not None and missing_after_common_crawl:
            try:
                inventory_outcome = wayback_inventory_loader(
                    tuple(missing_after_common_crawl)
                )
                if inspect.isawaitable(inventory_outcome):
                    inventory_outcome = await inventory_outcome
            except Exception as exc:  # noqa: BLE001 - bounded stage failure
                inventory_outcome = {
                    "status": "error",
                    "captures_by_url": {},
                    "stats": {
                        "requested_pages": len(missing_after_common_crawl),
                        "unique_pages": len(missing_after_common_crawl),
                        "prefix_queries_failed": 1,
                        "loader_error": f"{type(exc).__name__}: {exc}",
                    },
                }
            if not isinstance(inventory_outcome, Mapping):
                raise TypeError(
                    "wayback_inventory_loader must return a mapping outcome"
                )
            raw_inventory_stats = inventory_outcome.get("stats")
            if isinstance(raw_inventory_stats, Mapping):
                wayback_inventory_stats.update(dict(raw_inventory_stats))
            raw_captures = inventory_outcome.get("captures_by_url")
            if raw_captures is None:
                raw_captures = {}
            if not isinstance(raw_captures, Mapping):
                raise TypeError(
                    "Wayback inventory captures_by_url must be a mapping"
                )
            selected_capture_requests: List[Tuple[str, Dict[str, Any]]] = []
            for official_url in missing_after_common_crawl:
                capture = raw_captures.get(official_url)
                if capture is None:
                    continue
                if not isinstance(capture, Mapping):
                    wayback_error_by_url[official_url] = (
                        "TypeError: Wayback inventory capture must be a mapping"
                    )
                    continue
                selected_capture_requests.append((official_url, dict(capture)))
            wayback_inventory_stats["selected_capture_replays"] = len(
                selected_capture_requests
            )
            if selected_capture_requests:
                wayback_batch = await self.fetch_wayback_captures(
                    selected_capture_requests,
                    max_concurrency=int(max_concurrency),
                    replay_attempts=int(wayback_capture_replay_attempts),
                    retry_max_concurrency=min(
                        int(max_concurrency),
                        int(wayback_capture_retry_concurrency),
                    ),
                    result_callback=_emit_result,
                )
                wayback_inventory_stats["successful_capture_replays"] = int(
                    wayback_batch.stats.get("successful_pages", 0) or 0
                )
                wayback_inventory_stats["failed_capture_replays"] = int(
                    wayback_batch.stats.get("failed_pages", 0) or 0
                )
                for replay_stat_key in (
                    "first_pass_replay_calls",
                    "first_pass_successful_pages",
                    "first_pass_failed_pages",
                    "transient_first_pass_failures",
                    "semantic_first_pass_failures",
                    "replay_attempts_configured",
                    "replay_calls",
                    "replay_retries",
                    "replay_retry_pages",
                    "replay_retry_calls",
                    "replay_retry_successes",
                    "replay_retry_failures",
                    "retry_max_concurrency",
                ):
                    wayback_inventory_stats[replay_stat_key] = int(
                        wayback_batch.stats.get(replay_stat_key, 0) or 0
                    )
                for (official_url, _capture), result, replay_error in zip(
                    selected_capture_requests,
                    wayback_batch.results,
                    wayback_batch.errors,
                    strict=True,
                ):
                    if result is not None:
                        result_by_url[official_url] = result
                        continue
                    wayback_error_by_url[official_url] = str(
                        replay_error or "Wayback exact capture replay failed"
                    )

        missing_urls = [url for url in unique_urls if url not in result_by_url]
        grouped_inventory_is_authoritative = wayback_inventory_loader is not None
        per_page_fallback_disabled = (
            grouped_inventory_is_authoritative or not enable_per_page_fallback
        )
        per_page_fallback_urls = list(missing_urls)
        if per_page_fallback_disabled:
            # A caller-provided plural inventory is the sole archive discovery
            # wave for this batch.  Running the ordinary fallback below would
            # otherwise submit one legacy Wayback/archive.is request per miss,
            # defeating the same-domain grouping contract.
            per_page_fallback_urls = []
            for url in missing_urls:
                disabled_error = (
                    "grouped Wayback inventory yielded no replayable exact capture; "
                    "per-page archive fallback is disabled"
                    if grouped_inventory_is_authoritative
                    else "direct-only plural wave was unresolved; per-page fallback "
                    "is disabled"
                )
                prior_error = wayback_error_by_url.get(url)
                error_by_url[url] = (
                    f"{prior_error}; {disabled_error}"
                    if prior_error
                    else disabled_error
                )
        semaphore = asyncio.Semaphore(int(max_concurrency))
        residual_timeout_seconds = max(
            1,
            _env_int(
                "LEGAL_SCRAPER_RESIDUAL_FALLBACK_TIMEOUT_SECONDS",
                default=max(1, int(self.request_timeout_seconds)) + 10,
            ),
        )

        async def _fallback_one(url: str) -> None:
            async with semaphore:
                try:
                    fallback_kwargs: Dict[str, Any] = {
                        "enable_common_crawl": False,
                        "enable_archive_is": enable_archive_is,
                    }
                    if prefer_direct:
                        fallback_kwargs["enable_direct"] = False
                    elif direct_request_headers:
                        fallback_kwargs["request_headers"] = dict(
                            direct_request_headers
                        )
                    result = await asyncio.wait_for(
                        self.fetch_with_fallback(url, **fallback_kwargs),
                        timeout=residual_timeout_seconds,
                    )
                    _emit_result(url, result)
                    result_by_url[url] = result
                except asyncio.TimeoutError:
                    fallback_error = (
                        "TimeoutError: residual archival fallback exceeded "
                        f"{residual_timeout_seconds}s"
                    )
                    prior = wayback_error_by_url.get(url)
                    error_by_url[url] = (
                        f"{prior}; {fallback_error}" if prior else fallback_error
                    )
                except Exception as exc:  # noqa: BLE001 - aligned failure receipt
                    fallback_error = f"{type(exc).__name__}: {exc}"
                    prior = wayback_error_by_url.get(url)
                    error_by_url[url] = (
                        f"{prior}; {fallback_error}" if prior else fallback_error
                    )

        await asyncio.gather(
            *(_fallback_one(url) for url in per_page_fallback_urls),
            return_exceptions=False,
        )
        results = [result_by_url.get(url) for url in requested]
        errors = [error_by_url.get(url) for url in requested]
        hosts = {
            str(urlparse(url).hostname or "").lower()
            for url in unique_urls
            if urlparse(url).hostname
        }
        stats: Dict[str, Any] = {
            "requested_pages": len(requested),
            "unique_pages": len(unique_urls),
            "duplicate_page_requests_avoided": len(requested) - len(unique_urls),
            "domains": len(hosts),
            "common_crawl_pointer_candidates": sum(
                len(values) for values in records_by_url.values()
            ),
            "direct_initial_requests": direct_initial_requests,
            "direct_initial_successes": direct_initial_successes,
            "common_crawl_selected_pages": len(selected_pointer_requests),
            "common_crawl": common_crawl_stats,
            "wayback_inventory": wayback_inventory_stats,
            "result_callbacks_emitted": result_callbacks_emitted,
            "fallback_requests": len(per_page_fallback_urls),
            "grouped_inventory_residual_pages": (
                len(missing_urls) if grouped_inventory_is_authoritative else 0
            ),
            "per_page_archive_fallback_disabled": per_page_fallback_disabled,
            "residual_fallback_timeout_seconds": residual_timeout_seconds,
            "successful_pages": sum(result is not None for result in results),
            "failed_pages": sum(result is None for result in results),
        }
        return ArchivalMultiFetchResult(
            results=results,
            errors=errors,
            stats=stats,
        )

    def _fetch_direct(
        self,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Optional[FetchResult]:
        attempts: List[tuple[bool, str]] = [(True, "direct")]
        if self._enable_insecure_direct and str(url or "").lower().startswith(
            "https://"
        ):
            # Some state sites expose certificate-chain issues from this host.
            # If verified TLS fails to produce a response, retry insecurely.
            attempts.append((False, "direct_insecure_tls"))

        for verify, source in attempts:
            try:
                response = self._request_with_retries(
                    url,
                    timeout=self.request_timeout_seconds,
                    verify=verify,
                    headers={
                        str(key): str(value)
                        for key, value in dict(headers or {}).items()
                        if str(key).strip()
                    }
                    or None,
                )
            except ssl.SSLError:
                continue
            except Exception:
                continue
            if response is None:
                continue
            if response.status_code == 200 and self._content_validator(response.content):
                return FetchResult(
                    url=url,
                    content=response.content,
                    source=source,
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    status_code=response.status_code,
                )
            # Explicit non-200 responses should not be retried with altered TLS.
            return None
        return None

    def _fetch_from_common_crawl(self, url: str) -> Optional[FetchResult]:
        try:
            parsed = parse_exact_http_locator(url)
        except ValueError:
            return None

        modes_to_try: List[tuple[str, Dict[str, Any]]] = [("local", {}), ("cli", {})]
        remote_endpoint = os.environ.get("CCINDEX_MCP_ENDPOINT")
        if remote_endpoint:
            modes_to_try.append(("remote", {"mcp_endpoint": remote_endpoint}))

        records: List[Dict[str, Any]] = []
        selected_engine: Any = None
        for mode, mode_kwargs in modes_to_try:
            try:
                engine = CommonCrawlSearchEngine(mode=mode, **mode_kwargs)
                if not getattr(engine, "is_available", lambda: False)():
                    continue
                mode_records = engine.search_domain(parsed.hostname, max_matches=300)
                if mode_records:
                    records = mode_records
                    selected_engine = engine
                    break
            except Exception:
                continue

        if not records:
            return None

        preferred: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            candidate_url = str(record.get("url", "")).strip()
            if _same_archived_resource(candidate_url, url):
                preferred.append(record)

        # Domain inventory rows outside the exact official identity are misses;
        # never spend a WARC range request before target binding succeeds.
        candidates = preferred

        for record in candidates:
            warc_fetch = self._fetch_from_common_crawl_warc_record(
                url,
                record,
                engine=selected_engine,
            )
            if warc_fetch is not None:
                return warc_fetch

        return None

    @staticmethod
    def _common_crawl_collection(record: Dict[str, Any], warc_filename: str = "") -> str:
        for key in ("collection", "index", "index_id", "crawl", "crawl_id"):
            raw_value = record.get(key)
            value = raw_value if type(raw_value) is str else ""
            if value and value == value.strip() and re.fullmatch(r"[A-Za-z0-9._-]+", value):
                return value
            if raw_value not in (None, ""):
                return ""
        parts = str(warc_filename or "").strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "crawl-data":
            return parts[1]
        return ""

    def _fetch_candidate_archive_url(
        self,
        original_url: str,
        candidate_url: str,
        record: Dict[str, Any],
    ) -> Optional[FetchResult]:
        """Disabled compatibility seam: Common Crawl requires a WARC pointer."""

        del original_url, candidate_url, record
        return None

    def _fetch_from_common_crawl_warc_record(
        self,
        original_url: str,
        record: Dict[str, Any],
        *,
        engine: Any,
    ) -> Optional[FetchResult]:
        """Fetch and extract one exact Common Crawl pointer via shared APIs."""

        pointer = self._common_crawl_pointer(record)
        if pointer is None:
            return None
        warc_filename, offset, length = pointer

        try:
            if engine is None or not callable(getattr(engine, "fetch_warc_record", None)):
                return None
            raw_warc = engine.fetch_warc_record(
                str(warc_filename),
                offset,
                length,
                timeout_s=max(self.request_timeout_seconds, 45),
                # The pointer length is already the exact acquisition bound.
                # Passing it through avoids the shared API's small preview
                # default without allowing bytes outside the locator range.
                max_bytes=length,
            )
            if not isinstance(raw_warc, (bytes, bytearray, memoryview)):
                return None
            retained_warc = bytes(raw_warc)
            if len(retained_warc) != length:
                return None

            return self._common_crawl_result_from_warc_bytes(
                original_url=original_url,
                record=record,
                warc_filename=warc_filename,
                offset=offset,
                length=length,
                retained_warc=retained_warc,
            )
        except Exception:
            return None

    @staticmethod
    def _common_crawl_pointer(
        record: Dict[str, Any],
    ) -> Optional[Tuple[str, int, int]]:
        """Return one validated CDX WARC pointer without fetching bytes."""

        warc_filename = _safe_common_crawl_warc_filename(
            record.get("warc_filename")
            if record.get("warc_filename") is not None
            else record.get("filename")
        )
        warc_offset = record.get("warc_offset")
        if warc_offset is None:
            warc_offset = record.get("offset")
        warc_length = record.get("warc_length")
        if warc_length is None:
            warc_length = record.get("length")

        if not warc_filename or warc_offset is None or warc_length is None:
            return None
        offset = _canonical_nonnegative_integer(warc_offset, positive=False)
        length = _canonical_nonnegative_integer(warc_length, positive=True)
        if offset is None or length is None:
            return None
        return warc_filename, offset, length

    def _common_crawl_result_from_warc_bytes(
        self,
        *,
        original_url: str,
        record: Dict[str, Any],
        warc_filename: str,
        offset: int,
        length: int,
        retained_warc: bytes,
    ) -> Optional[FetchResult]:
        """Extract and verify one exact member returned by any shared fetch plan."""

        if len(retained_warc) != int(length):
            return None

        try:
            extracted = extract_http_from_warc_gzip_member(
                retained_warc,
                # Zero disables decompressed-record truncation in the shared
                # extractor.  The range itself remains exactly length-bounded.
                max_decompressed_bytes=0,
                # The shared chunk decoder treats positive values as caps.
                # This value is deliberately non-binding so returned content
                # remains byte-exact rather than silently truncated.
                max_body_bytes=(1 << 63) - 1,
                max_preview_chars=0,
                include_body_base64=True,
            )
            if (
                not extracted.ok
                or extracted.error is not None
                or extracted.http_status is None
                or int(extracted.http_status) != 200
                or not extracted.body_base64
            ):
                return None
            if str(extracted.warc_headers.get("warc-type") or "").strip().lower() != "response":
                return None
            indexed_value = record.get("url")
            indexed_url = indexed_value if type(indexed_value) is str else ""
            target_value = extracted.warc_headers.get("warc-target-uri")
            target_url = target_value if type(target_value) is str else ""
            if (
                not target_url
                or not _same_archived_resource(original_url, indexed_url)
                or not _same_archived_resource(indexed_url, target_url)
            ):
                return None
            raw_timestamp = record.get("timestamp")
            cdx_timestamp = raw_timestamp if type(raw_timestamp) is str else ""
            if (
                re.fullmatch(r"[0-9]{14}", cdx_timestamp) is None
                or _common_crawl_warc_timestamp(
                    extracted.warc_headers.get("warc-date")
                )
                != cdx_timestamp
            ):
                return None
            try:
                datetime.strptime(cdx_timestamp, "%Y%m%d%H%M%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                return None
            try:
                html_payload = base64.b64decode(
                    extracted.body_base64,
                    validate=True,
                )
            except Exception:
                return None
            cdx_digest = _common_crawl_payload_digest(record.get("digest"))
            warc_digest = _common_crawl_payload_digest(
                extracted.warc_headers.get("warc-payload-digest")
            )
            computed_digest = "sha1:" + base64.b32encode(
                hashlib.sha1(html_payload).digest()
            ).decode("ascii")
            if (
                not cdx_digest
                or not warc_digest
                or cdx_digest != warc_digest
                or cdx_digest != computed_digest
            ):
                return None
            declared_length = str(
                extracted.http_headers.get("content-length") or ""
            )
            if declared_length:
                if (
                    re.fullmatch(r"0|[1-9][0-9]*", declared_length) is None
                    or int(declared_length) != len(html_payload)
                ):
                    return None
            if not html_payload or not self._content_validator(html_payload):
                return None

            collection = self._common_crawl_collection(record, str(warc_filename))
            if not collection or str(warc_filename).split("/")[1] != collection:
                return None
            return FetchResult(
                url=original_url,
                content=html_payload,
                source="common_crawl",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                # This is the archived response status.  The shared engine
                # intentionally hides its internal HTTP range status.
                status_code=extracted.http_status,
                archive_url=warc_download_url(str(warc_filename)),
                archive_timestamp=cdx_timestamp,
                common_crawl_indexed_url=indexed_url,
                common_crawl_warc_filename=str(warc_filename),
                common_crawl_warc_offset=offset,
                common_crawl_warc_length=length,
                common_crawl_collection=collection,
                content_sha256=hashlib.sha256(html_payload).hexdigest(),
            )
        except Exception:
            return None

    def fetch_common_crawl_record(
        self,
        original_url: str,
        record: Dict[str, Any],
        *,
        engine: Any,
    ) -> Optional[FetchResult]:
        """Fetch one exact CDX/WARC member through the shared archive seam.

        State parsers use this public adapter instead of reimplementing range
        retrieval, WARC/HTTP decoding, truncation handling, and receipt field
        projection.  ``original_url`` remains the official locator while the
        returned ``archive_url`` identifies the immutable transport object.
        """

        if not isinstance(record, dict):
            raise TypeError("record must be a dictionary")
        return self._fetch_from_common_crawl_warc_record(
            str(original_url or "").strip(),
            dict(record),
            engine=engine,
        )

    def fetch_common_crawl_records(
        self,
        requests: Sequence[Tuple[str, Dict[str, Any]]],
        *,
        engine: Any,
        result_callback: Optional[Callable[[str, FetchResult], None]] = None,
        max_slice_bytes: Optional[int] = None,
        max_gap_bytes: Optional[int] = None,
        max_workers: Optional[int] = None,
    ) -> CommonCrawlBatchFetchResult:
        """Fetch many CDX pointers through the shared WARC slice batcher.

        Results stay aligned with ``requests``.  Grouping is by immutable WARC
        filename (not merely hostname), so pages from the same domain or from
        different domains share a request whenever their exact members are
        close enough in the same archive object.  Every member is length- and
        response/archive-verified independently after the bundle is split.
        ``result_callback`` runs only after that per-member verification.
        """

        if result_callback is not None and not callable(result_callback):
            raise TypeError("result_callback must be callable or None")
        if result_callback is not None and inspect.iscoroutinefunction(result_callback):
            raise TypeError("result_callback must be synchronous")

        def _emit_result(url: str, result: FetchResult) -> None:
            if result_callback is None:
                return
            callback_result = result_callback(url, result)
            if inspect.isawaitable(callback_result):
                close = getattr(callback_result, "close", None)
                if callable(close):
                    close()
                raise TypeError("result_callback must return synchronously")

        normalized_requests = list(requests or [])
        results: List[Optional[FetchResult]] = [None] * len(normalized_requests)
        grouped: Dict[
            str,
            List[Tuple[int, str, Dict[str, Any], int, int]],
        ] = {}
        invalid_pointers = 0
        for index, item in enumerate(normalized_requests):
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise TypeError(
                    "each Common Crawl batch request must be (official_url, record)"
                )
            original_url, raw_record = item
            if not isinstance(raw_record, dict):
                raise TypeError("each Common Crawl batch record must be a dictionary")
            record = dict(raw_record)
            pointer = self._common_crawl_pointer(record)
            official_url = str(original_url or "").strip()
            if not official_url or pointer is None:
                invalid_pointers += 1
                continue
            warc_filename, offset, length = pointer
            grouped.setdefault(warc_filename, []).append(
                (index, official_url, record, offset, length)
            )

        slice_limit = (
            int(max_slice_bytes)
            if max_slice_bytes is not None
            else _env_int(
                "STATE_SCRAPER_COMMON_CRAWL_SLICE_MAX_BYTES",
                25_000_000,
            )
        )
        gap_limit = (
            int(max_gap_bytes)
            if max_gap_bytes is not None
            else _env_int(
                "STATE_SCRAPER_COMMON_CRAWL_SLICE_GAP_BYTES",
                256_000,
            )
        )
        worker_limit = (
            int(max_workers)
            if max_workers is not None
            else _env_int("STATE_SCRAPER_COMMON_CRAWL_SLICE_WORKERS", 1)
        )
        if slice_limit <= 0:
            raise ValueError("max_slice_bytes must be positive")
        if gap_limit < 0:
            raise ValueError("max_gap_bytes must be non-negative")
        if worker_limit <= 0:
            raise ValueError("max_workers must be positive")

        valid_pointer_count = sum(len(items) for items in grouped.values())
        unique_pointer_count = sum(
            len({(offset, length) for _i, _u, _r, offset, length in items})
            for items in grouped.values()
        )
        aggregate: Dict[str, Any] = {
            "requested_pages": len(normalized_requests),
            "valid_pointers": valid_pointer_count,
            "invalid_pointers": invalid_pointers,
            "warc_objects": len(grouped),
            "max_slice_bytes": slice_limit,
            "max_gap_bytes": gap_limit,
            # These are derived from the immutable pointer inventory, so they
            # remain auditable even when a transport group fails before it can
            # populate detailed slice statistics.
            "requested_ranges": valid_pointer_count,
            "unique_ranges": unique_pointer_count,
            "duplicate_ranges": valid_pointer_count - unique_pointer_count,
            "range_fetch_calls": 0,
            "naive_range_fetches": 0,
            "range_fetches_avoided": 0,
            "planned_range_fetches": 0,
            "planned_range_fetches_avoided": 0,
            "retry_range_fetches": 0,
            "coalesced_gap_bytes": 0,
            "requested_member_bytes": 0,
        }

        batch_fn = getattr(engine, "fetch_warc_record_ranges_sliced", None)
        if not callable(batch_fn):
            for index, original_url, record, _offset, _length in (
                item for items in grouped.values() for item in items
            ):
                result = self.fetch_common_crawl_record(
                    original_url,
                    record,
                    engine=engine,
                )
                if result is not None:
                    _emit_result(original_url, result)
                results[index] = result
            unique_pointers = {
                (warc_filename, offset, length)
                for warc_filename, items in grouped.items()
                for _index, _url, _record, offset, length in items
            }
            aggregate.update(
                {
                    "batch_transport_available": False,
                    # The compatibility path above invokes the engine once per
                    # valid aligned request.  Do not under-report those calls
                    # merely because two requests share an exact pointer.
                    "requested_ranges": valid_pointer_count,
                    "unique_ranges": len(unique_pointers),
                    "duplicate_ranges": valid_pointer_count - len(unique_pointers),
                    "range_fetch_calls": valid_pointer_count,
                    "naive_range_fetches": valid_pointer_count,
                    "planned_range_fetches": valid_pointer_count,
                    "range_fetches_avoided": 0,
                    "successful_pages": sum(result is not None for result in results),
                    "failed_pages": sum(result is None for result in results),
                }
            )
            return CommonCrawlBatchFetchResult(results=results, stats=aggregate)

        aggregate["batch_transport_available"] = True
        for warc_filename in sorted(grouped):
            items = grouped[warc_filename]
            ranges = [(offset, length) for _i, _u, _r, offset, length in items]
            group_stats: Dict[str, Any] = {}
            try:
                data_by, error_by = batch_fn(
                    warc_filename,
                    ranges,
                    timeout_s=max(self.request_timeout_seconds, 45),
                    max_slice_bytes=slice_limit,
                    max_gap_bytes=gap_limit,
                    min_slice_bytes=0,
                    max_workers=worker_limit,
                    stats_out=group_stats,
                )
            except Exception as exc:
                logger.warning(
                    "Common Crawl WARC batch failed for %s: %s",
                    warc_filename,
                    exc,
                )
                data_by = {}
                error_by = {
                    (offset, length): f"{type(exc).__name__}: {exc}"
                    for _i, _u, _r, offset, length in items
                }

            if not isinstance(data_by, dict) or not isinstance(error_by, dict):
                data_by = {}
                error_by = {
                    (offset, length): "invalid shared WARC batch response"
                    for _i, _u, _r, offset, length in items
                }

            for key in (
                "range_fetch_calls",
                "naive_range_fetches",
                "planned_range_fetches",
                "planned_range_fetches_avoided",
                "retry_range_fetches",
                "coalesced_gap_bytes",
                "requested_member_bytes",
            ):
                aggregate[key] = int(aggregate.get(key) or 0) + int(
                    group_stats.get(key) or 0
                )

            for index, original_url, record, offset, length in items:
                retained_warc = data_by.get((offset, length))
                if not isinstance(retained_warc, (bytes, bytearray, memoryview)):
                    continue
                exact_member = bytes(retained_warc)
                if len(exact_member) != length:
                    continue
                result = self._common_crawl_result_from_warc_bytes(
                    original_url=original_url,
                    record=record,
                    warc_filename=warc_filename,
                    offset=offset,
                    length=length,
                    retained_warc=exact_member,
                )
                if result is not None:
                    _emit_result(original_url, result)
                results[index] = result

        aggregate["range_fetches_avoided"] = max(
            0,
            int(aggregate["naive_range_fetches"])
            - int(aggregate["range_fetch_calls"]),
        )
        aggregate["effective_range_fetches_avoided"] = int(
            aggregate["range_fetches_avoided"]
        )
        aggregate["successful_pages"] = sum(result is not None for result in results)
        aggregate["failed_pages"] = sum(result is None for result in results)
        return CommonCrawlBatchFetchResult(results=results, stats=aggregate)

    async def fetch_wayback_captures(
        self,
        capture_requests: Sequence[Tuple[str, Mapping[str, Any]]],
        *,
        max_concurrency: int = 8,
        replay_attempts: int = 1,
        retry_max_concurrency: int = 4,
        result_callback: Optional[Callable[[str, FetchResult], None]] = None,
    ) -> WaybackBatchFetchResult:
        """Replay exact CDX-selected captures without another CDX lookup.

        Each unique official URL is submitted once in the first replay wave.
        At most one second wave contains only first-pass transient transport
        failures and reuses the already selected exact capture records.  It
        never performs another CDX lookup.  Invalid capture identity,
        timestamp, declared status, response identity, content, validator, or
        digest is a semantic miss and is never retried.  The retry wave has a
        separately smaller concurrency bound so Internet Archive pressure
        cannot be amplified.
        """

        if isinstance(max_concurrency, bool) or int(max_concurrency) <= 0:
            raise ValueError("max_concurrency must be positive")
        if isinstance(replay_attempts, bool) or not 1 <= int(replay_attempts) <= 2:
            raise ValueError("replay_attempts must be one or two")
        if isinstance(retry_max_concurrency, bool) or int(
            retry_max_concurrency
        ) <= 0:
            raise ValueError("retry_max_concurrency must be positive")
        if result_callback is not None and not callable(result_callback):
            raise TypeError("result_callback must be callable or None")
        if result_callback is not None and inspect.iscoroutinefunction(
            result_callback
        ):
            raise TypeError("result_callback must be synchronous")

        requested: List[Tuple[str, Dict[str, Any]]] = []
        capture_by_url: Dict[str, Dict[str, Any]] = {}
        unique_urls: List[str] = []
        for item in capture_requests:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise TypeError(
                    "each Wayback capture request must be (official_url, capture)"
                )
            official_url, raw_capture = item
            try:
                url = parse_exact_http_locator(official_url).raw
            except ValueError as exc:
                raise ValueError(
                    "Wayback capture official URLs must be strict HTTP(S) locators"
                ) from exc
            if not isinstance(raw_capture, Mapping):
                raise TypeError("each Wayback capture must be a mapping")
            capture = dict(raw_capture)
            previous = capture_by_url.get(url)
            if previous is not None and previous != capture:
                raise ValueError(
                    "duplicate Wayback capture requests conflict for exact URL"
                )
            requested.append((url, capture))
            if previous is None:
                capture_by_url[url] = capture
                unique_urls.append(url)

        result_by_url: Dict[str, FetchResult] = {}
        error_by_url: Dict[str, str] = {}
        callback_count = 0
        replay_calls = 0
        first_pass_replay_calls = 0
        replay_retry_calls = 0
        replay_timeout_seconds = self._blocking_archival_stage_timeout_seconds()

        def _capture_error(
            official_url: str,
            capture: Mapping[str, Any],
        ) -> Optional[str]:
            original_url = str(
                capture.get("original_url") or capture.get("original") or ""
            ).strip()
            if not same_exact_http_locator(original_url, official_url):
                return "Wayback capture changed exact official URL identity"
            raw_timestamp = str(capture.get("timestamp") or "")
            timestamp = raw_timestamp.strip()
            if timestamp != raw_timestamp:
                return "Wayback capture timestamp is not exact"
            if not re.fullmatch(r"\d{14}", timestamp):
                return "Wayback capture lacks an exact fourteen-digit timestamp"
            try:
                datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                return "Wayback capture timestamp is not a real calendar time"
            status_code = _canonical_nonnegative_integer(
                capture.get("status_code")
                if capture.get("status_code") is not None
                else capture.get("statuscode"),
                positive=False,
            )
            if status_code != 200:
                return "Wayback capture does not declare exact HTTP 200 status"
            try:
                replay = parse_wayback_archive_url(
                    capture.get("wayback_url"),
                    allowed_modifiers=("id_",),
                    require_identity_modifier=True,
                )
            except ValueError:
                return "Wayback replay URL is not bound to the exact capture"
            if replay.timestamp != timestamp or not same_exact_http_locator(
                replay.original_url,
                official_url,
            ):
                return "Wayback replay URL is not bound to the exact capture"
            if not all(
                type(capture.get(field)) is str and bool(capture.get(field))
                for field in (
                    "wayback_cdx_query_url",
                    "wayback_cdx_response_sha256",
                    "wayback_cdx_fetched_at",
                )
            ):
                return "Wayback capture lacks complete CDX discovery evidence"
            return None

        valid_urls: List[str] = []
        for official_url in unique_urls:
            capture = capture_by_url[official_url]
            identity_error = _capture_error(official_url, capture)
            if identity_error:
                error_by_url[official_url] = identity_error
                continue
            valid_urls.append(official_url)

        async def _replay_one(
            official_url: str,
            *,
            semaphore: Any,
            retry_wave: bool,
        ) -> tuple[Optional[FetchResult], str, bool]:
            nonlocal replay_calls, first_pass_replay_calls, replay_retry_calls
            capture = capture_by_url[official_url]
            archive_url = str(capture["wayback_url"])

            def _run() -> Optional[FetchResult]:
                return asyncio.run(
                    self.fetch_wayback_replay(
                        archive_url,
                        official_url=official_url,
                    )
                )

            async with semaphore:
                replay_calls += 1
                if retry_wave:
                    replay_retry_calls += 1
                else:
                    first_pass_replay_calls += 1
                try:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(_run),
                        timeout=replay_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    return None, (
                        "TimeoutError: exact Wayback capture replay exceeded "
                        f"{replay_timeout_seconds:g}s"
                    ), True
                except _TransientWaybackReplayError as exc:
                    return None, f"{type(exc).__name__}: {exc}", True
                except Exception as exc:  # noqa: BLE001 - aligned replay miss
                    error = f"{type(exc).__name__}: {exc}"
                    return None, error, _wayback_replay_failure_is_transient(
                        error=error
                    )
            if result is None:
                return None, "Wayback exact capture replay failed", False
            if (
                not same_exact_http_locator(result.url, official_url)
                or int(result.status_code or 0) != 200
                or str(result.archive_timestamp or "")
                != str(capture.get("timestamp") or "")
                or not result.content
            ):
                return (
                    None,
                    "Wayback exact capture replay changed response identity",
                    False,
                )
            digest = hashlib.sha256(bytes(result.content)).hexdigest()
            if result.content_sha256 and result.content_sha256 != digest:
                return (
                    None,
                    "Wayback exact capture replay changed body digest",
                    False,
                )
            result.content_sha256 = digest
            result.wayback_cdx_query_url = str(
                capture.get("wayback_cdx_query_url") or ""
            ) or None
            result.wayback_cdx_response_sha256 = str(
                capture.get("wayback_cdx_response_sha256") or ""
            ) or None
            result.wayback_cdx_fetched_at = str(
                capture.get("wayback_cdx_fetched_at") or ""
            ) or None
            return result, "", False

        async def _run_wave(
            urls: Sequence[str],
            *,
            concurrency: int,
            retry_wave: bool,
        ) -> Dict[str, tuple[Optional[FetchResult], str, bool]]:
            semaphore = asyncio.Semaphore(max(1, int(concurrency)))
            rows = await asyncio.gather(
                *(
                    _replay_one(
                        url,
                        semaphore=semaphore,
                        retry_wave=retry_wave,
                    )
                    for url in urls
                ),
                return_exceptions=False,
            )
            return dict(zip(urls, rows, strict=True))

        first_rows = await _run_wave(
            valid_urls,
            concurrency=int(max_concurrency),
            retry_wave=False,
        )
        first_pass_successes = 0
        transient_first_pass_failures = 0
        semantic_first_pass_failures = len(unique_urls) - len(valid_urls)
        retry_urls: List[str] = []
        for official_url in valid_urls:
            result, error, transient = first_rows[official_url]
            if result is not None:
                result_by_url[official_url] = result
                first_pass_successes += 1
                continue
            error_by_url[official_url] = error
            if transient:
                transient_first_pass_failures += 1
                if int(replay_attempts) == 2:
                    retry_urls.append(official_url)
            else:
                semantic_first_pass_failures += 1

        retry_successes = 0
        if retry_urls:
            retry_rows = await _run_wave(
                retry_urls,
                concurrency=min(
                    int(max_concurrency),
                    int(retry_max_concurrency),
                ),
                retry_wave=True,
            )
            for official_url in retry_urls:
                result, error, _transient = retry_rows[official_url]
                if result is None:
                    error_by_url[official_url] = error
                    continue
                result_by_url[official_url] = result
                error_by_url.pop(official_url, None)
                retry_successes += 1

        for official_url in unique_urls:
            result = result_by_url.get(official_url)
            if result is None or result_callback is None:
                continue
            callback_result = result_callback(official_url, result)
            if inspect.isawaitable(callback_result):
                close = getattr(callback_result, "close", None)
                if callable(close):
                    close()
                raise TypeError("result_callback must return synchronously")
            callback_count += 1

        results = [result_by_url.get(url) for url, _capture in requested]
        errors = [error_by_url.get(url) for url, _capture in requested]
        unique_successes = len(result_by_url)
        return WaybackBatchFetchResult(
            results=results,
            errors=errors,
            stats={
                "requested_pages": len(requested),
                "unique_pages": len(unique_urls),
                "duplicate_page_requests_avoided": len(requested) - len(unique_urls),
                "replay_attempts_configured": int(replay_attempts),
                "first_pass_replay_calls": first_pass_replay_calls,
                "first_pass_successful_pages": first_pass_successes,
                "first_pass_failed_pages": len(unique_urls) - first_pass_successes,
                "transient_first_pass_failures": transient_first_pass_failures,
                "semantic_first_pass_failures": semantic_first_pass_failures,
                "replay_calls": replay_calls,
                "replay_retries": replay_retry_calls,
                "replay_retry_pages": len(retry_urls),
                "replay_retry_calls": replay_retry_calls,
                "replay_retry_successes": retry_successes,
                "replay_retry_failures": len(retry_urls) - retry_successes,
                "retry_max_concurrency": min(
                    int(max_concurrency),
                    int(retry_max_concurrency),
                ),
                "result_callbacks_emitted": callback_count,
                "successful_pages": sum(result is not None for result in results),
                "successful_unique_pages": unique_successes,
                "failed_pages": sum(result is None for result in results),
            },
        )

    async def fetch_wayback_replay(
        self,
        archive_url: str,
        *,
        official_url: Optional[str] = None,
    ) -> Optional[FetchResult]:
        """Retrieve one explicit Wayback capture with separate locator roles."""

        try:
            requested_replay = parse_wayback_archive_url(
                archive_url,
                allowed_modifiers=("", "id_", "if_"),
            )
        except ValueError:
            return None
        requested_timestamp = requested_replay.timestamp
        embedded_original = requested_replay.original_url
        try:
            expected_original = parse_exact_http_locator(
                official_url if official_url is not None else embedded_original
            ).raw
        except ValueError:
            return None
        if not same_exact_http_locator(expected_original, embedded_original):
            return None

        try:
            wayback_module = importlib.import_module(
                "ipfs_datasets_py.processors.web_archiving.wayback_machine_engine"
            )
            get_wayback_content = getattr(wayback_module, "get_wayback_content")
            content_result = await get_wayback_content(
                url=expected_original,
                timestamp=requested_timestamp,
                closest=False,
            )
            if not isinstance(content_result, dict):
                return None
            if content_result.get("status") != "success":
                try:
                    failure_status = int(
                        content_result.get("response_status") or 0
                    )
                except (TypeError, ValueError):
                    failure_status = 0
                failure_error = str(content_result.get("error") or "").strip()
                if _wayback_replay_failure_is_transient(
                    response_status=failure_status,
                    error=failure_error,
                ):
                    raise _TransientWaybackReplayError(
                        failure_error
                        or (
                            "exact Wayback replay returned transient HTTP "
                            f"{failure_status}"
                        )
                    )
                return None
            try:
                response_status = int(content_result.get("response_status") or 0)
            except (TypeError, ValueError):
                return None
            if response_status != 200:
                if _wayback_replay_failure_is_transient(
                    response_status=response_status
                ):
                    raise _TransientWaybackReplayError(
                        "exact Wayback replay returned transient HTTP "
                        f"{response_status}"
                    )
                return None
            content = content_result.get("content", b"")
            if isinstance(content, str):
                content = content.encode("utf-8", errors="replace")
            if not isinstance(content, (bytes, bytearray, memoryview)):
                return None
            payload = bytes(content)
            if not payload or not self._content_validator(payload):
                return None

            observed_original = str(content_result.get("original_url") or "").strip()
            if not same_exact_http_locator(observed_original, expected_original):
                return None
            raw_observed_timestamp = str(content_result.get("capture_timestamp") or "")
            observed_timestamp = raw_observed_timestamp.strip()
            if observed_timestamp != raw_observed_timestamp:
                return None
            if observed_timestamp != requested_timestamp:
                return None
            try:
                observed_replay = parse_wayback_archive_url(
                    content_result.get("wayback_url"),
                    allowed_modifiers=("id_",),
                    require_identity_modifier=True,
                )
            except ValueError:
                return None
            if observed_replay.timestamp != requested_timestamp or not same_exact_http_locator(
                observed_replay.original_url,
                expected_original,
            ):
                return None

            return FetchResult(
                url=expected_original,
                content=payload,
                source="wayback",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                status_code=response_status,
                archive_url=observed_replay.raw,
                archive_timestamp=observed_timestamp,
                content_sha256=hashlib.sha256(payload).hexdigest(),
            )
        except _TransientWaybackReplayError:
            raise
        except Exception as exc:
            if _wayback_replay_failure_is_transient(
                error=f"{type(exc).__name__}: {exc}"
            ):
                raise _TransientWaybackReplayError(str(exc)) from exc
            return None

    async def _fetch_from_wayback(self, url: str) -> Optional[FetchResult]:
        try:
            wayback_module = importlib.import_module(
                "ipfs_datasets_py.processors.web_archiving.wayback_machine_engine"
            )
            fetch_inventory = getattr(
                wayback_module,
                "fetch_wayback_capture_inventory",
            )
        except Exception:
            return None

        lookup_url = _extract_original_url_from_wayback(url) or str(url or "").strip()
        try:
            lookup_url = parse_exact_http_locator(lookup_url).raw
        except ValueError:
            return None
        try:
            inventory_result = await fetch_inventory(
                [lookup_url],
                max_queries=1,
                max_queries_per_origin=1,
                max_results_per_query=100,
            )
        except Exception as exc:
            self._mark_stage_backoff("wayback", reason=str(exc), url=lookup_url)
            inventory_result = {"status": "error", "captures_by_url": {}}

        captures_by_url = (
            inventory_result.get("captures_by_url")
            if isinstance(inventory_result, Mapping)
            else None
        )
        capture = (
            captures_by_url.get(lookup_url)
            if isinstance(captures_by_url, Mapping)
            else None
        )
        if not isinstance(capture, Mapping):
            status = str(
                (inventory_result.get("status") or "")
                if isinstance(inventory_result, Mapping)
                else ""
            ).strip().lower()
            error_text = str(
                (inventory_result.get("error") or "")
                if isinstance(inventory_result, Mapping)
                else ""
            ).strip().lower()
            combined = f"{status} {error_text}".strip()
            if any(
                token in combined
                for token in (
                    "connection refused",
                    "max retries exceeded",
                    "timed out",
                    "timeout",
                    "429",
                    "rate",
                    "quota",
                )
            ):
                self._mark_stage_backoff(
                    "wayback",
                    reason=combined or "wayback_transport_failure",
                    url=lookup_url,
                )
            return None

        capture_status = _canonical_nonnegative_integer(
            capture.get("status_code")
            if capture.get("status_code") is not None
            else capture.get("statuscode"),
            positive=False,
        )
        if capture_status != 200:
            return None
        try:
            timestamp = str(capture.get("timestamp") or "")
            archive_url = str(capture.get("wayback_url") or "")
            replay = parse_wayback_archive_url(
                archive_url,
                allowed_modifiers=("id_",),
                require_identity_modifier=True,
            )
            if (
                replay.timestamp != timestamp
                or not same_exact_http_locator(replay.original_url, lookup_url)
            ):
                return None
            result = await self.fetch_wayback_replay(
                replay.raw,
                official_url=lookup_url,
            )
            if result is None:
                return None
            result.wayback_cdx_query_url = str(
                capture.get("wayback_cdx_query_url") or ""
            ) or None
            result.wayback_cdx_response_sha256 = str(
                capture.get("wayback_cdx_response_sha256") or ""
            ) or None
            result.wayback_cdx_fetched_at = str(
                capture.get("wayback_cdx_fetched_at") or ""
            ) or None
            if not all(
                (
                    result.wayback_cdx_query_url,
                    result.wayback_cdx_response_sha256,
                    result.wayback_cdx_fetched_at,
                )
            ):
                return None
            return result
        except Exception as exc:
            err = str(exc).lower()
            if "timed out" in err or "max retries exceeded" in err or "connection" in err:
                self._mark_stage_backoff("wayback", reason=str(exc), url=lookup_url)
            return None

    async def _fetch_from_archive_is(self, url: str) -> Optional[FetchResult]:
        """Return no parser-authorizing result for archive.is.

        Its current integration does not expose a no-redirect final response
        identity plus an exact original-URL binding.  Keeping the method as a
        no-op preserves the public compatibility seam without allowing those
        unbound bytes into fresh state-law evidence.
        """

        del url
        return None

    @staticmethod
    def _looks_like_html(content: bytes) -> bool:
        if not content:
            return False
        sample = content[:4096].lower()
        return b"<html" in sample or b"<!doctype html" in sample

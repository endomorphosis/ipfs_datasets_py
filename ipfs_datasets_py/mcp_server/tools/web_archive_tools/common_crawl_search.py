"""Common Crawl search and data extraction using CDX Toolkit.

This tool provides access to Common Crawl datasets for large-scale web content analysis
using the CDX (Canonical Document Index) format.
"""

import asyncio
import logging
import multiprocessing as mp
import os
import queue as queue_module
from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit, urlunsplit

import anyio

logger = logging.getLogger(__name__)


def _error_search_result(error: str, records: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return one fail-closed shape for configuration and transport failures."""

    partial_records = list(records or [])
    return {
        "status": "error",
        "error": error,
        "results": partial_records,
        "count": len(partial_records),
        "complete": False,
        "truncated": False,
    }


def _canonical_http_url(value: str, *, field: str) -> str:
    """Normalize enough URL syntax to make an exact local comparison reliable."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    candidate = value.strip()
    if any(character.isspace() for character in candidate):
        raise ValueError(f"{field} must not contain whitespace")
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{field} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field} must not contain user information")

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.encode("idna").decode("ascii").lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} contains an invalid port") from exc
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    return urlunsplit((scheme, hostname, parsed.path or "/", parsed.query, ""))


def _normalize_domain(domain: str) -> str:
    if not isinstance(domain, str) or not domain.strip():
        raise ValueError("domain must be a non-empty hostname")
    candidate = domain.strip().lower()
    if any(character.isspace() for character in candidate):
        raise ValueError("domain must not contain whitespace")
    if "://" in candidate or any(character in candidate for character in "/?#"):
        raise ValueError("domain must be a hostname, not a URL")
    candidate = candidate.removeprefix("*.").lstrip(".").rstrip(".")
    if not candidate:
        raise ValueError("domain must contain a hostname")

    try:
        labels = [label.encode("idna").decode("ascii") for label in candidate.split(".")]
    except UnicodeError as exc:
        raise ValueError("domain contains an invalid hostname") from exc
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise ValueError("domain contains an invalid hostname")
    return ".".join(labels)


def _normalize_url_pattern(url_pattern: str) -> str:
    if not isinstance(url_pattern, str) or not url_pattern.strip():
        raise ValueError("url_pattern must be a non-empty string")
    candidate = url_pattern.strip()
    if any(character.isspace() for character in candidate):
        raise ValueError("url_pattern must not contain whitespace")
    if "#" in candidate:
        raise ValueError("url_pattern must not contain a URL fragment")
    wildcard_count = candidate.count("*")
    if wildcard_count > 1 or (
        wildcard_count == 1
        and not (candidate.startswith("*.") or candidate.endswith("*"))
    ):
        raise ValueError(
            "url_pattern supports one CDX domain wildcard ('*.host') or prefix wildcard ('prefix*')"
        )

    if candidate.startswith("*."):
        # CDX domain matching already includes every path, so a path suffix
        # would be both redundant and invalid for this wildcard mode.
        return f"*.{_normalize_domain(candidate[2:])}"

    validation_candidate = candidate.replace("*", "placeholder")
    if "://" in validation_candidate:
        parsed = urlsplit(validation_candidate)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url_pattern must identify an HTTP(S) URL")
    else:
        host = validation_candidate.split("/", 1)[0]
        _normalize_domain(host)
    return candidate


def _url_matches_domain(url: str, domain: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower().rstrip(".")
    return hostname == domain or hostname.endswith(f".{domain}")


def _url_matches_pattern(url: str, pattern: str) -> bool:
    if pattern.startswith("*."):
        return _url_matches_domain(url, pattern[2:])
    # cdx-toolkit also accepts scheme-less prefixes such as ``example.gov/law/*``.
    candidates = [url]
    if "://" not in pattern:
        candidates.append(url.split("://", 1)[-1])
    if pattern.endswith("*"):
        prefix = pattern[:-1]
        return any(candidate.startswith(prefix) for candidate in candidates)
    return pattern in candidates


def _resolve_search_selector(
    *,
    domain: Optional[str],
    url_prefix: Optional[str],
    url_pattern: Optional[str],
    canonical_urls: Optional[Sequence[str]],
) -> Tuple[str, Optional[str], Set[str]]:
    supplied = [domain is not None, url_prefix is not None, url_pattern is not None]
    if sum(supplied) != 1:
        raise ValueError("supply exactly one of domain, url_prefix, or url_pattern")

    normalized_domain: Optional[str] = None
    normalized_prefix: Optional[str] = None
    if domain is not None:
        normalized_domain = _normalize_domain(domain)
        query_pattern = f"*.{normalized_domain}"
    elif url_prefix is not None:
        if "*" in url_prefix:
            raise ValueError("url_prefix must not contain wildcards; use url_pattern instead")
        normalized_prefix = _canonical_http_url(url_prefix, field="url_prefix")
        query_pattern = f"{normalized_prefix}*"
    else:
        query_pattern = _normalize_url_pattern(str(url_pattern))

    exact_urls: Set[str] = set()
    if canonical_urls is not None:
        if isinstance(canonical_urls, (str, bytes)) or not canonical_urls:
            raise ValueError("canonical_urls must be a non-empty sequence of HTTP(S) URLs")
        exact_urls = {
            _canonical_http_url(candidate, field="canonical_urls item")
            for candidate in canonical_urls
        }
        for candidate in exact_urls:
            if normalized_domain is not None and not _url_matches_domain(candidate, normalized_domain):
                raise ValueError("every canonical URL must be within the selected domain")
            if normalized_prefix is not None and not candidate.startswith(normalized_prefix):
                raise ValueError("every canonical URL must be within url_prefix")
            if url_pattern is not None and not _url_matches_pattern(candidate, query_pattern):
                raise ValueError("every canonical URL must match url_pattern")

    return query_pattern, normalized_domain, exact_urls


def _json_cdx_record(data: Mapping[str, Any]) -> Dict[str, Any]:
    """Keep both legacy aliases and the native page/status/mime/WARC fields."""

    page = data.get("url", data.get("page", ""))
    status = data.get("status", data.get("status_code", ""))
    mime = data.get("mime", data.get("mime_type", ""))
    filename = data.get("filename", data.get("warc_filename", ""))
    offset = data.get("offset", data.get("warc_offset", ""))
    length = data.get("length", data.get("warc_length", ""))
    result = dict(data)
    result.update(
        {
            "url": page,
            "page": page,
            "timestamp": data.get("timestamp", ""),
            "status": status,
            "status_code": status,
            "mime": mime,
            "mime_type": mime,
            "digest": data.get("digest", ""),
            "filename": filename,
            "offset": offset,
            "length": length,
            "warc_filename": filename,
            "warc_offset": offset,
            "warc_length": length,
        }
    )
    return result


def _run_cdx_search(
    queue: Any,
    *,
    fetcher_kwargs: Dict[str, Any],
    search_kwargs: Dict[str, Any],
    record_cap: int,
    output_format: Literal["json", "cdx"],
    canonical_urls: Set[str],
) -> None:
    """Run exactly one CDX iterator in a killable worker process."""

    records: List[Dict[str, Any]] = []
    records_examined = 0
    try:
        from cdx_toolkit import CDXFetcher

        cdx = CDXFetcher(**fetcher_kwargs)
        truncated = False
        for record in cdx.iter(**search_kwargs):
            records_examined += 1
            if records_examined > record_cap:
                truncated = True
                break

            raw_data = getattr(record, "data", record)
            if not isinstance(raw_data, Mapping):
                raise TypeError("cdx-toolkit returned a record without mapping data")
            data = dict(raw_data)
            if canonical_urls:
                page = data.get("url", data.get("page", ""))
                try:
                    canonical_page = _canonical_http_url(str(page), field="CDX record URL")
                except ValueError:
                    continue
                if canonical_page not in canonical_urls:
                    continue
            records.append(_json_cdx_record(data) if output_format == "json" else data)

        queue.put(
            {
                "ok": True,
                "records": records,
                "records_examined": records_examined,
                "truncated": truncated,
                "complete": not truncated,
            }
        )
    except Exception as exc:
        queue.put(
            {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "records": records,
                "records_examined": records_examined,
                "truncated": False,
                "complete": False,
            }
        )


async def search_common_crawl(
    domain: Optional[str] = None,
    crawl_id: Optional[str] = None,
    limit: int = 100,
    from_timestamp: Optional[str] = None,
    to_timestamp: Optional[str] = None,
    output_format: Literal["json", "cdx"] = "json",
    *,
    url_prefix: Optional[str] = None,
    url_pattern: Optional[str] = None,
    canonical_urls: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Search Common Crawl through one domain/prefix iterator.

    Args:
        domain: Backward-compatible domain search (e.g., ``example.com``).
        crawl_id: Specific crawl ID (e.g., "CC-MAIN-2024-10"), defaults to latest
        limit: Strict maximum number of CDX records to inspect and return
        from_timestamp: Start timestamp filter (YYYYMMDD format)
        to_timestamp: End timestamp filter (YYYYMMDD format)
        output_format: Output format - "json" or "cdx"
        url_prefix: Absolute HTTP(S) prefix. Converted to one CDX prefix query.
        url_pattern: Explicit CDX URL pattern. Mutually exclusive with the other selectors.
        canonical_urls: Optional exact URL allow-list applied locally to the one iterator.

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: List of matching records
            - crawl_info: Information about the crawl used
            - count: Number of results returned
            - complete: True only when the CDX iterator exhausted cleanly
            - truncated: True when a cap-plus-one record proves more data exists
            - error: Error message (if failed)
    """
    try:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if output_format not in {"json", "cdx"}:
            raise ValueError("output_format must be 'json' or 'cdx'")
        query_pattern, normalized_domain, exact_urls = _resolve_search_selector(
            domain=domain,
            url_prefix=url_prefix,
            url_pattern=url_pattern,
            canonical_urls=canonical_urls,
        )
        try:
            timeout_seconds = float(
                os.getenv("COMMON_CRAWL_CDX_SEARCH_TIMEOUT_SECONDS", "180")
            )
        except ValueError as exc:
            raise ValueError("COMMON_CRAWL_CDX_SEARCH_TIMEOUT_SECONDS must be numeric") from exc
        if timeout_seconds <= 0:
            raise ValueError("COMMON_CRAWL_CDX_SEARCH_TIMEOUT_SECONDS must be positive")

        try:
            import cdx_toolkit
        except ImportError:
            return _error_search_result(
                "cdx-toolkit not installed. Install with: pip install cdx-toolkit"
            )
        if not hasattr(cdx_toolkit, "CDXFetcher"):
            return _error_search_result("cdx-toolkit does not expose CDXFetcher")
    except (TypeError, ValueError) as exc:
        return _error_search_result(f"Invalid Common Crawl search configuration: {exc}")

    fetcher_kwargs: Dict[str, Any] = {"source": "cc"}
    if crawl_id:
        fetcher_kwargs["crawl"] = [crawl_id]
    search_kwargs: Dict[str, Any] = {"url": query_pattern, "limit": limit + 1}
    if from_timestamp:
        search_kwargs["from_ts"] = from_timestamp
    if to_timestamp:
        search_kwargs["to"] = to_timestamp

    records: List[Dict[str, Any]] = []
    process: Optional[mp.Process] = None
    queue: Optional[mp.Queue] = None
    try:
        queue = mp.Queue(maxsize=1)
        process = mp.Process(
            target=_run_cdx_search,
            kwargs={
                "queue": queue,
                "fetcher_kwargs": fetcher_kwargs,
                "search_kwargs": search_kwargs,
                "record_cap": limit,
                "output_format": output_format,
                "canonical_urls": exact_urls,
            },
            daemon=True,
        )
        process.start()
        try:
            # Drain the result before joining. A large result can fill the Queue
            # pipe and keep the worker alive until the parent starts reading it.
            payload = await anyio.to_thread.run_sync(queue.get, True, timeout_seconds)
        except queue_module.Empty:
            if process.is_alive():
                process.terminate()
                await anyio.to_thread.run_sync(process.join, 5.0)
                logger.warning(
                    "Common Crawl CDX query %s timed out after %.1fs",
                    query_pattern,
                    timeout_seconds,
                )
                return _error_search_result(
                    f"Common Crawl search timed out after {timeout_seconds:.1f}s"
                )
            exit_code = getattr(process, "exitcode", None)
            return _error_search_result(
                f"Common Crawl search worker exited without a result (exit code {exit_code})"
            )

        await anyio.to_thread.run_sync(process.join, 5.0)
        if process.is_alive():
            process.terminate()
            await anyio.to_thread.run_sync(process.join, 5.0)
            return _error_search_result(
                "Common Crawl search worker did not exit after returning its result"
            )

        records = list(payload.get("records") or [])
        if not payload.get("ok"):
            error = str(payload.get("error") or "Common Crawl search failed")
            logger.warning("Common Crawl CDX query %s failed: %s", query_pattern, error)
            return _error_search_result(error, records)
    except asyncio.TimeoutError:
        if process is not None and process.is_alive():
            process.terminate()
            await anyio.to_thread.run_sync(process.join, 5.0)
        return _error_search_result(
            f"Common Crawl search timed out after {timeout_seconds:.1f}s", records
        )
    except Exception as search_error:
        logger.warning("Common Crawl CDX query %s failed: %s", query_pattern, search_error)
        return _error_search_result(
            f"{type(search_error).__name__}: {search_error}", records
        )
    finally:
        if queue is not None:
            try:
                queue.close()
                queue.join_thread()
            except (AttributeError, OSError, ValueError):
                pass

    truncated = bool(payload.get("truncated"))
    complete = bool(payload.get("complete")) and not truncated
    return {
        "status": "success",
        "results": records,
        "count": len(records),
        "records_examined": int(payload.get("records_examined") or 0),
        "complete": complete,
        "truncated": truncated,
        "crawl_info": {
            "source": "cc",
            "crawl": [crawl_id] if crawl_id else None,
            "domain": normalized_domain,
            "url_pattern": query_pattern,
            "canonical_url_count": len(exact_urls),
            "search_timestamp": datetime.now().isoformat(),
        },
    }


async def get_common_crawl_content(
    url: str, timestamp: str, crawl_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get content from Common Crawl for a specific URL and timestamp.

    Args:
        url: URL to retrieve content for
        timestamp: Timestamp of the capture (YYYYMMDDHHMMSS format)
        crawl_id: Specific crawl ID to search in

    Returns:
        Dict containing:
            - status: "success" or "error"
            - content: Raw content (if successful)
            - content_type: MIME type of the content
            - headers: HTTP headers
            - error: Error message (if failed)
    """
    try:
        try:
            from cdx_toolkit import CDXFetcher
            import requests
        except ImportError as e:
            return {"status": "error", "error": f"Required libraries not installed: {e}"}

        # A collection ID scopes the Common Crawl source; it is not itself a source.
        fetcher_kwargs: Dict[str, Any] = {"source": "cc"}
        if crawl_id:
            fetcher_kwargs["crawl"] = [crawl_id]
        cdx = CDXFetcher(**fetcher_kwargs)

        # Find the specific record
        records = list(cdx.iter(url=url, from_ts=timestamp, to=timestamp, limit=1))

        if not records:
            return {
                "status": "error",
                "error": "No records found for the specified URL and timestamp",
            }

        record = records[0]

        # Get WARC file URL and offset
        warc_url = f"https://commoncrawl.s3.amazonaws.com/{record.data.get('filename', '')}"
        offset = int(record.data.get("offset", 0))
        length = int(record.data.get("length", 0))

        # Download content from WARC
        headers = {"Range": f"bytes={offset}-{offset + length - 1}"}
        response = requests.get(warc_url, headers=headers, timeout=30)
        response.raise_for_status()

        return {
            "status": "success",
            "content": response.content,
            "content_type": record.data.get("mime", "application/octet-stream"),
            "headers": dict(response.headers),
            "warc_info": {
                "filename": record.data.get("filename", ""),
                "offset": offset,
                "length": length,
                "digest": record.data.get("digest", ""),
            },
        }

    except Exception as e:
        logger.error(f"Failed to get Common Crawl content for {url}: {e}")
        return {"status": "error", "error": str(e)}


async def list_common_crawl_indexes() -> Dict[str, Any]:
    """List available Common Crawl indexes.

    Returns:
        Dict containing:
            - status: "success" or "error"
            - indexes: List of available crawl indexes
            - count: Number of available indexes
            - error: Error message (if failed)
    """
    try:
        try:
            from cdx_toolkit import CDXFetcher
        except ImportError:
            return {
                "status": "error",
                "error": "cdx-toolkit not installed. Install with: pip install cdx-toolkit",
            }

        # Get list of available indexes
        cdx = CDXFetcher()
        indexes = cdx.list_cc_datasets()

        return {"status": "success", "indexes": indexes, "count": len(indexes)}

    except Exception as e:
        logger.error(f"Failed to list Common Crawl indexes: {e}")
        return {"status": "error", "error": str(e)}

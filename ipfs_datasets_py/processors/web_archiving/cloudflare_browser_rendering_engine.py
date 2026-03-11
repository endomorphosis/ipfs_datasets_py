"""Cloudflare Browser Rendering crawl engine.

Core domain logic for starting and retrieving Cloudflare Browser Rendering
``/crawl`` jobs. The endpoint is asynchronous: callers create a job, poll for a
terminal status, and then fetch the crawl records.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import anyio

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = {
    "completed",
    "errored",
    "cancelled_by_user",
    "cancelled_due_to_limits",
    "cancelled_due_to_timeout",
}


def _first_env(*names: str) -> Optional[str]:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def _resolve_credentials(
    account_id: Optional[str] = None,
    api_token: Optional[str] = None,
) -> tuple[str, str]:
    resolved_account_id = (
        account_id
        or _first_env(
            "IPFS_DATASETS_CLOUDFLARE_ACCOUNT_ID",
            "LEGAL_SCRAPER_CLOUDFLARE_ACCOUNT_ID",
            "CLOUDFLARE_ACCOUNT_ID",
        )
        or ""
    ).strip()
    resolved_api_token = (
        api_token
        or _first_env(
            "IPFS_DATASETS_CLOUDFLARE_API_TOKEN",
            "LEGAL_SCRAPER_CLOUDFLARE_API_TOKEN",
            "CLOUDFLARE_API_TOKEN",
        )
        or ""
    ).strip()
    if not resolved_account_id or not resolved_api_token:
        raise ValueError(
            "Cloudflare Browser Rendering requires account_id and api_token"
        )
    return resolved_account_id, resolved_api_token


def _endpoint(account_id: str, job_id: Optional[str] = None) -> str:
    base = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/browser-rendering/crawl"
    if job_id:
        return f"{base}/{job_id}"
    return base


def _headers(api_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


def _extract_error_message(payload: Dict[str, Any]) -> str:
    errors = payload.get("errors") or []
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            code = str(first.get("code") or "").strip()
            message = str(first.get("message") or "").strip()
            if code and message:
                return f"{code}: {message}"
            if message:
                return message
            if code:
                return code
        return str(first)
    return str(payload.get("message") or payload or "Cloudflare API request failed")


def _build_payload(
    *,
    url: str,
    limit: Optional[int] = None,
    depth: Optional[int] = None,
    formats: Optional[Iterable[str]] = None,
    render: Optional[bool] = None,
    source: Optional[str] = None,
    max_age: Optional[int] = None,
    modified_since: Optional[int] = None,
    user_agent: Optional[str] = None,
    include_external_links: Optional[bool] = None,
    include_subdomains: Optional[bool] = None,
    include_patterns: Optional[Iterable[str]] = None,
    exclude_patterns: Optional[Iterable[str]] = None,
    extra_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"url": url}
    if limit is not None:
        payload["limit"] = int(limit)
    if depth is not None:
        payload["depth"] = int(depth)
    if formats:
        payload["formats"] = [str(item) for item in formats if str(item).strip()]
    if render is not None:
        payload["render"] = bool(render)
    if source:
        payload["source"] = str(source)
    if max_age is not None:
        payload["maxAge"] = int(max_age)
    if modified_since is not None:
        payload["modifiedSince"] = int(modified_since)
    if user_agent:
        payload["userAgent"] = str(user_agent)

    options: Dict[str, Any] = {}
    if include_external_links is not None:
        options["includeExternalLinks"] = bool(include_external_links)
    if include_subdomains is not None:
        options["includeSubdomains"] = bool(include_subdomains)
    if include_patterns:
        options["includePatterns"] = [str(item) for item in include_patterns if str(item).strip()]
    if exclude_patterns:
        options["excludePatterns"] = [str(item) for item in exclude_patterns if str(item).strip()]
    if options:
        payload["options"] = options

    if extra_body:
        payload.update(dict(extra_body))
    return payload


async def start_cloudflare_browser_rendering_crawl(
    url: str,
    *,
    account_id: Optional[str] = None,
    api_token: Optional[str] = None,
    limit: Optional[int] = None,
    depth: Optional[int] = None,
    formats: Optional[Iterable[str]] = None,
    render: Optional[bool] = None,
    source: Optional[str] = None,
    max_age: Optional[int] = None,
    modified_since: Optional[int] = None,
    user_agent: Optional[str] = None,
    include_external_links: Optional[bool] = None,
    include_subdomains: Optional[bool] = None,
    include_patterns: Optional[Iterable[str]] = None,
    exclude_patterns: Optional[Iterable[str]] = None,
    request_timeout_seconds: int = 30,
    extra_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Start a Cloudflare Browser Rendering crawl job."""
    try:
        import requests

        resolved_account_id, resolved_api_token = _resolve_credentials(account_id, api_token)
        payload = _build_payload(
            url=url,
            limit=limit,
            depth=depth,
            formats=formats,
            render=render,
            source=source,
            max_age=max_age,
            modified_since=modified_since,
            user_agent=user_agent,
            include_external_links=include_external_links,
            include_subdomains=include_subdomains,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            extra_body=extra_body,
        )
        response = requests.post(
            _endpoint(resolved_account_id),
            headers=_headers(resolved_api_token),
            json=payload,
            timeout=request_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            return {
                "status": "error",
                "error": _extract_error_message(body),
                "submitted_url": url,
            }

        result = body.get("result")
        job_id = ""
        if isinstance(result, dict):
            job_id = str(result.get("id") or result.get("job_id") or "").strip()
        else:
            job_id = str(result or "").strip()
        if not job_id:
            return {
                "status": "error",
                "error": "Cloudflare crawl response did not include a job id",
                "submitted_url": url,
                "raw": body,
            }
        return {
            "status": "success",
            "job_id": job_id,
            "submitted_url": url,
            "submitted_at": datetime.utcnow().isoformat(),
            "request": payload,
        }
    except Exception as exc:
        logger.warning("Cloudflare crawl start failed for %s: %s", url, exc)
        return {
            "status": "error",
            "error": str(exc),
            "submitted_url": url,
        }


async def get_cloudflare_browser_rendering_crawl(
    job_id: str,
    *,
    account_id: Optional[str] = None,
    api_token: Optional[str] = None,
    cursor: Optional[object] = None,
    limit: Optional[int] = None,
    status_filter: Optional[str] = None,
    request_timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Fetch Cloudflare crawl status or results for a job."""
    try:
        import requests

        resolved_account_id, resolved_api_token = _resolve_credentials(account_id, api_token)
        params: Dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = int(limit)
        if status_filter:
            params["status"] = str(status_filter)

        response = requests.get(
            _endpoint(resolved_account_id, job_id=job_id),
            headers=_headers(resolved_api_token),
            params=params or None,
            timeout=request_timeout_seconds,
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("success"):
            return {
                "status": "error",
                "error": _extract_error_message(body),
                "job_id": job_id,
            }
        job = body.get("result") or {}
        return {
            "status": "success",
            "job_id": job_id,
            "job": job,
        }
    except Exception as exc:
        logger.warning("Cloudflare crawl lookup failed for %s: %s", job_id, exc)
        return {
            "status": "error",
            "error": str(exc),
            "job_id": job_id,
        }


async def cancel_cloudflare_browser_rendering_crawl(
    job_id: str,
    *,
    account_id: Optional[str] = None,
    api_token: Optional[str] = None,
    request_timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """Cancel an in-flight Cloudflare crawl job."""
    try:
        import requests

        resolved_account_id, resolved_api_token = _resolve_credentials(account_id, api_token)
        response = requests.delete(
            _endpoint(resolved_account_id, job_id=job_id),
            headers=_headers(resolved_api_token),
            timeout=request_timeout_seconds,
        )
        response.raise_for_status()
        return {
            "status": "success",
            "job_id": job_id,
            "cancelled_at": datetime.utcnow().isoformat(),
        }
    except Exception as exc:
        logger.warning("Cloudflare crawl cancel failed for %s: %s", job_id, exc)
        return {
            "status": "error",
            "error": str(exc),
            "job_id": job_id,
        }


async def _collect_records(
    job_id: str,
    *,
    account_id: Optional[str],
    api_token: Optional[str],
    limit: Optional[int],
    status_filter: Optional[str],
    request_timeout_seconds: int,
) -> Dict[str, Any]:
    records: List[Dict[str, Any]] = []
    cursor: Optional[object] = None
    final_job: Dict[str, Any] = {}
    remaining = int(limit) if limit is not None else None

    while True:
        page_limit = remaining if remaining is not None else limit
        page = await get_cloudflare_browser_rendering_crawl(
            job_id,
            account_id=account_id,
            api_token=api_token,
            cursor=cursor,
            limit=page_limit,
            status_filter=status_filter,
            request_timeout_seconds=request_timeout_seconds,
        )
        if page.get("status") != "success":
            return page
        final_job = dict(page.get("job") or {})
        page_records = list(final_job.get("records") or [])
        records.extend(page_records)

        if remaining is not None:
            remaining -= len(page_records)
            if remaining <= 0:
                break

        cursor = final_job.get("cursor")
        if cursor in (None, "", 0):
            break

    final_job["records"] = records[:limit] if limit is not None else records
    return {
        "status": "success",
        "job_id": job_id,
        "job": final_job,
        "records": final_job.get("records") or [],
    }


async def wait_for_cloudflare_browser_rendering_crawl(
    job_id: str,
    *,
    account_id: Optional[str] = None,
    api_token: Optional[str] = None,
    timeout_seconds: int = 120,
    poll_interval_seconds: float = 2.0,
    limit: Optional[int] = None,
    status_filter: Optional[str] = None,
    request_timeout_seconds: int = 30,
    cancel_on_timeout: bool = True,
) -> Dict[str, Any]:
    """Poll a Cloudflare crawl job until completion and fetch its records."""
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        page = await get_cloudflare_browser_rendering_crawl(
            job_id,
            account_id=account_id,
            api_token=api_token,
            limit=1,
            request_timeout_seconds=request_timeout_seconds,
        )
        if page.get("status") != "success":
            return page

        job = dict(page.get("job") or {})
        job_status = str(job.get("status") or "").strip().lower()
        if job_status in _TERMINAL_STATUSES:
            if job_status != "completed":
                return {
                    "status": job_status or "error",
                    "job_id": job_id,
                    "job": job,
                    "error": str(job.get("error") or f"Cloudflare crawl ended with status {job_status}").strip(),
                }
            result = await _collect_records(
                job_id,
                account_id=account_id,
                api_token=api_token,
                limit=limit,
                status_filter=status_filter,
                request_timeout_seconds=request_timeout_seconds,
            )
            if result.get("status") == "success":
                return {
                    "status": "success",
                    "job_id": job_id,
                    "job": result.get("job") or {},
                    "records": result.get("records") or [],
                }
            return result

        await anyio.sleep(max(0.1, float(poll_interval_seconds)))

    timeout_result: Dict[str, Any] = {
        "status": "timeout",
        "job_id": job_id,
        "error": f"Cloudflare crawl did not complete within {timeout_seconds} seconds",
    }
    if cancel_on_timeout:
        cancel_result = await cancel_cloudflare_browser_rendering_crawl(
            job_id,
            account_id=account_id,
            api_token=api_token,
            request_timeout_seconds=request_timeout_seconds,
        )
        timeout_result["cancel_result"] = cancel_result
    return timeout_result


async def crawl_with_cloudflare_browser_rendering(
    url: str,
    *,
    account_id: Optional[str] = None,
    api_token: Optional[str] = None,
    wait_for_completion: bool = True,
    timeout_seconds: int = 120,
    poll_interval_seconds: float = 2.0,
    request_timeout_seconds: int = 30,
    limit: Optional[int] = None,
    depth: Optional[int] = None,
    formats: Optional[Iterable[str]] = None,
    render: Optional[bool] = None,
    source: Optional[str] = None,
    max_age: Optional[int] = None,
    modified_since: Optional[int] = None,
    user_agent: Optional[str] = None,
    include_external_links: Optional[bool] = None,
    include_subdomains: Optional[bool] = None,
    include_patterns: Optional[Iterable[str]] = None,
    exclude_patterns: Optional[Iterable[str]] = None,
    status_filter: Optional[str] = None,
    extra_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run a complete Cloudflare crawl workflow for a URL."""
    started = await start_cloudflare_browser_rendering_crawl(
        url,
        account_id=account_id,
        api_token=api_token,
        limit=limit,
        depth=depth,
        formats=formats,
        render=render,
        source=source,
        max_age=max_age,
        modified_since=modified_since,
        user_agent=user_agent,
        include_external_links=include_external_links,
        include_subdomains=include_subdomains,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        request_timeout_seconds=request_timeout_seconds,
        extra_body=extra_body,
    )
    if started.get("status") != "success":
        return started
    if not wait_for_completion:
        return started

    job_id = str(started.get("job_id") or "").strip()
    finished = await wait_for_cloudflare_browser_rendering_crawl(
        job_id,
        account_id=account_id,
        api_token=api_token,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        limit=limit,
        status_filter=status_filter,
        request_timeout_seconds=request_timeout_seconds,
    )
    if finished.get("status") == "success":
        finished["submitted_url"] = url
    return finished


__all__ = [
    "start_cloudflare_browser_rendering_crawl",
    "get_cloudflare_browser_rendering_crawl",
    "wait_for_cloudflare_browser_rendering_crawl",
    "cancel_cloudflare_browser_rendering_crawl",
    "crawl_with_cloudflare_browser_rendering",
]
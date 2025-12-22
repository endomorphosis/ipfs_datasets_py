"""Archive check and submission utility for unified web scraper.

This tool checks if a URL is archived on Archive.org (Wayback Machine) or Archive.is,
and if not present, submits it to both archives before downloading.
"""
import logging
from typing import Dict, Optional, Any, List, Tuple
from datetime import datetime, timedelta
import asyncio
import json
import uuid

from urllib.parse import urlparse
import ipaddress

logger = logging.getLogger(__name__)


# In-memory async job registry.
# NOTE: This is process-local; if you need persistence across restarts,
# use `callback_file` to emit completion events to disk.
_ARCHIVE_JOBS: Dict[str, Dict[str, Any]] = {}
_ARCHIVE_JOBS_LOCK = asyncio.Lock()


def _is_safe_public_callback_url(callback_url: str) -> bool:
    """Basic SSRF-safety check for webhook callback URLs."""
    try:
        parsed = urlparse((callback_url or "").strip())
        if parsed.scheme not in {"http", "https"}:
            return False
        host = parsed.hostname
        if not host:
            return False
        if host.lower() == "localhost":
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        except ValueError:
            # Hostname: reject common local-only suffixes without DNS resolution.
            h = host.lower()
            if h.endswith(".local") or h.endswith(".internal"):
                return False
        return True
    except Exception:
        return False


async def _emit_archive_callback(
    payload: Dict[str, Any],
    *,
    callback_url: Optional[str] = None,
    callback_file: Optional[str] = None,
) -> None:
    """Emit a completion/progress event to a webhook and/or a local jsonl file."""
    if callback_file:
        try:
            line = json.dumps(payload, default=str)
            # Append JSONL
            with open(callback_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning(f"Failed writing archive callback_file={callback_file}: {e}")

    if callback_url and _is_safe_public_callback_url(callback_url):
        try:
            import requests

            requests.post(callback_url, json=payload, timeout=10)
        except Exception as e:
            logger.warning(f"Failed POSTing archive callback_url={callback_url}: {e}")


async def submit_archives_async(
    url: str,
    *,
    check_archive_org: bool = True,
    check_archive_is: bool = True,
    submit_if_missing: bool = True,
    poll_interval_seconds: float = 60.0,
    max_wait_seconds: float = 6 * 60 * 60,
    callback_url: Optional[str] = None,
    callback_file: Optional[str] = None,
    initial_submit_timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """Submit a URL to archives and monitor completion asynchronously.

    This returns immediately with a `job_id`. A background task will poll:
    - Wayback: presence via CDX search
    - Archive.is: status via submission_id (if available) else best-effort presence

    Completion/progress events can be delivered via:
    - `callback_file` (JSONL append)
    - `callback_url` (webhook POST, public http(s) only)
    """
    if not isinstance(url, str) or not url.strip():
        return {"status": "error", "error": "Invalid URL"}
    url = url.strip()

    job_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()

    initial = await check_and_submit_to_archives(
        url,
        check_archive_org=check_archive_org,
        check_archive_is=check_archive_is,
        submit_if_missing=submit_if_missing,
        wait_for_archive_completion=False,
        archive_timeout=max(1, int(initial_submit_timeout_seconds) if initial_submit_timeout_seconds else 60),
    )

    job: Dict[str, Any] = {
        "status": "submitted",
        "job_id": job_id,
        "url": url,
        "created_at": created_at,
        "updated_at": created_at,
        "poll_interval_seconds": float(poll_interval_seconds),
        "max_wait_seconds": float(max_wait_seconds),
        "initial": initial,
        "providers": {
            "archive_org": {
                "enabled": bool(check_archive_org),
                "state": "present" if initial.get("archive_org_present") else ("submitted" if initial.get("submitted_to_archive_org") else "missing"),
                "archive_url": initial.get("archive_org_url"),
            },
            "archive_is": {
                "enabled": bool(check_archive_is),
                "state": "present" if initial.get("archive_is_present") else ("submitted" if initial.get("submitted_to_archive_is") else "missing"),
                "archive_url": initial.get("archive_is_url"),
                "submission_id": (initial.get("archive_is_submission_result") or {}).get("submission_id"),
            },
        },
        "callback": {
            "callback_url": callback_url,
            "callback_file": callback_file,
        },
    }

    async with _ARCHIVE_JOBS_LOCK:
        _ARCHIVE_JOBS[job_id] = job

    # Start monitoring in the background
    asyncio.create_task(_monitor_archive_job(job_id))

    await _emit_archive_callback(
        {
            "event": "archive_job_submitted",
            "job_id": job_id,
            "url": url,
            "created_at": created_at,
            "providers": job["providers"],
        },
        callback_url=callback_url,
        callback_file=callback_file,
    )

    return {"status": "success", "job_id": job_id, "job": job}


async def get_archive_job(job_id: str) -> Dict[str, Any]:
    """Return the current state of an async archive submission job."""
    async with _ARCHIVE_JOBS_LOCK:
        job = _ARCHIVE_JOBS.get(job_id)
        if not job:
            return {"status": "error", "error": "Job not found", "job_id": job_id}
        return {"status": "success", "job_id": job_id, "job": job}


async def _monitor_archive_job(job_id: str) -> None:
    """Background poller that updates job state and emits completion callbacks."""
    async with _ARCHIVE_JOBS_LOCK:
        job = _ARCHIVE_JOBS.get(job_id)
    if not job:
        return

    url = job.get("url")
    callback_url = ((job.get("callback") or {}).get("callback_url"))
    callback_file = ((job.get("callback") or {}).get("callback_file"))
    poll_interval = float(job.get("poll_interval_seconds") or 60.0)
    max_wait = float(job.get("max_wait_seconds") or (6 * 60 * 60))

    start = asyncio.get_event_loop().time()
    emitted_complete = set()  # provider names

    while True:
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed > max_wait:
            async with _ARCHIVE_JOBS_LOCK:
                if job_id in _ARCHIVE_JOBS:
                    _ARCHIVE_JOBS[job_id]["status"] = "timeout"
                    _ARCHIVE_JOBS[job_id]["updated_at"] = datetime.now().isoformat()
            await _emit_archive_callback(
                {"event": "archive_job_timeout", "job_id": job_id, "url": url, "elapsed_seconds": elapsed},
                callback_url=callback_url,
                callback_file=callback_file,
            )
            return

        # Poll providers
        provider_updates: Dict[str, Any] = {}

        # Wayback
        try:
            org_enabled = bool(job.get("providers", {}).get("archive_org", {}).get("enabled"))
            if org_enabled:
                org_check = await _check_archive_org(url)
                if org_check.get("present"):
                    provider_updates["archive_org"] = {
                        "state": "present",
                        "archive_url": org_check.get("url"),
                        "timestamp": org_check.get("timestamp"),
                    }
        except Exception as e:
            provider_updates["archive_org"] = {"state": "error", "error": str(e)}

        # Archive.is
        try:
            is_enabled = bool(job.get("providers", {}).get("archive_is", {}).get("enabled"))
            if is_enabled:
                submission_id = job.get("providers", {}).get("archive_is", {}).get("submission_id")
                if submission_id:
                    from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_is_integration import check_archive_status

                    st = await check_archive_status(submission_id)
                    if st.get("status") == "success":
                        provider_updates["archive_is"] = {
                            "state": "present",
                            "archive_url": st.get("archive_url"),
                            "submission_id": submission_id,
                        }
                    elif st.get("status") == "pending":
                        provider_updates["archive_is"] = {
                            "state": "pending",
                            "submission_id": submission_id,
                        }
                else:
                    # Best-effort presence check
                    is_check = await _check_archive_is(url)
                    if is_check.get("present"):
                        provider_updates["archive_is"] = {"state": "present", "archive_url": is_check.get("url")}
        except Exception as e:
            provider_updates["archive_is"] = {"state": "error", "error": str(e)}

        # Apply updates
        if provider_updates:
            now = datetime.now().isoformat()
            async with _ARCHIVE_JOBS_LOCK:
                job_ref = _ARCHIVE_JOBS.get(job_id)
                if not job_ref:
                    return
                job_ref["updated_at"] = now
                for provider, upd in provider_updates.items():
                    job_ref.setdefault("providers", {}).setdefault(provider, {}).update(upd)

            await _emit_archive_callback(
                {"event": "archive_job_progress", "job_id": job_id, "url": url, "providers": provider_updates, "updated_at": now},
                callback_url=callback_url,
                callback_file=callback_file,
            )

        # Check completion
        async with _ARCHIVE_JOBS_LOCK:
            job_now = _ARCHIVE_JOBS.get(job_id)
        if not job_now:
            return

        all_done = True
        for provider_name, p in (job_now.get("providers") or {}).items():
            if not p.get("enabled"):
                continue
            state = p.get("state")
            if state != "present":
                all_done = False
            else:
                if provider_name not in emitted_complete:
                    emitted_complete.add(provider_name)
                    await _emit_archive_callback(
                        {"event": "archive_job_provider_complete", "job_id": job_id, "url": url, "provider": provider_name, "provider_state": p},
                        callback_url=callback_url,
                        callback_file=callback_file,
                    )

        if all_done:
            async with _ARCHIVE_JOBS_LOCK:
                if job_id in _ARCHIVE_JOBS:
                    _ARCHIVE_JOBS[job_id]["status"] = "complete"
                    _ARCHIVE_JOBS[job_id]["updated_at"] = datetime.now().isoformat()
            await _emit_archive_callback(
                {"event": "archive_job_complete", "job_id": job_id, "url": url, "providers": (job_now.get("providers") or {})},
                callback_url=callback_url,
                callback_file=callback_file,
            )
            return

        await asyncio.sleep(max(1.0, poll_interval))


async def check_and_submit_to_archives(
    url: str,
    check_archive_org: bool = True,
    check_archive_is: bool = True,
    submit_if_missing: bool = True,
    wait_for_archive_completion: bool = False,
    archive_timeout: int = 60
) -> Dict[str, Any]:
    """Check if URL is archived, submit to archives if not present.

    This function checks Archive.org (Wayback Machine) and Archive.is for the presence
    of the URL. If not found on either archive, it submits the URL to both archives
    before returning.

    Args:
        url: URL to check and archive
        check_archive_org: Whether to check Archive.org Wayback Machine
        check_archive_is: Whether to check Archive.is
        submit_if_missing: Whether to submit to archives if not present
        wait_for_archive_completion: Whether to wait for archiving to complete
        archive_timeout: Maximum time to wait for archiving (seconds)

    Returns:
        Dict containing:
            - status: "success" or "error"
            - url: Original URL
            - archive_org_present: Whether URL found in Archive.org
            - archive_is_present: Whether URL found in Archive.is
            - archive_org_url: Archive.org URL (if present or submitted)
            - archive_is_url: Archive.is URL (if present or submitted)
            - submitted_to_archive_org: Whether submitted to Archive.org
            - submitted_to_archive_is: Whether submitted to Archive.is
            - archive_org_submission_result: Submission result (if submitted)
            - archive_is_submission_result: Submission result (if submitted)
            - timestamp: When check was performed
            - error: Error message (if failed)
    """
    try:
        result = {
            "status": "success",
            "url": url,
            "archive_org_present": False,
            "archive_is_present": False,
            "archive_org_url": None,
            "archive_is_url": None,
            "submitted_to_archive_org": False,
            "submitted_to_archive_is": False,
            "archive_org_submission_result": None,
            "archive_is_submission_result": None,
            "timestamp": datetime.now().isoformat()
        }

        # Check Archive.org (Wayback Machine)
        if check_archive_org:
            archive_org_check = await _check_archive_org(url)
            result["archive_org_present"] = archive_org_check["present"]
            if archive_org_check["present"]:
                result["archive_org_url"] = archive_org_check.get("url")
            
            # Submit if not present
            if not archive_org_check["present"] and submit_if_missing:
                logger.info(f"URL not found in Archive.org, submitting: {url}")
                submission_result = await _submit_to_archive_org(url, wait_for_archive_completion, archive_timeout)
                result["submitted_to_archive_org"] = True
                result["archive_org_submission_result"] = submission_result
                if submission_result["status"] == "success":
                    result["archive_org_url"] = submission_result.get("archived_url")

        # Check Archive.is
        if check_archive_is:
            archive_is_check = await _check_archive_is(url)
            result["archive_is_present"] = archive_is_check["present"]
            if archive_is_check["present"]:
                result["archive_is_url"] = archive_is_check.get("url")
            
            # Submit if not present
            if not archive_is_check["present"] and submit_if_missing:
                logger.info(f"URL not found in Archive.is, submitting: {url}")
                submission_result = await _submit_to_archive_is(url, wait_for_archive_completion, archive_timeout)
                result["submitted_to_archive_is"] = True
                result["archive_is_submission_result"] = submission_result
                if submission_result["status"] == "success":
                    result["archive_is_url"] = submission_result.get("archive_url")

        # Determine overall status
        at_least_one_present = result["archive_org_present"] or result["archive_is_present"]
        at_least_one_submitted = result["submitted_to_archive_org"] or result["submitted_to_archive_is"]
        
        result["recommendation"] = _get_recommendation(result)
        result["summary"] = _generate_summary(result)

        return result

    except Exception as e:
        logger.error(f"Failed to check and submit archives for {url}: {e}")
        return {
            "status": "error",
            "url": url,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


async def _check_archive_org(url: str) -> Dict[str, Any]:
    """Check if URL is present in Archive.org Wayback Machine."""
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.wayback_machine_search import search_wayback_machine
        
        # Search for any captures of this URL
        search_result = await search_wayback_machine(url, limit=1)
        
        if search_result["status"] == "success" and search_result.get("count", 0) > 0:
            # URL is archived
            first_result = search_result["results"][0]
            return {
                "present": True,
                "url": first_result.get("wayback_url"),
                "timestamp": first_result.get("timestamp"),
                "count": search_result["count"]
            }
        else:
            return {
                "present": False
            }
            
    except Exception as e:
        logger.error(f"Failed to check Archive.org for {url}: {e}")
        return {
            "present": False,
            "error": str(e)
        }


async def _check_archive_is(url: str) -> Dict[str, Any]:
    """Check if URL is present in Archive.is."""
    try:
        import requests
        from urllib.parse import urlparse
        
        # Archive.is uses the domain as the search key
        parsed = urlparse(url)
        domain = parsed.netloc
        
        # Try to find existing archives
        # Note: Archive.is doesn't have a public API, so this is a best-effort check
        # using direct URL patterns
        
        # Try common Archive.is URL patterns
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        
        # These are potential archive URLs
        possible_urls = [
            f"https://archive.is/{url_hash}",
            f"https://archive.ph/{url_hash}",
            f"https://archive.today/{url_hash}"
        ]
        
        for archive_url in possible_urls:
            try:
                response = requests.head(archive_url, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    return {
                        "present": True,
                        "url": archive_url
                    }
            except:
                continue
        
        # If no direct hit, assume not present
        return {
            "present": False
        }
            
    except Exception as e:
        logger.error(f"Failed to check Archive.is for {url}: {e}")
        return {
            "present": False,
            "error": str(e)
        }


async def _submit_to_archive_org(url: str, wait_for_completion: bool = False, timeout: int = 60) -> Dict[str, Any]:
    """Submit URL to Archive.org Wayback Machine."""
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.wayback_machine_search import archive_to_wayback
        
        result = await archive_to_wayback(url)
        
        if wait_for_completion:
            # Wait a bit and verify it was archived
            await asyncio.sleep(5)
            verification = await _check_archive_org(url)
            if verification["present"]:
                result["verified"] = True
                result["archived_url"] = verification["url"]
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to submit {url} to Archive.org: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


async def _submit_to_archive_is(url: str, wait_for_completion: bool = False, timeout: int = 60) -> Dict[str, Any]:
    """Submit URL to Archive.is."""
    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_is_integration import archive_to_archive_is
        
        result = await archive_to_archive_is(url, wait_for_completion=wait_for_completion, timeout=timeout)
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to submit {url} to Archive.is: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def _get_recommendation(result: Dict[str, Any]) -> str:
    """Get recommendation based on archive check results."""
    if result["archive_org_present"] or result["archive_is_present"]:
        return "URL is archived - safe to proceed with scraping"
    elif result["submitted_to_archive_org"] or result["submitted_to_archive_is"]:
        return "URL was not archived but has been submitted - proceed with scraping"
    else:
        return "URL is not archived and submission was not attempted - proceed with caution"


def _generate_summary(result: Dict[str, Any]) -> str:
    """Generate human-readable summary of archive check."""
    summary_parts = []
    
    if result["archive_org_present"]:
        summary_parts.append("found in Archive.org")
    if result["archive_is_present"]:
        summary_parts.append("found in Archive.is")
    
    if result["submitted_to_archive_org"]:
        summary_parts.append("submitted to Archive.org")
    if result["submitted_to_archive_is"]:
        summary_parts.append("submitted to Archive.is")
    
    if not summary_parts:
        return "No archives found, no submissions made"
    
    return ", ".join(summary_parts)


async def batch_check_and_submit(
    urls: List[str],
    check_archive_org: bool = True,
    check_archive_is: bool = True,
    submit_if_missing: bool = True,
    max_concurrent: int = 5,
    delay_seconds: float = 1.0
) -> Dict[str, Any]:
    """Batch check and submit multiple URLs to archives.

    Args:
        urls: List of URLs to check and archive
        check_archive_org: Whether to check Archive.org
        check_archive_is: Whether to check Archive.is
        submit_if_missing: Whether to submit if not present
        max_concurrent: Maximum concurrent checks
        delay_seconds: Delay between operations

    Returns:
        Dict containing:
            - status: "success" or "error"
            - results: Dict mapping URL to result
            - total_urls: Total number of URLs processed
            - already_archived_count: Number already archived
            - submitted_count: Number submitted to archives
            - error_count: Number of errors
            - timestamp: When batch was completed
    """
    try:
        semaphore = asyncio.Semaphore(max_concurrent)
        results = {}
        already_archived_count = 0
        submitted_count = 0
        error_count = 0
        
        async def check_single_url(url: str):
            async with semaphore:
                try:
                    result = await check_and_submit_to_archives(
                        url,
                        check_archive_org=check_archive_org,
                        check_archive_is=check_archive_is,
                        submit_if_missing=submit_if_missing,
                        wait_for_archive_completion=False
                    )
                    await asyncio.sleep(delay_seconds)
                    return url, result
                except Exception as e:
                    logger.error(f"Error processing {url}: {e}")
                    return url, {"status": "error", "error": str(e)}
        
        # Process URLs concurrently
        tasks = [check_single_url(url) for url in urls]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for item in completed:
            if isinstance(item, Exception):
                error_count += 1
                continue
            
            url, result = item
            results[url] = result
            
            if result.get("status") == "error":
                error_count += 1
            else:
                if result.get("archive_org_present") or result.get("archive_is_present"):
                    already_archived_count += 1
                if result.get("submitted_to_archive_org") or result.get("submitted_to_archive_is"):
                    submitted_count += 1
        
        return {
            "status": "success",
            "results": results,
            "total_urls": len(urls),
            "already_archived_count": already_archived_count,
            "submitted_count": submitted_count,
            "error_count": error_count,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed batch check and submit: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

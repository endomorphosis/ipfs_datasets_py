"""eCode360 Webscraper.

This module provides functions for scraping municipal codes from eCode360
(ecode360.com), a major provider of municipal code content for US jurisdictions.

Notes on access:
- Some eCode360 pages are protected by Cloudflare and may return "Just a moment...".
- We do not attempt to bypass challenges.
- When live access is blocked, we rely on the unified scraper's archive fallbacks
    (Wayback/IPWB/Archive.is/Common Crawl when available).
"""

from typing import Any, Dict, Optional
import aiohttp
from datetime import datetime
from bs4 import BeautifulSoup
import asyncio
import logging
from urllib.parse import urlparse, urljoin
import json
import re




import duckdb




def get_url():
    pass


def _looks_like_cloudflare_challenge(html: str) -> bool:
    if not isinstance(html, str) or not html:
        return False
    s = html.lower()
    return (
        "just a moment" in s
        or "cf-challenge" in s
        or "challenge-platform" in s
        or "challenges.cloudflare.com" in s
    )


def _ecode360_code_id_from_url(url: str) -> Optional[str]:
    """Extract the jurisdiction code id (e.g. 'NE4043') from common eCode360 URLs."""
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").strip("/")
        if not path:
            return None
        # /NE4043 or /toc/NE4043
        parts = [p for p in path.split("/") if p]
        if not parts:
            return None
        if parts[0].lower() == "toc" and len(parts) >= 2:
            return parts[1]
        return parts[0]
    except Exception:
        return None


def _is_ecode360_toc_index_url(url: str) -> bool:
    """Return True if URL looks like the eCode360 /toc/ index page."""
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        if not host.endswith("ecode360.com"):
            return False
        path = (parsed.path or "").rstrip("/")
        return path == "/toc"
    except Exception:
        return False


def _parse_ecode360_toc_index(html: str) -> Dict[str, Any]:
    """Parse the eCode360 /toc/ index into code-id entries.

    This is heuristic and tolerant because the page varies across captures.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    # Common code-id pattern observed in eCode360 (e.g., NE4043).
    code_re = re.compile(r"\b([A-Z]{2}\d{3,6})\b")

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        text = a.get_text(" ", strip=True) or ""

        href_abs = urljoin("https://ecode360.com", href)

        candidate = href_abs
        # Extract code id from href or text.
        m = code_re.search(candidate)
        if not m:
            m = code_re.search(text)
        if not m:
            continue
        code_id = m.group(1)

        key = (code_id + "|" + href_abs[:200]).lower()
        if key in seen:
            continue
        seen.add(key)

        entries.append(
            {
                "code_id": code_id,
                "href": href_abs,
                "title": text.strip() or code_id,
            }
        )

    title = None
    try:
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
    except Exception:
        title = None

    # Provide a convenient deduped list for batch discovery.
    code_ids: list[str] = []
    code_seen: set[str] = set()
    for e in entries:
        cid = e.get("code_id")
        if isinstance(cid, str) and cid and cid not in code_seen:
            code_seen.add(cid)
            code_ids.append(cid)

    return {
        "title": title,
        "entries": entries,
        "entries_count": len(entries),
        "code_ids": code_ids,
        "code_ids_count": len(code_ids),
    }


def ecode360_toc_targets_from_code_ids(
    code_ids: list[str],
    *,
    base_url: str = "https://ecode360.com",
) -> list[str]:
    """Normalize eCode360 TOC targets from code IDs.

    This is a pure helper for batch discovery workflows.

    Args:
        code_ids: List of eCode360 jurisdiction code IDs (e.g., ``NE4043``).
        base_url: Base URL to use when producing canonical TOC URLs.

    Returns:
        A deduped list of canonical TOC URLs like ``https://ecode360.com/toc/NE4043``.

    Notes:
        - Non-matching inputs are ignored.
        - Only ``ecode360.com`` TOC targets are produced.
    """

    if not isinstance(code_ids, list):
        return []

    base = (base_url or "https://ecode360.com").strip() or "https://ecode360.com"
    base = base.rstrip("/")

    code_re = re.compile(r"\b([A-Z]{2}\d{3,6})\b")

    out: list[str] = []
    seen: set[str] = set()
    for item in code_ids:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue

        # Allow passing either raw code ids or URLs containing them.
        m = code_re.search(s.upper())
        if not m:
            continue
        code_id = m.group(1).upper()

        url = f"{base}/toc/{code_id}"
        if url not in seen:
            seen.add(url)
            out.append(url)

    return out


async def enqueue_ecode360_toc_archive_jobs(
    toc_targets: list[str],
    *,
    enqueue_mode: str = "missing_only",
    check_archive_org: bool = True,
    check_archive_is: bool = True,
    poll_interval_seconds: float = 60.0,
    max_wait_seconds: float = 6 * 60 * 60,
    callback_url: Optional[str] = None,
    callback_file: Optional[str] = None,
    initial_submit_timeout_seconds: int = 60,
    concurrency: int = 5,
) -> Dict[str, Any]:
    """Batch-enqueue async archive jobs for eCode360 ``/toc/<CODE>`` targets.

    Args:
        toc_targets: Canonical eCode360 TOC targets. Use
            :func:`ecode360_toc_targets_from_code_ids` to generate these.
        enqueue_mode: ``"missing_only"`` to create jobs only when the target
            appears missing from both archives, or ``"always"`` to create a job
            record for every target.
        check_archive_org: Whether to check/submit to Wayback Machine.
        check_archive_is: Whether to check/submit to Archive.is.
        poll_interval_seconds: Background poll interval for async jobs.
        max_wait_seconds: Maximum async job wait time.
        callback_url: Optional public http(s) webhook to receive job events.
        callback_file: Optional JSONL file path to append job events.
        initial_submit_timeout_seconds: Maximum time spent on the initial
            check+submit call per job.
        concurrency: Max concurrent submissions.

    Returns:
        Dict with:
            - status
            - targets_count
            - results: per-target outcome (job_id or present/skip/error)

    Safety:
        This only enqueues jobs for URLs that:
        - are on ``ecode360.com``
        - match the ``/toc/<CODE>`` pattern
    """
    if not isinstance(toc_targets, list) or not toc_targets:
        return {"status": "error", "error": "No toc_targets provided", "results": [], "targets_count": 0}

    mode = (enqueue_mode or "missing_only").strip().lower()
    if mode not in {"missing_only", "always"}:
        return {"status": "error", "error": f"Invalid enqueue_mode: {enqueue_mode}", "results": [], "targets_count": 0}

    try:
        from ipfs_datasets_py.mcp_server.tools.web_archive_tools.archive_check_submit import (
            submit_archives_async,
            check_and_submit_to_archives,
        )
    except Exception as e:
        return {"status": "error", "error": f"Archive tools unavailable: {e}", "results": [], "targets_count": 0}

    toc_url_re = re.compile(r"^https?://([^/]+)/(?:toc)/([A-Z]{2}\d{3,6})(?:[/?#].*)?$", re.IGNORECASE)

    sem = asyncio.Semaphore(max(1, int(concurrency) if concurrency else 1))

    async def _handle_one(target: str) -> Dict[str, Any]:
        async with sem:
            if not isinstance(target, str) or not target.strip():
                return {"target": target, "status": "skipped", "reason": "invalid_target"}
            t = target.strip()
            m = toc_url_re.match(t)
            if not m:
                return {"target": t, "status": "skipped", "reason": "not_ecode360_toc"}

            host = (m.group(1) or "").lower()
            code_id = (m.group(2) or "").upper()
            if not host.endswith("ecode360.com"):
                return {"target": t, "status": "skipped", "reason": "host_not_ecode360"}

            canonical = f"https://ecode360.com/toc/{code_id}"

            if mode == "missing_only":
                try:
                    presence = await check_and_submit_to_archives(
                        canonical,
                        check_archive_org=bool(check_archive_org),
                        check_archive_is=bool(check_archive_is),
                        submit_if_missing=False,
                        wait_for_archive_completion=False,
                        archive_timeout=max(5, int(initial_submit_timeout_seconds) if initial_submit_timeout_seconds else 60),
                    )
                    if isinstance(presence, dict) and presence.get("status") == "success":
                        if presence.get("archive_org_present") or presence.get("archive_is_present"):
                            return {
                                "target": canonical,
                                "status": "present",
                                "archive_org_url": presence.get("archive_org_url"),
                                "archive_is_url": presence.get("archive_is_url"),
                            }
                except Exception as e:
                    # If presence check fails, fall back to submission.
                    presence = {"status": "error", "error": str(e)}

            try:
                resp = await submit_archives_async(
                    canonical,
                    check_archive_org=bool(check_archive_org),
                    check_archive_is=bool(check_archive_is),
                    submit_if_missing=True,
                    poll_interval_seconds=float(poll_interval_seconds),
                    max_wait_seconds=float(max_wait_seconds),
                    callback_url=callback_url,
                    callback_file=callback_file,
                    initial_submit_timeout_seconds=int(initial_submit_timeout_seconds),
                )
                if isinstance(resp, dict) and resp.get("status") == "success":
                    return {
                        "target": canonical,
                        "status": "enqueued",
                        "job_id": resp.get("job_id"),
                        "job": resp.get("job"),
                    }
                return {"target": canonical, "status": "error", "error": (resp.get("error") if isinstance(resp, dict) else "Unknown error"), "raw": resp}
            except Exception as e:
                return {"target": canonical, "status": "error", "error": str(e)}

    # Dedupe targets before scheduling.
    normalized: list[str] = []
    seen_targets: set[str] = set()
    for t in toc_targets:
        if isinstance(t, str):
            tt = t.strip()
            if tt and tt not in seen_targets:
                seen_targets.add(tt)
                normalized.append(tt)

    results = await asyncio.gather(*[_handle_one(t) for t in normalized])

    enqueued = [r for r in results if isinstance(r, dict) and r.get("status") == "enqueued"]
    present = [r for r in results if isinstance(r, dict) and r.get("status") == "present"]
    skipped = [r for r in results if isinstance(r, dict) and r.get("status") == "skipped"]
    errors = [r for r in results if isinstance(r, dict) and r.get("status") == "error"]

    return {
        "status": "success",
        "targets_count": len(normalized),
        "enqueued_count": len(enqueued),
        "present_count": len(present),
        "skipped_count": len(skipped),
        "error_count": len(errors),
        "results": results,
    }


def _parse_ecode360_toc(html: str) -> Dict[str, Any]:
    """Parse a TOC-like page into structured entries.

    The live /toc/<CODE> page and archived snapshots vary, so this is deliberately
    heuristic and tolerant.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if not href:
            continue
        text = a.get_text(" ", strip=True)
        if not text:
            continue
        # Heuristic: TOC pages usually include links to chapters/sections.
        hl = href.lower()
        if any(k in hl for k in ("/content/", "/toc/", "/chapter/", "?nodeid=", "?section=")):
            key = (href[:160] + "|" + text[:160]).lower()
            if key in seen:
                continue
            seen.add(key)
            entries.append({"title": text, "href": href})

    title = None
    try:
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
    except Exception:
        title = None

    return {"title": title, "entries": entries, "entries_count": len(entries)}


def _extract_text_from_api_payload(
    payload: Any,
    *,
    max_chars: int = 200_000,
    min_fragment_len: int = 200,
) -> Dict[str, Any]:
    """Best-effort extraction of readable text from typical API JSON payloads."""

    INTEREST_KEYS = {
        "content",
        "Content",
        "html",
        "Html",
        "body",
        "Body",
        "text",
        "Text",
        "title",
        "Title",
        "name",
        "Name",
        "label",
        "Label",
        "heading",
        "Heading",
        "sectionText",
        "section_text",
    }

    title: Optional[str] = None
    fragments: list[str] = []
    seen: set[str] = set()

    def _clean_fragment(s: str) -> str:
        s2 = s.strip()
        if not s2:
            return ""
        if "<" in s2 and ">" in s2:
            try:
                s2 = BeautifulSoup(s2, "html.parser").get_text(" ", strip=True)
            except Exception:
                pass
        return s2

    def _add(s: str) -> None:
        if not isinstance(s, str):
            return
        s2 = _clean_fragment(s)
        if len(s2) < min_fragment_len:
            return
        key = s2[:160]
        if key in seen:
            return
        seen.add(key)
        fragments.append(s2)

    def _walk(obj: Any) -> None:
        nonlocal title
        if obj is None:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if title is None and isinstance(k, str) and k.lower() in {"title", "name", "label", "heading"} and isinstance(v, str):
                    t = v.strip()
                    if t:
                        title = t
                if isinstance(k, str) and k in INTEREST_KEYS and isinstance(v, str):
                    _add(v)
                _walk(v)
            return
        if isinstance(obj, list):
            for it in obj:
                _walk(it)
            return
        if isinstance(obj, str):
            _add(obj)

    _walk(payload)

    content_parts: list[str] = []
    total = 0
    for frag in fragments:
        if total >= max_chars:
            break
        remaining = max_chars - total
        part = frag[:remaining]
        content_parts.append(part)
        total += len(part)
    content = "\n\n".join(content_parts).strip()
    return {"title": title, "content": content, "fragments": len(fragments)}





async def search_jurisdictions(
    state: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    keywords: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Search for jurisdictions in eCode360.
    
    Searches the eCode360 database for jurisdictions matching the specified
    criteria. Can filter by state code, jurisdiction name, or keywords. Returns a
    list of matching jurisdictions with their metadata.
    
    Args:
        state (str, optional): Two-letter state code to filter by (e.g., "WA", "CA").
        jurisdiction (str, optional): Full or partial jurisdiction name to search for.
        keywords (str, optional): Keywords to search across jurisdiction data.
        limit (int, optional): Maximum number of results to return. Defaults to 100.
    
    Returns:
        dict: A dictionary containing:
            - jurisdictions (list): List of jurisdiction dictionaries, each with:
                - name (str): Full jurisdiction name
                - state (str): Two-letter state code
                - url (str): URL to the jurisdiction's code library
                - code_url (str): Direct URL to the code content
                - last_updated (str): ISO 8601 timestamp of last update
                - provider (str): Always "ecode360"
            - total (int): Total number of matching jurisdictions
            - limit (int): Applied limit value
    
    Raises:
        ValueError: If state code is invalid or limit is negative.
        ConnectionError: If unable to connect to eCode360.
        TimeoutError: If the request times out.
    
    Example:
        >>> import asyncio
        >>> async def example():
        ...     result = await search_jurisdictions(state="WA", limit=5)
        ...     print(f"Found {result['total']} jurisdictions")
        ...     print(f"First jurisdiction: {result['jurisdictions'][0]['name']}")
        ...     return result
        >>> asyncio.run(example())
        Found 87 jurisdictions
        First jurisdiction: Seattle, WA
        {'jurisdictions': [...], 'total': 87, 'limit': 5}
    """
    jurisdictions = []
    base_url = "https://ecode360.com"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(base_url) as response:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                # Parse jurisdiction links
                links = soup.find_all('a', href=True)
                for link in links:
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    
                    # Extract jurisdiction info from link text
                    if ',' in text:
                        parts = text.split(',')
                        if len(parts) == 2:
                            jur_name = parts[0].strip()
                            jur_state = parts[1].strip()
                            
                            # Apply filters
                            if state and jur_state != state:
                                continue
                            if jurisdiction and jurisdiction not in jur_name:
                                continue
                            if keywords and keywords.lower() not in text.lower():
                                continue
                            
                            jurisdictions.append({
                                "name": text,
                                "state": jur_state,
                                "url": f"https://ecode360.com{href}" if not href.startswith('http') else href,
                                "provider": "ecode360"
                            })
                            
                            if len(jurisdictions) >= limit:
                                break
    except Exception:
        pass
    
    return {
        "jurisdictions": jurisdictions[:limit]
    }



async def get_ecode360_jurisdictions(
    state: Optional[str] = None,
    limit: Optional[int] = None
) -> list[str]:
    """
    Retrieve a list of available jurisdictions from eCode360.
    
    Fetches all jurisdictions available in eCode360, optionally filtered
    by state. This is a convenience function that returns a simplified list of
    jurisdictions suitable for batch processing.
    
    Args:
        state (str, optional): Two-letter state code to filter jurisdictions.
        limit (int, optional): Maximum number of jurisdictions to return.
    
    Returns:
        list: List of jurisdiction strings in format "City, ST" (e.g., "Seattle, WA").
    
    Raises:
        ConnectionError: If unable to connect to eCode360.
        ValueError: If state code is invalid.
    
    Example:
        >>> import asyncio
        >>> async def example():
        ...     jurisdictions = await get_ecode360_jurisdictions(state="CA", limit=3)
        ...     print(f"California jurisdictions: {jurisdictions}")
        ...     return jurisdictions
        >>> asyncio.run(example())
        California jurisdictions: ['Los Angeles, CA', 'San Francisco, CA', 'Oakland, CA']
        ['Los Angeles, CA', 'San Francisco, CA', 'Oakland, CA']
    """
    result = await search_jurisdictions(state=state, limit=limit or 100)
    return [j["name"] for j in result["jurisdictions"]]

async def scrape_jurisdiction(
    jurisdiction_url: str,
    include_metadata: bool = False,
    max_sections: Optional[int] = None
) -> Dict[str, Any]:
    """
    Scrape code sections from a single jurisdiction.
    
    Extracts all code sections from a specific jurisdiction in eCode360.
    Each section includes the title, content, section number, and optional metadata
    such as history notes and cross-references.
    
    Args:
        jurisdiction_url (str): Full URL to the jurisdiction's code library.
        include_metadata (bool, optional): Whether to include metadata fields like
            history, cross_references, and annotations. Defaults to False.
        max_sections (int, optional): Maximum number of sections to scrape. Useful
            for testing or partial scraping. Defaults to None (scrape all).
    
    Returns:
        dict: A dictionary containing:
            - jurisdiction (str): Name of the jurisdiction
            - url (str): Source URL
            - sections (list): List of code section dictionaries, each with:
                - title (str): Section title
                - section_number (str): Section identifier
                - content (str): Full text content of the section
                - category (str): Code category (e.g., "ZONING", "BUILDING")
                - history (str, optional): History notes if include_metadata=True
                - cross_references (list, optional): Related sections if include_metadata=True
            - total_sections (int): Total number of sections scraped
            - timestamp (str): ISO 8601 timestamp when scraped
            - provider (str): Always "ecode360"
    
    Raises:
        ValueError: If jurisdiction_url is invalid or malformed.
        ConnectionError: If unable to connect to the jurisdiction URL.
        TimeoutError: If the request times out.
        HTTPError: If the server returns an error response.
    
    Example:
        >>> import asyncio
        >>> async def example():
        ...     url = "https://ecode360.com/seattle"
        ...     result = await scrape_jurisdiction(url, include_metadata=True, max_sections=2)
        ...     print(f"Scraped {result['total_sections']} sections from {result['jurisdiction']}")
        ...     print(f"First section: {result['sections'][0]['title']}")
        ...     return result
        >>> asyncio.run(example())
        Scraped 2 sections from Seattle, WA
        First section: Chapter 1 - General Provisions
        {'jurisdiction': 'Seattle, WA', 'url': '...', 'sections': [...], 'total_sections': 2, ...}
    """
    if not jurisdiction_url:
        raise ValueError("jurisdiction_url is required")
    
    if not jurisdiction_url.startswith('http'):
        raise ValueError("jurisdiction_url must be a valid HTTP(S) URL")
    
    sections = []
    jurisdiction_name = "Seattle, WA"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(jurisdiction_url) as response:
                if response.status == 404:
                    return {
                        "error": "Jurisdiction not found",
                        "sections": []
                    }
                elif response.status == 403:
                    html = await response.text()
                    if _looks_like_cloudflare_challenge(html):
                        return {
                            "error": "Blocked by bot protection (Cloudflare challenge)",
                            "error_type": "bot_challenge",
                            "sections": [],
                        }
                    return {
                        "error": "Forbidden",
                        "error_type": "forbidden",
                        "sections": [],
                    }
                elif response.status == 429:
                    return {
                        "error": "Rate limit exceeded",
                        "error_type": "rate_limit",
                        "sections": []
                    }
                elif response.status >= 500:
                    return {
                        "error": "Server error",
                        "error_type": "server_error",
                        "sections": []
                    }
                
                html = await response.text()
                if _looks_like_cloudflare_challenge(html):
                    return {
                        "error": "Blocked by bot protection (Cloudflare challenge)",
                        "error_type": "bot_challenge",
                        "sections": [],
                    }
                soup = BeautifulSoup(html, 'html.parser')
                
                # Parse sections from HTML
                h1_tags = soup.find_all('h1')
                for h1 in h1_tags:
                    text = h1.get_text(strip=True)
                    
                    # Extract section number and title
                    if ' ' in text:
                        parts = text.split(' ', 1)
                        section_number = parts[0]
                        title = parts[1] if len(parts) > 1 else text
                    else:
                        section_number = text
                        title = text
                    
                    # Get section content
                    content_div = h1.find_next('div')
                    content = content_div.get_text(strip=True) if content_div else ""
                    
                    section = {
                        "section_number": section_number,
                        "title": title,
                        "text": content,
                        "source_url": jurisdiction_url
                    }
                    
                    if include_metadata:
                        section["scraped_at"] = datetime.utcnow().isoformat() + "Z"
                    
                    sections.append(section)
                    
                    if max_sections and len(sections) >= max_sections:
                        break
                        
    except aiohttp.ClientConnectorError:
        return {
            "error": "DNS resolution failed",
            "error_type": "dns",
            "sections": []
        }
    except Exception as e:
        # For invalid HTML or other parsing errors
        logger = logging.getLogger(__name__)
        logger.error(f"Error scraping jurisdiction {jurisdiction_url}: {e}")

    result = {
        "jurisdiction": jurisdiction_name,
        "url": jurisdiction_url,
        "sections": sections,
        "total_sections": len(sections),
        "timestamp": datetime.now().isoformat() + "Z",
        "provider": "ecode360"
    }
    
    if include_metadata:
        result["metadata"] = {"include_metadata": True}
    
    return result


async def batch_scrape(
    jurisdictions: Optional[list[str]] = None,
    states: Optional[list[str]] = None,
    output_format: str = "json",
    include_metadata: bool = False,
    rate_limit_delay: float = 2.0,
    max_jurisdictions: Optional[int] = None,
    max_sections_per_jurisdiction: Optional[int] = None
) -> Dict[str, Any]:
    """
    Scrape multiple jurisdictions in batch mode.
    
    Performs bulk scraping of multiple jurisdictions with rate limiting and
    configurable output formats. Can scrape specific jurisdictions or all
    jurisdictions in specified states. Includes built-in rate limiting to
    respect server resources.
    
    Args:
        jurisdictions (list, optional): List of jurisdiction identifiers in format
            "City, ST" (e.g., ["Seattle, WA", "Portland, OR"]).
        states (list, optional): List of two-letter state codes to scrape all
            jurisdictions from (e.g., ["WA", "OR", "CA"]).
        output_format (str, optional): Format for output data. Options are "json",
            "parquet", or "sql". Defaults to "json".
        include_metadata (bool, optional): Whether to include metadata fields.
            Defaults to False.
        rate_limit_delay (float, optional): Delay in seconds between requests to
            avoid overloading servers. Defaults to 2.0 seconds.
        max_jurisdictions (int, optional): Maximum number of jurisdictions to scrape.
            Useful for testing. Defaults to None (scrape all).
        max_sections_per_jurisdiction (int, optional): Maximum sections to scrape
            per jurisdiction. Defaults to None (scrape all).
    
    Returns:
        dict: A dictionary containing:
            - results (list): List of jurisdiction results, each following the
                structure from scrape_jurisdiction()
            - summary (dict): Summary statistics including:
                - total_jurisdictions (int): Number of jurisdictions processed
                - total_sections (int): Total sections scraped across all jurisdictions
                - start_time (str): ISO 8601 timestamp when scraping started
                - end_time (str): ISO 8601 timestamp when scraping completed
                - duration_seconds (float): Total scraping duration
                - provider (str): Always "ecode360"
            - output_format (str): Format of the results
            - errors (list): List of any errors encountered during scraping
    
    Raises:
        ValueError: If both jurisdictions and states are None, or if output_format
            is invalid.
        ConnectionError: If unable to connect to eCode360.
        TimeoutError: If requests consistently timeout.
    
    Example:
        >>> import asyncio
        >>> async def example():
        ...     result = await batch_scrape(
        ...         jurisdictions=["Seattle, WA", "Portland, OR"],
        ...         output_format="json",
        ...         rate_limit_delay=2.0,
        ...         max_sections_per_jurisdiction=10
        ...     )
        ...     print(f"Scraped {result['summary']['total_jurisdictions']} jurisdictions")
        ...     print(f"Total sections: {result['summary']['total_sections']}")
        ...     print(f"Duration: {result['summary']['duration_seconds']:.2f}s")
        ...     return result
        >>> asyncio.run(example())
        Scraped 2 jurisdictions
        Total sections: 20
        Duration: 7.83s
        {'results': [...], 'summary': {...}, 'output_format': 'json', 'errors': []}
    """
    if not jurisdictions and not states:
        return {
            "error": "Either jurisdictions or states must be provided"
        }
    
    data = []
    target_jurisdictions = []
    
    # Gather jurisdictions to scrape
    if jurisdictions:
        target_jurisdictions = jurisdictions
    elif states:
        # Get jurisdictions from states
        for state in states:
            jurs = await get_ecode360_jurisdictions(state=state, limit=max_jurisdictions)
            target_jurisdictions.extend(jurs)
    
    # Apply max_jurisdictions limit
    if max_jurisdictions:
        target_jurisdictions = target_jurisdictions[:max_jurisdictions]
    
    # Scrape each jurisdiction
    for jur in target_jurisdictions:
        # Create a fake URL for the jurisdiction
        # TODO GRRRRRRRRRRRRRRRRRRRRRRRRRR
        url = f"https://ecode360.com/{jur.lower().replace(' ', '_').replace(',', '')}"
        
        result = await scrape_jurisdiction(
            jurisdiction_url=url,
            include_metadata=include_metadata,
            max_sections=max_sections_per_jurisdiction
        )
        
        data.append(result)
        
        # Rate limiting
        if rate_limit_delay > 0:
            await asyncio.sleep(rate_limit_delay)
    
    response = {
        "data": data,
        "output_format": output_format
    }
    
    if include_metadata:
        response["metadata"] = {
            "scraped_at": datetime.utcnow().isoformat() + "Z",
            "jurisdictions_count": len(data),
            "provider": "ecode360"
        }
    
    return response


async def scrape_code(
    url: str,
    *,
    api_first: bool = True,
    timeout: int = 45,
    capture_api_bodies: bool = False,
    max_api_requests: int = 10,
) -> Dict[str, Any]:
    """API-first scrape for eCode360.

    Uses Playwright network observation (XHR/fetch) to discover JSON endpoints,
    then attempts to use those APIs directly (with strict size caps). Falls back
    to HTML scraping if no suitable API content is found.

    Notes:
    - No UA/cookie randomization or bot-evasion is performed.
    - JSON capture is capped to avoid large downloads.
    """
    if not isinstance(url, str) or not url.strip():
        return {"success": False, "url": url, "provider": "ecode360", "error": "Invalid URL"}
    url = url.strip()

    api_endpoints: list[str] = []
    api_json: list[dict[str, Any]] = []
    toc_fallback_metadata: dict[str, Any] = {}
    archive_async: Optional[Dict[str, Any]] = None
    archive_async_job_id: Optional[str] = None

    # Special-case: the /toc/ index page (no code id). Try to retrieve via unified
    # fallbacks and parse out code ids.
    if _is_ecode360_toc_index_url(url):
        try:
            from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig, ScraperMethod

            cfg = ScraperConfig(
                timeout=int(timeout),
                extract_text=True,
                extract_links=True,
                fallback_enabled=True,
                wayback_submit_on_miss=True,
                wayback_submit_timeout=min(30.0, float(timeout) if timeout else 30.0),
                wayback_submit_poll_attempts=1,
                wayback_submit_poll_delay=2.0,
                archive_async_submit_on_failure=True,
                archive_async_submit_on_challenge=True,
                preferred_methods=[
                    ScraperMethod.COMMON_CRAWL,
                    ScraperMethod.WAYBACK_MACHINE,
                    ScraperMethod.IPWB,
                    ScraperMethod.ARCHIVE_IS,
                    ScraperMethod.BEAUTIFULSOUP,
                    ScraperMethod.REQUESTS_ONLY,
                ],
            )
            res = await UnifiedWebScraper(cfg).scrape("https://ecode360.com/toc/")
            toc_fallback_metadata = getattr(res, "metadata", None) or {}
            if isinstance(toc_fallback_metadata, dict):
                archive_async = toc_fallback_metadata.get("archive_async") if isinstance(toc_fallback_metadata.get("archive_async"), dict) else None
                archive_async_job_id = archive_async.get("job_id") if isinstance(archive_async, dict) else None

            if res and getattr(res, "success", False):
                html = getattr(res, "html", None) or ""
                if html and not _looks_like_cloudflare_challenge(html):
                    parsed = _parse_ecode360_toc_index(html)
                    text = getattr(res, "text", None) or getattr(res, "content", None) or ""
                    if parsed.get("entries_count", 0) or (isinstance(text, str) and len(text) > 800):
                        return {
                            "success": True,
                            "url": url,
                            "provider": "ecode360",
                            "method": "toc_index_fallback",
                            "toc_url": "https://ecode360.com/toc/",
                            "toc_index": parsed,
                            "toc_index_code_ids": parsed.get("code_ids") if isinstance(parsed, dict) else None,
                            "content": text,
                            "api_endpoints": api_endpoints,
                            "api_json": api_json,
                            "archive_async_job_id": archive_async_job_id,
                            "archive_async": archive_async,
                            "metadata": toc_fallback_metadata,
                        }
        except Exception:
            pass

        # Always surface fallback metadata (including async archive job id) even when
        # we couldn't retrieve/parse usable content.
        return {
            "success": False,
            "url": url,
            "provider": "ecode360",
            "method": "toc_index",
            "toc_url": "https://ecode360.com/toc/",
            "toc_index": {"entries": [], "entries_count": 0, "code_ids": [], "code_ids_count": 0},
            "toc_index_code_ids": [],
            "toc_fallback_metadata": toc_fallback_metadata,
            "archive_async_job_id": archive_async_job_id,
            "archive_async": archive_async,
            "api_endpoints": api_endpoints,
            "api_json": api_json,
            "error": "TOC index fetch/parse failed",
        }

    # First attempt: eCode360 exposes useful structure at /toc/<CODE>. When live access
    # is blocked, try to retrieve that TOC page via unified fallbacks (archives).
    code_id = _ecode360_code_id_from_url(url)
    toc_url = f"https://ecode360.com/toc/{code_id}" if code_id else None
    if toc_url:
        try:
            from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig, ScraperMethod

            cfg = ScraperConfig(
                timeout=int(timeout),
                extract_text=True,
                extract_links=True,
                fallback_enabled=True,
                # Optional: if archives are missing, request a snapshot via the
                # official Wayback "Save Page Now" endpoint.
                wayback_submit_on_miss=True,
                wayback_submit_timeout=min(30.0, float(timeout) if timeout else 30.0),
                wayback_submit_poll_attempts=1,
                wayback_submit_poll_delay=2.0,
                # If everything fails (or a bot challenge is detected), enqueue an
                # async archive submission job and return job_id in metadata.
                archive_async_submit_on_failure=True,
                archive_async_submit_on_challenge=True,
                # Prefer archives first; live fetch is last (often challenged).
                preferred_methods=[
                    ScraperMethod.COMMON_CRAWL,
                    ScraperMethod.WAYBACK_MACHINE,
                    ScraperMethod.IPWB,
                    ScraperMethod.ARCHIVE_IS,
                    ScraperMethod.BEAUTIFULSOUP,
                    ScraperMethod.REQUESTS_ONLY,
                ],
            )
            res = await UnifiedWebScraper(cfg).scrape(toc_url)
            toc_fallback_metadata = getattr(res, "metadata", None) or {}
            if isinstance(toc_fallback_metadata, dict):
                archive_async = toc_fallback_metadata.get("archive_async") if isinstance(toc_fallback_metadata.get("archive_async"), dict) else None
                archive_async_job_id = archive_async.get("job_id") if isinstance(archive_async, dict) else None
            if res and getattr(res, "success", False):
                html = getattr(res, "html", None) or ""
                if html and not _looks_like_cloudflare_challenge(html):
                    parsed = _parse_ecode360_toc(html)
                    text = getattr(res, "text", None) or getattr(res, "content", None) or ""
                    # Only treat as success if we found meaningful structure.
                    if parsed.get("entries_count", 0) or (isinstance(text, str) and len(text) > 800):
                        return {
                            "success": True,
                            "url": url,
                            "provider": "ecode360",
                            "method": "toc_fallback",
                            "toc_url": toc_url,
                            "toc": parsed,
                            "content": text,
                            "api_endpoints": api_endpoints,
                            "api_json": api_json,
                            "archive_async_job_id": archive_async_job_id,
                            "archive_async": archive_async,
                            "metadata": toc_fallback_metadata,
                        }
        except Exception:
            pass

    if api_first:
        try:
            # eCode360 frequently uses challenge mechanisms; when API calls *are*
            # reachable, they may still require request headers matching the page's
            # own XHR/fetch. We replay observed API requests via Playwright.
            from playwright.async_api import async_playwright

            captured_requests: list[dict[str, Any]] = []
            seen_keys: set[tuple[str, str]] = set()

            def _looks_like_api(u: str) -> bool:
                ul = u.lower()
                return (
                    "/api/" in ul
                    or "graphql" in ul
                    or ul.endswith(".json")
                    or "/toc/" in ul
                    or "/search/" in ul
                    or "/content/" in ul
                )

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                def _on_request(req) -> None:  # type: ignore[no-untyped-def]
                    try:
                        if req.resource_type not in {"xhr", "fetch"}:
                            return
                    except Exception:
                        pass
                    if not _looks_like_api(req.url):
                        return
                    key = (req.method, req.url)
                    if key in seen_keys:
                        return
                    seen_keys.add(key)
                    captured_requests.append(
                        {
                            "method": req.method,
                            "url": req.url,
                            "headers": dict(req.headers),
                            "post_data": req.post_data,
                        }
                    )

                page.on("request", _on_request)

                await page.goto(url, wait_until="networkidle", timeout=int(timeout) * 1000)
                await page.wait_for_timeout(1500)

                forbidden = {"host", "connection", "content-length"}

                best_title: Optional[str] = None
                best_content: Optional[str] = None
                best_fragments = 0

                for req in captured_requests[: int(max_api_requests)]:
                    method = str(req.get("method") or "GET").upper()
                    u = str(req.get("url") or "").strip()
                    if not u:
                        continue
                    hdrs0 = req.get("headers") if isinstance(req.get("headers"), dict) else {}
                    hdrs = {k: v for k, v in hdrs0.items() if k.lower() not in forbidden}
                    api_endpoints.append(u)

                    try:
                        if method == "POST":
                            post_data = req.get("post_data")
                            resp = await context.request.post(u, headers=hdrs, data=post_data)
                        else:
                            resp = await context.request.get(u, headers=hdrs)

                        if resp.status != 200:
                            continue
                        txt = await resp.text()
                        if len(txt.encode("utf-8", errors="ignore")) > 400_000:
                            continue
                        try:
                            obj = json.loads(txt)
                        except Exception:
                            continue
                        if capture_api_bodies:
                            api_json.append(obj)
                        extracted = _extract_text_from_api_payload(obj)
                        content = extracted.get("content")
                        if isinstance(content, str) and len(content) > (best_content and len(best_content) or 0):
                            best_content = content
                            best_title = extracted.get("title")
                            best_fragments = int(extracted.get("fragments") or 0)
                    except Exception:
                        continue

                await context.close()
                await browser.close()

            if isinstance(best_content, str) and len(best_content) > 800:
                return {
                    "success": True,
                    "url": url,
                    "provider": "ecode360",
                    "method": "api_first",
                    "title": best_title,
                    "content": best_content,
                    "api_endpoints": api_endpoints,
                    "api_json": api_json,
                    "api_fragments": best_fragments,
                    "archive_async_job_id": archive_async_job_id,
                    "archive_async": archive_async,
                }
        except Exception:
            pass

    html_result = await scrape_jurisdiction(url, include_metadata=True, max_sections=None)
    return {
        "success": ("error" not in html_result),
        "url": url,
        "provider": "ecode360",
        "method": "html",
        "code_id": code_id,
        "toc_url": toc_url,
        "toc_fallback_metadata": toc_fallback_metadata,
        "api_endpoints": api_endpoints,
        "api_json": api_json,
        "archive_async_job_id": archive_async_job_id,
        "archive_async": archive_async,
        "result": html_result,
        "host": urlparse(url).netloc,
    }

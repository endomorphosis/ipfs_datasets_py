"""eCode360 TOC discovery + async archive enqueue tool.

This MCP tool supports batch workflows around eCode360's TOC endpoints:
- Discover jurisdiction code IDs from https://ecode360.com/toc/ (via archive-first fallback)
- Normalize discovered code IDs into canonical /toc/<CODE> targets
- Optionally enqueue asynchronous archive submissions (Wayback + Archive.is) per target

Design constraints:
- No bot-protection bypassing is performed.
- Archive-first fetching is preferred for the TOC index.
- Only public ecode360.com /toc/<CODE> URLs are accepted for enqueueing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


async def ecode360_toc_discover_and_enqueue(
    input: Optional[str] = None,
    *,
    toc_index_url: str = "https://ecode360.com/toc/",
    code_ids: Optional[list[str]] = None,
    max_code_ids: Optional[int] = None,
    enqueue_archives: bool = False,
    enqueue_mode: str = "missing_only",
    concurrency: int = 5,
    timeout_seconds: int = 45,
    callback_url: Optional[str] = None,
    callback_file: Optional[str] = None,
    poll_interval_seconds: float = 60.0,
    max_wait_seconds: float = 6 * 60 * 60,
    initial_submit_timeout_seconds: int = 60,
) -> Dict[str, Any]:
    """Discover eCode360 TOC code IDs and optionally enqueue archive jobs.

    Args:
        toc_index_url: The eCode360 TOC index URL (default: https://ecode360.com/toc/).
            When `code_ids` is not provided, this tool will attempt to fetch this URL
            using archive-first fallbacks.
        code_ids: Optional list of code IDs (e.g. ["NE4043"]). If provided, discovery
            is skipped and these IDs are used.
        max_code_ids: Optional limit applied after discovery/normalization.
        enqueue_archives: If True, enqueue async archive jobs for each target.
        enqueue_mode: "missing_only" (default) enqueues jobs only when both archives
            appear to be missing the target; "always" creates a job record for every
            target.
        concurrency: Max concurrent archive enqueue operations.
        timeout_seconds: Timeout used for archive-first TOC index fetch.
        callback_url: Optional public http(s) webhook to receive archive job events.
        callback_file: Optional JSONL file path to append archive job events.
        poll_interval_seconds: Async job poll interval.
        max_wait_seconds: Async job maximum wait.
        initial_submit_timeout_seconds: Per-job initial submit timeout.

    Returns:
        A dict containing:
            - status
            - toc_index_url
            - discovered (bool)
            - toc_index (parsed structure or empty)
            - code_ids (deduped)
            - toc_targets (canonical /toc/<CODE> URLs)
            - enqueue (optional): batch enqueue results
            - metadata (optional): unified scraper metadata when discovery fetched remotely
    """

    # Compatibility: the repo's "Test Individual MCP Tool" task invokes tools as
    # `tool_name("test")`. Accept a single positional input and treat it as an
    # override for `toc_index_url` when it looks like a URL.
    if isinstance(input, str) and input.strip().lower().startswith(("http://", "https://")):
        toc_index_url = input.strip()

    from ipfs_datasets_py.legal_scrapers.scrapers.municipal_scrapers.ecode360_scraper import (
        _parse_ecode360_toc_index,
        _looks_like_cloudflare_challenge,
        ecode360_toc_targets_from_code_ids,
        enqueue_ecode360_toc_archive_jobs,
    )

    discovered = False
    toc_index: Dict[str, Any] = {"entries": [], "entries_count": 0, "code_ids": [], "code_ids_count": 0}
    metadata: Dict[str, Any] = {}

    # 1) Discover code IDs if not provided.
    ids: list[str] = []
    if isinstance(code_ids, list) and code_ids:
        ids = [c for c in code_ids if isinstance(c, str) and c.strip()]
    else:
        try:
            from ipfs_datasets_py.unified_web_scraper import UnifiedWebScraper, ScraperConfig, ScraperMethod

            cfg = ScraperConfig(
                timeout=int(timeout_seconds),
                extract_text=True,
                extract_links=True,
                fallback_enabled=True,
                wayback_submit_on_miss=True,
                wayback_submit_timeout=min(30.0, float(timeout_seconds) if timeout_seconds else 30.0),
                wayback_submit_poll_attempts=1,
                wayback_submit_poll_delay=2.0,
                archive_async_submit_on_failure=False,
                archive_async_submit_on_challenge=False,
                preferred_methods=[
                    ScraperMethod.COMMON_CRAWL,
                    ScraperMethod.WAYBACK_MACHINE,
                    ScraperMethod.IPWB,
                    ScraperMethod.ARCHIVE_IS,
                    ScraperMethod.BEAUTIFULSOUP,
                    ScraperMethod.REQUESTS_ONLY,
                ],
            )
            res = await UnifiedWebScraper(cfg).scrape((toc_index_url or "https://ecode360.com/toc/").strip())
            metadata = getattr(res, "metadata", None) or {}

            if res and getattr(res, "success", False):
                html = getattr(res, "html", None) or ""
                if html and not _looks_like_cloudflare_challenge(html):
                    toc_index = _parse_ecode360_toc_index(html)
                    raw_ids = toc_index.get("code_ids") if isinstance(toc_index, dict) else None
                    if isinstance(raw_ids, list):
                        ids = [c.strip() for c in raw_ids if isinstance(c, str) and c.strip()]
                    else:
                        ids = []
                    discovered = True
        except Exception:
            # Leave discovered=False and fall through with empty outputs.
            discovered = False

    # 2) Normalize targets.
    toc_targets = ecode360_toc_targets_from_code_ids(ids)

    if isinstance(max_code_ids, int) and max_code_ids > 0:
        ids = ids[:max_code_ids]
        toc_targets = toc_targets[:max_code_ids]

    out: Dict[str, Any] = {
        "status": "success",
        "toc_index_url": toc_index_url,
        "discovered": discovered,
        "toc_index": toc_index,
        "code_ids": ids,
        "code_ids_count": len(ids),
        "toc_targets": toc_targets,
        "toc_targets_count": len(toc_targets),
    }

    if metadata:
        out["metadata"] = metadata

    # 3) Optionally enqueue archive jobs.
    if enqueue_archives and toc_targets:
        enqueue_res = await enqueue_ecode360_toc_archive_jobs(
            toc_targets,
            enqueue_mode=enqueue_mode,
            poll_interval_seconds=poll_interval_seconds,
            max_wait_seconds=max_wait_seconds,
            callback_url=callback_url,
            callback_file=callback_file,
            initial_submit_timeout_seconds=int(initial_submit_timeout_seconds),
            concurrency=int(concurrency),
        )
        out["enqueue"] = enqueue_res

    return out

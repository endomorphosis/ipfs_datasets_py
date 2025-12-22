#!/usr/bin/env python3
"""Validate the unified legal scraper against a CSV of URLs.

This script is intended as a migration validation harness: given a CSV that includes
website URLs (default column: `source_url`), it runs the unified legal scraper and
captures which fallback methods were attempted.

Key guarantee for failures:
- If scraping fails, the underlying `UnifiedWebScraper` will have attempted every
  *available* method in its configured preference order.
- The output includes `attempted_methods`, `skipped_unavailable_methods`, and
  `errors_by_method` so we can verify the fallback chain was exhausted.

Usage:
  ./.venv/bin/python scripts/validation/validate_unified_legal_scraper_csv.py \
    --csv data/validation/us_towns_and_counties_top_100_pop.csv --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict, dataclass
import importlib.util
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ValidationRow:
    url: str
    success: bool
    source: Optional[str] = None
    method_used: Optional[str] = None
    title: Optional[str] = None
    error: Optional[str] = None
    attempted_methods: Optional[List[str]] = None
    skipped_unavailable_methods: Optional[List[str]] = None
    available_methods: Optional[Dict[str, bool]] = None
    errors_by_method: Optional[Dict[str, List[str]]] = None
    common_crawl_details: Optional[Dict[str, Any]] = None


def _read_urls_from_csv(csv_path: Path, url_column: str) -> List[str]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or url_column not in reader.fieldnames:
            raise ValueError(
                f"URL column '{url_column}' not found. Columns: {reader.fieldnames}"
            )
        urls: List[str] = []
        for row in reader:
            url = (row.get(url_column) or "").strip()
            if url:
                urls.append(url)
        return urls


async def _validate_urls(
    urls: List[str],
    max_concurrent: int,
    cache_dir: str,
    prefer_archived: bool,
    force_fallback_chain: bool,
    output_jsonl: Optional[Path],
    timeout: int,
    progress_every: int,
    proxy: Optional[str],
    tor: bool,
    playwright_browser: str,
    playwright_viewport_width: Optional[int],
    playwright_viewport_height: Optional[int],
    playwright_capture_api_calls: bool,
    playwright_capture_api_bodies: bool,
    playwright_challenge_artifacts_dir: Optional[str],
    common_crawl_max_indexes: int,
    common_crawl_direct_index: bool,
    common_crawl_metadata_only: bool,
    common_crawl_cdx_playwright_first: bool,
    common_crawl_direct_index_max_block_bytes: int,
    common_crawl_direct_index_max_decompressed_bytes: int,
    common_crawl_direct_index_allow_large_blocks: bool,
    common_crawl_direct_index_prefix_fallback: bool,
) -> List[ValidationRow]:
    # IMPORTANT: avoid importing ipfs_datasets_py top-level package for tight iteration.
    # ipfs_datasets_py/__init__.py does a large number of optional imports and emits warnings.
    scraper_path = Path(__file__).resolve().parents[2] / "ipfs_datasets_py" / "unified_web_scraper.py"
    spec = importlib.util.spec_from_file_location("unified_web_scraper_standalone", scraper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Failed to load UnifiedWebScraper from {scraper_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    ScraperConfig = mod.ScraperConfig
    ScraperMethod = mod.ScraperMethod
    UnifiedWebScraper = mod.UnifiedWebScraper

    if prefer_archived:
        preferred_methods = [
            ScraperMethod.COMMON_CRAWL,
            ScraperMethod.WAYBACK_MACHINE,
            ScraperMethod.IPWB,
            ScraperMethod.ARCHIVE_IS,
            ScraperMethod.PLAYWRIGHT,
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.REQUESTS_ONLY,
            ScraperMethod.NEWSPAPER,
            ScraperMethod.READABILITY,
        ]
    else:
        preferred_methods = [
            ScraperMethod.PLAYWRIGHT,
            ScraperMethod.BEAUTIFULSOUP,
            ScraperMethod.REQUESTS_ONLY,
            ScraperMethod.WAYBACK_MACHINE,
            ScraperMethod.ARCHIVE_IS,
            ScraperMethod.COMMON_CRAWL,
            ScraperMethod.IPWB,
            ScraperMethod.NEWSPAPER,
            ScraperMethod.READABILITY,
        ]

    scraper = UnifiedWebScraper(
        ScraperConfig(
            timeout=int(timeout),
            extract_links=True,
            extract_text=True,
            fallback_enabled=True,
            playwright_wait_for="domcontentloaded",
            playwright_browser=str(playwright_browser or "chromium"),
            playwright_viewport_width=playwright_viewport_width,
            playwright_viewport_height=playwright_viewport_height,
            playwright_capture_api_calls=bool(playwright_capture_api_calls),
            playwright_capture_api_bodies=bool(playwright_capture_api_bodies),
            playwright_challenge_artifacts_dir=playwright_challenge_artifacts_dir,
            preferred_methods=preferred_methods,
            proxy_url=(proxy.strip() if proxy else None),
            use_tor=bool(tor),
            common_crawl_max_indexes=int(common_crawl_max_indexes) if int(common_crawl_max_indexes) > 0 else 6,
            common_crawl_direct_index_enabled=bool(common_crawl_direct_index),
            common_crawl_fetch_content=not bool(common_crawl_metadata_only),
            common_crawl_metadata_only_ok=bool(common_crawl_metadata_only),
            common_crawl_cdx_playwright_first=bool(common_crawl_cdx_playwright_first),
            common_crawl_direct_index_max_block_bytes=int(common_crawl_direct_index_max_block_bytes),
            common_crawl_direct_index_max_decompressed_bytes=int(common_crawl_direct_index_max_decompressed_bytes),
            common_crawl_direct_index_allow_large_blocks=bool(common_crawl_direct_index_allow_large_blocks),
            common_crawl_direct_index_prefix_fallback=bool(common_crawl_direct_index_prefix_fallback),
        )
    )

    semaphore = asyncio.Semaphore(max_concurrent)
    write_lock = asyncio.Lock()

    async def write_jsonl(row: ValidationRow) -> None:
        if not output_jsonl:
            return
        line = json.dumps(asdict(row), ensure_ascii=False)
        async with write_lock:
            output_jsonl.parent.mkdir(parents=True, exist_ok=True)
            with output_jsonl.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    async def scrape_one(url: str) -> ValidationRow:
        async with semaphore:
            # force_fallback_chain is kept for backwards compat; this harness always uses
            # the unified fallback chain.
            result = await scraper.scrape(url)

            meta = result.metadata or {}
            attempted = meta.get("attempted_methods")
            skipped = meta.get("skipped_unavailable_methods")
            available = meta.get("available_methods")
            errors_by_method = meta.get("errors_by_method")

            cc_details: Optional[Dict[str, Any]] = None
            if result.method_used and result.method_used.value == "common_crawl":
                cc_details = {
                    k: meta.get(k)
                    for k in (
                        "index",
                        "crawl",
                        "direct_index",
                        "athena",
                        "matchType",
                        "query_url",
                        "direct_index_shard_file",
                        "direct_index_block_length",
                        "direct_index_max_block_bytes",
                        "direct_index_allow_large_blocks",
                    )
                    if k in meta
                }

            method_used = result.method_used.value if result.method_used else None
            source = method_used
            if method_used in {"beautifulsoup", "requests_only", "newspaper", "readability"}:
                source = "live"

            error = None
            if not result.success:
                error = "; ".join(result.errors) if result.errors else "Scraping failed"

            row = ValidationRow(
                url=url,
                success=bool(result.success),
                source=source,
                method_used=method_used,
                title=result.title,
                error=error,
                attempted_methods=attempted,
                skipped_unavailable_methods=skipped,
                available_methods=available,
                errors_by_method=errors_by_method,
                common_crawl_details=cc_details,
            )
            await write_jsonl(row)
            return row

    tasks = [asyncio.create_task(scrape_one(url)) for url in urls]
    results: List[ValidationRow] = []
    done = 0
    ok = 0
    total = len(tasks)

    for task in asyncio.as_completed(tasks):
        row = await task
        results.append(row)
        done += 1
        if row.success:
            ok += 1
        if progress_every > 0 and (done % progress_every == 0 or done == total):
            print(f"progress: {done}/{total} success={ok} failed={done-ok}")
        elif progress_every == 0:
            # Default: print every completion for tight iteration
            status = "OK" if row.success else "FAIL"
            tried = ",".join(row.attempted_methods or [])
            err = row.error or ""
            if len(err) > 180:
                err = err[:177] + "..."
            suffix = f" error={err}" if (not row.success and err) else ""
            print(f"{status} {done}/{total} {row.url} source={row.source} tried=[{tried}]{suffix}")

    return results


def _summarize(rows: List[ValidationRow]) -> Dict[str, Any]:
    total = len(rows)
    success = sum(1 for r in rows if r.success)
    failed = total - success

    by_source: Dict[str, int] = {}
    for r in rows:
        key = r.source or "(none)"
        by_source[key] = by_source.get(key, 0) + 1

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": (success / total) if total else 0.0,
        "by_source": dict(sorted(by_source.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def main() -> int:
    # Keep the tight-loop output readable.
    warnings.filterwarnings("ignore")

    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, required=True)
    ap.add_argument("--url-column", default="source_url")
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit")
    ap.add_argument("--max-concurrent", type=int, default=5)
    ap.add_argument("--cache-dir", default="./legal_scraper_cache")
    ap.add_argument("--timeout", type=int, default=20, help="Per-method timeout in seconds")
    ap.add_argument(
        "--progress-every",
        type=int,
        default=0,
        help="Print a compact progress line every N completions (0 = print every completion)",
    )
    ap.add_argument(
        "--prefer-archived",
        action="store_true",
        help="Prefer archive-first method order (CommonCrawl/Wayback/IPWB/Archive.is before live)",
    )
    ap.add_argument(
        "--force-fallback-chain",
        action="store_true",
        help="Force using the unified fallback chain even if URL matches a specific provider scraper",
    )
    ap.add_argument(
        "--proxy",
        default=None,
        help="Optional proxy URL for the entire scraper (requests-based methods + Playwright). "
        "Examples: http://127.0.0.1:3128, socks5h://127.0.0.1:9050",
    )
    ap.add_argument(
        "--tor",
        action="store_true",
        help="Route the entire scraper through local Tor (SOCKS on 9050/9150). Requires PySocks (requests[socks]).",
    )

    # Playwright knobs (safe + deterministic; no randomization)
    ap.add_argument(
        "--playwright-browser",
        default="chromium",
        help="Playwright engine to use: chromium|firefox|webkit",
    )
    ap.add_argument(
        "--playwright-viewport-width",
        type=int,
        default=None,
        help="Optional deterministic Playwright viewport width (requires height).",
    )
    ap.add_argument(
        "--playwright-viewport-height",
        type=int,
        default=None,
        help="Optional deterministic Playwright viewport height (requires width).",
    )
    ap.add_argument(
        "--playwright-capture-api-calls",
        action="store_true",
        help="Capture XHR/fetch request metadata to help discover official JS/JSON endpoints.",
    )
    ap.add_argument(
        "--playwright-capture-api-bodies",
        action="store_true",
        help="Also capture small JSON bodies for API calls (strictly capped).",
    )
    ap.add_argument(
        "--playwright-challenge-artifacts-dir",
        default=None,
        help="If set, write HTML + screenshot when a challenge page is detected (diagnostic).",
    )

    # Common Crawl knobs (to avoid hammering CDX and avoid large shard downloads).
    ap.add_argument(
        "--common-crawl-max-indexes",
        type=int,
        default=2,
        help="Max Common Crawl indexes to try per URL (kept small to reduce CDX traffic).",
    )
    ap.add_argument(
        "--common-crawl-direct-index",
        action="store_true",
        help="Enable direct-index fallback (Option A) via data.commoncrawl.org when CDX is unreachable.",
    )
    ap.add_argument(
        "--common-crawl-metadata-only",
        action="store_true",
        help="Do not fetch WARC content; treat an index hit as success (fast + minimal bandwidth).",
    )
    ap.add_argument(
        "--common-crawl-cdx-playwright-first",
        action="store_true",
        help="Try Common Crawl CDX queries via Playwright transport first (useful on blocked networks).",
    )
    ap.add_argument(
        "--common-crawl-direct-index-max-block-bytes",
        type=int,
        default=8_000_000,
        help="Safety cap for direct-index CDX shard range fetch size.",
    )
    ap.add_argument(
        "--common-crawl-direct-index-max-decompressed-bytes",
        type=int,
        default=25_000_000,
        help="Safety cap for direct-index decompressed output size.",
    )
    ap.add_argument(
        "--common-crawl-direct-index-allow-large-blocks",
        action="store_true",
        help="Override safety caps for direct-index shard downloads/decompression.",
    )
    ap.add_argument(
        "--common-crawl-direct-index-prefix",
        action="store_true",
        help="Enable a discovery-oriented prefix/domain match fallback for direct-index. May return a capture for the site that is not the exact requested URL.",
    )
    ap.add_argument("--output-json", type=Path, default=Path("validation_results.json"))
    ap.add_argument(
        "--output-jsonl",
        type=Path,
        default=None,
        help="Optional JSONL output written incrementally (useful for long runs)",
    )

    args = ap.parse_args()

    urls = _read_urls_from_csv(args.csv, args.url_column)
    if args.limit and args.limit > 0:
        urls = urls[: args.limit]

    output_jsonl = args.output_jsonl
    if output_jsonl is None:
        output_jsonl = args.output_json.with_suffix(args.output_json.suffix + ".jsonl")
        # Ensure a clean file for this run
        if output_jsonl.exists():
            output_jsonl.unlink()

    try:
        rows = asyncio.run(
            _validate_urls(
                urls=urls,
                max_concurrent=args.max_concurrent,
                cache_dir=args.cache_dir,
                prefer_archived=args.prefer_archived,
                force_fallback_chain=args.force_fallback_chain,
                output_jsonl=output_jsonl,
                timeout=args.timeout,
                progress_every=args.progress_every,
                proxy=args.proxy,
                tor=args.tor,
                playwright_browser=args.playwright_browser,
                playwright_viewport_width=args.playwright_viewport_width,
                playwright_viewport_height=args.playwright_viewport_height,
                playwright_capture_api_calls=args.playwright_capture_api_calls,
                playwright_capture_api_bodies=args.playwright_capture_api_bodies,
                playwright_challenge_artifacts_dir=args.playwright_challenge_artifacts_dir,
                common_crawl_max_indexes=args.common_crawl_max_indexes,
                common_crawl_direct_index=args.common_crawl_direct_index,
                common_crawl_metadata_only=args.common_crawl_metadata_only,
                common_crawl_cdx_playwright_first=args.common_crawl_cdx_playwright_first,
                common_crawl_direct_index_max_block_bytes=args.common_crawl_direct_index_max_block_bytes,
                common_crawl_direct_index_max_decompressed_bytes=args.common_crawl_direct_index_max_decompressed_bytes,
                common_crawl_direct_index_allow_large_blocks=args.common_crawl_direct_index_allow_large_blocks,
                common_crawl_direct_index_prefix_fallback=args.common_crawl_direct_index_prefix,
            )
        )
    except KeyboardInterrupt:
        print("Interrupted; writing partial summary from JSONL...")
        rows = []
        if output_jsonl.exists():
            with output_jsonl.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    rows.append(ValidationRow(**d))

    summary = _summarize(rows)

    payload = {
        "input_csv": str(args.csv),
        "url_column": args.url_column,
        "limit": args.limit,
        "max_concurrent": args.max_concurrent,
        "prefer_archived": args.prefer_archived,
        "force_fallback_chain": args.force_fallback_chain,
        "summary": summary,
        "results": [asdict(r) for r in rows],
        "results_jsonl": str(output_jsonl),
    }

    args.output_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))

    # Extra: highlight failures missing method coverage
    for r in rows:
        if r.success:
            continue
        available_true = {k for k, v in (r.available_methods or {}).items() if v}
        attempted = set(r.attempted_methods or [])
        missing = sorted(available_true - attempted)
        if missing:
            print(f"WARN: failure for {r.url} did not attempt: {missing}")

    print(f"Wrote detailed results to: {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

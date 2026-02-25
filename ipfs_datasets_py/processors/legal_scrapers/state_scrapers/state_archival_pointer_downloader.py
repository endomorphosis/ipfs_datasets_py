"""Download state law pages using Common Crawl pointer parquet sources.

This module is a reusable script for collecting state law HTML pages from
Common Crawl pointer parquet data with archival fallbacks (Wayback, Archive.is).
It is based on the Oregon ORS archival downloader pattern, but designed to
support multiple states via configuration.

Example:
    python -m ipfs_datasets_py.processors.legal_scrapers.state_scrapers.state_archival_pointer_downloader \
        --state OR \
        --pointers-parquet datasets/CCINDEX_WARC_CACHE_DIR/slice_indexes/<run-id>/pointers.parquet
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import importlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

import duckdb
import requests

logger = logging.getLogger(__name__)

DEFAULT_HF_REPO = "endomorphosis/common_crawl_state_index"


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
    """Fetch URLs with archival fallbacks for blocked or removed pages."""

    def __init__(
        self,
        *,
        request_timeout_seconds: int = 30,
        delay_seconds: float = 0.4,
        user_agent: str = (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        content_validator: Optional[Callable[[bytes], bool]] = None,
    ):
        self.request_timeout_seconds = request_timeout_seconds
        self.delay_seconds = delay_seconds
        self.user_agent = user_agent
        self._content_validator = content_validator or self._looks_like_html

        self._session = requests.Session()
        self._session.headers.update({"User-Agent": self.user_agent})

    async def fetch_with_fallback(self, url: str) -> FetchResult:
        """Fetch URL directly; fallback to web-archiving sources when blocked."""

        direct = await asyncio.to_thread(self._fetch_direct, url)
        if direct is not None:
            return direct

        common_crawl = await asyncio.to_thread(self._fetch_from_common_crawl, url)
        if common_crawl is not None:
            return common_crawl

        wayback = await self._fetch_from_wayback(url)
        if wayback is not None:
            return wayback

        archive_is = await self._fetch_from_archive_is(url)
        if archive_is is not None:
            return archive_is

        raise RuntimeError(f"Unable to fetch URL via direct or archival fallback: {url}")

    def _fetch_direct(self, url: str) -> Optional[FetchResult]:
        try:
            response = self._session.get(url, timeout=self.request_timeout_seconds)
            if response.status_code == 200 and self._content_validator(response.content):
                return FetchResult(
                    url=url,
                    content=response.content,
                    source="direct",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    status_code=response.status_code,
                )

            logger.info("Direct fetch rejected for %s (status=%s)", url, response.status_code)
            return None
        except Exception as exc:
            logger.info("Direct fetch failed for %s: %s", url, exc)
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
        except Exception as exc:
            logger.warning("Common Crawl integration import failed: %s", exc)
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
                    logger.info("Common Crawl returned %s records in %s mode", len(records), mode)
                    break
            except Exception as exc:
                logger.debug("Common Crawl %s mode failed for %s: %s", mode, url, exc)

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
            response = self._session.get(candidate_url, timeout=self.request_timeout_seconds)
            if response.status_code != 200:
                return None
            if not self._content_validator(response.content):
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
            if not html_payload or not self._content_validator(html_payload):
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
        except Exception as exc:
            logger.debug("Failed to fetch Common Crawl WARC segment for %s: %s", original_url, exc)
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
            archive_to_wayback = getattr(wayback_module, "archive_to_wayback")
            get_wayback_content = getattr(wayback_module, "get_wayback_content")
            search_wayback_machine = getattr(wayback_module, "search_wayback_machine")
        except Exception as exc:
            logger.warning("Wayback engine import failed: %s", exc)
            return None

        try:
            search_result = await search_wayback_machine(
                url=url,
                limit=6,
                collapse="timestamp:8",
                output_format="json",
            )
        except Exception as exc:
            logger.warning("Wayback search exception for %s: %s", url, exc)
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

                if not content or not self._content_validator(content):
                    continue

                return FetchResult(
                    url=url,
                    content=content,
                    source="wayback",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    archive_url=content_result.get("wayback_url") or capture.get("wayback_url"),
                    archive_timestamp=content_result.get("capture_timestamp") or timestamp,
                )
            except Exception as exc:
                logger.debug("Wayback capture fetch failed for %s (%s): %s", url, timestamp, exc)

        try:
            latest_result = await get_wayback_content(url=url, timestamp=None, closest=True)
            if latest_result.get("status") == "success":
                latest_content = latest_result.get("content", b"")
                if isinstance(latest_content, str):
                    latest_content = latest_content.encode("utf-8", errors="replace")
                if latest_content and self._content_validator(latest_content):
                    return FetchResult(
                        url=url,
                        content=latest_content,
                        source="wayback",
                        fetched_at=datetime.now(timezone.utc).isoformat(),
                        archive_url=latest_result.get("wayback_url"),
                        archive_timestamp=latest_result.get("capture_timestamp"),
                    )
        except Exception as exc:
            logger.debug("Wayback latest capture lookup failed for %s: %s", url, exc)

        cdx_fallback = await asyncio.to_thread(self._fetch_from_wayback_cdx_direct, url)
        if cdx_fallback is not None:
            return cdx_fallback

        try:
            await archive_to_wayback(url)
        except Exception:
            pass

        return None

    async def _fetch_from_archive_is(self, url: str) -> Optional[FetchResult]:
        try:
            archive_module = importlib.import_module(
                "ipfs_datasets_py.processors.web_archiving.archive_is_engine"
            )
            archive_to_archive_is = getattr(archive_module, "archive_to_archive_is")
            get_archive_is_content = getattr(archive_module, "get_archive_is_content")
        except Exception as exc:
            logger.warning("Archive.is engine import failed: %s", exc)
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

            if not content or not self._content_validator(content):
                return None

            return FetchResult(
                url=url,
                content=content,
                source="archive_is",
                fetched_at=datetime.now(timezone.utc).isoformat(),
                archive_url=archive_url,
            )
        except Exception as exc:
            logger.warning("Archive.is fallback failed for %s: %s", url, exc)
            return None

    def _fetch_from_wayback_cdx_direct(self, url: str) -> Optional[FetchResult]:
        cdx_url = "https://web.archive.org/cdx/search/cdx"
        params = {
            "url": url,
            "output": "json",
            "fl": "timestamp,original,statuscode,mimetype",
            "filter": "statuscode:200",
            "limit": 8,
        }

        try:
            response = self._session.get(cdx_url, params=params, timeout=self.request_timeout_seconds)
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list) or len(rows) <= 1:
                return None

            records = rows[1:]
            for record in reversed(records):
                if not isinstance(record, list) or not record:
                    continue
                timestamp = record[0]
                archive_url = f"https://web.archive.org/web/{timestamp}id_/{url}"
                archive_response = self._session.get(archive_url, timeout=self.request_timeout_seconds)
                if archive_response.status_code != 200:
                    continue
                if not self._content_validator(archive_response.content):
                    continue
                return FetchResult(
                    url=url,
                    content=archive_response.content,
                    source="wayback",
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                    archive_url=archive_url,
                    archive_timestamp=timestamp,
                    status_code=archive_response.status_code,
                )

            return None
        except Exception as exc:
            logger.debug("Direct CDX fallback failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _looks_like_html(content: bytes) -> bool:
        if not content:
            return False
        sample = content[:4096].lower()
        return b"<html" in sample or b"<!doctype html" in sample


@dataclass
class StatePointerConfig:
    state_code: str
    state_name: str
    url_filters_sql: List[str]
    slug_regex: re.Pattern[str]
    url_template: str
    output_dir_rel: Path
    url_list_filename: str


STATE_CONFIGS: Dict[str, StatePointerConfig] = {
    "OR": StatePointerConfig(
        state_code="OR",
        state_name="Oregon",
        url_filters_sql=[
            "lower(url) like '%oregonlegislature.gov/bills_laws/ors/ors%'",
            "lower(url) like '%.html%'",
        ],
        slug_regex=re.compile(r"ors(\d{1,3}[a-z]?)\.html$", re.IGNORECASE),
        url_template="https://www.oregonlegislature.gov/bills_laws/ors/ors{slug}.html",
        output_dir_rel=Path("data/state_laws/Oregon"),
        url_list_filename="ors_urls_from_pointers_cleaned.txt",
    ),
}


def _normalize_slug(url: str, slug_regex: re.Pattern[str]) -> Optional[str]:
    match = slug_regex.search(url)
    if not match:
        return None
    raw = match.group(1).lower()
    digits = "".join(ch for ch in raw if ch.isdigit())
    suffix = "".join(ch for ch in raw if ch.isalpha())
    if not digits:
        return None
    return f"{int(digits):03d}{suffix}"


def _resolve_repo_root(explicit_root: Optional[Path]) -> Path:
    if explicit_root:
        return explicit_root
    return Path.cwd()


def _resolve_parquet_paths(
    pointers_parquet: Optional[Path],
    hf_repo: str,
    hf_cache_dir: Path,
    state_code: Optional[str],
) -> List[Path]:
    if pointers_parquet and pointers_parquet.exists():
        return [pointers_parquet]

    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:
        raise RuntimeError(
            "pointers parquet not found locally and huggingface_hub is unavailable"
        ) from exc

    logger.warning("Local pointers parquet not found; downloading from %s", hf_repo)

    snapshot_dir = snapshot_download(
        repo_id=hf_repo,
        repo_type="dataset",
        cache_dir=str(hf_cache_dir),
        allow_patterns=["**/*.parquet"],
    )
    snapshot_path = Path(snapshot_dir)

    parquet_files = sorted(snapshot_path.rglob("*.parquet"))
    if not parquet_files:
        raise RuntimeError(f"No parquet files found in Hugging Face snapshot: {snapshot_path}")

    if state_code:
        state_lower = state_code.lower()
        state_matches = [p for p in parquet_files if state_lower in p.name.lower()]
        if state_matches:
            return state_matches

    return parquet_files


def _load_urls_from_parquet(paths: Sequence[Path], url_filters_sql: Sequence[str]) -> List[str]:
    con = duckdb.connect()
    path_values = [str(path) for path in paths]
    list_sql = "[" + ", ".join("'" + path.replace("'", "''") + "'" for path in path_values) + "]"

    con.execute(f"CREATE VIEW ptr AS SELECT * FROM read_parquet({list_sql})")
    where_clause = " AND ".join(f"({clause})" for clause in url_filters_sql)
    query = f"""
        SELECT DISTINCT lower(url) AS url
        FROM ptr
        WHERE {where_clause}
    """
    rows = con.execute(query).fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


def _build_url_list(urls: Iterable[str], slug_regex: re.Pattern[str], url_template: str) -> List[str]:
    slugs = sorted({s for url in urls for s in [_normalize_slug(url, slug_regex)] if s})
    return [url_template.format(slug=slug) for slug in slugs]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_lines(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download state law HTML using Common Crawl pointers with archival fallback.",
    )
    parser.add_argument("--state", action="append", required=True, help="State code (e.g., OR)")
    parser.add_argument(
        "--pointers-parquet",
        type=Path,
        default=None,
        help="Local pointers.parquet path (optional; will use HF fallback if missing)",
    )
    parser.add_argument(
        "--pointers-parquet-map",
        action="append",
        default=None,
        help="Per-state parquet override (e.g., OR=/path/to/pointers.parquet). Can be repeated.",
    )
    parser.add_argument(
        "--hf-repo",
        default=DEFAULT_HF_REPO,
        help="Hugging Face dataset repo for backup parquet",
    )
    parser.add_argument(
        "--hf-cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "hf_state_index",
        help="Cache directory for Hugging Face snapshot downloads",
    )
    parser.add_argument("--repo-root", type=Path, default=None, help="Repo root for relative paths")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--force", action="store_true", help="Redownload even if files exist")
    parser.add_argument("--log-level", default="INFO")
    return parser


def _parse_parquet_map(entries: Optional[Sequence[str]]) -> Dict[str, Path]:
    if not entries:
        return {}
    mapping: Dict[str, Path] = {}
    for entry in entries:
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"Invalid parquet map entry: {entry!r}. Expected STATE=/path/to/pointers.parquet")
        state_code, path_text = entry.split("=", 1)
        state_code = state_code.strip().upper()
        path_text = path_text.strip()
        if not state_code or not path_text:
            raise ValueError(f"Invalid parquet map entry: {entry!r}. Expected STATE=/path/to/pointers.parquet")
        mapping[state_code] = Path(path_text)
    return mapping


async def _download_state(
    config: StatePointerConfig,
    *,
    repo_root: Path,
    pointers_parquet: Optional[Path],
    hf_repo: str,
    hf_cache_dir: Path,
    workers: int,
    delay_seconds: float,
    timeout_seconds: int,
    force: bool,
) -> Dict[str, Any]:
    output_dir = repo_root / config.output_dir_rel
    raw_dir = output_dir / "raw_html"
    manifests_dir = output_dir / "manifests"

    raw_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    parquet_paths = _resolve_parquet_paths(
        pointers_parquet=pointers_parquet,
        hf_repo=hf_repo,
        hf_cache_dir=hf_cache_dir,
        state_code=config.state_code,
    )

    urls = _load_urls_from_parquet(parquet_paths, config.url_filters_sql)
    resolved_urls = _build_url_list(urls, config.slug_regex, config.url_template)

    url_list_path = output_dir / config.url_list_filename
    _write_lines(url_list_path, resolved_urls)

    fetch_client = ArchivalFetchClient(
        request_timeout_seconds=timeout_seconds,
        delay_seconds=delay_seconds,
    )

    semaphore = asyncio.Semaphore(max(1, int(workers)))
    manifests: List[Dict[str, Any]] = []

    async def _fetch_one(index: int, url: str) -> None:
        slug = _normalize_slug(url, config.slug_regex) or f"u{index:04d}"
        file_path = raw_dir / f"{config.state_code.lower()}_{slug}.html"
        async with semaphore:
            if file_path.exists() and not force:
                manifests.append(
                    {
                        "index": index,
                        "url": url,
                        "file": str(file_path),
                        "status": "skipped_existing",
                        "source": "cached",
                        "chapter_id": slug,
                    }
                )
                return
            try:
                fetch = await fetch_client.fetch_with_fallback(url)
                file_path.write_bytes(fetch.content)
                manifests.append(
                    {
                        "index": index,
                        "url": url,
                        "file": str(file_path),
                        "status": "downloaded",
                        "source": fetch.source,
                        "fetched_at": fetch.fetched_at,
                        "status_code": fetch.status_code,
                        "archive_url": fetch.archive_url,
                        "archive_timestamp": fetch.archive_timestamp,
                        "chapter_id": slug,
                    }
                )
            except Exception as exc:
                manifests.append(
                    {
                        "index": index,
                        "url": url,
                        "status": "error",
                        "error": str(exc),
                        "chapter_id": slug,
                    }
                )

            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)

    await asyncio.gather(*(_fetch_one(i, url) for i, url in enumerate(resolved_urls, start=1)))

    manifests.sort(key=lambda row: (row.get("chapter_id") or "", row.get("url") or ""))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    manifest_path = manifests_dir / f"pointer_manifest_{config.state_code.lower()}_{run_id}.json"
    report_path = manifests_dir / f"pointer_report_{config.state_code.lower()}_{run_id}.json"

    success = sum(1 for row in manifests if row.get("status") in {"downloaded", "skipped_existing"})
    source_counts: Dict[str, int] = {}
    for row in manifests:
        src = row.get("source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1

    report = {
        "status": "success" if success else "error",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_count": len(resolved_urls),
        "successful_count": success,
        "source_counts": source_counts,
        "workers": workers,
        "url_list_file": str(url_list_path),
        "manifest_file": str(manifest_path),
        "parquet_sources": [str(path) for path in parquet_paths],
    }

    _write_json(manifest_path, manifests)
    _write_json(report_path, report)

    return report


def run(argv: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    repo_root = _resolve_repo_root(args.repo_root)
    parquet_map = _parse_parquet_map(args.pointers_parquet_map)

    unknown_states = [code for code in args.state if code.upper() not in STATE_CONFIGS]
    if unknown_states:
        raise SystemExit(f"Unknown state configs: {unknown_states}")

    results: List[Dict[str, Any]] = []
    for state_code in args.state:
        config = STATE_CONFIGS[state_code.upper()]
        state_parquet = parquet_map.get(config.state_code, args.pointers_parquet)
        result = asyncio.run(
            _download_state(
                config,
                repo_root=repo_root,
                pointers_parquet=state_parquet,
                hf_repo=args.hf_repo,
                hf_cache_dir=args.hf_cache_dir,
                workers=args.workers,
                delay_seconds=args.delay_seconds,
                timeout_seconds=args.timeout_seconds,
                force=args.force,
            )
        )
        results.append(result)

    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    run()

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
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import duckdb

from ipfs_datasets_py.utils import anyio_compat as asyncio

from .state_archival_fetch import (
    ArchivalFetchClient as ArchivalFetchClient,
)
from .state_archival_fetch import FetchResult as FetchResult

logger = logging.getLogger(__name__)

DEFAULT_HF_REPO = "endomorphosis/common_crawl_state_index"


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


def _build_url_list(
    urls: Iterable[str], slug_regex: re.Pattern[str], url_template: str
) -> List[str]:
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
            raise ValueError(
                f"Invalid parquet map entry: {entry!r}. Expected STATE=/path/to/pointers.parquet"
            )
        state_code, path_text = entry.split("=", 1)
        state_code = state_code.strip().upper()
        path_text = path_text.strip()
        if not state_code or not path_text:
            raise ValueError(
                f"Invalid parquet map entry: {entry!r}. Expected STATE=/path/to/pointers.parquet"
            )
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
        enable_common_crawl=True,
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

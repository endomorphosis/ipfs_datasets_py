"""Batch-download WARC ranges from per-jurisdiction pointer parquet partitions.

Reads partitioned parquet pointers (partitioned by `jurisdiction`) and writes
HTML payloads into:
  data/state_laws/<STATE>/raw_html

Designed to work with outputs from:
  state_jurisdiction_pointer_inventory.py --write-partitioned-parquet
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

import duckdb
import requests

logger = logging.getLogger(__name__)

DEFAULT_ARCHIVE_DIR = Path("/home/barberb/municipal_scrape_workspace/archive")

DEFAULT_LAW_INCLUDE_REGEXES: List[str] = [
    r"legislature",
    r"legis",
    r"leginfo",
    r"statute",
    r"statutes",
    r"\\bcodes?\\b",
    r"session[-_]?laws?",
    r"revised[-_]?statutes?",
    r"constitutions?",
    r"\\btitle[s]?\\b",
    r"\\bchapter[s]?\\b",
    r"\\bsection[s]?\\b",
    r"/law[s]?/",
    r"/laws/",
]

DEFAULT_LAW_EXCLUDE_REGEXES: List[str] = [
    r"/news",
    r"/press",
    r"/events",
    r"/calendar",
    r"/jobs",
    r"/careers",
    r"/contact",
    r"/about",
    r"/privacy",
    r"/terms",
    r"/services",
    r"/faq",
    r"/search",
]


@dataclass
class PointerRecord:
    url: str
    warc_filename: str
    warc_offset: int
    warc_length: int


@dataclass
class RangeSlice:
    start: int
    end: int
    record_indexes: List[int]


class NonRetryableDownloadError(RuntimeError):
    pass


def _discover_common_crawl_import_roots() -> List[Path]:
    here = Path(__file__).resolve()
    candidates: List[Path] = []
    seen: set[str] = set()
    for parent in [here.parent, *here.parents]:
        src_root = parent / "src"
        target = src_root / "common_crawl_search_engine" / "ccindex" / "api.py"
        if target.exists():
            key = str(src_root)
            if key not in seen:
                seen.add(key)
                candidates.append(src_root)
    return candidates


def _import_ccindex_api():
    for root in _discover_common_crawl_import_roots():
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        try:
            from common_crawl_search_engine.ccindex import api  # type: ignore

            return api
        except Exception:
            continue
    return None


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._")[:180]


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_parquet_list_sql(paths: Sequence[Path]) -> str:
    items = ["'" + str(p).replace("'", "''") + "'" for p in paths]
    return "[" + ", ".join(items) + "]"


def _sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _build_url_where_clause(
    *,
    include_regexes: Sequence[str],
    exclude_regexes: Sequence[str],
) -> str:
    clauses: List[str] = []

    if include_regexes:
        include_clause = " OR ".join(
            f"regexp_matches(lower(url), {_sql_quote(pattern.lower())})"
            for pattern in include_regexes
        )
        clauses.append(f"({include_clause})")

    if exclude_regexes:
        for pattern in exclude_regexes:
            clauses.append(f"NOT regexp_matches(lower(url), {_sql_quote(pattern.lower())})")

    if not clauses:
        return "1=1"
    return " AND ".join(clauses)


def _load_pointer_records(
    parquet_paths: Sequence[Path],
    *,
    include_regexes: Sequence[str],
    exclude_regexes: Sequence[str],
) -> List[PointerRecord]:
    if not parquet_paths:
        return []

    con = duckdb.connect()
    list_sql = _build_parquet_list_sql(parquet_paths)
    url_where = _build_url_where_clause(
        include_regexes=include_regexes,
        exclude_regexes=exclude_regexes,
    )

    query = f"""
        SELECT lower(url) AS url,
               warc_filename,
               warc_offset,
               warc_length
        FROM read_parquet({list_sql})
        WHERE warc_filename IS NOT NULL
            AND lower(warc_filename) LIKE '%/warc/%'
            AND lower(warc_filename) LIKE '%.warc.gz'
          AND warc_offset IS NOT NULL
          AND warc_length IS NOT NULL
          AND url IS NOT NULL
          AND ({url_where})
    """
    rows = con.execute(query).fetchall()

    records: List[PointerRecord] = []
    for row in rows:
        try:
            records.append(
                PointerRecord(
                    url=str(row[0]),
                    warc_filename=str(row[1]),
                    warc_offset=int(row[2]),
                    warc_length=int(row[3]),
                )
            )
        except Exception:
            continue
    return records


def _group_by_warc(records: Sequence[PointerRecord]) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = {}
    for idx, record in enumerate(records):
        grouped.setdefault(record.warc_filename, []).append(idx)
    return grouped


def _coalesce_ranges(
    records: Sequence[PointerRecord],
    record_indexes: Sequence[int],
    *,
    gap_bytes: int,
    max_range_bytes: Optional[int],
) -> List[RangeSlice]:
    sorted_indexes = sorted(record_indexes, key=lambda i: records[i].warc_offset)
    slices: List[RangeSlice] = []

    current_start: Optional[int] = None
    current_end: Optional[int] = None
    current_records: List[int] = []

    for idx in sorted_indexes:
        record = records[idx]
        start = record.warc_offset
        end = record.warc_offset + record.warc_length - 1

        if current_start is None:
            current_start = start
            current_end = end
            current_records = [idx]
            continue

        gap = start - (current_end or start)
        candidate_end = max(current_end or end, end)
        candidate_size = candidate_end - (current_start or start) + 1

        should_merge = gap_bytes >= 0 and gap <= gap_bytes
        if max_range_bytes is not None and candidate_size > max_range_bytes:
            should_merge = False

        if should_merge:
            current_end = candidate_end
            current_records.append(idx)
        else:
            slices.append(RangeSlice(start=current_start, end=current_end or current_start, record_indexes=current_records))
            current_start = start
            current_end = end
            current_records = [idx]

    if current_start is not None:
        slices.append(RangeSlice(start=current_start, end=current_end or current_start, record_indexes=current_records))

    return slices


def _download_ranges_for_warc(
    warc_filename: str,
    ranges: Sequence[RangeSlice],
    *,
    out_dir: Path,
    timeout_seconds: int,
    overwrite: bool,
    allow_download: bool,
    max_retries: int,
    retry_backoff_seconds: float,
    playwright_fallback_on_403: bool,
) -> List[Dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_name(warc_filename)
    combined_path = out_dir / f"{safe_name}.ranges.bin"
    index_path = out_dir / f"{safe_name}.ranges.json"

    if combined_path.exists() and index_path.exists() and not overwrite:
        return json.loads(index_path.read_text(encoding="utf-8"))

    if not allow_download:
        raise RuntimeError(f"Missing range files for {warc_filename}: {combined_path} / {index_path}")

    url = "https://data.commoncrawl.org/" + warc_filename.lstrip("/")

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "municipal-scrape/1.0 (+https://commoncrawl.org)",
            "Accept-Encoding": "identity",
        }
    )
    index_entries: List[Dict[str, Any]] = []

    def _playwright_range_get(range_start: int, range_end: int) -> tuple[Optional[int], Optional[bytes], Optional[str]]:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as exc:
            return None, None, f"playwright_import_error: {exc}"

        target_headers = {"Range": f"bytes={int(range_start)}-{int(range_end)}"}
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                )
                response = context.request.get(
                    url,
                    headers=target_headers,
                    timeout=int(timeout_seconds * 1000),
                )
                status = int(response.status)
                if status not in (200, 206):
                    browser.close()
                    return status, None, f"playwright_status={status}"
                body = response.body()
                browser.close()
                return status, body, None
        except Exception as exc:
            return None, None, f"playwright_error: {exc}"

    with combined_path.open("wb") as handle:
        for range_slice in ranges:
            start = int(range_slice.start)
            end = int(range_slice.end)
            expected_size = (end - start) + 1
            headers = {"Range": f"bytes={start}-{end}"}
            logger.info("Downloading %s bytes=%s-%s", warc_filename, start, end)
            resp: Optional[requests.Response] = None
            raw_payload: Optional[bytes] = None
            last_error: Optional[str] = None
            for attempt in range(max(1, int(max_retries))):
                try:
                    resp = session.get(url, headers=headers, timeout=timeout_seconds, stream=True)
                    if resp.status_code in (200, 206):
                        break
                    if resp.status_code in (403, 429, 500, 502, 503, 504):
                        last_error = f"transient_status={resp.status_code}"
                        if attempt + 1 < max_retries:
                            sleep_seconds = retry_backoff_seconds * (2 ** attempt)
                            logger.warning(
                                "Retrying %s bytes=%s-%s after status %s (attempt %s/%s, sleep %.1fs)",
                                warc_filename,
                                start,
                                end,
                                resp.status_code,
                                attempt + 1,
                                max_retries,
                                sleep_seconds,
                            )
                            time.sleep(max(0.0, sleep_seconds))
                            continue
                    if resp.status_code == 403 and playwright_fallback_on_403:
                        logger.warning(
                            "Requests got 403 for %s bytes=%s-%s; trying Playwright fallback",
                            warc_filename,
                            start,
                            end,
                        )
                        pw_status, pw_data, pw_err = _playwright_range_get(start, end)
                        if pw_status in (200, 206) and pw_data is not None:
                            if pw_status == 200 and len(pw_data) != expected_size:
                                last_error = (
                                    f"playwright_status=200_size_mismatch expected={expected_size} got={len(pw_data)}"
                                )
                            else:
                                raw_payload = pw_data
                                resp = None
                                break
                        last_error = pw_err or f"playwright_status={pw_status}"
                    if resp.status_code in (400, 401, 404, 410, 416):
                        raise NonRetryableDownloadError(
                            f"Non-retryable status {resp.status_code} for {warc_filename} bytes={start}-{end}"
                        )
                    raise RuntimeError(f"Expected 200/206 for range GET, got {resp.status_code}")
                except NonRetryableDownloadError:
                    raise
                except Exception as exc:
                    last_error = str(exc)
                    if attempt + 1 < max_retries:
                        sleep_seconds = retry_backoff_seconds * (2 ** attempt)
                        logger.warning(
                            "Retrying %s bytes=%s-%s after error: %s (attempt %s/%s, sleep %.1fs)",
                            warc_filename,
                            start,
                            end,
                            exc,
                            attempt + 1,
                            max_retries,
                            sleep_seconds,
                        )
                        time.sleep(max(0.0, sleep_seconds))
                        continue
                    raise

            if resp is None or resp.status_code not in (200, 206):
                if raw_payload is None:
                    raise RuntimeError(
                        f"Failed range GET after retries for {warc_filename} bytes={start}-{end}: {last_error}"
                    )

            file_offset = handle.tell()
            sha256 = hashlib.sha256()
            size = 0
            if raw_payload is not None:
                handle.write(raw_payload)
                sha256.update(raw_payload)
                size = len(raw_payload)
            else:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    sha256.update(chunk)
                    size += len(chunk)

            index_entries.append(
                {
                    "start": start,
                    "end": end,
                    "file_offset": file_offset,
                    "size": size,
                    "sha256": sha256.hexdigest(),
                }
            )

    _write_json(index_path, index_entries)
    return index_entries


def _extract_http_payload(raw_bytes: bytes) -> bytes:
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


def _find_range_entry(entries: Sequence[Dict[str, Any]], offset: int, length: int) -> Optional[Dict[str, Any]]:
    end = offset + length - 1
    for entry in entries:
        if entry["start"] <= offset and entry["end"] >= end:
            return entry
    return None


def _url_to_output_name(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path or "index"
    safe_path = _safe_name(path.replace("/", "_")) or "index"
    short_hash = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{safe_path}__{short_hash}.html"


def _split_records_to_html(
    records: Sequence[PointerRecord],
    record_indexes: Sequence[int],
    *,
    ranges_index: Sequence[Dict[str, Any]],
    combined_path: Path,
    output_dir: Path,
    overwrite: bool,
) -> List[Dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests: List[Dict[str, Any]] = []

    with combined_path.open("rb") as handle:
        for idx in record_indexes:
            record = records[idx]
            entry = _find_range_entry(ranges_index, record.warc_offset, record.warc_length)
            if not entry:
                manifests.append(
                    {
                        "url": record.url,
                        "status": "missing_range",
                        "warc_filename": record.warc_filename,
                        "warc_offset": record.warc_offset,
                        "warc_length": record.warc_length,
                    }
                )
                continue

            offset_in_file = entry["file_offset"] + (record.warc_offset - entry["start"])
            handle.seek(offset_in_file)
            raw_bytes = handle.read(record.warc_length)
            payload = _extract_http_payload(raw_bytes)

            file_name = _url_to_output_name(record.url)
            file_path = output_dir / file_name

            if file_path.exists() and not overwrite:
                manifests.append(
                    {
                        "url": record.url,
                        "status": "skipped_existing",
                        "file": str(file_path),
                        "warc_filename": record.warc_filename,
                        "warc_offset": record.warc_offset,
                        "warc_length": record.warc_length,
                    }
                )
                continue

            file_path.write_bytes(payload)
            manifests.append(
                {
                    "url": record.url,
                    "status": "written",
                    "file": str(file_path),
                    "warc_filename": record.warc_filename,
                    "warc_offset": record.warc_offset,
                    "warc_length": record.warc_length,
                }
            )

    return manifests


def _fetch_records_via_ccindex(
    records: Sequence[PointerRecord],
    record_indexes: Sequence[int],
    *,
    output_dir: Path,
    overwrite: bool,
    ccapi: Any,
    cc_cache_mode: str,
    prefix: str,
    timeout_seconds: int,
    full_warc_cache_dir: Optional[Path],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifests: List[Dict[str, Any]] = []
    failed_warcs: Dict[str, str] = {}

    for idx in record_indexes:
        record = records[idx]
        file_name = _url_to_output_name(record.url)
        file_path = output_dir / file_name

        if file_path.exists() and not overwrite:
            manifests.append(
                {
                    "url": record.url,
                    "status": "skipped_existing",
                    "file": str(file_path),
                    "warc_filename": record.warc_filename,
                    "warc_offset": record.warc_offset,
                    "warc_length": record.warc_length,
                }
            )
            continue

        try:
            fetch, source, local_path = ccapi.fetch_warc_record(
                warc_filename=str(record.warc_filename),
                warc_offset=int(record.warc_offset),
                warc_length=int(record.warc_length),
                prefix=str(prefix),
                timeout_s=float(timeout_seconds),
                max_bytes=max(int(record.warc_length), 2_000_000),
                decode_gzip_text=False,
                cache_mode=str(cc_cache_mode),
                full_warc_cache_dir=(Path(full_warc_cache_dir) if full_warc_cache_dir else None),
            )
            if not getattr(fetch, "ok", False) or not getattr(fetch, "raw_base64", None):
                err = str(getattr(fetch, "error", None) or "fetch_warc_record failed")
                manifests.append(
                    {
                        "url": record.url,
                        "status": "fetch_failed",
                        "error": err,
                        "source": source,
                        "local_path": local_path,
                        "warc_filename": record.warc_filename,
                        "warc_offset": record.warc_offset,
                        "warc_length": record.warc_length,
                    }
                )
                failed_warcs.setdefault(record.warc_filename, err)
                continue

            raw_bytes = base64.b64decode(str(fetch.raw_base64))
            payload = _extract_http_payload(raw_bytes)
            file_path.write_bytes(payload)
            manifests.append(
                {
                    "url": record.url,
                    "status": "written",
                    "file": str(file_path),
                    "source": source,
                    "local_path": local_path,
                    "warc_filename": record.warc_filename,
                    "warc_offset": record.warc_offset,
                    "warc_length": record.warc_length,
                }
            )
        except Exception as exc:
            err = str(exc)
            manifests.append(
                {
                    "url": record.url,
                    "status": "fetch_failed",
                    "error": err,
                    "warc_filename": record.warc_filename,
                    "warc_offset": record.warc_offset,
                    "warc_length": record.warc_length,
                }
            )
            failed_warcs.setdefault(record.warc_filename, err)

    failed_list = [
        {"warc_filename": wf, "error": msg}
        for wf, msg in sorted(failed_warcs.items(), key=lambda kv: kv[0])
    ]
    return manifests, failed_list


def _discover_states(partitioned_parquet_dir: Path) -> List[str]:
    states: List[str] = []
    for entry in sorted(partitioned_parquet_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not entry.name.startswith("jurisdiction="):
            continue
        code = entry.name.split("=", 1)[1].strip().upper()
        if code:
            states.append(code)
    return states


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch-download WARC ranges from partitioned jurisdiction pointer parquet.",
    )
    parser.add_argument(
        "--partitioned-parquet-dir",
        type=Path,
        default=Path("artifacts/jurisdiction_pointer_inventory/pointers_by_jurisdiction"),
        help="Directory containing parquet partitions like jurisdiction=OR/",
    )
    parser.add_argument("--state", action="append", default=None, help="State/jurisdiction code to process (repeatable)")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="Repository root")
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR, help="Where to store .ranges files")
    parser.add_argument("--range-gap-bytes", type=int, default=1024)
    parser.add_argument("--max-range-bytes", type=int, default=None)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--overwrite-ranges", action="store_true")
    parser.add_argument("--overwrite-html", action="store_true")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--max-warc-files", type=int, default=None, help="Optional cap per state for starting partial runs")
    parser.add_argument("--max-retries", type=int, default=5, help="Max retries per range request on transient errors")
    parser.add_argument("--retry-backoff-seconds", type=float, default=1.5, help="Base exponential backoff seconds")
    parser.add_argument(
        "--cc-cache-mode",
        choices=["range", "auto", "full"],
        default="range",
        help="Fetch strategy: range=direct range GETs; auto/full use common_crawl_search_engine cache-aware fetcher.",
    )
    parser.add_argument(
        "--cc-prefix",
        default="https://data.commoncrawl.org/",
        help="Common Crawl base URL passed to ccindex fetcher.",
    )
    parser.add_argument(
        "--full-warc-cache-dir",
        type=Path,
        default=None,
        help="Optional directory for ccindex full-WARC cache when --cc-cache-mode=auto|full.",
    )
    parser.add_argument(
        "--playwright-fallback-on-403",
        action="store_true",
        help="On 403 range errors from requests, retry the same range via Playwright browser context.",
    )
    parser.add_argument("--laws-only", action="store_true", help="Apply strict law-focused URL filters")
    parser.add_argument(
        "--url-include-regex",
        action="append",
        default=None,
        help="Additional include regex for URL filtering (repeatable)",
    )
    parser.add_argument(
        "--url-exclude-regex",
        action="append",
        default=None,
        help="Additional exclude regex for URL filtering (repeatable)",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser


def run(argv: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    partitioned_parquet_dir = args.partitioned_parquet_dir.expanduser().resolve()
    if not partitioned_parquet_dir.exists():
        raise SystemExit(f"Partitioned parquet dir not found: {partitioned_parquet_dir}")

    requested_states = [s.upper() for s in (args.state or _discover_states(partitioned_parquet_dir))]
    if not requested_states:
        raise SystemExit("No jurisdictions found to process.")

    results: List[Dict[str, Any]] = []

    include_regexes: List[str] = list(args.url_include_regex or [])
    exclude_regexes: List[str] = list(args.url_exclude_regex or [])
    if args.laws_only:
        include_regexes = [*DEFAULT_LAW_INCLUDE_REGEXES, *include_regexes]
        exclude_regexes = [*DEFAULT_LAW_EXCLUDE_REGEXES, *exclude_regexes]

    ccapi = None
    if str(args.cc_cache_mode).lower() in {"auto", "full"}:
        ccapi = _import_ccindex_api()
        if ccapi is None:
            raise SystemExit(
                "--cc-cache-mode auto/full requested but common_crawl_search_engine.ccindex.api could not be imported"
            )

    for state_code in requested_states:
        part_dir = partitioned_parquet_dir / f"jurisdiction={state_code}"
        parquet_paths = sorted(part_dir.rglob("*.parquet"))
        if not parquet_paths:
            logger.warning("No parquet files for %s at %s", state_code, part_dir)
            continue

        logger.info("Loading pointer records for %s (%s parquet files)", state_code, len(parquet_paths))
        records = _load_pointer_records(
            parquet_paths,
            include_regexes=include_regexes,
            exclude_regexes=exclude_regexes,
        )
        grouped = _group_by_warc(records)

        warc_items = sorted(grouped.items(), key=lambda kv: kv[0])
        if args.max_warc_files is not None:
            warc_items = warc_items[: max(0, int(args.max_warc_files))]

        archive_dir = args.archive_dir.expanduser().resolve() / f"warc_ranges_{state_code.lower()}"
        html_output_dir = args.repo_root.expanduser().resolve() / "data" / "state_laws" / state_code / "raw_html"
        manifest_dir = args.repo_root.expanduser().resolve() / "data" / "state_laws" / state_code / "manifests"
        manifest_dir.mkdir(parents=True, exist_ok=True)

        all_manifests: List[Dict[str, Any]] = []
        failed_warc_files: List[Dict[str, Any]] = []

        if str(args.cc_cache_mode).lower() in {"auto", "full"}:
            selected_indexes: List[int] = []
            for _wf, idxs in warc_items:
                selected_indexes.extend(idxs)
            manifests, failed = _fetch_records_via_ccindex(
                records,
                selected_indexes,
                output_dir=html_output_dir,
                overwrite=args.overwrite_html,
                ccapi=ccapi,
                cc_cache_mode=str(args.cc_cache_mode),
                prefix=str(args.cc_prefix),
                timeout_seconds=int(args.timeout_seconds),
                full_warc_cache_dir=(
                    args.full_warc_cache_dir.expanduser().resolve()
                    if args.full_warc_cache_dir
                    else args.archive_dir.expanduser().resolve() / "full_warc_cache"
                ),
            )
            all_manifests.extend(manifests)
            failed_warc_files.extend(failed)
        else:
            for warc_filename, record_indexes in warc_items:
                try:
                    ranges = _coalesce_ranges(
                        records,
                        record_indexes,
                        gap_bytes=args.range_gap_bytes,
                        max_range_bytes=args.max_range_bytes,
                    )
                    ranges_index = _download_ranges_for_warc(
                        warc_filename,
                        ranges,
                        out_dir=archive_dir,
                        timeout_seconds=args.timeout_seconds,
                        overwrite=args.overwrite_ranges,
                        allow_download=not args.skip_download,
                        max_retries=args.max_retries,
                        retry_backoff_seconds=args.retry_backoff_seconds,
                        playwright_fallback_on_403=bool(args.playwright_fallback_on_403),
                    )

                    combined_path = archive_dir / f"{_safe_name(warc_filename)}.ranges.bin"
                    manifests = _split_records_to_html(
                        records,
                        record_indexes,
                        ranges_index=ranges_index,
                        combined_path=combined_path,
                        output_dir=html_output_dir,
                        overwrite=args.overwrite_html,
                    )
                    all_manifests.extend(manifests)
                except Exception as exc:
                    logger.error("Failed WARC %s for %s: %s", warc_filename, state_code, exc)
                    failed_warc_files.append({"warc_filename": warc_filename, "error": str(exc)})
                    continue

        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        manifest_path = manifest_dir / f"warc_batch_manifest_{state_code.lower()}_{run_id}.json"
        summary_path = manifest_dir / f"warc_batch_summary_{state_code.lower()}_{run_id}.json"
        _write_json(manifest_path, all_manifests)

        summary = {
            "state": state_code,
            "run_id": run_id,
            "records": len(records),
            "warc_files_total": len(grouped),
            "warc_files_processed": len(warc_items),
            "warc_files_failed": len(failed_warc_files),
            "failed_warc_files": failed_warc_files,
            "manifest": str(manifest_path),
            "summary": str(summary_path),
            "archive_dir": str(archive_dir),
            "html_output_dir": str(html_output_dir),
        }
        _write_json(summary_path, summary)
        results.append(summary)

    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    run()

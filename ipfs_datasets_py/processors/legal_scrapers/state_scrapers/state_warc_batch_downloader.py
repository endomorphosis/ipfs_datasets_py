"""Batch download WARC ranges for state law URLs and split into HTML files.

This script filters pointer parquet records for a state-specific URL pattern,
coalesces WARC byte ranges per WARC file, downloads those ranges in bulk, and
then splits the resulting payloads into HTML files.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import duckdb
import requests

from .state_archival_pointer_downloader import STATE_CONFIGS, _resolve_parquet_paths

logger = logging.getLogger(__name__)

DEFAULT_HF_REPO = "endomorphosis/common_crawl_state_index"
DEFAULT_ARCHIVE_DIR = Path("/home/barberb/municipal_scrape_workspace/archive")


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


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:200]


def _normalize_slug(url: str, slug_regex: re.Pattern[str]) -> Optional[str]:
    path = urlsplit(url).path
    match = slug_regex.search(path)
    if not match:
        return None
    raw = match.group(1).lower()
    digits = "".join(ch for ch in raw if ch.isdigit())
    suffix = "".join(ch for ch in raw if ch.isalpha())
    if not digits:
        return None
    return f"{int(digits):03d}{suffix}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _build_parquet_list_sql(paths: Sequence[Path]) -> str:
    parts = ["'" + str(p).replace("'", "''") + "'" for p in paths]
    return "[" + ", ".join(parts) + "]"


def _load_pointer_records(
    parquet_paths: Sequence[Path],
    url_filters_sql: Sequence[str],
) -> List[PointerRecord]:
    con = duckdb.connect()
    list_sql = _build_parquet_list_sql(parquet_paths)
    con.execute(f"CREATE VIEW ptr AS SELECT * FROM read_parquet({list_sql})")
    where_clause = " AND ".join(f"({clause})" for clause in url_filters_sql)
    query = f"""
        SELECT lower(url) AS url,
               warc_filename,
               warc_offset,
               warc_length
        FROM ptr
        WHERE {where_clause}
          AND warc_filename IS NOT NULL
          AND warc_offset IS NOT NULL
          AND warc_length IS NOT NULL
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
    prefix: str,
    timeout_seconds: int,
    overwrite: bool,
    allow_download: bool,
) -> List[Dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_name(warc_filename)
    combined_path = out_dir / f"{safe_name}.ranges.bin"
    index_path = out_dir / f"{safe_name}.ranges.json"

    if combined_path.exists() and index_path.exists() and not overwrite:
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if not allow_download:
        raise RuntimeError(f"Missing range files for {warc_filename}: {combined_path} / {index_path}")

    url = prefix.rstrip("/") + "/" + warc_filename.lstrip("/")

    session = requests.Session()
    index_entries: List[Dict[str, Any]] = []

    with combined_path.open("wb") as handle:
        for range_slice in ranges:
            start = int(range_slice.start)
            end = int(range_slice.end)
            headers = {"Range": f"bytes={start}-{end}"}
            logger.info("Downloading %s bytes=%s-%s", warc_filename, start, end)
            resp = session.get(url, headers=headers, timeout=timeout_seconds, stream=True)
            if resp.status_code != 206:
                raise RuntimeError(f"Expected 206 for range GET, got {resp.status_code}")

            file_offset = handle.tell()
            sha256 = hashlib.sha256()
            size = 0
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


def _split_records_to_html(
    records: Sequence[PointerRecord],
    record_indexes: Sequence[int],
    *,
    ranges_index: Sequence[Dict[str, Any]],
    combined_path: Path,
    output_dir: Path,
    slug_regex: re.Pattern[str],
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

            slug = _normalize_slug(record.url, slug_regex)
            if slug:
                name = f"ors{slug}.html"
            else:
                name = _safe_name(urlsplit(record.url).path) or _safe_name(record.url)
                name = f"{name}.html"
            file_path = output_dir / name

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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch download WARC ranges for state law URLs and split into HTML.",
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
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=DEFAULT_ARCHIVE_DIR,
        help="Directory to store downloaded WARC ranges",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root used for HTML output paths (default: current working directory)",
    )
    parser.add_argument(
        "--range-gap-bytes",
        type=int,
        default=1024,
        help="Max gap in bytes to coalesce ranges (default: 1024)",
    )
    parser.add_argument(
        "--max-range-bytes",
        type=int,
        default=None,
        help="Max size for a coalesced range (default: unlimited)",
    )
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--overwrite-ranges", action="store_true")
    parser.add_argument("--overwrite-html", action="store_true")
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Do not download ranges; require existing .ranges.bin/.ranges.json files",
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

    parquet_map = _parse_parquet_map(args.pointers_parquet_map)
    repo_root = args.repo_root or Path.cwd()

    results: List[Dict[str, Any]] = []
    for state_code in args.state:
        config = STATE_CONFIGS.get(state_code.upper())
        if not config:
            raise SystemExit(f"Unknown state config: {state_code}")

        state_parquet = parquet_map.get(config.state_code, args.pointers_parquet)
        parquet_paths = _resolve_parquet_paths(
            pointers_parquet=state_parquet,
            hf_repo=args.hf_repo,
            hf_cache_dir=args.hf_cache_dir,
            state_code=config.state_code,
        )

        records = _load_pointer_records(parquet_paths, config.url_filters_sql)
        grouped = _group_by_warc(records)

        archive_dir = args.archive_dir
        expected_suffix = f"warc_ranges_{config.state_code.lower()}"
        if archive_dir.name != expected_suffix:
            archive_dir = archive_dir / expected_suffix
        html_output_dir = repo_root / config.output_dir_rel / "raw_html"
        manifest_dir = repo_root / config.output_dir_rel / "manifests"

        manifest_dir.mkdir(parents=True, exist_ok=True)

        all_manifests: List[Dict[str, Any]] = []

        for warc_filename, record_indexes in grouped.items():
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
                prefix="https://data.commoncrawl.org/",
                timeout_seconds=args.timeout_seconds,
                overwrite=args.overwrite_ranges,
                allow_download=not args.skip_download,
            )

            combined_path = archive_dir / f"{_safe_name(warc_filename)}.ranges.bin"
            manifests = _split_records_to_html(
                records,
                record_indexes,
                ranges_index=ranges_index,
                combined_path=combined_path,
                output_dir=html_output_dir,
                slug_regex=config.slug_regex,
                overwrite=args.overwrite_html,
            )
            all_manifests.extend(manifests)

        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        manifest_path = manifest_dir / f"warc_batch_manifest_{config.state_code.lower()}_{run_id}.json"
        _write_json(manifest_path, all_manifests)

        results.append(
            {
                "state": config.state_code,
                "records": len(records),
                "warc_files": len(grouped),
                "manifest": str(manifest_path),
                "archive_dir": str(archive_dir),
                "html_output_dir": str(html_output_dir),
            }
        )

    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    run()

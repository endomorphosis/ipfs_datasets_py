#!/usr/bin/env python3
"""Discover official Netherlands BWB/BWBR document identifiers via SRU.

This is a discovery-only helper. It does not fetch law text, so it can safely
inventory the official BWB universe before the heavier sharded scrape jobs run.
"""

from __future__ import annotations

import argparse
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = (
    REPO_ROOT
    / "ipfs_datasets_py"
    / "processors"
    / "legal_scrapers"
    / "netherlands_laws"
    / "datasets"
    / "raw"
    / "nl_full_bwb_discovery"
)
SRU_ENDPOINT = "https://zoekservice.overheid.nl/sru/Search"
DEFAULT_QUERY = "cql.allRecords=1"
USER_AGENT = "ipfs-datasets-netherlands-law-scraper/1.0"


def local_name(tag: str) -> str:
    return str(tag or "").rsplit("}", 1)[-1]


def build_sru_url(query: str, *, start_record: int, maximum_records: int) -> str:
    params = {
        "operation": "searchRetrieve",
        "version": "2.0",
        "x-connection": "BWB",
        "query": query,
        "startRecord": str(start_record),
        "maximumRecords": str(maximum_records),
    }
    return f"{SRU_ENDPOINT}?{urlencode(params)}"


def parse_sru_page(xml_text: str) -> tuple[list[dict[str, Any]], int | None, int | None]:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    records: list[dict[str, Any]] = []
    total_records: int | None = None
    next_record_position: int | None = None
    current_record: dict[str, Any] | None = None

    for elem in root.iter():
        name = local_name(elem.tag)
        text = " ".join(str(elem.text or "").split())
        if name == "numberOfRecords" and text.isdigit():
            total_records = int(text)
        elif name == "nextRecordPosition" and text.isdigit():
            next_record_position = int(text)
        elif name == "record":
            current_record = {}
            records.append(current_record)
        elif current_record is not None and name == "recordPosition" and text.isdigit():
            current_record["record_position"] = int(text)
        elif current_record is not None and name == "identifier" and text.upper().startswith("BWBR"):
            current_record["identifier"] = text.upper()
        elif current_record is not None and name == "title" and text and "title" not in current_record:
            current_record["title"] = text
        elif current_record is not None and name == "type" and text and "document_type" not in current_record:
            current_record["document_type"] = text

    cleaned: list[dict[str, Any]] = []
    for record in records:
        identifier = str(record.get("identifier") or "")
        if not identifier:
            continue
        cleaned.append(
            {
                "identifier": identifier,
                "source_url": f"https://wetten.overheid.nl/{identifier}/",
                "information_url": f"https://wetten.overheid.nl/{identifier}/informatie",
                "record_position": record.get("record_position"),
                "title": record.get("title") or "",
                "document_type": record.get("document_type") or "",
            }
        )
    return cleaned, total_records, next_record_position


def discover(
    *,
    out_dir: Path,
    query: str,
    start_record: int,
    maximum_records: int,
    rate_limit_delay: float,
    max_pages: int | None,
    retries: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/xml,*/*;q=0.8"})
    next_start_record = max(1, int(start_record))
    pages_visited = 0
    total_records: int | None = None
    rows_by_identifier: dict[str, dict[str, Any]] = {}
    failed_pages: list[dict[str, Any]] = []
    jsonl_path = out_dir / "netherlands_bwb_full_discovery_urls.jsonl"
    if jsonl_path.exists():
        with jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                identifier = str(row.get("identifier") or "")
                if identifier and identifier not in rows_by_identifier:
                    rows_by_identifier[identifier] = row

    while True:
        if max_pages is not None and pages_visited >= max_pages:
            break
        url = build_sru_url(query, start_record=next_start_record, maximum_records=maximum_records)
        last_error = ""
        for attempt in range(max(1, retries + 1)):
            try:
                response = session.get(url, timeout=60)
                if int(response.status_code) not in {200, 406}:
                    raise RuntimeError(f"HTTP {response.status_code}")
                rows, page_total, next_record = parse_sru_page(response.text or "")
                if page_total is not None:
                    total_records = page_total
                for row in rows:
                    identifier = str(row.get("identifier") or "")
                    if identifier and identifier not in rows_by_identifier:
                        rows_by_identifier[identifier] = row
                pages_visited += 1
                if not next_record or (total_records is not None and next_record > total_records):
                    next_start_record = 0
                else:
                    next_start_record = int(next_record)
                last_error = ""
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt < retries:
                    time.sleep(max(1.0, rate_limit_delay))
        if last_error:
            failed_pages.append({"start_record": next_start_record, "url": url, "error": last_error})
            break
        if not next_start_record:
            break
        time.sleep(max(0.0, rate_limit_delay))

    rows = sorted(rows_by_identifier.values(), key=lambda item: str(item.get("identifier") or ""))
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    manifest = {
        "query": query,
        "sru_endpoint": SRU_ENDPOINT,
        "official_source": "official BWB SRU service",
        "maximum_records": maximum_records,
        "start_record": start_record,
        "max_pages": max_pages,
        "retries": retries,
        "pages_visited": pages_visited,
        "number_of_records_reported": total_records,
        "unique_laws_discovered": len(rows),
        "failed_pages_count": len(failed_pages),
        "failed_pages": failed_pages,
        "discovered_urls_path": str(jsonl_path),
        "retrieved_at": datetime.now().isoformat(),
        "notes": [
            "Discovery only; law text/status scraping is performed by sharded Netherlands laws scrape commands.",
            "Rows are deduplicated by BWBR identifier from the official BWB SRU response.",
        ],
    }
    manifest_path = out_dir / "netherlands_bwb_full_discovery_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover official BWB/BWBR identifiers via SRU.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--start-record", type=int, default=1)
    parser.add_argument("--maximum-records", type=int, default=1000)
    parser.add_argument("--rate-limit-delay", type=float, default=0.05)
    parser.add_argument("--max-pages", type=int, default=0, help="0 means unbounded.")
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()
    manifest = discover(
        out_dir=args.out_dir,
        query=args.query,
        start_record=args.start_record,
        maximum_records=args.maximum_records,
        rate_limit_delay=args.rate_limit_delay,
        max_pages=None if args.max_pages <= 0 else args.max_pages,
        retries=max(0, args.retries),
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if not manifest.get("failed_pages") else 1


if __name__ == "__main__":
    raise SystemExit(main())

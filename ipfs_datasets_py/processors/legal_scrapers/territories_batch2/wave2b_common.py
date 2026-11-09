#!/usr/bin/env python3
"""Shared helpers for Gap Matrix Wave 2B territory staging (additive, memsafe)."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import pyarrow as pa
import pyarrow.parquet as pq
import requests

UA = (
    "CountryLawScraper/1.0 (research; polite; Benjamin Barber legal corpus; "
    "contact via HuggingFace endomorphosis)"
)
ROOT = Path("/workspace/staging/territories_batch2_20261105")
RAW = ROOT / "raw"
DELAY = 2.0
STRIKE_CODES = {403, 429, 503}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def mem_available_kib() -> int:
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1])
    return 0


def require_mem(floor_gib: float = 3.2) -> None:
    kib = mem_available_kib()
    if kib < floor_gib * 1024 * 1024:
        raise RuntimeError(f"MemAvailable {kib} KiB < floor {floor_gib} GiB")


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    return s


class StrikeStop(RuntimeError):
    pass


def polite_get(
    sess: requests.Session,
    url: str,
    *,
    params: Optional[dict] = None,
    delay: float = DELAY,
    timeout=(20, 120),
    strikes: list[int] | None = None,
) -> requests.Response:
    if strikes is None:
        strikes = []
    require_mem()
    time.sleep(delay)
    r = sess.get(url, params=params, timeout=timeout)
    if r.status_code in STRIKE_CODES:
        strikes.append(r.status_code)
        if len(strikes) >= 3:
            raise StrikeStop(f"3-strike stop on {r.status_code} for {url}")
    return r


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_parquet(path: Path, rows: list[dict], schema_cols: Optional[list[str]] = None) -> int:
    if not rows:
        raise ValueError(f"refusing 0-row parquet: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if schema_cols:
        norm = [{c: r.get(c) for c in schema_cols} for r in rows]
    else:
        # union keys
        keys: list[str] = []
        seen = set()
        for r in rows:
            for k in r:
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        norm = [{c: r.get(c) for c in keys} for r in rows]
        schema_cols = keys
    table = pa.Table.from_pylist(norm)
    pq.write_table(table, path, compression="zstd")
    md = pq.read_metadata(path)
    if md.num_rows <= 0:
        raise ValueError(f"wrote 0-row parquet unexpectedly: {path}")
    return md.num_rows


def verify_load_dataset(dir_path: Path) -> dict:
    from datasets import load_dataset

    require_mem()
    out = {}
    data = dir_path / "data"
    for parquet in sorted(data.glob("*.parquet")):
        # streaming load of local parquet folder via data_files
        ds = load_dataset("parquet", data_files=str(parquet), split="train", streaming=True)
        n = 0
        first = None
        for row in ds:
            if first is None:
                first = list(row.keys())
            n += 1
            if n >= 3:
                # finish count via metadata instead of full stream when large
                break
        md = pq.read_metadata(parquet)
        if md.num_rows <= 0:
            raise ValueError(f"0-row parquet forbidden: {parquet}")
        out[parquet.name] = {"rows": md.num_rows, "columns": first or [], "stream_sample_ok": True}
    return out


LAW_COLS = [
    "id",
    "title",
    "text",
    "source_url",
    "source_type",
    "jurisdiction",
    "country",
    "language",
    "eli",
    "date",
    "date_issued",
    "retrieved_at",
    "license",
    "law_status",
    "identifier",
    "official_identifier",
    "article_count",
    "json_path",
    "metadata_json",
]

ART_COLS = [
    "law_id",
    "id",
    "title",
    "text",
    "source_url",
    "document_number",
    "article_number",
    "record_type",
    "metadata_json",
]


def extract_articles_from_bwb_text(law_id: str, text: str, source_url: str) -> list[dict]:
    """Heuristic article splitter for Dutch BWB plain text (Artikel N)."""
    if not text:
        return []
    parts = re.split(r"(?=\n\s*Artikel\s+[0-9A-Za-z\.\-]+)", text)
    arts = []
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"Artikel\s+([0-9A-Za-z\.\-]+)", part)
        if not m:
            continue
        num = m.group(1)
        if len(part) < 20:
            continue
        arts.append(
            {
                "law_id": law_id,
                "id": f"{law_id}::art::{num}",
                "title": f"Artikel {num}",
                "text": part[:200000],
                "source_url": source_url,
                "document_number": law_id,
                "article_number": num,
                "record_type": "article",
                "metadata_json": json.dumps({"extractor": "bwb_artikel_split_v1"}, ensure_ascii=False),
            }
        )
    return arts

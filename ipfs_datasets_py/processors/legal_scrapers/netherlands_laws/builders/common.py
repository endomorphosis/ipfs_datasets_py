"""Shared helpers for Netherlands laws packaging builders."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes


PARSER_NOISE_PHRASES = [
    "Toon relaties in LiDO",
    "Maak een permanente link",
    "Toon wetstechnische informatie",
    "Geen andere versie om mee te vergelijken",
    "Druk de regeling af",
    "Druk het regelingonderdeel af",
    "Sla de regeling op",
    "Sla het regelingonderdeel op",
]

PARSER_NOISE_PATTERNS = [
    re.compile(rf"\b{re.escape(phrase)}\b", re.IGNORECASE) for phrase in PARSER_NOISE_PHRASES
]
_WHITESPACE_RE = re.compile(r"\s+")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in iter_jsonl(path):
        rows.append(row)
    return rows


def count_jsonl(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def clean_legal_text(text: Any) -> str:
    """Remove official website UI chrome from scraped legal text."""
    if text is None:
        return ""
    cleaned = str(text)
    for pattern in PARSER_NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def stable_row_key(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def disambiguate_duplicate_article_identifiers(rows: list[dict[str, Any]]) -> int:
    """Make repeated scraper article IDs unique by appending a hierarchy-derived suffix."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        identifier = str(row.get("article_identifier") or "")
        if not identifier:
            continue
        groups.setdefault(identifier, []).append(row)

    changed = 0
    for identifier, group in groups.items():
        if len(group) < 2:
            continue
        for row in group:
            basis = {
                "citation": row.get("citation"),
                "hierarchy_path": row.get("hierarchy_path"),
                "hierarchy_path_text": row.get("hierarchy_path_text"),
                "article_number": row.get("article_number"),
                "text": row.get("text"),
            }
            suffix = hashlib.sha256(stable_row_key(basis).encode("utf-8")).hexdigest()[:12]
            row["article_identifier"] = f"{identifier}:path:{suffix}"
            changed += 1
    return changed


def _parquet_safe(value: Any) -> Any:
    if value == {}:
        return None
    if isinstance(value, dict):
        return {key: _parquet_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_parquet_safe(item) for item in value]
    return value


def _jsonify_complex(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_rows = [{key: _parquet_safe(value) for key, value in row.items()} for row in rows]
    try:
        table = pa.Table.from_pylist(safe_rows)
    except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError):
        table = pa.Table.from_pylist(
            [{key: _jsonify_complex(value) for key, value in row.items()} for row in safe_rows]
        )
    pq.write_table(table, path, compression="zstd")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_cid(path: Path) -> str:
    return cid_for_bytes(path.read_bytes())


def file_manifest_entry(path: Path, records: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "file_cid": file_cid(path),
    }
    if records is not None:
        entry["records"] = records
    return entry


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

"""Row builders for the 19-column world municipal schema.

Row granularity is one row per article (plus preamble/annex rows).
Content helpers are REUSED from the US municipal lane
(``municipal_law_database_scrapers/hub/parquet_writer.py``) — loaded by file
path so this module never triggers that package's heavy ``__init__`` chain:
- ``cid_v1_raw_sha256`` — CIDv1/base32/sha2-256 content IDs;
- ``strip_tags`` — inline-markup-flattening HTML→text.

Typical pipeline for one jurisdiction::

    rows = [make_row(doc_id=..., title=..., body_html=..., ...) for ...]
    rows = finalize_rows(rows)          # doc_order 0..n-1, dedupe doc_ids
    table = rows_to_table(rows)        # schema.rows_to_table
    assert_valid(table, jurisdiction_id=..., ...)   # schema.assert_valid
    write_html_parquet(path, table)    # parquet_io.write_html_parquet
"""

from __future__ import annotations

import html as _html_module
import importlib.util
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

_HUB_PARQUET_WRITER = (
    Path(__file__).resolve().parent.parent
    / "municipal_law_database_scrapers"
    / "hub"
    / "parquet_writer.py"
)

_hub_module: Any = None


def _hub() -> Any:
    """Load hub/parquet_writer.py by path (no package ``__init__`` import)."""
    global _hub_module
    if _hub_module is None:
        spec = importlib.util.spec_from_file_location(
            "world_municipal_hub_parquet_writer", _HUB_PARQUET_WRITER
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(
                f"cannot load hub parquet_writer at {_HUB_PARQUET_WRITER}"
            )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _hub_module = module
    return _hub_module


def cid_v1_raw_sha256(text: str) -> str:
    """CIDv1 (base32, raw, sha2-256) of UTF-8 text. Reused from the hub lane."""
    return _hub().cid_v1_raw_sha256(text)


def strip_tags(html_text: str) -> str:
    """Flatten inline markup to plain text. Reused from the hub lane."""
    return _hub().strip_tags(html_text)


def make_cid(jurisdiction_id: str, doc_id: str) -> str:
    """Content ID embedding the jurisdiction — globally unique per jurisdiction."""
    return cid_v1_raw_sha256(f"{jurisdiction_id}_{doc_id}.json")


def chunk_title(node_label: str) -> str:
    """US-style chunk title wrapper (mirrors the hub lane's chunk wrappers)."""
    return f'<div class="chunk-title">{_html_module.escape(node_label or "")}</div>'


def chunk_content(body_html: str) -> str:
    """US-style chunk content wrapper."""
    return f'<div class="chunk-content">{body_html or ""}</div>'


def slugify(text: str) -> str:
    """Generic article-slug helper: lowercase, non-alphanumerics to hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def make_row(
    *,
    jurisdiction_id: str,
    jurisdiction_name: str,
    country: str,
    doc_id: str,
    doc_order: int = 0,
    regeling_id: str = "",
    regeling_work_id: str = "",
    title: str = "",
    structural_path: str = "",
    node_label: str = "",
    html_title: Optional[str] = None,
    html: Optional[str] = None,
    text: Optional[str] = None,
    source_url: str = "",
    xml_url: str = "",
    date_effective: str = "",
    date_modified: str = "",
    retrieved: str = "",
    body_html: str = "",
    cid: Optional[str] = None,
    **extra: str,
) -> Dict[str, Any]:
    """Build one 19-column row dict with pilot-compatible defaults.

    Smart defaults: ``html`` falls back to ``chunk_content(body_html)``;
    ``html_title`` falls back to ``chunk_title(node_label)``; ``text`` falls
    back to ``strip_tags(html)``; ``cid`` falls back to
    ``make_cid(jurisdiction_id, doc_id)``. Country-specific provenance
    columns pass through ``extra`` (appended after column 19 by the schema).
    """
    if html is None:
        html = chunk_content(body_html) if body_html else ""
    if html_title is None:
        html_title = chunk_title(node_label) if node_label else ""
    if text is None:
        text = strip_tags(html)
    if cid is None:
        cid = make_cid(jurisdiction_id, doc_id)
    row: Dict[str, Any] = {
        "cid": cid,
        "jurisdiction_id": jurisdiction_id,
        "jurisdiction_name": jurisdiction_name,
        "country": country,
        "doc_id": doc_id,
        "regeling_id": regeling_id,
        "regeling_work_id": regeling_work_id,
        "doc_order": int(doc_order),
        "title": title,
        "structural_path": structural_path,
        "node_label": node_label,
        "html_title": html_title,
        "html": html,
        "text": text,
        "source_url": source_url,
        "xml_url": xml_url,
        "date_effective": date_effective,
        "date_modified": date_modified,
        "retrieved": retrieved,
    }
    row.update(extra)
    return row


def assign_doc_order(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """(Re)assign doc_order 0..n-1 in list order. Returns the same list."""
    for i, row in enumerate(rows):
        row["doc_order"] = i
    return list(rows)


def ensure_unique_doc_ids(
    rows: Sequence[Dict[str, Any]],
    recompute_cid: bool = True,
) -> List[Dict[str, Any]]:
    """Suffix duplicate doc_ids with -2, -3, ... (pilot convention).

    When a doc_id is suffixed, its cid is recomputed so the content ID keeps
    embedding the final doc_id.
    """
    seen: Dict[str, int] = {}
    out = list(rows)
    for row in out:
        base = str(row.get("doc_id", ""))
        n = seen.get(base, 0) + 1
        seen[base] = n
        if n > 1:
            row["doc_id"] = f"{base}-{n}"
            if recompute_cid and row.get("jurisdiction_id"):
                row["cid"] = make_cid(str(row["jurisdiction_id"]), str(row["doc_id"]))
    return out


def finalize_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Harvest-time finalize: dedupe doc_ids, then assign sequential doc_order."""
    rows = ensure_unique_doc_ids(rows)
    return assign_doc_order(rows)


def drop_empty_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop rows whose text (or html) is blank — the zero-empty-docs gate."""
    return [
        r
        for r in rows
        if str(r.get("text") or "").strip() and str(r.get("html") or "").strip()
    ]

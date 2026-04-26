#!/usr/bin/env python3
"""Retrieve municipal law pages from the Common Crawl municipal index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional


DEFAULT_REPO_ID = "endomorphosis/common_crawl_municipal_index"
DEFAULT_INDEX_FILE = "slice_indexes/uncapped_parquet_20260215_101154/pointers.parquet"


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.common_crawl_index_loader import (  # noqa: E402
    CommonCrawlIndexLoader,
)
from ipfs_datasets_py.processors.legal_scrapers.municipal_scraper_engine import (  # noqa: E402
    MunicipalScraperFallbacks,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_obj  # noqa: E402


def _parse_csv(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _download_index(*, repo_id: str, index_file: str, index_root: Path) -> Path:
    """Download the municipal pointer parquet into the local index tree."""
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        raise RuntimeError("huggingface_hub is required for --download-index") from exc

    municipal_dir = index_root / "municipal"
    municipal_dir.mkdir(parents=True, exist_ok=True)
    downloaded = hf_hub_download(
        repo_id=repo_id,
        repo_type="dataset",
        filename=index_file,
        local_dir=str(municipal_dir),
    )
    return Path(downloaded)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_records_parquet(path: Path, records: List[Dict[str, Any]]) -> Optional[Path]:
    if not records:
        return None
    import pyarrow as pa
    import pyarrow.parquet as pq

    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(records), path)
    return path


def _sql_literal(value: Any) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _candidate_score(row: Dict[str, Any]) -> int:
    url = str(row.get("url") or "").lower()
    mime = str(row.get("mime") or "").lower()
    status = int(row.get("status") or 0)
    score = 0
    if status == 200:
        score += 50
    if "pdf" in mime:
        score += 40
    if "efiles.portlandoregon.gov" in url and "/file/document" in url:
        score += 35
    if any(term in url for term in ("ordinance", "charter", "code", "pcc", "title", "chapter", "zoning")):
        score += 25
    if any(term in url for term in ("title33", "title%2033", "zoning%20code", "planning%20and%20zoning")):
        score += 25
    if "/archives/39969" in url:
        score -= 25
    if "login=1" in url or "forgot=1" in url:
        score -= 50
    return score


def _list_candidates(
    *,
    index_root: Path,
    output_root: Path,
    place_name: str,
    state_code: str,
    gnis: str,
    url_terms: List[str],
    mime_terms: List[str],
    limit: int,
) -> Dict[str, Any]:
    import duckdb

    municipal_dir = index_root / "municipal"
    parquet_files = sorted(municipal_dir.rglob("*.parquet"))
    if not parquet_files:
        raise RuntimeError(f"No local municipal parquet files found under {municipal_dir}")

    relation = "read_parquet([" + ", ".join(_sql_literal(str(path)) for path in parquet_files) + "])"
    filters = []
    if place_name:
        place = place_name.lower().removeprefix("city of ").strip()
        filters.append(f"lower(place_name) LIKE {_sql_literal('%' + place + '%')}")
    if state_code:
        filters.append(f"upper(state_code) = {_sql_literal(state_code.upper())}")
    if gnis:
        filters.append(f"gnis = {_sql_literal(gnis)}")
    if url_terms:
        filters.append("(" + " OR ".join(f"lower(url) LIKE {_sql_literal('%' + term.lower() + '%')}" for term in url_terms) + ")")
    if mime_terms:
        filters.append("(" + " OR ".join(f"lower(mime) LIKE {_sql_literal('%' + term.lower() + '%')}" for term in mime_terms) + ")")
    where = " AND ".join(filters) if filters else "TRUE"
    sql = f"""
        SELECT domain, url, collection, timestamp, mime, status,
               warc_filename, warc_offset, warc_length, gnis, place_name, state_code
        FROM {relation}
        WHERE {where}
        ORDER BY
          CASE WHEN status = 200 THEN 0 ELSE 1 END,
          CASE WHEN lower(mime) LIKE '%pdf%' THEN 0 ELSE 1 END,
          timestamp DESC
        LIMIT {max(1, int(limit))}
    """
    rows = [dict(row) for row in duckdb.connect().execute(sql).fetchdf().to_dict("records")]
    for row in rows:
        row["candidate_score"] = _candidate_score(row)
    rows.sort(key=lambda row: (int(row.get("candidate_score") or 0), str(row.get("timestamp") or "")), reverse=True)

    output_root.mkdir(parents=True, exist_ok=True)
    parquet_path = _write_records_parquet(output_root / "candidate_pointers.parquet", rows)
    json_path = output_root / "candidate_pointers.json"
    json_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "candidate_count": len(rows),
        "candidate_parquet": str(parquet_path) if parquet_path else None,
        "candidate_json": str(json_path),
        "top_candidates": rows[:10],
    }


def _extension_for_mime(mime: str) -> str:
    mime_l = str(mime or "").lower()
    if "pdf" in mime_l:
        return ".pdf"
    if "html" in mime_l:
        return ".html"
    if "text" in mime_l:
        return ".txt"
    return ".bin"


def _pages_for_parquet(
    result: Dict[str, Any],
    *,
    output_root: Path,
    include_html: bool,
) -> List[Dict[str, Any]]:
    pages = list(((result.get("data") or {}).get("pages") or []))
    rows: List[Dict[str, Any]] = []
    documents_dir = output_root / "documents"
    for index, page in enumerate(pages):
        metadata = dict(page.get("metadata") or {})
        record = dict(metadata.get("cc_record") or {})
        body_base64 = page.get("body_base64")
        body_mime = page.get("body_mime") or metadata.get("http_mime")
        document_path = None
        if body_base64:
            import base64

            documents_dir.mkdir(parents=True, exist_ok=True)
            suffix = _extension_for_mime(str(body_mime or ""))
            document_path = documents_dir / f"{index:05d}{suffix}"
            document_bytes = base64.b64decode(str(body_base64))
            document_path.write_bytes(document_bytes)
            document_cid = cid_for_bytes(document_bytes)
        else:
            document_cid = None
        text = str(page.get("text") or "")
        text_cid = cid_for_bytes(text.encode("utf-8")) if text else None
        record_payload = {
            "url": page.get("url"),
            "text_cid": text_cid,
            "document_cid": document_cid,
            "cc_record": record,
        }
        row = {
            "ipfs_cid": cid_for_obj(record_payload),
            "source_cid": document_cid or text_cid,
            "text_cid": text_cid,
            "document_cid": document_cid,
            "url": page.get("url"),
            "title": page.get("title"),
            "text": text,
            "links_json": json.dumps(page.get("links") or [], ensure_ascii=False),
            "document_path": str(document_path) if document_path else None,
            "body_mime": body_mime,
            "domain": record.get("domain"),
            "place_name": record.get("place_name"),
            "state_code": record.get("state_code"),
            "gnis": record.get("gnis"),
            "collection": record.get("collection"),
            "timestamp": record.get("timestamp"),
            "mime": record.get("mime"),
            "status": record.get("status"),
            "warc_filename": record.get("warc_filename"),
            "warc_offset": record.get("warc_offset"),
            "warc_length": record.get("warc_length"),
            "cc_source": metadata.get("cc_source"),
            "http_status": metadata.get("http_status"),
            "http_mime": metadata.get("http_mime"),
            "http_charset": metadata.get("http_charset"),
            "ok": metadata.get("ok"),
            "error": metadata.get("error"),
        }
        if include_html:
            row["html"] = page.get("html")
        rows.append(row)
    return rows


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Filter the local/HF municipal Common Crawl index, fetch matching WARC "
            "records, parse archived HTML, and write extracted municipal-law pages."
        )
    )
    parser.add_argument("--jurisdiction", default="Portland, OR", help='Human label such as "Portland, OR".')
    parser.add_argument("--url", default="https://www.portland.gov/code", help="Seed/current municipal code URL.")
    parser.add_argument("--place-name", default="", help="Optional place override, e.g. Portland.")
    parser.add_argument("--state-code", default="", help="Optional two-letter state override, e.g. OR.")
    parser.add_argument("--gnis", default="", help="Optional GNIS place id.")
    parser.add_argument("--url-terms", default="code,ordinance,charter,municipal", help="Comma-separated URL terms.")
    parser.add_argument("--mime-terms", default="", help="Optional comma-separated MIME filters, e.g. pdf,text/html.")
    parser.add_argument("--max-results", type=int, default=100, help="Maximum index pointers to consider.")
    parser.add_argument("--max-pages", type=int, default=25, help="Maximum WARC pages to fetch/extract.")
    parser.add_argument("--max-body-bytes", type=int, default=2_000_000, help="Maximum extracted HTTP body bytes per WARC record.")
    parser.add_argument("--index-root", default="data/common_crawl_indexes", help="Local Common Crawl index root.")
    parser.add_argument("--download-index", action="store_true", help="Download the municipal index parquet first.")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID, help="HF dataset repo containing the municipal index.")
    parser.add_argument("--index-file", default=DEFAULT_INDEX_FILE, help="Path to the parquet file inside the HF repo.")
    parser.add_argument("--output-root", default="workspace/municipal_common_crawl_laws", help="Output directory.")
    parser.add_argument("--include-html", action="store_true", help="Include raw HTML in the pages parquet.")
    parser.add_argument("--list-candidates", action="store_true", help="Only export scored pointer candidates; do not fetch WARC records.")
    parser.add_argument("--candidate-limit", type=int, default=500, help="Maximum candidates exported by --list-candidates.")
    parser.add_argument("--json", action="store_true", help="Print the full run manifest as JSON.")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> Dict[str, Any]:
    index_root = Path(args.index_root).expanduser().resolve()
    output_root = Path(args.output_root).expanduser().resolve()
    downloaded_index = None
    if args.download_index:
        downloaded_index = _download_index(
            repo_id=str(args.repo_id),
            index_file=str(args.index_file),
            index_root=index_root,
        )

    if args.list_candidates:
        candidates = _list_candidates(
            index_root=index_root,
            output_root=output_root,
            place_name=str(args.place_name or "").strip() or str(args.jurisdiction).split(",", 1)[0].strip(),
            state_code=str(args.state_code or "").strip().upper(),
            gnis=str(args.gnis or "").strip(),
            url_terms=_parse_csv(args.url_terms),
            mime_terms=_parse_csv(args.mime_terms),
            limit=int(args.candidate_limit),
        )
        manifest = {
            "success": True,
            "message": f"Exported {candidates['candidate_count']} Common Crawl municipal pointer candidate(s)",
            "jurisdiction": args.jurisdiction,
            "index_root": str(index_root),
            "downloaded_index": str(downloaded_index) if downloaded_index else None,
            "output_root": str(output_root),
            **candidates,
        }
        _write_json(output_root / "manifest.json", manifest)
        return manifest

    loader = CommonCrawlIndexLoader(local_base_dir=index_root, use_hf_fallback=not bool(args.download_index))
    scraper = MunicipalScraperFallbacks()
    result = await scraper._scrape_common_crawl(
        str(args.url),
        str(args.jurisdiction),
        index_loader=loader,
        place_name=str(args.place_name or "").strip() or None,
        state_code=str(args.state_code or "").strip().upper() or None,
        gnis=str(args.gnis or "").strip() or None,
        url_terms=_parse_csv(args.url_terms),
        mime_terms=_parse_csv(args.mime_terms),
        max_results=int(args.max_results),
        max_pages=int(args.max_pages),
        common_crawl_fetch_max_bytes=int(args.max_body_bytes),
    )

    pages = _pages_for_parquet(result, output_root=output_root, include_html=bool(args.include_html))
    page_parquet = _write_records_parquet(output_root / "pages.parquet", pages)
    records = list(((result.get("data") or {}).get("pages") or []))
    pointer_rows = [dict(((page.get("metadata") or {}).get("cc_record") or {})) for page in records]
    pointer_parquet = _write_records_parquet(output_root / "pointers.parquet", pointer_rows)

    manifest = {
        "success": bool(result.get("success")),
        "message": result.get("message"),
        "jurisdiction": args.jurisdiction,
        "url": args.url,
        "index_root": str(index_root),
        "downloaded_index": str(downloaded_index) if downloaded_index else None,
        "output_root": str(output_root),
        "pages_parquet": str(page_parquet) if page_parquet else None,
        "pointers_parquet": str(pointer_parquet) if pointer_parquet else None,
        "pages_extracted": len(pages),
        "metadata": result.get("metadata") or {},
    }
    _write_json(output_root / "manifest.json", manifest)
    if not result.get("success"):
        _write_json(output_root / "failure.json", result)
    return manifest


def main() -> int:
    import anyio

    args = _parse_args()
    manifest = anyio.run(_run, args)
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"Success: {manifest['success']}")
        print(f"Message: {manifest['message']}")
        print(f"Pages extracted: {manifest['pages_extracted']}")
        print(f"Output root: {manifest['output_root']}")
        if manifest.get("pages_parquet"):
            print(f"Pages parquet: {manifest['pages_parquet']}")
        if manifest.get("pointers_parquet"):
            print(f"Pointers parquet: {manifest['pointers_parquet']}")
    return 0 if manifest["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

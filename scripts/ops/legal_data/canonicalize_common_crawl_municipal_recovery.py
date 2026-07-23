#!/usr/bin/env python3
"""Convert recovered Common Crawl municipal pages into canonical CID parquet."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (  # noqa: E402
    build_canonical_corpus_artifacts,
    canonical_corpus_artifact_build_result_to_dict,
)
from ipfs_datasets_py.utils.cid_utils import cid_for_obj  # noqa: E402


_WS_RE = re.compile(r"\s+")


def _first_text(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = row.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _compact(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()


def _source_id_from_url(url: str) -> str:
    match = re.search(r"/code/(\d+)/([A-Za-z0-9]+)/([A-Za-z0-9]+)", url, flags=re.IGNORECASE)
    if match:
        return f"portland-code-{match.group(1)}-{match.group(2)}-{match.group(3)}"
    match = re.search(r"/code/(\d+)/([A-Za-z0-9]+)", url, flags=re.IGNORECASE)
    if match:
        return f"portland-code-{match.group(1)}-{match.group(2)}"
    match = re.search(r"/citycode/article/([^/?#]+)", url, flags=re.IGNORECASE)
    if match:
        return f"portland-citycode-article-{match.group(1)}"
    match = re.search(r"/record/([^/?#]+)/file/document", url, flags=re.IGNORECASE)
    if match:
        return f"portland-efiles-record-{match.group(1)}"
    return url.rstrip("/") or "common-crawl-municipal-recovery"


def _name_from_row(row: Mapping[str, Any]) -> str:
    title = _compact(row.get("title"))
    if title:
        return title
    text = _compact(row.get("text"))
    if not text:
        return _source_id_from_url(str(row.get("url") or ""))
    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]
    return first_sentence[:180].strip()


def _identifier_from_row(row: Mapping[str, Any], source_id: str) -> str:
    url = str(row.get("url") or "")
    title_number = re.match(r"^\s*(\d+(?:\.\d+)+)\b", _compact(row.get("title")))
    match = re.search(r"/code/(\d+)/([A-Za-z0-9]+)/([A-Za-z0-9]+)", url, flags=re.IGNORECASE)
    if match:
        if title_number:
            return f"Portland City Code {title_number.group(1)}"
        return f"Portland City Code {match.group(1)}.{match.group(2)}.{match.group(3)}"
    match = re.search(r"/code/(\d+)/([A-Za-z0-9]+)", url, flags=re.IGNORECASE)
    if match:
        return f"Portland City Code Chapter {match.group(1)}.{match.group(2)}"
    match = re.search(r"/citycode/article/([^/?#]+)", url, flags=re.IGNORECASE)
    if match:
        return f"Portland City Code article {match.group(1)}"
    match = re.search(r"/record/([^/?#]+)/file/document", url, flags=re.IGNORECASE)
    if match:
        return f"Portland eFiles record {match.group(1)}"
    return source_id


def _chapter_from_text(text: str) -> str:
    compact = _compact(text)
    if not compact:
        return ""
    patterns = [
        r"\b([A-Z]{2,}\s+\d+(?:\.\d+)?\s+[A-Z][A-Za-z0-9 ,&/\-]+)",
        r"\b(Title\s+\d+[A-Za-z0-9 .,&/\-]+)",
        r"\b(Chapter\s+\d+[A-Za-z0-9 .,&/\-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact)
        if match:
            return match.group(1)[:180].strip()
    return compact[:120].strip()


def _jsonld_for_row(row: Mapping[str, Any], canonical: Mapping[str, Any]) -> str:
    source_url = str(canonical.get("source_url") or "")
    state_code = str(canonical.get("state_code") or "")
    gnis = str(canonical.get("gnis") or "")
    payload: Dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "Legislation",
        "@id": f"ipfs://{canonical.get('ipfs_cid')}",
        "identifier": canonical.get("identifier"),
        "name": canonical.get("name"),
        "text": canonical.get("text"),
        "citation": canonical.get("bluebook_citation"),
        "legislationJurisdiction": state_code,
        "legislationType": "municipal_code",
        "url": source_url,
        "sameAs": source_url,
        "encoding": {
            "@type": "MediaObject",
            "contentUrl": source_url,
            "encodingFormat": row.get("body_mime") or row.get("mime"),
            "contentSize": row.get("warc_length"),
            "identifier": row.get("document_cid") or row.get("source_cid"),
        },
        "spatialCoverage": {
            "@type": "Place",
            "name": row.get("place_name"),
            "identifier": gnis,
            "addressRegion": state_code,
        },
        "isBasedOn": {
            "@type": "WebPage",
            "url": source_url,
            "archivedAt": f"https://data.commoncrawl.org/{row.get('warc_filename')}",
            "dateCreated": row.get("timestamp"),
        },
        "raw_source": {
            "common_crawl": {
                "domain": row.get("domain"),
                "collection": row.get("collection"),
                "timestamp": row.get("timestamp"),
                "mime": row.get("mime"),
                "status": row.get("status"),
                "warc_filename": row.get("warc_filename"),
                "warc_offset": row.get("warc_offset"),
                "warc_length": row.get("warc_length"),
            }
        },
    }
    cleaned = {key: value for key, value in payload.items() if value not in (None, "", {}, [])}
    return json.dumps(cleaned, ensure_ascii=False, sort_keys=True)


def _canonical_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    text = _compact(row.get("text"))
    source_url = _first_text(row, ("url", "source_url"))
    source_id = _source_id_from_url(source_url)
    identifier = _identifier_from_row(row, source_id)
    name = _name_from_row(row)
    state_code = _first_text(row, ("state_code",)).upper()
    source_cid = _first_text(row, ("source_cid", "document_cid", "text_cid"))
    ipfs_cid = _first_text(row, ("ipfs_cid",))
    canonical_without_jsonld: Dict[str, Any] = {
        "state_code": state_code,
        "source_id": source_id,
        "source_cid": source_cid,
        "identifier": identifier,
        "name": name,
        "text": text,
        "source_url": source_url,
        "official_cite": identifier,
        "bluebook_citation": identifier,
        "html_title": _compact(row.get("title")),
        "title": name,
        "chapter": _chapter_from_text(text),
        "gnis": _first_text(row, ("gnis",)),
        "doc_id": source_id,
        "doc_order": _first_text(row, ("timestamp",)),
        "document_cid": _first_text(row, ("document_cid",)),
        "text_cid": _first_text(row, ("text_cid",)),
        "document_path": _first_text(row, ("document_path",)),
        "body_mime": _first_text(row, ("body_mime", "mime")),
        "common_crawl_collection": _first_text(row, ("collection",)),
        "common_crawl_timestamp": _first_text(row, ("timestamp",)),
        "warc_filename": _first_text(row, ("warc_filename",)),
        "warc_offset": _first_text(row, ("warc_offset",)),
        "warc_length": _first_text(row, ("warc_length",)),
    }
    if not ipfs_cid:
        ipfs_cid = cid_for_obj(canonical_without_jsonld)
    canonical = {"ipfs_cid": ipfs_cid, **canonical_without_jsonld}
    canonical["jsonld"] = _jsonld_for_row(row, canonical)
    return canonical


def _dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in rows:
        key = str(row.get("ipfs_cid") or row.get("source_url") or "")
        if not key:
            continue
        if key not in seen:
            order.append(key)
        if len(str(row.get("text") or "")) >= len(str(seen.get(key, {}).get("text") or "")):
            seen[key] = row
    return [seen[key] for key in order]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Canonicalize Common Crawl municipal recovery parquet.")
    parser.add_argument("--input", required=True, help="Recovered pages.parquet from retrieve_municipal_laws_from_common_crawl.py.")
    parser.add_argument("--output-root", required=True, help="Output directory for canonical parquet and artifacts.")
    parser.add_argument("--state-code", default="OR", help="State code used for artifact naming/filtering.")
    parser.add_argument("--build-artifacts", action="store_true", help="Build CID, BM25, KG, embeddings, and FAISS artifacts.")
    parser.add_argument("--provider", default="", help="Embedding provider override.")
    parser.add_argument("--model", default="thenlper/gte-small", help="Embedding model name.")
    parser.add_argument("--device", default="", help="Embedding device override, e.g. cuda.")
    parser.add_argument("--no-faiss", action="store_true", help="Skip FAISS index build.")
    parser.add_argument("--include-empty-text", action="store_true", help="Keep document-only rows even when text extraction failed.")
    parser.add_argument("--json", action="store_true", help="Print JSON manifest.")
    return parser.parse_args()


def main() -> int:
    import pyarrow as pa
    import pyarrow.parquet as pq

    args = _parse_args()
    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    input_path = Path(args.input).expanduser().resolve()
    source_rows = pq.read_table(input_path).to_pylist()
    canonical_rows = _dedupe(
        [
            _canonical_row(row)
            for row in source_rows
            if bool(args.include_empty_text) or _compact(row.get("text"))
        ]
    )
    canonical_path = output_root / f"STATE-{str(args.state_code or '').upper()}.parquet"
    pq.write_table(pa.Table.from_pylist(canonical_rows), canonical_path)

    artifact = None
    if args.build_artifacts:
        artifact = canonical_corpus_artifact_build_result_to_dict(
            build_canonical_corpus_artifacts(
                "municipal_laws",
                canonical_parquet_path=str(canonical_path),
                state_code=str(args.state_code or "").upper() or None,
                output_root=str(output_root),
                provider=str(args.provider or "").strip() or None,
                model_name=str(args.model or "").strip() or "thenlper/gte-small",
                device=str(args.device or "").strip() or None,
                build_faiss=not bool(args.no_faiss),
                publish_to_hf=False,
                include_canonical_parquet=False,
            )
        )

    manifest = {
        "input": str(input_path),
        "output_root": str(output_root),
        "canonical_parquet": str(canonical_path),
        "source_row_count": len(source_rows),
        "canonical_row_count": len(canonical_rows),
        "artifact": artifact,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    else:
        print(f"Canonical parquet: {canonical_path}")
        print(f"Rows: {len(canonical_rows)} / {len(source_rows)}")
        if artifact:
            print(f"Artifacts output: {output_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the CID-addressed Hugging Face package for Netherlands laws."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.utils.cid_utils import cid_for_bytes, cid_for_obj

from .common import read_jsonl, sha256, write_jsonl, write_parquet
from ..paths import HF_DATA_DIR, RAW_DATA_DIR


RAW_DIR = RAW_DATA_DIR / "nl_test_output_docs"
OUT_DIR = HF_DATA_DIR / "ipfs_netherlands_laws"


def file_cid(path: Path) -> str:
    return cid_for_bytes(path.read_bytes())


def law_payload(row: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "record_type",
        "jurisdiction",
        "jurisdiction_name",
        "country",
        "language",
        "identifier",
        "law_identifier",
        "official_identifier",
        "law_version_identifier",
        "version_specific_identifier",
        "title",
        "canonical_title",
        "aliases",
        "text",
        "source_url",
        "canonical_law_url",
        "canonical_document_url",
        "versioned_law_url",
        "information_url",
        "document_type",
        "citation",
        "official_metadata",
        "effective_date",
        "version_start_date",
        "version_end_date",
        "is_current",
        "publication_date",
        "last_modified_date",
        "historical_versions",
        "article_count",
        "chapter_count",
        "scraped_at",
        "metadata",
    ]
    return {key: row.get(key) for key in keep}


def article_payload(row: dict[str, Any]) -> dict[str, Any]:
    keep = [
        "record_type",
        "law_identifier",
        "law_version_identifier",
        "version_specific_identifier",
        "document_identifier",
        "document_version_identifier",
        "article_identifier",
        "article_number",
        "article_heading",
        "citation",
        "document_citation",
        "hierarchy_path",
        "hierarchy_path_text",
        "hierarchy_labels",
        "book_label",
        "title_label",
        "chapter_label",
        "division_label",
        "paragraph_label",
        "article_label",
        "book_number",
        "title_number",
        "chapter_number",
        "division_number",
        "paragraph_number",
        "text",
        "effective_date",
        "version_start_date",
        "version_end_date",
        "is_current",
        "scraped_at",
    ]
    return {key: row.get(key) for key in keep}


def build_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_laws = read_jsonl(RAW_DIR / "netherlands_laws_index_latest.jsonl")
    raw_articles = read_jsonl(RAW_DIR / "netherlands_laws_articles_index_latest.jsonl")

    laws: list[dict[str, Any]] = []
    law_cid_by_id: dict[str, str] = {}
    cid_index: list[dict[str, Any]] = []
    for raw_row in raw_laws:
        payload = law_payload(raw_row)
        cid = cid_for_obj(payload)
        payload["cid"] = cid
        payload["content_address"] = f"ipfs://{cid}"
        laws.append(payload)
        law_id = str(payload.get("law_identifier") or payload.get("identifier") or "")
        law_cid_by_id[law_id] = cid
        cid_index.append(
            {
                "record_type": "law",
                "law_identifier": law_id,
                "article_identifier": None,
                "cid": cid,
                "content_address": f"ipfs://{cid}",
                "source_url": payload.get("source_url"),
                "title": payload.get("title"),
            }
        )

    articles: list[dict[str, Any]] = []
    for raw_row in raw_articles:
        payload = article_payload(raw_row)
        payload["law_cid"] = law_cid_by_id.get(str(payload.get("law_identifier") or ""), "")
        cid = cid_for_obj(payload)
        payload["cid"] = cid
        payload["content_address"] = f"ipfs://{cid}"
        articles.append(payload)
        cid_index.append(
            {
                "record_type": "article",
                "law_identifier": payload.get("law_identifier"),
                "article_identifier": payload.get("article_identifier"),
                "cid": cid,
                "content_address": f"ipfs://{cid}",
                "source_url": None,
                "title": payload.get("citation"),
            }
        )
    return laws, articles, cid_index


def write_readme() -> None:
    readme = """---
pretty_name: IPFS Netherlands Laws
language:
- nl
configs:
- config_name: laws
  data_files:
  - split: train
    path: parquet/laws/*.parquet
- config_name: articles
  data_files:
  - split: train
    path: parquet/articles/*.parquet
- config_name: cid_index
  data_files:
  - split: train
    path: parquet/cid_index/*.parquet
---
"""
    (OUT_DIR / "README.md").write_text(readme, encoding="utf-8")


def write_gitattributes() -> None:
    (OUT_DIR / ".gitattributes").write_text(
        "data/**/*.jsonl filter=lfs diff=lfs merge=lfs -text\n"
        "data/**/*.json filter=lfs diff=lfs merge=lfs -text\n"
        "parquet/**/*.parquet filter=lfs diff=lfs merge=lfs -text\n",
        encoding="utf-8",
    )


def build_manifest(laws: list[dict[str, Any]], articles: list[dict[str, Any]], cid_index: list[dict[str, Any]]) -> None:
    manifest: dict[str, Any] = {
        "dataset_name": "ipfs_netherlands_laws",
        "snapshot_date": "2026-04-11",
        "repo_target": "justicedao/ipfs_netherlands_laws",
        "jurisdiction": "Netherlands",
        "language": "nl",
        "cid_format": {"version": 1, "codec": "raw", "multihash": "sha2-256", "base": "base32"},
        "records": {"laws": len(laws), "articles": len(articles), "cid_index": len(cid_index)},
        "files": {},
    }
    for rel in [
        "data/laws/ipfs_netherlands_laws.jsonl",
        "data/articles/ipfs_netherlands_laws_articles.jsonl",
        "data/cid_index/ipfs_netherlands_laws_cid_index.jsonl",
        "data/metadata/netherlands_laws_run_metadata_latest.json",
        "parquet/laws/train-00000-of-00001.parquet",
        "parquet/articles/train-00000-of-00001.parquet",
        "parquet/cid_index/train-00000-of-00001.parquet",
    ]:
        path = OUT_DIR / rel
        info: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256(path), "file_cid": file_cid(path)}
        if rel.startswith("data/laws") or rel.startswith("parquet/laws"):
            info["records"] = len(laws)
        elif rel.startswith("data/articles") or rel.startswith("parquet/articles"):
            info["records"] = len(articles)
        elif rel.startswith("data/cid_index") or rel.startswith("parquet/cid_index"):
            info["records"] = len(cid_index)
        manifest["files"][rel] = info
    (OUT_DIR / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    laws, articles, cid_index = build_rows()
    run_metadata = json.loads((RAW_DIR / "netherlands_laws_run_metadata_latest.json").read_text(encoding="utf-8"))

    for rel in [
        "data/laws",
        "data/articles",
        "data/cid_index",
        "data/metadata",
        "parquet/laws",
        "parquet/articles",
        "parquet/cid_index",
    ]:
        (OUT_DIR / rel).mkdir(parents=True, exist_ok=True)

    write_jsonl(OUT_DIR / "data/laws/ipfs_netherlands_laws.jsonl", laws)
    write_jsonl(OUT_DIR / "data/articles/ipfs_netherlands_laws_articles.jsonl", articles)
    write_jsonl(OUT_DIR / "data/cid_index/ipfs_netherlands_laws_cid_index.jsonl", cid_index)
    (OUT_DIR / "data/metadata/netherlands_laws_run_metadata_latest.json").write_text(
        json.dumps(run_metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    write_parquet(OUT_DIR / "parquet/laws/train-00000-of-00001.parquet", laws)
    write_parquet(OUT_DIR / "parquet/articles/train-00000-of-00001.parquet", articles)
    write_parquet(OUT_DIR / "parquet/cid_index/train-00000-of-00001.parquet", cid_index)

    write_readme()
    write_gitattributes()
    build_manifest(laws, articles, cid_index)
    print(json.dumps({"laws": len(laws), "articles": len(articles), "cid_index": len(cid_index)}, indent=2))


if __name__ == "__main__":
    main()

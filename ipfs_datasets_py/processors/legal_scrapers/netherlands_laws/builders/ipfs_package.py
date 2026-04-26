"""Build the CID-addressed Hugging Face package for Netherlands laws."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.utils.cid_utils import cid_for_obj

from .common import file_manifest_entry, read_jsonl, write_json, write_jsonl, write_parquet
from ..paths import (
    DEFAULT_HF_REPO_IDS,
    HF_DATA_DIR,
    IPFS_DATASET_NAME,
    PACKAGE_RAW_OUTPUT_DIR,
)


DEFAULT_REPO_ID = DEFAULT_HF_REPO_IDS["base"]
DEFAULT_RAW_DIR = PACKAGE_RAW_OUTPUT_DIR
DEFAULT_OUT_DIR = HF_DATA_DIR / IPFS_DATASET_NAME


def coverage_note(run_metadata: dict[str, Any], record_counts: dict[str, int]) -> str:
    max_documents = run_metadata.get("max_documents")
    parsed = run_metadata.get("output_records_count") or run_metadata.get("documents_parsed") or record_counts.get("laws", 0)
    discovered = run_metadata.get("total_unique_laws_discovered") or run_metadata.get("unique_laws_discovered") or "unknown"
    failed = run_metadata.get("documents_failed", "unknown")
    if max_documents:
        return (
            f"This is a capped Netherlands scrape, not the full Dutch corpus. "
            f"The scrape used max_documents={max_documents}, parsed {parsed} law record(s), "
            f"and discovered {discovered} unique official BWBR law document(s) before applying the cap. "
            f"Documents failed: {failed}."
        )
    return (
        "This is an uncapped discovered-corpus Netherlands scrape from the configured official discovery sources, "
        "but it should not be described as the full Dutch corpus unless the run metadata confirms discovery covered "
        f"the complete intended BWBR population. Parsed law records: {parsed}; discovered: {discovered}; "
        f"documents failed: {failed}."
    )


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
        "article_rows_count",
        "article_extraction_status",
        "article_extraction_note",
        "article_extraction_diagnostics",
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


def build_rows(raw_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    raw_laws = read_jsonl(raw_dir / "netherlands_laws_index_latest.jsonl")
    raw_articles = read_jsonl(raw_dir / "netherlands_laws_articles_index_latest.jsonl")

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


def write_readme(
    out_dir: Path,
    repo_id: str = DEFAULT_REPO_ID,
    *,
    run_metadata: dict[str, Any] | None = None,
    record_counts: dict[str, int] | None = None,
) -> None:
    run_metadata = run_metadata or {}
    record_counts = record_counts or {}
    scrape_command = run_metadata.get("scrape_command") or (
        "python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape "
        "--use_default_seeds true --max_seed_pages <pages> --crawl_depth 1 "
        "--max_documents <cap> --rate_limit_delay <delay> --resume"
    )
    coverage = coverage_note(run_metadata, record_counts)
    readme = f"""---
pretty_name: IPFS Netherlands Laws
language:
- nl
task_categories:
- text-retrieval
- question-answering
- text-classification
tags:
- law
- legal
- legislation
- netherlands
- dutch
- ipfs
- cid
license: other
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

# IPFS Netherlands Laws

Hugging Face target: `{repo_id}`.

This dataset packages Netherlands law records with deterministic IPFS Content IDs. Each row includes a `cid` and `content_address`; article rows also include the parent `law_cid`.

{coverage}

This refresh includes parser coverage improvements for older/French heading styles such as `Article I.er`,
plus run metadata diagnostics that distinguish article-producing laws, parser-missing article cases,
and genuinely unnumbered/non-article documents.

Scrape command:

```bash
{scrape_command}
```

Current package counts:

- Laws: {record_counts.get("laws", 0)}
- Articles: {record_counts.get("articles", 0)}
- CID index rows: {record_counts.get("cid_index", 0)}
- Unique laws discovered before any document cap: {run_metadata.get("unique_laws_discovered", "unknown")}
- Documents failed: {run_metadata.get("documents_failed", "unknown")}
- Article-producing laws: {run_metadata.get("article_producing_laws_count", "unknown")}
- Non-article-producing laws: {run_metadata.get("non_article_producing_laws_count", "unknown")}

Remaining limitations before a full corpus release: increase/remove `max_documents`, validate shard/streaming behavior on larger runs, and spot-check laws that expose no article-level rows.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def write_gitattributes(out_dir: Path) -> None:
    (out_dir / ".gitattributes").write_text(
        "data/**/*.jsonl filter=lfs diff=lfs merge=lfs -text\n"
        "data/**/*.json filter=lfs diff=lfs merge=lfs -text\n"
        "parquet/**/*.parquet filter=lfs diff=lfs merge=lfs -text\n",
        encoding="utf-8",
    )


def build_manifest(
    laws: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    cid_index: list[dict[str, Any]],
    out_dir: Path,
    repo_id: str = DEFAULT_REPO_ID,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "dataset_name": IPFS_DATASET_NAME,
        "snapshot_date": "2026-04-11",
        "repo_target": repo_id,
        "upload_target": repo_id,
        "jurisdiction": "Netherlands",
        "language": "nl",
        "cid_format": {"version": 1, "codec": "raw", "multihash": "sha2-256", "base": "base32"},
        "records": {"laws": len(laws), "articles": len(articles), "cid_index": len(cid_index)},
        "files": {},
    }
    files: list[tuple[str, int | None]] = [
        ("data/laws/ipfs_netherlands_laws.jsonl", len(laws)),
        ("data/articles/ipfs_netherlands_laws_articles.jsonl", len(articles)),
        ("data/cid_index/ipfs_netherlands_laws_cid_index.jsonl", len(cid_index)),
        ("data/metadata/netherlands_laws_run_metadata_latest.json", None),
        ("parquet/laws/train-00000-of-00001.parquet", len(laws)),
        ("parquet/articles/train-00000-of-00001.parquet", len(articles)),
        ("parquet/cid_index/train-00000-of-00001.parquet", len(cid_index)),
    ]
    for rel, records in files:
        manifest["files"][rel] = file_manifest_entry(out_dir / rel, records)
    write_json(out_dir / "dataset_manifest.json", manifest)
    return manifest


def build_ipfs_cid_package(
    raw_dir: Path | None = None,
    out_dir: Path | None = None,
    repo_id: str = DEFAULT_REPO_ID,
) -> Path:
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    out_dir = out_dir or DEFAULT_OUT_DIR
    laws, articles, cid_index = build_rows(raw_dir)
    run_metadata = json.loads((raw_dir / "netherlands_laws_run_metadata_latest.json").read_text(encoding="utf-8"))

    for rel in [
        "data/laws",
        "data/articles",
        "data/cid_index",
        "data/metadata",
        "parquet/laws",
        "parquet/articles",
        "parquet/cid_index",
    ]:
        (out_dir / rel).mkdir(parents=True, exist_ok=True)

    write_jsonl(out_dir / "data/laws/ipfs_netherlands_laws.jsonl", laws)
    write_jsonl(out_dir / "data/articles/ipfs_netherlands_laws_articles.jsonl", articles)
    write_jsonl(out_dir / "data/cid_index/ipfs_netherlands_laws_cid_index.jsonl", cid_index)
    write_json(out_dir / "data/metadata/netherlands_laws_run_metadata_latest.json", run_metadata)
    write_parquet(out_dir / "parquet/laws/train-00000-of-00001.parquet", laws)
    write_parquet(out_dir / "parquet/articles/train-00000-of-00001.parquet", articles)
    write_parquet(out_dir / "parquet/cid_index/train-00000-of-00001.parquet", cid_index)

    write_readme(
        out_dir,
        repo_id,
        run_metadata=run_metadata,
        record_counts={"laws": len(laws), "articles": len(articles), "cid_index": len(cid_index)},
    )
    write_gitattributes(out_dir)
    build_manifest(laws, articles, cid_index, out_dir, repo_id)
    return out_dir


def main() -> None:
    out_dir = build_ipfs_cid_package()
    manifest = json.loads((out_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({"out_dir": str(out_dir), "records": manifest["records"]}, indent=2))


if __name__ == "__main__":
    main()

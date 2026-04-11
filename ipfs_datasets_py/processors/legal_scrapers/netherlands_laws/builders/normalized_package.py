"""Build a normalized Hugging Face package for Netherlands laws."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .common import read_jsonl, sha256, write_jsonl, write_parquet
from ..paths import HF_DATA_DIR, RAW_DATA_DIR


RAW_DIR = RAW_DATA_DIR / "nl_test_output_docs"
OUT_DIR = HF_DATA_DIR / "netherlands-laws-nl-normalized"


def measured_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def top_field_report(rows: list[dict[str, Any]], limit: int = 15) -> list[dict[str, Any]]:
    field_sizes: Counter[str] = Counter()
    nonnull: Counter[str] = Counter()
    for row in rows:
        for key, value in row.items():
            if value not in (None, "", [], {}):
                field_sizes[key] += measured_size(value)
                nonnull[key] += 1
    total = sum(field_sizes.values())
    report: list[dict[str, Any]] = []
    for key, size in sorted(field_sizes.items(), key=lambda kv: kv[1], reverse=True)[:limit]:
        report.append(
            {
                "field": key,
                "total_bytes": size,
                "pct_of_measured_fields": round((100 * size / total), 2) if total else 0.0,
                "nonnull_rows": nonnull[key],
                "avg_bytes_when_present": round(size / nonnull[key], 1) if nonnull[key] else 0.0,
            }
        )
    return report


def normalize_laws(raw_laws: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    return [{key: row.get(key) for key in keep} for row in raw_laws]


def normalize_articles(raw_articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    rows: list[dict[str, Any]] = []
    for row in raw_articles:
        out = {key: row.get(key) for key in keep}
        out["law_row_id"] = row.get("law_identifier")
        rows.append(out)
    return rows


def write_dataset_card() -> None:
    readme = """---
pretty_name: Netherlands Laws (Dutch, Normalized)
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
---

# Netherlands Laws (Dutch, Normalized)

This package is a normalized version of the Netherlands laws scrape output.
"""
    (OUT_DIR / "README.md").write_text(readme, encoding="utf-8")


def write_gitattributes() -> None:
    text = """data/**/*.jsonl filter=lfs diff=lfs merge=lfs -text
data/**/*.json filter=lfs diff=lfs merge=lfs -text
parquet/**/*.parquet filter=lfs diff=lfs merge=lfs -text
analysis/**/*.json filter=lfs diff=lfs merge=lfs -text
"""
    (OUT_DIR / ".gitattributes").write_text(text, encoding="utf-8")


def write_upload_script() -> None:
    text = """#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <namespace/dataset-name>"
  exit 1
fi

REPO_ID="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat <<EOF
cd "$SCRIPT_DIR"
git init
git lfs install
git remote add origin "https://huggingface.co/datasets/$REPO_ID"
git add .
git commit -m "Add normalized Netherlands laws dataset"
git branch -M main
git push origin main
EOF
"""
    path = OUT_DIR / "upload_to_hf.sh"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def main() -> None:
    raw_laws = read_jsonl(RAW_DIR / "netherlands_laws_index_latest.jsonl")
    raw_articles = read_jsonl(RAW_DIR / "netherlands_laws_articles_index_latest.jsonl")
    raw_search = read_jsonl(RAW_DIR / "netherlands_laws_search_index_latest.jsonl")
    run_metadata = json.loads((RAW_DIR / "netherlands_laws_run_metadata_latest.json").read_text(encoding="utf-8"))

    laws = normalize_laws(raw_laws)
    articles = normalize_articles(raw_articles)

    (OUT_DIR / "data" / "laws").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "data" / "articles").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "data" / "metadata").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "analysis").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "parquet" / "laws").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "parquet" / "articles").mkdir(parents=True, exist_ok=True)

    laws_jsonl = OUT_DIR / "data" / "laws" / "netherlands_laws_normalized.jsonl"
    articles_jsonl = OUT_DIR / "data" / "articles" / "netherlands_laws_articles_normalized.jsonl"

    write_jsonl(laws_jsonl, laws)
    write_jsonl(articles_jsonl, articles)
    write_parquet(OUT_DIR / "parquet" / "laws" / "train-00000-of-00001.parquet", laws)
    write_parquet(OUT_DIR / "parquet" / "articles" / "train-00000-of-00001.parquet", articles)

    raw_article_bytes = (RAW_DIR / "netherlands_laws_articles_index_latest.jsonl").stat().st_size
    normalized_article_bytes = articles_jsonl.stat().st_size
    report = {
        "raw": {
            "laws_rows": len(raw_laws),
            "articles_rows": len(raw_articles),
            "search_rows": len(raw_search),
            "article_jsonl_bytes": raw_article_bytes,
            "article_top_fields": top_field_report(raw_articles),
            "search_top_fields": top_field_report(raw_search),
        },
        "normalized": {
            "laws_rows": len(laws),
            "articles_rows": len(articles),
            "article_jsonl_bytes": normalized_article_bytes,
            "article_reduction_bytes": raw_article_bytes - normalized_article_bytes,
            "article_reduction_pct": round(100 * (raw_article_bytes - normalized_article_bytes) / raw_article_bytes, 2),
        },
        "scrape_trace": {
            "max_documents": run_metadata.get("max_documents"),
            "seed_url_count": run_metadata.get("seed_url_count"),
            "seed_pages_visited": run_metadata.get("seed_pages_visited"),
            "explicit_document_urls": run_metadata.get("explicit_document_urls"),
            "official_law_documents_accepted": run_metadata.get("official_law_documents_accepted"),
            "documents_parsed": run_metadata.get("documents_parsed"),
            "records_count": run_metadata.get("records_count"),
            "article_records_count": run_metadata.get("article_records_count"),
            "search_records_count": run_metadata.get("search_records_count"),
        },
    }

    (OUT_DIR / "analysis" / "size_inflation_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "data" / "metadata" / "netherlands_laws_run_metadata_latest.json").write_text(
        json.dumps(run_metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest = {
        "dataset_name": "netherlands-laws-nl-normalized",
        "snapshot_date": "2026-04-11",
        "package_variant": "normalized",
        "source_directory": str(RAW_DIR),
        "source_url": "https://wetten.overheid.nl/",
        "language": "nl",
        "jurisdiction": "Netherlands",
        "join_key": {"articles": "law_identifier", "laws": "law_identifier"},
        "notes": [
            "Law-level metadata is stored in the laws table.",
            "Repeated law-level fields were removed from article rows.",
            "This package was derived from a scrape run capped at max_documents=2.",
        ],
        "files": {},
    }
    for rel in [
        "data/laws/netherlands_laws_normalized.jsonl",
        "data/articles/netherlands_laws_articles_normalized.jsonl",
        "data/metadata/netherlands_laws_run_metadata_latest.json",
        "analysis/size_inflation_report.json",
        "parquet/laws/train-00000-of-00001.parquet",
        "parquet/articles/train-00000-of-00001.parquet",
    ]:
        path = OUT_DIR / rel
        info: dict[str, Any] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
        if rel.startswith("data/laws") or rel.startswith("parquet/laws"):
            info["records"] = len(laws)
        elif rel.startswith("data/articles") or rel.startswith("parquet/articles"):
            info["records"] = len(articles)
        manifest["files"][rel] = info
    (OUT_DIR / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    write_dataset_card()
    write_gitattributes()
    write_upload_script()
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

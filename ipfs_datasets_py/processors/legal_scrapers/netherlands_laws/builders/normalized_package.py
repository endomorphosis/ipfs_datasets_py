"""Build a normalized Hugging Face package for Netherlands laws."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .common import count_jsonl, file_manifest_entry, read_jsonl, write_json, write_jsonl, write_parquet
from ..paths import DEFAULT_HF_REPO_IDS, HF_DATA_DIR, NORMALIZED_DATASET_NAME, PACKAGE_RAW_OUTPUT_DIR


DEFAULT_REPO_ID = DEFAULT_HF_REPO_IDS["normalized"]
DEFAULT_RAW_DIR = PACKAGE_RAW_OUTPUT_DIR
DEFAULT_OUT_DIR = HF_DATA_DIR / NORMALIZED_DATASET_NAME


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


def write_dataset_card(
    out_dir: Path,
    repo_id: str = DEFAULT_REPO_ID,
    *,
    run_metadata: dict[str, Any] | None = None,
    record_counts: dict[str, int] | None = None,
) -> None:
    run_metadata = run_metadata or {}
    record_counts = record_counts or {}
    readme = f"""---
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

Hugging Face target: `{repo_id}`.

This package is a normalized version of the Netherlands laws scrape output.

This is a 100-law medium scrape from official Netherlands sources, not the full Netherlands corpus.

Scrape command:

```bash
python -m ipfs_datasets_py.processors.legal_scrapers.netherlands_laws scrape --use_default_seeds true --max_seed_pages 25 --crawl_depth 1 --max_documents 100 --rate_limit_delay 0.2 --skip_existing true
```

Current package counts:

- Laws: {record_counts.get("laws", 0)}
- Articles: {record_counts.get("articles", 0)}
- Search records in raw run: {run_metadata.get("search_records_count", "unknown")}
- Unique laws discovered before the 100-law cap: {run_metadata.get("unique_laws_discovered", "unknown")}
- Documents failed: {run_metadata.get("documents_failed", "unknown")}

Remaining limitations before a full corpus release: increase/remove `max_documents`, validate larger-run packaging/upload behavior, and spot-check laws that expose no article-level rows.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def write_gitattributes(out_dir: Path) -> None:
    text = """data/**/*.jsonl filter=lfs diff=lfs merge=lfs -text
data/**/*.json filter=lfs diff=lfs merge=lfs -text
parquet/**/*.parquet filter=lfs diff=lfs merge=lfs -text
analysis/**/*.json filter=lfs diff=lfs merge=lfs -text
"""
    (out_dir / ".gitattributes").write_text(text, encoding="utf-8")


def write_upload_script(out_dir: Path) -> None:
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
    path = out_dir / "upload_to_hf.sh"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def build_normalized_package(
    raw_dir: Path | None = None,
    out_dir: Path | None = None,
    repo_id: str = DEFAULT_REPO_ID,
) -> Path:
    raw_dir = raw_dir or DEFAULT_RAW_DIR
    out_dir = out_dir or DEFAULT_OUT_DIR
    raw_laws = read_jsonl(raw_dir / "netherlands_laws_index_latest.jsonl")
    raw_articles = read_jsonl(raw_dir / "netherlands_laws_articles_index_latest.jsonl")
    raw_search_rows = count_jsonl(raw_dir / "netherlands_laws_search_index_latest.jsonl")
    run_metadata = json.loads((raw_dir / "netherlands_laws_run_metadata_latest.json").read_text(encoding="utf-8"))

    laws = normalize_laws(raw_laws)
    articles = normalize_articles(raw_articles)

    (out_dir / "data" / "laws").mkdir(parents=True, exist_ok=True)
    (out_dir / "data" / "articles").mkdir(parents=True, exist_ok=True)
    (out_dir / "data" / "metadata").mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (out_dir / "parquet" / "laws").mkdir(parents=True, exist_ok=True)
    (out_dir / "parquet" / "articles").mkdir(parents=True, exist_ok=True)

    laws_jsonl = out_dir / "data" / "laws" / "netherlands_laws_normalized.jsonl"
    articles_jsonl = out_dir / "data" / "articles" / "netherlands_laws_articles_normalized.jsonl"

    write_jsonl(laws_jsonl, laws)
    write_jsonl(articles_jsonl, articles)
    write_parquet(out_dir / "parquet" / "laws" / "train-00000-of-00001.parquet", laws)
    write_parquet(out_dir / "parquet" / "articles" / "train-00000-of-00001.parquet", articles)

    raw_article_bytes = (raw_dir / "netherlands_laws_articles_index_latest.jsonl").stat().st_size
    normalized_article_bytes = articles_jsonl.stat().st_size
    report = {
        "raw": {
            "laws_rows": len(raw_laws),
            "articles_rows": len(raw_articles),
            "search_rows": raw_search_rows,
            "article_jsonl_bytes": raw_article_bytes,
            "article_top_fields": top_field_report(raw_articles),
        },
        "normalized": {
            "laws_rows": len(laws),
            "articles_rows": len(articles),
            "article_jsonl_bytes": normalized_article_bytes,
            "article_reduction_bytes": raw_article_bytes - normalized_article_bytes,
            "article_reduction_pct": round(100 * (raw_article_bytes - normalized_article_bytes) / raw_article_bytes, 2)
            if raw_article_bytes
            else 0.0,
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

    write_json(out_dir / "analysis" / "size_inflation_report.json", report)
    write_json(out_dir / "data" / "metadata" / "netherlands_laws_run_metadata_latest.json", run_metadata)

    manifest = {
        "dataset_name": NORMALIZED_DATASET_NAME,
        "snapshot_date": "2026-04-11",
        "package_variant": "normalized",
        "source_directory": str(raw_dir),
        "source_url": "https://wetten.overheid.nl/",
        "repo_target": repo_id,
        "upload_target": repo_id,
        "language": "nl",
        "jurisdiction": "Netherlands",
        "join_key": {"articles": "law_identifier", "laws": "law_identifier"},
        "records": {"laws": len(laws), "articles": len(articles)},
        "notes": [
            "Law-level metadata is stored in the laws table.",
            "Repeated law-level fields were removed from article rows.",
            f"This package was derived from a scrape run capped at max_documents={run_metadata.get('max_documents')}.",
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
        path = out_dir / rel
        records: int | None = None
        if rel.startswith("data/laws") or rel.startswith("parquet/laws"):
            records = len(laws)
        elif rel.startswith("data/articles") or rel.startswith("parquet/articles"):
            records = len(articles)
        manifest["files"][rel] = file_manifest_entry(path, records)
    write_json(out_dir / "dataset_manifest.json", manifest)

    write_dataset_card(
        out_dir,
        repo_id,
        run_metadata=run_metadata,
        record_counts={"laws": len(laws), "articles": len(articles)},
    )
    write_gitattributes(out_dir)
    write_upload_script(out_dir)
    return out_dir


def main() -> None:
    out_dir = build_normalized_package()
    report = json.loads((out_dir / "analysis" / "size_inflation_report.json").read_text(encoding="utf-8"))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

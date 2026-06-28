"""Build the unified WetWijzer Netherlands legal corpus bundle."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ipfs_datasets_py.utils.cid_utils import cid_for_obj

from .common import file_manifest_entry, write_json, write_jsonl, write_parquet
from ..paths import (
    BM25_INDEX_DATASET_NAME,
    DEFAULT_HF_REPO_IDS,
    DATASETS_DIR,
    HF_DATA_DIR,
    IPFS_DATASET_NAME,
    KNOWLEDGE_GRAPH_DATASET_NAME,
    OPERATIONS_DATA_DIR,
    UNIFIED_WETWIJZER_DATASET_NAME,
    VECTOR_INDEX_DATASET_NAME,
)


DEFAULT_REPO_ID = DEFAULT_HF_REPO_IDS["unified"]
DEFAULT_BASE_DIR = HF_DATA_DIR / IPFS_DATASET_NAME
DEFAULT_VECTOR_DIR = HF_DATA_DIR / VECTOR_INDEX_DATASET_NAME
DEFAULT_BM25_DIR = HF_DATA_DIR / BM25_INDEX_DATASET_NAME
DEFAULT_KG_DIR = HF_DATA_DIR / KNOWLEDGE_GRAPH_DATASET_NAME
DEFAULT_REPORTS_DIR = OPERATIONS_DATA_DIR
DEFAULT_OUT_DIR = HF_DATA_DIR / UNIFIED_WETWIJZER_DATASET_NAME
DATASET_VIEWER_ROW_GROUP_SIZE = 10_000

ARTICLE_REFERENCE_RE = re.compile(r"\b(?:Artikel|Article)\s+([0-9]+[a-zA-Z]?)\b")


def build_unified_wetwijzer_package(
    *,
    base_dir: Path | None = None,
    vector_dir: Path | None = None,
    bm25_dir: Path | None = None,
    kg_dir: Path | None = None,
    reports_dir: Path | None = None,
    out_dir: Path | None = None,
    repo_id: str = DEFAULT_REPO_ID,
    include_relationship_summaries: bool = True,
) -> Path:
    """Create a single HF-ready bundle from the existing quality-audited outputs."""

    base_dir = base_dir or DEFAULT_BASE_DIR
    vector_dir = vector_dir or DEFAULT_VECTOR_DIR
    bm25_dir = bm25_dir or DEFAULT_BM25_DIR
    kg_dir = kg_dir or DEFAULT_KG_DIR
    reports_dir = reports_dir or DEFAULT_REPORTS_DIR
    out_dir = out_dir or DEFAULT_OUT_DIR

    _reset_output_dir(out_dir)

    copied = _copy_package_layers(
        out_dir=out_dir,
        base_dir=base_dir,
        vector_dir=vector_dir,
        bm25_dir=bm25_dir,
        kg_dir=kg_dir,
        reports_dir=reports_dir,
    )
    if include_relationship_summaries:
        _write_logic_relationship_summaries(out_dir)

    _write_source_manifests(out_dir, base_dir, vector_dir, bm25_dir, kg_dir)
    manifest = _write_unified_manifest(out_dir, repo_id, copied)
    _write_readme(out_dir, repo_id, manifest)
    _write_gitattributes(out_dir)
    return out_dir


def _reset_output_dir(out_dir: Path) -> None:
    _ensure_safe_output_dir(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)


def _ensure_safe_output_dir(out_dir: Path) -> None:
    resolved = out_dir.resolve()
    safe_roots = [DATASETS_DIR.resolve(), Path(tempfile.gettempdir()).resolve()]
    if resolved in safe_roots or not any(resolved.is_relative_to(root) for root in safe_roots):
        roots = ", ".join(str(root) for root in safe_roots)
        raise ValueError(
            f"Refusing to reset unsafe unified package output directory: {resolved}. "
            f"Use a child directory under one of: {roots}"
        )


def _copy_package_layers(
    *,
    out_dir: Path,
    base_dir: Path,
    vector_dir: Path,
    bm25_dir: Path,
    kg_dir: Path,
    reports_dir: Path,
) -> dict[str, str]:
    copies = {
        "data/laws.parquet": base_dir / "parquet/laws/train-00000-of-00001.parquet",
        "data/articles.parquet": base_dir / "parquet/articles/train-00000-of-00001.parquet",
        "data/cid_index.parquet": base_dir / "parquet/cid_index/train-00000-of-00001.parquet",
        "indexes/vector/vector_mapping.parquet": vector_dir / "parquet/mapping/train-00000-of-00001.parquet",
        "indexes/vector/faiss.index": vector_dir / "artifacts/faiss.index",
        "indexes/vector/vectorizer.pkl": vector_dir / "artifacts/vectorizer.pkl",
        "indexes/vector/svd.pkl": vector_dir / "artifacts/svd.pkl",
        "indexes/vector/metadata.json": vector_dir / "artifacts/metadata.json",
        "indexes/bm25/bm25_documents.parquet": bm25_dir / "parquet/documents/train-00000-of-00001.parquet",
        "indexes/bm25/bm25_terms.parquet": bm25_dir / "parquet/terms/train-00000-of-00001.parquet",
        "indexes/bm25/metadata.json": bm25_dir / "artifacts/metadata.json",
        "graph/kg_nodes.parquet": kg_dir / "parquet/nodes/train-00000-of-00001.parquet",
        "graph/kg_edges.parquet": kg_dir / "parquet/edges/train-00000-of-00001.parquet",
        "graph/graph.jsonld": kg_dir / "data/graph/ipfs_netherlands_laws_kg.jsonld",
        "graph/metadata.json": kg_dir / "artifacts/metadata.json",
        "reports/run_metadata.json": base_dir / "data/metadata/netherlands_laws_run_metadata_latest.json",
    }

    report_paths = _select_reports(reports_dir)
    copies.update(report_paths)

    copied: dict[str, str] = {}
    for rel, source in copies.items():
        if not source.exists():
            raise FileNotFoundError(f"Cannot build unified package; missing source file for {rel}: {source}")
        destination = out_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied[rel] = str(source)
    _rewrite_viewer_friendly_parquet(out_dir / "indexes/bm25/bm25_terms.parquet")
    return copied


def _rewrite_viewer_friendly_parquet(path: Path) -> None:
    """Rewrite large copied parquet files with row groups small enough for Dataset Viewer."""

    table = pq.read_table(path)
    pq.write_table(
        table,
        path,
        compression="zstd",
        row_group_size=DATASET_VIEWER_ROW_GROUP_SIZE,
        write_page_index=True,
    )


def _select_reports(reports_dir: Path) -> dict[str, Path]:
    quality_dir = reports_dir / "quality_audit"
    return {
        "reports/coverage_report.json": _first_existing_or_latest(
            reports_dir,
            [
                "coverage_report_quality_audit_after_verify_*.json",
                "coverage_report_catalog_batch_5000_after_verify_*.json",
                "coverage_report_latest.json",
                "coverage_report*.json",
            ],
        ),
        "reports/integrity_report.json": _first_existing_or_latest(
            reports_dir,
            [
                "integrity_report_quality_audit_final_*.json",
                "integrity_report_catalog_batch_5000_after_verify_*.json",
                "integrity_report*.json",
            ],
        ),
        "reports/quality_report.json": quality_dir / "quality_report.json",
        "reports/duplicate_report.json": quality_dir / "duplicate_report.json",
        "reports/parser_noise_report.json": quality_dir / "parser_noise_report.json",
        "reports/hierarchy_report.json": quality_dir / "hierarchy_report.json",
        "reports/retrieval_validation_report.json": quality_dir / "retrieval_validation_report.json",
    }


def _first_existing_or_latest(directory: Path, patterns: list[str]) -> Path:
    for pattern in patterns:
        matches = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
        if matches:
            return matches[0]
    raise FileNotFoundError(f"No report matched any of {patterns} in {directory}")


def _write_source_manifests(out_dir: Path, base_dir: Path, vector_dir: Path, bm25_dir: Path, kg_dir: Path) -> None:
    sources = {
        "ipfs_netherlands_laws_manifest.json": base_dir / "dataset_manifest.json",
        "ipfs_netherlands_laws_vector_index_manifest.json": vector_dir / "dataset_manifest.json",
        "ipfs_netherlands_laws_bm25_index_manifest.json": bm25_dir / "dataset_manifest.json",
        "ipfs_netherlands_laws_knowledge_graph_manifest.json": kg_dir / "dataset_manifest.json",
    }
    for filename, source in sources.items():
        if not source.exists():
            raise FileNotFoundError(f"Missing source manifest: {source}")
        destination = out_dir / "manifests" / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def _write_logic_relationship_summaries(out_dir: Path) -> list[dict[str, Any]]:
    articles_path = out_dir / "data/articles.parquet"
    laws_path = out_dir / "data/laws.parquet"

    law_rows = _read_parquet_rows(
        laws_path,
        ["cid", "law_identifier", "title", "citation", "source_url", "law_status", "is_current"],
    )
    law_by_id = {str(row.get("law_identifier") or ""): row for row in law_rows}

    article_rows = _read_parquet_rows(
        articles_path,
        [
            "cid",
            "law_cid",
            "law_identifier",
            "article_identifier",
            "article_number",
            "citation",
            "document_citation",
            "text",
            "law_status",
            "is_current",
            "valid_from",
            "valid_to",
            "source_url",
        ],
    )

    by_law: dict[str, list[dict[str, Any]]] = defaultdict(list)
    article_by_number: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in article_rows:
        law_identifier = str(row.get("law_identifier") or "")
        by_law[law_identifier].append(row)
        article_number = _normalize_article_number(row.get("article_number"))
        if article_number and article_number not in article_by_number[law_identifier]:
            article_by_number[law_identifier][article_number] = row

    relationships: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for law_identifier, articles in by_law.items():
        law = law_by_id.get(law_identifier) or {}
        law_cid = str(law.get("cid") or articles[0].get("law_cid") or "")
        for index, article in enumerate(articles):
            _append_relationship(
                relationships,
                seen,
                relationship_type="parent_law",
                source=article,
                target_cid=law_cid,
                target_record_type="law",
                target_label=str(law.get("title") or law.get("citation") or law_identifier),
                target_identifier=law_identifier,
                note="Parent law relationship derived from article law_cid.",
            )
            if index > 0:
                previous = articles[index - 1]
                _append_relationship(
                    relationships,
                    seen,
                    relationship_type="previous_article",
                    source=article,
                    target_cid=str(previous.get("cid") or ""),
                    target_record_type="article",
                    target_label=str(previous.get("citation") or previous.get("article_identifier") or ""),
                    target_identifier=str(previous.get("article_identifier") or ""),
                    note="Previous article relationship derived from source article ordering within the same law.",
                )
            if index + 1 < len(articles):
                following = articles[index + 1]
                _append_relationship(
                    relationships,
                    seen,
                    relationship_type="next_article",
                    source=article,
                    target_cid=str(following.get("cid") or ""),
                    target_record_type="article",
                    target_label=str(following.get("citation") or following.get("article_identifier") or ""),
                    target_identifier=str(following.get("article_identifier") or ""),
                    note="Next article relationship derived from source article ordering within the same law.",
                )

            for target in _referenced_article_targets(article, article_by_number[law_identifier]):
                _append_relationship(
                    relationships,
                    seen,
                    relationship_type="referenced_article_candidate",
                    source=article,
                    target_cid=str(target.get("cid") or ""),
                    target_record_type="article",
                    target_label=str(target.get("citation") or target.get("article_identifier") or ""),
                    target_identifier=str(target.get("article_identifier") or ""),
                    confidence="low",
                    note="Candidate same-law article reference derived from article text mention.",
                )

    write_parquet(out_dir / "logic/logic_relationships.parquet", relationships)
    write_jsonl(out_dir / "logic/logic_relationships.jsonl", relationships)
    return relationships


def _read_parquet_rows(path: Path, columns: list[str]) -> list[dict[str, Any]]:
    parquet = pq.ParquetFile(path)
    available = [column for column in columns if column in parquet.schema_arrow.names]
    if not available:
        return []
    return parquet.read(columns=available).to_pylist()


def _normalize_article_number(value: Any) -> str:
    return str(value or "").strip().lower().rstrip(".")


def _referenced_article_targets(
    source: dict[str, Any],
    article_by_number: dict[str, dict[str, Any]],
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    text = str(source.get("text") or "")
    if not text:
        return []
    source_cid = str(source.get("cid") or "")
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in ARTICLE_REFERENCE_RE.finditer(text):
        target = article_by_number.get(_normalize_article_number(match.group(1)))
        target_cid = str((target or {}).get("cid") or "")
        if not target or not target_cid or target_cid == source_cid or target_cid in seen:
            continue
        seen.add(target_cid)
        targets.append(target)
        if len(targets) >= limit:
            break
    return targets


def _append_relationship(
    rows: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    relationship_type: str,
    source: dict[str, Any],
    target_cid: str,
    target_record_type: str,
    target_label: str,
    target_identifier: str,
    confidence: str = "high",
    note: str,
) -> None:
    source_cid = str(source.get("cid") or "")
    target_cid = str(target_cid or "")
    if not source_cid or not target_cid:
        return
    key = (relationship_type, source_cid, target_cid)
    if key in seen:
        return
    seen.add(key)
    row = {
        "relationship_type": relationship_type,
        "source_cid": source_cid,
        "target_cid": target_cid,
        "source_record_type": "article",
        "target_record_type": target_record_type,
        "law_cid": source.get("law_cid"),
        "law_identifier": source.get("law_identifier"),
        "source_identifier": source.get("article_identifier"),
        "target_identifier": target_identifier,
        "source_label": source.get("citation") or source.get("article_identifier"),
        "target_label": target_label,
        "source_law_status": source.get("law_status"),
        "source_is_current": source.get("is_current"),
        "source_valid_from": source.get("valid_from"),
        "source_valid_to": source.get("valid_to"),
        "source_url": source.get("source_url"),
        "status": "derived",
        "confidence": confidence,
        "derivation_note": note,
    }
    row["relationship_cid"] = cid_for_obj(row)
    rows.append(row)


def _write_unified_manifest(out_dir: Path, repo_id: str, copied_sources: dict[str, str]) -> dict[str, Any]:
    records = _record_counts(out_dir)
    source_manifests = _load_source_manifests(out_dir)
    coverage = _read_json(out_dir / "reports/coverage_report.json")
    quality = _read_json(out_dir / "reports/quality_report.json")
    integrity = _read_json(out_dir / "reports/integrity_report.json")
    run_metadata = _read_json(out_dir / "reports/run_metadata.json")

    manifest: dict[str, Any] = {
        "dataset_name": UNIFIED_WETWIJZER_DATASET_NAME,
        "repo_target": repo_id,
        "upload_target": repo_id,
        "jurisdiction": "Netherlands",
        "language": "nl",
        "build_date": datetime.now(UTC).isoformat(),
        "source_repos": {
            "base": DEFAULT_HF_REPO_IDS["base"],
            "vector": DEFAULT_HF_REPO_IDS["vector"],
            "bm25": DEFAULT_HF_REPO_IDS["bm25"],
            "knowledge_graph": DEFAULT_HF_REPO_IDS["knowledge-graph"],
        },
        "records": records,
        "coverage": {
            "counts": coverage.get("counts"),
            "percent_complete": coverage.get("percent_complete"),
            "completion_semantics": coverage.get("completion_semantics"),
            "law_status_counts": coverage.get("law_status_counts") or run_metadata.get("law_status_counts"),
            "article_extraction_status_counts": coverage.get("article_extraction_status_counts"),
        },
        "quality_audit": {
            "generated_at": quality.get("generated_at"),
            "records": quality.get("records"),
            "issue_summary": quality.get("issue_summary"),
            "current_gate_pass": (quality.get("quality_gate_recommendation") or {}).get("current_gate_pass"),
        },
        "integrity": {
            "generated_at": integrity.get("generated_at"),
            "ok": integrity.get("ok"),
            "issue_counts": integrity.get("issue_counts"),
        },
        "not_full_corpus_warning": (
            "This is a quality-audited partial Dutch corpus package. Do not claim full Dutch corpus coverage "
            "until every discovered BWBR identifier is parsed, intentionally skipped, or permanently failed "
            "with explanation."
        ),
        "source_local_files": copied_sources,
        "source_manifest_records": {
            name: manifest_data.get("records", {}) for name, manifest_data in source_manifests.items()
        },
        "sample_cids": _sample_cids(out_dir),
        "files": {},
    }

    for path in sorted(p for p in out_dir.rglob("*") if p.is_file() and p.name != "dataset_manifest.json"):
        rel = path.relative_to(out_dir).as_posix()
        manifest["files"][rel] = file_manifest_entry(path, _records_for_file(rel, records))

    write_json(out_dir / "dataset_manifest.json", manifest)
    return manifest


def _record_counts(out_dir: Path) -> dict[str, int]:
    counts = {
        "laws": _parquet_count(out_dir / "data/laws.parquet"),
        "articles": _parquet_count(out_dir / "data/articles.parquet"),
        "cid_index": _parquet_count(out_dir / "data/cid_index.parquet"),
        "vector_index": _parquet_count(out_dir / "indexes/vector/vector_mapping.parquet"),
        "bm25_documents": _parquet_count(out_dir / "indexes/bm25/bm25_documents.parquet"),
        "bm25_terms": _parquet_count(out_dir / "indexes/bm25/bm25_terms.parquet"),
        "knowledge_graph_nodes": _parquet_count(out_dir / "graph/kg_nodes.parquet"),
        "knowledge_graph_edges": _parquet_count(out_dir / "graph/kg_edges.parquet"),
    }
    logic_path = out_dir / "logic/logic_relationships.parquet"
    if logic_path.exists():
        counts["logic_relationships"] = _parquet_count(logic_path)
    return counts


def _parquet_count(path: Path) -> int:
    return int(pq.ParquetFile(path).metadata.num_rows)


def _records_for_file(rel: str, records: dict[str, int]) -> int | None:
    mapping = {
        "data/laws.parquet": "laws",
        "data/articles.parquet": "articles",
        "data/cid_index.parquet": "cid_index",
        "indexes/vector/vector_mapping.parquet": "vector_index",
        "indexes/bm25/bm25_documents.parquet": "bm25_documents",
        "indexes/bm25/bm25_terms.parquet": "bm25_terms",
        "graph/kg_nodes.parquet": "knowledge_graph_nodes",
        "graph/kg_edges.parquet": "knowledge_graph_edges",
        "logic/logic_relationships.parquet": "logic_relationships",
        "logic/logic_relationships.jsonl": "logic_relationships",
    }
    key = mapping.get(rel)
    return records.get(key) if key else None


def _load_source_manifests(out_dir: Path) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted((out_dir / "manifests").glob("*.json")):
        manifests[path.stem] = _read_json(path)
    return manifests


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sample_cids(out_dir: Path) -> dict[str, str | None]:
    samples: dict[str, str | None] = {}
    for name, path, column in [
        ("law", out_dir / "data/laws.parquet", "cid"),
        ("article", out_dir / "data/articles.parquet", "cid"),
        ("cid_index", out_dir / "data/cid_index.parquet", "cid"),
        ("vector", out_dir / "indexes/vector/vector_mapping.parquet", "source_cid"),
        ("bm25_document", out_dir / "indexes/bm25/bm25_documents.parquet", "source_cid"),
        ("knowledge_graph_node", out_dir / "graph/kg_nodes.parquet", "cid"),
        ("knowledge_graph_edge_source", out_dir / "graph/kg_edges.parquet", "source_cid"),
        ("logic_relationship_source", out_dir / "logic/logic_relationships.parquet", "source_cid"),
    ]:
        if not path.exists():
            samples[name] = None
            continue
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows == 0 or column not in parquet.schema_arrow.names:
            samples[name] = None
            continue
        samples[name] = str(parquet.read_row_group(0, columns=[column]).column(0)[0].as_py() or "")
    return samples


def _write_readme(out_dir: Path, repo_id: str, manifest: dict[str, Any]) -> None:
    records = manifest["records"]
    coverage_counts = (manifest.get("coverage") or {}).get("counts") or {}
    integrity = manifest.get("integrity") or {}
    quality = manifest.get("quality_audit") or {}
    readme = f"""---
pretty_name: WetWijzer Netherlands Legal Corpus
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
- bm25
- vector-search
- knowledge-graph
license: other
configs:
- config_name: laws
  data_files:
  - split: train
    path: data/laws.parquet
- config_name: articles
  data_files:
  - split: train
    path: data/articles.parquet
- config_name: cid_index
  data_files:
  - split: train
    path: data/cid_index.parquet
- config_name: vector_index
  data_files:
  - split: train
    path: indexes/vector/vector_mapping.parquet
- config_name: bm25_documents
  data_files:
  - split: train
    path: indexes/bm25/bm25_documents.parquet
- config_name: bm25_terms
  data_files:
  - split: train
    path: indexes/bm25/bm25_terms.parquet
- config_name: knowledge_graph_nodes
  data_files:
  - split: train
    path: graph/kg_nodes.parquet
- config_name: knowledge_graph_edges
  data_files:
  - split: train
    path: graph/kg_edges.parquet
- config_name: logic_relationships
  data_files:
  - split: train
    path: logic/logic_relationships.parquet
---

# WetWijzer Netherlands Legal Corpus

Hugging Face target: `{repo_id}`.

This unified dataset bundles the quality-audited WetWijzer Netherlands legal corpus stack in one repository for frontend retrieval. It preserves the existing compatibility repositories and does not replace or delete them.

## Contents

- Laws: {records.get("laws", 0):,}
- Articles: {records.get("articles", 0):,}
- CID index rows: {records.get("cid_index", 0):,}
- Vector mapping rows: {records.get("vector_index", 0):,}
- BM25 document rows: {records.get("bm25_documents", 0):,}
- BM25 term rows: {records.get("bm25_terms", 0):,}
- Knowledge graph nodes: {records.get("knowledge_graph_nodes", 0):,}
- Knowledge graph edges: {records.get("knowledge_graph_edges", 0):,}
- Logic/relationship summary rows: {records.get("logic_relationships", 0):,}

## Layout

- `data/laws.parquet`
- `data/articles.parquet`
- `data/cid_index.parquet`
- `indexes/vector/vector_mapping.parquet`
- `indexes/vector/faiss.index`
- `indexes/bm25/bm25_documents.parquet`
- `indexes/bm25/bm25_terms.parquet`
- `graph/kg_nodes.parquet`
- `graph/kg_edges.parquet`
- `graph/graph.jsonld`
- `logic/logic_relationships.parquet`
- `reports/*.json`
- `manifests/*.json`
- `dataset_manifest.json`

Every retrieval layer is joinable by CID. Law rows have `cid`; article rows have `cid` and `law_cid`; vector and BM25 rows use `source_cid`; graph nodes use `cid`; graph edges and relationship summaries use `source_cid`, `target_cid`, and a relationship type.

## Source Repositories

- `{DEFAULT_HF_REPO_IDS["base"]}`
- `{DEFAULT_HF_REPO_IDS["vector"]}`
- `{DEFAULT_HF_REPO_IDS["bm25"]}`
- `{DEFAULT_HF_REPO_IDS["knowledge-graph"]}`

## Coverage And Quality

This is a quality-audited partial Dutch corpus package, not a full Dutch corpus claim.

Completed catalog coverage: {coverage_counts.get("complete", "unknown")} of {coverage_counts.get("total_discovered_identifiers", "unknown")} discovered BWBR identifiers ({(manifest.get("coverage") or {}).get("percent_complete", "unknown")}%). Remaining identifiers: {coverage_counts.get("remaining", "unknown")}.

Integrity validation ok: {integrity.get("ok", "unknown")}. Quality gate passed: {quality.get("current_gate_pass", "unknown")}.

Historical and inactive laws are preserved. Use `law_status`, `is_current`, `valid_from`, `valid_to`, `effective_date`, `retrieved_at`, `status_source`, `status_confidence`, and `status_note` to distinguish current, historical, repealed, superseded, and unknown-status records.

This dataset is not legal advice. Users should verify official text and legal effect on `wetten.overheid.nl`.
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def _write_gitattributes(out_dir: Path) -> None:
    (out_dir / ".gitattributes").write_text(
        "*.parquet filter=lfs diff=lfs merge=lfs -text\n"
        "*.index filter=lfs diff=lfs merge=lfs -text\n"
        "*.pkl filter=lfs diff=lfs merge=lfs -text\n"
        "*.jsonld filter=lfs diff=lfs merge=lfs -text\n"
        "logic/*.jsonl filter=lfs diff=lfs merge=lfs -text\n",
        encoding="utf-8",
    )


def load_parquet_head(path: Path, *, columns: list[str] | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """Small verification helper for local/remote downloaded Parquet files."""

    parquet = pq.ParquetFile(path)
    read_columns = columns or parquet.schema_arrow.names
    if parquet.metadata.num_rows == 0:
        return []
    table = parquet.read_row_group(0, columns=[column for column in read_columns if column in parquet.schema_arrow.names])
    return table.slice(0, limit).to_pylist()


def validate_unified_package(out_dir: Path | None = None) -> dict[str, Any]:
    """Validate local unified bundle joins without downloading or scraping anything."""

    out_dir = out_dir or DEFAULT_OUT_DIR
    required = [
        "dataset_manifest.json",
        "data/laws.parquet",
        "data/articles.parquet",
        "data/cid_index.parquet",
        "indexes/vector/vector_mapping.parquet",
        "indexes/bm25/bm25_documents.parquet",
        "indexes/bm25/bm25_terms.parquet",
        "graph/kg_nodes.parquet",
        "graph/kg_edges.parquet",
        "logic/logic_relationships.parquet",
    ]
    missing = [rel for rel in required if not (out_dir / rel).exists()]
    sample = _sample_cids(out_dir)
    messages = [f"Missing required file: {rel}" for rel in missing]
    if "logic/logic_relationships.parquet" in missing:
        messages.append(
            "Relationship summaries are required for unified package validation; "
            "rebuild with include_relationship_summaries=True before upload."
        )

    manifest = _read_json(out_dir / "dataset_manifest.json") if "dataset_manifest.json" not in missing else {}
    article_rows = [] if "data/articles.parquet" in missing else load_parquet_head(
        out_dir / "data/articles.parquet",
        columns=["cid", "law_cid"],
        limit=1,
    )
    if not article_rows and "data/articles.parquet" not in missing:
        messages.append("Required parquet has no article rows: data/articles.parquet")

    article = article_rows[0] if article_rows else {}
    article_cid = article.get("cid")
    law_cid = article.get("law_cid")
    if article_rows and (not article_cid or not law_cid):
        messages.append("Sample article row must include cid and law_cid.")

    vector_match = _parquet_contains_if_present(
        out_dir,
        missing,
        "indexes/vector/vector_mapping.parquet",
        "source_cid",
        article_cid,
    )
    bm25_match = _parquet_contains_if_present(
        out_dir,
        missing,
        "indexes/bm25/bm25_documents.parquet",
        "source_cid",
        article_cid,
    )
    node_match = _parquet_contains_if_present(out_dir, missing, "graph/kg_nodes.parquet", "cid", article_cid)
    edge_match = _parquet_contains_if_present(out_dir, missing, "graph/kg_edges.parquet", "source_cid", article_cid)
    relationship_match = _parquet_contains_if_present(
        out_dir,
        missing,
        "logic/logic_relationships.parquet",
        "source_cid",
        article_cid,
    )
    parent_match = _parquet_contains_if_present(out_dir, missing, "data/laws.parquet", "cid", law_cid)

    checks = {
        "missing_required_files": missing,
        "sample_article_cid": article_cid,
        "sample_parent_law_cid": law_cid,
        "parent_law_found": parent_match,
        "vector_row_found": vector_match,
        "bm25_row_found": bm25_match,
        "graph_node_found": node_match,
        "graph_edge_found": edge_match,
        "logic_relationship_found": relationship_match,
    }
    ok = not messages and all(value for key, value in checks.items() if key.endswith("_found"))
    return {
        "ok": ok,
        "records": manifest.get("records", {}),
        "sample_cids": sample,
        "checks": checks,
        "messages": messages,
    }


def _parquet_contains_if_present(out_dir: Path, missing: list[str], rel: str, column: str, value: Any) -> bool:
    if value is None or rel in missing:
        return False
    return _parquet_contains(out_dir / rel, column, value)


def _parquet_contains(path: Path, column: str, value: Any) -> bool:
    parquet = pq.ParquetFile(path)
    if column not in parquet.schema_arrow.names:
        return False
    for batch in parquet.iter_batches(columns=[column], batch_size=8192):
        values = batch.column(0).to_pylist()
        if value in values:
            return True
    return False


def main() -> None:
    out_dir = build_unified_wetwijzer_package()
    print(json.dumps({"out_dir": str(out_dir), **validate_unified_package(out_dir)}, indent=2))


if __name__ == "__main__":
    main()

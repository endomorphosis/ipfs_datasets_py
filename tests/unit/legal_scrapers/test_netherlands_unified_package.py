from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
import pyarrow as pa
import pyarrow.parquet as pq

from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.common import write_json, write_parquet
from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.builders.unified_package import (
    _reset_output_dir,
    build_unified_wetwijzer_package,
    validate_unified_package,
)
from ipfs_datasets_py.processors.legal_scrapers.netherlands_laws.upload import resolve_targets


def test_build_unified_wetwijzer_package_preserves_layers_and_adds_relationships(tmp_path: Path) -> None:
    base_dir, vector_dir, bm25_dir, kg_dir, reports_dir = _write_source_packages(tmp_path)
    out_dir = tmp_path / "unified"

    result = build_unified_wetwijzer_package(
        base_dir=base_dir,
        vector_dir=vector_dir,
        bm25_dir=bm25_dir,
        kg_dir=kg_dir,
        reports_dir=reports_dir,
        out_dir=out_dir,
        repo_id="justicedao/wetwijzer_netherlands_legal_corpus",
    )

    assert result == out_dir
    assert (out_dir / "data/laws.parquet").exists()
    assert (out_dir / "indexes/vector/faiss.index").read_bytes() == b"faiss"
    assert (out_dir / "graph/graph.jsonld").exists()

    manifest = json.loads((out_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["records"]["laws"] == 1
    assert manifest["records"]["articles"] == 2
    assert manifest["records"]["logic_relationships"] == 5
    assert manifest["integrity"]["ok"] is True
    assert "not_full_corpus_warning" in manifest

    relationships = _read_parquet(out_dir / "logic/logic_relationships.parquet")
    relationship_types = {row["relationship_type"] for row in relationships}
    assert {"parent_law", "previous_article", "next_article"}.issubset(relationship_types)
    assert all(row["source_cid"] for row in relationships)
    assert all(row["target_cid"] for row in relationships)

    validation = validate_unified_package(out_dir)
    assert validation["ok"] is True
    assert validation["checks"]["sample_article_cid"] == "bafyarticle1"


def test_unified_upload_target_is_explicit_not_part_of_legacy_all() -> None:
    assert [target.key for target in resolve_targets(["unified"])] == ["unified"]
    assert [target.key for target in resolve_targets(["all"])] == ["base", "vector", "bm25", "knowledge-graph"]


def test_reset_output_dir_refuses_unsafe_existing_directory() -> None:
    with pytest.raises(ValueError, match="Refusing to reset unsafe unified package output directory"):
        _reset_output_dir(Path("/"))


def test_validate_unified_package_reports_missing_required_files(tmp_path: Path) -> None:
    out_dir = tmp_path / "unified"
    out_dir.mkdir()
    write_json(out_dir / "dataset_manifest.json", {"records": {}})

    validation = validate_unified_package(out_dir)

    assert validation["ok"] is False
    assert "data/articles.parquet" in validation["checks"]["missing_required_files"]
    assert any("Missing required file: data/articles.parquet" == message for message in validation["messages"])


def test_validate_unified_package_reports_empty_articles_parquet(tmp_path: Path) -> None:
    base_dir, vector_dir, bm25_dir, kg_dir, reports_dir = _write_source_packages(tmp_path)
    out_dir = tmp_path / "unified"
    build_unified_wetwijzer_package(
        base_dir=base_dir,
        vector_dir=vector_dir,
        bm25_dir=bm25_dir,
        kg_dir=kg_dir,
        reports_dir=reports_dir,
        out_dir=out_dir,
    )
    pq.write_table(
        pa.table({"cid": pa.array([], type=pa.string()), "law_cid": pa.array([], type=pa.string())}),
        out_dir / "data/articles.parquet",
        compression="zstd",
    )

    validation = validate_unified_package(out_dir)

    assert validation["ok"] is False
    assert validation["checks"]["sample_article_cid"] is None
    assert "Required parquet has no article rows: data/articles.parquet" in validation["messages"]


def test_validate_unified_package_requires_relationship_summaries(tmp_path: Path) -> None:
    base_dir, vector_dir, bm25_dir, kg_dir, reports_dir = _write_source_packages(tmp_path)
    out_dir = tmp_path / "unified"
    build_unified_wetwijzer_package(
        base_dir=base_dir,
        vector_dir=vector_dir,
        bm25_dir=bm25_dir,
        kg_dir=kg_dir,
        reports_dir=reports_dir,
        out_dir=out_dir,
        include_relationship_summaries=False,
    )

    validation = validate_unified_package(out_dir)

    assert validation["ok"] is False
    assert "logic/logic_relationships.parquet" in validation["checks"]["missing_required_files"]
    assert (
        "Relationship summaries are required for unified package validation; "
        "rebuild with include_relationship_summaries=True before upload."
    ) in validation["messages"]


def _write_source_packages(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    base_dir = tmp_path / "base"
    vector_dir = tmp_path / "vector"
    bm25_dir = tmp_path / "bm25"
    kg_dir = tmp_path / "kg"
    reports_dir = tmp_path / "reports"

    laws = [
        {
            "cid": "bafylaw1",
            "record_type": "document",
            "law_identifier": "BWBRTEST",
            "title": "Testwet",
            "citation": "Testwet",
            "source_url": "https://wetten.overheid.nl/BWBRTEST/",
            "law_status": "current",
            "is_current": True,
        }
    ]
    articles = [
        {
            "cid": "bafyarticle1",
            "law_cid": "bafylaw1",
            "record_type": "article",
            "law_identifier": "BWBRTEST",
            "article_identifier": "BWBRTEST:artikel:1",
            "article_number": "1",
            "citation": "Testwet, Artikel 1",
            "text": "Zie Artikel 2.",
            "law_status": "current",
            "is_current": True,
        },
        {
            "cid": "bafyarticle2",
            "law_cid": "bafylaw1",
            "record_type": "article",
            "law_identifier": "BWBRTEST",
            "article_identifier": "BWBRTEST:artikel:2",
            "article_number": "2",
            "citation": "Testwet, Artikel 2",
            "text": "Slotbepaling.",
            "law_status": "current",
            "is_current": True,
        },
    ]
    cid_index = [
        {"cid": "bafylaw1", "record_type": "law", "law_identifier": "BWBRTEST"},
        {"cid": "bafyarticle1", "record_type": "article", "law_identifier": "BWBRTEST"},
        {"cid": "bafyarticle2", "record_type": "article", "law_identifier": "BWBRTEST"},
    ]
    vector_rows = [
        {"cid": row["cid"], "source_cid": row["cid"], "law_cid": row.get("law_cid") or row["cid"], "record_type": row["record_type"]}
        for row in [laws[0], *articles]
    ]
    bm25_docs = [
        {"cid": row["cid"], "source_cid": row["cid"], "law_cid": row.get("law_cid") or row["cid"], "record_type": row["record_type"]}
        for row in [laws[0], *articles]
    ]
    bm25_terms = [{"term": "test", "doc_freq": 1, "idf": 1.0, "postings_count": 1, "postings": []}]
    kg_nodes = [
        {"cid": row["cid"], "source_cid": row["cid"], "record_type": row["record_type"], "label": row.get("citation") or row.get("title")}
        for row in [laws[0], *articles]
    ]
    kg_edges = [
        {
            "cid": "bafyarticle1",
            "edge_type": "isPartOf",
            "source_cid": "bafyarticle1",
            "target_cid": "bafylaw1",
            "law_identifier": "BWBRTEST",
            "article_identifier": "BWBRTEST:artikel:1",
        }
    ]

    write_parquet(base_dir / "parquet/laws/train-00000-of-00001.parquet", laws)
    write_parquet(base_dir / "parquet/articles/train-00000-of-00001.parquet", articles)
    write_parquet(base_dir / "parquet/cid_index/train-00000-of-00001.parquet", cid_index)
    write_json(base_dir / "data/metadata/netherlands_laws_run_metadata_latest.json", {"scraped_at": "2026-06-27T00:00:00"})
    write_json(base_dir / "dataset_manifest.json", {"records": {"laws": 1, "articles": 2, "cid_index": 3}})

    write_parquet(vector_dir / "parquet/mapping/train-00000-of-00001.parquet", vector_rows)
    (vector_dir / "artifacts").mkdir(parents=True)
    (vector_dir / "artifacts/faiss.index").write_bytes(b"faiss")
    (vector_dir / "artifacts/vectorizer.pkl").write_bytes(b"vectorizer")
    (vector_dir / "artifacts/svd.pkl").write_bytes(b"svd")
    write_json(vector_dir / "artifacts/metadata.json", {"records": 3})
    write_json(vector_dir / "dataset_manifest.json", {"records": {"mapping": 3}})

    write_parquet(bm25_dir / "parquet/documents/train-00000-of-00001.parquet", bm25_docs)
    write_parquet(bm25_dir / "parquet/terms/train-00000-of-00001.parquet", bm25_terms)
    write_json(bm25_dir / "artifacts/metadata.json", {"records": {"documents": 3, "terms": 1}})
    write_json(bm25_dir / "dataset_manifest.json", {"records": {"documents": 3, "terms": 1}})

    write_parquet(kg_dir / "parquet/nodes/train-00000-of-00001.parquet", kg_nodes)
    write_parquet(kg_dir / "parquet/edges/train-00000-of-00001.parquet", kg_edges)
    write_json(kg_dir / "artifacts/metadata.json", {"records": {"nodes": 3, "edges": 1}})
    write_json(kg_dir / "dataset_manifest.json", {"records": {"nodes": 3, "edges": 1}})
    (kg_dir / "data/graph").mkdir(parents=True)
    (kg_dir / "data/graph/ipfs_netherlands_laws_kg.jsonld").write_text('{"@graph":[]}', encoding="utf-8")

    write_json(
        reports_dir / "coverage_report_quality_audit_after_verify_20260627.json",
        {"counts": {"complete": 1, "total_discovered_identifiers": 10, "remaining": 9}, "percent_complete": 10.0},
    )
    write_json(reports_dir / "integrity_report_quality_audit_final_20260627.json", {"ok": True, "issue_counts": {}})
    write_json(reports_dir / "quality_audit/quality_report.json", {"quality_gate_recommendation": {"current_gate_pass": True}})
    write_json(reports_dir / "quality_audit/duplicate_report.json", {})
    write_json(reports_dir / "quality_audit/parser_noise_report.json", {})
    write_json(reports_dir / "quality_audit/hierarchy_report.json", {})
    write_json(reports_dir / "quality_audit/retrieval_validation_report.json", {})

    return base_dir, vector_dir, bm25_dir, kg_dir, reports_dir


def _read_parquet(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()

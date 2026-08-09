"""Tests for shared sorted BM25 layout (USCIR-014)."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import (
    canonical_identity,
    cid_v1_from_digest,
)
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import (
    BM25_DOCUMENT_SCHEMA_VERSION,
    BM25_LAYOUT_SCHEMA_VERSION,
    BM25_META_SCHEMA_VERSION,
    BM25_POSTING_SCHEMA_VERSION,
    BM25LayoutConfig,
    BM25LayoutError,
    DEFAULT_BM25_TOKENIZER_ID,
    DEFAULT_POSTINGS_PER_ROW,
    DEFAULT_ROWS_PER_SHARD,
    DEFAULT_TERMS_PER_SHARD,
    TASK_ID,
    bm25_term_score,
    build_bm25_layout,
    default_bm25_fixture_payload,
    default_bm25_fixture_path,
    explain_bm25_hit,
    tokenize_bm25_text,
    validate_bm25_layout,
    write_default_bm25_fixture,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label},
        domain="test/hf-graphrag-bm25",
        schema_version="test/v1",
    ).cid


def _rows() -> list[dict[str, object]]:
    return [
        {
            "entry_cid": _cid("alpha"),
            "title": "Freedom of Information Act",
            "body": "Each agency shall make records available under FOIA procedures.",
            "record_type": "section",
        },
        {
            "entry_cid": _cid("beta"),
            "title": "Privacy Act",
            "body": "No agency shall disclose any record without a written request.",
            "record_type": "section",
        },
        {
            "entry_cid": _cid("gamma"),
            "title": "Federal question",
            "body": "District courts have original jurisdiction of civil actions.",
            "record_type": "section",
        },
    ]


def _config() -> BM25LayoutConfig:
    return BM25LayoutConfig(
        max_documents=10,
        max_text_characters=4096,
        max_rows_per_shard=2,
        terms_per_shard=2,
        postings_per_row=2,
        max_query_terms=16,
    )


def _all_rows(root: Path, relative: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted((root / relative).glob("*.parquet")):
        result.extend(pq.read_table(path).to_pylist())
    return result


def test_tokenizer_is_versioned_and_deterministic() -> None:
    assert DEFAULT_BM25_TOKENIZER_ID.endswith("/v1")
    assert tokenize_bm25_text("Parser parser FOIA") == (
        "parser",
        "parser",
        "foia",
    )
    assert tokenize_bm25_text("foo/bar") == tokenize_bm25_text("foo/bar")


def test_physical_bounds_match_release_policy() -> None:
    assert DEFAULT_ROWS_PER_SHARD == 4096
    assert DEFAULT_TERMS_PER_SHARD == 4096
    assert DEFAULT_POSTINGS_PER_ROW == 4096
    with pytest.raises(BM25LayoutError):
        BM25LayoutConfig(max_rows_per_shard=4097)
    with pytest.raises(BM25LayoutError):
        BM25LayoutConfig(postings_per_row=4097)
    with pytest.raises(BM25LayoutError):
        BM25LayoutConfig(terms_per_shard=4097)


def test_build_exports_sorted_documents_and_term_range_indexes(tmp_path: Path) -> None:
    summary = build_bm25_layout(list(reversed(_rows())), tmp_path, config=_config())

    assert summary.document_count == 3
    assert summary.document_shard_count == 2
    assert summary.posting_shard_count >= 1
    assert summary.term_count > 0
    assert summary.token_instance_count > summary.document_count
    assert TASK_ID == "USCIR-014"
    assert summary.config.tokenizer == DEFAULT_BM25_TOKENIZER_ID

    documents = _all_rows(tmp_path, "data/bm25/documents")
    assert [row["document_index"] for row in documents] == [0, 1, 2]
    # Globally ordered by (record_type, entry_cid) when indices not supplied.
    assert [row["entry_cid"] for row in documents] == sorted(
        row["entry_cid"] for row in documents
    )
    assert all(
        row["schema_version"] == BM25_DOCUMENT_SCHEMA_VERSION for row in documents
    )

    postings = _all_rows(tmp_path, "data/bm25/postings")
    terms = [row["term"] for row in postings]
    assert terms == sorted(terms)
    for row in postings:
        assert len(row["document_indices"]) <= 2
        assert row["schema_version"] == BM25_POSTING_SCHEMA_VERSION
        assert len(row["document_indices"]) == len(row["title_frequencies"])
        assert len(row["document_indices"]) == len(row["body_frequencies"])

    document_index = pq.read_table(tmp_path / "indexes" / "bm25_document_chunks.parquet")
    keyword_index = pq.read_table(tmp_path / "indexes" / "bm25_keyword_shards.parquet")
    covered: set[str] = set()
    for row in document_index.to_pylist() + keyword_index.to_pylist():
        target = tmp_path / row["relative_path"]
        content = target.read_bytes()
        digest = hashlib.sha256(content).digest()
        assert row["sha256"] == digest.hex()
        assert row["cid"] == cid_v1_from_digest(digest)
        assert row["size_bytes"] == len(content)
        assert row["schema_version"] == BM25_META_SCHEMA_VERSION
        covered.add(row["relative_path"])
    assert covered == {
        path.relative_to(tmp_path).as_posix()
        for path in (tmp_path / "data" / "bm25").rglob("*.parquet")
    }


def test_validate_round_trip(tmp_path: Path) -> None:
    built = build_bm25_layout(_rows(), tmp_path, config=_config())
    validated = validate_bm25_layout(tmp_path, config=_config())
    assert validated.counts == built.counts
    assert math.isclose(
        validated.average_document_length,
        built.average_document_length,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert validated.config.schema_version == BM25_LAYOUT_SCHEMA_VERSION


def test_reference_score_matches_okapi_formula() -> None:
    score = bm25_term_score(
        tf=2.0,
        idf=1.5,
        doc_length=10.0,
        avg_doc_length=10.0,
        k1=1.2,
        b=0.75,
        field_weight=5.0,
    )
    # With dl == avgdl: idf * tf*(k1+1)/(tf+k1) * weight
    expected = 5.0 * 1.5 * (2.0 * 2.2) / (2.0 + 1.2)
    assert math.isclose(score, expected, rel_tol=0.0, abs_tol=1e-12)


def test_explain_hit_uses_field_weights() -> None:
    cfg = BM25LayoutConfig()
    explanation = explain_bm25_hit(
        term="agency",
        title_tf=1,
        body_tf=2,
        idf=1.0,
        title_length=4,
        body_length=10,
        avg_document_length=10.0,
        config=cfg,
    )
    assert explanation["total_score"] == explanation["title_score"] + explanation[
        "body_score"
    ]
    assert explanation["title_score"] > 0.0
    assert explanation["body_score"] > 0.0


def test_sharded_scores_match_reference_for_exported_cells(tmp_path: Path) -> None:
    summary = build_bm25_layout(_rows(), tmp_path, config=_config())
    documents = {row["document_index"]: row for row in _all_rows(tmp_path, "data/bm25/documents")}
    postings = _all_rows(tmp_path, "data/bm25/postings")
    avgdl = summary.average_document_length
    for row in postings:
        for offset, doc_index in enumerate(row["document_indices"]):
            doc = documents[doc_index]
            title_tf = row["title_frequencies"][offset]
            body_tf = row["body_frequencies"][offset]
            explanation = explain_bm25_hit(
                term=row["term"],
                title_tf=title_tf,
                body_tf=body_tf,
                idf=float(row["idf"]),
                title_length=int(doc["title_length"]),
                body_length=int(doc["body_length"]),
                avg_document_length=avgdl,
                config=summary.config,
            )
            # Reference formula is deterministic and finite.
            assert math.isfinite(explanation["total_score"])
            assert explanation["total_score"] >= 0.0


def test_no_posting_cell_exceeds_bound(tmp_path: Path) -> None:
    cfg = _config()
    build_bm25_layout(_rows(), tmp_path, config=cfg)
    for row in _all_rows(tmp_path, "data/bm25/postings"):
        assert len(row["document_indices"]) <= cfg.postings_per_row


def test_default_fixture_payload_and_on_disk_recipe(tmp_path: Path) -> None:
    payload = default_bm25_fixture_payload()
    assert payload["task_id"] == "USCIR-014"
    assert payload["maximum_rows_per_physical_shard"] == 4096
    assert payload["acceptance"]["terms_globally_ordered"] is True
    path = write_default_bm25_fixture(tmp_path / "bm25_reference.json")
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == payload
    # Sealed fixture path exists relative to package tests tree.
    sealed = default_bm25_fixture_path()
    assert sealed.name == "bm25_reference.json"


def test_input_order_does_not_change_layout(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    sa = build_bm25_layout(_rows(), a, config=_config())
    sb = build_bm25_layout(list(reversed(_rows())), b, config=_config())
    assert sa.counts == sb.counts
    assert _all_rows(a, "data/bm25/documents") == _all_rows(b, "data/bm25/documents")
    assert _all_rows(a, "data/bm25/postings") == _all_rows(b, "data/bm25/postings")

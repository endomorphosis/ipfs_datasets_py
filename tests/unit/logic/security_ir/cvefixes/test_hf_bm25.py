"""Tests for the deterministic CVEfixes Hugging Face BM25 layout."""

from __future__ import annotations

import hashlib
import math

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import (
    canonical_identity,
    cid_v1_from_digest,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_bm25 import (
    CVEFIXES_BM25_TOKENIZER,
    CVEFIXES_HF_BM25_DOCUMENT_SCHEMA_VERSION,
    CVEFIXES_HF_BM25_POSTING_SCHEMA_VERSION,
    CVEFIXES_HF_META_SCHEMA_VERSION,
    CVEfixesBM25LayoutConfig,
    CVEfixesBM25LayoutError,
    build_cvefixes_bm25_hf_layout,
    tokenize_cvefixes_bm25,
    validate_cvefixes_bm25_hf_layout,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label},
        domain="test/cvefixes-bm25",
        schema_version="test/v1",
    ).cid


def _rows() -> list[dict[str, object]]:
    return [
        {
            "authority": "candidate",
            "record_id": _cid("policy"),
            "record_json": (
                '{"effect":"deny","operation":"unsafe-parser",'
                '"reason":"parser parser"}'
            ),
            "record_type": "policy_candidate",
            "title": "CVE-2026-0042 unsafe parser",
        },
        {
            "authority": "non_authoritative",
            "record_id": _cid("graph"),
            "record_json": (
                '{"cve_id":"CVE-2026-0042","component":"parser"}'
            ),
            "record_type": "graph_node",
            "title": "Parser graph evidence",
        },
        {
            "authority": "non_authoritative",
            "record_id": _cid("source"),
            "record_json": (
                '{"cve_id":"CVE-2026-0042","language":"Python"}'
            ),
            "record_type": "source_record",
            "title": "Pinned source evidence",
        },
    ]


def _config() -> CVEfixesBM25LayoutConfig:
    return CVEfixesBM25LayoutConfig(
        max_documents=10,
        max_text_characters=4096,
        max_rows_per_shard=2,
        terms_per_shard=2,
        postings_per_row=2,
        max_query_terms=16,
    )


def _all_rows(root, relative: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for path in sorted((root / relative).glob("*.parquet")):
        result.extend(pq.read_table(path).to_pylist())
    return result


def test_tokenizer_is_code_aware_versioned_and_deterministic() -> None:
    assert CVEFIXES_BM25_TOKENIZER.endswith("/v1")
    assert tokenize_cvefixes_bm25(
        "ＣＶＥ-2026-0042 foo/bar foo_bar"
    ) == (
        "cve-2026-0042",
        "cve",
        "2026",
        "0042",
        "foo/bar",
        "foo",
        "bar",
        "foo_bar",
        "foo",
        "bar",
    )
    assert tokenize_cvefixes_bm25("Parser parser") == (
        "parser",
        "parser",
    )


def test_build_exports_skillcenter_layout_and_exact_meta_indexes(
    tmp_path,
) -> None:
    summary = build_cvefixes_bm25_hf_layout(
        list(reversed(_rows())), tmp_path, config=_config()
    )

    assert summary.document_count == 3
    assert summary.document_shard_count == 2
    assert summary.posting_shard_count > 1
    assert summary.term_count > 0
    assert summary.token_instance_count > summary.document_count
    assert summary.data_configs == {
        "bm25_documents": "data/bm25/documents/*.parquet",
        "bm25_postings": "data/bm25/postings/*.parquet",
    }
    assert summary.remote_index_configs == {
        "bm25_keyword_index": "indexes/bm25_keyword_shards.parquet"
    }
    fragment = summary.to_manifest_fragment()
    assert set(fragment["indexes"]) == {
        "bm25_document_chunks",
        "bm25_keyword_shards",
    }
    assert fragment["bm25"]["tokenizer"] == CVEFIXES_BM25_TOKENIZER
    assert fragment["counts"] == summary.counts

    document_index = pq.read_table(
        tmp_path / "indexes" / "bm25_document_chunks.parquet"
    )
    assert document_index.schema.names == [
        "cid",
        "end_document_index",
        "first_key",
        "kind",
        "last_key",
        "relative_path",
        "row_count",
        "schema_version",
        "sha256",
        "shard_id",
        "size_bytes",
        "start_document_index",
    ]
    keyword_index = pq.read_table(
        tmp_path / "indexes" / "bm25_keyword_shards.parquet"
    )
    assert keyword_index.schema.names == [
        *document_index.schema.names,
        "posting_count",
        "term_count",
        "token_instance_count",
    ]

    covered: set[str] = set()
    for row in document_index.to_pylist() + keyword_index.to_pylist():
        target = tmp_path / row["relative_path"]
        content = target.read_bytes()
        digest = hashlib.sha256(content).digest()
        assert row["sha256"] == digest.hex()
        assert row["cid"] == cid_v1_from_digest(digest)
        assert row["size_bytes"] == len(content)
        assert row["row_count"] == pq.ParquetFile(
            target
        ).metadata.num_rows
        assert row["schema_version"] == CVEFIXES_HF_META_SCHEMA_VERSION
        covered.add(row["relative_path"])
    assert covered == {
        path.relative_to(tmp_path).as_posix()
        for path in (tmp_path / "data" / "bm25").rglob("*.parquet")
    }


def test_documents_and_postings_preserve_reproducible_scoring_inputs(
    tmp_path,
) -> None:
    summary = build_cvefixes_bm25_hf_layout(
        _rows(), tmp_path, config=_config()
    )
    documents = _all_rows(tmp_path, "data/bm25/documents")
    postings = _all_rows(tmp_path, "data/bm25/postings")

    assert [row["document_index"] for row in documents] == [0, 1, 2]
    assert [(row["record_type"], row["entry_cid"]) for row in documents] == (
        sorted(
            (row["record_type"], row["record_id"]) for row in _rows()
        )
    )
    assert all(
        row["schema_version"]
        == CVEFIXES_HF_BM25_DOCUMENT_SCHEMA_VERSION
        for row in documents
    )
    assert all(
        row["document_length"]
        == row["title_length"] + row["body_length"]
        for row in documents
    )
    assert math.isclose(
        summary.average_document_length,
        sum(row["document_length"] for row in documents) / 3,
        rel_tol=0.0,
        abs_tol=1e-12,
    )

    parser_rows = [row for row in postings if row["term"] == "parser"]
    assert parser_rows
    assert [row["posting_chunk_index"] for row in parser_rows] == list(
        range(len(parser_rows))
    )
    document_indices = [
        index
        for row in parser_rows
        for index in row["document_indices"]
    ]
    title_frequencies = [
        frequency
        for row in parser_rows
        for frequency in row["title_frequencies"]
    ]
    body_frequencies = [
        frequency
        for row in parser_rows
        for frequency in row["body_frequencies"]
    ]
    assert document_indices == sorted(document_indices)
    assert len(document_indices) == 2
    assert sum(title_frequencies) >= 2
    assert sum(body_frequencies) >= 3
    assert all(
        row["schema_version"]
        == CVEFIXES_HF_BM25_POSTING_SCHEMA_VERSION
        and row["document_frequency"] == len(document_indices)
        and row["corpus_frequency"]
        == sum(title_frequencies) + sum(body_frequencies)
        and row["document_lengths"]
        == [
            documents[index]["document_length"]
            for index in row["document_indices"]
        ]
        for row in parser_rows
    )
    expected_idf = max(
        math.log(
            (len(documents) - len(document_indices) + 0.5)
            / (len(document_indices) + 0.5)
        ),
        1.0e-6,
    )
    assert all(
        math.isclose(
            row["idf"], expected_idf, rel_tol=0.0, abs_tol=1e-15
        )
        for row in parser_rows
    )


def test_build_is_byte_reproducible_without_explicit_document_indices(
    tmp_path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_summary = build_cvefixes_bm25_hf_layout(
        _rows(), first, config=_config()
    )
    second_summary = build_cvefixes_bm25_hf_layout(
        list(reversed(_rows())), second, config=_config()
    )

    assert first_summary.counts == second_summary.counts
    assert first_summary.indexes == second_summary.indexes
    first_files = {
        path.relative_to(first).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in first.rglob("*.parquet")
    }
    second_files = {
        path.relative_to(second).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in second.rglob("*.parquet")
    }
    assert first_files == second_files


def test_validation_fails_closed_for_tampered_shard(tmp_path) -> None:
    build_cvefixes_bm25_hf_layout(
        _rows(), tmp_path, config=_config()
    )
    shard = next(
        (tmp_path / "data" / "bm25" / "postings").glob("*.parquet")
    )
    content = bytearray(shard.read_bytes())
    content[-1] ^= 1
    shard.write_bytes(content)

    with pytest.raises(
        CVEfixesBM25LayoutError, match="descriptor differs"
    ):
        validate_cvefixes_bm25_hf_layout(
            tmp_path, config=_config()
        )


@pytest.mark.parametrize(
    "rows, match",
    [
        (
            [
                {**_rows()[0], "document_index": 0},
                _rows()[1],
            ],
            "present on every row",
        ),
        (
            [
                {**_rows()[0], "document_index": 0},
                {**_rows()[1], "document_index": 2},
            ],
            "contiguous from zero",
        ),
        (
            [
                _rows()[0],
                {
                    **_rows()[1],
                    "record_id": _rows()[0]["record_id"],
                },
            ],
            "duplicate entry CIDs",
        ),
    ],
)
def test_invalid_corpus_identity_or_order_is_rejected(
    tmp_path, rows, match
) -> None:
    with pytest.raises(CVEfixesBM25LayoutError, match=match):
        build_cvefixes_bm25_hf_layout(
            rows, tmp_path, config=_config()
        )

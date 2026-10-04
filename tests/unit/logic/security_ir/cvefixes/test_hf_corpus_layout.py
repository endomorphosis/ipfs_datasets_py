"""Tests for the standalone CVEfixes Hugging Face corpus layout."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.ir_core.identity import (
    canonical_identity,
    cid_v1_from_digest,
)
from ipfs_datasets_py.logic.security_ir.cvefixes.hf_corpus_layout import (
    CORPUS_COLUMNS,
    CORPUS_META_COLUMNS,
    CVEFIXES_HF_CORPUS_META_SCHEMA_VERSION,
    CVEFIXES_HF_CORPUS_SCHEMA_VERSION,
    CVEfixesHFCorpusIntegrityError,
    CVEfixesHFCorpusLayoutConfig,
    CVEfixesHFCorpusLayoutError,
    CVEfixesHFCorpusLimitError,
    build_cvefixes_hf_corpus_layout,
    read_cvefixes_hf_corpus_index,
    read_cvefixes_hf_corpus_layout,
    validate_cvefixes_hf_corpus_layout,
)


def _cid(label: str) -> str:
    return canonical_identity(
        {"label": label},
        domain="test/cvefixes-hf-corpus",
        schema_version="test/v1",
    ).cid


def _row(position: int) -> dict[str, object]:
    text = f"validate untrusted parser input before operation {position}"
    return {
        "document_index": position,
        "entry_cid": _cid(f"entry-{position}"),
        "node_cid": _cid(f"node-{position}"),
        "title": f"CVE repair evidence {position}",
        "text": text,
        "partition": "train",
        "shard_key": f"CVE-2026-{position:04d}",
        "kind": "code_unit",
        "authority": (
            "candidate" if position % 2 else "non_authoritative"
        ),
        "source_cids": [_cid(f"source-{position}")],
        "cwes": ["CWE-20"],
        "languages": ["c", "python"],
        "code_facts": ["bounds_checked", "input_validated"],
        "actions": ["reject", "validate"],
        "effects": ["invalid_input_rejected"],
        "policies": ["input_validation"],
        "graph_node": True,
        "grants_execution_authority": False,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "schema_version": CVEFIXES_HF_CORPUS_SCHEMA_VERSION,
    }


def _config(**overrides: object) -> CVEfixesHFCorpusLayoutConfig:
    values: dict[str, object] = {
        "max_documents": 16,
        "max_rows_per_shard": 2,
        "max_shards": 16,
        "max_text_characters": 1024,
        "max_text_utf8_bytes": 4096,
    }
    values.update(overrides)
    return CVEfixesHFCorpusLayoutConfig(**values)


def _artifact_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(
            (
                path
                for base in (root / "data" / "corpus", root / "indexes")
                for path in base.glob("*.parquet")
            ),
            key=lambda item: item.as_posix(),
        )
    }


def test_builds_exact_publisher_compatible_corpus_and_meta_index(
    tmp_path: Path,
) -> None:
    summary = build_cvefixes_hf_corpus_layout(
        [_row(2), _row(0), _row(1)],
        tmp_path,
        config=_config(),
    )

    assert summary.corpus_rows == 3
    assert summary.corpus_chunks == 2
    assert summary.counts == {"corpus_chunks": 2, "corpus_rows": 3}
    assert summary.configs == {
        "corpus": "data/corpus/*.parquet",
        "corpus_chunk_index": "indexes/corpus_chunks.parquet",
    }
    assert summary.indexes == {
        "corpus_chunks": summary.corpus_index.to_dict()
    }
    assert summary.corpus_index.config_name == "corpus_chunk_index"
    assert [item.config_name for item in summary.data_shards] == [
        "corpus",
        "corpus",
    ]
    assert {
        item["config_name"] for item in summary.artifact_inventory
    } == {"corpus", "corpus_chunk_index"}
    assert summary.to_manifest_fragment()["counts"] == summary.counts

    index = pq.read_table(tmp_path / "indexes/corpus_chunks.parquet")
    assert tuple(index.column_names) == CORPUS_META_COLUMNS
    assert index.schema.metadata == {
        b"schema_version": CVEFIXES_HF_CORPUS_META_SCHEMA_VERSION.encode()
    }
    meta_rows = index.to_pylist()
    assert [
        (
            row["shard_id"],
            row["start_document_index"],
            row["end_document_index"],
            row["row_count"],
        )
        for row in meta_rows
    ] == [(0, 0, 1, 2), (1, 2, 2, 1)]

    observed_documents: list[int] = []
    observed_entries: list[str] = []
    for meta in meta_rows:
        path = tmp_path / meta["relative_path"]
        content = path.read_bytes()
        digest = hashlib.sha256(content).digest()
        assert meta["sha256"] == digest.hex()
        assert meta["cid"] == cid_v1_from_digest(digest)
        assert meta["size_bytes"] == len(content)
        table = pq.read_table(path)
        assert tuple(table.column_names) == CORPUS_COLUMNS
        assert table.schema.metadata == {
            b"primary_key": b"entry_cid",
            b"schema_version": CVEFIXES_HF_CORPUS_SCHEMA_VERSION.encode(),
        }
        assert pa.types.is_int32(table.schema.field("document_index").type)
        assert pa.types.is_large_string(table.schema.field("text").type)
        assert pa.types.is_list(table.schema.field("source_cids").type)
        assert pa.types.is_boolean(
            table.schema.field("grants_execution_authority").type
        )
        parquet = pq.ParquetFile(path)
        assert {
            parquet.metadata.row_group(group).column(column).compression
            for group in range(parquet.num_row_groups)
            for column in range(
                parquet.metadata.row_group(group).num_columns
            )
        } == {"ZSTD"}
        observed_documents.extend(table["document_index"].to_pylist())
        observed_entries.extend(table["entry_cid"].to_pylist())
        assert meta["first_key"] == table["entry_cid"][0].as_py()
        assert meta["last_key"] == table["entry_cid"][-1].as_py()
    assert observed_documents == [0, 1, 2]
    assert observed_entries == [_row(index)["entry_cid"] for index in range(3)]


def test_read_and_verify_helpers_return_complete_immutable_rows(
    tmp_path: Path,
) -> None:
    built = build_cvefixes_hf_corpus_layout(
        [_row(0), _row(1), _row(2)],
        tmp_path,
        config=_config(),
    )
    verified = validate_cvefixes_hf_corpus_layout(
        tmp_path, config=_config()
    )
    rows = read_cvefixes_hf_corpus_layout(
        tmp_path, config=_config()
    )
    index = read_cvefixes_hf_corpus_index(
        tmp_path, config=_config()
    )

    assert verified.counts == built.counts
    assert [row["document_index"] for row in rows] == [0, 1, 2]
    assert sum(row["row_count"] for row in index) == len(rows)
    with pytest.raises(TypeError):
        rows[0]["authority"] = "candidate"


def test_corpus_layout_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    build_cvefixes_hf_corpus_layout(
        [_row(0), _row(1), _row(2)],
        first,
        config=_config(),
    )
    build_cvefixes_hf_corpus_layout(
        [_row(2), _row(1), _row(0)],
        second,
        config=_config(),
    )

    assert _artifact_bytes(first) == _artifact_bytes(second)


@pytest.mark.parametrize(
    ("mutate", "error", "match"),
    [
        (
            lambda row: row.pop("title"),
            CVEfixesHFCorpusLayoutError,
            "fields differ",
        ),
        (
            lambda row: row.update(text_sha256="0" * 64),
            CVEfixesHFCorpusIntegrityError,
            "differs from text",
        ),
        (
            lambda row: row.update(grants_execution_authority=True),
            CVEfixesHFCorpusLayoutError,
            "never grant",
        ),
        (
            lambda row: row.update(entry_cid="b" + "z" * 58),
            CVEfixesHFCorpusLayoutError,
            "release CID profile",
        ),
        (
            lambda row: row.update(authority="authoritative"),
            CVEfixesHFCorpusLayoutError,
            "candidate or non_authoritative",
        ),
        (
            lambda row: row.update(actions=["validate", "reject"]),
            CVEfixesHFCorpusLayoutError,
            "canonical sorted order",
        ),
    ],
)
def test_unsafe_or_noncanonical_rows_fail_closed(
    tmp_path: Path, mutate, error, match: str
) -> None:
    row = _row(0)
    mutate(row)
    with pytest.raises(error, match=match):
        build_cvefixes_hf_corpus_layout(
            [row], tmp_path, config=_config()
        )


def test_dense_indices_and_unique_entry_cids_are_required(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        CVEfixesHFCorpusLayoutError, match="dense from zero"
    ):
        build_cvefixes_hf_corpus_layout(
            [_row(0), _row(2)], tmp_path / "gap", config=_config()
        )
    duplicate = _row(1)
    duplicate["entry_cid"] = _row(0)["entry_cid"]
    with pytest.raises(
        CVEfixesHFCorpusLayoutError, match="duplicate entry CIDs"
    ):
        build_cvefixes_hf_corpus_layout(
            [_row(0), duplicate],
            tmp_path / "duplicate",
            config=_config(),
        )


def test_text_is_bounded_by_characters_and_utf8_bytes(
    tmp_path: Path,
) -> None:
    row = _row(0)
    text = "é" * 8
    row["text"] = text
    row["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
    with pytest.raises(
        CVEfixesHFCorpusLimitError, match="UTF-8 byte limit"
    ):
        build_cvefixes_hf_corpus_layout(
            [row],
            tmp_path,
            config=_config(
                max_text_characters=8,
                max_text_utf8_bytes=8,
            ),
        )


def test_validation_rejects_tampering_and_unindexed_files(
    tmp_path: Path,
) -> None:
    build_cvefixes_hf_corpus_layout(
        [_row(0), _row(1), _row(2)],
        tmp_path,
        config=_config(),
    )
    shard = tmp_path / "data/corpus/part-000000.parquet"
    content = bytearray(shard.read_bytes())
    content[-1] ^= 1
    shard.write_bytes(content)
    with pytest.raises(
        CVEfixesHFCorpusIntegrityError, match="descriptor differs"
    ):
        validate_cvefixes_hf_corpus_layout(
            tmp_path, config=_config()
        )

    # Rebuild the valid family, then prove that unindexed material is rejected.
    build_cvefixes_hf_corpus_layout(
        [_row(0), _row(1), _row(2)],
        tmp_path,
        config=_config(),
    )
    (tmp_path / "data/corpus/part-999999.parquet").write_bytes(
        (tmp_path / "data/corpus/part-000000.parquet").read_bytes()
    )
    with pytest.raises(
        CVEfixesHFCorpusIntegrityError,
        match="does not cover data shards exactly",
    ):
        validate_cvefixes_hf_corpus_layout(
            tmp_path, config=_config()
        )


def test_failed_rebuild_preserves_existing_layout_and_other_families(
    tmp_path: Path,
) -> None:
    build_cvefixes_hf_corpus_layout(
        [_row(0), _row(1)],
        tmp_path,
        config=_config(),
    )
    unrelated = tmp_path / "data/vectors/part-000000.parquet"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"owned by vector layout")
    before = _artifact_bytes(tmp_path)
    invalid = _row(0)
    invalid["text_sha256"] = "f" * 64

    with pytest.raises(CVEfixesHFCorpusIntegrityError):
        build_cvefixes_hf_corpus_layout(
            [invalid], tmp_path, config=_config()
        )

    assert _artifact_bytes(tmp_path) == before
    assert unrelated.read_bytes() == b"owned by vector layout"

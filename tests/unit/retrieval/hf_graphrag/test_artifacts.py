"""Unit tests for shared bounded HF GraphRAG artifact schemas and writers.

USCIR-009 acceptance: writers enforce 4,096 rows/pointers, stable
tie-breakers, confined paths, row/byte/hash descriptors, cleanup on
failure, and deterministic fixture output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import (
    ARTIFACT_WRITER_SCHEMA_VERSION,
    ArtifactIntegrityError,
    ArtifactWriterConfig,
    StagingSession,
    atomic_staging,
    atomic_write_bytes,
    build_fixture_rows,
    confine_path,
    describe_file,
    file_digest,
    verify_descriptor,
    write_bounded_shards,
    write_fixture_release,
    write_pointer_cells,
    write_zstd_parquet,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    COMPACT_INDEX_SCHEMA_VERSION,
    DESCRIPTOR_SCHEMA_VERSION,
    MAX_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    SCHEMA_VERSION,
    ArtifactDescriptor,
    ArtifactFamily,
    ArtifactPathError,
    CompactIndexRow,
    InvalidDigestError,
    PhysicalBoundError,
    SortKeyError,
    chunk_pointers,
    content_sha256,
    example_compact_index_payload,
    example_descriptor_payload,
    normalize_relative_artifact_path,
    normalize_sha256,
    part_filename,
    physical_bounds_policy,
    shard_sequence,
    stable_sort_rows,
    validate_physical_pointer_count,
    validate_physical_row_count,
)


# ---------------------------------------------------------------------------
# Schema constants and descriptors
# ---------------------------------------------------------------------------


def test_physical_bounds_are_4096():
    bounds = physical_bounds_policy()
    assert bounds["max_rows_per_physical_shard"] == 4096
    assert bounds["max_pointers_per_row"] == 4096
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_POINTERS_PER_ROW == 4096
    assert SCHEMA_VERSION.startswith("hf-graphrag")
    assert DESCRIPTOR_SCHEMA_VERSION.startswith("hf-graphrag")
    assert COMPACT_INDEX_SCHEMA_VERSION.startswith("hf-graphrag")


def test_example_descriptor_and_compact_index_round_trip():
    descriptor = ArtifactDescriptor.from_mapping(example_descriptor_payload())
    assert descriptor.row_count == 2
    assert descriptor.relative_path == "data/corpus/part-000000.parquet"
    assert len(descriptor.sha256) == 64
    again = ArtifactDescriptor.from_mapping(descriptor.to_dict())
    assert again.to_dict() == descriptor.to_dict()

    index_row = CompactIndexRow.from_mapping(example_compact_index_payload())
    assert index_row.shard_id == 0
    assert index_row.first_key == "entry-a"
    assert CompactIndexRow.from_mapping(index_row.to_dict()).to_dict()[
        "relative_path"
    ] == index_row.relative_path


def test_descriptor_rejects_oversize_row_count():
    payload = example_descriptor_payload()
    payload["row_count"] = MAX_ROWS_PER_PHYSICAL_SHARD + 1
    with pytest.raises(PhysicalBoundError):
        ArtifactDescriptor.from_mapping(payload)


def test_descriptor_rejects_invalid_digest_and_absolute_path():
    payload = example_descriptor_payload()
    payload["sha256"] = "deadbeef"
    with pytest.raises(InvalidDigestError):
        ArtifactDescriptor.from_mapping(payload)

    payload = example_descriptor_payload()
    payload["relative_path"] = "/tmp/escape.parquet"
    with pytest.raises(ArtifactPathError):
        ArtifactDescriptor.from_mapping(payload)

    payload = example_descriptor_payload()
    payload["relative_path"] = "../escape.parquet"
    with pytest.raises(ArtifactPathError):
        ArtifactDescriptor.from_mapping(payload)


# ---------------------------------------------------------------------------
# Paths, digests, sharding, and tie-breakers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/abs/path",
        "C:/windows/path",
        "foo\\bar",
        "a/../b",
        "./x",
        "data/.git/config",
        "",
    ],
)
def test_normalize_relative_path_rejects_unsafe(path: str):
    with pytest.raises((ArtifactPathError, Exception)):
        normalize_relative_artifact_path(path)


def test_normalize_relative_path_accepts_confined_posix():
    assert (
        normalize_relative_artifact_path("data/corpus/part-000000.parquet")
        == "data/corpus/part-000000.parquet"
    )


def test_sha256_normalization():
    digest = content_sha256("x")
    assert normalize_sha256(digest) == digest
    assert normalize_sha256(f"sha256:{digest}") == digest
    with pytest.raises(InvalidDigestError):
        normalize_sha256("not-a-digest")


def test_shard_sequence_enforces_4096():
    values = list(range(5000))
    shards = shard_sequence(values)
    assert all(len(shard) <= 4096 for shard in shards)
    assert sum(len(shard) for shard in shards) == 5000
    assert len(shards[0]) == 4096
    assert len(shards[1]) == 5000 - 4096

    with pytest.raises(PhysicalBoundError):
        shard_sequence(values, max_rows=MAX_ROWS_PER_PHYSICAL_SHARD + 1)


def test_chunk_pointers_enforces_4096():
    pointers = list(range(5000))
    cells = chunk_pointers(pointers)
    assert all(len(cell) <= 4096 for cell in cells)
    assert sum(len(cell) for cell in cells) == 5000
    assert write_pointer_cells(pointers) == cells

    with pytest.raises(PhysicalBoundError):
        validate_physical_pointer_count(4097)
    with pytest.raises(PhysicalBoundError):
        chunk_pointers(pointers, max_pointers=MAX_POINTERS_PER_ROW + 1)


def test_stable_sort_tie_breakers_are_deterministic():
    rows = [
        {"score": 0.5, "entry_cid": "b"},
        {"score": 0.9, "entry_cid": "a"},
        {"score": 0.9, "entry_cid": "c"},
        {"score": 0.5, "entry_cid": "a"},
    ]
    ordered = stable_sort_rows(
        rows,
        primary_keys=("score",),
        tie_breakers=("entry_cid",),
        descending=("score",),
    )
    assert [row["entry_cid"] for row in ordered] == ["a", "c", "a", "b"]
    # Equal scores resolve by entry_cid ascending (a before c, a before b).
    assert ordered[0]["score"] == 0.9 and ordered[0]["entry_cid"] == "a"
    assert ordered[1]["score"] == 0.9 and ordered[1]["entry_cid"] == "c"

    # Input order must not affect the result.
    reversed_order = stable_sort_rows(
        list(reversed(rows)),
        primary_keys=("score",),
        tie_breakers=("entry_cid",),
        descending=("score",),
    )
    assert [row["entry_cid"] for row in reversed_order] == [
        row["entry_cid"] for row in ordered
    ]


def test_stable_sort_requires_keys_and_fields():
    with pytest.raises(SortKeyError):
        stable_sort_rows([{"a": 1}], primary_keys=(), tie_breakers=())
    with pytest.raises(SortKeyError):
        stable_sort_rows([{"a": 1}], primary_keys=("missing",))


def test_part_filename_is_zero_padded():
    assert part_filename(0) == "part-000000.parquet"
    assert part_filename(12) == "part-000012.parquet"


# ---------------------------------------------------------------------------
# Writers: bounds, descriptors, confinement, cleanup, determinism
# ---------------------------------------------------------------------------


def test_write_zstd_parquet_enforces_row_bound(tmp_path: Path):
    pytest.importorskip("pyarrow")
    rows = [{"entry_cid": f"e-{i}", "document_index": i} for i in range(10)]
    path = tmp_path / "ok.parquet"
    written = write_zstd_parquet(path, rows, max_rows=16)
    assert written == 10
    assert path.is_file()

    oversize = [{"entry_cid": f"e-{i}", "document_index": i} for i in range(5)]
    with pytest.raises(PhysicalBoundError):
        write_zstd_parquet(tmp_path / "bad.parquet", oversize, max_rows=4)
    assert not (tmp_path / "bad.parquet").exists()
    # Partial files must not remain after failure.
    assert not list(tmp_path.glob(".*.partial"))


def test_write_bounded_shards_enforces_4096_and_descriptors(tmp_path: Path):
    pytest.importorskip("pyarrow")
    # 5 rows, max 2 per shard => 3 shards with stable document_index order.
    rows = list(reversed(build_fixture_rows(5)))
    result = write_bounded_shards(
        rows,
        root=tmp_path,
        data_dir="data/corpus",
        index_path="indexes/corpus_chunks.parquet",
        family=ArtifactFamily.CORPUS,
        primary_keys=("document_index",),
        tie_breakers=("entry_cid",),
        key_fields=("entry_cid",),
        config=ArtifactWriterConfig(max_rows_per_shard=2),
    )
    assert result.total_rows == 5
    assert len(result.data_descriptors) == 3
    assert all(item.row_count <= 2 for item in result.data_descriptors)
    assert all(item.row_count <= MAX_ROWS_PER_PHYSICAL_SHARD for item in result.data_descriptors)
    # Descriptors carry relative path + rows + bytes + hash.
    for item in result.data_descriptors:
        assert item.relative_path.startswith("data/corpus/part-")
        assert item.size_bytes > 0
        assert len(item.sha256) == 64
        assert item.content_cid is not None
        verify_descriptor(tmp_path, item)

    assert result.compact_index_descriptor is not None
    verify_descriptor(tmp_path, result.compact_index_descriptor)
    assert len(result.compact_index_rows) == 3
    # Sorted order: first shard starts at entry-000000.
    assert result.compact_index_rows[0].first_key == "entry-000000"
    assert result.compact_index_rows[0].row_count == 2
    assert result.compact_index_rows[-1].row_count == 1


def test_writer_config_rejects_oversize_bounds():
    with pytest.raises(PhysicalBoundError):
        ArtifactWriterConfig(max_rows_per_shard=MAX_ROWS_PER_PHYSICAL_SHARD + 1)
    with pytest.raises(PhysicalBoundError):
        ArtifactWriterConfig(max_pointers_per_row=MAX_POINTERS_PER_ROW + 1)


def test_confine_path_rejects_escape(tmp_path: Path):
    with pytest.raises(ArtifactPathError):
        confine_path(tmp_path, "../outside.parquet")
    with pytest.raises(ArtifactPathError):
        confine_path(tmp_path, "/etc/passwd")
    target = confine_path(tmp_path, "data/ok.parquet")
    assert target == (tmp_path / "data" / "ok.parquet").resolve() or str(
        target
    ).endswith("data/ok.parquet")


def test_atomic_write_bytes_cleans_partial_on_failure(tmp_path: Path, monkeypatch):
    target = tmp_path / "out.bin"
    real_replace = __import__("os").replace

    def boom(src, dst):  # noqa: ANN001
        raise OSError("simulated replace failure")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        atomic_write_bytes(target, b"payload")
    assert not target.exists()
    assert not list(tmp_path.glob(".*.partial"))
    monkeypatch.setattr("os.replace", real_replace)
    atomic_write_bytes(target, b"payload")
    assert target.read_bytes() == b"payload"


def test_atomic_staging_cleanup_on_failure(tmp_path: Path):
    pytest.importorskip("pyarrow")
    staging_dirs_before = set(tmp_path.glob(".hf-graphrag-stage-*"))
    with pytest.raises(RuntimeError):
        with atomic_staging(tmp_path) as session:
            path = session.confine("data/partial.parquet")
            write_zstd_parquet(
                path,
                [{"entry_cid": "a", "document_index": 0}],
                max_rows=16,
            )
            assert path.is_file()
            raise RuntimeError("force failure")
    staging_dirs_after = set(tmp_path.glob(".hf-graphrag-stage-*"))
    assert staging_dirs_after == staging_dirs_before
    # No leaked data under the release root.
    assert not (tmp_path / "data").exists() or not any(
        (tmp_path / "data").rglob("*.parquet")
    )


def test_write_bounded_shards_cleanup_on_failure(tmp_path: Path, monkeypatch):
    pytest.importorskip("pyarrow")
    rows = build_fixture_rows(4)

    original = write_zstd_parquet
    calls = {"n": 0}

    def flaky(path, rows, **kwargs):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("simulated mid-write failure")
        return original(path, rows, **kwargs)

    monkeypatch.setattr(
        "ipfs_datasets_py.retrieval.hf_graphrag.artifacts.write_zstd_parquet",
        flaky,
    )
    with pytest.raises(RuntimeError):
        write_bounded_shards(
            rows,
            root=tmp_path,
            data_dir="data/corpus",
            index_path="indexes/corpus_chunks.parquet",
            primary_keys=("document_index",),
            config=ArtifactWriterConfig(max_rows_per_shard=2),
        )
    # Staging cleaned and no committed corpus shards.
    assert not list(tmp_path.glob(".hf-graphrag-stage-*"))
    corpus = tmp_path / "data" / "corpus"
    assert not corpus.exists() or not list(corpus.glob("*.parquet"))
    assert not (tmp_path / "indexes" / "corpus_chunks.parquet").exists()


def test_fixture_output_is_deterministic(tmp_path: Path):
    pytest.importorskip("pyarrow")
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    summary_a = write_fixture_release(root_a, row_count=5, max_rows_per_shard=2)
    summary_b = write_fixture_release(root_b, row_count=5, max_rows_per_shard=2)

    # Logical fixture summary is path-root-independent and timestamp-free.
    def logical(summary: dict) -> dict:
        payload = json.loads(json.dumps(summary, sort_keys=True))
        return payload

    assert logical(summary_a) == logical(summary_b)
    assert summary_a["fixture_schema_version"] == ARTIFACT_WRITER_SCHEMA_VERSION
    assert summary_a["result"]["total_rows"] == 5
    assert len(summary_a["result"]["data_shards"]) == 3

    # Byte-identical Parquet shards across independent roots.
    for relative in (
        "data/corpus/part-000000.parquet",
        "data/corpus/part-000001.parquet",
        "data/corpus/part-000002.parquet",
        "indexes/corpus_chunks.parquet",
        "fixture_summary.json",
    ):
        a = (root_a / relative).read_bytes()
        b = (root_b / relative).read_bytes()
        assert a == b, relative
        assert content_sha256(a) == content_sha256(b)


def test_describe_and_verify_file(tmp_path: Path):
    path = tmp_path / "data" / "sample.bin"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"hello-artifact")
    size, digest = file_digest(path)
    descriptor = describe_file(
        path,
        root=tmp_path,
        row_count=0,
        family=ArtifactFamily.REPORT,
        media_type="application/octet-stream",
    )
    assert descriptor.size_bytes == size
    assert descriptor.sha256 == digest.hex()
    assert descriptor.relative_path == "data/sample.bin"
    verify_descriptor(tmp_path, descriptor)

    # Tamper then fail closed.
    path.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError):
        verify_descriptor(tmp_path, descriptor)


def test_validate_physical_row_count_bound():
    assert validate_physical_row_count(0) == 0
    assert validate_physical_row_count(4096) == 4096
    with pytest.raises(PhysicalBoundError):
        validate_physical_row_count(4097)


def test_staging_session_commit_file(tmp_path: Path):
    pytest.importorskip("pyarrow")
    with atomic_staging(tmp_path) as session:
        assert isinstance(session, StagingSession)
        staged = session.confine("reports/note.json")
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text('{"ok":true}', encoding="utf-8")
        final = session.commit_file("reports/note.json")
        assert final.is_file()
        assert final.read_text(encoding="utf-8") == '{"ok":true}'
        session.mark_committed()
    assert (tmp_path / "reports" / "note.json").is_file()

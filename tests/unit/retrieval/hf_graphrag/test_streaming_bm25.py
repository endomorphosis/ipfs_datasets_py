"""Focused restart/integrity tests for the shared streaming BM25 writer."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.retrieval.hf_graphrag import streaming_bm25
from ipfs_datasets_py.retrieval.hf_graphrag.streaming_bm25 import (
    CHECKPOINT_FILENAME,
    StreamingBM25Error,
    StreamingMultiFieldBM25Config,
    StreamingMultiFieldBM25Profile,
    StreamingMultiFieldDocument,
    write_streaming_multifield_bm25_layout,
)


class OneShot(Iterable[Mapping[str, Any]]):
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.iterations = 0

    def __iter__(self) -> Iterator[Mapping[str, Any]]:
        self.iterations += 1
        if self.iterations > 1:
            raise AssertionError("source was traversed more than once")
        yield from self.rows


class ExplodingSource(Iterable[Mapping[str, Any]]):
    def __iter__(self) -> Iterator[Mapping[str, Any]]:
        raise AssertionError("verified checkpoint unexpectedly consumed source")
        yield  # pragma: no cover


_PROJECT_CALLS = 0
_PROJECT_MUST_NOT_RUN = False


def _identity(row: Mapping[str, Any]) -> str:
    return str(row["entry_cid"])


def _order(row: Mapping[str, Any]) -> tuple[int, str]:
    return int(row["order"]), str(row["entry_cid"])


def _project(
    row: Mapping[str, Any], document_index: int
) -> StreamingMultiFieldDocument:
    global _PROJECT_CALLS
    if _PROJECT_MUST_NOT_RUN:
        raise AssertionError("verified projection checkpoint was recomputed")
    _PROJECT_CALLS += 1
    return StreamingMultiFieldDocument(
        entry_cid=str(row["entry_cid"]),
        chunk_cid=str(row["chunk_cid"]),
        field_terms={
            "title": str(row["title"]).lower().split(),
            "body": str(row["body"]).lower().split(),
        },
        payload={"label": str(row["label"])},
    )


def _schema(pa: Any, profile: StreamingMultiFieldBM25Profile) -> Any:
    return pa.schema(
        [
            ("schema_version", pa.string(), False),
            ("document_index", pa.int64(), False),
            ("route_key", pa.string(), False),
            ("entry_cid", pa.string(), False),
            ("chunk_cid", pa.string(), False),
            ("document_length", pa.int64(), False),
            ("title_length", pa.int64(), False),
            ("body_length", pa.int64(), False),
            ("label", pa.string(), False),
        ],
        metadata={b"schema_version": profile.document_schema_version.encode("ascii")},
    )


def _profile() -> StreamingMultiFieldBM25Profile:
    return StreamingMultiFieldBM25Profile(
        field_names=("title", "body"),
        field_weights={"title": 2.0, "body": 1.0},
        query_title_fields=("title",),
        query_body_fields=("body",),
        tokenizer_id="fixture-tokenizer/v1",
        document_schema_version="fixture-document/v1",
        posting_schema_version="fixture-posting/v1",
        config_digest="c" * 64,
    )


def _config(*, max_rows_per_shard: int = 2) -> StreamingMultiFieldBM25Config:
    return StreamingMultiFieldBM25Config(
        max_records_in_memory=2,
        max_rows_per_shard=max_rows_per_shard,
        postings_per_row=2,
        max_routing_rows=16,
    )


def _rows() -> list[dict[str, Any]]:
    return [
        {
            "body": "statute court",
            "chunk_cid": "chunk-c",
            "entry_cid": "entry-c",
            "label": "C",
            "order": 3,
            "title": "Public Law",
        },
        {
            "body": "agency rule statute",
            "chunk_cid": "chunk-a",
            "entry_cid": "entry-a",
            "label": "A",
            "order": 1,
            "title": "State Code",
        },
        {
            "body": "court code",
            "chunk_cid": "chunk-b",
            "entry_cid": "entry-b",
            "label": "B",
            "order": 2,
            "title": "Civil Law",
        },
    ]


def _write(
    source: Iterable[Mapping[str, Any]],
    output: Path,
    checkpoint: Path,
    *,
    source_digest: str = "a" * 64,
    config: StreamingMultiFieldBM25Config | None = None,
    resume: bool,
):
    return write_streaming_multifield_bm25_layout(
        source,
        output,
        profile=_profile(),
        config=config or _config(),
        identity_key=_identity,
        order_key=_order,
        project_document=_project,
        document_schema_factory=_schema,
        checkpoint_dir=checkpoint,
        source_digest=source_digest,
        resume=resume,
    )


@pytest.fixture(autouse=True)
def _reset_projector_state():
    global _PROJECT_CALLS, _PROJECT_MUST_NOT_RUN
    _PROJECT_CALLS = 0
    _PROJECT_MUST_NOT_RUN = False
    yield
    _PROJECT_CALLS = 0
    _PROJECT_MUST_NOT_RUN = False


def test_completed_checkpoint_reuses_verified_outputs_without_source(
    tmp_path: Path,
) -> None:
    source = OneShot(_rows())
    first = _write(
        source,
        tmp_path / "release",
        tmp_path / "checkpoint",
        resume=True,
    )
    assert source.iterations == 1
    assert _PROJECT_CALLS == len(_rows())
    assert first.executed_stages == (
        "documents",
        "pointers",
        "posting_fields",
        "projection",
        "publication",
        "source_identity",
        "source_spool",
        "term_stats",
    )

    global _PROJECT_MUST_NOT_RUN
    _PROJECT_MUST_NOT_RUN = True
    second = _write(
        ExplodingSource(),
        tmp_path / "release",
        tmp_path / "checkpoint",
        resume=True,
    )

    assert second.executed_stages == ()
    assert "publication" in second.resumed_stages
    assert second.index_root_cid == first.index_root_cid
    assert second.source_root_cid == first.source_root_cid
    assert second.descriptors == first.descriptors


def test_restart_after_publication_failure_reuses_projection_and_sorts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = streaming_bm25.write_zstd_parquet
    calls = 0

    def fail_first_publication(*args: Any, **kwargs: Any):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated publication interruption")
        return original(*args, **kwargs)

    monkeypatch.setattr(streaming_bm25, "write_zstd_parquet", fail_first_publication)
    source = OneShot(_rows())
    with pytest.raises(RuntimeError, match="simulated publication interruption"):
        _write(
            source,
            tmp_path / "release",
            tmp_path / "checkpoint",
            resume=True,
        )
    assert source.iterations == 1
    assert _PROJECT_CALLS == len(_rows())
    checkpoint = json.loads(
        (tmp_path / "checkpoint" / CHECKPOINT_FILENAME).read_text(encoding="utf-8")
    )
    assert checkpoint["status"] == "building"
    assert set(checkpoint["stages"]) == {
        "documents",
        "pointers",
        "posting_fields",
        "projection",
        "source_identity",
        "source_spool",
        "term_stats",
    }

    monkeypatch.setattr(streaming_bm25, "write_zstd_parquet", original)
    global _PROJECT_MUST_NOT_RUN
    _PROJECT_MUST_NOT_RUN = True
    resumed = _write(
        ExplodingSource(),
        tmp_path / "release",
        tmp_path / "checkpoint",
        resume=True,
    )

    assert resumed.executed_stages == ("publication",)
    assert set(resumed.resumed_stages) == set(checkpoint["stages"])
    assert resumed.document_count == len(_rows())


def test_interrupted_external_sort_resumes_only_from_verified_source_spool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = streaming_bm25.external_sort_to_file
    interrupted = False

    def interrupt_identity_sort(
        records: Iterable[Mapping[str, Any]],
        output_path: str | Path,
        **kwargs: Any,
    ):
        nonlocal interrupted
        if not interrupted and Path(output_path).name == "identity-sorted.jsonl":
            interrupted = True
            return original(
                records,
                output_path,
                interrupt_after_runs=1,
                **kwargs,
            )
        return original(records, output_path, **kwargs)

    monkeypatch.setattr(
        streaming_bm25, "external_sort_to_file", interrupt_identity_sort
    )
    source = OneShot(_rows())
    with pytest.raises(StreamingBM25Error, match="source_identity sort interrupted"):
        _write(
            source,
            tmp_path / "release",
            tmp_path / "checkpoint",
            resume=True,
        )
    assert source.iterations == 1
    checkpoint = json.loads(
        (tmp_path / "checkpoint" / CHECKPOINT_FILENAME).read_text(encoding="utf-8")
    )
    assert checkpoint["stages"]["source_spool"]["status"] == "complete"
    assert checkpoint["stages"]["source_identity"]["status"] == "building"

    monkeypatch.setattr(streaming_bm25, "external_sort_to_file", original)
    resumed = _write(
        ExplodingSource(),
        tmp_path / "release",
        tmp_path / "checkpoint",
        resume=True,
    )

    assert resumed.document_count == len(_rows())
    assert {"source_identity", "source_spool"}.issubset(resumed.resumed_stages)
    assert int(resumed.sort_receipts["source_identity"]["run_count"]) >= 2


@pytest.mark.parametrize(
    ("source_digest", "config"),
    [
        ("b" * 64, _config()),
        ("a" * 64, _config(max_rows_per_shard=3)),
    ],
)
def test_resume_rejects_source_or_config_drift_before_source_iteration(
    tmp_path: Path,
    source_digest: str,
    config: StreamingMultiFieldBM25Config,
) -> None:
    _write(
        OneShot(_rows()),
        tmp_path / "release",
        tmp_path / "checkpoint",
        resume=True,
    )

    with pytest.raises(
        StreamingBM25Error,
        match="does not match the active source/profile/config",
    ):
        _write(
            ExplodingSource(),
            tmp_path / "release",
            tmp_path / "checkpoint",
            source_digest=source_digest,
            config=config,
            resume=True,
        )


def test_resume_rejects_modified_checkpoint_stage_instead_of_recomputing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = streaming_bm25.write_zstd_parquet

    def interrupt(*args: Any, **kwargs: Any):
        raise RuntimeError("stop before publication")

    monkeypatch.setattr(streaming_bm25, "write_zstd_parquet", interrupt)
    with pytest.raises(RuntimeError, match="stop before publication"):
        _write(
            OneShot(_rows()),
            tmp_path / "release",
            tmp_path / "checkpoint",
            resume=True,
        )
    projection = tmp_path / "checkpoint" / "work" / "projected-documents.jsonl"
    with projection.open("ab") as handle:
        handle.write(b"tampered\n")
    monkeypatch.setattr(streaming_bm25, "write_zstd_parquet", original)

    with pytest.raises(StreamingBM25Error, match="projection.*digest mismatch"):
        _write(
            ExplodingSource(),
            tmp_path / "release",
            tmp_path / "checkpoint",
            resume=True,
        )


def test_completed_resume_rejects_modified_published_artifact(tmp_path: Path) -> None:
    first = _write(
        OneShot(_rows()),
        tmp_path / "release",
        tmp_path / "checkpoint",
        resume=True,
    )
    target = tmp_path / "release" / first.document_descriptors[0].relative_path
    with target.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(StreamingBM25Error, match="failed verification"):
        _write(
            ExplodingSource(),
            tmp_path / "release",
            tmp_path / "checkpoint",
            resume=True,
        )


def test_resume_requires_explicit_sha256_bound_checkpoint(tmp_path: Path) -> None:
    with pytest.raises(StreamingBM25Error, match="source_digest is required"):
        write_streaming_multifield_bm25_layout(
            OneShot(_rows()),
            tmp_path / "release",
            profile=_profile(),
            config=_config(),
            identity_key=_identity,
            order_key=_order,
            project_document=_project,
            document_schema_factory=_schema,
            checkpoint_dir=tmp_path / "checkpoint",
            resume=True,
        )

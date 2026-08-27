"""Focused tests for the persisted canonical state-law chunk corpus."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.open_us_law_embeddings import (
    PINNED_TOKEN_COUNTER_ID,
    deterministic_project,
    fixture_embedding_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    fixture_bm25_config,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    write_state_laws_bm25_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_chunk_physical import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    CANONICAL_DOCUMENT_ORDER,
    CHUNK_INDEX_PATH,
    STREAMING_CHUNK_STORE_PRODUCTION_READY,
    StateLawsChunkPhysicalError,
    write_state_laws_chunk_physical_layout,
)
from ipfs_datasets_py.processors.legal_data.state_laws_chunker import (
    StateLawsChunker,
)
from ipfs_datasets_py.processors.legal_data.state_laws_corpus_physical import (
    write_state_laws_corpus_physical_layout_from_iterable,
)
from ipfs_datasets_py.processors.legal_data.state_laws_embedding_store import (
    build_state_laws_embedding_store,
)
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    AdmissionStatus,
    CorpusRecord,
    SourceAuthorityClass,
    SourceReceiptRecord,
    VerificationResult,
)
from ipfs_datasets_py.retrieval.hf_graphrag.artifacts import verify_descriptor

RELEASE_POINT = "state-laws-v2-2026-08-24"
TOKEN_COUNTER_ID = PINNED_TOKEN_COUNTER_ID


def _model_token_counter(text: str) -> int:
    return len(text.split())


def _sha(seed: str, *, prefixed: bool = False) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"sha256:{digest}" if prefixed else digest


def _record(ordinal: int, text: str) -> CorpusRecord:
    return CorpusRecord(
        entry_cid=_sha(f"entry-{ordinal}", prefixed=True),
        legal_id=f"state:AL:code:1:{ordinal}",
        source_cid=_sha(f"source-cid-{ordinal}", prefixed=True),
        jurisdiction="AL",
        code_family="code",
        section=str(ordinal),
        admission_status=AdmissionStatus.ADMITTED,
        admission_reason="verified official full-frontier acquisition",
        release_point=RELEASE_POINT,
        source_checksum=_sha("source-AL"),
        verification_result=VerificationResult.VERIFIED,
        acquisition_time="2026-08-24T00:00:00Z",
        official_source_url="https://legislature.al.gov/code",
        acquisition_receipt_id="scrape-al-sealed",
        parser_version="state-law-parser-v2",
        text=text,
        title="1",
    )


def _receipt(row_count: int) -> SourceReceiptRecord:
    checksum = _sha("source-AL")
    return SourceReceiptRecord(
        receipt_id="scrape-al-sealed",
        jurisdiction="AL",
        official_source_url="https://legislature.al.gov/code",
        release_point=RELEASE_POINT,
        observation_time="2026-08-24T00:00:00Z",
        source_authority_class=SourceAuthorityClass.OFFICIAL,
        source_checksum=checksum,
        verification_result=VerificationResult.VERIFIED,
        discovered=row_count,
        fetched=row_count,
        excluded=0,
        quarantined=0,
        failed_final=0,
        frontier_closed=True,
        relative_path="receipts/scrape/al.json",
        start_urls=("https://legislature.al.gov/code",),
        content_hashes=(checksum,),
        payload={
            "adapter_input_row_count": row_count,
            "admission_eligible": True,
            "qualification_reasons": [],
            "reported_canonical_row_count": row_count,
        },
    )


class _OneShotRecords:
    def __init__(self, rows: list[CorpusRecord]) -> None:
        self.rows = rows
        self.iterations = 0

    def __iter__(self) -> Iterator[CorpusRecord]:
        self.iterations += 1
        if self.iterations != 1:
            raise AssertionError("normalized source was consumed more than once")
        yield from self.rows


def _corpus(tmp_path: Path, records: list[CorpusRecord]):
    source = _OneShotRecords(records)
    layout = write_state_laws_corpus_physical_layout_from_iterable(
        source,
        source_receipts=[_receipt(len(records))],
        output_dir=tmp_path,
        max_rows_per_shard=2,
        max_records_in_memory=2,
    )
    assert source.iterations == 1
    return layout


def _long_text(section: int) -> str:
    return (
        f"Section {section}. (a) Alpha beta gamma delta epsilon zeta eta theta. "
        "(b) Iota kappa lambda mu nu xi omicron pi. "
        "(c) Rho sigma tau upsilon phi chi psi omega."
    )


def test_chunk_store_chunks_each_parent_once_and_reconstructs_exactly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [_record(2, _long_text(2)), _record(1, _long_text(1))]
    corpus = _corpus(tmp_path, records)
    original = StateLawsChunker.chunk_corpus_row
    calls: list[str] = []

    def counted(self, row, *, model_token_limit, **kwargs):
        calls.append(str(row["entry_cid"]))
        return original(
            self,
            row,
            model_token_limit=model_token_limit,
            **kwargs,
        )

    monkeypatch.setattr(StateLawsChunker, "chunk_corpus_row", counted)
    layout = write_state_laws_chunk_physical_layout(
        corpus,
        model_token_limit=8,
        overlap_tokens=2,
        model_token_counter=_model_token_counter,
        model_token_counter_id=TOKEN_COUNTER_ID,
        max_rows_per_shard=2,
        max_records_in_memory=2,
    )

    assert len(calls) == len(records)
    assert len(set(calls)) == len(records)
    assert layout.production_ready is True
    assert STREAMING_CHUNK_STORE_PRODUCTION_READY is True
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert layout.parent_document_count == len(records)
    assert layout.chunk_count > len(records)
    assert layout.config["canonical_document_order"] == list(CANONICAL_DOCUMENT_ORDER)

    rows = list(layout.iter_chunks())
    assert rows == list(layout.iter_chunks())
    assert [int(row["document_index"]) for row in rows] == list(range(len(rows)))
    assert list(layout.iter_document_chunk_keys()) == [
        (index, str(row["chunk_cid"])) for index, row in enumerate(rows)
    ]
    assert [(row["jurisdiction_code"], row["chunk_cid"]) for row in rows] == sorted(
        (row["jurisdiction_code"], row["chunk_cid"]) for row in rows
    )
    assert len({str(row["chunk_cid"]) for row in rows}) == len(rows)
    assert all(row["entry_cid"] == row["chunk_cid"] for row in rows)
    assert all(row["body"] == row["exclusive_text"] for row in rows)
    assert any(row["overlap_token_count"] > 0 for row in rows)
    assert all(row["model_token_counter_id"] == TOKEN_COUNTER_ID for row in rows)
    assert all(int(row["model_input_token_count"]) <= 8 for row in rows)

    expected = {record.entry_cid: record.text for record in records}
    by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_parent[str(row["parent_entry_cid"])].append(row)
    assert set(by_parent) == set(expected)
    for parent_cid, chunks in by_parent.items():
        chunks.sort(key=lambda row: int(row["char_start"]))
        assert "".join(str(row["body"]) for row in chunks) == expected[parent_cid]

    routes = pq.read_table(tmp_path / CHUNK_INDEX_PATH).to_pylist()
    assert sum(int(route["row_count"]) for route in routes) == len(rows)
    assert [int(route["start_document_index"]) for route in routes] == list(
        range(0, len(rows), 2)
    )
    for descriptor in layout.descriptors:
        assert verify_descriptor(tmp_path, descriptor).is_file()
    for receipt in layout.sort_receipts.values():
        assert receipt["status"] == "complete"
        assert int(receipt["peak_resident_records"]) <= 2
        assert int(receipt["max_records_in_memory"]) == 2

    fragment = layout.to_manifest_fragment()
    assert fragment["corpus"]["rechunk_downstream"] is False
    assert fragment["corpus"]["body_field"] == "body"
    assert fragment["corpus"]["embedding_text_field"] == "text"
    assert set(fragment["indexes"]) == {"corpus_chunks"}


def test_chunk_store_refuses_truncation_and_duplicate_chunk_cids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    truncated_corpus = _corpus(
        tmp_path / "truncated",
        [_record(1, " ".join(f"token-{index}" for index in range(40)))],
    )
    with pytest.raises(StateLawsChunkPhysicalError, match="truncated statutory text"):
        write_state_laws_chunk_physical_layout(
            truncated_corpus,
            model_token_limit=2,
            max_chunks_per_section=1,
        )
    assert not (tmp_path / "truncated" / "data" / "corpus_chunks").exists()

    duplicate_corpus = _corpus(
        tmp_path / "duplicate",
        [_record(1, "First complete provision."), _record(2, "Second provision.")],
    )
    original = StateLawsChunker.chunk_corpus_row
    collision = f"sha256:{'f' * 64}"

    def collided(self, row, *, model_token_limit, **kwargs):
        result = original(
            self,
            row,
            model_token_limit=model_token_limit,
            **kwargs,
        )
        return replace(
            result,
            chunks=tuple(
                replace(chunk, chunk_cid=collision) for chunk in result.chunks
            ),
        )

    monkeypatch.setattr(StateLawsChunker, "chunk_corpus_row", collided)
    with pytest.raises(StateLawsChunkPhysicalError, match="duplicate canonical"):
        write_state_laws_chunk_physical_layout(
            duplicate_corpus,
            model_token_limit=512,
        )
    assert not (tmp_path / "duplicate" / "data" / "corpus_chunks").exists()


def test_chunk_replay_detects_descriptor_tampering(tmp_path: Path) -> None:
    corpus = _corpus(tmp_path, [_record(1, _long_text(1))])
    layout = write_state_laws_chunk_physical_layout(
        corpus,
        model_token_limit=8,
        model_token_counter=_model_token_counter,
        model_token_counter_id=TOKEN_COUNTER_ID,
        max_rows_per_shard=2,
        max_records_in_memory=2,
    )
    target = tmp_path / layout.data_descriptors[0].relative_path
    with target.open("ab") as handle:
        handle.write(b"tampered")

    with pytest.raises(StateLawsChunkPhysicalError, match="descriptor failed"):
        list(layout.iter_chunks())


def test_persisted_rows_replay_into_bm25_and_embeddings_without_rechunking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = _corpus(
        tmp_path / "source",
        [_record(1, _long_text(1)), _record(2, _long_text(2))],
    )
    chunks = write_state_laws_chunk_physical_layout(
        corpus,
        output_dir=tmp_path / "chunks",
        model_token_limit=8,
        overlap_tokens=2,
        model_token_counter=_model_token_counter,
        model_token_counter_id=TOKEN_COUNTER_ID,
        max_rows_per_shard=2,
        max_records_in_memory=2,
    )
    expected_cids = tuple(chunks.iter_chunk_cids())

    def must_not_rechunk(*_args, **_kwargs):  # pragma: no cover - behavior
        raise AssertionError("downstream consumer reran StateLawsChunker")

    monkeypatch.setattr(StateLawsChunker, "chunk_corpus_row", must_not_rechunk)
    bm25 = write_state_laws_bm25_physical_layout_from_iterable(
        chunks.iter_chunks(),
        tmp_path / "bm25",
        config=fixture_bm25_config(
            max_records_in_memory=2,
            max_rows_per_shard=32,
            postings_per_cell=2,
        ),
        canonical_chunk_artifact_digest=(
            chunks.corpus_index_descriptor.sha256
        ),
        checkpoint_dir=tmp_path / "bm25-checkpoint",
        resume=True,
    )
    embeddings = build_state_laws_embedding_store(
        chunks.iter_chunks(jurisdiction_code="AL"),
        tmp_path / "embeddings",
        jurisdiction_code="AL",
        config=fixture_embedding_config(batch_size=2),
        embedder=deterministic_project,
        rows_per_part=2,
        max_sort_records_in_memory=2,
    )

    assert tuple(bm25.iter_chunk_cids()) == expected_cids
    assert (
        bm25.canonical_chunk_artifact_digest
        == chunks.corpus_index_descriptor.sha256
    )
    assert embeddings.row_count == len(expected_cids)
    embedded_cids: list[str] = []
    for descriptor in embeddings.descriptors:
        embedded_cids.extend(
            str(value)
            for value in pq.read_table(
                Path(embeddings.output_root) / str(descriptor["relative_path"]),
                columns=["chunk_cid"],
            )
            .column("chunk_cid")
            .to_pylist()
        )
    assert tuple(embedded_cids) == expected_cids


def test_model_token_validator_is_required_for_production_and_fails_closed(
    tmp_path: Path,
) -> None:
    corpus = _corpus(tmp_path / "source", [_record(1, "Alpha betaword.")])
    compatibility = write_state_laws_chunk_physical_layout(
        corpus,
        output_dir=tmp_path / "compatibility",
        model_token_limit=4,
    )
    assert compatibility.production_ready is False
    assert compatibility.model_token_validation_passed is False

    unpinned = write_state_laws_chunk_physical_layout(
        corpus,
        output_dir=tmp_path / "unpinned",
        model_token_limit=4,
        model_token_counter=_model_token_counter,
        model_token_counter_id="fixture-unpinned-tokenizer/v1",
    )
    assert unpinned.model_token_validation_passed is True
    assert unpinned.production_ready is False

    def subword_expanding_counter(text: str) -> int:
        return len(text.split()) * 3

    with pytest.raises(
        StateLawsChunkPhysicalError,
        match="exceeds model token limit",
    ):
        write_state_laws_chunk_physical_layout(
            corpus,
            output_dir=tmp_path / "rejected",
            model_token_limit=4,
            model_token_counter=subword_expanding_counter,
            model_token_counter_id="fixture-subword-expander/v1",
        )
    assert not (tmp_path / "rejected" / "data" / "corpus_chunks").exists()

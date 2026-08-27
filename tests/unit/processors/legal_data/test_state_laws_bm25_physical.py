"""Physical state-law BM25 export and shared-query round-trip tests."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (
    FIELD_ORDER,
    TOKENIZER_ID,
    bind_fixture_bm25,
    fixture_bm25_chunks,
    fixture_bm25_config,
    project_legal_document,
    tokenize_query,
)
from ipfs_datasets_py.processors.legal_data.state_laws_bm25_physical import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    DOCUMENT_INDEX_PATH,
    INDEX_TO_LAYOUT_PRODUCTION_READY,
    ITERABLE_TO_LAYOUT_PRODUCTION_READY,
    KEYWORD_INDEX_PATH,
    POSTING_SCHEMA_VERSION,
    write_state_laws_bm25_physical_layout,
    write_state_laws_bm25_physical_layout_from_iterable,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    BoundedRemoteQueryEngine,
    QueryIntegrityError,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    ImmutableHubResolver,
    LocalRootTransport,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_dumps,
    content_sha256,
)

PINNED_REVISION = "4d62373051f2436296eb123d8c28819a91ea460a"


class _OneShotRows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        if self.iterations != 1:
            raise AssertionError("production source was iterated more than once")
        yield from self._rows


class _ExplodingRows:
    def __iter__(self):
        raise AssertionError("verified BM25 checkpoint unexpectedly consumed chunks")
        yield  # pragma: no cover


def _fixture_index():
    # Two documents keep even the tight two-row/two-pointer physical fixture
    # bounds satisfiable without ever splitting one term across route shards.
    return bind_fixture_bm25(
        fixture_bm25_chunks()[:2],
        config=fixture_bm25_config(
            max_rows_per_shard=2,
            postings_per_cell=2,
            max_route_page_rows=2,
        ),
    )


def _read_family(root: Path, relative_dir: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted((root / relative_dir).glob("*.parquet")):
        rows.extend(pq.read_table(path).to_pylist())
    return rows


def test_writer_emits_direct_columns_and_preserves_legal_postings(
    tmp_path: Path,
) -> None:
    index = _fixture_index()
    layout = write_state_laws_bm25_physical_layout(index, tmp_path)

    assert layout.counts["bm25_documents"] == index.document_count
    assert layout.counts["bm25_postings"] == index.posting_count
    assert layout.counts["bm25_terms"] == index.term_count
    assert (tmp_path / DOCUMENT_INDEX_PATH).is_file()
    assert (tmp_path / KEYWORD_INDEX_PATH).is_file()

    documents = _read_family(tmp_path, "data/bm25/documents")
    postings = _read_family(tmp_path, "data/bm25/postings")
    assert documents
    assert postings
    assert all("record_json" not in row for row in documents + postings)
    assert {str(row["term"]) for row in postings} == {
        posting.term for shard in index.term_shards for posting in shard.terms
    }

    expected: dict[tuple[str, str], dict[str, int]] = {}
    for shard in index.term_shards:
        for posting in shard.terms:
            for cell in posting.cells:
                for pointer in cell.pointers:
                    expected[(posting.term, pointer.entry_cid)] = {
                        field_name: int(pointer.field_tf.get(field_name, 0))
                        for field_name in FIELD_ORDER
                    }

    observed_pointer_count = 0
    for row in postings:
        assert row["schema_version"] == POSTING_SCHEMA_VERSION
        document_indices = list(row["document_indices"])
        parallel_columns = (
            "body_frequencies",
            "chunk_cids",
            "document_lengths",
            "entry_cids",
            "title_frequencies",
            "total_frequencies",
            "weighted_frequencies",
            *(f"legal_{name}_frequencies" for name in FIELD_ORDER),
            *(f"legal_{name}_lengths" for name in FIELD_ORDER),
        )
        assert len(document_indices) <= index.config.postings_per_cell
        assert all(len(row[name]) == len(document_indices) for name in parallel_columns)
        observed_pointer_count += len(document_indices)
        for offset, entry_cid in enumerate(row["entry_cids"]):
            field_tf = expected[(str(row["term"]), str(entry_cid))]
            assert {
                name: int(row[f"legal_{name}_frequencies"][offset])
                for name in FIELD_ORDER
            } == field_tf
            assert int(row["total_frequencies"][offset]) == sum(field_tf.values())
            assert int(row["title_frequencies"][offset]) == field_tf["title"]
            assert int(row["body_frequencies"][offset]) == sum(
                field_tf[name] for name in FIELD_ORDER if name != "title"
            )
    assert observed_pointer_count == index.posting_count

    document_routes = pq.read_table(tmp_path / DOCUMENT_INDEX_PATH).to_pylist()
    keyword_routes = pq.read_table(tmp_path / KEYWORD_INDEX_PATH).to_pylist()
    assert len(document_routes) == len(layout.document_descriptors)
    assert len(keyword_routes) == len(layout.posting_descriptors)
    for route in document_routes + keyword_routes:
        target = tmp_path / str(route["relative_path"])
        assert target.is_file()
        assert int(route["row_count"]) <= index.config.max_rows_per_shard
        assert int(route["size_bytes"]) == target.stat().st_size

    fragment = layout.to_manifest_fragment()
    assert set(fragment["indexes"]) == {
        "bm25_document_chunks",
        "bm25_keyword_shards",
    }
    assert fragment["bm25"]["tokenizer"] == index.tokenizer_id
    assert fragment["bm25"]["config"] == index.config.to_dict()
    assert fragment["bm25"]["field_weights"] == (index.config.field_weights.to_dict())
    assert fragment["bm25"]["query_analyzer"] == {
        "required": True,
        "tokenizer_id": index.tokenizer_id,
    }
    assert fragment["bm25"]["query_field_projection"]["exact_field_lengths"] is True


def test_shared_query_engine_round_trips_direct_posting_rows(
    tmp_path: Path,
) -> None:
    index = _fixture_index()
    layout = write_state_laws_bm25_physical_layout(index, tmp_path)
    manifest = {
        "primary_key": "entry_cid",
        "schema_version": "hf-graphrag-release/v1",
        **layout.to_manifest_fragment(),
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )

    resolver = ImmutableHubResolver(
        repo_id="justicedao/ipfs_state_laws",
        revision=PINNED_REVISION,
        cache_dir=tmp_path / "cache",
        transport=LocalRootTransport(tmp_path),
        local_root=tmp_path,
        supported_schemas={"hf-graphrag-release/v1"},
    )
    result = BoundedRemoteQueryEngine(
        resolver,
        bm25_query_analyzers={TOKENIZER_ID: tokenize_query},
    ).run_bm25(
        "texaspublicinfo", top_k=2, hydrate=False
    )

    expected_entry_cid = next(
        document.entry_cid
        for document in index.documents
        if document.jurisdiction_code == "TX"
    )
    assert result.complete is True
    assert result.results
    assert result.results[0]["entry_cid"] == expected_entry_cid
    assert result.results[0]["matched_terms"] == ["texaspublicinfo"]
    data_paths = {
        item["relative_path"]
        for item in result.fetch_trace["files"]
        if item["route"]["family"] == "bm25_postings"
    }
    assert len(data_paths) == 1


def test_manifest_injected_analyzer_preserves_exact_legal_citation(
    tmp_path: Path,
) -> None:
    index = _fixture_index()
    layout = write_state_laws_bm25_physical_layout(index, tmp_path)
    manifest = {
        "primary_key": "entry_cid",
        "schema_version": "hf-graphrag-release/v1",
        **layout.to_manifest_fragment(),
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    resolver = ImmutableHubResolver(
        repo_id="justicedao/ipfs_state_laws",
        revision=PINNED_REVISION,
        cache_dir=tmp_path / "cache",
        transport=LocalRootTransport(tmp_path),
        local_root=tmp_path,
        supported_schemas={"hf-graphrag-release/v1"},
    )
    engine = BoundedRemoteQueryEngine(resolver)

    with pytest.raises(QueryIntegrityError, match="requires an injected"):
        engine.run_bm25("§ 001", top_k=2, hydrate=False)

    engine.register_bm25_query_analyzers({TOKENIZER_ID: tokenize_query})
    result = engine.run_bm25("§ 001", top_k=2, hydrate=False)

    expected_entry_cid = next(
        document.entry_cid
        for document in index.documents
        if document.jurisdiction_code == "TX"
    )
    assert result.complete is True
    assert result.diagnostics["query_terms"] == ["§_001"]
    assert result.explain["tokenizer"] == TOKENIZER_ID
    assert result.explain["query_analyzer_injected"] is True
    assert result.results[0]["entry_cid"] == expected_entry_cid
    assert result.results[0]["matched_terms"] == ["§_001"]


def test_shared_query_exactly_matches_seven_field_weighted_reference(
    tmp_path: Path,
) -> None:
    rows = [dict(row) for row in fixture_bm25_chunks()[:2]]
    rows[0].update({"body": "neutral", "citation": "weightprobe"})
    rows[1].update({"body": "weightprobe", "citation": "neutral"})
    config = fixture_bm25_config(
        max_records_in_memory=2,
        max_rows_per_shard=2,
        postings_per_cell=2,
    )
    reference = bind_fixture_bm25(rows, config=config)
    layout = write_state_laws_bm25_physical_layout_from_iterable(
        iter(rows),
        tmp_path,
        config=config,
    )
    manifest = {
        "primary_key": "entry_cid",
        "schema_version": "hf-graphrag-release/v1",
        **layout.to_manifest_fragment(),
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    resolver = ImmutableHubResolver(
        repo_id="justicedao/ipfs_state_laws",
        revision=PINNED_REVISION,
        cache_dir=tmp_path / "cache",
        transport=LocalRootTransport(tmp_path),
        local_root=tmp_path,
        supported_schemas={"hf-graphrag-release/v1"},
    )
    result = BoundedRemoteQueryEngine(
        resolver,
        bm25_query_analyzers={TOKENIZER_ID: tokenize_query},
    ).run_bm25("weightprobe", top_k=2, hydrate=False)
    expected = reference.search("weightprobe", top_k=2)

    assert [row["entry_cid"] for row in result.results] == [
        hit.entry_cid for hit in expected
    ]
    assert [row["score"] for row in result.results] == pytest.approx(
        [hit.score for hit in expected], abs=1e-12
    )
    assert expected[0].explanations[0].field_contributions[0].field == "citation"
    assert expected[1].explanations[0].field_contributions[0].field == "body"
    for observed, expected_hit in zip(result.results, expected, strict=True):
        contribution = observed["explain"][0]["field_contributions"]
        expected_contribution = expected_hit.explanations[0].field_contributions
        assert [item["field"] for item in contribution] == [
            item.field for item in expected_contribution
        ]
        assert [item["weight"] for item in contribution] == pytest.approx(
            [item.weight for item in expected_contribution]
        )
        assert observed["explain"][0]["scorer"] == "exact_multifield"


def test_streaming_writer_spills_one_shot_rows_and_preserves_seven_fields(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_rows = fixture_bm25_chunks()[:3]
    source = _OneShotRows(source_rows)
    config = fixture_bm25_config(
        max_records_in_memory=2,
        max_rows_per_shard=2,
        postings_per_cell=2,
    )

    # The production adapter must never cross the legacy materializing builder.
    import ipfs_datasets_py.processors.legal_data.state_laws_bm25 as legacy

    monkeypatch.setattr(
        legacy,
        "build_state_laws_bm25_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("legacy BM25 builder was called")
        ),
    )
    layout = write_state_laws_bm25_physical_layout_from_iterable(
        source,
        tmp_path,
        config=config,
    )

    assert source.iterations == 1
    assert layout.production_ready is True
    assert ITERABLE_TO_LAYOUT_PRODUCTION_READY is True
    assert INDEX_TO_LAYOUT_PRODUCTION_READY is False
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert not (tmp_path / "manifest.json").exists()
    assert layout.counts["bm25_documents"] == len(source_rows)
    chunk_cids = tuple(layout.iter_chunk_cids())
    assert len(chunk_cids) == len(source_rows)
    assert len(set(chunk_cids)) == len(chunk_cids)
    assert set(chunk_cids) == {str(row["chunk_cid"]) for row in source_rows}
    assert tuple(layout.iter_document_chunk_keys()) == tuple(
        (int(row["document_index"]), str(row["chunk_cid"]))
        for row in sorted(
            _read_family(tmp_path, "data/bm25/documents"),
            key=lambda row: int(row["document_index"]),
        )
    )
    assert set(layout.key_evidence["parent_entry_cids"]) == {
        str(row["parent_entry_cid"]) for row in source_rows
    }
    for receipt in layout.sort_receipts.values():
        assert int(receipt["peak_resident_records"]) <= 2
        assert int(receipt["max_records_in_memory"]) == 2
    assert int(layout.sort_receipts["source_identity"]["run_count"]) >= 2
    assert int(layout.sort_receipts["documents"]["run_count"]) >= 2
    assert int(layout.sort_receipts["posting_fields"]["run_count"]) > 2

    expected: dict[tuple[str, str], dict[str, int]] = {}
    vocabulary: set[str] = set()
    for position, source_row in enumerate(source_rows):
        document = project_legal_document(
            source_row,
            document_index=position,
            config=config,
        )
        per_field = {name: Counter(document.fields[name].terms) for name in FIELD_ORDER}
        for term in set().union(*(set(counter) for counter in per_field.values())):
            vocabulary.add(term)
            expected[(term, document.entry_cid)] = {
                name: int(per_field[name].get(term, 0)) for name in FIELD_ORDER
            }

    postings = _read_family(tmp_path, "data/bm25/postings")
    assert {str(row["term"]) for row in postings} == vocabulary
    observed: set[tuple[str, str]] = set()
    exact_columns = tuple(f"legal_{name}_frequencies" for name in FIELD_ORDER)
    exact_length_columns = tuple(f"legal_{name}_lengths" for name in FIELD_ORDER)
    for row in postings:
        pointers = len(row["document_indices"])
        assert pointers <= 2
        assert {*exact_columns, *exact_length_columns}.issubset(row)
        for column in (
            "body_frequencies",
            "chunk_cids",
            "document_lengths",
            "entry_cids",
            "title_frequencies",
            "total_frequencies",
            "weighted_frequencies",
            *exact_columns,
            *exact_length_columns,
        ):
            assert len(row[column]) == pointers
        for offset, entry_cid in enumerate(row["entry_cids"]):
            key = (str(row["term"]), str(entry_cid))
            observed.add(key)
            field_tfs = expected[key]
            assert {
                name: int(row[f"legal_{name}_frequencies"][offset])
                for name in FIELD_ORDER
            } == field_tfs
            assert int(row["title_frequencies"][offset]) == field_tfs["title"]
            assert int(row["body_frequencies"][offset]) == sum(
                field_tfs[name] for name in FIELD_ORDER if name != "title"
            )
            assert int(row["total_frequencies"][offset]) == sum(field_tfs.values())
            for name in FIELD_ORDER:
                if field_tfs[name] > 0:
                    assert int(row[f"legal_{name}_lengths"][offset]) >= field_tfs[name]
    assert observed == set(expected)

    document_frequencies = sorted(
        (
            term,
            len(
                {
                    entry_cid
                    for observed_term, entry_cid in observed
                    if observed_term == term
                }
            ),
        )
        for term in vocabulary
    )
    assert list(layout.iter_vocabulary_document_frequencies()) == (document_frequencies)
    fragment = layout.to_manifest_fragment()
    assert fragment["bm25"]["config"] == config.to_dict()
    assert fragment["bm25"]["config_digest"] == config.digest
    assert str(fragment["bm25"]["index_root_cid"]).startswith("sha256:")
    assert fragment["bm25"]["vocabulary_sha256"] == content_sha256(
        canonical_json_dumps(sorted(vocabulary))
    )
    assert fragment["bm25"]["document_frequency_sha256"] == content_sha256(
        canonical_json_dumps(document_frequencies)
    )
    assert fragment["bm25"]["physical_vocabulary_proof"] == {
        "document_frequency_column": "document_frequency",
        "document_frequency_sha256": fragment["bm25"]["document_frequency_sha256"],
        "keyword_index_path": KEYWORD_INDEX_PATH,
        "posting_glob": "data/bm25/postings/*.parquet",
        "posting_rows_are_lexicographic": True,
        "term_column": "term",
        "vocabulary_sha256": fragment["bm25"]["vocabulary_sha256"],
    }
    assert (
        sum(item.row_count for item in layout.document_descriptors)
        == (layout.counts["bm25_documents"])
    )
    assert (
        sum(item.row_count for item in layout.posting_descriptors)
        == (layout.counts["bm25_posting_rows"])
    )


def test_streaming_wrapper_reuses_canonical_chunk_digest_checkpoint(
    tmp_path: Path,
) -> None:
    source_rows = fixture_bm25_chunks()[:3]
    source = _OneShotRows(source_rows)
    digest = "sha256:" + "9" * 64
    config = fixture_bm25_config(
        max_records_in_memory=2,
        max_rows_per_shard=2,
        postings_per_cell=2,
    )
    first = write_state_laws_bm25_physical_layout_from_iterable(
        source,
        tmp_path / "release",
        config=config,
        canonical_chunk_artifact_digest=digest,
        checkpoint_dir=tmp_path / "checkpoint",
        resume=True,
    )

    assert source.iterations == 1
    assert first.canonical_chunk_artifact_digest == "9" * 64
    assert first.checkpoint_path == str(
        tmp_path / "checkpoint" / "streaming_bm25_checkpoint.json"
    )
    assert "projection" in first.executed_stages
    bm25_manifest = first.to_manifest_fragment()["bm25"]
    assert bm25_manifest["canonical_chunk_artifact_digest"] == "9" * 64
    assert (
        bm25_manifest["canonical_chunk_artifact_digest_contract"]
        == "corpus_chunks_index_descriptor_sha256"
    )

    second = write_state_laws_bm25_physical_layout_from_iterable(
        _ExplodingRows(),
        tmp_path / "release",
        config=config,
        canonical_chunk_artifact_digest=digest,
        checkpoint_dir=tmp_path / "checkpoint",
        resume=True,
    )

    assert second.executed_stages == ()
    assert "publication" in second.resumed_stages
    assert second.layout.index_root_cid == first.layout.index_root_cid
    assert second.descriptors == first.descriptors

    with pytest.raises(ValueError, match="active source/profile/config"):
        write_state_laws_bm25_physical_layout_from_iterable(
            _ExplodingRows(),
            tmp_path / "release",
            config=config,
            canonical_chunk_artifact_digest="7" * 64,
            checkpoint_dir=tmp_path / "checkpoint",
            resume=True,
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"resume": True},
        {"checkpoint_dir": "checkpoint"},
        {"canonical_chunk_artifact_digest": "8" * 64},
    ],
)
def test_streaming_wrapper_requires_complete_checkpoint_contract(
    tmp_path: Path,
    kwargs: dict[str, object],
) -> None:
    if "checkpoint_dir" in kwargs:
        kwargs["checkpoint_dir"] = tmp_path / str(kwargs["checkpoint_dir"])
    with pytest.raises(
        ValueError,
        match="canonical_chunk_artifact_digest and checkpoint_dir are both required",
    ):
        write_state_laws_bm25_physical_layout_from_iterable(
            _ExplodingRows(),
            tmp_path / "release",
            config=fixture_bm25_config(),
            **kwargs,
        )


def test_streaming_writer_uses_shared_jurisdiction_chunk_cid_order(
    tmp_path: Path,
) -> None:
    first = dict(fixture_bm25_chunks()[0])
    second = dict(first)
    first.update(
        {
            "chunk_cid": "sha256:" + "f" * 64,
            "chunk_id": "tx:552:001#chunk=0000",
            "chunk_index": 0,
        }
    )
    second.update(
        {
            "body": "Second searchable chunk in the same parent statute.",
            "chunk_cid": "sha256:" + "1" * 64,
            "chunk_id": "tx:552:001#chunk=0001",
            "chunk_index": 1,
        }
    )

    write_state_laws_bm25_physical_layout_from_iterable(
        iter((first, second)),
        tmp_path,
        config=fixture_bm25_config(
            max_records_in_memory=2,
            max_rows_per_shard=2,
            postings_per_cell=2,
        ),
    )

    documents = sorted(
        _read_family(tmp_path, "data/bm25/documents"),
        key=lambda row: int(row["document_index"]),
    )
    assert [row["chunk_cid"] for row in documents] == [
        second["chunk_cid"],
        first["chunk_cid"],
    ]


def test_streaming_layout_uses_existing_remote_query_routes(tmp_path: Path) -> None:
    config = fixture_bm25_config(
        max_records_in_memory=2,
        max_rows_per_shard=2,
        postings_per_cell=2,
    )
    layout = write_state_laws_bm25_physical_layout_from_iterable(
        iter(fixture_bm25_chunks()[:3]),
        tmp_path,
        config=config,
    )
    manifest = {
        "primary_key": "entry_cid",
        "schema_version": "hf-graphrag-release/v1",
        **layout.to_manifest_fragment(),
    }
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    resolver = ImmutableHubResolver(
        repo_id="justicedao/ipfs_state_laws",
        revision=PINNED_REVISION,
        cache_dir=tmp_path / "cache",
        transport=LocalRootTransport(tmp_path),
        local_root=tmp_path,
        supported_schemas={"hf-graphrag-release/v1"},
    )
    result = BoundedRemoteQueryEngine(
        resolver,
        bm25_query_analyzers={TOKENIZER_ID: tokenize_query},
    ).run_bm25(
        "texaspublicinfo", top_k=2, hydrate=False
    )
    assert result.complete is True
    assert result.results[0]["entry_cid"] == str(fixture_bm25_chunks()[0]["chunk_cid"])
    assert result.results[0]["matched_terms"] == ["texaspublicinfo"]

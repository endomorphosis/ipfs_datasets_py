"""Unit tests for Federal Register field-weighted term-range BM25 (LCR-056).

Acceptance: documents equal admitted searchable chunks; postings
reconcile, physical bounds hold, boundary terms route once, and scores
match reference BM25.

Tests are hermetic. No Hub upload, no tokens, no absolute home paths.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    DEFAULT_B,
    DEFAULT_K1,
    DOCUMENT_COUNT_CEILING,
    DOCUMENTS_SORTED_BY,
    FIELD_ORDER,
    FORBIDDEN_DOCUMENT_CEILING,
    GOAL_ID,
    LEGAL_TOKENIZER_ID,
    MAX_POSTING_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    POSTINGS_SORTED_BY,
    PRIMARY_KEY,
    PRODUCER,
    PROGRAM_ID,
    REPORT_SCHEMA,
    SCHEMA_VERSION,
    TASK_ID,
    TERMS_SORTED_BY,
    TOKENIZER_ID,
    TOKENIZER_SHARED_BY,
    Bm25BoundError,
    Bm25ConfigError,
    Bm25CoverageError,
    Bm25Hit,
    FederalRegisterBm25Config,
    FederalRegisterBm25Index,
    PostingPointer,
    assert_boundary_terms_route_once,
    assert_every_admitted_chunk_has_document,
    assert_externally_sorted,
    assert_federal_bm25_report,
    assert_no_posting_lineage,
    assert_postings_reconcile,
    assert_scores_match_reference,
    assert_shards_bounded,
    bind_fixture_bm25,
    build_corpus_root_cid,
    build_federal_bm25_report,
    build_federal_register_bm25_index,
    default_bm25_config,
    default_bm25_report_path,
    fixture_bm25_chunks,
    fixture_bm25_config,
    iter_projected_documents,
    load_federal_bm25_report,
    production_bm25_bounds,
    project_admitted_documents,
    reconcile_roots,
    reference_field_term_score,
    rows_from_materialized_corpus,
    shared_tokenizer_identity,
    split_posting_cells,
    tokenize_index_text,
    tokenize_query,
    write_federal_bm25_report,
)
from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
    POSTING_LINEAGE_FORBIDDEN_FIELDS,
    materialize_federal_register_corpus,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import TOKENIZER_VERSION
from ipfs_datasets_py.retrieval.hf_graphrag.bm25 import tokenize_bm25_text


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


def _admitted(chunks: list[dict] | None = None) -> list[dict]:
    rows = list(chunks) if chunks is not None else fixture_bm25_chunks()
    return [
        row
        for row in rows
        if str(row.get("disposition") or "").lower() == "admitted"
    ]


@pytest.fixture(scope="module")
def corpus():
    return materialize_federal_register_corpus()


@pytest.fixture(scope="module")
def compact_index():
    return bind_fixture_bm25()


# ---------------------------------------------------------------------------
# Identity / production bounds
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-bm25-v1"
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-federal-bm25@1"
    assert TASK_ID == "LCR-056"
    assert GOAL_ID == "LCR-G120"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert PRODUCER == "federal_register_bm25.py"
    assert PRIMARY_KEY == "chunk_cid"
    assert TOKENIZER_ID == "federal-register-bm25-tokenizer/v1"
    assert LEGAL_TOKENIZER_ID == "uscode-bm25-tokenizer/v1"
    assert TOKENIZER_SHARED_BY == "build_and_query"
    assert DOCUMENTS_SORTED_BY == "year_month_type_then_document_index"
    assert TERMS_SORTED_BY == "lexicographic_term"
    assert POSTINGS_SORTED_BY == "term_then_chunk_cid"
    assert RELEASE_PROFILE == "federal-register-ir-graphrag/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False


def test_production_bounds_match_release_policy() -> None:
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_POSTING_POINTERS_PER_ROW == 4096
    assert DOCUMENT_COUNT_CEILING is None
    assert FORBIDDEN_DOCUMENT_CEILING == 250_000
    bounds = production_bm25_bounds()
    assert bounds["maximum_rows_per_physical_shard"] == 4096
    assert bounds["maximum_posting_pointers_per_cell"] == 4096
    assert bounds["document_count_ceiling"] is None


def test_oversize_shard_bound_fails_closed() -> None:
    with pytest.raises(Bm25BoundError):
        fixture_bm25_config(max_rows_per_shard=4097)


def test_oversize_posting_cell_bound_fails_closed() -> None:
    with pytest.raises(Bm25BoundError):
        fixture_bm25_config(postings_per_cell=4097)


def test_oversize_route_page_bound_fails_closed() -> None:
    with pytest.raises(Bm25BoundError):
        fixture_bm25_config(max_route_page_rows=4097)


def test_inherited_250k_ceiling_is_rejected() -> None:
    with pytest.raises(Bm25ConfigError):
        FederalRegisterBm25Config(max_documents=FORBIDDEN_DOCUMENT_CEILING)


# ---------------------------------------------------------------------------
# Shared legal tokenizer
# ---------------------------------------------------------------------------


def test_build_and_query_share_the_versioned_legal_tokenizer() -> None:
    config = default_bm25_config()
    text = "40 C.F.R. § 98 emissions reporting rule"
    build_terms = tokenize_index_text(text, config=config)
    query_terms = tokenize_query(text, config=config)
    assert build_terms == query_terms
    assert config.tokenizer.tokenizer_id == LEGAL_TOKENIZER_ID
    assert config.tokenizer_id == TOKENIZER_ID
    identity = shared_tokenizer_identity(config)
    assert identity["tokenizer_id"] == TOKENIZER_ID
    assert identity["legal_tokenizer_id"] == LEGAL_TOKENIZER_ID
    assert identity["tokenizer_version"] == TOKENIZER_VERSION
    assert identity["used_for_build"] is True
    assert identity["used_for_query"] is True
    assert identity["shared_by"] == TOKENIZER_SHARED_BY


def test_query_does_not_use_the_generic_layout_tokenizer() -> None:
    text = "40 C.F.R. § 98 emissions reporting"
    legal = tokenize_query(text, config=default_bm25_config())
    generic = tokenize_bm25_text(text)
    assert legal
    assert tuple(legal) != generic
    index = bind_fixture_bm25()
    hits = index.search(text, top_k=3)
    assert index.tokenizer_id == TOKENIZER_ID
    assert all(isinstance(hit, Bm25Hit) for hit in hits)


def test_index_search_tokenizes_with_the_same_config_as_build(compact_index) -> None:
    query = "emissions reporting rule"
    query_terms = tokenize_query(query, config=compact_index.config)
    build_terms = tokenize_index_text(query, config=compact_index.config)
    assert query_terms == build_terms
    hits = compact_index.search(query, top_k=8)
    assert hits
    matched = {term for hit in hits for term in hit.matched_terms}
    assert matched <= set(query_terms)


# ---------------------------------------------------------------------------
# Coverage / projection against compact fixtures
# ---------------------------------------------------------------------------


def test_every_admitted_chunk_has_one_document(compact_index) -> None:
    rows = fixture_bm25_chunks()
    admitted = _admitted(rows)
    assert compact_index.document_count == len(admitted)
    assert_every_admitted_chunk_has_document(rows, compact_index)
    assert {doc.chunk_cid for doc in compact_index.documents} == {
        row["chunk_cid"] for row in admitted
    }
    assert all(doc.total_length > 0 for doc in compact_index.documents)


def test_quarantine_and_excluded_rows_never_enter_the_index(compact_index) -> None:
    identities = {doc.chunk_cid for doc in compact_index.documents}
    assert _cid("f") not in identities
    assert "" not in identities
    assert compact_index.document_count == 8


def test_positional_identity_is_rejected() -> None:
    with pytest.raises(Exception):
        project_admitted_documents(
            [
                {
                    "entry_cid": "row-12",
                    "chunk_cid": "row-12",
                    "body": "positional identity must fail",
                    "disposition": "admitted",
                    "document_type": "rule",
                    "year_month": "2026-03",
                }
            ],
            config=fixture_bm25_config(),
        )


def test_duplicate_chunk_cid_fails_closed() -> None:
    first = _admitted()[0]
    with pytest.raises(Bm25CoverageError):
        project_admitted_documents([first, dict(first)], config=fixture_bm25_config())


def test_empty_corpus_fails_closed() -> None:
    with pytest.raises(Bm25CoverageError):
        project_admitted_documents([], config=fixture_bm25_config())


def test_roots_reconcile(compact_index) -> None:
    rows = fixture_bm25_chunks()
    root = build_corpus_root_cid(rows)
    proof = reconcile_roots(compact_index, expected_corpus_root_cid=root)
    assert proof["reconciled"] is True
    assert proof["document_count"] == compact_index.document_count


def test_iter_projected_documents_accepts_a_generator() -> None:
    rows = fixture_bm25_chunks()

    def _stream() -> Iterator[dict]:
        yield from rows

    projected = list(iter_projected_documents(_stream(), config=fixture_bm25_config()))
    assert len(projected) == len(_admitted(rows))
    assert {doc.chunk_cid for doc in projected} == {
        row["chunk_cid"] for row in _admitted(rows)
    }


# ---------------------------------------------------------------------------
# LCR-055 admitted corpus coverage
# ---------------------------------------------------------------------------


def test_documents_equal_admitted_searchable_chunks(corpus) -> None:
    index = build_federal_register_bm25_index(corpus, config=fixture_bm25_config())
    assert index.document_count == len(corpus.chunks)
    assert {doc.chunk_cid for doc in index.documents} == {
        chunk.chunk_cid for chunk in corpus.chunks
    }
    assert_every_admitted_chunk_has_document(corpus, index)
    assert_postings_reconcile(index)
    rows = rows_from_materialized_corpus(corpus)
    assert len(rows) == len(corpus.chunks)
    assert all(row["disposition"] == "admitted" for row in rows)


def test_recovery_never_increments_bm25_family(corpus) -> None:
    index = build_federal_register_bm25_index(corpus, config=fixture_bm25_config())
    assert index.document_count == corpus.family_counts.chunks
    assert index.document_count != corpus.family_counts.recovery
    recovery_ids = {record.recovery_id for record in corpus.recovery_records}
    assert recovery_ids.isdisjoint({doc.chunk_cid for doc in index.documents})


# ---------------------------------------------------------------------------
# External sort
# ---------------------------------------------------------------------------


def test_documents_are_externally_sorted_by_document_index(compact_index) -> None:
    rows = fixture_bm25_chunks()
    incoming = [
        (str(row.get("year_month")), str(row.get("document_type")), str(row.get("document_number")))
        for row in _admitted(rows)
    ]
    assert incoming != sorted(incoming)
    assert_externally_sorted(compact_index)
    indexes = [doc.document_index for doc in compact_index.documents]
    assert indexes == sorted(indexes)
    assert indexes == list(range(len(indexes)))
    receipt = compact_index.sort_receipts["documents"]
    assert receipt["externally_sorted"] is True
    assert receipt["family"] == "documents"
    assert receipt["peak_resident_records"] <= compact_index.config.max_records_in_memory


def test_terms_and_postings_are_externally_sorted_lexicographically(compact_index) -> None:
    names: list[str] = []
    for shard in compact_index.term_shards:
        shard_terms = [item.term for item in shard.terms]
        assert shard_terms == sorted(shard_terms)
        names.extend(shard_terms)
    assert names == sorted(names)
    assert names[0] <= names[-1]
    assert compact_index.sort_receipts["terms"]["externally_sorted"] is True
    assert compact_index.sort_receipts["postings"]["externally_sorted"] is True
    for shard in compact_index.term_shards:
        for term in shard.terms:
            cids = [
                pointer.entry_cid
                for cell in term.cells
                for pointer in cell.pointers
            ]
            assert cids == sorted(cids)


# ---------------------------------------------------------------------------
# Physical 4096 bounds
# ---------------------------------------------------------------------------


def test_every_shard_and_posting_cell_is_bounded(compact_index) -> None:
    assert_shards_bounded(compact_index)
    assert compact_index.document_shard_count >= 2
    assert compact_index.term_shard_count >= 2
    for shard in compact_index.document_shards:
        assert 1 <= shard.row_count <= compact_index.config.max_rows_per_shard
        assert shard.row_count <= 4096
        assert "/year_month=" in shard.relative_path
        assert "/document_type=" in shard.relative_path
        assert not shard.relative_path.startswith("/")
    for shard in compact_index.term_shards:
        assert 1 <= shard.row_count <= compact_index.config.max_rows_per_shard
        assert shard.row_count <= 4096
        assert shard.first_term <= shard.last_term
        assert shard.relative_path.startswith("data/bm25/postings/")
        for term in shard.terms:
            for cell in term.cells:
                assert 1 <= cell.pointer_count <= compact_index.config.postings_per_cell
                assert cell.pointer_count <= 4096
    for page in (*compact_index.document_routes.pages, *compact_index.term_routes.pages):
        assert len(page) <= compact_index.config.max_route_page_rows
        assert len(page) <= 4096


def test_posting_cells_split_when_pointers_exceed_the_bound(compact_index) -> None:
    pointers = [
        PostingPointer(
            entry_cid=_cid(nibble),
            document_index=offset,
            field_tf={"body": 1},
            tf=1,
            chunk_cid=_cid(nibble),
        )
        for offset, nibble in enumerate("abcde")
    ]
    cells = split_posting_cells(pointers, max_pointers=2)
    assert len(cells) == 3
    assert [cell.pointer_count for cell in cells] == [2, 2, 1]
    assert all(cell.pointer_count <= 2 for cell in cells)

    multi_cell = [
        term
        for shard in compact_index.term_shards
        for term in shard.terms
        if term.cell_count > 1
    ]
    assert multi_cell, "fixture must exercise posting-cell splits"
    for term in multi_cell:
        assert term.pointer_count == term.document_frequency
        assert all(cell.pointer_count <= 2 for cell in term.cells)


def test_production_bounds_are_4096_even_when_fixtures_are_tighter() -> None:
    production = default_bm25_config()
    fixture = fixture_bm25_config()
    assert production.max_rows_per_shard == 4096
    assert production.postings_per_cell == 4096
    assert production.max_route_page_rows == 4096
    assert fixture.max_rows_per_shard == 2
    assert fixture.postings_per_cell == 2
    index = bind_fixture_bm25()
    assert index.config.max_rows_per_shard == 2
    assert max(shard.row_count for shard in index.document_shards) <= 2
    assert max(shard.row_count for shard in index.term_shards) <= 2


def test_postings_do_not_duplicate_source_lineage(compact_index) -> None:
    assert_no_posting_lineage(compact_index)
    assert_postings_reconcile(compact_index)
    for shard in compact_index.term_shards:
        for term in shard.terms:
            payload = term.to_dict()
            assert POSTING_LINEAGE_FORBIDDEN_FIELDS.isdisjoint(payload)


# ---------------------------------------------------------------------------
# Term-range routing / search
# ---------------------------------------------------------------------------


def test_query_reads_only_covering_term_range_shards(compact_index) -> None:
    query_terms = tokenize_query("epaemissionsrule", config=compact_index.config)
    assert query_terms
    routed = compact_index.route_query_terms(query_terms)
    assert routed
    for shard in routed:
        assert any(shard.covers(term) for term in query_terms)
    unrouted = [
        shard
        for shard in compact_index.term_shards
        if shard.shard_id not in {item.shard_id for item in routed}
    ]
    for shard in unrouted:
        assert all(not shard.covers(term) for term in query_terms)


def test_boundary_terms_route_once(compact_index) -> None:
    assert_boundary_terms_route_once(compact_index)
    for previous, current in zip(compact_index.term_shards, compact_index.term_shards[1:]):
        assert previous.last_term < current.first_term


def test_search_ranks_the_epa_emissions_rule(compact_index) -> None:
    hits = compact_index.search("epaemissionsrule", top_k=5)
    assert hits
    assert hits[0].chunk_cid == _cid("a")
    assert hits[0].legal_id == "fr:2026-04567:2026-03-16"
    assert hits[0].score > 0.0
    assert hits[0].explanations
    for explanation in hits[0].explanations:
        assert explanation.routed_path.startswith("data/bm25/postings/")
        assert explanation.field_contributions
        assert explanation.idf >= 0.0


def test_agency_and_type_filters_are_honored(compact_index) -> None:
    hits = compact_index.search(
        "emissions reporting",
        top_k=8,
        filters={"agency": "Department of Transportation"},
    )
    assert hits
    assert all(hit.filters.get("agency") == "Department of Transportation" for hit in hits)
    assert all(hit.chunk_cid == _cid("e") for hit in hits)

    typed = compact_index.search(
        "emissions",
        top_k=8,
        filters={"document_type": "proposed_rule"},
    )
    assert typed
    assert all(hit.filters.get("document_type") == "proposed_rule" for hit in typed)


def test_field_weights_are_recorded_and_used(compact_index) -> None:
    weights = compact_index.config.field_weights.to_dict()
    assert set(weights) == set(FIELD_ORDER)
    assert weights["citation"] > weights["body"]
    assert weights["title"] == 5.0
    assert compact_index.config.k1 == DEFAULT_K1
    assert compact_index.config.b == DEFAULT_B
    hits = compact_index.search("EPA emissions reporting rule", top_k=3)
    assert hits
    fields_used = {
        contribution.field
        for hit in hits
        for explanation in hit.explanations
        for contribution in explanation.field_contributions
    }
    assert fields_used
    assert fields_used <= set(FIELD_ORDER)


def test_stopword_only_query_returns_no_hits(compact_index) -> None:
    assert compact_index.search("the and or of", top_k=5) == []


def test_scores_match_reference_bm25(compact_index) -> None:
    fixtures = assert_scores_match_reference(compact_index)
    assert fixtures
    document = compact_index.document_by_cid(_cid("a"))
    explanation = compact_index.explain_term(document, "epaemissionsrule")
    expected = 0.0
    for contribution in explanation.field_contributions:
        reference = reference_field_term_score(
            tf=contribution.tf,
            idf=explanation.idf,
            field_length=contribution.field_length,
            average_field_length=float(
                compact_index.average_field_lengths[contribution.field]
            ),
            k1=compact_index.config.k1,
            b=compact_index.config.b,
            field_weight=contribution.weight,
        )
        assert contribution.score == pytest.approx(reference, abs=1e-12)
        expected += reference
    assert explanation.total_score == pytest.approx(expected, abs=1e-12)


def test_build_from_unsorted_rows_is_deterministic() -> None:
    rows = fixture_bm25_chunks()
    first = build_federal_register_bm25_index(rows, config=fixture_bm25_config())
    second = build_federal_register_bm25_index(
        list(reversed(rows)), config=fixture_bm25_config()
    )
    assert first.index_root_cid == second.index_root_cid
    assert [doc.chunk_cid for doc in first.documents] == [
        doc.chunk_cid for doc in second.documents
    ]
    assert [shard.first_term for shard in first.term_shards] == [
        shard.first_term for shard in second.term_shards
    ]


def test_index_is_the_federal_register_type(compact_index) -> None:
    assert isinstance(compact_index, FederalRegisterBm25Index)
    fragment = compact_index.to_manifest_fragment()
    assert fragment["task_id"] == TASK_ID
    assert fragment["bm25"]["tokenizer_id"] == TOKENIZER_ID
    assert fragment["bm25"]["primary_key"] == PRIMARY_KEY
    assert fragment["bm25"]["documents_sorted_by"] == DOCUMENTS_SORTED_BY
    assert fragment["bm25"]["terms_sorted_by"] == TERMS_SORTED_BY


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_bm25_report_is_secret_free_and_fixture_bound(corpus, tmp_path: Path) -> None:
    report = build_federal_bm25_report(corpus=corpus)
    assert report["task_id"] == TASK_ID
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["acceptance"]["documents_equal_admitted_searchable_chunks"] is True
    assert report["acceptance"]["postings_reconcile"] is True
    assert report["acceptance"]["physical_bounds_hold"] is True
    assert report["acceptance"]["boundary_terms_route_once"] is True
    assert report["acceptance"]["scores_match_reference_bm25"] is True
    assert report["acceptance"]["hub_upload"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["authorizing_for_publication"] is False
    assert report["admitted"]["document_count"] == len(corpus.chunks)
    assert report["family_counts"]["bm25"] == len(corpus.chunks)
    assert report["network_required"] is False
    assert report["differential"]["scores_match_reference_bm25"] is True
    assert report["differential"]["fixtures"]
    assert find_secret_surfaces(report) == []
    blob = json.dumps(report, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob
    assert "sk-" not in blob
    assert_federal_bm25_report(report)
    path = tmp_path / "federal_bm25.json"
    written = write_federal_bm25_report(path, corpus=corpus)
    assert written == path
    loaded = load_federal_bm25_report(path)
    assert loaded["task_id"] == TASK_ID
    assert "/home/" not in path.read_text(encoding="utf-8")


def test_on_disk_bm25_report_matches_contract(corpus) -> None:
    path = default_bm25_report_path()
    write_federal_bm25_report(path, corpus=corpus)
    assert path.is_file()
    assert path.name == "federal_bm25.json"
    assert "legal_corpora_reindex" in path.parts
    loaded = load_federal_bm25_report(path)
    assert loaded["task_id"] == TASK_ID
    assert loaded["acceptance"]["hub_upload"] is False
    assert_federal_bm25_report(loaded)
    blob = path.read_text(encoding="utf-8")
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert loaded["checks"]["admitted_documents_equal_chunks"] is True
    assert loaded["parameters"]["tokenizer_id"] == TOKENIZER_ID

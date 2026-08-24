"""Unit tests for Federal Register BM25/graph adjacency reconciliation (LCR-076).

Acceptance: bounded BM25-neighbor lexical edges are derived from the sealed
BM25 space; every graph edge appears exactly once in both directions;
dangling/duplicate keys are zero; shard/pointer bounds of 4096 hold; receipt
digests gate later tasks. Lexical overlay is not legal authority.

Tests are hermetic. No Hub upload, no tokens, no absolute home paths.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
    TASK_ID as BM25_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.federal_register_graph import (
    ADJACENCY_PAGING_TASK_ID,
    TASK_ID as GRAPH_TASK_ID,
    GraphEdgeClass,
    GraphEdgeType,
    SIMILARITY_EDGE_TYPES,
)
from ipfs_datasets_py.processors.legal_data.federal_register_adjacency_gate import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    AUTHORIZES_RELEASE,
    BUNDLE,
    CANDIDATE_ACCUMULATION_METHOD,
    DEFAULT_NEIGHBOR_K,
    EDGE_AUTHORITY,
    GOAL_ID,
    HUB_UPLOAD,
    INCOMING_ADJACENCY_DIR,
    LEXICAL_GRAPH_DEFAULT_MODE,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_NEIGHBOR_K,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MODE_FIXTURE,
    OUTGOING_ADJACENCY_DIR,
    PRODUCER,
    PROGRAM_ID,
    RECEIPT_SCHEMA_VERSION,
    REPORT_SCHEMA,
    SCHEMA_VERSION,
    TASK_ID,
    VIRTUAL_TERM_DOCUMENT_EDGE_TYPE,
    AdjacencyBoundError,
    AdjacencyConfig,
    AdjacencyDirection,
    AdjacencyPointer,
    AdjacencyReceiptError,
    Bm25NeighborEdge,
    GraphReleaseAuthorizationError,
    LexicalGraphConfig,
    LexicalGraphConfigError,
    LexicalGraphExpansionError,
    LexicalGraphScanError,
    accumulate_neighbor_candidates,
    admitted_rows_for_bm25,
    assert_adjacency_bounded,
    assert_adjacency_reconciled,
    assert_federal_adjacency_reconciliation,
    assert_graph_edges_invert_exactly_once,
    assert_zero_dangling_or_duplicate_keys,
    bind_fixture_graph_adjacency,
    bind_fixture_lexical_graph,
    build_federal_adjacency_reconciliation,
    build_federal_register_lexical_graph,
    build_federal_register_lexical_graph_from_rows,
    build_two_way_adjacency,
    default_adjacency_config,
    default_adjacency_reconciliation_path,
    default_lexical_graph_config,
    fixture_adjacency_config,
    fixture_lexical_chunks,
    isolated_federal_chunk,
    load_federal_adjacency_reconciliation,
    materialize_bm25_neighbor_edges,
    neighbor_query_terms,
    non_authoritative_edge_semantics,
    page_adjacency_pointers,
    production_adjacency_bounds,
    shard_adjacency_pages,
    write_federal_adjacency_reconciliation,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    RELEASE_PROFILE,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import TOKENIZER_ID


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sample_overlay():
    return bind_fixture_lexical_graph()


@pytest.fixture(scope="module")
def isolated_overlay():
    return bind_fixture_lexical_graph(include_isolated=True)


@pytest.fixture(scope="module")
def fixture_bundle():
    return bind_fixture_graph_adjacency()


# ---------------------------------------------------------------------------
# Identity / production bounds
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-adjacency-gate-v1"
    assert RECEIPT_SCHEMA_VERSION == "federal-register-adjacency-reconciliation-v1"
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-federal-adjacency@1"
    assert TASK_ID == "LCR-076"
    assert GOAL_ID == "LCR-G120"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert PRODUCER == "federal_register_adjacency_gate.py"
    assert BUNDLE == "federal-graph-adjacency-reconciliation"
    assert RELEASE_PROFILE == "federal-register-ir-graphrag/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert AUTHORIZES_RELEASE is False
    assert HUB_UPLOAD is False
    assert MODE_FIXTURE == "fixture"
    assert ADJACENCY_PAGING_TASK_ID == "LCR-076"
    assert BM25_TASK_ID == "LCR-056"
    assert GRAPH_TASK_ID == "LCR-058"
    assert TOKENIZER_ID == "federal-register-bm25-tokenizer/v1"
    assert LEXICAL_GRAPH_DEFAULT_MODE == (
        "virtual_term_document_edges_plus_bounded_bm25_neighbors"
    )
    assert CANDIDATE_ACCUMULATION_METHOD == "postings_driven"
    assert default_adjacency_reconciliation_path().name == (
        "federal_adjacency_reconciliation.json"
    )


def test_production_bounds_match_release_policy() -> None:
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ADJACENCY_POINTERS_PER_ROW == 4096
    bounds = production_adjacency_bounds()
    assert bounds["maximum_rows_per_physical_shard"] == 4096
    assert bounds["maximum_adjacency_pointers_per_row"] == 4096
    assert bounds["candidate_accumulation_method"] == "postings_driven"
    assert "all_pairs" in bounds["forbidden_candidate_methods"]
    assert bounds["similarity_cannot_establish_legal_authority"] is True
    assert bounds["full_adjacency_paging"] == "LCR-076"


def test_oversize_adjacency_page_bound_fails_closed() -> None:
    with pytest.raises((AdjacencyBoundError, LexicalGraphConfigError)):
        AdjacencyConfig(max_pointers_per_page=4097)


def test_oversize_adjacency_shard_bound_fails_closed() -> None:
    with pytest.raises((AdjacencyBoundError, LexicalGraphConfigError)):
        AdjacencyConfig(max_rows_per_shard=4097)


def test_all_pairs_candidate_method_is_refused() -> None:
    with pytest.raises(LexicalGraphScanError):
        LexicalGraphConfig(candidate_accumulation="all_pairs")
    with pytest.raises(LexicalGraphScanError):
        LexicalGraphConfig(candidate_accumulation="o_n_squared")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_default_lexical_config_pins_and_rejects_invalid() -> None:
    cfg = default_lexical_graph_config()
    assert cfg.neighbor_k == DEFAULT_NEIGHBOR_K
    assert cfg.max_neighbors_per_document == DEFAULT_NEIGHBOR_K
    assert cfg.materialize_term_document_edges is False
    assert cfg.allow_full_postings_expansion is False
    assert cfg.materialize_neighbors is True
    assert cfg.candidate_accumulation == CANDIDATE_ACCUMULATION_METHOD
    assert cfg.mode == LEXICAL_GRAPH_DEFAULT_MODE
    assert cfg.schema_version == SCHEMA_VERSION
    assert cfg.config_cid.startswith("sha256:")
    with pytest.raises(LexicalGraphConfigError):
        LexicalGraphConfig(neighbor_k=0)
    with pytest.raises(LexicalGraphConfigError):
        LexicalGraphConfig(neighbor_k=MAX_NEIGHBOR_K + 1)
    with pytest.raises(LexicalGraphConfigError):
        LexicalGraphConfig(neighbor_k=8, max_neighbors_per_document=4)
    with pytest.raises(LexicalGraphConfigError):
        LexicalGraphConfig(
            materialize_term_document_edges=True,
            allow_full_postings_expansion=False,
        )


def test_fixture_adjacency_config_is_tight_but_still_4096_capped() -> None:
    cfg = fixture_adjacency_config()
    assert cfg.max_pointers_per_page == 2
    assert cfg.max_rows_per_shard == 2
    assert cfg.max_pointers_per_page <= MAX_ADJACENCY_POINTERS_PER_ROW
    assert default_adjacency_config().max_pointers_per_page == 4096
    assert default_adjacency_config().max_rows_per_shard == 4096


# ---------------------------------------------------------------------------
# BM25 postings are the canonical virtual term-document graph
# ---------------------------------------------------------------------------


def test_overlay_matches_bm25_vocabulary_and_postings(sample_overlay) -> None:
    sample_overlay.assert_bm25_parity()
    index = sample_overlay.index
    assert sample_overlay.term_count == index.term_count
    assert sample_overlay.document_count == index.document_count
    bm25_terms = {term.term for shard in index.term_shards for term in shard.terms}
    assert set(sample_overlay.vocabulary) == bm25_terms
    for shard in index.term_shards:
        for term_row in shard.terms:
            posting = sample_overlay.posting_list(term_row.term)
            assert posting.document_frequency == term_row.document_frequency
            assert len(posting.postings) == term_row.document_frequency
            pointer_cids = [
                pointer.entry_cid
                for cell in term_row.cells
                for pointer in cell.pointers
            ]
            assert list(posting.entry_cids()) == sorted(pointer_cids)
            for edge in posting.postings:
                assert edge.durable is False
                assert edge.authority == EDGE_AUTHORITY
                assert edge.edge_type == VIRTUAL_TERM_DOCUMENT_EDGE_TYPE
                assert edge.term_frequency >= 1


def test_virtual_term_document_traversal(sample_overlay) -> None:
    term = (
        "emissions"
        if sample_overlay.has_term("emissions")
        else sample_overlay.vocabulary[0]
    )
    edges = sample_overlay.documents_for_term(term)
    assert edges
    assert all(not edge.durable for edge in edges)
    entry = edges[0].entry_cid
    terms = sample_overlay.terms_for_document(entry)
    assert term in terms
    assert list(terms) == sorted(terms)


def test_build_from_rows_matches_index_path() -> None:
    rows = fixture_lexical_chunks()
    from_rows = build_federal_register_lexical_graph_from_rows(rows)
    from_index = bind_fixture_lexical_graph(rows)
    assert from_rows.vocabulary == from_index.vocabulary
    assert from_rows.term_document_pair_count == from_index.term_document_pair_count
    assert from_rows.neighbor_edge_count == from_index.neighbor_edge_count


def test_full_term_document_expansion_disabled_by_default(sample_overlay) -> None:
    receipt = sample_overlay.expansion_receipt()
    assert receipt["virtual_traversal_only"] is True
    assert receipt["materialize_term_document_edges"] is False
    assert receipt["durable_term_document_edges"] == 0
    assert sample_overlay.expands_full_term_document_edges is False
    assert sample_overlay.durable_edge_count == sample_overlay.neighbor_edge_count
    with pytest.raises(LexicalGraphExpansionError):
        sample_overlay.materialize_all_term_document_edges()


def test_virtual_iteration_does_not_require_full_materialization(
    sample_overlay,
) -> None:
    streamed = list(sample_overlay.iter_virtual_term_document_edges())
    assert len(streamed) == sample_overlay.term_document_pair_count
    assert sample_overlay.term_document_pair_count > 0
    assert all(not edge.durable for edge in streamed)


def test_opt_in_full_expansion_requires_explicit_flags(sample_overlay) -> None:
    cfg = LexicalGraphConfig(
        materialize_term_document_edges=True,
        allow_full_postings_expansion=True,
        materialize_neighbors=False,
    )
    overlay = build_federal_register_lexical_graph(sample_overlay.index, config=cfg)
    edges = overlay.materialize_all_term_document_edges()
    assert len(edges) == overlay.term_document_pair_count
    assert overlay.expands_full_term_document_edges is True


# ---------------------------------------------------------------------------
# Postings-driven neighbor accumulation (not O(N^2))
# ---------------------------------------------------------------------------


def test_neighbor_candidates_are_exactly_the_posting_union(isolated_overlay) -> None:
    index = isolated_overlay.index
    isolated = isolated_federal_chunk()["entry_cid"]
    source = next(
        document
        for document in index.documents
        if document.entry_cid != isolated
    )
    query_terms = neighbor_query_terms(source, config=isolated_overlay.config)
    candidates = accumulate_neighbor_candidates(
        index, query_terms, exclude_entry_cid=source.entry_cid
    )
    expected: set[str] = set()
    for term in query_terms:
        posting = index.term_posting(term)
        if posting is None:
            continue
        for cell in posting.cells:
            for pointer in cell.pointers:
                if pointer.entry_cid != source.entry_cid:
                    expected.add(pointer.entry_cid)
    assert set(candidates) == expected
    assert isolated not in candidates
    assert source.entry_cid not in candidates


def test_isolated_document_is_never_an_all_pairs_candidate(isolated_overlay) -> None:
    isolated = isolated_federal_chunk()["entry_cid"]
    assert isolated in isolated_overlay.document_terms
    for edge in isolated_overlay.neighbor_edges:
        assert edge.target_entry_cid != isolated or edge.source_entry_cid == isolated
    isolated_neighbors = isolated_overlay.neighbors_for_document(isolated)
    assert isolated_neighbors == ()


def test_neighbor_materialization_records_zero_pair_scans(sample_overlay) -> None:
    stats = sample_overlay.neighbor_build_stats
    assert stats.method == CANDIDATE_ACCUMULATION_METHOD
    assert stats.full_corpus_pair_scans == 0
    assert stats.candidates_scored == stats.posting_candidates
    assert stats.neighbor_edges_emitted == sample_overlay.neighbor_edge_count
    for edge in sample_overlay.neighbor_edges:
        source_terms = set(sample_overlay.terms_for_document(edge.source_entry_cid))
        target_terms = set(sample_overlay.terms_for_document(edge.target_entry_cid))
        assert set(edge.matched_terms) <= source_terms
        assert set(edge.matched_terms) <= target_terms


def test_neighbor_caps_are_enforced(sample_overlay) -> None:
    counts: dict[str, int] = defaultdict(int)
    for edge in sample_overlay.neighbor_edges:
        counts[edge.source_entry_cid] += 1
    assert counts
    for source, count in counts.items():
        assert count <= sample_overlay.config.neighbor_k
        assert count <= sample_overlay.config.max_neighbors_per_document
        neighbors = sample_overlay.neighbors_for_document(source)
        assert len(neighbors) <= sample_overlay.config.neighbor_k


def test_smaller_neighbor_k_is_respected(sample_overlay) -> None:
    cfg = LexicalGraphConfig(neighbor_k=2, max_neighbors_per_document=2)
    overlay = build_federal_register_lexical_graph(sample_overlay.index, config=cfg)
    counts: dict[str, int] = defaultdict(int)
    for edge in overlay.neighbor_edges:
        counts[edge.source_entry_cid] += 1
    assert counts
    assert max(counts.values()) <= 2
    source = next(iter(counts))
    with pytest.raises(LexicalGraphConfigError):
        overlay.neighbors_for_document(source, top_k=3)


def test_materialize_neighbors_can_be_disabled(sample_overlay) -> None:
    cfg = LexicalGraphConfig(materialize_neighbors=False)
    overlay = build_federal_register_lexical_graph(sample_overlay.index, config=cfg)
    assert overlay.neighbor_edge_count == 0
    edges, stats = materialize_bm25_neighbor_edges(sample_overlay.index, config=cfg)
    assert edges == ()
    assert stats.neighbor_edges_emitted == 0


def test_neighbor_edges_are_deterministic(sample_overlay) -> None:
    first = build_federal_register_lexical_graph(sample_overlay.index)
    second = build_federal_register_lexical_graph(sample_overlay.index)
    assert [edge.to_dict() for edge in first.neighbor_edges] == [
        edge.to_dict() for edge in second.neighbor_edges
    ]
    for prev, cur in zip(first.neighbor_edges, first.neighbor_edges[1:]):
        if prev.source_entry_cid == cur.source_entry_cid:
            assert prev.score >= cur.score


def test_edge_semantics_are_explicitly_non_authoritative(sample_overlay) -> None:
    semantics = non_authoritative_edge_semantics()
    assert semantics["authority"] == EDGE_AUTHORITY
    assert semantics["proof_authority"] is False
    assert semantics["legal_authority"] is False
    assert semantics["retrieval_hint"] is True
    assert semantics["edge_class"] == GraphEdgeClass.SIMILARITY.value
    assert sample_overlay.neighbor_edge_count >= 1
    for edge in sample_overlay.neighbor_edges:
        assert isinstance(edge, Bm25NeighborEdge)
        assert edge.edge_type == GraphEdgeType.BM25_NEIGHBOR_OF.value
        assert edge.edge_class == GraphEdgeClass.SIMILARITY.value
        assert edge.authority == EDGE_AUTHORITY
        assert edge.proof_authority is False
        assert edge.candidate_accumulation == CANDIDATE_ACCUMULATION_METHOD
        assert edge.score > 0.0
        assert edge.config_cid.startswith("sha256:")
        assert GraphEdgeType.BM25_NEIGHBOR_OF in SIMILARITY_EDGE_TYPES


def test_similarity_neighbor_projection_for_legal_graph(sample_overlay) -> None:
    sims = sample_overlay.to_similarity_neighbors()
    assert len(sims) == sample_overlay.neighbor_edge_count
    for sim in sims:
        assert sim.edge_type is GraphEdgeType.BM25_NEIGHBOR_OF
        assert sim.metric == "bm25"
        assert sim.config_cid


# ---------------------------------------------------------------------------
# Bounded two-way adjacency
# ---------------------------------------------------------------------------


def test_two_way_adjacency_reconciles_and_resolves(fixture_bundle) -> None:
    overlay, projection, adjacency = fixture_bundle
    assert_adjacency_bounded(adjacency)
    assert_adjacency_reconciled(adjacency)
    assert_graph_edges_invert_exactly_once(adjacency)
    assert_zero_dangling_or_duplicate_keys(adjacency)
    assert adjacency.outgoing_page_count >= 1
    assert adjacency.incoming_page_count >= 1
    assert adjacency.outgoing_shard_count >= 1
    assert adjacency.incoming_shard_count >= 1
    assert overlay.neighbor_edge_count >= 1
    assert projection.graph_cid
    outgoing_triples = {
        (page.node_cid, pointer.edge_cid, pointer.neighbor_node_cid)
        for page in adjacency.outgoing_pages
        for pointer in page.pointers
    }
    incoming_triples = {
        (pointer.neighbor_node_cid, pointer.edge_cid, page.node_cid)
        for page in adjacency.incoming_pages
        for pointer in page.pointers
    }
    assert outgoing_triples == incoming_triples
    for page in (*adjacency.outgoing_pages, *adjacency.incoming_pages):
        for pointer in page.pointers:
            assert pointer.edge_cid in adjacency.edges


def test_every_graph_edge_appears_exactly_once_in_both_directions(fixture_bundle) -> None:
    _overlay, projection, adjacency = fixture_bundle
    outgoing: dict[str, tuple[str, str]] = {}
    incoming: dict[str, tuple[str, str]] = {}
    for page in adjacency.outgoing_pages:
        for pointer in page.pointers:
            assert pointer.edge_cid not in outgoing
            outgoing[pointer.edge_cid] = (page.node_cid, pointer.neighbor_node_cid)
    for page in adjacency.incoming_pages:
        for pointer in page.pointers:
            assert pointer.edge_cid not in incoming
            incoming[pointer.edge_cid] = (pointer.neighbor_node_cid, page.node_cid)
    graph_cids = {edge.edge_cid for edge in projection.edges}
    assert graph_cids <= set(outgoing)
    assert graph_cids <= set(incoming)
    for edge in projection.edges:
        expected = (edge.source_node_cid, edge.target_node_cid)
        assert outgoing[edge.edge_cid] == expected
        assert incoming[edge.edge_cid] == expected


def test_adjacency_pages_and_shards_obey_configured_and_production_bounds(
    fixture_bundle,
) -> None:
    _overlay, _projection, adjacency = fixture_bundle
    assert adjacency.config.max_pointers_per_page == 2
    assert adjacency.config.max_rows_per_shard == 2
    assert adjacency.max_outgoing_pointers <= 2
    assert adjacency.max_incoming_pointers <= 2
    assert adjacency.max_outgoing_shard_rows <= 2
    assert adjacency.max_incoming_shard_rows <= 2
    assert adjacency.max_outgoing_pointers <= MAX_ADJACENCY_POINTERS_PER_ROW
    assert adjacency.max_incoming_pointers <= MAX_ADJACENCY_POINTERS_PER_ROW
    assert adjacency.max_outgoing_shard_rows <= MAX_ROWS_PER_PHYSICAL_SHARD
    assert adjacency.max_incoming_shard_rows <= MAX_ROWS_PER_PHYSICAL_SHARD
    for shard in adjacency.outgoing_shards:
        assert shard.relative_path.startswith(OUTGOING_ADJACENCY_DIR)
        assert shard.row_count <= 2
    for shard in adjacency.incoming_shards:
        assert shard.relative_path.startswith(INCOMING_ADJACENCY_DIR)
        assert shard.row_count <= 2


def test_high_degree_node_is_paged_not_unbounded() -> None:
    node = "sha256:" + ("a" * 64)
    neighbors = [f"sha256:{str(index).zfill(64)}" for index in range(5)]
    pointers = [
        AdjacencyPointer(
            edge_cid=f"sha256:{str(index + 20).zfill(64)}",
            neighbor_node_cid=neighbor,
            edge_type=GraphEdgeType.HAS_SOURCE.value,
            edge_class=GraphEdgeClass.PROVENANCE.value,
        )
        for index, neighbor in enumerate(neighbors)
    ]
    pages = page_adjacency_pointers(
        node, AdjacencyDirection.OUT, pointers, max_pointers=2
    )
    assert len(pages) == 3
    assert all(page.pointer_count <= 2 for page in pages)
    assert sum(page.pointer_count for page in pages) == 5
    shards = shard_adjacency_pages(
        pages, direction=AdjacencyDirection.OUT, max_rows=2
    )
    assert len(shards) == 2
    assert all(shard.row_count <= 2 for shard in shards)


def test_page_split_rejects_oversize_pointer_bound() -> None:
    with pytest.raises((AdjacencyBoundError, LexicalGraphConfigError)):
        page_adjacency_pointers(
            "sha256:" + ("b" * 64),
            "out",
            [
                AdjacencyPointer(
                    edge_cid="sha256:" + ("c" * 64),
                    neighbor_node_cid="sha256:" + ("d" * 64),
                    edge_type="HAS_SOURCE",
                    edge_class="provenance",
                )
            ],
            max_pointers=4097,
        )


def test_recovery_rows_are_excluded_from_bm25_binder() -> None:
    rows = [
        isolated_federal_chunk(),
        {
            "body": "recovery payload",
            "configuration": "recovery",
            "disposition": "quarantined",
            "entry_cid": "sha256:" + ("f" * 64),
            "heading": "recovery",
            "is_recovery": True,
        },
    ]
    admitted = admitted_rows_for_bm25(rows)
    assert len(admitted) == 1
    assert admitted[0]["entry_cid"] == isolated_federal_chunk()["entry_cid"]


def test_rebuild_adjacency_is_deterministic(fixture_bundle) -> None:
    overlay, projection, first = fixture_bundle
    second = build_two_way_adjacency(
        projection, overlay=overlay, config=fixture_adjacency_config()
    )
    assert first.to_dict() == second.to_dict()
    assert [page.to_dict() for page in first.outgoing_pages] == [
        page.to_dict() for page in second.outgoing_pages
    ]
    assert [page.to_dict() for page in first.incoming_pages] == [
        page.to_dict() for page in second.incoming_pages
    ]


def test_zero_dangling_or_duplicate_keys(fixture_bundle) -> None:
    overlay, projection, adjacency = fixture_bundle
    overlay_ids = set(overlay.document_terms)
    bm25_ids = {document.entry_cid for document in overlay.index.documents}
    assert overlay_ids == bm25_ids
    node_cids = {node.node_cid for node in projection.nodes}
    assert set(adjacency.node_cids) == node_cids
    graph_cids = {edge.edge_cid for edge in projection.edges}
    assert graph_cids <= set(adjacency.edges)
    assert len(adjacency.node_cids) == len(set(adjacency.node_cids))
    assert len(adjacency.edges) == len(set(adjacency.edges))
    assert_zero_dangling_or_duplicate_keys(adjacency)


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def test_receipt_is_software_contract_only_and_matches_disk(tmp_path: Path) -> None:
    built = build_federal_adjacency_reconciliation()
    assert_federal_adjacency_reconciliation(built)
    assert built["task_id"] == TASK_ID
    assert built["goal_id"] == GOAL_ID
    assert built["program_id"] == PROGRAM_ID
    assert built["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert built["authorizing_for_release"] is False
    assert built["authorizing_for_publication"] is False
    assert built["authorizing_hub_upload"] is False
    assert built["hub_upload"] is False
    assert built["proves_software_contract_only"] is True
    assert built["mode"] == MODE_FIXTURE
    assert built["network_required"] is False
    assert built["acceptance"][
        "bm25_neighbor_lexical_edges_bounded_and_derived_from_sealed_bm25"
    ]
    assert built["acceptance"][
        "every_graph_edge_appears_exactly_once_in_both_directions"
    ]
    assert built["acceptance"]["zero_dangling_or_duplicate_keys"]
    assert built["acceptance"]["shard_and_pointer_bounds_4096"]
    assert built["acceptance"]["lexical_overlay_is_not_legal_authority"]
    assert built["acceptance"]["secrets_absent"] is True
    assert built["acceptance"]["hub_upload"] is False
    assert built["checks"]["candidate_accumulation_method"] == "postings_driven"
    assert built["checks"]["full_corpus_pair_scans"] == 0
    assert built["checks"]["production_max_adjacency_pointers"] == 4096
    assert built["checks"]["production_max_rows_per_shard"] == 4096
    assert built["checks"]["dangling_keys"] == 0
    assert built["checks"]["duplicate_keys"] == 0
    assert built["checks"]["full_adjacency_paging_owned_by"] == "LCR-076"
    assert built["checks"]["bm25_task_id"] == "LCR-056"
    assert built["checks"]["graph_task_id"] == "LCR-058"
    assert built["demo"]["max_outgoing_pointers"] <= 4096
    assert built["demo"]["max_incoming_pointers"] <= 4096
    assert built["demo"]["max_outgoing_shard_rows"] <= 4096
    assert built["demo"]["max_incoming_shard_rows"] <= 4096
    assert built["receipt_sha256"] == built["report_digest_sha256"]
    assert len(built["receipt_sha256"]) == 64
    assert find_secret_surfaces(built) == []
    blob = json.dumps(built, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob
    assert "sk-" not in blob

    scratch = tmp_path / "federal_adjacency_reconciliation.json"
    write_federal_adjacency_reconciliation(scratch)
    reloaded = load_federal_adjacency_reconciliation(scratch)
    assert reloaded["receipt_sha256"] == built["receipt_sha256"]
    assert reloaded["report_digest_sha256"] == built["report_digest_sha256"]


def test_receipt_refuses_release_authorization() -> None:
    payload = build_federal_adjacency_reconciliation()
    forged = dict(payload)
    forged["authorizing_for_release"] = True
    with pytest.raises(GraphReleaseAuthorizationError):
        assert_federal_adjacency_reconciliation(forged)
    forged = dict(payload)
    forged["authorizing_for_publication"] = True
    with pytest.raises(GraphReleaseAuthorizationError):
        assert_federal_adjacency_reconciliation(forged)
    forged = dict(payload)
    forged["hub_upload"] = True
    with pytest.raises(GraphReleaseAuthorizationError):
        assert_federal_adjacency_reconciliation(forged)


def test_missing_receipt_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(AdjacencyReceiptError):
        load_federal_adjacency_reconciliation(tmp_path / "missing.json")


def test_on_disk_receipt_matches_contract() -> None:
    path = default_adjacency_reconciliation_path()
    write_federal_adjacency_reconciliation(path)
    assert path.is_file()
    assert path.name == "federal_adjacency_reconciliation.json"
    assert "legal_corpora_reindex" in path.parts
    loaded = load_federal_adjacency_reconciliation(path)
    assert loaded["task_id"] == TASK_ID
    assert loaded["goal_id"] == GOAL_ID
    assert loaded["program_id"] == PROGRAM_ID
    assert loaded["acceptance"]["hub_upload"] is False
    assert loaded["acceptance"]["secrets_absent"] is True
    assert loaded["acceptance"]["lexical_overlay_is_not_legal_authority"] is True
    assert_federal_adjacency_reconciliation(loaded)
    blob = path.read_text(encoding="utf-8")
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert loaded["checks"]["graph_edges_invert_exactly_once"] is True
    assert loaded["bounds"]["maximum_rows_per_physical_shard"] == 4096
    assert loaded["bounds"]["maximum_adjacency_pointers_per_row"] == 4096
    assert loaded["depends_on"] == ["LCR-056", "LCR-058"]
    rebuilt = build_federal_adjacency_reconciliation()
    assert loaded["receipt_sha256"] == rebuilt["receipt_sha256"]

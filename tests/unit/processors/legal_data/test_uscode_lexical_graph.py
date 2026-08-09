"""Unit tests for US Code postings-backed lexical graph overlay (USCIR-023).

Acceptance:

* Overlay matches BM25 vocabulary/postings.
* Full 13.6M durable lexical-edge expansion is avoided by default.
* Neighbor caps are enforced.
* Edge semantics are explicitly non-authoritative.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_bm25 import (
    build_uscode_bm25_index,
)
from ipfs_datasets_py.processors.legal_data.uscode_graph import (
    GraphEdgeClass,
    GraphEdgeType,
    SIMILARITY_EDGE_TYPES,
)
from ipfs_datasets_py.processors.legal_data.uscode_lexical_graph import (
    DEFAULT_NEIGHBOR_K,
    EDGE_AUTHORITY,
    EDGE_TYPE_BM25_NEIGHBOR,
    FIXTURE_SCHEMA_VERSION,
    GOAL_ID,
    LEGACY_DOCUMENT_TERM_PAIR_COUNT,
    LEXICAL_GRAPH_DEFAULT_MODE,
    MAX_NEIGHBOR_K,
    SCHEMA_VERSION,
    TASK_ID,
    Bm25NeighborEdge,
    LexicalGraphConfig,
    LexicalGraphConfigError,
    LexicalGraphExpansionError,
    build_default_bm25_neighbors_fixture_payload,
    build_uscode_lexical_graph,
    build_uscode_lexical_graph_from_rows,
    default_bm25_neighbors_fixture_path,
    default_lexical_graph_config,
    load_bm25_neighbors_fixture_payload,
    materialize_bm25_neighbor_edges,
    non_authoritative_edge_semantics,
    run_all_fixture_cases,
    run_fixture_case,
)
from ipfs_datasets_py.processors.legal_data.uscode_tokenizer import TOKENIZER_ID

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_bm25_neighbors.json"
)


def _sample_rows() -> list[dict]:
    return [
        {
            "entry_cid": "sha256:" + ("a" * 64),
            "chunk_cid": "sha256:" + ("b" * 64),
            "legal_id": "usc:us:5:552",
            "title": "5",
            "section": "552",
            "heading": (
                "Public information; agency rules, opinions, orders, records, "
                "and proceedings"
            ),
            "chapter": "5",
            "citation": "5 U.S.C. § 552",
            "body": (
                "Each agency shall make available to the public information "
                "as follows: final opinions and orders made in the adjudication "
                "of cases under the Freedom of Information Act."
            ),
            "note": "Known as the Freedom of Information Act.",
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("c" * 64),
            "chunk_cid": "sha256:" + ("d" * 64),
            "legal_id": "usc:us:5:552a",
            "title": "5",
            "section": "552a",
            "heading": "Records maintained on individuals",
            "chapter": "5",
            "citation": "5 U.S.C. § 552a",
            "body": (
                "No agency shall disclose any record which is contained in a "
                "system of records by any means of communication to any person "
                "or to another agency."
            ),
            "note": "Privacy Act of 1974.",
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("e" * 64),
            "chunk_cid": "sha256:" + ("f" * 64),
            "legal_id": "usc:us:35:101",
            "title": "35",
            "section": "101",
            "heading": "Inventions patentable",
            "chapter": "10",
            "citation": "35 U.S.C. § 101",
            "body": (
                "Whoever invents or discovers any new and useful process, "
                "machine, manufacture, or composition of matter may obtain a patent."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("1" * 64),
            "chunk_cid": "sha256:" + ("2" * 64),
            "legal_id": "usc:us:35:103",
            "title": "35",
            "section": "103",
            "heading": "Conditions for patentability; non-obvious subject matter",
            "chapter": "10",
            "citation": "35 U.S.C. § 103",
            "body": (
                "A patent for a claimed invention may not be obtained if the "
                "differences between the claimed invention and the prior art "
                "would have been obvious before the effective filing date."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "sha256:" + ("3" * 64),
            "chunk_cid": "sha256:" + ("4" * 64),
            "legal_id": "usc:us:17:107",
            "title": "17",
            "section": "107",
            "heading": "Limitations on exclusive rights: Fair use",
            "chapter": "1",
            "citation": "17 U.S.C. § 107",
            "body": (
                "Notwithstanding the provisions of sections 106 and 106A, the "
                "fair use of a copyrighted work is not an infringement of copyright."
            ),
            "disposition": "admitted",
            "release_point": "us/pl/118/45",
        },
        {
            "entry_cid": "",
            "row_id": "recovery-src-01",
            "disposition": "quarantined",
            "is_recovery": True,
            "body": "workflow recovery payload must not enter BM25",
        },
        {
            "entry_cid": "sha256:" + ("9" * 64),
            "disposition": "excluded",
            "body": "excluded incomplete provenance row",
            "title": "99",
            "section": "999",
        },
    ]


@pytest.fixture(scope="module")
def sample_index():
    return build_uscode_bm25_index(_sample_rows())


@pytest.fixture(scope="module")
def sample_overlay(sample_index):
    return build_uscode_lexical_graph(sample_index)


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_neighbors_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_bm25_neighbors_fixture_path().name == "uscode_bm25_neighbors.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 32_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["goal_id"] == GOAL_ID
    assert payload["primary_key"] == "entry_cid"
    assert payload["default_parameters"]["tokenizer_id"] == TOKENIZER_ID
    assert payload["default_parameters"]["mode"] == LEXICAL_GRAPH_DEFAULT_MODE
    assert payload["legacy_document_term_pair_count"] == LEGACY_DOCUMENT_TERM_PAIR_COUNT
    assert payload["acceptance"]["overlay_matches_bm25_vocabulary_postings"]
    assert payload["acceptance"]["full_term_document_expansion_disabled_by_default"]
    assert payload["acceptance"]["neighbor_caps_enforced"]
    assert payload["acceptance"]["edge_semantics_explicitly_non_authoritative"]
    assert isinstance(payload["cases"], list)
    assert len(payload["cases"]) >= 5
    for case in payload["cases"]:
        assert "case_id" in case
        assert "expect" in case
        assert "kind" in case
        # Recipe form: no bulk edge / posting golden dumps.
        assert "edges" not in case
        assert "postings" not in case
        assert "neighbors" not in case
        assert "documents" not in case


def test_default_payload_matches_on_disk_recipe():
    built = build_default_bm25_neighbors_fixture_payload()
    on_disk = load_bm25_neighbors_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["task_id"] == on_disk["task_id"]
    assert built["default_parameters"]["neighbor_k"] == on_disk["default_parameters"][
        "neighbor_k"
    ]
    assert built["default_parameters"]["mode"] == on_disk["default_parameters"]["mode"]
    assert (
        built["legacy_document_term_pair_count"]
        == on_disk["legacy_document_term_pair_count"]
    )
    built_ids = [c["case_id"] for c in built["cases"]]
    disk_ids = [c["case_id"] for c in on_disk["cases"]]
    assert built_ids == disk_ids
    assert built["edge_semantics"] == on_disk["edge_semantics"]


def test_all_sealed_fixture_cases_pass():
    results = run_all_fixture_cases(_FIXTURE_PATH, rows=_sample_rows())
    assert results
    for result in results:
        assert result["ok"], result


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_default_config_pins_and_rejects_invalid():
    cfg = default_lexical_graph_config()
    assert cfg.neighbor_k == DEFAULT_NEIGHBOR_K
    assert cfg.max_neighbors_per_document == DEFAULT_NEIGHBOR_K
    assert cfg.materialize_term_document_edges is False
    assert cfg.allow_full_postings_expansion is False
    assert cfg.materialize_neighbors is True
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


# ---------------------------------------------------------------------------
# BM25 vocabulary / postings parity
# ---------------------------------------------------------------------------


def test_overlay_matches_bm25_vocabulary_and_postings(sample_index, sample_overlay):
    sample_overlay.assert_bm25_parity()
    assert sample_overlay.term_count == sample_index.term_count
    assert sample_overlay.document_count == sample_index.document_count
    assert set(sample_overlay.vocabulary) == set(sample_index.document_frequency)
    for term, df in sample_index.document_frequency.items():
        posting = sample_overlay.posting_list(term)
        assert posting.document_frequency == df
        assert len(posting.postings) == df
        # Every posting document must exist in the BM25 index.
        for edge in posting.postings:
            doc = sample_index.document_by_cid(edge.entry_cid)
            assert term in doc.all_terms()
            assert edge.term_frequency >= 1
            assert edge.durable is False
            assert edge.authority == EDGE_AUTHORITY


def test_virtual_term_document_traversal(sample_overlay):
    # "patent" should hit the Title 35 sections.
    assert sample_overlay.has_term("patent") or any(
        "patent" in t for t in sample_overlay.vocabulary
    )
    term = "patent" if sample_overlay.has_term("patent") else sample_overlay.vocabulary[0]
    edges = sample_overlay.documents_for_term(term)
    assert edges
    assert all(not e.durable for e in edges)
    assert all(e.authority == EDGE_AUTHORITY for e in edges)
    # document→term inverse.
    entry = edges[0].entry_cid
    terms = sample_overlay.terms_for_document(entry)
    assert term in terms
    assert list(terms) == sorted(terms)


def test_build_from_rows_matches_index_path():
    rows = _sample_rows()
    from_rows = build_uscode_lexical_graph_from_rows(rows)
    index = build_uscode_bm25_index(rows)
    from_index = build_uscode_lexical_graph(index)
    assert from_rows.vocabulary == from_index.vocabulary
    assert from_rows.term_document_pair_count == from_index.term_document_pair_count
    assert from_rows.neighbor_edge_count == from_index.neighbor_edge_count


# ---------------------------------------------------------------------------
# Avoid full 13.6M durable expansion by default
# ---------------------------------------------------------------------------


def test_full_term_document_expansion_disabled_by_default(sample_overlay):
    receipt = sample_overlay.expansion_receipt()
    assert receipt["virtual_traversal_only"] is True
    assert receipt["materialize_term_document_edges"] is False
    assert receipt["durable_term_document_edges"] == 0
    assert receipt["legacy_document_term_pair_count"] == LEGACY_DOCUMENT_TERM_PAIR_COUNT
    assert sample_overlay.expands_full_term_document_edges is False
    # Durable edges are only the bounded neighbor projection.
    assert sample_overlay.durable_edge_count == sample_overlay.neighbor_edge_count
    # Full expansion must be refused without explicit dual opt-in.
    with pytest.raises(LexicalGraphExpansionError) as exc_info:
        sample_overlay.materialize_all_term_document_edges()
    assert "13" in str(exc_info.value) or "disabled" in str(exc_info.value).lower()


def test_virtual_iteration_does_not_require_full_materialization(sample_overlay):
    # Streaming virtual edges is always allowed and never marks them durable.
    streamed = list(sample_overlay.iter_virtual_term_document_edges())
    assert len(streamed) == sample_overlay.term_document_pair_count
    assert sample_overlay.term_document_pair_count > 0
    # Pair count for the tiny fixture is far below the legacy 13.6M scale.
    assert sample_overlay.term_document_pair_count < LEGACY_DOCUMENT_TERM_PAIR_COUNT
    assert all(not edge.durable for edge in streamed)


def test_opt_in_full_expansion_requires_explicit_flags(sample_index):
    cfg = LexicalGraphConfig(
        materialize_term_document_edges=True,
        allow_full_postings_expansion=True,
        materialize_neighbors=False,
    )
    overlay = build_uscode_lexical_graph(sample_index, config=cfg)
    edges = overlay.materialize_all_term_document_edges()
    assert len(edges) == overlay.term_document_pair_count
    assert overlay.expands_full_term_document_edges is True


# ---------------------------------------------------------------------------
# Neighbor caps
# ---------------------------------------------------------------------------


def test_neighbor_caps_are_enforced(sample_overlay):
    assert sample_overlay.config.neighbor_k == DEFAULT_NEIGHBOR_K
    counts: dict[str, int] = defaultdict(int)
    for edge in sample_overlay.neighbor_edges:
        counts[edge.source_entry_cid] += 1
    for source, count in counts.items():
        assert count <= sample_overlay.config.neighbor_k
        assert count <= sample_overlay.config.max_neighbors_per_document
        neighbors = sample_overlay.neighbors_for_document(source)
        assert len(neighbors) <= sample_overlay.config.neighbor_k


def test_smaller_neighbor_k_is_respected(sample_index):
    cfg = LexicalGraphConfig(neighbor_k=2, max_neighbors_per_document=2)
    overlay = build_uscode_lexical_graph(sample_index, config=cfg)
    counts: dict[str, int] = defaultdict(int)
    for edge in overlay.neighbor_edges:
        counts[edge.source_entry_cid] += 1
    assert counts
    assert max(counts.values()) <= 2
    # Requesting more than the cap fails closed.
    source = next(iter(counts))
    with pytest.raises(LexicalGraphConfigError):
        overlay.neighbors_for_document(source, top_k=3)


def test_materialize_neighbors_can_be_disabled(sample_index):
    cfg = LexicalGraphConfig(materialize_neighbors=False)
    overlay = build_uscode_lexical_graph(sample_index, config=cfg)
    assert overlay.neighbor_edge_count == 0
    assert materialize_bm25_neighbor_edges(sample_index, config=cfg) == ()


def test_neighbor_edges_are_deterministic(sample_index):
    a = build_uscode_lexical_graph(sample_index)
    b = build_uscode_lexical_graph(sample_index)
    assert [e.to_dict() for e in a.neighbor_edges] == [
        e.to_dict() for e in b.neighbor_edges
    ]
    # Sorted by source, -score, target.
    for i in range(1, len(a.neighbor_edges)):
        prev = a.neighbor_edges[i - 1]
        cur = a.neighbor_edges[i]
        if prev.source_entry_cid == cur.source_entry_cid:
            assert prev.score >= cur.score


# ---------------------------------------------------------------------------
# Non-authoritative edge semantics
# ---------------------------------------------------------------------------


def test_edge_semantics_are_explicitly_non_authoritative(sample_overlay):
    semantics = non_authoritative_edge_semantics()
    assert semantics["authority"] == EDGE_AUTHORITY
    assert semantics["proof_authority"] is False
    assert semantics["legal_authority"] is False
    assert semantics["retrieval_hint"] is True
    assert semantics["edge_class"] == GraphEdgeClass.SIMILARITY.value

    assert sample_overlay.neighbor_edge_count >= 1
    for edge in sample_overlay.neighbor_edges:
        assert isinstance(edge, Bm25NeighborEdge)
        assert edge.edge_type == EDGE_TYPE_BM25_NEIGHBOR
        assert edge.edge_type == GraphEdgeType.BM25_NEIGHBOR_OF.value
        assert edge.edge_class == GraphEdgeClass.SIMILARITY.value
        assert edge.authority == EDGE_AUTHORITY
        assert edge.proof_authority is False
        assert edge.durable is True
        assert edge.config_cid.startswith("sha256:")
        assert edge.score > 0.0
        assert edge.metric == "bm25"
        # Disjoint from legal edge types.
        assert GraphEdgeType.BM25_NEIGHBOR_OF in SIMILARITY_EDGE_TYPES


def test_similarity_neighbor_projection_for_legal_graph(sample_overlay):
    sims = sample_overlay.to_similarity_neighbors()
    assert len(sims) == sample_overlay.neighbor_edge_count
    for sim in sims:
        assert sim.edge_type is GraphEdgeType.BM25_NEIGHBOR_OF
        assert sim.metric == "bm25"
        assert sim.config_cid
        assert sim.score > 0.0
        # legal_id preferred when available.
        assert sim.source_legal_id
        assert sim.target_legal_id


def test_neighbor_edge_rejects_authoritative_semantics():
    with pytest.raises(LexicalGraphConfigError):
        Bm25NeighborEdge(
            source_entry_cid="sha256:" + ("a" * 64),
            target_entry_cid="sha256:" + ("c" * 64),
            score=1.0,
            matched_terms=("patent",),
            config_cid="sha256:" + ("f" * 64),
            authority="legal",
        )
    with pytest.raises(LexicalGraphConfigError):
        Bm25NeighborEdge(
            source_entry_cid="sha256:" + ("a" * 64),
            target_entry_cid="sha256:" + ("c" * 64),
            score=1.0,
            matched_terms=("patent",),
            config_cid="sha256:" + ("f" * 64),
            proof_authority=True,
        )
    with pytest.raises(LexicalGraphConfigError):
        Bm25NeighborEdge(
            source_entry_cid="sha256:" + ("a" * 64),
            target_entry_cid="sha256:" + ("c" * 64),
            score=1.0,
            matched_terms=("patent",),
            config_cid="sha256:" + ("f" * 64),
            edge_type="CITES",
        )


# ---------------------------------------------------------------------------
# Manifest / receipt surface
# ---------------------------------------------------------------------------


def test_manifest_fragment_and_dict_surface(sample_overlay):
    fragment = sample_overlay.to_manifest_fragment()
    assert fragment["task_id"] == TASK_ID
    assert fragment["goal_id"] == GOAL_ID
    lg = fragment["lexical_graph"]
    assert lg["schema_version"] == SCHEMA_VERSION
    assert lg["mode"] == LEXICAL_GRAPH_DEFAULT_MODE
    assert lg["neighbor_k"] == DEFAULT_NEIGHBOR_K
    assert lg["edge_semantics"]["authority"] == EDGE_AUTHORITY
    assert lg["expansion"]["virtual_traversal_only"] is True
    payload = sample_overlay.to_dict()
    assert payload["term_count"] == sample_overlay.term_count
    assert payload["neighbor_edge_count"] == sample_overlay.neighbor_edge_count


def test_fixture_case_runner_rejects_unknown_kind():
    with pytest.raises(Exception):
        run_fixture_case({"case_id": "x", "kind": "not-a-real-kind", "expect": {}})

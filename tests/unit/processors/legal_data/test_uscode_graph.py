"""Unit tests for legal ontology and citation projection (USCIR-021).

Acceptance:

* Legal and similarity semantics are disjoint.
* Unresolved citations are preserved honestly.
* Source spans are bound.
* Fixture graph paths match the sealed expectations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.uscode_graph import (
    CITATION_PARSER_VERSION,
    FIXTURE_SCHEMA_VERSION,
    GRAPH_ONTOLOGY,
    LEGAL_EDGE_TYPES,
    ONTOLOGY_VERSION,
    SCHEMA_VERSION,
    SIMILARITY_EDGE_TYPES,
    SPAN_REQUIRED_EDGE_TYPES,
    TASK_ID,
    GraphCorpusRow,
    GraphEdgeClass,
    GraphEdgeType,
    GraphFixtureError,
    GraphNodeType,
    GraphOntology,
    GraphOntologyError,
    GraphProjectionError,
    LegalSimilarityCollisionError,
    ResolutionStatus,
    SourceSpan,
    SourceSpanError,
    UscodeGraphEdge,
    UscodeGraphNode,
    UscodeGraphProjector,
    assert_legal_similarity_disjoint,
    build_default_graph_expected_fixture_payload,
    default_graph_expected_fixture_path,
    extract_citation_mentions,
    find_graph_paths,
    load_graph_expected_fixture_payload,
    match_expected_paths,
    project_uscode_graph,
    resolve_citations,
    run_fixture_case,
)

# tests/unit/processors/legal_data/this_file.py → tests/
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "legal_ir"
    / "uscode_graph_expected.json"
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return load_graph_expected_fixture_payload(_FIXTURE_PATH)


@pytest.fixture(scope="module")
def fixture_projection(fixture_payload: dict):
    return project_uscode_graph(
        fixture_payload["records"],
        similarity_neighbors=fixture_payload.get("similarity_neighbors") or [],
    )


# ---------------------------------------------------------------------------
# Fixture integrity
# ---------------------------------------------------------------------------


def test_graph_expected_fixture_is_present_and_compact():
    assert _FIXTURE_PATH.is_file()
    assert default_graph_expected_fixture_path().name == "uscode_graph_expected.json"
    size = _FIXTURE_PATH.stat().st_size
    assert size < 64_000
    payload = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert payload["task_id"] == TASK_ID
    assert payload["ontology_version"] == ONTOLOGY_VERSION
    assert payload["acceptance"]["legal_and_similarity_semantics_disjoint"]
    assert payload["acceptance"]["unresolved_citations_preserved_honestly"]
    assert payload["acceptance"]["source_spans_are_bound"]
    assert payload["acceptance"]["fixture_graph_paths_match"]
    assert isinstance(payload["records"], list)
    assert isinstance(payload["expected_paths"], list)
    assert len(payload["expected_paths"]) >= 8
    # Recipe form: no bulk node/edge golden dumps.
    assert "nodes" not in payload
    assert "edges" not in payload


def test_default_payload_matches_on_disk_recipe():
    built = build_default_graph_expected_fixture_payload()
    on_disk = load_graph_expected_fixture_payload(_FIXTURE_PATH)
    assert built["schema_version"] == on_disk["schema_version"]
    assert built["task_id"] == on_disk["task_id"]
    assert built["ontology_version"] == on_disk["ontology_version"]
    built_ids = [p["path_id"] for p in built["expected_paths"]]
    disk_ids = [p["path_id"] for p in on_disk["expected_paths"]]
    assert built_ids == disk_ids
    assert [r["legal_id"] for r in built["records"]] == [
        r["legal_id"] for r in on_disk["records"]
    ]


def test_malformed_fixture_rejected(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": "nope", "records": []}), encoding="utf-8")
    with pytest.raises(GraphFixtureError):
        load_graph_expected_fixture_payload(bad)


def test_sealed_fixture_case_passes(fixture_payload: dict):
    outcome = run_fixture_case(fixture_payload)
    assert outcome["ok"], outcome
    assert outcome["unresolved_ok"]
    assert not outcome["span_errors"]
    assert not outcome["similarity_leaked_into_legal_paths"]
    assert all(item["matched"] for item in outcome["path_matches"])


# ---------------------------------------------------------------------------
# Ontology: legal vs similarity disjoint
# ---------------------------------------------------------------------------


def test_legal_and_similarity_edge_types_are_disjoint():
    assert_legal_similarity_disjoint()
    assert not (LEGAL_EDGE_TYPES & SIMILARITY_EDGE_TYPES)
    for edge_type in SIMILARITY_EDGE_TYPES:
        assert GRAPH_ONTOLOGY.edge_class_for(edge_type) is GraphEdgeClass.SIMILARITY
    for edge_type in LEGAL_EDGE_TYPES:
        assert GRAPH_ONTOLOGY.edge_class_for(edge_type) is not GraphEdgeClass.SIMILARITY


def test_ontology_rejects_wrong_edge_class_for_legal_edge():
    with pytest.raises((GraphOntologyError, LegalSimilarityCollisionError)):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.CITES,
            GraphNodeType.SECTION,
            GraphNodeType.SECTION,
            edge_class=GraphEdgeClass.SIMILARITY,
        )


def test_ontology_rejects_wrong_direction():
    with pytest.raises(GraphOntologyError):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.CODIFIES,
            GraphNodeType.SECTION,
            GraphNodeType.PUBLIC_LAW,
        )


def test_similarity_neighbor_cannot_use_legal_edge_type():
    with pytest.raises(LegalSimilarityCollisionError):
        from ipfs_datasets_py.processors.legal_data.uscode_graph import (
            SimilarityNeighbor,
        )

        SimilarityNeighbor(
            source_legal_id="usc:us:35:101",
            target_legal_id="usc:us:35:102",
            score=1.0,
            edge_type=GraphEdgeType.CITES,
        )


def test_projection_keeps_similarity_out_of_legal_paths(fixture_projection):
    fixture_projection.assert_semantics_disjoint()
    assert fixture_projection.similarity_edge_count == 1
    legal_paths = find_graph_paths(fixture_projection, legal_only=True)
    for path in legal_paths:
        for edge_type in path.edge_types:
            assert edge_type not in {e.value for e in SIMILARITY_EDGE_TYPES}
    # Similarity edges exist but are non-authoritative.
    sim_edges = fixture_projection.similarity_edges()
    assert len(sim_edges) == 1
    assert sim_edges[0].edge_type is GraphEdgeType.BM25_NEIGHBOR_OF
    assert sim_edges[0].edge_class is GraphEdgeClass.SIMILARITY
    assert sim_edges[0].payload.get("authority") == "non_authoritative"


# ---------------------------------------------------------------------------
# Unresolved citations preserved honestly
# ---------------------------------------------------------------------------


def test_unresolved_citations_preserve_source_text_and_parser_version(fixture_projection):
    unresolved_nodes = [
        n
        for n in fixture_projection.nodes
        if n.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]
    assert unresolved_nodes
    for node in unresolved_nodes:
        assert node.legal_id is None
        assert node.payload.get("resolution_status") == ResolutionStatus.UNRESOLVED.value
        assert node.payload.get("mention_text")
        assert node.payload.get("parser_version") == CITATION_PARSER_VERSION

    unresolved_edges = [
        e
        for e in fixture_projection.edges
        if e.edge_type is GraphEdgeType.CITES_UNRESOLVED
    ]
    assert unresolved_edges
    for edge in unresolved_edges:
        assert edge.resolution_status is ResolutionStatus.UNRESOLVED
        assert edge.source_span is not None
        assert edge.source_span.text
        assert edge.payload.get("parser_version") == CITATION_PARSER_VERSION
    # At least one sealed unresolved mention from the fixture recipe.
    unresolved_texts = " ".join(
        e.source_span.text for e in unresolved_edges if e.source_span is not None
    )
    assert "9999" in unresolved_texts or "§ 41" in unresolved_texts


def test_resolve_citations_does_not_invent_targets():
    text = "See 99 U.S.C. § 9999 for a fictional provision."
    resolved = resolve_citations(text, known_legal_ids=["usc:us:35:101"])
    assert len(resolved) == 1
    item = resolved[0]
    assert item.resolution_status is ResolutionStatus.UNRESOLVED
    assert item.target_legal_id is None
    assert item.span.text
    assert item.mention.parser_version == CITATION_PARSER_VERSION


def test_resolved_usc_citation_against_known_set():
    text = "Cross-ref 35 U.S.C. § 102."
    resolved = resolve_citations(text, known_legal_ids=["usc:us:35:102"])
    assert len(resolved) == 1
    assert resolved[0].resolution_status is ResolutionStatus.RESOLVED
    assert resolved[0].target_legal_id == "usc:us:35:102"


# ---------------------------------------------------------------------------
# Source spans bound
# ---------------------------------------------------------------------------


def test_source_span_binds_to_source_text():
    text = "See 35 U.S.C. § 101 today."
    span = SourceSpan.from_occurrence(text, "35 U.S.C. § 101")
    assert span.start >= 0
    assert text[span.start : span.end] == span.text
    span.bind_to_source(text)


def test_source_span_rejects_mismatch():
    with pytest.raises(SourceSpanError):
        SourceSpan(start=0, end=3, text="nope").bind_to_source("abc")


def test_span_required_edges_have_bound_spans(fixture_projection):
    for edge in fixture_projection.edges:
        if edge.edge_type in SPAN_REQUIRED_EDGE_TYPES:
            assert edge.source_span is not None
            assert edge.source_span.end >= edge.source_span.start
            assert len(edge.source_span.text) == edge.source_span.end - edge.source_span.start


def test_cites_edge_without_span_rejected():
    src = UscodeGraphNode(
        node_type=GraphNodeType.SECTION,
        node_key="section:usc:us:35:101",
        label="101",
        legal_id="usc:us:35:101",
    )
    tgt = UscodeGraphNode(
        node_type=GraphNodeType.SECTION,
        node_key="section:usc:us:35:102",
        label="102",
        legal_id="usc:us:35:102",
    )
    with pytest.raises(SourceSpanError):
        UscodeGraphEdge(
            edge_type=GraphEdgeType.CITES,
            source_node_cid=src.node_cid,
            target_node_cid=tgt.node_cid,
            edge_class=GraphEdgeClass.CITATION,
            source_span=None,
        )


# ---------------------------------------------------------------------------
# Projection coverage
# ---------------------------------------------------------------------------


def test_projection_emits_structural_citation_public_law_and_version_edges(
    fixture_projection,
):
    edge_types = {e.edge_type for e in fixture_projection.edges}
    assert GraphEdgeType.CONTAINS in edge_types
    assert GraphEdgeType.CITES in edge_types
    assert GraphEdgeType.CODIFIES in edge_types
    assert GraphEdgeType.AMENDS in edge_types
    assert GraphEdgeType.TRANSFERS in edge_types
    assert GraphEdgeType.HAS_SOURCE in edge_types
    assert GraphEdgeType.HAS_VERSION in edge_types
    assert GraphEdgeType.CITES_UNRESOLVED in edge_types
    assert GraphEdgeType.DERIVED_FROM in edge_types
    assert GraphEdgeType.BM25_NEIGHBOR_OF in edge_types

    node_types = {n.node_type for n in fixture_projection.nodes}
    assert GraphNodeType.CODE in node_types
    assert GraphNodeType.TITLE in node_types
    assert GraphNodeType.CHAPTER in node_types
    assert GraphNodeType.SECTION in node_types
    assert GraphNodeType.PUBLIC_LAW in node_types
    assert GraphNodeType.UNRESOLVED_CITATION in node_types
    assert GraphNodeType.VERSION in node_types


def test_projection_is_deterministic(fixture_payload: dict):
    first = project_uscode_graph(
        fixture_payload["records"],
        similarity_neighbors=fixture_payload.get("similarity_neighbors") or [],
    )
    second = project_uscode_graph(
        fixture_payload["records"],
        similarity_neighbors=fixture_payload.get("similarity_neighbors") or [],
    )
    assert first.graph_cid == second.graph_cid
    assert [n.node_cid for n in first.nodes] == [n.node_cid for n in second.nodes]
    assert [e.edge_cid for e in first.edges] == [e.edge_cid for e in second.edges]


def test_empty_corpus_fails_closed():
    with pytest.raises(GraphProjectionError):
        project_uscode_graph([])


def test_extract_public_law_and_stat_mentions():
    text = "Enacted by Pub. L. 112-29; see also 125 Stat. 284."
    mentions = extract_citation_mentions(text)
    kinds = {m.kind for m in mentions}
    assert "public_law" in kinds
    assert "statutes_at_large" in kinds


# ---------------------------------------------------------------------------
# Fixture graph paths match sealed expectations
# ---------------------------------------------------------------------------


def test_fixture_graph_paths_match_sealed_expectations(
    fixture_payload: dict, fixture_projection
):
    matches = match_expected_paths(
        fixture_projection, fixture_payload["expected_paths"]
    )
    assert matches
    failed = [m for m in matches if not m["matched"]]
    assert not failed, failed


def test_each_expected_path_has_stable_path_id(fixture_payload: dict):
    ids = [p["path_id"] for p in fixture_payload["expected_paths"]]
    assert len(ids) == len(set(ids))
    for path in fixture_payload["expected_paths"]:
        assert path["source_key"]
        assert path["target_key"]
        assert path["edge_types"]


def test_schema_versions_stable():
    assert SCHEMA_VERSION.startswith("uscode-graph")
    assert ONTOLOGY_VERSION.startswith("uscode-graph-ontology")
    assert FIXTURE_SCHEMA_VERSION.startswith("uscode-graph-expected")
    assert GraphOntology().version == ONTOLOGY_VERSION


def test_corpus_row_from_mapping_builds_legal_id():
    row = GraphCorpusRow.from_mapping(
        {
            "entry_cid": "sha256:" + "a" * 64,
            "title": "35",
            "section": "101",
            "text": "sample",
        }
    )
    assert row.legal_id == "usc:us:35:101"


def test_projector_class_matches_module_helper(fixture_payload: dict):
    via_class = UscodeGraphProjector().project(fixture_payload["records"])
    via_helper = project_uscode_graph(fixture_payload["records"])
    # Without similarity neighbors both should still be consistent with themselves.
    assert via_class.legal_edge_count == via_helper.legal_edge_count
    assert len(via_class.nodes) == len(via_helper.nodes)

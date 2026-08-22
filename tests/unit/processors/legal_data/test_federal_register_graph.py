"""Unit tests for the Federal Register agency/rulemaking/citation graph (LCR-058).

Acceptance: endpoint closure, edge uniqueness, adjacency inversion, family
bounds, provenance paths, and unresolved-reference accounting pass.

Tests are hermetic. No Hub upload, no tokens, no absolute home paths, and
no network. Similarity/lexical neighbors are not legal authority.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (
    find_secret_surfaces,
)
from ipfs_datasets_py.processors.legal_data.federal_register_bm25 import (
    TASK_ID as BM25_TASK_ID,
)
from ipfs_datasets_py.processors.legal_data.federal_register_corpus import (
    materialize_federal_register_corpus,
)
from ipfs_datasets_py.processors.legal_data.federal_register_graph import (
    ADJACENCY_PAGING_TASK_ID,
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    CITATION_PARSER_VERSION,
    GOAL_ID,
    GRAPH_ONTOLOGY,
    LEGAL_EDGE_TYPES,
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    MODE_FIXTURE,
    NON_AUTHORITATIVE_AUTHORITY,
    ONTOLOGY_VERSION,
    PRIMARY_KEY,
    PRODUCER,
    PROGRAM_ID,
    REPORT_SCHEMA,
    REQUIRED_COVERAGE_NODE_TYPES,
    SCHEMA_VERSION,
    SIMILARITY_EDGE_TYPES,
    TASK_ID,
    FederalRegisterGraphProjection,
    GraphBoundError,
    GraphCorpusRow,
    GraphEdgeClass,
    GraphEdgeType,
    GraphNodeType,
    GraphOntologyError,
    GraphProjectionError,
    LegalSimilarityCollisionError,
    ResolutionStatus,
    SimilarityNeighbor,
    assert_adjacency_inversion,
    assert_edge_uniqueness,
    assert_endpoint_closure,
    assert_family_bounds,
    assert_federal_graph_report,
    assert_legal_similarity_disjoint,
    assert_provenance_paths,
    assert_unresolved_reference_accounting,
    bind_fixture_graph,
    build_corpus_root_cid,
    build_federal_graph_report,
    default_graph_report_path,
    extract_citation_mentions,
    find_graph_paths,
    fixture_graph_config,
    fixture_graph_rows,
    load_federal_graph_report,
    production_graph_bounds,
    production_graph_config,
    project_federal_register_graph,
    project_federal_register_graph_from_corpus,
    reconcile_roots,
    rows_from_materialized_corpus,
    write_federal_graph_report,
)
from ipfs_datasets_py.processors.legal_data.federal_register_release_schema import (
    RELEASE_PROFILE,
)


def _cid(nibble: str) -> str:
    return f"sha256:{nibble.lower() * 64}"


@pytest.fixture(scope="module")
def corpus():
    return materialize_federal_register_corpus()


@pytest.fixture(scope="module")
def compact_graph():
    return bind_fixture_graph()


# ---------------------------------------------------------------------------
# Identity / production bounds
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "federal-register-graph-v1"
    assert ONTOLOGY_VERSION == "federal-register-graph-ontology/v1"
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-federal-graph@1"
    assert TASK_ID == "LCR-058"
    assert GOAL_ID == "LCR-G120"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert PRODUCER == "federal_register_graph.py"
    assert PRIMARY_KEY == "node_cid"
    assert CITATION_PARSER_VERSION == "federal-register-citation-parser/v1"
    assert RELEASE_PROFILE == "federal-register-ir-graphrag/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert MODE_FIXTURE == "fixture"
    assert ADJACENCY_PAGING_TASK_ID == "LCR-076"
    assert BM25_TASK_ID == "LCR-056"


def test_production_bounds_match_release_policy() -> None:
    assert MAX_ROWS_PER_PHYSICAL_SHARD == 4096
    assert MAX_ADJACENCY_POINTERS_PER_ROW == 4096
    bounds = production_graph_bounds()
    assert bounds["maximum_rows_per_physical_shard"] == 4096
    assert bounds["maximum_adjacency_pointers_per_row"] == 4096
    assert bounds["similarity_cannot_establish_legal_authority"] is True
    assert bounds["full_adjacency_paging"] == "LCR-076"
    production = production_graph_config()
    fixture = fixture_graph_config()
    assert production.max_rows_per_physical_shard == 4096
    assert production.max_adjacency_pointers_per_row == 4096
    assert fixture.max_rows_per_physical_shard == 2
    assert fixture.max_adjacency_pointers_per_row == 8


def test_oversize_adjacency_bound_fails_closed() -> None:
    with pytest.raises(GraphBoundError):
        fixture_graph_config(max_adjacency_pointers_per_row=4097)


def test_oversize_shard_bound_fails_closed() -> None:
    with pytest.raises(GraphBoundError):
        fixture_graph_config(max_rows_per_physical_shard=4097)


# ---------------------------------------------------------------------------
# Ontology: legal vs similarity disjoint
# ---------------------------------------------------------------------------


def test_legal_and_similarity_edge_types_are_disjoint() -> None:
    assert_legal_similarity_disjoint()
    assert not (LEGAL_EDGE_TYPES & SIMILARITY_EDGE_TYPES)
    for edge_type in SIMILARITY_EDGE_TYPES:
        assert GRAPH_ONTOLOGY.edge_class_for(edge_type) is GraphEdgeClass.SIMILARITY
    for edge_type in LEGAL_EDGE_TYPES:
        assert GRAPH_ONTOLOGY.edge_class_for(edge_type) is not GraphEdgeClass.SIMILARITY


def test_ontology_rejects_wrong_edge_class_for_legal_edge() -> None:
    with pytest.raises((GraphOntologyError, LegalSimilarityCollisionError)):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.CITES,
            GraphNodeType.DOCUMENT,
            GraphNodeType.CITATION_CFR,
            edge_class=GraphEdgeClass.SIMILARITY,
        )


def test_ontology_rejects_wrong_direction() -> None:
    with pytest.raises(GraphOntologyError):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.ISSUED_BY,
            GraphNodeType.AGENCY,
            GraphNodeType.DOCUMENT,
        )


def test_similarity_neighbor_cannot_use_legal_edge_type() -> None:
    with pytest.raises(LegalSimilarityCollisionError):
        SimilarityNeighbor(
            source_legal_id="fr:2026-04567:2026-03-16:type=rule",
            target_legal_id="fr:2026-04568:2026-03-16:type=proposed_rule",
            score=1.0,
            edge_type=GraphEdgeType.CITES,
        )


def test_required_coverage_node_types_are_declared() -> None:
    declared = set(GRAPH_ONTOLOGY.node_types)
    for required in REQUIRED_COVERAGE_NODE_TYPES:
        assert required in declared


# ---------------------------------------------------------------------------
# Compact fixture projection
# ---------------------------------------------------------------------------


def test_compact_fixture_covers_required_node_and_edge_types(compact_graph) -> None:
    compact_graph.assert_coverage()
    node_types = {item.node_type.value for item in compact_graph.nodes}
    for required in REQUIRED_COVERAGE_NODE_TYPES:
        assert required in node_types, required
    edge_types = {item.edge_type for item in compact_graph.edges}
    assert GraphEdgeType.ISSUED_BY in edge_types
    assert GraphEdgeType.HAS_DOCKET in edge_types
    assert GraphEdgeType.HAS_RIN in edge_types
    assert GraphEdgeType.CITES in edge_types
    assert GraphEdgeType.CITES_UNRESOLVED in edge_types
    assert GraphEdgeType.CORRECTS in edge_types
    assert GraphEdgeType.RELATED_TO in edge_types
    assert GraphEdgeType.PUBLISHED_ON in edge_types
    assert GraphEdgeType.EFFECTIVE_ON in edge_types
    assert GraphEdgeType.HAS_PROVENANCE in edge_types
    assert GraphEdgeType.HAS_SOURCE in edge_types
    assert GraphEdgeType.DERIVED_FROM in edge_types
    assert GraphEdgeType.BM25_NEIGHBOR_OF in edge_types


def test_quarantine_and_excluded_rows_never_enter_the_graph(compact_graph) -> None:
    identities = {node.entry_cid for node in compact_graph.nodes if node.entry_cid}
    assert _cid("f") not in identities
    assert compact_graph.document_count == 8
    assert compact_graph.skipped_row_count == 2
    assert compact_graph.family_counts()["graph"] == 8


def test_shared_docket_and_rin_nodes_are_reused(compact_graph) -> None:
    dockets = [node for node in compact_graph.nodes if node.node_type is GraphNodeType.DOCKET]
    rins = [node for node in compact_graph.nodes if node.node_type is GraphNodeType.RIN]
    docket_keys = {node.node_key for node in dockets}
    rin_keys = {node.node_key for node in rins}
    assert "docket:EPA-HQ-OAR-2026-0001" in docket_keys
    assert "rin:2060-AV00" in rin_keys
    docket_edges = [
        edge
        for edge in compact_graph.edges
        if edge.edge_type is GraphEdgeType.HAS_DOCKET
        and compact_graph.node_by_cid()[edge.target_node_cid].node_key
        == "docket:EPA-HQ-OAR-2026-0001"
    ]
    assert len(docket_edges) == 2


def test_agencies_dates_and_rulemaking_identifiers_are_projected(compact_graph) -> None:
    agencies = {
        node.label
        for node in compact_graph.nodes
        if node.node_type is GraphNodeType.AGENCY
    }
    assert "Environmental Protection Agency" in agencies
    assert "Department of Transportation" in agencies
    dates = {
        node.payload.get("date")
        for node in compact_graph.nodes
        if node.node_type is GraphNodeType.DATE
    }
    assert "2026-03-16" in dates
    assert "2026-04-15" in dates
    paths = find_graph_paths(
        compact_graph,
        legal_only=True,
        source_keys=["document:fr:2026-04567:2026-03-16:type=rule"],
        max_depth=1,
    )
    edge_types = {path.edge_types[0] for path in paths}
    assert "ISSUED_BY" in edge_types
    assert "HAS_DOCKET" in edge_types
    assert "HAS_RIN" in edge_types
    assert "PUBLISHED_ON" in edge_types
    assert "EFFECTIVE_ON" in edge_types


def test_correction_and_related_document_edges(compact_graph) -> None:
    by_key = compact_graph.node_by_key()
    correction_source = by_key["document:fr:2026-07001:2026-06-01:type=notice:rel=corrects:related=2026-04567"]
    correction_target = by_key["document:fr:2026-04567:2026-03-16:type=rule"]
    corrects = [
        edge
        for edge in compact_graph.edges
        if edge.edge_type is GraphEdgeType.CORRECTS
        and edge.source_node_cid == correction_source.node_cid
        and edge.target_node_cid == correction_target.node_cid
    ]
    assert corrects
    related = [
        node
        for node in compact_graph.nodes
        if node.node_type is GraphNodeType.RELATED_DOCUMENT
    ]
    assert related
    assert all(
        node.legal_id is None
        and node.payload.get("resolution_status") == ResolutionStatus.UNRESOLVED.value
        for node in related
    )
    assert any(node.document_number == "2026-99999" for node in related)


# ---------------------------------------------------------------------------
# Citations / unresolved honesty
# ---------------------------------------------------------------------------


def test_extract_citation_mentions_covers_cfr_usc_and_fr_volume() -> None:
    text = "See 40 C.F.R. § 98.1, 42 U.S.C. § 7412, and 91 FR 99999."
    mentions = extract_citation_mentions(text)
    kinds = {item.kind for item in mentions}
    assert kinds == {"cfr", "usc", "fr_volume"}


def test_unresolved_citations_preserve_source_text_and_parser_version(compact_graph) -> None:
    unresolved_nodes = [
        item
        for item in compact_graph.nodes
        if item.node_type is GraphNodeType.UNRESOLVED_CITATION
    ]
    assert unresolved_nodes
    for node in unresolved_nodes:
        assert node.legal_id is None
        assert node.payload.get("resolution_status") == ResolutionStatus.UNRESOLVED.value
        assert node.payload.get("mention_text")
        assert node.payload.get("parser_version") == CITATION_PARSER_VERSION
    unresolved_edges = [
        item
        for item in compact_graph.edges
        if item.edge_type is GraphEdgeType.CITES_UNRESOLVED
    ]
    assert unresolved_edges
    texts = " ".join(
        item.source_span.text for item in unresolved_edges if item.source_span is not None
    )
    assert "91 FR 99999" in texts or "91 FR" in texts
    accounting = assert_unresolved_reference_accounting(compact_graph)
    assert accounting["unresolved_citations"] == compact_graph.unresolved_count
    assert accounting["unresolved_related_documents"] == compact_graph.unresolved_related_count


def test_resolved_cfr_usc_and_fr_citations_are_typed(compact_graph) -> None:
    cfr = compact_graph.nodes_of_type(GraphNodeType.CITATION_CFR)
    usc = compact_graph.nodes_of_type(GraphNodeType.CITATION_USC)
    fr_cite = compact_graph.nodes_of_type(GraphNodeType.CITATION_FR)
    assert cfr
    assert usc
    assert fr_cite
    assert any("98.1" in (node.payload.get("section") or "") for node in cfr)
    assert any(node.payload.get("section") == "7412" for node in usc)
    assert any(node.payload.get("document_number") == "2026-04567" for node in fr_cite)
    cites = [edge for edge in compact_graph.edges if edge.edge_type is GraphEdgeType.CITES]
    assert cites
    assert all(edge.source_span is not None for edge in cites)


def test_unresolved_references_never_invent_targets(compact_graph) -> None:
    invented = [
        node
        for node in compact_graph.nodes
        if node.node_type in {GraphNodeType.UNRESOLVED_CITATION, GraphNodeType.RELATED_DOCUMENT}
        and node.legal_id is not None
    ]
    assert invented == []
    for edge in compact_graph.edges:
        if edge.resolution_status is ResolutionStatus.UNRESOLVED:
            assert edge.payload.get("invented_target") is not True


# ---------------------------------------------------------------------------
# Acceptance gates
# ---------------------------------------------------------------------------


def test_endpoint_closure_edge_uniqueness_and_adjacency_inversion(compact_graph) -> None:
    assert isinstance(compact_graph, FederalRegisterGraphProjection)
    assert_endpoint_closure(compact_graph)
    assert_edge_uniqueness(compact_graph)
    assert_adjacency_inversion(compact_graph)
    assert_family_bounds(compact_graph)
    assert compact_graph.graph_cid.startswith("sha256:")
    node_cids = [node.node_cid for node in compact_graph.nodes]
    assert node_cids == sorted(
        node_cids,
        key=lambda cid: (
            compact_graph.node_by_cid()[cid].node_type.value,
            compact_graph.node_by_cid()[cid].node_key,
            cid,
        ),
    )


def test_outgoing_is_the_inverse_of_incoming(compact_graph) -> None:
    outgoing = {
        pointer.edge_cid: (descriptor.node_cid, pointer.neighbor_cid)
        for descriptor in compact_graph.outgoing
        for pointer in descriptor.pointers
    }
    incoming = {
        pointer.edge_cid: (pointer.neighbor_cid, descriptor.node_cid)
        for descriptor in compact_graph.incoming
        for pointer in descriptor.pointers
    }
    assert outgoing == incoming
    assert set(outgoing) == {edge.edge_cid for edge in compact_graph.edges}


def test_family_bounds_hold_on_compact_descriptors(compact_graph) -> None:
    assert_family_bounds(compact_graph)
    paged = False
    for descriptor in (*compact_graph.outgoing, *compact_graph.incoming):
        assert descriptor.pointer_count <= compact_graph.config.max_adjacency_pointers_per_row
        assert descriptor.pointer_count <= 4096
        assert descriptor.page_index >= 0
        if descriptor.page_index > 0:
            paged = True
    assert paged, "fixture bound must exercise summarized multi-page adjacency"


def test_provenance_paths_bind_official_source_fields(compact_graph) -> None:
    paths = assert_provenance_paths(compact_graph)
    assert paths
    documents = compact_graph.nodes_of_type(GraphNodeType.DOCUMENT)
    provenance_sources = {
        path.source_key for path in paths if path.edge_types == ("HAS_PROVENANCE",)
    }
    assert provenance_sources == {node.node_key for node in documents}
    for node in compact_graph.nodes_of_type(GraphNodeType.PROVENANCE):
        assert (
            node.payload.get("official_source_url")
            or node.payload.get("source_cid")
            or node.payload.get("acquisition_receipt_id")
        )
    for node in compact_graph.nodes_of_type(GraphNodeType.SOURCE):
        assert node.payload.get("source_cid")
        assert str(node.payload.get("official_source_url") or "").startswith("https://")


def test_similarity_edges_are_non_authoritative(compact_graph) -> None:
    similar = [edge for edge in compact_graph.edges if edge.is_similarity]
    assert similar
    for edge in similar:
        assert edge.edge_class is GraphEdgeClass.SIMILARITY
        assert edge.payload.get("authority") == NON_AUTHORITATIVE_AUTHORITY
        assert edge.edge_type in SIMILARITY_EDGE_TYPES
    legal_paths = find_graph_paths(compact_graph, legal_only=True, max_depth=2)
    for path in legal_paths:
        assert "BM25_NEIGHBOR_OF" not in path.edge_types
        assert "SIMILAR_TO" not in path.edge_types
        assert "EMBEDDING_NEIGHBOR_OF" not in path.edge_types


def test_positional_identity_is_rejected() -> None:
    with pytest.raises(Exception):
        project_federal_register_graph(
            [
                {
                    "entry_cid": "row-12",
                    "legal_id": "row-12",
                    "document_number": "2026-00000",
                    "publication_date": "2026-03-16",
                    "document_type": "rule",
                    "body": "positional identity must fail",
                    "disposition": "admitted",
                }
            ]
        )


def test_empty_corpus_fails_closed() -> None:
    with pytest.raises(GraphProjectionError):
        project_federal_register_graph([])


def test_duplicate_typed_edges_collapse_to_one(compact_graph) -> None:
    keys = [edge.uniqueness_key() for edge in compact_graph.edges]
    assert len(keys) == len(set(keys))


def test_roots_reconcile(compact_graph) -> None:
    rows = fixture_graph_rows()
    root = build_corpus_root_cid(rows)
    proof = reconcile_roots(compact_graph, expected_corpus_root_cid=root)
    assert proof["reconciled"] is True
    assert proof["document_count"] == compact_graph.document_count


# ---------------------------------------------------------------------------
# LCR-055 admitted corpus coverage
# ---------------------------------------------------------------------------


def test_admitted_corpus_documents_project_with_acceptance_gates(corpus) -> None:
    projection = project_federal_register_graph_from_corpus(
        corpus, config=fixture_graph_config()
    )
    rows = rows_from_materialized_corpus(corpus)
    assert len(rows) == len(corpus.corpus_records)
    assert projection.document_count == len(corpus.corpus_records)
    assert {node.legal_id for node in projection.nodes_of_type(GraphNodeType.DOCUMENT)} == {
        record.legal_id for record in corpus.corpus_records
    }
    assert_endpoint_closure(projection)
    assert_edge_uniqueness(projection)
    assert_adjacency_inversion(projection)
    assert_family_bounds(projection)
    assert_provenance_paths(projection)
    assert_unresolved_reference_accounting(projection)
    agencies = {
        node.label
        for node in projection.nodes
        if node.node_type is GraphNodeType.AGENCY
    }
    assert "Environmental Protection Agency" in agencies
    recovery_ids = {record.recovery_id for record in corpus.recovery_records}
    graph_ids = {node.entry_cid for node in projection.nodes if node.entry_cid}
    assert recovery_ids.isdisjoint(graph_ids)
    assert projection.document_count == corpus.family_counts.corpus
    proof = reconcile_roots(
        projection, expected_corpus_root_cid=build_corpus_root_cid(corpus)
    )
    assert proof["reconciled"] is True


def test_graph_corpus_row_from_mapping_round_trip() -> None:
    row = GraphCorpusRow.from_mapping(fixture_graph_rows()[0])
    assert row.document_number == "2026-04567"
    assert row.docket_ids == ("EPA-HQ-OAR-2026-0001",)
    assert row.regulation_id_numbers == ("2060-AV00",)
    assert row.agencies == ("Environmental Protection Agency",)
    assert row.effective_date == "2026-04-15"


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_graph_report_is_secret_free_and_fixture_bound(corpus, tmp_path: Path) -> None:
    report = build_federal_graph_report(corpus=corpus)
    assert report["task_id"] == TASK_ID
    assert report["schema_version"] == SCHEMA_VERSION
    assert report["goal_id"] == GOAL_ID
    assert report["acceptance"]["endpoint_closure"] is True
    assert report["acceptance"]["edge_uniqueness"] is True
    assert report["acceptance"]["adjacency_inversion"] is True
    assert report["acceptance"]["family_bounds"] is True
    assert report["acceptance"]["provenance_paths"] is True
    assert report["acceptance"]["unresolved_reference_accounting"] is True
    assert report["acceptance"]["secrets_absent"] is True
    assert report["acceptance"]["hub_upload"] is False
    assert report["authorizing_hub_upload"] is False
    assert report["authorizing_for_publication"] is False
    assert report["mode"] == MODE_FIXTURE
    assert report["network_required"] is False
    assert report["admitted"]["document_count"] == len(corpus.corpus_records)
    assert report["family_counts"]["graph"] == len(corpus.corpus_records)
    assert report["depends_on"] == ["LCR-055", "LCR-056"]
    assert report["checks"]["bm25_task_id"] == "LCR-056"
    assert report["checks"]["bm25_is_not_legal_authority"] is True
    assert report["checks"]["full_adjacency_paging_owned_by"] == "LCR-076"
    assert report["ontology"]["version"] == ONTOLOGY_VERSION
    assert find_secret_surfaces(report) == []
    blob = json.dumps(report, sort_keys=True)
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert "hf_" not in blob
    assert "Bearer " not in blob
    assert "sk-" not in blob
    assert_federal_graph_report(report)
    path = tmp_path / "federal_graph.json"
    written = write_federal_graph_report(path, corpus=corpus)
    assert written == path
    loaded = load_federal_graph_report(path)
    assert loaded["task_id"] == TASK_ID
    assert "/home/" not in path.read_text(encoding="utf-8")


def test_on_disk_graph_report_matches_contract(corpus) -> None:
    path = default_graph_report_path()
    write_federal_graph_report(path, corpus=corpus)
    assert path.is_file()
    assert path.name == "federal_graph.json"
    assert "legal_corpora_reindex" in path.parts
    loaded = load_federal_graph_report(path)
    assert loaded["task_id"] == TASK_ID
    assert loaded["acceptance"]["hub_upload"] is False
    assert_federal_graph_report(loaded)
    blob = path.read_text(encoding="utf-8")
    assert "/home/" not in blob
    assert "/Users/" not in blob
    assert loaded["checks"]["endpoint_closure"] is True
    assert loaded["bounds"]["maximum_rows_per_physical_shard"] == 4096
    assert loaded["bounds"]["maximum_adjacency_pointers_per_row"] == 4096
    assert loaded["demo"]["document_count"] == 8
    assert loaded["demo"]["unresolved"]["unresolved_citations"] >= 1
    assert loaded["adjacency"]["inversion_holds"] is True

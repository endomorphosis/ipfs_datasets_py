"""Unit tests for the multi-jurisdiction legal and provenance graph (LCR-030).

Acceptance: Deterministic nodes and edges cover jurisdiction, code, title,
chapter, section, subsection, source, edition, act, citation, amendment, and
provenance with unresolved citations preserved, exact-51 coverage, and no
embedding or lexical similarity misrepresented as legal authority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.processors.legal_data.state_laws_graph import (
    AUTHORIZES_HUB_UPLOAD,
    AUTHORIZES_PUBLICATION,
    AUTHORIZES_RELEASE,
    CITATION_PARSER_VERSION,
    EXPECTED_JURISDICTION_COUNT,
    FIXTURE_SCHEMA_VERSION,
    GOAL_ID,
    GRAPH_ONTOLOGY,
    LEGAL_EDGE_TYPES,
    NON_AUTHORITATIVE_AUTHORITY,
    ONTOLOGY_VERSION,
    PRODUCER,
    PROGRAM_ID,
    RECEIPT_SCHEMA_VERSION,
    REPORT_SCHEMA,
    REQUIRED_COVERAGE_NODE_TYPES,
    SCHEMA_VERSION,
    SIMILARITY_EDGE_TYPES,
    SPAN_REQUIRED_EDGE_TYPES,
    TASK_ID,
    CitationResolutionError,
    GraphCorpusRow,
    GraphEdgeClass,
    GraphEdgeType,
    GraphOntology,
    GraphOntologyError,
    GraphProjectionError,
    GraphReceiptError,
    GraphReleaseAuthorizationError,
    LegalSimilarityCollisionError,
    StateLawsGraphEdge,
    StateLawsGraphNode,
    StateLawsGraphProjector,
    ResolutionStatus,
    SimilarityNeighbor,
    SourceSpan,
    SourceSpanError,
    GraphNodeType,
    assert_legal_graph_receipt,
    assert_legal_similarity_disjoint,
    bind_fixture_graph,
    build_default_graph_expected_fixture_payload,
    build_graph_evaluation_report,
    build_legal_graph_receipt,
    check_evaluation_report,
    default_graph_evaluation_report_path,
    default_legal_graph_receipt_path,
    extract_citation_mentions,
    find_graph_paths,
    fixture_seed_records,
    load_legal_graph_receipt,
    lookup_citation_locator,
    match_expected_paths,
    production_graph_bounds,
    project_state_laws_graph,
    resolve_citations,
    run_fixture_case,
    strip_subsection_qualifier,
    write_legal_graph_receipt,
)
from ipfs_datasets_py.processors.legal_data.state_laws_identity import LEGAL_ID_PREFIX
from ipfs_datasets_py.processors.legal_data.state_laws_release_schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    AdmissionStatus,
)


@pytest.fixture(scope="module")
def fixture_payload() -> dict:
    return build_default_graph_expected_fixture_payload()


@pytest.fixture(scope="module")
def fixture_projection(fixture_payload: dict):
    return project_state_laws_graph(
        fixture_payload["records"],
        similarity_neighbors=fixture_payload.get("similarity_neighbors") or [],
    )


def _section_record(payload: dict, section: str) -> dict:
    for record in payload["records"]:
        if record.get("hierarchy", {}).get("section") == section:
            return record
    raise AssertionError(f"missing fixture record for section {section!r}")


# ---------------------------------------------------------------------------
# Identity / ontology
# ---------------------------------------------------------------------------


def test_schema_and_task_identity_are_stable() -> None:
    assert SCHEMA_VERSION == "state-laws-graph-v1"
    assert ONTOLOGY_VERSION == "state-laws-graph-ontology/v1"
    assert FIXTURE_SCHEMA_VERSION == "state-laws-graph-expected-v1"
    assert RECEIPT_SCHEMA_VERSION == "state-laws-legal-graph-receipt-v1"
    assert TASK_ID == "LCR-030"
    assert GOAL_ID == "LCR-G040"
    assert PROGRAM_ID == "legal-corpora-reindex-v1"
    assert PRODUCER == "state_laws_graph.py"
    assert RELEASE_PROFILE == "state-laws-ir-graphrag/v2"
    assert AUTHORIZES_PUBLICATION is False
    assert AUTHORIZES_RELEASE is False
    assert AUTHORIZES_HUB_UPLOAD is False
    assert GraphOntology().version == ONTOLOGY_VERSION
    assert REPORT_SCHEMA == "ipfs_datasets_py/legal-corpora-reindex-graph@1"
    assert tuple(REQUIRED_COVERAGE_NODE_TYPES) == (
        "jurisdiction",
        "code",
        "title",
        "chapter",
        "section",
        "subsection",
        "source",
        "edition",
        "act",
        "citation",
        "amendment",
        "provenance",
    )


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
            GraphNodeType.SECTION,
            GraphNodeType.SECTION,
            edge_class=GraphEdgeClass.SIMILARITY,
        )


def test_ontology_rejects_wrong_direction() -> None:
    with pytest.raises(GraphOntologyError):
        GRAPH_ONTOLOGY.validate_edge(
            GraphEdgeType.CONTAINS,
            GraphNodeType.SECTION,
            GraphNodeType.JURISDICTION,
        )


def test_similarity_neighbor_cannot_use_legal_edge_type() -> None:
    with pytest.raises(LegalSimilarityCollisionError):
        SimilarityNeighbor(
            source_legal_id="state:OR:ors:192:192.311;edition=2024-official",
            target_legal_id="state:WA:rcw:42:56:42.56.030;edition=2024-official",
            score=1.0,
            edge_type=GraphEdgeType.CITES,
        )


def test_production_bounds_match_release_policy() -> None:
    bounds = production_graph_bounds()
    assert bounds["maximum_rows_per_physical_shard"] == MAX_ROWS_PER_PHYSICAL_SHARD
    assert bounds["maximum_adjacency_pointers_per_row"] == MAX_ADJACENCY_POINTERS_PER_ROW
    assert bounds["similarity_cannot_establish_legal_authority"] is True
    assert bounds["exact_51_jurisdiction_count"] == EXPECTED_JURISDICTION_COUNT
    assert default_legal_graph_receipt_path().name == "graph_evaluation.json"
    assert default_graph_evaluation_report_path().name == "graph_evaluation.json"


# ---------------------------------------------------------------------------
# Coverage of required node types
# ---------------------------------------------------------------------------


def test_projection_covers_required_node_and_edge_types(fixture_projection) -> None:
    node_types = {item.node_type.value for item in fixture_projection.nodes}
    for required in REQUIRED_COVERAGE_NODE_TYPES:
        assert required in node_types, required
    assert GraphNodeType.UNRESOLVED_CITATION.value in node_types
    assert GraphNodeType.ACT.value in node_types

    edge_types = {item.edge_type for item in fixture_projection.edges}
    assert GraphEdgeType.CONTAINS in edge_types
    assert GraphEdgeType.CITES in edge_types
    assert GraphEdgeType.CITES_UNRESOLVED in edge_types
    assert GraphEdgeType.HAS_CITATION in edge_types
    assert GraphEdgeType.AMENDS in edge_types
    assert GraphEdgeType.HAS_AMENDMENT in edge_types
    assert GraphEdgeType.HAS_SOURCE in edge_types
    assert GraphEdgeType.HAS_EDITION in edge_types
    assert GraphEdgeType.VERSION_OF in edge_types
    assert GraphEdgeType.HAS_PROVENANCE in edge_types
    assert GraphEdgeType.CODIFIES in edge_types
    assert GraphEdgeType.DERIVED_FROM in edge_types
    assert GraphEdgeType.REPEALS in edge_types
    assert GraphEdgeType.TRANSFERS in edge_types
    assert GraphEdgeType.BM25_NEIGHBOR_OF in edge_types
    assert GraphEdgeType.EMBEDDING_NEIGHBOR_OF in edge_types


def test_projection_is_multi_jurisdiction(fixture_projection) -> None:
    jurisdictions = {
        item.payload.get("jurisdiction_code")
        for item in fixture_projection.nodes
        if item.node_type is GraphNodeType.JURISDICTION
    }
    assert {"OR", "CA", "NY", "WA", "DC"} <= jurisdictions
    assert len(jurisdictions) == EXPECTED_JURISDICTION_COUNT
    assert fixture_projection.exact_51_coverage_ok()
    codes = {
        item.node_key
        for item in fixture_projection.nodes
        if item.node_type is GraphNodeType.CODE
    }
    assert "code:OR:ors" in codes
    assert "code:CA:penal-code" in codes
    assert "code:NY:penal-law" in codes
    assert "code:WA:rcw" in codes
    assert "code:DC:code" in codes


def test_hierarchy_contains_jurisdiction_code_title_chapter_section_subsection(
    fixture_projection,
) -> None:
    keys = {item.node_key for item in fixture_projection.nodes}
    assert "jurisdiction:WA" in keys
    assert "code:WA:rcw" in keys
    assert "title:WA:rcw:42" in keys
    assert any(item.startswith("chapter:WA:rcw:42:56") for item in keys)
    assert any(item.startswith("section:state:WA:rcw:") for item in keys)
    assert any(item.startswith("subsection:state:NY:penal-law:") for item in keys)

    paths = find_graph_paths(
        fixture_projection,
        legal_only=True,
        source_keys=["jurisdiction:WA"],
        max_depth=4,
    )
    chapter_hits = [
        path
        for path in paths
        if path.edge_types == ("CONTAINS", "CONTAINS", "CONTAINS")
        and path.node_keys[1] == "code:WA:rcw"
        and path.node_keys[2] == "title:WA:rcw:42"
        and path.node_keys[3].startswith("chapter:WA:rcw:42:56")
    ]
    assert chapter_hits


# ---------------------------------------------------------------------------
# Unresolved citations preserved honestly
# ---------------------------------------------------------------------------


def test_unresolved_citations_preserve_source_text_and_parser_version(
    fixture_projection,
) -> None:
    unresolved_nodes = [
        item
        for item in fixture_projection.nodes
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
        for item in fixture_projection.edges
        if item.edge_type is GraphEdgeType.CITES_UNRESOLVED
    ]
    assert unresolved_edges
    for edge in unresolved_edges:
        assert edge.resolution_status in {
            ResolutionStatus.UNRESOLVED,
            ResolutionStatus.AMBIGUOUS,
        }
        assert edge.source_span is not None
        assert edge.source_span.text
        assert edge.payload.get("parser_version") == CITATION_PARSER_VERSION
    unresolved_texts = " ".join(
        item.source_span.text for item in unresolved_edges if item.source_span is not None
    )
    assert "99.9999" in unresolved_texts


def test_resolve_citations_does_not_invent_targets() -> None:
    text = "See ORS 99.9999 for a fictional provision."
    resolved = resolve_citations(
        text,
        known_legal_ids=["state:OR:ors:192:192.311;edition=2024-official"],
        locator_index={
            ("OR", "ors", "192.311"): [
                "state:OR:ors:192:192.311;edition=2024-official"
            ]
        },
        default_jurisdiction="OR",
        default_code_family="ors",
    )
    assert resolved
    item = next(entry for entry in resolved if "99.9999" in entry.mention.mention_text)
    assert item.resolution_status is ResolutionStatus.UNRESOLVED
    assert item.target_legal_id is None
    assert item.span.text
    assert item.mention.parser_version == CITATION_PARSER_VERSION


def test_resolved_cross_jurisdiction_citation(fixture_payload: dict, fixture_projection) -> None:
    oregon = _section_record(fixture_payload, "192.311")
    california = _section_record(fixture_payload, "187")
    oregon_key = f"section:{oregon['legal_id']}"
    california_key = f"section:{california['legal_id']}"
    cites = [
        item
        for item in fixture_projection.edges
        if item.edge_type is GraphEdgeType.CITES
        and fixture_projection.node_by_cid()[item.source_node_cid].node_key == oregon_key
        and fixture_projection.node_by_cid()[item.target_node_cid].node_key
        == california_key
    ]
    assert cites
    assert cites[0].source_span is not None
    assert "Penal Code" in cites[0].source_span.text


# ---------------------------------------------------------------------------
# Similarity is not legal authority
# ---------------------------------------------------------------------------


def test_projection_keeps_similarity_out_of_legal_paths(fixture_projection) -> None:
    fixture_projection.assert_semantics_disjoint()
    assert fixture_projection.similarity_edge_count == 2
    legal_paths = find_graph_paths(fixture_projection, legal_only=True)
    for path in legal_paths:
        for edge_type in path.edge_types:
            assert edge_type not in {item.value for item in SIMILARITY_EDGE_TYPES}
    sim_edges = fixture_projection.similarity_edges()
    assert {item.edge_type for item in sim_edges} == {
        GraphEdgeType.BM25_NEIGHBOR_OF,
        GraphEdgeType.EMBEDDING_NEIGHBOR_OF,
    }
    for edge in sim_edges:
        assert edge.edge_class is GraphEdgeClass.SIMILARITY
        assert edge.payload.get("authority") == NON_AUTHORITATIVE_AUTHORITY


def test_similarity_edge_cannot_claim_legal_authority(fixture_projection) -> None:
    oregon = next(
        item
        for item in fixture_projection.nodes
        if item.node_type is GraphNodeType.SECTION and item.payload.get("section") == "192.311"
    )
    washington = next(
        item
        for item in fixture_projection.nodes
        if item.node_type is GraphNodeType.SECTION and item.payload.get("section") == "42.56.030"
    )
    with pytest.raises(LegalSimilarityCollisionError):
        StateLawsGraphEdge(
            edge_type=GraphEdgeType.EMBEDDING_NEIGHBOR_OF,
            source_node_cid=oregon.node_cid,
            target_node_cid=washington.node_cid,
            edge_class=GraphEdgeClass.SIMILARITY,
            payload={"authority": "legal"},
        )


# ---------------------------------------------------------------------------
# Source spans bound
# ---------------------------------------------------------------------------


def test_source_span_binds_to_source_text() -> None:
    text = "See ORS 192.314 today."
    span = SourceSpan.from_occurrence(text, "ORS 192.314")
    assert span.start >= 0
    assert text[span.start : span.end] == span.text
    span.bind_to_source(text)


def test_source_span_rejects_mismatch() -> None:
    with pytest.raises(SourceSpanError):
        SourceSpan(start=0, end=3, text="nope").bind_to_source("abc")


def test_span_required_edges_have_bound_spans(fixture_projection) -> None:
    for edge in fixture_projection.edges:
        if edge.edge_type in SPAN_REQUIRED_EDGE_TYPES:
            assert edge.source_span is not None
            assert edge.source_span.end >= edge.source_span.start
            assert len(edge.source_span.text) == edge.source_span.end - edge.source_span.start


def test_cites_edge_without_span_rejected(fixture_projection) -> None:
    sections = [
        item
        for item in fixture_projection.nodes
        if item.node_type is GraphNodeType.SECTION
    ]
    with pytest.raises(SourceSpanError):
        StateLawsGraphEdge(
            edge_type=GraphEdgeType.CITES,
            source_node_cid=sections[0].node_cid,
            target_node_cid=sections[1].node_cid,
            edge_class=GraphEdgeClass.CITATION,
            source_span=None,
        )


# ---------------------------------------------------------------------------
# Determinism, exclusions, and projector helpers
# ---------------------------------------------------------------------------


def test_projection_is_deterministic(fixture_payload: dict) -> None:
    first = project_state_laws_graph(
        fixture_payload["records"],
        similarity_neighbors=fixture_payload.get("similarity_neighbors") or [],
    )
    second = project_state_laws_graph(
        fixture_payload["records"],
        similarity_neighbors=fixture_payload.get("similarity_neighbors") or [],
    )
    assert first.graph_cid == second.graph_cid
    assert [item.node_cid for item in first.nodes] == [item.node_cid for item in second.nodes]
    assert [item.edge_cid for item in first.edges] == [item.edge_cid for item in second.edges]
    node_order = [(item.node_type.value, item.node_key, item.node_cid) for item in first.nodes]
    assert node_order == sorted(node_order)
    edge_order = [
        (item.edge_type.value, item.source_node_cid, item.target_node_cid, item.edge_cid)
        for item in first.edges
    ]
    assert edge_order == sorted(edge_order)


def test_empty_corpus_fails_closed() -> None:
    with pytest.raises(GraphProjectionError):
        project_state_laws_graph([])


def test_recovery_rows_are_excluded_from_graph_counts(fixture_projection) -> None:
    assert fixture_projection.skipped_row_count == 1
    recovery_nodes = [
        item
        for item in fixture_projection.nodes
        if item.payload.get("section") == "recovery-1"
        or (item.legal_id or "").endswith("recovery-1")
    ]
    assert not recovery_nodes


def test_quarantine_only_corpus_fails_closed() -> None:
    row = {
        "code_family": "statutes",
        "configuration": AdmissionStatus.QUARANTINED.value,
        "document_kind": "statute",
        "edition": "2024-official",
        "entry_cid": "sha256:" + "a" * 64,
        "hierarchy": {"section": "1"},
        "jurisdiction_code": "OR",
        "source_cid": "sha256:" + "b" * 64,
        "text": "quarantined text that must not enter the graph family counts.",
    }
    with pytest.raises(GraphProjectionError):
        project_state_laws_graph([row])


def test_projector_class_matches_module_helper(fixture_payload: dict) -> None:
    via_class = StateLawsGraphProjector().project(fixture_payload["records"])
    via_helper = project_state_laws_graph(fixture_payload["records"])
    assert via_class.legal_edge_count == via_helper.legal_edge_count
    assert len(via_class.nodes) == len(via_helper.nodes)
    assert via_class.graph_cid == via_helper.graph_cid


def test_corpus_row_from_mapping_builds_legal_id() -> None:
    row = GraphCorpusRow.from_mapping(
        {
            "code_family": "ors",
            "edition": "2024-official",
            "entry_cid": "sha256:" + "a" * 64,
            "hierarchy": {"title": "192", "section": "192.311"},
            "jurisdiction_code": "OR",
            "source_cid": "sha256:" + "b" * 64,
            "text": "sample",
        }
    )
    assert row.legal_id.startswith(f"{LEGAL_ID_PREFIX}:OR:ors:")
    assert row.section == "192.311"
    assert row.jurisdiction_code == "OR"


def test_strip_subsection_qualifier_returns_parent_section() -> None:
    records = fixture_seed_records()
    ny = next(item for item in records if item["jurisdiction_code"] == "NY")
    parent = strip_subsection_qualifier(ny["legal_id"])
    assert parent != ny["legal_id"]
    assert "subsection=" not in parent
    assert parent in ny["legal_id"] or ny["legal_id"].startswith(parent.split(";")[0])


# ---------------------------------------------------------------------------
# Citation parser
# ---------------------------------------------------------------------------


def test_extract_public_law_and_state_and_usc_mentions() -> None:
    text = (
        "See ORS 192.314, Cal. Penal Code § 187, 5 U.S.C. § 552, "
        "and Pub. L. 112-29. Also RCW 42.56.070 and D.C. Code § 2-532."
    )
    mentions = extract_citation_mentions(text, default_jurisdiction="OR", default_code_family="ors")
    kinds = {item.kind for item in mentions}
    assert "state_code" in kinds or "bluebook" in kinds
    assert "usc" in kinds
    assert "public_law" in kinds
    locators = {
        (item.jurisdiction_code, item.code_family, item.section)
        for item in mentions
        if item.section
    }
    assert ("OR", "ors", "192.314") in locators
    assert ("CA", "penal-code", "187") in locators
    assert ("WA", "rcw", "42.56.070") in locators
    assert ("DC", "code", "2-532") in locators
    assert ("US", "usc", "552") in locators


def test_lookup_citation_locator_aliases() -> None:
    assert lookup_citation_locator("ORS") == ("OR", "ors")
    assert lookup_citation_locator("Penal Code", prefix="Cal.") == ("CA", "penal-code")
    assert lookup_citation_locator("Penal Law", prefix="N.Y.") == ("NY", "penal-law")
    assert lookup_citation_locator("Rev. Code", prefix="Wash.") == ("WA", "rcw")
    assert lookup_citation_locator("D.C. Code") == ("DC", "code")


def test_unresolved_citation_node_rejects_invented_legal_id() -> None:
    with pytest.raises(CitationResolutionError):
        StateLawsGraphNode(
            node_type=GraphNodeType.UNRESOLVED_CITATION,
            node_key="unresolved:demo",
            label="ORS 99.9999",
            legal_id="state:OR:ors:99:99.9999;edition=2024-official",
        )


# ---------------------------------------------------------------------------
# Fixture paths and sealed case
# ---------------------------------------------------------------------------


def test_sealed_fixture_case_passes(fixture_payload: dict) -> None:
    outcome = run_fixture_case(fixture_payload)
    assert outcome["ok"], outcome
    assert outcome["unresolved_ok"]
    assert outcome["coverage_ok"]
    assert not outcome["span_errors"]
    assert not outcome["similarity_leaked_into_legal_paths"]
    assert all(item["matched"] for item in outcome["path_matches"])


def test_fixture_graph_paths_match_sealed_expectations(
    fixture_payload: dict, fixture_projection
) -> None:
    matches = match_expected_paths(fixture_projection, fixture_payload["expected_paths"])
    assert matches
    failed = [item for item in matches if not item["matched"]]
    assert not failed, failed
    ids = [item["path_id"] for item in fixture_payload["expected_paths"]]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 8


def test_default_payload_is_compact_recipe(fixture_payload: dict) -> None:
    assert fixture_payload["schema_version"] == FIXTURE_SCHEMA_VERSION
    assert fixture_payload["task_id"] == TASK_ID
    assert fixture_payload["ontology_version"] == ONTOLOGY_VERSION
    assert fixture_payload["acceptance"]["legal_and_similarity_semantics_disjoint"]
    assert fixture_payload["acceptance"]["unresolved_citations_preserved_honestly"]
    assert fixture_payload["acceptance"]["required_coverage_node_types_present"]
    assert "nodes" not in fixture_payload
    assert "edges" not in fixture_payload
    assert isinstance(fixture_payload["records"], list)
    assert isinstance(fixture_payload["expected_paths"], list)


def test_bind_fixture_graph_matches_helper(fixture_projection) -> None:
    bound = bind_fixture_graph()
    assert bound.graph_cid == fixture_projection.graph_cid


# ---------------------------------------------------------------------------
# Provenance / amendment / edition / source
# ---------------------------------------------------------------------------


def test_source_edition_and_provenance_edges_are_present(fixture_projection) -> None:
    by_type = {item.node_type: [] for item in fixture_projection.nodes}
    for node in fixture_projection.nodes:
        by_type.setdefault(node.node_type, []).append(node)
    assert by_type[GraphNodeType.SOURCE]
    assert by_type[GraphNodeType.EDITION]
    assert by_type[GraphNodeType.PROVENANCE]
    edition_keys = {item.node_key for item in by_type[GraphNodeType.EDITION]}
    assert "edition:2024-official" in edition_keys
    has_source = [
        item for item in fixture_projection.edges if item.edge_type is GraphEdgeType.HAS_SOURCE
    ]
    has_edition = [
        item for item in fixture_projection.edges if item.edge_type is GraphEdgeType.HAS_EDITION
    ]
    has_provenance = [
        item
        for item in fixture_projection.edges
        if item.edge_type is GraphEdgeType.HAS_PROVENANCE
    ]
    assert has_source
    assert has_edition
    assert has_provenance


def test_amendment_node_is_not_a_similarity_edge(fixture_projection) -> None:
    amendments = [
        item for item in fixture_projection.nodes if item.node_type is GraphNodeType.AMENDMENT
    ]
    assert amendments
    amends = [
        item for item in fixture_projection.edges if item.edge_type is GraphEdgeType.AMENDS
    ]
    assert amends
    for edge in amends:
        assert edge.is_legal
        assert not edge.is_similarity
        assert edge.edge_class is GraphEdgeClass.AUTHORITY


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def test_receipt_is_software_contract_only_and_matches_disk(
    tmp_path: Path, fixture_projection
) -> None:
    built = build_legal_graph_receipt(fixture_projection)
    assert_legal_graph_receipt(built)
    assert built["task_id"] == TASK_ID
    assert built["schema_version"] == RECEIPT_SCHEMA_VERSION
    assert built["authorizing_for_release"] is False
    assert built["authorizing_for_publication"] is False
    assert built["proves_software_contract_only"] is True
    assert built["acceptance"]["deterministic_nodes_and_edges_cover_required_types"]
    assert built["acceptance"]["unresolved_citations_preserved"]
    assert built["acceptance"]["embedding_or_lexical_similarity_not_legal_authority"]
    assert built["acceptance"]["uniqueness"] is True
    assert built["acceptance"]["referential_integrity"] is True
    assert built["acceptance"]["51_jurisdiction_coverage"] is True
    assert built["acceptance"]["unresolved_citation_accounting"] is True
    assert built["acceptance"]["similarity_not_authority"] is True
    assert built["acceptance"]["secrets_absent"] is True
    assert built["acceptance"]["hub_upload"] is False
    assert built["acceptance"]["authorizing_for_publication"] is False
    assert built["checks"]["similarity_edges_non_authoritative"]
    assert built["checks"]["unresolved_citations_have_no_invented_legal_id"]
    assert built["demo"]["graph_cid"] == fixture_projection.graph_cid
    assert built["demo"]["jurisdiction_codes"] == list(fixture_projection.jurisdiction_codes())
    assert check_evaluation_report(built)["ok"] is True
    assert built["family_counts"]["graph_nodes"] == len(fixture_projection.nodes)
    assert built["family_counts"]["graph_edges"] == len(fixture_projection.edges)

    written = tmp_path / "graph_evaluation.json"
    write_legal_graph_receipt(written)
    loaded = load_legal_graph_receipt(written)
    assert_legal_graph_receipt(loaded)
    assert loaded["receipt_sha256"] == built["receipt_sha256"]

    on_disk_path = default_legal_graph_receipt_path()
    assert on_disk_path.is_file()
    on_disk = load_legal_graph_receipt(on_disk_path)
    assert_legal_graph_receipt(on_disk)
    assert on_disk == built


def test_receipt_rejects_release_authorization() -> None:
    payload = build_legal_graph_receipt()
    payload["authorizing_for_release"] = True
    with pytest.raises(GraphReleaseAuthorizationError):
        assert_legal_graph_receipt(payload)


def test_receipt_rejects_digest_tamper() -> None:
    payload = build_legal_graph_receipt()
    payload["demo"]["node_count"] = 0
    with pytest.raises(GraphReceiptError):
        assert_legal_graph_receipt(payload)


def test_missing_receipt_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(GraphReceiptError):
        load_legal_graph_receipt(tmp_path / "missing.json")


def test_uniqueness_and_referential_integrity(fixture_projection) -> None:
    assert fixture_projection.uniqueness_ok()
    assert fixture_projection.referential_integrity_ok()
    node_cids = [item.node_cid for item in fixture_projection.nodes]
    node_keys = [item.node_key for item in fixture_projection.nodes]
    edge_cids = [item.edge_cid for item in fixture_projection.edges]
    assert len(node_cids) == len(set(node_cids))
    assert len(node_keys) == len(set(node_keys))
    assert len(edge_cids) == len(set(edge_cids))
    known = set(node_cids)
    for edge in fixture_projection.edges:
        assert edge.source_node_cid in known
        assert edge.target_node_cid in known


def test_recovery_rows_do_not_increment_family_counts(fixture_projection) -> None:
    report = build_graph_evaluation_report(fixture_projection)
    assert fixture_projection.skipped_row_count == 1
    assert report["family_counts"]["graph_nodes"] == len(fixture_projection.nodes)
    assert report["family_counts"]["graph_edges"] == len(fixture_projection.edges)
    assert report["checks"]["recovery_and_quarantine_excluded_from_graph_counts"] is True
    recovery_ids = [
        item.legal_id
        for item in fixture_projection.nodes
        if item.legal_id and "recovery-1" in item.legal_id
    ]
    assert not recovery_ids


def test_receipt_rejects_hub_upload() -> None:
    payload = build_legal_graph_receipt()
    payload["authorizing_hub_upload"] = True
    with pytest.raises(GraphReleaseAuthorizationError):
        assert_legal_graph_receipt(payload)


def test_version_of_edges_are_legal_not_similarity(fixture_projection) -> None:
    version_edges = [
        item for item in fixture_projection.edges if item.edge_type is GraphEdgeType.VERSION_OF
    ]
    assert version_edges
    for edge in version_edges:
        assert edge.is_legal
        assert not edge.is_similarity
        assert edge.edge_class is GraphEdgeClass.PROVENANCE

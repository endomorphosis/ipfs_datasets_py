"""Ontology / prosecution knowledge-graph projection tests (PATLAW-091).

Validates that the patent graph adapter:

* projects every required entity kind with source CID/span linkage
* produces deterministic digests and ordered node/edge sets
* preserves disclosure on priority/continuation/amendment/rejection/
  examiner/applicant/legal-authority edges
* keeps LLM-proposed edges as unverified candidates (no source authority)
* loads into GraphEngine with every relationship endpoint present
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ipfs_datasets_py.knowledge_graphs.adapters.patent import (
    CASE_SCHEMA_VERSION,
    DISCLOSURE_SENSITIVE_RELATIONS,
    NODE_KINDS,
    PROJECTION_SCHEMA_VERSION,
    CandidateAuthorityError,
    DisclosureUpgradeError,
    MissingEndpointError,
    MissingSourceLinkError,
    PatentGraphAdapterError,
    PatentGraphProjector,
    assert_projection_invariants,
    canonical_json,
    load_golden_prosecution_case,
    ontology_node_kinds,
    ontology_relations,
    project_golden_prosecution_case,
    project_patent_graph,
)
from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    AuthorityClaim,
    DisclosureClass,
    EdgeProvenance,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "patent"
    / "graph"
    / "golden_prosecution_case.json"
)

CID_A = "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi"
CID_B = "bafybeic3g5s5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x5x"


def _link(
    *,
    source_cid: str = CID_A,
    artifact_id: str = "artifact:1",
    start: int = 0,
    end: int = 10,
) -> dict:
    return {
        "source_cid": source_cid,
        "artifact_id": artifact_id,
        "span": {"start": start, "end": end, "unit": "char"},
    }


def _minimal_case(**overrides: object) -> dict:
    case = {
        "schema_version": CASE_SCHEMA_VERSION,
        "case_id": "case-minimal",
        "tenant_id": "tenant-public",
        "entities": [
            {
                "id": "app-1",
                "kind": "application",
                "label": "16/1",
                "disclosure": "public_official",
                "source_links": [_link()],
            },
            {
                "id": "parent-1",
                "kind": "application",
                "label": "15/1",
                "disclosure": "public_official",
                "source_links": [_link(artifact_id="artifact:parent", start=10, end=20)],
            },
        ],
        "edges": [
            {
                "subject": "app-1",
                "object": "parent-1",
                "relation": "priority",
                "source_links": [_link(start=30, end=40)],
            }
        ],
        "candidate_edges": [],
    }
    case.update(overrides)
    return case


def test_ontology_exports_required_node_kinds() -> None:
    kinds = ontology_node_kinds()
    assert kinds is NODE_KINDS
    required = {
        "authority",
        "edition",
        "section",
        "amendment",
        "effective_interval",
        "family",
        "application",
        "publication",
        "patent",
        "claim",
        "office_action",
        "rejection",
        "response",
        "citation",
        "classification",
        "examiner",
        "applicant",
        "legal_authority",
    }
    assert required <= kinds


def test_ontology_exports_disclosure_sensitive_relations() -> None:
    relations = ontology_relations()
    for name in (
        "priority",
        "continuation",
        "amends",
        "rejects",
        "examiner",
        "applicant",
        "legal_authority",
    ):
        assert name in relations
        assert name in DISCLOSURE_SENSITIVE_RELATIONS


def test_golden_fixture_exists_and_projects() -> None:
    assert GOLDEN_PATH.is_file(), f"missing golden fixture: {GOLDEN_PATH}"
    payload = load_golden_prosecution_case(GOLDEN_PATH)
    assert "case" in payload
    projection = project_golden_prosecution_case(GOLDEN_PATH)
    assert projection.schema_version == PROJECTION_SCHEMA_VERSION
    assert projection.case_id == "golden-prosecution-us16123456"
    assert_projection_invariants(projection)


def test_golden_projection_covers_required_entity_kinds() -> None:
    projection = project_golden_prosecution_case(GOLDEN_PATH)
    kinds_present = {node.kind for node in projection.nodes}
    # Full ontology appears in the golden case.
    assert NODE_KINDS <= kinds_present


def test_every_node_and_source_edge_joins_source_cid_and_span() -> None:
    projection = project_golden_prosecution_case(GOLDEN_PATH)
    for node in projection.nodes:
        assert node.source_links, node.node_id
        for link in node.source_links:
            assert link.source_cid
            assert link.artifact_id
            # Span is required in the golden case for exact joinability.
            assert link.span is not None
            assert link.span.end >= link.span.start
    for edge in projection.source_derived_edges():
        assert edge.source_links, edge.edge_id
        for link in edge.source_links:
            assert link.source_cid
            assert link.span is not None


def test_projection_is_deterministic() -> None:
    first = project_golden_prosecution_case(GOLDEN_PATH)
    second = project_golden_prosecution_case(GOLDEN_PATH)
    assert first.projection_digest == second.projection_digest
    assert first.to_dict() == second.to_dict()
    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    # Input order independence: reverse entities and edges.
    payload = load_golden_prosecution_case(GOLDEN_PATH)
    case = dict(payload["case"])
    case["entities"] = list(reversed(list(case["entities"])))
    case["edges"] = list(reversed(list(case["edges"])))
    third = project_patent_graph(case)
    assert third.projection_digest == first.projection_digest
    assert [n.node_id for n in third.nodes] == [n.node_id for n in first.nodes]
    assert [e.edge_id for e in third.edges] == [e.edge_id for e in first.edges]


def test_llm_proposed_edges_remain_unverified_candidates() -> None:
    projection = project_golden_prosecution_case(GOLDEN_PATH)
    candidates = projection.candidate_edges()
    assert candidates, "golden case must include at least one LLM candidate edge"
    assert set(projection.candidate_edge_ids) == {e.edge_id for e in candidates}
    for edge in candidates:
        assert edge.provenance is EdgeProvenance.CANDIDATE
        assert edge.authority_claim is not AuthorityClaim.SOURCE_BOUND
        assert edge.authority_claim in (
            AuthorityClaim.REVIEW_ONLY,
            AuthorityClaim.NONE,
        )
        assert edge.metadata.get("verification_status") == "unverified"
        assert edge.metadata.get("candidate") == "true"


def test_candidate_channel_rejects_source_authority_claim() -> None:
    case = _minimal_case(
        candidate_edges=[
            {
                "subject": "app-1",
                "object": "parent-1",
                "relation": "cites",
                "provenance": "llm_proposed",
                "authority_claim": "source_bound",
            }
        ]
    )
    with pytest.raises((CandidateAuthorityError, PatentGraphAdapterError)):
        project_patent_graph(case)


def test_disclosure_preserved_on_sensitive_edges() -> None:
    case = _minimal_case(
        entities=[
            {
                "id": "app-private",
                "kind": "application",
                "label": "private app",
                "disclosure": "confidential_application",
                "source_links": [_link()],
            },
            {
                "id": "parent-public",
                "kind": "application",
                "label": "public parent",
                "disclosure": "public_official",
                "source_links": [_link(artifact_id="artifact:parent")],
            },
            {
                "id": "examiner-1",
                "kind": "examiner",
                "label": "Examiner",
                "disclosure": "public_official",
                "source_links": [_link(artifact_id="artifact:ex")],
            },
            {
                "id": "applicant-1",
                "kind": "applicant",
                "label": "Applicant",
                "disclosure": "confidential_application",
                "source_links": [_link(artifact_id="artifact:ap")],
            },
            {
                "id": "auth-1",
                "kind": "legal_authority",
                "label": "35 USC 103",
                "disclosure": "public_official",
                "source_links": [_link(artifact_id="artifact:auth")],
            },
            {
                "id": "rej-1",
                "kind": "rejection",
                "label": "103 rej",
                "disclosure": "public_official",
                "source_links": [_link(artifact_id="artifact:rej")],
            },
            {
                "id": "claim-1",
                "kind": "claim",
                "label": "Claim 1",
                "disclosure": "public_official",
                "source_links": [_link(artifact_id="artifact:cl")],
            },
            {
                "id": "amend-1",
                "kind": "amendment",
                "label": "Amendment",
                "disclosure": "public_official",
                "source_links": [_link(artifact_id="artifact:am")],
            },
        ],
        edges=[
            {
                "subject": "app-private",
                "object": "parent-public",
                "relation": "priority",
                "source_links": [_link(start=1, end=2)],
            },
            {
                "subject": "app-private",
                "object": "parent-public",
                "relation": "continuation",
                "source_links": [_link(start=2, end=3)],
            },
            {
                "subject": "amend-1",
                "object": "claim-1",
                "relation": "amends",
                "source_links": [_link(start=3, end=4)],
            },
            {
                "subject": "rej-1",
                "object": "claim-1",
                "relation": "rejects",
                "source_links": [_link(start=4, end=5)],
            },
            {
                "subject": "rej-1",
                "object": "examiner-1",
                "relation": "examiner",
                "source_links": [_link(start=5, end=6)],
            },
            {
                "subject": "app-private",
                "object": "applicant-1",
                "relation": "applicant",
                "source_links": [_link(start=6, end=7)],
            },
            {
                "subject": "rej-1",
                "object": "auth-1",
                "relation": "legal_authority",
                "source_links": [_link(start=7, end=8)],
            },
        ],
    )
    projection = project_patent_graph(case)
    by_relation = {
        e.metadata.get("relation"): e for e in projection.edges
    }
    # Priority/continuation touch confidential application → must not be public-only.
    assert by_relation["priority"].disclosure is DisclosureClass.CONFIDENTIAL_APPLICATION
    assert by_relation["continuation"].disclosure is DisclosureClass.CONFIDENTIAL_APPLICATION
    assert by_relation["applicant"].disclosure is DisclosureClass.CONFIDENTIAL_APPLICATION
    # Public endpoints stay public_official.
    assert by_relation["amends"].disclosure is DisclosureClass.PUBLIC_OFFICIAL
    assert by_relation["rejects"].disclosure is DisclosureClass.PUBLIC_OFFICIAL
    assert by_relation["examiner"].disclosure is DisclosureClass.PUBLIC_OFFICIAL
    assert by_relation["legal_authority"].disclosure is DisclosureClass.PUBLIC_OFFICIAL


def test_disclosure_upgrade_rejected_on_sensitive_edge() -> None:
    case = _minimal_case(
        entities=[
            {
                "id": "app-private",
                "kind": "application",
                "label": "private",
                "disclosure": "confidential_application",
                "source_links": [_link()],
            },
            {
                "id": "parent-private",
                "kind": "application",
                "label": "parent private",
                "disclosure": "confidential_application",
                "source_links": [_link(artifact_id="artifact:p")],
            },
        ],
        edges=[
            {
                "subject": "app-private",
                "object": "parent-private",
                "relation": "priority",
                "disclosure": "public_official",  # illegal upgrade
                "source_links": [_link()],
            }
        ],
    )
    with pytest.raises(DisclosureUpgradeError):
        project_patent_graph(case)


def test_missing_endpoint_fails_closed() -> None:
    case = _minimal_case(
        edges=[
            {
                "subject": "app-1",
                "object": "missing-node",
                "relation": "priority",
                "source_links": [_link()],
            }
        ]
    )
    with pytest.raises(MissingEndpointError):
        project_patent_graph(case)


def test_source_derived_edge_requires_source_links() -> None:
    case = _minimal_case(
        edges=[
            {
                "subject": "app-1",
                "object": "parent-1",
                "relation": "priority",
                # no source_links
            }
        ]
    )
    with pytest.raises((MissingSourceLinkError, PatentGraphAdapterError)):
        project_patent_graph(case)


def test_node_without_source_links_fails() -> None:
    case = _minimal_case(
        entities=[
            {
                "id": "app-1",
                "kind": "application",
                "label": "16/1",
                "disclosure": "public_official",
                "source_links": [],
            }
        ],
        edges=[],
    )
    with pytest.raises((MissingSourceLinkError, PatentGraphAdapterError)):
        project_patent_graph(case)


def test_unknown_disclosure_fails_closed() -> None:
    case = _minimal_case(
        entities=[
            {
                "id": "app-1",
                "kind": "application",
                "label": "x",
                "disclosure": "unknown",
                "source_links": [_link()],
            }
        ],
        edges=[],
    )
    with pytest.raises(PatentGraphAdapterError, match="unknown disclosure"):
        project_patent_graph(case)


def test_load_into_graph_engine_endpoints_exist() -> None:
    projection = project_golden_prosecution_case(GOLDEN_PATH)
    engine, report = projection.load_into_engine(GraphEngine())
    assert report["missing_endpoint_relationships"] == 0
    assert report["nodes_imported"] == len(projection.nodes)
    assert report["relationships_imported"] == len(projection.edges)
    # Every edge endpoint is resolvable in the engine.
    for edge in projection.edges:
        assert engine.get_node(edge.subject_id) is not None
        assert engine.get_node(edge.object_id) is not None
        rel = engine.get_relationship(edge.edge_id)
        assert rel is not None
        assert rel.start_node == edge.subject_id
        assert rel.end_node == edge.object_id
        # Source CID preserved on relationship properties for source-derived edges.
        if edge.provenance is EdgeProvenance.SOURCE_DERIVED:
            assert rel.properties.get("source_cid")
            assert rel.properties.get("verified") is True
        else:
            assert rel.properties.get("verified") is False
            assert rel.properties.get("verification_status") == "unverified"


def test_projector_instance_matches_module_helper() -> None:
    case = _minimal_case()
    via_helper = project_patent_graph(case)
    via_class = PatentGraphProjector().project(case)
    assert via_helper.projection_digest == via_class.projection_digest


def test_golden_fixture_json_is_compact_recipe() -> None:
    """Fixture is a compact recipe, not a bulk re-emission of full envelopes."""
    raw = GOLDEN_PATH.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert payload["schema_version"] == "patent.graph.golden.v1"
    case = payload["case"]
    assert "entities" in case and "edges" in case
    # Avoid shipping full projected envelopes per entity (admission policy).
    assert "projection" not in payload or payload.get("projection") is None
    assert len(raw.encode("utf-8")) < 100_000

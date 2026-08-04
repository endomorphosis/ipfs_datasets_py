"""Integration tests for public legal knowledge-graph snapshot builder.

PATLAW-173 acceptance:

* No orphan edges
* Authority edges cite source spans / receipts
* Snapshot is deterministic for pinned corpus / graph schema versions
* Private / mixed inputs fail closed
* Nodes, edges, JSON-LD, and snapshot receipt are suitable for Hub packaging
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.processors.domains.patent.public_legal_corpus_materializer import (
    PrivateOrMixedInputError,
    PublicLegalCorpusMaterializer,
    UnreviewedRightsError,
    build_default_public_legal_recipe,
)
from ipfs_datasets_py.processors.domains.patent.public_legal_graph_builder import (
    AUTHORITY_RELATIONS,
    EDGES_FILENAME,
    GOAL_ID,
    GRAPH_ROOT_FILENAME,
    GRAPH_SCHEMA_VERSION,
    INTERFACE,
    JSONLD_FILENAME,
    NODE_KINDS,
    NODES_FILENAME,
    RECEIPT_FILENAME,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
    TASK_ID,
    BuildMode,
    MissingAuthoritySpanError,
    OrphanEdgeError,
    PrivateGraphInputError,
    PublicLegalGraphBuilder,
    PublicLegalGraphNode,
    PublicLegalGraphSnapshot,
    build_jsonld_document,
    build_public_legal_knowledge_graph,
    builds_are_byte_identical,
    is_authority_edge,
    load_snapshot,
    project_public_legal_graph,
    validate_graph_build,
    verify_authority_edges_cite_spans,
    verify_graph_invariants,
    verify_no_orphan_edges,
)
from ipfs_datasets_py.processors.domains.patent.retrieval_contracts import (
    RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
    AuthorityClaim,
    DisclosureClass,
    EdgeKind,
    EdgeProvenance,
    GraphEdge,
    SourceLink,
    SourceSpan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def recipe() -> dict:
    return build_default_public_legal_recipe()


@pytest.fixture(scope="module")
def materialization(recipe: dict):
    materializer = PublicLegalCorpusMaterializer(require_all_families=True)
    return materializer.materialize_from_recipe(recipe)


@pytest.fixture(scope="module")
def builder() -> PublicLegalGraphBuilder:
    return PublicLegalGraphBuilder()


@pytest.fixture(scope="module")
def baseline(builder: PublicLegalGraphBuilder, materialization):
    return builder.build_from_materialization(materialization)


# ---------------------------------------------------------------------------
# Projection coverage
# ---------------------------------------------------------------------------


def test_default_recipe_projects_all_node_kinds(baseline):
    kinds = {node.kind for node in baseline.nodes}
    # Core kinds always present for the multi-family fixture.
    assert "document" in kinds
    assert "source_root" in kinds
    assert "family" in kinds
    assert "authority" in kinds
    assert "citation" in kinds
    assert kinds <= NODE_KINDS
    assert baseline.snapshot.counts.documents == 8
    assert baseline.snapshot.counts.nodes == len(baseline.nodes)
    assert baseline.snapshot.counts.edges == len(baseline.edges)
    assert baseline.snapshot.counts.nodes >= baseline.snapshot.counts.documents


def test_every_document_has_structural_edges(baseline, materialization):
    doc_ids = {
        f"node:document:{doc.record_id}" for doc in materialization.documents
    }
    relations_by_subject: dict[str, set[str]] = {}
    for edge in baseline.edges:
        rel = edge.metadata.get("relation") or edge.kind.value
        relations_by_subject.setdefault(edge.subject_id, set()).add(rel)
    for doc_node_id in doc_ids:
        rels = relations_by_subject.get(doc_node_id, set())
        assert "in_edition" in rels
        assert "member_of" in rels
        assert "classifies" in rels
        assert "has_citation" in rels


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_repeat_builds_are_content_address_stable(
    builder: PublicLegalGraphBuilder, materialization, baseline
):
    first = builder.build_from_materialization(materialization)
    second = builder.build_from_materialization(materialization)
    third = build_public_legal_knowledge_graph(materialization=materialization)

    assert first.graph_root_cid == second.graph_root_cid == baseline.graph_root_cid
    assert (
        first.graph_digest_sha256
        == second.graph_digest_sha256
        == baseline.graph_digest_sha256
    )
    assert first.to_canonical_bytes() == second.to_canonical_bytes()
    assert builds_are_byte_identical(first, third)

    restored = PublicLegalGraphSnapshot.from_dict(first.snapshot.to_dict())
    assert restored.graph_root_cid == first.graph_root_cid
    assert restored.graph_digest_sha256 == first.graph_digest_sha256


def test_recipe_and_materialization_share_graph_root(
    builder: PublicLegalGraphBuilder, recipe: dict, baseline
):
    from_recipe = builder.build_from_recipe(recipe, require_all_families=True)
    assert from_recipe.graph_root_cid == baseline.graph_root_cid
    assert from_recipe.corpus_root_cid == baseline.corpus_root_cid


def test_document_order_does_not_affect_graph_cid(
    builder: PublicLegalGraphBuilder, recipe: dict, baseline
):
    shuffled = copy.deepcopy(recipe)
    shuffled["documents"] = list(reversed(shuffled["documents"]))
    result = builder.build_from_recipe(shuffled, require_all_families=True)
    assert result.graph_root_cid == baseline.graph_root_cid
    assert [n.node_id for n in result.nodes] == sorted(n.node_id for n in result.nodes)
    assert [e.edge_id for e in result.edges] == sorted(e.edge_id for e in result.edges)


def test_changed_source_text_changes_graph_cid(
    builder: PublicLegalGraphBuilder, recipe: dict, baseline
):
    altered = copy.deepcopy(recipe)
    altered["documents"][0]["text"] = altered["documents"][0]["text"] + " [amended]"
    result = builder.build_from_recipe(altered, require_all_families=True)
    assert result.graph_root_cid != baseline.graph_root_cid
    assert result.graph_digest_sha256 != baseline.graph_digest_sha256
    # Corpus pin also changes, and graph binds corpus pin.
    assert result.corpus_root_cid != baseline.corpus_root_cid


def test_pinned_schema_version_is_stable(baseline):
    assert baseline.snapshot.schema_version == SCHEMA_VERSION
    assert baseline.snapshot.graph_schema_version == GRAPH_SCHEMA_VERSION
    assert baseline.snapshot.interface == INTERFACE
    assert baseline.snapshot.task_id == TASK_ID
    assert baseline.snapshot.goal_id == GOAL_ID
    assert baseline.snapshot.identity["graph_schema_version"] == GRAPH_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Orphan + authority gates
# ---------------------------------------------------------------------------


def test_no_orphan_edges(baseline):
    verify_no_orphan_edges(baseline.nodes, baseline.edges)
    node_ids = {n.node_id for n in baseline.nodes}
    for edge in baseline.edges:
        assert edge.subject_id in node_ids
        assert edge.object_id in node_ids
    assert baseline.snapshot.orphan_check == "pass"


def test_authority_edges_cite_source_spans_and_receipts(baseline):
    verify_authority_edges_cite_spans(baseline.edges)
    authority_edges = [e for e in baseline.edges if is_authority_edge(e)]
    assert authority_edges
    assert baseline.snapshot.counts.authority_edges == len(authority_edges)
    assert baseline.snapshot.authority_span_check == "pass"

    for edge in authority_edges:
        assert edge.provenance is EdgeProvenance.SOURCE_DERIVED
        assert edge.source_links
        assert any(link.span is not None for link in edge.source_links)
        assert any(bool(link.source_receipt_id) for link in edge.source_links)
        relation = edge.metadata.get("relation") or edge.kind.value
        assert relation in AUTHORITY_RELATIONS or edge.kind in {
            EdgeKind.REFERENCES_AUTHORITY,
            EdgeKind.CLASSIFIES,
            EdgeKind.SUPERSEDES,
        }


def test_orphan_edge_detection_fails_closed(baseline):
    nodes = list(baseline.nodes)
    # Drop one node that is referenced by edges.
    if len(nodes) < 2:
        pytest.skip("need multiple nodes")
    victim = nodes[0]
    remaining = [n for n in nodes if n.node_id != victim.node_id]
    # Only fail when an edge still points at the victim.
    dangling = [
        e
        for e in baseline.edges
        if e.subject_id == victim.node_id or e.object_id == victim.node_id
    ]
    if not dangling:
        pytest.skip("selected node has no edges")
    with pytest.raises(OrphanEdgeError):
        verify_no_orphan_edges(remaining, baseline.edges)


def test_authority_edge_missing_span_fails():
    edge = GraphEdge(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        edge_id="edge:classifies:test:authority",
        subject_id="node:document:x",
        object_id="node:authority:statute",
        kind=EdgeKind.CLASSIFIES,
        provenance=EdgeProvenance.SOURCE_DERIVED,
        authority_claim=AuthorityClaim.SOURCE_BOUND,
        source_links=(
            SourceLink(
                source_cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                artifact_id="artifact:x",
                span=None,
                source_receipt_id="receipt:x",
            ),
        ),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
        metadata={"relation": "classifies"},
    )
    with pytest.raises(MissingAuthoritySpanError):
        verify_authority_edges_cite_spans([edge])


def test_authority_edge_missing_receipt_fails():
    edge = GraphEdge(
        schema_version=RETRIEVAL_CONTRACTS_SCHEMA_VERSION,
        edge_id="edge:references_authority:test:cite",
        subject_id="node:document:x",
        object_id="node:citation:y",
        kind=EdgeKind.REFERENCES_AUTHORITY,
        provenance=EdgeProvenance.SOURCE_DERIVED,
        authority_claim=AuthorityClaim.SOURCE_BOUND,
        source_links=(
            SourceLink(
                source_cid="bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
                artifact_id="artifact:x",
                span=SourceSpan(start=0, end=8, unit="char"),
                source_receipt_id=None,
            ),
        ),
        disclosure=DisclosureClass.PUBLIC_OFFICIAL,
        tenant_id="tenant-public",
        metadata={"relation": "references_authority"},
    )
    with pytest.raises(MissingAuthoritySpanError):
        verify_authority_edges_cite_spans([edge])


# ---------------------------------------------------------------------------
# Cross-references / supersedes
# ---------------------------------------------------------------------------


def test_mpep_references_section_101(baseline):
    """MPEP § 2106 fixture text cites 35 U.S.C. § 101 → authority edge."""
    refs = [
        e
        for e in baseline.edges
        if (e.metadata.get("relation") or e.kind.value) == "references_authority"
        and e.subject_id == "node:document:mpep:2106"
    ]
    assert refs
    # At least one mention span is present.
    assert all(e.source_links and e.source_links[0].span is not None for e in refs)
    # Prefer resolution to the USC § 101 document when match succeeds.
    resolved = [
        e
        for e in refs
        if e.object_id == "node:document:usc:35:101"
        or e.metadata.get("resolved_record_id") == "usc:35:101"
        or "101" in (e.metadata.get("mention") or "")
    ]
    assert resolved


def test_ecfr_supersedes_annual_cfr_for_section_1_56(baseline):
    supersedes = [
        e
        for e in baseline.edges
        if (e.metadata.get("relation") or e.kind.value) == "supersedes"
    ]
    # Fixture has ecfr 1.56 (2024) and cfr 1.56 (2023).
    pair = [
        e
        for e in supersedes
        if e.subject_id == "node:document:ecfr:37:1.56"
        and e.object_id == "node:document:cfr:37:1.56-2023"
    ]
    assert pair
    assert pair[0].source_links[0].span is not None
    assert pair[0].source_links[0].source_receipt_id


# ---------------------------------------------------------------------------
# Private fail-closed
# ---------------------------------------------------------------------------


def test_private_classification_fails_closed(
    builder: PublicLegalGraphBuilder, recipe: dict
):
    private = copy.deepcopy(recipe)
    private["documents"][0]["classification"] = "confidential_application"
    with pytest.raises((PrivateOrMixedInputError, PrivateGraphInputError)):
        builder.build_from_recipe(private, require_all_families=True)


def test_unreviewed_rights_fail_closed(
    builder: PublicLegalGraphBuilder, recipe: dict
):
    unreviewed = copy.deepcopy(recipe)
    unreviewed["documents"][0]["rights_review"] = {
        "license_expression": "public-domain-US-government",
        "notes": "",
        "redistribution_allowed": False,
        "review_status": "unreviewed",
        "reviewed_at": "",
        "reviewed_by": "",
    }
    with pytest.raises(UnreviewedRightsError):
        builder.build_from_recipe(unreviewed, require_all_families=True)


# ---------------------------------------------------------------------------
# Staging / JSON-LD / validation
# ---------------------------------------------------------------------------


def test_dry_run_and_stage_share_graph_cid(
    builder: PublicLegalGraphBuilder,
    materialization,
    baseline,
    tmp_path: Path,
):
    staged = builder.build_from_materialization(
        materialization, stage=True, output_dir=tmp_path / "graph"
    )
    assert staged.mode is BuildMode.STAGE
    assert staged.graph_root_cid == baseline.graph_root_cid
    assert staged.graph_digest_sha256 == baseline.graph_digest_sha256
    out = tmp_path / "graph"
    assert (out / NODES_FILENAME).is_file()
    assert (out / EDGES_FILENAME).is_file()
    assert (out / JSONLD_FILENAME).is_file()
    assert (out / SNAPSHOT_FILENAME).is_file()
    assert (out / RECEIPT_FILENAME).is_file()
    assert (out / GRAPH_ROOT_FILENAME).is_file()

    loaded = load_snapshot(out / SNAPSHOT_FILENAME)
    assert loaded.graph_root_cid == baseline.graph_root_cid
    assert loaded.orphan_check == "pass"
    assert loaded.authority_span_check == "pass"

    # JSONL row counts match.
    node_lines = [
        line
        for line in (out / NODES_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    edge_lines = [
        line
        for line in (out / EDGES_FILENAME).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(node_lines) == len(baseline.nodes)
    assert len(edge_lines) == len(baseline.edges)

    jsonld = json.loads((out / JSONLD_FILENAME).read_text(encoding="utf-8"))
    assert jsonld["graph_root_cid"] == baseline.graph_root_cid
    assert jsonld["corpus_root_cid"] == baseline.corpus_root_cid
    assert "@graph" in jsonld
    assert jsonld["graph_schema_version"] == GRAPH_SCHEMA_VERSION


def test_stage_from_corpus_dir(
    builder: PublicLegalGraphBuilder,
    recipe: dict,
    baseline,
    tmp_path: Path,
):
    corpus_dir = tmp_path / "corpus"
    materializer = PublicLegalCorpusMaterializer(require_all_families=True)
    materializer.materialize_from_recipe(recipe, stage=True, output_dir=corpus_dir)

    result = builder.build_from_corpus_dir(
        corpus_dir, stage=True, output_dir=tmp_path / "graph-from-corpus"
    )
    assert result.graph_root_cid == baseline.graph_root_cid
    assert result.corpus_root_cid == baseline.corpus_root_cid


def test_jsonld_hub_shape(baseline):
    jsonld = build_jsonld_document(
        baseline.nodes,
        baseline.edges,
        corpus_root_cid=baseline.corpus_root_cid,
        graph_root_cid=baseline.graph_root_cid,
    )
    assert jsonld["@context"]
    graph = jsonld["@graph"]
    assert len(graph) == len(baseline.nodes) + len(baseline.edges)
    node_rows = [item for item in graph if "node_id" in item]
    edge_rows = [item for item in graph if "edge_id" in item]
    assert len(node_rows) == len(baseline.nodes)
    assert len(edge_rows) == len(baseline.edges)
    for row in node_rows:
        assert row["source_cid"]
        assert row["@id"]
    for row in edge_rows:
        assert row.get("source_cid") or row.get("relation") == "in_edition"


def test_hub_node_rows_have_join_fields(baseline):
    for node in baseline.nodes:
        row = node.to_hub_row()
        assert row["node_id"]
        assert row["jsonld_id"]
        assert row["label"]
        assert row["kind"] in NODE_KINDS
        assert row["source_cid"].startswith("b")


def test_validate_graph_build_receipt(baseline):
    receipt = validate_graph_build(baseline)
    assert receipt["ok"] is True
    assert receipt["stable"] is True
    assert receipt["task_id"] == TASK_ID
    assert receipt["orphan_check"] == "pass"
    assert receipt["authority_span_check"] == "pass"
    assert receipt["node_count"] == len(baseline.nodes)
    assert receipt["edge_count"] == len(baseline.edges)


def test_snapshot_binds_corpus_and_counts(baseline, materialization):
    snap = baseline.snapshot
    assert snap.corpus_root_cid == materialization.corpus_root_cid
    assert snap.corpus_digest_sha256 == materialization.corpus_digest_sha256
    assert snap.partition == "public"
    assert snap.counts.documents == len(materialization.documents)
    assert snap.nodes_cid.startswith("b")
    assert snap.edges_cid.startswith("b")
    assert snap.jsonld_cid.startswith("b")
    assert len(snap.document_joins) == len(materialization.documents)
    for join in snap.document_joins:
        assert join["document_cid"]
        assert join["source_cid"]
        assert join["record_id"]


def test_node_round_trip(baseline):
    original = baseline.nodes[0]
    restored = PublicLegalGraphNode.from_dict(original.to_dict())
    assert restored.node_id == original.node_id
    assert restored.content_digest == original.content_digest
    assert restored.source_cid == original.source_cid


def test_verify_graph_invariants_receipt(baseline):
    gate = verify_graph_invariants(baseline.nodes, baseline.edges)
    assert gate["orphan_check"] == "pass"
    assert gate["authority_span_check"] == "pass"
    assert gate["nodes"] == len(baseline.nodes)
    assert gate["edges"] == len(baseline.edges)


def test_project_public_legal_graph_direct(materialization):
    nodes, edges = project_public_legal_graph(
        materialization.documents,
        materialization.manifest.source_roots,
    )
    assert nodes
    assert edges
    verify_graph_invariants(nodes, edges)


def test_stage_rejects_missing_output_dir(
    builder: PublicLegalGraphBuilder, materialization
):
    with pytest.raises(Exception) as exc_info:
        builder.build_from_materialization(materialization, stage=True, output_dir=None)
    assert "output_dir" in str(exc_info.value).lower()
